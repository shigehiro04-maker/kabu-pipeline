#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
 html_report.py — ドル円モデルの結果を1枚のWebページに書き出す
================================================================================

usdjpy_model.py から呼ばれます。単体で使うものではありません。

  出力: output/index.html  （画像もフォントも外部参照なしの自己完結ファイル）

  ・スマホでもそのまま読めるレスポンシブ
  ・ダークモード対応（端末の設定に追従）
  ・グラフはSVGなので拡大しても滲まない
  ・外部への通信を一切しないので、オフラインでも開ける
================================================================================
"""

from __future__ import annotations

import html
import io
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# 実行環境のタイムゾーンはUTCのことが多いが、読む人は日本にいる。
# ページ上の時刻は必ず日本時間で表示する。
JST = timezone(timedelta(hours=9))


def now_jst() -> datetime:
    return datetime.now(timezone.utc).astimezone(JST)


# ローソク足に表示する期間（年）。全期間（2022年〜）を1枚に詰めると
# 1本1px以下になって潰れるので、直近だけを描く。
CANDLE_YEARS = 2

# 端末に最初から入っているフォントだけを使う（外部読み込みなし）
FONT_STACK = ('"Hiragino Sans","Hiragino Kaku Gothic ProN","Yu Gothic Medium",'
              '"Yu Gothic","Noto Sans JP","Noto Sans CJK JP","Meiryo",'
              'system-ui,sans-serif')
MONO_STACK = ('"SF Mono","SFMono-Regular","Menlo","Consolas",'
              '"Roboto Mono",monospace')

# グラフのSVGに埋め込むフォント指定。日本語フォントだけを並べ、
# 欧文専用フォント（DejaVu Sans など）を混ぜない。混ぜると日本語フォントが
# 無い端末で中国語字形に落ちる。
SVG_FONT_STACK = ("'Hiragino Sans','Hiragino Kaku Gothic ProN','Yu Gothic Medium',"
                  "'Yu Gothic','Noto Sans JP','Noto Sans CJK JP','Meiryo',"
                  "system-ui,sans-serif")


# ==============================================================================
# matplotlib の図を、レスポンシブなインラインSVGに変換する
# ==============================================================================

# matplotlibが焼き込む色 → ページのテーマ変数への対応表。
# これを差し替えないと、図の文字や軸がライト用の濃い色のまま固定され、
# ダークモードで背景に沈んで読めなくなる。
SVG_COLOR_MAP = {
    "#1f2937": "var(--ink)",     # 本文・回帰線
    "#54635f": "var(--ink2)",    # 軸ラベル
    "#8a9a95": "var(--ink3)",    # 目盛り・補助線
    "#d9e0dd": "var(--rule)",    # グリッド・枠
    "#bc4526": "var(--usd)",     # 実勢レート（赤系）
    "#12907a": "var(--accent)",  # フェアバリュー（緑系）
    "#2f5aa8": "var(--jpy)",     # 補助系列（青系）
    "#8a6a12": "var(--warn)",    # 2年金利差の線（琥珀系）
    "#b7c4bf": "var(--rule2)",   # 右軸の枠線
}


def theme_svg(svg: str) -> str:
    """SVG内の固定色を、ページのCSS変数に置き換えてテーマに追従させる。"""
    for hexcode, varname in SVG_COLOR_MAP.items():
        # matplotlib は大文字/小文字のどちらでも書き出すことがある
        for form in (hexcode, hexcode.upper()):
            svg = svg.replace(form, varname)
    return svg


def fig_to_svg(fig) -> str:
    """Figure を <svg> 文字列にする。幅100%で伸縮するように属性を書き換える。"""
    buf = io.StringIO()
    fig.savefig(buf, format="svg", bbox_inches="tight")
    svg = buf.getvalue()

    # XML宣言とDOCTYPEを落とし、<svg> 以降だけ残す
    svg = svg[svg.index("<svg"):]

    # viewBox が無ければ width/height から作る
    if "viewBox" not in svg:
        m = re.search(r'width="([\d.]+)pt"\s+height="([\d.]+)pt"', svg)
        if m:
            svg = svg.replace("<svg", f'<svg viewBox="0 0 {m.group(1)} {m.group(2)}"', 1)

    # 固定サイズを外して、親要素いっぱいに広がるようにする
    svg = re.sub(r'width="[\d.]+pt"', 'width="100%"', svg, count=1)
    svg = re.sub(r'height="[\d.]+pt"', 'height="auto"', svg, count=1)

    # --- 漢字が中国語の字形になるのを防ぐ -----------------------------------
    # matplotlib は font.sans-serif の既定値を全部つなげて書き出すため、
    # 'DejaVu Sans' など日本語を持たない欧文フォントが日本語フォントの後ろに
    # 並ぶ。日本語フォントが入っていない端末（スマホなど）ではそこを通り抜けて
    # ブラウザ既定のCJKフォント＝簡体字中国語が選ばれ、「直」「値」などが
    # 中国語字形で表示されてしまう。
    # ページ本文と同じ日本語フォントの並びに置き換え、さらに lang="ja" を付けて
    # ブラウザのフォールバックにも日本語を選ばせる。
    svg = re.sub(r'font-family:\s*[^;"]*', f"font-family:{SVG_FONT_STACK}", svg)
    svg = svg.replace("<svg ", '<svg lang="ja" xml:lang="ja" ', 1)
    return theme_svg(svg)


def load_ohlc(csv_path) -> pd.DataFrame | None:
    """
    ローソク足用の四本値（始値・高値・安値・終値）を読み込む。

    data.csv と同じフォルダの usdjpy_ohlc.csv を探す。無ければ None を返し、
    ページはこれまでどおり終値の折れ線だけで作られる（必須ファイルではない）。

    列: date,open,high,low,close
    """
    if not csv_path:
        return None
    p = Path(csv_path).expanduser().parent / "usdjpy_ohlc.csv"
    if not p.exists():
        return None
    try:
        o = pd.read_csv(p, parse_dates=["date"])
    except Exception:
        return None

    need = {"date", "open", "high", "low", "close"}
    if not need.issubset(o.columns):
        return None

    o = o.dropna(subset=["open", "high", "low", "close"]).sort_values("date")
    # 高値・安値が実体をはみ出していない行だけ使う（壊れたデータの混入対策）
    body_hi = o[["open", "close"]].max(axis=1)
    body_lo = o[["open", "close"]].min(axis=1)
    ok = (o["high"] >= body_hi - 1e-9) & (o["low"] <= body_lo + 1e-9) & (o["high"] >= o["low"])
    return o[ok].reset_index(drop=True) if ok.any() else None


def _draw_candles(ax, o: pd.DataFrame, C: dict):
    """
    ローソク足を描く。x は 0,1,2… の連番（日付そのままだと土日が
    すき間になって間延びするため）。上昇＝円安を赤、下落＝円高を青。
    """
    x = np.arange(len(o))
    op = o["open"].to_numpy(); cl = o["close"].to_numpy()
    hi = o["high"].to_numpy();  lo = o["low"].to_numpy()

    up = cl >= op
    colors = np.where(up, C["actual"], C["alt"])

    # ヒゲ（高値〜安値）
    ax.vlines(x, lo, hi, color=colors, linewidth=0.9, zorder=2)

    # 実体。始値と終値が同値だと高さ0で消えてしまうので下限を入れる。
    span = float(np.nanmax(hi) - np.nanmin(lo)) or 1.0
    floor = span * 0.0012
    bottom = np.minimum(op, cl)
    height = np.maximum(np.abs(cl - op), floor)
    ax.bar(x, height, bottom=bottom, width=0.64, color=colors,
           linewidth=0, zorder=3)
    return x


def _month_ticks(dates: pd.Series, min_gap: int = 8):
    """
    月が変わる位置だけを目盛りにする。
    先頭の月が数日しか無いと隣のラベルと重なって潰れるので、
    間隔が min_gap 本未満のものは落とす。
    """
    cand = []
    prev = None
    for i, d in enumerate(dates):
        key = (d.year, d.month)
        if key != prev:
            cand.append((i, f"{d:%Y-%m}"))
            prev = key

    # 「直前に採用した目盛り」から min_gap 本以上離れているものだけ残す。
    # 次の目盛りとの距離で判定すると、間隔が一様に狭いとき全部落ちてしまう。
    pos, lab, last = [], [], None
    for i, l in cand:
        if last is None or i - last >= min_gap:
            pos.append(i); lab.append(l); last = i
    return pos, lab


def build_charts(df: pd.DataFrame, sens: dict, bt: dict, C: dict,
                 ohlc: pd.DataFrame | None = None) -> dict:
    """ページに載せるグラフを作り、SVG文字列の辞書で返す。"""
    import logging
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # 環境に日本語フォントが無いと font_manager が大量に警告を出すので黙らせる。
    # svg.fonttype='none' なので文字はテキストのまま埋まり、
    # 表示側（Macなど）のフォントで描画される。作成環境のフォントは関係ない。
    logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)

    # svg.fonttype='none' にすると、文字が図形化されずテキストのまま残る。
    # ファイルが軽くなり、閲覧側のフォントで綺麗に表示される。
    plt.rcParams.update({
        "svg.fonttype": "none",
        "font.family": "Hiragino Sans, Noto Sans CJK JP, sans-serif",
        "axes.unicode_minus": False,
        "figure.facecolor": "none", "axes.facecolor": "none", "savefig.facecolor": "none",
        "axes.edgecolor": C["grid"], "axes.linewidth": 1.0,
        "axes.grid": True, "grid.color": C["grid"], "grid.linewidth": 0.8,
        "axes.spines.top": False, "axes.spines.right": False,
        "text.color": C["ink"], "axes.labelcolor": C["ink2"],
        "xtick.color": C["ink3"], "ytick.color": C["ink3"],
        "xtick.labelsize": 9, "ytick.labelsize": 9,
        "axes.labelsize": 10,
        "legend.frameon": False, "legend.fontsize": 9.5,
    })

    out = {}
    d = df.dropna(subset=["fair"])

    # --- ローソク足（直近）＋日米金利差 ----------------------------------------
    if ohlc is not None and len(ohlc) > 5:
        # 金利差を日付で突き合わせる（無い日は線が切れるだけ）
        cd = ohlc.merge(df[["date", "spread2", "spread10"]], on="date", how="left")
        cutoff = cd["date"].max() - pd.DateOffset(years=CANDLE_YEARS)
        cd = cd[cd["date"] >= cutoff].reset_index(drop=True)
        x = np.arange(len(cd))

        fig, ax = plt.subplots(figsize=(13, 4.8))
        _draw_candles(ax, cd, C)

        # 縦軸はローソクが収まる範囲
        lo_v = float(cd["low"].min()); hi_v = float(cd["high"].max())
        pad = (hi_v - lo_v) * 0.06 or 0.5
        ax.set_ylim(lo_v - pad, hi_v + pad)
        ax.set_ylabel("ドル/円")
        ax.grid(axis="x", visible=False)

        # 金利差は単位（pt）が違うので右軸にまとめる。2年と10年は同じ単位なので
        # 同じ軸に並べれば水準そのものも比べられる。
        handles, labels = [], []
        series = [("spread2", "日米2年金利差（右軸）", C["warn"]),
                  ("spread10", "日米10年金利差（右軸）", C["fair"])]
        drawn = [(col, lab, col_c) for col, lab, col_c in series
                 if col in cd.columns and cd[col].notna().any()]
        if drawn:
            ax2 = ax.twinx()
            for col, lab, cc in drawn:
                ln, = ax2.plot(x, cd[col], color=cc, lw=1.5, alpha=0.9,
                               label=lab, zorder=5)
                handles.append(ln); labels.append(lab)
            ax2.set_ylabel("金利差 (pt)", color=C["ink2"])
            ax2.tick_params(axis="y", colors=C["ink2"])
            ax2.spines["right"].set_visible(True)
            ax2.spines["right"].set_color(C["rule2"])
            ax2.grid(False)

        # ラベルが10個前後に収まるよう、本数に応じて間引く
        pos, lab = _month_ticks(cd["date"], min_gap=max(8, len(cd) // 11))
        ax.set_xticks(pos); ax.set_xticklabels(lab)
        ax.set_xlim(-1, len(cd))
        if handles:
            ax.legend(handles, labels, loc="lower left", bbox_to_anchor=(0, 1.0),
                      ncol=len(handles), borderaxespad=0)
        out["candle"] = fig_to_svg(fig); plt.close(fig)

    # --- 実勢 vs フェアバリュー ------------------------------------------------
    if len(d) > 5:
        fig, ax = plt.subplots(figsize=(10, 4.2))
        ax.fill_between(d["date"], d["fair"] - d["resid_sd"], d["fair"] + d["resid_sd"],
                        color=C["fair"], alpha=0.14, linewidth=0, label="フェアバリュー ±1σ")
        ax.plot(d["date"], d["fair"], color=C["fair"], lw=2.0, label="フェアバリュー")
        ax.plot(d["date"], d["usdjpy"], color=C["actual"], lw=2.0, label="実勢レート")
        last = d.iloc[-1]
        ax.scatter([last["date"]], [last["usdjpy"]], s=40, color=C["actual"], zorder=5)
        ax.set_ylabel("ドル円")
        ax.set_xlim(d["date"].iloc[0], d["date"].iloc[-1])
        ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=3, borderaxespad=0)
        out["fair"] = fig_to_svg(fig); plt.close(fig)

        # --- 乖離zスコア -------------------------------------------------------
        fig, ax = plt.subplots(figsize=(10, 2.6))
        ax.axhline(0, color=C["ink3"], lw=1.0)
        for lv in (2, -2):
            ax.axhline(lv, color=C["ink3"], lw=0.9, ls="--")
        ax.fill_between(d["date"], 0, d["z"], where=d["z"] >= 0,
                        color=C["actual"], alpha=0.6, linewidth=0)
        ax.fill_between(d["date"], 0, d["z"], where=d["z"] < 0,
                        color=C["alt"], alpha=0.6, linewidth=0)
        ax.set_ylabel("σ")
        ax.set_xlim(d["date"].iloc[0], d["date"].iloc[-1])
        out["dev"] = fig_to_svg(fig); plt.close(fig)

    # --- 感応度の散布図 --------------------------------------------------------
    s = df.dropna(subset=["d_spread2", "d_logfx"])
    if len(s) > 30:
        r = sens["ols"]
        fig, ax = plt.subplots(figsize=(5.6, 4.2))
        ax.axhline(0, color=C["grid"], lw=1); ax.axvline(0, color=C["grid"], lw=1)
        ax.scatter(s["d_spread2"], s["d_logfx"], s=11, color=C["actual"],
                   alpha=0.32, linewidth=0)
        if np.isfinite(r.beta):
            xs = np.linspace(s["d_spread2"].min(), s["d_spread2"].max(), 40)
            ax.plot(xs, r.alpha + r.beta * xs, color=C["ink"], lw=2.0)
        ax.set_xlabel("日米2年金利差の変化 (pt)")
        ax.set_ylabel("ドル円の変化 (%)")
        out["sens"] = fig_to_svg(fig); plt.close(fig)

    # --- バックテスト ----------------------------------------------------------
    fwd = [c for c in df.columns if c.startswith("fwd")]
    if bt.get("ok") and fwd:
        b = df.dropna(subset=["z", fwd[0]])
        fig, ax = plt.subplots(figsize=(5.6, 4.2))
        ax.axhline(0, color=C["grid"], lw=1); ax.axvline(0, color=C["grid"], lw=1)
        ax.scatter(b["z"], b[fwd[0]], s=11, color=C["ink3"], alpha=0.3, linewidth=0)
        bins = pd.cut(b["z"], bins=np.arange(-3.5, 4.0, 1.0))
        g = b.groupby(bins, observed=True)[fwd[0]].mean()
        ax.bar([iv.mid for iv in g.index], g.values, width=0.8,
               color=[C["alt"] if v >= 0 else C["actual"] for v in g.values], alpha=0.9)
        ax.set_xlabel("乖離zスコア（＋＝円安に行き過ぎ）")
        ax.set_ylabel(f"{bt['horizon']}営業日後のリターン (%)")
        out["bt"] = fig_to_svg(fig); plt.close(fig)

    return out


# ==============================================================================
# ページ本体
# ==============================================================================

CSS = """
:root{
  --ground:#F1F4F2; --surface:#FBFCFB; --surface2:#E8EDEA;
  --ink:#141F1C; --ink2:#54635F; --ink3:#7E8D88;
  --rule:#D3DCD8; --rule2:#B7C4BF;
  --accent:#0D6353; --accent-soft:#DCEAE5;
  --usd:#A6392A; --usd-soft:#F6E6E2; --usd-fill:#D79A8C;
  --jpy:#1B5A90; --jpy-soft:#E0EAF3; --jpy-fill:#8FB4D4;
  --warn:#8A6A12; --warn-soft:#F4EDD9;
}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){
  --ground:#0E1614; --surface:#161F1D; --surface2:#1D2724;
  --ink:#E4EBE8; --ink2:#A3B3AE; --ink3:#7E8E89;
  --rule:#2A3633; --rule2:#3F4E4A;
  --accent:#4CBBA3; --accent-soft:#14302B;
  --usd:#E89076; --usd-soft:#34211C; --usd-fill:#8A4E40;
  --jpy:#7FB2DD; --jpy-soft:#182734; --jpy-fill:#3C6488;
  --warn:#D8B75F; --warn-soft:#2C2718;
}}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);font-family:__FONT__;
     font-size:16px;line-height:1.8;-webkit-font-smoothing:antialiased;
     -webkit-text-size-adjust:100%}
.wrap{max-width:1080px;margin:0 auto;padding:0 18px 80px}
h1{font-size:clamp(22px,4.4vw,32px);line-height:1.35;margin:0;font-weight:700;letter-spacing:.01em}
h2{font-size:clamp(17px,3vw,21px);margin:0;font-weight:700}
p{margin:0}
.num{font-family:__MONO__;font-variant-numeric:tabular-nums}
.kick{font-family:__MONO__;font-size:10.5px;font-weight:600;letter-spacing:.16em;
      text-transform:uppercase;color:var(--ink3)}

header{padding:40px 0 26px;display:flex;flex-direction:column;gap:12px}
.meta{display:flex;flex-wrap:wrap;gap:6px 16px;font-family:__MONO__;font-size:12px;color:var(--ink3)}

.verdict{padding:20px 22px;border-radius:2px;display:flex;flex-direction:column;gap:6px;
         border-left:4px solid var(--accent);background:var(--accent-soft)}
.verdict.up{border-left-color:var(--usd);background:var(--usd-soft)}
.verdict.dn{border-left-color:var(--jpy);background:var(--jpy-soft)}
.verdict .lbl{font-family:__MONO__;font-size:11px;letter-spacing:.14em;color:var(--ink2)}
.verdict .val{font-size:clamp(19px,3.6vw,26px);font-weight:700;line-height:1.35}
.verdict .sub{font-size:13.5px;color:var(--ink2);line-height:1.7}

.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
       gap:1px;background:var(--rule);border:1px solid var(--rule);margin-top:26px}
.tile{background:var(--surface);padding:15px 16px 17px;display:flex;flex-direction:column;gap:3px}
.tile dt{font-size:11.5px;color:var(--ink2);margin:0}
.tile dd{margin:0;font-family:__MONO__;font-variant-numeric:tabular-nums;
         font-size:22px;font-weight:500;line-height:1.2}
.tile .u{font-size:12px;font-weight:400}
.tile .s{font-size:10.5px;color:var(--ink3);font-family:__MONO__}
.hi{color:var(--usd)} .lo{color:var(--jpy)} .ac{color:var(--accent)}

section{padding-top:46px;display:flex;flex-direction:column;gap:18px}
.head{display:flex;flex-direction:column;gap:8px;border-bottom:1px solid var(--rule2);padding-bottom:12px}
.note{font-size:13.5px;color:var(--ink2);line-height:1.8;max-width:70ch}
.card{background:var(--surface);border:1px solid var(--rule);padding:16px 14px}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]) .card{background:var(--surface2)}}
.card svg{display:block;width:100%;height:auto}
/* ローソク足は1本1本を潰さないため、狭い画面では横スクロールさせる */
.card.wide{overflow-x:auto;-webkit-overflow-scrolling:touch}
.card.wide>svg{min-width:900px}
.scrollhint{display:none;font-size:12px;color:var(--ink3);margin:6px 0 0}
@media (max-width:980px){.scrollhint{display:block}}
.cap{font-size:12.5px;color:var(--ink3);line-height:1.7;max-width:80ch}
.two{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:18px}

.tw{overflow-x:auto;border:1px solid var(--rule);-webkit-overflow-scrolling:touch}
table{border-collapse:collapse;width:100%;min-width:560px;background:var(--surface);font-size:13.5px}
th,td{padding:12px 14px;text-align:left;border-bottom:1px solid var(--rule);vertical-align:top;line-height:1.7}
thead th{background:var(--surface2);font-size:11.5px;letter-spacing:.05em;color:var(--ink2);
         font-weight:700;border-bottom:1.5px solid var(--rule2);white-space:nowrap}
tbody th{font-weight:500;font-size:13px;white-space:nowrap}
tbody tr:last-child th,tbody tr:last-child td{border-bottom:0}
td.n{font-family:__MONO__;font-variant-numeric:tabular-nums;white-space:nowrap}
.chip{font-family:__MONO__;font-size:11px;font-weight:600;letter-spacing:.06em;
      padding:2px 7px;display:inline-block;white-space:nowrap}
.c-up{background:var(--usd-soft);color:var(--usd)}
.c-dn{background:var(--jpy-soft);color:var(--jpy)}
.c-fl{background:var(--surface2);color:var(--ink2);border:1px solid var(--rule2)}

.score{border-top:1.5px solid var(--ink);border-bottom:1.5px solid var(--ink)}
.row{display:grid;grid-template-columns:130px 1fr 210px;gap:14px 18px;align-items:center;
     padding:14px 0;border-bottom:1px solid var(--rule)}
.row:last-child{border-bottom:0}
.row .lbl{font-size:13.5px;font-weight:700}
.row .txt{font-size:13px;color:var(--ink2);line-height:1.65}
.gauge{display:flex;flex-direction:column;gap:6px}
.meter{display:grid;grid-template-columns:1fr 1fr;height:12px;border:1px solid var(--rule2);
       position:relative;background:var(--surface)}
.meter::after{content:"";position:absolute;left:50%;top:-4px;bottom:-4px;width:1.5px;
              margin-left:-.75px;background:var(--ink2)}
.meter i{display:block;height:100%}
.meter .l{justify-self:end;background:var(--jpy-fill)}
.meter .r{justify-self:start;background:var(--usd-fill)}
.ax{display:grid;grid-template-columns:auto 1fr auto;align-items:baseline;gap:8px;
    font-family:__MONO__;font-size:9.5px;letter-spacing:.1em}
.ax .a{color:var(--jpy)} .ax .b{color:var(--usd);text-align:right}
.ax .v{text-align:center;font-size:10.5px;font-weight:600;letter-spacing:.02em;color:var(--ink)}
@media (max-width:720px){
  .row{grid-template-columns:1fr;gap:8px}
  .row .txt{order:3}
}

.warn{background:var(--warn-soft);border-left:3px solid var(--warn);padding:16px 18px;
      display:flex;flex-direction:column;gap:6px}
.warn .t{font-family:__MONO__;font-size:10.5px;font-weight:600;letter-spacing:.12em;color:var(--warn)}
.warn p{font-size:13.5px;color:var(--ink2);line-height:1.75}
footer{margin-top:56px;padding-top:20px;border-top:1px solid var(--rule);
       font-size:12px;color:var(--ink3);line-height:1.8}
"""


def _tile(label, value, unit="", sub="", cls=""):
    u = f'<span class="u">{unit}</span>' if unit else ""
    s = f'<span class="s">{html.escape(sub)}</span>' if sub else ""
    return (f'<div class="tile"><dt>{html.escape(label)}</dt>'
            f'<dd class="{cls}">{value}{u}</dd>{s}</div>')


def _gauge(value: float, verdict: str) -> str:
    """-100〜+100 を左右のバーにする（＋＝円安側）。"""
    w = min(abs(value), 100.0)
    left = f'<i class="l" style="width:{w:.0f}%"></i><i class="r" style="width:0"></i>'
    right = f'<i class="l" style="width:0"></i><i class="r" style="width:{w:.0f}%"></i>'
    bars = right if value > 0 else left
    return (f'<div class="gauge"><div class="meter">{bars}</div>'
            f'<div class="ax"><span class="a">円高</span>'
            f'<span class="v">{html.escape(verdict)}</span>'
            f'<span class="b">円安</span></div></div>')


def write_html(df, sens, bt, grid, score, args, outdir, score_items):
    """すべての結果を1枚のHTMLにまとめて保存し、パスを返す。"""
    C = {"actual": "#BC4526", "fair": "#12907A", "alt": "#2F5AA8",
         "warn": "#8A6A12",
         "ink": "#1F2937", "ink2": "#54635F", "ink3": "#8A9A95",
         "grid": "#D9E0DD", "rule2": "#B7C4BF"}
    ohlc = load_ohlc(getattr(args, "csv", None))
    charts = build_charts(df, sens, bt, C, ohlc)

    d = df.dropna(subset=["fair"])
    has_fv = len(d) > 0
    last = d.iloc[-1] if has_fv else None
    spot = args.spot if args.spot else sens["spot"]
    demo = bool(getattr(args, "demo", False))

    # ---- 判定バナー ----------------------------------------------------------
    v = score["final"]
    cls = "up" if v >= 20 else ("dn" if v <= -20 else "")
    if abs(v) < 20:
        sub = ("材料が割れています。無理に方向を決めないのが正解です。"
               "こういう局面では、金利差の結論は待つのが安全です。")
    else:
        side = "円安" if v > 0 else "円高"
        sub = (f"5つの材料の重み付き合計が{side}側に傾いています。"
               f"ただし例外フィルター（×{score['exception_factor']:.2f}）を掛けた後の値です。")

    # ---- タイル --------------------------------------------------------------
    # 実勢レートが「いつ時点の値なのか」を必ず添える。
    # --spot で手入力した現在値と、CSVの最終営業日の終値とでは意味が違うため。
    if args.spot:
        asof = getattr(args, "spot_asof", None)
        spot_sub = (f"{asof} 時点" if asof
                    else f"{now_jst():%Y-%m-%d %H:%M} JST 時点（手入力）")
    else:
        spot_sub = f"{df['date'].iloc[-1]:%Y-%m-%d} 終値"
    tiles = [_tile("ドル円（実勢）", f"{spot:.2f}", "", spot_sub, "hi")]
    if has_fv:
        tiles += [
            _tile("フェアバリュー", f"{last['fair']:.2f}", "",
                  f"直近{args.window}日 / {args.method}", "ac"),
            _tile("乖離", f"{last['resid']:+.2f}", "円", "実勢 − フェア"),
            _tile("乖離 zスコア", f"{last['z']:+.2f}", "σ",
                  "±2σ超で行き過ぎ", "hi" if last["z"] > 0 else "lo"),
        ]
    sp = float(df["spread2"].iloc[-1])
    tiles += [
        _tile("日米2年金利差", f"{sp:.2f}", "pt", "米2年 − 日2年"),
        _tile("金利感応度", f"{sens['pct_per_pt']:+.2f}", "%/pt",
              f"10bpで約{sens['yen_per_10bp']:+.2f}円"),
    ]

    # ---- シナリオ表 ----------------------------------------------------------
    rows = []
    for _, r in grid.iterrows():
        dy = r["ドル円の変化(円)"]
        chip = ('<span class="chip c-up">▲ 円安</span>' if dy > 0.05 else
                '<span class="chip c-dn">▼ 円高</span>' if dy < -0.05 else
                '<span class="chip c-fl">— 中立</span>')
        rows.append(
            f'<tr><th scope="row">FRB {r["FOMC"]}<br>日銀 {r["日銀"]}</th>'
            f'<td>{chip}</td>'
            f'<td class="n">{r["金利差の変化(pt)"]:+.4f}</td>'
            f'<td class="n">{dy:+.2f} 円</td>'
            f'<td class="n"><strong>{r["着地水準"]:.2f}</strong></td></tr>')
    scen_rows = "\n".join(rows)

    # ---- スコアカード --------------------------------------------------------
    srows = []
    for name, w, note in score_items:
        val = float(args.score_inputs.get(name, 0))
        pct = val / 2.0 * 100.0
        verd = ("強く円安寄り" if pct >= 60 else "円安寄り" if pct >= 20 else
                "中立" if abs(pct) < 20 else "円高寄り" if pct > -60 else "強く円高寄り")
        srows.append(
            f'<div class="row"><span class="lbl">{html.escape(name)}</span>'
            f'<span class="txt">重み {w}%　{html.escape(note)}</span>'
            f'{_gauge(pct, verd)}</div>')
    score_rows = "\n".join(srows)

    # ---- バックテスト --------------------------------------------------------
    if bt.get("ok"):
        ratio = bt["ratio"]
        judge = ("ランダムウォークをわずかに上回りました" if ratio < 0.98 else
                 "ほぼ互角（＝実質的に勝てていません）" if ratio < 1.02 else
                 "ランダムウォークに負けました")
        bt_html = f"""
        <div class="tw"><table>
          <tbody>
            <tr><th scope="row">乖離zと{bt['horizon']}日後リターンの関係</th>
                <td class="n">傾き {bt['full'].beta:+.2f}　R² {bt['full'].r2:.3f}</td></tr>
            <tr><th scope="row">符号の的中率</th>
                <td class="n">{bt['hit_rate']*100:.1f}%　（コイン投げ＝50%）</td></tr>
            <tr><th scope="row">モデルの予測誤差 (RMSE)</th><td class="n">{bt['rmse_model']:.3f}%</td></tr>
            <tr><th scope="row">ランダムウォークの予測誤差</th><td class="n">{bt['rmse_rw']:.3f}%</td></tr>
            <tr><th scope="row">比率（1未満なら勝ち）</th>
                <td class="n"><strong>{ratio:.3f}</strong>　{html.escape(judge)}</td></tr>
          </tbody>
        </table></div>"""
    else:
        bt_html = ('<p class="note">データが足りず、バックテストは実施できませんでした。</p>')

    demo_banner = ""
    if demo:
        demo_banner = """
        <div class="warn" style="margin-top:20px">
          <span class="t">DEMO DATA</span>
          <p><strong>このページは合成デモデータで作られています。実際の相場ではありません。</strong>
          合成データは「乖離が必ず平均に戻る」よう人工的に作ってあるため、バックテストの成績は
          実データより大幅に良く出ます。見るべきは数字の良さではなく、ページの構成と検証の手順です。</p>
        </div>"""

    def chart(key, title, cap, wide=False):
        if key not in charts:
            return ""
        cls = "card wide" if wide else "card"
        hint = ('<p class="scrollhint">← 横にスワイプすると全期間を追えます</p>'
                if wide else "")
        return f"""
        <section>
          <div class="head"><p class="kick">{title[0]}</p><h2>{html.escape(title[1])}</h2></div>
          <div class="{cls}">{charts[key]}</div>{hint}
          <p class="cap">{cap}</p>
        </section>"""

    page = f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>ドル円 金利差モデル</title>
<style>{CSS.replace('__FONT__', FONT_STACK).replace('__MONO__', MONO_STACK)}</style>
</head>
<body>
<div class="wrap">

<header>
  <p class="kick">USD / JPY — Rate Differential Model</p>
  <h1>ドル円 金利差モデル</h1>
  <div class="meta">
    <span>更新 {now_jst():%Y-%m-%d %H:%M} JST</span>
    <span>データ {df['date'].iloc[0]:%Y-%m-%d} 〜 {df['date'].iloc[-1]:%Y-%m-%d}（{len(df)}営業日）</span>
    <span>{'合成デモデータ' if demo else '実データ'}</span>
  </div>
</header>

<div class="verdict {cls}">
  <span class="lbl">TODAY'S READ</span>
  <span class="val">{html.escape(score['verdict'])}　<span class="num">{v:+.0f}</span> / 100</span>
  <span class="sub">{sub}</span>
</div>

{demo_banner}

<dl class="tiles">{''.join(tiles)}</dl>

{chart('candle', ('01 — Price Action', f'ドル/円（直近{CANDLE_YEARS}年）'),
       '1本が1営業日で、実体の上下が始値と終値、細いヒゲが高値と安値です。'
       '赤が終値＞始値（その日は円安）、青が終値＜始値（円高）。'
       '重ねた2本の線は日米の金利差（右軸・pt）で、'
       '<strong>琥珀色が2年、緑が10年</strong>です。'
       '<strong>金利差の向きとローソクの向きがそろっているか</strong>を見るための図です。'
       'そろっていない期間は、金利差以外の要因が相場を動かしています。'
       '2年は金融政策の織り込み、10年は成長率とインフレの見通しを映すので、'
       '2本が逆方向に動いているときは市場の見方が変わりかけているサインです。'
       '四本値は1時間足を日次に組み直したもの（UTC基準）で、'
       'モデル本体が使う終値（NY正午の仲値）とは0.1円ほどずれることがあります。', wide=True)}

{chart('fair', ('02 — Fair Value', '長期の全体像：実勢レート vs フェアバリュー'),
       '緑の線が「今の金利差ならこのくらいが妥当」という推定値、帯はその±1σ。'
       '赤い実勢がこの帯から大きく外れているときだけ、乖離に情報量があります。'
       'こちらは全期間を1枚に収めるため終値の折れ線です。')}

{chart('dev', ('03 — Deviation', 'フェアバリューからの乖離（zスコア）'),
       '＋は金利差で説明できるより円安に、−は円高に行き過ぎている状態。'
       '±2σを超えたら要注意。ただし何か月も片側に張り付いているときは、'
       '「いずれ戻る」ではなく「金利差だけでは説明が足りない」というサインです。')}

<section>
  <div class="head"><p class="kick">04 — Scenario</p><h2>FOMC × 日銀 のシナリオ</h2></div>
  <p class="note">効くのは「決定」ではなく<strong>「織り込みとのズレ」</strong>です。
  前提の織り込み確率は FOMC {args.p_fomc_hike:.0%} / 日銀 {args.p_boj_hike:.0%}、
  現在値 {spot:.2f} 円、感応度 {sens['pct_per_pt']:+.2f}%/pt で計算しています。</p>
  <div class="tw"><table>
    <thead><tr><th>組み合わせ</th><th>方向</th><th>金利差の変化</th><th>ドル円の変化</th><th>着地水準</th></tr></thead>
    <tbody>{scen_rows}</tbody>
  </table></div>
  <p class="cap">「利上げ×利上げ」と「据え置き×据え置き」が同じ値になるのは正しい挙動です。
  両国が同じ方向に動くとサプライズが打ち消し合い、金利差は織り込み確率の差だけで決まります。</p>
</section>

<section>
  <div class="head"><p class="kick">05 — Scorecard</p><h2>方向性スコア</h2></div>
  <div class="score">{score_rows}</div>
  <p class="cap">素点 {score['raw_pct']:+.1f} に例外フィルター ×{score['exception_factor']:.2f}
  （介入警戒・リスクオフ・ポジションの偏り）を掛けて最終スコア {v:+.1f}。
  例外は方向を持たないので、足し算ではなく掛け算で結論を弱めます。</p>
</section>

<section>
  <div class="head"><p class="kick">06 — Backtest</p><h2>このモデルは使えるのか</h2></div>
  <p class="note">サンプルの前70%だけで係数を推定し、<strong>残り30%（モデルが一度も見ていない期間）</strong>で
  ランダムウォーク（＝「動かない」と予想）と予測誤差を比べた結果です。</p>
  {bt_html}
  <div class="two">
    {f'<div class="card">{charts["sens"]}</div>' if 'sens' in charts else ''}
    {f'<div class="card">{charts["bt"]}</div>' if 'bt' in charts else ''}
  </div>
  <p class="cap">左：金利差の変化とドル円の変化（日次）。R²が低いのは当然で、
  日々の値動きの大半は金利差以外で決まっています。
  右：乖離zと{bt.get('horizon', 20)}営業日後のリターン。棒はゾーン別の平均です。</p>
</section>

<section>
  <div class="head"><p class="kick">07 — Limits</p><h2>効かなくなる場面</h2></div>
  <div class="warn">
    <span class="t">CAUTION</span>
    <p>短期の為替はランダムウォークに勝つのが極めて難しいことが知られています。
    このページは「明日いくらか」を当てるものではなく、
    <strong>「今の水準は金利差で説明できる範囲か」</strong>を測るものです。
    次の局面では結論を弱めるか、判断を保留してください。</p>
    <p><strong>為替介入</strong>（当局の意思が金利差を上書きする）／
    <strong>リスクオフ</strong>（株の急落でキャリー取引が巻き戻る）／
    <strong>ポジションの偏り</strong>（小さな材料で大きく戻る）／
    <strong>構造的な円売り</strong>（貿易赤字・対外投資が金利差と無関係に円を売り続ける）／
    <strong>財政と政治</strong>（方程式の外側から効く）</p>
  </div>
</section>

<footer>
  本ページは教育・分析目的で自動生成されたものであり、投資助言ではありません。<br>
  生成: usdjpy_model.py　/　{now_jst():%Y-%m-%d %H:%M:%S} JST　/
  データ出典: FRED（ドル円・米金利・VIX）、財務省 国債金利情報（日本国債利回り）
</footer>

</div>
</body>
</html>"""

    path = outdir / "index.html"
    path.write_text(page, encoding="utf-8")
    return path
