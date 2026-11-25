#!/usr/bin/env python3
"""全銘柄の5分足でチャートパターンを判定し、ページ用のデータを書く。

  引け後（毎日の更新）: python dtp_scan.py --market jp --mode close
                         手元の data/intraday（その日まで）で、その日に出たシグナル（結果つき）と、
                         大引け時点で形成中（ブレイク待ち）のパターンを出す。
  取引中（15分おき）  : python dtp_scan.py --market us --mode live
                         Yahoo から当日の5分足を取り（東証は約20分遅れ）、前日までの手元の5分足とつないで判定する。
                         取引時間外・休場日は何もしない。手元のCSV・保管庫には書かない。

出力（公開）: data/charts/daytrade/latest.json（一覧）、data/charts/daytrade/b<0〜15>.json（銘柄ごとの線と当日の足）、
              data/charts/daytrade/stats.json（パターン別の成績。dtp_backtest.py の結果をそのまま写す）
"""
import argparse
import datetime
import json
import os
import shutil
import sys
import time
from multiprocessing import Pool

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dtp_core as C  # noqa: E402
import dtp_data as D  # noqa: E402

NSHARD = 16
SESS = {"jp": ("09:00", "15:30"), "us": ("09:30", "16:00")}
TAIL_SESSIONS = 6
_M, _TODAY = None, None


def shard(code):
    return sum(ord(ch) for ch in code) % NSHARD


def r4(x):
    if x is None or not np.isfinite(x):
        return None
    ax = abs(x)
    return round(float(x), 2 if ax >= 100 else 3 if ax >= 1 else 4)


def _init(market, today):
    global _M, _TODAY
    _M, _TODAY = D.cfg(market), today


def one(args):
    code, df = args
    if df is None or len(df) < 80:
        return None
    days = df["dt"].str[:10]
    ud = sorted(days.unique())
    df = df[days.isin(ud[-TAIL_SESSIONS:])].reset_index(drop=True)
    days = df["dt"].str[:10]
    last_day = days.iloc[-1]
    prev = df[days < last_day]
    tvd = (prev["c"] * prev["v"]).groupby(prev["dt"].str[:10]).sum()
    tv = float(tvd.tail(5).mean()) if len(tvd) else 0.0
    t_from = int(np.flatnonzero((days == last_day).to_numpy())[0])
    try:
        ev, fm, A = C.analyze(df, t_from=t_from, want_outcome=True)
    except Exception:
        return None
    n = A["n"]
    last = float(A["c"][-1])
    pc = float(prev["c"].iloc[-1]) if len(prev) else None
    chg = (last / pc - 1) * 100 if pc else None
    dt = A["dt"]
    sig, form, draws = [], [], []
    for e in ev:
        if e["t"] < t_from:
            continue
        r = e["res"]
        hit = r["hit"] if r else "open"
        pnl = r["pnl"] * 100 if r else 0.0
        pts, lines = C.drawing(e, e["d"])
        hhmm = dt[e["t"]][11:16]
        sig.append([code, hhmm, e["key"], r4(e["E"]), r4(e["target"]), r4(e["stop"]), r4(e["level"]),
                    e["volr"], hit, round(pnl, 3), n - 1 - e["t"]])
        draws.append({"k": f"{e['key']}|{hhmm}", "e": dt[e["t"]], "p": [[dt[i], r4(p)] for i, p in pts],
                      "l": [[dt[max(0, a)], r4(b), dt[min(x, n - 1)], r4(y)] for a, b, x, y in lines]})
    for f in fm:
        pts, lines = C.drawing(f, f["d"])
        form.append([code, f["key"], r4(f["level"]), r4(f["target"]), r4(f["stop"]), f["dist_pct"], f["dist_atr"]])
        draws.append({"k": f"{f['key']}|形成中", "e": None, "p": [[dt[i], r4(p)] for i, p in pts],
                      "l": [[dt[max(0, a)], r4(b), dt[min(x, n - 1)], r4(y)] for a, b, x, y in lines]})
    today_bars = None
    if _TODAY is not None:          # 取引中：当日の足（チャートの intra/*.js は前日まで）
        g = df[days == last_day]
        today_bars = [[s[11:16].replace(":", ""), r4(o), r4(h), r4(l), r4(c), int(v)]
                      for s, o, h, l, c, v in zip(g["dt"], g["o"], g["h"], g["l"], g["c"], g["v"])]
    if not sig and not form:
        return {"code": code, "tv": tv, "last": last, "chg": chg, "sig": [], "form": [], "draws": [], "today": None, "day": last_day}
    return {"code": code, "tv": tv, "last": r4(last), "chg": None if chg is None else round(chg, 2),
            "sig": sig, "form": form, "draws": draws, "today": today_bars, "day": last_day}


# ---------------------------------------------------------------- 取引中のデータ取得
def fetch_today(m, codes, now_ex):
    import yfinance as yf
    out = {}
    today = now_ex.strftime("%Y-%m-%d")
    syms = {c: m["yahoo"](c) for c in codes}
    B = 200
    for i in range(0, len(codes), B):
        part = codes[i:i + B]
        for attempt in range(2):
            try:
                data = yf.download([syms[c] for c in part], period="1d", interval="5m", group_by="ticker",
                                   auto_adjust=False, prepost=False, threads=True, progress=False, actions=False)
                break
            except Exception as ex:
                data = None
                print(f"  {i}: 失敗（{ex}）", flush=True)
                time.sleep(5)
        if data is None or data.empty:
            continue
        for c in part:
            s = syms[c]
            try:
                sub = data[s] if isinstance(data.columns, pd.MultiIndex) else data
            except KeyError:
                continue
            sub = sub.dropna(subset=["Open", "High", "Low", "Close"])
            if sub.empty:
                continue
            idx = sub.index.tz_convert(m["tz"]) if sub.index.tz is not None else sub.index
            d = pd.DataFrame({"dt": idx.strftime("%Y-%m-%d %H:%M"), "o": sub["Open"].values, "h": sub["High"].values,
                              "l": sub["Low"].values, "c": sub["Close"].values, "v": sub["Volume"].fillna(0).values})
            d = d[d["dt"].str[:10] == today]
            if len(d) >= 2:
                out[c] = d.iloc[:-1]        # 最後の足はまだ途中なので使わない
        print(f"  [{time.strftime('%H:%M:%S')}] {min(i + B, len(codes))}/{len(codes)}  当日の足 {len(out)}", flush=True)
        time.sleep(0.5)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", required=True, choices=["jp", "us"])
    ap.add_argument("--mode", default="close", choices=["close", "live"])
    ap.add_argument("--codes", default="")
    ap.add_argument("--force", action="store_true", help="取引時間外でも live を実行（確認用）")
    ap.add_argument("--procs", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    a = ap.parse_args()
    m = D.cfg(a.market)
    tick = D.load_tickers(m)
    codes = [c for c in a.codes.split(",") if c] or sorted(tick)
    now_ex = datetime.datetime.now(tz=__import__("zoneinfo").ZoneInfo(m["tz"]))
    t0 = time.time()
    today = None
    todays = {}
    if a.mode == "live":
        hm = now_ex.strftime("%H:%M")
        op, cl = SESS[a.market]
        if not a.force and (now_ex.weekday() >= 5 or not (op < hm <= "16:10" if a.market == "us" else op < hm <= "15:40")):
            print(f"取引時間外（{now_ex:%Y-%m-%d %H:%M} 現地）のため何もしません")
            return 3
        todays = fetch_today(m, codes, now_ex)
        if len(todays) < len(codes) * 0.2:
            print(f"当日の足が取れた銘柄が少ない（{len(todays)}）ので休場日とみて終了")
            return 3
        today = now_ex.strftime("%Y-%m-%d")

    def gen():
        for c in codes:
            df = D.load_recent(m, c)
            if today is not None:
                td = todays.get(c)
                if td is None:
                    continue
                df = pd.concat([df[df["dt"].str[:10] < today], td]) if df is not None else td
                df = df.reset_index(drop=True)
            yield c, df

    res = []
    with Pool(a.procs, initializer=_init, initargs=(a.market, today)) as pool:
        for r in pool.imap_unordered(one, gen(), chunksize=16):
            if r:
                res.append(r)
    if not res:
        print("判定できる銘柄がありません")
        return 1
    day = max(r["day"] for r in res)
    res = [r for r in res if r["day"] == day]     # 最新日に足がある銘柄だけ
    sig, form = [], []
    shards = [dict() for _ in range(NSHARD)]
    info = {}
    for r in res:
        c = r["code"]
        if r["sig"] or r["form"]:
            info[c] = [tick.get(c, {}).get("name", ""), tick.get(c, {}).get("market", ""), round(r["tv"] / 1e6, 1),
                       r["last"], r["chg"]]
            sig += r["sig"]
            form += r["form"]
            shards[shard(c)][c] = {"d": r["draws"], "t": r["today"]}
    asof = max((s[1] for s in sig), default="")
    if today is not None:
        last_bar = max((len(v) for v in todays.values()), default=0)
        asof = max(todays[c]["dt"].iloc[-1] for c in todays)[11:16] if todays else ""
    out_dir = os.path.join(m["pub"], "daytrade")
    os.makedirs(out_dir, exist_ok=True)
    jst = datetime.datetime.now(tz=__import__("zoneinfo").ZoneInfo("Asia/Tokyo"))
    data = {"market": a.market, "mode": a.mode, "day": day, "asof": asof, "made": jst.strftime("%Y-%m-%d %H:%M"),
            "live": today is not None and now_ex.strftime("%H:%M") < SESS[a.market][1],
            "cols_sig": ["code", "time", "key", "entry", "target", "stop", "level", "volr", "hit", "pnl", "ago"],
            "cols_form": ["code", "key", "level", "target", "stop", "dist_pct", "dist_atr"],
            "info_cols": ["name", "market", "tv_m", "last", "chg"],
            "patterns": {k: [v[0], v[1], v[2]] for k, v in C.PATTERNS.items()},
            "sig": sorted(sig, key=lambda s: (s[1], s[0]), reverse=True), "form": form, "info": info,
            "nshard": NSHARD, "scanned": len(res)}
    tmp = os.path.join(out_dir, "latest.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, os.path.join(out_dir, "latest.json"))
    for i, s in enumerate(shards):
        tmp = os.path.join(out_dir, f"b{i}.json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, os.path.join(out_dir, f"b{i}.json"))
    st = os.path.join(m["out"], "stats.json")
    if os.path.exists(st):
        shutil.copyfile(st, os.path.join(out_dir, "stats.json"))
    print(f"{m['name']} {a.mode}: {day} {asof} 時点  判定 {len(res)}銘柄・シグナル {len(sig)}件・形成中 {len(form)}件  "
          f"{time.time() - t0:.0f}秒")
    return 0


if __name__ == "__main__":
    sys.exit(main())
