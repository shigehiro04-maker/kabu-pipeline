#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""各銘柄の公式サイトURLと事業概要をYahoo!ファイナンス（米国版API）から取る

ダッシュボードの銘柄詳細に「何をしている会社か」を一行で出すためのデータです。
数字だけ並んでいても社名から事業が想像できない銘柄が多いので、概要とリンクを添えます。

取得するのは assetProfile モジュールの2つだけ。

    website              公式サイトのURL（日本語サイトが返る。言語の問題なし）
    longBusinessSummary  事業内容の説明。**英文**で、平均900文字ほど

英文のままではダッシュボードに載せられないので、この列はあくまで下書きです。
別途、日本語60〜100字に要約したものを company_profile.csv の「事業概要」列に入れます
（要約は手作業ではなくClaudeに任せています。詳しくは README_分析.md）。

    ./.venv/bin/python fetch_company_profile.py            # 未取得の銘柄だけ
    ./.venv/bin/python fetch_company_profile.py --refresh  # 全銘柄を取り直す
    ./.venv/bin/python fetch_company_profile.py --limit 50 # 動作確認用

出力: fundamentals/company_profile.csv
    コード, 会社URL, 事業概要, 事業概要(英文), 取得日
「事業概要」（日本語）は再取得しても消えません。英文だけが上書きされます。
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent
SRC = BASE / "fundamentals" / "fundamentals_latest.csv"
OUT = BASE / "fundamentals" / "company_profile.csv"

CRUMB_URL = "https://query2.finance.yahoo.com/v1/test/getcrumb"
COOKIE_URL = "https://fc.yahoo.com"
API = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/{sym}"

COLS = ["コード", "会社URL", "事業概要", "事業概要(英文)", "取得日"]

# 1件あたりの待ち時間（秒）。Yahooは連続アクセスに厳しいので詰めすぎない。
WAIT = 0.25
# 429（アクセス過多）が返ったときに待つ秒数。段階的に伸ばす。
BACKOFF = [5, 15, 45, 120]


def new_session():
    """cookieとcrumbを取り直した新しいセッションを返す"""
    from curl_cffi import requests as creq
    s = creq.Session(impersonate="chrome")
    s.get(COOKIE_URL, timeout=20)
    crumb = s.get(CRUMB_URL, timeout=20).text.strip()
    if not crumb or len(crumb) > 40:
        raise RuntimeError(f"crumbを取得できませんでした: {crumb[:40]!r}")
    return s, crumb


def fetch_one(s, crumb, code: str) -> dict | None:
    """1銘柄ぶんの assetProfile を返す。取れなければ None"""
    r = s.get(API.format(sym=f"{code}.T"),
              params={"modules": "assetProfile", "crumb": crumb}, timeout=20)
    if r.status_code == 429:
        raise TooMany()
    if r.status_code != 200:
        return None
    try:
        return r.json()["quoteSummary"]["result"][0]["assetProfile"]
    except Exception:
        return None


class TooMany(Exception):
    pass


def main() -> int:
    ap = argparse.ArgumentParser(description="公式サイトURLと事業概要を取得する")
    ap.add_argument("--src", default=str(SRC))
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--refresh", action="store_true", help="取得済みの銘柄も取り直す")
    ap.add_argument("--limit", type=int, default=0, help="先頭から何銘柄だけ試す")
    args = ap.parse_args()

    src, out = Path(args.src), Path(args.out)
    if not src.exists():
        print(f"入力が見つかりません: {src}", file=sys.stderr)
        return 1

    codes = (pd.read_csv(src, encoding="utf-8-sig", dtype={"コード": str})["コード"]
             .astype(str).drop_duplicates().tolist())

    # 既存ぶんは残す。日本語の要約を消さないための土台。
    have = pd.DataFrame(columns=COLS)
    if out.exists():
        have = pd.read_csv(out, encoding="utf-8-sig", dtype={"コード": str})
        for c in COLS:
            if c not in have.columns:
                have[c] = ""
        have = have[COLS]
    known = set(have["コード"]) if not args.refresh else set()

    todo = [c for c in codes if c not in known]
    if args.limit:
        todo = todo[:args.limit]
    print(f"対象 {len(todo):,}銘柄（全{len(codes):,}銘柄中、取得済み {len(known):,}）")
    if not todo:
        print("新しく取る銘柄はありません。")
        return 0

    s, crumb = new_session()
    rows, ng, t0 = [], [], time.time()
    for i, code in enumerate(todo, 1):
        for attempt in range(len(BACKOFF) + 1):
            try:
                j = fetch_one(s, crumb, code)
                break
            except TooMany:
                if attempt >= len(BACKOFF):
                    print(f"\n{code} でアクセス過多が続いたため中断します。"
                          f"しばらく空けてもう一度実行してください。", file=sys.stderr)
                    j = None
                    todo = todo[:i]
                    break
                w = BACKOFF[attempt]
                print(f"\n  アクセス過多。{w}秒待って再試行します（{code}）", flush=True)
                time.sleep(w)
                s, crumb = new_session()
            except Exception as e:
                if attempt >= 1:
                    print(f"\n  {code}: {e}", file=sys.stderr)
                    j = None
                    break
                time.sleep(2)
                s, crumb = new_session()

        if j is None:
            ng.append(code)
        else:
            rows.append({
                "コード": code,
                "会社URL": (j.get("website") or "").strip(),
                "事業概要": "",
                "事業概要(英文)": " ".join((j.get("longBusinessSummary") or "").split()),
                "取得日": str(date.today()),
            })

        if i % 100 == 0 or i == len(todo):
            el = time.time() - t0
            rate = i / el if el else 0
            left = (len(todo) - i) / rate if rate else 0
            print(f"  {i:,}/{len(todo):,}件  取得 {len(rows):,}  失敗 {len(ng):,}"
                  f"  残り約{left/60:.0f}分", flush=True)
            _save(out, have, rows)   # 途中で止まっても失わない

        time.sleep(WAIT)

    _save(out, have, rows)
    print(f"\n書き出しました → {out}")
    if ng:
        print(f"取得できなかった銘柄 {len(ng)}件: {'、'.join(ng[:20])}"
              + ("…" if len(ng) > 20 else ""))
    return 0


def _save(out: Path, have: pd.DataFrame, rows: list) -> None:
    """既存の日本語要約を保ったまま書き出す"""
    if not rows:
        return
    new = pd.DataFrame(rows)
    old = have.set_index("コード") if len(have) else None
    if old is not None:
        # 既に日本語の要約があるコードは、その文をそのまま引き継ぐ
        ja = new["コード"].map(old["事業概要"]).fillna("")
        new["事業概要"] = new["事業概要"].where(new["事業概要"] != "", ja)
        keep = have[~have["コード"].isin(set(new["コード"]))]
        allrows = pd.concat([keep, new], ignore_index=True)
    else:
        allrows = new
    out.parent.mkdir(parents=True, exist_ok=True)
    allrows[COLS].sort_values("コード").to_csv(out, index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    raise SystemExit(main())
