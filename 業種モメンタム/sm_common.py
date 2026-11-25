#!/usr/bin/env python3
"""業種モメンタム（試験運用）の共通部品。ルールは PREREG.md（2026-10-12 固定）

  判断日   : 毎月の最終営業日の終値
  対象銘柄 : 内国株式・60営業日の売買代金中央値 1億円以上・終値 100円以上
  業種点数 : 33業種ごとの「終値 ÷ 252営業日前の終値 − 1」の単純平均（対象5銘柄以上）
  持つもの : 上位5業種。参考に下位5業種・全業種平均
  値動き   : 判断日に固定した銘柄の日次リターンの単純平均（−50%〜+100%で打ち切り）
  記録     : 判断日の翌営業日の終値から、次の判断日の翌営業日の終値まで
"""
from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent            # ~/株分析/業種モメンタム
BASE = HERE.parent                                # ~/株分析
PRICES = BASE / "data" / "prices"
SECTORS = BASE / "tickers" / "sectors.csv"
TOPIX = BASE / "株価指数" / "data" / "topix.csv"
GAP_DAILY = BASE / "寄り前ギャップ" / "output" / "record_daily.csv"
OUT = Path(os.environ["SM_OUT"]) if os.environ.get("SM_OUT") else HERE / "output"   # SM_OUT は試し用
SIG = OUT / "signals"            # 判断日ごとの業種の点数と持つもの
DAILY = OUT / "record_daily.csv"  # 日次の記録
SITE = Path(os.environ["SM_SITE"]) if os.environ.get("SM_SITE") else BASE / "data" / "charts"
LOOKBACK, N_TOP, MIN_N = 252, 5, 5
LIQ_MIN, PX_MIN = 1e8, 100
W_GAP, W_SM = 0.30, 0.70          # 組み合わせの重み（固定）
START = pd.Timestamp("2026-10-30")  # 最初の判断日


def load_sectors() -> pd.DataFrame:
    s = pd.read_csv(SECTORS, dtype={"code": str})
    s = s[s["market"].astype(str).str.contains("内国株式")]
    return s[["code", "name", "sector33"]].drop_duplicates("code").set_index("code")


def load_panel(codes, last_n: int | None = 330) -> dict[str, pd.DataFrame]:
    """株価CSV（分割調整済み）の終値・出来高。last_n 行だけ（None で全期間）"""
    C, V = {}, {}
    for c in codes:
        f = PRICES / f"{c}.csv"
        if not f.exists():
            continue
        try:
            x = pd.read_csv(f, index_col="date", usecols=["date", "close", "volume"])
        except Exception:
            continue
        if x.empty:
            continue
        x.index = pd.to_datetime(x.index)
        x = x[~x.index.duplicated(keep="last")].sort_index()
        x = x[x["close"] > 0]
        if last_n:
            x = x.iloc[-last_n:]
        C[c], V[c] = x["close"], x["volume"]
    C, V = pd.DataFrame(C).sort_index(), pd.DataFrame(V).sort_index()
    # 東証の営業日（半数以上の銘柄に値がある日）にそろえる
    cnt = C.notna().sum(axis=1)
    days = cnt.index[cnt >= cnt.max() * 0.5]
    return {"close": C.loc[days], "volume": V.loc[days]}


def is_month_end(days: pd.DatetimeIndex, d: pd.Timestamp) -> bool:
    """d がその月の最終営業日か。翌営業日が分かっていればそれで、無ければ暦（土日・祝日）で判断"""
    nxt = days[days > d]
    if len(nxt):
        return nxt[0].month != d.month
    return next_business_day(d).month != d.month


def next_business_day(d: pd.Timestamp) -> pd.Timestamp:
    try:
        import jpholiday
        hol = jpholiday.is_holiday
    except Exception:
        hol = lambda x: False
    x = d + pd.Timedelta(days=1)
    while x.weekday() >= 5 or hol(x.date()) or (x.month == 12 and x.day == 31) or (x.month == 1 and x.day <= 3):
        x += pd.Timedelta(days=1)
    return x


def make_signal(P: dict, sec: pd.DataFrame, asof: pd.Timestamp) -> pd.DataFrame:
    """asof の終値までで業種の点数と順位を作る。戻り値は1行1銘柄（業種・点数・順位・区分）"""
    C, V = P["close"].loc[:asof], P["volume"].loc[:asof]
    if asof not in C.index or len(C) < LOOKBACK + 1:
        raise ValueError(f"{asof.date()} の判断に株価が足りません")
    tv = (C * V).iloc[-60:]
    liq = tv.median().where(tv.notna().sum() >= 40)
    last = C.iloc[-1]; base = C.iloc[-1 - LOOKBACK]
    ok = (liq >= LIQ_MIN) & (last >= PX_MIN) & last.notna() & base.notna()
    m = (last / base - 1)[ok]
    g = sec["sector33"].reindex(m.index)
    m, g = m[g.notna()], g[g.notna()]
    agg = m.groupby(g).agg(["mean", "size"])
    agg = agg[agg["size"] >= MIN_N]
    rk = agg["mean"].rank(ascending=False, method="first").astype(int)
    nsec = len(rk)
    kind = pd.Series("中", index=rk.index)
    kind[rk <= N_TOP] = "上位"; kind[rk > nsec - N_TOP] = "下位"
    df = pd.DataFrame({"コード": m.index, "業種": g.values, "銘柄名": sec["name"].reindex(m.index).values,
                       "銘柄の12か月_pct": (m.values * 100).round(3)})
    df = df[df["業種"].isin(rk.index)]
    df["業種の点数_pct"] = df["業種"].map(agg["mean"] * 100).round(3)
    df["業種の順位"] = df["業種"].map(rk)
    df["区分"] = df["業種"].map(kind)
    return df.sort_values(["業種の順位", "コード"]).reset_index(drop=True)


def daily_returns(sig: pd.DataFrame, C: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp | None) -> pd.DataFrame:
    """判断に固定した銘柄で、start〜end の日次リターン（%）: 上位・下位・全業種平均・LS・超過"""
    cols = [c for c in sig["コード"] if c in C.columns]
    r = (C[cols] / C[cols].shift(1) - 1).clip(-0.5, 1.0)
    r = r.loc[start:end] if end is not None else r.loc[start:]
    if r.empty:
        return pd.DataFrame()
    g = sig.set_index("コード")["業種"].reindex(cols)
    secd = r.T.groupby(g).mean().T           # 業種ごとの日次（等加重、値の無い銘柄は外す）
    kind = sig.drop_duplicates("業種").set_index("業種")["区分"]
    top = secd[[s for s in secd if kind.get(s) == "上位"]].mean(axis=1)
    bot = secd[[s for s in secd if kind.get(s) == "下位"]].mean(axis=1)
    allm = secd.mean(axis=1)
    out = pd.DataFrame({"上位5_pct": top, "下位5_pct": bot, "全業種_pct": allm})
    out["LS_pct"] = out["上位5_pct"] - out["下位5_pct"]
    out["超過_pct"] = out["上位5_pct"] - out["全業種_pct"]
    return (out * 100).round(5)


def today() -> pd.Timestamp:
    return pd.Timestamp(dt.date.today())
