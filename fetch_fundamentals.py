#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""東証全銘柄 ファンダメンタルデータ取得

Yahoo Finance の fundamentals-timeseries API から、銘柄ごとに
・損益計算書（売上高・営業利益・税引前利益・当期純利益・EPS・一株配当）
・貸借対照表（総資産・自己資本・流動資産・流動負債・発行済株式数）
・キャッシュフロー計算書（営業CF・投資CF・財務CF・フリーCF）
・バリュエーション（時価総額・PER・PBR・PSR）
を1リクエストで取得し、指標を計算して CSV に出力する。

出力
  fundamentals/fundamentals_by_year.csv   1行 = 銘柄 × 決算期（直近3期）
  fundamentals/fundamentals_latest.csv    1行 = 銘柄（最新期＋3期推移、スクリーニング用）
  fundamentals/failed.csv                 取得できなかった銘柄
  fundamentals/raw/<code>.json            APIの生レスポンス（キャッシュ）

使い方
  ./.venv/bin/python fetch_fundamentals.py --codes 7203,6758,9432   # 動作確認
  ./.venv/bin/python fetch_fundamentals.py                          # 全銘柄
  ./.venv/bin/python fetch_fundamentals.py --refresh                # キャッシュ無視
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import threading
import time
import datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import splits_util  # noqa: E402  株式分割の台帳（data/splits.csv）

BASE = Path(__file__).resolve().parent
TICKERS_CSV = BASE / "tickers" / "tse_tickers.csv"
SECTORS_CSV = BASE / "tickers" / "sectors.csv"
DAILY_DIR = BASE / "data" / "daily"
OUT_DIR = BASE / "fundamentals"
RAW_DIR = OUT_DIR / "raw"
LOG_DIR = BASE / "logs"

# ---------------------------------------------------------------- API 定義

BASE_URL = "https://query2.finance.yahoo.com"
TS_URL = BASE_URL + "/ws/fundamentals-timeseries/v1/finance/timeseries/{sym}"

# 年次（annual）で取得する項目
ANNUAL_KEYS = [
    # 損益計算書
    "TotalRevenue", "OperatingRevenue",
    "GrossProfit", "CostOfRevenue",
    "OperatingIncome", "TotalOperatingIncomeAsReported",
    "PretaxIncome",
    "NetIncome", "NetIncomeCommonStockholders",
    "BasicEPS", "DilutedEPS", "BasicAverageShares",
    "DividendPerShare",
    # 貸借対照表
    "TotalAssets", "StockholdersEquity", "TotalEquityGrossMinorityInterest",
    "CurrentAssets", "CurrentLiabilities",
    "OrdinarySharesNumber", "ShareIssued", "TreasurySharesNumber",
    # キャッシュフロー計算書
    "OperatingCashFlow", "InvestingCashFlow", "FinancingCashFlow",
    "FreeCashFlow", "CashDividendsPaid",
    # EV/EBITDA・ROTC・インタレストカバレッジ用
    "TotalDebt", "NetDebt", "CashAndCashEquivalents",
    "CashCashEquivalentsAndShortTermInvestments", "InvestedCapital",
    "EBITDA", "NormalizedEBITDA", "ReconciledDepreciation", "InterestExpense",
    # ピオトロスキーFスコア（TradingView定義）用
    "NormalizedIncome",                                   # 特別損益前の純利益
    "LongTermDebt", "LongTermDebtAndCapitalLeaseObligation",  # 長期借入金
    "IssuanceOfCapitalStock", "CommonStockIssuance",      # 株式の発行による収入
]

# 直近（trailing）で取得するバリュエーション指標
TRAILING_KEYS = ["MarketCap", "PeRatio", "PbRatio", "PsRatio"]

PERIOD1 = int(dt.datetime(2015, 1, 1).timestamp())

# ---------------------------------------------------------------- ユーティリティ

_print_lock = threading.Lock()


def log(msg: str) -> None:
    ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _print_lock:
        print(f"[{ts}] {msg}", flush=True)


class Pacer:
    """全スレッド合計のリクエスト間隔を最低 interval 秒に保つ。
    429 を食らったら間隔を自動的に広げる。"""

    def __init__(self, interval: float, max_interval: float = 3.0):
        self.interval = interval
        self.max_interval = max_interval
        self._next = 0.0
        self._lock = threading.Lock()
        self.throttled = 0

    def wait(self) -> None:
        # 自分の順番（スロット）を1つだけ予約し、その時刻まで1回だけ眠る。
        with self._lock:
            start = max(time.monotonic(), self._next)
            self._next = start + self.interval
        delay = start - time.monotonic()
        if delay > 0:
            time.sleep(delay)

    def slow_down(self) -> None:
        with self._lock:
            self.throttled += 1
            self.interval = min(self.interval * 1.6 + 0.05, self.max_interval)
            self._next = max(self._next, time.monotonic() + 20.0)
            iv = self.interval
        log(f"レート制限を検知 → 間隔を {iv:.2f} 秒に広げて20秒待機")


def num(v):
    """数値化。None/変換不可は None。"""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def first(d: dict, *keys):
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return None


def div(a, b, scale=1.0):
    a, b = num(a), num(b)
    if a is None or b in (None, 0):
        return None
    return a / b * scale


def rnd(v, nd=2):
    return None if v is None else round(v, nd)


# ---------------------------------------------------------------- 取得

def build_types(annual_keys, trailing_keys) -> str:
    parts = [f"annual{k}" for k in annual_keys]
    parts += [f"trailing{k}" for k in trailing_keys]
    return ",".join(parts)


UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

_local = threading.local()
REQ_TIMEOUT = 20.0


class RateLimited(Exception):
    pass


def get_session():
    """スレッドごとに独立したHTTPセッションを持つ。
    yfinance の共有セッション（cookie/crumb 取得でロック待ちになる）は使わない。"""
    s = getattr(_local, "session", None)
    if s is not None:
        return s
    try:
        from curl_cffi import requests as creq
        s = creq.Session(impersonate="chrome")
    except Exception:
        import requests as rq
        s = rq.Session()
        s.headers.update({"User-Agent": UA, "Accept": "application/json"})
    _local.session = s
    return s


def fetch_symbol(sym: str, pacer: Pacer, retries: int = 4) -> dict:
    """1銘柄ぶんの timeseries を取得して JSON を返す。"""
    period2 = int(time.time())

    def _one(annual_keys, trailing_keys):
        params = {
            "symbol": sym,
            "type": build_types(annual_keys, trailing_keys),
            "period1": PERIOD1,
            "period2": period2,
        }
        last_err = None
        for attempt in range(retries):
            pacer.wait()
            try:
                resp = get_session().get(TS_URL.format(sym=sym), params=params,
                                         timeout=REQ_TIMEOUT)
                if resp.status_code == 429:
                    raise RateLimited()
                if resp.status_code in (404, 401, 403):
                    if resp.status_code != 404:
                        raise RuntimeError(f"HTTP {resp.status_code}")
                    return None
                if resp.status_code >= 400:
                    raise RuntimeError(f"HTTP {resp.status_code}")
                return resp.json()
            except RateLimited as e:
                last_err = e
                pacer.slow_down()
            except Exception as e:  # ネットワーク/JSONエラー
                last_err = e
                _local.session = None  # セッションを作り直す
                time.sleep(min(2 ** attempt, 8) + random.random())
        raise last_err if last_err else RuntimeError("unknown fetch error")

    payload = _one(ANNUAL_KEYS, TRAILING_KEYS)
    if payload is None:
        return {}
    results = (payload.get("timeseries") or {}).get("result") or []
    got = sum(1 for r in results if any(k not in ("meta", "timestamp") for k in r))
    if got == 0 and len(ANNUAL_KEYS) > 8:
        # 長いURLが落とされるケースがあるので半分ずつ試す
        half = len(ANNUAL_KEYS) // 2
        merged = {"timeseries": {"result": []}}
        for ak, tk in ((ANNUAL_KEYS[:half], TRAILING_KEYS), (ANNUAL_KEYS[half:], [])):
            p = _one(ak, tk)
            if p:
                merged["timeseries"]["result"] += (p.get("timeseries") or {}).get("result") or []
        payload = merged
    return payload


def parse_payload(payload: dict) -> dict:
    """{'annual': {'2025-03-31': {key: value, ...}}, 'trailing': {key: (date, value)}}"""
    annual: dict[str, dict] = {}
    trailing: dict[str, tuple] = {}
    for item in (payload.get("timeseries") or {}).get("result") or []:
        for tname, points in item.items():
            if tname in ("meta", "timestamp") or not isinstance(points, list):
                continue
            if tname.startswith("annual"):
                base, bucket = tname[len("annual"):], annual
            elif tname.startswith("trailing"):
                base, bucket = tname[len("trailing"):], trailing
            else:
                continue
            for p in points:
                if not p:
                    continue
                as_of = p.get("asOfDate")
                raw = (p.get("reportedValue") or {}).get("raw")
                if as_of is None or raw is None:
                    continue
                if bucket is annual:
                    rec = annual.setdefault(as_of, {})
                    rec[base] = raw
                    if p.get("currencyCode"):
                        rec["__ccy"] = p["currencyCode"]
                else:
                    prev = trailing.get(base)
                    if prev is None or as_of >= prev[0]:
                        trailing[base] = (as_of, raw)
    return {"annual": annual, "trailing": trailing}


# ---------------------------------------------------------------- 指標計算

def year_metrics(rec: dict, prev: dict | None) -> dict:
    revenue = num(first(rec, "TotalRevenue", "OperatingRevenue"))
    op = num(first(rec, "OperatingIncome", "TotalOperatingIncomeAsReported"))
    pretax = num(rec.get("PretaxIncome"))
    net = num(first(rec, "NetIncomeCommonStockholders", "NetIncome"))
    assets = num(rec.get("TotalAssets"))
    equity = num(first(rec, "StockholdersEquity", "TotalEquityGrossMinorityInterest"))
    cur_a = num(rec.get("CurrentAssets"))
    cur_l = num(rec.get("CurrentLiabilities"))
    ocf = num(rec.get("OperatingCashFlow"))
    icf = num(rec.get("InvestingCashFlow"))
    fcf_fin = num(rec.get("FinancingCashFlow"))
    fcf = num(rec.get("FreeCashFlow"))

    # 株数は期末発行済株式数を使う。BasicAverageShares は Yahoo 側で桁が
    # 1/1000 になっている銘柄が散見されるため、株数の根拠には使わない。
    shares = num(rec.get("OrdinarySharesNumber"))
    issued = num(rec.get("ShareIssued"))
    treasury = num(rec.get("TreasurySharesNumber")) or 0.0
    if shares is None:
        shares = (issued - treasury) if issued else None
    # 時価総額は日本の慣行（JPX・Yahoo!ファイナンス）に合わせ、自己株式を含む
    # 発行済株式総数で計算する。BPS・EPSは1株あたりの価値なので自己株式を除いた
    # 株数（shares）のまま。
    if issued is None:
        issued = (shares + treasury) if shares is not None else None

    eps = num(first(rec, "BasicEPS", "DilutedEPS"))
    if eps is None:
        eps = div(net, shares)
    bps = div(equity, shares)

    dps = num(rec.get("DividendPerShare"))
    if dps is None:
        # 一株配当を持たない銘柄が多いので、支払配当総額 ÷ 期末株数で代替する
        paid = num(rec.get("CashDividendsPaid"))
        if paid and shares:
            dps = round(abs(paid) / shares, 2)
        elif rec.get("FinancingCashFlow") is not None:
            # 財務CFはあるのに配当支払の計上が無い ＝ 無配とみなす
            dps = 0.0

    # 売上総利益：開示があればそれを使い、無ければ 売上高 - 売上原価 で補う
    gross = num(rec.get("GrossProfit"))
    cost_rev = num(rec.get("CostOfRevenue"))
    if gross is None and revenue is not None and cost_rev is not None:
        gross = revenue - cost_rev
    if cost_rev is None and revenue is not None and gross is not None:
        cost_rev = revenue - gross

    prev_assets = num(prev.get("TotalAssets")) if prev else None

    return {
        "通貨": rec.get("__ccy") or "",
        "売上高": revenue,
        "売上原価": cost_rev,
        "売上総利益": gross,
        "売上総利益率(%)": rnd(div(gross, revenue, 100)),
        "営業利益": op,
        "税引前利益": pretax,
        "当期純利益": net,
        "営業利益率(%)": rnd(div(op, revenue, 100)),
        "総資産": assets,
        "自己資本": equity,
        "自己資本比率(%)": rnd(div(equity, assets, 100)),
        "流動資産": cur_a,
        "流動負債": cur_l,
        "流動比率(%)": rnd(div(cur_a, cur_l, 100)),
        "営業CF": ocf,
        "投資CF": icf,
        "財務CF": fcf_fin,
        "フリーCF": fcf,
        "発行済株式数": shares,
        "発行済株式総数": issued,
        "有利子負債": num(rec.get("TotalDebt")),
        "純有利子負債": num(rec.get("NetDebt")),
        "現金同等物": num(first(rec, "CashCashEquivalentsAndShortTermInvestments",
                                "CashAndCashEquivalents")),
        "投下資本": num(rec.get("InvestedCapital")),
        "EBITDA": num(first(rec, "EBITDA", "NormalizedEBITDA")),
        "減価償却費": num(rec.get("ReconciledDepreciation")),
        "支払利息": num(rec.get("InterestExpense")),
        "特別損益前純利益": num(rec.get("NormalizedIncome")),
        "長期借入金": num(first(rec, "LongTermDebt", "LongTermDebtAndCapitalLeaseObligation")),
        "株式発行収入": num(first(rec, "IssuanceOfCapitalStock", "CommonStockIssuance")),
        "BPS": rnd(bps),
        "EPS": rnd(eps),
        "一株配当": dps,
        "総資本増加率(%)": rnd(div(assets - prev_assets, prev_assets, 100)) if (assets and prev_assets) else None,
    }


BY_YEAR_COLS = [
    "コード", "銘柄名", "市場", "業種", "決算期", "通貨",
    "売上高", "売上原価", "売上総利益", "売上総利益率(%)",
    "営業利益", "税引前利益", "当期純利益", "営業利益率(%)",
    "総資産", "自己資本", "自己資本比率(%)",
    "流動資産", "流動負債", "流動比率(%)",
    "営業CF", "投資CF", "財務CF", "フリーCF",
    "発行済株式数", "発行済株式総数", "BPS", "EPS", "一株配当", "総資本増加率(%)",
    "有利子負債", "純有利子負債", "現金同等物", "投下資本", "EBITDA", "減価償却費", "支払利息",
    "特別損益前純利益", "長期借入金", "株式発行収入",
]

LATEST_COLS = [
    "コード", "銘柄名", "市場", "業種", "株価", "株価日付", "時価総額",
    "決算期", "通貨",
    "売上高", "営業利益", "税引前利益", "当期純利益", "営業利益率(%)",
    "自己資本比率(%)", "流動比率(%)",
    "営業CF", "投資CF", "財務CF", "フリーCF",
    "BPS", "EPS", "一株配当", "配当利回り(%)",
    "PER", "PBR", "PSR", "総資本増加率(%)",
    "売上高_前期", "売上高_前々期", "営業利益_前期", "営業利益_前々期",
    "当期純利益_前期", "当期純利益_前々期",
    "売上高成長率(%)", "営業利益成長率(%)",
    "総資産", "自己資本", "発行済株式数", "発行済株式総数",
    "有利子負債", "純有利子負債", "現金同等物", "投下資本", "EBITDA", "減価償却費", "支払利息",
    "時価総額(自己株式除く)", "取得日",
]


def build_rows(meta: dict, parsed: dict, price: tuple | None, years: int):
    """(by_year_rows, latest_row) を返す"""
    annual = parsed.get("annual") or {}
    trailing = parsed.get("trailing") or {}
    # Yahoo は年次系列に中間期のBSスナップショットを混ぜてくることがある。
    # 損益項目を持つ日付だけを「決算期」として扱う。
    # EPS だけが単独で先行して入っている日付があるため、EPS は判定に使わない。
    PL_KEYS = ("TotalRevenue", "OperatingRevenue", "OperatingIncome",
               "TotalOperatingIncomeAsReported", "PretaxIncome",
               "NetIncome", "NetIncomeCommonStockholders")
    dates = sorted((d for d, rec in annual.items() if any(k in rec for k in PL_KEYS)),
                   reverse=True)
    if not dates:
        return [], None

    by_year = []
    for i, d in enumerate(dates[:years]):
        prev = annual.get(dates[i + 1]) if i + 1 < len(dates) else None
        m = year_metrics(annual[d], prev)
        row = {"コード": meta["code"], "銘柄名": meta["name"], "市場": meta["market"],
               "業種": meta["sector"], "決算期": d}
        row.update(m)
        by_year.append(row)

    # 株式分割・併合があった銘柄は、Yahoo が分割を反映する前に取得したキャッシュだと
    # 株価（分割調整済み）と決算の株数・1株指標（分割前）が食い違い、時価総額・PER・PBR が
    # 1/分割比 になる。台帳 data/splits.csv（fix_splits.py / backfill_splits.py が作る）で
    # 全期の株数・EPS・BPS・一株配当を「いまの株数ベース」にそろえる（splits_util.py）。
    h = split_basis_factor(meta["code"], parsed, by_year[0])
    if h != 1.0:
        by_year = [adjust_for_splits(r, h) for r in by_year]
    by_year = apply_new_listing_shares(meta["code"], by_year)
    latest = by_year[0]
    close = price[1] if price else None
    price_date = price[0] if price else ""

    # 指標は「保存済みの終値 × 直近本決算の実績値」で自前計算し、株価と整合させる。
    # 計算できない場合のみ Yahoo の trailing 値（数日前基準）を使う。
    shares = latest["発行済株式数"]
    issued = latest.get("発行済株式総数") or shares
    # 時価総額は自己株式を含む発行済株式総数ベース（Yahoo!ファイナンス・JPXと同じ）。
    # 自己株式を除いた分は別列に残す。
    mcap = (close * issued) if (close and issued) else None
    mcap_ex = (close * shares) if (close and shares) else None
    if mcap is None:
        mcap = num(trailing.get("MarketCap", (None, None))[1])

    per = div(close, latest["EPS"]) if (close and latest["EPS"]) else None
    if per is None:
        per = num(trailing.get("PeRatio", (None, None))[1])
    pbr = div(close, latest["BPS"]) if (close and latest["BPS"]) else None
    if pbr is None:
        pbr = num(trailing.get("PbRatio", (None, None))[1])
    psr = div(mcap, latest["売上高"]) if (mcap and latest["売上高"]) else None
    if psr is None:
        psr = num(trailing.get("PsRatio", (None, None))[1])

    prior = by_year[1] if len(by_year) > 1 else {}
    prior2 = by_year[2] if len(by_year) > 2 else {}

    row = {
        "コード": meta["code"], "銘柄名": meta["name"], "市場": meta["market"],
        "業種": meta["sector"],
        "株価": close, "株価日付": price_date,
        "時価総額": rnd(mcap, 0) if mcap else None,
        "時価総額(自己株式除く)": rnd(mcap_ex, 0) if mcap_ex else None,
        "決算期": latest["決算期"], "通貨": latest["通貨"],
        "配当利回り(%)": rnd(div(latest["一株配当"], close, 100)),
        "PER": rnd(per), "PBR": rnd(pbr), "PSR": rnd(psr),
        "売上高_前期": prior.get("売上高"), "売上高_前々期": prior2.get("売上高"),
        "営業利益_前期": prior.get("営業利益"), "営業利益_前々期": prior2.get("営業利益"),
        "当期純利益_前期": prior.get("当期純利益"), "当期純利益_前々期": prior2.get("当期純利益"),
        "売上高成長率(%)": rnd(div((latest["売上高"] or 0) - (prior.get("売上高") or 0), prior.get("売上高"), 100)),
        "営業利益成長率(%)": rnd(div((latest["営業利益"] or 0) - (prior.get("営業利益") or 0), prior.get("営業利益"), 100)),
        "取得日": dt.date.today().isoformat(),
    }
    for k in ("売上高", "営業利益", "税引前利益", "当期純利益", "営業利益率(%)",
              "自己資本比率(%)", "流動比率(%)", "営業CF", "投資CF", "財務CF", "フリーCF",
              "BPS", "EPS", "一株配当", "総資本増加率(%)", "総資産", "自己資本",
              "発行済株式数", "発行済株式総数", "有利子負債", "純有利子負債", "現金同等物", "投下資本", "EBITDA", "減価償却費", "支払利息"):
        row[k] = latest.get(k)
    return by_year, row


def split_basis_factor(code, parsed, latest_row):
    """Yahoo の決算データ（キャッシュ）の株数を「いまの株数ベース」に直す係数 h を返す。

    Yahoo の fundamentals-timeseries は、取得した時点で分かっている分割を過去の全期に
    さかのぼって反映した株数・EPS を返す（1333 は2025年12月の3分割後、過去4期とも分割後の株数）。
    つまり直すべきなのは「キャッシュを取った後の分割」だけで、全期に同じ係数を掛ければよい。
    どの分割がまだ反映されていないかは、Yahoo の直近の時価総額 ÷ 同じ日の株価（手元の分割調整済み
    株価＝いまの株数ベース）＝いまの株数と、キャッシュの発行済株式総数を比べて決める。
    確かめられないときは、キャッシュの取得日より後に権利落ちした分割比の積を使う。
    """
    if str(code) not in splits_util.ledger():
        return 1.0
    raw = RAW_DIR / f"{code}.json"
    fetched = dt.date.fromtimestamp(raw.stat().st_mtime).isoformat() if raw.exists() else None
    fallback = splits_util.factor_after(code, fetched) if fetched else 1.0
    issued = latest_row.get("発行済株式総数") or latest_row.get("発行済株式数")
    mc = (parsed.get("trailing") or {}).get("MarketCap")
    now_shares = None
    if mc and mc[1] and fetched:
        px = _close_on(code, str(mc[0])[:10])
        # 時価総額の日付が取得日より古い／株価が無いときは使わない
        if px and str(mc[0])[:10] >= (dt.date.fromisoformat(fetched) - dt.timedelta(days=45)).isoformat():
            now_shares = num(mc[1]) / px
    h, _ = splits_util.choose(code, issued, now_shares, fallback)
    return h


def _close_on(code, day):
    """data/prices/<code>.csv の day 以前で最後の終値（分割調整済み＝いまの株数ベース）"""
    path = PRICES_DIR / f"{code}.csv"
    if not path.exists():
        return None
    last = None
    with path.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r.get("date", "") > day:
                break
            last = r.get("close")
    return num(last) if last else None


_SHARES_QUOTE = None


def new_listing_shares(code):
    """fetch_new_listing_shares.py が保存した、新規上場銘柄のいまの発行済株式数"""
    global _SHARES_QUOTE
    if _SHARES_QUOTE is None:
        _SHARES_QUOTE = {}
        path = OUT_DIR / "shares_quote.csv"
        if path.exists():
            with path.open(encoding="utf-8-sig", newline="") as fh:
                for r in csv.DictReader(fh):
                    v = num(r.get("shares"))
                    if v:
                        _SHARES_QUOTE[r["code"]] = v
    return _SHARES_QUOTE.get(str(code))


def apply_new_listing_shares(code, by_year):
    """上場して間もない銘柄は、決算データの株数が上場前のもの（分割・公募増資の前）か空なので、
    Yahoo の銘柄情報のいまの株数に置き換え、EPS・BPS を当期純利益・自己資本 ÷ 株数で計算し直す。
    決算データの株数があり、いまの株数との差が2割未満ならそのまま使う。"""
    q = new_listing_shares(code)
    if not q or not by_year:
        return by_year
    cur = by_year[0].get("発行済株式総数") or by_year[0].get("発行済株式数")
    if cur and abs(cur / q - 1) < 0.2:
        return by_year
    out = []
    for r in by_year:
        r = dict(r)
        r["発行済株式数"] = q
        r["発行済株式総数"] = q
        r["EPS"] = round(r["当期純利益"] / q, 2) if r.get("当期純利益") is not None else None
        r["BPS"] = round(r["自己資本"] / q, 2) if r.get("自己資本") is not None else None
        out.append(r)
    return out


def adjust_for_splits(row, h):
    """1期ぶんの行の株数を h 倍、BPS・EPS・一株配当を 1/h にした新しい dict を返す。"""
    row = dict(row)
    for k in ("発行済株式数", "発行済株式総数"):
        if row.get(k):
            row[k] = row[k] * h
    for k in ("BPS", "EPS", "一株配当"):
        if row.get(k) is not None:
            row[k] = round(row[k] / h, 4)
    return row


_SPLITS = None


def split_factor_after(code, period_end):
    """data/splits.csv（fix_splits.py が作る台帳）から、決算期末より後の分割比の積を返す。"""
    global _SPLITS
    if _SPLITS is None:
        _SPLITS = {}
        path = Path(__file__).resolve().parent / "data" / "splits.csv"
        if path.exists():
            with open(path, encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    try:
                        _SPLITS.setdefault(r["code"], []).append((r["ex_date"], float(r["ratio"])))
                    except (KeyError, ValueError):
                        continue
    f = 1.0
    for ex, ratio in _SPLITS.get(str(code), []):
        if period_end and str(ex) > str(period_end)[:10]:
            f *= ratio
    return f


# ---------------------------------------------------------------- 入力データ

def load_universe(markets=None, codes=None, limit=None):
    if not TICKERS_CSV.exists():
        sys.exit(f"銘柄リストがありません: {TICKERS_CSV}\n先に fetch_stocks.py --refresh-tickers を実行してください。")
    sectors = {}
    if SECTORS_CSV.exists():
        with SECTORS_CSV.open(encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if r.get("code"):
                    sectors[r["code"].strip()] = (r.get("sector33") or "").strip()
    rows = []
    with TICKERS_CSV.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            code = (r.get("code") or "").strip()
            if not code:
                continue
            market = (r.get("market") or "").strip()
            if markets and not any(m in market for m in markets):
                continue
            rows.append({"code": code, "name": (r.get("name") or "").strip(),
                         "market": market, "sector": sectors.get(code, "")})
    if codes:
        want = {c.strip().upper() for c in codes}
        rows = [r for r in rows if r["code"].upper() in want]
    if limit:
        rows = rows[:limit]
    return rows


PRICES_DIR = BASE / "data" / "prices"


PRICE_MAX = 1_000_000   # 1株100万円超は日本株ではあり得ないので異常値とみなす


def price_from_history(code: str):
    """data/prices/<code>.csv の最終行から終値を読む（日次ファイルに無い銘柄用）"""
    p = PRICES_DIR / f"{code}.csv"
    if not p.exists():
        return None
    try:
        last = None
        with p.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                c = num(row.get("close"))
                # 壊れた値（0以下・1株100万円超）は飛ばし、直近のまともな終値を採る
                if c and 0 < c <= PRICE_MAX:
                    last = row
        if last:
            return ((last.get("date") or "").strip(), num(last.get("close")))
    except Exception:
        pass
    return None


def load_previous_latest() -> dict:
    """前回の fundamentals_latest.csv を {コード: 行} で読む（決算の更新検知に使う）"""
    path = OUT_DIR / "fundamentals_latest.csv"
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            return {r["コード"]: r for r in csv.DictReader(f) if r.get("コード")}
    except Exception as e:
        log(f"前回CSVの読み込みに失敗（更新検知はスキップ）: {e}")
        return {}


def is_due(prev_row: dict | None, due_days: int) -> bool:
    """次の本決算が出ているはずなら True（前回の決算期から due_days 日経過）"""
    if not prev_row:
        return True
    d = (prev_row.get("決算期") or "").strip()
    try:
        fy = dt.date.fromisoformat(d)
    except ValueError:
        return True
    return (dt.date.today() - fy).days >= due_days


EARNINGS_COLS = [
    "検知日", "コード", "銘柄名", "市場", "業種", "新決算期", "前決算期",
    "売上高", "売上高成長率(%)", "営業利益", "営業利益成長率(%)",
    "当期純利益", "EPS", "一株配当", "自己資本比率(%)", "営業CF",
]


def write_earnings_updates(prev: dict, latest_rows: list) -> int:
    """前回より決算期が進んだ銘柄を earnings_updates.csv に追記する"""
    if not prev:
        log("新しい決算の検知: 前回CSVが無いためスキップ")
        return 0
    today = dt.date.today().isoformat()
    new = []
    for r in latest_rows:
        p = prev.get(r["コード"])
        if not p:
            continue  # 新規上場・新規取得銘柄は決算更新ではないので記録しない
        old_d = (p.get("決算期") or "").strip()
        if r["決算期"] and old_d and r["決算期"] > old_d:
            row = {c: r.get(c) for c in EARNINGS_COLS}
            row.update({"検知日": today, "新決算期": r["決算期"], "前決算期": old_d})
            new.append(row)
    if not new:
        log("新しい決算の検知: なし")
        return 0
    path = OUT_DIR / "earnings_updates.csv"
    exists = path.exists()
    with path.open("a", encoding="utf-8" if exists else "utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=EARNINGS_COLS, extrasaction="ignore")
        if not exists:
            w.writeheader()
        for row in new:
            w.writerow({c: ("" if row.get(c) is None else row.get(c)) for c in EARNINGS_COLS})
    log(f"新しい決算を検知: {len(new)} 銘柄 → {path}")
    for r in new[:10]:
        log(f"  {r['コード']} {r['銘柄名']}: {r['前決算期']} → {r['新決算期']}"
            f"（売上高{r['売上高成長率(%)']}%・営業利益{r['営業利益成長率(%)']}%）")
    return len(new)


def load_prices():
    """直近の data/daily/*.csv から終値を読む → {code: (date, close)}"""
    if not DAILY_DIR.exists():
        return {}
    files = sorted(DAILY_DIR.glob("*.csv"))
    if not files:
        return {}
    latest = files[-1]
    out, bad = {}, []
    with latest.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            c = (r.get("code") or "").strip()
            close = num(r.get("close"))
            if not c or not close:
                continue
            # データ元がスケールの壊れた値を返すことがある（1909は3,700円が
            # 162億円になっていた）。1株100万円超は日本株ではあり得ないので捨てる。
            # make_chart_html.py の PRICE_MAX と同じ基準。
            if close <= 0 or close > PRICE_MAX:
                bad.append((c, close))
                continue
            out[c] = ((r.get("date") or latest.stem).strip(), close)
    log(f"株価: {latest.name} から {len(out)} 銘柄を読み込み")
    if bad:
        log("  株価が異常なため除外: " +
            ", ".join(f"{c}({v:,.0f}円)" for c, v in bad[:10])
            + (f" ほか{len(bad)-10}銘柄" if len(bad) > 10 else ""))
    return out


# ---------------------------------------------------------------- メイン

def main():
    ap = argparse.ArgumentParser(description="東証全銘柄のファンダメンタルデータを取得")
    ap.add_argument("--codes", help="対象コードをカンマ区切りで指定（動作確認用）")
    ap.add_argument("--markets", nargs="*", help="市場で絞る 例: プライム スタンダード")
    ap.add_argument("--limit", type=int, help="先頭N銘柄だけ")
    # 4期にしているのは analyze_fundamentals.py の成長性・収益性が直近4期を使うため。
    # データ元が持っているのも4期までなので、これ以上増やしても取れません。
    ap.add_argument("--years", type=int, default=4, help="出力する決算期数（既定4）")
    ap.add_argument("--workers", type=int, default=4, help="並列数（既定4）")
    ap.add_argument("--interval", type=float, default=0.35, help="リクエスト間隔の下限秒（既定0.35）")
    ap.add_argument("--refresh", action="store_true", help="キャッシュを無視して取り直す")
    ap.add_argument("--max-age-days", type=int, default=7, help="キャッシュ有効日数（既定7）")
    ap.add_argument("--timeout", type=float, default=20.0, help="1リクエストのタイムアウト秒（既定20）")
    ap.add_argument("--rebuild-only", action="store_true",
                    help="通信せず、キャッシュと最新株価だけでCSVを作り直す")
    ap.add_argument("--due-only", action="store_true",
                    help="次の本決算が出ているはずの銘柄だけ取得し直す（他はキャッシュ）")
    ap.add_argument("--due-days", type=int, default=400,
                    help="前回の決算期から何日経過したら再取得するか（既定400）")
    args = ap.parse_args()

    global REQ_TIMEOUT
    REQ_TIMEOUT = args.timeout

    for d in (OUT_DIR, RAW_DIR, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)

    universe = load_universe(args.markets, args.codes.split(",") if args.codes else None, args.limit)
    if not universe:
        sys.exit("対象銘柄がありません。")
    prices = load_prices()
    prev = load_previous_latest()

    # どの銘柄を取りに行くか決める
    if args.rebuild_only:
        due = set()
        log(f"モード: キャッシュのみ（通信なし）／対象 {len(universe)} 銘柄")
    elif args.due_only:
        due = {m["code"] for m in universe
               if is_due(prev.get(m["code"]), args.due_days)
               or not (RAW_DIR / f"{m['code']}.json").exists()}
        log(f"モード: 決算更新のみ／{len(universe)} 銘柄中 {len(due)} 銘柄を再取得"
            f"（前回の決算期から{args.due_days}日以上経過）")
    else:
        due = {m["code"] for m in universe}
        log(f"対象 {len(universe)} 銘柄／並列 {args.workers}／間隔 {args.interval}秒")

    pacer = Pacer(args.interval)
    cutoff = time.time() - args.max_age_days * 86400
    verbose = len(universe) <= 20

    # 接続確認（1銘柄だけ単独で取得して、通信できることを確かめる）
    if due:
        probe = sorted(due)[0]
        t_probe = time.time()
        try:
            p = fetch_symbol(f"{probe}.T", pacer, retries=2)
            n = len((p.get("timeseries") or {}).get("result") or [])
            log(f"接続確認OK: {probe} → {n} 系列 ({time.time()-t_probe:.1f}秒)")
        except Exception as e:
            msg = f"接続確認に失敗しました: {type(e).__name__}: {e}"
            if args.due_only:
                # 自動実行中にYahooへ繋がらないときは、取得を諦めて
                # 手元のキャッシュ＋当日終値でCSVだけ作り直す
                log(msg + " → 今回は取得を見送り、キャッシュからCSVを作り直します")
                due = set()
            else:
                sys.exit(msg + "\nネットワーク／Yahoo Finance 側の問題の可能性があります。")

    results: dict[str, dict] = {}
    failed: list[tuple[str, str, str]] = []
    done = 0
    total = len(universe)
    t0 = time.time()

    def work(meta):
        code = meta["code"]
        raw_path = RAW_DIR / f"{code}.json"
        has_cache = raw_path.exists()
        if code not in due:
            cache_ok = has_cache          # 対象外の銘柄はキャッシュをそのまま使う
        elif args.refresh or args.due_only:
            cache_ok = False              # 対象銘柄は必ず取りに行く
        else:
            cache_ok = has_cache and raw_path.stat().st_mtime > cutoff
        if cache_ok:
            try:
                return meta, json.loads(raw_path.read_text(encoding="utf-8")), True
            except Exception:
                pass
        if code not in due:
            raise FileNotFoundError("キャッシュがありません（通信しないモード）")
        try:
            payload = fetch_symbol(f"{code}.T", pacer)
        except Exception:
            payload = None
        if payload:
            raw_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            return meta, payload, False
        # 取得できなかったときは、前回のキャッシュがあればそれを使う
        # （更新日に Yahoo が落ちていてもCSVから銘柄が消えないようにする）
        if raw_path.exists():
            try:
                return meta, json.loads(raw_path.read_text(encoding="utf-8")), True
            except Exception:
                pass
        return meta, payload, False

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(work, m): m for m in universe}
        for fut in as_completed(futures):
            meta = futures[fut]
            done += 1
            try:
                meta, payload, cached = fut.result()
                parsed = parse_payload(payload or {})
                if not parsed["annual"]:
                    failed.append((meta["code"], meta["name"], "財務データなし"))
                else:
                    results[meta["code"]] = {"meta": meta, "parsed": parsed}
            except Exception as e:
                failed.append((meta["code"], meta["name"], f"{type(e).__name__}: {e}"))
            if verbose:
                st = "OK" if meta["code"] in results else "NG"
                log(f"  {meta['code']} {meta['name']}: {st}")
            if done % 100 == 0 or done == total:
                el = time.time() - t0
                rate = done / el if el else 0
                eta = (total - done) / rate if rate else 0
                log(f"{done}/{total} 完了　成功 {len(results)}／失敗 {len(failed)}"
                    f"　{rate:.1f}件/秒　残り約 {eta/60:.0f}分")

    log(f"取得完了: 成功 {len(results)} / 失敗 {len(failed)}（レート制限 {pacer.throttled}回）")

    by_year_rows, latest_rows = [], []
    filled_price = 0
    for code in sorted(results):
        item = results[code]
        price = prices.get(code)
        if price is None:
            price = price_from_history(code)
            if price:
                filled_price += 1
        rows, latest = build_rows(item["meta"], item["parsed"], price, args.years)
        by_year_rows += rows
        if latest:
            latest_rows.append(latest)
    if filled_price:
        log(f"日次ファイルに無い {filled_price} 銘柄は data/prices/ の最終行から株価を補完")

    def write_csv(path: Path, cols, rows):
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow({c: ("" if r.get(c) is None else r.get(c)) for c in cols})
        log(f"出力: {path}　{len(rows)} 行")

    # 銘柄を絞って実行したときは、全銘柄のCSVを上書きしないよう別名にする
    subset = bool(args.codes or args.limit or args.markets)
    sfx = "_subset" if subset else ""
    if subset:
        log("※ 銘柄を絞った実行のため、出力ファイル名に _subset を付けます")

    write_csv(OUT_DIR / f"fundamentals_by_year{sfx}.csv", BY_YEAR_COLS, by_year_rows)
    if not subset:
        write_earnings_updates(prev, latest_rows)
    write_csv(OUT_DIR / f"fundamentals_latest{sfx}.csv", LATEST_COLS, latest_rows)

    with (OUT_DIR / f"failed{sfx}.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["コード", "銘柄名", "理由"])
        w.writerows(failed)
    log(f"出力: {OUT_DIR / f'failed{sfx}.csv'}　{len(failed)} 行")

    # 決算期の鮮度チェック（Yahoo側の更新が止まっている銘柄の検出）
    if latest_rows:
        limit = (dt.date.today() - dt.timedelta(days=460)).isoformat()
        stale = [r for r in latest_rows if r["決算期"] < limit]
        if stale:
            sample = ", ".join(r["コード"] for r in stale[:5])
            log(f"注意: 決算期が15か月以上前の銘柄が {len(stale)} 件あります（例: {sample}）")

    # 欠損率レポート
    if latest_rows:
        log("--- 主要項目の取得率 ---")
        for c in ["時価総額", "売上高", "営業利益", "税引前利益", "当期純利益",
                  "自己資本比率(%)", "流動比率(%)", "営業CF", "投資CF", "財務CF",
                  "BPS", "EPS", "一株配当", "配当利回り(%)", "PER", "PBR", "PSR",
                  "総資本増加率(%)"]:
            n = sum(1 for r in latest_rows if r.get(c) not in (None, ""))
            log(f"  {c:<16} {n:>5}/{len(latest_rows)}  ({n/len(latest_rows)*100:5.1f}%)")


if __name__ == "__main__":
    main()
