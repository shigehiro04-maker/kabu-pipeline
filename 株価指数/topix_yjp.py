#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TOPIX そのものの日足を Yahoo!ファイナンス（日本）から取る（無料・登録なし。2026-11-25 作成）

それまでの TOPIX は ETF（1306.T）の終値を世界統計データの月末値で換算していたため、月末値の公表が
遅れると数か月分ずれがたまっていた（2026-11-25 に約1%）。Yahoo!ファイナンス（日本）の 998405.T
（TOPIX）の時系列ページと現在値ページから、指数そのものの値を取る。

  data/topix_yjp.csv（Date,Open,High,Low,Close）にためる。初回は 2009年からさかのぼって取る
  （1か月ずつ、1ページ20日分。全部で数分）。2回目からは直近2か月の取り直し＋当日分だけ（数秒）。
  当日分：時系列ページは夕方まで当日が載らないので、現在値ページの値（15:30 の終値）を使う。
  現在値ページの「前日比」から逆算した前日終値が時系列の最新の終値と合うときだけ当日分として足す
  （祝日に前の日の値を当日として足さないため）。
  ページの作りが変わって取れなくなったら例外を出す（呼び出し側は ETF 換算にフォールバックする）。

  手動: ~/株分析/.venv/bin/python topix_yjp.py [--outdir data]
"""
from __future__ import annotations
import datetime as dt, re, sys, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

URL = "https://finance.yahoo.co.jp/quote/998405.T"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"}
JST = ZoneInfo("Asia/Tokyo")
START = dt.date(2009, 1, 1)
ROW = re.compile(r'<th[^>]*>(\d{4}/\d{1,2}/\d{1,2})</th>(.*?)</tr>', re.S)
NUM = re.compile(r'_StyledNumber__value[^>]*>([-\d,\.]+)<')
num = lambda s: float(s.replace(",", ""))


def get(url, **params):
    for i in range(3):
        try:
            r = requests.get(url, headers=UA, params=params, timeout=30)
            r.raise_for_status()
            return r.text
        except Exception:
            if i == 2:
                raise
            time.sleep(3 + 3 * i)


def history(frm: dt.date | None = None, to: dt.date | None = None, pages: int = 30) -> dict:
    """時系列ページ（新しい順・1ページ20日分）を最後まで。{日付: (O,H,L,C)}"""
    out, page = {}, 1
    while page <= pages:
        p = {"page": page}
        if frm:
            p.update({"from": frm.strftime("%Y%m%d"), "to": to.strftime("%Y%m%d"), "timeFrame": "d"})
        rows = []
        for d, rest in ROW.findall(get(URL + "/history", **p)):
            v = NUM.findall(rest)
            if len(v) >= 4:
                rows.append((dt.date(*map(int, d.split("/"))), tuple(num(x) for x in v[:4])))
        new = [r for r in rows if r[0] not in out]
        if not new:
            break
        out.update(new)
        if len(rows) < 20:
            break
        page += 1
        time.sleep(0.7)
    return out


def quote() -> dict:
    """現在値ページ：現在値・前日比・始値・高値・安値と値の時刻"""
    t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", get(URL)))
    m = re.search(r"([\d,]+\.\d+) 前日比 ([-+]?[\d,]+\.\d+) \( ?[-+]?[\d\.]+ ?% ?\)\D{0,30}?(\d{1,2}:\d{2})", t)
    if not m:
        raise ValueError("Yahoo!ファイナンス：現在値が見つかりません（ページの作りが変わった可能性）")
    q = {"price": num(m.group(1)), "chg": num(m.group(2)), "time": m.group(3)}
    for k, lab in (("open", "始値"), ("high", "高値"), ("low", "安値")):
        mm = re.search(lab + r" 用語 ([\d,]+\.\d+)", t)
        q[k] = num(mm.group(1)) if mm else None
    return q


def update(path: Path, log=print) -> pd.DataFrame:
    try:
        old = pd.read_csv(path, parse_dates=["Date"]).set_index("Date")
        have = {d.date(): tuple(r) for d, r in old[["Open", "High", "Low", "Close"]].iterrows()}
    except FileNotFoundError:
        have = {}
    today = dt.datetime.now(JST).date()
    # 足りない月（初回は2009年から）＋直近2か月は取り直す
    months, m = [], dt.date(START.year, START.month, 1)
    got = {(d.year, d.month) for d in have}
    recent = {(today.year, today.month), ((today.replace(day=1) - dt.timedelta(days=1)).year, (today.replace(day=1) - dt.timedelta(days=1)).month)}
    while m <= today:
        if (m.year, m.month) not in got or (m.year, m.month) in recent:
            months.append(m)
        m = (m.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    if len(months) > 3:
        log(f"  TOPIX（Yahoo!ファイナンス）: {len(months)}か月分を取得します（初回は数分）")
    n0 = len(have)
    if len(months) <= 2:
        have.update(history(pages=1))                # 直近20日分（1ページ）
    else:
        for i, m in enumerate(months):
            end = (m.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
            have.update(history(m, end))
            time.sleep(0.5)
    if not have:
        raise ValueError("Yahoo!ファイナンス：TOPIX の時系列が取れません")
    # 当日分（引け後に時系列へ載る前）
    try:
        q = quote()
        last = max(have)
        prev = round(q["price"] - q["chg"], 2)
        now = dt.datetime.now(JST)
        if (last < today and now.weekday() < 5 and now.hour * 60 + now.minute >= 15 * 60 + 30
                and q["time"] == "15:30" and abs(prev - have[last][3]) < 0.015):
            have[today] = (q["open"] or q["price"], q["high"] or q["price"], q["low"] or q["price"], q["price"])
            log(f"  TOPIX 当日分（現在値ページ）: {today} {q['price']:,.2f}（前日比 {q['chg']:+.2f}）")
    except Exception as ex:
        log(f"  TOPIX 当日分: 取れません（{ex}）")
    df = pd.DataFrame([(pd.Timestamp(d), *v) for d, v in sorted(have.items())],
                      columns=["Date", "Open", "High", "Low", "Close"]).set_index("Date")
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path)
    log(f"  TOPIX（Yahoo!ファイナンス）: {df.index[0].date()} 〜 {df.index[-1].date()}（{len(df)}日、+{len(df) - n0}）")
    return df


if __name__ == "__main__":
    out = Path(sys.argv[sys.argv.index("--outdir") + 1]) if "--outdir" in sys.argv else Path(__file__).resolve().parent / "data"
    update(out / "topix_yjp.csv")
