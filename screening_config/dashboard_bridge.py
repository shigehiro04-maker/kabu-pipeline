#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""スクリーニング定義表（screening_conditions.csv / ranking_definitions.csv）を
東証スクリーニングのページ（make_fundamental_dashboard.py）に渡すための橋渡し。

    from screening_config.dashboard_bridge import augment
    info = augment(payload)      # payload = dashboard_data.json を読んだ dict（その場で書き換える）

やること
  1. 定義表の条件のうち、ページのデータに無い列を足す（テクニカル追加分・チャート形状・
     EDINET DB 由来・理論株価・寄付比など）。値は screening_engine.condition_values で計算する。
  2. 定義表の条件 → ページの列名 の対応表と、ランキング定義を payload["定義表"] に入れる。
  3. 元データの整合性チェック（FLT_DATA_OK）に当たった銘柄は、PER・EPS・ROE・ROA・
     売上系・利益率系の列を NULL にし、「データ不整合」列を True にする（NULL > 不正確値）。

通信はしない。読むのは ~/株分析 の CSV だけ。
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

CONF_DIR = Path(__file__).resolve().parent
if str(CONF_DIR) not in sys.path:
    sys.path.insert(0, str(CONF_DIR))
import screening_engine as se  # noqa: E402

# 既存列の名前がページと違うが、同じ意味の列がページにあるもの
SAME_AS = {
    "FLT_SIZE": "規模",
    "FLT_INVEST": "最低投資金額(万円)",
    "FLT_PRICE_MIN": "株価",
    "FIN_ROE": "ROE(%)",
    "FIN_ROA": "ROA(%)",
    "FIN_EV_EBITDA": "EV/EBITDA",
    "FIN_PCFR": "PCFR",
    "FIN_DE": "負債資本比率",
    "FIN_ICR": "インタレストカバレッジ",
    "FIN_MCAP": "時価総額(億円)",
    "FIN_SALES": "売上高(億円)",
    "FIN_NI": "当期純利益(億円)",
}
# 定義表にはあるがページには出さないもの（重複・別の形で持つもの）
SKIP = {"FIN_PRETAX",      # 税引前利益（円）。FIN_PRETAX_OKU（億円）と同じ値
        "FLT_DATA_OK"}     # 「データ不整合」列として別に持つ
# ページの上の絞り込み欄で既に選べるもの（条件の一覧には出さない）
IN_FILTER_BAR = {"FLT_MARKET", "FLT_SECTOR", "FLT_SIZE", "FLT_INVEST", "FLT_ETF", "FLT_DATA_OK"}
# 円で持っている金額は億円にして出す
YEN_TO_OKU = {"FIN_MCAP_GROSS", "FIN_PRETAX_OKU", "FIN_FCF"}
NEW_NAME = {
    "FIN_MCAP_GROSS": "時価総額・発行済ベース(億円)",
    "FIN_PRETAX_OKU": "税引前利益(億円)",
    "FIN_FCF": "フリーCF(億円)",
    "FIN_KEIJO": "経常利益(億円)",
    "FLT_FIN_EXCLUDE": "金融業以外",
    "FLT_N225": "日経225採用",
    "FLT_TOPIX100": "TOPIX100採用",
    "FLT_JPX400": "JPX日経400採用",
    "FLT_ACCT_STD": "会計基準",
    "VOL_DEV": "出来高乖離率(%)",
    "EDB_NETCASH_RATIO": "ネットキャッシュ比率・清原式(倍)",
    "EDB_RECORD_NI": "史上最高益",
    "EDB_SPLIT_HEURISTIC": "分割調整が推測値",
    "EDB_DIV_STREAK": "連続増配年数(年)",
    "VAL_CONFIDENCE": "理論株価の信頼度",
    "VAL_GAP_ALL": "理論株価乖離率・需給込み(%)",
    "VAL_GAP_FUND": "理論株価乖離率・ファンダのみ(%)",
    "FIN_KEIJO_MARGIN": "売上高経常利益率(%)",
}
# 整合性チェックに当たった銘柄で NULL にするページの列
#  （screening_engine の EPS_DEPENDENT / SALES_DEPENDENT に対応する列と、それから計算される列）
GUARDED = [
    "PER", "PER(時価総額ベース)", "EPS", "益回り(%)", "PEG", "ROE(%)", "平均ROE(%)", "ROA(%)",
    "売上高(億円)", "売上高成長率(%)", "売上高CAGR(%)", "PSR", "営業利益率(%)", "営業利益成長率(%)",
    "純利益率(%)", "直近経常利益率(%)", "EBITDAマージン(%)", "営業CFマージン(%)", "売上高経常利益率(%)",
]
# ランキングの見出し（MarketSpeed の並びに合わせたまとまり）
RANK_GROUP = {**{f"R{i:02d}": "値動き" for i in range(1, 11)},
              **{f"R{i:02d}": "出来高・売買代金" for i in (11, 12, 13, 14, 26, 27, 28)},
              **{f"R{i:02d}": "株価指標" for i in range(15, 20)},
              **{f"R{i:02d}": "信用残" for i in range(20, 26)}}
CAT_ORDER = {
    "チャート形状": ["急上昇", "上昇", "上昇ストップ", "調整", "もみ合い", "リバウンド", "下げとまった", "下落", "急落", "その他"],
    "パラボリック": ["上昇", "下降"],
    "理論株価の信頼度": ["高", "中", "低"],
}


def _clean(v):
    if v is None:
        return None
    if isinstance(v, (bool, np.bool_)):
        return "はい" if v else "いいえ"
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        if not math.isfinite(v):
            return None
        return float(f"{v:.5g}")
    if isinstance(v, str):
        return v if v.strip() and v != "nan" else None
    return v


def _parse_rule(text: str, conds: dict) -> dict | None:
    """'FIN_PER>0' 'VAL_CONFIDENCE=高' 'FLT_FIN_EXCLUDE' をページで評価できる形にする。"""
    m = re.fullmatch(r"([A-Z0-9_]+)\s*(>=|<=|>|<|=)?\s*(.*)", text.strip())
    if not m:
        return None
    cid, op, val = m.group(1), m.group(2), m.group(3)
    c = conds.get(cid)
    if c is None:
        return None
    if op is None:
        lo, hi = se.to_float(c["既定の下限"]), se.to_float(c["既定の上限"])
        if c["単位"] == "真偽":
            return {"c": cid, "op": "=", "v": "はい"}
        if lo is not None or hi is not None:
            return {"c": cid, "op": "range", "lo": lo, "hi": hi}
        return None
    try:
        return {"c": cid, "op": op, "v": float(val)}
    except ValueError:
        return {"c": cid, "op": op, "v": val}


def augment(payload: dict) -> dict:
    conds, ranks = se.load_config()
    df = se.load_universe(conds)
    fields: list = payload["fields"]
    rows: list = payload["stocks"]
    have = set(fields)
    ci = fields.index("コード")
    codes = [se.norm_code(r[ci]) for r in rows]

    def add_field(name: str, series: pd.Series):
        s = series.reindex(codes)
        fields.append(name)
        have.add(name)
        for r, v in zip(rows, s.tolist()):
            r.append(_clean(v))

    cmeta, added = [], []
    for cid, c in conds.items():
        if c["状態"] not in se.USABLE or c["区分"] == "対象外":
            continue
        if cid in SKIP:
            continue
        if cid in se.SHAPES:                 # 個別の形状フラグは「チャート形状（60日）」の区分で選べる
            continue
        col = c["既存列"] if c["既存列"] else ""
        if cid in SAME_AS and SAME_AS[cid] in have:
            key = SAME_AS[cid]
        elif col in have and cid not in NEW_NAME:
            key = col
        else:
            key = NEW_NAME.get(cid) or col or c["条件名"]
            if key in have:
                key = key + "・定義表"
            v = se.condition_values(df, c)
            if cid in YEN_TO_OKU:
                v = v / 1e8
            add_field(key, v)
            added.append(key)
        kind = "cat" if c["単位"] in ("区分", "真偽") else "num"
        order = next((o for k, o in CAT_ORDER.items() if k in key), None)
        if c["単位"] == "真偽":
            order = ["はい", "いいえ"]
        unit = c["単位"] if kind == "num" else ""
        if cid in YEN_TO_OKU or cid in ("FIN_MCAP", "FIN_SALES", "FIN_NI"):
            unit = "億円"
        if cid == "FLT_INVEST":
            unit = "万円"
        if cid == "FIN_DE":
            unit = "倍"
        cmeta.append({"id": cid, "g": c["区分"], "name": c["条件名"], "key": key, "kind": kind,
                      "unit": unit, "dir": c["良い向き"], "state": c["状態"],
                      "bar": cid in IN_FILTER_BAR, "order": order,
                      "note": (c["備考"] or "")[:120]})

    # ---- 整合性チェック
    ok = se._data_ok(df).reindex(codes)
    bad = [(v is False) or (v is np.False_) for v in ok.tolist()]
    nulled = 0
    for name in GUARDED:
        if name not in have:
            continue
        j = fields.index(name)
        for r, b in zip(rows, bad):
            if b and r[j] is not None:
                r[j] = None
                nulled += 1
    fields.append("データ不整合")
    for r, b in zip(rows, bad):
        r.append(bool(b))

    # ---- ランキング
    key_of = {m["id"]: m["key"] for m in cmeta}
    rmeta = []
    for rid, r in ranks.items():
        cid = r["並べる条件ID"]
        usable = r["状態"] in se.USABLE and conds.get(cid, {}).get("状態") in se.USABLE and cid in key_of
        rules = [x for x in (_parse_rule(t, conds) for t in
                 filter(None, (r["既定で除外"] + "|" + r["対象の絞り込み"]).split("|"))) if x]
        for x in rules:
            x["k"] = key_of.get(x["c"])
        rmeta.append({"id": rid, "ms": r["MarketSpeed番号"], "name": r["ランキング名"],
                      "g": RANK_GROUP.get(rid, "独自"), "cid": cid, "key": key_of.get(cid),
                      "asc": r["並び順"] == "asc", "n": int(r["表示件数"] or 100),
                      "rules": [x for x in rules if x["k"]], "ok": usable,
                      "state": r["状態"], "note": r["備考"],
                      "unit": next((m["unit"] for m in cmeta if m["id"] == cid), "")})

    payload["定義表"] = {"conds": cmeta, "ranks": rmeta, "added": added}
    info = {"added": len(added), "conds": len(cmeta), "ranks": sum(1 for x in rmeta if x["ok"]),
            "bad": sum(bad), "nulled": nulled}
    payload["summary"]["データ不整合"] = info["bad"]
    return info


if __name__ == "__main__":
    import json
    src = Path(sys.argv[1] if len(sys.argv) > 1 else se.BASE / "fundamentals/analysis_nofin/dashboard_data.json")
    p = json.loads(src.read_text(encoding="utf-8"))
    print(augment(p))
    print(p["定義表"]["added"])
