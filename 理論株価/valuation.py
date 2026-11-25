"""東証全銘柄の理論株価（7手法）と、需給・心理・市場の織り込みによる補正の比較

入力（どれも通信なし。run_fundamentals.sh・需給分析が作ったファイルを読むだけ）
  fundamentals/analysis/スコア一覧.csv     株価・EPS・BPS・会社予想・ベータ・テクニカル・需給スコア
  fundamentals/fundamentals_latest.csv     株数・EBITDA・純有利子負債・有利子負債・支払利息
  fundamentals/fundamentals_by_year.csv    フリーCFの3期平均
  ドル円モデル/data.csv                    日本10年国債利回り（無リスク金利）

出力
  fundamentals/valuation.csv               最新の結果（ほかのスクリプトから使う用）
  理論株価/output/理論株価_YYYY-MM-DD.csv  日付ごとの控え（60日で掃除）
  理論株価/data/valuation.sqlite           全履歴（テーブル valuation、日付×コード）
  ページは report_valuation.py が作る（data/charts/valuation.html）

手法（ファンダメンタルの理論株価）
  1 PER法    予想EPS × 適正PER（自社の過去3期のPERの加重平均3:2:1。そろわなければ直近のPER（株価÷実績EPS）→業種の予想PER中央値）
  2 PBR法    BPS（実績）× 適正PBR。適正PBR＝適正PER × ROE（赤字なら自社の過去PBR→理論PBR）
  3 DCF法    フリーCF（3期平均。赤字や予想純利益の30%未満なら予想純利益→税引後営業利益×50%）を10年（5年成長→5年で永久成長率へ減速）＋継続価値でWACC割引
  4 DDM      予想配当を5年成長→5年減速→永久成長で株主資本コスト割引
  理論株価（ファンダ）＝ 上の4手法と、下のRIM・はっしゃん式・東洋経済式を合わせた7手法（類似企業比較は2026/10に除外）の有効な値の中央値

補正（比較用）
  A 需給補正   需給スコア（50が中立）で ±10%
  B 心理補正   モメンタム（250日・125日騰落率、52週レンジ位置）と過熱（RSI・25日線乖離）で ±15%
  C 市場の織り込み  業種の予想PERの25/50/75%点で見た価格帯と、今の株価が織り込むDCFの成長率

6 RIM（残余利益モデル）
  理論株価＝BPS＋Σ(ROE_t−株主資本コスト)×BPS_{t−1}÷(1＋株主資本コスト)^t＋継続価値
  1〜2年目のROE＝今期予想EPS÷BPS（無ければ実績）、3〜10年目で業種のROE中央値へ線形に収れん
  BPSはクリーンサープラス（BPS＋EPS−配当）で積み上げ。11年目以降の残余利益は毎年 持続率ω で減衰
  織り込みROE＝今の株価を定常RIM（P＝B×(1＋(ROE−ke)/(ke−g))）で説明するROE

7 はっしゃん式理論株価
  理論株価＝(資産価値＋事業価値)×市場リスク評価率、上限株価＝資産価値＋事業価値×2
  資産価値＝BPS×割引評価率（自己資本比率80%以上0.8／67%以上0.75／50%以上0.7／33%以上0.65／10%以上0.6／未満0.5）
  事業価値＝EPS×ROA×150×財務レバレッジ補正
    EPS＝今期予想経常利益×0.7÷株数（予想が無ければ直近の経常利益、それも無ければ税引前利益）。BPSの60%が上限
    ROA＝EPS÷(BPS÷自己資本比率)、上限30%。財務レバレッジ補正＝1÷(自己資本比率＋0.33)（0.66〜1でクリップ＝1.0〜1.5倍）
  市場リスク：実際のPBRが0.5倍未満なら割引（0.41〜0.49倍×0.8、0.34〜×0.67、0.25〜×0.5、0.21〜×0.34、0.04〜0.20倍×0.25→0.05、それ未満×0.025→0.005）

8 東洋経済式（会社四季報の理論株価。四季報プロ500「破綻危険度・理論株価の詳細解説」の計算式）
  理論株価＝直近期BPS＋将来の1株当たり超過利益の現在価値
  超過利益の現在価値＝Σ(EPS_t−BPS_{t−1}×ke)÷(1＋ke)^t を n期まで（継続価値なし）
  n＝10期（toyo_n_max / toyo_n_min）。四季報の2026/9/2時点の理論株価一覧（約3,600銘柄）に最もよく合う期数
  1期目＝今期予想EPS、2期目＝来期予想EPS。予想の無い期は直前の予想ROE（EPS÷期首BPS）が続くとして EPS＝ROE×期首BPS
  ke（株主資本コスト）＝10年国債利回り＋β×株式リスクプレミアム4.5%。βは修正ベータ（0.67β＋0.33）を0.6〜1.5に制限
    （四季報の一覧への当てはめで決めた値。小型株の上乗せは使わない）
  直近期BPS＝決算短信の公式BPS（自己資本ベース・最新の本決算、分割調整済み。bps_official.py）。無ければYahooのBPS
  今期予想BPS＝直近期BPS＋今期予想EPS−今期予想配当（クリーンサープラス）
  BPS_t＝BPS_{t−1}＋EPS_t−配当_t（クリーンサープラス。2期目以降の配当は今期予想の配当性向）
  特殊要因による過大な値を避けるため、株価の3倍を上限とする（東洋経済と同じ。toyo_cap＝None で上限なし）
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
DIR = Path(__file__).resolve().parent
FUND = BASE / "fundamentals"

# ---------------------------------------------------------------- 前提（ここを変えると全銘柄が変わる）
P = dict(
    rf_default=0.020,   # 10年国債が読めないときの無リスク金利
    mrp=0.050,          # 株式リスクプレミアム（日本株の一般的な目安 5〜6%の下寄り）
    g_term=0.015,       # 永久成長率（名目）
    tax=0.30,           # 実効税率
    beta_lo=0.5, beta_hi=1.8,
    size_prem=[(100e8, 0.015), (300e8, 0.010), (1000e8, 0.005)],   # 時価総額がこれ未満なら上乗せ
    dcf_small=0.30,            # FCF3期平均が予想純利益のこの割合未満なら「極端に小さい」→予想純利益を出発点に
    g1_lo=-0.05, g1_hi=0.15,   # DCFの当初5年の成長率の上下限
    g1_hi_growth=0.30,         # 過去の売上CAGRと会社予想がともに15%超の高成長企業だけ、上限を30%に
    ddm_min_payout=0.25,       # 配当性向がこれ未満の会社はDDMを使わない（配当で価値を表さない成長企業）
    rim_moat=0.5,              # RIM：業種ROEを上回る分のうち、長期に残る割合（0＝業種平均まで戻る）
    gd_hi=0.08,                # 配当成長率の上限
    pbr_lo=0.2, pbr_hi=8.0,    # 理論PBRの上下限
    max_mult=15.0,
    rim_omega=0.6,
    mode_tol=0.10,
    own_per_lo=3.0, own_per_hi=150.0,
    roe_cap=0.60,              # PBR法（適正PER×ROE）に使うROEの上限   # 自社の過去PERとして使う範囲（外れた期は除く）
    anchor_w=0.5,              # 要確認の銘柄：自社の過去PBRにもとづく株価の重み（0.5＝7手法の中央値と半々）             # 最頻値：±10%以内に集まった手法をひとかたまりとみなす             # RIM：11年目以降の残余利益の持続率（0＝消える、1＝永久に続く）             # 株価の15倍超・0以下の手法値は異常値として捨てる
    toyo_cap=3.0,              # 東洋経済式：株価に対する倍率の上限（四季報と同じ3倍。None＝上限なし）
    toyo_n_max=10,             # 東洋経済式：来期予想がある銘柄の期数n（四季報一覧に合わせて10）
    toyo_n_min=10,             # 東洋経済式：来期予想が無い銘柄の期数n
    toyo_mrp=0.045,            # 東洋経済式：株式リスクプレミアム（四季報一覧への当てはめ）
    toyo_beta_adj=True,        # 東洋経済式：修正ベータ（0.67β＋0.33）を使う
    toyo_beta_lo=0.6, toyo_beta_hi=1.5,
    jukyu_amp=0.10,            # 需給補正の最大幅
    psy_amp=0.15,              # 心理補正の最大幅
)
METHODS = ["PER法", "PBR法", "DCF法", "DDM", "はっしゃん式", "RIM", "東洋経済式"]


def log(*a):
    print(*a, flush=True)


def num(s):
    return pd.to_numeric(s, errors="coerce")


def risk_free() -> tuple[float, str]:
    f = BASE / "ドル円モデル" / "data.csv"
    try:
        d = pd.read_csv(f).dropna(subset=["jp10y"])
        return float(d["jp10y"].iloc[-1]) / 100, f"日本10年国債 {d['date'].iloc[-1]}"
    except Exception:
        return P["rf_default"], "既定値"


def load() -> pd.DataFrame:
    s = pd.read_csv(FUND / "analysis" / "スコア一覧.csv", dtype={"コード": str}, low_memory=False)
    l = pd.read_csv(FUND / "fundamentals_latest.csv", dtype={"コード": str}, low_memory=False)
    keep = ["コード", "発行済株式数", "時価総額(自己株式除く)", "EBITDA", "純有利子負債", "有利子負債",
            "現金同等物", "支払利息", "営業利益", "売上高", "税引前利益", "一株配当", "株価日付", "通貨"]
    d = s.merge(l[[c for c in keep if c in l.columns]], on="コード", how="left", suffixes=("", "_l"))
    y = pd.read_csv(FUND / "fundamentals_by_year.csv", dtype={"コード": str}, low_memory=False)
    y = y.sort_values(["コード", "決算期"], ascending=[True, False])
    y["fcf"] = num(y["フリーCF"]).fillna(num(y["営業CF"]) + num(y["投資CF"]))
    f3 = y.groupby("コード").head(3).groupby("コード")["fcf"].agg(["mean", "count"])
    d = d.merge(f3.rename(columns={"mean": "FCF3期平均", "count": "FCF期数"}), left_on="コード",
                right_index=True, how="left")
    g3 = y.groupby("コード").head(3).assign(ocf=lambda t: num(t["営業CF"]), ni=lambda t: num(t["当期純利益"]))
    cc = g3.groupby("コード").agg(ocf=("ocf", "sum"), ni=("ni", "sum"), n=("ni", "count"))
    cc["現金化率"] = (cc["ocf"] / cc["ni"]).where((cc["ni"] > 0) & (cc["n"] >= 2))
    d = d.merge(cc[["現金化率"]], left_on="コード", right_index=True, how="left")
    for c in d.columns:
        if c not in ("コード", "銘柄名", "市場", "業種", "決算期", "株価日付") and d[c].dtype == object:
            if c in ("金融",):
                continue
            conv = num(d[c])
            if conv.notna().sum() > 0.5 * d[c].notna().sum():
                d[c] = conv
    fy_ = BASE / "fundamentals" / "forecast_yahoo.csv"
    if fy_.exists():
        yf_ = pd.read_csv(fy_, dtype={"コード": str}, encoding="utf-8-sig")
        yc = ["コード", "予想EPS(Yahoo)", "アナリスト数", "Yahoo取得日"] + (["来期予想EPS(Yahoo)"] if "来期予想EPS(Yahoo)" in yf_.columns else [])
        yf_ = yf_.rename(columns={"取得日": "Yahoo取得日"})[yc]
        d = d.merge(yf_, on="コード", how="left")
        for c in ("予想EPS(Yahoo)", "アナリスト数", "来期予想EPS(Yahoo)"):
            if c not in d:
                d[c] = np.nan
            d[c] = num(d[c])
    d["金融"] = d["金融"].astype(str).str.lower().isin(["true", "1"])
    # 金融子会社（販売金融・銀行・カード等）を持つ会社：貸付の増加が投資CF・営業CFに入りFCFが歪むためDCFの対象外。一覧は finance_subsidiary.csv（追加・削除可）
    fs_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "finance_subsidiary.csv")
    fs_codes = set(pd.read_csv(fs_path, dtype={"コード": str})["コード"].str.strip()) if os.path.exists(fs_path) else set()
    d["金融子会社"] = d["コード"].astype(str).str[:4].isin(fs_codes)
    # 東洋経済式に使うBPS：決算短信の公式BPS（非支配株主持分・優先株を除く自己資本ベース、Yahooより新しい本決算があればそれ）
    try:
        import bps_official
        d["BPS_短信補正"] = d["BPS"]
        d = bps_official.apply(d, bps_col="BPS_短信補正")
    except Exception as e:                      # 補正に失敗しても Yahoo のBPSで続行
        log(f"BPSの短信補正に失敗（Yahooのまま）: {e}")
        d["BPS_短信補正"], d["BPSの出所"] = d["BPS"], "Yahoo（純資産÷株数）"
    return d


def sector_stats(d: pd.DataFrame) -> pd.DataFrame:
    """業種ごとの倍率の分布。外れ値を除いて中央値・四分位を取る（業種の銘柄が5未満なら市場全体）"""
    d = d.copy()
    d["_fper"] = np.where(d["予想EPS(円)"] > 0, d["株価"] / d["予想EPS(円)"], np.nan)
    d["_per"] = np.where(d["EPS"] > 0, d["株価"] / d["EPS"], np.nan)
    d["_pbr"] = np.where(d["BPS"] > 0, d["株価"] / d["BPS"], np.nan)
    d["_eve"] = num(d["EV/EBITDA"])
    lim = {"_fper": (1, 80), "_per": (1, 80), "_pbr": (0.05, 20), "_eve": (0.5, 50)}
    for c, (lo, hi) in lim.items():
        d.loc[(d[c] < lo) | (d[c] > hi), c] = np.nan
    rows = {}
    allq = {c: d[c].quantile([.25, .5, .75]).values for c in lim}
    for sec, g in d.groupby("業種"):
        r = {}
        for c in lim:
            v = g[c].dropna()
            q = v.quantile([.25, .5, .75]).values if len(v) >= 5 else allq[c]
            r[c + "_q25"], r[c + "_q50"], r[c + "_q75"] = q
            r[c + "_n"] = len(v)
        rows[sec] = r
    return pd.DataFrame.from_dict(rows, orient="index")


def dcf_value(fcf0, g1, wacc, gT, net_debt, shares):
    """10年（5年 g1 → 5年かけて gT へ線形に減速）＋継続価値。1株あたりの株主価値を返す"""
    if not (np.isfinite(fcf0) and fcf0 > 0 and wacc > gT + 0.005 and shares > 0):
        return np.nan
    pv, f = 0.0, fcf0
    for t in range(1, 11):
        g = g1 if t <= 5 else g1 + (gT - g1) * (t - 5) / 5
        f *= 1 + g
        pv += f / (1 + wacc) ** t
    tv = f * (1 + gT) / (wacc - gT) / (1 + wacc) ** 10
    eq = pv + tv - (net_debt if np.isfinite(net_debt) else 0.0)
    return eq / shares if eq > 0 else np.nan


def dcf_ev(fcf0, g1, wacc, gT):
    """DCFの事業価値（10年分の現在価値＋継続価値）"""
    if not (np.isfinite(fcf0) and fcf0 > 0 and wacc > gT + 0.005):
        return np.nan
    pv, f = 0.0, fcf0
    for t in range(1, 11):
        g = g1 if t <= 5 else g1 + (gT - g1) * (t - 5) / 5
        f *= 1 + g
        pv += f / (1 + wacc) ** t
    return pv + f * (1 + gT) / (wacc - gT) / (1 + wacc) ** 10


def ddm_value(d0, g1, ke, gT):
    if not (np.isfinite(d0) and d0 > 0 and ke > gT + 0.005):
        return np.nan
    pv, dv = 0.0, d0
    for t in range(1, 11):
        g = g1 if t <= 5 else g1 + (gT - g1) * (t - 5) / 5
        dv *= 1 + g
        pv += dv / (1 + ke) ** t
    return pv + dv * (1 + gT) / (ke - gT) / (1 + ke) ** 10


def implied_growth(price, fcf0, wacc, gT, net_debt, shares):
    """今の株価になるDCFの当初5年成長率（二分法）。範囲外なら端の値で止める"""
    if not (np.isfinite(price) and price > 0 and np.isfinite(fcf0) and fcf0 > 0):
        return np.nan
    f = lambda g: (dcf_value(fcf0, g, wacc, gT, net_debt, shares) or 0) - price
    lo, hi = -0.30, 0.60
    flo, fhi = f(lo), f(hi)
    if not np.isfinite(flo):
        flo = -price
    if flo > 0:
        return lo
    if not np.isfinite(fhi) or fhi < 0:
        return hi
    for _ in range(50):
        mid = (lo + hi) / 2
        fm = f(mid)
        if not np.isfinite(fm):
            fm = -price
        lo, hi = (mid, hi) if fm < 0 else (lo, mid)
    return (lo + hi) / 2


def pct_rank(s: pd.Series) -> pd.Series:
    return s.rank(pct=True) - 0.5          # −0.5〜+0.5、欠損は欠損


def hist_mult() -> pd.DataFrame:
    """自社の過去の評価倍率（直近3期の加重平均。新しい期ほど重く 3:2:1）
      PER ＝ 期中の平均株価 ÷ その期のEPS（＝平均時価総額 ÷ 純利益）
      PBR ＝ 期中の平均株価 ÷ その期末のBPS
    株価CSV・EPS・BPSとも分割調整済みなので、分割をまたいでもずれない。2期以上そろわない倍率は欠損"""
    yrs = pd.read_csv(FUND / "fundamentals_by_year.csv", dtype={"コード": str}, low_memory=False)
    yrs = yrs.sort_values(["コード", "決算期"], ascending=[True, False])
    W = [3.0, 2.0, 1.0]
    out = {}

    def wavg(v):
        v = [(x, w) for x, w in v if x is not None]
        if len(v) < 2:
            return np.nan
        return float(sum(x * w for x, w in v) / sum(w for _, w in v))

    for c, g in yrs.groupby("コード"):
        f = BASE / "data" / "prices" / f"{c}.csv"
        if not f.exists():
            continue
        try:
            p = pd.read_csv(f, usecols=["date", "close"]).dropna()
        except Exception:
            continue
        dts, cl = p["date"].to_numpy(dtype=str), p["close"].to_numpy(dtype=float)
        pe, pb = [], []
        for k, (_, r) in enumerate(g.head(3).iterrows()):
            end = str(r["決算期"])[:10]
            start = f"{int(end[:4]) - 1}{end[4:]}"
            m = (dts > start) & (dts <= end)
            if m.sum() < 120:
                continue
            avg = cl[m].mean()
            e = num(pd.Series([r["EPS"]])).iloc[0]
            b = num(pd.Series([r["BPS"]])).iloc[0]
            x = avg / e if e and e > 0 else None
            pe.append((x if x is not None and P["own_per_lo"] <= x <= P["own_per_hi"] else None, W[k]))
            y = avg / b if b and b > 0 else None
            pb.append((y if y is not None and 0.05 <= y <= 100 else None, W[k]))
        out[c] = (wavg(pe), wavg(pb))
    return pd.DataFrame.from_dict(out, orient="index", columns=["own_per", "own_pbr"])


def hist_pbr(codes, years: pd.DataFrame) -> dict:
    """過去3期の決算期末のPBR（株価CSVの期末終値÷その期のBPS）。候補の銘柄だけ読む"""
    out = {}
    yy = years[years["コード"].isin(codes)]
    for c, g in yy.groupby("コード"):
        f = BASE / "data" / "prices" / f"{c}.csv"
        if not f.exists():
            continue
        try:
            p = pd.read_csv(f, usecols=["date", "close"])
        except Exception:
            continue
        p = p.dropna().sort_values("date")
        v = []
        for _, r in g.head(3).iterrows():
            q = p[p["date"] <= str(r["決算期"])[:10]]
            b = num(pd.Series([r["BPS"]])).iloc[0]
            if len(q) and b and b > 0:
                v.append(float(q["close"].iloc[-1]) / b)
        out[c] = v
    return out


def build() -> tuple[pd.DataFrame, dict]:
    rf, rf_src = risk_free()
    gT = P["g_term"]
    d = load()
    ss = sector_stats(d)
    d = d.join(ss, on="業種")
    px = d["株価"]
    sh = d["発行済株式数"].where(d["発行済株式数"] > 0)
    sh = sh.fillna(d["時価総額(自己株式除く)"] / px)
    mcap = d["時価総額(自己株式除く)"].fillna(px * sh)

    # ---- 資本コスト
    beta = d["ベータ"].clip(0, 3)
    badj = (0.67 * beta + 0.33).clip(P["beta_lo"], P["beta_hi"]).fillna(1.0)
    size = pd.Series(0.0, index=d.index)
    for lim, add in sorted(P["size_prem"], key=lambda x: -x[0]):
        size = size.where(~(mcap < lim), add)
    ke = rf + badj * P["mrp"] + size
    debt = d["有利子負債"].fillna(0).clip(lower=0)
    kd = (d["支払利息"] / debt.replace(0, np.nan)).clip(0.005, 0.06).fillna(rf + 0.01)
    wv = mcap / (mcap + debt)
    wacc = (wv * ke + (1 - wv) * kd * (1 - P["tax"])).clip(lower=gT + 0.02)
    nd = d["純有利子負債"].fillna(d["有利子負債"] - d["現金同等物"]).fillna(0)

    # ---- 成長率
    sg_hist = d["売上高CAGR(%)"] / 100
    sg_fwd = d["予想売上高成長率(%)"] / 100
    hi_growth = (sg_hist > 0.15) & (sg_fwd > 0.15)
    g1_cap = pd.Series(np.where(hi_growth, P["g1_hi_growth"], P["g1_hi"]), index=d.index)
    g1 = pd.concat([sg_hist, sg_fwd], axis=1).mean(axis=1).clip(lower=P["g1_lo"]).clip(upper=g1_cap).fillna(0.02)

    # 予想EPS：最新のアナリスト予想（Yahoo、取得から45日以内・会社予想や実績と桁が合うもの）→ 会社予想（J-Quants）→ 実績
    eps_jq = d["予想EPS(円)"]
    ey = d.get("予想EPS(Yahoo)")
    if ey is not None:
        base_e = eps_jq.where(eps_jq.notna(), d["EPS"])
        r_ = ey / base_e
        fresh = pd.to_datetime(d["Yahoo取得日"], errors="coerce") >= pd.Timestamp.today() - pd.Timedelta(days=45)
        ok_y = ey.notna() & fresh & (d["アナリスト数"].fillna(0) >= 1) & (base_e.isna() | ((r_ > 0.33) & (r_ < 3)) | (base_e <= 0))
    else:
        ok_y = pd.Series(False, index=d.index)
        ey = pd.Series(np.nan, index=d.index)
    eps_f = ey.where(ok_y, eps_jq.where(eps_jq.notna(), d["EPS"]))
    eps_src = np.where(ok_y, "アナリスト予想(Yahoo)", np.where(eps_jq.notna(), "会社予想(決算短信)", "実績"))
    d["予想EPS(円)"] = ey.where(ok_y, eps_jq)          # PER法・業種PERの判定も最新の予想で
    bps = d["BPS"]

    # 1 PER法：予想EPS × 適正PER。適正PER＝自社の過去3期のPER（平均株価÷EPS＝時価総額÷純利益）の加重平均（3:2:1）。
    #   過去のPERが2期以上そろわない銘柄（上場間もない・赤字が多い）は直近のPER→業種の予想PER中央値
    HM = hist_mult()
    own_per = d["コード"].map(HM["own_per"])
    own_pbr = d["コード"].map(HM["own_pbr"])
    sec_per = d["_fper_q50"].where(d["予想EPS(円)"].notna(), d["_per_q50"])
    # 過去のPERが2期そろわない銘柄は直近のPER（今の株価÷直近決算の実績EPS）。それも無い・範囲外なら業種の予想PER中央値
    cur_per = (px / d["EPS"]).where(d["EPS"] > 0)
    cur_per = cur_per.where((cur_per >= P["own_per_lo"]) & (cur_per <= P["own_per_hi"]))
    per_mult = own_per.fillna(cur_per).fillna(sec_per)
    per_basis = np.where(own_per.notna(), "自社の過去PER", np.where(cur_per.notna(), "直近のPER（過去2期そろわず）", "業種の予想PER"))
    v_per = (eps_f * per_mult).where(eps_f > 0)

    # 2 PBR法：BPS（実績）× 適正PBR。
    #   適正PBR＝自社の過去3期のPBR（期中の平均株価÷期末BPS）の加重平均（3:2:1）。そろわない銘柄は理論PBR（(ROE−g)/(株主資本コスト−g)）
    #   適正PBRを実績BPSで測っているので、当てはめるのも実績BPS（予想BPSは使わない）
    roe = pd.concat([d["ROE(%)"], d["平均ROE(%)"]], axis=1).mean(axis=1) / 100
    roe = roe.clip(-0.2, 0.4)
    jpbr = ((roe - gT) / (ke - gT)).clip(P["pbr_lo"], P["pbr_hi"])
    fbps = bps.where(bps > 0)
    # 適正PBR ＝ 適正PER × ROE（PBR＝PER×ROE）。今の稼ぐ力（ROE）を反映する
    #   ROE＝直近の実績。一時的な跳ね上がりに備え、3期平均の1.5倍を超えるときは直近と平均の平均。上限は roe_cap
    roe_act = d["ROE(%)"] / 100
    roe_avg = d["平均ROE(%)"] / 100
    spike = (roe_avg > 0) & (roe_act > roe_avg * 1.5)
    roe_use = roe_act.where(~spike, (roe_act + roe_avg) / 2).clip(upper=P["roe_cap"])
    pbr_from_per = (per_mult * roe_use).where(roe_use > 0)
    pbr_mult = pbr_from_per.fillna(own_pbr).fillna(jpbr)
    pbr_basis = np.where(pbr_from_per.notna(), "適正PER×ROE", np.where(own_pbr.notna(), "自社の過去PBR", "理論PBR"))
    v_pbr = (fbps * pbr_mult).where(bps > 0)

    # 3 DCF法（金融は対象外：預金・保険負債を負債とみなすとFCFが意味を持たない）
    #   出発点：フリーCFの3期平均。赤字または予想純利益の30%未満（成長投資で一時的に小さい）なら予想純利益（予想EPS×株数）。
    #   予想純利益も無い・赤字なら税引後営業利益×50%
    fcf3 = d["FCF3期平均"].copy()
    ni_f = (eps_f * sh).where((eps_f > 0) & (sh > 0))
    alt = (d["営業利益"] * (1 - P["tax"]) * 0.5).where(d["営業利益"] > 0)
    small = (fcf3 <= 0) | fcf3.isna() | (ni_f.notna() & (fcf3 < ni_f * P["dcf_small"]))
    use_fcf = (fcf3 > 0) & ~small
    use_ni = ~use_fcf & ni_f.notna()
    use_alt = ~use_fcf & ~use_ni & alt.notna()
    fcf0 = fcf3.where(use_fcf, ni_f.where(use_ni, alt.where(use_alt)))
    why = np.where(fcf3 > 0, "FCFが予想純利益の30%未満のため", "FCFが赤字のため")
    fcf_src = np.where(use_fcf, "フリーCFの3期平均",
              np.where(use_ni, pd.Series("予想純利益（", index=d.index) + why + "）",
              np.where(use_alt, pd.Series("税引後営業利益×50%（", index=d.index) + why + "）", "")))
    ev_dcf = pd.Series([dcf_ev(f, g, w, gT) for f, g, w in zip(fcf0, g1, wacc)], index=d.index)
    v_dcf = pd.Series([dcf_value(f, g, w, gT, n, s) if not fin else np.nan
                       for f, g, w, n, s, fin in zip(fcf0, g1, wacc, nd, sh, d["金融"] | d["金融子会社"])], index=d.index)

    # 4 DDM
    d0 = d["予想1株配当(円)"].where(d["予想1株配当(円)"] > 0, d["一株配当"])
    payout = (d0 / eps_f).where(eps_f > 0)
    sus = (roe * (1 - payout.clip(0, 1))).where(payout.notna())
    gd = pd.concat([d["配当CAGR(%)"] / 100, sus], axis=1).min(axis=1).clip(0, P["gd_hi"]).fillna(0)
    v_ddm = pd.Series([ddm_value(a, b, c, gT) for a, b, c in zip(d0, gd, ke)], index=d.index)
    v_ddm = v_ddm.where(~(payout < P["ddm_min_payout"]))

    # （参考・理論株価には使わない）類似企業（業種中央値の EV/EBITDA と PBR）
    v_eve = ((d["_eve_q50"] * d["EBITDA"] - nd) / sh).where((d["EBITDA"] > 0) & ~d["金融"])
    v_eve = v_eve.where(v_eve > 0)
    v_cpb = (d["_pbr_q50"] * bps).where(bps > 0)
    v_cmp = pd.concat([v_eve, v_cpb], axis=1).mean(axis=1)

    # ---- A 需給補正
    js = d["需給スコア"]
    f_j = (1 + P["jukyu_amp"] * ((js - 50) / 35).clip(-1, 1)).fillna(1.0)

    # ---- B 心理補正（モメンタム＋過熱）
    mom = (0.4 * pct_rank(d["250日騰落率(%)"]).fillna(0) + 0.3 * pct_rank(d["125日騰落率(%)"]).fillna(0)
           + 0.3 * pct_rank(d["52週レンジ位置(%)"]).fillna(0)) * 2          # −1〜+1
    rsi, dev25 = d["RSI(14)(%)"], d["25日線乖離(%)"]
    heat = pd.Series(0.0, index=d.index)
    heat -= np.where(rsi >= 75, 0.3, 0) ; heat += np.where(rsi <= 25, 0.2, 0)
    heat -= np.where(dev25 >= 20, 0.3, 0) ; heat += np.where(dev25 <= -20, 0.2, 0)
    psy = ((mom + heat).clip(-1.2, 1.2) / 1.2)
    f_p = 1 + P["psy_amp"] * psy

    # ---- 参考：RIM（残余利益モデル）
    roe_all = d["ROE(%)"].where(d["ROE(%)"].between(-50, 60)) / 100
    sec_roe = roe_all.groupby(d["業種"]).transform("median").fillna(roe_all.median())
    om = P["rim_omega"]

    def rim(b0, eps1, dps1, ke_, roe_lt):
        if not (np.isfinite(b0) and b0 > 0 and np.isfinite(eps1) and np.isfinite(ke_)):
            return (np.nan,) * 3
        roe1 = float(np.clip(eps1 / b0, -0.5, 0.6))
        po = float(np.clip(dps1 / eps1, 0, 1)) if (np.isfinite(dps1) and eps1 > 0) else 0.3
        b, pv, ri = b0, 0.0, 0.0
        for t in range(1, 11):
            tgt = roe_lt + max(roe1 - roe_lt, 0) * P["rim_moat"]     # 業種を上回る分は一部が残る（競争優位）
            r_t = roe1 if t <= 2 else roe1 + (tgt - roe1) * (t - 2) / 8
            ri = (r_t - ke_) * b
            pv += ri / (1 + ke_) ** t
            e = r_t * b
            b = b + e - (e * po if e > 0 else 0)
            if b <= 0:
                break
        tv = ri * om / (1 + ke_ - om) / (1 + ke_) ** 10
        return b0 + pv + tv, pv, tv

    d0r = d["予想1株配当(円)"].where(d["予想1株配当(円)"] >= 0, d["一株配当"])
    R3 = [rim(b, e, dv, k, rl) for b, e, dv, k, rl in zip(bps, eps_f, d0r, ke, sec_roe)]
    rim_v = pd.Series([x[0] for x in R3], index=d.index)
    rim_v = rim_v.where(rim_v > 0)
    rim_pv = pd.Series([x[1] for x in R3], index=d.index)
    rim_tv = pd.Series([x[2] for x in R3], index=d.index)
    imp_roe = ke + ((px / bps) - 1) * (ke - gT)

    # ---- 東洋経済式（会社四季報の理論株価）
    bps_tk = d["BPS_短信補正"].where(d["BPS_短信補正"].notna(), bps)     # 短信の公式BPS（自己資本ベース・最新の本決算）。bps_official.py
    #   理論株価＝直近期BPS＋(今期予想EPS−直近期BPS×ke)/(1+ke)＋(来期予想EPS−今期予想BPS×ke)/(1+ke)^2
    #   ke＝10年国債利回り＋β×リスクプレミアム。株価の3倍が上限
    beta_tk = d["ベータ"].clip(0, 3)
    if P["toyo_beta_adj"]:
        beta_tk = 0.67 * beta_tk + 0.33
    beta_tk = beta_tk.clip(P["toyo_beta_lo"], P["toyo_beta_hi"]).fillna(1.0)
    ke_tk = rf + beta_tk * P["toyo_mrp"]
    e1_tk = eps_f
    ey2 = d["来期予想EPS(Yahoo)"] if "来期予想EPS(Yahoo)" in d else pd.Series(np.nan, index=d.index)
    r2 = ey2 / e1_tk
    ok2 = ok_y & ey2.notna() & ((e1_tk <= 0) | ((r2 > 0.33) & (r2 < 3)))
    e2_src = np.where(ok2, "アナリスト予想(Yahoo)", "来期予想なし（今期ROE横ばいで延長）")
    dps_tk = d0r.fillna(0).clip(lower=0)
    po_tk = (dps_tk / e1_tk).where(e1_tk > 0).clip(0, 1).fillna(0)
    n_tk = pd.Series(np.where(ok2, P["toyo_n_max"], P["toyo_n_min"]), index=d.index)
    NT = max(P["toyo_n_max"], P["toyo_n_min"])
    b_prev = bps_tk.copy()
    pv_tk = pd.Series(0.0, index=d.index)
    RI, EPS_T = {}, {}
    roe_last = pd.Series(np.nan, index=d.index)
    for t in range(1, NT + 1):
        if t == 1:
            e_t = e1_tk
            dv_t = dps_tk
        else:
            if t == 2:
                roe_last = (e1_tk / bps_tk).where(bps_tk > 0)              # 来期予想が無い銘柄はここから延長
            e_ext = (roe_last.clip(-0.5, 0.6) * b_prev)
            e_t = ey2.where(ok2, e_ext) if t == 2 else e_ext
            if t == 2:
                roe_last = roe_last.where(~ok2, (ey2 / b_prev).where(b_prev > 0))   # 3期目以降は来期予想ROE
            dv_t = (e_t * po_tk).where(e_t > 0, 0.0)
        act = t <= n_tk
        ri_t = (e_t - b_prev * ke_tk).where(act)
        RI[t], EPS_T[t] = ri_t, e_t.where(act)
        pv_tk = pv_tk + (ri_t / (1 + ke_tk) ** t).fillna(0).where(act, 0.0)
        b_prev = (b_prev + e_t - dv_t).where(act, b_prev)
        if t == 1:
            b1_tk = b_prev.copy()
    e2_tk = EPS_T[2]
    ri1_tk, ri2_tk = RI[1], RI[2]
    tk_raw = (bps_tk + pv_tk).where((bps_tk > 0) & e1_tk.notna() & RI[1].notna())
    cap_ = P.get("toyo_cap")
    tk_capped = (tk_raw > px * cap_) if cap_ else pd.Series(False, index=d.index)
    tk_val = (tk_raw.clip(upper=px * cap_) if cap_ else tk_raw).where(tk_raw > 0)

    # ---- 参考：はっしゃん式
    er = (d["自己資本比率(%)"] / 100).clip(lower=0.001)
    rate = np.select([er >= .8, er >= .67, er >= .5, er >= .33, er >= .1], [.8, .75, .7, .65, .6], .5)
    asset_v = (bps * rate).where(bps > 0, 0.0)
    keijo = (d["今期予想経常利益(億円)"] * 1e8)
    keijo = keijo.fillna(d["直近経常利益率(%)"] / 100 * d["売上高"]).fillna(d["税引前利益"] if "税引前利益" in d else np.nan)
    h_eps = (keijo * 0.7 / sh).clip(upper=(bps * 0.6).where(bps > 0, 0))
    h_roa = (h_eps / (bps / er)).clip(upper=0.30)
    lev = 1 / (er + 0.33).clip(0.66, 1.0)
    biz_v = (h_eps * h_roa * 150 * lev).where((h_eps > 0) & (bps > 0), 0.0)
    pbr_now = (px / bps).where(bps > 0)
    def h_risk(x):
        if not np.isfinite(x) or x >= 0.5: return 1.0
        if x > 0.40: return 0.80
        if x > 0.33: return 0.67
        if x > 0.25: return 0.50
        if x > 0.20: return 0.34
        if x >= 0.04: return 0.05 + (x - 0.04) / 0.16 * 0.20
        return 0.005 + max(x, 0) / 0.04 * 0.02
    h_rr = pbr_now.map(h_risk)
    h_val = ((asset_v + biz_v) * h_rr).where(keijo.notna() & bps.notna())
    h_cap = (asset_v + biz_v * 2).where(h_val.notna())

    V = pd.DataFrame({"PER法": v_per, "PBR法": v_pbr, "DCF法": v_dcf, "DDM": v_ddm,
                      "はっしゃん式": h_val, "RIM": rim_v, "東洋経済式": tk_val})
    V_raw = V.copy()
    bad = (V <= 0) | V.gt(px * P["max_mult"], axis=0)
    V = V.mask(bad)
    fx = d["通貨"].fillna("JPY") != "JPY"            # 外貨建て決算は株価（円）と単位が合わないので除外
    V = V.mask(fx, np.nan)
    fair = V.median(axis=1)
    nmeth = V.notna().sum(axis=1)
    # 7手法の値のちらばり（平均値・最頻値・標準偏差）
    v_mean = V.mean(axis=1)
    v_std = V.std(axis=1, ddof=1)          # 標本標準偏差（Excel の STDEV.S と同じ）。2手法未満は欠損

    def mode_val(row):
        """最頻値：連続値なので「±{tol}%以内に最も多くの手法が集まる価格」とし、その手法の値の平均を返す"""
        v = np.sort(row[np.isfinite(row)])
        if len(v) == 0:
            return np.nan, 0
        best, bn = None, 0
        for c in v:
            grp = v[(v >= c * (1 - P["mode_tol"])) & (v <= c * (1 + P["mode_tol"]))]
            if len(grp) > bn or (len(grp) == bn and best is not None and grp.std() < best.std()):
                best, bn = grp, len(grp)
        return float(best.mean()), int(bn)
    MO = [mode_val(r) for r in V.to_numpy(dtype=float)]
    v_mode = pd.Series([m[0] for m in MO], index=V.index)
    v_mode_n = pd.Series([m[1] for m in MO], index=V.index)


    out = pd.DataFrame({
        "コード": d["コード"], "銘柄名": d["銘柄名"], "市場": d["市場"], "業種": d["業種"],
        "金融": d["金融"], "金融子会社": d["金融子会社"], "株価": px, "時価総額(億円)": (mcap / 1e8).round(1),
    })
    for m in METHODS:
        out[m] = V[m].round(1)
    out["有効手法数"] = nmeth
    out["理論株価_平均値"] = v_mean.round(1)
    out["理論株価_最頻値"] = v_mode.round(1)
    out["最頻値の手法数"] = v_mode_n.where(nmeth > 0)
    out["理論株価_標準偏差"] = v_std.round(1)
    out["変動係数(%)"] = (v_std / v_mean * 100).round(1)
    out["乖離率(平均値)(%)"] = ((v_mean / px - 1) * 100).round(1)
    out["乖離率(最頻値)(%)"] = ((v_mode / px - 1) * 100).round(1)
    out["理論株価(ファンダ)"] = fair.round(1)
    out["手法の最小"] = V.min(axis=1).round(1)
    out["手法の最大"] = V.max(axis=1).round(1)
    out["手法のばらつき(%)"] = ((V.max(axis=1) - V.min(axis=1)) / fair * 100).round(0)
    out["需給スコア"] = js
    out["需給判定"] = d.get("需給判定")
    out["需給係数"] = f_j.round(3)
    out["心理指数"] = (psy * 100).round(0)        # −100〜+100
    out["心理係数"] = f_p.round(3)
    out["理論株価(需給補正)"] = (fair * f_j).round(1)
    out["理論株価(心理補正)"] = (fair * f_p).round(1)
    out["理論株価(需給・心理込み)"] = (fair * f_j * f_p).round(1)
    for c in ["理論株価(ファンダ)", "理論株価(需給補正)", "理論株価(心理補正)", "理論株価(需給・心理込み)"]:
        out[c.replace("理論株価", "乖離率") + "(%)"] = ((out[c] / px - 1) * 100).round(1)

    # ---- C 市場の織り込み
    fe = d["予想EPS(円)"]
    use_f = fe > 0
    for q, nm in [("q25", "弱気"), ("q50", "中立"), ("q75", "強気")]:
        mult = d[f"_fper_{q}"].where(use_f, d[f"_per_{q}"])
        out[f"業種PER帯_{nm}"] = (eps_f * mult).where(eps_f > 0).round(1)
    out["予想PER"] = (px / fe).where(fe > 0).round(1)
    out["業種予想PER中央値"] = d["_fper_q50"].round(1)
    ig = pd.Series([implied_growth(p, f, w, gT, n, s) if not fin else np.nan
                    for p, f, w, n, s, fin in zip(px, fcf0, wacc, nd, sh, d["金融"] | d["金融子会社"])], index=d.index)
    out["織り込み成長率(%)"] = (ig * 100).round(1)
    out["想定成長率(%)"] = (g1 * 100).round(1)
    out["期待ギャップ(%pt)"] = ((ig - g1) * 100).round(1)

    # ---- 前提（銘柄ごと）
    out["株主資本コスト(%)"] = (ke * 100).round(2)
    out["WACC(%)"] = (wacc * 100).round(2)
    out["理論PBR"] = jpbr.round(2)
    out["配当成長率(%)"] = (gd * 100).round(1)
    out["業種PBR中央値"] = d["_pbr_q50"].round(2)
    out["業種EV/EBITDA中央値"] = d["_eve_q50"].round(1)
    out["信頼度"] = np.select([nmeth >= 5, nmeth >= 3, nmeth >= 1], ["高", "中", "低"], "算出不可")
    out["RIM_残余利益の現在価値"] = rim_pv.mask(fx).round(1)
    out["RIM_継続価値"] = rim_tv.mask(fx).round(1)
    out["今期予想ROE(%)"] = (eps_f / bps * 100).where(bps > 0).round(1)
    out["業種ROE中央値(%)"] = (sec_roe * 100).round(1)
    out["織り込みROE(%)"] = (imp_roe * 100).where(bps > 0).mask(fx).round(1)
    out["乖離率(RIM)(%)"] = ((out["RIM"] / px - 1) * 100).round(1)
    out["はっしゃん式_上限"] = h_cap.mask(fx).round(1)
    out["はっしゃん式_資産価値"] = asset_v.mask(fx).round(1)
    out["はっしゃん式_事業価値"] = biz_v.mask(fx).round(1)
    out["はっしゃん式_リスク評価率"] = h_rr.round(3)
    out["乖離率(はっしゃん式)(%)"] = ((out["はっしゃん式"] / px - 1) * 100).round(1)
    out["乖離率(東洋経済式)(%)"] = ((out["東洋経済式"] / px - 1) * 100).round(1)
    out["東洋経済式_超過利益の現在価値"] = pv_tk.where(tk_raw.notna()).mask(fx).round(1)
    out["計算_東洋_株主資本コスト(%)"] = (ke_tk * 100).round(2)
    out["計算_東洋_ベータ"] = beta_tk.round(2)
    out["計算_東洋_来期EPS"] = e2_tk.round(2)
    out["計算_東洋_来期EPSの出所"] = np.where(e1_tk.notna(), e2_src, "")
    out["計算_東洋_今期予想BPS"] = b1_tk.round(1)
    out["計算_東洋_配当"] = dps_tk.round(2)
    out["計算_東洋_超過利益1"] = ri1_tk.round(2)
    out["計算_東洋_超過利益2"] = ri2_tk.round(2)
    out["計算_東洋_n期"] = n_tk.where(tk_raw.notna())
    out["計算_東洋_BPS"] = bps_tk.round(1)
    out["計算_東洋_BPSの出所"] = d["BPSの出所"]
    out["計算_東洋_延長ROE(%)"] = (roe_last * 100).where(tk_raw.notna()).round(1)
    for t in range(3, NT + 1):
        out[f"計算_東洋_超過利益{t}"] = RI[t].round(2)
    out["計算_東洋_超過利益(3期目以降)の現在価値"] = sum(((RI[t] / (1 + ke_tk) ** t).fillna(0)) for t in range(3, NT + 1)).where(tk_raw.notna()).round(1)
    out["計算_東洋_上限適用"] = tk_capped.fillna(False)
    out["計算_東洋_上限前"] = tk_raw.round(1)
    out.loc[fx, "信頼度"] = "対象外"
    flg = lambda c: d[c].astype(str).str.lower().isin(["true", "1"]) if c in d else pd.Series(False, index=d.index)
    note = np.where(fx, "外貨建て決算", "")
    for c, t in [("EPS乖離", "EPSと株価の単位ずれの疑い"), ("決算が古い", "決算が古い"), ("一時要因の疑い", "一時的な損益の疑い")]:
        note = np.where(flg(c), np.where(note == "", t, note + "・" + t), note)
    # ---- 理論株価の当てはまりが悪い可能性（市場が長く割り引いている・利益が現金になっていない・乖離が極端）
    ratio = fair / px
    pbr_now = (px / bps).where(bps > 0)
    cand = d["コード"][(ratio > 2) | (ratio < 1 / 3) | (pbr_now < 0.5) | ((d["現金化率"] < 0.3) & ~d["金融"])]
    yrs = pd.read_csv(FUND / "fundamentals_by_year.csv", dtype={"コード": str}, low_memory=False)
    hp = hist_pbr(set(cand), yrs.sort_values(["コード", "決算期"], ascending=[True, False]))
    long_disc = d["コード"].map(lambda c: len(hp.get(c, [])) >= 3 and max(hp[c]) < 0.5) & (pbr_now < 0.5)
    cash_weak = (d["現金化率"] < 0.3) & ~d["金融"]
    extreme = ratio > 3
    rich = ratio < 1 / 3
    out["過去3期のPBR"] = d["コード"].map(lambda c: "・".join(f"{x:.2f}" for x in hp.get(c, [])) or None)
    out["利益の現金化率(%)"] = (d["現金化率"] * 100).round(0)
    for m, t in [(long_disc, "市場が3期以上PBR0.5倍未満で評価（構造的な割引の可能性）"),
                 (cash_weak, "利益が現金になっていない（3期の営業CF÷純利益が30%未満）"),
                 (extreme, "理論株価が株価の3倍超（特殊要因の確認を）"),
                 (rich, "株価が理論株価の3倍超（手法の想定を超える高い成長期待が織り込まれている）")]:
        m = m.fillna(False).to_numpy()
        note = np.where(m, np.where(note == "", t, note + "・" + t), note)
    caution = (long_disc | cash_weak | extreme | rich).fillna(False)
    out.loc[caution & out["信頼度"].isin(["高", "中"]), "信頼度"] = "低"
    out["注意"] = note

    # ---- チェックに当てはまる銘柄だけ、自社の過去PBR（市場が実際につけてきた評価）で理論株価を引き下げる
    #   自社PBR基準 ＝ 過去3期（ある分だけ）の期末PBRの中央値 × 今のBPS
    #   引き下げ後 ＝ 7手法の中央値 ×(1−w) ＋ 自社PBR基準 × w（w＝anchor_w）。上がる方向には使わない
    hist_med = d["コード"].map(lambda c: float(np.median(hp[c])) if hp.get(c) else np.nan)
    anchor = (hist_med * bps).where(bps > 0)
    w = P["anchor_w"]
    adj = (fair * (1 - w) + anchor * w)
    # 割安側の要確認は引き下げだけ、株価が理論株価の3倍超（rich）のときだけ引き上げにも使う
    down = (caution & ~rich).to_numpy() & (adj < fair).to_numpy()
    up_ = rich.fillna(False).to_numpy() & (adj > fair).to_numpy()
    use = adj.notna().to_numpy() & (down | up_)
    fair2 = fair.where(~use, adj)
    out["自社過去PBR(中央値)"] = hist_med.round(2)
    out["自社PBR基準の株価"] = anchor.round(1)
    out["理論株価(引き下げ前)"] = fair.round(1)
    out["引き下げ"] = use & down
    out["引き上げ"] = use & up_
    out["理論株価(ファンダ)"] = fair2.round(1)
    out["理論株価(需給補正)"] = (fair2 * f_j).round(1)
    out["理論株価(心理補正)"] = (fair2 * f_p).round(1)
    out["理論株価(需給・心理込み)"] = (fair2 * f_j * f_p).round(1)
    for c in ["理論株価(ファンダ)", "理論株価(需給補正)", "理論株価(心理補正)", "理論株価(需給・心理込み)"]:
        out[c.replace("理論株価", "乖離率") + "(%)"] = ((out[c] / px - 1) * 100).round(1)
    out["自社過去PER(加重平均)"] = own_per.round(1)
    out["直近PER(実績)"] = cur_per.round(1)
    out["PER法の倍率"] = per_mult.round(1)
    out["PER法の基準"] = per_basis
    out["自社過去PBR(加重平均)"] = own_pbr.round(2)
    out["BPS(実績)"] = fbps.round(1)
    out["PBR法の倍率"] = pbr_mult.round(2)
    out["PBR法の基準"] = pbr_basis
    out["PBR法のROE(%)"] = (roe_use * 100).round(1)
    # ---- 各手法の計算に使った値（ページで「どの値でどう計算したか」を表示する用）
    out["計算_DCF_FCF(億円)"] = (fcf0 / 1e8).round(2)
    out["計算_DCF_FCFの基準"] = np.where(d["金融子会社"], "対象外（金融子会社があり、FCFが貸付の増減で歪むため）", fcf_src)
    out["計算_DCF_事業価値(億円)"] = (ev_dcf / 1e8).round(1)
    out["計算_純有利子負債(億円)"] = (nd / 1e8).round(1)
    out["計算_株数(百万株)"] = (sh / 1e6).round(3)
    out["計算_DDM_配当(円)"] = d0.round(2)
    out["計算_配当性向(%)"] = (payout * 100).round(1)
    out["計算_EBITDA(億円)"] = (d["EBITDA"] / 1e8).round(1)
    out["計算_類似_EVEBITDA株価"] = v_eve.round(1)
    out["計算_類似_PBR株価"] = v_cpb.round(1)
    out["計算_自己資本比率(%)"] = (er * 100).round(1)
    out["計算_割引評価率"] = rate
    out["計算_はっしゃん_EPS"] = h_eps.round(2)
    out["計算_はっしゃん_ROA(%)"] = (h_roa * 100).round(2)
    out["計算_レバレッジ補正"] = lev.round(3)
    out["計算_経常利益(億円)"] = (keijo / 1e8).round(1)
    roe1_ = (eps_f / bps).clip(-0.5, 0.6)
    out["計算_RIM_目標ROE(%)"] = ((sec_roe + (roe1_ - sec_roe).clip(lower=0) * P["rim_moat"]) * 100).round(1)
    exc = []
    for i in range(len(V_raw)):
        names = [m for m in METHODS if pd.notna(V_raw.iloc[i][m]) and pd.isna(V.iloc[i][m])]
        exc.append("・".join(names))
    out["計算_除外した手法"] = exc
    out["予想EPS"] = eps_f.round(2)
    out["予想EPSの出所"] = eps_src
    out["基準日"] = d.get("株価日付")

    meta = dict(P, rf=rf, rf_src=rf_src, 銘柄数=len(out), 算出数=int(fair.notna().sum()))
    return out, meta


def write_db(path: Path, t: pd.DataFrame, asof: str, meta: dict) -> None:
    con = sqlite3.connect(path)
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(valuation)")]
        if cols and cols != list(t.columns):      # 列が変わったら旧表を退避して作り直す
            from datetime import datetime as _dt
            con.execute(f"ALTER TABLE valuation RENAME TO valuation_old_{_dt.now():%Y%m%d_%H%M%S}")
        elif cols:
            con.execute("DELETE FROM valuation WHERE 日付 = ?", (asof,))
        t.to_sql("valuation", con, if_exists="append", index=False)
        con.execute("CREATE INDEX IF NOT EXISTS ix_val ON valuation(コード, 日付)")
        con.execute("CREATE TABLE IF NOT EXISTS meta(日付 TEXT PRIMARY KEY, json TEXT)")
        con.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (asof, json.dumps(meta, ensure_ascii=False)))
        con.commit()
    finally:
        con.close()


def save(out: pd.DataFrame, meta: dict) -> str:
    asof = str(out["基準日"].dropna().max() or date.today().isoformat())[:10]
    out.to_csv(FUND / "valuation.csv", index=False, encoding="utf-8-sig")
    (DIR / "output").mkdir(exist_ok=True)
    out.to_csv(DIR / "output" / f"理論株価_{asof}.csv", index=False, encoding="utf-8-sig")
    for f in sorted((DIR / "output").glob("理論株価_*.csv"))[:-60]:
        f.unlink(missing_ok=True)
    (DIR / "data").mkdir(exist_ok=True)
    t = out.copy()
    t.insert(0, "日付", asof)
    t["金融"] = t["金融"].astype(int)
    db = DIR / "data" / "valuation.sqlite"
    # 一時フォルダで更新してから丸ごと書き戻す（同期フォルダや共有フォルダでジャーナルが残って壊れるのを防ぐ）
    import shutil, tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "v.sqlite"
        if db.exists() and db.stat().st_size > 0:
            shutil.copyfile(db, tmp)
            try:
                sqlite3.connect(tmp).execute("PRAGMA quick_check").fetchone()
            except sqlite3.DatabaseError:          # 壊れていたら退避して作り直す
                shutil.copyfile(db, db.with_suffix(f".broken_{asof}"))
                tmp.unlink()
        write_db(tmp, t, asof, meta)
        shutil.copyfile(tmp, db)
    return asof


def main() -> int:
    out, meta = build()
    asof = save(out, meta)
    meta["asof"] = asof
    (DIR / "data" / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"理論株価: {meta['算出数']}/{meta['銘柄数']} 銘柄を算出（基準日 {asof}、無リスク金利 {meta['rf']*100:.2f}% {meta['rf_src']}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
