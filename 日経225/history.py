#!/usr/bin/env python3
"""構成銘柄と株価換算係数の履歴（data/events.csv）から、過去の任意の日の構成を復元する。"""
from __future__ import annotations

import pandas as pd

from nk_common import load_components, load_events

# 定期見直し（実施日 → 基準日）
PERIODIC = [
    ("2023-04-03", "2023-01-31"), ("2023-10-02", "2023-07-31"),
    ("2024-04-01", "2024-01-31"), ("2024-10-01", "2024-07-31"),
    ("2025-04-01", "2025-01-31"), ("2025-10-01", "2025-07-31"),
    ("2026-04-01", "2026-01-31"), ("2026-10-01", "2026-07-31"),
]


def members_on(day, events: pd.DataFrame | None = None, current: set | None = None) -> set:
    """day の取引終了時点の構成銘柄（day に実施された入れ替えは反映済み）"""
    day = pd.Timestamp(day).strftime("%Y-%m-%d")
    ev = load_events() if events is None else events
    cur = set(load_components()["code"]) if current is None else set(current)
    for e in ev.sort_values("effective", ascending=False).itertuples():
        if e.effective > day:
            if e.type == "add":
                cur.discard(e.code)
            elif e.type == "del":
                cur.add(e.code)
    return cur


def members_before(effective, events=None, current=None) -> set:
    """実施日の前営業日の構成銘柄（＝見直し前）"""
    d = pd.Timestamp(effective) - pd.Timedelta(days=1)
    return members_on(d, events, current)


def periodic_reviews(events: pd.DataFrame | None = None) -> list[dict]:
    """定期見直しごとの実際の採用・除外（臨時の入れ替えを除く）"""
    ev = load_events() if events is None else events
    out = []
    for eff, base in PERIODIC:
        e = ev[(ev["effective"] == eff) & ev["type"].isin(["add", "del"])
               & ev["reason"].fillna("").str.startswith("定期")]
        out.append({"effective": eff, "base": base,
                    "announced": e["announced"].min() if len(e) else "",
                    "adds": e[e["type"] == "add"]["code"].tolist(),
                    "dels": e[e["type"] == "del"]["code"].tolist(),
                    "reasons": dict(zip(e["code"], e["reason"]))})
    return out
