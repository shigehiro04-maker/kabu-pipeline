#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全銘柄のファンダメンタル・ダッシュボードを生成する。

入力（~/株分析/fundamentals/）
  fundamentals_by_year.csv   通期の時系列（最大4期）
  fundamentals_latest.csv    株価・時価総額・PER/PBR など
  company_profile.csv        事業概要（任意）

出力（~/株分析/dashboards/）
  index.html                 全銘柄一覧（検索・ソート）
  <コード>.html              銘柄ごとのダッシュボード
  assets/style.css, app.js   共通アセット
  data/index.json            一覧用データ

通期ベース
  手元のYahoo由来データは通期のみ（最大4期）のため、通期の時系列だけで構成する。
  売上総利益は fetch_fundamentals.py が取得した売上総利益／売上原価から算出する。未取得なら
  GrossProfit を追加して再取得すれば、そのまま埋まる。

使い方
  python3 make_company_dashboards.py                # 全銘柄
  python3 make_company_dashboards.py 7203 6758      # 銘柄指定
  python3 make_company_dashboards.py --limit 50     # 先頭50銘柄だけ
"""

import jq_files  # J-Quants＋TDnet の決算短信サマリー
import csv
import json
import os
import sys
import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
FUND = BASE / "fundamentals"
OUT = Path(os.environ["DASH_OUT"]) if os.environ.get("DASH_OUT") else BASE / "dashboards"
JQ_DIR = FUND / "jq_summary"

YEN_PER_MILLION = 1e6


# ------------------------------------------------------------------ helpers
def num(s):
    """CSVの文字列を float か None に。"""
    if s is None:
        return None
    s = str(s).strip().replace(",", "")
    if s == "" or s.lower() in ("nan", "none", "-", "--"):
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    if v != v:  # NaN
        return None
    return v


def yen_to_m(v):
    """円 -> 百万円。"""
    return None if v is None else round(v / YEN_PER_MILLION, 3)


def read_csv(path):
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def fy_label(date_str):
    """'2026-03-31' -> ('26/3期', 2026, 3)"""
    try:
        y, m = int(date_str[0:4]), int(date_str[5:7])
    except (ValueError, IndexError, TypeError):
        return (str(date_str), None, None)
    return ("%02d/%d期" % (y % 100, m), y, m)



# ------------------------------------------------------------------ J-Quants 決算短信サマリー
def _jv(r, *keys):
    """連結の値が無ければ個別（NC〜）の値。"""
    for k in keys:
        v = num(r.get(k))
        if v is not None:
            return v
    for k in keys:
        v = num(r.get("NC" + k))
        if v is not None:
            return v
    return None


def load_jq_detail():
    """fundamentals/jq_summary/*.json から銘柄ごとに
    fy: {期末YYYY-MM: 経常利益・年間配当・配当性向}（本決算の実績）
    fc: {期末日: 売上・営業・経常・純利益・EPS・年間配当}（最新の会社予想）
    q : 単独四半期の売上・営業・経常・純利益（累計の差分）
    std: 会計基準（JP / IFRS / US …）
    を返す。無ければ空。"""
    if not JQ_DIR.exists():
        return {}
    recs = {}
    for f in jq_files.files(JQ_DIR):
        try:
            rows = json.loads(f.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if not isinstance(rows, list):
            continue
        for r in rows:
            doc = r.get("DocType", "") or ""
            if "REIT" in doc:
                continue
            c = str(r.get("Code", ""))
            code = c[:4] if len(c) == 5 and c.endswith("0") else c
            recs.setdefault(code, []).append(r)

    CUR = {"rev": ("FSales",), "op": ("FOP",), "odp": ("FOdP",), "ni": ("FNP", "FNp"),
           "eps": ("FEPS",), "div": ("FDivAnn",)}
    NXT = {"rev": ("NxFSales",), "op": ("NxFOP",), "odp": ("NxFOdP",), "ni": ("NxFNp", "NxFNP"),
           "eps": ("NxFEPS",), "div": ("NxFDivAnn",)}
    out = {}
    for code, rs in recs.items():
        rs.sort(key=lambda r: (r.get("DiscDate", ""), r.get("DiscTime", "")))
        fs, fc, std = {}, {}, ""
        for r in rs:
            doc = r.get("DocType", "") or ""
            fyen = (r.get("CurFYEn") or "")[:10]
            per = r.get("CurPerType", "") or ""
            isfs = "FinancialStatements" in doc
            if isfs:
                std = doc.rsplit("_", 1)[-1] if "_" in doc else std
                if fyen and per in ("1Q", "2Q", "3Q", "FY"):
                    fs[(fyen, per)] = r
            if isfs and per == "FY":
                tgt = (r.get("NxtFYEn") or "")[:10]
                if not tgt and len(fyen) == 10:
                    tgt = "%d%s" % (int(fyen[:4]) + 1, fyen[4:])
                keys = NXT
            else:
                tgt, keys = fyen, CUR
            if not tgt:
                continue
            got = {k: _jv(r, *ks) for k, ks in keys.items()}
            if any(v is not None for v in got.values()):
                slot = fc.setdefault(tgt, {})
                slot.update({k: v for k, v in got.items() if v is not None})
                slot["disc"] = r.get("DiscDate", "")

        fy = {}
        for (fyen, per), r in fs.items():
            if per == "FY":
                fy[fyen[:7]] = {"odp": _jv(r, "OdP"), "div": _jv(r, "DivAnn"),
                                "payout": _jv(r, "PayoutRatioAnn")}

        q = []
        for fyen in sorted({k[0] for k in fs}):
            prev = None
            for i, per in enumerate(("1Q", "2Q", "3Q", "FY")):
                r = fs.get((fyen, per))
                if r is None:
                    prev = None
                    continue
                cum = {"rev": _jv(r, "Sales"), "op": _jv(r, "OP"),
                       "odp": _jv(r, "OdP"), "ni": _jv(r, "NP")}
                if i == 0:
                    st = dict(cum)
                elif prev is None:
                    st = None
                else:
                    st = {k: (None if cum[k] is None or prev[k] is None else cum[k] - prev[k])
                          for k in cum}
                prev = cum
                if not st or st["rev"] is None:
                    continue
                row = {"fy": "%s/%s" % (fyen[2:4], "4Q" if per == "FY" else per),
                       "fyEnd": fyen, "perEnd": (r.get("CurPerEn") or "")[:10],
                       "perSt": (r.get("CurPerSt") or "")[:10] if i == 0 else None,
                       "disc": r.get("DiscDate", "")}
                for k, v in st.items():
                    row[k] = yen_to_m(v)
                row["opm"] = (row["op"] / row["rev"]) if (row["op"] is not None and row["rev"]) else None
                q.append(row)
        out[code] = {"std": std, "fy": fy, "fc": fc, "q": q[-8:]}
    return out


def attach_jq(c, d):
    """通期に経常利益・配当性向・フリーCF（営業CF＋投資CF）を足し、会社予想の行と四半期を付ける。
    IFRS・米国基準など経常利益の無い会計基準では税引前利益で代用する。"""
    d = d or {}
    A = c["annual"]
    jp = d.get("std") == "JP"
    c["odpName"] = "経常利益" if jp else "税引前利益"
    fy = d.get("fy", {})
    for a in A:
        j = fy.get((a["fyEnd"] or "")[:7], {})
        a["odp"] = yen_to_m(j.get("odp")) if jp else a.get("pbt")
        a["payout"] = (a["dps"] / a["eps"]) if (a.get("dps") is not None and a.get("eps") and a["eps"] > 0) else None
        a["frcf"] = (a["ocf"] + a["icf"]) if (a.get("ocf") is not None and a.get("icf") is not None) else None

    c["fc"] = None
    if A:
        last = A[-1]
        lym = (last["fyEnd"] or "")[:7]
        cand = sorted(k for k in d.get("fc", {}) if k[:7] > lym)
        if cand:
            k = cand[0]
            f = d["fc"][k]
            if f.get("rev") is not None or f.get("op") is not None:
                # 株式分割で一株配当の基準がずれていれば、直近実績の比で合わせる
                scale = 1.0
                jd = fy.get(lym, {}).get("div")
                if jd and last.get("dps") and jd > 0:
                    r = last["dps"] / jd
                    if abs(r - 1) > 0.05:
                        scale = r
                lab, _, _ = fy_label(k)
                row = {"fy": lab + "予", "fyEnd": k, "fc": True, "disc": f.get("disc", ""),
                       "rev": yen_to_m(f.get("rev")), "op": yen_to_m(f.get("op")),
                       "odp": yen_to_m(f.get("odp")) if jp else None,
                       "ni": yen_to_m(f.get("ni")),
                       "dps": (f["div"] * scale) if f.get("div") is not None else None,
                       "eps": (f["eps"] * scale) if f.get("eps") is not None else None}
                row["opm"] = (row["op"] / row["rev"]) if (row["op"] is not None and row["rev"]) else None
                row["payout"] = (f["div"] / f["eps"]) if (f.get("div") is not None and f.get("eps") and f["eps"] > 0) else None
                # 会社予想の取り違え（四半期の予想・単位違いなど）を除く：直近4四半期の合計か直近通期と比べて桁外れなら出さない
                q4 = [x["rev"] for x in d.get("q", [])[-4:] if x.get("rev") is not None]
                ref = sum(q4) if len(q4) == 4 else last.get("rev")
                if row["rev"] is not None and ref and ref > 0 and not (0.4 <= row["rev"] / ref <= 2.5):
                    row = None
                c["fc"] = row
    c["quarters"] = d.get("q", [])

# ------------------------------------------------------------------ load
def load_cost_of_sales():
    """fundamentals/cost_of_sales_by_year.csv から (コード, 年度) -> {売上高, 売上原価, 売上総利益} を作る。
    ファイルが無ければ空の辞書を返す（後方互換）。"""
    out = {}
    for r in read_csv(FUND / "cost_of_sales_by_year.csv"):
        code = (r.get("コード") or "").strip()
        year = (r.get("年度") or "").strip()
        if not code or not year:
            continue
        rev = num(r.get("売上高"))
        cost = num(r.get("売上原価"))
        gross = num(r.get("売上総利益"))
        if gross is None and rev is not None and cost is not None:
            gross = rev - cost
        if gross is None:
            continue
        out[(code, year)] = {"rev": rev, "cost": cost, "gross": gross,
                             "std": (r.get("会計基準") or "").strip()}
    return out


def bs_rows(per):
    """期末日ごとの貸借対照表を、グラフの区分（百万円）に直す。直近5期まで。"""
    out = []
    for end in sorted(per)[-5:]:
        b = per[end]
        m = lambda k: yen_to_m(b.get(k))
        ta, ca, cl, tl, na, eq = m("ta"), m("ca"), m("cl"), m("tl"), m("na"), m("eq")
        if not ta:
            continue
        # 負債＋純資産が総資産と2%以上ずれるとき（取り出しの取り違え）は負債を「総資産−純資産」にそろえる
        if tl is not None and na is not None and abs(tl + na - ta) > 0.02 * abs(ta):
            tl = ta - na
        cash, recv, inv, ppe, pay = m("cash"), m("recv"), m("inv"), m("ppe"), m("pay")
        pos = lambda v: None if v is None else max(0.0, round(v, 3))
        r = {"fy": fy_label(end)[0].replace("期", ""), "fyEnd": end, "std": b.get("std"),
             "ta": ta, "tl": tl, "na": na, "noCA": ca is None}
        if ca is not None:
            r.update(cash=cash, recv=recv, inv=inv, oca=pos(ca - (cash or 0) - (recv or 0) - (inv or 0)),
                     ppe=ppe, onca=pos(ta - ca - (ppe or 0)))
        else:                                   # 銀行など流動・固定の区分が無い会社
            r.update(cash=cash, ppe=ppe, onca=pos(ta - (cash or 0) - (ppe or 0)))
        if cl is not None and tl is not None:
            r.update(pay=pay, ocl=pos(cl - (pay or 0)), ncl=pos(tl - cl))
        else:
            r.update(ncl=tl)
        if na is not None:
            e = eq if eq is not None else na
            if na <= 0:                         # 債務超過：純資産はマイナスのまま渡し、グラフ側で「債務超過」と表示
                r.update(eq=round(na, 3), oeq=0.0, neg=True)
            else:                               # 非支配持分がマイナスなど自己資本＞純資産のときも、内訳は純資産の範囲に収める
                e = min(max(e, 0.0), na)
                r.update(eq=round(e, 3), oeq=pos(na - e))
        out.append(r)
    return out


def load():
    by_year = read_csv(FUND / "fundamentals_by_year.csv")
    latest = {r["コード"]: r for r in read_csv(FUND / "fundamentals_latest.csv")}
    profile = {r["コード"]: r for r in read_csv(FUND / "company_profile.csv")}

    companies = {}
    for r in by_year:
        code = (r.get("コード") or "").strip()
        if not code:
            continue
        c = companies.setdefault(code, {
            "code": code,
            "name": (r.get("銘柄名") or "").strip(),
            "market": (r.get("市場") or "").strip(),
            "sector": (r.get("業種") or "").strip(),
            "currency": (r.get("通貨") or "").strip(),
            "annual": [],
        })
        lab, y, m = fy_label(r.get("決算期"))
        c["annual"].append({
            "fy": lab, "fyEnd": (r.get("決算期") or "").strip(), "y": y,
            "rev":  yen_to_m(num(r.get("売上高"))),
            "gp":   yen_to_m(num(r.get("売上総利益"))) if r.get("売上総利益") not in (None, "") \
                    else (lambda rv, cs: None if (rv is None or cs is None) else yen_to_m(rv - cs))(
                        num(r.get("売上高")), num(r.get("売上原価"))),
            "op":   yen_to_m(num(r.get("営業利益"))),
            "pbt":  yen_to_m(num(r.get("税引前利益"))),
            "ni":   yen_to_m(num(r.get("当期純利益"))),
            "ta":   yen_to_m(num(r.get("総資産"))),
            "se":   yen_to_m(num(r.get("自己資本"))),
            "eq":   (lambda v: None if v is None else v / 100)(num(r.get("自己資本比率(%)"))),
            "cr":   (lambda v: None if v is None else v / 100)(num(r.get("流動比率(%)"))),
            "ocf":  yen_to_m(num(r.get("営業CF"))),
            "icf":  yen_to_m(num(r.get("投資CF"))),
            "fcf":  yen_to_m(num(r.get("財務CF"))),
            "freecf": yen_to_m(num(r.get("フリーCF"))),
            "ibd":  yen_to_m(num(r.get("有利子負債"))),
            "cash": yen_to_m(num(r.get("現金同等物"))),
            "ebitda": yen_to_m(num(r.get("EBITDA"))),
            "eps":  num(r.get("EPS")),
            "bps":  num(r.get("BPS")),
            "dps":  num(r.get("一株配当")),
        })

    cos = load_cost_of_sales()
    jq = load_jq_detail()
    try:
        holders = json.loads((FUND / "shareholders.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        holders = {}
    # 貸借対照表（fetch_shareholders.py が有価証券報告書から取り出す。期末日 → 区分ごとの金額）
    bs_path = Path(os.environ["BS_JSON"]) if os.environ.get("BS_JSON") else FUND / "balance_sheet.json"
    try:
        bsheets = json.loads(bs_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        bsheets = {}

    for code, c in companies.items():
        c["annual"].sort(key=lambda a: a["fyEnd"] or "")
        # 売上原価CSVが持つ期は売上総利益を埋める（決算期の西暦 = 年度 で突き合わせ）
        for a in c["annual"]:
            if a["gp"] is not None:
                continue
            m = cos.get((code, (a["fyEnd"] or "")[:4]))
            if not m:
                continue
            a["gp"] = yen_to_m(m["gross"])
            a["cost"] = yen_to_m(m["cost"])
            a["gpStd"] = m["std"]
            # 粗利率は売上総利益と同じ出所の売上高で計算し、内部整合を保つ
            a["gpm"] = (m["gross"] / m["rev"]) if m["rev"] else None
            # 2つの出所で売上高が2%%以上ずれる期は参考値として印を付ける
            if m["rev"] and a["rev"]:
                a["gpRef"] = abs(m["rev"] / 1e6 - a["rev"]) / a["rev"] > 0.02
        for a in c["annual"]:
            a["opm"] = (a["op"] / a["rev"]) if (a["op"] is not None and a["rev"]) else None
            a["nim"] = (a["ni"] / a["rev"]) if (a["ni"] is not None and a["rev"]) else None
            if a.get("gpm") is None:
                a["gpm"] = (a["gp"] / a["rev"]) if (a["gp"] is not None and a["rev"]) else None
            a["roe"] = (a["ni"] / a["se"]) if (a["ni"] is not None and a["se"]) else None
            a["roa"] = (a["ni"] / a["ta"]) if (a["ni"] is not None and a["ta"]) else None

        attach_jq(c, jq.get(code))
        h = holders.get(code)
        c["holders"] = ({k: h.get(k) for k in ("asof", "filed", "issued", "treasury", "holders")} if h else None)
        c["bs"] = bs_rows(bsheets.get(code) or {})
        hs = c["holders"]
        if hs and hs.get("issued"):
            # 株式数の単位ずれ（千株表記など）を、記載の「割合」と突き合わせて確かめる。合わなければ割合だけで描く
            base = hs["issued"] - (hs.get("treasury") or 0)
            ok = [abs(x[1] / base - x[2]) <= max(0.003, x[2] * 0.1)
                  for x in hs["holders"] if x[1] and x[2] and base > 0]
            if ok and sum(ok) < len(ok) * 0.7:
                hs["issued"] = hs["treasury"] = None

        L = latest.get(code, {})
        c["market"] = c["market"] or (L.get("市場") or "").strip()
        c["sector"] = c["sector"] or (L.get("業種") or "").strip()
        c["quote"] = {
            "price": num(L.get("株価")),
            "priceDate": (L.get("株価日付") or "").strip(),
            "mcap": yen_to_m(num(L.get("時価総額"))),
            "per": num(L.get("PER")),
            "pbr": num(L.get("PBR")),
            "psr": num(L.get("PSR")),
            "yld": (lambda v: None if v is None else v / 100)(num(L.get("配当利回り(%)"))),
            "asof": (L.get("取得日") or "").strip(),
        }
        c["biz"] = (profile.get(code, {}).get("事業概要") or "").strip()[:400]
        u = (profile.get(code, {}).get("会社URL") or "").strip()
        c["url"] = u if u.lower().startswith(("http://", "https://")) else ""

    # 業種ごとの中央値（一目で「業種の中でどうか」を判断するための基準）
    import statistics
    buckets = {}
    for c in companies.values():
        if not c["annual"]:
            continue
        a = c["annual"][-1]
        b = buckets.setdefault(c["sector"] or "その他", [])
        b.append({"opm": a["opm"], "nim": a["nim"], "eq": a["eq"], "roe": a["roe"],
                  "gpm": a["gpm"], "per": c["quote"]["per"], "pbr": c["quote"]["pbr"],
                  "yld": c["quote"]["yld"]})
    med = {}
    for sec, rows in buckets.items():
        m = {"n": len(rows)}
        for k in ("opm", "nim", "eq", "roe", "gpm", "per", "pbr", "yld"):
            vals = [r[k] for r in rows if r[k] is not None]
            # PER/PBR は異常値が中央値を歪めるので常識的な範囲に限る
            if k == "per":
                vals = [v for v in vals if 0 < v < 200]
            if k == "pbr":
                vals = [v for v in vals if 0 < v < 30]
            m[k] = statistics.median(vals) if len(vals) >= 5 else None
        med[sec] = m
    for c in companies.values():
        c["peer"] = med.get(c["sector"] or "その他", {"n": 0})

    return companies


# ------------------------------------------------------------------ assets
STYLE = r"""
:root{
  color-scheme:light;
  --plane:#f4f4f1; --surface:#fcfcfb; --sunk:#eeeee9;
  --ink:#14140f; --ink-2:#4f4e48; --ink-3:#86857d;
  --rule:#dedcd3; --rule-s:#c3c1b5; --grid:#e5e3da; --band:rgba(42,120,214,.07);
  --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --s4:#eda100;
  --up:#006300; --down:#d03b3b; --chip:rgba(20,20,15,.05);
  --ok:#0ca30c; --wn:#fab219; --wn-ink:#8a5d00; --bad:#d03b3b;
  --c-rev:#e0504a; --c-op:#e9a14b; --c-odp:#b9d5ad; --c-ni:#5cbfb2; --c-line:#cfcfca;
  --c-ocf:#e8923c; --c-icf:#f2c84b; --c-fin:#a7df5c; --c-cash:#65a3cf; --c-free:#27418f;
  --c-div:#55a35a; --c-pay:#a9d48c;
  --b-cash:#65a3cf; --b-recv:#8fbde0; --b-inv:#b7d4ec; --b-oca:#d9e7f4; --b-ppe:#55a35a; --b-onca:#a9d48c;
  --b-pay:#e0504a; --b-ocl:#f0a7a1; --b-ncl:#c7bfe6; --b-oeq:#f7e3a6; --b-eq:#f2c84b;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  color-scheme:dark;
  --plane:#0d0d0c; --surface:#1a1a19; --sunk:#232321;
  --ink:#f7f7f4; --ink-2:#c3c2b7; --ink-3:#8d8c84;
  --rule:#2e2e2b; --rule-s:#3d3d39; --grid:#2c2c2a; --band:rgba(57,135,229,.12);
  --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500;
  --up:#0ca30c; --down:#e66767; --chip:rgba(255,255,255,.07);
  --ok:#0ca30c; --wn:#fab219; --wn-ink:#fab219; --bad:#e66767;
  --c-rev:#e8625c; --c-op:#eda955; --c-odp:#9cc28f; --c-ni:#4fb3a6; --c-line:#5f5f5a;
  --c-ocf:#ea9a47; --c-icf:#e7c04a; --c-fin:#97d14f; --c-cash:#5f9ccb; --c-free:#7f9cf0;
  --c-div:#5fae63; --c-pay:#9ccb7f;
  --b-cash:#5f9ccb; --b-recv:#4c84b2; --b-inv:#3b6890; --b-oca:#2f4b64; --b-ppe:#5fae63; --b-onca:#3f7a45;
  --b-pay:#e8625c; --b-ocl:#a85a55; --b-ncl:#6d6596; --b-oeq:#8a7a45; --b-eq:#e7c04a;
}}
:root[data-theme="dark"]{
  color-scheme:dark;
  --plane:#0d0d0c; --surface:#1a1a19; --sunk:#232321;
  --ink:#f7f7f4; --ink-2:#c3c2b7; --ink-3:#8d8c84;
  --rule:#2e2e2b; --rule-s:#3d3d39; --grid:#2c2c2a; --band:rgba(57,135,229,.12);
  --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500;
  --up:#0ca30c; --down:#e66767; --chip:rgba(255,255,255,.07);
  --ok:#0ca30c; --wn:#fab219; --wn-ink:#fab219; --bad:#e66767;
  --c-rev:#e8625c; --c-op:#eda955; --c-odp:#9cc28f; --c-ni:#4fb3a6; --c-line:#5f5f5a;
  --c-ocf:#ea9a47; --c-icf:#e7c04a; --c-fin:#97d14f; --c-cash:#5f9ccb; --c-free:#7f9cf0;
  --c-div:#5fae63; --c-pay:#9ccb7f;
  --b-cash:#5f9ccb; --b-recv:#4c84b2; --b-inv:#3b6890; --b-oca:#2f4b64; --b-ppe:#5fae63; --b-onca:#3f7a45;
  --b-pay:#e8625c; --b-ocl:#a85a55; --b-ncl:#6d6596; --b-oeq:#8a7a45; --b-eq:#e7c04a;
}
*{box-sizing:border-box}
body{margin:0;background:var(--plane);color:var(--ink);
  font-family:"Hiragino Kaku Gothic ProN","Yu Gothic",system-ui,sans-serif;
  font-size:14px;line-height:1.6;-webkit-font-smoothing:antialiased}
.wrap{max-width:1180px;margin:0 auto;padding-inline:16px;padding-block:24px 48px}
a{color:var(--s1)}
.mast{border-bottom:2px solid var(--rule-s);padding-bottom:13px}
.eyebrow{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;
  letter-spacing:.14em;text-transform:uppercase;color:var(--ink-3)}
h1{font-weight:700;font-size:clamp(22px,4vw,31px);line-height:1.2;margin:6px 0 10px;letter-spacing:-.01em}
h1 .code{font-family:ui-monospace,monospace;font-size:.62em;color:var(--ink-3);margin-left:10px;font-weight:500}
.slip{display:flex;flex-wrap:wrap;font-family:ui-monospace,monospace;font-size:11.5px;color:var(--ink-2)}
.slip div{padding-right:14px;margin-right:14px;border-right:1px solid var(--rule)}
.slip div:last-child{border-right:0;margin-right:0}
.slip b{color:var(--ink);font-weight:500}
.biz{margin:12px 0 0;font-size:12.5px;color:var(--ink-2);max-width:68ch}
.ledger{display:grid;grid-template-columns:repeat(5,1fr);background:var(--surface);
  border-bottom:1px solid var(--rule-s)}
.cell{padding:17px 17px 15px;border-right:1px solid var(--rule);min-width:0}
.cell:last-child{border-right:0}
.cell.hero{background:linear-gradient(to bottom,var(--band),transparent 70%)}
.k-lab{font-family:ui-monospace,monospace;font-size:10.5px;letter-spacing:.09em;
  text-transform:uppercase;color:var(--ink-3);display:flex;gap:6px;align-items:center}
.k-val{font-weight:700;font-size:clamp(20px,2.4vw,28px);line-height:1.1;margin-top:8px;letter-spacing:-.015em}
.k-val small{font-size:.5em;font-weight:500;color:var(--ink-2);margin-left:2px}
.k-sub{margin-top:6px;font-size:11.5px;color:var(--ink-2);display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.delta{font-family:ui-monospace,monospace;font-size:11px;padding:1px 5px;border-radius:3px;background:var(--chip);white-space:nowrap}
.delta.u{color:var(--up)} .delta.d{color:var(--down)}
.mark{font-family:ui-monospace,monospace;font-size:9px;color:var(--ink-3);
  border:1px solid var(--rule-s);border-radius:2px;padding:0 3px;line-height:1.4}
.bar{display:flex;flex-wrap:wrap;align-items:center;gap:10px 16px;padding:13px 0 14px;border-bottom:1px solid var(--rule)}
.bar .lab{font-family:ui-monospace,monospace;font-size:10.5px;letter-spacing:.09em;text-transform:uppercase;color:var(--ink-3)}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1px;background:var(--rule);border-bottom:1px solid var(--rule)}
.panel{background:var(--surface);padding:17px 17px 13px;min-width:0}
.panel.full{grid-column:1/-1}
.p-head{display:flex;align-items:baseline;justify-content:space-between;gap:12px;flex-wrap:wrap}
.p-title{font-weight:700;font-size:14.5px}
.p-unit{font-family:ui-monospace,monospace;font-size:10.5px;color:var(--ink-3);letter-spacing:.05em}
.p-sub{font-size:11.5px;color:var(--ink-2);margin:2px 0 9px}
.p-tools{display:flex;gap:6px;align-items:center}
.tbtn{background:transparent;border:1px solid var(--rule-s);border-radius:3px;font:inherit;
  font-size:11px;padding:2px 8px;color:var(--ink-2);cursor:pointer}
.tbtn[aria-pressed="true"]{background:var(--ink);color:var(--surface);border-color:var(--ink)}
.tbtn:focus-visible,input:focus-visible,select:focus-visible{outline:2px solid var(--s1);outline-offset:1px}
.legend{display:flex;flex-wrap:wrap;gap:4px 15px;margin:0 0 6px;font-size:11.5px;color:var(--ink-2)}
.legend span{display:inline-flex;align-items:center;gap:6px}
.sw{width:11px;height:11px;border-radius:2px;flex:none}
.sw.ln{height:3px;width:14px}
.sw.ln.dot{position:relative}
.legend .fcnote{color:var(--ink-3);font-size:11px}
.plot{position:relative}
.plot svg{display:block;width:100%;overflow:visible}
.tip{position:absolute;pointer-events:none;opacity:0;transition:opacity .09s;background:var(--surface);
  border:1px solid var(--rule-s);box-shadow:0 6px 18px rgba(0,0,0,.13);border-radius:5px;
  padding:8px 10px;font-size:11.5px;min-width:130px;z-index:5}
.tip h4{margin:0 0 5px;font-size:11px;font-family:ui-monospace,monospace;letter-spacing:.05em;color:var(--ink-3);font-weight:500}
.tip .row{display:flex;justify-content:space-between;gap:14px;line-height:1.7}
.tip .row i{display:inline-flex;align-items:center;gap:6px;font-style:normal;color:var(--ink-2)}
.tip .row b{font-family:ui-monospace,monospace;font-weight:500;font-variant-numeric:tabular-nums}
.kbplot{position:relative}
.kbplot svg{display:block;width:100%;overflow:visible}
.kbtip{position:absolute;pointer-events:none;opacity:0;transition:opacity .09s;background:var(--surface);
  border:1px solid var(--rule-s);box-shadow:0 6px 18px rgba(0,0,0,.13);border-radius:5px;
  padding:8px 10px;font-size:11.5px;min-width:130px;z-index:5}
.kbtip h4{margin:0 0 5px;font-size:11px;font-family:ui-monospace,monospace;letter-spacing:.05em;color:var(--ink-3);font-weight:500}
.kbtip .row{display:flex;justify-content:space-between;gap:14px;line-height:1.7}
.kbtip .row i{display:inline-flex;align-items:center;gap:6px;font-style:normal;color:var(--ink-2)}
.kbtip .row b{font-family:ui-monospace,monospace;font-weight:500;font-variant-numeric:tabular-nums}
.kbpie{display:flex;gap:22px;align-items:center;flex-wrap:wrap;padding:4px 0 6px}
.kbpie svg{flex:none;width:min(250px,100%);height:auto;margin:0 auto}
.kbleg{list-style:none;margin:0;padding:0;flex:1 1 320px;min-width:0;font-size:12.5px}
.kbleg li{display:flex;align-items:center;gap:9px;padding:4px 0;border-bottom:1px solid var(--rule)}
.kbleg li.oth{color:var(--ink-2)}
.kbleg i{width:11px;height:11px;border-radius:2px;flex:none}
.kbleg .nm{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.kbleg .sh{color:var(--ink-3);font-size:11px;font-family:ui-monospace,monospace;white-space:nowrap}
.kbleg .pc{font-family:ui-monospace,monospace;font-weight:600;min-width:4.6em;text-align:right}
.kbseg{display:flex;margin-left:10px}
.kbseg button{font:inherit;font-size:11px;padding:2px 10px;border:1px solid var(--rule-s);background:transparent;color:var(--ink-2);cursor:pointer}
.kbseg button:first-child{border-radius:3px 0 0 3px}.kbseg button:last-child{border-radius:0 3px 3px 0;border-left:0}
.kbseg button[aria-pressed="true"]{background:var(--ink);color:var(--surface);border-color:var(--ink)}
.kblegend{display:flex;flex-wrap:wrap;gap:3px 13px;margin:0 0 6px;font-size:11.5px;color:var(--ink-2)}
.kblegend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px}
.site{margin:8px 0 0}
.site a{display:inline-flex;align-items:baseline;gap:8px;font-size:12px;text-decoration:none;color:var(--ink-2);
  border:1px solid var(--rule-s);border-radius:6px;padding:3px 10px;max-width:100%}
.site a b{color:var(--ink);font-weight:600;white-space:nowrap}
.site a span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-family:ui-monospace,monospace;font-size:11px}
.site a:hover{border-color:var(--s1)}
.kbzoomable{cursor:zoom-in}
.kbzoom{position:fixed;inset:0;z-index:60;background:rgba(0,0,0,.5);display:flex;align-items:center;justify-content:center;padding:14px}
.kbzbox{position:relative;background:var(--surface);color:var(--ink);border-radius:12px;width:min(1100px,100%);max-height:calc(100vh - 28px);
  overflow:auto;padding:16px 18px 12px;box-shadow:0 12px 40px rgba(0,0,0,.35)}
.kbzclose{position:absolute;top:6px;right:8px;z-index:2;border:0;background:transparent;font-size:26px;line-height:1;color:var(--ink-2);cursor:pointer;padding:4px 10px}
.kbzbody>.p-head,.kbzbody>div>.p-head,.kbzbody>.fh,.kbzbody>div>.fh{padding-right:40px}
.kbzbody .fh{font-size:15px}.kbzbody .fl,.kbzbody .legend,.kbzbody .kblegend{font-size:12.5px}
.kbzbody .kbzoomable{cursor:default}
.kbzbody .kbpie svg{width:min(340px,78vw)}.kbzbody .kbleg{font-size:13px}.kbzbody .kbleg .sh{display:inline}
html.kbz-open{overflow:hidden}
.kbzbody .kbzhead{padding:0;background:transparent;border:0;grid-column:auto;min-width:0}
.kbempty{padding:26px 0 30px;text-align:center;color:var(--ink-3);font-size:12.5px;border:1px dashed var(--rule-s);border-radius:5px;margin-top:6px}
.empty{padding:26px 0 30px;text-align:center;color:var(--ink-3);font-size:12.5px;
  border:1px dashed var(--rule-s);border-radius:5px;margin-top:6px}
.tblwrap{overflow-x:auto;margin-top:4px}
table{border-collapse:collapse;width:100%;font-size:12px;font-variant-numeric:tabular-nums}
th,td{padding:5px 9px;text-align:right;border-bottom:1px solid var(--rule);white-space:nowrap}
th{font-family:ui-monospace,monospace;font-size:10px;letter-spacing:.06em;text-transform:uppercase;
  color:var(--ink-3);font-weight:500;border-bottom:1px solid var(--rule-s)}
th:first-child,td:first-child{text-align:left;position:sticky;left:0;background:var(--surface)}
tbody tr:hover td{background:var(--sunk)}
td.na,th.na{color:var(--ink-3)}
.foot{padding-top:20px;font-size:11.5px;color:var(--ink-2)}
.foot h2{font-size:13px;margin:0 0 8px;color:var(--ink)}
.foot ol{margin:0;padding-left:1.4em} .foot li{margin-bottom:5px}
/* index */
.tools{display:flex;flex-wrap:wrap;gap:10px;align-items:center;padding:14px 0;border-bottom:1px solid var(--rule)}
input[type=search],select{font:inherit;font-size:13px;padding:6px 10px;border:1px solid var(--rule-s);
  border-radius:4px;background:var(--surface);color:var(--ink)}
input[type=search]{min-width:min(280px,100%);flex:1 1 220px}
#count{font-family:ui-monospace,monospace;font-size:11.5px;color:var(--ink-3);margin-left:auto}
#list{background:var(--surface);border-bottom:1px solid var(--rule-s)}
#list table{font-size:12.5px}
#list th{cursor:pointer;user-select:none;position:sticky;top:0;background:var(--surface);z-index:2}
#list th[aria-sort]:after{content:" ▾";color:var(--ink-3)}
#list th[aria-sort=ascending]:after{content:" ▴"}
/* 判定カード */
.cards{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:1px;background:var(--rule);
  border-bottom:1px solid var(--rule-s);margin-top:0}
.card{background:var(--surface);padding:14px 16px 11px;min-width:0}
.c-top{display:flex;justify-content:space-between;align-items:center;gap:8px}
.c-name{font-size:12px;color:var(--ink-2);font-weight:600}
.c-chip{display:inline-flex;align-items:center;gap:4px;font-size:11px;font-weight:600;
  padding:2px 8px 2px 7px;border-radius:999px;background:var(--chip);white-space:nowrap}
.c-chip i{width:7px;height:7px;border-radius:50%;flex:none}
.st-good .c-chip{color:var(--ok)}   .st-good .c-chip i{background:var(--ok)}
.st-warn .c-chip{color:var(--wn-ink)} .st-warn .c-chip i{background:var(--wn)}
.st-bad  .c-chip{color:var(--bad)}  .st-bad  .c-chip i{background:var(--bad)}
.st-flat .c-chip{color:var(--ink-2)} .st-flat .c-chip i{background:var(--ink-3)}
.st-none .c-chip{color:var(--ink-3);font-weight:500} .st-none .c-chip i{background:var(--rule-s)}
.c-val{font-weight:700;font-size:clamp(22px,2.6vw,30px);line-height:1.1;margin-top:10px;letter-spacing:-.015em}
.c-val small{font-size:.5em;font-weight:500;color:var(--ink-2);margin-left:2px}
.c-sub{margin-top:4px;font-size:11.5px;color:var(--ink-3);line-height:1.5}
.biz{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
details.more{background:var(--surface);border-bottom:1px solid var(--rule)}
details.more summary{cursor:pointer;padding:12px 17px;font-size:13px;color:var(--ink-2);font-weight:600;list-style:none}
details.more summary::-webkit-details-marker{display:none}
details.more summary:before{content:"\25B8  ";color:var(--ink-3)}
details.more[open] summary:before{content:"\25BE  "}
details.more summary:focus-visible{outline:2px solid var(--s1);outline-offset:-2px}
details.more .inner{padding:0 17px 15px}
details.more .inner.foot{padding-top:0;font-size:12px}
@media (max-width:980px){.cards{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media (max-width:560px){.cards{grid-template-columns:repeat(2,minmax(0,1fr))}}
/* 評価サマリー帯 */
.strip{display:grid;grid-template-columns:repeat(5,1fr);background:var(--surface);
  border-bottom:1px solid var(--rule-s);border-top:1px solid var(--rule-s)}
.v{padding:13px 15px 12px;border-right:1px solid var(--rule);min-width:0}
.v:last-child{border-right:0}
.v-top{display:flex;align-items:center;gap:7px}
.v-dot{width:9px;height:9px;border-radius:50%;flex:none}
.v-name{font-size:11.5px;color:var(--ink-2);font-weight:500}
.v-state{margin-top:5px;font-weight:700;font-size:15px;letter-spacing:-.01em;display:flex;align-items:center;gap:5px}
.v-state .ico{font-size:12px;font-family:ui-monospace,monospace}
.v-note{margin-top:3px;font-size:11px;color:var(--ink-3);font-variant-numeric:tabular-nums;
  overflow-wrap:anywhere}
.v.good .v-dot{background:var(--ok)} .v.good .v-state{color:var(--ok)}
.v.warn .v-dot{background:var(--wn)} .v.warn .v-state{color:var(--wn-ink)}
.v.bad  .v-dot{background:var(--bad)} .v.bad  .v-state{color:var(--bad)}
.v.flat .v-dot{background:var(--ink-3)} .v.flat .v-state{color:var(--ink)}
.v.none .v-dot{background:var(--rule-s)} .v.none .v-state{color:var(--ink-3);font-weight:500;font-size:13px}
.spark{display:block;margin-top:9px;width:100%;height:24px}
/* 一覧の判定チップ */
.chip{display:inline-flex;align-items:center;gap:5px;font-size:11.5px;white-space:nowrap}
.chip i{width:8px;height:8px;border-radius:50%;flex:none;font-style:normal}
@media (max-width:980px){.strip{grid-template-columns:repeat(3,1fr)}
  .v{border-bottom:1px solid var(--rule)}.v:nth-child(3n){border-right:0}}
@media (max-width:560px){.strip{grid-template-columns:repeat(2,1fr)}
  .v:nth-child(3n){border-right:1px solid var(--rule)}.v:nth-child(2n){border-right:0}}
@media (max-width:860px){
  .ledger{grid-template-columns:repeat(2,1fr)}
  .cell{border-bottom:1px solid var(--rule)}
  .cell:nth-child(2n){border-right:0}
  .cell.hero{grid-column:1/-1}
  .grid{grid-template-columns:1fr}
}
@media (max-width:460px){.ledger{grid-template-columns:1fr}.cell{border-right:0}}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
"""

APP = r"""
"use strict";
var CHO = 1e6; // 1兆円 = 1,000,000 百万円
function css(v){ return getComputedStyle(document.documentElement).getPropertyValue(v).trim(); }
function fmtMoney(v){
  if(v==null) return {n:"—",u:""};
  var a=Math.abs(v);
  if(a>=CHO) return {n:(v/CHO).toFixed(2), u:"兆円"};
  if(a>=100) return {n:(v/100).toFixed(0).replace(/\B(?=(\d{3})+(?!\d))/g,","), u:"億円"};
  return {n:Math.round(v).toLocaleString(), u:"百万円"};
}
function money(v){ var o=fmtMoney(v); return v==null? "—" : o.n+o.u; }
function pct(v,d){ return v==null? "—" : (v*100).toFixed(d==null?1:d)+"%"; }
function signPct(v){ return v==null? "—" : (v>0?"+":"")+(v*100).toFixed(1)+"%"; }
function yoy(a,b){ return (a==null||b==null||b===0)? null : a/b-1; }
function numf(v,d){ return v==null? "—" : v.toFixed(d==null?2:d); }

function niceTicks(lo,hi,n){
  var span=(hi-lo)||1, raw=span/(n||4), mag=Math.pow(10,Math.floor(Math.log10(raw))), r=raw/mag;
  var step=(r<1.5?1:r<3?2:r<7?5:10)*mag, t=[];
  for(var v=Math.floor(lo/step)*step; v<=hi+step*0.5; v+=step) t.push(+v.toFixed(10));
  return t;
}

function Chart(host, cfg){
  var wrap=document.createElement("div"); wrap.className="plot";
  var tip=document.createElement("div"); tip.className="tip";
  host.appendChild(wrap); wrap.appendChild(tip);
  var rows=cfg.rows;
  function draw(){
    var W=wrap.clientWidth||460; if(W<40) return;
    var narrow=W<380, H=cfg.height||(narrow?188:210);
    var mL=narrow?40:50, mR=10, mT=10, mB=narrow?28:26;
    var n=rows.length; if(!n) return;
    var iw=Math.max(40,W-mL-mR), ih=Math.max(40,H-mT-mB);
    var keys=cfg.series.map(function(s){return s.key;}), vals=[];
    rows.forEach(function(r){ keys.forEach(function(k){ if(r[k]!=null) vals.push(r[k]); }); });
    if(!vals.length){ wrap.innerHTML='<div class="empty">データなし</div>'; return; }
    var dmax=Math.max.apply(null,vals), dmin=Math.min.apply(null,vals);
    var lo = cfg.zero===false ? dmin-(dmax-dmin||Math.abs(dmax)||1)*0.2 : Math.min(0,dmin);
    var hi = dmax + (dmax-lo)*0.08;
    if(hi===lo){ hi=lo+1; }
    var ticks=niceTicks(lo,hi,narrow?3:4);
    lo=Math.min(lo,ticks[0]); hi=Math.max(hi,ticks[ticks.length-1]);
    function Y(v){ return mT+ih-(v-lo)/(hi-lo)*ih; }
    var band=iw/n; function Xc(i){ return mL+band*(i+0.5); }
    var g=[], zeroY=Y(Math.min(Math.max(0,lo),hi));

    if(cfg.highlightLast){
      var hs=Math.max(0,n-cfg.highlightLast);
      g.push('<rect x="'+(mL+band*hs).toFixed(1)+'" y="'+mT+'" width="'+(band*(n-hs)).toFixed(1)+'" height="'+ih+'" fill="'+css("--band")+'"/>');
    }
    ticks.forEach(function(t){
      var y=Y(t).toFixed(1);
      g.push('<line x1="'+mL+'" x2="'+(mL+iw)+'" y1="'+y+'" y2="'+y+'" stroke="'+(t===0?css("--rule-s"):css("--grid"))+'" stroke-width="1"/>');
      g.push('<text x="'+(mL-7)+'" y="'+y+'" text-anchor="end" dominant-baseline="middle" font-size="'+(narrow?9:10)+'" font-family="ui-monospace,monospace" fill="'+css("--ink-3")+'">'+cfg.ytick(t)+'</text>');
    });
    var every=Math.max(1,Math.ceil(n/(narrow?5:10)));
    rows.forEach(function(r,i){
      if(i%every!==0 && i!==n-1) return;
      g.push('<text x="'+Xc(i).toFixed(1)+'" y="'+(mT+ih+14)+'" text-anchor="middle" font-size="'+(narrow?9:10)+'" font-family="ui-monospace,monospace" fill="'+css("--ink-3")+'">'+cfg.xtick(r)+'</text>');
    });

    if(cfg.type==="bar"){
      var nb=cfg.series.length, pad=Math.min(9,band*0.16), slot=(band-pad*2)/nb;
      cfg.series.forEach(function(s,si){
        var col=css(s.color);
        rows.forEach(function(r,i){
          var v=r[s.key]; if(v==null) return;
          var y0=Y(Math.max(0,v)), y1=Y(Math.min(0,v));
          var x=mL+band*i+pad+slot*si+(nb>1?1:0), w=Math.max(1.5,slot-(nb>1?2:0));
          g.push('<rect x="'+x.toFixed(1)+'" y="'+y0.toFixed(1)+'" width="'+w.toFixed(1)+'" height="'+Math.max(1.5,Math.abs(y1-y0)).toFixed(1)+'" rx="'+Math.min(4,w/2).toFixed(1)+'" fill="'+col+'"/>');
        });
      });
    } else {
      cfg.series.forEach(function(s){
        var col=css(s.color), seg=[], parts=[];
        rows.forEach(function(r,i){
          if(r[s.key]==null){ if(seg.length){parts.push(seg); seg=[];} return; }
          seg.push([Xc(i),Y(r[s.key]),r]);
        });
        if(seg.length) parts.push(seg);
        parts.forEach(function(p){
          if(p.length===1){ g.push('<circle cx="'+p[0][0].toFixed(1)+'" cy="'+p[0][1].toFixed(1)+'" r="3.2" fill="'+col+'"/>'); return; }
          g.push('<path d="'+p.map(function(q,i){return (i?"L":"M")+q[0].toFixed(1)+" "+q[1].toFixed(1);}).join(" ")+'" fill="none" stroke="'+col+'" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>');
        });
        var flat=[]; parts.forEach(function(p){flat=flat.concat(p);});
        if(flat.length){ var e=flat[flat.length-1];
          g.push('<circle cx="'+e[0].toFixed(1)+'" cy="'+e[1].toFixed(1)+'" r="4" fill="'+col+'" stroke="'+css("--surface")+'" stroke-width="2"/>'); }
        if(s.hollowWhen){ flat.forEach(function(q){ if(!s.hollowWhen(q[2])) return;
          g.push('<circle cx="'+q[0].toFixed(1)+'" cy="'+q[1].toFixed(1)+'" r="3.4" fill="'+css("--surface")+'" stroke="'+col+'" stroke-width="2"/>'); }); }
      });
    }
    g.push('<line id="xh" x1="0" x2="0" y1="'+mT+'" y2="'+(mT+ih)+'" stroke="'+css("--rule-s")+'" stroke-width="1" opacity="0"/>');
    g.push('<line x1="'+mL+'" x2="'+(mL+iw)+'" y1="'+zeroY.toFixed(1)+'" y2="'+zeroY.toFixed(1)+'" stroke="'+css("--rule-s")+'" stroke-width="1"/>');

    wrap.querySelectorAll("svg").forEach(function(s){s.remove();});
    wrap.insertAdjacentHTML("afterbegin",
      '<svg viewBox="0 0 '+W+' '+H+'" width="'+W+'" height="'+H+'" role="img" aria-label="'+cfg.aria+'">'+g.join("")+'</svg>');

    var el=wrap.querySelector("svg"), xh=el.querySelector("#xh");
    function move(ev){
      var rect=el.getBoundingClientRect();
      var x=(ev.touches?ev.touches[0].clientX:ev.clientX)-rect.left;
      var i=Math.max(0,Math.min(n-1,Math.floor((x-mL)/band))), r=rows[i];
      xh.setAttribute("x1",Xc(i).toFixed(1)); xh.setAttribute("x2",Xc(i).toFixed(1)); xh.setAttribute("opacity","0.8");
      tip.innerHTML='<h4>'+cfg.tipTitle(r)+'</h4>'+cfg.series.map(function(s){
        return '<div class="row"><i><span class="sw'+(cfg.type==="bar"?"":" ln")+'" style="background:'+css(s.color)+'"></span>'+s.name+'</i><b>'+cfg.tipVal(r[s.key],r,s)+'</b></div>';
      }).join("");
      tip.style.opacity="1";
      tip.style.left=Math.max(2,Math.min(W-tip.offsetWidth-2,Xc(i)-tip.offsetWidth/2))+"px";
      tip.style.top="4px";
    }
    function leave(){ tip.style.opacity="0"; xh.setAttribute("opacity","0"); }
    el.addEventListener("mousemove",move); el.addEventListener("mouseleave",leave);
    el.addEventListener("touchstart",move,{passive:true});
    el.addEventListener("touchmove",move,{passive:true});
    el.addEventListener("touchend",leave);
  }
  new ResizeObserver(draw).observe(wrap);
  return {redraw:draw, setRows:function(r){rows=r; draw();}};
}

function tableHTML(rows, cols){
  return '<div class="tblwrap"><table><thead><tr>'+cols.map(function(c){return '<th>'+c.h+'</th>';}).join("")
    +'</tr></thead><tbody>'+rows.map(function(r){return '<tr>'+cols.map(function(c){
      var v=c.f(r); return '<td'+(v==="—"?' class="na"':'')+'>'+v+'</td>';}).join("")+'</tr>';}).join("")
    +'</tbody></table></div>';
}

function panel(host, o){
  host.innerHTML='<div class="p-head"><div class="p-title">'+o.title+'</div>'
    +'<div class="p-tools"><span class="p-unit">'+o.unit+'</span>'
    +(o.cols?'<button type="button" class="tbtn" aria-pressed="false">表</button>':'')+'</div></div>'
    +(o.sub?'<div class="p-sub">'+o.sub+'</div>':'')
    +(o.series.length>1?'<div class="legend">'+o.series.map(function(s){
        return '<span><span class="sw'+(o.chart.type==="bar"?"":" ln")+'" style="background:var('+s.color+')"></span>'+s.name+'</span>';}).join("")+'</div>':'');
  if(!o.chart.rows.length){
    host.insertAdjacentHTML("beforeend",'<div class="empty">'+(o.emptyText||"データなし")+'</div>');
    return null;
  }
  var ph=document.createElement("div"); host.appendChild(ph);
  var ch=Chart(ph,Object.assign({},o.chart,{series:o.series}));
  if(o.cols){
    var th=document.createElement("div"); th.hidden=true; host.appendChild(th);
    th.innerHTML=tableHTML(o.chart.rows.slice().reverse(),o.cols);
    var b=host.querySelector(".tbtn");
    b.addEventListener("click",function(){
      var on=b.getAttribute("aria-pressed")==="true";
      b.setAttribute("aria-pressed",String(!on));
      ph.hidden=!on; th.hidden=on; if(on) ch.redraw();
    });
  }
  return ch;
}


function panel2(host, o){
  var leg=o.bars.map(function(s){return '<span><span class="sw" style="background:var('+s.color+')"></span>'+s.name+'</span>';})
    .concat(o.lines.map(function(s){return '<span><span class="sw ln" style="background:var('+(s.dot||s.color)+')"></span>'+s.name+(s.axis==="R"?'（右軸）':'')+'</span>';}));
  host.innerHTML='<div class="p-head"><div class="p-title">'+o.title+'</div>'
    +'<div class="p-tools"><span class="p-unit">'+o.unit+'</span>'
    +(o.cols?'<button type="button" class="tbtn" aria-pressed="false">表</button>':'')+'</div></div>'
    +(o.sub?'<div class="p-sub">'+o.sub+'</div>':'')
    +(leg.length?'<div class="legend">'+leg.join("")+'</div>':'');
  if(!o.rows.length || !leg.length){
    host.insertAdjacentHTML("beforeend",'<div class="empty">'+(o.emptyText||"データなし")+'</div>');
    return null;
  }
  var ph=document.createElement("div"); host.appendChild(ph);
  var ch=Combo(ph,o);
  if(o.cols){
    var th=document.createElement("div"); th.hidden=true; host.appendChild(th);
    th.innerHTML=tableHTML(o.rows.slice().reverse(),o.cols);
    var b=host.querySelector(".tbtn");
    b.addEventListener("click",function(){
      var on=b.getAttribute("aria-pressed")==="true";
      b.setAttribute("aria-pressed",String(!on));
      ph.hidden=!on; th.hidden=on; if(on) ch.redraw();
    });
  }
  return ch;
}

function spark(vals,color){
  var w=160,h=24,p=3, ok=vals.filter(function(v){return v!=null;});
  if(ok.length<2) return "";
  var mn=Math.min.apply(null,ok), mx=Math.max.apply(null,ok), sp=(mx-mn)||Math.abs(mx)||1;
  var lo=Math.min(mn,0)===0&&mn>=0?mn:mn;
  var pts=[];
  for(var i=0;i<vals.length;i++){
    if(vals[i]==null) continue;
    pts.push([p+i*(w-2*p)/(vals.length-1), h-p-(vals[i]-lo)/sp*(h-2*p)]);
  }
  if(pts.length<2) return "";
  var d=pts.map(function(q,i){return (i?"L":"M")+q[0].toFixed(1)+" "+q[1].toFixed(1);}).join(" ");
  var e=pts[pts.length-1];
  return '<svg class="spark" viewBox="0 0 '+w+' '+h+'" preserveAspectRatio="none" aria-hidden="true">'
    +'<path d="'+d+'" fill="none" stroke="'+color+'" stroke-width="1.6" vector-effect="non-scaling-stroke" stroke-linejoin="round"/>'
    +'<circle cx="'+e[0].toFixed(1)+'" cy="'+e[1].toFixed(1)+'" r="2.5" fill="'+color+'"/></svg>';
}

var ICO={good:"▲",warn:"▼",bad:"▼",flat:"●",none:"—"};

/* 判定：直近通期を業種中央値と比べる。▲＝良い側 ●＝並み ▼＝注意 */
function levelOf(C){
  var A=C.annual||[], P=C.peer||{}, n=A.length, last=A[n-1]||{}, first=A[0]||{}, q=C.quote||{}, r={};
  var cagr=null;
  if(n>=2 && first.rev>0 && last.rev>0) cagr=Math.pow(last.rev/first.rev,1/(n-1))-1;
  if(cagr==null) r.g={st:"none",lab:"データなし"};
  else {
    var opDown=(last.op!=null && first.op!=null && last.op<first.op);
    var g=cagr<0?"bad":(cagr>=0.05?(opDown?"warn":"good"):"flat");
    r.g={st:g,lab:{bad:"減収",warn:"増収減益",good:"増収増益",flat:"横ばい"}[g]};
  }
  if(last.opm==null) r.p={st:"none",lab:"データなし"};
  else {
    var m=P.opm, p;
    if(last.opm<0) p="bad";
    else if(m!=null) p=last.opm>=m*1.2?"good":(last.opm<m*0.6?"warn":"flat");
    else p=last.opm>=0.10?"good":(last.opm<0.03?"warn":"flat");
    r.p={st:p,lab:{bad:"赤字",good:"高い",warn:"低い",flat:"並み"}[p]};
  }
  if(last.eq==null) r.f={st:"none",lab:"データなし"};
  else {
    var me=P.eq, f;
    if(last.eq<0.10 && (me==null || last.eq<me*0.8)) f="bad";
    else if(last.eq<0.20) f=(me!=null && last.eq>=me)?"flat":"warn";
    else f=(last.eq>=0.50 || (me!=null && last.eq>=me*1.3))?"good":"flat";
    r.f={st:f,lab:{bad:"薄い",warn:"やや薄い",good:"厚い",flat:"標準"}[f]};
  }
  if(last.roe==null) r.e={st:"none",lab:"データなし"};
  else {
    var e=last.roe<0?"bad":(last.roe>=0.10?"good":(last.roe<0.05?"warn":"flat"));
    r.e={st:e,lab:{bad:"赤字",good:"高い",warn:"低い",flat:"標準"}[e]};
  }
  if(q.per==null && q.pbr==null) r.v={st:"none",lab:"データなし"};
  else {
    var cheap=0, rich=0;
    if(q.per!=null && P.per!=null){ if(q.per<P.per) cheap++; else rich++; }
    if(q.pbr!=null && P.pbr!=null){ if(q.pbr<P.pbr) cheap++; else rich++; }
    var v=(P.per==null&&P.pbr==null)?"flat":(cheap>=2?"good":(rich>=2?"warn":"flat"));
    r.v={st:v,lab:{good:"割安",warn:"割高",flat:"並み"}[v]};
  }
  return r;
}

function renderCompany(C){
  var A=C.annual||[], P=C.peer||{}, q=C.quote||{};
  var last=A[A.length-1]||{}, prev=A[A.length-2]||{};
  var el=function(id){return document.getElementById(id);};

  el("slip").innerHTML=[
    ["市場",C.market||"—"],["業種",C.sector||"—"],
    ["株価",q.price!=null?q.price.toLocaleString()+"円":"—"],
    ["時価総額",money(q.mcap)],["決算期",last.fy||"—"]
  ].map(function(x){return "<div>"+x[0]+" <b>"+x[1]+"</b></div>";}).join("");

  /* ---- 上段：判定カード5枚 ---- */
  var L=levelOf(C);
  var vs=function(v){return v==null?"":" ・ 業種 "+pct(v);};
  function card(name,lv,val,unit,sub,sp){
    return '<div class="card st-'+lv.st+'"><div class="c-top"><span class="c-name">'+name+'</span>'
      +'<span class="c-chip"><span aria-hidden="true">'+ICO[lv.st]+'</span>'+lv.lab+'</span></div>'
      +'<div class="c-val">'+val+'<small>'+(unit||"")+'</small></div>'
      +'<div class="c-sub">'+sub+'</div>'+(sp||"")+'</div>';
  }
  function pv(x){ return x==null? ["—",""] : [(x*100).toFixed(1),"%"]; }
  var mr=fmtMoney(last.rev), po=pv(last.opm), pe=pv(last.eq), pr=pv(last.roe);
  var col=function(v){return css(v);};
  el("cards").innerHTML=[
    card("成長性",L.g,mr.n,mr.u,"売上高 ・ 前期比 "+signPct(yoy(last.rev,prev.rev)),
         spark(A.map(function(r){return r.rev;}),col("--s1"))),
    card("収益性",L.p,po[0],po[1],"営業利益率"+vs(P.opm),
         spark(A.map(function(r){return r.opm;}),col("--s3"))),
    card("財務安全性",L.f,pe[0],pe[1],"自己資本比率"+vs(P.eq),
         spark(A.map(function(r){return r.eq;}),col("--s1"))),
    card("資本効率",L.e,pr[0],pr[1],"ROE"+vs(P.roe),
         spark(A.map(function(r){return r.roe;}),col("--s4"))),
    card("割安度",L.v,q.per==null?"—":q.per.toFixed(1),q.per==null?"":"倍",
         "PER ・ PBR "+numf(q.pbr,2)+"倍"+(P.per!=null?"<br>業種 "+numf(P.per,1)+"倍 / "+numf(P.pbr,2)+"倍":""),"")
  ].join("");

  /* ---- チャート4枚：データの無い系列は出さない ---- */
  function S(list){ return list.filter(function(s){ return A.some(function(r){return r[s.key]!=null;}); }); }
  function decFor(st){ return st>=1?0:(st>=0.1?1:2); }
  function stepOf(tk){ return tk&&tk.length>1?Math.abs(tk[1]-tk[0]):0; }
  /* 目盛りは軸全体で単位をそろえる（兆の軸なら0.5兆、億の軸なら億） */
  var choTick=function(t,tk){ var mx=Math.max.apply(null,(tk||[t]).map(Math.abs)), st=stepOf(tk);
    if(t===0) return "0";
    return mx>=CHO? (t/CHO).toFixed(decFor(st/CHO))+"兆" : (t/100).toFixed(decFor(st/100)); };
  var pctTick=function(t,tk){ return (t*100).toFixed(decFor(stepOf(tk)*100||1))+"%"; };
  var tipM=function(v){ return money(v); };
  var tipP=function(v,r,s){ return v==null?"—":pct(v)+(s.key==="gpm"&&r.gpRef?"（参考）":""); };
  var aTitle=function(r){ return r.fy+"（"+r.fyEnd+"）"; };
  var aTick=function(r){ return r.fy.replace("期",""); };
  var base={rows:A,tipTitle:aTitle,xtick:aTick};
  function ch(o){ return Object.assign({},base,o); }

  var AF=A.concat(C.fc?[C.fc]:[]), Q=C.quarters||[], odpName=C.odpName||"経常利益";
  function has(rows,k){ return rows.some(function(r){return r[k]!=null;}); }
  function F(rows,list){ return list.filter(function(s){ return has(rows,s.key); }); }
  var tipP=function(v){ return v==null?"—":pct(v); };
  var aTitle2=function(r){ return r.fc? r.fy.replace("予","")+"（会社予想・"+(r.disc||"")+"開示）" : aTitle(r); };
  var aTick2=function(r){ return r.fy.replace("期",""); };
  var yenTick=function(t){ return t%1? t.toFixed(1) : String(t); };
  var yen=function(v){ return v==null?"—":(v%1? v.toFixed(2):v.toFixed(0))+"円"; };
  var mcol=function(h,k){ return {h:h,f:function(r){return money(r[k]);}}; };
  var fyCol={h:"決算期",f:function(r){return r.fy;}};

  panel2(el("p-annual"),{title:"通期決算",unit:"億円 / %",
    sub:C.fc?"右端の薄い棒は今期の会社予想":"",
    rows:AF, aria:"通期決算",
    bars:F(AF,[{key:"rev",name:"売上高",color:"--c-rev"},{key:"op",name:"営業利益",color:"--c-op"},
               {key:"odp",name:odpName,color:"--c-odp"},{key:"ni",name:"純利益",color:"--c-ni"}]),
    lines:F(AF,[{key:"opm",name:"営業利益率",color:"--c-line",dot:"--c-op",axis:"R"}]),
    yl:choTick, yr:pctTick, tipL:tipM, tipR:tipP, tipTitle:aTitle2, xtick:aTick2,
    cols:[fyCol,mcol("売上高","rev"),mcol("営業利益","op"),mcol(odpName,"odp"),mcol("純利益","ni"),
          {h:"営業利益率",f:function(r){return pct(r.opm);}}]});

  panel2(el("p-cf"),{title:"キャッシュフロー",unit:"億円",
    rows:A, aria:"通期のキャッシュフロー",
    bars:F(A,[{key:"ocf",name:"営業CF",color:"--c-ocf"},{key:"icf",name:"投資CF",color:"--c-icf"},
              {key:"fcf",name:"財務CF",color:"--c-fin"},{key:"cash",name:"現預金等",color:"--c-cash"}]),
    lines:F(A,[{key:"frcf",name:"フリーCF",color:"--c-free",axis:"L",w:2.5}]),
    yl:choTick, yr:pctTick, tipL:tipM, tipR:tipP, tipTitle:aTitle, xtick:aTick2,
    cols:[fyCol,mcol("営業CF","ocf"),mcol("投資CF","icf"),mcol("財務CF","fcf"),mcol("フリーCF","frcf"),mcol("現預金等","cash")]});

  panel2(el("p-q"),{title:"四半期決算",unit:"億円 / %",
    sub:Q.length?"単独四半期（累計の差分）":"",
    rows:Q, aria:"四半期決算", emptyText:"四半期データなし（決算短信が未取得）",
    bars:F(Q,[{key:"rev",name:"売上高",color:"--c-rev"},{key:"op",name:"営業利益",color:"--c-op"},
              {key:"odp",name:"経常利益",color:"--c-odp"},{key:"ni",name:"純利益",color:"--c-ni"}]),
    lines:F(Q,[{key:"opm",name:"営業利益率",color:"--c-line",dot:"--c-op",axis:"R"}]),
    yl:choTick, yr:pctTick, tipL:tipM, tipR:tipP,
    tipTitle:function(r){ return r.fy+"（〜"+r.perEnd+"）"; }, xtick:function(r){ return r.fy; },
    cols:[{h:"四半期",f:function(r){return r.fy;}},mcol("売上高","rev"),mcol("営業利益","op"),mcol("経常利益","odp"),
          mcol("純利益","ni"),{h:"営業利益率",f:function(r){return pct(r.opm);}}]});

  panel2(el("p-div"),{title:"配当",unit:"円 / %",
    sub:(C.fc&&C.fc.dps!=null)?"右端の薄い棒は今期の会社予想":"",
    rows:(C.fc&&C.fc.dps!=null)?AF:A, aria:"一株配当と配当性向", emptyText:"配当データなし",
    bars:F(A,[{key:"dps",name:"配当金",color:"--c-div"}]),
    lines:F(AF,[{key:"payout",name:"配当性向",color:"--c-pay",axis:"R"}]),
    yl:yenTick, yr:pctTick, tipL:yen, tipR:tipP, tipTitle:aTitle2, xtick:aTick2,
    cols:[fyCol,{h:"配当金",f:function(r){return yen(r.dps);}},{h:"配当性向",f:function(r){return pct(r.payout);}},
          {h:"EPS",f:function(r){return yen(r.eps);}}]});

  var bp=el("p-bs"), BS=C.bs||[];
  bp.innerHTML='<div class="p-head"><div class="p-title">貸借対照表</div><span class="p-unit" style="margin-left:auto">'+(BS.length?(BS[BS.length-1].std==="IFRS"?"IFRS":"日本基準"):"")+'</span></div>';
  if(BS.length) kbBS(bp, BS); else bp.hidden=true;   // データの無い銘柄（米国基準など）は枠ごと出さない

  var HS=C.holders, hp=el("p-holders");
  hp.innerHTML='<div class="p-head"><div class="p-title">株主構成</div><span class="p-unit">発行済株式に対する割合</span></div>'
    +(HS?'<div class="p-sub">有価証券報告書（'+(HS.asof||"").slice(0,7).replace("-","年")+'月末時点・'+(HS.filed||"")+'提出）の大株主上位10名と自己株式</div>':'');
  kbPie(hp, HS);

  /* ---- 折りたたみの詳細表：全期が空の列は出さない ---- */
  var cols=[
    {h:"決算期",f:function(r){return r.fy;}},
    {h:"売上高",k:"rev",f:function(r){return money(r.rev);}},
    {h:"売上総利益",k:"gp",f:function(r){return money(r.gp);}},
    {h:"営業利益",k:"op",f:function(r){return money(r.op);}},
    {h:"当期純利益",k:"ni",f:function(r){return money(r.ni);}},
    {h:"粗利率",k:"gpm",f:function(r){return r.gpm==null?"—":pct(r.gpm)+(r.gpRef?"（参考）":"");}},
    {h:"営業利益率",k:"opm",f:function(r){return pct(r.opm);}},
    {h:"ROE",k:"roe",f:function(r){return pct(r.roe);}},
    {h:"自己資本比率",k:"eq",f:function(r){return pct(r.eq);}},
    {h:"営業CF",k:"ocf",f:function(r){return money(r.ocf);}},
    {h:"EPS",k:"eps",f:function(r){return r.eps==null?"—":numf(r.eps)+"円";}},
    {h:"配当",k:"dps",f:function(r){return r.dps==null?"—":numf(r.dps)+"円";}}
  ].filter(function(c){ return !c.k || A.some(function(r){return r[c.k]!=null;}); });
  el("t-annual").innerHTML=tableHTML(A.slice().reverse(),cols);
}

/* ---------------- index page ---------------- */
function renderIndex(ROWS){
  var q=document.getElementById("q"), sec=document.getElementById("sec"), mk=document.getElementById("mk");
  var list=document.getElementById("list"), count=document.getElementById("count");
  var sortKey="mcap", sortAsc=false;
  var COLS=[
    {k:"name",h:"銘柄",f:function(r){return '<a href="'+r.code+'.html">'+r.name+'</a> <span style="color:var(--ink-3);font-size:11px">'+r.code+'</span>';},t:"s"},
    {k:"sector",h:"業種",f:function(r){return r.sector||"—";},t:"s"},
    {k:"rank",h:"判定",f:function(r){
      var L={sp:"収益性",sf:"財務",sv:"割安度"},
          T={good:"良好",flat:"標準",warn:"注意",bad:"警戒",none:"データなし"};
      return '<span class="chip">'+["sp","sf","sv"].map(function(k){
        var st=r[k]||"none";
        return '<i style="background:var('+(st==="good"?"--ok":st==="warn"?"--wn":st==="bad"?"--bad":st==="flat"?"--ink-3":"--rule-s")
          +')" title="'+L[k]+"："+T[st]+'"></i>';
      }).join("")+'</span>';}},
    {k:"mcap",h:"時価総額",f:function(r){return money(r.mcap);}},
    {k:"opm",h:"営業利益率",f:function(r){return pct(r.opm);}},
    {k:"eq",h:"自己資本比率",f:function(r){return pct(r.eq);}},
    {k:"roe",h:"ROE",f:function(r){return pct(r.roe);}},
    {k:"per",h:"PER",f:function(r){return numf(r.per,1);}},
    {k:"pbr",h:"PBR",f:function(r){return numf(r.pbr,2);}},
    {k:"yld",h:"利回り",f:function(r){return pct(r.yld,2);}}
  ];
  function uniq(k){ var s={}; ROWS.forEach(function(r){ if(r[k]) s[r[k]]=1; }); return Object.keys(s).sort(); }
  uniq("sector").forEach(function(v){ sec.insertAdjacentHTML("beforeend",'<option>'+v+'</option>'); });
  uniq("market").forEach(function(v){ mk.insertAdjacentHTML("beforeend",'<option>'+v+'</option>'); });

  function render(){
    var term=(q.value||"").trim().toLowerCase(), s=sec.value, m=mk.value;
    var out=ROWS.filter(function(r){
      if(s && r.sector!==s) return false;
      if(m && r.market!==m) return false;
      if(!term) return true;
      return r.code.toLowerCase().indexOf(term)>=0 || (r.name||"").toLowerCase().indexOf(term)>=0;
    });
    var col=COLS.filter(function(c){return c.k===sortKey;})[0]||COLS[3];
    out.sort(function(a,b){
      var x=a[sortKey], y=b[sortKey];
      if(sortKey==="rank"){
        var W={good:3,flat:2,warn:1,bad:0,none:-1};
        var sc=function(r){return ["sp","sf","sv"].reduce(function(t,k){return t+(W[r[k]||"none"]);},0);};
        x=sc(a); y=sc(b); return sortAsc? x-y : y-x;
      }
      if(col.t==="s"){ x=x||""; y=y||""; return sortAsc? (x<y?-1:x>y?1:0) : (x>y?-1:x<y?1:0); }
      if(x==null) return 1; if(y==null) return -1;
      return sortAsc? x-y : y-x;
    });
    count.textContent=out.length.toLocaleString()+" / "+ROWS.length.toLocaleString()+" 銘柄";
    var show=out.slice(0,600);
    list.innerHTML='<div class="tblwrap"><table><thead><tr>'+COLS.map(function(c){
        return '<th'+(c.k===sortKey?' aria-sort="'+(sortAsc?"ascending":"descending")+'"':'')+' data-k="'+c.k+'">'+c.h+'</th>';
      }).join("")+'</tr></thead><tbody>'+show.map(function(r){
        return '<tr>'+COLS.map(function(c){ var v=c.f(r); return '<td'+(v==="—"?' class="na"':'')+'>'+v+'</td>'; }).join("")+'</tr>';
      }).join("")+'</tbody></table></div>'
      +(out.length>show.length?'<div class="p-sub" style="padding:8px 10px">先頭 '+show.length+' 件を表示（絞り込むと全件表示されます）</div>':'');
    list.querySelectorAll("th").forEach(function(th){
      th.addEventListener("click",function(){
        var k=th.dataset.k;
        if(k===sortKey) sortAsc=!sortAsc; else { sortKey=k; sortAsc=(COLS.filter(function(c){return c.k===k;})[0]||{}).t==="s"; }
        render();
      });
    });
  }
  [q,sec,mk].forEach(function(e){ e.addEventListener("input",render); });
  render();
}
"""


# ------------------------------------------------------------------ 判定
# 個別ページの評価サマリーと同じ基準。業種中央値が無い場合は絶対値で判定する。
def state_profit(opm, med):
    if opm is None:
        return "none"
    if opm < 0:
        return "bad"
    if med is not None:
        return "good" if opm >= med * 1.2 else ("warn" if opm < med * 0.6 else "flat")
    return "good" if opm >= 0.10 else ("warn" if opm < 0.03 else "flat")


def state_finance(eq, med):
    if eq is None:
        return "none"
    if eq < 0.10 and (med is None or eq < med * 0.8):
        return "bad"
    if eq < 0.20:
        return "flat" if (med is not None and eq >= med) else "warn"
    return "good" if (eq >= 0.50 or (med is not None and eq >= med * 1.3)) else "flat"


def state_value(per, pbr, mper, mpbr):
    if per is None and pbr is None:
        return "none"
    cheap = rich = 0
    if per is not None and mper is not None:
        cheap, rich = (cheap + 1, rich) if per < mper else (cheap, rich + 1)
    if pbr is not None and mpbr is not None:
        cheap, rich = (cheap + 1, rich) if pbr < mpbr else (cheap, rich + 1)
    if mper is None and mpbr is None:
        return "flat"
    return "good" if cheap >= 2 else ("warn" if rich >= 2 else "flat")


# ------------------------------------------------------------------ html
def company_html(c):
    esc = lambda s: (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    payload = {
        "code": c["code"], "name": c["name"], "market": c["market"], "sector": c["sector"],
        "quote": c["quote"], "annual": c["annual"], "peer": c.get("peer") or {"n": 0},
        "fc": c.get("fc"), "quarters": c.get("quarters") or [], "odpName": c.get("odpName"), "holders": c.get("holders"), "bs": c.get("bs") or [],
    }
    biz = ('<p class="biz">%s</p>' % esc(c["biz"])) if c["biz"] else ""
    if c.get("url"):   # 会社の公式サイト（新しいタブで開く）
        biz += ('<p class="site"><a href="%s" target="_blank" rel="noopener noreferrer"><b>公式サイト ↗</b><span>%s</span></a></p>'
                % (esc(c["url"]).replace('"', "&quot;"), esc(c["url"].split("://", 1)[-1].rstrip("/"))))
    return """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>%(name)s（%(code)s）業績ダッシュボード</title>
<link rel="stylesheet" href="assets/style.css">
</head>
<body>
<div class="wrap">
  <header class="mast">
    <div class="eyebrow"><a href="../fundamentals.html" style="color:inherit">← 東証スクリーニング</a></div>
    <h1>%(name)s<span class="code">%(code)s</span></h1>
    <div class="slip" id="slip"></div>
    %(biz)s
  </header>

  <section class="cards" id="cards" aria-label="判定サマリー"></section>

  <section class="grid">
    <div class="panel" id="p-annual"></div>
    <div class="panel" id="p-cf"></div>
    <div class="panel" id="p-q"></div>
    <div class="panel" id="p-div"></div>
    <div class="panel full" id="p-bs"></div>
    <div class="panel full" id="p-holders"></div>
  </section>

  <details class="more">
    <summary>通期の数値をすべて見る</summary>
    <div class="inner" id="t-annual"></div>
  </details>
  <details class="more">
    <summary>判定の基準と注記</summary>
    <div class="inner foot"><ol>
      <li>直近の通期決算を、同じ業種の中央値と比べて判定しています。▲＝良い側　●＝並み　▼＝注意。</li>
      <li>成長性：売上高の年平均成長率が5%%以上で増収。利益が初年度を下回ると増収減益。</li>
      <li>収益性：営業利益率が業種中央値の1.2倍以上で高い、0.6倍未満で低い。</li>
      <li>財務安全性：自己資本比率が50%%以上か業種の1.3倍以上で厚い、20%%未満で薄め（業種並みなら標準）。</li>
      <li>資本効率：ROE 10%%以上で高い、5%%未満で低い。</li>
      <li>割安度：PERとPBRがともに業種中央値を下回ると割安、ともに上回ると割高。</li>
      <li>売上総利益・粗利率は売上原価データがある期のみ表示し、データの無い系列・列は出しません。</li>
      <li>グラフ：通期・配当の右端の薄い棒は会社予想（決算短信の最新値。J-Quants と TDnet）。折れ線は右軸（%%）。</li>
      <li>経常利益は決算短信（J-Quants と TDnet）から取得（日本基準のみ。取得範囲は直近約2年）。IFRS・米国基準は税引前利益で表示します。</li>
      <li>貸借対照表は有価証券報告書（EDINET API）の連結貸借対照表（連結が無い会社は個別）を区分にまとめたもの。日本基準とIFRSの科目を対応させています。売上債権は受取手形・売掛金・電子記録債権・契約資産、買入債務は支払手形・買掛金・電子記録債務の合計。自己資本は純資産から非支配株主持分と新株予約権を除いた額です。</li>
      <li>株主構成は最新の有価証券報告書「大株主の状況」（上位10名）と自己株式数から、発行済株式数に対する割合で描画（EDINET API）。その他は上位10名・自己株式以外の合計です。</li>
      <li>四半期決算は累計値の差分から単独四半期を算出。フリーCFは営業CF＋投資CF。配当性向は一株配当÷EPS。</li>
      <li>出所：~/株分析 の fundamentals/（通期）。株価・時価総額は取得日時点。生成 %(built)s</li>
    </ol></div>
  </details>
</div>
<script src="assets/app.js"></script>
<script>renderCompany(%(json)s);</script>
</body>
</html>
""" % {
        "name": esc(c["name"]) or c["code"], "code": c["code"], "biz": biz,
        "built": datetime.date.today().isoformat(),
        "json": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    }


def index_html(rows, built):
    return """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>東証全銘柄 ファンダメンタル一覧</title>
<link rel="stylesheet" href="assets/style.css">
</head>
<body>
<div class="wrap">
  <header class="mast">
    <div class="eyebrow">Fundamentals · %(n)s 銘柄</div>
    <h1>東証全銘柄 ファンダメンタル一覧</h1>
    <div class="slip">
      <div>収録 <b>%(n)s 銘柄</b></div>
      <div>期間 <b>直近通期（最大4期）</b></div>
      <div>生成 <b>%(built)s</b></div>
    </div>
  </header>
  <div class="tools">
    <input type="search" id="q" placeholder="コードまたは銘柄名で検索">
    <select id="sec"><option value="">業種すべて</option></select>
    <select id="mk"><option value="">市場すべて</option></select>
    <span class="chip" style="color:var(--ink-3)">判定（収益性・財務・割安度）<i style="background:var(--ok)"></i>良好<i style="background:var(--ink-3)"></i>標準<i style="background:var(--wn)"></i>注意<i style="background:var(--bad)"></i>警戒</span><span id="count"></span>
  </div>
  <section id="list"></section>
  <details class="more">
    <summary>使い方</summary>
    <div class="inner foot"><ol>
      <li>見出しをクリックで並び替え（判定は良い順）。銘柄名をクリックで個別ページへ。</li>
      <li>絞り込み前は先頭600件を表示します。検索・業種・市場で絞ると全件出ます。</li>
      <li>判定の丸にカーソルを乗せると項目名と判定が出ます。</li>
    </ol></div>
  </details>
</div>
<script src="assets/app.js"></script>
<script>renderIndex(%(json)s);</script>
</body>
</html>
""" % {"n": "{:,}".format(len(rows)), "built": built,
       "json": json.dumps(rows, ensure_ascii=False, separators=(",", ":"))}


# ------------------------------------------------------------------ main
def main(argv):
    codes = [a for a in argv if not a.startswith("-")]
    limit = None
    if "--limit" in argv:
        limit = int(argv[argv.index("--limit") + 1])

    companies = load()
    keys = sorted(companies.keys())
    if codes:
        keys = [k for k in keys if k in codes]
    if limit:
        keys = keys[:limit]

    if not keys:
        print("該当する銘柄がありません。引数を確認してください（指定: %s）。"
              "\n何も出力せず終了します。" % (codes or "なし"), file=sys.stderr)
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "assets").mkdir(exist_ok=True)
    (OUT / "data").mkdir(exist_ok=True)
    (OUT / "assets" / "style.css").write_text(STYLE, encoding="utf-8")
    (OUT / "assets" / "app.js").write_text(APP + "\n" + (BASE / "kb_charts.js").read_text(encoding="utf-8"), encoding="utf-8")

    index_rows, skipped = [], 0
    for i, code in enumerate(keys, 1):
        c = companies[code]
        if not c["annual"]:
            skipped += 1
            continue
        (OUT / ("%s.html" % code)).write_text(company_html(c), encoding="utf-8")
        last = c["annual"][-1]
        P = c.get("peer") or {}
        index_rows.append({
            "code": code, "name": c["name"], "market": c["market"], "sector": c["sector"],
            "mcap": c["quote"]["mcap"], "rev": last["rev"], "opm": last["opm"],
            "nim": last["nim"], "eq": last["eq"], "roe": last["roe"], "gpm": last["gpm"],
            "per": c["quote"]["per"], "pbr": c["quote"]["pbr"], "yld": c["quote"]["yld"],
            "sp": state_profit(last["opm"], P.get("opm")),
            "sf": state_finance(last["eq"], P.get("eq")),
            "sv": state_value(c["quote"]["per"], c["quote"]["pbr"], P.get("per"), P.get("pbr")),
        })
        if i % 500 == 0:
            print("  %d / %d" % (i, len(keys)), flush=True)

    built = datetime.date.today().isoformat()
    index_rows.sort(key=lambda r: -(r["mcap"] or 0))
    (OUT / "data" / "index.json").write_text(
        json.dumps(index_rows, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (OUT / "index.html").write_text(index_html(index_rows, built), encoding="utf-8")

    gp_co = sum(1 for c in (companies[k] for k in keys)
                if c["annual"] and any(a["gp"] is not None for a in c["annual"]))
    gp_fy = sum(1 for c in (companies[k] for k in keys)
                for a in c["annual"] if a["gp"] is not None)
    print("[%s] 生成: %d 銘柄 / スキップ %d / 出力先 %s"
          % (datetime.datetime.now().strftime("%F %T"), len(index_rows), skipped, OUT))
    print("  売上総利益あり: %d 銘柄 / %d 決算期（残り %d 銘柄は売上原価待ち）"
          % (gp_co, gp_fy, len(index_rows) - gp_co))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]) or 0)
