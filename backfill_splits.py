#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""過去の株式分割・併合の履歴を台帳 data/splits.csv に取り込み、未調整のまま残っている株価を直す

なぜ必要か:
  fix_splits.py は「直近で起きた分割」を毎日見つけて台帳に載せるが、それより前の分割は台帳に無い。
  台帳は fetch_fundamentals.py（決算の株数・EPS・BPS・一株配当を今の株数ベースにそろえる）と
  forecast_extra.py（会社予想の1株指標）が使うので、過去の分割が抜けていると
    ・決算期末のあと、fix_splits.py を入れる前に分割した銘柄の PER・PBR・配当利回りがずれる
    ・過年度のEPS・配当が分割前のままで、EPS成長率・連続増配・減配回数・株数の増減が壊れる
    ・会社予想（J-Quants Free は12週遅れ）が分割前ベースで、予想配当利回りがずれる
  ということが起きる。

やること（run_daily.sh から月1回、自動で呼ばれる。手動で何度流しても結果は同じ）:
  1. Yahoo（yfinance）から全銘柄の直近 --years 年の分割履歴を100銘柄ずつまとめて取り、
     台帳に無いものを source=yahoo_hist, applied=history で追記する（既存の行は変えない）。
  2. 台帳の分割のうち、権利落ちから --recent 日より前のもの（それより新しいものは fix_splits.py が
     毎日見直している）について、株価CSVの権利落ち日の段差を調べる。段差が分割比とほぼ同じ
     （＝株価が未調整）なら、権利落ち日より前の行を ÷分割比（出来高は×分割比）で作り直す。
     修正前のCSVは data/prices_backup/<日付>/ に保存する。

使い方:
  ./.venv/bin/python backfill_splits.py              # 取り込み＋株価の修正
  ./.venv/bin/python backfill_splits.py --dry-run    # 何が変わるかだけ表示
  ./.venv/bin/python backfill_splits.py --no-fetch   # 通信せず、台帳にある分割で株価の確認・修正だけ
"""
import argparse
import logging
import math
import os
import shutil
import sys
import time
from datetime import datetime, timedelta

import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
PRICES = os.path.join(BASE, "data", "prices")
LEDGER = os.path.join(BASE, "data", "splits.csv")
BACKUP_ROOT = os.path.join(BASE, "data", "prices_backup")
TICKERS = os.path.join(BASE, "tickers", "tse_tickers.csv")
STAMP = os.path.join(BASE, "data", "splits_backfill.stamp")
LOG = os.path.join(BASE, "logs", "splits.log")
PX = ["open", "high", "low", "close"]
BATCH = 100
MATCH = 0.15      # 権利落ち日の段差が 1/分割比 に ±15% 以内なら「未調整」とみなす
MIN_RATIO = 1.4   # 分割比（併合は逆数）がこれ未満の株価は直さない（値動きと区別できない）
MAX_STEP = 0.4    # 直したあと、権利落ち日の前後にこれを超える段差が残るなら書き換えない


def setup_log():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [backfill] %(message)s",
                        handlers=[logging.FileHandler(LOG, encoding="utf-8"), logging.StreamHandler(sys.stdout)])


def load_ledger():
    if not os.path.exists(LEDGER):
        return pd.DataFrame(columns=["code", "ex_date", "ratio", "source", "applied"])
    return pd.read_csv(LEDGER, dtype={"code": str, "ex_date": str, "applied": str, "source": str})


def save_ledger(L):
    L = L.drop_duplicates(["code", "ex_date"], keep="first").sort_values(["ex_date", "code"])
    L.to_csv(LEDGER, index=False)


def fetch_history(codes, years):
    """{code: [(ex_date, ratio), ...]} を Yahoo から取る（100銘柄ずつ）。"""
    import yfinance as yf
    out, failed = {}, 0
    for i in range(0, len(codes), BATCH):
        part = codes[i:i + BATCH]
        syms = [f"{c}.T" for c in part]
        try:
            data = yf.download(syms, period=f"{years}y", interval="1d", actions=True,
                               auto_adjust=True, group_by="ticker", threads=True, progress=False)
        except Exception as e:
            logging.info("  %d〜%d 銘柄目の取得に失敗（%s）", i + 1, i + len(part), e)
            failed += len(part)
            continue
        for c, s in zip(part, syms):
            try:
                sub = data[s] if isinstance(data.columns, pd.MultiIndex) else data
                sp = pd.to_numeric(sub.get("Stock Splits"), errors="coerce").dropna()
            except Exception:
                continue
            sp = sp[(sp > 0) & (sp != 1)]
            if len(sp):
                idx = sp.index.tz_localize(None) if getattr(sp.index, "tz", None) is not None else sp.index
                out[c] = [(ix.strftime("%Y-%m-%d"), float(v)) for ix, v in zip(idx, sp.values)]
        time.sleep(1.5)
        if (i // BATCH) % 10 == 9:
            logging.info("  分割履歴の取得 %d / %d 銘柄", min(i + BATCH, len(codes)), len(codes))
    return out, failed


def read_prices(path):
    d = pd.read_csv(path, dtype={"date": str})
    return d.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)


def step(d, ex):
    """権利落ち日の前後の終値の比（後÷前）。出来高0の行は見ない。"""
    v = d[pd.to_numeric(d["volume"], errors="coerce").fillna(0) > 0]
    pre, post = v[v["date"] < ex].tail(1), v[v["date"] >= ex].head(1)
    if pre.empty or post.empty:
        return None
    a, b = float(pre["close"].iloc[0]), float(post["close"].iloc[0])
    return b / a if a > 0 and b > 0 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=6, help="取り込む分割履歴の年数（既定6。決算4期＋会社予想2年を覆う）")
    ap.add_argument("--recent", type=int, default=30, help="この日数より新しい分割は fix_splits.py に任せる")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-fetch", action="store_true")
    a = ap.parse_args()
    setup_log()
    today = datetime.now().strftime("%Y-%m-%d")
    L = load_ledger()
    have = {(r.code, r.ex_date) for r in L.itertuples()}

    # 1) 分割履歴の取り込み
    if not a.no_fetch:
        codes = pd.read_csv(TICKERS, dtype={"code": str}, encoding="utf-8-sig")["code"].dropna().tolist()
        logging.info("分割履歴の取り込み: %d 銘柄・直近%d年", len(codes), a.years)
        hist, failed = fetch_history(codes, a.years)
        add = []
        for c, rows in hist.items():
            known = pd.to_datetime(L.loc[L["code"] == c, "ex_date"], errors="coerce")
            for ex, r in rows:
                # fix_splits.py が載せた行と数日ずれて重複しないようにする
                if (c, ex) in have or (len(known) and (abs(known - pd.Timestamp(ex)).min() <= pd.Timedelta(days=5))):
                    continue
                add.append(dict(code=c, ex_date=ex, ratio=r, source="yahoo_hist", applied="history"))
        logging.info("分割履歴: %d 銘柄に分割あり／台帳への追加 %d 件（取得失敗 %d 銘柄）",
                     len(hist), len(add), failed)
        if add and not a.dry_run:
            L = pd.concat([L, pd.DataFrame(add)], ignore_index=True)
            save_ledger(L)
            L = load_ledger()

    # 2) 未調整のまま残っている株価の修正
    old = (datetime.now() - timedelta(days=a.recent)).strftime("%Y-%m-%d")
    bdir = os.path.join(BACKUP_ROOT, today)
    fixed, skipped = [], []
    for c, g in L[L["ex_date"] < old].groupby("code"):
        path = os.path.join(PRICES, f"{c}.csv")
        if not os.path.exists(path):
            continue
        d = read_prices(path)
        changed = False
        for _, r in g.sort_values("ex_date", ascending=False).iterrows():
            ex, ratio = r["ex_date"], float(r["ratio"])
            if abs(math.log(ratio)) < math.log(MIN_RATIO):
                continue                      # 1.1分割など小さい比は日々の値動きと見分けられないので触らない
            s = step(d, ex)
            if s is None or abs(s * ratio - 1) > MATCH or abs(math.log(s * ratio)) > abs(math.log(s)) / 3:
                continue                      # 段差が無い＝調整済み（または分割比と合わない）
            new = d.copy()
            for col in PX + ["volume"]:
                new[col] = pd.to_numeric(new[col], errors="coerce")
            pre = new["date"] < ex
            new.loc[pre, PX] = (new.loc[pre, PX] / ratio).round(2)
            new.loc[pre, "volume"] = (new.loc[pre, "volume"] * ratio).round()
            new["volume"] = new["volume"].astype("Int64")
            s2 = step(new, ex)
            if s2 is None or abs(s2 - 1) > MAX_STEP:
                skipped.append(c)
                logging.info("  %s: 権利落ち %s 分割比 %s で直しても段差 %.2f 倍が残るため見送り", c, ex, ratio, s2 or 0)
                continue
            logging.info("  %s: 権利落ち %s 分割比 %s の株価が未調整（段差 %.3f → %.3f）%s",
                         c, ex, ratio, s, s2, "（確認のみ）" if a.dry_run else "を修正")
            d, changed = new, True
            L.loc[(L["code"] == c) & (L["ex_date"] == ex), "applied"] = today
        if changed:
            fixed.append(c)
            if not a.dry_run:
                os.makedirs(bdir, exist_ok=True)
                if not os.path.exists(os.path.join(bdir, f"{c}.csv")):
                    shutil.copy(path, os.path.join(bdir, f"{c}.csv"))
                d.to_csv(path, index=False)
    if not a.dry_run:
        save_ledger(L)
        if not a.no_fetch:
            open(STAMP, "w").write(today + "\n")
    logging.info("過去の分割: 株価を %d 銘柄で修正 / %d 銘柄は見送り（%s）", len(fixed), len(skipped), " ".join(skipped))


if __name__ == "__main__":
    main()
