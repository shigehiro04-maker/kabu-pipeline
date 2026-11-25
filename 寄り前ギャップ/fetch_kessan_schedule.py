#!/usr/bin/env python3
"""JPX「決算発表予定日」の Excel を取得する（承認済み 2026-10-12・無料。毎日 run_daily.sh から、数秒）
https://www.jpx.co.jp/listing/event-schedules/financial-announcement/ に載っている kessan*.xlsx のうち、
株分析/決算発表予定日/ に保存する（JPX は毎週更新。同じ名前でも中身が変わっていれば上書き。2〜3ファイル・数百KB）。
古い版は消さない。読み込み側（gap_common._jpx_schedule）は同じ決算期のうち「現在」日付の新しい版を使う。
"""
from __future__ import annotations

import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent.parent
DST = BASE / "決算発表予定日"
SITE = "https://www.jpx.co.jp"
PAGE = SITE + "/listing/event-schedules/financial-announcement/index.html"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}


def log(m: str) -> None:
    print(f"[{datetime.now():%F %T}] {m}", flush=True)


def main() -> int:
    DST.mkdir(exist_ok=True)
    try:
        html = requests.get(PAGE, headers=UA, timeout=30).text
    except Exception as e:
        log(f"決算発表予定日: ページを取得できませんでした（前回までのファイルを使います）: {e}")
        return 0
    links = sorted(set(re.findall(r'href="([^"]*kessan[^"]*\.xlsx)"', html)))
    if not links:
        log("決算発表予定日: ページに Excel が見つかりませんでした（ページの形が変わった可能性）")
        return 0
    new = 0
    for href in links:
        name = href.rsplit("/", 1)[-1]
        f = DST / name
        try:
            r = requests.get(href if href.startswith("http") else SITE + href, headers=UA, timeout=60)
            r.raise_for_status()
            if f.exists() and f.read_bytes() == r.content:
                continue
            f.write_bytes(r.content)
            new += 1
            log(f"決算発表予定日: {name} を保存（{len(r.content):,} バイト）")
        except Exception as e:
            log(f"決算発表予定日: {name} の取得に失敗: {e}")
        time.sleep(1)
    log(f"決算発表予定日: ページの Excel {len(links)} 件、新規・更新 {new} 件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
