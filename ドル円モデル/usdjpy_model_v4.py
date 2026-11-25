#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
 ドル円 金利差モデル  (USD/JPY Rate-Differential Model)
================================================================================

このスクリプトは、日米金利差からドル円の「フェアバリュー（妥当水準）」を推定し、
実勢との乖離を測り、金融政策イベントのシナリオを計算し、方向性をスコア化します。

  MODULE 1  フェアバリューと乖離     … 今の金利差ならドル円はいくらが妥当か
  MODULE 2  金利感応度(beta)         … 金利差1ptでドル円は何%動くか
  MODULE 3  イベント・シナリオ計算   … FOMC/日銀の結果別にドル円がどこへ行くか
  MODULE 4  方向性スコアリング       … 5材料+例外フィルターを合成した傾き
  MODULE 5  正直なバックテスト       … このモデルはランダムウォークに勝てるのか

--------------------------------------------------------------------------------
 使い方
--------------------------------------------------------------------------------
  1) デモを見る（データ不要。合成データで全機能が動きます）
        python3 usdjpy_model.py --demo

  2) 実データで動かす
        python3 usdjpy_model.py --csv data.csv

  3) シナリオだけ計算する（イベント当日用）
        python3 usdjpy_model.py --csv data.csv --spot 154.4 \
            --p-fomc-hike 0.55 --p-boj-hike 0.60

  必要パッケージ:  pandas, numpy, matplotlib
        pip install pandas numpy matplotlib

--------------------------------------------------------------------------------
 入力CSVの形式（1行目はヘッダー。列名はこのとおりに）
--------------------------------------------------------------------------------
  date,usdjpy,us2y,jp2y,us10y,jp10y,vix
  2024-01-02,141.90,4.33,0.05,3.94,0.62,13.20

  ・date    : YYYY-MM-DD
  ・usdjpy  : ドル円レート
  ・us2y    : 米2年債利回り(%)   ← このモデルの主役
  ・jp2y    : 日本2年債利回り(%)
  ・us10y   : 米10年債利回り(%)  ← 補助
  ・jp10y   : 日本10年債利回り(%)
  ・vix     : VIX指数（任意。空欄でも動きます）

  データの入手先はすべて無料です。README_使い方.md を参照してください。

--------------------------------------------------------------------------------
 このモデルの限界（先に読んでください）
--------------------------------------------------------------------------------
  短期の為替レートは、学術的にはランダムウォーク（＝今日の値が明日の最良の予想）
  に勝つのが非常に難しいことが知られています。MODULE 5 は、そのことを自分の目で
  確かめるために入れてあります。

  したがってこのモデルの正しい使い方は「明日いくらになるか当てる」ことではなく、
  「今の水準は金利差から説明できる範囲か、それとも行き過ぎか」を測ることです。
  乖離が大きいときにこそ情報量があります。
================================================================================
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

# ==============================================================================
# 設定 — ここを書き換えれば挙動が変わります
# ==============================================================================

ROLL_WINDOW   = 250   # ローリング回帰の窓（営業日）。250 ≒ 1年
SD_WINDOW     = 120   # 乖離の標準偏差を取る窓（同梱Excelと同じ）
FWD_HORIZON   = 20    # 「乖離」が何営業日後のリターンを説明するか検証する期間
POLICY_STEP   = 0.25  # 1回の利上げ幅(%pt)
PASSTHROUGH   = 0.70  # 政策サプライズが2年債利回りに伝わる割合（後述）
OUTPUT_DIR    = Path("output")

REQUIRED_COLS = ["date", "usdjpy", "us2y", "jp2y"]
OPTIONAL_COLS = ["us10y", "jp10y", "vix"]

# 配色（カラーユニバーサル検証済み）
C_ACTUAL = "#BC4526"   # 実勢レート
C_FAIR   = "#12907A"   # フェアバリュー
C_ALT    = "#2F5AA8"   # 補助系列
C_INK    = "#1F2937"
C_MUTED  = "#8A9A95"
C_GRID   = "#E3E8E6"
C_SURF   = "#FCFCFB"


# ==============================================================================
# 汎用: 最小二乗法（statsmodels なしで動かすための自前実装）
# ==============================================================================

@dataclass
class OLSResult:
    alpha: float
    beta: float
    r2: float
    tstat: float
    n: int
    resid_sd: float

    def __str__(self) -> str:
        return (f"beta={self.beta:+.4f}  t={self.tstat:+.2f}  "
                f"R^2={self.r2:.3f}  n={self.n}")


def ols(x: np.ndarray, y: np.ndarray) -> OLSResult:
    """単回帰 y = alpha + beta*x を解き、t値とR^2を返す。"""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    n = len(x)
    if n < 30:
        return OLSResult(np.nan, np.nan, np.nan, np.nan, n, np.nan)

    xm, ym = x.mean(), y.mean()
    sxx = ((x - xm) ** 2).sum()
    if sxx == 0:
        return OLSResult(np.nan, np.nan, np.nan, np.nan, n, np.nan)

    beta = ((x - xm) * (y - ym)).sum() / sxx
    alpha = ym - beta * xm
    resid = y - (alpha + beta * x)
    sse = (resid ** 2).sum()
    sst = ((y - ym) ** 2).sum()
    r2 = 1.0 - sse / sst if sst > 0 else np.nan
    sigma2 = sse / (n - 2)
    se_beta = np.sqrt(sigma2 / sxx)
    tstat = beta / se_beta if se_beta > 0 else np.nan
    return OLSResult(alpha, beta, r2, tstat, n, float(np.sqrt(sigma2)))


# ==============================================================================
# データ読み込み
# ==============================================================================

def load_data(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]

    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise SystemExit(
            f"[エラー] CSVに必須列がありません: {missing}\n"
            f"        必要な列: {REQUIRED_COLS}  （任意: {OPTIONAL_COLS}）"
        )
    for c in OPTIONAL_COLS:
        if c not in df.columns:
            df[c] = np.nan

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for c in ["usdjpy", "us2y", "jp2y", "us10y", "jp10y", "vix"]:
        # FRED の欠損記号 "." などを NaN に落とす
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    # 祝日で片方だけ欠けるのは普通なので、前日値で埋める
    df[["usdjpy", "us2y", "jp2y", "us10y", "jp10y", "vix"]] = (
        df[["usdjpy", "us2y", "jp2y", "us10y", "jp10y", "vix"]].ffill()
    )
    df = df.dropna(subset=["usdjpy", "us2y", "jp2y"]).reset_index(drop=True)

    if len(df) < 30:
        raise SystemExit(
            f"[エラー] 使えるデータが {len(df)} 行しかありません。\n"
            f"        date / usdjpy / us2y / jp2y の4列がすべて埋まっている行だけを数えています。\n"
            f"        テンプレートCSVは列の並びを示すための見本なので、そのままでは動きません。\n"
            f"        README_使い方.md の手順で実データを集めてから、もう一度実行してください。\n"
            f"        （データなしで動きを見たいときは `--demo` を付けてください）"
        )
    if len(df) < ROLL_WINDOW + SD_WINDOW:
        print(f"[警告] データが {len(df)} 行です。乖離zスコアには "
              f"{ROLL_WINDOW + SD_WINDOW} 行必要なので、MODULE 1 は空欄になります。\n"
              f"       MODULE 2〜4（感応度・シナリオ・スコアリング）は計算できます。",
              file=sys.stderr)
    elif len(df) < ROLL_WINDOW + SD_WINDOW + FWD_HORIZON + 30:
        print(f"[警告] データが {len(df)} 行しかありません。"
              f"ローリング窓({ROLL_WINDOW})に対して短すぎるため、結果は不安定です。"
              f"最低でも {ROLL_WINDOW + FWD_HORIZON + 30} 行を推奨します。", file=sys.stderr)
    return df


def make_demo_data(n: int = 900, seed: int = 7) -> pd.DataFrame:
    """
    デモ用の合成データ。実データではありません。
    「金利差が縮小していく一方で、構造的な円売りが効いてドル円は下がりきらない」
    という2026年に近い状況を、わざと再現してあります。
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2023-01-02", periods=n)

    # 米2年債: 5.0% 付近から 3.5% へ、ゆらぎながら低下
    us2y = 5.0 - 1.5 * np.linspace(0, 1, n) ** 0.8 + np.cumsum(rng.normal(0, 0.020, n)) * 0.5
    # 日本2年債: 0.0% から 1.1% へ上昇
    jp2y = 0.0 + 1.1 * np.linspace(0, 1, n) ** 1.3 + np.cumsum(rng.normal(0, 0.008, n)) * 0.5
    spread = us2y - jp2y

    # ドル円 = 金利差の関数 + 構造的な円売りトレンド + 平均回帰するノイズ
    structural = np.linspace(0, 14, n)             # 貿易赤字・対外投資などの恒常的な円売り
    noise = np.zeros(n)
    for i in range(1, n):                           # AR(1): 乖離が徐々に戻る動き
        noise[i] = 0.97 * noise[i - 1] + rng.normal(0, 0.85)
    usdjpy = 92.0 + 11.5 * spread + structural + noise

    vix = 14 + 4 * np.abs(rng.normal(0, 1, n)) + np.where(rng.random(n) < 0.01, 18, 0)

    return pd.DataFrame({
        "date": dates,
        "usdjpy": np.round(usdjpy, 3),
        "us2y": np.round(us2y, 3),
        "jp2y": np.round(jp2y, 3),
        "us10y": np.round(us2y + 0.55 + rng.normal(0, 0.05, n), 3),
        "jp10y": np.round(jp2y + 1.30 + rng.normal(0, 0.04, n), 3),
        "vix": np.round(vix, 2),
    })


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["spread2"] = df["us2y"] - df["jp2y"]
    df["spread10"] = df["us10y"] - df["jp10y"]
    df["d_spread2"] = df["spread2"].diff()
    df["d_logfx"] = np.log(df["usdjpy"]).diff() * 100.0   # 日次変化率(%)
    df[f"fwd{FWD_HORIZON}"] = (
        df["usdjpy"].shift(-FWD_HORIZON) / df["usdjpy"] - 1.0
    ) * 100.0
    return df


# ==============================================================================
# MODULE 1 — フェアバリューと乖離
# ==============================================================================

def fair_value(df: pd.DataFrame, window: int = ROLL_WINDOW,
               method: str = "beta", use_trend: bool = True,
               beta_mode: str = "rolling") -> pd.DataFrame:
    """
    「今の金利差なら、ドル円はいくらが妥当か」を推定する。方式は2つ選べます。

    ------------------------------------------------------------------------
    method="beta"  （既定・おすすめ）
    ------------------------------------------------------------------------
        fair_t = 直近W日の平均レート
                 + (金利差感応度) × (今の金利差 − 直近W日の平均金利差)

        感応度は「変化どうしの回帰」から推定します。水準どうしを回帰すると、
        金利差とドル円がどちらも同じ向きにダラダラ動いているだけで見せかけの
        相関が出てしまう（spurious regression）ためです。この方式なら符号が
        経済的におかしくなりにくく、構造的な円売りは「平均レート」の側が
        自動的に吸収してくれます。

    ------------------------------------------------------------------------
    method="level" （教科書的な方式。落とし穴を体験するため）
    ------------------------------------------------------------------------
        usdjpy = a + b × 金利差 ( + c × 時間トレンド )

        金融機関のレポートでよく見る形ですが、構造的な円売りが強い局面では
        b がマイナス（＝金利差が広がると円高、という経済的にありえない推定）に
        なりがちです。実際に --method level で走らせると、その警告が出ます。
        「モデルは壊れることがある」と知っておくために残してあります。

    どちらの方式も窓を [t-W+1, t] に限っているので、将来のデータは一切
    使っていません（＝先読みバイアスなし）。
    """
    df = df.copy()
    y = df["usdjpy"]
    x = df["spread2"]

    if method == "beta":
        if beta_mode == "full":
            # 全期間の1本の回帰係数を使う（同梱のExcel版と同じ計算）
            b_pct = pd.Series(ols(df["d_spread2"].values, df["d_logfx"].values).beta,
                              index=df.index)
        else:
            # 変化どうしの回帰係数をローリングで推定（単位: % / 1pt）
            dcov = df["d_spread2"].rolling(window).cov(df["d_logfx"])
            dvar = df["d_spread2"].rolling(window).var()
            b_pct = dcov / dvar
        ybar = y.rolling(window).mean()
        xbar = x.rolling(window).mean()
        df["fv_beta"] = b_pct / 100.0 * ybar          # 円 / 1pt に換算
        df["fair"] = ybar + df["fv_beta"] * (x - xbar)

    elif method == "level":
        yv = y.to_numpy(dtype=float)
        xv = x.to_numpy(dtype=float)
        tv = np.arange(len(df), dtype=float)
        n = len(df)
        fair = np.full(n, np.nan)
        bhat = np.full(n, np.nan)
        for i in range(window - 1, n):
            sl = slice(i - window + 1, i + 1)
            xs, ys, ts = xv[sl], yv[sl], tv[sl]
            ok = np.isfinite(xs) & np.isfinite(ys)
            if ok.sum() < window * 0.8:
                continue
            cols = [np.ones(ok.sum()), xs[ok]]
            if use_trend:
                cols.append(ts[ok])
            try:
                coef, *_ = np.linalg.lstsq(np.column_stack(cols), ys[ok], rcond=None)
            except np.linalg.LinAlgError:
                continue
            fair[i] = coef[0] + coef[1] * xv[i] + (coef[2] * tv[i] if use_trend else 0.0)
            bhat[i] = coef[1]
        df["fv_beta"] = bhat
        df["fair"] = fair
    else:
        raise SystemExit(f"[エラー] 未知の method: {method}  (beta / level のいずれか)")

    df["resid"] = df["usdjpy"] - df["fair"]
    df["resid_sd"] = df["resid"].rolling(SD_WINDOW).std()
    df["z"] = df["resid"] / df["resid_sd"]
    df.attrs["fv_method"] = method
    return df


# ==============================================================================
# MODULE 2 — 金利感応度 (beta)
# ==============================================================================

def sensitivity(df: pd.DataFrame) -> dict:
    """
    日次の変化どうしを回帰する:  ΔlogFX(%) = a + b * Δspread2(pt)

    水準どうしの回帰と違い、こちらは見せかけの相関(spurious regression)に
    なりにくく、シナリオ計算に使うべきなのはこの beta のほう。
    """
    res = ols(df["d_spread2"].values, df["d_logfx"].values)
    spot = float(df["usdjpy"].iloc[-1])
    return {
        "ols": res,
        "pct_per_pt": res.beta,                       # 金利差+1.00pt → ドル円 +x%
        "yen_per_10bp": res.beta / 100.0 * spot * 0.10,
        "spot": spot,
    }


# ==============================================================================
# MODULE 3 — イベント・シナリオ計算
# ==============================================================================

def policy_surprise(hike: bool, prob_hike: float, step: float = POLICY_STEP) -> float:
    """
    「決定そのもの」ではなく「織り込みとのズレ」を金利のサプライズに換算する。

      例) 利上げ確率60%で実際に利上げ  → +0.25 * (1-0.60) = +0.10pt のサプライズ
          利上げ確率60%で据え置き      → -0.25 * 0.60     = -0.15pt のサプライズ

    ここがこのモデルの肝。90%織り込まれた利上げが実行されても相場がほとんど
    動かない（むしろ材料出尽くしで逆に動く）理由が、この式に入っている。
    """
    prob_hike = min(max(prob_hike, 0.0), 1.0)
    return step * (1.0 - prob_hike) if hike else -step * prob_hike


def scenario_grid(spot: float, beta_pct_per_pt: float,
                  p_fomc_hike: float, p_boj_hike: float,
                  passthrough: float = PASSTHROUGH) -> pd.DataFrame:
    """FOMC × 日銀 の4通りについて、ドル円の着地水準を計算する。"""
    rows = []
    for us_hike in (True, False):
        for jp_hike in (True, False):
            s_us = policy_surprise(us_hike, p_fomc_hike)
            s_jp = policy_surprise(jp_hike, p_boj_hike)
            d_spread = passthrough * (s_us - s_jp)
            d_pct = beta_pct_per_pt * d_spread
            d_yen = spot * d_pct / 100.0
            rows.append({
                "FOMC": "利上げ" if us_hike else "据え置き",
                "日銀": "利上げ" if jp_hike else "据え置き",
                "米サプライズ(pt)": round(s_us, 4),
                "日サプライズ(pt)": round(s_jp, 4),
                "金利差の変化(pt)": round(d_spread, 4),
                "ドル円の変化(%)": round(d_pct, 3),
                "ドル円の変化(円)": round(d_yen, 2),
                "着地水準": round(spot + d_yen, 2),
            })
    return pd.DataFrame(rows)


# ==============================================================================
# MODULE 4 — 方向性スコアリング
# ==============================================================================

SCORE_ITEMS = [
    # (項目, 重み, 説明)
    ("日米金利差の方向", 25, "拡大なら＋(円安) / 縮小なら−(円高)"),
    ("FRBのタカ派度",   25, "タカ派なら＋(円安) / ハト派なら−(円高)"),
    ("日銀のタカ派度",   20, "タカ派なら−(円高) / ハト派なら＋(円安)  ※符号が逆"),
    ("米CPI",           15, "上振れなら＋(円安) / 下振れなら−(円高)"),
    ("米雇用統計",       15, "強ければ＋(円安) / 弱ければ−(円高)"),
]


def direction_score(scores: dict[str, float], exception_factor: float = 1.0) -> dict:
    """
    各項目を -2(強い円高) 〜 +2(強い円安) で採点し、重み付き合計を -100〜+100 に換算。

    例外フィルター（介入警戒・リスクオフ・ポジション偏り）は方向を持たないので、
    足し算ではなく「掛け算で結論を弱める」係数として扱う。
      1.0 = 例外なし  /  0.5 = 半分に割り引く  /  0.2 = ほぼ判断保留
    """
    total_w = sum(w for _, w, _ in SCORE_ITEMS)
    raw = sum(w * float(scores.get(name, 0)) for name, w, _ in SCORE_ITEMS)
    pct = raw / (total_w * 2.0) * 100.0
    final = pct * exception_factor

    if   final >= 50:  verdict = "強く円安寄り"
    elif final >= 20:  verdict = "円安寄り"
    elif final > -20:  verdict = "方向感なし（無理に張らない）"
    elif final > -50:  verdict = "円高寄り"
    else:              verdict = "強く円高寄り"

    return {"raw_pct": pct, "final": final, "verdict": verdict,
            "exception_factor": exception_factor}


# ==============================================================================
# MODULE 5 — 正直なバックテスト
# ==============================================================================

def backtest(df: pd.DataFrame, horizon: int = FWD_HORIZON) -> dict:
    """
    問1: 乖離zは、その後のリターンを説明できるか？
    問2: このモデルはランダムウォーク（＝「動かない」と予想）に勝てるか？

    問2は、サンプルの前70%だけで係数を推定し、残り30%（モデルが一度も見て
    いない期間）で予測誤差を比べる、という真の意味での検証をしている。
    """
    d = df.dropna(subset=["z", f"fwd{horizon}"]).copy()
    if len(d) < 120:
        return {"ok": False, "reason": f"検証に使える行が {len(d)} 行しかありません"}

    zz = d["z"].values
    fw = d[f"fwd{horizon}"].values

    full = ols(zz, fw)
    # 符号の的中率: z<0(割安)のとき上昇、z>0(割高)のとき下落、を当てられたか
    pred_dir = -np.sign(zz)
    hit = float(np.mean(pred_dir == np.sign(fw)))

    split = int(len(d) * 0.70)
    tr = ols(zz[:split], fw[:split])
    z_te, f_te = zz[split:], fw[split:]
    if not np.isfinite(tr.beta) or len(z_te) < 30:
        return {"ok": False, "reason": "分割後のサンプルが足りません"}

    pred_model = tr.alpha + tr.beta * z_te
    rmse_model = float(np.sqrt(np.mean((f_te - pred_model) ** 2)))
    rmse_rw = float(np.sqrt(np.mean(f_te ** 2)))     # ランダムウォーク = 「0%」と予想

    return {
        "ok": True, "horizon": horizon, "n": len(d),
        "full": full, "hit_rate": hit,
        "rmse_model": rmse_model, "rmse_rw": rmse_rw,
        "ratio": rmse_model / rmse_rw if rmse_rw > 0 else np.nan,
        "n_test": len(z_te),
    }


# ==============================================================================
# 作図
# ==============================================================================

def setup_matplotlib():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    for cand in ["Noto Sans CJK JP", "IPAGothic", "Hiragino Sans",
                 "Yu Gothic", "MS Gothic", "TakaoGothic"]:
        if any(f.name == cand for f in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = cand
            break
    else:
        print("[警告] 日本語フォントが見つかりません。グラフの日本語が □ になります。",
              file=sys.stderr)

    plt.rcParams.update({
        "axes.unicode_minus": False,
        "figure.facecolor": C_SURF, "axes.facecolor": C_SURF,
        "savefig.facecolor": C_SURF,
        "axes.edgecolor": C_GRID, "axes.linewidth": 1.0,
        "axes.grid": True, "grid.color": C_GRID, "grid.linewidth": 0.8,
        "axes.spines.top": False, "axes.spines.right": False,
        "text.color": C_INK, "axes.labelcolor": C_INK,
        "xtick.color": C_MUTED, "ytick.color": C_MUTED,
        "xtick.labelsize": 9, "ytick.labelsize": 9,
        "axes.titlesize": 12, "axes.titleweight": "bold",
        "axes.titlelocation": "left", "axes.titlepad": 12,
        "legend.frameon": False, "legend.fontsize": 9,
        "figure.dpi": 110,
    })
    return plt


def make_charts(df: pd.DataFrame, sens: dict, bt: dict, outdir: Path, tag: str = ""):
    plt = setup_matplotlib()
    outdir.mkdir(parents=True, exist_ok=True)
    d = df.dropna(subset=["fair"]).copy()
    files = []
    has_fv = len(d) > 5

    if not has_fv:
        print("[情報] データ行数が足りないため、図1（フェアバリュー）と図2（乖離）は"
              "作成しません。図3（感応度）は作成します。", file=sys.stderr)

    # --- 図1: 実勢 vs フェアバリュー -----------------------------------------
    if has_fv:
      fig, ax = plt.subplots(figsize=(10, 4.6))
      ax.fill_between(d["date"], d["fair"] - d["resid_sd"], d["fair"] + d["resid_sd"],
                    color=C_FAIR, alpha=0.13, linewidth=0, label="フェアバリュー ±1σ")
      ax.plot(d["date"], d["fair"], color=C_FAIR, lw=2.0, label="フェアバリュー（金利差から推定）")
      ax.plot(d["date"], d["usdjpy"], color=C_ACTUAL, lw=2.0, label="実勢レート")
      last = d.iloc[-1]
      ax.scatter([last["date"]], [last["usdjpy"]], s=42, color=C_ACTUAL, zorder=5,
               edgecolor=C_SURF, linewidth=2)
      ax.annotate(f"{last['usdjpy']:.1f}", (last["date"], last["usdjpy"]),
                xytext=(8, 4), textcoords="offset points",
                color=C_ACTUAL, fontsize=10, fontweight="bold")
      ax.annotate(f"{last['fair']:.1f}", (last["date"], last["fair"]),
                xytext=(8, -12), textcoords="offset points",
                color=C_FAIR, fontsize=10, fontweight="bold")
      ax.set_title(f"実勢レート vs 金利差から推定したフェアバリュー{tag}", pad=34)
      ax.set_ylabel("ドル円")
      ax.set_xlim(d["date"].iloc[0], d["date"].iloc[-1])
      ax.legend(loc="lower left", bbox_to_anchor=(0, 1.005), ncol=3,
              borderaxespad=0, fontsize=9)
      fig.tight_layout()
      p = outdir / "1_fairvalue.png"; fig.savefig(p); plt.close(fig); files.append(p)

      # --- 図2: 乖離zスコア -----------------------------------------------------
      fig, ax = plt.subplots(figsize=(10, 3.6))
      ax.axhspan(-2, 2, color=C_MUTED, alpha=0.10, linewidth=0)
      ax.axhline(0, color=C_MUTED, lw=1.2)
      for lv in (2, -2):
        ax.axhline(lv, color=C_MUTED, lw=1.0, ls="--")
      ax.fill_between(d["date"], 0, d["z"], where=d["z"] >= 0,
                    color=C_ACTUAL, alpha=0.55, linewidth=0)
      ax.fill_between(d["date"], 0, d["z"], where=d["z"] < 0,
                    color=C_ALT, alpha=0.55, linewidth=0)
      ax.annotate("＋＝円安に行き過ぎ", xy=(0.01, 0.94), xycoords="axes fraction",
                color=C_ACTUAL, fontsize=9.5, fontweight="bold")
      ax.annotate("−＝円高に行き過ぎ", xy=(0.01, 0.06), xycoords="axes fraction",
                color=C_ALT, fontsize=9.5, fontweight="bold")
      ax.set_xlim(d["date"].iloc[0], d["date"].iloc[-1])
      ax.set_title(f"フェアバリューからの乖離（zスコア）{tag}")
      ax.set_ylabel("標準偏差")
      fig.tight_layout()
      p = outdir / "2_deviation.png"; fig.savefig(p); plt.close(fig); files.append(p)

    # --- 図3: 感応度の散布図 --------------------------------------------------
    r = sens["ols"]
    s = df.dropna(subset=["d_spread2", "d_logfx"])
    fig, ax = plt.subplots(figsize=(6.4, 5.2))
    ax.axhline(0, color=C_GRID, lw=1); ax.axvline(0, color=C_GRID, lw=1)
    ax.scatter(s["d_spread2"], s["d_logfx"], s=13, color=C_ACTUAL,
               alpha=0.35, linewidth=0)
    if np.isfinite(r.beta):
        xs = np.linspace(s["d_spread2"].min(), s["d_spread2"].max(), 50)
        ax.plot(xs, r.alpha + r.beta * xs, color=C_INK, lw=2.2)
        ax.annotate(f"金利差 +1.00pt → ドル円 {r.beta:+.2f}%\n"
                    f"（＝10bpあたり約 {sens['yen_per_10bp']:+.2f}円）\n"
                    f"R² = {r.r2:.3f}",
                    xy=(0.03, 0.97), xycoords="axes fraction", va="top",
                    fontsize=10, color=C_INK,
                    bbox=dict(boxstyle="round,pad=0.5", fc=C_SURF, ec=C_GRID))
    ax.set_title("金利差の変化 と ドル円の変化（日次）")
    ax.set_xlabel("日米2年金利差の変化 (pt)")
    ax.set_ylabel("ドル円の変化 (%)")
    fig.tight_layout()
    p = outdir / "3_sensitivity.png"; fig.savefig(p); plt.close(fig); files.append(p)

    # --- 図4: バックテスト ----------------------------------------------------
    fig, ax = plt.subplots(figsize=(6.4, 5.2))
    b = df.dropna(subset=["z", f"fwd{FWD_HORIZON}"])
    if len(b) < 10:
        plt.close(fig)
        return files
    ax.axhline(0, color=C_GRID, lw=1); ax.axvline(0, color=C_GRID, lw=1)
    ax.scatter(b["z"], b[f"fwd{FWD_HORIZON}"], s=13, color=C_MUTED,
               alpha=0.35, linewidth=0, label="各日")
    if len(b) > 60:
        bins = pd.cut(b["z"], bins=np.arange(-3.5, 4.0, 1.0))
        g = b.groupby(bins, observed=True)[f"fwd{FWD_HORIZON}"].mean()
        ctr = [iv.mid for iv in g.index]
        cols = [C_ALT if v >= 0 else C_ACTUAL for v in g.values]
        ax.bar(ctr, g.values, width=0.82, color=cols, alpha=0.9, label="ゾーン別の平均")
    ax.set_title(f"乖離zスコア と その後{FWD_HORIZON}営業日のリターン")
    ax.set_xlabel("乖離zスコア（＋＝円安に行き過ぎ）")
    ax.set_ylabel(f"{FWD_HORIZON}営業日後のリターン (%)")
    if bt.get("ok"):
        ax.annotate(f"傾き {bt['full'].beta:+.2f}  R² {bt['full'].r2:.3f}\n"
                    f"符号の的中率 {bt['hit_rate']*100:.1f}%",
                    xy=(0.03, 0.97), xycoords="axes fraction", va="top",
                    fontsize=10, bbox=dict(boxstyle="round,pad=0.5", fc=C_SURF, ec=C_GRID))
    ax.legend(loc="lower left")
    fig.tight_layout()
    p = outdir / "4_backtest.png"; fig.savefig(p); plt.close(fig); files.append(p)

    return files


# ==============================================================================
# レポート出力
# ==============================================================================

def hr(ch="─", n=78): return ch * n


def wpad(text: str, width: int) -> str:
    """全角文字を2桁として数え、表示幅を揃える。"""
    import unicodedata
    w = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)
    return text + " " * max(0, width - w)


def report(df: pd.DataFrame, sens: dict, bt: dict, grid: pd.DataFrame,
           score: dict, args) -> str:
    d = df.dropna(subset=["fair"])
    has_fv = len(d) > 0
    last = d.iloc[-1] if has_fv else None
    L = []
    A = L.append

    A("=" * 78)
    A(" ドル円 金利差モデル — 分析レポート")
    A("=" * 78)
    A(f" 期間          : {df['date'].iloc[0]:%Y-%m-%d} 〜 {df['date'].iloc[-1]:%Y-%m-%d}"
      f"  ({len(df)}営業日)")
    A(f" データソース  : {'合成デモデータ（実データではありません）' if args.demo else args.csv}")
    A("")

    A(hr()); A(" MODULE 1  フェアバリューと乖離"); A(hr())
    if not has_fv:
        A(f"  計算できません。フェアバリューには最低 {ROLL_WINDOW} 行、乖離zスコアには")
        A(f"  {ROLL_WINDOW + SD_WINDOW} 行のデータが必要です（現在 {len(df)} 行）。")
        A(f"  README_使い方.md の手順でデータを追加してください。")
        A(f"  なお MODULE 2〜4 は下のとおり計算できています。")
        A("")
    else:
        A(f"  実勢レート            : {last['usdjpy']:>10.2f} 円")
        A(f"  フェアバリュー        : {last['fair']:>10.2f} 円   "
          f"(直近{args.window}営業日 / 方式={args.method})")
        A(f"  乖離                  : {last['resid']:>+10.2f} 円")
        A(f"  乖離 zスコア          : {last['z']:>+10.2f} σ")
        z60 = d["z"].tail(60).mean()
        if np.isfinite(z60) and abs(z60) >= 1.5:
            side60 = "円安" if z60 > 0 else "円高"
            A(f"      直近60営業日の平均z = {z60:+.2f} σ。長期間ずっと片側に張り付いています。")
            A(f"      これは「金利差以外の力が{side60}方向に効き続けている」ことを意味します")
            A(f"      （構造的な円売り・介入・リスク選好など）。この状態では、乖離は")
            A(f"      『いずれ戻る』サインではなく『金利差だけでは足りない』サインです。")
        if abs(last["z"]) >= 2:
            side = "円安" if last["z"] > 0 else "円高"
            A(f"      → |z| が2σを超えています。金利差から説明できる範囲を超えて"
              f"{side}に振れている状態です。")
        else:
            A(f"      → 金利差から説明できる範囲内です（±2σ）。乖離は今のところ材料になりません。")
        A(f"  回帰の傾き            : 金利差 +1.00pt → ドル円 {last['fv_beta']:+.2f} 円 （水準ベース）")
        if np.isfinite(last["fv_beta"]) and last["fv_beta"] < 0:
            A("      [!] 傾きがマイナスです。「金利差が広がると円高になる」という経済的に")
            A("          おかしい推定なので、この期間のフェアバリューは信用しないでください。")
            A("          直近1年は金利差以外の力（構造的な円売り・介入など）が支配的だった、")
            A("          というのが実態です。窓を長くする(ROLL_WINDOW)か、乖離zは使わずに")
            A("          MODULE 3・4 だけを使うのが安全です。")
        A("")

    A(hr()); A(" MODULE 2  金利感応度 (beta) — シナリオ計算の土台"); A(hr())
    r = sens["ols"]
    A(f"  日次変化の回帰: ΔlogFX(%) = a + b × Δ金利差(pt)")
    A(f"      {r}")
    A(f"  金利差 +1.00pt (100bp) → ドル円 {sens['pct_per_pt']:+.2f} %")
    A(f"  金利差 +0.10pt ( 10bp) → ドル円 {sens['yen_per_10bp']:+.2f} 円 "
      f"(spot {sens['spot']:.2f} 換算)")
    if np.isfinite(r.r2):
        A(f"  ※ R²={r.r2:.3f} は「日々の値動きのうち金利差で説明できる割合」。"
          f"残りの{(1-r.r2)*100:.0f}%は")
        A(f"     金利差以外（需給・リスクオフ・介入など）で動いています。これが普通です。")
    A("")

    A(hr()); A(" MODULE 3  イベント・シナリオ（FOMC × 日銀）"); A(hr())
    A(f"  前提: spot={args.spot if args.spot else sens['spot']:.2f} / "
      f"利上げ幅={POLICY_STEP:.2f}pt / 2年債への伝わり方={PASSTHROUGH:.0%}")
    A(f"        市場の織り込み: FOMC利上げ確率={args.p_fomc_hike:.0%}, "
      f"日銀利上げ確率={args.p_boj_hike:.0%}")
    A("")
    A("  " + grid.to_string(index=False).replace("\n", "\n  "))
    A("")
    A("  読み方: 効くのは「決定」ではなく「織り込みとのズレ」。すでに織り込まれた")
    A("          利上げが実行されても、サプライズはその分だけ小さくなります。")
    A("")

    A(hr()); A(" MODULE 4  方向性スコアリング"); A(hr())
    for name, w, note in SCORE_ITEMS:
        v = args.score_inputs.get(name, 0)
        bar = ("█" * int(abs(v) * 4)).ljust(8)
        side = "円安" if v > 0 else ("円高" if v < 0 else "中立")
        A(f"  {wpad(name, 20)} 重み{w:>3}%  {v:+.1f} [{bar}] {wpad(side, 5)}{note}")
    A(f"  {wpad('例外フィルター', 20)}          ×{score['exception_factor']:.2f}  "
      f"(介入警戒・リスクオフ・ポジション偏りによる割引)")
    A("")
    A(f"  素点     : {score['raw_pct']:+.1f} / 100")
    A(f"  最終スコア: {score['final']:+.1f} / 100   →  【{score['verdict']}】")
    A("")

    A(hr()); A(" MODULE 5  バックテスト — このモデルは本当に使えるのか"); A(hr())
    if not bt.get("ok"):
        A(f"  実施できませんでした: {bt.get('reason')}")
    else:
        A(f"  問1: 乖離zは その後{bt['horizon']}営業日のリターンを説明できるか")
        A(f"       {bt['full']}")
        A(f"       符号の的中率 : {bt['hit_rate']*100:.1f}%  (コイン投げ=50%)")
        sgn = "予想どおり（乖離は縮む方向に戻る）" if bt["full"].beta < 0 else "予想と逆（乖離が拡大する）"
        A(f"       傾きの符号   : {sgn}")
        A("")
        A(f"  問2: ランダムウォークに勝てるか（前70%で推定し、残り30%で検証）")
        A(f"       モデルの予測誤差(RMSE)       : {bt['rmse_model']:.3f} %")
        A(f"       ランダムウォークの予測誤差   : {bt['rmse_rw']:.3f} %")
        A(f"       比率 (1未満なら勝ち)         : {bt['ratio']:.3f}")
        A("")
        if bt["ratio"] < 0.98:
            A("       → この期間ではランダムウォークをわずかに上回りました。ただし")
            A("         取引コストを引くと優位が消える水準であることが多く、過信は禁物です。")
        elif bt["ratio"] < 1.02:
            A("       → ほぼ互角、つまり実質的にランダムウォークに勝てていません。")
            A("         これは失敗ではなく、為替では標準的な結果です。")
        else:
            A("       → ランダムウォークに負けました。点予測には使わないでください。")
        A("")
        A("       いずれの結果でも、このモデルの価値は「明日いくらか」ではなく")
        A("       「今の水準は説明できる範囲か」を測ることにあります。")
        if args.demo:
            A("")
            A("  [!] デモ注意: 合成データは「乖離が必ず平均に戻る」よう人工的に作って")
            A("      あるため、この成績は実データより大幅に良く出ます。実データでは")
            A("      的中率50〜55%、比率0.95〜1.05あたりに収まるのが普通です。")
            A("      ここで見てほしいのは数字の良さではなく、検証の手順のほうです。")
    A("")
    A("=" * 78)
    A(" 本ツールは教育・分析目的であり、投資助言ではありません。")
    A("=" * 78)
    return "\n".join(L)


# ==============================================================================
# main
# ==============================================================================

def main():
    ap = argparse.ArgumentParser(
        description="ドル円 金利差モデル",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", help="入力CSVのパス")
    ap.add_argument("--demo", action="store_true",
                    help="合成データでデモ実行（CSV不要）")
    ap.add_argument("--fetch", action="store_true",
                    help="FRED・財務省からデータを自動取得してから分析する"
                         "（同じフォルダに fetch_data.py が必要）")
    ap.add_argument("--fetch-start", default=None,
                    help="--fetch の取得開始日 YYYY-MM-DD（既定: 4年前）")
    ap.add_argument("--out", default=str(OUTPUT_DIR), help="出力先フォルダ")
    ap.add_argument("--spot", type=float, default=None,
                    help="シナリオ計算に使う現在値（省略時はデータの最終値）")
    ap.add_argument("--spot-asof", default=None, metavar="日時",
                    help="--spot の値をどの時点で取得したか。"
                         "例: --spot-asof '2026-09-09 23:20'。"
                         "省略すると実行時刻が使われます")
    ap.add_argument("--p-fomc-hike", type=float, default=0.55,
                    help="市場が織り込むFOMC利上げ確率 0〜1 (既定 0.55)")
    ap.add_argument("--p-boj-hike", type=float, default=0.60,
                    help="市場が織り込む日銀利上げ確率 0〜1 (既定 0.60)")
    ap.add_argument("--exception", type=float, default=1.0,
                    help="例外フィルターの割引係数 0〜1 (1.0=例外なし)")
    ap.add_argument("--method", choices=["beta", "level"], default="beta",
                    help="フェアバリューの推定方式 (既定 beta)。level は教科書的な"
                         "水準回帰で、壊れ方を見るためのもの")
    ap.add_argument("--beta", choices=["rolling", "full"], default="rolling",
                    help="感応度をローリングで推定するか、全期間で1本にするか。"
                         "full は同梱のExcel版と同じ計算になります (既定 rolling)")
    ap.add_argument("--no-trend", action="store_true",
                    help="フェアバリュー回帰から時間トレンド項を外す（単回帰にする）")
    ap.add_argument("--window", type=int, default=ROLL_WINDOW,
                    help=f"ローリング回帰の窓（営業日, 既定 {ROLL_WINDOW}）")
    ap.add_argument("--no-charts", action="store_true", help="グラフを作らない")
    ap.add_argument("--html", action="store_true",
                    help="結果を1枚のWebページ output/index.html に書き出す")
    ap.add_argument("--open", action="store_true",
                    help="--html で作ったページをブラウザで開く")
    ap.add_argument("--publish", nargs="?", const="~/株分析/data/charts/usdjpy.html",
                    default=None, metavar="コピー先",
                    help="--html で作ったページを公開用フォルダにコピーする。"
                         "既定は ~/株分析/data/charts/usdjpy.html "
                         "（deploy_github.sh がそのままGitHub Pagesに載せます）")
    args = ap.parse_args()

    if args.fetch:
        try:
            import fetch_data
        except ImportError:
            ap.error("--fetch には fetch_data.py が必要です。"
                     "usdjpy_model.py と同じフォルダに置いてください。")
        from datetime import date, timedelta
        today = date.today()
        start = args.fetch_start or str(today - timedelta(days=365 * 4 + 30))
        print(f"\nデータを自動取得します（{start} 〜 {today}）\n")
        fetched = fetch_data.build(start, str(today))
        out = args.csv or "data.csv"
        fetched.to_csv(out, index=False, encoding="utf-8")
        print(f"\n[取得完了] {out} に {len(fetched)}行 保存しました。\n")
        args.csv = out

    if not args.csv and not args.demo:
        ap.error("--csv / --demo / --fetch のいずれかを指定してください。\n"
                 "  --fetch  … データを自動取得して分析（おすすめ）\n"
                 "  --demo   … 合成データで動きだけ確認\n"
                 "  --csv    … 手元のCSVで分析")

    tag = ""
    if args.demo:
        df = make_demo_data()
        tag = "  ※合成デモデータ"
        print("\n*** デモモード: 以下はすべて合成データによる出力です。"
              "実際の相場ではありません。 ***\n")
    else:
        df = load_data(args.csv)

    df = add_features(df)
    df = fair_value(df, window=args.window, method=args.method,
                    use_trend=not args.no_trend, beta_mode=args.beta)

    sens = sensitivity(df)
    bt = backtest(df)
    spot = args.spot if args.spot else sens["spot"]
    grid = scenario_grid(spot, sens["pct_per_pt"], args.p_fomc_hike, args.p_boj_hike)

    # 方向性スコアの入力。ここを手で書き換えて使ってください（-2〜+2）
    args.score_inputs = {
        "日米金利差の方向": -1.0,   # 縮小方向 → 円高寄り
        "FRBのタカ派度":   +1.5,   # 利上げ観測 → 円安寄り
        "日銀のタカ派度":  -1.5,   # 利上げ観測 → 円高寄り（符号が逆）
        "米CPI":           -0.5,   # コアは鈍化 → やや円高寄り
        "米雇用統計":      +1.5,   # 大幅上振れ → 円安寄り
    }
    score = direction_score(args.score_inputs, args.exception)

    txt = report(df, sens, bt, grid, score, args)
    print(txt)

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "report.txt").write_text(txt, encoding="utf-8")
    df.to_csv(outdir / "analysis_detail.csv", index=False, encoding="utf-8-sig")
    grid.to_csv(outdir / "scenario_grid.csv", index=False, encoding="utf-8-sig")

    if not args.no_charts:
        try:
            files = make_charts(df, sens, bt, outdir, tag)
            print(f"\n[出力] グラフ {len(files)}枚: " +
                  ", ".join(f.name for f in files))
        except Exception as e:
            print(f"[警告] グラフ作成に失敗しました: {e}", file=sys.stderr)

    if args.html:
        try:
            import html_report
            page = html_report.write_html(df, sens, bt, grid, score, args,
                                          outdir, SCORE_ITEMS)
            print(f"\n[出力] Webページ: {page.resolve()}")
            print(f"       ブラウザで開く:  open {page}")
            if args.publish:
                dest = Path(args.publish).expanduser()
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(page.read_bytes())
                print(f"[公開] {dest} にコピーしました。")
                print(f"       次に `bash ~/株分析/deploy_github.sh` を実行すると、")
                print(f"       スマホから見られるURLに反映されます。")
            if args.open:
                import webbrowser
                webbrowser.open(page.resolve().as_uri())
        except ImportError:
            print("[警告] html_report.py が見つかりません。"
                  "usdjpy_model.py と同じフォルダに置いてください。", file=sys.stderr)
        except Exception as e:
            print(f"[警告] Webページの作成に失敗しました: {e}", file=sys.stderr)

    print(f"[出力] {outdir.resolve()} に report.txt / analysis_detail.csv / "
          f"scenario_grid.csv を保存しました。")


if __name__ == "__main__":
    main()
