#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全銘柄のベータ値とボラティリティを、手元の株価データから計算する

ベータは「市場が1%動いたとき、その銘柄が何%動く傾向があるか」。
1を超えると市場より値動きが大きく、1未満だと小さい。

市場の動きにはTOPIXなどの指数を使うのが普通ですが、手元に指数データが無いので、
**プライム全銘柄の時価総額加重リターン**を市場の代わりにしています。
TOPIXも同じ作り（プライム全銘柄の時価総額加重）なので、実質的に同じものになります。

    ./.venv/bin/python compute_beta.py
    ./.venv/bin/python compute_beta.py --years 3 --min-days 200

出力: fundamentals/beta.csv
  コード, ベータ, ベータ(1年), 年率ボラティリティ(%), 250日騰落率(%),
  125日騰落率(%), 52週高値, 52週安値, 52週レンジ位置(%)
  ※52週高安は終値ベース（ザラ場の高値・安値は使っていない）
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
OUT = BASE / "fundamentals" / "beta.csv"

PRICE_MAX = 1_000_000      # make_chart_html.py と同じ異常値の基準
MAX_DAILY_MOVE = 0.5       # 1日で±50%超の変化は株式分割などの可能性が高いので除く


LOOKBACK_DAYS = 250        # 四季報の「値上がり」に合わせた営業日数（およそ1年）
HALF_YEAR_DAYS = 125       # およそ6か月。マルチバガー判定のエントリー条件に使う


def load_returns(years: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """全銘柄の日次リターンを1枚の表にする（列=銘柄、行=日付）。

    ついでに騰落率（250日・125日）と52週高安・レンジ内の位置も返す。
    価格データを2度読まずに済ませるため、ここでまとめて計算している。
    52週レンジ位置は「(現在値−52週安値)÷(52週高値−52週安値)×100」で、
    0%なら年初来安値、100%なら年初来高値。安いほど（0%に近いほど）
    次の1年のリターンが高いというのが論文の主張。"""
    cutoff = pd.Timestamp.today().normalize() - pd.DateOffset(years=years)
    series = {}
    stats = {}
    files = sorted(PRICES.glob("*.csv"))
    for i, f in enumerate(files, 1):
        code = f.stem
        try:
            d = pd.read_csv(f, usecols=["date", "close"])
        except Exception:
            continue
        d["date"] = pd.to_datetime(d["date"], errors="coerce")
        d = d.dropna(subset=["date"])
        d = d[d["date"] >= cutoff]
        c = pd.to_numeric(d["close"], errors="coerce")
        d = d[(c > 0) & (c <= PRICE_MAX)]
        if len(d) < 30:
            continue
        s = d.set_index("date")["close"].astype("float64")
        s = s[~s.index.duplicated(keep="last")]
        series[code] = s
        rec = {}
        last = float(s.iloc[-1])
        if len(s) > LOOKBACK_DAYS:
            # 分割・併合で価格が飛んでいる銘柄は騰落率が実態とかけ離れるので出さない
            span = s.iloc[-(LOOKBACK_DAYS + 1):]
            jump = span.pct_change().abs().max()
            if pd.notna(jump) and jump <= MAX_DAILY_MOVE:
                rec[f"{LOOKBACK_DAYS}日騰落率(%)"] = (last / float(s.iloc[-(LOOKBACK_DAYS + 1)]) - 1) * 100
                win = s.iloc[-LOOKBACK_DAYS:]
                hi, lo = float(win.max()), float(win.min())
                rec["52週高値"], rec["52週安値"] = hi, lo
                if hi > lo:
                    rec["52週レンジ位置(%)"] = (last - lo) / (hi - lo) * 100
        if len(s) > HALF_YEAR_DAYS:
            span6 = s.iloc[-(HALF_YEAR_DAYS + 1):]
            jump6 = span6.pct_change().abs().max()
            if pd.notna(jump6) and jump6 <= MAX_DAILY_MOVE:
                rec[f"{HALF_YEAR_DAYS}日騰落率(%)"] = (last / float(s.iloc[-(HALF_YEAR_DAYS + 1)]) - 1) * 100
        if rec:
            stats[code] = rec
        if i % 500 == 0:
            print(f"  読み込み {i}/{len(files)}", file=sys.stderr)

    px = pd.DataFrame(series).sort_index()
    ret = px.pct_change()
    # 分割・併合が価格に反映されていない日を除く
    ret = ret.mask(ret.abs() > MAX_DAILY_MOVE)
    extra = pd.DataFrame(stats).T
    extra.index.name = "コード"
    return ret, extra


def market_return(ret: pd.DataFrame, weights: pd.Series) -> pd.Series:
    """時価総額加重の市場リターン。TOPIXの作り方に合わせている"""
    cols = [c for c in ret.columns if c in weights.index]
    r, w = ret[cols], weights[cols]
    # その日に値がある銘柄だけで加重平均する（欠損日があっても偏らない）
    mask = r.notna()
    wsum = mask.mul(w, axis=1).sum(axis=1)
    num = r.fillna(0).mul(w, axis=1).sum(axis=1)
    mkt = num / wsum.replace(0, np.nan)
    return mkt.dropna()


def main() -> int:
    ap = argparse.ArgumentParser(description="ベータ値とボラティリティを計算する")
    ap.add_argument("--years", type=int, default=3, help="対象期間（年）")
    ap.add_argument("--min-days", type=int, default=200, help="これ未満の日数なら計算しない")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    if not LATEST.exists():
        print(f"{LATEST} がありません。先に fetch_fundamentals.py を実行してください。",
              file=sys.stderr)
        return 1

    info = pd.read_csv(LATEST, encoding="utf-8-sig", dtype={"コード": str})
    print(f"日次リターンを作成中（直近{args.years}年）…")
    ret, extra = load_returns(args.years)
    print(f"  {ret.shape[1]:,}銘柄 × {ret.shape[0]:,}営業日")
    col250 = f"{LOOKBACK_DAYS}日騰落率(%)"
    col125 = f"{HALF_YEAR_DAYS}日騰落率(%)"
    print(f"  {LOOKBACK_DAYS}営業日前比の騰落率: {int(extra.get(col250, pd.Series(dtype=float)).notna().sum()):,}銘柄"
          f"／{HALF_YEAR_DAYS}営業日前比: {int(extra.get(col125, pd.Series(dtype=float)).notna().sum()):,}銘柄"
          f"／52週レンジ位置: {int(extra.get('52週レンジ位置(%)', pd.Series(dtype=float)).notna().sum()):,}銘柄")

    # 市場＝プライムの時価総額加重。時価総額が無い銘柄は市場側に入れない。
    prime = info[(info["市場"] == "プライム") & info["時価総額"].notna()]
    w = prime.set_index("コード")["時価総額"].astype("float64")
    w = w[w > 0]
    mkt = market_return(ret, w)
    print(f"  市場リターン: プライム{len(set(w.index) & set(ret.columns)):,}銘柄の時価総額加重"
          f"／{len(mkt):,}営業日")

    var_m = mkt.var()
    # 直近1年（LOOKBACK_DAYS営業日）だけのベータも出す。スクリーニングで
    # 「いまの値動きの荒さ」を見たいとき、3年だと古い相場を引きずるため。
    # 標本が1年分しかないので値は振れやすい。
    mkt1 = mkt.iloc[-LOOKBACK_DAYS:]
    var_m1 = mkt1.var()
    rows = []
    for code in ret.columns:
        r = ret[code]
        pair = pd.concat([r, mkt], axis=1, join="inner").dropna()
        if len(pair) < args.min_days:
            continue
        beta = pair.iloc[:, 0].cov(pair.iloc[:, 1]) / var_m if var_m else np.nan
        vol = r.std() * np.sqrt(252) * 100
        p1 = pair.iloc[-LOOKBACK_DAYS:]
        beta1 = (p1.iloc[:, 0].cov(p1.iloc[:, 1]) / var_m1
                 if var_m1 and len(p1) >= LOOKBACK_DAYS * 0.8 else np.nan)
        rows.append({
            "コード": code,
            "ベータ": round(float(beta), 3) if np.isfinite(beta) else None,
            "ベータ(1年)": round(float(beta1), 3) if np.isfinite(beta1) else None,
            "年率ボラティリティ(%)": round(float(vol), 1) if np.isfinite(vol) else None,
            "ベータ使用日数": len(pair),
        })

    out = pd.DataFrame(rows)
    # ベータが出せない銘柄（上場して日が浅いなど）でも騰落率と52週高安は残す
    ex = extra.round({col250: 2, col125: 2, "52週高値": 2, "52週安値": 2,
                      "52週レンジ位置(%)": 1}).reset_index()
    out = out.merge(ex, on="コード", how="outer").sort_values("コード")
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out, index=False, encoding="utf-8-sig")

    b = out["ベータ"].dropna()
    b1 = out["ベータ(1年)"].dropna()
    print(f"\n{len(out):,}銘柄を書き出しました → {args.out}")
    print(f"  1年ベータ: {len(b1):,}銘柄／中央値 {b1.median():.2f}")
    print(f"  ベータの中央値 {b.median():.2f}／四分位 {b.quantile(.25):.2f}〜{b.quantile(.75):.2f}"
          f"／範囲 {b.min():.2f}〜{b.max():.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
