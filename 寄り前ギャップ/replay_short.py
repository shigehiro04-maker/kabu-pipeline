#!/usr/bin/env python3
"""売り側（上の窓を売る）と決算翌日の印を、本番のスクリプト（gap_core）で過去の日に1日ずつ流して再現する（先読みなし）
出力 output/replay_short_daily.csv, output/replay_short_trades.csv、買い側の決算除く版 output/replay_buy_earn_daily.csv
  python replay_short.py [開始日] [終了日]
"""
import sys, time
import numpy as np, pandas as pd
from gap_common import OUT, TOPIX, load_panel, load_universe_codes
from gap_core import make_candidates, evaluate, evaluate_short
lo = pd.Timestamp(sys.argv[1] if len(sys.argv) > 1 else '2025-10-01'); hi = pd.Timestamp(sys.argv[2] if len(sys.argv) > 2 else '2026-10-09')
tag = sys.argv[3] if len(sys.argv) > 3 else ''
t0 = time.time()
names = load_universe_codes()
P = load_panel(names['code'], last_n=None)
P = {k: v.loc[lo - pd.Timedelta(days=200):] for k, v in P.items()}
C = P['close']; cnt = C.notna().sum(axis=1); days = cnt.index[cnt >= cnt.max() * 0.5]
tp = pd.read_csv(TOPIX, parse_dates=['Date']).set_index('Date'); tp = tp[~tp.index.duplicated(keep='last')]
TS, DS, DB = [], [], []
run = days[(days >= lo) & (days < hi)]
for asof in run:
    Pi = {k: v.loc[:asof] for k, v in P.items()}
    day = days[days > asof][0]
    cand = make_candidates(Pi, asof, names, target=day)
    t = tp.at[day, 'Close'] / tp.at[day, 'Open'] - 1 if day in tp.index else np.nan
    tr, dl = evaluate_short(cand, P, day, t); TS += tr; DS += dl
    _, db = evaluate(cand, P, day, t); DB += db
pd.DataFrame(TS).to_csv(OUT / f'replay_short_trades{tag}.csv', index=False, encoding='utf-8-sig')
d = pd.DataFrame(DS); d.to_csv(OUT / f'replay_short_daily{tag}.csv', index=False, encoding='utf-8-sig')
b = pd.DataFrame(DB); b.to_csv(OUT / f'replay_buy_earn_daily{tag}.csv', index=False, encoding='utf-8-sig')
for k in (1.0, 0.5):
    x = d[d.k == k]; y = b[b.k == k]
    print(f'売り k={k}: {len(x)}日 売った日 {(x["売った数"]>0).sum()} 日平均 {x["損益_pct"].mean()*100:.1f}bp 年率 {x["損益_pct"].mean()*245:.1f}% '
          f'／決算除く 日平均 {x["決算除く_損益_pct"].mean()*100:.1f}bp')
    print(f'買い k={k}: 日平均 {y["損益_pct"].mean()*100:.1f}bp ／決算除く {y["決算除く_損益_pct"].mean()*100:.1f}bp  決算翌日を含んだ日 {(y["うち決算翌日"]>0).sum()}')
print(f'{time.time()-t0:.0f}秒')
