#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EDINET DB の financials 応答から、スクリーニング用の指標を作る。

fetch_cost_of_sales.py が売上原価のために既に取っている応答
（/companies/{edinet}/financials?period=annual&years=6）から、必要な生の項目を
追加で保存するだけなので、**APIの呼び出し回数は増えない**。

出力
  fundamentals/edinet_metrics_by_year.csv   1行 = 銘柄 × 決算期（最大6期、生の項目）
  fundamentals/edinet_metrics_latest.csv    1行 = 銘柄（直近期の指標。screening_config が読む）

指標の作り方（EDINET DB のメソドロジーに合わせ、怪しい値は NULL にする）
  経常利益変化率(%)   (今期 − 前期) ÷ |前期| × 100。前期が0以下・符号反転は NULL
  当座比率(%)         (現金 + 売上債権) ÷ 流動負債 × 100（有価証券は含まない近似）
  売上債権回転率(回)   売上高 ÷ 期末売上債権
  棚卸資産回転率(回)   売上原価 ÷ 期末棚卸資産（EDINET DB と同じく売上原価で割る）
  CCC(日)             売上債権日数 + 棚卸日数 − 仕入債務日数
  ROIC税前(%)         営業利益 ÷ (純資産 + 有利子負債 − 現金) × 100。投下資本≤0・|値|>100 は NULL
  連続増配年数         分割調整後DPSが前期より増えた年が何年続いているか（取得できた6期の範囲＝最大5年）
  最高益               直近期の当期純利益が取得6期の中で最大かつ黒字なら1（3期未満は NULL）
  DOE(%)              配当総額 ÷ 自己資本 × 100。50%超は NULL
  ネットキャッシュ(円)  流動資産 − 負債合計（比率は screening_engine 側で時価総額で割る）
  金融業（銀行・保険・証券・その他金融）は回転・CCC・ROIC・当座比率を NULL にする。

使い方
  ./.venv/bin/python edinet_metrics.py     # 蓄積済みの by_year から latest を作り直す（通信なし）
"""
from __future__ import annotations

import csv
import datetime as dt
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent
OUT_DIR = BASE / "fundamentals"
BY_YEAR_CSV = OUT_DIR / "edinet_metrics_by_year.csv"
LATEST_CSV = OUT_DIR / "edinet_metrics_latest.csv"

VERSION = 1          # 保存項目を変えたら上げる（上げると余り枠で全社を順に取り直す）
YEARS_KEEP = 6
FINANCIAL_SECTORS = {"銀行業", "保険業", "証券、商品先物取引業", "その他金融業"}

# 保存する生の項目: 列名 -> APIのキー候補（snake_case / camelCase の揺れは pick が吸収）
RAW_FIELDS = {
    "売上高": ("revenue", "net_sales", "operating_revenue"),
    "売上原価": ("cost_of_sales", "costOfRevenue"),
    "営業利益": ("operating_income",),
    "経常利益": ("ordinary_income", "ordinary_profit"),
    "当期純利益": ("net_income",),
    "現金": ("cash", "cash_and_deposits", "cash_and_equivalents"),
    "売上債権": ("trade_receivables", "notes_and_accounts_receivable"),
    "棚卸資産": ("inventories", "inventory"),
    "仕入債務": ("trade_payables", "notes_and_accounts_payable"),
    "流動資産": ("current_assets",),
    "流動負債": ("current_liabilities",),
    "負債合計": ("total_liabilities",),
    "純資産": ("net_assets",),
    "株主資本": ("shareholders_equity",),
    "非支配株主持分": ("non_controlling_interests",),
    "有利子負債_流動": ("ibd_current",),
    "有利子負債_固定": ("ibd_noncurrent",),
    "配当総額": ("dividends_total_announced",),
    "配当支払額": ("cash_dividends_paid",),
    "調整後DPS": ("adjusted_dividend_per_share",),
    "調整後EPS": ("adjusted_eps",),
}
TEXT_FIELDS = {
    "会計基準": ("accounting_standard",),
    "分割調整の出所": ("split_adjustment_factor_source", "split_adjustment_source"),
    "提出日": ("submit_date",),
}
BY_YEAR_FIELDS = ["コード", "EDINETコード", "年度"] + list(TEXT_FIELDS) + list(RAW_FIELDS) + ["取得日"]

LATEST_FIELDS = [
    "コード", "EDINETコード", "年度", "会計基準", "金融業", "売上高", "当期純利益",
    "経常利益", "経常利益_前期", "経常利益変化率(%)",
    "当座比率(%)", "売上債権回転率(回)", "棚卸資産回転率(回)",
    "売上債権日数", "棚卸日数", "仕入債務日数", "CCC(日)",
    "投下資本", "ROIC税前(%)",
    "連続増配年数", "連続増配_上限到達", "最高益", "DOE(%)",
    "ネットキャッシュ(円)", "分割調整推測", "収録期数", "取得日",
]


# ---------------------------------------------------------------- 小道具

def _pick(row: dict, names):
    for n in names:
        if n in row and row[n] not in (None, ""):
            return row[n]
    low = {k.lower().replace("_", ""): v for k, v in row.items()}
    for n in names:
        v = low.get(n.lower().replace("_", ""))
        if v not in (None, ""):
            return v
    return None


def _num(v):
    if v in (None, "", "-"):
        return None
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def _fmt(v, nd=2):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "1" if v else "0"
    if abs(v - round(v)) < 1e-9 and abs(v) >= 1000:
        return str(int(round(v)))
    return f"{v:.{nd}f}"


def _rows(data):
    """応答の中の「決算期ごとの辞書のリスト」を探す。"""
    stack = [data]
    while stack:
        cur = stack.pop(0)
        if isinstance(cur, list):
            ds = [x for x in cur if isinstance(x, dict)]
            if ds and any(("fiscal_year" in d or "fiscalYear" in d) for d in ds):
                return ds
            stack.extend(cur)
        elif isinstance(cur, dict):
            stack.extend(cur.values())
    return []


# ---------------------------------------------------------------- 蓄積

def parse(data) -> list[dict]:
    out = []
    for r in _rows(data):
        fy = str(_pick(r, ("fiscal_year", "fiscalYear")) or "").strip()[:10]
        if not fy:
            continue
        row = {"年度": fy}
        for col, names in TEXT_FIELDS.items():
            row[col] = str(_pick(r, names) or "")[:20 if col != "提出日" else 10]
        for col, names in RAW_FIELDS.items():
            row[col] = _num(_pick(r, names))
        out.append(row)
    out.sort(key=lambda x: x["年度"], reverse=True)
    return out


def load_store() -> dict:
    store = {}
    if BY_YEAR_CSV.exists():
        with open(BY_YEAR_CSV, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if r.get("コード") and r.get("年度"):
                    store.setdefault(r["コード"], {})[r["年度"]] = r
    return store


def update(store: dict, code: str, ec: str, data) -> int:
    """1社分の応答を蓄積に反映し、保存した期数を返す。"""
    rows = parse(data)
    if not rows:
        return 0
    kept = store.setdefault(code, {})
    t = dt.date.today().isoformat()
    for r in rows[:YEARS_KEEP]:
        rec = {"コード": code, "EDINETコード": ec, "取得日": t}
        for k, v in r.items():
            rec[k] = v if isinstance(v, str) else _fmt(v, 4) if v is not None else ""
        kept[r["年度"]] = rec
    for fy in sorted(kept, reverse=True)[YEARS_KEEP:]:
        del kept[fy]
    return len(rows[:YEARS_KEEP])


def save_store(store: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = BY_YEAR_CSV.with_suffix(".csv.tmp")
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=BY_YEAR_FIELDS)
        w.writeheader()
        for code in sorted(store):
            for fy in sorted(store[code], reverse=True)[:YEARS_KEEP]:
                w.writerow({k: store[code][fy].get(k, "") for k in BY_YEAR_FIELDS})
    os.replace(tmp, BY_YEAR_CSV)


# ---------------------------------------------------------------- 指標

def _div(a, b):
    return None if a is None or b is None or b == 0 else a / b


def compute(years: list[dict], financial: bool) -> dict:
    """years は新しい順。値は数値(None可)。"""
    g = lambda i, k: _num(years[i].get(k)) if i < len(years) else None
    cur = years[0]
    m = {"年度": cur.get("年度", ""), "会計基準": cur.get("会計基準", ""),
         "金融業": financial, "収録期数": float(len(years))}

    m["売上高"], m["当期純利益"] = g(0, "売上高"), g(0, "当期純利益")   # Yahoo との突き合わせ用
    # 経常利益（日本基準のみ。IFRS・US基準は区分が無く NULL のまま）
    k0, k1 = g(0, "経常利益"), g(1, "経常利益")
    m["経常利益"], m["経常利益_前期"] = k0, k1
    m["経常利益変化率(%)"] = ((k0 - k1) / abs(k1) * 100
                          if k0 is not None and k1 is not None and k1 > 0 and k0 >= 0 else None)

    rev, cos = g(0, "売上高"), g(0, "売上原価")
    rec, inv, pay = g(0, "売上債権"), g(0, "棚卸資産"), g(0, "仕入債務")
    cash, cl = g(0, "現金"), g(0, "流動負債")

    if not financial:
        if cash is not None and rec is not None and cl and cl > 0:
            m["当座比率(%)"] = (cash + rec) / cl * 100
        if rev and rev > 0 and rec and rec > 0:
            m["売上債権回転率(回)"] = rev / rec
            m["売上債権日数"] = rec / rev * 365
        if cos and cos > 0 and inv and inv > 0:
            m["棚卸資産回転率(回)"] = cos / inv
            m["棚卸日数"] = inv / cos * 365
        if cos and cos > 0 and pay is not None and pay >= 0:
            m["仕入債務日数"] = pay / cos * 365
        if m.get("売上債権日数") is not None and m.get("仕入債務日数") is not None:
            # 棚卸資産が無い業種（サービス等）は棚卸日数0として扱う
            inv_days = m.get("棚卸日数") if inv else 0.0
            if inv_days is not None:
                m["CCC(日)"] = m["売上債権日数"] + inv_days - m["仕入債務日数"]
        na, op = g(0, "純資産"), g(0, "営業利益")
        ibd = None
        if g(0, "有利子負債_流動") is not None or g(0, "有利子負債_固定") is not None:
            ibd = (g(0, "有利子負債_流動") or 0) + (g(0, "有利子負債_固定") or 0)
        if na is not None and ibd is not None and cash is not None:
            ic = na + ibd - cash
            m["投下資本"] = ic
            if ic > 0 and op is not None:
                x = op / ic * 100
                m["ROIC税前(%)"] = x if abs(x) <= 100 else None

    # 連続増配（分割調整後DPS。取得できた期の範囲だけで数える）
    dps = [g(i, "調整後DPS") for i in range(len(years))]
    streak = 0
    for i in range(len(dps) - 1):
        a, b = dps[i], dps[i + 1]
        if a is None or b is None or not (a > b):
            break
        streak += 1
    if dps and dps[0] is not None:
        m["連続増配年数"] = float(streak)
        m["連続増配_上限到達"] = streak == len(dps) - 1 and streak > 0

    ni = [g(i, "当期純利益") for i in range(len(years))]
    ni_ok = [x for x in ni if x is not None]
    if len(ni_ok) >= 3 and ni[0] is not None:
        m["最高益"] = ni[0] > 0 and ni[0] >= max(ni_ok)

    div = g(0, "配当総額")
    if div is None and g(0, "配当支払額") is not None:
        div = abs(g(0, "配当支払額"))
    eq = g(0, "株主資本")
    if eq is None and g(0, "純資産") is not None:
        eq = g(0, "純資産") - (g(0, "非支配株主持分") or 0)
    if div is not None and eq and eq > 0:
        x = div / eq * 100
        m["DOE(%)"] = x if x <= 50 else None

    ca, tl = g(0, "流動資産"), g(0, "負債合計")
    if ca is not None and tl is not None:
        m["ネットキャッシュ(円)"] = ca - tl

    src = (cur.get("分割調整の出所") or "").strip()
    m["分割調整推測"] = (src == "heuristic_inferred") if src else None
    return m


def save_latest(store: dict, sectors: dict | None = None) -> int:
    sectors = sectors or {}
    tmp = LATEST_CSV.with_suffix(".csv.tmp")
    n = 0
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LATEST_FIELDS)
        w.writeheader()
        for code in sorted(store):
            fys = sorted(store[code], reverse=True)
            if not fys:
                continue
            years = [store[code][fy] for fy in fys]
            m = compute(years, sectors.get(code, "") in FINANCIAL_SECTORS)
            row = {"コード": code, "EDINETコード": years[0].get("EDINETコード", ""),
                   "取得日": years[0].get("取得日", "")}
            for k in LATEST_FIELDS:
                if k in m:
                    v = m[k]
                    row[k] = v if isinstance(v, str) else _fmt(v)
            w.writerow({k: row.get(k, "") for k in LATEST_FIELDS})
            n += 1
    os.replace(tmp, LATEST_CSV)
    return n


def load_sectors() -> dict:
    p = BASE / "fundamentals" / "fundamentals_latest.csv"
    out = {}
    if p.exists():
        with open(p, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                out[(r.get("コード") or "").strip()] = r.get("業種", "")
    return out


if __name__ == "__main__":
    st = load_store()
    n = save_latest(st, load_sectors())
    print(f"{LATEST_CSV.relative_to(BASE)}: {n}社（by_year {sum(len(v) for v in st.values())}行）")
