"""決算短信（J-Quants）の公式BPSで、Yahoo由来のBPSを補正する

Yahoo の BPS（純資産÷株数）は、四季報（東洋経済）のBPSと次の2点でずれる（2026/9/2の四季報一覧との突き合わせで確認）
  1 非支配株主持分・優先株などを含んだ純資産で割っている → 短信のBPS（自己資本ベース）より大きい（約100銘柄）
  2 Yahoo の決算期が古いまま（1〜2年前の決算）→ 新しい本決算のBPSになっていない（約90銘柄）
そこで、短信の最新の本決算（FY）のBPSが Yahoo の決算期と同じか新しければ、そちらを使う。
短信のBPSは開示時点の株数ベースなので、data/splits.csv の分割で今の株数ベースにそろえる。
四半期のBPSは使わない（四季報は本決算のBPSを使っており、四半期にすると一致が減るため）。
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
import jq_files  # J-Quants＋TDnet の決算短信サマリー

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
import splits_util as su  # noqa: E402


def _n(r, k):
    for kk in (k, "NC" + k):
        try:
            v = float(r.get(kk) or "nan")
            if np.isfinite(v):
                return v
        except (TypeError, ValueError):
            pass
    return np.nan


def latest_fy_bps(jq_dir: Path = BASE / "fundamentals" / "jq_summary") -> pd.DataFrame:
    """コードごとに、最新の本決算短信の BPS・期末・開示日・自己資本"""
    best = {}
    for f in jq_files.files(jq_dir):
        try:
            rows = json.loads(f.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if not isinstance(rows, list):
            continue
        for r in rows:
            doc = r.get("DocType", "")
            if not doc.startswith("FY") or "FinancialStatements" not in doc or "REIT" in doc:
                continue
            c = str(r.get("Code", ""))
            c = c[:4] if len(c) == 5 and c.endswith("0") else c
            bps = _n(r, "BPS")
            if not np.isfinite(bps):
                continue
            key = (str(r.get("CurPerEn") or ""), str(r.get("DiscDate") or ""))
            if c not in best or key >= best[c][0]:
                own = _n(r, "EqAR") * _n(r, "TA")
                best[c] = (key, bps, own)
    return pd.DataFrame([dict(コード=c, 短信期末=k[0], 短信開示日=k[1], 短信BPS=b, 短信自己資本=o)
                         for c, (k, b, o) in best.items()])


def apply(d: pd.DataFrame, bps_col: str = "BPS", period_col: str = "決算期",
          shares_col: str = "発行済株式数") -> pd.DataFrame:
    """d の BPS を短信の公式BPSで置き換える。元の値は「BPS(Yahoo)」、出所は「BPSの出所」に残す"""
    j = latest_fy_bps()
    d = d.copy()
    d["BPS(Yahoo)"] = d[bps_col]
    d["BPSの出所"] = np.where(d[bps_col].notna(), "Yahoo（純資産÷株数）", "")
    if j.empty:
        return d
    d = d.merge(j, on="コード", how="left")
    shr = pd.to_numeric(d[shares_col], errors="coerce") if shares_col in d else pd.Series(np.nan, index=d.index)
    adj = []
    for c, b, o, w, sh in zip(d["コード"], d["短信BPS"], d["短信自己資本"], d["短信開示日"], shr):
        if not np.isfinite(b):
            adj.append(np.nan)
            continue
        implied = o / b if (np.isfinite(o) and b) else None
        g, _ = su.choose(c, implied, sh if np.isfinite(sh) else None, su.factor_after(c, w))
        adj.append(b / g)
    d["短信BPS(分割調整)"] = adj
    ours = d[period_col].astype(str).str[:7].where(d[period_col].notna(), "")
    newer = d["短信期末"].fillna("").str[:7] >= ours
    use = newer & d["短信BPS(分割調整)"].notna() & (d["短信BPS(分割調整)"] > -1e12)
    d.loc[use, bps_col] = d.loc[use, "短信BPS(分割調整)"].round(2)
    older = use & (d["短信期末"].fillna("").str[:7] > ours)
    d.loc[use, "BPSの出所"] = np.where(older[use], "決算短信（Yahooより新しい本決算）", "決算短信（自己資本ベース）")
    return d
