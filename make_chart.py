#!/usr/bin/env python3
"""銘柄CSVからチャート(ローソク足＋ボリンジャーバンド＋移動平均＋出来高)を作成する。

使い方:
    python3 make_chart.py 7203            # 直近6ヶ月
    python3 make_chart.py 7203 6758 --months 12
"""
import argparse, csv, os, sys
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.ticker import FuncFormatter

BASE = os.path.dirname(os.path.abspath(__file__))
PRICES = os.path.join(BASE, "data", "prices")
OUTDIR = os.path.join(BASE, "data", "charts")

from matplotlib import font_manager as _fm
_avail = {f.name for f in _fm.fontManager.ttflist}
for _f in ["Hiragino Sans", "Noto Sans CJK JP", "IPAexGothic", "Noto Sans JP", "Droid Sans Fallback"]:
    if _f in _avail:
        matplotlib.rcParams["font.family"] = [_f, "DejaVu Sans"]
        break
matplotlib.rcParams["axes.unicode_minus"] = False


def load_names():
    path = os.path.join(BASE, "tickers", "prime_tickers.csv")
    names = {}
    try:
        with open(path, encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                names[str(row["code"]).strip()] = row["name"].strip()
    except Exception:
        pass
    return names


def build(code, months, names):
    src = os.path.join(PRICES, f"{code}.csv")
    if not os.path.exists(src):
        print(f"[skip] {code}: CSVがありません")
        return None
    df = pd.read_csv(src, parse_dates=["date"]).sort_values("date").reset_index(drop=True)

    # 指標は全期間で計算してから表示範囲を切り出す（端の欠損を防ぐ）
    df["ma5"] = df["close"].rolling(5).mean()
    df["ma25"] = df["close"].rolling(25).mean()
    df["ma75"] = df["close"].rolling(75).mean()
    mid = df["close"].rolling(20).mean()
    sd = df["close"].rolling(20).std(ddof=0)
    df["bb_mid"], df["bb_u1"], df["bb_l1"] = mid, mid + sd, mid - sd
    df["bb_u2"], df["bb_l2"] = mid + 2 * sd, mid - 2 * sd

    end = df["date"].iloc[-1]
    start = end - pd.DateOffset(months=months)
    d = df[df["date"] >= start].reset_index(drop=True)
    if len(d) < 5:
        print(f"[skip] {code}: データが不足しています")
        return None

    x = range(len(d))
    fig, (ax, axv) = plt.subplots(
        2, 1, figsize=(14, 8), sharex=True,
        gridspec_kw={"height_ratios": [3.2, 1], "hspace": 0.06})
    fig.patch.set_facecolor("white")

    # ボリンジャーバンド
    ax.fill_between(x, d["bb_l2"], d["bb_u2"], color="#4A6FA5", alpha=0.10, lw=0, label="BB ±2σ")
    ax.fill_between(x, d["bb_l1"], d["bb_u1"], color="#4A6FA5", alpha=0.16, lw=0, label="BB ±1σ")
    for col in ["bb_u2", "bb_l2"]:
        ax.plot(x, d[col], color="#4A6FA5", lw=0.8, ls="--", alpha=0.7)
    ax.plot(x, d["bb_mid"], color="#4A6FA5", lw=1.0, alpha=0.9, label="BB 中心線 (20日)")

    # ローソク足
    for i, r in d.iterrows():
        up = r["close"] >= r["open"]
        c = "#D14343" if up else "#2E7D6B"
        ax.vlines(i, r["low"], r["high"], color=c, lw=0.8, zorder=3)
        lo, h = min(r["open"], r["close"]), abs(r["close"] - r["open"])
        ax.add_patch(Rectangle((i - 0.32, lo), 0.64, h if h else (r["high"] - r["low"]) * 0.004 or 0.01,
                               facecolor=c if up else c, edgecolor=c, lw=0.6, zorder=4))

    ax.plot(x, d["ma5"], color="#E8A33D", lw=1.2, label="5日移動平均", zorder=5)
    ax.plot(x, d["ma25"], color="#3A7CA5", lw=1.2, label="25日移動平均", zorder=5)
    ax.plot(x, d["ma75"], color="#8E5BA6", lw=1.2, label="75日移動平均", zorder=5)

    last = d.iloc[-1]
    prev = d.iloc[-2]["close"]
    chg = last["close"] - prev
    pct = chg / prev * 100 if prev else 0
    name = names.get(str(code), "")
    ax.set_title(f"{code} {name}   終値 {last['close']:,.1f}  "
                 f"({chg:+,.1f} / {pct:+.2f}%)   {last['date']:%Y-%m-%d}",
                 fontsize=15, loc="left", pad=12)
    ax.legend(loc="upper left", fontsize=9, ncol=3, framealpha=0.9)
    ax.grid(alpha=0.25, lw=0.6)
    ax.set_ylabel("株価 (円)")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, p: f"{v:,.0f}"))
    ax.axhline(last["close"], color="#999", lw=0.7, ls=":")

    vc = ["#D14343" if c >= o else "#2E7D6B" for o, c in zip(d["open"], d["close"])]
    axv.bar(x, d["volume"], color=vc, alpha=0.55, width=0.7)
    axv.set_ylabel("出来高")
    axv.grid(alpha=0.25, lw=0.6)
    axv.yaxis.set_major_formatter(FuncFormatter(
        lambda v, p: f"{v/1e6:,.1f}M" if v >= 1e6 else f"{v/1e3:,.0f}K"))

    step = max(1, len(d) // 12)
    ticks = list(x)[::step]
    axv.set_xticks(ticks)
    axv.set_xticklabels([d["date"].iloc[i].strftime("%y/%m/%d") for i in ticks], rotation=0, fontsize=9)
    axv.set_xlim(-1, len(d))

    os.makedirs(OUTDIR, exist_ok=True)
    out = os.path.join(OUTDIR, f"{code}.png")
    fig.savefig(out, dpi=140, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"[ok] {out}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("codes", nargs="+")
    ap.add_argument("--months", type=int, default=6)
    a = ap.parse_args()
    names = load_names()
    for c in a.codes:
        build(c, a.months, names)
