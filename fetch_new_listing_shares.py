#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
上場して間もない銘柄の「いまの発行済株式数」を Yahoo の銘柄情報から取る。

Yahoo の決算データ（fetch_fundamentals.py が使う年次の貸借対照表）は、上場前の決算期の
株数しか持っていないか、株数そのものが空のことが多い。上場時の株式分割や公募増資が
反映されないため、時価総額・PER・PBR・理論株価が空欄になったり、桁違いになったりする
（例：621A オーディオストックは上場前の10万株のまま → 時価総額1.3億円・EPS 4,398円）。

そこで、株価の履歴が1年未満の銘柄（＝最近の新規上場）だけ、Yahoo の銘柄情報の
sharesOutstanding を取り、fundamentals/shares_quote.csv に保存する。
fetch_fundamentals.py は、決算データの株数が空か、これと2割以上違う銘柄でこちらを使う。

run_fundamentals.sh から毎日呼ばれる。1銘柄1秒ほど、取得から7日以内の銘柄は取り直さない。

使い方:
    ./.venv/bin/python fetch_new_listing_shares.py            # 対象銘柄を更新
    ./.venv/bin/python fetch_new_listing_shares.py --codes 621A,622A
"""
import argparse
import csv
import datetime as dt
import os
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
TICKERS = os.path.join(BASE, "tickers", "tse_tickers.csv")
PRICES = os.path.join(BASE, "data", "prices")
OUT = os.path.join(BASE, "fundamentals", "shares_quote.csv")

RECENT_DAYS = 400    # 株価の履歴がこれより短い銘柄を「新規上場」とみなす
REFRESH_DAYS = 7


def first_date(code):
    p = os.path.join(PRICES, f"{code}.csv")
    try:
        with open(p, encoding="utf-8") as f:
            next(f)
            return f.readline().split(",")[0]
    except Exception:
        return None


def load_out():
    if not os.path.exists(OUT):
        return {}
    with open(OUT, encoding="utf-8-sig") as f:
        return {r["code"]: r for r in csv.DictReader(f)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", help="カンマ区切りで銘柄を指定（期間の条件を無視）")
    a = ap.parse_args()

    today = dt.date.today()
    with open(TICKERS, encoding="utf-8-sig") as f:
        listed = {r["code"]: r["name"] for r in csv.DictReader(f)}

    if a.codes:
        targets = [c.strip().upper() for c in a.codes.split(",") if c.strip()]
    else:
        cutoff = (today - dt.timedelta(days=RECENT_DAYS)).isoformat()
        targets = [c for c in listed if (first_date(c) or "0000") >= cutoff]

    have = load_out()
    # 上場廃止・期間外になった銘柄は残さない（--codes 指定時は既存を保持）
    rows = {c: r for c, r in have.items() if c in listed and (a.codes or c in targets)}

    due = [c for c in targets
           if c not in rows
           or (today - dt.date.fromisoformat(rows[c]["fetched"])).days >= REFRESH_DAYS]
    print(f"新規上場（株価履歴{RECENT_DAYS}日未満）: {len(targets)} 銘柄／取得 {len(due)} 銘柄")

    if due:
        import yfinance as yf
        for c in due:
            sh = None
            try:
                info = yf.Ticker(f"{c}.T").info or {}
                sh = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
            except Exception as e:
                print(f"  {c}: 取得失敗 {type(e).__name__}: {e}")
            if sh:
                rows[c] = {"code": c, "name": listed.get(c, ""), "shares": int(sh),
                           "first_price": first_date(c) or "", "fetched": today.isoformat()}
                print(f"  {c} {listed.get(c, '')}: {int(sh):,} 株")
            else:
                print(f"  {c} {listed.get(c, '')}: 株数なし")
            time.sleep(1.0)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["code", "name", "shares", "first_price", "fetched"])
        w.writeheader()
        w.writerows(sorted(rows.values(), key=lambda r: r["code"]))
    print(f"保存: {OUT}（{len(rows)} 銘柄）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
