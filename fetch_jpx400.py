#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JPX日経インデックス400 の構成銘柄一覧を JPX の公開ページ（無料）から取得する。

出力: fundamentals/jpx400.csv（コード, JPX日経400採用, 取得日, 出典）
  ・構成銘柄の入れ替えは年1回（8月末）なので、run_daily.sh からは25日に1回だけ動かす。
  ・索引ページから構成銘柄ファイル（CSV / Excel / PDF）のリンクを探して読む。
  ・銘柄数が 380〜420 の範囲で、東証の銘柄リストと9割以上一致したときだけ上書きする。
    それ以外（ページの形式が変わった等）は前回のファイルを残し、見つけたリンクをログに出す。

実行:
    ./.venv/bin/python fetch_jpx400.py            # 取得
    ./.venv/bin/python fetch_jpx400.py --file 手元のファイル   # ダウンロード済みの一覧から作る
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import re
import sys
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent
OUT = BASE / "fundamentals" / "jpx400.csv"
TICKERS = BASE / "tickers" / "tse_tickers.csv"
INDEX_URLS = [
    "https://www.jpx.co.jp/markets/indices/jpx-nikkei400/index.html",
    "https://www.jpx.co.jp/markets/indices/jpx-nikkei400/01.html",
]
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
CODE_RE = re.compile(r"(?<![0-9A-Za-z])([1-9][0-9][0-9A-Z][0-9A-Z])(?![0-9A-Za-z])")
N_MIN, N_MAX = 380, 420


def log(msg):
    print(f"[{dt.datetime.now():%F %T}] {msg}")


def find_links() -> list[str]:
    import requests
    links = []
    for url in INDEX_URLS:
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
        except Exception as e:
            log(f"索引ページを開けません: {url}（{e}）")
            continue
        r.encoding = r.apparent_encoding
        for href, text in re.findall(r'<a[^>]+href="([^"]+\.(?:csv|xlsx|xls|pdf))"[^>]*>(.*?)</a>', r.text, re.S | re.I):
            full = href if href.startswith("http") else "https://www.jpx.co.jp" + href
            label = re.sub(r"<[^>]+>", "", text).strip()
            links.append((full, label))
    for full, label in links:
        log(f"  リンク候補: {label[:40]} -> {full}")
    # 構成銘柄らしいものを優先（CSV > Excel > PDF）
    def score(x):
        url, label = x
        s = 0
        if re.search(r"構成銘柄|constituent|400_j|銘柄一覧", label + url, re.I):
            s -= 10
        s += {"csv": 0, "xlsx": 1, "xls": 1, "pdf": 2}[url.rsplit(".", 1)[-1].lower()]
        return s
    seen, out = set(), []
    for url, _ in sorted(links, key=score):
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def codes_from_bytes(data: bytes, ext: str) -> list[str]:
    ext = ext.lower()
    if ext == "pdf":
        from pdfminer.high_level import extract_text
        text = extract_text(io.BytesIO(data))
        return CODE_RE.findall(text)
    if ext in ("xlsx", "xls"):
        sheets = pd.read_excel(io.BytesIO(data), sheet_name=None, header=None, dtype=str)
        frames = list(sheets.values())
    else:
        for enc in ("utf-8-sig", "cp932"):
            try:
                frames = [pd.read_csv(io.BytesIO(data), header=None, dtype=str, encoding=enc)]
                break
            except Exception:
                frames = []
    codes = []
    for df in frames:
        # 「コード」の見出しがある列を優先。無ければ表全体から4桁コードを拾う
        col = None
        for i in range(min(10, len(df))):
            for j, v in enumerate(df.iloc[i].astype(str)):
                if "コード" in v or "Code" in v:
                    col = j
                    break
            if col is not None:
                break
        cells = df[col] if col is not None else df.stack()
        for v in cells.dropna().astype(str):
            m = CODE_RE.fullmatch(v.strip().replace(".0", "")[:4]) if len(v.strip()) <= 6 else None
            if m:
                codes.append(m.group(1))
    return codes


def validate(codes: list[str]) -> tuple[bool, str, list[str]]:
    uniq = sorted(set(codes))
    universe = set()
    if TICKERS.exists():
        universe = set(pd.read_csv(TICKERS, dtype=str, encoding="utf-8-sig")["code"].str.strip())
    hit = [c for c in uniq if c in universe] if universe else uniq
    ok = N_MIN <= len(hit) <= N_MAX and (not universe or len(hit) >= 0.9 * len(uniq))
    return ok, f"{len(uniq)}銘柄（東証リストと一致 {len(hit)}）", hit


def save(codes: list[str], src: str):
    t = dt.date.today().isoformat()
    df = pd.DataFrame({"コード": codes, "JPX日経400採用": 1, "取得日": t, "出典": src})
    tmp = OUT.with_suffix(".csv.tmp")
    df.to_csv(tmp, index=False, encoding="utf-8-sig")
    tmp.replace(OUT)
    log(f"保存: {OUT.relative_to(BASE)}（{len(codes)}銘柄）")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="ダウンロード済みの構成銘柄一覧（csv/xlsx/pdf）")
    a = ap.parse_args()
    if a.file:
        p = Path(a.file)
        ok, msg, codes = validate(codes_from_bytes(p.read_bytes(), p.suffix.lstrip(".")))
        log(f"{p.name}: {msg}")
        if ok:
            save(codes, p.name)
            return 0
        log("銘柄数が想定外のため保存しませんでした")
        return 1

    import requests
    for url in find_links():
        try:
            r = requests.get(url, headers=HEADERS, timeout=60)
            r.raise_for_status()
            ok, msg, codes = validate(codes_from_bytes(r.content, url.rsplit(".", 1)[-1]))
        except Exception as e:
            log(f"読めません: {url}（{e}）")
            continue
        log(f"{url}: {msg}")
        if ok:
            save(codes, url)
            return 0
    log("構成銘柄一覧が見つかりませんでした。前回のファイルを使います"
        "（JPXのページで一覧をダウンロードし --file で渡すこともできます）")
    return 1


if __name__ == "__main__":
    sys.exit(main())
