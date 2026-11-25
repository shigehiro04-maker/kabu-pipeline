#!/usr/bin/env python3
"""日経平均の入れ替えイベントの検証。

1. 再現テスト   過去の定期見直しを、基準日までの株価だけで selection.simulate に予想させ、実際の発表と比べる
2. イベント分析 実際に採用・除外された銘柄の、基準日→発表→実施→実施後 の対TOPIX超過リターン
3. 予想どおりに売買した場合の成績（基準日の翌営業日に予想採用銘柄を買い、実施日の前営業日に売る 等）
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from history import members_before, periodic_reviews
from nk_common import load_excludes
from selection import ABS_ADD, MAX_SWAPS, liquidity_table, simulate

WINDOWS = [  # (名前, 始点, 終点)  始点・終点は「その日の終値」
    ("基準日→発表日", "base", "ann"),
    ("発表翌日（発表日→翌営業日）", "ann", "ann1"),
    ("発表翌日→実施前日", "ann1", "pre"),
    ("基準日→実施前日", "base", "pre"),
    ("実施前日→実施後20日", "pre", "post20"),
]


def _bday_on_or_before(idx: pd.DatetimeIndex, d) -> pd.Timestamp | None:
    d = pd.Timestamp(d)
    i = idx.searchsorted(d, side="right") - 1
    return idx[i] if i >= 0 else None


def _bday_after(idx: pd.DatetimeIndex, d, n: int = 1) -> pd.Timestamp | None:
    d = pd.Timestamp(d)
    i = idx.searchsorted(d, side="right") + n - 1
    return idx[i] if i < len(idx) else None


def replay(panel: pd.DataFrame, industry: dict, prime: set, reviews=None) -> list[dict]:
    """過去の定期見直しを順番に再現する。前回75位以内なのに採用されなかった銘柄は、次回は絶対採用扱いにしない"""
    reviews = reviews or periodic_reviews()
    out, passed = [], set()
    for rv in reviews:
        mem = members_before(rv["effective"])
        liq = liquidity_table(panel, rv["base"], universe=prime | mem)
        excl = set(load_excludes(rv["announced"]))
        sim = simulate(liq, mem, industry, rv["effective"], excluded=excl, passed_over=passed)
        pa = [d.code for d in sim.decisions if d.action == "採用"]
        pdl = [d.code for d in sim.decisions if d.action == "除外"]
        top = sim.ranks[(sim.ranks["liq_rank"] <= ABS_ADD) & ~sim.ranks["member"]]["code"]
        # 枠（3銘柄）が埋まっていなかったのに採用されなかった＝日経の指標では75位以内でなかったとみなす
        if len(rv["adds"]) < MAX_SWAPS:
            passed = passed | set(top)
        passed = passed - set(rv["adds"]) - excl
        out.append({**rv, "pred_adds": pa, "pred_dels": pdl, "sim": sim,
                    "hit_adds": sorted(set(pa) & set(rv["adds"])),
                    "hit_dels": sorted(set(pdl) & set(rv["dels"])),
                    "passed_over": sorted(passed)})
    return out


def replay_frame(rep: list[dict], names: dict) -> pd.DataFrame:
    rows = []
    for r in rep:
        f = lambda L: "、".join(f"{c} {names.get(c, '')}" for c in L) or "－"
        rows.append({
            "実施日": r["effective"], "基準日": r["base"], "発表日": r["announced"],
            "実際の採用": f(r["adds"]), "予想の採用": f(r["pred_adds"]),
            "採用の的中": f"{len(r['hit_adds'])}/{len(r['adds'])}",
            "実際の除外": f(r["dels"]), "予想の除外": f(r["pred_dels"]),
            "除外の的中": f"{len(r['hit_dels'])}/{len(r['dels'])}",
        })
    return pd.DataFrame(rows)


def _ret(px: pd.Series, a, b) -> float:
    if a is None or b is None:
        return np.nan
    pa, pb = px.get(a, np.nan), px.get(b, np.nan)
    if not (pa > 0 and pb > 0):
        return np.nan
    return pb / pa - 1.0


def event_study(closes: pd.DataFrame, topix: pd.Series, events: pd.DataFrame, bases: dict) -> pd.DataFrame:
    """closes: 日付×コードの終値（分割調整済み）、events: events.csv の add/del（定期見直し）
    bases: 実施日→基準日"""
    idx = closes.index
    rows = []
    for e in events.itertuples():
        if e.code not in closes.columns or e.effective not in bases:
            continue
        px = closes[e.code].dropna()
        if px.empty:
            continue
        pts = {
            "base": _bday_on_or_before(idx, bases[e.effective]),
            "ann": _bday_on_or_before(idx, e.announced),
            "ann1": _bday_after(idx, e.announced, 1),
            "pre": _bday_on_or_before(idx, pd.Timestamp(e.effective) - pd.Timedelta(days=1)),
        }
        pts["post20"] = _bday_after(idx, pts["pre"], 20) if pts["pre"] is not None else None
        row = {"実施日": e.effective, "発表日": e.announced, "区分": "採用" if e.type == "add" else "除外",
               "コード": e.code, "銘柄名": e.name, "理由": e.reason}
        for name, a, b in WINDOWS:
            r = _ret(px, pts[a], pts[b])
            t = _ret(topix, pts[a], pts[b])
            row[name] = (r - t) * 100 if not (np.isnan(r) or np.isnan(t)) else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def summarize_events(es: pd.DataFrame) -> pd.DataFrame:
    cols = [w[0] for w in WINDOWS]
    if es.empty:
        return pd.DataFrame()
    g = es.groupby("区分")[cols]
    s = pd.concat({"平均(%)": g.mean(), "中央値(%)": g.median(),
                   "プラスの割合(%)": g.agg(lambda x: (x > 0).mean() * 100 if x.notna().any() else np.nan),
                   "件数": g.count()}, axis=0)
    return s.round(2)


def strategy(rep: list[dict], closes: pd.DataFrame, topix: pd.Series) -> pd.DataFrame:
    """予想に従って売買した場合（等金額）。基準日の翌営業日の終値で入り、
       ・発表前日に手じまう（発表を待たない）
       ・実施前日に手じまう（予想が当たった銘柄は指数買いの日まで持つ、外れたら発表翌日に手じまう）"""
    idx = closes.index
    rows = []
    for r in rep:
        entry = _bday_after(idx, r["base"], 1)
        ann = _bday_on_or_before(idx, r["announced"])
        ann1 = _bday_after(idx, r["announced"], 1)
        pre = _bday_on_or_before(idx, pd.Timestamp(r["effective"]) - pd.Timedelta(days=1))
        for side, preds, actual in (("買い（予想採用）", r["pred_adds"], r["adds"]),
                                    ("売り（予想除外）", r["pred_dels"], r["dels"])):
            sign = 1 if side.startswith("買い") else -1
            for c in preds:
                if c not in closes.columns:
                    continue
                px = closes[c].dropna()
                hit = c in actual
                r1 = _ret(px, entry, ann) - _ret(topix, entry, ann)
                exit2 = pre if hit else ann1
                r2 = _ret(px, entry, exit2) - _ret(topix, entry, exit2)
                rows.append({"実施日": r["effective"], "売買": side, "コード": c, "的中": "○" if hit else "×",
                             "発表前日まで(%)": sign * r1 * 100, "実施前日まで(%)": sign * r2 * 100})
    return pd.DataFrame(rows)
