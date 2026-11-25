"""最新の予想EPS（Yahoo Finance のアナリスト予想コンセンサス）を取り足す。

J-Quants の無料プランは決算短信が12週間遅れで、期中の業績予想の修正が反映されない。
そこで Yahoo Finance の「今期（0y）の予想EPS平均」を銘柄ごとに取り、理論株価の予想EPSに使う。
アナリストの予想が無い銘柄（主に小型株）は、これまでどおり J-Quants の会社予想を使う。

  保存先 : fundamentals/forecast_yahoo.csv
           コード, 予想EPS(Yahoo), 予想EPS下限, 予想EPS上限, アナリスト数, 来期予想EPS(Yahoo), 取得日
  更新   : 取得日が古い順に、1回あたり最大 --max 件（既定 1000）・最大 --minutes 分（既定 15）
           毎日少しずつ回して、全銘柄を約1週間で1巡する
  手動   : ~/株分析/.venv/bin/python ~/株分析/理論株価/fetch_forecast_yahoo.py --all   # 全銘柄（1〜2時間）

run_valuation.sh から毎日呼ばれる。失敗しても手元のファイルで理論株価の計算は続く。
"""
from __future__ import annotations

import argparse
import csv
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "fundamentals" / "forecast_yahoo.csv"
COLS = ["コード", "予想EPS(Yahoo)", "予想EPS下限", "予想EPS上限", "アナリスト数", "来期予想EPS(Yahoo)", "取得日"]


def codes() -> list[str]:
    f = BASE / "tickers" / "tse_tickers.csv"
    with open(f, encoding="utf-8-sig", newline="") as fh:
        return [r["code"] for r in csv.DictReader(fh) if r.get("code")]


def load() -> dict[str, dict]:
    if not OUT.exists():
        return {}
    with open(OUT, encoding="utf-8-sig", newline="") as fh:
        return {r["コード"]: r for r in csv.DictReader(fh)}


def save(rows: dict[str, dict]) -> None:
    tmp = OUT.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        for c in sorted(rows):
            w.writerow({k: rows[c].get(k, "") for k in COLS})
    tmp.replace(OUT)


def fval(x):
    try:
        v = float(x)
        return None if v != v else v
    except Exception:
        return None


def fetch_one(code: str) -> dict:
    import yfinance as yf
    t = yf.Ticker(f"{code}.T")
    row = {"コード": code, "取得日": date.today().isoformat()}
    for attempt in range(3):
        try:
            est = t.get_earnings_estimate()
            if est is not None and len(est):
                if "0y" in est.index:
                    r = est.loc["0y"]
                    row.update({"予想EPS(Yahoo)": fval(r.get("avg")), "予想EPS下限": fval(r.get("low")),
                                "予想EPS上限": fval(r.get("high")), "アナリスト数": fval(r.get("numberOfAnalysts"))})
                if "+1y" in est.index:
                    row["来期予想EPS(Yahoo)"] = fval(est.loc["+1y"].get("avg"))
            return row
        except Exception as e:  # 429 など
            if "Too Many" in str(e) or "429" in str(e):
                time.sleep(20 * (attempt + 1))
            else:
                time.sleep(2 + random.random() * 2)
    return row                                                     # 取れなくても取得日は進める（翌週に再挑戦）


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=1000)
    ap.add_argument("--minutes", type=float, default=15)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("codes", nargs="*")
    a = ap.parse_args()
    try:
        import yfinance  # noqa: F401
    except ImportError:
        print("yfinance が無いため、最新の予想EPSの取得を見送ります", file=sys.stderr)
        return 0
    rows = load()
    target = a.codes or codes()
    if not a.codes:
        target.sort(key=lambda c: rows.get(c, {}).get("取得日", ""))          # 古い順（未取得が先頭）
        if not a.all:
            today = date.today().isoformat()
            target = [c for c in target if rows.get(c, {}).get("取得日", "") < today][: a.max]
    t0, done, got = time.time(), 0, 0
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {}
        it = iter(target)
        def submit_next():
            c = next(it, None)
            if c is not None:
                futs[ex.submit(fetch_one, c)] = c
        for _ in range(a.workers * 2):
            submit_next()
        while futs:
            for f in as_completed(list(futs)):
                c = futs.pop(f)
                try:
                    r = f.result()
                    rows[c] = r
                    done += 1
                    got += r.get("予想EPS(Yahoo)") is not None
                except Exception:
                    pass
                if done % 200 == 0:
                    save(rows)
                if a.all or (time.time() - t0) / 60 < a.minutes:
                    time.sleep(0.3)
                    submit_next()
                break
    save(rows)
    print(f"Yahoo予想EPS: {done} 銘柄を確認（予想あり {got}）・{(time.time()-t0)/60:.1f}分 → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
