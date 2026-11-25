"""デイトレパターンの市場ごとの設定とデータの読み込み（東証版・米国版で共通）"""
import csv
import glob
import os

import pandas as pd

HOME = os.path.expanduser("~")
MARKETS = {
    "jp": {"base": os.path.join(HOME, "株分析"), "tz": "Asia/Tokyo", "cur": "円", "name": "東証",
           "yahoo": lambda c: f"{c}.T"},
    "us": {"base": os.path.join(HOME, "米国株分析"), "tz": "America/New_York", "cur": "ドル", "name": "米国",
           "yahoo": lambda c: c.replace(".", "-")},
}


def cfg(market):
    m = dict(MARKETS[market])
    m["key"] = market
    b = m["base"]
    m["intraday"] = os.path.join(b, "data", "intraday")
    m["archive"] = os.path.join(b, "data", "intraday_archive")
    m["out"] = os.path.join(b, "data", "daytrade")          # 検証結果など（公開しない）
    m["site"] = os.path.join(b, "data", "charts")
    m["pub"] = os.path.join(b, "data", "daytrade", "site")   # ページの出力先（非公開。公開は検証後に判断）
    m["tickers"] = os.path.join(b, "tickers", "tse_tickers.csv")
    return m


def load_tickers(m):
    with open(m["tickers"], encoding="utf-8-sig") as f:
        return {r["code"].strip(): {"name": (r.get("name") or "").strip(), "market": (r.get("market") or "").strip()}
                for r in csv.DictReader(f) if r.get("code", "").strip()}


def load_archive(m, code):
    """保管庫の5分足を全部つなげる（古い→新しい）"""
    parts = []
    for p in sorted(glob.glob(os.path.join(m["archive"], "*", f"{code}.csv.gz"))):
        try:
            parts.append(pd.read_csv(p, dtype={"dt": str}))
        except Exception:
            pass
    if not parts:
        return None
    df = pd.concat(parts).drop_duplicates("dt", keep="last").sort_values("dt").reset_index(drop=True)
    return df.dropna(subset=["o", "h", "l", "c"])


def load_recent(m, code):
    p = os.path.join(m["intraday"], f"{code}.csv")
    if not os.path.exists(p):
        return None
    try:
        df = pd.read_csv(p, dtype={"dt": str})
    except Exception:
        return None
    return df.dropna(subset=["o", "h", "l", "c"]).sort_values("dt").reset_index(drop=True)
