#!/usr/bin/env python3
"""検証用のデータ作り（5分足・保管庫の全期間）。通信なし。

  python dtp_features.py --market jp|us

出力（非公開） data/daytrade/research/
  events.pkl  : パターンのシグナル1回ごとに、条件（地合い・日足トレンド・相対出来高・時間帯・窓・VWAP など）と、
                出口ルールごとの損益（目標/損切り・1R・2R・損切りのみ・30分・1時間・大引け）、売買コストを持つ表
  strat.pkl   : 逆張りなどパターン以外の仕組み（窓の逆張り・VWAP回帰・ブレイク失敗の逆張り・寄り付き30分の勢い）
  market.pkl  : 市場全体（全銘柄平均）の、寄り付きからの騰落（足ごと）
損益はすべて「方向をそろえた％」（買いは上がると＋、売りは下がると＋）。コストは片道1ティック×2（往復）。
"""
import argparse
import os
import sys
import time
from multiprocessing import Pool

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dtp_core as C  # noqa: E402
import dtp_data as D  # noqa: E402

MIN_TURNOVER = {"jp": 1e8, "us": 1e6}
BREAKOUTS = {"U1", "D1", "U2", "D2", "U3", "D3", "D4", "U10", "D10", "O1+", "O1-", "O4+", "O4-", "U4", "U5", "D5", "U6", "D6", "U7", "D7"}
# 寄り付き30分の勢い：(勢いを測る終わりの時刻, エントリーの足の開始時刻)。手じまいは大引け
MOM = {"jp": ("09:30", "14:55"), "us": ("10:00", "15:25")}
_M, _T500 = None, set()


def tick_jp(p, t500):
    if t500:
        for lim, tk in ((1000, 0.1), (3000, 0.5), (10000, 1), (30000, 5), (100000, 10), (300000, 50), (1e6, 100), (3e6, 500)):
            if p <= lim:
                return tk
        return 1000
    for lim, tk in ((3000, 1), (5000, 5), (30000, 10), (50000, 50), (300000, 100), (500000, 500), (3e6, 1000), (5e6, 5000)):
        if p <= lim:
            return tk
    return 10000


def cost_pct(p, market, t500):
    tk = tick_jp(p, t500) if market == "jp" else (0.01 if p >= 1 else 0.0001)
    return 2 * tk / p * 100


def sim(h, l, o, c, t, se, E, stop, target, d):
    """足 t の終値 E で入り、stop・target（None 可）・大引け se で手じまったときの損益（％、方向をそろえた値）"""
    for j in range(t + 1, se + 1):
        if d > 0:
            if l[j] <= stop:
                return (min(stop, o[j]) - E) / E * 100
            if target is not None and h[j] >= target:
                return (target - E) / E * 100
        else:
            if h[j] >= stop:
                return (E - max(stop, o[j])) / E * 100
            if target is not None and l[j] <= target:
                return (E - target) / E * 100
    return d * (c[se] - E) / E * 100


def _init(market, t500):
    global _M, _T500
    _M, _T500 = D.cfg(market), set(t500)


def daily_feats(code, dates):
    """日足：その日より前の終値の25日線かい離・5日騰落（日付→値）"""
    p = os.path.join(_M["base"], "data", "prices", f"{code}.csv")
    if not os.path.exists(p):
        return {}, {}
    try:
        d = pd.read_csv(p, usecols=["date", "close"]).dropna()
    except Exception:
        return {}, {}
    d = d.sort_values("date")
    ma = d["close"].rolling(25).mean()
    trend = (d["close"] / ma - 1) * 100
    r5 = (d["close"] / d["close"].shift(5) - 1) * 100
    s_tr = pd.Series(trend.values, index=d["date"].values)
    s_r5 = pd.Series(r5.values, index=d["date"].values)
    # その日の前営業日までの値
    idx = np.searchsorted(d["date"].values, np.array(dates), side="left") - 1
    out_tr, out_r5 = {}, {}
    for dt, i in zip(dates, idx):
        if i >= 0:
            out_tr[dt] = s_tr.iloc[i]
            out_r5[dt] = s_r5.iloc[i]
    return out_tr, out_r5


def one(code):
    m = _M
    df = D.load_archive(m, code)
    if df is None or len(df) < 300:
        return None
    day = df["dt"].str[:10]
    tvd = (df["c"] * df["v"]).groupby(day).sum()
    tv = float(tvd.mean())
    if tv < MIN_TURNOVER[m["key"]]:
        return None
    t500 = code in _T500
    try:
        ev, _, A = C.analyze(df)
    except Exception:
        return None
    o, h, l, c, v, atr, n = A["o"], A["h"], A["l"], A["c"], A["v"], A["atr"], A["n"]
    dt, ss, se = A["dt"], A["sess_start"], A["sess_end"]
    days = np.array([s[:10] for s in dt])
    k = np.arange(n) - ss                                   # セッション内の何本目か
    sopen = o[ss]
    first = np.flatnonzero(A["newsess"])
    prev_close = np.full(n, np.nan)
    for i, s in enumerate(first):
        if i > 0:
            prev_close[s:(first[i + 1] if i + 1 < len(first) else n)] = c[s - 1]
    gap = (sopen / prev_close - 1) * 100
    ret_open = (c / sopen - 1) * 100
    tp = (h + l + c) / 3
    g = pd.Series(days)
    cv = pd.Series(v).groupby(g).cumsum().to_numpy()
    vwap = pd.Series(tp * v).groupby(g).cumsum().to_numpy() / np.where(cv > 0, cv, np.nan)
    # 相対出来高：その時刻までの出来高 ÷ 直近5日の同じ時刻までの平均
    piv = pd.DataFrame({"d": days, "k": k, "cv": cv}).pivot_table(index="d", columns="k", values="cv")
    prev5 = piv.shift(1).rolling(5, min_periods=3).mean()
    st = prev5.stack()
    lut = {(a, b): x for (a, b), x in st.items()}
    rvol = np.array([cv[i] / lut[(days[i], k[i])] if (days[i], k[i]) in lut and lut[(days[i], k[i])] > 0 else np.nan
                     for i in range(n)])
    udays = list(dict.fromkeys(days))
    tr_d, r5_d = daily_feats(code, udays)
    hhmm = np.array([s[11:16] for s in dt])

    rows = []
    for e in ev:
        r = e["res"]
        if r is None:
            continue
        t, d, E = e["t"], e["d"], e["E"]
        tg, sp = e["target"], e["stop"]
        risk = abs(E - sp)
        cst = cost_pct(E, m["key"], t500)
        x = {"code": code, "dt": dt[t], "day": days[t], "key": e["key"], "d": d, "E": E,
             "tod": int(k[t]), "hhmm": hhmm[t],
             "trend_d": d * tr_d.get(days[t], np.nan), "r5_d": d * r5_d.get(days[t], np.nan),
             "rvol": rvol[t], "gap_d": d * gap[t], "dayret_d": d * ret_open[t],
             "vwap_d": d * (c[t] - vwap[t]) / atr[t] if np.isfinite(vwap[t]) else np.nan,
             "atrp": atr[t] / E * 100, "volr": e["volr"], "logtv": np.log10(tv), "price": E,
             "rr": abs(tg - E) / risk if risk > 0 else np.nan, "riskp": risk / E * 100,
             "cost": cst, "t500": t500,
             "hit": r["hit"], "pnl": r["pnl"] * 100, "r30": r["r30"] * 100, "r60": r["r60"] * 100, "rc": r["rc"] * 100}
        st_ = se[t]
        x["p1R"] = sim(h, l, o, c, t, st_, E, sp, E + d * risk, d)
        x["p2R"] = sim(h, l, o, c, t, st_, E, sp, E + d * 2 * risk, d)
        x["pstop"] = sim(h, l, o, c, t, st_, E, sp, None, d)
        # ブレイク失敗の逆張り：抜けた後6本以内に終値で線の内側へ戻ったら逆方向に入る（損切り＝抜けた後の高値/安値、目標1.5R）
        if e["key"] in BREAKOUTS:
            lv = e["level"]
            for j in range(t + 1, min(t + 7, st_)):
                if d * (c[j] - lv) < 0:
                    ext = h[t:j + 1].max() if d > 0 else l[t:j + 1].min()
                    Er = c[j]
                    spr = ext + d * 0.2 * atr[j]
                    rk = abs(spr - Er)
                    if rk > 0:
                        x["fail_t"] = dt[j]
                        x["fail_pnl"] = sim(h, l, o, c, j, st_, Er, spr, Er - d * 1.5 * rk, -d)
                        x["fail_rc"] = -d * (c[st_] - Er) / Er * 100
                        x["fail_cost"] = cost_pct(Er, m["key"], t500)
                    break
        rows.append(x)

    strat = []

    def add(kind, t, d, E, stop, target, extra=None):
        st_ = se[t]
        if t >= st_:
            return
        y = {"code": code, "dt": dt[t], "day": days[t], "kind": kind, "d": d, "E": E, "tod": int(k[t]), "hhmm": hhmm[t],
             "trend_d": d * tr_d.get(days[t], np.nan), "rvol": rvol[t], "gap_d": d * gap[t], "dayret_d": d * ret_open[t],
             "atrp": atr[t] / E * 100, "logtv": np.log10(tv), "cost": cost_pct(E, m["key"], t500),
             "pnl": sim(h, l, o, c, t, st_, E, stop, target, d),
             "r60": d * (c[min(t + 12, st_)] - E) / E * 100, "rc": d * (c[st_] - E) / E * 100}
        if extra:
            y.update(extra)
        strat.append(y)

    for i, s in enumerate(first):
        if i == 0 or not np.isfinite(prev_close[s]):
            continue
        e_ = se[s]
        if e_ - s < 20:
            continue
        pc = prev_close[s]
        gp = gap[s]
        # 窓の逆張り：1%以上の窓。寄り付き15分（3本）の後に窓と逆方向へ。目標＝前日終値（窓埋め）、損切り＝最初の15分の高値/安値＋ATR×0.5
        if abs(gp) >= 1.0:
            t = s + 2
            d = -1 if gp > 0 else 1
            ext = h[s:t + 1].max() if d < 0 else l[s:t + 1].min()
            stop = ext - d * 0.5 * atr[t]
            if d * (pc - c[t]) > 0:
                add("窓の逆張り", t, d, c[t], stop, pc, {"gap": abs(gp)})
        # 寄り付き30分の勢い：前日終値→寄り付き30分後の騰落の方向に、大引け30分前に入って大引けで手じまう
        mk_end, mk_ent = MOM[m["key"]]
        ii = np.flatnonzero((hhmm[s:e_ + 1] == mk_end))
        jj = np.flatnonzero((hhmm[s:e_ + 1] == mk_ent))
        if len(ii) and len(jj):
            a_, b_ = s + ii[0], s + jj[0]
            r0 = (c[a_] / pc - 1) * 100
            if abs(r0) >= 0.5 and b_ < e_:
                d = 1 if r0 > 0 else -1
                add("寄り付き30分の勢い", b_, d, c[b_], c[b_] - d * 3 * atr[b_], None, {"r0": abs(r0)})
        # VWAP回帰：寄り付き30分後〜大引け30分前、VWAP から ATR×3 以上離れて向きが変わった足で VWAP へ向けて入る
        last = -99
        for t in range(s + 6, e_ - 6):
            if not np.isfinite(vwap[t]) or t - last < 12:
                continue
            dev = (c[t] - vwap[t]) / atr[t]
            if dev >= 3 and c[t] < c[t - 1]:
                d = -1
            elif dev <= -3 and c[t] > c[t - 1]:
                d = 1
            else:
                continue
            ext = h[t - 5:t + 1].max() if d < 0 else l[t - 5:t + 1].min()
            add("VWAP回帰", t, d, c[t], ext - d * 0.5 * atr[t], vwap[t], {"dev": abs(dev)})
            last = t
    for x in rows:
        if "fail_t" in x:
            strat.append({"code": code, "dt": x["fail_t"], "day": x["day"], "kind": "ブレイク失敗の逆張り", "d": -x["d"],
                          "E": np.nan, "key": x["key"], "pnl": x["fail_pnl"], "rc": x["fail_rc"], "cost": x["fail_cost"],
                          "logtv": x["logtv"], "atrp": x["atrp"], "hhmm": x["fail_t"][11:16]})
    # 市場全体：足ごとの寄り付きからの騰落（合計・数）
    mk = pd.DataFrame({"dt": dt, "s": ret_open, "n": 1.0}).groupby("dt").sum()
    return rows, strat, mk


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", required=True, choices=["jp", "us"])
    ap.add_argument("--codes", default="")
    ap.add_argument("--procs", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    a = ap.parse_args()
    m = D.cfg(a.market)
    out = os.path.join(m["out"], "research")
    os.makedirs(out, exist_ok=True)
    t500 = []
    p5 = os.path.join(D.cfg("jp")["out"], "topix500.txt")
    if a.market == "jp" and os.path.exists(p5):
        t500 = open(p5).read().split()
    codes = [c for c in a.codes.split(",") if c] or sorted(D.load_tickers(m))
    t0 = time.time()
    rows, strat, mks = [], [], []
    with Pool(a.procs, initializer=_init, initargs=(a.market, t500)) as pool:
        for i, r in enumerate(pool.imap_unordered(one, codes, chunksize=4)):
            if r:
                rows += r[0]
                strat += r[1]
                mks.append(r[2])
            if (i + 1) % 500 == 0:
                print(f"  {i + 1}/{len(codes)}  シグナル {len(rows)}  {time.time() - t0:.0f}秒", flush=True)
    mk = pd.concat(mks).groupby(level=0).sum()
    mk["mkt"] = mk["s"] / mk["n"]
    mk = mk[mk["n"] >= 30][["mkt", "n"]]
    ev = pd.DataFrame(rows)
    stt = pd.DataFrame(strat)
    for X in (ev, stt):
        X["mkt_d"] = X["d"] * X["dt"].map(mk["mkt"])
    ev.to_pickle(os.path.join(out, "events.pkl"))
    stt.to_pickle(os.path.join(out, "strat.pkl"))
    mk.to_pickle(os.path.join(out, "market.pkl"))
    print(f"{m['name']}: シグナル {len(ev):,}件・その他の仕組み {len(stt):,}件・{ev['day'].nunique()}営業日  {time.time() - t0:.0f}秒")
    return 0


if __name__ == "__main__":
    sys.exit(main())
