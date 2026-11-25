"""需給分析ダッシュボード（data/charts/jukyu.html）と、銘柄ごとのデータ（data/charts/jukyu/<コード>.js）、
トップ画面のカード用の要約（data/charts/jukyu_summary.json）を書く。analyze_jukyu.py から呼ばれる。

銘柄ごとのデータは <script> で読む（file:// で開いても動くように。sig/<コード>.js と同じ方式）。
ページ本体（HTML・JS）は jukyu_page.html、見た目（CSS）は jukyu_style.css にあり、/*CSS*/ /*DATA*/ などを差し込む。"""
from __future__ import annotations

import html
import json
import math
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

DIR = Path(__file__).resolve().parent
SITE = DIR.parent / "data" / "charts"
TEMPLATE = DIR / "jukyu_page.html"

CSS = (DIR / "jukyu_style.css").read_text(encoding="utf-8")   # 見た目はこのファイル


def _e(s) -> str:
    return html.escape("" if s is None else str(s))


def _c(v, nd=2):
    """JSONに入れる値（NaN→None、小数を丸める）"""
    if v is None:
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        if math.isnan(v) or math.isinf(v):
            return None
        return round(float(v), nd) if nd else int(round(float(v)))
    if isinstance(v, (pd.Timestamp, datetime)):
        return v.strftime("%Y-%m-%d")
    return v


LIST_FIELDS = [
    ("コード", 0), ("銘柄名", 0), ("市場", 0), ("業種", 0), ("終値", 1), ("需給判定", 0), ("需給スコア", 0),
    ("信用買残(株)", 0), ("信用売残(株)", 0), ("信用倍率(倍)", 2), ("買残前日比(株)", 0), ("買残5日変化(%)", 1),
    ("買残回転日数(日)", 1), ("売残回転日数(日)", 2), ("信用買い評価損益率(%)", 1), ("貸借倍率(倍)", 2),
    ("逆日歩(円)", 2), ("大口空売り比率(%)", 2), ("出来高倍率(当日/25日)", 2), ("売買代金25日平均(百万円)", 0),
    ("上値出来高比率(%)", 0), ("規制等", 0), ("需給メモ", 0), ("信用区分", 0), ("5日騰落率(%)", 1),
    ("20日騰落率(%)", 1), ("買残上場比(%)", 2), ("売残前日比(株)", 0), ("大口空売り報告数", 0),
    ("信用売り評価損益率(%)", 1), ("逆日歩(年率%)", 1), ("日証金差引(株)", 0), ("大口空売り30日変化(%pt)", 2),
    ("一般信用買残比率(%)", 0), ("価格帯別出来高最多価格(円)", 1), ("最多価格帯からの乖離(%)", 1),
    ("出来高(株)", 0), ("売残上場比(%)", 2),
    ("買残5日差(株)", 0), ("売残5日差(株)", 0), ("買残20日差(株)", 0), ("売残20日差(株)", 0),
]


def stock_files(d, m, px, vps, sp) -> int:
    """銘柄ごとのデータ jukyu/<コード>.js"""
    out = SITE / "jukyu"
    out.mkdir(parents=True, exist_ok=True)
    mm = m.sort_values("申込日")
    groups = {c: g for c, g in mm.groupby("コード")}
    holders = {}
    if not sp.empty:
        s = sp.sort_values(["計算日", "公表日"]).drop_duplicates(["コード", "報告者", "委託者", "ファンド"], keep="last")
        s = s[s["残高割合"] >= 0.005]
        for c, g in s.groupby("コード"):
            g = g.sort_values("残高割合", ascending=False)
            holders[c] = [[r.報告者 + (f"（{r.ファンド}）" if r.ファンド else ""), _c(r.残高割合 * 100, 2),
                           _c(r.計算日), _c(r.前回残高割合 * 100 if pd.notna(r.前回残高割合) else None, 2)]
                          for r in g.itertuples()][:15]
    n = 0
    for c in d["コード"]:
        g = groups.get(c)
        p = px.get(c)
        obj = {"code": c}
        if g is not None:
            obj["m"] = {"d": [x.strftime("%Y-%m-%d") for x in g["申込日"]],
                        "b": [_c(x, 0) for x in g["買残"]], "s": [_c(x, 0) for x in g["売残"]]}
            if p is not None:
                cl = p["close"]
                obj["m"]["p"] = [_c(cl.loc[:x].iat[-1], 2) if len(cl.loc[:x]) else None for x in g["申込日"]]
        if p is not None:
            q = p.iloc[-120:]
            obj["pr"] = {"d": [x.strftime("%Y-%m-%d") for x in q.index], "c": [_c(x, 2) for x in q["close"]],
                         "v": [_c(x, 0) for x in q["volume"]]}
        if c in vps:
            obj["vp"] = {"lo": vps[c]["lo"], "hi": vps[c]["hi"], "h": [_c(x, 0) for x in vps[c]["h"]]}
        if c in holders:
            obj["sp"] = holders[c]
        (out / f"{c}.js").write_text(
            f"window.JK_LOAD({json.dumps(obj, ensure_ascii=False, separators=(',', ':'))});", encoding="utf-8")
        n += 1
    return n


def write_all(*, d, m, days, px, vps, sp, sector, mk, mkw, smk, ss, inv, sp_top, M) -> None:
    SITE.mkdir(parents=True, exist_ok=True)
    n = stock_files(d, m, px, vps, sp)

    fields = [f for f, _ in LIST_FIELDS if f in d.columns]
    nd = dict(LIST_FIELDS)
    srt = d.sort_values("需給スコア", ascending=False)
    rows = [[_c(v, nd[f]) for f, v in zip(fields, r)] for r in srt[fields].itertuples(index=False, name=None)]

    # 市場全体の系列
    mkt = {}
    if not mkw.empty:
        w = mkw.copy()
        w["申込日"] = pd.to_datetime(w["申込日"])
        w = w[w["申込日"] >= w["申込日"].max() - timedelta(days=365 * 10)]
        mkt["w"] = {"d": [x.strftime("%Y-%m-%d") for x in w["申込日"]],
                    "b": [_c(x / 1e6, 2) for x in w["買残金額"]],             # 百万円 → 兆円
                    "s": [_c(x / 1e6, 2) for x in w["売残金額"]],
                    "r": [_c(b / s if s else None, 2) for b, s in zip(w["買残金額"], w["売残金額"])]}
    if not mk.empty:
        mkt["d"] = {k: [_c(x, 2) for x in mk[c]] for k, c in
                    (("b", "買残(億円)"), ("s", "売残(億円)"), ("r", "信用倍率(倍)"), ("pl", "信用買い評価損益率(%)"),
                     ("spl", "信用売り評価損益率(%)"))}
        mkt["d"]["d"] = list(mk["申込日"])
    if not smk.empty:
        s = smk.sort_values("日付").tail(260)
        r = s["空売り比率(%)"]
        mkt["ss"] = {"d": list(s["日付"]), "r": [_c(x, 1) for x in r],
                     "ma": [_c(x, 1) for x in r.rolling(25, min_periods=5).mean()]}
    if not inv.empty:
        p = inv[inv["市場"] == "プライム"].sort_values("週末").tail(104)
        keys = ["海外投資家", "個人", "信託銀行", "投資信託", "事業法人", "自己", "生保・損保", "都銀・地銀等",
                "その他法人等", "その他金融機関", "証券会社", "個人現金", "個人信用"]
        mkt["inv"] = {"d": list(p["週末"]), **{k: [_c(x, 0) for x in p[k]] for k in keys if k in p.columns}}

    sec_rows = [[_e(i)] + [_c(v, 2) for v in r] for i, r in sector.iterrows()]
    sec_cols = list(sector.columns)

    def last(k, sub):
        try:
            v = mkt[sub][k]
            return next((x for x in reversed(v) if x is not None), None)
        except (KeyError, IndexError):
            return None

    summary = {"asof": M.strftime("%Y-%m-%d"), "生成": datetime.now().strftime("%Y-%m-%d %H:%M"),
               "信用倍率": last("r", "d"), "評価損益率": last("pl", "d"),
               "空売り比率": last("r", "ss"), "空売り比率25日": last("ma", "ss"), "空売り日付": last("d", "ss"),
               "海外": last("海外投資家", "inv"), "個人": last("個人", "inv"), "週": last("d", "inv"),
               "踏み上げ候補": [[r["コード"], r["銘柄名"]] for _, r in
                           d[d["需給判定"] == "踏み上げ候補"].sort_values("需給スコア", ascending=False).head(5).iterrows()],
               "判定": {k: int(v) for k, v in d["需給判定"].value_counts().items()}}
    (SITE / "jukyu_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")

    from analyze_jukyu import GUIDE
    guide = "".join(f"<tr><th>{_e(k)}</th><td>{_e(v)}</td></tr>" for k, v in GUIDE)
    payload = json.dumps({"f": fields, "r": rows, "mkt": mkt, "sec": {"c": sec_cols, "r": sec_rows},
                          "sum": summary, "days": len(days),
                          "dl": [pd.Timestamp(x).strftime("%Y-%m-%d") for x in days],          # 信用残の申込日（古い順）
                          "pxd": max((p.index.max() for p in px.values() if len(p)), default=pd.NaT).strftime("%Y-%m-%d")
                          if px else None},                                                   # 株価の最終日
                         ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("</", "<\\/")
    page = TEMPLATE.read_text(encoding="utf-8")
    page = page.replace("/*CSS*/", CSS).replace("/*DATA*/", payload).replace("<!--GUIDE-->", guide) \
        .replace("__ASOF__", M.strftime("%Y-%m-%d")).replace("__GEN__", datetime.now().strftime("%Y-%m-%d %H:%M")) \
        .replace("__DAYS__", str(len(days)))
    (SITE / "jukyu.html").write_text(page, encoding="utf-8")
    print(f"ダッシュボード: data/charts/jukyu.html（銘柄データ {n:,}件）", flush=True)
