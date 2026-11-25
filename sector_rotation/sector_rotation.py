#!/usr/bin/env python3
"""セクターローテーション分析（日米）

何をするもの？
  - 米国 S&P500 11セクター（SPDRセクターETF）
  - 日本 TOPIX-17業種（NEXT FUNDS TOPIX-17 ETF）
  - 日本 東証33業種（~/株分析/data/prices の個別株から自前で業種指数を合成）
  について、相対強度（RRG）・モメンタム・マクロ感応度（ベータ）を計算し、
  1〜3ヶ月のシナリオ別「対市場の期待超過リターン」とスコアを出します。

出力（このフォルダの output/ に保存）
  - sector_rotation_YYYY-MM-DD.xlsx   … シナリオ・重みを変えると再計算されるExcelモデル
  - sector_rotation_YYYY-MM-DD.html   … RRGチャート付きダッシュボード
  - results_YYYY-MM-DD.json           … 計算結果（他ツール連携用）

実行:
  ~/株分析/.venv/bin/python ~/株分析/sector_rotation/sector_rotation.py
"""
import json
import os
import sys
import warnings
from datetime import date

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)                      # ~/株分析
OUT = os.path.join(HERE, "output")
os.makedirs(OUT, exist_ok=True)

# ----------------------------------------------------------------------------
# 設定
# ----------------------------------------------------------------------------
US = {
    "XLK": "情報技術", "XLC": "通信サービス", "XLY": "一般消費財", "XLP": "生活必需品",
    "XLE": "エネルギー", "XLF": "金融", "XLV": "ヘルスケア", "XLI": "資本財",
    "XLB": "素材", "XLRE": "不動産", "XLU": "公益",
}
US_BENCH = "SPY"

JP17 = {
    "1617.T": "食品", "1618.T": "エネルギー資源", "1619.T": "建設・資材",
    "1620.T": "素材・化学", "1621.T": "医薬品", "1622.T": "自動車・輸送機",
    "1623.T": "鉄鋼・非鉄", "1624.T": "機械", "1625.T": "電機・精密",
    "1626.T": "情報通信・サービス", "1627.T": "電力・ガス", "1628.T": "運輸・物流",
    "1629.T": "商社・卸売", "1630.T": "小売", "1631.T": "銀行",
    "1632.T": "金融（除く銀行）", "1633.T": "不動産",
}
JP_BENCH = "1306.T"   # TOPIX連動ETF

MACRO = {
    "^TNX": "米10年金利", "^IRX": "米3ヶ月金利", "JPY=X": "ドル円",
    "CL=F": "WTI原油", "HG=F": "銅", "GC=F": "金", "^VIX": "VIX",
    "HYG": "米ハイイールド債", "IEF": "米7-10年国債",
}

# マクロ感応度（ベータ）を推定するファクター（週次変化）
#   rate : 米10年金利の変化（%ポイント）
#   oil  : 原油の変化率（%）
#   fx   : ドル円の変化率（%）  ＋＝円安
#   cuau : 銅/金レシオの変化率（%）＝景気期待
#   mkt  : 市場（ベンチマーク）の変化率（%）
FACTORS = ["rate", "oil", "fx", "cuau", "mkt"]
FACTOR_LABEL = {
    "rate": "米10年金利 変化(%pt)", "oil": "原油 変化率(%)", "fx": "ドル円 変化率(%)",
    "cuau": "銅/金レシオ 変化率(%)", "mkt": "市場 変化率(%)",
}
BETA_WEEKS = 156      # 3年分の週次データでベータ推定

# 3ヶ月シナリオ（初期値。Excelの「シナリオ」シートで自由に変更可）
SCENARIOS = {
    "S1 ベース：高金利で横ばい・AI主導継続": {"rate": 0.00, "oil": -5.0, "fx": 0.0, "cuau": 2.0, "mkt": 3.0, "prob": 0.50},
    "S2 強気：インフレ鈍化・利上げ打ち止め": {"rate": -0.50, "oil": -15.0, "fx": -3.0, "cuau": 3.0, "mkt": 6.0, "prob": 0.25},
    "S3 弱気：金利急騰・リスクオフ": {"rate": 0.50, "oil": 10.0, "fx": -3.0, "cuau": -8.0, "mkt": -10.0, "prob": 0.25},
}

# 総合スコアの重み（Excelで変更可）
WEIGHTS = {"RS-Ratio": 0.20, "RS-Momentum": 0.20, "12-1ヶ月モメンタム": 0.20, "シナリオ期待値": 0.40}

QUAD_JP = {"Leading": "先導（強い・加速）", "Weakening": "減速（強い・失速）",
           "Lagging": "劣後（弱い・悪化）", "Improving": "改善（弱い・回復）"}


# ----------------------------------------------------------------------------
# データ取得
# ----------------------------------------------------------------------------
def download(tickers, period="6y"):
    import yfinance as yf
    df = yf.download(list(tickers), period=period, auto_adjust=True,
                     progress=False, threads=True)["Close"]
    if isinstance(df, pd.Series):
        df = df.to_frame()
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df = df[df.index.dayofweek < 5]          # 土日のクォート（為替など）は除外
    from market_phase import clean_prices
    return clean_prices(df.sort_index())      # 異常値（1/10の値など）を除去


def build_jp33(days=1600):
    """~/株分析 の個別株日足から、プライム銘柄で33業種指数を合成する。
    重み = 前日までの60日平均売買代金（時価総額の代用）。1日±30%超の変化は除外。"""
    sec_path = os.path.join(BASE, "tickers", "sectors.csv")
    pdir = os.path.join(BASE, "data", "prices")
    if not (os.path.exists(sec_path) and os.path.isdir(pdir)):
        print("  33業種: 株価データが見つからないためスキップ")
        return None, None, None
    sec =pd.read_csv(sec_path, dtype={"code": str})
    sec = sec[sec["market"].astype(str).str.contains("プライム") & sec["sector33"].notna()]
    rets, vals = {}, {}
    for code in sec["code"]:
        f = os.path.join(pdir, f"{code}.csv")
        if not os.path.exists(f):
            continue
        try:
            p = pd.read_csv(f, usecols=["date", "close", "volume"], parse_dates=["date"]).set_index("date")
        except Exception:
            continue
        p = p[~p.index.duplicated()].sort_index().iloc[-days:]
        if len(p) < 300:
            continue
        r = p["close"].pct_change()
        r[(r.abs() > 0.30)] = np.nan
        rets[code] = r
        vals[code] = (p["close"] * p["volume"]).rolling(60, min_periods=20).mean().shift(1)
    R = pd.DataFrame(rets)
    V = pd.DataFrame(vals).reindex(R.index)
    # 直近の取引日が極端に少ない日（祝日の取り込みミス等）を除外
    R = R[R.notna().sum(axis=1) > 0.5 * R.shape[1]]
    V = V.reindex(R.index)
    smap = sec.set_index("code")["sector33"]
    idx = {}
    W = V.where(R.notna())
    for s, codes in smap.groupby(smap).groups.items():
        cs = [c for c in codes if c in R.columns]
        if len(cs) < 3:
            continue
        w = W[cs]
        rr = (R[cs] * w).sum(axis=1) / w.sum(axis=1)
        idx[s] = 100 * (1 + rr.fillna(0)).cumprod()
    w_all = W
    bench = (R * w_all).sum(axis=1) / w_all.sum(axis=1)
    bench = 100 * (1 + bench.fillna(0)).cumprod()
    out = pd.DataFrame(idx)
    counts = smap[smap.index.isin(R.columns)].value_counts()
    skipped = sorted(set(smap.unique()) - set(out.columns))
    print(f"  33業種: {R.shape[1]}銘柄から{out.shape[1]}業種を合成（最終日 {out.index[-1].date()}）"
          + (f" ※銘柄不足で除外: {skipped}" if skipped else ""))
    return out, bench.rename("プライム合成"), counts


# ----------------------------------------------------------------------------
# 計算
# ----------------------------------------------------------------------------
def ret_over(s, n):
    s = s.dropna()
    if len(s) <= n:
        return np.nan
    return (s.iloc[-1] / s.iloc[-1 - n] - 1) * 100


def rrg(px_w, bench_w, trend=26, smooth=3, mom_lag=4):
    """RRG（相対回転グラフ）
    RS-Ratio    = 100 + 相対株価(対市場)が直近26週平均を何%上回るか（3週平滑）
    RS-Momentum = 100 + RS-Ratioの4週間の変化（%pt）
    → 右上=先導 / 右下=減速 / 左下=劣後 / 左上=改善。通常は時計回りに回る。"""
    rs = px_w.div(bench_w, axis=0)
    ratio = 100 * rs / rs.rolling(trend).mean()
    ratio = ratio.ewm(span=smooth, adjust=False).mean()
    mom = 100 + (ratio - ratio.shift(mom_lag))
    return ratio, mom


def quadrant(r, m):
    if np.isnan(r) or np.isnan(m):
        return ""
    if r >= 100 and m >= 100:
        return "Leading"
    if r >= 100:
        return "Weakening"
    if m >= 100:
        return "Improving"
    return "Lagging"


def factor_frame(macro, bench_w):
    m = macro.resample("W-FRI").last().ffill()
    f = pd.DataFrame(index=m.index)
    f["rate"] = m["^TNX"].diff()                       # Yahooの^TNXは%表示
    f["oil"] = 100 * np.log(m["CL=F"].clip(lower=1)).diff()
    f["fx"] = 100 * np.log(m["JPY=X"]).diff()
    f["cuau"] = 100 * np.log(m["HG=F"] / m["GC=F"]).diff()
    f["mkt"] = 100 * np.log(bench_w.reindex(f.index).ffill()).diff()
    return f


def betas(rel_w, fac, weeks=BETA_WEEKS):
    out = {}
    for c in rel_w.columns:
        d = pd.concat([rel_w[c].rename("y"), fac], axis=1).dropna().iloc[-weeks:]
        if len(d) < 52:
            continue
        X = np.column_stack([np.ones(len(d)), d[FACTORS].values])
        y = d["y"].values
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        resid = y - X @ coef
        s2 = resid @ resid / (len(y) - X.shape[1])
        se = np.sqrt(np.diag(s2 * np.linalg.inv(X.T @ X)))
        r2 = 1 - resid.var() / y.var()
        row = {f: coef[i + 1] for i, f in enumerate(FACTORS)}
        row.update({f"t_{f}": coef[i + 1] / se[i + 1] for i, f in enumerate(FACTORS)})
        row["R2"] = r2
        out[c] = row
    return pd.DataFrame(out).T


def analyze(px, bench, names, label):
    """1市場ぶんの分析。px: 日次終値(列=セクター), bench: 日次ベンチマーク"""
    px = px.ffill()
    bench = bench.ffill()
    common = px.index.intersection(bench.index)
    px, bench = px.loc[common], bench.loc[common]
    pw = px.resample("W-FRI").last()
    bw = bench.resample("W-FRI").last()
    ratio, mom = rrg(pw, bw)
    rel_w = 100 * (np.log(pw).diff().sub(np.log(bw).diff(), axis=0))
    rows = []
    for c in px.columns:
        s = px[c]
        r = {"code": c, "name": names.get(c, c)}
        for k, n in {"1週": 5, "1ヶ月": 21, "3ヶ月": 63, "6ヶ月": 126, "12ヶ月": 252}.items():
            r[k] = ret_over(s, n)
            r[f"{k}_対市場"] = r[k] - ret_over(bench, n)
        sd = s.dropna()
        bd = bench.reindex(sd.index)
        if len(sd) > 260:
            r["12-1ヶ月モメンタム"] = ((sd.iloc[-22] / sd.iloc[-253]) / (bd.iloc[-22] / bd.iloc[-253]) - 1) * 100
        else:
            r["12-1ヶ月モメンタム"] = np.nan
        r["200日線乖離"] = (sd.iloc[-1] / sd.rolling(200).mean().iloc[-1] - 1) * 100
        r["52週高値比"] = (sd.iloc[-1] / sd.iloc[-252:].max() - 1) * 100
        r["RS-Ratio"] = ratio[c].iloc[-1]
        r["RS-Momentum"] = mom[c].iloc[-1]
        r["局面"] = quadrant(r["RS-Ratio"], r["RS-Momentum"])
        r["局面_4週前"] = quadrant(ratio[c].iloc[-5], mom[c].iloc[-5])
        rows.append(r)
    tbl = pd.DataFrame(rows).set_index("code")
    tails = {c: [[round(ratio[c].iloc[i], 2), round(mom[c].iloc[i], 2)] for i in range(-8, 0)]
             for c in px.columns if not np.isnan(ratio[c].iloc[-1])}
    hist = {"ratio": ratio.iloc[-26:].round(2), "mom": mom.iloc[-26:].round(2)}
    return {"label": label, "table": tbl, "tails": tails, "hist": hist, "rel_w": rel_w,
            "bench_w": bw, "asof": str(px.index[-1].date())}


def add_scenarios(res, fac):
    b = betas(res["rel_w"], fac.assign(mkt=100 * np.log(res["bench_w"]).diff()))
    tbl = res["table"].join(b)
    exp_cols = []
    for i, (sn, sc) in enumerate(SCENARIOS.items()):
        col = f"S{i+1}"
        tbl[col] = sum(tbl[f] * sc[f] for f in FACTORS)
        exp_cols.append(col)
    tbl["シナリオ期待値"] = sum(tbl[f"S{i+1}"] * sc["prob"] for i, sc in enumerate(SCENARIOS.values()))
    z = lambda s: (s - s.mean()) / s.std(ddof=1)
    tbl["総合スコア"] = sum(z(tbl[k]) * w for k, w in WEIGHTS.items())
    tbl["順位"] = tbl["総合スコア"].rank(ascending=False).astype(int)
    res["table"] = tbl.sort_values("総合スコア", ascending=False)
    return res


def macro_panel(macro):
    m = macro.ffill()
    rows = []
    for t, nm in MACRO.items():
        if t not in m:
            continue
        s = m[t].dropna()
        is_rate = t in ("^TNX", "^IRX")
        def chg(n):
            if len(s) <= n:
                return np.nan
            return (s.iloc[-1] - s.iloc[-1 - n]) if is_rate else (s.iloc[-1] / s.iloc[-1 - n] - 1) * 100
        rows.append({"指標": nm, "ticker": t, "現在値": s.iloc[-1], "1ヶ月変化": chg(21),
                     "3ヶ月変化": chg(63), "12ヶ月変化": chg(252),
                     "単位": "%pt" if is_rate else "%", "日付": str(s.index[-1].date())})
    p = pd.DataFrame(rows).set_index("ticker")
    cuau = (m["HG=F"] / m["GC=F"]).dropna()
    curve = (m["^TNX"] - m["^IRX"]).dropna()
    spy200 = None
    sig = {
        "銅/金レシオ 3ヶ月変化(%)": (cuau.iloc[-1] / cuau.iloc[-64] - 1) * 100,
        "米長短金利差 10年-3ヶ月(%pt)": curve.iloc[-1],
        "米長短金利差 3ヶ月変化(%pt)": curve.iloc[-1] - curve.iloc[-64],
        "ハイイールド/国債 3ヶ月変化(%)": ((m["HYG"] / m["IEF"]).iloc[-1] / (m["HYG"] / m["IEF"]).iloc[-64] - 1) * 100,
    }
    growth = sig["銅/金レシオ 3ヶ月変化(%)"] > 0
    inflation = (p.loc["CL=F", "3ヶ月変化"] > 0) and (p.loc["^TNX", "3ヶ月変化"] > 0)
    regime = {(True, True): "景気拡大×インフレ上昇（リフレ／景気後期）",
              (True, False): "景気拡大×インフレ鈍化（ゴルディロックス）",
              (False, True): "景気減速×インフレ上昇（スタグフレーション警戒）",
              (False, False): "景気減速×インフレ鈍化（景気後退／ディスインフレ）"}[(growth, inflation)]
    favored = {(True, True): "エネルギー・素材・資本財・金融（景気敏感＋インフレ耐性）",
               (True, False): "情報技術・一般消費財・通信（グロース）",
               (False, True): "エネルギー・生活必需品・公益（実物資産＋ディフェンシブ）",
               (False, False): "ヘルスケア・生活必需品・公益・長期債（ディフェンシブ）"}[(growth, inflation)]
    return p, sig, {"growth": bool(growth), "inflation": bool(inflation), "regime": regime, "favored": favored}


# ----------------------------------------------------------------------------
# Excel 出力（シナリオ・重みを変えると再計算されるモデル）
# ----------------------------------------------------------------------------
def write_excel(path, results, macro_p, sig, regime, phases=None):
    from openpyxl import Workbook
    from openpyxl.formatting.rule import ColorScaleRule
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter as L

    wb = Workbook()
    H = Font(bold=True, color="FFFFFF")
    HF = PatternFill("solid", fgColor="1F3A5F")
    INP = PatternFill("solid", fgColor="FFF4CC")
    thin = Side(style="thin", color="CCCCCC")
    BOX = Border(left=thin, right=thin, top=thin, bottom=thin)

    def header(ws, row, vals, col=1):
        for i, v in enumerate(vals):
            c = ws.cell(row=row, column=col + i, value=v)
            c.font, c.fill = H, HF
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    # --- 使い方
    ws = wb.active
    ws.title = "使い方"
    lines = [
        "セクターローテーション分析モデル（日米）",
        f"データ基準日: 米国 {results['us']['asof']} / 日本 {results['jp17']['asof']}",
        "",
        "■ このExcelでできること",
        "1) 「シナリオ」シートの黄色セル（3ヶ月後のマクロ変化と確率）を書き換える",
        "   → 各セクターシートの S1〜S3（シナリオ別の対市場超過リターン予想）と期待値が再計算されます",
        "2) 「シナリオ」シートの重み（黄色）を変えると、総合スコアと順位が再計算されます",
        "",
        "■ 列の意味（各セクターシート）",
        "対市場リターン … 業種リターン − 市場（米:SPY／日:TOPIX ETF、33業種:プライム合成）",
        "12-1ヶ月モメンタム … 12ヶ月前→1ヶ月前の対市場リターン（直近1ヶ月の反動を除く定番指標）",
        "RS-Ratio … 対市場の相対株価が26週平均より何%上か（100超＝市場より強いトレンド）",
        "RS-Momentum … RS-Ratioの4週変化（100超＝相対的な強さが加速中）",
        "局面 … Leading(先導) → Weakening(減速) → Lagging(劣後) → Improving(改善) と時計回りに回るのが典型",
        "β(金利)… 米10年金利が1%pt上がった週に、対市場で何%動いたか（過去3年の週次回帰）",
        "β(原油)/β(ドル円)/β(銅金)/β(市場) … それぞれ1%動いた週の対市場の動き",
        "S1〜S3 … シナリオのマクロ変化 × β の合計＝そのシナリオでの3ヶ月対市場リターン予想(%)",
        "",
        "■ 注意",
        "・βは過去の平均的な関係で、将来も同じとは限りません。R²が低い業種は説明力が弱い点に注意。",
        "・33業種はETFが無いため、プライム銘柄を売買代金加重で合成した自前指数です（公式TOPIX業種指数とは差があります）。",
        "・投資判断はご自身で。本モデルは考え方の整理用です。",
    ]
    for i, t in enumerate(lines, 1):
        ws.cell(row=i, column=1, value=t)
    ws["A1"].font = Font(bold=True, size=14)
    ws.column_dimensions["A"].width = 110

    # --- シナリオ
    sc = wb.create_sheet("シナリオ")
    sc["A1"] = "3ヶ月シナリオ（黄色セルを編集）"
    sc["A1"].font = Font(bold=True, size=13)
    header(sc, 3, ["シナリオ"] + [FACTOR_LABEL[f] for f in FACTORS] + ["確率"])
    for i, (nm, s) in enumerate(SCENARIOS.items()):
        r = 4 + i
        sc.cell(row=r, column=1, value=nm)
        for j, f in enumerate(FACTORS):
            c = sc.cell(row=r, column=2 + j, value=s[f])
            c.fill = INP
        c = sc.cell(row=r, column=7, value=s["prob"])
        c.fill, c.number_format = INP, "0%"
    sc["A7"] = "確率合計"
    sc["G7"] = "=SUM(G4:G6)"
    sc["G7"].number_format = "0%"
    sc["A8"] = "※『市場 変化率』は各市場のベンチマーク（米:SPY、日:TOPIX）に共通で適用。β(市場)が1より大きい業種は上昇相場で有利。"
    header(sc, 10, ["スコアの重み", "重み"])
    for i, (k, w) in enumerate(WEIGHTS.items()):
        sc.cell(row=11 + i, column=1, value=k)
        c = sc.cell(row=11 + i, column=2, value=w)
        c.fill = INP
    sc["A15"] = "合計"
    sc["B15"] = "=SUM(B11:B14)"
    sc.column_dimensions["A"].width = 34
    for j in range(2, 8):
        sc.column_dimensions[L(j)].width = 18
    sc.row_dimensions[3].height = 32

    # --- セクターシート
    cols = ["コード", "業種", "1ヶ月\n対市場%", "3ヶ月\n対市場%", "6ヶ月\n対市場%", "12ヶ月\n対市場%",
            "12-1ヶ月\nモメンタム%", "RS-Ratio", "RS-\nMomentum", "局面",
            "β 金利", "β 原油", "β ドル円", "β 銅金", "β 市場", "R²",
            "S1", "S2", "S3", "期待値%", "z RS-R", "z RS-M", "z 12-1", "z 期待値", "総合スコア", "順位"]
    sheet_names = {"us": "米国11セクター", "jp17": "日本17業種", "jp33": "日本33業種"}
    for key, sname in sheet_names.items():
        if key not in results:
            continue
        res = results[key]
        t = res["table"]
        ws = wb.create_sheet(sname)
        ws["A1"] = f"{res['label']}（基準日 {res['asof']}）"
        ws["A1"].font = Font(bold=True, size=13)
        ws["A2"] = "S1〜S3 = シナリオ別の3ヶ月対市場リターン予想（%）。シナリオ名は『シナリオ』シート参照。"
        header(ws, 4, cols)
        ws.row_dimensions[4].height = 34
        n0, n1 = 5, 4 + len(t)
        for i, (code, r) in enumerate(t.iterrows()):
            row = n0 + i
            vals = [code, r["name"], r["1ヶ月_対市場"], r["3ヶ月_対市場"], r["6ヶ月_対市場"], r["12ヶ月_対市場"],
                    r["12-1ヶ月モメンタム"], r["RS-Ratio"], r["RS-Momentum"], QUAD_JP.get(r["局面"], r["局面"]),
                    r["rate"], r["oil"], r["fx"], r["cuau"], r["mkt"], r["R2"]]
            for j, v in enumerate(vals):
                v = None if (isinstance(v, float) and np.isnan(v)) else v
                ws.cell(row=row, column=1 + j, value=v)
            for k in range(3):
                ws.cell(row=row, column=17 + k,
                        value=f"=SUMPRODUCT($K{row}:$O{row},シナリオ!$B${4+k}:$F${4+k})")
            ws.cell(row=row, column=20, value=f"=Q{row}*シナリオ!$G$4+R{row}*シナリオ!$G$5+S{row}*シナリオ!$G$6")
            for k, src in enumerate(["H", "I", "G", "T"]):
                ws.cell(row=row, column=21 + k,
                        value=f"=IFERROR(STANDARDIZE({src}{row},AVERAGE({src}${n0}:{src}${n1}),STDEV({src}${n0}:{src}${n1})),0)")
            ws.cell(row=row, column=25,
                    value=f"=U{row}*シナリオ!$B$11+V{row}*シナリオ!$B$12+W{row}*シナリオ!$B$13+X{row}*シナリオ!$B$14")
            ws.cell(row=row, column=26, value=f"=RANK(Y{row},Y${n0}:Y${n1})")
            for j in range(1, 27):
                c = ws.cell(row=row, column=j)
                c.border = BOX
                if 3 <= j <= 9 or 17 <= j <= 25:
                    c.number_format = "0.0"
                if 11 <= j <= 16:
                    c.number_format = "0.00"
        for colL in ["C", "D", "E", "F", "G", "T", "Y"]:
            ws.conditional_formatting.add(f"{colL}{n0}:{colL}{n1}", ColorScaleRule(
                start_type="min", start_color="F8696B", mid_type="num", mid_value=0,
                mid_color="FFFFFF", end_type="max", end_color="63BE7B"))
        ws.column_dimensions["B"].width = 18
        ws.column_dimensions["J"].width = 18
        for j in list(range(3, 10)) + list(range(11, 27)):
            ws.column_dimensions[L(j)].width = 9
        ws.freeze_panes = "C5"

        # RRG履歴
        hs = wb.create_sheet(f"{sname}_RRG履歴")
        hs["A1"] = f"{res['label']} RRG 週次履歴（直近26週）"
        hs["A1"].font = Font(bold=True)
        hr, hm = res["hist"]["ratio"], res["hist"]["mom"]
        header(hs, 3, ["週"] + [f"{res['table'].loc[c,'name']} R" for c in hr.columns] +
               [f"{res['table'].loc[c,'name']} M" for c in hm.columns])
        for i, d in enumerate(hr.index):
            hs.cell(row=4 + i, column=1, value=str(d.date()))
            for j, c in enumerate(hr.columns):
                hs.cell(row=4 + i, column=2 + j, value=None if np.isnan(hr.loc[d, c]) else float(hr.loc[d, c]))
                hs.cell(row=4 + i, column=2 + len(hr.columns) + j,
                        value=None if np.isnan(hm.loc[d, c]) else float(hm.loc[d, c]))

    # --- マクロ
    ms = wb.create_sheet("マクロ", 1)
    ms["A1"] = "マクロ環境"
    ms["A1"].font = Font(bold=True, size=13)
    header(ms, 3, ["指標", "現在値", "1ヶ月変化", "3ヶ月変化", "12ヶ月変化", "単位", "日付"])
    for i, (tk, r) in enumerate(macro_p.iterrows()):
        for j, k in enumerate(["指標", "現在値", "1ヶ月変化", "3ヶ月変化", "12ヶ月変化", "単位", "日付"]):
            c = ms.cell(row=4 + i, column=1 + j, value=r[k])
            if j in (1, 2, 3, 4):
                c.number_format = "0.00"
    rr = 5 + len(macro_p)
    for i, (k, v) in enumerate(sig.items()):
        ms.cell(row=rr + i, column=1, value=k)
        ms.cell(row=rr + i, column=2, value=float(v)).number_format = "0.00"
    rr += len(sig) + 1
    ms.cell(row=rr, column=1, value="局面判定（機械的）").font = Font(bold=True)
    ms.cell(row=rr, column=2, value=regime["regime"])
    ms.cell(row=rr + 1, column=1, value="教科書的に有利な業種")
    ms.cell(row=rr + 1, column=2, value=regime["favored"])
    ms.cell(row=rr + 2, column=1, value="判定ルール")
    ms.cell(row=rr + 2, column=2, value="景気=銅/金レシオの3ヶ月変化>0、インフレ=原油と米10年金利の3ヶ月変化がともに>0")
    ms.column_dimensions["A"].width = 32
    ms.column_dimensions["B"].width = 16
    try:
        from market_phase import phase_excel
        phase_excel(wb, phases)
        from heatmap import heat_excel
        heat_excel(wb, results)
    except Exception as e:
        print('  相場の四季シート作成に失敗:', e)
    wb.save(path)


# ----------------------------------------------------------------------------
# HTML ダッシュボード
# ----------------------------------------------------------------------------
def fmt(v, d=1, sign=True):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "–"
    return f"{v:+.{d}f}" if sign else f"{v:.{d}f}"


def cls(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return ""
    return "pos" if v > 0 else "neg" if v < 0 else ""


def html_table(res):
    t = res["table"]
    sn = list(SCENARIOS.keys())
    h = ["<table class='tbl'><thead><tr><th>順位</th><th>業種</th><th>局面</th><th>1ヶ月</th><th>3ヶ月</th>"
         "<th class='d'>6ヶ月</th><th class='d'>12-1M</th><th class='d'>RS-R</th><th class='d'>RS-M</th>"
         f"<th class='d' title='{sn[0]}'>S1</th><th class='d' title='{sn[1]}'>S2</th><th class='d' title='{sn[2]}'>S3</th>"
         "<th>期待値</th><th>スコア</th></tr></thead><tbody>"]
    for code, r in t.iterrows():
        q = r["局面"]
        moved = "" if r["局面_4週前"] == q or not r["局面_4週前"] else f"<small class='d'>←{r['局面_4週前']}</small>"
        h.append(
            f"<tr><td>{r['順位']}</td><td class='nm'>{r['name']}</td>"
            f"<td><span class='q q{q}'>{q}</span>{moved}</td>"
            + "".join(f"<td class='{cls(r[k])}'>{fmt(r[k])}</td>" for k in ["1ヶ月_対市場", "3ヶ月_対市場"])
            + "".join(f"<td class='d {cls(r[k])}'>{fmt(r[k])}</td>" for k in ["6ヶ月_対市場", "12-1ヶ月モメンタム"])
            + f"<td class='d'>{fmt(r['RS-Ratio'],1,False)}</td><td class='d'>{fmt(r['RS-Momentum'],1,False)}</td>"
            + "".join(f"<td class='d {cls(r[k])}'>{fmt(r[k])}</td>" for k in ["S1", "S2", "S3"])
            + f"<td class='{cls(r['シナリオ期待値'])}'>{fmt(r['シナリオ期待値'])}</td>"
            + f"<td class='{cls(r['総合スコア'])}'><b>{fmt(r['総合スコア'],2)}</b></td></tr>")
    h.append("</tbody></table>")
    return "".join(h)


def _commentary_details(html):
    """commentary.html の <h3> ごとに折りたたみ（<details>）にする。最初の節だけ開いておく"""
    import re
    parts = re.split(r"(<h3>.*?</h3>)", html, flags=re.S)
    head, out, first = parts[0], [], True
    for i in range(1, len(parts), 2):
        title = re.sub(r"</?h3>", "", parts[i])
        body = parts[i + 1] if i + 1 < len(parts) else ""
        out.append(f"<details{' open' if first else ''}><summary>{title}</summary><div class='dbody'>{body}</div></details>")
        first = False
    return head + "".join(out)


def summary_tiles(results, phases):
    """ページ先頭の『いまの状況』タイル（データから自動生成）"""
    tiles = []
    try:
        from market_phase import PH_COLOR
    except Exception:
        PH_COLOR = {}
    for pk, lab in [("us", "米国"), ("jp", "日本")]:
        if phases and pk in phases:
            r = phases[pk]
            tiles.append(f"<div class='tile'><div class='tl'>{lab}の相場局面</div>"
                         f"<div class='tv' style='color:{PH_COLOR.get(r['phase'], 'inherit')}'>{r['season']}・{r['phase']}</div>"
                         f"<div class='ts'>次の局面へのサイン {sum(s['点灯'] for s in r['signals'])}/{len(r['signals'])} 点灯</div></div>")
    for key, lab in [("us", "米国"), ("jp33", "日本33業種"), ("jp17", "日本17業種")]:
        if key not in results or (key == "jp17" and "jp33" in results):
            continue
        t = results[key]["table"]
        top = "、".join(t["name"].iloc[:3])
        lead = "、".join(t.loc[t["局面"] == "Leading", "name"].iloc[:4]) or "なし"
        tiles.append(f"<div class='tile w'><div class='tl'>{lab} スコア上位</div><div class='tv sm'>{top}</div>"
                     f"<div class='ts'>先導局面：{lead}</div></div>")
    return "<div class='tiles'>" + "".join(tiles) + "</div>"


def write_html(path, results, macro_p, sig, regime, today, phases=None, home="./index.html"):
    charts = {}
    for key, res in results.items():
        t = res["table"]
        charts[key] = [{"name": t.loc[c, "name"], "pts": res["tails"][c], "q": t.loc[c, "局面"]}
                       for c in t.index if c in res["tails"]]
    mrows = "".join(
        f"<tr><td class='nm'>{r['指標']}</td><td>{fmt(r['現在値'],2,False)}</td><td class='{cls(r['1ヶ月変化'])}'>{fmt(r['1ヶ月変化'],2)}</td>"
        f"<td class='{cls(r['3ヶ月変化'])}'>{fmt(r['3ヶ月変化'],2)}</td><td class='d {cls(r['12ヶ月変化'])}'>{fmt(r['12ヶ月変化'],2)}</td>"
        f"<td class='d'>{r['単位']}</td></tr>" for _, r in macro_p.iterrows())
    srows = "".join(f"<tr><td class='nm'>{k}</td><td>{fmt(v,2)}</td></tr>" for k, v in sig.items())
    scen = "".join(
        f"<tr><td class='nm'>{nm}</td>" + "".join(f"<td>{fmt(s[f],2)}</td>" for f in FACTORS)
        + f"<td>{s['prob']:.0%}</td></tr>" for i, (nm, s) in enumerate(SCENARIOS.items()))
    try:
        from market_phase import phase_html
        phase_block = phase_html(phases, results)
    except Exception as e:
        print("  相場の四季の表示に失敗:", e)
        phase_block = ""
    try:
        from heatmap import heat_html
        heat_block = heat_html(results, phases)
    except Exception as e:
        print("  ヒートマップの表示に失敗:", e)
        heat_block = ""
    comm_path = os.path.join(HERE, "commentary.html")
    commentary = open(comm_path, encoding="utf-8").read() if os.path.exists(comm_path) else ""
    if commentary:
        import re
        m = re.search(r"<h2[^>]*>.*?<small>(.*?)</small>", commentary, flags=re.S)
        when = m.group(1) if m else ""
        commentary = (f"<p class='note'>解説（手動で更新：{when}）。数値は作成時点のもので、下の各セクションは毎日自動更新されます。</p>"
                      + _commentary_details(commentary))
    asof = max(r["asof"] for r in results.values())
    built = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")
    nav = [("sum", "概要"), ("phase", "相場の四季"), ("heat", "ヒートマップ")] + \
          [(k, {"us": "米国", "jp17": "日本17業種", "jp33": "日本33業種"}[k]) for k in results] + [("macro", "マクロ・シナリオ")]
    navh = "".join(f"<a href='#{a}'>{b}</a>" for a, b in nav)
    sections = ""
    for key, res in results.items():
        sections += (f"<section id='{key}'><h2>{res['label']} <small>基準日 {res['asof']}</small></h2>"
                     f"<div class='card rrgc'><div class='rrg'><canvas id='c_{key}'></canvas></div>"
                     f"<p class='note'>線は直近8週の軌跡、●が最新週。右上＝先導／右下＝減速／左下＝劣後／左上＝改善（時計回りに回るのが典型）</p></div>"
                     f"<div class='card scroll tblc'><button class='btn allcol' type='button'>全列を表示</button>{html_table(res)}</div></section>")
    html = f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#f9f9f7">
<title>セクターローテーション（日米）</title>
<script>(function(){{var m=/[?&#]theme=(dark|light)/.exec(location.search+location.hash),t=m&&m[1];
if(!t){{try{{t=localStorage.getItem('fdb-theme')}}catch(e){{}}}}if(t)document.documentElement.setAttribute('data-theme',t);}})();</script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
@import url("https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap");
:root{{--bg:#f9f9f7;--card:#fcfcfb;--ink:#0b0b0b;--sub:#6b6a66;--line:#e1e0d9;--hover:rgba(11,11,11,.04);--acc:#2a78d6;
--pos:#1f7a4d;--neg:#c93a3a;--lead:#16a34a;--weak:#d97706;--lag:#dc2626;--imp:#2563eb;color-scheme:light}}
@media (prefers-color-scheme:dark){{:root:where(:not([data-theme="light"])){{--bg:#0d0d0d;--card:#1a1a19;--ink:#f3f3f1;--sub:#a3a29b;--line:#2c2c2a;
--hover:rgba(255,255,255,.05);--acc:#3987e5;--pos:#4fbf8a;--neg:#e66767;color-scheme:dark}}}}
:root[data-theme="dark"]{{--bg:#0d0d0d;--card:#1a1a19;--ink:#f3f3f1;--sub:#a3a29b;--line:#2c2c2a;--hover:rgba(255,255,255,.05);--acc:#3987e5;
--pos:#4fbf8a;--neg:#e66767;color-scheme:dark}}
*{{box-sizing:border-box}}
html{{scroll-behavior:smooth;scroll-padding-top:56px;-webkit-text-size-adjust:100%}}
body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 system-ui,-apple-system,"Hiragino Sans","Hiragino Kaku Gothic ProN","Segoe UI",sans-serif;font-variant-numeric:tabular-nums}}
main{{max-width:1180px;margin:0 auto;padding:16px 16px 48px}}
header{{display:flex;align-items:flex-start;justify-content:space-between;gap:8px}}
header a.home{{color:inherit;text-decoration:none;font-size:14px;color:var(--sub)}}
h1{{font-size:21px;margin:2px 0 0}}
.sub{{color:var(--sub);font-size:12px}}
.btn{{border:1px solid var(--line);background:transparent;color:var(--ink);border-radius:8px;padding:5px 11px;font:inherit;font-size:12.5px;cursor:pointer;white-space:nowrap;flex-shrink:0}}
nav.chips{{position:sticky;top:0;z-index:20;display:flex;gap:6px;overflow-x:auto;padding:8px 0;margin:10px -16px 0;padding-left:16px;padding-right:16px;
background:color-mix(in srgb,var(--bg) 92%,transparent);backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px);scrollbar-width:none;border-bottom:1px solid var(--line)}}
nav.chips::-webkit-scrollbar{{display:none}}
nav.chips a{{flex:0 0 auto;font-size:12.5px;text-decoration:none;color:var(--ink);border:1px solid var(--line);border-radius:99px;padding:4px 12px;background:var(--card)}}
h2{{font-size:17px;margin:28px 0 10px;border-left:4px solid var(--acc);padding-left:8px}}
h2 small,h1 small{{color:var(--sub);font-weight:normal;font-size:12px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px;margin-bottom:12px}}
.grid{{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:12px}}
.grid .card{{margin-bottom:0}}
.scroll{{overflow-x:auto;-webkit-overflow-scrolling:touch}}
.tbl{{border-collapse:collapse;width:100%;font-size:12.5px;white-space:nowrap}}
.tbl th,.tbl td{{padding:5px 6px;border-bottom:1px solid var(--line);text-align:right}}
.tbl th{{color:var(--sub);font-weight:600;background:var(--card)}}
.tbl td.nm,.tbl td:nth-child(3){{text-align:left}}
.tbl td.nm{{white-space:normal;min-width:6em}}
.pos{{color:var(--pos)}} .neg{{color:var(--neg)}}
.q{{display:inline-block;padding:0 6px;border-radius:4px;color:#fff;font-size:11px}}
.qLeading{{background:var(--lead)}} .qWeakening{{background:var(--weak)}} .qLagging{{background:var(--lag)}} .qImproving{{background:var(--imp)}}
small{{color:var(--sub);margin-left:4px}}
.regime{{font-size:16px;font-weight:700}}
.note{{color:var(--sub);font-size:12px}}
.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,250px),1fr));gap:10px;margin-top:12px}}
.tile{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px}}
.tile .tl{{font-size:12px;color:var(--sub)}} .tile .tv{{font-size:20px;font-weight:700;margin:2px 0}} .tile .tv.sm{{font-size:15px}}
.tile .ts{{font-size:12px;color:var(--sub)}}
.comm{{margin-top:12px}}
.comm>h2{{display:none}}
details{{background:var(--card);border:1px solid var(--line);border-radius:12px;margin-bottom:8px}}
details summary{{cursor:pointer;padding:11px 14px;font-weight:700;font-size:14.5px;list-style:none}}
details summary::-webkit-details-marker{{display:none}}
details summary::after{{content:"＋";float:right;color:var(--sub)}}
details[open] summary::after{{content:"－"}}
.dbody{{padding:0 14px 10px}} .dbody ul,.dbody ol{{padding-left:1.3em;margin:4px 0}} .dbody li{{margin:4px 0}}
.rrg{{position:relative;height:540px;max-width:860px;margin:0 auto}}
.tblc{{position:relative}} .allcol{{display:none;margin-bottom:6px}}
@media (max-width:760px){{
 main{{padding:12px 12px 40px}} nav.chips{{margin:8px -12px 0;padding-left:12px;padding-right:12px}}
 h1{{font-size:18px}} h2{{font-size:16px;margin-top:24px}}
 .grid{{grid-template-columns:1fr}}
 .rrg{{height:380px}}
 .tbl{{font-size:12px}} .tbl th,.tbl td{{padding:5px 4px}}
 .tblc:not(.all) .d{{display:none}}
 .allcol{{display:inline-block}}
 .card{{padding:10px}}
 .tiles{{grid-template-columns:1fr 1fr;gap:8px}} .tile{{padding:10px 12px}} .tile .tv{{font-size:17px}} .tile .tv.sm{{font-size:14px}}
 .tile.w{{grid-column:1/-1}}
}}
/* ===== 2026-11 デザイン刷新（トップ画面と共通）：黒／白地、枠線なしのカード、数字は Inter の極太。騰落は赤＝上昇／緑＝下落 ===== */
:root{{--bg:#f3f4f6;--card:#fff;--ink:#0c0d10;--sub:#5b6068;--line:#dfe2e7;--hover:rgba(12,13,16,.05);--acc:#0c0d10;--pos:#b91c24;--neg:#08705a;--lit:#b45309}}
@media (prefers-color-scheme:dark){{:root:where(:not([data-theme="light"])){{--bg:#050608;--card:#101216;--ink:#f2f4f8;--sub:#8f96a3;--line:#23262d;--hover:rgba(255,255,255,.06);--acc:#5cc8ff;--pos:#ff7378;--neg:#3fd0a4;--lit:#f0a53a}}}}
:root[data-theme="dark"]{{--bg:#050608;--card:#101216;--ink:#f2f4f8;--sub:#8f96a3;--line:#23262d;--hover:rgba(255,255,255,.06);--acc:#5cc8ff;--pos:#ff7378;--neg:#3fd0a4;--lit:#f0a53a}}
body{{font-family:Inter,"Hiragino Sans","Hiragino Kaku Gothic ProN","Noto Sans JP",system-ui,-apple-system,"Segoe UI",sans-serif;-webkit-font-smoothing:antialiased}}
h1{{font-weight:800;letter-spacing:.02em}}
h2{{border-left:0;padding-left:0;border-top:3px solid var(--ink);padding-top:10px;font-weight:800}}
@media (min-width:761px){{h1{{font-size:24px}}h2{{margin-top:36px}}}}
.card,.tile,details{{border:0;border-radius:14px}}
.tile .tv{{font-weight:800;letter-spacing:-.02em}}
.regime{{font-weight:800}}
nav.chips{{border-bottom:0}}
nav.chips a{{border:0;font-weight:600}}
.tbl th{{font-weight:800}}
.tbl td.pos,.tbl td.neg{{font-weight:600}}
</style></head><body><main>
<header><div><a class="home" href="{home}">‹ トップ</a>
<h1>セクターローテーション（日米）</h1>
<div class="sub">データ基準日 {asof} ／ 更新 {built}</div></div>
<button class="btn" id="theme" type="button">明暗</button></header>
<nav class="chips">{navh}</nav>
<section id="sum"><h2>いまの状況 <small>データから自動判定</small></h2>
{summary_tiles(results, phases)}
{('<div class="comm">' + commentary + '</div>') if commentary else ''}
</section>
<section id="phase">{phase_block}</section>
<section id="heat">{heat_block}</section>
{sections}
<section id="macro"><h2>マクロ環境</h2>
<div class="grid"><div class="card scroll tblc"><table class="tbl"><thead><tr><th>指標</th><th>現在値</th><th>1ヶ月</th><th>3ヶ月</th><th class="d">12ヶ月</th><th class="d">単位</th></tr></thead><tbody>{mrows}</tbody></table></div>
<div class="card"><div class="regime">{regime['regime']}</div><p>教科書的に有利：{regime['favored']}</p>
<table class="tbl"><tbody>{srows}</tbody></table>
<p class="note">判定ルール：景気＝銅/金レシオの3ヶ月変化&gt;0、インフレ＝原油と米10年金利の3ヶ月変化がともに&gt;0</p></div></div>
<h2>3ヶ月シナリオ <small>Excelで変更可</small></h2>
<div class="card scroll"><table class="tbl"><thead><tr><th>シナリオ</th>{''.join(f'<th>{FACTOR_LABEL[f]}</th>' for f in FACTORS)}<th>確率</th></tr></thead><tbody>{scen}</tbody></table>
<p class="note">S1〜S3：各シナリオのマクロ変化 × 業種の感応度(β) から計算した3ヶ月の対市場リターン予想(%)。期待値は確率加重。スコア＝RS-Ratio・RS-Momentum・12-1ヶ月モメンタム・期待値のzスコア加重和。</p></div>
</section>
<p class="note">データ：Yahoo Finance、multpl.com、財務省、J-Quants。33業種はプライム銘柄を売買代金加重で合成した自作指数。投資判断はご自身の責任で。</p>
</main>
<script>
(function(){{const b=document.getElementById('theme');b.onclick=()=>{{const r=document.documentElement;
const cur=r.getAttribute('data-theme')||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');const nx=cur==='dark'?'light':'dark';
r.setAttribute('data-theme',nx);try{{localStorage.setItem('fdb-theme',nx)}}catch(e){{}}location.reload();}};}})();
document.querySelectorAll('.allcol').forEach(b=>b.onclick=()=>{{const c=b.closest('.tblc');c.classList.toggle('all');b.textContent=c.classList.contains('all')?'主要な列だけ表示':'全列を表示';}});
const CS=getComputedStyle(document.documentElement);
Chart.defaults.color=CS.getPropertyValue('--sub').trim()||'#666';
Chart.defaults.borderColor=CS.getPropertyValue('--line').trim()||'#ddd';
const MOB=matchMedia('(max-width:760px)').matches;
const DATA={json.dumps(charts, ensure_ascii=False)};
const QC={{Leading:'#16a34a',Weakening:'#d97706',Lagging:'#dc2626',Improving:'#2563eb'}};
const quad={{id:'quad',beforeDraw(c){{const {{ctx,chartArea:a,scales:{{x,y}}}}=c;const cx=x.getPixelForValue(100),cy=y.getPixelForValue(100);
ctx.save();[[a.left,a.top,cx,cy,'rgba(37,99,235,.08)','改善'],[cx,a.top,a.right,cy,'rgba(22,163,74,.09)','先導'],
[a.left,cy,cx,a.bottom,'rgba(220,38,38,.08)','劣後'],[cx,cy,a.right,a.bottom,'rgba(217,119,6,.09)','減速']].forEach(([x0,y0,x1,y1,col,t],i)=>{{
ctx.fillStyle=col;ctx.fillRect(x0,y0,x1-x0,y1-y0);ctx.fillStyle='rgba(128,128,128,.7)';ctx.font='bold '+(MOB?11:13)+'px sans-serif';
ctx.fillText(t,i%2? x1-(MOB?28:36):x0+6,i<2? y0+16:y1-6);}});ctx.restore();}},
afterDatasetsDraw(c){{const ctx=c.ctx;ctx.save();ctx.font=(MOB?10:11)+'px sans-serif';ctx.fillStyle=getComputedStyle(document.body).color;
c.data.datasets.forEach((d,i)=>{{const m=c.getDatasetMeta(i);const p=m.data[m.data.length-1];if(p)ctx.fillText(d.label,p.x+5,p.y-4);}});ctx.restore();}}}};
for(const [k,arr] of Object.entries(DATA)){{const el=document.getElementById('c_'+k);if(!el)continue;
let xs=[],ys=[];arr.forEach(s=>s.pts.slice(-4).forEach(p=>{{xs.push(p[0]);ys.push(p[1]);}}));
const pad=(a)=>{{const mn=Math.min(...a,100),mx=Math.max(...a,100);const r=Math.max(100-mn,mx-100)*1.1+0.5;return [100-r,100+r];}};
const [x0,x1]=pad(xs),[y0,y1]=pad(ys);
new Chart(el,{{type:'scatter',data:{{datasets:arr.map(s=>({{label:s.name,data:s.pts.map(p=>({{x:p[0],y:p[1]}})),showLine:true,
borderColor:QC[s.q]+'99',backgroundColor:QC[s.q],borderWidth:1.5,pointRadius:s.pts.map((_,i)=>i==s.pts.length-1?(MOB?4:5):1.2),pointHitRadius:8}}))}},
options:{{animation:false,maintainAspectRatio:false,plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:(t)=>t.dataset.label+' R:'+t.parsed.x.toFixed(1)+' M:'+t.parsed.y.toFixed(1)}}}}}},
scales:{{x:{{min:x0,max:x1,title:{{display:!MOB,text:'RS-Ratio（相対トレンド）'}},ticks:{{maxTicksLimit:MOB?5:9}}}},y:{{min:y0,max:y1,title:{{display:!MOB,text:'RS-Momentum（勢い）'}},ticks:{{maxTicksLimit:MOB?5:9}}}}}}}},plugins:[quad]}});}}
</script></body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


# ----------------------------------------------------------------------------
SITE = os.path.join(BASE, "data", "charts")      # 東証株分析の公開フォルダ（GitHub Pages）


def publish_site(results, macro_p, sig, regime, today, phases):
    """東証株分析の公開フォルダに sector.html と、トップ画面のカード用 sector_summary.json を置く。
    公開（GitHub Pagesへのpush）は run_daily.sh の deploy_github.sh が行う。"""
    if not os.path.isdir(SITE):
        return
    write_html(os.path.join(SITE, "sector.html"), results, macro_p, sig, regime, today, phases, home="./index.html")
    summ = {"updated": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
            "asof": max(r["asof"] for r in results.values()), "phases": {}, "top": {}}
    for k, r in (phases or {}).items():
        summ["phases"][k] = {"label": r["label"], "phase": r["phase"], "season": r["season"],
                             "conviction": round(r["conviction"], 2),
                             "signals": f"{sum(x['点灯'] for x in r['signals'])}/{len(r['signals'])}"}
    for k, res in results.items():
        summ["top"][k] = list(res["table"]["name"].iloc[:3])
    with open(os.path.join(SITE, "sector_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summ, f, ensure_ascii=False)
    print("   公開用:", os.path.join(SITE, "sector.html"))


def main():
    today = date.today().isoformat()
    print("1/4 価格データ取得（Yahoo Finance）…")
    tick = list(US) + [US_BENCH] + list(JP17) + [JP_BENCH] + list(MACRO) + ["^GSPC"]
    px = download(tick)
    print(f"  取得 {px.shape[1]}銘柄 / 最終日 {px.index[-1].date()}")
    missing = [t for t in tick if t not in px or px[t].dropna().empty]
    if missing:
        print("  取得失敗:", missing)

    print("2/4 33業種指数を合成…")
    jp33, jp33b, counts = build_jp33()

    print("3/4 計算（RRG・モメンタム・β・シナリオ）…")
    macro = px[[t for t in MACRO if t in px]]
    spy_w = px[US_BENCH].ffill().resample("W-FRI").last()
    fac = factor_frame(macro, spy_w)
    results = {}
    us_px = px[[t for t in US if t in px]].dropna(how="all")
    results["us"] = add_scenarios(analyze(us_px, px[US_BENCH].dropna(), US, "米国 S&P500 11セクター"), fac)
    jp_px = px[[t for t in JP17 if t in px]].dropna(how="all")
    results["jp17"] = add_scenarios(analyze(jp_px, px[JP_BENCH].dropna(), JP17, "日本 TOPIX-17業種"), fac)
    if jp33 is not None:
        names33 = {c: c for c in jp33.columns}
        # ベンチマークは17業種と同じTOPIX ETF（売買代金加重の合成市場は半導体の比重が過大になるため）
        results["jp33"] = add_scenarios(analyze(jp33, px[JP_BENCH].dropna(), names33, "日本 東証33業種（プライム合成）"), fac)
    macro_p, sig, regime = macro_panel(macro)
    try:
        from heatmap import heat_data
        srcs = {"us": (us_px, px[US_BENCH], US), "jp17": (jp_px, px[JP_BENCH], JP17)}
        if jp33 is not None:
            srcs["jp33"] = (jp33, px[JP_BENCH], {c: c for c in jp33.columns})
        for key, (p_, b_, nm) in srcs.items():
            if key in results:
                results[key]["heat"] = heat_data(p_, b_.dropna(), list(results[key]["table"].index), nm)
    except Exception as e:
        print("  ヒートマップの計算に失敗:", e)
    try:
        import market_phase
        print("  相場の四季を判定…")
        phases = market_phase.run(px)
        for k, r in phases.items():
            print(f"   {r['label']}: {r['phase']}（確度 {r['conviction']:.2f}）")
    except Exception as e:
        print("  相場の四季の判定に失敗:", e)
        phases = {}

    print("4/4 出力…")
    xl = os.path.join(OUT, f"sector_rotation_{today}.xlsx")
    ht = os.path.join(OUT, f"sector_rotation_{today}.html")
    write_excel(xl, results, macro_p, sig, regime, phases)
    write_html(ht, results, macro_p, sig, regime, today, phases, home="../../data/charts/index.html")
    publish_site(results, macro_p, sig, regime, today, phases)
    js = {k: {"asof": v["asof"], "table": json.loads(v["table"].drop(columns=[], errors="ignore").to_json(orient="index", force_ascii=False))}
          for k, v in results.items()}
    js["macro"] = json.loads(macro_p.to_json(orient="index", force_ascii=False))
    js["signals"] = sig
    js["regime"] = regime
    js["phases"] = {k: {kk: vv for kk, vv in v.items() if kk not in ("history", "monthly")} for k, v in phases.items()}
    js["scenarios"] = SCENARIOS
    with open(os.path.join(OUT, f"results_{today}.json"), "w", encoding="utf-8") as f:
        json.dump(js, f, ensure_ascii=False, indent=1, default=float)
    print("  ", xl)
    print("  ", ht)
    return results


if __name__ == "__main__":
    main()
