#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
米国株の銘柄情報を Yahoo Finance の quoteSummary（無料）から1銘柄1リクエストでまとめて取る。
東証版の fetch_sectors.py（業種）・fetch_company_profile.py（会社概要）・fetch_shareholders.py（大株主）・
shares_quote（いまの株数）・決算発表予定日 にあたるデータをここで揃える。

取得するモジュール
  quoteType            種別（EQUITY 以外＝ファンド等は対象から外す）
  assetProfile         業種（セクター11分類・業種約145分類）、国、従業員数、公式サイト、事業概要（英文）
  defaultKeyStatistics いまの発行済株式数・浮動株・空売り残高（月2回 FINRA 公表値）
  majorHoldersBreakdown 内部者・機関投資家の保有比率
  institutionOwnership 機関投資家の上位10社（13F）
  calendarEvents       次回決算発表予定日・配当権利落ち日

出力
  tickers/us_sectors.csv            code,yahoo,sector,industry,country,quote_type
  tickers/us_excluded.csv           EQUITY 以外とクローズドエンド型ファンド（CEF）で外した銘柄（code,name,quote_type）
  fundamentals/company_profile.csv  コード,会社URL,事業概要,事業概要(英文),国,従業員数,取得日
  fundamentals/shares_quote.csv     コード,発行済株式数,浮動株数,空売り残高,空売り残高_前月,空売り比率(浮動株%),空売り日数,空売り基準日,内部者保有(%),機関保有(%)
  fundamentals/shareholders.json    {コード: {asof, insider, institution, holders:[[名称,株式数,割合%,基準日],...]}}
  fundamentals/shareholders.csv     1行 = 銘柄 × 機関投資家
  fundamentals/earnings_calendar.csv コード,銘柄名,次回決算日,次回決算日_幅,配当権利落ち日,配当支払日
  fundamentals/raw_profile/<yahoo>.json  生レスポンス（キャッシュ）

使い方
  python us_fetch_profile.py                 # 7日以上前に取った銘柄だけ取り直す（初回は全銘柄・約15分）
  python us_fetch_profile.py --max-age-days 1
  python us_fetch_profile.py --rebuild-only  # 通信せずキャッシュからCSVを作り直す
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
TICKERS = BASE / "tickers" / "us_tickers.csv"
SECTORS = BASE / "tickers" / "us_sectors.csv"
EXCLUDED = BASE / "tickers" / "us_excluded.csv"
FUND = BASE / "fundamentals"
RAW = FUND / "raw_profile"
RAW.mkdir(parents=True, exist_ok=True)

API = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/{sym}"
MODULES = ("quoteType,assetProfile,defaultKeyStatistics,majorHoldersBreakdown,"
           "institutionOwnership,calendarEvents")

import re
CEF = re.compile(r"\b(funds?|trust|municipals?|muni|income|dividend|portfolio|premium|yield|closed[- ]end)\b"
                 r"|\binvestors$", re.I)
CEF_NOT = re.compile(r"northern trust corporation|trust company|bancorp|bank", re.I)

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
    with open(TICKERS, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def rebuild(tickers):
    today = date.today().isoformat()
    sectors, prof, shares, cal, excluded, sh_csv = [], [], [], [], [], []
    holders = {}
    keep = []
    old_ja = {}
    pp = FUND / "company_profile.csv"
    if pp.exists():
        with open(pp, encoding="utf-8-sig") as f:
            old_ja = {r["コード"]: r.get("事業概要", "") for r in csv.DictReader(f)}
    for t in tickers:
        p = RAW / f"{t['yahoo']}.json"
        if not p.exists():
            keep.append(t)
            continue
        d = json.loads(p.read_text())
        if d.get("_notfound"):
            keep.append(t)
            continue
        qt = (d.get("quoteType") or {}).get("quoteType") or ""
        if qt and qt != "EQUITY":
            excluded.append({"code": t["code"], "name": t["name"], "quote_type": qt})
            continue
        ap = d.get("assetProfile") or {}
        # クローズドエンド型ファンド（東証版で除外している投資信託にあたる）は Yahoo では EQUITY 扱いなので名前で外す
        if ap.get("industry") == "Asset Management" and CEF.search(t["name"]) and not CEF_NOT.search(t["name"]):
            excluded.append({"code": t["code"], "name": t["name"], "quote_type": "CEF"})
            continue
        keep.append(t)
        ks = d.get("defaultKeyStatistics") or {}
        mh = d.get("majorHoldersBreakdown") or {}
        io_ = (d.get("institutionOwnership") or {}).get("ownershipList") or []
        ce = d.get("calendarEvents") or {}
        sectors.append({"code": t["code"], "yahoo": t["yahoo"], "sector": ap.get("sector", ""),
                        "industry": ap.get("industry", ""), "country": ap.get("country", ""),
                        "quote_type": qt})
        prof.append({"コード": t["code"], "会社URL": ap.get("website", ""),
                     "事業概要": old_ja.get(t["code"], ""),
                     "事業概要(英文)": (ap.get("longBusinessSummary") or "").replace("\n", " "),
                     "国": ap.get("country", ""), "従業員数": ap.get("fullTimeEmployees", ""),
                     "取得日": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d")})
        ins, inst = raw(mh.get("insidersPercentHeld")), raw(mh.get("institutionsPercentHeld"))
        spf = raw(ks.get("shortPercentOfFloat"))
        shares.append({"コード": t["code"], "発行済株式数": raw(ks.get("sharesOutstanding")) or "",
                       "発行済株式数(全種類)": raw(ks.get("impliedSharesOutstanding")) or "",
                       "浮動株数": raw(ks.get("floatShares")) or "",
                       "空売り残高": raw(ks.get("sharesShort")) or "",
                       "空売り残高_前月": raw(ks.get("sharesShortPriorMonth")) or "",
                       "空売り比率(浮動株%)": round(spf * 100, 2) if isinstance(spf, (int, float)) else "",
                       "空売り日数": raw(ks.get("shortRatio")) or "",
                       "空売り基準日": fmtdate(ks.get("dateShortInterest")),
                       "内部者保有(%)": round(ins * 100, 2) if isinstance(ins, (int, float)) else "",
                       "機関保有(%)": round(inst * 100, 2) if isinstance(inst, (int, float)) else "",
                       "最終分割日": fmtdate(ks.get("lastSplitDate")),
                       "最終分割比": ks.get("lastSplitFactor") or ""})
        hl = []
        for h in io_[:10]:
            row = [h.get("organization", ""), raw(h.get("position")),
                   round(raw(h.get("pctHeld")) * 100, 2) if isinstance(raw(h.get("pctHeld")), (int, float)) else None,
                   fmtdate(h.get("reportDate"))]
            hl.append(row)
            sh_csv.append({"コード": t["code"], "銘柄名": t["name"], "株主名": row[0], "株式数": row[1],
                           "保有比率(%)": row[2], "基準日": row[3]})
        holders[t["code"]] = {"asof": max((h[3] for h in hl), default=""),
                              "insider": shares[-1]["内部者保有(%)"], "institution": shares[-1]["機関保有(%)"],
                              "holders": hl}
        er = ce.get("earnings") or {}
        eds = [fmtdate(x) for x in (er.get("earningsDate") or [])]
        cal.append({"コード": t["code"], "銘柄名": t["name"], "次回決算日": eds[0] if eds else "",
                    "次回決算日_幅": eds[-1] if len(eds) > 1 else "",
                    "配当権利落ち日": fmtdate(ce.get("exDividendDate")),
                    "配当支払日": fmtdate(ce.get("dividendDate"))})

    def wcsv(path, rows, cols):
        with open(path, "w", newline="", encoding="utf-8-sig" if path.parent == FUND else "utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)

    wcsv(SECTORS, sectors, ["code", "yahoo", "sector", "industry", "country", "quote_type"])
    wcsv(FUND / "company_profile.csv", prof, ["コード", "会社URL", "事業概要", "事業概要(英文)", "国", "従業員数", "取得日"])
    if shares:
        wcsv(FUND / "shares_quote.csv", shares, list(shares[0].keys()))
    wcsv(FUND / "shareholders.csv", sh_csv, ["コード", "銘柄名", "株主名", "株式数", "保有比率(%)", "基準日"])
    (FUND / "shareholders.json").write_text(json.dumps(holders, ensure_ascii=False))
    wcsv(FUND / "earnings_calendar.csv", sorted(cal, key=lambda r: r["次回決算日"] or "9"),
         ["コード", "銘柄名", "次回決算日", "次回決算日_幅", "配当権利落ち日", "配当支払日"])

    if excluded:
        old = {}
        if EXCLUDED.exists():
            with open(EXCLUDED, encoding="utf-8") as f:
                old = {r["code"]: r for r in csv.DictReader(f)}
        for e in excluded:
            old[e["code"]] = e
        wcsv(EXCLUDED, list(old.values()), ["code", "name", "quote_type"])
        with open(TICKERS, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["code", "yahoo", "name", "market", "adr"])
            w.writeheader()
            w.writerows(keep)
        log(f"EQUITY 以外の {len(excluded)} 銘柄を対象から外しました（tickers/us_excluded.csv）")
    log(f"CSV 再作成: 業種 {len(sectors)}・大株主 {len(holders)}・決算予定 {sum(1 for c in cal if c['次回決算日'])}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-age-days", type=float, default=7)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--interval", type=float, default=0.3)
    ap.add_argument("--codes")
    ap.add_argument("--rebuild-only", action="store_true")
    a = ap.parse_args()
    tickers = load_tickers()
    if not a.rebuild_only:
        todo = tickers
        if a.codes:
            want = {c.strip().upper().replace(".", "-") for c in a.codes.split(",")}
            todo = [t for t in tickers if t["yahoo"] in want]
        cutoff = time.time() - a.max_age_days * 86400
        todo = [t for t in todo if not (RAW / f"{t['yahoo']}.json").exists()
                or (RAW / f"{t['yahoo']}.json").stat().st_mtime < cutoff]
        log(f"取得: {len(todo)} 銘柄")
        pacer = Pacer(a.interval)
        done, fail = 0, []

        def job(t):
            d = fetch(t["yahoo"], pacer)
            (RAW / f"{t['yahoo']}.json").write_text(json.dumps(d))

        with ThreadPoolExecutor(a.workers) as ex:
            futs = {ex.submit(job, t): t for t in todo}
            for f in as_completed(futs):
                try:
                    f.result()
                    done += 1
                except Exception as e:
                    fail.append(futs[f]["yahoo"])
                if (done + len(fail)) % 250 == 0:
                    log(f"  {done + len(fail)}/{len(todo)}（失敗 {len(fail)}）")
        log(f"取得完了: 成功 {done}・失敗 {len(fail)}" + (f"（{','.join(fail[:30])}）" if fail else ""))
    rebuild(tickers)


if __name__ == "__main__":
    sys.exit(main())
