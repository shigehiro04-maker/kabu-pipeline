#!/usr/bin/env python3
"""月末の判断（毎日 run_daily.sh から。月末の営業日だけ output/signals/<判断日>.csv を作る。通信なし・十数秒）
  python sm_signal.py                 いちばん新しい株価の日が月末なら作る
  python sm_signal.py --asof 2026-10-30   指定日で作る（月末でなくても作る。試し用）
"""
from __future__ import annotations

import argparse
import sys

import pandas as pd

from sm_common import SIG, START, is_month_end, load_panel, load_sectors, make_signal


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--asof"); a = ap.parse_args()
    sec = load_sectors()
    P = load_panel(sec.index)
    days = P["close"].index
    if a.asof:
        todo = [pd.Timestamp(a.asof)]
    else:
        # 月末の営業日のうち、まだ判断ファイルが無いものを作る（処理が止まった日があっても、その月末の株価までで後から作れる）
        todo = [d for d in days if d >= START and is_month_end(days, d) and not (SIG / f"{d.date()}.csv").exists()]
        if not todo:
            last = days[-1]
            why = f"最初の判断日（{START.date()}）より前なので" if last < START else "月末ではない（または作成済み）ため"
            print(f"{last.date()}: {why}判断なし"); return 0
    SIG.mkdir(parents=True, exist_ok=True)
    for asof in todo:
        s = make_signal(P, sec, asof)          # asof の終値までしか使わない
        s.to_csv(SIG / f"{asof.date()}.csv", index=False, encoding="utf-8-sig")
        top = s.drop_duplicates("業種").sort_values("業種の順位")
        print(f"{asof.date()} 判断: 上位 " + "、".join(f"{r.業種}({r['業種の点数_pct']:+.1f}%)" for _, r in top.head(5).iterrows()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
