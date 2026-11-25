#!/usr/bin/env python3
"""
最適投資ウェイトの推移を計算する（ローリング・ポートフォリオ最適化）

対象   : fundamentals/analysis/スコア一覧.csv の総合順位上位（既定20銘柄・1業種2銘柄まで）
価格   : data/prices/<code>.csv（分割調整済み終値）
手法   : 最大シャープレシオ / 最小分散 / リスクパリティ（すべて買いのみ）
推定   : 過去 WINDOW 年の日次リターン、毎月末にリバランス
出力   : ポートフォリオ最適化/最適ウェイト推移_<日付>.xlsx
         （各手法のウェイト推移・最新ウェイト・事後検証バックテスト・グラフ）

使い方（~/株分析 で）:
  python3 optimize_weights.py                     # 既定設定
  python3 optimize_weights.py --top 15 --cap 0.2  # 15銘柄・1銘柄上限20%
  python3 optimize_weights.py --codes 7203 6758 8035 9984   # 銘柄を直接指定
  python3 optimize_weights.py --window 1 --freq Q # 1年窓・四半期リバランス
  python3 optimize_weights.py --sector-top 2 --cap 0.1   # 各業種の時価総額1・2位
必要: pandas numpy scipy openpyxl
  （.venv に scipy が無ければ: ./.venv/bin/pip install scipy）
"""
import argparse
import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize

BASE = Path(__file__).resolve().parent
SCORE_CSV = BASE / "fundamentals" / "analysis" / "スコア一覧.csv"
PRICE_DIR = BASE / "data" / "prices"
OUT_DIR = BASE / "ポートフォリオ最適化"
TD = 245  # 東証の年間営業日（概算）

METHODS = {"max_sharpe": "最大シャープ", "min_var": "最小分散", "risk_parity": "リスクパリティ"}


# ---------------------------------------------------------------- 銘柄選定
def select_universe(top, per_sector, codes=None, sector_top=0):
    sc = pd.read_csv(SCORE_CSV, dtype={"コード": str})
    sc["コード"] = sc["コード"].str.strip()
    if sector_top:
        # 各業種の時価総額上位 sector_top 銘柄（価格ファイルがあるもの）
        sc = sc[sc["株価遅延日数"].fillna(0) <= 5]
        sc = sc[sc["コード"].map(lambda c: (PRICE_DIR / f"{c}.csv").exists())]
        sc = sc.dropna(subset=["時価総額(億円)", "業種"])
        sel = (sc.sort_values("時価総額(億円)", ascending=False)
                 .groupby("業種", sort=False).head(sector_top)
                 .sort_values(["業種", "時価総額(億円)"], ascending=[True, False]))
    elif codes:
        sel = sc[sc["コード"].isin(codes)].copy()
        missing = set(codes) - set(sel["コード"])
        for c in missing:  # スコア一覧に無くても価格があれば使う
            sel = pd.concat([sel, pd.DataFrame({"コード": [c], "銘柄名": [c], "業種": ["-"]})])
        sel = sel.set_index("コード").loc[codes].reset_index()
    else:
        sc = sc[(sc["決算が古い"] != True) & (sc["株価遅延日数"].fillna(0) <= 5)]
        sc = sc.sort_values(["総合順位", "評価平均", "時価総額(億円)"],
                            ascending=[True, False, False])
        picked, cnt = [], {}
        for _, r in sc.iterrows():
            if not (PRICE_DIR / f"{r['コード']}.csv").exists():
                continue
            if per_sector and cnt.get(r["業種"], 0) >= per_sector:
                continue
            picked.append(r)
            cnt[r["業種"]] = cnt.get(r["業種"], 0) + 1
            if len(picked) >= top:
                break
        sel = pd.DataFrame(picked)
    cols = [c for c in ["コード", "銘柄名", "業種", "総合評価", "総合順位", "時価総額(億円)"] if c in sel]
    return sel[cols].reset_index(drop=True)


def load_prices(codes):
    s = {}
    for c in codes:
        p = PRICE_DIR / f"{c}.csv"
        if not p.exists():
            print(f"  ! 価格ファイルなし: {c}")
            continue
        d = pd.read_csv(p, parse_dates=["date"]).set_index("date")["close"]
        s[c] = d[~d.index.duplicated()]
    px = pd.DataFrame(s).sort_index()
    return px


# ---------------------------------------------------------------- 推定
def ledoit_wolf(X):
    """Ledoit-Wolf(2004) 縮小共分散（ターゲット: 分散平均×単位行列）"""
    X = X - X.mean(0)
    n, p = X.shape
    S = X.T @ X / n
    mu = np.trace(S) / p
    F = mu * np.eye(p)
    d2 = np.sum((S - F) ** 2) / p
    b2 = sum(np.sum((np.outer(x, x) - S) ** 2) for x in X) / p / n ** 2
    b2 = min(b2, d2)
    delta = b2 / d2 if d2 > 0 else 1.0
    return delta * F + (1 - delta) * S, delta


def estimate(R, shrink_mu):
    """R: 日次リターン(窓) → 年率の期待リターンμ, 共分散Σ"""
    S, _ = ledoit_wolf(R.values)
    cov = S * TD
    mu_hist = R.mean().values * TD
    mu = (1 - shrink_mu) * mu_hist + shrink_mu * mu_hist.mean()  # 平均方向へ縮小
    return mu, cov


# ---------------------------------------------------------------- 最適化
def _solve(obj, n, cap, x0=None):
    x0 = np.full(n, 1 / n) if x0 is None else x0
    cons = [{"type": "eq", "fun": lambda w: w.sum() - 1}]
    res = minimize(obj, x0, method="SLSQP", bounds=[(0, cap)] * n,
                   constraints=cons, options={"maxiter": 500, "ftol": 1e-12})
    w = np.clip(res.x, 0, None)
    return w / w.sum()


def max_sharpe(mu, cov, rf, cap):
    ex = mu - rf
    if np.all(ex <= 0):  # 全銘柄の超過リターンが負 → 最小分散で代替
        return min_var(cov, cap)
    f = lambda w: -(w @ ex) / np.sqrt(w @ cov @ w)
    best = None
    for x0 in (None, min_var(cov, cap)):
        w = _solve(f, len(mu), cap, x0)
        if best is None or f(w) < f(best):
            best = w
    return best


def min_var(cov, cap):
    return _solve(lambda w: w @ cov @ w * 1e4, len(cov), cap)


def risk_parity(cov, iters=500):
    """リスク寄与均等（循環座標降下法, Griveau-Billion et al.）"""
    n = len(cov)
    b = np.full(n, 1 / n)
    x = 1 / np.sqrt(np.diag(cov))
    for _ in range(iters):
        x_old = x.copy()
        for i in range(n):
            c = cov[i] @ x - cov[i, i] * x[i]
            x[i] = (-c + np.sqrt(c * c + 4 * cov[i, i] * b[i])) / (2 * cov[i, i])
        if np.max(np.abs(x - x_old)) < 1e-10:
            break
    return x / x.sum()


# ---------------------------------------------------------------- メイン
def run(args):
    uni = select_universe(args.top, args.per_sector, args.codes, args.sector_top)
    print(f"対象 {len(uni)} 銘柄:", ", ".join(f"{r.コード} {r.銘柄名}" for r in uni.itertuples()))
    px = load_prices(uni["コード"].tolist())
    px = px.loc[px.index >= px.index.max() - pd.DateOffset(years=args.history)]
    rets = px.pct_change(fill_method=None)
    rets = rets.where(rets.abs() < 0.5)  # 異常値(データ誤り)を除外

    win = int(args.window * TD)
    min_obs = int(win * 0.9)
    rule = {"M": "ME", "Q": "QE"}[args.freq]
    ends = rets.groupby(rets.index.to_period(rule[0])).tail(1).index
    last = rets.index.max()
    if ends[-1] != last:
        ends = ends.append(pd.DatetimeIndex([last]))
    ends = [d for d in ends if (rets.index <= d).sum() >= win]

    W = {m: {} for m in METHODS}
    info = []
    for d in ends:
        R = rets.loc[:d].tail(win)
        ok = R.notna().sum() >= min_obs
        R = R.loc[:, ok].fillna(0.0)
        if R.shape[1] < 2:
            continue
        cap = max(args.cap, 1.0 / R.shape[1] + 1e-9)
        mu, cov = estimate(R, args.shrink_mu)
        ws = {"max_sharpe": max_sharpe(mu, cov, args.rf, cap),
              "min_var": min_var(cov, cap),
              "risk_parity": risk_parity(cov)}
        for m, w in ws.items():
            W[m][d] = pd.Series(w, index=R.columns)
            vol = np.sqrt(w @ cov @ w)
            info.append({"日付": d, "手法": METHODS[m], "銘柄数": R.shape[1],
                         "想定リターン(年率%)": w @ mu * 100, "想定リスク(年率%)": vol * 100,
                         "想定シャープ": (w @ mu - args.rf) / vol})
    W = {m: pd.DataFrame(v).T.reindex(columns=uni["コード"]).fillna(0.0) for m, v in W.items()}
    return uni, px, rets, W, pd.DataFrame(info)


def backtest(rets, W, rf):
    """各リバランス日のウェイトで翌期間を保有（期中は値動きでドリフト）した実績"""
    dates = W["min_var"].index
    out = {}
    eq = None
    for m in list(METHODS) + ["equal"]:
        daily = []
        turn = []
        prev = None
        for i, d in enumerate(dates[:-1]):
            if m == "equal":
                live = rets.loc[:d].tail(TD).notna().sum() > TD * 0.9
                w = live.astype(float) / live.sum()
            else:
                w = W[m].loc[d]
            seg = rets.loc[(rets.index > d) & (rets.index <= dates[i + 1]), w.index].fillna(0)
            val = (1 + seg).cumprod().mul(w, axis=1)
            nav = val.sum(1)
            pr = nav / np.r_[1.0, nav.values[:-1]] - 1
            daily.append(pd.Series(pr.values, index=seg.index))
            if prev is not None:
                turn.append(np.abs(w - prev).sum() / 2)
            prev = val.iloc[-1] / val.iloc[-1].sum() if len(val) else w
        s = pd.concat(daily)
        out[m] = (s, np.mean(turn) if turn else np.nan)
    names = {**METHODS, "equal": "均等ウェイト"}
    nav = pd.DataFrame({names[m]: (1 + s).cumprod() for m, (s, _) in out.items()})
    stats = []
    for m, (s, t) in out.items():
        yrs = len(s) / TD
        cagr = (1 + s).prod() ** (1 / yrs) - 1
        vol = s.std() * np.sqrt(TD)
        n = (1 + s).cumprod()
        mdd = (n / n.cummax() - 1).min()
        stats.append({"手法": names[m], "年率リターン(%)": cagr * 100, "年率リスク(%)": vol * 100,
                      "シャープレシオ": (cagr - rf) / vol, "最大ドローダウン(%)": mdd * 100,
                      "平均回転率(片道,%/回)": t * 100 if m != "equal" else np.nan})
    return nav, pd.DataFrame(stats)


# ---------------------------------------------------------------- Excel
def write_excel(path, args, uni, W, info, nav, stats):
    from openpyxl.chart import AreaChart, LineChart, BarChart, Reference
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    label = dict(zip(uni["コード"], uni["コード"] + " " + uni["銘柄名"].astype(str)))
    latest = pd.DataFrame({METHODS[m]: W[m].iloc[-1] for m in METHODS})
    latest.index = [label[c] for c in latest.index]
    latest = latest.sort_values("最大シャープ", ascending=False)

    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        note = pd.DataFrame({"項目": [
            "作成日時", "対象銘柄", "推定窓", "リバランス", "無リスク金利", "1銘柄上限",
            "期待リターン", "共分散", "制約", "推移の期間",
            "注意1", "注意2", "注意3", "注意4"], "内容": [
            dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
            (f"各業種の時価総額上位{args.sector_top}銘柄（{len(uni)}銘柄・{uni['業種'].nunique()}業種）" if args.sector_top
             else "指定銘柄" if args.codes else f"スコア一覧の総合順位上位{args.top}（1業種{args.per_sector}銘柄まで）"),
            f"過去{args.window}年の日次リターン", {"M": "毎月末", "Q": "四半期末"}[args.freq],
            f"{args.rf*100:.2f}%（年率）", f"{args.cap*100:.0f}%（最大シャープ・最小分散に適用）",
            f"過去平均を銘柄平均方向へ{args.shrink_mu*100:.0f}%縮小（最大シャープのみ使用）",
            "Ledoit-Wolf縮小推定", "買いのみ・合計100%",
            f"{W['min_var'].index[0].date()} 〜 {W['min_var'].index[-1].date()}",
            "銘柄選定は『現在の』スコアで行っているため、過去の時点では知り得ない情報を使っています（後知恵バイアス）。バックテストの成績は実力より良く見えやすい点に注意。",
            "最大シャープは過去リターンに強く依存し、ウェイトが大きく振れやすい手法です。最小分散・リスクパリティと見比べてください。",
            "分割調整済み終値ベース（配当は含まない）。売買コスト・税金は考慮していません。",
            "時点ごとに、推定窓の9割以上の価格データがある銘柄だけを対象にしています（上場の新しい銘柄は途中から加わります）。"]})
        note.to_excel(xw, sheet_name="説明", index=False)
        uni.to_excel(xw, sheet_name="対象銘柄", index=False)
        latest.mul(100).round(2).to_excel(xw, sheet_name="最新ウェイト(%)")
        for m, jp in METHODS.items():
            df = W[m].copy() * 100
            df.columns = [label[c] for c in df.columns]
            df.index = df.index.date
            df.index.name = "日付"
            df.round(2).to_excel(xw, sheet_name=f"推移_{jp}")
        # 業種別に合計したウェイト推移
        sec = dict(zip(uni["コード"], uni["業種"]))
        for m, jp in METHODS.items():
            g = (W[m] * 100).T.groupby(lambda c: sec.get(c, "-")).sum().T
            g = g[g.mean().sort_values(ascending=False).index]
            g.index = g.index.date
            g.index.name = "日付"
            g.round(2).to_excel(xw, sheet_name=f"業種別_{jp}")
        lsec = pd.DataFrame({METHODS[m]: (W[m].iloc[-1] * 100).groupby(lambda c: sec.get(c, "-")).sum()
                             for m in METHODS}).sort_values("最大シャープ", ascending=False)
        lsec.index.name = "業種"
        lsec.round(2).to_excel(xw, sheet_name="最新_業種別(%)")
        stats.round(2).to_excel(xw, sheet_name="バックテスト", index=False)
        n2 = nav.resample("ME").last()
        n2.index = n2.index.date
        n2.index.name = "月末"
        n2.round(4).to_excel(xw, sheet_name="バックテスト", startrow=len(stats) + 3)
        inf = info.copy()
        inf["日付"] = inf["日付"].dt.date
        inf.round(3).to_excel(xw, sheet_name="想定リスク・リターン", index=False)

        wb = xw.book
        hdr = PatternFill("solid", fgColor="1F4E78")
        for ws in wb.worksheets:
            for c in ws[1]:
                c.font = Font(bold=True, color="FFFFFF")
                c.fill = hdr
                c.alignment = Alignment(wrap_text=True, vertical="center")
            ws.freeze_panes = "B2"
            ws.column_dimensions["A"].width = 14
            for i in range(2, ws.max_column + 1):
                ws.column_dimensions[get_column_letter(i)].width = 13
        ws = wb["説明"]
        ws.column_dimensions["A"].width = 16
        ws.column_dimensions["B"].width = 110
        for r in ws.iter_rows(min_row=2):
            r[1].alignment = Alignment(wrap_text=True, vertical="top")
        wb["対象銘柄"].column_dimensions["B"].width = 30
        wb["最新ウェイト(%)"].column_dimensions["A"].width = 34

        # 推移グラフ（積み上げ面）
        for m, jp in [(m, p + j) for m, j in METHODS.items() for p in ("推移_", "業種別_")]:
            ws = wb[jp]
            nr, nc = ws.max_row, ws.max_column
            ch = AreaChart()
            ch.grouping = "percentStacked"
            ch.title = f"最適ウェイトの推移（{jp.replace('推移_', '銘柄別・').replace('業種別_', '業種別・')}）"
            ch.y_axis.title = "ウェイト"
            ch.height, ch.width = 18, 34
            ch.legend.position = "b"
            ch.add_data(Reference(ws, min_col=2, max_col=nc, min_row=1, max_row=nr), titles_from_data=True)
            ch.set_categories(Reference(ws, min_col=1, min_row=2, max_row=nr))
            ch.x_axis.number_format = "yyyy-mm"
            ws.add_chart(ch, f"{get_column_letter(nc + 2)}2")
        # 最新ウェイト棒グラフ
        ws = wb["最新ウェイト(%)"]
        ch = BarChart()
        ch.type = "bar"
        ch.title = "最新の最適ウェイト(%)"
        ch.height, ch.width = 14, 22
        ch.add_data(Reference(ws, min_col=2, max_col=4, min_row=1, max_row=ws.max_row), titles_from_data=True)
        ch.set_categories(Reference(ws, min_col=1, min_row=2, max_row=ws.max_row))
        ch.y_axis.scaling.orientation = "maxMin"
        ch.x_axis.scaling.orientation = "maxMin"
        ws.add_chart(ch, "F2")
        # 累積リターン
        ws = wb["バックテスト"]
        r0 = len(stats) + 4
        ch = LineChart()
        ch.title = "事後検証：1円投資の推移（リバランス後の翌月を保有）"
        ch.height, ch.width = 12, 26
        ch.add_data(Reference(ws, min_col=2, max_col=5, min_row=r0, max_row=ws.max_row), titles_from_data=True)
        ch.set_categories(Reference(ws, min_col=1, min_row=r0 + 1, max_row=ws.max_row))
        ws.add_chart(ch, "H2")
        ws.column_dimensions["A"].width = 16


def main():
    ap = argparse.ArgumentParser(description="最適投資ウェイトの推移")
    ap.add_argument("--top", type=int, default=20, help="総合順位上位から何銘柄（既定20）")
    ap.add_argument("--per-sector", type=int, default=2, help="1業種あたり最大銘柄数（0=制限なし）")
    ap.add_argument("--codes", nargs="+", help="銘柄コードを直接指定")
    ap.add_argument("--sector-top", type=int, default=0, help="各業種の時価総額上位N銘柄を対象にする（例: 2）")
    ap.add_argument("--tag", default="", help="出力ファイル名に付ける名前")
    ap.add_argument("--window", type=float, default=3, help="推定窓（年, 既定3）")
    ap.add_argument("--freq", choices=["M", "Q"], default="M", help="リバランス M=毎月 Q=四半期")
    ap.add_argument("--history", type=int, default=10, help="使う価格履歴（年）")
    ap.add_argument("--cap", type=float, default=0.25, help="1銘柄の上限ウェイト（既定0.25）")
    ap.add_argument("--rf", type=float, default=0.005, help="無リスク金利（年率, 既定0.005）")
    ap.add_argument("--shrink-mu", type=float, default=0.5, help="期待リターンの縮小率 0〜1")
    args = ap.parse_args()

    uni, px, rets, W, info = run(args)
    nav, stats = backtest(rets, W, args.rf)
    OUT_DIR.mkdir(exist_ok=True)
    tag = args.tag or (f"業種時価総額上位{args.sector_top}" if args.sector_top else "")
    out = OUT_DIR / f"最適ウェイト推移_{tag + '_' if tag else ''}{dt.date.today():%Y%m%d}.xlsx"
    write_excel(out, args, uni, W, info, nav, stats)
    print(f"\nリバランス回数: {len(W['min_var'])} 回 "
          f"({W['min_var'].index[0].date()} 〜 {W['min_var'].index[-1].date()})")
    print("\n[事後検証]\n" + stats.round(2).to_string(index=False))
    lab = dict(zip(uni["コード"], uni["銘柄名"]))
    print("\n[最新ウェイト %]")
    lw = pd.DataFrame({METHODS[m]: W[m].iloc[-1] * 100 for m in METHODS})
    lw.index = [f"{c} {lab[c]}" for c in lw.index]
    print(lw.sort_values("最大シャープ", ascending=False).round(1).to_string())
    print(f"\n保存: {out}")


if __name__ == "__main__":
    main()
