#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
東証株のアナリスト予想を Yahoo Finance の quoteSummary（無料）から1銘柄1リクエストで取る。

取得するモジュール
  financialData            目標株価（平均・中央値・高値・安値）、投資判断の平均点、アナリスト人数
  recommendationTrend      投資判断の人数分布（今月〜3か月前）
  earningsTrend            EPS・売上高の予想（今四半期・来四半期・今期・来期）、予想の推移（7〜90日前）、修正件数
  earningsHistory          過去4四半期の予想と実績（決算サプライズ）
  upgradeDowngradeHistory  証券会社ごとの格上げ・格下げ・目標株価変更の履歴

出力
  fundamentals/analyst.csv            1行=1銘柄（ランキング・スクリーニング用の主な数値）
  fundamentals/analyst.json           {コード: 詳細}（株式分析ダッシュボード用）
  fundamentals/analyst_history/<日付>.csv.gz  取得した日の analyst.csv の控え（過去の予想は Yahoo に残らないため手元にためる）
  fundamentals/raw_analyst/<yahoo>.json  生レスポンス（キャッシュ）

使い方
  python us_fetch_analyst.py                 # 6日以上前に取った銘柄だけ取り直す（初回は全銘柄・約20分）
  python us_fetch_analyst.py --codes 7203,6758
  python us_fetch_analyst.py --rebuild-only  # 通信せず、最新の終値で上昇余地を計算し直す
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path

import random
import threading

BASE = Path(__file__).resolve().parent
FUND = BASE / "fundamentals"
RAW = FUND / "raw_analyst"
RAW.mkdir(parents=True, exist_ok=True)
HIST = FUND / "analyst_history"
API = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/{sym}"
MODULES = "financialData,recommendationTrend,earningsTrend,earningsHistory,upgradeDowngradeHistory"
TICKERS = BASE / "tickers" / "tse_tickers.csv"

# ---- Yahoo quoteSummary の取得（米国株分析/us_fetch_profile.py と同じ作り） ----
_lock = threading.Lock()
_local = threading.local()


def log(m):
    with _lock:
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {m}", flush=True)


class Pacer:
    def __init__(self, interval):
        self.interval = interval
        self._next = 0.0
        self._l = threading.Lock()

    def wait(self):
        with self._l:
            now = time.monotonic()
            t = max(now, self._next)
            self._next = t + self.interval
        if t > now:
            time.sleep(t - now)

    def slow(self):
        with self._l:
            self.interval = min(self.interval * 1.5, 3.0)
            self._next = time.monotonic() + 30
        log(f"アクセス過多を検知 → 間隔 {self.interval:.2f} 秒、30秒待機")


_sess = {"s": None, "crumb": None, "gen": 0}
_sess_lock = threading.Lock()


def session(bad_gen=None):
    """cookie と crumb は全スレッドで1つを共用する（crumb の取り直しが多いと Yahoo に弾かれるため）"""
    with _sess_lock:
        if _sess["s"] is not None and bad_gen != _sess["gen"]:
            return _sess["s"], _sess["crumb"], _sess["gen"]
        from curl_cffi import requests as creq
        for attempt in range(6):
            s = creq.Session(impersonate="chrome")
            try:
                s.get("https://fc.yahoo.com", timeout=20)
                crumb = s.get("https://query2.finance.yahoo.com/v1/test/getcrumb", timeout=20).text.strip()
            except Exception:
                crumb = ""
            if crumb and len(crumb) <= 40 and " " not in crumb and "<" not in crumb:
                _sess.update(s=s, crumb=crumb, gen=_sess["gen"] + 1)
                return s, crumb, _sess["gen"]
            wait = 30 * (attempt + 1)
            log(f"crumb を取得できません（{crumb[:30]!r}）→ {wait}秒待って再試行")
            time.sleep(wait)
        raise RuntimeError("crumb を取得できませんでした")


def fetch(sym, pacer):
    last = None
    gen = None
    for attempt in range(5):
        pacer.wait()
        try:
            s, crumb, gen = session(gen if attempt and last == "401" else None)
            r = s.get(API.format(sym=sym), params={"modules": MODULES, "crumb": crumb}, timeout=25)
            if r.status_code == 429:
                pacer.slow()
                last = "429"
                continue
            if r.status_code == 404:
                return {"_notfound": True}
            if r.status_code == 401:
                last = "401"
                continue
            r.raise_for_status()
            last = None
            res = (r.json().get("quoteSummary") or {}).get("result") or []
            return res[0] if res else {"_notfound": True}
        except Exception as e:
            last = str(e)
            time.sleep(min(2 ** attempt, 10) + random.random())
    raise RuntimeError(str(last))


def raw(v):
    if isinstance(v, dict):
        return v.get("raw", v.get("fmt"))
    return v


def fmtdate(v):
    v = raw(v)
    if isinstance(v, (int, float)) and v > 0:
        return datetime.fromtimestamp(v, timezone.utc).strftime("%Y-%m-%d")
    return v or ""




def load_tickers():
    """東証の銘柄一覧。Yahoo のコードは <コード>.T"""
    with open(TICKERS, encoding="utf-8-sig") as f:
        return [{"code": r["code"], "yahoo": r["code"] + ".T", "name": r["name"], "market": r.get("market", "")}
                for r in csv.DictReader(f)]


PERIODS = ["0q", "+1q", "0y", "+1y"]
MIN_ANALYSTS = 3     # 目標株価・投資判断をランキングに使う最低人数（CSV の「人数」列で絞る）


def num(v):
    v = raw(v)
    return v if isinstance(v, (int, float)) and v == v else None


def r(v, n=2):
    return round(v, n) if isinstance(v, (int, float)) else None


def pct(a, b):
    """(a-b)/|b| を % で"""
    if a is None or b is None or b == 0:
        return None
    return round((a - b) / abs(b) * 100, 2)


def latest_close():
    d = BASE / "data" / "daily"
    files = sorted(d.glob("*.csv"))
    if not files:
        return {}, ""
    out = {}
    with open(files[-1], encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            try:
                out[row["code"]] = float(row["close"])
            except (ValueError, KeyError):
                pass
    return out, files[-1].stem


def parse(d, close, base=None):
    """生レスポンス → (詳細 dict, CSV 用の1行)。予想が何も無ければ (None, None)"""
    fd = d.get("financialData") or {}
    px = close if close else num(fd.get("currentPrice"))
    tg = {k: num(fd.get(s)) for k, s in (("mean", "targetMeanPrice"), ("median", "targetMedianPrice"),
                                         ("high", "targetHighPrice"), ("low", "targetLowPrice"))}
    n_tg = num(fd.get("numberOfAnalystOpinions"))
    rec_mean = num(fd.get("recommendationMean"))

    rec = []
    for t in (d.get("recommendationTrend") or {}).get("trend") or []:
        row = [t.get("period"), t.get("strongBuy") or 0, t.get("buy") or 0, t.get("hold") or 0,
               t.get("sell") or 0, t.get("strongSell") or 0]
        if sum(row[1:]):
            rec.append(row)
    rec0 = next((x for x in rec if x[0] == "0m"), None)
    rec3 = next((x for x in rec if x[0] == "-3m"), None)

    def score(x):   # 1=強い買い … 5=強い売り
        n = sum(x[1:])
        return round(sum((i + 1) * c for i, c in enumerate(x[1:])) / n, 2) if n else None

    est = {}
    cur_e = cur_r = ""
    for t in (d.get("earningsTrend") or {}).get("trend") or []:
        p = t.get("period")
        if p not in PERIODS:
            continue
        ee, re_ = t.get("earningsEstimate") or {}, t.get("revenueEstimate") or {}
        et, er = t.get("epsTrend") or {}, t.get("epsRevisions") or {}
        cur_e = cur_e or ee.get("earningsCurrency") or et.get("epsTrendCurrency") or ""
        cur_r = cur_r or re_.get("revenueCurrency") or ""
        e = {"end": t.get("endDate") or "",
             "eps": num(ee.get("avg")), "eps_lo": num(ee.get("low")), "eps_hi": num(ee.get("high")),
             "eps_n": num(ee.get("numberOfAnalysts")), "eps_ya": num(ee.get("yearAgoEps")),
             "eps_g": r(num(ee.get("growth")) * 100, 1) if num(ee.get("growth")) is not None else None,
             "rev": num(re_.get("avg")), "rev_lo": num(re_.get("low")), "rev_hi": num(re_.get("high")),
             "rev_n": num(re_.get("numberOfAnalysts")), "rev_ya": num(re_.get("yearAgoRevenue")),
             "rev_g": r(num(re_.get("growth")) * 100, 1) if num(re_.get("growth")) is not None else None,
             "t": [num(et.get(k)) for k in ("current", "7daysAgo", "30daysAgo", "60daysAgo", "90daysAgo")],
             "up7": num(er.get("upLast7days")), "up30": num(er.get("upLast30days")),
             "dn7": num(er.get("downLast7Days")), "dn30": num(er.get("downLast30days"))}
        if not e["eps_n"]:
            e["eps"] = e["eps_lo"] = e["eps_hi"] = e["eps_g"] = None
        if not e["rev_n"]:
            e["rev"] = e["rev_lo"] = e["rev_hi"] = e["rev_g"] = None
        if e["eps"] is not None or e["rev"] is not None:
            est[p] = e

    # 今期の売上高の前年比は、手元の決算（前期の実績）から計算し直す。
    # Yahoo の「前年の売上高」は通期でない値が入っていることがある（例：トヨタで +197% と出る）
    y = est.get("0y")
    if base and y and y.get("rev") and base[1] and base[1] > 0 and y.get("end") and base[0]:
        try:
            if int(y["end"][:4]) == int(base[0][:4]) + 1 and y["end"][5:7] == base[0][5:7]:
                y["rev_ya"] = base[1]
                y["rev_g"] = round((y["rev"] / base[1] - 1) * 100, 1)
        except ValueError:
            pass

    hist = []
    for h in (d.get("earningsHistory") or {}).get("history") or []:
        a, e = num(h.get("epsActual")), num(h.get("epsEstimate"))
        if a is None and e is None:
            continue
        sp = num(h.get("surprisePercent"))
        hist.append([fmtdate(h.get("quarter")), e, a, r(sp * 100, 1) if sp is not None else None])
    hist.sort(key=lambda x: x[0] or "")

    ud = []
    for h in ((d.get("upgradeDowngradeHistory") or {}).get("history") or [])[:20]:
        ts = h.get("epochGradeDate")
        if not ts:
            continue
        ud.append([datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d"), h.get("firm", ""),
                   h.get("fromGrade", ""), h.get("toGrade", ""), h.get("action", ""),
                   num(h.get("priorPriceTarget")) or None, num(h.get("currentPriceTarget")) or None])
    cut = date.today().toordinal() - 90
    ud90 = [u for u in ud if date.fromisoformat(u[0]).toordinal() >= cut]

    if tg["mean"] is None and not rec and not est:
        return None, None

    detail = {"px": px, "target": tg, "n": n_tg, "rec_mean": rec_mean, "rec": rec,
              "cur": cur_e or cur_r, "cur_rev": cur_r or cur_e, "est": est, "hist": hist, "ud": ud}

    y0, y1, q0 = est.get("0y", {}), est.get("+1y", {}), est.get("0q", {})

    def chg(e, i):   # EPS 予想が i 番目（1=7日前, 2=30日前, 4=90日前）からどれだけ変わったか
        t = e.get("t") or []
        return pct(t[0], t[i]) if len(t) > i and t[0] is not None and t[i] is not None and t[i] > 0 else None

    beats = [h for h in hist if h[3] is not None]
    row = {
        "目標株価_平均": r(tg["mean"]), "目標株価_中央値": r(tg["median"]),
        "目標株価_高値": r(tg["high"]), "目標株価_安値": r(tg["low"]),
        "上昇余地(%)": pct(tg["mean"], px) if tg["mean"] else None,
        "上昇余地_安値(%)": pct(tg["low"], px) if tg["low"] else None,
        "アナリスト人数": int(n_tg) if n_tg else None,
        "投資判断(1強い買い〜5強い売り)": rec_mean if rec_mean is not None else (score(rec0) if rec0 else None),
        "強い買い": rec0[1] if rec0 else None, "買い": rec0[2] if rec0 else None, "中立": rec0[3] if rec0 else None,
        "売り": rec0[4] if rec0 else None, "強い売り": rec0[5] if rec0 else None,
        "買い比率(%)": round((rec0[1] + rec0[2]) / sum(rec0[1:]) * 100, 1) if rec0 else None,
        "投資判断_3か月の変化": round(score(rec0) - score(rec3), 2) if rec0 and rec3 else None,
        "EPS予想通貨": cur_e or cur_r, "売上予想通貨": cur_r or cur_e,
        "今期決算期末": y0.get("end", ""),
        "今期EPS予想": r(y0.get("eps"), 3), "今期EPS成長率(%)": y0.get("eps_g"),
        "来期EPS予想": r(y1.get("eps"), 3), "来期EPS成長率(%)": y1.get("eps_g"),
        "今期売上予想": y0.get("rev"), "今期売上成長率(%)": y0.get("rev_g"),
        "来期売上予想": y1.get("rev"), "来期売上成長率(%)": y1.get("rev_g"),
        "今四半期EPS予想": r(q0.get("eps"), 3),
        "今期EPS予想人数": int(y0["eps_n"]) if y0.get("eps_n") else None,
        "今期EPS修正_30日(%)": chg(y0, 2), "今期EPS修正_90日(%)": chg(y0, 4),
        "来期EPS修正_30日(%)": chg(y1, 2), "来期EPS修正_90日(%)": chg(y1, 4),
        "今期_上方修正数_30日": int(y0["up30"]) if y0.get("up30") is not None else None,
        "今期_下方修正数_30日": int(y0["dn30"]) if y0.get("dn30") is not None else None,
        "サプライズ_直近(%)": beats[-1][3] if beats else None,
        "サプライズ_4期平均(%)": round(sum(h[3] for h in beats) / len(beats), 1) if beats else None,
        "予想超え回数(直近4期)": f"{sum(1 for h in beats if h[3] > 0)}/{len(beats)}" if beats else "",
        "格上げ数_90日": sum(1 for u in ud90 if u[4] == "up"),
        "格下げ数_90日": sum(1 for u in ud90 if u[4] == "down"),
        "直近の判断変更日": ud[0][0] if ud else "",
    }
    return detail, row


def rebuild(tickers):
    close, asof = latest_close()
    rows, details = [], {}
    base = {}
    try:
        with open(FUND / "fundamentals_latest.csv", encoding="utf-8-sig") as f:
            for x in csv.DictReader(f):
                try:
                    base[x["コード"]] = (x.get("決算期", ""), float(x.get("売上高") or 0))
                except ValueError:
                    pass
    except OSError:
        pass
    for t in tickers:
        p = RAW / f"{t['yahoo']}.json"
        if not p.exists():
            continue
        d = json.loads(p.read_text())
        if d.get("_notfound"):
            continue
        detail, row = parse(d, close.get(t["code"]), base.get(t["code"]))
        if not detail:
            continue
        got = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d")
        detail["fetched"] = got
        details[t["code"]] = detail
        rows.append({"コード": t["code"], "銘柄名": t["name"], "株価": close.get(t["code"]) or detail["px"],
                     **row, "取得日": got})
    if not rows:
        log("アナリスト予想のある銘柄がありません（CSV は更新しません）")
        return
    cols = list(rows[0].keys())
    with open(FUND / "analyst.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    (FUND / "analyst.json").write_text(json.dumps({"asof": asof, "data": details}, ensure_ascii=False,
                                                  separators=(",", ":")))
    n_t = sum(1 for x in rows if x["目標株価_平均"])
    n_e = sum(1 for x in rows if x["今期EPS予想"] is not None)
    log(f"CSV 再作成: 予想あり {len(rows)} 銘柄（目標株価 {n_t}・今期EPS予想 {n_e}）／株価 {asof}")


def snapshot():
    """取得した日の控え。過去の予想は Yahoo に残らないので手元にためる（公開しない）"""
    src = FUND / "analyst.csv"
    if not src.exists():
        return
    HIST.mkdir(exist_ok=True)
    with open(src, "rb") as f, gzip.open(HIST / f"{date.today().isoformat()}.csv.gz", "wb") as g:
        g.write(f.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-age-days", type=float, default=6)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--interval", type=float, default=0.3)
    ap.add_argument("--codes")
    ap.add_argument("--rebuild-only", action="store_true")
    a = ap.parse_args()
    tickers = load_tickers()
    fetched = 0
    if not a.rebuild_only:
        todo = tickers
        if a.codes:
            want = {c.strip().upper() + ".T" for c in a.codes.split(",")}
            todo = [t for t in tickers if t["yahoo"] in want]
            cutoff = time.time() + 1
        else:
            cutoff = time.time() - a.max_age_days * 86400
        todo = [t for t in todo if not (RAW / f"{t['yahoo']}.json").exists()
                or (RAW / f"{t['yahoo']}.json").stat().st_mtime < cutoff]
        log(f"取得: {len(todo)} 銘柄")
        pacer = Pacer(a.interval)
        fail = []

        def job(t):
            d = fetch(t["yahoo"], pacer)
            (RAW / f"{t['yahoo']}.json").write_text(json.dumps(d))

        with ThreadPoolExecutor(a.workers) as ex:
            futs = {ex.submit(job, t): t for t in todo}
            for f in as_completed(futs):
                try:
                    f.result()
                    fetched += 1
                except Exception:
                    fail.append(futs[f]["yahoo"])
                if (fetched + len(fail)) % 250 == 0:
                    log(f"  {fetched + len(fail)}/{len(todo)}（失敗 {len(fail)}）")
        log(f"取得完了: 成功 {fetched}・失敗 {len(fail)}" + (f"（{','.join(fail[:30])}）" if fail else ""))
    rebuild(tickers)
    if fetched:
        snapshot()


if __name__ == "__main__":
    sys.exit(main())
