#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
発行済株式数の公式値との突き合わせ（通信なし・数秒）  2026-11-02 作成

公式の最新値（J-Quants 決算短信サマリーの期末発行済株式数、無ければ有報＝EDINET の大株主欄）に、
開示日より後の株式分割・併合（data/splits.csv）を掛けた株数と、自前の発行済株式総数を比べる。
3% 超ずれた銘柄を fundamentals/verify/shares_suspects.txt に書き、verify_shares.py --codes-file で
株探の「いまの株数」を取りに行く（自社株消却・増資・分割の反映漏れの確認）。
短信は分割が開示前なら分割後の株数で書くことがあるので、分割は「開示日より後」のものだけ掛ける。

  ./.venv/bin/python shares_crosscheck.py
"""
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
F = BASE / "fundamentals"


def main():
    jq = {}
    for fp in sorted((F / "jq_summary").glob("*.json")):
        for x in json.loads(fp.read_text(encoding="utf-8")):
            if not x.get("ShOutFY"):
                continue
            c = x["Code"][:4] if x["Code"][4:] == "0" else x["Code"]
            k = (x["CurPerEn"], x["DiscDate"])
            if c not in jq or k >= jq[c][0]:
                jq[c] = (k, float(x["ShOutFY"]))
    sh = json.loads((F / "shareholders.json").read_text(encoding="utf-8"))
    sp = pd.read_csv(BASE / "data/splits.csv", dtype={"code": str})
    sp["d"] = sp["ex_date"].astype(str).str[:10]
    la = pd.read_csv(F / "fundamentals_latest.csv", dtype={"コード": str}, encoding="utf-8-sig")
    ex = F / "shares_external.csv"
    recent = set()
    if ex.exists():
        e = pd.read_csv(ex, dtype={"コード": str}, encoding="utf-8-sig")
        recent = set(e[e["取得日"] >= (date.today() - timedelta(days=30)).isoformat()]["コード"])
    rows, sus = [], []
    for r in la.itertuples():
        c, cand = r.コード, []
        if c in jq:
            cand.append((jq[c][0][0], jq[c][0][1], jq[c][1], "決算短信"))
        x = sh.get(c)
        if x and x.get("issued"):
            cand.append((str(x.get("asof")), str(x.get("filed") or x.get("asof")), float(x["issued"]), "有報"))
        if not cand:
            continue
        asof, disc, iss, src = max(cand)
        f = float(np.prod(sp[(sp["code"] == c) & (sp["d"] > disc)]["ratio"].astype(float))) or 1.0
        ref = iss * f
        ours = r.発行済株式総数
        ratio = ours / ref if pd.notna(ours) and ref else np.nan
        if pd.isna(ratio) or abs(ratio - 1) > 0.03:
            rows.append(dict(コード=c, 銘柄名=r.銘柄名, 自前株数=ours, 公式株数=ref, 比=round(ratio, 3) if pd.notna(ratio) else None,
                             出所=src, 基準日=asof, 開示日=disc, 分割補正=f, 株探で確認済み=c in recent))
            if c not in recent:
                sus.append(c)
    out = F / "verify"
    out.mkdir(exist_ok=True)
    pd.DataFrame(rows).to_csv(out / f"shares_crosscheck_{date.today():%Y%m%d}.csv", index=False, encoding="utf-8-sig")
    (out / "shares_suspects.txt").write_text("\n".join(sus) + ("\n" if sus else ""), encoding="utf-8")
    print(f"公式値と3%超ずれ {len(rows)} 銘柄（うち株探で未確認 {len(sus)}）→ fundamentals/verify/shares_suspects.txt")


if __name__ == "__main__":
    main()
