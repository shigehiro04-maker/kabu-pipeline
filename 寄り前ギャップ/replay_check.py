#!/usr/bin/env python3
"""本番のスクリプト（gap_core）で過去の日を1日ずつ流し、検証（第4章 t1_buy_on_gap.py）と同じ結果になるか確かめる
各日、その日までの株価だけを切り出して候補を作り、翌営業日の始値・終値で答え合わせする（先読みなし）。
出力 output/replay_daily.csv, output/replay_trades.csv（試験運用の記録とは別）
  python replay_check.py [開始日] [終了日]
"""
import sys
import numpy as np, pandas as pd
from gap_common import OUT, TOPIX, load_panel, load_universe_codes
from gap_core import make_candidates, evaluate
lo = pd.Timestamp(sys.argv[1] if len(sys.argv) > 1 else '2025-10-01'); hi = pd.Timestamp(sys.argv[2] if len(sys.argv) > 2 else '2026-10-09')
names = load_universe_codes()
P = load_panel(names['code'], last_n=None)
P = {k: v.loc[lo - pd.Timedelta(days=200):] for k, v in P.items()}
C = P['close']; cnt = C.notna().sum(axis=1); days = cnt.index[cnt >= cnt.max() * 0.5]
tp = pd.read_csv(TOPIX, parse_dates=['Date']).set_index('Date'); tp = tp[~tp.index.duplicated(keep='last')]
T, D = [], []
run = days[(days >= lo) & (days < hi)]
for i, asof in enumerate(run):
    Pi = {k: v.loc[:asof] for k, v in P.items()}
    cand = make_candidates(Pi, asof, names)
    day = days[days > asof][0]
    t = tp.at[day, 'Close'] / tp.at[day, 'Open'] - 1 if day in tp.index else np.nan
    tr, dl = evaluate(cand, P, day, t)
    T += tr; D += dl
pd.DataFrame(T).to_csv(OUT / 'replay_trades.csv', index=False, encoding='utf-8-sig')
d = pd.DataFrame(D); d.to_csv(OUT / 'replay_daily.csv', index=False, encoding='utf-8-sig')
# 検証の日次と比べる
ref = pd.read_pickle(HERE_REF := (OUT.parents[1] / '平均回帰_株とETF_第4章_20261010/output/t1_daily.pkl'))
for k, key in [(1.0, 'k=1.0 フィルターあり N=10'), (0.5, 'k=0.5 フィルターあり N=10')]:
    a = d[d.k == k].set_index(pd.to_datetime(d[d.k == k]['日付']))['損益_pct'] / 100
    b = ref[key].reindex(a.index).fillna(0)
    m = a.index <= ref[key].index[-1]
    a2, b2 = a[m], b[m]
    print(f'k={k}: 日数 {len(a2)}  本番版 年率 {a2.mean()*245*100:.1f}%  検証版 年率 {b2.mean()*245*100:.1f}%  日次相関 {a2.corr(b2):.3f}  '
          f'買った日 本番 {(d[d.k==k]["買った数"]>0).sum()} / 検証 {(ref[key].reindex(a.index).notna()).sum()}')
