#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
各銘柄データの照合（公的データとの突き合わせ）  2026-11-02 作成

照合先（すべて無料・登録不要 or 既存の無料キー）
  1) JPX 上場銘柄一覧 data_j.xlsx  … 銘柄名・市場区分・33業種
  2) 金融庁 EDINET コードリスト（Edinetcode.zip） … 上場区分・決算日・証券コード⇔EDINETコード
  3) EDINET DB（既に取得済みの有報データ edinet_metrics_by_year.csv） … 売上高・営業利益・純利益・純資産
  3b) J-Quants 決算短信サマリー（fundamentals/jq_summary/） … 有報と照合できない期の売上高・営業利益・純利益、新しい本決算の有無
  4) 自前データ同士の整合 … 時価総額＝株価×株数、株価＝最新終値、PER/PBR の再計算

出力: fundamentals/verify/verify_YYYYMMDD.csv（1行＝1つの不一致）と summary.txt
  ./.venv/bin/python verify_data.py
"""
import io, os, re, sys, unicodedata, zipfile
from datetime import date
from pathlib import Path

import pandas as pd
import requests

BASE = Path(__file__).resolve().parent
OUT = BASE / "fundamentals" / "verify"
OUT.mkdir(parents=True, exist_ok=True)
TODAY = date.today().strftime("%Y%m%d")
HEAD = {"User-Agent": "Mozilla/5.0"}
issues = []


def add(code, name, kind, field, ours, ref, src, note=""):
    issues.append(dict(コード=code, 銘柄名=name, 区分=kind, 項目=field,
                       自前データ=ours, 照合先=ref, 照合元=src, 備考=note))


def norm(s):
    s = unicodedata.normalize("NFKC", str(s or ""))
    s = re.sub(r"\s+", "", s)
    for w in ("株式会社", "(株)", "ホールディングス", "ＨＤ", "HD"):
        s = s.replace(w, "")
    return s.upper().replace("・", "").replace("－", "-").replace("ー", "-")


# ---------- 自前データ ----------
tk = pd.read_csv(BASE / "tickers/tse_tickers.csv", dtype=str, encoding="utf-8-sig")
fu = pd.read_csv(BASE / "fundamentals/fundamentals_latest.csv", dtype={"コード": str}, encoding="utf-8-sig")
names = dict(zip(tk.code, tk.name))

# ---------- 1) JPX ----------
sys.path.insert(0, str(BASE))
from update_tickers import find_list_url  # noqa
url = find_list_url()
jpx = pd.read_excel(io.BytesIO(requests.get(url, headers=HEAD, timeout=60).content), dtype=str)
jpx.columns = [c.strip() for c in jpx.columns]
jpx = jpx.rename(columns={"コード": "code", "銘柄名": "name", "市場・商品区分": "mkt", "33業種区分": "s33"})
jpx_asof = str(jpx["日付"].iloc[0])
stock = jpx[jpx.mkt.str.contains("内国株式|外国株式", na=False)].copy()
stock["m"] = stock.mkt.str.replace(r"（.*）", "", regex=True).str.replace("市場", "")
J = stock.set_index("code")

ours = set(tk.code)
for c in sorted(set(J.index) - ours):
    add(c, J.at[c, "name"], "銘柄の過不足", "銘柄", "なし", "JPXに上場", "JPX上場銘柄一覧",
        "JPX一覧にあるが自前リストにない（月末以降に上場廃止なら問題なし）")
for c in sorted(ours - set(J.index)):
    add(c, names[c], "銘柄の過不足", "銘柄", "あり", "JPX一覧になし", "JPX上場銘柄一覧",
        f"{jpx_asof}以降の新規上場なら問題なし")

for r in tk.itertuples():
    if r.code not in J.index:
        continue
    j = J.loc[r.code]
    if norm(r.name) != norm(j["name"]):
        add(r.code, r.name, "銘柄名", "銘柄名", r.name, j["name"], "JPX上場銘柄一覧")
    if r.market != j["m"]:
        add(r.code, r.name, "市場区分", "市場", r.market, j["m"], "JPX上場銘柄一覧")

for r in fu.itertuples():
    c = r.コード
    if c in J.index:
        j = J.loc[c]
        if str(r.業種) != str(j["s33"]) and str(j["s33"]) not in ("-", "nan"):
            add(c, r.銘柄名, "業種", "33業種", r.業種, j["s33"], "JPX上場銘柄一覧")
        if str(r.市場) != j["m"]:
            add(c, r.銘柄名, "市場区分", "市場(財務表)", r.市場, j["m"], "JPX上場銘柄一覧")

# ---------- 2) EDINET コードリスト ----------
z = requests.get("https://disclosure2dl.edinet-fsa.go.jp/searchdocument/codelist/Edinetcode.zip",
                 headers=HEAD, timeout=60).content
raw = zipfile.ZipFile(io.BytesIO(z)).read("EdinetcodeDlInfo.csv").decode("cp932")
ed = pd.read_csv(io.StringIO(raw), skiprows=1, dtype=str)
ed = ed[ed["証券コード"].notna()].copy()
ed["code"] = ed["証券コード"].str[:4]
E = ed.drop_duplicates("code").set_index("code")
mine = pd.read_csv(BASE / "fundamentals/edinet_companies.csv", dtype=str, encoding="utf-8-sig")
mine_map = dict(zip(mine["コード"], mine["EDINETコード"]))

for c, ecode in mine_map.items():
    if c in E.index and E.at[c, "ＥＤＩＮＥＴコード"] != ecode:
        add(c, names.get(c, ""), "EDINETコード", "EDINETコード", ecode, E.at[c, "ＥＤＩＮＥＴコード"],
            "EDINETコードリスト", "対応表が古い（別会社の有報を取り込む恐れ）")

for r in fu.itertuples():
    c = r.コード
    if c not in E.index:
        continue
    e = E.loc[c]
    if e["上場区分"] != "上場":
        add(c, r.銘柄名, "上場区分", "上場区分", "上場", e["上場区分"], "EDINETコードリスト")
    m = re.match(r"(\d+)月", str(e["決算日"]))
    if m and isinstance(r.決算期, str) and len(r.決算期) >= 7:
        if int(r.決算期[5:7]) != int(m.group(1)):
            add(c, r.銘柄名, "決算期", "決算月", r.決算期, e["決算日"], "EDINETコードリスト",
                "決算期変更の直後なら問題なし")

# ---------- 3) EDINET DB 有報の数値 ----------
by = pd.read_csv(BASE / "fundamentals/edinet_metrics_by_year.csv", dtype={"コード": str}, encoding="utf-8-sig")
by = by[by["提出日"].notna()].copy()
by["_sub"] = pd.to_datetime(by["提出日"])
BG = {c: g for c, g in by.groupby("コード")}


def ed_match(code, fy):
    g = BG.get(code)
    if g is None:
        return None
    d = (g["_sub"] - pd.Timestamp(fy)).dt.days
    h = g[(d > 0) & (d <= 125)]
    return None if h.empty else h.sort_values("_sub").iloc[-1]


fin_sec = {"銀行業", "保険業", "証券、商品先物取引業", "その他金融業"}
pairs = [("売上高", "売上高", 0.02), ("営業利益", "営業利益", 0.03),
         ("当期純利益", "当期純利益", 0.02), ("自己資本", "株主資本", 0.10)]
n_fin = 0
for r in fu.itertuples():
    c = r.コード
    if not isinstance(r.決算期, str):
        continue
    e = ed_match(c, r.決算期)
    if e is None:
        continue
    n_fin += 1
    for f_ours, f_ed, tol in pairs:
        if f_ours == "売上高" and r.業種 in fin_sec:
            continue
        a, b = getattr(r, f_ours), e[f_ed]
        if pd.isna(a) or pd.isna(b) or b == 0:
            continue
        diff = abs(a - b) / abs(b)
        if diff > tol:
            if f_ours == "自己資本":
                b2 = e["純資産"] - (0 if pd.isna(e["非支配株主持分"]) else e["非支配株主持分"])
                if not pd.isna(b2) and b2 and abs(a - b2) / abs(b2) <= tol:
                    continue
            add(c, r.銘柄名, "財務数値", f"{f_ours}({r.決算期[:7]}期)", f"{a:,.0f}", f"{b:,.0f}",
                "EDINET(有報)", f"差 {diff*100:.1f}%  会計基準:{e['会計基準']}")

# ---------- 3b) 決算短信（J-Quants 決算短信サマリー＝TDnet の公式値） 2026-11-02 追加 ----------
from reconcile_edinet import jq_fy_table  # noqa
JQ = jq_fy_table()
jq_last = {}
for (c, fy) in JQ:
    jq_last[c] = max(jq_last.get(c, ""), fy)
n_jq = 0
for r in fu.itertuples():
    c = r.コード
    if not isinstance(r.決算期, str):
        continue
    if jq_last.get(c, "") > r.決算期:
        add(c, r.銘柄名, "決算が古い", "決算期", r.決算期, jq_last[c], "決算短信(J-Quants)", "短信が出ている新しい本決算が未反映")
    v = JQ.get((c, r.決算期))
    if v is None or ed_match(c, r.決算期) is not None or str(r.通貨) not in ("JPY", "nan"):
        continue
    n_jq += 1
    for f in ("売上高", "営業利益", "当期純利益"):
        if f == "売上高" and r.業種 in fin_sec:
            continue
        a, b = getattr(r, f), v[f]
        if pd.isna(a) or pd.isna(b) or b == 0:
            continue
        if abs(a - b) > max(abs(b) * 0.02, 1_000_000):
            add(c, r.銘柄名, "財務数値", f"{f}({r.決算期[:7]}期)", f"{a:,.0f}", f"{b:,.0f}",
                "決算短信(J-Quants)", f"差 {abs(a-b)/abs(b)*100:.1f}%")

# ---------- 4) 自前データの整合 ----------
daily = sorted((BASE / "data/daily").glob("*.csv"))[-1]
dl = pd.read_csv(daily, dtype={"code": str}, encoding="utf-8-sig").set_index("code")
last = daily.stem
for r in fu.itertuples():
    c = r.コード
    if c in dl.index and not pd.isna(r.株価):
        cl = dl.at[c, "close"]
        if not pd.isna(cl) and abs(r.株価 - cl) / cl > 0.001:
            add(c, r.銘柄名, "株価", "株価", f"{r.株価:,.1f}({r.株価日付})", f"{cl:,.1f}({last})",
                "日次株価CSV", "財務表の株価が最新終値と違う")
    if not pd.isna(r.株価) and not pd.isna(r.発行済株式総数) and not pd.isna(r.時価総額) and r.時価総額:
        calc = r.株価 * r.発行済株式総数
        if abs(calc - r.時価総額) / r.時価総額 > 0.02:
            add(c, r.銘柄名, "時価総額", "時価総額", f"{r.時価総額:,.0f}", f"{calc:,.0f}",
                "株価×発行済株式総数", "計算が合わない")
    if not pd.isna(r.発行済株式数) and not pd.isna(r.発行済株式総数) and r.発行済株式総数:
        if r.発行済株式数 > r.発行済株式総数 * 1.001 or r.発行済株式数 < r.発行済株式総数 * 0.3:
            add(c, r.銘柄名, "株数", "発行済株式数(自己株除く)", f"{r.発行済株式数:,.0f}",
                f"{r.発行済株式総数:,.0f}", "発行済株式総数", "自己株除きが総数を超える/3割未満")
    if not pd.isna(r.EPS) and r.EPS > 0 and not pd.isna(r.PER) and not pd.isna(r.株価):
        if abs(r.株価 / r.EPS - r.PER) / max(r.PER, 0.01) > 0.05:
            add(c, r.銘柄名, "指標", "PER", r.PER, round(r.株価 / r.EPS, 2), "株価÷EPS")

# ---------- 5) 有報が未取得で Yahoo の数値が疑わしい銘柄 ----------
#   ・営業利益が売上総利益と同じ（Yahoo の取り違えの典型。電力・ガスなど売上総利益を開示しない業種は除く）
#   ・直近の決算期が15か月より前（Yahoo に最新の本決算が入っていない）
have = set(BG)
fby = pd.read_csv(BASE / "fundamentals/fundamentals_by_year.csv", dtype={"コード": str}, encoding="utf-8-sig")
lat = fby.sort_values("決算期").groupby("コード").tail(1)
prio = []
for r in lat.itertuples():
    if r.業種 in ("電気・ガス業",) or pd.isna(r.売上総利益) or pd.isna(r.営業利益) or not r.売上総利益:
        continue
    if abs(r.営業利益 - r.売上総利益) <= abs(r.売上総利益) * 0.01 and r.売上原価 and r.コード not in have \
            and (r.コード, r.決算期) not in JQ:
        add(r.コード, r.銘柄名, "要確認(有報未取得)", "営業利益", f"{r.営業利益:,.0f}",
            f"売上総利益 {r.売上総利益:,.0f}", "Yahoo内部の整合", "営業利益＝売上総利益（取り違えの疑い）")
        prio.append(r.コード)
cut = (pd.Timestamp.today() - pd.DateOffset(months=15)).strftime("%Y-%m-%d")
for r in fu.itertuples():
    if isinstance(r.決算期, str) and r.決算期 < cut:
        add(r.コード, r.銘柄名, "決算が古い", "決算期", r.決算期, f"{cut} より前", "Yahoo",
            "最新の本決算が未反映（決算期変更・Yahoo未更新）")
        if r.コード not in have:
            prio.append(r.コード)
(OUT / "edinet_priority.txt").write_text("\n".join(dict.fromkeys(prio)) + "\n", encoding="utf-8")

df = pd.DataFrame(issues)
path = OUT / f"verify_{TODAY}.csv"
df.to_csv(path, index=False, encoding="utf-8-sig")
lines = [f"照合日 {TODAY} / JPX一覧 {jpx_asof} 時点 / 日次株価 {last}",
         f"対象 {len(tk)} 銘柄（財務表 {len(fu)}、有報と照合できた {n_fin}、決算短信と照合できた {n_jq}）",
         f"不一致 合計 {len(df)} 件"]
if len(df):
    for k, v in df.groupby("区分").size().sort_values(ascending=False).items():
        lines.append(f"  {k}: {v}")
(OUT / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
print(path)
