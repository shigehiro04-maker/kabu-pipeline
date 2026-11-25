#!/usr/bin/env python3
"""保管してある5分足（data/intraday_archive、2026-08〜）で、各パターンが出た後の値動きを集計する。

  python dtp_backtest.py --market jp     （東証）
  python dtp_backtest.py --market us     （米国）

出力（公開しない控え）: data/daytrade/events.csv.gz（1行=1回のシグナルと結果）
出力（ページ用）      : data/daytrade/stats.json（パターンごとの勝率・目標到達率・平均損益など）
- エントリー＝シグナルが出た足の終値。手じまい＝目標・損切りに先に届いた方、どちらも無ければその日の大引け。
- 手数料・スリッページは入れていない。大引けの足（その日の最後の足）で出たシグナルは結果が無いので集計しない。
- 売買代金が小さすぎる銘柄（1日平均 東証1億円・米国100万ドル未満）は集計から外す（デイトレードに向かない）。
"""
import argparse
import datetime
import json
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
# 時間帯の区切り（寄り付きから約1時間／中盤／引け前）
TODS = {"jp": ("10:00", "14:00"), "us": ("10:30", "14:30")}
TOD = TODS["jp"]
_M = None


def _init(market):
    global _M
    _M = D.cfg(market)


def one(code):
    df = D.load_archive(_M, code)
    if df is None or len(df) < 200:
        return code, None, None
    days = df["dt"].str[:10]
    tv = (df["c"] * df["v"]).groupby(days).sum()
    if tv.mean() < MIN_TURNOVER[_M["key"]]:
        return code, None, None
    try:
        ev, _, A = C.analyze(df)
    except Exception:
        return code, None, None
    rows = []
    for e in ev:
        r = e["res"]
        if r is None:
            continue
        rows.append((code, A["dt"][e["t"]], e["key"], round(e["E"], 4), round(e["target"], 4), round(e["stop"], 4),
                     r["hit"], round(r["pnl"] * 100, 4), round(r["r30"] * 100, 4), round(r["r60"] * 100, 4),
                     round(r["rc"] * 100, 4), e["volr"]))
    # 比べる基準：どの足で買っても1時間後に上がっている割合と平均
    c, se = A["c"], A["sess_end"]
    idx = np.arange(A["n"])
    j = np.minimum(idx + 12, se)
    ok = j > idx
    base = (c[j[ok]] - c[idx[ok]]) / c[idx[ok]]
    bl = (int((base > 0).sum()), int((base < 0).sum()), float(base.sum()), int(ok.sum()))
    return code, rows, bl


def summarize(ev):
    def st(g):
        p = g["pnl"].to_numpy()
        if len(p) == 0:
            return None
        return {"n": int(len(p)), "win": round(float((p > 0).mean() * 100), 1),
                "tgt": round(float((g["hit"] == "target").mean() * 100), 1),
                "stp": round(float((g["hit"] == "stop").mean() * 100), 1),
                "avg": round(float(p.mean()), 3), "med": round(float(np.median(p)), 3),
                "avg_win": round(float(p[p > 0].mean()), 3) if (p > 0).any() else None,
                "avg_loss": round(float(p[p <= 0].mean()), 3) if (p <= 0).any() else None,
                "w30": round(float((g["r30"] > 0).mean() * 100), 1), "a30": round(float(g["r30"].mean()), 3),
                "w60": round(float((g["r60"] > 0).mean() * 100), 1), "a60": round(float(g["r60"].mean()), 3),
                "wc": round(float((g["rc"] > 0).mean() * 100), 1), "ac": round(float(g["rc"].mean()), 3)}
    out = {}
    for k, g in ev.groupby("key"):
        s = st(g)
        hv = g[g["volr"].fillna(0) >= 1.5]
        s["vol"] = st(hv) if len(hv) >= 20 else None
        s["codes"] = int(g["code"].nunique())
        hh = g["dt"].str[11:16]
        for nm, mk in (("am", hh < TOD[0]), ("mid", (hh >= TOD[0]) & (hh < TOD[1])), ("pm", hh >= TOD[1])):
            sub = g[mk]
            s[nm] = st(sub) if len(sub) >= 20 else None
        out[k] = s
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", required=True, choices=["jp", "us"])
    ap.add_argument("--codes", default="")
    ap.add_argument("--procs", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    a = ap.parse_args()
    m = D.cfg(a.market)
    global TOD
    TOD = TODS[a.market]
    os.makedirs(m["out"], exist_ok=True)
    codes = [c for c in a.codes.split(",") if c] or sorted(D.load_tickers(m))
    t0 = time.time()
    rows, bl = [], [0, 0, 0.0, 0]
    with Pool(a.procs, initializer=_init, initargs=(a.market,)) as pool:
        for i, (code, r, b) in enumerate(pool.imap_unordered(one, codes, chunksize=8)):
            if r:
                rows += r
            if b:
                bl = [bl[0] + b[0], bl[1] + b[1], bl[2] + b[2], bl[3] + b[3]]
            if (i + 1) % 500 == 0:
                print(f"  {i + 1}/{len(codes)}  シグナル {len(rows)}  {time.time() - t0:.0f}秒", flush=True)
    cols = ["code", "dt", "key", "E", "target", "stop", "hit", "pnl", "r30", "r60", "rc", "volr"]
    ev = pd.DataFrame(rows, columns=cols).sort_values(["dt", "code"])
    ev.to_csv(os.path.join(m["out"], "events.csv.gz"), index=False, compression="gzip")
    days = sorted(ev["dt"].str[:10].unique()) if len(ev) else []
    stats = {"market": a.market, "made": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
             "from": days[0] if days else None, "to": days[-1] if days else None, "sessions": len(days),
             "codes": int(ev["code"].nunique()) if len(ev) else 0, "signals": int(len(ev)),
             "baseline": {"up60": round(bl[0] / max(1, bl[3]) * 100, 1), "down60": round(bl[1] / max(1, bl[3]) * 100, 1),
                          "avg60": round(bl[2] / max(1, bl[3]) * 100, 4)},
             "patterns": summarize(ev) if len(ev) else {}}
    with open(os.path.join(m["out"], "stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=1)
    print(f"検証: {stats['codes']}銘柄・{stats['sessions']}営業日（{stats['from']}〜{stats['to']}）"
          f"・シグナル {stats['signals']}件  {time.time() - t0:.0f}秒")
    for k in C.PATTERNS:
        s = stats["patterns"].get(k)
        if s:
            print(f"  {k:4s} {C.PATTERNS[k][1]:22s} n={s['n']:6d} 勝率{s['win']:5.1f}% 目標{s['tgt']:5.1f}% "
                  f"損切{s['stp']:5.1f}% 平均{s['avg']:+.3f}% 1h勝率{s['w60']:5.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
