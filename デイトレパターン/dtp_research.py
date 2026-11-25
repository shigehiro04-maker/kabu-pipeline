#!/usr/bin/env python3
"""検証1〜7をまとめて計算し、結果を JSON に書く（通信なし）。先に dtp_features.py・dtp_daily.py を実行しておく。

  python dtp_research.py --market jp|us

出力（非公開） data/daytrade/research/results.json
統計の考え方
- 同じ日のシグナルは地合いで一緒に動くので、t値は「日ごとの平均」のばらつきで計算する（日をまとめた t 値）。日足は月ごと。
- 条件探し（検証1）は、前半の営業日で条件を選び、後半の営業日で同じ条件が効くかを確かめる。
- 損益はすべて売買コスト（往復2ティック）を引いた値（net）。コストを引く前は gross。
"""
import argparse
import itertools
import json
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dtp_core as C  # noqa: E402
import dtp_data as D  # noqa: E402

TODS = {"jp": ("10:00", "14:00"), "us": ("10:30", "14:30")}


def clus(x, g):
    """x の平均と、g（日・月）ごとにまとめた頑健な t 値（同じ日のシグナルが一緒に動く分を考える）・プラスの日の割合"""
    x = np.asarray(x, float)
    if len(x) == 0:
        return None, None, None
    mu = float(x.mean())
    res = pd.Series(x - mu).groupby(np.asarray(g)).sum()
    G = len(res)
    if G < 5:
        return mu, None, None
    se = np.sqrt((res ** 2).sum() * G / (G - 1)) / len(x)
    pos = float((pd.Series(x).groupby(np.asarray(g)).mean() > 0).mean() * 100)
    return mu, (float(mu / se) if se > 0 else None), pos


def r3(x):
    return None if x is None or not np.isfinite(x) else round(float(x), 3)


def r1(x):
    return None if x is None or not np.isfinite(x) else round(float(x), 1)


def summary(net, gross, g, win_src=None):
    m, t, pd_ = clus(net, g)
    w = np.asarray(win_src if win_src is not None else net)
    return {"n": int(len(net)), "gross": r3(np.mean(gross)), "net": r3(m), "t": r1(t) if t is not None else None,
            "win": r1((w > 0).mean() * 100), "days_pos": r1(pd_)}


def maxdd(net, g):
    """日ごとに平均した損益（1回あたり％）を足していったときの最大の落ち込み"""
    s = pd.Series(np.asarray(net, float)).groupby(np.asarray(g)).mean().sort_index().cumsum()
    return r3((s.cummax() - s).max()) if len(s) else None


# ---------------------------------------------------------------- 条件
def conditions(e, market):
    am, pm = TODS[market]
    q = lambda col, p: e[col].quantile(p)
    a1, a2 = q("atrp", 1 / 3), q("atrp", 2 / 3)
    l1, l2 = q("logtv", 1 / 3), q("logtv", 2 / 3)
    return {
        "地合いが順方向": e["mkt_d"] > 0, "地合いが逆方向": e["mkt_d"] < 0,
        "日足トレンドが順方向": e["trend_d"] > 0, "日足トレンドが逆方向": e["trend_d"] < 0,
        "5日騰落が順方向": e["r5_d"] > 0, "5日騰落が逆方向": e["r5_d"] < 0,
        "相対出来高1.5倍以上": e["rvol"] >= 1.5, "相対出来高0.8倍未満": e["rvol"] < 0.8,
        "足の出来高1.5倍以上": e["volr"] >= 1.5,
        "寄り付き1時間": e["hhmm"] < am, "中盤": (e["hhmm"] >= am) & (e["hhmm"] < pm), "引け前": e["hhmm"] >= pm,
        "窓が順方向1%以上": e["gap_d"] >= 1, "窓が逆方向1%以上": e["gap_d"] <= -1,
        "当日騰落が順方向": e["dayret_d"] > 0, "当日騰落が逆方向": e["dayret_d"] < 0,
        "VWAPより順方向側": e["vwap_d"] > 0, "VWAPより逆方向側": e["vwap_d"] < 0,
        "値動き大（ATR上位1/3）": e["atrp"] >= a2, "値動き小（ATR下位1/3）": e["atrp"] < a1,
        "売買代金 上位1/3": e["logtv"] >= l2, "売買代金 下位1/3": e["logtv"] < l1,
        "損益比2以上": e["rr"] >= 2, "コスト0.05%以下": e["cost"] <= 0.05,
    }


SAME = [("地合い",), ("日足トレンド",), ("5日騰落",), ("相対出来高",), ("寄り付き1時間", "中盤", "引け前"), ("窓が",),
        ("当日騰落",), ("VWAP",), ("値動き",), ("売買代金",)]


def same_var(a, b):
    for grp in SAME:
        if any(a.startswith(x) for x in grp) and any(b.startswith(x) for x in grp):
            return True
    return False


def search_rules(e, market, net_col="net"):
    """前半で選んだ条件（パターン×条件1つ・2つ）が後半でも効くか"""
    days = sorted(e["day"].unique())
    half = days[len(days) // 2]
    conds = conditions(e, market)
    names = list(conds)
    M = {k: v.to_numpy() for k, v in conds.items()}
    dayi = pd.Categorical(e["day"], categories=days).codes
    tr = (e["day"] < half).to_numpy()
    netv = e[net_col].to_numpy()
    keys = e["key"].to_numpy()
    nd = len(days)

    def stat(mask):
        n = mask.sum()
        if n < 30:
            return n, None, None
        s = np.bincount(dayi[mask], weights=netv[mask], minlength=nd)
        c = np.bincount(dayi[mask], minlength=nd)
        ok = c > 0
        dm = s[ok] / c[ok]
        if len(dm) < 5 or dm.std(ddof=1) == 0:
            return n, float(netv[mask].mean()), None
        return n, float(netv[mask].mean()), float(dm.mean() / (dm.std(ddof=1) / np.sqrt(len(dm))))

    rules = []
    combos = [()] + [(a,) for a in names] + [(a, b) for a, b in itertools.combinations(names, 2) if not same_var(a, b)]
    for k in sorted(set(keys)) + ["(全パターン)"]:
        km = np.ones(len(e), bool) if k == "(全パターン)" else keys == k
        for cb in combos:
            m = km.copy()
            for cn in cb:
                m &= M[cn]
            ntr, mtr, ttr = stat(m & tr)
            if ntr < 200 or mtr is None or ttr is None:
                continue
            rules.append((k, cb, ntr, mtr, ttr, m))
    sel = [r for r in rules if r[3] > 0 and r[4] >= 2.0]
    out = []
    for k, cb, ntr, mtr, ttr, m in sorted(sel, key=lambda r: -r[4]):
        nte, mte, tte = stat(m & ~tr)
        out.append({"key": k, "cond": " ＋ ".join(cb) or "（条件なし）", "n_tr": int(ntr), "net_tr": r3(mtr), "t_tr": r1(ttr),
                    "n_te": int(nte), "net_te": r3(mte), "t_te": r1(tte)})
    held = [x for x in out if x["net_te"] is not None and x["net_te"] > 0]
    held2 = [x for x in out if x["t_te"] is not None and x["t_te"] >= 2]
    return {"split": half, "train_days": sum(d < half for d in days), "test_days": sum(d >= half for d in days),
            "tested": len(rules), "selected": len(out), "held_pos": len(held), "held_t2": len(held2),
            "top": out[:40], "survivors": held2[:40]}


# ---------------------------------------------------------------- 本体
def intraday(market, R):
    m = D.cfg(market)
    e = pd.read_pickle(os.path.join(m["out"], "research", "events.pkl"))
    s = pd.read_pickle(os.path.join(m["out"], "research", "strat.pkl"))
    e["net"] = e["pnl"] - e["cost"]
    days = sorted(e["day"].unique())
    R["period"] = [days[0], days[-1], len(days)]
    R["n_events"] = int(len(e))
    R["n_codes"] = int(e["code"].nunique())
    # ---- 4. コスト
    R["cost"] = {"mean": r3(e["cost"].mean()), "median": r3(e["cost"].median()),
                 "p75": r3(e["cost"].quantile(.75)), "gross_abs_mean": r3(e["pnl"].abs().mean()),
                 "buckets": []}
    for lo, hi, nm in ((0, 0.03, "0.03%以下"), (0.03, 0.05, "0.03〜0.05%"), (0.05, 0.1, "0.05〜0.1%"),
                       (0.1, 0.2, "0.1〜0.2%"), (0.2, 99, "0.2%超")):
        g = e[(e["cost"] > lo) & (e["cost"] <= hi)] if lo > 0 else e[e["cost"] <= hi]
        if len(g):
            R["cost"]["buckets"].append({"name": nm, **summary(g["net"], g["pnl"], g["day"]),
                                         "share": r1(len(g) / len(e) * 100)})
    # ---- パターン別（gross・net）と出口の比較（6）
    pats = []
    exits = [("pnl", "目標・損切り"), ("p1R", "目標1R"), ("p2R", "目標2R"), ("pstop", "損切りのみ→大引け"),
             ("r30", "30分後"), ("r60", "1時間後"), ("rc", "大引け")]
    for k in C.PATTERNS:
        g = e[e["key"] == k]
        if not len(g):
            continue
        row = {"key": k, **summary(g["net"], g["pnl"], g["day"])}
        row["exits"] = {}
        for col, nm in exits:
            nv = g[col] - g["cost"]
            wins, losses = nv[nv > 0], nv[nv <= 0]
            row["exits"][nm] = {"net": r3(nv.mean()), "win": r1((nv > 0).mean() * 100),
                                "payoff": r3(wins.mean() / -losses.mean()) if len(wins) and len(losses) and losses.mean() < 0 else None,
                                "dd": maxdd(nv, g["day"])}
        lq = g[g["cost"] <= 0.05]
        row["liquid"] = summary(lq["net"], lq["pnl"], lq["day"]) if len(lq) >= 100 else None
        row["rev_r60"] = r3((-g["r60"] - g["cost"]).mean())
        row["rev_rc"] = r3((-g["rc"] - g["cost"]).mean())
        pats.append(row)
    R["patterns"] = pats
    allg = summary(e["net"], e["pnl"], e["day"])
    R["all"] = allg
    # ---- 1. 条件つき（前半で選び後半で確認）
    t0 = time.time()
    R["rules"] = search_rules(e, market)
    lq = e[e["cost"] <= 0.05].copy()
    R["rules_liquid"] = search_rules(lq, market) if len(lq) > 5000 else None
    R["rules_gross"] = search_rules(e, market, net_col="pnl")     # 参考：コストを引く前
    print(f"  条件探し {time.time() - t0:.0f}秒")
    # ---- 2. 逆張り
    s["net"] = s["pnl"] - s["cost"]
    st = []
    for kind, g in s.groupby("kind"):
        x = {"kind": kind, **summary(g["net"], g["pnl"], g["day"])}
        lqg = g[g["cost"] <= 0.05]
        x["liquid"] = summary(lqg["net"], lqg["pnl"], lqg["day"]) if len(lqg) >= 100 else None
        half = days[len(days) // 2]
        a, b = g[g["day"] < half], g[g["day"] >= half]
        x["train"] = summary(a["net"], a["pnl"], a["day"]) if len(a) > 50 else None
        x["test"] = summary(b["net"], b["pnl"], b["day"]) if len(b) > 50 else None
        sub = []
        if kind == "窓の逆張り":
            for lo in (1, 2, 4):
                h = g[g["gap"] >= lo]
                sub.append({"name": f"窓{lo}%以上", **summary(h["net"], h["pnl"], h["day"])})
            for nm, h in (("窓が上（売り）", g[g["d"] < 0]), ("窓が下（買い）", g[g["d"] > 0])):
                sub.append({"name": nm, **summary(h["net"], h["pnl"], h["day"])})
        if kind == "VWAP回帰":
            for lo in (3, 4, 5):
                h = g[g["dev"] >= lo]
                sub.append({"name": f"ATR×{lo}以上離れた", **summary(h["net"], h["pnl"], h["day"])})
        if kind == "寄り付き30分の勢い":
            for lo in (0.5, 1, 2):
                h = g[g["r0"] >= lo]
                sub.append({"name": f"勢い{lo}%以上", **summary(h["net"], h["pnl"], h["day"])})
        if kind == "ブレイク失敗の逆張り":
            for k2, h in g.groupby("key"):
                if len(h) >= 300:
                    sub.append({"name": "元のパターン " + C.PATTERNS[k2][1], **summary(h["net"], h["pnl"], h["day"])})
        x["sub"] = sub
        st.append(x)
    R["strat"] = st
    return e


def daily(market, R):
    m = D.cfg(market)
    p = os.path.join(m["out"], "research", "daily_events.pkl")
    if not os.path.exists(p):
        return
    e = pd.read_pickle(p)
    base = pd.read_pickle(os.path.join(m["out"], "research", "daily_base.pkl"))
    e["net"] = e["pnl"] - e["cost"]
    e["mon"] = e["dt"].str[:7]
    D_ = {"period": [e["dt"].min(), e["dt"].max()], "n": int(len(e)),
          "base": {"up12": r1(base["up"].sum() / base["n"].sum() * 100), "avg12": r3(base["sum"].sum() / base["n"].sum())},
          "base_year": {y: r3(b["sum"] / b["n"]) for y, b in base.iterrows()}}
    years = sorted(e["year"].unique())
    pats = []
    for k in C.PATTERNS:
        g = e[e["key"] == k]
        if len(g) < 50:
            continue
        row = {"key": k, **summary(g["net"], g["pnl"], g["mon"])}
        row["r12"] = r3((g["r60"] - g["cost"]).mean())
        row["r20"] = r3((g["rc"] - g["cost"]).mean())
        if "mkt_fwd20_d" in g:
            ex = g["rc"] - g["mkt_fwd20_d"] - g["cost"]
            mm, tt, _ = clus(ex.fillna(0), g["mon"])
            row["excess20"] = r3(mm)
            row["excess20_t"] = r1(tt) if tt is not None else None
        row["tgt"] = r1((g["hit"] == "target").mean() * 100)
        row["stp"] = r1((g["hit"] == "stop").mean() * 100)
        a, b = g[g["year"] <= "2021"], g[g["year"] >= "2022"]
        row["train"] = summary(a["net"], a["pnl"], a["mon"]) if len(a) > 50 else None
        row["test"] = summary(b["net"], b["pnl"], b["mon"]) if len(b) > 50 else None
        row["years"] = {y: r3(g[g["year"] == y]["net"].mean()) if (g["year"] == y).sum() >= 20 else None for y in years}
        row["pos_years"] = sum(1 for v in row["years"].values() if v is not None and v > 0)
        up = g[g["trend200_d"] > 0]
        dn = g[g["trend200_d"] < 0]
        row["with_trend"] = summary(up["net"], up["pnl"], up["mon"]) if len(up) > 50 else None
        row["against_trend"] = summary(dn["net"], dn["pnl"], dn["mon"]) if len(dn) > 50 else None
        pats.append(row)
    D_["patterns"] = pats
    D_["years"] = years
    R["daily"] = D_
    return e


def ml(e, market, R, daily_mode=False):
    """7. LightGBM で「コスト後の損益」を予測。時間で 学習60%・調整20%・確認20% に分ける"""
    import lightgbm as lgb
    if daily_mode:
        feats = ["d", "trend200_d", "dev25_d", "volr", "atrp", "logtv", "mkt20_d", "cost"]
        tcol = "dt"
    else:
        feats = ["d", "tod", "trend_d", "r5_d", "rvol", "gap_d", "dayret_d", "vwap_d", "atrp", "volr", "logtv",
                 "rr", "riskp", "cost", "mkt_d"]
        tcol = "day"
    X = e[feats].copy()
    X["key"] = pd.Categorical(e["key"], categories=list(C.PATTERNS))
    y = (e["pnl"] - e["cost"]).clip(-5, 5)
    ts = sorted(e[tcol].unique()) if not daily_mode else sorted(e["dt"].str[:7].unique())
    tv = e[tcol] if not daily_mode else e["dt"].str[:7]
    a, b = ts[int(len(ts) * .6)], ts[int(len(ts) * .8)]
    tr, va, te = (tv < a).to_numpy(), ((tv >= a) & (tv < b)).to_numpy(), (tv >= b).to_numpy()
    params = {"objective": "regression", "learning_rate": 0.03, "num_leaves": 31, "min_data_in_leaf": 500,
              "feature_fraction": 0.8, "bagging_fraction": 0.8, "bagging_freq": 1, "lambda_l2": 10, "verbose": -1}
    dtr = lgb.Dataset(X[tr], y[tr])
    dva = lgb.Dataset(X[va], y[va])
    mdl = lgb.train(params, dtr, 2000, valid_sets=[dva], callbacks=[lgb.early_stopping(100, verbose=False)])
    p = mdl.predict(X[te], num_iteration=mdl.best_iteration)
    yt = (e["pnl"] - e["cost"])[te].to_numpy()
    g = tv[te].to_numpy()
    dec = pd.qcut(p, 10, labels=False, duplicates="drop")
    deciles = [{"d": int(i) + 1, "pred": r3(p[dec == i].mean()), "net": r3(yt[dec == i].mean()), "n": int((dec == i).sum())}
               for i in sorted(set(dec))]
    top = dec == dec.max()
    m_, t_, pos = clus(yt[top], g[top])
    p_above = p > 0
    m2, t2, pos2 = clus(yt[p_above], g[p_above]) if p_above.sum() > 30 else (None, None, None)
    corr = float(pd.Series(p).corr(pd.Series(yt), method="spearman"))
    imp = sorted(zip(mdl.feature_name(), mdl.feature_importance("gain")), key=lambda x: -x[1])
    tot = sum(v for _, v in imp) or 1
    out = {"split": [ts[0], a, b, ts[-1]], "n_test": int(te.sum()), "iters": int(mdl.best_iteration),
           "spearman": r3(corr), "deciles": deciles,
           "top": {"n": int(top.sum()), "net": r3(m_), "t": r1(t_) if t_ is not None else None, "days_pos": r1(pos)},
           "pred_pos": {"n": int(p_above.sum()), "net": r3(m2), "t": r1(t2) if t2 is not None else None, "days_pos": r1(pos2)},
           "all_test": r3(yt.mean()),
           "importance": [{"f": f, "share": r1(v / tot * 100)} for f, v in imp[:10]]}
    R["ml_daily" if daily_mode else "ml"] = out
    if not daily_mode:      # フォワードテスト用に、今日の時点のモデルを保存（上位10%の線も）
        d_ = os.path.join(D.cfg(market)["out"], "research")
        mdl.save_model(os.path.join(d_, "ml_5m_model.txt"), num_iteration=mdl.best_iteration)
        json.dump({"feats": feats, "cut_top10": float(np.quantile(p, 0.9)), "trained_to": ts[-1]},
                  open(os.path.join(d_, "ml_5m_meta.json"), "w"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", required=True, choices=["jp", "us"])
    a = ap.parse_args()
    m = D.cfg(a.market)
    R = {"market": a.market, "made": time.strftime("%Y-%m-%d %H:%M")}
    t0 = time.time()
    e = intraday(a.market, R)
    print(f"  5分足の集計 {time.time() - t0:.0f}秒")
    ml(e, a.market, R)
    print(f"  機械学習（5分足） {time.time() - t0:.0f}秒")
    de = daily(a.market, R)
    if de is not None:
        ml(de, a.market, R, daily_mode=True)
    print(f"  日足 {time.time() - t0:.0f}秒")
    with open(os.path.join(m["out"], "research", "results.json"), "w", encoding="utf-8") as f:
        json.dump(R, f, ensure_ascii=False, indent=1, default=lambda x: None if isinstance(x, float) and not np.isfinite(x) else str(x))
    r = R["rules"]
    print(f"{m['name']}: 条件 {r['tested']:,}通り → 前半で有望 {r['selected']} → 後半もプラス {r['held_pos']}・t≥2 {r['held_t2']}")
    print("  機械学習（5分足）上位10%:", R["ml"]["top"], " 全体:", R["ml"]["all_test"], " 順位相関:", R["ml"]["spearman"])
    if "ml_daily" in R:
        print("  機械学習（日足）上位10%:", R["ml_daily"]["top"], " 全体:", R["ml_daily"]["all_test"], " 順位相関:", R["ml_daily"]["spearman"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
