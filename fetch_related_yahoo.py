#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同業他社・関連銘柄のための Yahoo Finance データ（無料・登録なし）を取る。東証版・米国版で共通。

  東証（--market jp）：quoteSummary assetProfile の業種（約145分類）・セクター・従業員数
                       ＋ recommendationsbysymbol（Yahoo の「よく一緒に見られている銘柄」上位5）
  米国（--market us）：recommendationsbysymbol だけ（業種は us_fetch_profile.py で取得済み）

出力  <各フォルダ>/fundamentals/yahoo_related.json
      {コード: {"ind": 業種, "sec": セクター, "emp": 従業員数, "rec": [[Yahooコード, 点数], ...], "d": 取得日}}

使い方
  ~/株分析/.venv/bin/python ~/株分析/fetch_related_yahoo.py --market jp           # 7日より古い銘柄だけ
  ~/株分析/.venv/bin/python ~/株分析/fetch_related_yahoo.py --market us --max-age-days 0
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path.home() / "米国株分析"))
import us_fetch_profile as up  # noqa: E402  （cookie・crumb・間隔調整を流用）

DIRS = {"jp": Path.home() / "株分析", "us": Path.home() / "米国株分析"}
REC = "https://query2.finance.yahoo.com/v6/finance/recommendationsbysymbol/{sym}"
QS = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/{sym}"
LOCK = threading.Lock()


def get(url, pacer, params=None):
    gen = None
    last = None
    for attempt in range(5):
        pacer.wait()
        try:
            s, crumb, gen = up.session(gen if attempt and last == "401" else None)
            p = dict(params or {})
            if p:
                p["crumb"] = crumb
            r = s.get(url, params=p or None, timeout=25)
            if r.status_code == 429:
                pacer.slow(); last = "429"; continue
            if r.status_code == 404:
                return None
            if r.status_code == 401:
                last = "401"; continue
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            last = str(e)
            import time, random
            time.sleep(min(2 ** attempt, 10) + random.random())
    raise RuntimeError(str(last))


def symbols(market):
    base = DIRS[market]
    out = {}
    with open(base / "fundamentals" / "fundamentals_latest.csv", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            c = r["コード"]
            out[c] = f"{c}.T" if market == "jp" else c.replace(".", "-")
    if market == "us":
        p = base / "tickers" / "us_sectors.csv"
        if p.exists():
            with open(p, encoding="utf-8-sig") as f:
                for r in csv.DictReader(f):
                    if r.get("code") in out and r.get("yahoo"):
                        out[r["code"]] = r["yahoo"]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", choices=["jp", "us"], required=True)
    ap.add_argument("--max-age-days", type=int, default=7)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--interval", type=float, default=0.25)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    out_p = DIRS[a.market] / "fundamentals" / "yahoo_related.json"
    store = json.loads(out_p.read_text(encoding="utf-8")) if out_p.exists() else {}
    syms = symbols(a.market)
    cut = (date.today() - timedelta(days=a.max_age_days)).isoformat()
    todo = [c for c in syms if store.get(c, {}).get("d", "") < cut or a.max_age_days == 0]
    if a.limit:
        todo = todo[:a.limit]
    up.log(f"{a.market}: 対象 {len(todo)} / {len(syms)} 銘柄")
    pacer = up.Pacer(a.interval)
    cnt = {"ok": 0, "ng": 0}

    def one(c):
        sym = syms[c]
        try:
            x = {"d": date.today().isoformat()}
            js = get(REC.format(sym=sym), pacer)
            res = ((js or {}).get("finance") or {}).get("result") or []
            x["rec"] = [[r["symbol"], round(r.get("score") or 0, 4)]
                        for r in (res[0].get("recommendedSymbols") if res else []) or []]
            if a.market == "jp":
                js = get(QS.format(sym=sym), pacer, {"modules": "assetProfile"})
                res = ((js or {}).get("quoteSummary") or {}).get("result") or []
                ap_ = (res[0].get("assetProfile") if res else None) or {}
                x.update(ind=ap_.get("industry"), sec=ap_.get("sector"), emp=ap_.get("fullTimeEmployees"))
            with LOCK:
                store[c] = x
                cnt["ok"] += 1
        except Exception as e:  # noqa: BLE001
            with LOCK:
                cnt["ng"] += 1
            up.log(f"失敗 {c}: {str(e)[:100]}")
        with LOCK:
            n = cnt["ok"] + cnt["ng"]
            if n % 300 == 0:
                out_p.write_text(json.dumps(store, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
                up.log(f"  {n} / {len(todo)}")

    with ThreadPoolExecutor(a.workers) as ex:
        list(ex.map(one, todo))
    out_p.write_text(json.dumps(store, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    up.log(f"{a.market}: 取得 {cnt['ok']} / 失敗 {cnt['ng']} / 保有 {len(store)} → {out_p}")


if __name__ == "__main__":
    main()
