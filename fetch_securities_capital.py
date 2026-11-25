#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""上場証券会社の自己資本規制比率を、日本取引所グループの公表資料から取り込む

証券会社の健全性は会計上の自己資本比率では測れません。顧客からの預り金や
信用取引の建玉が資産に乗るため、野村ホールディングスの自己資本比率は5.9%、
大和証券グループ本社は4.7%にしかならず、事業会社（中央値55%）と同じ物差しに
乗せると全社が最低評価になってしまいます。

代わりに使うのが**自己資本規制比率**（金融商品取引法46条の6）です。
    自己資本規制比率 ＝ 固定化されていない自己資本 ÷ リスク相当額合計
市場リスク・取引先リスク・基礎的リスクをまとめて分母に置き、それに対して
すぐ動かせる自己資本がどれだけあるかを見ます。規制上の水準は次のとおり。

    140%未満 … 金融庁への届出義務
    120%未満 … 業務方法の変更命令・業務停止命令
    100%未満 … 登録取消

日本取引所グループが四半期ごとに「総合取引参加者の自己資本規制比率」を
1枚の表にまとめて公表しているので、それを読み取ります。索引ページから最新の
PDFを自分で探すので、四半期が変わってもURLの手直しは要りません。

    ./.venv/bin/python fetch_securities_capital.py            # 取得して上書き
    ./.venv/bin/python fetch_securities_capital.py --dry-run  # 中身を見るだけ

出力: fundamentals/securities_capital.csv
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import requests

BASE = Path(__file__).resolve().parent
OUT = BASE / "fundamentals" / "securities_capital.csv"

INDEX = "https://www.jpx.co.jp/rules-participants/participants/ratio/index.html"
# 索引ページの構造が変わったときの保険。ここが古くても索引の自動探索が優先されます。
FALLBACK = ("https://www.jpx.co.jp/rules-participants/participants/ratio/"
            "tvdivq0000001z14-att/tvdivq000000v4aj.pdf")

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) kabu-bunseki/1.0"}

# 規制上の最低水準。これを下回ると業務停止命令の対象になります。
MIN_RATIO = 120.0

# JPXの「総合取引参加者名」→ その証券会社を傘下に持つ上場会社のコード。
# 参加者名は証券会社の単体名（例「野村」＝野村證券）、コードは上場している親会社です。
# 迷うものは載せていません（載せなかった銘柄は会計上の自己資本比率で評価されます）。
SEC_MAP = {
    "野村": "8604",              # 野村ホールディングス
    "大和": "8601",              # 大和証券グループ本社
    "ＳＢＩ": "8473",            # ＳＢＩホールディングス
    "松井": "8628",              # 松井証券
    "岡三": "8609",              # 岡三証券グループ
    "東海東京": "8616",          # 東海東京フィナンシャル・ホールディングス
    "マネックス": "8698",        # マネックスグループ
    "GMOクリック": "7177",       # ＧＭＯフィナンシャルホールディングス
    "JIA": "7172",               # ジャパンインベストメントアドバイザー
    "岩井コスモ": "8707",        # 岩井コスモホールディングス
    "丸三": "8613",              # 丸三証券
    "アイザワ": "8708",          # アイザワ証券グループ
    "いちよし": "8624",          # いちよし証券
    "極東": "8706",              # 極東証券
    "水戸": "8622",              # 水戸証券
    "東洋": "8614",              # 東洋証券
    "光世": "8617",              # 光世証券
    "今村": "7175",              # 今村証券
    "丸八": "8700",              # 丸八証券
    "日産": "8705",              # 日産証券グループ
    "あかつき": "8737",          # あかつき本社
}

# 上場している証券会社のうち、自己資本規制比率を持たない（＝証券会社ではない）もの。
# PE・ベンチャーキャピタル・資産運用会社・リース会社などで、実態は事業会社です。
# 一覧に出てこなくても異常ではないので、警告から外します。
NOT_BROKERS = {
    "7148",   # ＦＰＧ（リース・信託）
    "8595",   # ジャフコ グループ（ベンチャーキャピタル）
    "8739",   # スパークス・グループ（資産運用）
    "5842",   # インテグラル（プライベートエクイティ）
    "7347",   # マーキュリアホールディングス（資産運用）
    "5834",   # ＳＢＩリーシングサービス（リース）
    "8518",   # 日本アジア投資（ベンチャーキャピタル）
    "3113",   # ＵＮＩＶＡ・Ｏａｋホールディングス
    "8746",   # ｕｎｂａｎｋｅｄ
    "254A",   # ＡＩフュージョンキャピタルグループ
}


def find_pdf() -> tuple[str, str]:
    """索引ページから最新のPDFを探す。見つからなければ既知のURLを返す"""
    try:
        r = requests.get(INDEX, headers=UA, timeout=30)
        r.raise_for_status()
        html = r.text
        # 「総合取引参加者の自己資本規制比率」の添付PDFは -att/ の下に置かれている
        m = re.findall(r'href="([^"]*ratio/[^"]*-att/[^"]*\.pdf)"', html)
        if m:
            url = m[0]
            if url.startswith("/"):
                url = "https://www.jpx.co.jp" + url
            return url, "索引ページから自動取得"
    except Exception as e:
        print(f"索引ページを読めませんでした（{e}）。既知のURLを使います。", file=sys.stderr)
    return FALLBACK, "既定のURL"


def parse_pdf(path: Path) -> tuple[pd.DataFrame, str]:
    """PDFの表を読み取る。戻り値は (参加者名と比率の表, 基準日)"""
    try:
        import pdfplumber
    except ImportError:
        print("pdfplumber が必要です:  ./.venv/bin/pip install pdfplumber", file=sys.stderr)
        raise

    # 「参加者名 数字×5 比率%」の並び。名前に空白を含む会社があるので貪欲には取らない
    row_re = re.compile(
        r"^(.+?)\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)\s+([\d.]+)%"
    )
    rows, asof = [], ""
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if not asof:
                m = re.search(r"自己資本規制比率（(.+?)）", text)
                if m:
                    asof = m.group(1)
            for line in text.split("\n"):
                m = row_re.match(line)
                if m:
                    rows.append({"参加者名": m.group(1).strip(),
                                 "自己資本規制比率(%)": float(m.group(7))})
    return pd.DataFrame(rows), asof


def normalise_asof(s: str) -> str:
    """「2026年6月末」→「2026-06-30」。月末日はその月の実際の末日にする"""
    m = re.search(r"(\d{4})年\s*(\d{1,2})月末", s)
    if not m:
        return s
    y, mo = int(m.group(1)), int(m.group(2))
    nxt = date(y + (mo == 12), (mo % 12) + 1, 1)
    return str(nxt - pd.Timedelta(days=1).to_pytimedelta())


def main() -> int:
    ap = argparse.ArgumentParser(description="証券会社の自己資本規制比率を取得する")
    ap.add_argument("--url", help="PDFのURLを直接指定する")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--dry-run", action="store_true", help="書き出さずに中身を表示する")
    args = ap.parse_args()

    url, how = (args.url, "手動指定") if args.url else find_pdf()
    print(f"取得元: {url}  （{how}）")

    tmp = Path("/tmp/jpx_securities_capital.pdf")
    try:
        r = requests.get(url, headers=UA, timeout=60)
        r.raise_for_status()
        tmp.write_bytes(r.content)
    except Exception as e:
        print(f"PDFを取得できませんでした: {e}", file=sys.stderr)
        return 1

    table, asof_raw = parse_pdf(tmp)
    if table.empty:
        print("PDFから表を読み取れませんでした。様式が変わった可能性があります。", file=sys.stderr)
        return 1
    asof = normalise_asof(asof_raw)
    print(f"{len(table)}社を読み取りました（基準日 {asof or '不明'}）")

    table["コード"] = table["参加者名"].map(SEC_MAP)
    got = table.dropna(subset=["コード"]).copy()
    got["基準日"] = asof
    got["出所"] = url
    got["規制最低水準(%)"] = MIN_RATIO
    got["資本余裕度(%pt)"] = (got["自己資本規制比率(%)"] - MIN_RATIO).round(1)
    got = got[["コード", "参加者名", "自己資本規制比率(%)", "規制最低水準(%)",
               "資本余裕度(%pt)", "基準日", "出所"]].sort_values("コード")

    missing = sorted(set(SEC_MAP.values()) - set(got["コード"]))
    if missing:
        print(f"※ 対応表にあるのに一覧で見つからなかったコード: {'、'.join(missing)}",
              file=sys.stderr)

    print(f"\n上場会社に紐づいたのは {len(got)}社")
    # 列名に記号が入っているので itertuples は使えない（属性名が書き換えられる）
    for _, r in got.iterrows():
        print(f"  {r['コード']}  {r['参加者名']:<12} {r['自己資本規制比率(%)']:>7.1f}%"
              f"  （最低{MIN_RATIO:.0f}%に対し +{r['資本余裕度(%pt)']:.1f}%pt）")

    if args.dry_run:
        print("\n--dry-run のため書き出していません。")
        return 0

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    got.to_csv(out, index=False, encoding="utf-8-sig")
    (out.parent / "securities_capital_asof.txt").write_text(
        f"{asof}\n{url}\n取得 {datetime.now():%Y-%m-%d %H:%M}\n", encoding="utf-8")
    print(f"\n書き出しました → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
