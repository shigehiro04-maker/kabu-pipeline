#!/usr/bin/env python3
"""試験運用の答え合わせ：売り側（上の窓を売る、2026-10-13 から。毎日 run_daily.sh から、通信なし・数十秒）

候補ファイル output/candidates/<判断日>.csv のうち、翌営業日の株価がそろったものを、
実際の始値・終値で「条件を満たした銘柄を寄付きで売り、大引けで買い戻した」として記録する（損益は売りの向き）。
お金は動かさない（紙の上の売買）。コストは引いていない（損益分岐は検証で片道約18bp）。
  record_short_trades.csv : 1取引1行（k=1 と k=0.5 の両方）
  record_short_daily.csv  : 1日1行（同上）。ヘッジ後 = 損益 ＋ TOPIX（1306換算）の寄付き→大引け
すでに記録した日は飛ばす（何度動かしても同じ結果）。
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from gap_common import CAND, DAILY_S as DAILY, REC_S as REC, TOPIX, load_panel
from gap_core import evaluate_short as evaluate


def main():
    files = sorted(CAND.glob("*.csv"))
    if not files:
        print("候補ファイルがまだありません"); return 0
    done = set()
    if DAILY.exists():
        dd = pd.read_csv(DAILY, dtype={"判断日": str})
        done = set(dd["判断日"])
    todo = [f for f in files if f.stem not in done]
    if not todo:
        print("新しく答え合わせする日はありません"); return 0
    cands = {f.stem: pd.read_csv(f, dtype={"コード": str}).set_index("コード") for f in todo}
    codes = sorted(set().union(*[c.index for c in cands.values()]))
    P = load_panel(codes, last_n=60)
    C = P["close"]; cnt = C.notna().sum(axis=1)
    days = cnt.index[cnt >= cnt.max() * 0.5]
    tp = pd.read_csv(TOPIX, parse_dates=["Date"]).set_index("Date")
    tp = tp[~tp.index.duplicated(keep="last")]
    T, D = [], []
    for stem, cand in cands.items():
        asof = pd.Timestamp(stem)
        nxt = days[days > asof]
        if len(nxt) == 0:
            print(f"{stem}: 翌営業日の株価待ち"); continue
        day = nxt[0]
        for k in [c for c in cand.columns if c.startswith("候補_")]:
            cand[k] = cand[k].astype(str).str.lower().isin(["true", "1"])
        t_ioc = tp.at[day, "Close"] / tp.at[day, "Open"] - 1 if day in tp.index else np.nan
        if not any(c.startswith("売り候補_") for c in cand.columns):
            print(f"{stem}: 売り側の列が無い候補ファイル（追加前に作成）なので飛ばす"); continue
        tr, dl = evaluate(cand, P, day, t_ioc)
        for x in tr + dl:
            x["判断日"] = stem
        T += tr; D += dl
        print(f"{stem} → {day.date()}: " + " / ".join(f"売り k={x['k']:g} {x['売った数']}銘柄 {x['損益_pct']:+.2f}%" for x in dl))
    if D:
        for path, rows in [(REC, T), (DAILY, D)]:
            new = pd.DataFrame(rows)
            if path.exists() and len(new):
                new = pd.concat([pd.read_csv(path, dtype={"コード": str, "判断日": str}), new], ignore_index=True)
            if len(new):
                cols = ["判断日"] + [c for c in new.columns if c != "判断日"]
                new[cols].sort_values(["日付", "k"] + (["順位"] if "順位" in new else [])).to_csv(path, index=False, encoding="utf-8-sig")
    return 0


if __name__ == "__main__":
    sys.exit(main())
