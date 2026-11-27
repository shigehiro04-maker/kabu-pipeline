#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
株式分割・併合の自動検出と株価CSVの修正（run_daily.sh から fetch_stocks.py の直後に呼ぶ）

なぜ必要か:
  fetch_stocks.py の日次更新は「直近10日分を Yahoo から取り直して上書き」する。
  分割があると Yahoo は過去の株価を分割調整済みの値で返すため、直近10日だけが
  調整済み・それより前は未調整のまま、という不連続な系列になる（2026-09-29 に53銘柄で発生）。
  さらに Yahoo の調整係数は配当調整などが混ざって分割比とずれることがある。

やること:
  1. 検出: 直近40行で終値が1日で 1/1.8 未満 or 1.8 倍超に動いた銘柄を候補にする。
           data/splits.csv（台帳）に載っていて権利落ちから30日以内の銘柄も毎日見直す。
  2. 分割比: Yahoo の分割情報（yfinance の splits）を優先。無ければ、日次スナップショット
           （data/daily/*.csv ＝その日に取得した生の終値）の前日比から推定し、
           よくある比率（2, 3, 5, 10 など）に8%以内で近いときだけ採用する。
  3. 修正: 権利落ち日より前の行を「生の値 ÷ 分割比」（出来高は × 分割比）で作り直す。
           生の値は日次スナップショットがあればそれを、無ければ初回修正前のCSVの値を使う。
           2回目以降（台帳で修正済み）は、スナップショットのある直近の行だけを上書きし直す
           （Yahoo が直近10日を調整済みの値で上書きし直すため）。二重に割ることはない。
  4. 権利落ち日の前後で ±40% を超える段差が残る場合は修正せず、ログに警告を出す。
  5. 修正前のCSVは data/prices_backup/<日付>/ に保存する。

台帳 data/splits.csv（code, ex_date, ratio, source, applied）は splits_util.py を通して
fetch_fundamentals.py（全決算期の株数・BPS・EPS・一株配当）と forecast_extra.py（会社予想の
予想EPS・予想1株配当）が読み、「いまの株数ベース」にそろえる（株価は分割後、株数は分割前、
という食い違いで時価総額や PER・PBR が 1/分割比 になったり、過年度比較が壊れたりするのを防ぐ）。
過去の分割履歴は backfill_splits.py が月1回まとめて台帳に足す。

使い方:
  ./.venv/bin/python fix_splits.py                # 通常（日次）
  ./.venv/bin/python fix_splits.py --dry-run      # 検出と分割比の確認だけ（CSVは書き換えない）
  ./.venv/bin/python fix_splits.py --codes 8766,8377 --from-backup data/prices_backup/2026-09-29
      # 指定銘柄を、バックアップ（未調整の旧CSV）から作り直す
"""
import argparse
import csv
import glob
import logging
import os
import shutil
import sys
from datetime import datetime, timedelta

import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
PRICES = os.path.join(BASE, "data", "prices")
DAILY = os.path.join(BASE, "data", "daily")
LEDGER = os.path.join(BASE, "data", "splits.csv")
BACKUP_ROOT = os.path.join(BASE, "data", "prices_backup")
LOG = os.path.join(BASE, "logs", "splits.log")

JUMP = 1.8            # 1日でこの倍率を超える変化を候補にする
LOOK_ROWS = 40        # 検出に使う直近の行数
RECHECK_DAYS = 30     # 台帳の銘柄を毎日見直す期間（権利落ち日から）
NICE = [1.5, 2, 2.5, 3, 4, 5, 6, 8, 10, 15, 20, 25, 30, 40, 50, 100]
TOL = 0.08            # 推定分割比をよくある比率に丸める許容幅
MAX_STEP = 0.4        # 修正後、権利落ち日の前後でこれを超える段差が残れば書き換えない
PX = ["open", "high", "low", "close"]


def setup_log():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.FileHandler(LOG, encoding="utf-8"), logging.StreamHandler(sys.stdout)])


def read_prices(path):
    d = pd.read_csv(path, dtype={"date": str})
    return d.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)


def load_snapshots():
    """日次スナップショット {date: DataFrame(index=code)}。その日に取得した生の値。"""
    out = {}
    for f in sorted(glob.glob(os.path.join(DAILY, "*.csv"))):
        d = os.path.basename(f)[:-4]
        try:
            s = pd.read_csv(f, dtype={"code": str}, encoding="utf-8-sig").set_index("code")
            out[d] = s
        except Exception:
            continue
    return out


def load_ledger():
    if not os.path.exists(LEDGER):
        return pd.DataFrame(columns=["code", "ex_date", "ratio", "source", "applied"])
    return pd.read_csv(LEDGER, dtype={"code": str, "ex_date": str, "applied": str})


def save_ledger(L):
    L = L.drop_duplicates(["code", "ex_date"], keep="last").sort_values(["ex_date", "code"])
    L.to_csv(LEDGER, index=False)


def detect(codes=None):
    """直近で不連続な銘柄を探す。出来高0の行（上場廃止後のゴミ値など）は無視する。"""
    cand = {}
    files = [os.path.join(PRICES, f"{c}.csv") for c in codes] if codes else glob.glob(os.path.join(PRICES, "*.csv"))
    for f in files:
        c = os.path.basename(f)[:-4]
        try:
            d = read_prices(f).tail(LOOK_ROWS)
        except Exception:
            continue
        d = d[pd.to_numeric(d["volume"], errors="coerce").fillna(0) > 0]
        if len(d) < 3:
            continue
        cl = pd.to_numeric(d["close"], errors="coerce").values
        dates = d["date"].values
        for i in range(1, len(cl)):
            if cl[i - 1] > 0 and cl[i] > 0:
                r = cl[i - 1] / cl[i]
                if r > JUMP or r < 1 / JUMP:
                    cand[c] = (dates[i], r)
    return cand


def yahoo_splits(code, since):
    try:
        import yfinance as yf
        s = yf.Ticker(f"{code}.T").splits
        if s is None or s.empty:
            return []
        s.index = s.index.tz_localize(None) if s.index.tz is not None else s.index
        s = s[s.index >= pd.Timestamp(since)]
        return [(ix.strftime("%Y-%m-%d"), float(v)) for ix, v in s.items() if v and v != 1]
    except Exception as e:
        logging.info("  %s: Yahoo の分割情報を取得できませんでした（%s）", code, e)
        return []


def nice(r):
    for n in NICE:
        for v in (n, 1 / n):
            if abs(r / v - 1) <= TOL:
                return v
    return None


def infer_from_snapshots(code, snaps, around):
    """生の終値（スナップショット）の前日比から、権利落ち日と分割比を推定する。"""
    days = sorted(d for d in snaps if code in snaps[d].index)
    best = None
    for a, b in zip(days, days[1:]):
        if b < (pd.Timestamp(around) - timedelta(days=20)).strftime("%Y-%m-%d"):
            continue
        p0, p1 = float(snaps[a].at[code, "close"]), float(snaps[b].at[code, "close"])
        if p0 > 0 and p1 > 0:
            r = p0 / p1
            if (r > JUMP or r < 1 / JUMP) and (best is None or abs(r - 1) > abs(best[1] - 1)):
                best = (b, r)
    if not best:
        return None
    v = nice(best[1])
    return (best[0], v) if v else None


def rebuild(code, ex_date, ratio, snaps, first_time, base_df=None):
    """権利落ち日より前の行を分割調整した DataFrame を返す。"""
    d = (base_df if base_df is not None else read_prices(os.path.join(PRICES, f"{code}.csv"))).copy()
    for c in PX + ["volume"]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    pre = d["date"] < ex_date
    for i in d.index[pre]:
        dt = d.at[i, "date"]
        s = snaps.get(dt)
        if s is not None and code in s.index and str(s.at[code, "date"]) == dt:
            raw = s.loc[code]
            for c in PX:
                d.at[i, c] = round(float(raw[c]) / ratio, 2)
            d.at[i, "volume"] = int(float(raw["volume"]) * ratio) if pd.notna(raw["volume"]) else d.at[i, "volume"]
        elif first_time:
            for c in PX:
                d.at[i, c] = round(d.at[i, c] / ratio, 2)
            d.at[i, "volume"] = int(d.at[i, "volume"] * ratio) if pd.notna(d.at[i, "volume"]) else d.at[i, "volume"]
    d["volume"] = d["volume"].astype("Int64")
    return d


def step_ok(d, ex_date):
    pre = d[d["date"] < ex_date].tail(1)
    post = d[d["date"] >= ex_date].head(1)
    if pre.empty or post.empty:
        return True, None
    r = float(post["close"].iloc[0]) / float(pre["close"].iloc[0])
    return abs(r - 1) <= MAX_STEP, r


def actual_step(d, around, k, days=20):
    """CSV の around（台帳・Yahoo の権利落ち日）の前後 days 日に、分割比 k（未調整のまま）か 1/k（二重に割った）の
    段差が残っていれば (その日付, 前日終値÷当日終値) を返す。Yahoo の権利落ち日が実際と数日ずれることがあるため
    （2026-11 のキーエンス 6861 は Yahoo が 11-19、実際の値下がりは 11-16）。"""
    import math
    if not k or k <= 0:
        return None
    lo = (pd.Timestamp(around) - timedelta(days=days)).strftime("%Y-%m-%d")
    hi = (pd.Timestamp(around) + timedelta(days=days)).strftime("%Y-%m-%d")
    x = d[(d["date"] >= lo) & (d["date"] <= hi)].copy()
    x = x[pd.to_numeric(x["volume"], errors="coerce").fillna(0) > 0]
    cl = pd.to_numeric(x["close"], errors="coerce").values
    dates = x["date"].values
    best = None
    for i in range(1, len(cl)):
        if cl[i - 1] > 0 and cl[i] > 0:
            r = cl[i - 1] / cl[i]
            if r > JUMP or r < 1 / JUMP:
                for t in (k, 1 / k):
                    if abs(math.log(r / t)) < math.log(1.3) and (best is None or abs(math.log(r)) > abs(math.log(best[1]))):
                        best = (dates[i], r, t)
    return best


def realign(d, step_date, v):
    """step_date より前の行を ÷v（出来高は ×v）して段差を消した DataFrame を返す。"""
    d = d.copy()
    for c in PX + ["volume"]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    pre = d["date"] < step_date
    for c in PX:
        d.loc[pre, c] = (d.loc[pre, c] / v).round(2)
    d.loc[pre, "volume"] = (d.loc[pre, "volume"] * v).round()
    d["volume"] = d["volume"].astype("Int64")
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--codes", default="")
    ap.add_argument("--from-backup", default="", help="未調整の旧CSVがあるフォルダ（--codes と併用）")
    a = ap.parse_args()
    setup_log()
    today = datetime.now().strftime("%Y-%m-%d")
    snaps = load_snapshots()
    L = load_ledger()
    codes = [c.strip() for c in a.codes.split(",") if c.strip()]

    cand = detect(codes or None)
    if codes:
        for c in codes:
            cand.setdefault(c, (today, None))
    # 台帳にあり、権利落ちから日が浅い銘柄は毎日見直す（Yahoo が直近10日を上書きし直すため）
    recent = (datetime.now() - timedelta(days=RECHECK_DAYS)).strftime("%Y-%m-%d")
    for _, r in L[L["ex_date"] >= recent].iterrows():
        cand.setdefault(r["code"], (r["ex_date"], None))
    if not cand:
        logging.info("分割の検出: 該当なし")
        return
    logging.info("分割の候補 %d 銘柄: %s", len(cand), " ".join(sorted(cand)))

    bdir = os.path.join(BACKUP_ROOT, today)
    fixed, warn = [], []
    for code, (jd, jr) in sorted(cand.items()):
        path = os.path.join(PRICES, f"{code}.csv")
        if not os.path.exists(path):
            continue
        known = L[(L["code"] == code) & (L["ex_date"] >= recent)]
        if len(known):
            ex_date, ratio, src = known["ex_date"].iloc[-1], float(known["ratio"].iloc[-1]), known["source"].iloc[-1]
            first = str(known["applied"].iloc[-1]) in ("", "nan", "None")
        else:
            ys = yahoo_splits(code, (pd.Timestamp(jd) - timedelta(days=40)).strftime("%Y-%m-%d"))
            if ys:
                ex_date, ratio = ys[-1]; src = "yahoo"
            else:
                inf = infer_from_snapshots(code, snaps, jd)
                if not inf:
                    logging.info("  %s: %s に %.2f 倍の段差があるが分割比を特定できないため見送り", code, jd, jr or 0)
                    warn.append(code); continue
                ex_date, ratio = inf; src = "inferred"
            first = True
        base = None
        if a.from_backup and os.path.exists(os.path.join(a.from_backup, f"{code}.csv")):
            base = read_prices(os.path.join(a.from_backup, f"{code}.csv"))
            # バックアップより新しい行は現在のCSVから足す
            cur = read_prices(path)
            base = pd.concat([base, cur[~cur["date"].isin(base["date"])]]).sort_values("date").reset_index(drop=True)
            first = True
        new = rebuild(code, ex_date, ratio, snaps, first, base)
        ok, r = step_ok(new, ex_date)
        old_ex = ex_date
        if not ok:
            # 権利落ち日のずれ（Yahoo の日付が実際と違う）や、過去の修正で二重に割った段差が残っている場合は、
            # 実際の段差の日を探し、その日より前を段差の分だけ直す。台帳の権利落ち日も実際の日に直す。
            st = actual_step(read_prices(path), ex_date, ratio)
            if st:
                sd, rr, t = st
                cand_new = realign(read_prices(path), sd, t)
                inf = infer_from_snapshots(code, snaps, sd)
                real_ex = inf[0] if inf and abs((pd.Timestamp(inf[0]) - pd.Timestamp(sd)).days) <= 20 else sd
                ok2, r2 = step_ok(cand_new, sd)
                if ok2:
                    logging.info("  %s: 権利落ち %s では段差 %.2f 倍が残るため、実際の段差 %s（%.2f 倍）で直す（台帳の権利落ち日 %s）",
                                 code, ex_date, r, sd, rr, real_ex)
                    new, ok, r, ex_date = cand_new, True, r2, real_ex
                    first = True
        if not ok:
            logging.info("  %s: 分割比 %s（%s, 権利落ち %s）で直しても段差 %.2f 倍が残るため見送り", code, ratio, src, ex_date, r)
            warn.append(code); continue
        old = read_prices(path)
        changed = not old[PX].round(2).equals(new[PX].round(2)) if len(old) == len(new) else True
        if changed and not a.dry_run:
            os.makedirs(bdir, exist_ok=True)
            if not os.path.exists(os.path.join(bdir, f"{code}.csv")):
                shutil.copy(path, os.path.join(bdir, f"{code}.csv"))
            new.to_csv(path, index=False)
        if not a.dry_run:
            if ex_date != old_ex:
                L = L[~((L["code"] == code) & (L["ex_date"] == old_ex))]
            L = pd.concat([L, pd.DataFrame([dict(code=code, ex_date=ex_date, ratio=ratio, source=src,
                                                 applied=today if first else known["applied"].iloc[-1])])])
        if changed:
            fixed.append(code)
            logging.info("  %s: 分割比 %s（%s）権利落ち %s で修正%s（前後の段差 %s）", code, ratio, src, ex_date,
                         "（確認のみ）" if a.dry_run else "", f"{r:.3f}" if r else "—")
    if not a.dry_run:
        save_ledger(L)
    logging.info("分割の修正: %d 銘柄を修正 / %d 銘柄は見送り（%s）", len(fixed), len(warn), " ".join(warn))


if __name__ == "__main__":
    main()
