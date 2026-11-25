#!/usr/bin/env python3
"""試験運用の記録（毎日 run_daily.sh から。通信なし・十数秒）
判断ファイル output/signals/<判断日>.csv ごとに、判断日の翌営業日の終値から次の判断日の翌営業日の終値までの
日次リターンを record_daily.csv に足す。すでにある日付は書き換えない（何度動かしても同じ）。
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from sm_common import DAILY, SIG, TOPIX, daily_returns, load_panel


def main():
    files = sorted(SIG.glob("*.csv"))
    if not files:
        print("判断ファイルがまだありません（最初の判断日は 2026-10-30）"); return 0
    sigs = {pd.Timestamp(f.stem): pd.read_csv(f, dtype={"コード": str}) for f in files}
    codes = sorted(set().union(*[set(s["コード"]) for s in sigs.values()]))
    P = load_panel(codes, last_n=None if len(sigs) > 10 else 330)
    C = P["close"]; days = C.index
    have = set()
    if DAILY.exists():
        have = set(pd.read_csv(DAILY, dtype={"判断日": str})["日付"])
    tp = pd.read_csv(TOPIX, parse_dates=["Date"]).set_index("Date")["Close"]
    tp = tp[~tp.index.duplicated(keep="last")]
    rows = []
    ks = sorted(sigs)
    for i, asof in enumerate(ks):
        nxt = days[days > asof]
        if len(nxt) < 2:
            print(f"{asof.date()}: 記録の開始待ち"); continue
        start = nxt[1]                                       # 判断日の翌営業日の終値 → その次の日 から
        end = None
        if i + 1 < len(ks):
            n2 = days[days > ks[i + 1]]
            end = n2[0] if len(n2) else None
        d = daily_returns(sigs[asof], C, start, end)
        if d.empty:
            continue
        d.insert(0, "判断日", str(asof.date()))
        d["TOPIX_pct"] = ((tp / tp.shift(1) - 1) * 100).reindex(d.index).round(5)
        d.index = [str(x.date()) for x in d.index]
        rows.append(d[~d.index.isin(have)])
    new = pd.concat(rows) if rows else pd.DataFrame()
    if new.empty:
        print("新しく記録する日はありません"); return 0
    new.index.name = "日付"; new = new.reset_index()
    if DAILY.exists():
        new = pd.concat([pd.read_csv(DAILY, dtype={"判断日": str}), new], ignore_index=True)
    new.sort_values("日付").to_csv(DAILY, index=False, encoding="utf-8-sig")
    print(f"記録を追加: {len(new) - len(have)}日（最後 {new['日付'].max()}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
