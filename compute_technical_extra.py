#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""スクリーニング定義表（screening_config）の「テクニカル追加分・寄付比・チャート形状・
PER/PBR/配当利回りの変化率」を全銘柄ぶん計算する（通信なし）。

    ./.venv/bin/python compute_technical_extra.py

入力  data/prices/*.csv（日足OHLCV）、fundamentals/fundamentals_latest.csv
出力  fundamentals/technical_extra.csv        1行 = 銘柄
      fundamentals/valuation_history.csv      日々の PER・PBR・配当利回りの控え（直近130営業日）

compute_technical.py（SBI式の指標）とは別ファイルにしてある。株価データの読み込み・
分割の扱いは compute_technical.load をそのまま使う（未反映の分割がある日より後だけで計算）。

■ テクニカル（MarketSpeed II の初期値に合わせた）
  CCI(20)               TP=(高+安+終)/3。(TP − TPの20日平均) ÷ (0.015 × 平均偏差)
  ウィリアムズ%R(14)     (14日高値 − 終値) ÷ (14日高値 − 14日安値) × −100
  ROC(25)               終値 ÷ 25日前終値 × 100
  モメンタム(10)         終値 − 10日前終値（円）
  ATR(14)%              ワイルダー平滑のATR ÷ 終値 × 100
  VR(25)                (上昇日出来高 + 変わらず日/2) ÷ (下落日出来高 + 変わらず日/2) × 100
  強弱Aレシオ(26)        Σ(高値 − 始値) ÷ Σ(始値 − 安値) × 100
  アルーンOSC(14)        アルーン・アップ − アルーン・ダウン
  UOS(7,14,28)          100 × (4×A7 + 2×A14 + A28) ÷ 7
  ボラティリティレシオ(14) 当日TR ÷ (14日高値 − 14日安値)
  DPO(20)               終値 − 11日前時点の20日単純平均（円）
  HLバンド位置(20)       (終値 − 20日安値) ÷ (20日高値 − 20日安値) × 100
  エンベロープ乖離(25)   (終値 − 25日平均) ÷ 25日平均 × 100
  パラボリック           AF 0.02（刻み0.02・上限0.2）。終値がSARより上なら「上昇」
■ 寄付比騰落率          (終値 − 始値) ÷ 始値 × 100（最新日。ザラ場中ではなく引け後の値）
■ チャート形状（楽天の基準は非公開のため独自定義。期間 20・60・120 営業日）
  R=期間騰落率, R1=前半の騰落率, R2=直近1/4期間の騰落率, W=(期間高値−期間安値)÷期間平均
  上から順に最初に当てはまった形状を採用。どれにも当たらなければ「その他」
    急上昇 R≥+25% / 上昇 +10%≤R<+25% かつ R2≥0 / 上昇ストップ R1≥+10% かつ |R2|<2%
    調整 R1≥+10% かつ R2≤−5% / もみ合い |R|<5% かつ W<15%
    リバウンド R1≤−10% かつ 期間安値から+10%以上 / 下げとまった R1≤−10% かつ |R2|<2%
    下落 −25%<R≤−10% かつ R2≤0 / 急落 R≤−25%
■ PER・PBR・配当利回りの変化率(20日)
  valuation_history.csv に毎日の値を貯め、20営業日前の実績値と比べる（方式=実績）。
  履歴が足りない間は「1株指標が変わらず株価だけ動いた」とみなす近似（方式=近似）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from compute_technical import PRICES, LATEST, load, wilder

BASE = Path(__file__).resolve().parent
OUT = BASE / "fundamentals" / "technical_extra.csv"
HIST = BASE / "fundamentals" / "valuation_history.csv"
HIST_KEEP = 130
CHG_N = 20
SHAPE_PERIODS = (20, 60, 120)


def rnd(x, k=2):
    return None if x is None or not np.isfinite(x) else round(float(x), k)


def psar(h, lo, af0=0.02, step=0.02, amax=0.2):
    n = len(h)
    if n < 5:
        return None, None
    up = True
    sar, ep, af = lo[0], h[0], af0
    for i in range(1, n):
        sar = sar + af * (ep - sar)
        if up:
            sar = min(sar, lo[i - 1], lo[i - 2] if i >= 2 else lo[i - 1])
            if lo[i] < sar:
                up, sar, ep, af = False, ep, lo[i], af0
            elif h[i] > ep:
                ep, af = h[i], min(af + step, amax)
        else:
            sar = max(sar, h[i - 1], h[i - 2] if i >= 2 else h[i - 1])
            if h[i] > sar:
                up, sar, ep, af = True, ep, h[i], af0
            elif lo[i] < ep:
                ep, af = lo[i], min(af + step, amax)
    return ("上昇" if up else "下降"), sar


def shape(c, h, lo, n):
    if len(c) < n + 1:
        return None
    w = c[-(n + 1):]
    hh, ll = h[-n:].max(), lo[-n:].min()
    r = w[-1] / w[0] - 1
    half = n // 2
    r1 = w[half] / w[0] - 1
    q = max(1, n // 4)
    r2 = w[-1] / w[-1 - q] - 1
    width = (hh - ll) / w.mean()
    from_low = w[-1] / ll - 1 if ll > 0 else np.nan
    if r >= 0.25:
        return "急上昇"
    if 0.10 <= r < 0.25 and r2 >= 0:
        return "上昇"
    if r1 >= 0.10 and abs(r2) < 0.02:
        return "上昇ストップ"
    if r1 >= 0.10 and r2 <= -0.05:
        return "調整"
    if abs(r) < 0.05 and width < 0.15:
        return "もみ合い"
    if r1 <= -0.10 and from_low >= 0.10:
        return "リバウンド"
    if r1 <= -0.10 and abs(r2) < 0.02:
        return "下げとまった"
    if -0.25 < r <= -0.10 and r2 <= 0:
        return "下落"
    if r <= -0.25:
        return "急落"
    return "その他"


def indicators(d: pd.DataFrame) -> dict:
    o = d["open"].to_numpy(float)
    h = d["high"].to_numpy(float)
    lo = d["low"].to_numpy(float)
    c = d["close"].to_numpy(float)
    v = d["volume"].to_numpy(float)
    n = len(c)
    r = {}
    cp = np.r_[np.nan, c[:-1]]
    tr = np.fmax(h, cp) - np.fmin(lo, cp)
    tr[0] = h[0] - lo[0]

    if n >= 1 and o[-1] > 0:
        r["寄付比騰落率(%)"] = rnd((c[-1] / o[-1] - 1) * 100)
    if n >= 20:
        tp = (h + lo + c) / 3
        win = tp[-20:]
        md = np.mean(np.abs(win - win.mean()))
        r["CCI(20)"] = rnd((tp[-1] - win.mean()) / (0.015 * md)) if md > 0 else None
        hh, ll = h[-20:].max(), lo[-20:].min()
        r["HLバンド位置(20)(%)"] = rnd((c[-1] - ll) / (hh - ll) * 100) if hh > ll else None
    if n >= 14:
        hh, ll = h[-14:].max(), lo[-14:].min()
        r["ウィリアムズ%R(14)"] = rnd((hh - c[-1]) / (hh - ll) * -100) if hh > ll else None
        r["ボラティリティレシオ(14)"] = rnd(tr[-1] / (hh - ll), 3) if hh > ll else None
    if n >= 26:
        r["ROC(25)(%)"] = rnd(c[-1] / c[-26] * 100)
    if n >= 11:
        r["モメンタム(10)(円)"] = rnd(c[-1] - c[-11], 1)
    if n >= 15:
        atr = wilder(tr, 14)[-1]
        r["ATR(14)(%)"] = rnd(atr / c[-1] * 100)
    if n >= 26 and np.isfinite(v[-25:]).all():
        dc = np.diff(c[-26:])
        vv = v[-25:]
        up, dn, eq = vv[dc > 0].sum(), vv[dc < 0].sum(), vv[dc == 0].sum()
        den = dn + eq / 2
        r["VR(25)(%)"] = rnd((up + eq / 2) / den * 100) if den > 0 else None
    if n >= 26 and (o[-26:] > 0).all():
        a = (h[-26:] - o[-26:]).sum()
        b = (o[-26:] - lo[-26:]).sum()
        r["強弱Aレシオ(26)(%)"] = rnd(a / b * 100) if b > 0 else None
    if n >= 15:
        hw, lw = h[-15:], lo[-15:]
        # 何日前に14日高値・安値をつけたか
        since_h = 14 - int(np.flatnonzero(hw == hw.max())[-1])
        since_l = 14 - int(np.flatnonzero(lw == lw.min())[-1])
        r["アルーンOSC(14)"] = rnd((14 - since_h) / 14 * 100 - (14 - since_l) / 14 * 100, 1)
    if n >= 29:
        bp = c - np.fmin(lo, cp)
        s = lambda x, k: x[-k:].sum()
        a7, a14, a28 = (s(bp, k) / s(tr, k) if s(tr, k) > 0 else np.nan for k in (7, 14, 28))
        r["UOS(%)"] = rnd(100 * (4 * a7 + 2 * a14 + a28) / 7)
    if n >= 31:
        sma20_back = c[-31:-11].mean()          # 11日前時点の20日平均
        r["DPO(20)(円)"] = rnd(c[-1] - sma20_back, 1)
    if n >= 25:
        m25 = c[-25:].mean()
        r["エンベロープ乖離(25)(%)"] = rnd((c[-1] - m25) / m25 * 100)
    if n >= 10:
        pos, sar = psar(h[-250:], lo[-250:])
        r["パラボリック"] = pos
        r["パラボリックSAR"] = rnd(sar, 1) if sar is not None else None
    for p in SHAPE_PERIODS:
        r[f"チャート形状({p}日)"] = shape(c, h, lo, p)
    return r


# ---------------------------------------------------------------- 変化率

def valuation_changes(latest_date: str) -> pd.DataFrame:
    if not LATEST.exists():
        return pd.DataFrame()
    f = pd.read_csv(LATEST, encoding="utf-8-sig", dtype={"コード": str})
    cur = pd.DataFrame({
        "コード": f["コード"].str.strip(),
        "日付": f.get("株価日付", latest_date).fillna(latest_date) if "株価日付" in f else latest_date,
        "株価": pd.to_numeric(f["株価"], errors="coerce"),
        "PER": pd.to_numeric(f["PER"], errors="coerce"),
        "PBR": pd.to_numeric(f["PBR"], errors="coerce"),
        "配当利回り(%)": pd.to_numeric(f["配当利回り(%)"], errors="coerce"),
    })
    hist = pd.read_csv(HIST, dtype={"コード": str}) if HIST.exists() else pd.DataFrame(columns=cur.columns)
    hist = pd.concat([hist, cur], ignore_index=True) if len(hist) else cur.copy()
    hist = hist.drop_duplicates(["コード", "日付"], keep="last")
    days = sorted(hist["日付"].dropna().unique())[-HIST_KEEP:]
    hist = hist[hist["日付"].isin(days)].sort_values(["コード", "日付"])
    tmp = HIST.with_suffix(".csv.tmp")
    hist.to_csv(tmp, index=False)
    tmp.replace(HIST)

    out = cur.set_index("コード")[[]].copy()
    base_day = days[-1 - CHG_N] if len(days) > CHG_N else None
    if base_day is not None:
        old = hist[hist["日付"] == base_day].set_index("コード")
        mode = "実績"
    else:
        old = None
        mode = "近似"
    curi = cur.set_index("コード")
    for col, name in (("PER", "PER変化率(20日)(%)"), ("PBR", "PBR変化率(20日)(%)"),
                      ("配当利回り(%)", "配当利回り変化率(20日)(%)")):
        if old is not None:
            prev = old[col].reindex(curi.index)
        else:
            prev = pd.Series(np.nan, index=curi.index)
        out[name] = (curi[col] - prev) / prev.where(prev > 0) * 100
    out["変化率の方式"] = mode
    return out


# ---------------------------------------------------------------- 本体

def main() -> int:
    files = sorted(PRICES.glob("*.csv"))
    if not files:
        print(f"{PRICES} に株価データがありません", file=sys.stderr)
        return 1
    latest = max(pd.to_datetime(pd.read_csv(f, usecols=["date"])["date"].iloc[-1]) for f in files[:200])
    rows, back = [], {}
    for i, f in enumerate(files, 1):
        d = load(f, latest)
        if d is None:
            continue
        rec = {"コード": f.stem, "基準日": d["date"].iloc[-1].strftime("%Y-%m-%d")}
        rec.update(indicators(d))
        rows.append(rec)
        c = d["close"].to_numpy(float)
        if len(c) > CHG_N:
            back[f.stem] = c[-1] / c[-1 - CHG_N]
        if i % 1000 == 0:
            print(f"  {i:,}/{len(files):,}", file=sys.stderr)
    out = pd.DataFrame(rows).set_index("コード")

    chg = valuation_changes(latest.strftime("%Y-%m-%d"))
    if not chg.empty:
        out = out.join(chg, how="left")
        # 履歴が足りない間の近似: PER・PBR は株価比で動き、利回りは逆数で動くとみなす
        ratio = pd.Series(back).reindex(out.index)
        approx = out["変化率の方式"] == "近似"
        out.loc[approx, "PER変化率(20日)(%)"] = (ratio - 1) * 100
        out.loc[approx, "PBR変化率(20日)(%)"] = (ratio - 1) * 100
        out.loc[approx, "配当利回り変化率(20日)(%)"] = (1 / ratio - 1) * 100
        for c in ("PER変化率(20日)(%)", "PBR変化率(20日)(%)", "配当利回り変化率(20日)(%)"):
            out[c] = pd.to_numeric(out[c], errors="coerce").round(2)

    out.reset_index().to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"{OUT.relative_to(BASE)}: {len(out)}銘柄（基準日 {latest:%Y-%m-%d}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
