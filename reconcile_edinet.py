#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Yahoo の財務数値を、有価証券報告書（EDINET DB）の値に合わせる   2026-11-02 作成

なぜ必要か（verify_data.py の照合で見つかったもの）:
  Yahoo は一部の銘柄で「営業利益」に売上総利益を入れてくる（3372 関門海: 営業利益 34億円 ⇔ 有報 1.9億円、
  3377 バイク王: 営業利益・純利益とも 120億円台 ⇔ 有報 5.9億円・3.3億円、ほか 3662・6384・6668・7782・8018 など）。
  そのままだと営業利益率・成長率・スコアが桁違いになる。

やること（fetch_fundamentals.py の直後、analyze_fundamentals.py の前に呼ぶ）:
  1. fundamentals_by_year.csv の各期を、同じ期の有報（提出日が期末の1〜125日後）の値（edinet_metrics_by_year.csv）と比べ、
     売上高・営業利益・当期純利益が 5% 超かつ 1000万円超ずれていたら有報の値に置き換える。
     金融4業種の売上高は定義が違う（経常収益など）ので置き換えない。
  2. 置き換えた期の 営業利益率・EPS を計算し直す。税引前利益が置き換え前の誤った営業利益と
     同じ（1%以内）なら、同じ取り違えとみなして空にする。
  3. fundamentals_latest.csv の直近期・前期・前々期の値と、営業利益率・EPS・PER・成長率を計算し直す。
  4. 発行済株式数を外部データ（verify_shares.py が株探から取った値）に合わせる（apply_external_shares）。
  5. （2026-11-02 追加）J-Quants 決算短信サマリー（fundamentals/jq_summary/、取引所 TDnet の公式値）とも突き合わせる。
     有報で照合できない期は短信の値に合わせ、Yahoo に入っていない新しい本決算（短信が出ている期）は行を追加する。
     優先順位: 有報（EDINET） ＞ 決算短信（J-Quants） ＞ Yahoo。
  置き換えた内容は fundamentals/verify/edinet_corrections.csv に出す（毎回上書き。照合元の列つき）。

  ./.venv/bin/python reconcile_edinet.py
"""
import jq_files  # J-Quants＋TDnet の決算短信サマリー
from pathlib import Path

import numpy as np
import pandas as pd


BASE = Path(__file__).resolve().parent
F = BASE / "fundamentals"
FIN = {"銀行業", "保険業", "証券、商品先物取引業", "その他金融業"}
REL, ABS = 0.02, 1_000_000   # 2% 超かつ 100万円超のずれで公式値に合わせる（2026-11-02 に 5%・1000万円から厳しく）
FIELDS = ["売上高", "営業利益", "当期純利益"]


def rd(v, n=2):
    return None if v is None or pd.isna(v) or np.isinf(v) else round(float(v), n)


def div(a, b, k=1.0):
    if a is None or b is None or pd.isna(a) or pd.isna(b) or b == 0:
        return None
    return a / b * k


JQ_DIR = F / "jq_summary"


def _f(v):
    try:
        return float(v) if v not in ("", None) else np.nan
    except (TypeError, ValueError):
        return np.nan


def jq_fy_table():
    """J-Quants 決算短信サマリーの本決算（FY）を {(コード, 期末日): dict} にする。
    同じ期が複数あれば開示日の新しいもの（訂正短信）を、連結と個別があれば連結を使う。"""
    import json
    best = {}
    for fp in jq_files.files(JQ_DIR):
        try:
            rows = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:  # noqa
            continue
        for x in rows:
            dt_ = str(x.get("DocType", ""))
            if x.get("CurPerType") != "FY" or not dt_.startswith("FYFinancialStatements") or "REIT" in dt_:
                continue
            code = x["Code"][:4] if x["Code"][4:] == "0" else x["Code"]
            key = (code, x["CurPerEn"])
            rank = ("_Consolidated_" in dt_, x["DiscDate"], x.get("DiscTime", ""))
            if key not in best or rank >= best[key][0]:
                best[key] = (rank, x)
    out = {}
    for key, (_, x) in best.items():
        sh, tr = _f(x.get("ShOutFY")), _f(x.get("TrShFY"))
        out[key] = dict(売上高=_f(x.get("Sales")), 営業利益=_f(x.get("OP")), 当期純利益=_f(x.get("NP")),
                        EPS=_f(x.get("EPS")), BPS=_f(x.get("BPS")), 総資産=_f(x.get("TA")), 自己資本=_f(x.get("Eq")),
                        自己資本比率=_f(x.get("EqAR")) * 100, 営業CF=_f(x.get("CFO")), 投資CF=_f(x.get("CFI")),
                        財務CF=_f(x.get("CFF")), 現金同等物=_f(x.get("CashEq")), 一株配当=_f(x.get("DivAnn")),
                        発行済株式総数=sh, 発行済株式数=sh - (0 if pd.isna(tr) else tr),
                        会計基準=x["DocType"].split("_")[-1], 開示日=x["DiscDate"])
    return out


def append_jq_periods(by, jq, log):
    """Yahoo の決算表に無い、より新しい本決算を短信の値で追加する（銘柄名・市場・業種は前の行から引き継ぐ）。"""
    last = by.sort_values("決算期").groupby("コード").tail(1).set_index("コード")
    add = []
    for (code, fy), v in jq.items():
        if code not in last.index or not isinstance(last.at[code, "決算期"], str) or fy <= last.at[code, "決算期"]:
            continue
        if pd.isna(v["当期純利益"]) and pd.isna(v["売上高"]):
            continue
        prev = last.loc[code]
        if str(prev["通貨"]) not in ("JPY", "nan"):
            continue
        row = {c: np.nan for c in by.columns}
        for c in ("コード", "銘柄名", "市場", "業種", "通貨"):
            row[c] = prev[c] if c != "コード" else code
        row["決算期"] = fy
        for c in ("売上高", "営業利益", "当期純利益", "EPS", "総資産", "自己資本", "営業CF", "投資CF", "財務CF",
                  "現金同等物", "一株配当", "発行済株式総数", "発行済株式数"):
            row[c] = v[c]
        if row["業種"] in FIN:
            row["営業利益"] = np.nan
        row["自己資本比率(%)"] = rd(v["自己資本比率"])
        row["BPS"] = v["BPS"] if pd.notna(v["BPS"]) else rd(div(v["自己資本"], v["発行済株式数"]))
        if pd.notna(v["営業CF"]) and pd.notna(v["投資CF"]):
            row["フリーCF"] = v["営業CF"] + v["投資CF"]
        row["営業利益率(%)"] = rd(div(row["営業利益"], row["売上高"], 100))
        add.append(row)
        log.append(dict(コード=code, 銘柄名=prev["銘柄名"], 決算期=fy, 項目="本決算を追加", Yahoo="（未収録）",
                        有報=v["当期純利益"], 会計基準=v["会計基準"], 有報提出日=v["開示日"], 照合元="決算短信(J-Quants)"))
    if add:
        by = pd.concat([by, pd.DataFrame(add)[by.columns]], ignore_index=True)
    return by, {r["コード"] for r in add}


def main():
    by = pd.read_csv(F / "fundamentals_by_year.csv", dtype={"コード": str}, encoding="utf-8-sig")
    la = pd.read_csv(F / "fundamentals_latest.csv", dtype={"コード": str}, encoding="utf-8-sig")
    ed = pd.read_csv(F / "edinet_metrics_by_year.csv", dtype={"コード": str}, encoding="utf-8-sig")
    # 決算年度の数え方は会社ごとに違う（1月決算は前年の年度になる）ので、年度ではなく
    # 「有報の提出日が決算期末の 1〜125 日後」で同じ期を探す。提出日の無い行（前期の比較情報）は使わない。
    ed = ed[ed["提出日"].notna()].copy()
    ed["_sub"] = pd.to_datetime(ed["提出日"])
    G = {c: g for c, g in ed.groupby("コード")}

    def match(code, fy):
        g = G.get(code)
        if g is None:
            return None
        d = (g["_sub"] - pd.Timestamp(fy)).dt.days
        h = g[(d > 0) & (d <= 125)]
        return None if h.empty else h.sort_values("_sub").iloc[-1]

    log = []
    jq = jq_fy_table()
    by, appended = append_jq_periods(by, jq, log)
    # まず各行に対応する公式値（有報 ＞ 決算短信）を探す
    off = {}
    for i, r in by.iterrows():
        if not isinstance(r["決算期"], str):
            continue
        e = match(r["コード"], r["決算期"])
        src = "有報(EDINET)"
        if e is None:
            v = jq.get((r["コード"], r["決算期"]))
            if v is None or str(r["通貨"]) not in ("JPY", "nan"):
                continue
            e = pd.Series({**v, "提出日": v["開示日"]})
            src = "決算短信(J-Quants)"
        off[i] = (e, src)
    official_rows = list(off)

    # 直近期は 2% 超のずれで公式値に合わせる。過去の期は、Yahoo が遡及修正（非継続事業の組み替え・会計方針変更）
    # 後の値を持っていることがあり、当時の公式値に戻すと成長率がかえって狂うので、
    #   ・15% 超のずれ（営業利益と売上総利益の取り違え・期ずれなど明らかな誤り）、または
    #   ・直近期と同じ向き・同じ幅（±1.5ポイント）のずれ（売上高と営業収益の定義の違いなど、毎期そろったずれ）
    # のときだけ合わせる。
    lastfy = by.groupby("コード")["決算期"].max()
    latest_gap = {}
    for i, (e, src) in off.items():
        r = by.loc[i]
        if r["決算期"] != lastfy.get(r["コード"]):
            continue
        for f in FIELDS:
            a, b = r[f], e[f]
            if pd.notna(a) and pd.notna(b) and b:
                latest_gap[(r["コード"], f)] = (a - b) / abs(b)

    for i, (e, src) in off.items():
        r = by.loc[i]
        is_latest = r["決算期"] == lastfy.get(r["コード"])
        old_op = r["営業利益"]
        changed = []
        for f in FIELDS:
            if f == "売上高" and r["業種"] in FIN:
                continue
            a, b = r[f], e[f]
            if pd.isna(b):
                continue
            if pd.isna(a):
                if f != "営業利益":
                    continue
                ok = True
            else:
                gap = (a - b) / max(abs(b), 1)
                ok = abs(a - b) > ABS and abs(gap) > REL
                if ok and not is_latest:
                    lg = latest_gap.get((r["コード"], f))
                    ok = abs(gap) > 0.15 or (lg is not None and abs(lg) > REL and abs(gap - lg) <= 0.015)
            if ok:
                by.at[i, f] = b
                changed.append(f)
                log.append(dict(コード=r["コード"], 銘柄名=r["銘柄名"], 決算期=r["決算期"], 項目=f,
                                Yahoo=a, 有報=b, 会計基準=e["会計基準"], 有報提出日=e["提出日"], 照合元=src))
        if not changed:
            continue
        if "営業利益" in changed and not pd.isna(r["税引前利益"]) and not pd.isna(old_op) and old_op \
                and abs(r["税引前利益"] - old_op) <= abs(old_op) * 0.01:
            by.at[i, "税引前利益"] = np.nan
        by.at[i, "営業利益率(%)"] = rd(div(by.at[i, "営業利益"], by.at[i, "売上高"], 100))
        if "当期純利益" in changed:
            by.at[i, "EPS"] = rd(div(by.at[i, "当期純利益"], r["発行済株式数"]))

    # ---- 営業利益が公式値と合っているのに 売上総利益＝営業利益 なら、売上総利益の方が誤り（販管費0はありえない）。
    #      Yahoo が売上原価の無い会社で売上高や営業利益を売上総利益に入れる典型なので、売上原価・売上総利益を空にする。
    gp_blank = 0
    for i in official_rows:
        op, gp = by.at[i, "営業利益"], by.at[i, "売上総利益"]
        if pd.notna(op) and pd.notna(gp) and gp and abs(op - gp) <= abs(gp) * 0.01 and by.at[i, "業種"] != "電気・ガス業":
            log.append(dict(コード=by.at[i, "コード"], 銘柄名=by.at[i, "銘柄名"], 決算期=by.at[i, "決算期"], 項目="売上総利益を空に",
                            Yahoo=gp, 有報=np.nan, 会計基準="", 有報提出日="", 照合元="営業利益と同額（Yahoo の取り違え）"))
            for f in ("売上原価", "売上総利益", "売上総利益率(%)"):
                by.at[i, f] = np.nan
            gp_blank += 1

    # ---- latest を by_year から作り直す（置き換えた銘柄だけ）----
    fixed = {x["コード"] for x in log}
    byc = by[by["コード"].isin(fixed)].sort_values("決算期", ascending=False).groupby("コード")
    for i, r in la[la["コード"].isin(fixed)].iterrows():
        g = byc.get_group(r["コード"])
        if r["コード"] not in appended:
            g = g[g["決算期"] <= str(r["決算期"])]
        if g.empty:
            continue
        cur = g.iloc[0]
        if r["コード"] in appended:   # 短信で追加した新しい期を「直近期」にする（取れない項目は前の期の値のまま）
            la.at[i, "決算期"] = cur["決算期"]
            for f in ["総資産", "自己資本", "自己資本比率(%)", "BPS", "一株配当", "営業CF", "投資CF", "財務CF",
                      "フリーCF", "現金同等物", "発行済株式数", "発行済株式総数"]:
                if pd.notna(cur[f]):
                    la.at[i, f] = cur[f]
            px = r["株価"]
            if pd.notna(px):
                la.at[i, "PBR"] = rd(div(px, la.at[i, "BPS"]))
                la.at[i, "配当利回り(%)"] = rd(div(la.at[i, "一株配当"], px, 100))
                la.at[i, "時価総額"] = round(px * la.at[i, "発行済株式総数"]) if pd.notna(la.at[i, "発行済株式総数"]) else r["時価総額"]
                if pd.notna(la.at[i, "発行済株式数"]):
                    la.at[i, "時価総額(自己株式除く)"] = round(px * la.at[i, "発行済株式数"])
        p1 = g.iloc[1] if len(g) > 1 else None
        p2 = g.iloc[2] if len(g) > 2 else None
        for f in ["売上高", "営業利益", "当期純利益", "税引前利益", "営業利益率(%)", "EPS"]:
            la.at[i, f] = cur[f]
        for f in FIELDS:
            la.at[i, f + "_前期"] = p1[f] if p1 is not None else la.at[i, f + "_前期"]
            la.at[i, f + "_前々期"] = p2[f] if p2 is not None else la.at[i, f + "_前々期"]
        eps = la.at[i, "EPS"]
        la.at[i, "PER"] = rd(div(r["株価"], eps)) if not pd.isna(eps) and eps else None
        for f, col in (("売上高", "売上高成長率(%)"), ("営業利益", "営業利益成長率(%)")):
            prev = la.at[i, f + "_前期"]
            la.at[i, col] = rd(div(la.at[i, f] - prev, prev, 100)) if not pd.isna(prev) else None
        la.at[i, "PSR"] = rd(div(la.at[i, "時価総額"], la.at[i, "売上高"]))

    log2 = apply_external_shares(by, la)
    log2 += fix_treasury_ratio(la)

    by.to_csv(F / "fundamentals_by_year.csv", index=False, encoding="utf-8-sig")
    la.to_csv(F / "fundamentals_latest.csv", index=False, encoding="utf-8-sig")
    out = F / "verify"
    out.mkdir(exist_ok=True)
    pd.DataFrame(log, columns=["コード", "銘柄名", "決算期", "項目", "Yahoo", "有報", "会計基準", "有報提出日", "照合元"]) \
        .to_csv(out / "edinet_corrections.csv", index=False, encoding="utf-8-sig")
    print(f"公式値（有報・決算短信）に置き換え: {len(fixed)} 銘柄 / {len(log)} 項目（うち新しい本決算を追加 {len(appended)} 銘柄）"
          " → fundamentals/verify/edinet_corrections.csv")
    pd.DataFrame(log2).to_csv(out / "shares_corrections.csv", index=False, encoding="utf-8-sig")
    print(f"株数を外部データ（株探）に合わせた: {len(log2)} 銘柄 → fundamentals/verify/shares_corrections.csv")


def fix_treasury_ratio(la):
    """自己株除きの株数が総数を超える・総数の3割未満など、ありえない値なら、公式の最新値
    （決算短信の期末発行済株式数・自己株式数、無ければ有報の大株主欄）の「自己株を除く割合」で直す。
    割合は株式分割で変わらないので、分割の前後どちらの値にも使える。"""
    import json
    ratio = {}
    for fp in jq_files.files(JQ_DIR):
        try:
            rows = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:  # noqa
            continue
        for x in rows:
            sh, tr = _f(x.get("ShOutFY")), _f(x.get("TrShFY"))
            if pd.isna(sh) or not sh:
                continue
            code = x["Code"][:4] if x["Code"][4:] == "0" else x["Code"]
            k = (x["CurPerEn"], x["DiscDate"])
            if code not in ratio or k >= ratio[code][0]:
                ratio[code] = (k, (sh - (0 if pd.isna(tr) else tr)) / sh)
    try:
        shj = json.loads((F / "shareholders.json").read_text(encoding="utf-8"))
    except Exception:  # noqa
        shj = {}
    for code, x in shj.items():
        if x.get("issued") and (code not in ratio or str(x.get("asof", "")) > ratio[code][0][0]):
            ratio[code] = ((str(x.get("asof", "")), ""), (x["issued"] - (x.get("treasury") or 0)) / x["issued"])
    out = []
    for i, r in la.iterrows():
        tot, ex = r["発行済株式総数"], r["発行済株式数"]
        if pd.isna(tot) or not tot or r["コード"] not in ratio:
            continue
        if pd.notna(ex) and tot * 0.3 <= ex <= tot * 1.001:
            continue
        new = round(tot * ratio[r["コード"]][1])
        la.at[i, "発行済株式数"] = new
        if pd.notna(r["株価"]):
            la.at[i, "時価総額(自己株式除く)"] = round(r["株価"] * new)
        out.append(dict(コード=r["コード"], 銘柄名=r["銘柄名"], 自前株数=ex, 外部株数=new, 比=None, 分割比="",
                        直し方="自己株除きの株数を公式の自己株比率で補正", 時価総額_前=r["時価総額"],
                        時価総額_後=r["時価総額"], 外部取得日=ratio[r["コード"]][0][0]))
    return out


BIG_RATIOS = [1.5, 2, 2.5, 3, 4, 5, 10, 20, 100]


def apply_external_shares(by, la):
    """verify_shares.py が保存した外部の発行済株式数（fundamentals/shares_external.csv、45日以内）と
    3% 超ずれている銘柄を直す。比が決算期末より後の分割台帳の分割比（反映漏れ・二重反映）か、2倍・3倍・1/5 などにぴったりなら全期の株数・1株指標を同じ比で直し
    （分割の反映漏れ）、そうでなければ直近の発行済株式総数と時価総額だけ直す（増資・消却など）。"""
    path = F / "shares_external.csv"
    if not path.exists():
        return []
    ex = pd.read_csv(path, dtype={"コード": str}, encoding="utf-8-sig")
    cut = (pd.Timestamp.today() - pd.Timedelta(days=45)).strftime("%Y-%m-%d")
    ex = ex[ex["取得日"] >= cut].drop_duplicates("コード", keep="last").set_index("コード")
    sp = pd.read_csv(BASE / "data/splits.csv", dtype={"code": str})
    log2 = []
    for i, r in la.iterrows():
        c = r["コード"]
        if c not in ex.index or pd.isna(r["発行済株式総数"]) or not r["発行済株式総数"]:
            continue
        q, got = float(ex.at[c, "外部株数"]), ex.at[c, "取得日"]
        # 外部の株数を取った後に分割・併合があれば、その値はもう古い
        if ((sp["code"] == c) & (sp["ex_date"].astype(str).str[:10] > got)).any():
            continue
        h = q / r["発行済株式総数"]
        if abs(h - 1) <= 0.01:   # 株探の「いまの株数」と1%超違えば合わせる（2026-11-02 に 3% から変更）
            continue
        # 分割比の候補: 台帳 data/splits.csv のうち直近の決算期末より後の分割比の積（反映漏れ）と
        # その逆数（二重反映）。自己株の消却・増資でも株数は1割前後動くので、許容幅は
        # 分割比が大きい（1.5倍以上）ときだけ広く（±25%）、小さいときは ±2% にする。
        aft = sp[(sp["code"] == c) & (sp["ex_date"].astype(str).str[:10] > str(r["決算期"]))] \
            .sort_values("ex_date")["ratio"].astype(float).tolist()
        cands, g = set(), 1.0
        for k in reversed(aft):
            g *= k
            cands |= {g, 1 / g}
        f = 1
        for g in sorted(cands, key=lambda g: abs(np.log(h / g))):
            big = max(g, 1 / g) >= 1.5
            if abs(np.log(h / g)) <= (0.25 if big else 0.02):
                f = g
            break
        if f == 1:   # 台帳に無い分割でも、2倍・3倍などにぴったり（±3%）なら分割の反映漏れとみなす
            f = next((k for k in BIG_RATIOS + [1 / k for k in BIG_RATIOS] if abs(h / k - 1) < 0.03), 1)
        is_split = f != 1
        px = r["株価"]
        if is_split:
            h = f
            for frame, idx in ((la, [i]), (by, by.index[by["コード"] == c])):
                for j in idx:
                    for k in ("発行済株式数", "発行済株式総数"):
                        if pd.notna(frame.at[j, k]):
                            frame.at[j, k] = frame.at[j, k] * h
                    for k in ("BPS", "EPS", "一株配当"):
                        if pd.notna(frame.at[j, k]):
                            frame.at[j, k] = round(frame.at[j, k] / h, 4)
            la.at[i, "発行済株式総数"] = q   # 分割を直したあと、増資・消却の差も外部の値に合わせる
            la.at[i, "PER"] = rd(div(px, la.at[i, "EPS"]))
            la.at[i, "PBR"] = rd(div(px, la.at[i, "BPS"]))
            la.at[i, "配当利回り(%)"] = rd(div(la.at[i, "一株配当"], px, 100))
            if pd.notna(la.at[i, "発行済株式数"]) and pd.notna(px):
                la.at[i, "時価総額(自己株式除く)"] = round(px * la.at[i, "発行済株式数"])
        else:
            la.at[i, "発行済株式総数"] = q
        big_change = (not is_split) and not (0.67 <= h <= 1.5)
        # 自己株除きの株数も総数の変化に合わせる（自己株の数はそのまま。総数を超えないように）
        tot0 = r["発行済株式総数"] * (h if is_split else 1)
        ex0 = la.at[i, "発行済株式数"]
        if pd.notna(ex0):
            tr = max(tot0 - ex0, 0)
            la.at[i, "発行済株式数"] = q - tr if q - tr > q * 0.5 else q * ex0 / tot0
            if pd.notna(px):
                la.at[i, "時価総額(自己株式除く)"] = round(px * la.at[i, "発行済株式数"])
        # 分割以外で株数が1.5倍超・2/3未満に変わった（大量の増資・経営統合・新株予約権の行使など）なら、
        # 決算期末の株数で割った EPS・BPS では PER・PBR が桁違いになるので、いまの株数で割り直す。
        if big_change and pd.notna(la.at[i, "発行済株式数"]) and la.at[i, "発行済株式数"]:
            n = la.at[i, "発行済株式数"]
            la.at[i, "EPS"] = rd(div(la.at[i, "当期純利益"], n), 4)
            la.at[i, "BPS"] = rd(div(la.at[i, "自己資本"], n), 4)
            la.at[i, "PER"] = rd(div(px, la.at[i, "EPS"]))
            la.at[i, "PBR"] = rd(div(px, la.at[i, "BPS"]))
        old_mc = r["時価総額"]
        if pd.notna(px):
            la.at[i, "時価総額"] = round(px * la.at[i, "発行済株式総数"])
            la.at[i, "PSR"] = rd(div(la.at[i, "時価総額"], la.at[i, "売上高"]))
        log2.append(dict(コード=c, 銘柄名=r["銘柄名"], 自前株数=r["発行済株式総数"], 外部株数=q,
                         比=round(q / r["発行済株式総数"], 3), 分割比=round(f, 4) if is_split else "",
                         直し方="全期（分割の反映漏れ）" if is_split else
                         ("直近の株数・時価総額・EPS・BPS（大きな増減）" if big_change else "直近の株数・時価総額のみ"),
                         時価総額_前=old_mc, 時価総額_後=la.at[i, "時価総額"], 外部取得日=got))
    return log2


if __name__ == "__main__":
    main()
