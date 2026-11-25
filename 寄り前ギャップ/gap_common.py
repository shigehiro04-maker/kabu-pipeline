#!/usr/bin/env python3
"""寄り前ギャップ（Buy-on-Gap 試験運用）の共通部品

ルール（『Algorithmic Trading』第4章 例4.1。検証は 平均回帰_株とETF_第4章_20261010/）
  運用対象 : 前月末の時点で、60日の売買代金の中央値 2億円以上・時価総額 300億円以上（ETF・REIT等を除く内国株）
  買う条件 : 当日始値 < 前日安値 ×（1 − k × σ90）  かつ  当日始値 > 20日移動平均
             σ90 = 前日までの90営業日の日次リターンの標準偏差、20日移動平均 = 前日までの終値20日
  買い方   : 条件を満たした銘柄のうち、始値 ÷ 前日安値 が最も小さい 10 銘柄を寄付きで同額ずつ買い、大引けで売る
  k        : 1.0（本書の既定、主）。0.5 も参考として並べて記録する

追加（2026-10-12、第7章の検証 日中モメンタム_第7章_20261012/ の B2・B3 による。2026-10-13 から記録。条件は固定）
  売る条件 : 当日始値 > 前日高値 ×（1 + k × σ90）  かつ  当日始値 < 20日移動平均（買いの鏡写し）
             寄りからストップ高に張り付いた銘柄（始値＝高値 かつ 前日終値比 +13%以上）は除く
  売り方   : 条件を満たした銘柄のうち、始値 ÷ 前日高値 が最も大きい 10 銘柄を寄付きで同額ずつ売り、大引けで買い戻す（紙の記録のみ）
  決算翌日 : 判断日〜対象日の前日 に決算発表（予定）がある銘柄に印を付ける。売買の条件は変えず、
             「決算翌日を除いて選んだ場合」も並べて記録する
             発表日は JPX「決算発表予定日」の Excel（株分析/kessan*.xlsx か 株分析/決算発表予定日/*.xlsx）と、
             J-Quants 決算サマリー（fundamentals/jq_summary、実際の開示日。過去の再現用）を合わせて使う
"""
from __future__ import annotations

import datetime as dt
import os
import re
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent            # ~/株分析/寄り前ギャップ
BASE = HERE.parent                                # ~/株分析
PRICES = BASE / "data" / "prices"
TICKERS = BASE / "tickers" / "tse_tickers.csv"
SECTORS = BASE / "tickers" / "sectors.csv"
FUND = BASE / "fundamentals" / "fundamentals_latest.csv"
TOPIX = BASE / "株価指数" / "data" / "topix.csv"
OUT = Path(os.environ["GAP_OUT"]) if os.environ.get("GAP_OUT") else HERE / "output"   # GAP_OUT は試し用
CAND = OUT / "candidates"          # 引け後に作る候補（日付＝判断に使った最終日）
REC = OUT / "record_trades.csv"    # 答え合わせ（1取引1行）
DAILY = OUT / "record_daily.csv"   # 答え合わせ（1日1行）
REC_S = OUT / "record_short_trades.csv"   # 売り側の答え合わせ（1取引1行）
DAILY_S = OUT / "record_short_daily.csv"  # 売り側の答え合わせ（1日1行）
JQ_SUM = BASE / "fundamentals" / "jq_summary"
SITE = Path(os.environ["GAP_SITE"]) if os.environ.get("GAP_SITE") else BASE / "data" / "charts"
KS = (1.0, 0.5)
N_PICK = 10
LIQ_MIN, MCAP_MIN = 200, 300       # 百万円・億円（運用中の条件と同じ）


def load_universe_codes() -> pd.DataFrame:
    """内国株（プライム・スタンダード・グロース）の一覧（コード・名前・市場・業種）"""
    s = pd.read_csv(SECTORS, dtype={"code": str})
    s = s[s["market"].astype(str).str.contains("内国株式")]
    return s[["code", "name", "market", "sector33"]].drop_duplicates("code")


def load_panel(codes, last_n: int | None = 160) -> dict[str, pd.DataFrame]:
    """株価CSV（分割・配当調整済み）から 始値・高値・安値・終値・出来高 のパネル。last_n 行だけ読む（None で全期間）"""
    d = {k: {} for k in ("open", "high", "low", "close", "volume")}
    for c in codes:
        f = PRICES / f"{c}.csv"
        if not f.exists():
            continue
        try:
            x = pd.read_csv(f, index_col="date")
        except Exception:
            continue
        if x.empty:
            continue
        x.index = pd.to_datetime(x.index)
        x = x[~x.index.duplicated(keep="last")].sort_index()
        if last_n:
            x = x.iloc[-last_n:]
        for k in d:
            if k in x:
                d[k][c] = x[k]
    return {k: pd.DataFrame(v).sort_index() for k, v in d.items()}


def mcap_oku(close_last: pd.Series) -> pd.Series:
    """時価総額（億円）。決算データの時価総額を最新終値で引き直す（ヒートマップと同じ考え方）"""
    f = pd.read_csv(FUND, dtype={"コード": str}, usecols=["コード", "株価", "時価総額"]).drop_duplicates("コード").set_index("コード")
    mc = pd.to_numeric(f["時価総額"], errors="coerce") / 1e8
    px = pd.to_numeric(f["株価"], errors="coerce")
    return (mc * close_last.reindex(mc.index) / px).reindex(close_last.index)


def month_end_universe(P: dict, asof: pd.Timestamp) -> pd.Series:
    """asof より前の最後の月末の時点で、運用対象かどうか（True/False）"""
    C, V = P["close"], P["volume"]
    idx = C.index[C.index < asof.to_period("M").start_time]
    if len(idx) == 0:
        return pd.Series(False, index=C.columns)
    me = idx[-1]
    tv = (C * V).loc[:me].iloc[-60:]
    liq = tv.median() / 1e6
    liq = liq.where((C * V).loc[:me].iloc[-60:].notna().sum() >= 40)
    # 時価総額は「いまの時価総額 × 月末の終値 ÷ いまの終値」で月末に引き戻す（株数の変化は無視）
    last = C.ffill().iloc[-1]
    mc_now = mcap_oku(last)
    mc_me = mc_now * C.loc[:me].ffill().iloc[-1] / last
    return (liq >= LIQ_MIN) & (mc_me >= MCAP_MIN)


def next_business_day(d: pd.Timestamp) -> pd.Timestamp:
    """東証の次の営業日（土日・祝日・12/31〜1/3 を除く）"""
    try:
        import jpholiday
        hol = jpholiday.is_holiday
    except Exception:                                  # jpholiday が無ければ土日だけ除く
        hol = lambda x: False
    x = d + pd.Timedelta(days=1)
    while x.weekday() >= 5 or hol(x.date()) or (x.month == 12 and x.day == 31) or (x.month == 1 and x.day <= 3):
        x += pd.Timedelta(days=1)
    return x


def bands(P: dict, asof: pd.Timestamp, univ: pd.Series) -> pd.DataFrame:
    """asof（最後の取引日）までの株価から、翌営業日の「買いの価格帯」を銘柄ごとに出す"""
    C, L, H = P["close"].loc[:asof], P["low"].loc[:asof], P["high"].loc[:asof]
    if asof not in C.index:
        raise ValueError(f"{asof.date()} の株価がありません")
    r = C / C.shift(1) - 1
    sd90 = r.iloc[-90:].std(ddof=1).where(r.iloc[-90:].notna().sum() >= 60)
    ma20 = C.iloc[-20:].mean().where(C.iloc[-20:].notna().sum() >= 15)
    lowp = L.loc[asof]
    ok = univ.reindex(C.columns).fillna(False).astype(bool) & C.loc[asof].notna() & lowp.notna() & sd90.notna() & ma20.notna()
    df = pd.DataFrame({"終値": C.loc[asof], "前日安値": lowp, "σ90_pct": sd90 * 100, "20日線": ma20, "前日高値": H.loc[asof]})[ok]
    for k in KS:
        df[f"上限_k{k:g}"] = df["前日安値"] * (1 - k * df["σ90_pct"] / 100)
        df[f"候補_k{k:g}"] = df[f"上限_k{k:g}"] > df["20日線"]
    for k in KS:   # 売り側：始値が「売り下限」より上、20日線より下なら条件成立
        df[f"売り下限_k{k:g}"] = df["前日高値"] * (1 + k * df["σ90_pct"] / 100)
        df[f"売り候補_k{k:g}"] = df[f"売り下限_k{k:g}"] < df["20日線"]
    return df


def open_rule(o: float, low_prev: float, sd: float, ma: float, k: float) -> bool:
    return np.isfinite(o) and o < low_prev * (1 - k * sd / 100) and o > ma


def today() -> pd.Timestamp:
    return pd.Timestamp(dt.date.today())


# ------------------------------------------------------------------ 決算発表日（決算翌日の印）
def _jpx_schedule() -> pd.DataFrame:
    """JPX「決算発表予定日」Excel（kessanMM_MMDD.xlsx）。同じ決算期の版が複数あれば「現在」日付の新しい方"""
    files = sorted(set(BASE.glob("kessan*.xlsx")) | set((BASE / "決算発表予定日").glob("*.xlsx")))
    best = {}
    for f in files:
        try:
            x = pd.read_excel(f, header=None)
        except Exception:
            continue
        title = str(x.iat[0, 0]); asof_txt = str(x.iat[2, 0])
        m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", asof_txt)
        a = pd.Timestamp(int(m[1]), int(m[2]), int(m[3])) if m else pd.Timestamp(f.stat().st_mtime, unit="s")
        if title not in best or a > best[title][0]:
            best[title] = (a, x)
    rows = []
    for a, x in best.values():
        y = x.iloc[5:, :2].copy(); y.columns = ["date", "code"]
        y["date"] = pd.to_datetime(y["date"], errors="coerce")
        y["code"] = y["code"].astype(str).str.strip().str.upper()
        rows.append(y[y["date"].notna() & y["code"].str.fullmatch(r"\d{3}[0-9A-Z]")])
    return pd.concat(rows) if rows else pd.DataFrame(columns=["date", "code"])


def _jq_disclosures() -> pd.DataFrame:
    """J-Quants 決算サマリーの実際の開示日（決算短信のみ）"""
    import glob, json
    rows = []
    for f in sorted(glob.glob(str(JQ_SUM / "*.json"))):
        try:
            for r in json.load(open(f)):
                dt_ = str(r.get("DocType", ""))
                if "FinancialStatements" in dt_ and dt_[:2] in ("1Q", "2Q", "3Q", "FY"):
                    rows.append((r["DiscDate"], str(r["Code"])[:4]))
        except Exception:
            continue
    d = pd.DataFrame(rows, columns=["date", "code"]); d["date"] = pd.to_datetime(d["date"])
    return d


_EARN = None
def earnings_dates() -> pd.DataFrame:
    global _EARN
    if _EARN is None:
        _EARN = pd.concat([_jpx_schedule(), _jq_disclosures()]).drop_duplicates()
    return _EARN


def earnings_flag(codes, asof: pd.Timestamp, target: pd.Timestamp) -> pd.Series:
    """判断日 asof 〜 対象日の前日 に決算発表（予定）がある銘柄 = True（大引け後の発表が対象日の寄りに出る）"""
    e = earnings_dates()
    hit = set(e.loc[(e["date"] >= asof) & (e["date"] < target), "code"])
    return pd.Series([c in hit for c in codes], index=codes)


def earnings_coverage(target: pd.Timestamp) -> str:
    """発表日のデータが対象日まで届いているか（JPX予定表の最終日）"""
    j = _jpx_schedule()
    return str(j["date"].max().date()) if len(j) else "なし"
