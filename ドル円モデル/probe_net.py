#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
probe_net.py — どの取得元に、どの通信方法なら届くのかを1分で調べる。

    cd ~/株分析/ドル円モデル
    ../.venv/bin/python probe_net.py

各リクエストは15秒で打ち切るので、全部失敗しても2分はかかりません。
"""
from __future__ import annotations
import ssl
import sys
import time
import urllib.request

TIMEOUT = 15

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept": "text/csv,text/plain,*/*;q=0.8",
           "Accept-Language": "ja,en-US;q=0.9,en;q=0.8"}

TARGETS = [
    ("FRED",   "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS2&cosd=2026-09-01"),
    ("Yahoo",  "https://query1.finance.yahoo.com/v8/finance/chart/JPY=X?interval=1d&range=5d"),
    ("財務省", "https://www.mof.go.jp/jgbs/reference/interest_rate/jgbcm.csv"),
    ("日銀",   "https://www.boj.or.jp/statistics/market/short/mutan/index.htm"),
]


def via_curl_cffi(url):
    from curl_cffi import requests as cr        # 未インストールなら ImportError
    r = cr.get(url, impersonate="chrome", timeout=TIMEOUT)
    r.raise_for_status()
    return r.content


def via_requests(url):
    import requests
    s = requests.Session(); s.headers.update(HEADERS)
    r = s.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    return r.content


def via_urllib(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=TIMEOUT,
                                context=ssl.create_default_context()) as r:
        return r.read()


def via_curl(url):
    import shutil, subprocess
    exe = shutil.which("curl") or "/usr/bin/curl"
    p = subprocess.run([exe, "-sS", "--fail", "--location", "--compressed",
                        "--http1.1", "--connect-timeout", "8",
                        "--max-time", str(TIMEOUT), "-A", UA, url],
                       capture_output=True, timeout=TIMEOUT + 5)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.decode("utf-8", "replace").strip()[:120] or
                           f"終了コード {p.returncode}")
    return p.stdout


WAYS = [("curl_cffi", via_curl_cffi), ("requests", via_requests),
        ("urllib", via_urllib), ("curl", via_curl)]

print(f"python: {sys.executable}")
print(f"各リクエスト {TIMEOUT}秒で打ち切り\n")
print(f"{'取得元':<8} {'通信方法':<11} {'結果':<6} {'秒':>5}  詳細")
print("-" * 78)
best: dict[str, list[str]] = {}
for label, url in TARGETS:
    for name, fn in WAYS:
        t0 = time.time()
        try:
            data = fn(url)
            el = time.time() - t0
            print(f"{label:<8} {name:<11} {'OK':<6} {el:5.1f}  {len(data):,} バイト")
            best.setdefault(label, []).append(name)
        except ImportError:
            print(f"{label:<8} {name:<11} {'-':<6} {'':>5}  未インストール")
        except Exception as e:
            el = time.time() - t0
            print(f"{label:<8} {name:<11} {'NG':<6} {el:5.1f}  "
                  f"{type(e).__name__}: {str(e)[:60]}")
    print()

print("=" * 78)
for label, _ in TARGETS:
    ok = best.get(label)
    print(f"  {label:<8} {'→ ' + '・'.join(ok) + ' で届く' if ok else '→ どの方法でも届きませんでした'}")
