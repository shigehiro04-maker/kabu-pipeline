#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
取得漏れの監査スクリプト。

JPX の上場銘柄一覧（プライム・スタンダード・グロース）と、
data/prices/ に保存済みの CSV を突き合わせて、取れていない銘柄を洗い出す。
オプションで、未取得銘柄が Yahoo Finance に存在するかも実際に確認する。

使い方:
    ./.venv/bin/python audit_coverage.py            # 突き合わせのみ（数秒）
    ./.venv/bin/python audit_coverage.py --probe    # 未取得銘柄の取得可否も確認（数分）

出力:
    coverage_report.csv   … 全銘柄の状態一覧（market, code, name, status）
"""

import argparse
import csv
import io
import os
import sys
from collections import Counter, defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PRICES_DIR = os.path.join(BASE_DIR, "data", "prices")
REPORT = os.path.join(BASE_DIR, "coverage_report.csv")
JPX_URL = None  # update_tickers.find_list_url() で毎回探す

MARKETS = ["プライム", "スタンダード", "グロース"]


def load_jpx():
    import pandas as pd
    import requests

    print("JPX から上場銘柄一覧を取得中 ...")
    # URLは JPX の一覧ページから探す（2026年9月に .xls → .xlsx へ変わったため固定URLをやめた）
    sys.path.insert(0, BASE_DIR)
    from update_tickers import find_list_url
    r = requests.get(find_list_url(), timeout=60, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    df = pd.read_excel(io.BytesIO(r.content))

    code_col = next(c for c in df.columns if "コード" in str(c))
    name_col = next(c for c in df.columns if "銘柄名" in str(c))
    mkt_col = next(c for c in df.columns if "市場" in str(c))

    out = []
    for _, row in df.iterrows():
        raw = str(row[mkt_col])
        seg = next((m for m in MARKETS if raw.startswith(m)), None)
        if seg is None:
            continue          # ETF・REIT・出資証券など株式3市場以外は対象外
        out.append({
            "market": seg,
            "market_raw": raw,
            "code": str(row[code_col]).strip(),
            "name": str(row[name_col]).strip(),
        })
    return out


def probe(codes):
    """Yahoo Finance にデータが存在するか実際に確認する。"""
    import pandas as pd
    import yfinance as yf

    found = set()
    B = 100
    for i in range(0, len(codes), B):
        batch = codes[i:i + B]
        syms = [f"{c}.T" for c in batch]
        try:
            data = yf.download(syms, period="1mo", interval="1d",
                               group_by="ticker", threads=True,
                               progress=False, actions=False, auto_adjust=True)
        except Exception as e:
            print(f"  バッチ {i//B+1} 失敗: {e}", file=sys.stderr)
            continue
        for c, s in zip(batch, syms):
            try:
                sub = data[s] if isinstance(data.columns, pd.MultiIndex) else data
                if not sub.dropna(subset=["Close"]).empty:
                    found.add(c)
            except Exception:
                pass
        print(f"  確認 {min(i+B, len(codes))}/{len(codes)}")
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true",
                    help="未取得銘柄が Yahoo Finance にあるか実際に確認する")
    args = ap.parse_args()

    listed = load_jpx()
    have = {f[:-4] for f in os.listdir(PRICES_DIR) if f.endswith(".csv")}

    by_market = defaultdict(list)
    for r in listed:
        r["status"] = "取得済み" if r["code"] in have else "未取得"
        by_market[r["market"]].append(r)

    listed_codes = {r["code"] for r in listed}
    orphans = sorted(have - listed_codes)   # CSVはあるが今の上場一覧にない

    print("\n" + "=" * 58)
    print(f"{'市場':<12}{'上場数':>8}{'取得済み':>10}{'未取得':>8}")
    print("-" * 58)
    for m in MARKETS:
        rows = by_market[m]
        ok = sum(1 for r in rows if r["status"] == "取得済み")
        print(f"{m:<12}{len(rows):>8}{ok:>10}{len(rows)-ok:>8}")
    tot = sum(len(by_market[m]) for m in MARKETS)
    tok = sum(1 for r in listed if r["status"] == "取得済み")
    print("-" * 58)
    print(f"{'合計':<12}{tot:>8}{tok:>10}{tot-tok:>8}")
    print("=" * 58)

    missing = [r for r in listed if r["status"] == "未取得"]

    # 未取得をコード形式で分類（英数字コードは2024年以降の新規上場に多い）
    alnum = [r for r in missing if not r["code"].isdigit()]
    numeric = [r for r in missing if r["code"].isdigit()]
    print(f"\n未取得の内訳:  4桁数字コード {len(numeric)} 件 / 英数字コード {len(alnum)} 件")

    if alnum:
        print("\n英数字コードの銘柄（コード形式の判定漏れ）:")
        for r in alnum[:15]:
            print(f"  {r['code']:<6}{r['market']:<8}{r['name']}")
        if len(alnum) > 15:
            print(f"  … 他 {len(alnum)-15} 件")

    if numeric:
        c = Counter(r["market"] for r in numeric)
        print("\n4桁数字コードで未取得のもの（市場別）:", dict(c))
        prime_missing = [r for r in numeric if r["market"] == "プライム"]
        if prime_missing:
            print("  ※プライムに未取得あり（要確認）:")
            for r in prime_missing[:20]:
                print(f"    {r['code']:<6}{r['name']}")

    if orphans:
        print(f"\nCSVはあるが現在の上場一覧に無い銘柄: {len(orphans)} 件")
        print("  （上場廃止・市場変更・コード変更の可能性）")
        print("  ", ", ".join(orphans[:20]))

    if args.probe and missing:
        print(f"\nYahoo Finance でのデータ有無を確認中（{len(missing)} 銘柄）...")
        found = probe([r["code"] for r in missing])
        for r in missing:
            r["status"] = "未取得(取得可)" if r["code"] in found else "未取得(データ無し)"
        print(f"  取得可能: {len(found)} 件 / データ無し: {len(missing)-len(found)} 件")
        nodata = [r for r in missing if r["code"] not in found]
        if nodata:
            print("  データ無しの例:")
            for r in nodata[:15]:
                print(f"    {r['code']:<6}{r['market']:<8}{r['name']}")

    with open(REPORT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["market", "code", "name", "status"])
        for r in sorted(listed, key=lambda x: (MARKETS.index(x["market"]), x["code"])):
            w.writerow([r["market"], r["code"], r["name"], r["status"]])
        for c in orphans:
            w.writerow(["(上場一覧に無し)", c, "", "CSVのみ存在"])

    print(f"\n詳細レポート: {REPORT}")


if __name__ == "__main__":
    main()
