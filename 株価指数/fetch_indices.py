#!/usr/bin/env python3
"""
主要指数（日経平均・TOPIX・日経VI・ダウ平均・S&P500・NASDAQ総合・NASDAQ100・SOX指数・ラッセル2000・VIX）と
米10年国債利回り・ドル円・WTI原油先物・金先物・ビットコインの日足を
無料ソースから取得し、指標ごとのCSVと終値一覧CSVに保存するスクリプト。

・毎回「取得できる全期間」を取り直し、既存CSVとマージして保存します。
  ソース側で古いデータが消えても（例：日経VIの公式CSVは2023年以降のみ）、
  手元のCSVには蓄積され続けます。
・ソースごとにフォールバックがあり、1つが失敗しても他の指標は保存されます。

使い方:
    pip install yfinance pandas requests
    python3 fetch_indices.py                  # ~/market_data に保存
    python3 fetch_indices.py --outdir ./data  # 保存先を指定

任意の設定:
    JQUANTS_API_KEY  … J-Quants(JPX公式)のAPIキー。TOPIXのフォールバックに使用
                        （無料プランは直近約2年・12週遅れ）
    seed/<指標名>.csv … 手元で入手した過去データ(Date,Open,High,Low,Close)を置くと
                        初回にマージされます（例: seed/topix.csv, seed/nikkei_vi.csv）

出力:
    <outdir>/<指標名>.csv   Date,Open,High,Low,Close,Volume,Source
    <outdir>/all_close.csv  日付×7指標の終値（分析用のワイド形式）
    <outdir>/fetch.log      実行ログ
"""
from __future__ import annotations

import argparse
import io
import logging
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import requests

COLS = ["Open", "High", "Low", "Close", "Volume"]
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) market-data-script"}
TIMEOUT = 60
log = logging.getLogger("fetch")


# ---------------------------------------------------------------- 共通処理
def normalize(df: pd.DataFrame, source: str) -> pd.DataFrame:
    """Date をインデックスにし、Open/High/Low/Close/Volume/Source に揃える。"""
    df = df.copy()
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    df.index.name = "Date"
    for c in COLS:
        if c not in df.columns:
            df[c] = pd.NA
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df[COLS].dropna(subset=["Close"])
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df["Source"] = source
    return df


def http_get(url: str, **kw) -> requests.Response:
    r = requests.get(url, headers={**UA, **kw.pop("headers", {})}, timeout=TIMEOUT, **kw)
    r.raise_for_status()
    return r


# ---------------------------------------------------------------- 各ソース
def from_yahoo(symbol: str) -> pd.DataFrame:
    import yfinance as yf

    df = yf.Ticker(symbol).history(period="max", interval="1d", auto_adjust=False)
    if df is None or df.empty:
        raise ValueError(f"Yahoo: {symbol} のデータが空です")
    return normalize(df, f"yahoo:{symbol}")


def from_stooq(symbol: str) -> pd.DataFrame:
    r = http_get("https://stooq.com/q/d/l/", params={"s": symbol, "i": "d"})
    text = r.text.strip()
    if not text.lower().startswith("date"):
        raise ValueError(f"Stooq: CSVではない応答です（先頭: {text[:80]!r}）")
    df = pd.read_csv(io.StringIO(text), index_col="Date")
    return normalize(df, f"stooq:{symbol}")


def from_fred(series: str) -> pd.DataFrame:
    r = http_get("https://fred.stlouisfed.org/graph/fredgraph.csv", params={"id": series})
    df = pd.read_csv(io.StringIO(r.text))
    df = df.rename(columns={df.columns[0]: "Date", df.columns[1]: "Close"}).set_index("Date")
    return normalize(df, f"fred:{series}")


def from_nikkei_csv(url: str) -> pd.DataFrame:
    """日経平均プロフィルの公式CSV（Shift_JIS、末尾に注記行あり）。"""
    r = http_get(url)
    text = r.content.decode("cp932", errors="replace")
    df = pd.read_csv(io.StringIO(text))
    df = df.rename(columns={df.columns[0]: "Date", "始値": "Open", "高値": "High",
                            "安値": "Low", "終値": "Close"})
    df["Date"] = pd.to_datetime(df["Date"], format="%Y/%m/%d", errors="coerce")
    df = df.dropna(subset=["Date"]).set_index("Date")  # 注記行を除去
    for c in ["Open", "High", "Low", "Close"]:
        df[c] = df[c].astype(str).str.replace(",", "")
    return normalize(df, "nikkei:" + url.rsplit("/", 1)[-1])


def from_cboe_vix() -> pd.DataFrame:
    url = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
    df = pd.read_csv(io.StringIO(http_get(url).text))
    df.columns = [c.strip().title() for c in df.columns]
    df["Date"] = pd.to_datetime(df["Date"], format="%m/%d/%Y")
    return normalize(df.set_index("Date"), "cboe:VIX_History")


OUTDIR: Path | None = None   # main() で設定（TOPIX換算で世界統計データの写しを探すため）


SPLIT_FACTORS = [10, 5, 4, 3, 2, 1/2, 1/3, 1/4, 1/5, 1/10]


def fix_scale_jumps(df: pd.DataFrame) -> pd.DataFrame:
    """Yahoo の ETF 株価は、株式分割の前後で一部の期間だけ調整されずに 10倍・1/10 などに
    跳ねていることがある（1306.T は 2015年1月・2026年3〜4月など）。指数連動ETFが1日で
    ±40%以上動くことはないので、そうした日を分割の段差とみなし、最新の水準にそろえる。"""
    c = df["Close"].astype(float)
    q = (c / c.shift(1)).fillna(1.0)
    jump = pd.Series(1.0, index=df.index)
    for t, v in q.items():
        if v > 1.4 or v < 1 / 1.4:
            k = min(SPLIT_FACTORS, key=lambda f: abs(np.log(v / f)))
            if abs(np.log(v / k)) < np.log(1.15):     # 分割比にほぼ一致
                jump[t] = k
            else:
                log.warning("  1306.T %s の値動き %.1f倍 は分割比と合わないため、そのまま使います", t.date(), v)
    # 各日の補正倍率 = その日より後の段差の積（最新の日が基準）
    factor = jump[::-1].cumprod()[::-1].shift(-1).fillna(1.0)
    n = int((jump != 1.0).sum())
    if n:
        log.info("  1306.T の分割による段差を %d か所補正しました", n)
    out = df.copy()
    for col in ["Open", "High", "Low", "Close"]:
        out[col] = out[col] * factor
    return out


def from_topix_etf() -> pd.DataFrame:
    """TOPIX連動ETF（1306.T NEXT FUNDS TOPIX）の終値を TOPIX の水準に換算する。
    換算比率 = 世界統計データの TOPIX 月末値（2007年〜）・年末値 ÷ 同じ日の ETF 終値。
    各日には「その日以前で直近の月末（年末）」の比率を掛ける（分配金落ち・信託報酬による
    ずれは月末ごとに補正される）。世界統計データが無いときは ETF の終値そのままは使わず失敗にする。"""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import make_dashboard
    est = make_dashboard.load_estat_topix(OUTDIR) if OUTDIR else None
    if est is None or est.empty:
        raise ValueError("世界統計データのTOPIX（換算の基準）が無いため換算できません")
    etf = fix_scale_jumps(from_yahoo("1306.T"))
    ref = est.set_index("Date")["Close"].astype(float).sort_index()
    ref = ref[~ref.index.duplicated(keep="last")]
    # 基準日（月末・年末が休日なら直前の取引日）の ETF 終値。比率はその取引日から適用する
    ref = ref[ref.index >= etf.index[0]]
    pos = etf.index.searchsorted(ref.index, side="right") - 1
    tdays = etf.index[pos]
    ratio = pd.Series(ref.values / etf["Close"].values[pos], index=tdays).dropna()
    ratio = ratio[~ratio.index.duplicated(keep="last")]
    if ratio.empty:
        raise ValueError("ETFと世界統計データの重なる期間がありません")
    r = ratio.reindex(etf.index, method="ffill").bfill()     # 各日に直近の比率
    out = etf.copy()
    for c in ["Open", "High", "Low", "Close"]:
        out[c] = (out[c] * r).round(2)
    out["Volume"] = pd.NA
    out["Source"] = "yahoo:1306.T換算"
    big = out["Close"].pct_change().abs()
    if (big > 0.2).any():
        log.warning("  換算後に1日20%%超の変動が残っています: %s",
                    ", ".join(str(d.date()) for d in big[big > 0.2].index[:5]))
    log.info("  （換算比率 最新 %.3f・基準 %s）", r.iloc[-1], ratio.index[-1].date())
    return out


def from_jquants_topix() -> pd.DataFrame:
    key = os.environ.get("JQUANTS_API_KEY")
    if not key:
        raise ValueError("JQUANTS_API_KEY が未設定のためスキップ")
    url = "https://api.jquants.com/v2/indices/bars/daily/topix"
    rows, params = [], {}
    while True:
        j = http_get(url, headers={"x-api-key": key}, params=params).json()
        rows += j.get("data", [])
        if not j.get("pagination_key"):
            break
        params = {"pagination_key": j["pagination_key"]}
    if not rows:
        raise ValueError("J-Quants: データが空です")
    df = pd.DataFrame(rows).rename(columns={"O": "Open", "H": "High", "L": "Low", "C": "Close"})
    return normalize(df.set_index("Date"), "jquants:topix")


# ---------------------------------------------------------------- 指標定義
NIKKEI_DAILY = "https://indexes.nikkei.co.jp/nkave/historical/nikkei_stock_average_daily_jp.csv"
NIKKEI_VI_DAILY = "https://indexes.nikkei.co.jp/nkave/historical/nikkei_stock_average_vi_daily_jp.csv"

# (指標名, 表示名, [(説明, 取得関数), ...])  上から順に試し、成功したものを採用
# ※ mode="all" の指標は成功した全ソースをマージ（長期の履歴と最新値を両取り）
INDICES = [
    ("nikkei225", "日経平均", "first", [
        ("Yahoo ^N225 (1965〜)", lambda: from_yahoo("^N225")),
        ("日経公式CSV", lambda: from_nikkei_csv(NIKKEI_DAILY)),
        ("FRED NIKKEI225 (終値のみ)", lambda: from_fred("NIKKEI225")),
    ]),
    ("topix", "TOPIX", "all", [
        # 後ろほど優先（同じ日は後のソースで上書き）：ETF換算 < J-Quants < stooq（指数そのもの）
        ("TOPIX連動ETF 1306.T（TOPIX換算）", from_topix_etf),
        ("J-Quants", from_jquants_topix),
        ("Stooq ^TPX", lambda: from_stooq("^tpx")),
    ]),
    ("nikkei_vi", "日経平均VI", "first", [
        ("日経公式CSV (2023〜)", lambda: from_nikkei_csv(NIKKEI_VI_DAILY)),
    ]),
    ("dow", "ダウ平均", "first", [
        ("Yahoo ^DJI (1992〜)", lambda: from_yahoo("^DJI")),
        ("Stooq ^DJI", lambda: from_stooq("^dji")),
    ]),
    ("sp500", "S&P500", "first", [
        ("Yahoo ^GSPC (1927〜)", lambda: from_yahoo("^GSPC")),
        ("Stooq ^SPX", lambda: from_stooq("^spx")),
    ]),
    ("nasdaq100", "NASDAQ100", "first", [
        ("Yahoo ^NDX (1985〜)", lambda: from_yahoo("^NDX")),
        ("FRED NASDAQ100 (終値のみ)", lambda: from_fred("NASDAQ100")),
    ]),
    # 2026-11-24：CBOE公式CSVは公表が1日遅れて最新日が欠けるため、"all" にして足りない日を Yahoo で補う
    #   （後ろほど優先：同じ日は CBOE の値を使う）
    ("vix", "VIX", "all", [
        ("Yahoo ^VIX", lambda: from_yahoo("^VIX")),
        ("CBOE公式CSV (1990〜)", from_cboe_vix),
    ]),
    # 2026-11-16 追加（主要指数ダッシュボード。トップ画面のマーケット概況のタイルにある指数・金利・為替・商品）
    ("nasdaq", "NASDAQ総合", "first", [("Yahoo ^IXIC (1971〜)", lambda: from_yahoo("^IXIC"))]),
    ("sox", "SOX指数", "first", [("Yahoo ^SOX (1994〜)", lambda: from_yahoo("^SOX"))]),
    ("russell2000", "ラッセル2000", "first", [("Yahoo ^RUT (1987〜)", lambda: from_yahoo("^RUT"))]),
    ("us10y", "米10年国債利回り", "first", [
        ("Yahoo ^TNX (1962〜)", lambda: from_yahoo("^TNX")),
        ("FRED DGS10", lambda: from_fred("DGS10")),
    ]),
    ("usdjpy", "ドル円", "first", [
        ("Yahoo JPY=X (1996〜)", lambda: from_yahoo("JPY=X")),
        ("FRED DEXJPUS (終値のみ)", lambda: from_fred("DEXJPUS")),
    ]),
    ("wti", "WTI原油先物", "first", [("Yahoo CL=F (2000〜)", lambda: from_yahoo("CL=F"))]),
    ("gold", "金先物", "first", [("Yahoo GC=F (2000〜)", lambda: from_yahoo("GC=F"))]),
    ("btc", "ビットコイン", "first", [("Yahoo BTC-USD (2014〜)", lambda: from_yahoo("BTC-USD"))]),
]


# ---------------------------------------------------------------- 保存
def load_csv(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    df = pd.read_csv(path)
    df = df.rename(columns={df.columns[0]: "Date"}).set_index("Date")
    src = df["Source"] if "Source" in df.columns else None
    df.index = pd.to_datetime(df.index)
    out = normalize(df, f"seed:{path.name}")
    if src is not None:
        src.index = df.index
        src = src[~src.index.duplicated(keep="last")]
        out["Source"] = src.reindex(out.index).fillna(f"seed:{path.name}")
    return out


def merge(old: pd.DataFrame | None, new: pd.DataFrame) -> pd.DataFrame:
    """同じ日付は新しい取得結果を優先。古い日付は既存データを残す。"""
    if old is None or old.empty:
        return new
    df = pd.concat([old, new])
    return df[~df.index.duplicated(keep="last")].sort_index()


def fetch_one(name, label, mode, sources) -> pd.DataFrame | None:
    frames = []
    for desc, fn in sources:
        try:
            df = fn()
            log.info("  ✓ %s: %s 〜 %s (%d行)", desc, df.index[0].date(), df.index[-1].date(), len(df))
            frames.append(df)
            if mode == "first":
                break
        except Exception as e:  # noqa: BLE001
            log.warning("  ✗ %s: %s", desc, e)
    if not frames:
        return None
    out = frames[0]
    for f in frames[1:]:
        out = merge(out, f)  # 後のソースで同日を上書き（最新値を優先）
    return out


# 米国株分析（~/米国株分析/主要指数/run_indices.sh）から呼ぶとき：日本は日経平均・日経平均VI（TOPIX は取らない）
if os.environ.get("KB_IDX_MARKET") == "us":
    INDICES = [x for x in INDICES if x[0] not in ("topix",)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--outdir", default=str(Path.home() / "market_data"), help="CSVの保存先")
    ap.add_argument("--html", help="ダッシュボードHTMLの出力先（省略時 <outdir>/dashboard.html）")
    ap.add_argument("--home", help="ダッシュボードの「‹ トップ」リンク先（例: ./index.html）")
    args = ap.parse_args()

    outdir = Path(args.outdir).expanduser()
    global OUTDIR
    OUTDIR = outdir
    outdir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(sys.stdout),
                  logging.FileHandler(outdir / "fetch.log", encoding="utf-8")],
    )

    closes, failed = {}, []
    for name, label, mode, sources in INDICES:
        log.info("[%s] %s", name, label)
        path = outdir / f"{name}.csv"
        existing = load_csv(path)
        seed = load_csv(outdir / "seed" / f"{name}.csv")
        base = merge(seed, existing) if seed is not None else existing

        new = fetch_one(name, label, mode, sources)
        if new is None:
            failed.append(label)
            log.error("  → 全ソース失敗。既存データを維持します")
            merged = base
        else:
            merged = merge(base, new)

        if merged is not None and not merged.empty:
            merged.to_csv(path, date_format="%Y-%m-%d")
            closes[name] = merged["Close"]
            log.info("  → 保存: %s 〜 %s (%d行)", merged.index[0].date(), merged.index[-1].date(), len(merged))

    if closes:
        wide = pd.DataFrame(closes).sort_index()
        wide.index.name = "Date"
        wide.to_csv(outdir / "all_close.csv", date_format="%Y-%m-%d")
        log.info("all_close.csv を保存しました（%d行）", len(wide))

    try:  # 同じフォルダに make_dashboard.py があればダッシュボードも更新
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import make_dashboard
        log.info("ダッシュボードを更新しました: %s", make_dashboard.build(
            outdir, Path(args.html).expanduser() if args.html else None, args.home))
    except ImportError:
        pass
    except Exception as e:  # noqa: BLE001
        log.warning("ダッシュボードの生成に失敗: %s", e)

    if failed:
        log.error("取得失敗: %s", ", ".join(failed))
        return 1
    log.info("完了")
    return 0


if __name__ == "__main__":
    sys.exit(main())
