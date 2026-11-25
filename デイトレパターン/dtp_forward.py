#!/usr/bin/env python3
"""5. 記録だけの売買（フォワードテスト）。検証した日より後の新しい日だけで、成績が検証どおりかを確かめる（通信なし）。

  python dtp_forward.py --market jp|us          集計（毎日の更新から呼ぶ。先に dtp_features.py を実行）
  python dtp_forward.py --market us --freeze    今の候補（条件・機械学習のモデル）を固定する（最初の1回だけ）

固定するもの（data/daytrade/research/forward/）
  rules.json  : 検証1で「前半で選び、後半でもプラスだった」条件（コスト前・流動性の高い銘柄のコスト後の両方）
  ml_model.txt・ml_meta.json : 検証7の機械学習のモデルと「上位10%」の線
  freeze.json : 固定した日（この日より後の営業日だけを数える）
出力 forward/result.json（固定した後の日ごとの成績）
"""
import argparse
import json
import os
import shutil
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dtp_data as D  # noqa: E402
from dtp_research import conditions, clus, r1, r3  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", required=True, choices=["jp", "us"])
    ap.add_argument("--freeze", action="store_true")
    a = ap.parse_args()
    m = D.cfg(a.market)
    rd = os.path.join(m["out"], "research")
    fd = os.path.join(rd, "forward")
    os.makedirs(fd, exist_ok=True)
    if a.freeze:
        if os.path.exists(os.path.join(fd, "freeze.json")):
            print("すでに固定済み（やり直すときは forward/ を消してから）")
            return 0
        R = json.load(open(os.path.join(rd, "results.json"), encoding="utf-8"))
        rules = []
        for src, cost in (("rules_gross", "gross"), ("rules_liquid", "net_liquid"), ("rules", "net")):
            for x in (R.get(src) or {}).get("top", []):
                if x["net_te"] is not None and x["net_te"] > 0:
                    rules.append({**x, "src": cost})
        json.dump(rules, open(os.path.join(fd, "rules.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        shutil.copyfile(os.path.join(rd, "ml_5m_model.txt"), os.path.join(fd, "ml_model.txt"))
        shutil.copyfile(os.path.join(rd, "ml_5m_meta.json"), os.path.join(fd, "ml_meta.json"))
        json.dump({"day": R["period"][1], "made": R["made"]}, open(os.path.join(fd, "freeze.json"), "w"))
        print(f"固定しました：条件 {len(rules)}件・機械学習モデル（{R['period'][1]} までのデータ）")
        return 0
    if not os.path.exists(os.path.join(fd, "freeze.json")):
        print("まだ固定していません（--freeze）")
        return 0
    fz = json.load(open(os.path.join(fd, "freeze.json")))
    e = pd.read_pickle(os.path.join(rd, "events.pkl"))
    e["net"] = e["pnl"] - e["cost"]
    conds = conditions(e, a.market)     # 分位の線は全期間で決まる（検証時と少しずれることがある）
    new = (e["day"] > fz["day"]).to_numpy()
    days = sorted(e.loc[new, "day"].unique())
    out = {"freeze": fz["day"], "days": days, "n_days": len(days), "rules": [], "ml": None,
           "all": None}
    if len(days):
        f = e[new]
        mu, t, pos = clus(f["net"], f["day"])
        out["all"] = {"n": int(len(f)), "net": r3(mu), "gross": r3(f["pnl"].mean())}
        for x in json.load(open(os.path.join(fd, "rules.json"), encoding="utf-8")):
            msk = new & (e["key"] == x["key"]).to_numpy() if x["key"] != "(全パターン)" else new.copy()
            for cn in ([] if x["cond"] == "（条件なし）" else x["cond"].split(" ＋ ")):
                msk &= conds[cn].to_numpy()
            if x["src"] == "net_liquid":
                msk &= (e["cost"] <= 0.05).to_numpy()
            g = e[msk]
            col = "pnl" if x["src"] == "gross" else "net"
            if len(g):
                mu, t, pos = clus(g[col], g["day"])
                out["rules"].append({"key": x["key"], "cond": x["cond"], "src": x["src"], "bt_net_te": x["net_te"],
                                     "n": int(len(g)), "value": r3(mu), "net": r3(g["net"].mean()), "t": r1(t) if t else None})
        try:
            import lightgbm as lgb
            meta = json.load(open(os.path.join(fd, "ml_meta.json")))
            mdl = lgb.Booster(model_file=os.path.join(fd, "ml_model.txt"))
            X = f[meta["feats"]].copy()
            from dtp_core import PATTERNS
            X["key"] = pd.Categorical(f["key"], categories=list(PATTERNS))
            p = mdl.predict(X)
            top = p >= meta["cut_top10"]
            g = f[top]
            mu, t, pos = clus(g["net"], g["day"]) if len(g) else (None, None, None)
            out["ml"] = {"n": int(top.sum()), "net": r3(mu), "t": r1(t) if t else None, "days_pos": r1(pos)}
        except Exception as ex:
            out["ml"] = {"error": str(ex)}
    json.dump(out, open(os.path.join(fd, "result.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{m['name']} フォワード：固定 {fz['day']} の後 {len(days)}営業日。機械学習上位10%: {out['ml']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
