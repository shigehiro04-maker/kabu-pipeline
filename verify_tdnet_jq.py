#!/usr/bin/env python3
"""TDnet から読んだ決算短信の数字（fetch_tdnet.py → fundamentals/jq_summary_tdnet/）を、
J-Quants の決算短信サマリー（fundamentals/jq_summary/、無料版は12週遅れ）で答え合わせする。2026-11-16 作成。

両方にある開示日（J-Quants が追いついた日）について、開示番号（J-Quants の DiscNo ＝ TDnet の zip 名の後ろ14桁）で
1件ずつ対応づけ、売上・利益・EPS・資産・CF・株数・配当・会社予想を比べる。通信なし・数秒。

出力:
  fundamentals/verify/tdnet_vs_jquants.csv          食い違い（1行＝1開示×1項目）。J-Quants にだけある・TDnet にだけある開示も
  fundamentals/verify/tdnet_vs_jquants_summary.json 件数・一致率・項目別の食い違い数・最後に確かめた開示日
画面には使わない（数字の正しさの確認用）。食い違いが増えたら fetch_tdnet.py の読み取りを直す。
"""
import csv
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
JQ = BASE / "fundamentals" / "jq_summary"
TD = BASE / "fundamentals" / "jq_summary_tdnet"
OUT = BASE / "fundamentals" / "verify"

# 比べる項目と名前。許容差は「相対 0.1%」か下の絶対差（四捨五入の違い）の大きいほう
FIELDS = {
    "Sales": "売上高", "OP": "営業利益", "OdP": "経常利益", "NP": "純利益", "EPS": "EPS",
    "TA": "総資産", "Eq": "純資産", "EqAR": "自己資本比率", "BPS": "BPS",
    "CFO": "営業CF", "CFI": "投資CF", "CFF": "財務CF", "CashEq": "現金同等物",
    "DivAnn": "年間配当", "PayoutRatioAnn": "配当性向",
    "ShOutFY": "発行済株式数", "TrShFY": "自己株式数", "AvgSh": "期中平均株式数",
    "FSales": "予想売上高", "FOP": "予想営業利益", "FOdP": "予想経常利益", "FNP": "予想純利益", "FEPS": "予想EPS",
    "FDivAnn": "予想年間配当",
    "NxFSales": "来期予想売上高", "NxFOP": "来期予想営業利益", "NxFOdP": "来期予想経常利益", "NxFNp": "来期予想純利益",
    "NxFEPS": "来期予想EPS", "NxFDivAnn": "来期予想年間配当",
}
ABS_TOL = {"EPS": 0.011, "BPS": 0.011, "FEPS": 0.011, "NxFEPS": 0.011, "EqAR": 0.0015, "PayoutRatioAnn": 0.0015,
           "DivAnn": 0.011, "FDivAnn": 0.011, "NxFDivAnn": 0.011}


def f(v):
    try:
        return float(v) if v not in ("", None) else None
    except (TypeError, ValueError):
        return None


def load(d: Path, days=None):
    out = {}
    for p in sorted(d.glob("*.json")):
        if days is not None and p.stem not in days:
            continue
        try:
            rows = json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        for r in rows if isinstance(rows, list) else []:
            no = str(r.get("DiscNo") or "")[-14:]
            if no:
                out[no] = r
    return out


def target(r):
    t = r.get("DocType", "") or ""
    return ("FinancialStatements" in t or "ForecastRevision" in t) and "REIT" not in t


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    tdays = {p.stem for p in TD.glob("*.json")}
    jdays = {p.stem for p in JQ.glob("*.json")}
    days = tdays & jdays
    if not days:
        print("J-Quants と TDnet の両方にある開示日がまだありません（J-Quants が追いつくのを待つ）")
        json.dump({"確かめた開示日": [], "注": "重なる日なし"}, (OUT / "tdnet_vs_jquants_summary.json").open("w"),
                  ensure_ascii=False, indent=1)
        return 0
    jq = {k: v for k, v in load(JQ, days).items() if target(v)}
    td = {k: v for k, v in load(TD, days).items() if target(v)}
    rows, per_field = [], {k: [0, 0] for k in FIELDS}   # [比べた数, 食い違い]
    docs_ok = docs_ng = 0
    for no, j in sorted(jq.items(), key=lambda x: (x[1].get("DiscDate", ""), x[0])):
        code = j["Code"][:4] if j["Code"].endswith("0") and len(j["Code"]) == 5 else j["Code"]
        base = {"開示日": j.get("DiscDate", ""), "コード": code, "書類": j.get("DocType", ""), "開示番号": no}
        t = td.get(no)
        if t is None:
            rows.append({**base, "項目": "（開示ごと）", "J-Quants": "", "TDnet": "", "差(%)": "", "判定": "TDnetに無い"})
            continue
        bad = False
        fy = str(j.get("DocType", "")).startswith("FY")
        for k, name in FIELDS.items():
            # 中間期・四半期のキャッシュフローは決算短信の要約に無く（添付の財務諸表だけ）、fetch_tdnet.py は要約しか読まない。
            # サイトで使うのは本決算の CF だけなので比べない
            if not fy and k in ("CFO", "CFI", "CFF", "CashEq"):
                continue
            a = f(j.get(k))
            if a is None:
                continue
            b = f(t.get(k))
            per_field[k][0] += 1
            if b is None:
                judge = "TDnetで空"
            else:
                tol = max(abs(a) * 0.001, ABS_TOL.get(k, 0.5))
                if abs(a - b) <= tol:
                    continue
                judge = "値が違う"
            per_field[k][1] += 1
            bad = True
            rows.append({**base, "項目": name, "J-Quants": j.get(k), "TDnet": t.get(k, ""),
                         "差(%)": round((b / a - 1) * 100, 2) if (b is not None and a) else "", "判定": judge})
        docs_ng += bad
        docs_ok += not bad
    only_td = [no for no in td if no not in jq]
    for no in only_td:
        t = td[no]
        rows.append({"開示日": t.get("DiscDate", ""), "コード": t["Code"][:4], "書類": t.get("DocType", ""), "開示番号": no,
                     "項目": "（開示ごと）", "J-Quants": "", "TDnet": "", "差(%)": "", "判定": "J-Quantsに無い"})
    cols = ["開示日", "コード", "書類", "開示番号", "項目", "J-Quants", "TDnet", "差(%)", "判定"]
    with (OUT / "tdnet_vs_jquants.csv").open("w", encoding="utf-8-sig", newline="") as fo:
        w = csv.DictWriter(fo, cols)
        w.writeheader()
        w.writerows(rows)
    n_cmp = sum(v[0] for v in per_field.values())
    n_bad = sum(v[1] for v in per_field.values())
    summ = {
        "確かめた開示日": sorted(days), "J-Quantsの開示": len(jq), "TDnetの開示": len(td),
        "対応がついた開示": docs_ok + docs_ng, "全項目一致の開示": docs_ok, "食い違いのある開示": docs_ng,
        "TDnetに無い開示": sum(1 for no in jq if no not in td), "J-Quantsに無い開示": len(only_td),
        "比べた値": n_cmp, "食い違った値": n_bad, "値の一致率(%)": round((1 - n_bad / n_cmp) * 100, 3) if n_cmp else None,
        "項目別（比べた数, 食い違い）": {FIELDS[k]: v for k, v in per_field.items() if v[0]},
    }
    (OUT / "tdnet_vs_jquants_summary.json").write_text(json.dumps(summ, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"TDnet と J-Quants の突き合わせ（{min(days)}〜{max(days)}、{len(days)}日）: "
          f"開示 {docs_ok + docs_ng} 件のうち全項目一致 {docs_ok}・食い違い {docs_ng}、"
          f"値 {n_cmp} 個の一致率 {summ['値の一致率(%)']}%、TDnetに無い {summ['TDnetに無い開示']}・J-Quantsに無い {len(only_td)}"
          f" → fundamentals/verify/tdnet_vs_jquants.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
