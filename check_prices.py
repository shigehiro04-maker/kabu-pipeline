#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
株価CSVの点検と修正（run_daily.sh から fix_splits.py の直後に呼ぶ）

なぜ必要か（2026-10-10 の検証 平均回帰実装_第3章_20261010/ で見つかったもの）:
  Yahoo は、上場廃止前後や再上場の銘柄で、桁違いの値（10億円超）・負の値を返すことがある
  （例: 7183 は 2026-10-05 から約8.6億円、8303 は過去に負の値と540億円）。
  また、分割の調整が権利落ち日より数日前から入り、それより前が未調整のまま残る銘柄がある
  （例: 8227 は分割の1日前、7946 は3日前に −66%・−80% の段差）。fix_splits.py は
  権利落ち日の段差しか見ないので、これを取りこぼす。

やること:
  1. ありえない値の行を削除する
       ・始値〜終値のどれかが0以下・空
       ・終値が1000万円超
       ・終値が、前後約1年の売買のある日の中央値の50倍超／50分の1未満（桁違い・ゴミ値）
       ・売買が続くようになる前の、出来高がほぼ0の部分（上場前・再上場前の埋め値）。
         実際の株価と3倍以上離れているか、60行以上続き出来高のある日が2%未満のとき
     残る正常な行が20行未満になる銘柄（全期間が壊れている）は書き換えず、警告だけ出す。
  2. 分割の日ずれを直す
       台帳 data/splits.csv の権利落ち日（分割比1.5倍以上）の前10日〜後1日に、分割比（±8%）と同じ大きさの1日の段差があり、
       権利落ち日そのものには段差が無い場合、段差の日より前の行を分割比で調整する
       （価格 ÷ 分割比、出来高 × 分割比）。直したあとに段差が40%以内に収まるときだけ書き換える。
  3. 終値が高値〜安値の外にある行は数えて報告するだけ（書き換えない）。
  修正前のCSVは data/prices_backup/<日付>_check/ に保存する。結果は logs/price_check.log と
  data/price_check_latest.csv（今回見つかったもの全部）に出す。

  ./.venv/bin/python check_prices.py            # 通常（日次）
  ./.venv/bin/python check_prices.py --dry-run  # 見つけるだけ（CSVは書き換えない）
"""
import argparse
import glob
import logging
import os
import shutil
import sys
from datetime import datetime

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
PRICES = os.path.join(BASE, "data", "prices")
LEDGER = os.path.join(BASE, "data", "splits.csv")
BACKUP_ROOT = os.path.join(BASE, "data", "prices_backup")
REPORT = os.path.join(BASE, "data", "price_check_latest.csv")
LOG = os.path.join(BASE, "logs", "price_check.log")
PX = ["open", "high", "low", "close"]

ABS_MAX = 1e7          # これを超える終値はありえない（東証の最高値の銘柄でも数十万円台）
REL = 50               # 前後約1年の中央値からこの倍率を超えて離れた値はゴミ値
REF_N = 20             # 中央値に使う直前の正常な行数
MIN_ROWS = 20          # 正常な行がこれ未満なら、全期間が壊れているとみなして触らない
SPLIT_TOL = 0.08
SPLIT_BEFORE, SPLIT_AFTER = 10, 1   # 権利落ち日の前後（暦日）で段差を探す範囲
MAX_STEP = 0.4


def setup_log():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.FileHandler(LOG, encoding="utf-8"), logging.StreamHandler(sys.stdout)])


def read_prices(path):
    d = pd.read_csv(path, dtype={"date": str})
    d = d.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)
    for c in PX + ["volume"]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    return d


def bad_rows(d):
    """削除すべき行の位置（bool 配列）と理由"""
    n = len(d)
    bad = np.zeros(n, bool); why = [""] * n
    px = d[PX].values
    cl = d["close"].values
    vol = d["volume"].fillna(0).values
    for i in range(n):
        if not np.isfinite(px[i]).all() or (px[i] <= 0).any():
            bad[i] = True; why[i] = "0以下・空"
        elif cl[i] > ABS_MAX:
            bad[i] = True; why[i] = "1000万円超"
    # 上場前の埋め値: 売買が続くようになる前（直後20行の半分以上に出来高がある最初の日より前）の部分で、
    # 出来高のある日が1割未満、かつ値がその後の実際の株価と3倍以上離れているもの
    start = next((i for i in range(n - REF_N) if (vol[i:i + REF_N] > 0).mean() >= 0.5), None)
    if start is not None:
        start = next(i for i in range(start, n) if vol[i] > 0)   # 窓の先頭の出来高0の行も埋め値に含める
    if start is not None and start >= REF_N and (vol[:start] > 0).mean() < 0.1:
        seg = cl[:start][~bad[:start]]
        real = np.median(cl[start:start + REF_N])
        if len(seg) and real > 0:
            m = np.median(seg)
            far = m > 0 and max(m / real, real / m) > 3
            long_dead = start >= 60 and (vol[:start] > 0).mean() < 0.02
            if far or long_dead:
                for i in range(start):
                    if not bad[i]:
                        bad[i] = True; why[i] = "上場前の埋め値（出来高がほぼ0）"
    # 桁違い: 前後約1年の売買のある日の終値の中央値から REL 倍超離れた値
    ok = ~bad & (vol > 0)
    if ok.sum() < REF_N:
        ok = ~bad
    if ok.sum() == 0:
        return bad, why
    ref = pd.Series(np.where(ok, cl, np.nan)).rolling(251, center=True, min_periods=REF_N).median()
    ref = ref.ffill().bfill().fillna(np.nanmedian(np.where(ok, cl, np.nan))).values
    for i in range(n):
        if not bad[i] and ref[i] > 0 and (cl[i] > ref[i] * REL or cl[i] < ref[i] / REL):
            bad[i] = True; why[i] = "前後1年の中央値から桁違い"
    return bad, why


def load_ledger():
    if not os.path.exists(LEDGER):
        return pd.DataFrame(columns=["code", "ex_date", "ratio"])
    L = pd.read_csv(LEDGER, dtype={"code": str, "ex_date": str})
    return L[pd.to_numeric(L["ratio"], errors="coerce").fillna(1) != 1]


def split_shift(d, ledger_rows):
    """分割の日ずれ: (段差の日, 分割比, 権利落ち日) のリスト"""
    out = []
    if len(d) < 3:
        return out
    dates = pd.to_datetime(d["date"]); cl = d["close"].values
    for _, r in ledger_rows.iterrows():
        ex, ratio = pd.Timestamp(r["ex_date"]), float(r["ratio"])
        if 1 / 1.5 < ratio < 1.5:                       # 小さい分割比は普通の値動きと区別できない
            continue
        win = (dates >= ex - pd.Timedelta(days=SPLIT_BEFORE)) & (dates <= ex + pd.Timedelta(days=SPLIT_AFTER))
        idx = np.where(win.values)[0]
        jump_day, at_ex = None, False
        for i in idx:
            if i == 0 or cl[i - 1] <= 0:
                continue
            jr = cl[i - 1] / cl[i]                       # 分割比 ratio なら前日÷当日 ≈ ratio
            if abs(jr / ratio - 1) <= SPLIT_TOL:
                if dates[i] >= ex:
                    at_ex = True
                else:
                    jump_day = i
        if jump_day is not None and not at_ex:
            out.append((jump_day, ratio, r["ex_date"]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--codes", default="")
    a = ap.parse_args()
    setup_log()
    today = datetime.now().strftime("%Y-%m-%d")
    bdir = os.path.join(BACKUP_ROOT, f"{today}_check")
    L = load_ledger()
    codes = [c.strip() for c in a.codes.split(",") if c.strip()]
    files = [os.path.join(PRICES, f"{c}.csv") for c in codes] if codes else sorted(glob.glob(os.path.join(PRICES, "*.csv")))
    rep, n_fix, n_del, n_split, broken = [], 0, 0, 0, []
    for f in files:
        code = os.path.basename(f)[:-4]
        try:
            d = read_prices(f)
        except Exception:
            continue
        if d.empty:
            continue
        changed = False
        # 1. ありえない値
        bad, why = bad_rows(d)
        if bad.any():
            for i in np.where(bad)[0]:
                rep.append(dict(コード=code, 日付=d.at[i, "date"], 種類="削除: " + why[i], 終値=d.at[i, "close"]))
            if (~bad).sum() < MIN_ROWS:
                broken.append(code)
                rep.append(dict(コード=code, 日付="", 種類=f"全期間が壊れている（正常{int((~bad).sum())}行）: 書き換えない", 終値=np.nan))
                continue
            d = d[~bad].reset_index(drop=True); changed = True; n_del += int(bad.sum())
        # 2. 分割の日ずれ
        for i, ratio, ex in split_shift(d, L[L["code"] == code]):
            new = d.copy()
            pre = new.index < i
            for c in PX:
                new.loc[pre, c] = (new.loc[pre, c] / ratio).round(2)
            new.loc[pre, "volume"] = (new.loc[pre, "volume"] * ratio).round()
            step = new.at[i, "close"] / new.at[i - 1, "close"] - 1
            if abs(step) <= MAX_STEP:
                rep.append(dict(コード=code, 日付=new.at[i, "date"], 種類=f"分割の日ずれを修正（台帳 {ex} ×{ratio:g}、段差 {step:+.1%}）", 終値=new.at[i, "close"]))
                d = new; changed = True; n_split += 1
            else:
                rep.append(dict(コード=code, 日付=d.at[i, "date"], 種類=f"分割の日ずれの疑い（台帳 {ex} ×{ratio:g}）: 直しても段差 {step:+.1%} のため見送り", 終値=d.at[i, "close"]))
        # 3. 終値が高安の外（報告のみ）
        out = (d["close"] > d["high"] * 1.001) | (d["close"] < d["low"] * 0.999)
        for i in np.where(out.values)[0]:
            rep.append(dict(コード=code, 日付=d.at[i, "date"], 種類="終値が高値〜安値の外（報告のみ）", 終値=d.at[i, "close"]))
        if changed:
            n_fix += 1
            if not a.dry_run:
                os.makedirs(bdir, exist_ok=True)
                if not os.path.exists(os.path.join(bdir, f"{code}.csv")):
                    shutil.copy(f, os.path.join(bdir, f"{code}.csv"))
                d["volume"] = d["volume"].round().astype("Int64")
                d.to_csv(f, index=False)
    R = pd.DataFrame(rep, columns=["コード", "日付", "種類", "終値"])
    if not a.dry_run and not codes:
        R.to_csv(REPORT, index=False, encoding="utf-8-sig")
    logging.info("株価の点検%s: %d 銘柄を修正（ありえない値 %d 行を削除、分割の日ずれ %d 件）／全期間が壊れている %d 銘柄（%s）／高安の外 %d 行",
                 "（確認のみ）" if a.dry_run else "", n_fix, n_del, n_split, len(broken), " ".join(broken),
                 int(R["種類"].str.startswith("終値が高値").sum()) if len(R) else 0)
    for c, g in R[~R["種類"].str.startswith("終値が高値")].groupby("コード"):
        logging.info("  %s: %s", c, " / ".join(f"{k} {v}件" for k, v in g["種類"].value_counts().items()))
    return R


if __name__ == "__main__":
    main()
