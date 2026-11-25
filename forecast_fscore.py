"""予想Fスコア（復活Fスコア戦略の会社予想ベース版）

J-Quants の fins summary（決算短信サマリー）から今期の会社予想を読み、
F1〜F3・F7を「今年度の会社予想」で判定します。残りの5項目は前年度実績で判定します。
マネックス証券「復活Fスコア戦略」（2026年9月）の定義に合わせたものです。

  F1 営業利益      今期予想営業利益がプラス
  F2 ROA変化       今期予想営業利益÷前期末総資産 ＞ 前期営業利益÷(前期末と前々期末の総資産の平均)
  F3 営業利益率     今期予想営業利益÷今期予想売上高 ＞ 前期営業利益÷前期売上高
  F4 営業CF        前期の営業CFがプラス
  F5 流動比率       前期の流動比率が前々期を上回る
  F6 有利子負債     前期の有利子負債÷総資産が前々期を下回る
  F7 資産回転率     今期予想売上高÷前期末総資産 ＞ 前期売上高÷前々期末総資産
  F8 アクルーアル   前期の当期純利益が営業CFを下回る
  F9 株式発行       前期の発行済株式総数が前々期から増えていない（CF内訳が無いための代用）

ここでの「前期」は直近の本決算（実績）、「今期」はその次の期です。実績は2期分あれば判定でき、
実績ベースのFスコア（3期必要）より対象銘柄が広がります。

予想データの置き場所: fundamentals/jq_summary/YYYY-MM-DD.json
  （jquants --output json fins summary --date YYYY-MM-DD の出力。fetch_jq_summary.sh が毎日取り足します）
Freeプランは12週間遅れなので、直近12週間に出た予想修正は反映されません。
"""
from __future__ import annotations
import jq_files  # J-Quants＋TDnet の決算短信サマリー

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

YF_COLS = [
    "予想F1営業利益", "予想F2ROA変化", "予想F3営業利益率", "予想F4営業CF", "予想F5流動比率",
    "予想F6有利子負債", "予想F7資産回転率", "予想F8アクルーアル", "予想F9株式発行",
]
YF_INFO_COLS = ["今期予想売上高(億円)", "今期予想営業利益(億円)", "今期予想営業利益率(%)",
                "予想の対象期", "予想の開示日"]
YF_ALL = YF_COLS + ["予想Fスコア"] + YF_INFO_COLS + ["予想Fデータ品質"]


def _num(v):
    if v in ("", None):
        return np.nan
    try:
        return float(v)
    except (TypeError, ValueError):
        return np.nan


def _pick(r, key):
    """連結の値が無ければ個別（NC〜）の値を使う。"""
    v = _num(r.get(key))
    return v if not np.isnan(v) else _num(r.get("NC" + key))


def load_jq_summary(jq_dir: Path):
    """(予想, 実績) の2つの表を返す。キーは コード と 期末年月(YYYY-MM)。"""
    fc, act = [], []
    for f in jq_files.files(jq_dir):
        try:
            rows = json.loads(f.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if not isinstance(rows, list):
            continue
        for r in rows:
            code = str(r.get("Code", ""))
            code = code[:4] if len(code) == 5 and code.endswith("0") else code
            doc = r.get("DocType", "")
            when = f"{r.get('DiscDate', '')} {r.get('DiscTime', '')}"
            cur = str(r.get("CurFYEn") or "")[:7]
            if not cur or "REIT" in doc:
                continue
            if doc.startswith("FY") and "FinancialStatements" in doc:
                act.append(dict(コード=code, 期=cur, 開示=when,
                                売上高=_pick(r, "Sales"), 営業利益=_pick(r, "OP"),
                                総資産=_pick(r, "TA"), 営業CF=_num(r.get("CFO")),
                                当期純利益=_pick(r, "NP")))
                nxt = str(r.get("NxtFYEn") or "")[:7] or \
                    (pd.Timestamp(r["CurFYEn"]) + pd.DateOffset(years=1)).strftime("%Y-%m")
                fs, fo = _pick(r, "NxFSales"), _pick(r, "NxFOP")
                if not (np.isnan(fs) and np.isnan(fo)):
                    fc.append(dict(コード=code, 期=nxt, 開示=when, 予想売上高=fs, 予想営業利益=fo))
            else:
                # 四半期決算・業績予想の修正に載る「当期の通期予想」
                fs, fo = _pick(r, "FSales"), _pick(r, "FOP")
                if not (np.isnan(fs) and np.isnan(fo)):
                    fc.append(dict(コード=code, 期=cur, 開示=when, 予想売上高=fs, 予想営業利益=fo))
    fc = pd.DataFrame(fc, columns=["コード", "期", "開示", "予想売上高", "予想営業利益"])
    act = pd.DataFrame(act, columns=["コード", "期", "開示", "売上高", "営業利益",
                                     "総資産", "営業CF", "当期純利益"])
    # 同じ期の予想が何度も出ていれば、項目ごとに最新の値（売上だけの修正などに備える）
    fc = fc.sort_values("開示")
    last = lambda s: s.dropna().iloc[-1] if s.notna().any() else np.nan
    fc = fc.groupby(["コード", "期"]).agg(予想売上高=("予想売上高", last),
                                          予想営業利益=("予想営業利益", last),
                                          開示=("開示", "last")).reset_index()
    act = act.sort_values("開示").groupby(["コード", "期"]).last().reset_index()
    return fc, act


def attach_forecast_fscore(d: pd.DataFrame, by_year: Path, jq_dir: Path,
                           financial_sectors) -> pd.DataFrame:
    d = d.copy()
    for c in YF_ALL:
        d[c] = np.nan
    d["予想の対象期"] = ""
    d["予想の開示日"] = ""
    d["予想Fデータ品質"] = ""
    if not jq_dir.exists() or not any(jq_dir.glob("*.json")):
        print(f"※ {jq_dir} に会社予想が無いため、予想Fスコアは評価しません。", file=sys.stderr)
        d["予想Fデータ品質"] = "会社予想のデータが無い"
        return d
    if not by_year.exists():
        return d

    fc, act = load_jq_summary(jq_dir)
    fc = fc.set_index(["コード", "期"])
    act = act.set_index(["コード", "期"])
    newest_act = act.reset_index().groupby("コード")["期"].max()

    y = pd.read_csv(by_year, encoding="utf-8-sig", dtype={"コード": str})
    y["決算期"] = pd.to_datetime(y["決算期"], errors="coerce")
    y = y.dropna(subset=["決算期"]).sort_values(["コード", "決算期"])
    y = y.drop_duplicates(["コード", "決算期"], keep="last")
    shares = pd.to_numeric(y.get("発行済株式総数"), errors="coerce")
    if "発行済株式数" in y.columns:
        shares = shares.fillna(pd.to_numeric(y["発行済株式数"], errors="coerce"))
    y["_株式数"] = shares
    ygrp = {c: g.tail(2) for c, g in y.groupby("コード", observed=True)}

    res, notes = {}, {}
    for code in d["コード"].astype(str):
        g = ygrp.get(code)
        if g is None or len(g) < 2:
            notes[code] = "決算が2期分そろっていない"
            continue
        p, t = g.iloc[0], g.iloc[1]          # p=前々期, t=前期（直近の本決算）
        per = t["決算期"].strftime("%Y-%m")
        nxt = (t["決算期"] + pd.DateOffset(years=1)).strftime("%Y-%m")
        if code in newest_act.index and newest_act[code] > per:
            notes[code] = "J-Quantsに新しい本決算があり、Yahooの実績が追いついていない"
            continue
        if (code, nxt) not in fc.index:
            notes[code] = "今期の会社予想が無い（未開示・レンジ予想）"
            continue
        f = fc.loc[(code, nxt)]
        FS, FO = f["予想売上高"], f["予想営業利益"]
        # 前期実績は予想と同じ出所（決算短信）を優先し、無ければYahooの値
        a = act.loc[(code, per)] if (code, per) in act.index else None
        def cur(col):
            v = a[col] if a is not None else np.nan
            return v if not pd.isna(v) else t.get(col, np.nan)
        S, OP, TA = cur("売上高"), cur("営業利益"), cur("総資産")
        CFO, NP = cur("営業CF"), cur("当期純利益")
        TA_p = p["総資産"]
        miss = []
        for lab, v in [("今期予想営業利益", FO), ("今期予想売上高", FS), ("前期の売上高", S),
                       ("前期の営業利益", OP), ("前期の総資産", TA), ("前々期の総資産", TA_p),
                       ("前期の営業CF", CFO), ("前期の当期純利益", NP),
                       ("流動資産・流動負債", t["流動資産"] * t["流動負債"] * p["流動資産"] * p["流動負債"]),
                       ("有利子負債", t["有利子負債"] * p["有利子負債"]),
                       ("発行済株式数", t["_株式数"] * p["_株式数"])]:
            if pd.isna(v):
                miss.append(f"{lab}が欠損")
        for c in ("総資産", "流動資産", "流動負債", "有利子負債"):
            if pd.notna(t[c]) and t[c] == p[c]:
                miss.append(f"{c}が前期と前々期で同値（補完疑い）")
        info = {"今期予想売上高(億円)": FS / 1e8, "今期予想営業利益(億円)": FO / 1e8,
                "今期予想営業利益率(%)": FO / FS * 100 if FS and FS > 0 else np.nan,
                "予想の対象期": nxt, "予想の開示日": str(f["開示"])[:10]}
        if miss:
            notes[code] = "; ".join(miss)
            res[code] = info
            continue
        sc = {
            "予想F1営業利益": FO > 0,
            "予想F2ROA変化": FO / TA > OP / ((TA + TA_p) / 2),
            "予想F3営業利益率": FS > 0 and S > 0 and FO / FS > OP / S,
            "予想F4営業CF": CFO > 0,
            "予想F5流動比率": t["流動資産"] / t["流動負債"] > p["流動資産"] / p["流動負債"],
            "予想F6有利子負債": t["有利子負債"] / TA < p["有利子負債"] / TA_p,
            "予想F7資産回転率": FS / TA > S / TA_p,
            "予想F8アクルーアル": NP < CFO,
            "予想F9株式発行": t["_株式数"] <= p["_株式数"],
        }
        sc = {k: float(bool(v)) for k, v in sc.items()}
        sc["予想Fスコア"] = sum(sc.values())
        res[code] = {**sc, **info}

    idx = d["コード"].astype(str)
    R = pd.DataFrame.from_dict(res, orient="index")
    for c in R.columns:
        d[c] = idx.map(R[c])
    for c in YF_COLS + ["予想Fスコア"] + YF_INFO_COLS[:3]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d["予想の対象期"] = d["予想の対象期"].fillna("")
    d["予想の開示日"] = d["予想の開示日"].fillna("")
    d["予想Fデータ品質"] = idx.map(notes).fillna("")
    fin = d["業種"].isin(financial_sectors)
    for c in YF_COLS + ["予想Fスコア"]:
        d.loc[fin, c] = np.nan
    d.loc[fin, "予想Fデータ品質"] = "金融4業種のため対象外"

    n_ok = int(d["予想Fスコア"].notna().sum())
    print(f"予想Fスコア: {n_ok:,}/{len(d):,}銘柄で算出（会社予想 {len(fc):,}件）")
    return d
