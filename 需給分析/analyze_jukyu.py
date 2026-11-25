"""需給分析：蓄積したデータと株価CSVから、銘柄ごと・業種ごと・市場全体の需給指標を作る（通信なし）。

出力
  fundamentals/jukyu.csv                 銘柄ごとの需給指標（ファンダメンタル分析のスコア一覧に結合）
  需給分析/output/需給分析_YYYY-MM-DD.xlsx  Excel（読み方・銘柄一覧・候補・業種別・市場全体・投資部門別…）
  data/charts/jukyu.html ・ jukyu_summary.json ・ jukyu/<コード>.json   ダッシュボード（report_jukyu.py）
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

DIR = Path(__file__).resolve().parent
BASE = DIR.parent
DATA = DIR / "data"
OUT = DIR / "output"
PRICES = BASE / "data" / "prices"
SECTORS = BASE / "tickers" / "sectors.csv"
TICKERS = BASE / "tickers" / "tse_tickers.csv"
TOPIX = BASE / "株価指数" / "data" / "topix.csv"
JUKYU_CSV = BASE / "fundamentals" / "jukyu.csv"

# fundamentals/jukyu.csv の列（analyze_fundamentals.py の JUKYU_COLS と同じ並び）
JUKYU_COLS = [
    "信用買残(株)", "信用売残(株)", "信用倍率(倍)", "買残前日比(株)", "売残前日比(株)",
    "買残5日変化(%)", "買残20日変化(%)", "売残5日変化(%)", "売残20日変化(%)",
    "買残上場比(%)", "売残上場比(%)", "買残回転日数(日)", "売残回転日数(日)", "一般信用買残比率(%)",
    "信用買い評価損益率(%)", "信用売り評価損益率(%)",
    "貸借倍率(倍)", "日証金差引(株)", "逆日歩(円)", "逆日歩(年率%)",
    "大口空売り比率(%)", "大口空売り報告数", "大口空売り30日変化(%pt)",
    "出来高(株)", "出来高倍率(当日/25日)", "売買代金25日平均(百万円)",
    "価格帯別出来高最多価格(円)", "最多価格帯からの乖離(%)", "上値出来高比率(%)",
    "信用区分", "規制等", "信用残の申込日", "需給スコア", "需給判定", "需給メモ",
]


def log(*a):
    print(f"[{datetime.now():%H:%M:%S}]", *a, flush=True)


def _csvs(sub: str) -> list[Path]:
    return sorted((DATA / sub).glob("????-??-??.csv"))


def read(path: Path, **kw) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8-sig", dtype={"コード": str}, **kw)


# ------------------------------------------------------------ 読み込み

def load_margin() -> pd.DataFrame:
    rows = []
    for f in _csvs("margin"):
        d = read(f)
        d.insert(0, "申込日", pd.Timestamp(f.stem))
        rows.append(d)
    if not rows:
        raise SystemExit("信用残のデータがありません。先に fetch_jukyu.py を実行してください。")
    m = pd.concat(rows, ignore_index=True)
    return adjust_splits(m)


SHARE_COLS = ["売残", "売残前日比", "買残", "買残前日比", "売残一般", "売残一般前日比", "売残制度", "売残制度前日比",
              "買残一般", "買残一般前日比", "買残制度", "買残制度前日比"]


def adjust_splits(m: pd.DataFrame) -> pd.DataFrame:
    """株式分割・併合の前の信用残（株数）を、いまの株数ベースにそろえる。
    株価CSVは分割調整済みなので、そろえないと時価や増減率が分割日にとぶ（金額＝約定代金はそのまま）。
    台帳は株価CSVと同じ data/splits.csv（fix_splits.py・backfill_splits.py が作る）。"""
    sys.path.insert(0, str(BASE))
    try:
        from splits_util import ledger
        led = ledger()
    except Exception as e:
        log(f"※ 分割の台帳を読めないため、信用残の分割調整をしません: {e}")
        return m
    first = m["申込日"].min()
    n = 0
    for code, evs in led.items():
        for ex, ratio in evs:
            exd = pd.Timestamp(ex)
            if exd <= first:
                continue
            sel = (m["コード"] == code) & (m["申込日"] < exd)
            if sel.any():
                cols = [c for c in SHARE_COLS if c in m.columns]
                m.loc[sel, cols] = m.loc[sel, cols] * ratio
                n += 1
    if n:
        log(f"信用残の分割調整: {n}件")
    return m


def load_prices(codes, days=300) -> dict[str, pd.DataFrame]:
    out = {}
    for c in codes:
        f = PRICES / f"{c}.csv"
        if not f.exists():
            continue
        try:
            p = pd.read_csv(f, parse_dates=["date"]).dropna(subset=["close"]).tail(days)
        except Exception:
            continue
        if len(p) >= 30:
            out[c] = p.set_index("date")
    return out


def load_short_positions() -> pd.DataFrame:
    fs = _csvs("short_positions")
    if not fs:
        return pd.DataFrame()
    rows = []
    for f in fs:
        d = read(f, parse_dates=["計算日", "前回計算日"])
        d["公表日"] = pd.Timestamp(f.stem)
        rows.append(d)
    d = pd.concat(rows, ignore_index=True)
    for c in ("委託者", "ファンド"):
        d[c] = d[c].fillna("")
    return d


def short_balance(sp: pd.DataFrame, asof: pd.Timestamp) -> pd.DataFrame:
    """asof 時点で分かっている、報告者（＋委託者・ファンド）ごとの最新の空売り残高割合。
    0.5%を下回った報告（割合が0.5%未満）以降は残高が分からないので、0.5%以上だけを数える。"""
    if sp.empty:
        return pd.DataFrame(columns=["コード", "大口空売り比率(%)", "大口空売り報告数"])
    s = sp[sp["計算日"] <= asof].sort_values(["計算日", "公表日"])
    s = s.drop_duplicates(["コード", "報告者", "委託者", "ファンド"], keep="last")
    s = s[s["残高割合"] >= 0.005]
    g = s.groupby("コード").agg(**{"大口空売り比率(%)": ("残高割合", lambda v: v.sum() * 100),
                                   "大口空売り報告数": ("残高割合", "size")})
    return g.reset_index()


# ------------------------------------------------------------ 株価・出来高の指標

def price_metrics(p: pd.DataFrame) -> dict:
    c, v = p["close"], p["volume"].fillna(0)
    last = p.index[-1]
    v25 = v.iloc[-26:-1].mean()             # 当日を除く25日平均
    tv = (c * v)
    r = {"終値": c.iat[-1], "株価日付": last,
         "出来高(株)": v.iat[-1],
         "出来高倍率(当日/25日)": v.iat[-1] / v25 if v25 > 0 else np.nan,
         "出来高25日平均": v.iloc[-25:].mean(),
         "売買代金(百万円)": tv.iat[-1] / 1e6,
         "売買代金25日平均(百万円)": tv.iloc[-25:].mean() / 1e6,
         "25日線乖離(%)": (c.iat[-1] / c.iloc[-25:].mean() - 1) * 100,
         "20日騰落率(%)": (c.iat[-1] / c.iat[-21] - 1) * 100 if len(c) > 21 else np.nan,
         "5日騰落率(%)": (c.iat[-1] / c.iat[-6] - 1) * 100 if len(c) > 6 else np.nan}
    # 価格帯別出来高（直近60営業日、20本）：典型価格 (H+L+C)/3 の帯に出来高を積む
    q = p.iloc[-60:]
    lo, hi = q["low"].min(), q["high"].max()
    if hi > lo:
        edges = np.linspace(lo, hi, 21)
        tp = (q["high"] + q["low"] + q["close"]) / 3
        hist, _ = np.histogram(tp, bins=edges, weights=q["volume"].fillna(0))
        k = int(hist.argmax())
        poc = (edges[k] + edges[k + 1]) / 2
        tot = hist.sum()
        above = hist[(edges[:-1] + edges[1:]) / 2 > c.iat[-1]].sum()
        r.update({"価格帯別出来高最多価格(円)": poc,
                  "最多価格帯からの乖離(%)": (c.iat[-1] / poc - 1) * 100,
                  "上値出来高比率(%)": above / tot * 100 if tot > 0 else np.nan,
                  "_vp": {"lo": float(lo), "hi": float(hi), "h": [float(x) for x in hist]}})
    return r


def close_on(p: pd.DataFrame, day: pd.Timestamp):
    s = p["close"].loc[:day]
    return s.iat[-1] if len(s) else np.nan


# ------------------------------------------------------------ 需給スコア

def score_row(r: pd.Series) -> tuple[float, str, str]:
    """0〜100（50が中立）。どれも「上値の重さ・軽さ」と「買い戻し（踏み上げ）の燃料」を見る経験則で、
    過去データでの検証はまだ（信用残の日次データは取得開始から貯まる）。内訳は需給メモに書く。"""
    s, memo = 50.0, []

    def add(x, why):
        nonlocal s
        s += x
        memo.append(f"{why}{x:+.0f}")

    ratio, buy_days = r.get("信用倍率(倍)"), r.get("買残回転日数(日)")
    sell_days = r.get("売残回転日数(日)")
    if pd.notna(ratio):
        if ratio < 1:
            add(8, "売り長")
        elif ratio < 2:
            add(4, "倍率低め")
        elif ratio >= 20:
            add(-10, "倍率20倍超")
        elif ratio >= 8:
            add(-5, "倍率高め")
    if pd.notna(buy_days):
        if buy_days >= 15:
            add(-10, "買残が出来高15日分超")
        elif buy_days >= 7:
            add(-5, "買残が出来高7日分超")
        elif buy_days < 2:
            add(3, "買残軽い")
    if pd.notna(sell_days) and sell_days >= 3:
        add(6 if sell_days >= 7 else 3, "売残が厚い")
    pl = r.get("信用買い評価損益率(%)")
    if pd.notna(pl) and r.get("信用買残(株)", 0) > 0:
        if pl <= -20:
            add(-8, "買い方の含み損大")
        elif pl <= -10:
            add(-4, "買い方の含み損")
        elif pl >= 5:
            add(3, "買い方に含み益")
    ch5, px5 = r.get("買残5日変化(%)"), r.get("5日騰落率(%)")
    if pd.notna(ch5) and pd.notna(px5):
        if ch5 >= 10 and px5 < 0:
            add(-5, "下げで買残増")
        elif ch5 <= -10 and px5 > 0:
            add(5, "上げで買残減（整理進む）")
    if pd.notna(r.get("逆日歩(円)")) and r["逆日歩(円)"] > 0:
        add(6, "逆日歩")
    lb = r.get("貸借倍率(倍)")
    if pd.notna(lb) and lb < 1:
        add(3, "日証金で貸株超過")
    spr = r.get("大口空売り比率(%)")
    if pd.notna(spr) and spr >= 2:
        # 2026-10-10 に符号を反転（旧: +3「積み上がり＝踏み上げの燃料」）。2025-10〜2026-09 の検証で、
        # 大口空売りが多い銘柄はその後に負けやすかった（順位相関 −0.01〜−0.04、2%以上のフラグも同じ向き）。
        # 詳細は ~/株分析/平均回帰実装_第3章_20261010/README_平均回帰実装.md の検証2-1
        add(-3, "大口の空売りが多い（売り方優勢）")
    up = r.get("上値出来高比率(%)")
    if pd.notna(up):
        if up >= 60:
            add(-5, "上値にしこり")
        elif up <= 15:
            add(4, "上値が軽い")
    vr, px1 = r.get("出来高倍率(当日/25日)"), r.get("25日線乖離(%)")
    if pd.notna(vr) and vr >= 2 and pd.notna(px1) and px1 > 0:
        add(3, "出来高を伴う上昇")
    s = float(np.clip(s, 0, 100))

    flags = str(r.get("規制等") or "")
    squeeze = (pd.notna(ratio) and ratio < 1.5 and pd.notna(sell_days) and sell_days >= 2
               and ((pd.notna(r.get("逆日歩(円)")) and r["逆日歩(円)"] > 0) or (pd.notna(spr) and spr >= 1))
               and pd.notna(px1) and px1 > 0
               and not (pd.notna(buy_days) and buy_days >= 10) and s >= 55)   # 買い方が重い銘柄は除く
    if any(ch in flags for ch in "規日○"):
        verdict = "規制・注意"
    elif squeeze:
        verdict = "踏み上げ候補"
    elif s >= 65:
        verdict = "好需給"
    elif pd.notna(ratio) and ratio >= 8 and pd.notna(buy_days) and buy_days >= 7:
        verdict = "買残重い"
    elif pd.notna(pl) and pl <= -20 and pd.notna(buy_days) and buy_days >= 5:
        verdict = "投げ警戒"
    elif s <= 35:
        verdict = "需給悪い"
    else:
        verdict = "中立"
    return s, verdict, "・".join(memo)


# ------------------------------------------------------------ 本体

def build():
    m = load_margin()
    days = sorted(m["申込日"].unique())
    M = pd.Timestamp(days[-1])
    log(f"信用残: {len(days)}日分（{pd.Timestamp(days[0]).date()}〜{M.date()}）")
    cur = m[m["申込日"] == M].set_index("コード")

    tick = pd.read_csv(TICKERS, dtype=str, encoding="utf-8-sig")
    sec = pd.read_csv(SECTORS, dtype=str, encoding="utf-8-sig")
    names = dict(zip(sec["code"], sec["name"])) | dict(zip(tick["code"], tick["name"]))
    market = dict(zip(tick["code"], tick["market"]))
    sector = dict(zip(sec["code"], sec["sector33"]))

    codes = [c for c in tick["code"] if c in cur.index]   # 普通株（ETF等は除く）
    px = load_prices(codes)
    log(f"株価CSV: {len(px):,}銘柄")

    # 信用残の時系列（コード×申込日）
    piv_b = m.pivot_table(index="申込日", columns="コード", values="買残", aggfunc="last")
    piv_s = m.pivot_table(index="申込日", columns="コード", values="売残", aggfunc="last")

    def chg(piv, c, n):
        if c not in piv.columns or len(piv) <= n:
            return np.nan
        a, b = piv[c].iat[-1], piv[c].iat[-1 - n]
        return (a / b - 1) * 100 if pd.notna(b) and b > 0 and pd.notna(a) else np.nan

    def diff(piv, c, n):
        """n営業日前からの増減（株数）。ランキングの週次（5日）・月次（20日）用"""
        if c not in piv.columns or len(piv) <= n:
            return np.nan
        a, b = piv[c].iat[-1], piv[c].iat[-1 - n]
        return a - b if pd.notna(a) and pd.notna(b) else np.nan

    tz = _latest("taisyaku")
    sh = _latest("shina")
    fl = read(DATA / "flags.csv") if (DATA / "flags.csv").exists() else pd.DataFrame(columns=["コード", "規制等"])
    flags = dict(zip(fl["コード"], fl["規制等"].fillna("")))
    sp = load_short_positions()
    sb_now = short_balance(sp, M + timedelta(days=7)).set_index("コード")
    sb_old = short_balance(sp, M - timedelta(days=30)).set_index("コード")

    recs, vps = [], {}
    for c in codes:
        r = cur.loc[c]
        rec = {"コード": c, "銘柄名": names.get(c, ""), "市場": market.get(c, ""), "業種": sector.get(c, "")}
        b, s_ = r.get("買残"), r.get("売残")
        rec["信用買残(株)"], rec["信用売残(株)"] = b, s_
        rec["信用倍率(倍)"] = b / s_ if pd.notna(s_) and s_ > 0 else np.nan
        rec["買残前日比(株)"], rec["売残前日比(株)"] = r.get("買残前日比"), r.get("売残前日比")
        # 前日分が手元にあれば、分割調整後の差で置き換える（分割日の前日比がとばないように）
        if len(piv_b) >= 2 and c in piv_b.columns and pd.notna(piv_b[c].iat[-2]):
            rec["買残前日比(株)"] = piv_b[c].iat[-1] - piv_b[c].iat[-2]
            if pd.notna(piv_s[c].iat[-2]):
                rec["売残前日比(株)"] = piv_s[c].iat[-1] - piv_s[c].iat[-2]
        rec["買残5日変化(%)"], rec["買残20日変化(%)"] = chg(piv_b, c, 5), chg(piv_b, c, 20)
        rec["売残5日変化(%)"], rec["売残20日変化(%)"] = chg(piv_s, c, 5), chg(piv_s, c, 20)
        rec["買残5日差(株)"], rec["買残20日差(株)"] = diff(piv_b, c, 5), diff(piv_b, c, 20)
        rec["売残5日差(株)"], rec["売残20日差(株)"] = diff(piv_s, c, 5), diff(piv_s, c, 20)
        rec["買残上場比(%)"] = r.get("買残上場比") * 100 if pd.notna(r.get("買残上場比")) else np.nan
        rec["売残上場比(%)"] = r.get("売残上場比") * 100 if pd.notna(r.get("売残上場比")) else np.nan
        rec["一般信用買残比率(%)"] = r.get("買残一般") / b * 100 if pd.notna(b) and b > 0 else np.nan
        rec["信用区分"] = r.get("区分")
        rec["規制等"] = flags.get(c, "")
        rec["信用残の申込日"] = M.date().isoformat()
        rec["買残金額"], rec["売残金額"] = r.get("買残金額"), r.get("売残金額")
        p = px.get(c)
        if p is not None:
            pm = price_metrics(p)
            vp = pm.pop("_vp", None)
            if vp:
                vps[c] = vp
            rec.update(pm)
            v25 = pm["出来高25日平均"]
            rec["買残回転日数(日)"] = b / v25 if v25 and v25 > 0 and pd.notna(b) else np.nan
            rec["売残回転日数(日)"] = s_ / v25 if v25 and v25 > 0 and pd.notna(s_) else np.nan
            cm = close_on(p, M)
            if pd.notna(r.get("買残金額")) and r.get("買残金額") > 0 and b > 0:
                rec["信用買い評価損益率(%)"] = (b * cm / r["買残金額"] - 1) * 100
            if pd.notna(r.get("売残金額")) and r.get("売残金額") > 0 and s_ > 0:
                rec["信用売り評価損益率(%)"] = (1 - s_ * cm / r["売残金額"]) * 100
            rec["_close_M"] = cm
        if c in tz.index:
            t = tz.loc[c]
            rec["貸借倍率(倍)"] = t["融資残"] / t["貸株残"] if t["貸株残"] > 0 else np.nan
            rec["日証金差引(株)"] = t["差引残"]
            rec["日証金融資残(株)"], rec["日証金貸株残(株)"] = t["融資残"], t["貸株残"]
        if c in sh.index:
            rec["逆日歩(円)"] = sh.loc[c, "逆日歩"]
            rec["逆日歩(年率%)"] = sh.loc[c, "逆日歩(%)"] * 365 if pd.notna(sh.loc[c, "逆日歩(%)"]) else np.nan
        if c in sb_now.index:
            rec["大口空売り比率(%)"] = sb_now.loc[c, "大口空売り比率(%)"]
            rec["大口空売り報告数"] = sb_now.loc[c, "大口空売り報告数"]
            rec["大口空売り30日変化(%pt)"] = rec["大口空売り比率(%)"] - (
                sb_old.loc[c, "大口空売り比率(%)"] if c in sb_old.index else 0)
        recs.append(rec)
    d = pd.DataFrame(recs)
    sc = d.apply(score_row, axis=1, result_type="expand")
    d["需給スコア"], d["需給判定"], d["需給メモ"] = sc[0], sc[1], sc[2]
    log("需給判定: " + "・".join(f"{k} {v}" for k, v in d["需給判定"].value_counts().items()))
    return d, m, days, px, vps, sp


def _latest(sub: str) -> pd.DataFrame:
    fs = _csvs(sub)
    if not fs:
        return pd.DataFrame().set_index(pd.Index([], name="コード"))
    return read(fs[-1]).drop_duplicates("コード").set_index("コード")


# ------------------------------------------------------------ 業種・市場全体

def sector_table(d: pd.DataFrame, ss: pd.DataFrame) -> pd.DataFrame:
    x = d[d["業種"].fillna("") != ""].copy()
    x["買残時価"] = x["信用買残(株)"] * x["_close_M"]
    x["売残時価"] = x["信用売残(株)"] * x["_close_M"]
    x["買残前日時価"] = (x["信用買残(株)"] - x["買残前日比(株)"]) * x["_close_M"]
    g = x.groupby("業種").agg(銘柄数=("コード", "size"), 買残時価=("買残時価", "sum"), 売残時価=("売残時価", "sum"),
                             買残前日時価=("買残前日時価", "sum"), 買残金額=("買残金額", "sum"),
                             需給スコア中央値=("需給スコア", "median"))
    t = pd.DataFrame({"銘柄数": g["銘柄数"],
                      "買残(億円)": g["買残時価"] / 1e8, "売残(億円)": g["売残時価"] / 1e8,
                      "信用倍率(倍)": g["買残時価"] / g["売残時価"].replace(0, np.nan),
                      "買残前日比(%)": (g["買残時価"] / g["買残前日時価"] - 1) * 100,
                      "信用買い評価損益率(%)": (g["買残時価"] / g["買残金額"] - 1) * 100,
                      "需給スコア中央値": g["需給スコア中央値"]})
    if not ss.empty:
        ss = ss.copy()
        ss["日付"] = pd.to_datetime(ss["日付"])
        lastd = ss["日付"].max()
        cur = ss[ss["日付"] == lastd].set_index("業種")["空売り比率(%)"]
        recent = ss[ss["日付"] > lastd - timedelta(days=30)].groupby("業種")["空売り比率(%)"].mean()
        year = ss[ss["日付"] > lastd - timedelta(days=365)].groupby("業種")["空売り比率(%)"].mean()
        t["空売り比率(%)"] = t.index.map(cur)
        t["空売り比率20日平均(%)"] = t.index.map(recent)
        t["空売り比率1年平均(%)"] = t.index.map(year)
    return t.sort_values("信用倍率(倍)")


def market_series(m: pd.DataFrame, px: dict, d: pd.DataFrame) -> pd.DataFrame:
    """日ごとの市場全体（普通株）：買残・売残（時価・億円）、信用倍率、信用買い評価損益率"""
    common = set(d["コード"])
    out = []
    for day, g in m[m["コード"].isin(common)].groupby("申込日"):
        cl = g["コード"].map(lambda c: close_on(px[c], day) if c in px else np.nan)
        ok = cl.notna()
        bv = (g["買残"] * cl)[ok].sum()
        sv = (g["売残"] * cl)[ok].sum()
        out.append({"申込日": pd.Timestamp(day).date().isoformat(), "買残(億円)": bv / 1e8, "売残(億円)": sv / 1e8,
                    "信用倍率(倍)": bv / sv if sv else np.nan,
                    "買残(百万株)": g["買残"].sum() / 1e6, "売残(百万株)": g["売残"].sum() / 1e6,
                    "信用買い評価損益率(%)": (bv / g.loc[ok, "買残金額"].sum() - 1) * 100,
                    "信用売り評価損益率(%)": (1 - sv / g.loc[ok, "売残金額"].sum()) * 100})
    return pd.DataFrame(out)


def load_opt(name: str) -> pd.DataFrame:
    f = DATA / name
    return pd.read_csv(f, encoding="utf-8-sig") if f.exists() else pd.DataFrame()


# ------------------------------------------------------------ 出力

GUIDE = [
    ("信用買残・信用売残", "信用取引で買って（売って）まだ決済していない株数。買残は将来の売り、売残は将来の買い戻しになる。"
                         "JPXが毎営業日、前営業日申込分を全銘柄で公表（2026年から日々公表）。"),
    ("信用倍率", "買残÷売残。1倍未満は「売り長」で、上がると買い戻しが入りやすい（踏み上げ）。"
               "10倍・20倍と高いほど、上値で戻り売りが出やすい。売残0のときは空欄。"),
    ("買残回転日数", "買残÷25日平均出来高。何日分の出来高に相当する買残が残っているか。7日超は上値が重くなりやすい。"),
    ("信用買い評価損益率", "買残の時価÷約定金額−1。JPXの金額は約定代金なので、買い方の平均的な含み損益が分かる。"
                       "−20%前後は追証・投げが出やすい水準（市場全体では底のサインとして有名）。"),
    ("貸借倍率・逆日歩", "日本証券金融（日証金）の融資残÷貸株残。1倍未満は株不足で、逆日歩（品貸料）が付くと"
                     "売り方にコストがかかり買い戻しを急がせる。"),
    ("大口空売り比率", "JPXの「空売り残高に関する情報」で、発行済株式の0.5%以上の空売りを報告した機関の割合の合計"
                    "（報告者ごとの最新値。0.5%を下回った後は分からないので数えない）。2%以上は需給スコアで −3"
                    "（過去1年の検証で、多い銘柄ほどその後に負けやすかったため。踏み上げの燃料とはみなさない）。"),
    ("出来高・価格帯別出来高", "出来高倍率＝当日÷25日平均。価格帯別出来高は直近60日の出来高を20の価格帯に積んだもの。"
                          "上値出来高比率が高いほど、上に「しこり」（高値で買って戻りを待つ人）が多い。"),
    ("空売り比率", "東証の売買代金のうち空売りの割合（JPX空売り集計）。40%超が続くと売り方が積み上がり、反発時に買い戻しが出やすい。"),
    ("投資部門別売買状況", "海外投資家・個人・信託銀行（年金）・投資信託・事業法人（自社株買い）などの買い越し・売り越し（週次・億円）。"),
    ("需給スコア", "上の指標を足し引きした0〜100（50が中立）。内訳は「需給メモ」。経験則による目安で、"
                "信用残の日次データが貯まり次第、検証して重みを見直す。投資判断はご自身で。"),
]


def write_excel(path: Path, d, sector, mk, mkw, smk, inv, sp_top) -> None:
    show = ["コード", "銘柄名", "市場", "業種", "終値", "需給判定", "需給スコア"] + \
        [c for c in JUKYU_COLS if c not in ("需給スコア", "需給判定")] + \
        ["売買代金(百万円)", "5日騰落率(%)", "20日騰落率(%)", "25日線乖離(%)"]
    show = [c for c in show if c in d.columns]
    base = d.sort_values("需給スコア", ascending=False)[show]
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        pd.DataFrame(GUIDE, columns=["指標", "読み方"]).to_excel(xw, sheet_name="読み方", index=False)
        base.to_excel(xw, sheet_name="銘柄一覧", index=False)
        for name in ("踏み上げ候補", "好需給", "買残重い", "投げ警戒", "規制・注意"):
            base[base["需給判定"] == name].to_excel(xw, sheet_name=name, index=False)
        base.sort_values("買残5日変化(%)", ascending=False).dropna(subset=["買残5日変化(%)"]).head(200) \
            .to_excel(xw, sheet_name="買残急増", index=False)
        base[base["出来高倍率(当日/25日)"] >= 3].sort_values("出来高倍率(当日/25日)", ascending=False) \
            .to_excel(xw, sheet_name="出来高急増", index=False)
        sector.reset_index().to_excel(xw, sheet_name="業種別", index=False)
        if not mk.empty:
            mk.to_excel(xw, sheet_name="市場の信用残(日次)", index=False)
        if not mkw.empty:
            mkw.to_excel(xw, sheet_name="市場の信用残(週次)", index=False)
        if not smk.empty:
            smk.to_excel(xw, sheet_name="空売り比率", index=False)
        if not inv.empty:
            inv.to_excel(xw, sheet_name="投資部門別(億円)", index=False)
        if not sp_top.empty:
            sp_top.to_excel(xw, sheet_name="大口空売り", index=False)
        for ws in xw.book.worksheets:
            ws.freeze_panes = "C2" if ws.title in ("銘柄一覧",) else "A2"
            for col in ws.columns:
                w = max(len(str(c.value or "")) for c in list(col)[:50])
                ws.column_dimensions[col[0].column_letter].width = min(max(8, w * 1.3), 60)


def main() -> int:
    d, m, days, px, vps, sp = build()
    OUT.mkdir(parents=True, exist_ok=True)
    M = pd.Timestamp(days[-1])

    # 1) fundamentals/jukyu.csv
    cols = ["コード"] + [c for c in JUKYU_COLS if c in d.columns]
    d[cols].to_csv(JUKYU_CSV, index=False, encoding="utf-8-sig")
    log(f"{JUKYU_CSV.relative_to(BASE)}: {len(d):,}銘柄")

    # 2) 業種・市場
    ss = load_opt("short_sector.csv")
    sector = sector_table(d, ss)
    mk = market_series(m, px, d)
    # 市場全体の日次系列は、その日に計算した値を data/market_daily.csv に残して以後は書き換えない
    # （株価CSVは配当・分割で過去の値が調整されるため、毎回計算し直すと過去の評価損益率が少しずつ動く）
    mfile = DATA / "market_daily.csv"
    if mfile.exists() and not mk.empty:
        old = pd.read_csv(mfile, encoding="utf-8-sig", dtype={"申込日": str})
        mk = pd.concat([old, mk[~mk["申込日"].isin(old["申込日"])]]).sort_values("申込日")
    if not mk.empty:
        mk.to_csv(mfile, index=False, encoding="utf-8-sig")
    mkw = load_opt("margin_market_weekly.csv")
    smk = load_opt("short_market.csv")
    inv = load_opt("investor_weekly.csv")
    if not inv.empty:
        for c in inv.columns:
            if c not in ("週末", "市場"):
                inv[c] = inv[c] / 1e5        # 千円 → 億円
        inv = inv.sort_values(["週末", "市場"])
    sp_top = pd.DataFrame()
    if not sp.empty:
        s = sp.sort_values(["計算日", "公表日"]).drop_duplicates(["コード", "報告者", "委託者", "ファンド"], keep="last")
        s = s[s["残高割合"] >= 0.005].copy()
        s["銘柄名"] = s["コード"].map(dict(zip(d["コード"], d["銘柄名"])))
        s["残高割合(%)"] = s["残高割合"] * 100
        s["前回残高割合(%)"] = s["前回残高割合"] * 100
        sp_top = s.sort_values("残高割合", ascending=False)[
            ["コード", "銘柄名", "報告者", "委託者", "ファンド", "残高割合(%)", "残高数量", "計算日", "前回残高割合(%)"]]

    xlsx = OUT / f"需給分析_{date.today():%Y-%m-%d}.xlsx"
    write_excel(xlsx, d, sector, mk, mkw, smk, inv, sp_top)
    log(f"Excel: {xlsx.relative_to(BASE)}")

    # 3) ダッシュボード
    import report_jukyu
    report_jukyu.write_all(d=d, m=m, days=days, px=px, vps=vps, sp=sp, sector=sector, mk=mk, mkw=mkw,
                           smk=smk, ss=ss, inv=inv, sp_top=sp_top, M=M)
    return 0


if __name__ == "__main__":
    sys.exit(main())
