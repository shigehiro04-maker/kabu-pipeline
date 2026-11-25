#!/usr/bin/env python3
"""Yahoo の四半期財務に、TDnet で発表済みの最新の決算がどこまで入っているかを東証全銘柄で調べる。

  1) Yahoo fundamentals-timeseries の四半期・年次（売上・営業利益・純利益）を全銘柄で取る
     → fundamentals/raw_quarterly/<コード>.json（--no-fetch で通信せずに集計だけ）
  2) fundamentals/kessan_latest.csv（fetch_tdnet.py）の最新の決算短信の期間末と比べる
  3) 結果 → fundamentals/verify/yahoo_quarter_check.csv と画面に集計
"""
import argparse
import csv
import datetime as dt
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import fetch_fundamentals as ff

BASE = Path(__file__).resolve().parent
RAW = BASE / "fundamentals" / "raw_quarterly"
KEYS = ["TotalRevenue", "OperatingIncome", "NetIncome"]
TYPES = ",".join([f"quarterly{k}" for k in KEYS] + [f"annual{k}" for k in KEYS])


def fetch(code, pacer):
    sym = f"{code}.T"
    params = {"symbol": sym, "type": TYPES, "period1": int(dt.datetime(2023, 1, 1).timestamp()),
              "period2": int(dt.datetime.now().timestamp())}
    for i in range(4):
        pacer.wait()
        try:
            r = ff.get_session().get(ff.TS_URL.format(sym=sym), params=params, timeout=20)
            if r.status_code == 429:
                pacer.slow_down()
                continue
            if r.status_code == 404:
                return {}
            r.raise_for_status()
            return r.json()
        except Exception:  # noqa
            ff._local.session = None
    return None


def parse(p):
    out = {"quarterly": {}, "annual": {}}
    for it in (p.get("timeseries") or {}).get("result") or []:
        for k, vals in it.items():
            if k in ("meta", "timestamp") or not isinstance(vals, list):
                continue
            b = "quarterly" if k.startswith("quarterly") else "annual"
            base = k[len(b):]
            for v in vals:
                if v and v.get("asOfDate") and (v.get("reportedValue") or {}).get("raw") is not None:
                    out[b].setdefault(v["asOfDate"], {})[base] = v["reportedValue"]["raw"]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    uni = ff.load_universe()
    if not a.no_fetch:
        pacer = ff.Pacer(0.3)
        done = [0]
        lock = threading.Lock()

        def work(m):
            p = fetch(m["code"], pacer)
            if p is not None:
                (RAW / f"{m['code']}.json").write_text(json.dumps(p), encoding="utf-8")
            with lock:
                done[0] += 1
                if done[0] % 300 == 0:
                    ff.log(f"{done[0]}/{len(uni)}")
        with ThreadPoolExecutor(a.workers) as ex:
            list(ex.map(work, uni))
    td = {}
    with (BASE / "fundamentals" / "kessan_latest.csv").open(encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            td[r["コード"]] = r
    rows = []
    for m in uni:
        c = m["code"]
        f = RAW / f"{c}.json"
        y = parse(json.loads(f.read_text())) if f.exists() else {"quarterly": {}, "annual": {}}
        qd = sorted(y["quarterly"])
        ad = sorted(y["annual"])
        t = td.get(c)
        row = {"コード": c, "銘柄名": m["name"], "市場": m["market"],
               "Yahoo最新四半期": qd[-1] if qd else "", "Yahoo最新年次": ad[-1] if ad else "",
               "TDnet開示日": t["開示日"] if t else "", "TDnet期間末": t["期間末"] if t else "",
               "TDnet四半期": t["四半期"] if t else ""}
        if t and t["期間末"]:
            pe = t["期間末"]
            has_q = pe in y["quarterly"]
            has_a = t["四半期"] == "4" and pe in y["annual"]
            row["反映"] = "あり" if (has_q or has_a) else "なし"
            row["経過日数"] = (dt.date.today() - dt.date.fromisoformat(t["開示日"])).days
            # 第1四半期・本決算は累計＝その期なので売上を突き合わせられる
            # 第1〜3四半期は累計なので、Yahoo の四半期を q 期分足して比べる（途中の期が欠けていれば比べない）
            yv = None
            q = int(t["四半期"] or 0)
            if t["四半期"] == "4" and has_a:
                yv = y["annual"][pe].get("TotalRevenue")
            elif 1 <= q <= 3 and has_q:
                ds = [d for d in qd if d <= pe][-q:]
                span = (dt.date.fromisoformat(pe) - dt.date.fromisoformat(ds[0])).days
                if len(ds) == q and span <= (q - 1) * 92 + 5:
                    vs = [y["quarterly"][d].get("TotalRevenue") for d in ds]
                    if all(v is not None for v in vs):
                        yv = sum(vs)
            if yv and t["売上高"]:
                row["売上の差(%)"] = round((yv / float(t["売上高"]) - 1) * 100, 2)
        rows.append(row)
    cols = ["コード", "銘柄名", "市場", "TDnet開示日", "TDnet期間末", "TDnet四半期", "Yahoo最新四半期",
            "Yahoo最新年次", "反映", "経過日数", "売上の差(%)"]
    out = BASE / "fundamentals" / "verify" / "yahoo_quarter_check.csv"
    out.parent.mkdir(exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, cols)
        w.writeheader()
        w.writerows(rows)
    # 集計
    tgt = [r for r in rows if r.get("反映")]
    print(f"全銘柄 {len(rows)}、TDnet で直近31日に決算短信あり {len(tgt)}")
    print(f"Yahoo に反映済み {sum(r['反映']=='あり' for r in tgt)}（{sum(r['反映']=='あり' for r in tgt)/max(len(tgt),1)*100:.1f}%）")
    bins = [(0, 3), (4, 7), (8, 14), (15, 21), (22, 40)]
    for lo, hi in bins:
        g = [r for r in tgt if lo <= r["経過日数"] <= hi]
        if g:
            k = sum(r["反映"] == "あり" for r in g)
            print(f"  発表から{lo}〜{hi}日: {k}/{len(g)}（{k/len(g)*100:.0f}%）")
    for mk in ("プライム", "スタンダード", "グロース"):
        g = [r for r in tgt if mk in r["市場"]]
        if g:
            k = sum(r["反映"] == "あり" for r in g)
            print(f"  {mk}: {k}/{len(g)}（{k/len(g)*100:.0f}%）")
    d = [r["売上の差(%)"] for r in rows if r.get("売上の差(%)") is not None]
    if d:
        ok = sum(abs(x) < 0.5 for x in d)
        print(f"売上の突き合わせ（第1四半期・本決算） {len(d)} 件中、差0.5%未満 {ok}")
    nod = [r for r in rows if not r["Yahoo最新四半期"]]
    print(f"Yahoo に四半期データが1つも無い銘柄 {len(nod)}")
    print(f"→ {out}")


if __name__ == "__main__":
    sys.exit(main())
