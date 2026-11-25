#!/usr/bin/env python3
"""本番と同じ関数で、過去の月末（2017-09〜）を順に判断して記録を再現する（試験運用とは別の output/replay_*）
  python replay_check.py [開始 YYYY-MM] [終了 YYYY-MM]
その月末までの株価だけで判断する（先読みなし）。第6章の検証（21営業日ごと）の月次 LS と比べる。
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from sm_common import OUT, daily_returns, is_month_end, load_panel, load_sectors, make_signal

BASE6 = OUT.parent.parent / "モメンタム_第6章_20261012" / "output" / "D_monthly.csv"


def main():
    s0 = sys.argv[1] if len(sys.argv) > 1 else "2017-09"; s1 = sys.argv[2] if len(sys.argv) > 2 else "2026-09"
    sec = load_sectors(); P = load_panel(sec.index, last_n=None); C = P["close"]; days = C.index
    mes = [d for d in days if s0 <= d.strftime("%Y-%m") <= s1 and is_month_end(days, d)]
    sigs = {d: make_signal(P, sec, d) for d in mes}
    rows, picks = [], []
    for i, d in enumerate(mes):
        nxt = days[days > d]
        if len(nxt) < 2: continue
        end = days[days > mes[i + 1]][0] if i + 1 < len(mes) else None
        x = daily_returns(sigs[d], C, nxt[1], end); x.insert(0, "判断日", str(d.date())); rows.append(x)
        t = sigs[d].drop_duplicates("業種"); picks.append(dict(判断日=str(d.date()), 上位5="・".join(t[t.区分 == "上位"].業種), 下位5="・".join(t[t.区分 == "下位"].業種)))
    R = pd.concat(rows); R.index.name = "日付"
    R.to_csv(OUT / "replay_daily.csv", encoding="utf-8-sig"); pd.DataFrame(picks).to_csv(OUT / "replay_picks.csv", index=False, encoding="utf-8-sig")
    m = R[["LS_pct", "超過_pct", "上位5_pct", "全業種_pct"]].div(100).groupby(R.index.to_period("M")).apply(lambda x: (1 + x).prod() - 1)
    st = lambda x: f"年率 {x.mean() * 1200:+.1f}%  シャープ {x.mean() / x.std() * np.sqrt(12):.2f}  最大DD {((1 + x).cumprod() / (1 + x).cumprod().cummax() - 1).min() * 100:.1f}%"
    print(f"再現 {m.index[0]}〜{m.index[-1]}（{len(m)}か月）")
    print("  LS（上位5−下位5）:", st(m["LS_pct"])); print("  超過（上位5−全業種）:", st(m["超過_pct"]))
    if BASE6.exists():
        b = pd.read_csv(BASE6, index_col=0); b.index = pd.PeriodIndex(b.index, freq="M")
        j = m.join(b["業種モメンタムLS"], how="inner")
        print(f"  第6章（21営業日ごと）との月次相関: {j['LS_pct'].corr(j['業種モメンタムLS']):.3f}（{len(j)}か月）"
              f"  第6章 年率 {j['業種モメンタムLS'].mean() * 1200:+.1f}%")
    m.to_csv(OUT / "replay_monthly.csv", encoding="utf-8-sig")
    return 0


if __name__ == "__main__":
    sys.exit(main())
