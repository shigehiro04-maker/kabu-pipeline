#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全銘柄の「新高値」の状況を、手元の株価データ（data/prices/*.csv）から計算する

新高値投資法で使う2種類の高値を出す。どちらも高値はザラ場の高値（high）で判定し、
high が無い日は終値で代える。

  52週新高値   その日の高値が、前日までの250営業日の最高値以上
  上場来高値   その日の高値が、前日までの手元データ全期間の最高値以上
               ※株価データは2016年8月以降しか無いので、それより前に上場した銘柄は
                「約10年来高値」の意味になる

    ./.venv/bin/python compute_new_high.py

出力: fundamentals/new_high.csv
  コード, 新高値からの日数, 新高値回数(20日), 52週高値乖離(%),
  上場来高値からの日数, 上場来高値乖離(%), 出来高倍率(5日/50日), 新高値の基準日,
  5日線乖離(%), 25日線乖離(%), 75日線乖離(%), 200日線乖離(%), 移動平均線の上の本数,
  ボックス幅(%), ボックス上抜け(%), 横ばい上放れ
  横ばい上放れ＝直近5営業日を除く前の60営業日の値幅が20%以内で、最新の終値がその最高値を上回る
  日数は営業日。0なら最新の営業日に更新した。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
PRICES = BASE / "data" / "prices"
OUT = BASE / "fundamentals" / "new_high.csv"

PRICE_MAX = 1_000_000      # compute_beta.py と同じ異常値の基準
MAX_DAILY_MOVE = 0.5       # 1日で±50%超は株式分割などが価格に反映されていない疑い
WINDOW = 250               # 52週＝およそ250営業日
MIN_DAYS_ATH = 60          # 上場来高値は上場直後だと毎日更新になるので、これ未満は判定しない
COUNT_DAYS = 20            # 直近何営業日の新高値回数を数えるか
MA_DAYS = (5, 25, 75, 200) # 移動平均線（終値ベース）
BOX_DAYS = 60              # 横ばい（ボックス）を見る期間。直近BREAK_DAYSを除いたその前の60営業日
BREAK_DAYS = 5             # 直近何営業日をブレイクの期間とみるか
BOX_MAX_WIDTH = 20.0       # ボックスの値幅（最高値÷最安値−1）がこれ以下なら「横ばい」とみなす(%)
STALE_DAYS = 10            # 最新日の株価がこれより古い銘柄（売買停止・上場廃止）は出さない


def one(f: Path, latest: pd.Timestamp) -> dict | None:
    try:
        d = pd.read_csv(f)
    except Exception:
        return None
    if "close" not in d.columns or "date" not in d.columns:
        return None
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    d = d.dropna(subset=["date"]).drop_duplicates("date", keep="last").sort_values("date")
    c = pd.to_numeric(d["close"], errors="coerce")
    h = pd.to_numeric(d["high"], errors="coerce") if "high" in d.columns else c
    h = h.where((h > 0) & (h <= PRICE_MAX), c)
    ok = (c > 0) & (c <= PRICE_MAX)
    d, c, h = d[ok], c[ok].to_numpy(float), h[ok].to_numpy(float)
    n = len(c)
    if n < 30 or (latest - d["date"].iloc[-1]).days > STALE_DAYS:
        return None
    rec = {"コード": f.stem, "新高値の基準日": d["date"].iloc[-1].strftime("%Y-%m-%d")}
    move = np.abs(np.diff(c) / c[:-1])

    # --- 52週新高値 ---
    if n > WINDOW and move[-WINDOW:].max() <= MAX_DAILY_MOVE:
        hs = pd.Series(h)
        prev = hs.shift(1).rolling(WINDOW, min_periods=WINDOW).max()
        nh = (hs >= prev).to_numpy()
        idx = np.flatnonzero(nh)
        # 過去250営業日に一度も無ければ「250日超」とみなして上限の値を入れる
        rec["新高値からの日数"] = int(n - 1 - idx[-1]) if len(idx) and n - 1 - idx[-1] < WINDOW else WINDOW
        rec["新高値回数(20日)"] = int(nh[-COUNT_DAYS:].sum())
        hi52 = float(h[-WINDOW:].max())
        rec["52週高値乖離(%)"] = round((c[-1] / hi52 - 1) * 100, 2)

    # --- 上場来高値（手元データの全期間） ---
    # 分割が反映されていない日があると過去の高値が実態より高く残るので、その銘柄は出さない
    if n >= MIN_DAYS_ATH and move.max() <= MAX_DAILY_MOVE:
        hs = pd.Series(h)
        prev = hs.shift(1).cummax()
        ath = (hs >= prev).to_numpy(copy=True)  # pandas の Copy-on-Write で読み取り専用になるため複製
        ath[:MIN_DAYS_ATH] = False
        idx = np.flatnonzero(ath)
        rec["上場来高値からの日数"] = int(n - 1 - idx[-1]) if len(idx) else int(n - 1 - int(np.argmax(h)))
        rec["上場来高値乖離(%)"] = round((c[-1] / float(h.max()) - 1) * 100, 2)

    # --- 移動平均線との位置 ---
    above = 0
    for m in MA_DAYS:
        if n >= m:
            ma = float(c[-m:].mean())
            gap = (c[-1] / ma - 1) * 100
            rec[f"{m}日線乖離(%)"] = round(gap, 2)
            above += gap > 0
    if n >= max(MA_DAYS):
        rec["移動平均線の上の本数"] = int(above)

    # --- 横ばいからの上放れ ---
    # 直近5営業日を除いた、その前の60営業日を「ボックス」とみる。
    # その値幅（終値の最高÷最安−1）が20%以内なら横ばい、最新の終値がボックスの最高値を
    # 上回っていれば「上放れ」。ブレイクした日が直近5営業日の中にあることになる。
    if n >= BOX_DAYS + BREAK_DAYS and move[-(BOX_DAYS + BREAK_DAYS):].max() <= MAX_DAILY_MOVE:
        box = c[-(BOX_DAYS + BREAK_DAYS):-BREAK_DAYS]
        bhi, blo = float(box.max()), float(box.min())
        width = (bhi / blo - 1) * 100
        rec["ボックス幅(%)"] = round(width, 2)
        rec["ボックス上抜け(%)"] = round((c[-1] / bhi - 1) * 100, 2)
        rec["横ばい上放れ"] = int(width <= BOX_MAX_WIDTH and c[-1] > bhi)

    # --- 出来高の盛り上がり ---
    if "volume" in d.columns and n >= 50:
        v = pd.to_numeric(d["volume"], errors="coerce").to_numpy(float)
        v50 = np.nanmean(v[-50:])
        if v50 > 0:
            rec["出来高倍率(5日/50日)"] = round(float(np.nanmean(v[-5:]) / v50), 2)
    return rec


def main() -> int:
    ap = argparse.ArgumentParser(description="新高値の状況を計算する")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    files = sorted(PRICES.glob("*.csv"))
    if not files:
        print(f"{PRICES} に株価データがありません。", file=sys.stderr)
        return 1
    # 全体の最新日（どの銘柄でも最も新しい日付）を先に拾い、止まっている銘柄を除く基準にする
    latest = max(pd.to_datetime(pd.read_csv(f, usecols=["date"])["date"].iloc[-1])
                 for f in files[:200])
    rows = []
    for i, f in enumerate(files, 1):
        r = one(f, latest)
        if r:
            rows.append(r)
        if i % 1000 == 0:
            print(f"  読み込み {i}/{len(files)}", file=sys.stderr)
    out = pd.DataFrame(rows)
    out.to_csv(args.out, index=False, encoding="utf-8-sig")
    nh = out.get("新高値からの日数", pd.Series(dtype=float))
    at = out.get("上場来高値からの日数", pd.Series(dtype=float))
    print(f"新高値: {len(out):,}銘柄（基準日 {latest:%Y-%m-%d}）／"
          f"最新日に52週新高値 {int((nh == 0).sum()):,}銘柄・5営業日以内 {int((nh <= 4).sum()):,}銘柄／"
          f"最新日に上場来高値 {int((at == 0).sum()):,}銘柄／"
          f"4本の移動平均線より上 {int((out.get('移動平均線の上の本数') == 4).sum()):,}銘柄／"
          f"横ばい上放れ {int((out.get('横ばい上放れ') == 1).sum()):,}銘柄")
    print(f"出力: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
