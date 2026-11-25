"""yfinance からの取得と整形（backfill / daily_update 共通）"""
import time

import pandas as pd
import yfinance as yf

from common import COLUMNS, RETRY, SLEEP, log

_FIELDS = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]


def _extract(raw: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """yf.download の戻り値から 1銘柄分を標準列に整形して返す"""
    if raw is None or raw.empty:
        return pd.DataFrame(columns=COLUMNS)

    if isinstance(raw.columns, pd.MultiIndex):
        lv0 = raw.columns.get_level_values(0)
        lv1 = raw.columns.get_level_values(1)
        if ticker in set(lv0):
            df = raw[ticker]
        elif ticker in set(lv1):
            df = raw.xs(ticker, axis=1, level=1)
        else:
            return pd.DataFrame(columns=COLUMNS)
    else:
        df = raw

    df = df.dropna(how="all")
    if df.empty:
        return pd.DataFrame(columns=COLUMNS)

    out = pd.DataFrame(index=df.index)
    for f in _FIELDS:
        out[f] = df[f] if f in df.columns else pd.NA
    # Adj Close が無い場合は Close で代用
    if out["Adj Close"].isna().all():
        out["Adj Close"] = out["Close"]

    out = out.rename(columns={"Adj Close": "AdjClose"})
    out = out.dropna(subset=["Close"])
    if out.empty:
        return pd.DataFrame(columns=COLUMNS)

    out.index = pd.to_datetime(out.index).tz_localize(None).normalize()
    out = out[~out.index.duplicated(keep="last")].sort_index()

    out = out.reset_index()
    out = out.rename(columns={out.columns[0]: "Date"})
    out["Date"] = out["Date"].dt.strftime("%Y-%m-%d")
    for c in ("Open", "High", "Low", "Close", "AdjClose"):
        out[c] = pd.to_numeric(out[c], errors="coerce").round(4)
    out["Volume"] = pd.to_numeric(out["Volume"], errors="coerce").fillna(0).astype("int64")
    return out[COLUMNS]


def download_batch(tickers, **kwargs) -> dict:
    """複数銘柄をまとめて取得し {ticker: DataFrame} を返す（リトライつき）"""
    params = dict(
        tickers=list(tickers),
        interval="1d",
        auto_adjust=False,     # 実際の取引値（調整前）+ Adj Close を得る
        actions=False,
        group_by="ticker",
        threads=True,
        progress=False,
        repair=True,
    )
    params.update(kwargs)

    raw = None
    for attempt in range(1, RETRY + 1):
        try:
            raw = yf.download(**params)
            break
        except TypeError as e:
            # yfinance のバージョン差で受け付けない引数があれば外して再試行
            dropped = False
            for opt in ("repair", "actions", "progress"):
                if opt in params and opt in str(e):
                    params.pop(opt)
                    dropped = True
            if dropped:
                log(f"  互換のため一部オプションを無効化して再試行: {e}")
                continue
            log(f"  取得失敗 (試行 {attempt}/{RETRY}): {e}")
            if attempt == RETRY:
                return {}
            time.sleep(SLEEP * attempt * 3)
        except Exception as e:
            log(f"  取得失敗 (試行 {attempt}/{RETRY}): {e}")
            if attempt == RETRY:
                return {}
            time.sleep(SLEEP * attempt * 3)

    out = {t: _extract(raw, t) for t in tickers}

    # repair 機能は scipy を必要とする。未導入で全滅した場合は無効にして再取得。
    if params.get("repair") and all(df.empty for df in out.values()):
        log("  repair機能が使えないため、無効にして再取得します（scipy未導入）。")
        params["repair"] = False
        try:
            raw = yf.download(**params)
            out = {t: _extract(raw, t) for t in tickers}
        except Exception as e:
            log(f"  再取得も失敗: {e}")

    return out
