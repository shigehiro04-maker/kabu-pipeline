"""当日の日足を取得し、銘柄別CSVを更新 ＋ 当日一括CSVを出力する。

取得した直近数日分は、既存CSVの同じ日付を「置き換え」ます。
これにより、場中に保存された未確定の値や、Yahoo側の事後修正が
自動的に確定値へ上書きされます。

  python daily_update.py                 # 本日分
  python daily_update.py --date 2026-08-31
"""
import argparse
import csv
import datetime as dt
import io
import subprocess
import sys
import time

from common import (BASE_DIR, BATCH, COLUMNS, DAILY_DIR, ENCODING, SLEEP,
                    TICKERS_CSV, acquire_lock, load_tickers, log,
                    mark_incomplete, price_path)
from fetcher import download_batch

UNIVERSE_MAX_AGE_DAYS = 7   # 銘柄リストがこれより古ければ自動更新
HEADER = ",".join(COLUMNS)


def refresh_universe_if_stale() -> None:
    try:
        if TICKERS_CSV.exists():
            age = time.time() - TICKERS_CSV.stat().st_mtime
            if age < UNIVERSE_MAX_AGE_DAYS * 86400:
                return
        log("銘柄リストを更新します（新規上場・市場変更の反映）...")
        subprocess.run([sys.executable, str(BASE_DIR / "fetch_universe.py")],
                       check=True, cwd=str(BASE_DIR))
    except Exception as e:
        log(f"銘柄リストの更新に失敗しました（既存リストで続行）: {e}")


def df_to_lines(df) -> "list[str]":
    buf = io.StringIO()
    df.to_csv(buf, index=False, header=False, lineterminator="\n")
    return [l for l in buf.getvalue().splitlines() if l.strip()]


def merge_into_csv(path, df) -> str:
    """既存CSVに df をマージ。戻り値は 'created' / 'updated' / 'unchanged'。"""
    new_lines = df_to_lines(df)
    if not path.exists():
        path.write_text(HEADER + "\n" + "\n".join(new_lines) + "\n", encoding=ENCODING)
        return "created"

    old = [l for l in path.read_text(encoding=ENCODING).splitlines() if l.strip()]
    body = old[1:] if old and old[0].startswith("Date") else old

    fresh_dates = set(df["Date"])
    merged = [l for l in body if l.split(",", 1)[0] not in fresh_dates] + new_lines
    merged.sort(key=lambda l: l.split(",", 1)[0])

    if merged == body:
        return "unchanged"
    path.write_text(HEADER + "\n" + "\n".join(merged) + "\n", encoding=ENCODING)
    return "updated"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="対象日 YYYY-MM-DD（既定: 本日）")
    ap.add_argument("--batch", type=int, default=BATCH)
    ap.add_argument("--days", type=int, default=10, help="取得する直近営業日数")
    args = ap.parse_args()

    target = args.date or dt.date.today().strftime("%Y-%m-%d")
    log(f"=== 日次更新 開始 (対象日: {target}) ===")

    if not acquire_lock():
        log("別の取得処理（backfill など）が実行中のため、今回はスキップします。")
        return 0

    refresh_universe_if_stale()
    rows = load_tickers()
    log(f"対象 {len(rows)} 銘柄")

    daily_rows = []
    stats = {"created": 0, "updated": 0, "unchanged": 0}
    nodata = 0
    total_batches = (len(rows) + args.batch - 1) // args.batch

    for bi in range(total_batches):
        chunk = rows[bi * args.batch : (bi + 1) * args.batch]
        result = download_batch([r["ticker"] for r in chunk], period=f"{args.days}d")

        for r in chunk:
            df = result.get(r["ticker"])
            if df is None or df.empty:
                nodata += 1
                continue

            path = price_path(r["code"])
            outcome = merge_into_csv(path, df)
            stats[outcome] += 1
            if outcome == "created":
                # 直近分しか無いので、後で backfill が10年分を取り直せるよう記録
                mark_incomplete(r["code"])

            hit = df[df["Date"] == target]
            if not hit.empty:
                rec = hit.iloc[0]
                daily_rows.append([r["code"], r["name"], r["market"]] +
                                  [rec[c] for c in COLUMNS])

        if (bi + 1) % 10 == 0 or bi + 1 == total_batches:
            log(f"  バッチ {bi + 1}/{total_batches} 完了 — 更新 {stats['updated']} / "
                f"新規 {stats['created']} / 変化なし {stats['unchanged']} / "
                f"データなし {nodata} / 当日データ {len(daily_rows)}")
        if bi + 1 < total_batches:
            time.sleep(SLEEP)

    if not daily_rows:
        log(f"{target} のデータは1銘柄もありませんでした（休場日、または配信前）。"
            f" 一括CSVは作成しません。")
        log("=== 日次更新 終了 ===")
        return 0

    out = DAILY_DIR / f"{target}.csv"
    with out.open("w", encoding=ENCODING, newline="") as f:
        w = csv.writer(f)
        w.writerow(["Code", "Name", "Market"] + COLUMNS)
        w.writerows(sorted(daily_rows, key=lambda x: x[0]))

    log(f"当日一括CSV: {out} ({len(daily_rows)} 銘柄)")
    log(f"銘柄別CSV: 更新 {stats['updated']} / 新規 {stats['created']} / "
        f"変化なし {stats['unchanged']} / データなし {nodata}")
    log("=== 日次更新 終了 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
