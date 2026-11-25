#!/usr/bin/env python3
"""候補の作成と答え合わせの中身（毎日の処理と過去の再現で共用）
2026-10-12：売り側（上の窓を売る）と「決算翌日」の印を追加（買いの条件・選び方は変更なし）"""
from __future__ import annotations

import numpy as np
import pandas as pd

from gap_common import KS, N_PICK, bands, earnings_flag, month_end_universe, next_business_day


def make_candidates(P: dict, asof: pd.Timestamp, names: pd.DataFrame, target: pd.Timestamp | None = None) -> pd.DataFrame:
    """asof の引け後に作る、翌営業日の価格帯（運用対象の全銘柄。候補_k* / 売り候補_k* が True の銘柄だけが売買されうる）"""
    univ = month_end_universe(P, asof + pd.Timedelta(days=1))   # 翌営業日の前の月末（月初でも同じ）
    b = bands(P, asof, univ)
    b.index.name = "コード"
    nm = names.set_index("code")
    b.insert(0, "銘柄名", nm["name"].reindex(b.index))
    b.insert(1, "業種", nm["sector33"].reindex(b.index))
    b.insert(0, "判断日", asof.date())
    tg = target if target is not None else next_business_day(asof)
    b["決算翌日"] = earnings_flag(list(b.index), asof, tg).values
    return b


def _flag(cand: pd.DataFrame) -> pd.Series:
    if "決算翌日" not in cand:
        return pd.Series(False, index=cand.index)
    return cand["決算翌日"].astype(str).str.lower().isin(["true", "1"])


def evaluate(cand: pd.DataFrame, P: dict, day: pd.Timestamp, tp_ioc: float) -> tuple[list, list]:
    """day（翌営業日）の始値・終値で答え合わせ。条件を満たした銘柄からギャップの小さい順に N_PICK 銘柄
    あわせて「決算翌日の銘柄を除いて選んだ場合」の損益も日次に記録する（参考）"""
    O, H, L, C, V = (P[k].loc[day] if day in P[k].index else pd.Series(dtype=float) for k in ("open", "high", "low", "close", "volume"))
    fl = _flag(cand)
    trades, daily = [], []
    for k in KS:
        hi = cand[f"上限_k{k:g}"]; lo = cand["20日線"]
        o = O.reindex(cand.index)
        okk = cand[f"候補_k{k:g}"] & (o < hi) & (o > lo) & (H.reindex(cand.index) > L.reindex(cand.index)) & (V.reindex(cand.index) > 0) & C.reindex(cand.index).notna()
        g = (o / cand["前日安値"] - 1)[okk].sort_values()
        pick = g.index[:N_PICK]
        rets = []
        for rank, c in enumerate(pick, 1):
            r = C[c] / O[c] - 1
            rets.append(r)
            trades.append(dict(日付=day.date(), k=k, 順位=rank, コード=c, 銘柄名=cand.at[c, "銘柄名"], 業種=cand.at[c, "業種"],
                               前日安値=round(cand.at[c, "前日安値"], 2), 上限=round(hi[c], 2), 下限_20日線=round(lo[c], 2),
                               始値=O[c], 終値=C[c], ギャップ_pct=round(g[c] * 100, 2), 損益_pct=round(r * 100, 3), 決算翌日=bool(fl[c])))
        m = float(np.mean(rets)) if rets else 0.0
        g2 = g[~fl.reindex(g.index).fillna(False).astype(bool)]
        p2 = g2.index[:N_PICK]
        m2 = float(np.mean([C[c] / O[c] - 1 for c in p2])) if len(p2) else 0.0
        daily.append(dict(日付=day.date(), k=k, 条件を満たした数=int(okk.sum()), 買った数=len(pick),
                          損益_pct=round(m * 100, 4), TOPIX寄り引け_pct=round(tp_ioc * 100, 4) if np.isfinite(tp_ioc) else np.nan,
                          ヘッジ後_pct=round((m - tp_ioc) * 100, 4) if (rets and np.isfinite(tp_ioc)) else 0.0,
                          うち決算翌日=int(fl.reindex(pick).fillna(False).sum()), 決算除く_買った数=len(p2), 決算除く_損益_pct=round(m2 * 100, 4)))
    return trades, daily


def evaluate_short(cand: pd.DataFrame, P: dict, day: pd.Timestamp, tp_ioc: float) -> tuple[list, list]:
    """売り側：始値が「売り下限」より上・20日線より下の銘柄を、始値÷前日高値 が大きい順に N_PICK 銘柄、寄りで売り引けで買い戻す。
    損益は売りの向き（株価が下がればプラス）。寄りからストップ高に張り付いた銘柄は除く"""
    if not any(c.startswith("売り候補_") for c in cand.columns):
        return [], []
    O, H, L, C, V = (P[k].loc[day] if day in P[k].index else pd.Series(dtype=float) for k in ("open", "high", "low", "close", "volume"))
    fl = _flag(cand)
    o = O.reindex(cand.index); h = H.reindex(cand.index)
    locked = (o >= h) & (o / cand["終値"] - 1 >= 0.13)
    trades, daily = [], []
    for k in KS:
        sc = cand[f"売り候補_k{k:g}"].astype(str).str.lower().isin(["true", "1"])
        lo = cand[f"売り下限_k{k:g}"]; hi = cand["20日線"]
        okk = sc & (o > lo) & (o < hi) & (h > L.reindex(cand.index)) & (V.reindex(cand.index) > 0) & C.reindex(cand.index).notna() & ~locked
        g = (o / cand["前日高値"] - 1)[okk].sort_values(ascending=False)
        res = {}
        for lab, gg in (("", g), ("決算除く_", g[~fl.reindex(g.index).fillna(False).astype(bool)])):
            pick = gg.index[:N_PICK]
            rets = [-(C[c] / O[c] - 1) for c in pick]
            res[lab] = (pick, rets)
            if lab:
                continue
            for rank, (c, r) in enumerate(zip(pick, rets), 1):
                trades.append(dict(日付=day.date(), k=k, 順位=rank, コード=c, 銘柄名=cand.at[c, "銘柄名"], 業種=cand.at[c, "業種"],
                                   前日高値=round(cand.at[c, "前日高値"], 2), 売り下限=round(lo[c], 2), 上限_20日線=round(hi[c], 2),
                                   始値=O[c], 終値=C[c], ギャップ_pct=round(g[c] * 100, 2), 損益_pct=round(r * 100, 3), 決算翌日=bool(fl[c])))
        pick, rets = res[""]; p2, r2 = res["決算除く_"]
        m = float(np.mean(rets)) if rets else 0.0
        m2 = float(np.mean(r2)) if r2 else 0.0
        daily.append(dict(日付=day.date(), k=k, 条件を満たした数=int(okk.sum()), 売った数=len(pick),
                          損益_pct=round(m * 100, 4), TOPIX寄り引け_pct=round(tp_ioc * 100, 4) if np.isfinite(tp_ioc) else np.nan,
                          ヘッジ後_pct=round((m + tp_ioc) * 100, 4) if (rets and np.isfinite(tp_ioc)) else 0.0,
                          うち決算翌日=int(fl.reindex(pick).fillna(False).sum()), 決算除く_売った数=len(p2), 決算除く_損益_pct=round(m2 * 100, 4)))
    return trades, daily
