#!/usr/bin/env python3
"""引け後に、翌営業日の「寄り前に確認する買い候補」を作る（毎日 run_daily.sh から、通信なし・数十秒）

出力 output/candidates/<判断日>.csv（運用対象の全銘柄の価格帯。候補_k1 / 候補_k0.5 が True の銘柄が買い候補、
  売り候補_k1 / 売り候補_k0.5 が売り候補（紙の記録のみ）、決算翌日 は対象日の寄りまでに決算発表がある銘柄）
使い方（翌朝 8:50〜8:59）: 候補の寄り前の気配が「下限（20日線）より上、上限より下」なら成行で買い、引けで売る。
  条件に入った銘柄が10を超えたら、気配 ÷ 前日安値 が小さい順に10銘柄。
  python gap_candidates.py [--asof YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import sys

import pandas as pd

from gap_common import CAND, earnings_coverage, load_panel, load_universe_codes, next_business_day
from gap_core import make_candidates


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asof", help="判断日（既定: 株価CSVの最新日）")
    a = ap.parse_args()
    names = load_universe_codes()
    P = load_panel(names["code"], last_n=170)
    C = P["close"]
    cnt = C.notna().sum(axis=1)
    days = cnt.index[cnt >= cnt.max() * 0.5]                # 半分以上の銘柄に値がある日 = 取引日
    asof = pd.Timestamp(a.asof) if a.asof else days[-1]
    if a.asof:
        P = {k: v.loc[:asof] for k, v in P.items()}
    cand = make_candidates(P, asof, names)
    CAND.mkdir(parents=True, exist_ok=True)
    f = CAND / f"{asof.date()}.csv"
    cand.to_csv(f, encoding="utf-8-sig", float_format="%.4f")
    nb = next_business_day(asof)
    print(f"判断日 {asof.date()} → 対象日 {nb.date()}  運用対象 {len(cand)}銘柄  "
          f"候補 k=1: {int(cand['候補_k1'].sum())}  k=0.5: {int(cand['候補_k0.5'].sum())}  "
          f"売り候補 k=1: {int(cand['売り候補_k1'].sum())}  k=0.5: {int(cand['売り候補_k0.5'].sum())}  "
          f"決算翌日 {int(cand['決算翌日'].sum())}（予定表の最終日 {earnings_coverage(nb)}）  → {f.name}")


if __name__ == "__main__":
    sys.exit(main())
