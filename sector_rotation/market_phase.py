#!/usr/bin/env python3
"""相場の四季（浦上邦雄）の判定：金融相場／業績相場／逆金融相場／逆業績相場

考え方
  株価 = EPS（業績）× PER（評価）。4つの局面は「金利」「業績」「株価」の向きの組み合わせで決まる。

    局面        金利   業績(EPS)  株価   株価上昇の主役
    金融相場     ↓      ↓〜底     ↑     PER拡大（金融緩和で評価が上がる）
    業績相場     ↑(緩)  ↑         ↑     EPS拡大（PERは横ばい〜低下）
    逆金融相場   ↑(急)  ↑(まだ良い) ↓    PER縮小（引き締めで評価が下がる）
    逆業績相場   ↓      ↓         ↓     EPS縮小

判定方法
  4つの指標の6ヶ月変化を -1〜+1 に変換（tanh）し、局面ごとの「典型パターン」との一致度をスコア化。
  一番スコアが高い局面を現在の局面とする。

データ
  米国: 株価=S&P500、EPS=S&P500 12ヶ月実績EPS（multpl.com、月次）、金利=米10年・米3ヶ月
  日本: 株価=同じ銘柄群の時価総額合計（TOPIXに近い）、EPS=プライム銘柄の会社予想純利益の合計（J-Quants 決算短信サマリー）、
        金利=国債10年（財務省）・日銀政策金利
  ※ EPSは公表の遅れがあるため、直近数ヶ月は最後の値で横ばい扱い（stale_months で表示）。
"""
import glob
import io
import json
import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
CACHE = os.path.join(HERE, "output", "cache")
os.makedirs(CACHE, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

PHASES = ["金融相場", "業績相場", "逆金融相場", "逆業績相場"]
SEASON = {"金融相場": "春", "業績相場": "夏", "逆金融相場": "秋", "逆業績相場": "冬"}
NEXT = {"金融相場": "業績相場", "業績相場": "逆金融相場", "逆金融相場": "逆業績相場", "逆業績相場": "金融相場"}

# 各局面の典型パターン（株価, 金利, EPS, PER の向き。+1=上昇, -1=低下, 0=問わない）
TEMPLATE = {
    "金融相場":   {"P": 1.0, "R": -1.0, "E": -0.5, "V": 1.0},
    "業績相場":   {"P": 1.0, "R": 0.5, "E": 1.0, "V": -0.5},
    "逆金融相場": {"P": -1.0, "R": 1.0, "E": 0.5, "V": -1.0},
    "逆業績相場": {"P": -1.0, "R": -0.5, "E": -1.0, "V": 0.0},
}
# tanh変換のスケール（この大きさの変化で約0.76）
SCALE = {"P": 8.0, "E": 5.0, "V": 8.0, "R_long": 0.40, "R_policy": 0.25}

# 日銀の政策金利（誘導目標。0〜0.1%は0.05%として扱う）
BOJ_POLICY = [
    ("2016-02-16", -0.10), ("2024-03-19", 0.05), ("2024-07-31", 0.25), ("2025-01-24", 0.50),
    ("2025-12-19", 0.75), ("2026-06-16", 1.00), ("2026-09-18", 1.25),
]

# 局面ごとに教科書的に強い業種（目安）
TYPICAL = {
    "金融相場": "金利低下の恩恵：不動産・建設・グロース/ハイテク・小型株。出遅れ景気敏感の買い戻し",
    "業績相場": "前半＝素材・化学・鉄鋼・機械などの景気敏感、後半＝ハイテク・消費関連・資源",
    "逆金融相場": "ディフェンシブ（食品・医薬品・公益・通信）。前半は銀行・保険など金利上昇の恩恵業種",
    "逆業績相場": "ディフェンシブ・高配当・低PBR。景気敏感と小型株は避ける",
}


# ----------------------------------------------------------------------------
def clean_prices(df, thresh=0.35):
    """Yahooの異常値（例：1306.Tの2026/3/30-31が1/10の値）を除去。
    前後11日の中央値から35%以上離れた値を欠損にして前日値で埋める。"""
    df = df.copy()
    orig_nan = df.isna()                      # 元から無い日（休場日など）は欠損のまま残す
    for c in df.columns:
        s = df[c]
        med = s.rolling(11, center=True, min_periods=3).median()
        bad = (np.log(s / med).abs() > np.log(1 + thresh))
        if bad.any():
            df.loc[bad, c] = np.nan
    return df.ffill(limit=5).mask(orig_nan)


def _cache_csv(name, s=None):
    p = os.path.join(CACHE, name)
    if s is not None:
        s.to_csv(p)
        return s
    if os.path.exists(p):
        return pd.read_csv(p, index_col=0, parse_dates=True).iloc[:, 0]
    return None


def fetch_multpl(kind):
    """kind: 'earnings'（12ヶ月実績EPS）/ 'pe'（PER）。失敗時は前回のキャッシュを使う。"""
    import requests
    url = {"earnings": "https://www.multpl.com/s-p-500-earnings/table/by-month",
           "pe": "https://www.multpl.com/s-p-500-pe-ratio/table/by-month"}[kind]
    try:
        r = requests.get(url, headers=UA, timeout=30)
        r.raise_for_status()
        t = pd.read_html(io.StringIO(r.text))[0]
        t.columns = ["date", "value"]
        t["date"] = pd.to_datetime(t["date"])
        t["value"] = pd.to_numeric(t["value"].astype(str).str.replace(r"[^0-9.\-]", "", regex=True), errors="coerce")
        s = t.dropna().set_index("date")["value"].sort_index()
        return _cache_csv(f"multpl_{kind}.csv", s)
    except Exception as e:
        print(f"  multpl {kind} 取得失敗（キャッシュ使用）: {e}")
        return _cache_csv(f"multpl_{kind}.csv")


def fetch_jgb10():
    """財務省の国債金利（日次）から10年債利回り。失敗時はキャッシュ。"""
    import requests
    try:
        r = requests.get("https://www.mof.go.jp/jgbs/reference/interest_rate/data/jgbcm_all.csv",
                         headers=UA, timeout=60)
        r.raise_for_status()
        txt = r.content.decode("shift_jis", errors="replace")
        df = pd.read_csv(io.StringIO(txt), skiprows=1)
        df = df.rename(columns={df.columns[0]: "date"})
        era = {"S": 1925, "H": 1988, "R": 2018}

        def conv(x):
            try:
                g, rest = x[0], x[1:]
                y, m, d = rest.split(".")
                return pd.Timestamp(era[g] + int(y), int(m), int(d))
            except Exception:
                return pd.NaT
        df["date"] = df["date"].astype(str).map(conv)
        s = pd.to_numeric(df.set_index("date")["10年"], errors="coerce").dropna()
        s = s[s.index.notna()].sort_index()
        try:  # 当月分（jgbcm.csv）を足す
            r2 = requests.get("https://www.mof.go.jp/jgbs/reference/interest_rate/jgbcm.csv", headers=UA, timeout=30)
            d2 = pd.read_csv(io.StringIO(r2.content.decode("shift_jis", errors="replace")), skiprows=1)
            d2 = d2.rename(columns={d2.columns[0]: "date"})
            d2["date"] = d2["date"].astype(str).map(conv)
            s2 = pd.to_numeric(d2.set_index("date")["10年"], errors="coerce").dropna()
            s2 = s2[s2.index.notna()]
            s = pd.concat([s, s2]).groupby(level=0).last().sort_index()
        except Exception:
            pass
        return _cache_csv("jgb10.csv", s)
    except Exception as e:
        print(f"  国債金利 取得失敗（キャッシュ使用）: {e}")
        return _cache_csv("jgb10.csv")


def boj_policy(index):
    s = pd.Series({pd.Timestamp(d): v for d, v in BOJ_POLICY}).sort_index()
    return s.reindex(s.index.union(index)).ffill().reindex(index)


def jp_forecast_aggregate(start="2024-09-30"):
    """J-Quants 決算短信サマリーから、プライム銘柄の会社予想純利益合計（月末時点）と時価総額合計を作る。
    同じ銘柄群で比較するため、全期間で予想がある銘柄だけを使う（バランスド・パネル）。"""
    jdir = os.path.join(BASE, "fundamentals", "jq_summary")
    files = sorted(glob.glob(os.path.join(jdir, "*.json")))
    if not files:
        return None
    rows = []
    for f in files:
        try:
            for r in json.load(open(f, encoding="utf-8")):
                if r.get("CurPerType") == "FY":
                    v = r.get("NxFNp") or r.get("FNP")
                else:
                    v = r.get("FNP")
                if v in (None, ""):
                    continue
                sh = float(r["ShOutFY"]) - float(r.get("TrShFY") or 0) if r.get("ShOutFY") else np.nan
                rows.append((pd.Timestamp(r["DiscDate"]), str(r["Code"])[:4], float(v), sh))
        except Exception:
            continue
    if not rows:
        return None
    d = pd.DataFrame(rows, columns=["date", "code", "fnp", "shares"]).sort_values("date")
    sec = pd.read_csv(os.path.join(BASE, "tickers", "sectors.csv"), dtype={"code": str})
    prime = set(sec.loc[sec["market"].astype(str).str.contains("プライム"), "code"])
    d = d[d["code"].isin(prime)]
    last = d["date"].max()
    months = pd.date_range(start, last + pd.offsets.MonthEnd(0), freq="ME")
    fnp = d.pivot_table(index="date", columns="code", values="fnp", aggfunc="last")
    shs = d.pivot_table(index="date", columns="code", values="shares", aggfunc="last")
    allidx = fnp.index.union(months)
    fnp_m = fnp.reindex(allidx).ffill().reindex(months)
    shs_m = shs.reindex(allidx).ffill().reindex(months)
    panel = fnp_m.columns[fnp_m.notna().all()]
    # 月末株価
    closes = {}
    pdir = os.path.join(BASE, "data", "prices")
    for c in panel:
        f = os.path.join(pdir, f"{c}.csv")
        if os.path.exists(f):
            p = pd.read_csv(f, usecols=["date", "close"], parse_dates=["date"]).set_index("date")["close"]
            closes[c] = p[~p.index.duplicated()].sort_index()
    if not closes:
        return None
    C = pd.DataFrame(closes)
    C_m = C.reindex(C.index.union(months)).ffill().reindex(months)
    panel = [c for c in panel if c in C_m.columns and c in shs_m.columns and shs_m[c].notna().any()]
    shs_m = shs_m.bfill()          # 最初の開示に株数が無い場合は後の値で補う
    # 現在まで（株価は最新月まで、予想は最後の開示日まで）
    today_m = pd.Timestamp(C.index.max()) + pd.offsets.MonthEnd(0)
    months_full = pd.date_range(start, today_m, freq="ME")
    fnp_f = fnp_m[panel].reindex(months_full).ffill()
    shs_f = shs_m[panel].reindex(months_full).ffill()
    C_f = C.reindex(C.index.union(months_full)).ffill().reindex(months_full)[panel]
    C_f.iloc[-1] = C[panel].ffill().iloc[-1]          # 最新月は最新の終値
    mcap = (C_f * shs_f).sum(axis=1)
    np_sum = fnp_f.sum(axis=1)
    out = pd.DataFrame({"np_forecast": np_sum / 1e12, "mcap": mcap / 1e12})
    out["per"] = out["mcap"] / out["np_forecast"]
    out.attrs["n"] = len(panel)
    out.attrs["last_disclosure"] = str(last.date())
    out.attrs["stale_from"] = str((last + pd.offsets.MonthEnd(0)).date())
    return out


# ----------------------------------------------------------------------------
def score_frame(m):
    """m: 月次DataFrame（price, eps, per, r_long, r_policy）→ 指標・スコア・局面を付けて返す"""
    f = pd.DataFrame(index=m.index)
    f["P"] = m["price"].pct_change(6) * 100
    f["E"] = m["eps"].pct_change(6) * 100
    f["V"] = m["per"].pct_change(6) * 100
    f["R_long"] = m["r_long"].diff(6)
    f["R_policy"] = m["r_policy"].diff(6)
    s = pd.DataFrame(index=m.index)
    s["P"] = np.tanh(f["P"] / SCALE["P"])
    s["E"] = np.tanh(f["E"] / SCALE["E"])
    s["V"] = np.tanh(f["V"] / SCALE["V"])
    s["R"] = (np.tanh(f["R_long"] / SCALE["R_long"]) + np.tanh(f["R_policy"] / SCALE["R_policy"])) / 2
    for ph, t in TEMPLATE.items():
        den = sum(abs(v) for v in t.values())
        f[ph] = sum(t[k] * s[k] for k in t) / den
    f = f.dropna(subset=PHASES)
    f["局面"] = f[PHASES].idxmax(axis=1)
    srt = np.sort(f[PHASES].values, axis=1)
    f["確度"] = srt[:, -1] - srt[:, -2]           # 1位と2位の差（大きいほど明確）
    for k in ["P", "E", "V", "R"]:
        f[f"s_{k}"] = s[k].reindex(f.index)
    return f


def transition_signals(phase, m, daily_price):
    """現在の局面から次の局面へ移る兆候をチェック（True=点灯）"""
    p = daily_price.dropna()
    below200 = bool(p.iloc[-1] < p.rolling(200).mean().iloc[-1])
    r3 = lambda col: m[col].iloc[-1] - m[col].iloc[-4]
    pct3 = lambda col: (m[col].iloc[-1] / m[col].iloc[-4] - 1) * 100
    sig = {
        "金融相場": [("業績（EPS）が3ヶ月で増加に転じた", pct3("eps") > 0),
                   ("長期金利が3ヶ月で上昇に転じた", r3("r_long") > 0)],
        "業績相場": [("長期金利が6ヶ月で+0.5%pt以上上昇（引き締め的）", m["r_long"].iloc[-1] - m["r_long"].iloc[-7] >= 0.5),
                   ("政策金利が直近6ヶ月で引き上げられた", m["r_policy"].iloc[-1] - m["r_policy"].iloc[-7] > 0),
                   ("PERが3ヶ月で低下（評価の縮小が始まった）", pct3("per") < 0),
                   ("株価が200日移動平均を下回った", below200)],
        "逆金融相場": [("業績（EPS）が3ヶ月で減少に転じた", pct3("eps") < 0),
                    ("長期金利が3ヶ月で低下に転じた（ピークアウト）", r3("r_long") < 0)],
        "逆業績相場": [("政策金利が引き下げられた（6ヶ月）", m["r_policy"].iloc[-1] - m["r_policy"].iloc[-7] < 0),
                    ("業績はまだ悪いが株価が3ヶ月で上昇", pct3("price") > 0 and pct3("eps") < 0)],
    }[phase]
    return [{"条件": t, "点灯": bool(v)} for t, v in sig]


def build_monthly_us(px):
    price = px["^GSPC"].dropna().resample("ME").last()
    eps = fetch_multpl("earnings")
    if eps is None:
        return None
    eps = eps.resample("ME").last()
    stale_from = eps.dropna().index[-1]
    idx = price.index
    m = pd.DataFrame(index=idx)
    m["price"] = price
    m["eps"] = eps.reindex(idx.union(eps.index)).ffill().reindex(idx)
    m["per"] = m["price"] / m["eps"]
    m["r_long"] = px["^TNX"].dropna().resample("ME").last().reindex(idx).ffill()
    m["r_policy"] = px["^IRX"].dropna().resample("ME").last().reindex(idx).ffill()
    m = m.dropna()
    m.attrs["eps_last"] = str(stale_from.date())
    m.attrs["eps_note"] = "S&P500 12ヶ月実績EPS（multpl.com）"
    return m


def build_monthly_jp(px):
    agg = jp_forecast_aggregate()
    if agg is None:
        return None
    jgb = fetch_jgb10()
    idx = agg.index
    m = pd.DataFrame(index=idx)
    m["price"] = agg["mcap"]          # 株価＝同じ銘柄群の時価総額合計（PERと整合、TOPIXに近い）
    m["eps"] = agg["np_forecast"]
    m["per"] = agg["per"]
    m["mcap"] = agg["mcap"]
    m["r_long"] = jgb.resample("ME").last().reindex(idx).ffill() if jgb is not None else np.nan
    m["r_policy"] = boj_policy(idx)
    m = m.dropna(subset=["price", "eps", "per", "r_long"])
    m.attrs["eps_last"] = agg.attrs["last_disclosure"]
    m.attrs["eps_note"] = f"プライム{agg.attrs['n']}社の会社予想純利益合計（J-Quants、兆円）"
    return m


def analyze_market(m, daily_price, label):
    f = score_frame(m)
    cur = f.iloc[-1]
    ph = cur["局面"]
    stale = (m.index[-1].to_period("M") - pd.Timestamp(m.attrs["eps_last"]).to_period("M")).n
    return {
        "label": label, "asof": str(daily_price.dropna().index[-1].date()),
        "phase": ph, "season": SEASON[ph], "next": NEXT[ph],
        "scores": {p: float(cur[p]) for p in PHASES}, "conviction": float(cur["確度"]),
        "metrics": {"株価 6ヶ月変化(%)": float(cur["P"]), "EPS 6ヶ月変化(%)": float(cur["E"]),
                    "PER 6ヶ月変化(%)": float(cur["V"]), "長期金利 6ヶ月変化(%pt)": float(cur["R_long"]),
                    "政策/短期金利 6ヶ月変化(%pt)": float(cur["R_policy"])},
        "levels": {"株価": float(m["price"].iloc[-1]), "EPS": float(m["eps"].iloc[-1]),
                   "PER": float(m["per"].iloc[-1]), "長期金利": float(m["r_long"].iloc[-1]),
                   "政策/短期金利": float(m["r_policy"].iloc[-1])},
        "signals": transition_signals(ph, m, daily_price),
        "typical": TYPICAL[ph], "typical_next": TYPICAL[NEXT[ph]],
        "eps_note": m.attrs["eps_note"], "eps_last": m.attrs["eps_last"], "eps_stale_months": int(stale),
        "history": f, "monthly": m,
    }


def run(px):
    """px: yfinance の日次終値（^GSPC, ^TNX, ^IRX, 1306.T を含む）"""
    out = {}
    mu = build_monthly_us(px)
    if mu is not None:
        out["us"] = analyze_market(mu, px["^GSPC"], "米国（S&P500）")
    mj = build_monthly_jp(px)
    if mj is not None:
        out["jp"] = analyze_market(mj, px["1306.T"], "日本（TOPIX）")
    return out


if __name__ == "__main__":
    import yfinance as yf
    px = yf.download(["^GSPC", "^TNX", "^IRX", "1306.T"], period="15y", auto_adjust=True, progress=False)["Close"]
    px.index = pd.to_datetime(px.index).tz_localize(None)
    px = clean_prices(px[px.index.dayofweek < 5])
    res = run(px)
    pd.set_option("display.width", 220)
    for k, r in res.items():
        print(f"\n== {r['label']}  局面: {r['phase']}（{r['season']}） 確度 {r['conviction']:.2f}  EPS最終 {r['eps_last']}")
        print({p: round(v, 2) for p, v in r["scores"].items()})
        print({p: round(v, 2) for p, v in r["metrics"].items()})
        print(r["levels"]); print(r["signals"])
        h = r["history"]
        print(h[["P", "E", "V", "R_long", "R_policy", "局面", "確度"]].iloc[-30:].round(2).to_string())


# ----------------------------------------------------------------------------
# 出力（ダッシュボードHTMLの部品・Excelシート）
# ----------------------------------------------------------------------------
PH_COLOR = {"金融相場": "#2f9e6e", "業績相場": "#e0a12b", "逆金融相場": "#d0603a", "逆業績相場": "#4a6fa5"}
PH_DESC = {
    "金融相場": "金利↓・業績↓・株価↑（PER拡大が主役）",
    "業績相場": "金利↑・業績↑・株価↑（EPS拡大が主役）",
    "逆金融相場": "金利↑・業績↑・株価↓（PER縮小が主役）",
    "逆業績相場": "金利↓・業績↓・株価↓（EPS縮小が主役）",
}


def _arrow(v, th):
    if v is None or np.isnan(v):
        return "–"
    return "↑" if v > th else "↓" if v < -th else "→"


def conviction_text(c):
    return "明確" if c >= 0.30 else "やや優勢" if c >= 0.10 else "移行期（判定が拮抗）"


def phase_html(phases, sector_results=None):
    """ダッシュボードに差し込むHTML（Chart.jsは本体側で読み込み済みの前提）"""
    if not phases:
        return ""
    cards, charts = [], {}
    for key, r in phases.items():
        ph = r["phase"]
        sc = r["scores"]
        # 2x2 の四季
        order = [("金融相場", "春"), ("業績相場", "夏"), ("逆業績相場", "冬"), ("逆金融相場", "秋")]
        cells = ""
        for p, sea in order:
            on = p == ph
            cells += (f"<div class='ph{' on' if on else ''}' style='--c:{PH_COLOR[p]}'>"
                      f"<div class='phn'>{sea}・{p}</div><div class='phd'>{PH_DESC[p]}</div>"
                      f"<div class='phs'>スコア {sc[p]:+.2f}</div></div>")
        ring = (f"<div class='ring'>{cells}<div class='cyc'>春→夏→秋→冬と時計回りに循環</div></div>")
        mt = r["metrics"]
        lv = r["levels"]
        rows = [
            ("株価", lv["株価"], mt["株価 6ヶ月変化(%)"], "%", 2.0),
            ("EPS（業績）", lv["EPS"], mt["EPS 6ヶ月変化(%)"], "%", 1.0),
            ("PER（評価）", lv["PER"], mt["PER 6ヶ月変化(%)"], "%", 2.0),
            ("長期金利", lv["長期金利"], mt["長期金利 6ヶ月変化(%pt)"], "%pt", 0.10),
            ("政策/短期金利", lv["政策/短期金利"], mt["政策/短期金利 6ヶ月変化(%pt)"], "%pt", 0.05),
        ]
        trs = "".join(
            f"<tr><td>{n}</td><td>{v:,.2f}</td><td class='{'pos' if c > 0 else 'neg' if c < 0 else ''}'>{c:+.2f}{u}</td>"
            f"<td class='arr'>{_arrow(c, th)}</td></tr>" for n, v, c, u, th in rows)
        sig = r["signals"]
        lit = sum(s["点灯"] for s in sig)
        sigs = "".join(f"<li class='{'lit' if s['点灯'] else ''}'>{'●' if s['点灯'] else '○'} {s['条件']}</li>" for s in sig)
        h = r["history"].iloc[-24:]
        strip = "".join(
            f"<div class='cell' style='background:{PH_COLOR[p]}' title='{d.strftime('%Y-%m')} {p} 確度{c:.2f}'>"
            f"<span>{d.strftime('%y/%m') if (len(h)-1-i) % 4 == 0 else ''}</span></div>"
            for i, (d, p, c) in enumerate(zip(h.index, h["局面"], h["確度"])))
        leaders = ""
        if sector_results:
            mk = ["us"] if key == "us" else (["jp33"] if "jp33" in sector_results else ["jp17"])
            names = []
            for k2 in mk:
                if k2 in sector_results:
                    t = sector_results[k2]["table"]
                    names += [n for n in t.loc[(t["局面"] == "Leading") | ((t["局面"] == "Improving") & (t["RS-Momentum"] > 102)), "name"]]
            leaders = "、".join(dict.fromkeys(names)) or "（該当なし）"
        stale = (f"<p class='note'>※EPSの最新データは {r['eps_last']} 時点（{r['eps_stale_months']}ヶ月分は横ばい扱い）。"
                 f"{r['eps_note']}</p>")
        cards.append(f"""
<div class='card phcard'>
 <h3>{r['label']} <small>基準日 {r['asof']}</small></h3>
 <div class='phbig' style='--c:{PH_COLOR[ph]}'>{r['season']}・{ph}<small>判定：{conviction_text(r['conviction'])}（確度 {r['conviction']:.2f}）</small></div>
 <div class='phgrid'>
  <div>{ring}</div>
  <div><table class='tbl'><thead><tr><th>指標</th><th>現在値</th><th>6ヶ月変化</th><th>向き</th></tr></thead><tbody>{trs}</tbody></table>
  <p class='note'>典型パターン：{PH_DESC[ph]}</p></div>
 </div>
 <h4>次の局面（{r['next']}）へのサイン：{lit}/{len(sig)} 点灯</h4><ul class='sig'>{sigs}</ul>
 <h4>過去24ヶ月の局面の推移</h4><div class='strip'>{strip}</div>
 <div class='legend'>{''.join(f"<span><i style='background:{PH_COLOR[p]}'></i>{p}</span>" for p in PHASES)}</div>
 <h4>EPSとPERの推移（株価＝EPS×PER）</h4><div style='height:260px'><canvas id='ph_{key}'></canvas></div>
 <h4>業種への示唆</h4>
 <p><b>いまの局面で教科書的に強い業種：</b>{r['typical']}<br>
 <b>次の局面（{r['next']}）で強い業種：</b>{r['typical_next']}<br>
 <b>実際にRRGで勢いが強い業種（先導＋勢いの強い改善）：</b>{leaders}</p>
 {stale}
</div>""")
        mm = r["monthly"].iloc[-36:]
        charts[key] = {"labels": [d.strftime("%Y-%m") for d in mm.index],
                       "eps": [round(float(x), 3) for x in mm["eps"]],
                       "per": [round(float(x), 2) for x in mm["per"]],
                       "stale": r["eps_last"][:7]}
    css = """<style>
.phwrap{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,560px),1fr));gap:12px}
.phcard h3{margin:2px 0 8px;font-size:16px} .phcard h4{margin:14px 0 6px;font-size:13.5px}
.phbig{display:inline-block;background:var(--c);color:#fff;font-weight:700;font-size:20px;padding:6px 14px;border-radius:8px}
.phbig small{display:block;font-size:11.5px;font-weight:normal;color:#fff;margin:0;opacity:.95}
.phgrid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:12px;margin-top:10px}
@media (max-width:640px){.phgrid{grid-template-columns:1fr}}
.ring{display:grid;grid-template-columns:1fr 1fr;gap:6px;position:relative}
.ph{border:2px solid var(--line);border-radius:8px;padding:6px 8px;opacity:.55}
.ph.on{border-color:var(--c);background:color-mix(in srgb,var(--c) 14%,transparent);opacity:1}
.phn{font-weight:700;color:var(--c)} .phd{font-size:11px;color:var(--sub)} .phs{font-size:12px}
.cyc{grid-column:1/3;text-align:center;font-size:11px;color:var(--sub)}
.arr{font-size:16px;text-align:center!important} .phcard .tbl th{position:static}
.sig{list-style:none;padding:0;margin:0} .sig li{padding:2px 0;color:var(--sub)} .sig li.lit{color:var(--lit,var(--neg));font-weight:600}
.strip{display:flex;gap:2px} .strip .cell{flex:1;height:26px;border-radius:3px;position:relative}
.strip .cell span{position:absolute;top:28px;left:0;font-size:10px;color:var(--sub);white-space:nowrap}
.legend{margin-top:20px;font-size:11.5px;color:var(--sub)} .legend span{margin-right:12px} .legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px}
</style>"""
    js = f"""<script>
const PH={json.dumps(charts, ensure_ascii=False)};
for(const [k,d] of Object.entries(PH)){{const el=document.getElementById('ph_'+k);if(!el)continue;
new Chart(el,{{type:'line',data:{{labels:d.labels,datasets:[
{{label:'EPS（業績）',data:d.eps,borderColor:'#e0a12b',backgroundColor:'#e0a12b',yAxisID:'y',pointRadius:0,borderWidth:2,
 segment:{{borderDash:c=>d.labels[c.p0DataIndex]>=d.stale?[4,4]:undefined}}}},
{{label:'PER（評価）',data:d.per,borderColor:'#4a6fa5',backgroundColor:'#4a6fa5',yAxisID:'y1',pointRadius:0,borderWidth:2}}]}},
options:{{animation:false,maintainAspectRatio:false,interaction:{{mode:'index',intersect:false}},
plugins:{{legend:{{position:'top'}}}},scales:{{y:{{position:'left',title:{{display:true,text:'EPS'}}}},
y1:{{position:'right',grid:{{drawOnChartArea:false}},title:{{display:true,text:'PER（倍）'}}}}}}}}}});}}
</script>"""
    intro = ("<p class='note'>相場の四季（浦上邦雄）：株価＝EPS×PER。金利と業績の向きで「金融→業績→逆金融→逆業績」と循環します。"
             "株価・EPS・PER・金利の6ヶ月変化を、各局面の典型パターンと照合してスコア化しています（点線のEPSは未公表期間で横ばい扱い）。</p>")
    return css + "<h2>相場の四季（いまどの局面？）</h2>" + intro + "<div class='phwrap'>" + "".join(cards) + "</div>" + js


def phase_excel(wb, phases):
    from openpyxl.styles import Font, PatternFill, Alignment
    if not phases:
        return
    H = Font(bold=True, color="FFFFFF")
    HF = PatternFill("solid", fgColor="1F3A5F")
    INP = PatternFill("solid", fgColor="FFF4CC")
    ws = wb.create_sheet("相場の四季", 1)
    keys = [k for k in ["us", "jp"] if k in phases]
    cols = {k: 2 + i for i, k in enumerate(keys)}
    L = lambda c: "ABCDEFGH"[c - 1]

    def hdr(row, vals):
        for i, v in enumerate(vals):
            c = ws.cell(row=row, column=1 + i, value=v)
            c.font, c.fill = H, HF
            c.alignment = Alignment(horizontal="center", wrap_text=True)
    ws["A1"] = "相場の四季（金融／業績／逆金融／逆業績）の判定"
    ws["A1"].font = Font(bold=True, size=13)
    ws["A2"] = "黄色セル（スケール・典型パターン）を変えると判定が再計算されます。6ヶ月変化は実行時のデータ。"
    hdr(3, ["指標（6ヶ月変化）"] + [phases[k]["label"] for k in keys])
    mk = ["株価 6ヶ月変化(%)", "EPS 6ヶ月変化(%)", "PER 6ヶ月変化(%)", "長期金利 6ヶ月変化(%pt)", "政策/短期金利 6ヶ月変化(%pt)"]
    for i, m in enumerate(mk):
        ws.cell(row=4 + i, column=1, value=m)
        for k in keys:
            ws.cell(row=4 + i, column=cols[k], value=round(phases[k]["metrics"][m], 4)).number_format = "0.00"
    hdr(10, ["変換スケール", "値"])
    sc = [("株価", SCALE["P"]), ("EPS", SCALE["E"]), ("PER", SCALE["V"]), ("長期金利", SCALE["R_long"]), ("政策金利", SCALE["R_policy"])]
    for i, (n, v) in enumerate(sc):
        ws.cell(row=11 + i, column=1, value=n)
        c = ws.cell(row=11 + i, column=2, value=v)
        c.fill = INP
    hdr(17, ["−1〜+1に変換"] + [phases[k]["label"] for k in keys])
    names = ["株価", "金利", "EPS", "PER"]
    for i, n in enumerate(names):
        ws.cell(row=18 + i, column=1, value=n)
    for k in keys:
        c = L(cols[k])
        ws[f"{c}18"] = f"=TANH({c}4/$B$11)"
        ws[f"{c}19"] = f"=(TANH({c}7/$B$14)+TANH({c}8/$B$15))/2"
        ws[f"{c}20"] = f"=TANH({c}5/$B$12)"
        ws[f"{c}21"] = f"=TANH({c}6/$B$13)"
        for r in range(18, 22):
            ws[f"{c}{r}"].number_format = "0.00"
    hdr(23, ["典型パターン", "株価", "金利", "EPS", "PER"])
    for i, p in enumerate(PHASES):
        ws.cell(row=24 + i, column=1, value=p)
        for j, k2 in enumerate(["P", "R", "E", "V"]):
            c = ws.cell(row=24 + i, column=2 + j, value=TEMPLATE[p][k2])
            c.fill = INP
    hdr(29, ["局面スコア"] + [phases[k]["label"] for k in keys])
    for i, p in enumerate(PHASES):
        r = 30 + i
        ws.cell(row=r, column=1, value=p)
        t = 24 + i
        for k in keys:
            c = L(cols[k])
            ws[f"{c}{r}"] = (f"=($B{t}*{c}$18+$C{t}*{c}$19+$D{t}*{c}$20+$E{t}*{c}$21)"
                             f"/(ABS($B{t})+ABS($C{t})+ABS($D{t})+ABS($E{t}))")
            ws[f"{c}{r}"].number_format = "+0.00;-0.00"
    ws["A35"] = "判定"
    ws["A36"] = "確度（1位−2位）"
    ws["A35"].font = ws["A36"].font = Font(bold=True)
    for k in keys:
        c = L(cols[k])
        ws[f"{c}35"] = f"=INDEX($A$30:$A$33,MATCH(MAX({c}30:{c}33),{c}30:{c}33,0))"
        ws[f"{c}35"].font = Font(bold=True, size=12)
        ws[f"{c}36"] = f"=LARGE({c}30:{c}33,1)-LARGE({c}30:{c}33,2)"
        ws[f"{c}36"].number_format = "0.00"
    ws["A38"] = "局面の典型パターン"
    ws["A38"].font = Font(bold=True)
    for i, p in enumerate(PHASES):
        ws.cell(row=39 + i, column=1, value=p)
        ws.cell(row=39 + i, column=2, value=PH_DESC[p])
        ws.cell(row=39 + i, column=4, value="強い業種の目安：" + TYPICAL[p])
    ws.column_dimensions["A"].width = 30
    for c in "BCDE":
        ws.column_dimensions[c].width = 16

    # 推移
    hs = wb.create_sheet("相場の四季_推移", 2)
    hs["A1"] = "月次の推移（EPSの点線部分＝未公表期間は横ばい扱い）"
    row = 3
    for k in keys:
        r = phases[k]
        h = r["history"].join(r["monthly"][["price", "eps", "per", "r_long", "r_policy"]])
        hs.cell(row=row, column=1, value=r["label"]).font = Font(bold=True)
        row += 1
        heads = ["月", "株価", "EPS", "PER", "長期金利", "政策/短期金利", "株価6M%", "EPS6M%", "PER6M%",
                 "長期金利6M", "政策金利6M"] + PHASES + ["判定", "確度"]
        for j, v in enumerate(heads):
            c = hs.cell(row=row, column=1 + j, value=v)
            c.font, c.fill = H, HF
        row += 1
        for d, x in h.iloc[::-1].iterrows():
            vals = [d.strftime("%Y-%m"), x["price"], x["eps"], x["per"], x["r_long"], x["r_policy"],
                    x["P"], x["E"], x["V"], x["R_long"], x["R_policy"]] + [x[p] for p in PHASES] + [x["局面"], x["確度"]]
            for j, v in enumerate(vals):
                c = hs.cell(row=row, column=1 + j, value=(float(v) if isinstance(v, (float, np.floating)) else v))
                if j >= 1 and j != 15:
                    c.number_format = "0.00"
            fill = PatternFill("solid", fgColor=PH_COLOR[x["局面"]].lstrip("#"))
            hs.cell(row=row, column=16).fill = fill
            hs.cell(row=row, column=16).font = Font(color="FFFFFF", bold=True)
            row += 1
        row += 2
    hs.column_dimensions["A"].width = 10
