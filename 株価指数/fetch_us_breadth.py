#!/usr/bin/env python3
"""米国の騰落レシオ（ダウ平均・S&P500・NASDAQ100）を、各指数の構成銘柄の株価から計算する。

  python 株価指数/fetch_us_breadth.py            # 株価指数/data/us_breadth.json を更新

  ・構成銘柄の一覧は S&P500＝Wikipedia、NASDAQ100＝Nasdaq社の公開API（どちらも無料・登録不要）から取り、
    data/us_constituents.json に保存（7日ごとに取り直し。失敗時は前回分を使う）。
    ダウ平均の30銘柄は無料で機械的に取れる一覧がないため、下の DOW30 を使う（入れ替えがあったら書き換える）
  ・株価は Yahoo Finance（yfinance・無料）。初回は約5年分、2回目以降は直近だけ取り足して data/us_closes.csv に蓄積
  ・騰落レシオ＝直近25日（10日）の値上がり銘柄数の合計 ÷ 値下がり銘柄数の合計 × 100
  ・「いまの構成銘柄」でさかのぼって数えるので、古い期間ほど目安（入れ替えで外れた銘柄は入らない）
"""
from __future__ import annotations

import io
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
CONS = DATA / "us_constituents.json"
CLOSES = DATA / "us_closes.csv"
OUT = DATA / "us_breadth.json"
WIKI = {"dow": None, "sp500": None, "nasdaq100": None}     # 出力する順
# ダウ平均の構成30銘柄（2024-11 にNVDA・SHWが入った時点の構成。入れ替えがあったらここを直す）
DOW30 = ["AAPL", "AMGN", "AMZN", "AXP", "BA", "CAT", "CRM", "CSCO", "CVX", "DIS", "GS", "HD", "HON", "IBM", "JNJ",
         "JPM", "KO", "MCD", "MMM", "MRK", "MSFT", "NKE", "NVDA", "PG", "SHW", "TRV", "UNH", "V", "VZ", "WMT"]
UA = {"User-Agent": "Mozilla/5.0 (personal market dashboard; pandas.read_html)"}


def fetch_constituents(key: str) -> list[str]:
    import requests
    if key == "dow":
        return list(DOW30)
    if key == "nasdaq100":
        r = requests.get("https://api.nasdaq.com/api/quote/list-type/nasdaq100",
                         headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}, timeout=30)
        r.raise_for_status()
        s = [str(x.get("symbol", "")).strip().replace(".", "-") for x in r.json()["data"]["data"]["rows"]]
        lo, hi = 95, 110
    else:
        r = requests.get("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", headers=UA, timeout=30)
        r.raise_for_status()
        t = pd.read_html(io.StringIO(r.text))[0]
        s = t["Symbol"].astype(str).str.strip().str.replace(".", "-", regex=False).tolist()
        lo, hi = 480, 520
    s = sorted({x for x in s if x and x.replace("-", "").isalnum() and len(x) <= 6})
    if not lo <= len(s) <= hi:
        raise RuntimeError(f"{key}: 構成銘柄の数がおかしい（{len(s)}）")
    return s


def constituents() -> dict:
    old = json.loads(CONS.read_text(encoding="utf-8")) if CONS.exists() else {}
    fresh = old.get("asof") and (datetime.now() - datetime.fromisoformat(old["asof"])).days < 7
    if fresh and all(old.get(k) for k in WIKI):
        return old
    new = {"asof": datetime.now().strftime("%Y-%m-%d")}
    for k in WIKI:
        try:
            new[k] = fetch_constituents(k)
            print(f"  構成銘柄 {k}: {len(new[k])}")
        except Exception as e:
            if old.get(k):
                print(f"  構成銘柄 {k}: 取得失敗（{e}）→ 前回分を使用")
                new[k] = old[k]
            else:
                raise
    CONS.write_text(json.dumps(new, ensure_ascii=False), encoding="utf-8")
    return new


def download(tickers: list[str], period: str) -> pd.DataFrame:
    import yfinance as yf
    frames = []
    for i in range(0, len(tickers), 100):
        part = tickers[i:i + 100]
        for attempt in range(3):
            try:
                df = yf.download(part, period=period, interval="1d", auto_adjust=True, progress=False, threads=True)
                c = df["Close"] if isinstance(df.columns, pd.MultiIndex) else df[["Close"]].set_axis(part, axis=1)
                frames.append(c)
                break
            except Exception as e:
                print(f"  株価の取得に失敗（{i}〜, {attempt + 1}回目）: {e}")
                time.sleep(5)
        time.sleep(1)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, axis=1)
    out.index = pd.to_datetime(out.index).tz_localize(None).normalize()
    return out.loc[:, ~out.columns.duplicated()].dropna(how="all")


def closes(tickers: list[str]) -> pd.DataFrame:
    old = pd.read_csv(CLOSES, index_col=0, parse_dates=True) if CLOSES.exists() else pd.DataFrame()
    missing = [t for t in tickers if t not in old.columns]
    if old.empty or len(missing) > 20:
        new = download(tickers, "5y")          # 初回、または構成が大きく変わったときは取り直し
        allc = new if not new.empty else old
    else:
        new = download(tickers, "1mo")         # ふだんは直近だけ取り足す
        allc = new.combine_first(old) if not new.empty else old
        if missing:
            m = download(missing, "5y")
            if not m.empty:
                allc = allc.combine_first(m)
    allc = allc.sort_index()
    if not allc.empty:
        allc.round(4).to_csv(CLOSES)
    return allc


def ratio(c: pd.DataFrame) -> dict:
    # きょうの米国市場がまだ終わっていない行（半分以上が空）は使わない
    c = c[c.notna().sum(axis=1) >= c.shape[1] * 0.5]
    d = c.diff()
    ok = c.notna() & c.shift(1).notna()
    cnt = pd.DataFrame({"up": ((d > 0) & ok).sum(axis=1), "dn": ((d < 0) & ok).sum(axis=1)}).iloc[1:]
    r25 = cnt["up"].rolling(25).sum() / cnt["dn"].rolling(25).sum().replace(0, np.nan) * 100
    r10 = cnt["up"].rolling(10).sum() / cnt["dn"].rolling(10).sum().replace(0, np.nan) * 100
    cnt = cnt.assign(r25=r25, r10=r10).dropna(subset=["r25", "r10"])
    epoch = pd.Timestamp("1970-01-01")
    return {"d": ((cnt.index - epoch).days).tolist(), "r25": [round(float(x), 1) for x in cnt["r25"]],
            "r10": [round(float(x), 1) for x in cnt["r10"]], "up": cnt["up"].astype(int).tolist(),
            "dn": cnt["dn"].astype(int).tolist(), "n": int(c.shape[1])}


def main() -> int:
    DATA.mkdir(parents=True, exist_ok=True)
    cons = constituents()
    tickers = sorted(set(sum((cons[k] for k in WIKI), [])))
    c = closes(tickers)
    if c.empty:
        print("株価を取得できませんでした（us_breadth.json は前回のまま）")
        return 1
    out = {"asof": datetime.now().strftime("%Y-%m-%d %H:%M")}
    for k in WIKI:
        cols = [t for t in cons[k] if t in c.columns]
        if len(cols) < len(cons[k]) * 0.8:
            print(f"  {k}: 株価のある銘柄が少ないため飛ばします（{len(cols)}/{len(cons[k])}）")
            continue
        out[k] = ratio(c[cols])
        r = out[k]
        if r["d"]:
            print(f"  {k}: {len(cols)}銘柄・{len(r['d'])}日・25日 {r['r25'][-1]}%（値上がり {r['up'][-1]}／値下がり {r['dn'][-1]}）")
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"米国の騰落レシオを出力しました: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
