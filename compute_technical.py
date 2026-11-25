#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SBI証券のスクリーナーにある「株価パフォーマンス」「テクニカル」系の指標を、
手元の株価データ（data/prices/*.csv）から全銘柄ぶん計算する

    ./.venv/bin/python compute_technical.py

出力: fundamentals/technical.csv（1銘柄1行。通信なし・約1分）

■ 株価パフォーマンス
  前日比(円) / 前日比(%)         終値の前日比
  5日騰落率(%) / 20日騰落率(%)   5・20営業日前の終値との比較（1週・4週）
  対市場超過(1日)(%pt) / 対市場超過(20日)(%pt)
                                 同じ期間の市場（プライムの時価総額加重＝TOPIX相当）との差。
                                 SBIの「日経平均の値上がり率上回り／値下がり率下回り」の代わり
  売買代金(百万円)               最新日の 終値×出来高（VWAPが無いので近似）
  平均売買代金(百万円)           直近25営業日の平均
  売買代金増加率(%)              最新日の売買代金 ÷ 25日平均 − 1
  出来高増加率(%)                最新日の出来高 ÷ 前日の出来高 − 1
  出来高倍率(6日/25日)           直近6日の平均出来高 ÷ 25日平均（SBIの「出来高平均6日/25日倍率」）
  60日ボラティリティ(%)          直近60営業日の日次リターンの標準偏差を年率換算
  52週安値からの上昇率(%)        終値 ÷ 過去250営業日の安値 − 1
  年初来高値からの日数 / 年初来安値からの日数
                                 今年の高値（安値）を最後に更新してからの営業日数。0＝最新日に更新
  年初来高値乖離(%) / 年初来安値からの上昇率(%)

■ テクニカル
  GC(5×25)からの日数 など        短期線が長期線を上抜けて（GC）／下抜けて（DC）から何営業日か。
                                 いまその状態が続いている銘柄だけ値が入る。0＝最新日にクロス
                                 ①5日×25日 ②25日×75日 ③75日×200日
  一目 雲の位置                  1＝雲の上・0＝雲の中・−1＝雲の下（転換9・基準26・先行52）
  雲上抜けからの日数 / 雲下抜けからの日数
  ボリンジャー位置(σ)            (終値−25日平均) ÷ 25日標準偏差。+2以上は+2σ超え
  RSI(14)(%)                     ワイルダー方式
  RCI(9)(%) / RCI(26)(%)
  ストキャス%K(9) / ストキャス%D / スローストキャス%D
  +DI(14) / −DI(14) / ADX(14)    DMI
  サイコロジカル(12)(%)          直近12日のうち上がった日の割合
  MACDヒストグラム(%)            (MACD−シグナル) ÷ 終値。MACD(12,26)・シグナル9
  MACD GCからの日数              MACDがシグナルを上抜けてからの日数
  新値3本足                      1＝陽線（上昇基調）・−1＝陰線
  新値3本足の転換からの日数
  ベータ(対業種)(1年)            東証33業種の時価総額加重リターンに対するベータ
  ドル円感応度(2年)              週次リターンでドル円に回帰した係数。+なら円安で上がりやすい
                                 （ドル円のデータは ドル円モデル/usdjpy_ohlc.csv を使う）

株式分割・併合が株価に反映されていない日（1日で±50%超の動き）があると指標が壊れるので、
その日より後のデータだけで計算する（足りなければその指標は空欄）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
PRICES = BASE / "data" / "prices"
LATEST = BASE / "fundamentals" / "fundamentals_latest.csv"
USDJPY = BASE / "ドル円モデル" / "usdjpy_ohlc.csv"
OUT = BASE / "fundamentals" / "technical.csv"

PRICE_MAX = 1_000_000
MAX_DAILY_MOVE = 0.5
STALE_DAYS = 10
KEEP_DAYS = 520            # 計算に使う直近の営業日数（200日線のクロスを約1年さかのぼれる分）
CROSSES = ((5, 25, "5×25"), (25, 75, "25×75"), (75, 200, "75×200"))


# ---------------------------------------------------------------- 小道具
def run_len(state: np.ndarray) -> int | None:
    """最後の要素がTrueなら、Trueが何日続いているか−1（0＝最新日に成立）。Falseなら None"""
    if len(state) == 0 or not state[-1]:
        return None
    f = np.flatnonzero(~state)
    return int(len(state) - 1 - f[-1] - 1) if len(f) else int(len(state) - 1)


def wilder(x: np.ndarray, n: int) -> np.ndarray:
    """ワイルダーの平滑化（RSI・DMIで使う）"""
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    out[n - 1] = np.nanmean(x[:n])
    for i in range(n, len(x)):
        out[i] = out[i - 1] + (x[i] - out[i - 1]) / n
    return out


def ema(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x).ewm(span=n, adjust=False).mean().to_numpy()


def rci(c: np.ndarray, n: int) -> float:
    if len(c) < n:
        return np.nan
    w = c[-n:]
    price_rank = pd.Series(w).rank(ascending=False, method="average").to_numpy()
    date_rank = np.arange(n, 0, -1)          # 最新日＝1位
    d2 = ((date_rank - price_rank) ** 2).sum()
    return (1 - 6 * d2 / (n * (n * n - 1))) * 100


def three_line_break(c: np.ndarray):
    """新値3本足。(現在の向き 1/−1, 転換からの日数) を返す"""
    if len(c) < 10:
        return np.nan, np.nan
    lines = []                 # (low, high, color)
    turn_i = 0
    p0 = c[0]
    for i in range(1, len(c)):
        x = c[i]
        if not lines:
            if x > p0:
                lines.append((p0, x, 1)); turn_i = i
            elif x < p0:
                lines.append((x, p0, -1)); turn_i = i
            continue
        lo, hi, col = lines[-1]
        last3 = lines[-3:]
        if col == 1:
            if x > hi:
                lines.append((hi, x, 1))
            elif x < min(l[0] for l in last3):
                lines.append((x, lo, -1)); turn_i = i
        else:
            if x < lo:
                lines.append((x, lo, -1))
            elif x > max(l[1] for l in last3):
                lines.append((hi, x, 1)); turn_i = i
    if not lines:
        return np.nan, np.nan
    return lines[-1][2], len(c) - 1 - turn_i


def cap_weighted(ret: pd.DataFrame, w: pd.Series) -> pd.Series:
    cols = [c for c in ret.columns if c in w.index]
    r, ww = ret[cols], w[cols]
    mask = r.notna()
    den = mask.mul(ww, axis=1).sum(axis=1)
    num = r.fillna(0).mul(ww, axis=1).sum(axis=1)
    return (num / den.replace(0, np.nan))


def beta_of(y: pd.Series, x: pd.Series, min_n: int) -> float:
    p = pd.concat([y, x], axis=1, join="inner").dropna()
    if len(p) < min_n:
        return np.nan
    v = p.iloc[:, 1].var()
    return p.iloc[:, 0].cov(p.iloc[:, 1]) / v if v else np.nan


# ---------------------------------------------------------------- 1銘柄
def load(f: Path, latest: pd.Timestamp):
    try:
        d = pd.read_csv(f)
    except Exception:
        return None
    if "close" not in d.columns:
        return None
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    d = d.dropna(subset=["date"]).drop_duplicates("date", keep="last").sort_values("date")
    for k in ("open", "high", "low", "close", "volume"):
        d[k] = pd.to_numeric(d[k], errors="coerce") if k in d.columns else np.nan
    d = d[(d["close"] > 0) & (d["close"] <= PRICE_MAX)]
    if len(d) < 30 or (latest - d["date"].iloc[-1]).days > STALE_DAYS:
        return None
    d = d.iloc[-KEEP_DAYS:].reset_index(drop=True)
    # 高値・安値が無い（または壊れている）日は終値で代える
    for k in ("high", "low"):
        bad = ~((d[k] > 0) & (d[k] <= PRICE_MAX))
        d.loc[bad, k] = d.loc[bad, "close"]
    d["high"] = d[["high", "close"]].max(axis=1)
    d["low"] = d[["low", "close"]].min(axis=1)
    # 分割・併合が反映されていない日があれば、その日以降だけを使う
    move = d["close"].pct_change().abs()
    jumps = np.flatnonzero(move.to_numpy() > MAX_DAILY_MOVE)
    if len(jumps):
        d = d.iloc[jumps[-1]:].reset_index(drop=True)
    return d


def indicators(d: pd.DataFrame, year_start: pd.Timestamp) -> dict:
    c = d["close"].to_numpy(float)
    h = d["high"].to_numpy(float)
    lo = d["low"].to_numpy(float)
    v = d["volume"].to_numpy(float)
    n = len(c)
    r = {}
    rnd = lambda x, k=2: None if x is None or not np.isfinite(x) else round(float(x), k)

    # --- 株価パフォーマンス ---
    if n >= 2:
        r["前日比(円)"] = rnd(c[-1] - c[-2], 1)
        r["前日比(%)"] = rnd((c[-1] / c[-2] - 1) * 100)
    if n >= 6:
        r["5日騰落率(%)"] = rnd((c[-1] / c[-6] - 1) * 100)
    if n >= 21:
        r["20日騰落率(%)"] = rnd((c[-1] / c[-21] - 1) * 100)
    if n >= 25 and np.isfinite(v[-25:]).sum() >= 20:
        tv = c * v / 1e6
        avg25 = np.nanmean(tv[-25:])
        r["売買代金(百万円)"] = rnd(tv[-1], 1)
        r["平均売買代金(百万円)"] = rnd(avg25, 1)
        if avg25 > 0:
            r["売買代金増加率(%)"] = rnd((tv[-1] / avg25 - 1) * 100, 1)
        v25 = np.nanmean(v[-25:])
        if v25 > 0:
            r["出来高倍率(6日/25日)"] = rnd(np.nanmean(v[-6:]) / v25)
        if v[-2] > 0:
            r["出来高増加率(%)"] = rnd((v[-1] / v[-2] - 1) * 100, 1)
    if n >= 61:
        dr = np.diff(np.log(c[-61:]))
        r["60日ボラティリティ(%)"] = rnd(dr.std(ddof=1) * np.sqrt(252) * 100, 1)
    if n >= 250:
        r["52週安値からの上昇率(%)"] = rnd((c[-1] / lo[-250:].min() - 1) * 100, 1)
    ytd = (d["date"] >= year_start).to_numpy()
    if ytd.sum() >= 1 and (~ytd).sum() >= 0:
        k = np.flatnonzero(ytd)
        hh, ll = h[k], lo[k]
        # 年初来高値（安値）を最後に更新した日＝その日までの今年の最高値（最安値）に並んだ日
        hi_idx = np.flatnonzero(hh >= np.maximum.accumulate(hh))[-1]
        lo_idx = np.flatnonzero(ll <= np.minimum.accumulate(ll))[-1]
        r["年初来高値からの日数"] = int(len(k) - 1 - hi_idx)
        r["年初来安値からの日数"] = int(len(k) - 1 - lo_idx)
        r["年初来高値乖離(%)"] = rnd((c[-1] / hh.max() - 1) * 100)
        r["年初来安値からの上昇率(%)"] = rnd((c[-1] / ll.min() - 1) * 100)

    # --- 移動平均線のクロス ---
    cs = pd.Series(c)
    for s, l, tag in CROSSES:
        if n >= l + 1:
            ms = cs.rolling(s).mean().to_numpy()
            ml = cs.rolling(l).mean().to_numpy()
            ok = ~np.isnan(ml)
            up = (ms > ml)[ok]
            r[f"GC({tag})からの日数"] = run_len(up)
            r[f"DC({tag})からの日数"] = run_len(~up)

    # --- 一目均衡表 ---
    if n >= 52 + 26 + 1:
        hs, ls = pd.Series(h), pd.Series(lo)
        tenkan = (hs.rolling(9).max() + ls.rolling(9).min()) / 2
        kijun = (hs.rolling(26).max() + ls.rolling(26).min()) / 2
        spanA = ((tenkan + kijun) / 2).shift(26)
        spanB = ((hs.rolling(52).max() + ls.rolling(52).min()) / 2).shift(26)
        top = np.fmax(spanA.to_numpy(), spanB.to_numpy())
        bot = np.fmin(spanA.to_numpy(), spanB.to_numpy())
        ok = ~np.isnan(top)
        above, below = (c > top)[ok], (c < bot)[ok]
        r["一目 雲の位置"] = 1 if above[-1] else (-1 if below[-1] else 0)
        r["雲上抜けからの日数"] = run_len(above)
        r["雲下抜けからの日数"] = run_len(below)

    # --- ボリンジャーバンド ---
    if n >= 25:
        w = c[-25:]
        sd = w.std(ddof=0)
        if sd > 0:
            r["ボリンジャー位置(σ)"] = rnd((c[-1] - w.mean()) / sd)

    # --- RSI ---
    if n >= 15:
        diff = np.diff(c)
        g = wilder(np.where(diff > 0, diff, 0.0), 14)
        ls_ = wilder(np.where(diff < 0, -diff, 0.0), 14)
        if np.isfinite(g[-1]) and (g[-1] + ls_[-1]) > 0:
            r["RSI(14)(%)"] = rnd(100 * g[-1] / (g[-1] + ls_[-1]), 1)

    # --- RCI ---
    r["RCI(9)(%)"] = rnd(rci(c, 9), 1)
    r["RCI(26)(%)"] = rnd(rci(c, 26), 1)

    # --- ストキャスティクス ---
    if n >= 9 + 6:
        hh9 = pd.Series(h).rolling(9).max()
        ll9 = pd.Series(lo).rolling(9).min()
        rng = (hh9 - ll9).replace(0, np.nan)
        k = (pd.Series(c) - ll9) / rng * 100
        # %D・SD は分子分母を別々に3日合計する一般的な作り方
        num = (pd.Series(c) - ll9).rolling(3).sum()
        den = (hh9 - ll9).rolling(3).sum().replace(0, np.nan)
        dline = num / den * 100
        sd_ = dline.rolling(3).mean()
        r["ストキャス%K(9)"] = rnd(k.iloc[-1], 1)
        r["ストキャス%D"] = rnd(dline.iloc[-1], 1)
        r["スローストキャス%D"] = rnd(sd_.iloc[-1], 1)

    # --- DMI ---
    if n >= 14 * 3:
        up = h[1:] - h[:-1]
        dn = lo[:-1] - lo[1:]
        pdm = np.where((up > dn) & (up > 0), up, 0.0)
        mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
        tr = np.maximum.reduce([h[1:] - lo[1:], np.abs(h[1:] - c[:-1]), np.abs(lo[1:] - c[:-1])])
        atr = wilder(tr, 14)
        with np.errstate(divide="ignore", invalid="ignore"):
            pdi = 100 * wilder(pdm, 14) / atr
            mdi = 100 * wilder(mdm, 14) / atr
            dx = 100 * np.abs(pdi - mdi) / (pdi + mdi)
        dx = np.where(np.isfinite(dx), dx, np.nan)
        start = np.flatnonzero(np.isfinite(dx))
        if len(start) >= 14:
            adx = wilder(dx[start[0]:], 14)
            r["+DI(14)"] = rnd(pdi[-1], 1)
            r["−DI(14)"] = rnd(mdi[-1], 1)
            r["ADX(14)"] = rnd(adx[-1], 1)

    # --- サイコロジカルライン ---
    if n >= 13:
        r["サイコロジカル(12)(%)"] = rnd((np.diff(c[-13:]) > 0).mean() * 100, 1)

    # --- MACD ---
    if n >= 26 + 9 + 5:
        macd = ema(c, 12) - ema(c, 26)
        sig = ema(macd, 9)
        r["MACDヒストグラム(%)"] = rnd((macd[-1] - sig[-1]) / c[-1] * 100, 3)
        r["MACD GCからの日数"] = run_len((macd > sig)[26:])

    # --- 新値3本足 ---
    col, days = three_line_break(c[-250:])
    if np.isfinite(col):
        r["新値3本足"] = int(col)
        r["新値3本足の転換からの日数"] = int(days)
    return r


# ---------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description="テクニカル指標を計算する")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    files = sorted(PRICES.glob("*.csv"))
    if not files:
        print(f"{PRICES} に株価データがありません。", file=sys.stderr)
        return 1
    latest = max(pd.to_datetime(pd.read_csv(f, usecols=["date"])["date"].iloc[-1])
                 for f in files[:200])
    year_start = pd.Timestamp(latest.year, 1, 1)

    rows, closes = [], {}
    for i, f in enumerate(files, 1):
        d = load(f, latest)
        if d is None:
            continue
        rec = {"コード": f.stem, "テクニカルの基準日": d["date"].iloc[-1].strftime("%Y-%m-%d")}
        rec.update(indicators(d, year_start))
        rows.append(rec)
        closes[f.stem] = d.set_index("date")["close"]
        if i % 1000 == 0:
            print(f"  {i:,}/{len(files):,}", file=sys.stderr)
    out = pd.DataFrame(rows).set_index("コード")

    # --- 市場・業種との比較（時価総額加重） ---
    px = pd.DataFrame(closes).sort_index()
    ret = px.pct_change(fill_method=None)
    ret = ret.mask(ret.abs() > MAX_DAILY_MOVE)
    if LATEST.exists():
        info = pd.read_csv(LATEST, encoding="utf-8-sig", dtype={"コード": str})
        info = info[info["時価総額"].notna() & (info["時価総額"] > 0)]
        w = info.set_index("コード")["時価総額"].astype(float)
        prime = info.loc[info["市場"] == "プライム", "コード"]
        mkt = cap_weighted(ret, w[w.index.isin(prime)])
        lr = np.log1p(ret)
        m1 = mkt.iloc[-1] * 100
        m20 = (np.expm1(np.log1p(mkt).iloc[-20:].sum())) * 100
        s20 = np.expm1(lr.iloc[-20:].sum(min_count=18)) * 100
        out["対市場超過(1日)(%pt)"] = (ret.iloc[-1] * 100 - m1).round(2)
        out["対市場超過(20日)(%pt)"] = (s20 - m20).round(2)
        print(f"市場（プライム時価総額加重）: 1日 {m1:+.2f}% ／ 20日 {m20:+.2f}%")

        # 業種ベータ（1年）
        sec = info.set_index("コード")["業種"]
        last250 = ret.iloc[-250:]
        sb = {}
        for s, codes in sec.groupby(sec):
            members = [c for c in codes.index if c in last250.columns]
            if len(members) < 3:
                continue
            sr = cap_weighted(last250[members], w[members])
            for c in members:
                sb[c] = beta_of(last250[c], sr, 200)
        out["ベータ(対業種)(1年)"] = pd.Series(sb).round(2)

    # --- ドル円感応度（週次・2年） ---
    if USDJPY.exists():
        fx = pd.read_csv(USDJPY, parse_dates=["date"]).set_index("date")["close"].astype(float)
        fxw = fx.resample("W-FRI").last().pct_change(fill_method=None)
        pw = px.resample("W-FRI").last().pct_change(fill_method=None)
        pw = pw.mask(pw.abs() > MAX_DAILY_MOVE)
        pw = pw[pw.index >= pw.index.max() - pd.Timedelta(days=730)]
        fxw = fxw.reindex(pw.index)
        ok = fxw.notna()
        sens = {}
        v = fxw[ok].var()
        for c in pw.columns:
            y = pw.loc[ok, c]
            m = y.notna()
            if m.sum() >= 52 and v:
                sens[c] = np.cov(y[m], fxw[ok][m])[0, 1] / fxw[ok][m].var()
        out["ドル円感応度(2年)"] = pd.Series(sens).round(2)
        print(f"ドル円感応度: {len(sens):,}銘柄（{fx.index.min():%Y-%m}〜{fx.index.max():%Y-%m}の週次）")
    else:
        print(f"※ {USDJPY} が無いのでドル円感応度は空欄", file=sys.stderr)

    out = out.reset_index()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out, index=False, encoding="utf-8-sig")
    print(f"テクニカル指標: {len(out):,}銘柄（基準日 {latest:%Y-%m-%d}）→ {args.out}")
    for k in ("GC(5×25)からの日数", "RSI(14)(%)", "一目 雲の位置", "新値3本足"):
        if k in out:
            print(f"  {k}: {int(out[k].notna().sum()):,}銘柄")
    return 0


if __name__ == "__main__":
    sys.exit(main())
