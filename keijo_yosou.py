"""四季報式スコア用の「経常利益」と「会社予想PER」

J-Quants の fins summary（決算短信サマリー。fundamentals/jq_summary/ に1日1ファイル）から
次の2つを作り、四季報式スコアの収益性と割安度を四季報の定義に近づけます。

1. 収益性 … 売上高経常利益率
   Yahooの年次決算には経常利益の区分が無いので、決算短信の経常利益（OdP）を
   決算期（年月）で突き合わせて差し込みます。
     ・日本基準の会社  : 経常利益が取れた期は経常利益、取れない期は税引前利益
     ・IFRS・米国基準  : 経常利益という区分が無いので税引前利益（IFRSには特別損益の
                        区分も無く、税引前利益が経常利益にいちばん近い）
   どちらで何期計算したかは「収益性の基準」列に残します。
   IFRSの会社が短信の経常利益欄に税引前利益を入れている例があるため、
   経常利益を使うのは短信が日本基準（DocType が _JP）のときだけにしています。

2. 割安度 … 会社予想PER
   四季報は今期の会社予想PERで割安度を測ります。
     予想PER ＝ 時価総額（自己株式除く）÷ 今期の会社予想純利益
   1株あたりの予想EPSではなく純利益で割るのは、短信の開示後に株式分割があっても
   ズレないようにするためです（Freeプランは12週間遅れなので分割をまたぎやすい）。
   「今期」は手元の最新の本決算の次の期。その期の予想が無ければ使いません。
"""
from __future__ import annotations
import jq_files  # J-Quants＋TDnet の決算短信サマリー

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

KEIJO_COLS = ["平均経常利益率(%)", "直近経常利益率(%)", "収益性の基準"]
YOSOU_COLS = ["予想PER", "今期予想純利益(億円)", "今期予想経常利益(億円)",
              "予想経常増益率(%)", "予想PERの対象期", "予想PERの開示日"]


def _num(v):
    if v in ("", None):
        return np.nan
    try:
        return float(v)
    except (TypeError, ValueError):
        return np.nan


def _pick(r, *keys):
    """連結の値が無ければ個別（NC〜）の値を使う。キーは表記ゆれ（NxFNp/NxFNP）ごと渡す。"""
    for k in keys:
        v = _num(r.get(k))
        if not np.isnan(v):
            return v
    for k in keys:
        v = _num(r.get("NC" + k))
        if not np.isnan(v):
            return v
    return np.nan


def _code(r) -> str:
    c = str(r.get("Code", ""))
    return c[:4] if len(c) == 5 and c.endswith("0") else c


def load_jq(jq_dir: Path):
    """(実績, 予想) の2表を返す。キーは コード と 期（期末の YYYY-MM）。"""
    act, fc = [], []
    for f in jq_files.files(jq_dir):
        try:
            rows = json.loads(f.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if not isinstance(rows, list):
            continue
        for r in rows:
            doc = r.get("DocType", "")
            cur = str(r.get("CurFYEn") or "")[:7]
            if not cur or "REIT" in doc:
                continue
            code = _code(r)
            when = f"{r.get('DiscDate', '')} {r.get('DiscTime', '')}"
            std = doc.rsplit("_", 1)[-1] if "_" in doc else ""
            if doc.startswith("FY") and "FinancialStatements" in doc:
                act.append(dict(コード=code, 期=cur, 開示=when, 基準=std,
                                経常利益=_pick(r, "OdP") if std == "JP" else np.nan))
                nxt = str(r.get("NxtFYEn") or "")[:7]
                if not nxt:
                    try:
                        nxt = (pd.Timestamp(r["CurFYEn"]) + pd.DateOffset(years=1)).strftime("%Y-%m")
                    except Exception:
                        nxt = ""
                if nxt:
                    fc.append(dict(コード=code, 期=nxt, 開示=when,
                                   予想純利益=_pick(r, "NxFNp", "NxFNP"),
                                   予想経常利益=_pick(r, "NxFOdP") if std == "JP" else np.nan))
            else:
                # 四半期決算・業績予想の修正に載る「当期の通期予想」
                fc.append(dict(コード=code, 期=cur, 開示=when,
                               予想純利益=_pick(r, "FNP", "FNp"),
                               予想経常利益=_pick(r, "FOdP") if std == "JP" else np.nan))
    act = pd.DataFrame(act, columns=["コード", "期", "開示", "基準", "経常利益"])
    fc = pd.DataFrame(fc, columns=["コード", "期", "開示", "予想純利益", "予想経常利益"])
    last = lambda s: s.dropna().iloc[-1] if s.notna().any() else np.nan
    act = act.sort_values("開示").groupby(["コード", "期"]).agg(
        経常利益=("経常利益", last), 基準=("基準", "last"), 開示=("開示", "last")).reset_index()
    # 同じ期の予想が何度も出ていれば、項目ごとに最新の値（純利益だけの修正などに備える）
    fc = fc.sort_values("開示").groupby(["コード", "期"]).agg(
        予想純利益=("予想純利益", last), 予想経常利益=("予想経常利益", last),
        開示=("開示", "last")).reset_index()
    return act, fc


def _safe_div(a, b):
    with np.errstate(divide="ignore", invalid="ignore"):
        r = a / b.replace(0, np.nan)
    return r.replace([np.inf, -np.inf], np.nan)


def attach_keijo_yosou(d: pd.DataFrame, by_year: Path, jq_dir: Path, periods: int) -> pd.DataFrame:
    d = d.copy()
    for c in KEIJO_COLS + YOSOU_COLS:
        d[c] = np.nan
    for c in ("収益性の基準", "予想PERの対象期", "予想PERの開示日"):
        d[c] = ""
    if not by_year.exists():
        return d
    have_jq = jq_dir.exists() and any(jq_dir.glob("*.json"))
    if have_jq:
        act, fc = load_jq(jq_dir)
    else:
        print(f"※ {jq_dir} が無いため、収益性は税引前利益、割安度は実績PERのままです。",
              file=sys.stderr)
        act = pd.DataFrame(columns=["コード", "期", "経常利益", "基準", "開示"])
        fc = pd.DataFrame(columns=["コード", "期", "予想純利益", "予想経常利益", "開示"])

    # ---- 1. 収益性: 期ごとに 経常利益 → 税引前利益 の順で使う ----------------------
    y = pd.read_csv(by_year, encoding="utf-8-sig", dtype={"コード": str})
    y["決算期"] = pd.to_datetime(y["決算期"], errors="coerce")
    y = y.dropna(subset=["決算期"]).sort_values(["コード", "決算期"])
    y = y.drop_duplicates(["コード", "決算期"], keep="last")
    y = y.groupby("コード", observed=True).tail(periods).copy()
    y["期"] = y["決算期"].dt.strftime("%Y-%m")
    y = y.merge(act[["コード", "期", "経常利益"]], on=["コード", "期"], how="left")
    rev = pd.to_numeric(y["売上高"], errors="coerce")
    pre = pd.to_numeric(y["税引前利益"], errors="coerce")
    kei = pd.to_numeric(y["経常利益"], errors="coerce")
    y["_kei"] = kei.notna()
    y["_margin"] = _safe_div(kei.where(y["_kei"], pre), rev.where(rev > 0)) * 100
    y["_kmargin"] = _safe_div(kei, rev.where(rev > 0)) * 100
    g = y.groupby("コード", observed=True)
    margin = g["_margin"].mean()
    n_all = g["_margin"].count()
    n_kei = y[y["_margin"].notna()].groupby("コード", observed=True)["_kei"].sum()
    latest_k = y.dropna(subset=["_kmargin"]).groupby("コード", observed=True)["_kmargin"].last()

    # 会計基準（直近の短信）。IFRS・米国基準は経常利益が無いのが正常
    std = act.sort_values("期").groupby("コード")["基準"].last()
    idx = d["コード"].astype(str)
    d["平均経常利益率(%)"] = idx.map(margin).astype("float64").round(2)
    d["直近経常利益率(%)"] = idx.map(latest_k).astype("float64").round(2)
    nk = idx.map(n_kei).fillna(0).astype(int)
    na = idx.map(n_all).fillna(0).astype(int)
    sd = idx.map(std).fillna("")
    basis = np.where(na == 0, "",
             np.where(nk == na, "経常利益（" + na.astype(str) + "期）",
             np.where(nk > 0, "経常利益" + nk.astype(str) + "期＋税引前利益" + (na - nk).astype(str) + "期",
             np.where(sd.isin(["IFRS", "US", "JMIS"]), "税引前利益（" + sd + "）",
                      "税引前利益（経常利益未取得）"))))
    d["収益性の基準"] = basis

    # ---- 2. 会社予想PER ----------------------------------------------------------
    last_act = y.groupby("コード", observed=True)["決算期"].max()
    fc = fc.copy()
    fc["_end"] = pd.to_datetime(fc["期"] + "-01", errors="coerce") + pd.offsets.MonthEnd(0)
    fc = fc.dropna(subset=["_end"])
    fc["_last"] = fc["コード"].map(last_act)
    # 今期 ＝ 最新の本決算の次の期（決算期変更の変則決算も拾えるよう 3〜15か月先まで）
    gap = (fc["_end"] - fc["_last"]).dt.days
    fc = fc[gap.between(80, 460)]
    fc = fc.sort_values(["コード", "_end"]).groupby("コード").head(1).set_index("コード")

    mcap = pd.to_numeric(d.get("時価総額(自己株式除く)"), errors="coerce") \
        if "時価総額(自己株式除く)" in d.columns else pd.Series(np.nan, index=d.index)
    mcap = mcap.fillna(pd.to_numeric(d.get("時価総額"), errors="coerce"))
    np_fc = idx.map(fc["予想純利益"]).astype("float64")
    kei_fc = idx.map(fc["予想経常利益"]).astype("float64")
    per = _safe_div(mcap, np_fc.where(np_fc > 0))
    d["予想PER"] = per.round(2)
    d["今期予想純利益(億円)"] = (np_fc / 1e8).round(1)
    d["今期予想経常利益(億円)"] = (kei_fc / 1e8).round(1)
    # 前期実績の経常利益（短信）に対する予想の伸び
    kei_last = y.dropna(subset=["経常利益"]).sort_values("決算期").groupby("コード")["経常利益"].last()
    kl = idx.map(kei_last).astype("float64")
    d["予想経常増益率(%)"] = (_safe_div(kei_fc - kl, kl.where(kl > 0)) * 100).round(1)
    d["予想PERの対象期"] = idx.map(fc["期"]).fillna("")
    d["予想PERの開示日"] = idx.map(fc["開示"].str[:10]).fillna("")

    print(f"経常利益: {int(nk.gt(0).sum()):,}銘柄で経常利益を使用"
          f"（全期 {int(((nk == na) & (na > 0)).sum()):,}／一部 {int(((nk > 0) & (nk < na)).sum()):,}）、"
          f"予想PER {int(d['予想PER'].notna().sum()):,}銘柄")
    return d
