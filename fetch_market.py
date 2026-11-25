#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
マーケット概況に使う指数・金利・為替・商品の日足を取る（Yahoo Finance・無料）。

  出力: data/market/<キー>.csv（date,open,high,low,close,volume）
        取れた全期間を手元のCSVと合わせて保存する（指数は最高値の判定に全期間を使う）
  東証版（~/株分析）。run_daily.sh の 3b-4a（ヒートマップの後・トップ画面の前）から呼ぶ。十数秒。
  最後に fetch_news.py（ニュースの見出し）も呼ぶ。
  失敗した系列は前回のCSVをそのまま残す（概況は手元にある日付までで作る）。

  手動: ~/株分析/.venv/bin/python ~/株分析/fetch_market.py
"""
import csv, sys, time
from pathlib import Path

BASE = Path(__file__).resolve().parent
OUT = BASE / "data" / "market"

# キー: (Yahoo のシンボル, 取得期間)
SERIES = {
    "dow":    ("^DJI", "max"),      # NYダウ
    "sp500":  ("^GSPC", "max"),     # S&P500
    "nasdaq": ("^IXIC", "max"),     # NASDAQ総合
    "ndx":    ("^NDX", "max"),      # NASDAQ100
    "rut":    ("^RUT", "max"),      # ラッセル2000（小型株）
    "sox":    ("^SOX", "max"),      # フィラデルフィア半導体株指数
    "vix":    ("^VIX", "5y"),       # VIX（恐怖指数）
    "us10y":  ("^TNX", "5y"),       # 米10年国債利回り（%）
    "us5y":   ("^FVX", "5y"),       # 米5年国債利回り（%）
    "usdjpy": ("JPY=X", "5y"),      # ドル円
    "dxy":    ("DX-Y.NYB", "5y"),   # ドル指数
    "wti":    ("CL=F", "5y"),       # WTI原油先物
    "gold":   ("GC=F", "5y"),       # 金先物
    "btc":    ("BTC-USD", "5y"),    # ビットコイン
}

# 東証版：日経平均・TOPIX・日経平均VI は 株価指数/data/ にあるので、ここでは海外の指数・金利・為替・商品だけを取る
SERIES = {k: (v[0], "5y") for k, v in SERIES.items()
          if k in ("dow", "sp500", "nasdaq", "sox", "vix", "us10y", "usdjpy", "wti", "gold", "btc")}


def read(p):
    rows = {}
    try:
        with open(p, encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                rows[r["date"]] = r
    except FileNotFoundError:
        pass
    return rows


def fetch(sym, period):
    import yfinance as yf
    last = None
    for i in range(3):
        try:
            df = yf.Ticker(sym).history(period=period, interval="1d", auto_adjust=False)
            if df is not None and len(df) > 5:
                return df
        except Exception as ex:      # 一時的な失敗は少し待って取り直す
            last = ex
        time.sleep(2 + 3 * i)
    raise RuntimeError(f"{sym}: 取得できません（{last}）")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    bad = 0
    for key, (sym, period) in SERIES.items():
        p = OUT / f"{key}.csv"
        old = read(p)
        try:
            df = fetch(sym, period if not old else ("max" if period == "max" and len(old) < 300 else "3mo"))
        except Exception as ex:
            print(f"{key}: 失敗 {ex}")
            bad += 1
            continue
        n0 = len(old)
        for ts, r in df.iterrows():
            c = r.get("Close")
            if c is None or c != c or c <= 0:
                continue
            d = ts.strftime("%Y-%m-%d")
            f = lambda v: "" if v is None or v != v else f"{float(v):.4f}"
            old[d] = {"date": d, "open": f(r.get("Open")), "high": f(r.get("High")), "low": f(r.get("Low")),
                      "close": f(c), "volume": f(r.get("Volume"))}
        with open(p, "w", encoding="utf-8", newline="") as fo:
            w = csv.DictWriter(fo, fieldnames=["date", "open", "high", "low", "close", "volume"])
            w.writeheader()
            for d in sorted(old):
                w.writerow(old[d])
        last = max(old)
        print(f"{key}（{sym}）: {len(old):,}日分（+{len(old) - n0}）最終 {last} {old[last]['close']}")
    try:      # 概況に添えるニュースの見出し（Google ニュース RSS）。失敗しても前回までの見出しで続ける
        import fetch_news
        fetch_news.main()
    except Exception as ex:
        print(f"ニュースの見出し: 失敗 {ex}")
    return 1 if bad == len(SERIES) else 0


if __name__ == "__main__":
    sys.exit(main())
