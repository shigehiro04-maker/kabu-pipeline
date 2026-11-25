"""はっしゃん式理論株価の指標（理論株価Webの45項目のうち、手元のデータで計算できるもの）

入力
  fundamentals/valuation.csv            最新のはっしゃん式（資産価値・事業価値・リスク評価率・上限株価）
  fundamentals/fundamentals_by_year.csv 過去の決算（最大4期）→ 過去のはっしゃん式理論株価の推移
  data/prices/<コード>.csv              日足（最大10年）→ 株価トレンド・α値・相関度・出来高
出力
  fundamentals/hashang_metrics.csv

計算の注意（理論株価Webとの違い）
  ・決算データが最大4期分のため「10年来理論」「理論増減数」「全相関度」「配当増減数」は取れる期間（最大4期）で計算する。
    持続成長・配当成長の「増減数+8以上（10年）」は、取れる期間に合わせて「増えた回数−減った回数 ≥ 遷移回数×8/9」に読み替える
  ・過去の理論株価は、予想経常利益の代わりに各期の税引前利益（実績）で計算し、決算期末の45日後から次の決算まで有効とする
  ・10年スコア・配当格付・投資難易度・株主優待・直近先行は算出方法が非公開またはデータが無いため出さない
  ・割安･収益性、出来高過熱、流動性(万)は公開されている目安に沿った当方の定義（下の定数）
"""
from __future__ import annotations

import sys
from math import ceil
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
SITE = BASE / "data" / "charts"
CHART_DIR = SITE / "valuation"     # 銘柄ごとの理論株価チャート用データ valuation/<コード>.js（ページが必要なときだけ読む）
FUND = BASE / "fundamentals"
LAG_DAYS = 45          # 決算期末から理論株価が更新されるまでの目安


def num(s):
    return pd.to_numeric(s, errors="coerce")


def hashang(bps, er, keijo, shares, price):
    """はっしゃん式（理論株価Web準拠）。戻り値: 理論株価, 資産価値, 事業価値, 上限株価"""
    if not (np.isfinite(bps) and bps > 0 and np.isfinite(er)):
        return (np.nan,) * 4
    er = max(er, 0.001)
    rate = .8 if er >= .8 else .75 if er >= .67 else .7 if er >= .5 else .65 if er >= .33 else .6 if er >= .1 else .5
    asset = bps * rate
    biz = 0.0
    if np.isfinite(keijo) and keijo > 0 and shares > 0:
        eps = min(keijo * 0.7 / shares, bps * 0.6)
        roa = min(eps / (bps / er), 0.30)
        lev = 1 / min(1.0, max(0.66, er + 0.33))
        biz = eps * roa * 150 * lev
    pbr = price / bps if np.isfinite(price) and price > 0 else np.nan
    if not np.isfinite(pbr) or pbr >= 0.5:
        rr = 1.0
    elif pbr > 0.40: rr = 0.80
    elif pbr > 0.33: rr = 0.67
    elif pbr > 0.25: rr = 0.50
    elif pbr > 0.20: rr = 0.34
    elif pbr >= 0.04: rr = 0.05 + (pbr - 0.04) / 0.16 * 0.20
    else: rr = 0.005 + max(pbr, 0) / 0.04 * 0.02
    return (asset + biz) * rr, asset, biz, asset + biz * 2


def updown(vals):
    v = [x for x in vals if np.isfinite(x)]
    if len(v) < 2:
        return np.nan, 0
    s = sum(1 if b > a else -1 if b < a else 0 for a, b in zip(v, v[1:]))
    return s, len(v) - 1


def corr(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 6 or np.std(a[m]) == 0 or np.std(b[m]) == 0:
        return np.nan
    return float(np.corrcoef(a[m], b[m])[0, 1])


def _r(x):
    if x is None or not np.isfinite(x):
        return None
    return round(float(x), 1) if abs(x) < 1000 else int(round(x))


def write_chart(code, m, tm, am, um):
    """valuation/<コード>.js：月足の株価・理論株価・上限株価・資産価値（JSONP形式。file:// でも読める）"""
    import json
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    d = {"s": m.index[0].strftime("%Y-%m"), "p": [_r(x) for x in m["close"]],
         "t": [_r(x) for x in tm], "u": [_r(x) for x in um], "a": [_r(x) for x in am]}
    js = "window.VH=window.VH||{};VH[" + json.dumps(code) + "]=" + json.dumps(d, separators=(",", ":")) + ";"
    f = CHART_DIR / f"{code}.js"
    try:
        if f.exists() and f.read_text(encoding="utf-8") == js:
            return
    except Exception:
        pass
    f.write_text(js, encoding="utf-8")


def main() -> int:
    val = pd.read_csv(FUND / "valuation.csv", dtype={"コード": str}, low_memory=False)
    yrs = pd.read_csv(FUND / "fundamentals_by_year.csv", dtype={"コード": str}, low_memory=False)
    yrs = yrs.sort_values(["コード", "決算期"])
    sc = pd.read_csv(FUND / "analysis" / "スコア一覧.csv", dtype={"コード": str}, low_memory=False)
    sc = sc.set_index("コード")
    by = {c: g for c, g in yrs.groupby("コード")}
    rows = []
    for _, v in val.iterrows():
        c = v["コード"]
        r = {"コード": c}
        px_now = v["株価"]
        T, A, B, U = (num(pd.Series([v.get(k)])).iloc[0] for k in ("はっしゃん式", "はっしゃん式_資産価値", "はっしゃん式_事業価値", "はっしゃん式_上限"))
        r["事業比率(%)"] = round(B / T * 100, 1) if np.isfinite(T) and T > 0 and np.isfinite(B) else np.nan
        r["最新α値(%)"] = round((T / px_now - 1) * 100, 1) if np.isfinite(T) and px_now > 0 else np.nan
        f = BASE / "data" / "prices" / f"{c}.csv"
        if not f.exists():
            rows.append(r); continue
        try:
            p = pd.read_csv(f, usecols=["date", "close", "volume"], parse_dates=["date"]).dropna(subset=["close"])
        except Exception:
            rows.append(r); continue
        if p.empty:
            rows.append(r); continue
        p = p.set_index("date").sort_index()
        last = p.index[-1]
        cl = p["close"]
        # ---- 長期株価トレンド
        first = cl.iloc[0]
        r["10年来株価(%)"] = round((cl.iloc[-1] / first - 1) * 100, 1)
        r["データ開始日"] = p.index[0].date().isoformat()
        hi_d = cl.idxmax()
        r["株価高値比(%)"] = round((cl.iloc[-1] / cl.max() - 1) * 100, 1)
        r["株価高値後(月)"] = int(round((last - hi_d).days / 30.44))
        # ---- 月足
        m = p.resample("ME").agg({"close": "last", "volume": "sum"}).dropna(subset=["close"])
        # ---- 過去の理論株価（各決算期）
        g = by.get(c)
        pts = []   # (有効開始日, 理論, 資産, 事業)
        if g is not None:
            for _, y in g.iterrows():
                end = pd.Timestamp(str(y["決算期"])[:10])
                eff = end + pd.Timedelta(days=LAG_DAYS)
                bps, eq = num(pd.Series([y["BPS"]])).iloc[0], num(pd.Series([y["自己資本"]])).iloc[0]
                er = num(pd.Series([y["自己資本比率(%)"]])).iloc[0] / 100
                kj = num(pd.Series([y["税引前利益"]])).iloc[0]
                sh = eq / bps if bps and bps > 0 and eq and eq > 0 else np.nan
                pr = cl[:eff]
                price = float(pr.iloc[-1]) if len(pr) else np.nan
                t, a, b, _ = hashang(bps, er, kj, sh, price)
                if np.isfinite(t):
                    pts.append((eff, t, a, b))
        if np.isfinite(T):
            pts.append((last, T, A, B))
        pts.sort(key=lambda x: x[0])
        tv = [x[1] for x in pts]
        if len(tv) >= 2:
            r["10年来理論(%)"] = round((tv[-1] / tv[0] - 1) * 100, 1) if tv[0] > 0 else np.nan
            s, n = updown(tv)
            r["理論増減数"] = s
            r["理論の遷移回数"] = n
            r["理論高値比(%)"] = round((tv[-1] / max(tv) - 1) * 100, 1)
            imax = int(np.argmax(tv))
            r["理論高値後(月)"] = int(round((last - pts[imax][0]).days / 30.44))
            r["理論の期間"] = f"{pts[0][0].date().isoformat()}〜"
        # 月末ごとの理論株価（その時点で有効な最新の値）
        if pts:
            eff_idx = pd.DatetimeIndex([x[0] for x in pts])
            tm = []
            for d in m.index:
                k = eff_idx.searchsorted(d, side="right") - 1
                tm.append(tv[k] if k >= 0 else np.nan)
            m["theory"] = tm
            am, um = [], []
            for d in m.index:
                k = eff_idx.searchsorted(d, side="right") - 1
                am.append(pts[k][2] if k >= 0 else np.nan)
                um.append(pts[k][2] + pts[k][3] * 2 if k >= 0 else np.nan)
            m["alpha"] = (m["theory"] - m["close"]) / m["close"]
            ok = m["theory"].notna()
            if ok.sum() >= 3:
                r["平均α値(%)"] = round(float(m.loc[ok, "alpha"].mean()) * 100, 1)
            r["全相関度(%)"] = round(corr(m.loc[ok, "close"], m.loc[ok, "theory"]) * 100, 1) if ok.sum() >= 6 else np.nan
            mm = m.loc[ok].tail(12)
            r["1年相関度(%)"] = round(corr(mm["close"], mm["theory"]) * 100, 1) if len(mm) >= 6 else np.nan
            # 直近理論：2ヶ月前に有効だった理論株価からの変化
            d2 = last - pd.DateOffset(months=2)
            k = eff_idx.searchsorted(d2, side="right") - 1
            if k >= 0 and tv[k] > 0:
                r["直近理論(%)"] = round((tv[-1] / tv[k] - 1) * 100, 1)
        # ---- 直近トレンド（2ヶ月）
        d2 = last - pd.DateOffset(months=2)
        prev = cl[:d2]
        if len(prev):
            r["直近株価(%)"] = round((cl.iloc[-1] / prev.iloc[-1] - 1) * 100, 1)
        sh_now = num(pd.Series([sc["発行済株式数"].get(c) if "発行済株式数" in sc else np.nan])).iloc[0]
        if not np.isfinite(sh_now):
            sh_now = v["時価総額(億円)"] * 1e8 / px_now if px_now > 0 else np.nan
        vol2 = p["volume"][p.index > d2].sum()
        vol2p = p["volume"][(p.index > d2 - pd.DateOffset(months=2)) & (p.index <= d2)].sum()
        if vol2p > 0:
            r["直近出来高(%)"] = round((vol2 / vol2p - 1) * 100, 1)
        # ---- 出来高過熱・イナゴ指数（月足）
        if len(m) >= 2 and np.isfinite(sh_now) and sh_now > 0:
            turn = m["volume"].iloc[-1] / sh_now * 100
            r["月間回転率(%)"] = round(turn, 1)
            r["出来高過熱"] = ("A:大炎上" if turn >= 100 else "B:炎上" if turn >= 50 else "C:過熱" if turn >= 20
                              else "D:活発" if turn >= 10 else "E:普通" if turn >= 5 else "F:平穏")
        if len(m) >= 2:
            ina = (m["close"].iloc[-1] / m["close"].iloc[-2] - 1) * 100
            r["イナゴ指数(%)"] = round(ina, 1)
            r["イナゴ判定"] = "イナゴ注意報" if ina >= 50 else "暴落注意報" if ina <= -33 else ""
        # ---- 流動性（万）：25日平均売買代金の1%（当方の目安）
        tv25 = (p["close"] * p["volume"]).tail(25).mean()
        r["流動性(万)"] = round(tv25 * 0.01 / 1e4, 0) if np.isfinite(tv25) else np.nan
        # ---- 株主還元トレンド
        dy = num(pd.Series([sc["配当利回り(%)"].get(c)])).iloc[0] if "配当利回り(%)" in sc else np.nan
        r["配当利回り(%)"] = round(dy, 2) if np.isfinite(dy) else np.nan
        if g is not None:
            dv = num(g["一株配当"]).tolist()
            dvf = [x for x in dv if np.isfinite(x)]
            if dvf:
                s, n = updown(dvf)
                r["配当増減数"] = s
                r["配当の遷移回数"] = n
                cur = dvf[-1]
                r["配当高値比(%)"] = round((cur / max(dvf) - 1) * 100, 1) if max(dvf) > 0 else np.nan
        # ---- 決算日・上場年数（株価データの範囲内）
        if g is not None and len(g):
            r["決算期"] = str(g["決算期"].iloc[-1])[:7]
        yrs_listed = (last - p.index[0]).days / 365.25
        r["上場年数"] = "10年以上" if yrs_listed >= 9.9 else f"{yrs_listed:.1f}年"
        rows.append(r)

    o = pd.DataFrame(rows)
    # ---- 企業価値コア4条件（理論株価Webの目安。期間が短い分は遷移回数で読み替え）
    need = lambda n: np.ceil(n * 8 / 9)
    o["正相関度〇"] = ((o["全相関度(%)"] >= 50) & (o["1年相関度(%)"] >= 50) & (o["10年来理論(%)"] >= 0)).astype(int)
    o["割安修正〇"] = ((o["平均α値(%)"] >= 0) & (o["最新α値(%)"] >= 0) & (o["最新α値(%)"] < o["平均α値(%)"])).astype(int)
    o["持続成長〇"] = ((o["理論の遷移回数"] >= 2) & (o["理論増減数"] >= need(o["理論の遷移回数"]))
                      & (o["理論高値比(%)"] >= -15)).astype(int)
    o["配当成長〇"] = ((o["配当の遷移回数"] >= 2) & (o["配当増減数"] >= need(o["配当の遷移回数"]))
                      & (o["配当高値比(%)"] >= -15)).astype(int)
    o["コア4条件"] = o[["正相関度〇", "割安修正〇", "持続成長〇", "配当成長〇"]].sum(axis=1)
    # ---- 割安･収益性（当方の目安）
    def cheap(row):
        a, t = row.get("最新α値(%)"), row.get("リスク評価率")
        if not np.isfinite(a):
            return ""
        if np.isfinite(t) and t < 1:
            return "減額型"
        return ("超割安" if a >= 100 else "割安" if a >= 50 else "準割安" if a >= 20 else "適正" if a >= -20
                else "準割高" if a >= -50 else "割高" if a >= -70 else "超割高" if a >= -90 else "投機型")
    def prof(row):
        b = row.get("事業比率(%)")
        if not np.isfinite(b):
            return ""
        return ("赤字" if b <= 0 else "超低収益" if b < 20 else "低収益" if b <= 40 else "標準" if b < 60
                else "高収益" if b < 80 else "超高収益")
    o = o.merge(val[["コード", "はっしゃん式_リスク評価率"]].rename(columns={"はっしゃん式_リスク評価率": "リスク評価率"}), on="コード", how="left")
    o["割安･収益性"] = [f"{cheap(r)}・{prof(r)}".strip("・") for _, r in o.iterrows()]
    o = o.drop(columns=["リスク評価率"])
    o.to_csv(FUND / "hashang_metrics.csv", index=False, encoding="utf-8-sig")
    print(f"はっしゃん式の指標: {len(o)} 銘柄 → {FUND/'hashang_metrics.csv'}（コア4条件2以上 {int((o['コア4条件']>=2).sum())} 銘柄）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
