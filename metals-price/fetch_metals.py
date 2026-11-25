#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_metals.py
====================
為替レート(USD/JPY)と 金・銀・プラチナ・パラジウム・銅 の価格(USD/oz)を、
無料・登録不要のAPIから取得し、metals_price_log.csv に1行ずつ追記していきます。
（この6項目のみ、無料で安定して自動取得できるAPIがあります。他の12品目は
 無料の安定した自動取得APIが見つかっていないため、対象外です。）

使い方:
    1) 実行:      python3 fetch_metals.py
       実行するたびに metals_price_log.csv の末尾に1行ずつ追記されます
       （ファイルが無ければ、ヘッダー付きで新規作成します）。
    2) 毎日18:00に自動実行するよう launchd に登録済みです
       （登録スクリプト: install_metals_schedule.sh）。
"""

import sys
import csv
import json
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

TROY_OZ_G = 31.1035
LB_G = 453.592
JST = timezone(timedelta(hours=9))

FRANKFURTER_URL = "https://api.frankfurter.dev/v2/rate/usd/jpy"
GOLD_API_URL = "https://api.gold-api.com/price/{symbol}"

# (CSV列名の接頭辞, 取得元シンボル, 追加の単位換算)
TARGETS = [
    ("Au_金", "XAU", None),
    ("Ag_銀", "XAG", None),
    ("Pt_プラチナ", "XPT", None),
    ("Pd_パラジウム", "XPD", None),
    ("Cu_銅", "HG", "lb_to_oz"),
]

HEADERS = {"User-Agent": "metals-price-csv-logger/1.0"}
CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "metals_price_log.csv")


def fetch_json(url, timeout=15):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_usd_jpy():
    data = fetch_json(FRANKFURTER_URL)
    return float(data["rate"])


def fetch_gold_api_price(symbol):
    data = fetch_json(GOLD_API_URL.format(symbol=symbol))
    return float(data["price"])


def build_header():
    header = ["timestamp_jst", "timestamp_utc", "USD_JPY"]
    for prefix, _symbol, _conv in TARGETS:
        header.append(f"{prefix}_USD_oz")
    for prefix, _symbol, _conv in TARGETS:
        header.append(f"{prefix}_JPY_g")
    return header


def main():
    print(f"[{datetime.now(JST):%Y-%m-%d %H:%M:%S JST}] データ取得を開始します...")

    # 1) 先にすべての値を取得する。途中で失敗したらCSVには一切書き込まない。
    try:
        usd_jpy = fetch_usd_jpy()
        print(f"  為替 USD/JPY = {usd_jpy}")

        prices_oz = {}
        for prefix, symbol, conv in TARGETS:
            raw = fetch_gold_api_price(symbol)
            if conv == "lb_to_oz":
                price_oz = raw * TROY_OZ_G / LB_G
                print(f"  {prefix}: {raw} USD/lb  ->  {price_oz:.4f} USD/oz")
            else:
                price_oz = raw
                print(f"  {prefix}: {price_oz} USD/oz")
            prices_oz[prefix] = price_oz
    except (urllib.error.URLError, urllib.error.HTTPError, KeyError, ValueError, TimeoutError) as e:
        sys.exit(f"データ取得に失敗しました。CSVは変更していません。\nエラー: {e}")

    # 2) 行を組み立てて追記する
    now_utc = datetime.now(timezone.utc)
    now_jst = now_utc.astimezone(JST)

    row = {
        "timestamp_jst": now_jst.strftime("%Y-%m-%d %H:%M:%S"),
        "timestamp_utc": now_utc.strftime("%Y-%m-%d %H:%M:%S"),
        "USD_JPY": round(usd_jpy, 4),
    }
    for prefix, _symbol, _conv in TARGETS:
        oz = prices_oz[prefix]
        row[f"{prefix}_USD_oz"] = round(oz, 6)
        row[f"{prefix}_JPY_g"] = round(oz * usd_jpy / TROY_OZ_G, 4)

    header = build_header()
    file_exists = os.path.isfile(CSV_PATH)
    with open(CSV_PATH, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

    print(f"[{datetime.now(JST):%Y-%m-%d %H:%M:%S JST}] 追記しました: {CSV_PATH}")


if __name__ == "__main__":
    main()
