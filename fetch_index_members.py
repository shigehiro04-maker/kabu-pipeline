#!/usr/bin/env python3
"""監視銘柄ページの初期設定の一覧表（指数の採用銘柄）を data/index_members.json に保存する（2026-11-16 追加）。
採用銘柄が入れ替わったら、次の更新で一覧表も自動で入れ替わる（利用者の指定）。すべて無料の公開情報。

東証版（~/株分析）
  日経225   fundamentals/nikkei225.csv の 日経225採用=1（日経225 入れ替え予想の処理が保守）
  TOPIX     JPX「TOPIX構成銘柄ウエイト一覧」 topixweight_j.csv（毎月更新）
  読売333   読売新聞「読売333 構成銘柄一覧」 https://www.yomiuri.co.jp/yomiuri333/component/
米国版（~/米国株分析）
  NYダウ・S&P500・NASDAQ100   ~/株分析/株価指数/data/us_constituents.json（fetch_us_breadth.py が7日ごとに取得）
  NASDAQ総合  NASDAQ に上場する普通株（data/charts/_summary.json の市場=NASDAQ。ETF・優先株などは対象外なので近似）
  SOX指数     Nasdaq 公式の構成銘柄（indexes.nasdaqomx.com の Weighting）
取得に失敗した指数は前回の銘柄を残す。make_watch.py が読む。
使い方:  python3 fetch_index_members.py
"""
from __future__ import annotations

import csv
import datetime
import io
import json
import re
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent
JP = Path.home() / "株分析"
OUT = BASE / "data" / "index_members.json"
US = BASE.name == "米国株分析"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}


def today():
    return datetime.date.today().isoformat()


# ---------------------------------------------------------------- 東証
def n225():
    with open(BASE / "fundamentals" / "nikkei225.csv", encoding="utf-8-sig") as fh:
        c = [r["コード"] for r in csv.DictReader(fh) if str(r.get("日経225採用", "")).strip() in ("1", "1.0", "True")]
    f = BASE / "fundamentals" / "nikkei225.csv"
    return c, datetime.date.fromtimestamp(f.stat().st_mtime).isoformat()


def topix():
    r = requests.get("https://www.jpx.co.jp/automation/markets/indices/topix/files/topixweight_j.csv", headers=UA, timeout=60)
    r.raise_for_status()
    rows = list(csv.reader(io.StringIO(r.content.decode("cp932", "ignore"))))
    c, d = [], ""
    for x in rows[1:]:
        if len(x) >= 3 and re.fullmatch(r"\d{3}[0-9A-Z]", x[2].strip()):
            c.append(x[2].strip()); d = d or x[0].strip()
    asof = f"{d[:4]}-{d[4:6]}-{d[6:8]}" if re.fullmatch(r"\d{8}", d) else today()
    return c, asof


def y333():
    r = requests.get("https://www.yomiuri.co.jp/yomiuri333/component/", headers=UA, timeout=60)
    r.raise_for_status()
    c = re.findall(r'yomiuri333-component__code">\s*(\d{3}[0-9A-Z])\s*<', r.text)
    m = re.search(r"(\d{4})\.(\d{1,2})\.(\d{1,2})\s*時点", r.text)  # ページの「2026.11.13 時点」
    asof = f"{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}" if m else today()
    return list(dict.fromkeys(c)), asof


# ---------------------------------------------------------------- 米国
def us_cons(key):
    d = json.load(open(JP / "株価指数" / "data" / "us_constituents.json", encoding="utf-8"))
    return [x.replace("-", ".") for x in d[key]], d.get("asof", "")


def nasdaq():
    rows = json.load(open(BASE / "data" / "charts" / "_summary.json", encoding="utf-8"))
    return sorted(r["code"] for r in rows if r.get("mk") == "NASDAQ"), max((r.get("date", "") for r in rows), default="")


def sox():
    d = datetime.date.today()
    for _ in range(7):  # 直近の営業日（休日は空なので前の日へ）
        d -= datetime.timedelta(days=1)
        if d.weekday() >= 5:
            continue
        r = requests.post("https://indexes.nasdaqomx.com/Index/WeightingData", headers={**UA, "X-Requested-With": "XMLHttpRequest"},
                          data={"id": "SOX", "tradeDate": d.isoformat() + "T00:00:00.000", "timeOfDay": "SOD"}, timeout=60)
        r.raise_for_status()
        a = r.json().get("aaData") or []
        if a:
            return [x["Symbol"].replace("-", ".") for x in a], d.isoformat()
    raise RuntimeError("直近7日の構成銘柄が取れません")


SPEC = ([("dow", "NYダウ", lambda: us_cons("dow")), ("nasdaq", "NASDAQ総合", nasdaq),
         ("ndx", "NASDAQ100", lambda: us_cons("nasdaq100")), ("sp500", "S&P500", lambda: us_cons("sp500")),
         ("sox", "SOX指数", sox)]
        if US else
        [("n225", "日経225", n225), ("topix", "TOPIX", topix), ("y333", "読売333", y333)])
MIN = {"n225": 200, "topix": 1000, "y333": 300, "dow": 30, "nasdaq": 1000, "ndx": 90, "sp500": 450, "sox": 25}


def main():
    old = {}
    if OUT.exists():
        try:
            old = {x["k"]: x for x in json.load(open(OUT, encoding="utf-8"))["lists"]}
        except Exception:
            pass
    lists, msg = [], []
    for k, t, fn in SPEC:
        try:
            c, asof = fn()
            if len(c) < MIN[k]:
                raise RuntimeError(f"{len(c)}銘柄しかありません（ページの形が変わった可能性）")
            prev = set(old.get(k, {}).get("c", []))
            add, rm = [x for x in c if x not in prev], [x for x in prev if x not in c]
            lists.append({"k": k, "t": t, "c": c, "asof": asof})
            msg.append(f"{t} {len(c)}" + (f"（入替 +{len(add)} −{len(rm)}）" if prev and (add or rm) else ""))
        except Exception as ex:
            print(f"{t}: 取得できませんでした（前回の銘柄を使います）: {ex}")
            if k in old:
                lists.append(old[k])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    json.dump({"built": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "lists": lists},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print("指数の採用銘柄: " + "・".join(msg) + f" → {OUT}")


if __name__ == "__main__":
    main()
