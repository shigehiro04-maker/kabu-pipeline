#!/usr/bin/env python3
"""同じ22パターンを日足（約10年分）で検出し、結果を集める（通信なし）。

  python dtp_daily.py --market jp|us

- 判定は5分足と同じ dtp_core（日足モード：最長20営業日保有。目標・損切りに先に届いた方、どちらも無ければ20日後に手じまう）。
- 窓（その他❸）は日足では判定しない。
- 売買代金（直近20日平均）が 東証1億円・米国100万ドル未満の時点のシグナルは除く。
- いま上場している銘柄だけなので、上場廃止になった銘柄は入っていない（買いの成績が少し良く出やすい）。
出力（非公開） data/daytrade/research/daily_events.pkl・daily_base.pkl
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
from dtp_features import cost_pct  # noqa: E402

HOLD = 20
MIN_TV = {"jp": 1e8, "us": 1e6}
_M, _T500 = None, set()


def _init(market, t500):
    global _M, _T500
    _M, _T500 = D.cfg(market), set(t500)


def one(code):
    p = os.path.join(_M["base"], "data", "prices", f"{code}.csv")
    if not os.path.exists(p):
        return None
    try:
        d = pd.read_csv(p).dropna(subset=["open", "high", "low", "close"])
    except Exception:
        return None
    d = d[(d[["open", "high", "low", "close"]] > 0).all(axis=1)].sort_values("date").reset_index(drop=True)
    if len(d) < 300:
        return None
    df = pd.DataFrame({"dt": d["date"].astype(str), "o": d["open"], "h": d["high"], "l": d["low"], "c": d["close"],
                       "v": d["volume"].fillna(0)})
    try:
        ev, _, A = C.analyze(df, hold=HOLD)
    except Exception:
        return None
    c = A["c"]
    tv = (df["c"] * df["v"]).rolling(20).mean().to_numpy()
    ma200 = pd.Series(c).rolling(200).mean().to_numpy()
    ma25 = pd.Series(c).rolling(25).mean().to_numpy()
    t500 = code in _T500
    rows = []
    for e in ev:
        r = e["res"]
        t = e["t"]
        if r is None or not (tv[t] >= MIN_TV[_M["key"]]):
            continue
        dd = e["d"]
        rows.append((code, A["dt"][t], e["key"], dd, e["E"],
                     dd * (c[t] / ma200[t] - 1) * 100 if np.isfinite(ma200[t]) else np.nan,
                     dd * (c[t] / ma25[t] - 1) * 100 if np.isfinite(ma25[t]) else np.nan,
                     e["volr"], A["atr"][t] / c[t] * 100, np.log10(tv[t]),
                     r["hit"], r["pnl"] * 100, r["r30"] * 100, r["r60"] * 100, r["rc"] * 100,
                     cost_pct(e["E"], _M["key"], t500)))
    # 比べる基準：どの日に買っても12日後に上がっていた割合・平均（流動性の条件は同じ）
    n = len(c)
    j = np.minimum(np.arange(n) + 12, n - 1)
    ok = (j > np.arange(n)) & (tv >= MIN_TV[_M["key"]])
    fr = (c[j] - c) / c * 100
    base = pd.DataFrame({"y": pd.Series(A["dt"]).str[:4][ok].values, "r": fr[ok]})
    base = base.groupby("y")["r"].agg(["sum", "count", lambda x: (x > 0).sum()])
    base.columns = ["sum", "n", "up"]
    # 市場全体：日ごとの騰落（全銘柄平均）
    dr = pd.DataFrame({"dt": A["dt"][1:], "r": (c[1:] / c[:-1] - 1) * 100, "n": 1.0})
    dr = dr[np.abs(dr["r"]) < 50].groupby("dt").sum()
    return rows, base, dr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", required=True, choices=["jp", "us"])
    ap.add_argument("--procs", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    a = ap.parse_args()
    m = D.cfg(a.market)
    out = os.path.join(m["out"], "research")
    os.makedirs(out, exist_ok=True)
    t500 = []
    p5 = os.path.join(D.cfg("jp")["out"], "topix500.txt")
    if a.market == "jp" and os.path.exists(p5):
        t500 = open(p5).read().split()
    codes = sorted(D.load_tickers(m))
    t0 = time.time()
    rows, bases, drs = [], [], []
    with Pool(a.procs, initializer=_init, initargs=(a.market, t500)) as pool:
        for i, r in enumerate(pool.imap_unordered(one, codes, chunksize=8)):
            if r:
                rows += r[0]
                bases.append(r[1])
                drs.append(r[2])
            if (i + 1) % 1000 == 0:
                print(f"  {i + 1}/{len(codes)}  シグナル {len(rows):,}  {time.time() - t0:.0f}秒", flush=True)
    cols = ["code", "dt", "key", "d", "E", "trend200_d", "dev25_d", "volr", "atrp", "logtv", "hit", "pnl",
            "r30", "r60", "rc", "cost"]
    ev = pd.DataFrame(rows, columns=cols)
    mk = pd.concat(drs).groupby(level=0).sum()
    mk["r"] = mk["r"] / mk["n"]
    mk = mk[mk["n"] >= 30]
    # 地合い：直近20日の市場全体の騰落（シグナルの日まで）
    m20 = mk["r"].rolling(20).sum()
    ev["mkt20_d"] = ev["d"] * ev["dt"].map(m20)
    ev["year"] = ev["dt"].str[:4]
    # 市場平均（全銘柄）の、シグナルの日から20営業日先までの騰落（方向をそろえる）。パターンの20日後と比べるため
    fwd = mk["r"][::-1].rolling(HOLD, min_periods=HOLD).sum()[::-1].shift(-1)
    ev["mkt_fwd20_d"] = ev["d"] * ev["dt"].map(fwd)
    mk.to_pickle(os.path.join(out, "daily_market.pkl"))
    base = pd.concat(bases).groupby(level=0).sum()
    ev.to_pickle(os.path.join(out, "daily_events.pkl"))
    base.to_pickle(os.path.join(out, "daily_base.pkl"))
    print(f"{m['name']} 日足: シグナル {len(ev):,}件（{ev['dt'].min()}〜{ev['dt'].max()}）  {time.time() - t0:.0f}秒")
    return 0


if __name__ == "__main__":
    sys.exit(main())
