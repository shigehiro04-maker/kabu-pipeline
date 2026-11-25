"""過去10年分の日足を銘柄ごとのCSVに保存する（初回の一括取得）。

  python backfill.py            # 未取得の銘柄だけ取得（途中再開OK）
  python backfill.py --force    # 既存ファイルも作り直す
  python backfill.py --limit 20 # 動作確認用に先頭20銘柄だけ
"""
import argparse
import sys
import time

from common import (BATCH, ENCODING, SLEEP, YEARS, acquire_lock, load_incomplete,
                    load_tickers, log, price_path, save_incomplete)
from fetcher import download_batch


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="既存CSVも上書きする")
    ap.add_argument("--limit", type=int, default=0, help="先頭N銘柄だけ処理（テスト用）")
    ap.add_argument("--batch", type=int, default=BATCH, help="1回に取得する銘柄数")
    args = ap.parse_args()

    if not acquire_lock():
        log("別の取得処理が実行中です。終了します。")
        return 0

    rows = load_tickers()
    if args.limit:
        rows = rows[: args.limit]

    incomplete = load_incomplete()
    todo = [r for r in rows
            if args.force
            or not price_path(r["code"]).exists()
            or r["code"] in incomplete]
    log(f"対象 {len(rows)} 銘柄 / 取得が必要 {len(todo)} 銘柄"
        + (f"（うち履歴が不完全 {len(incomplete)} 銘柄）" if incomplete else ""))
    if not todo:
        log("すべて取得済みです。")
        return 0

    saved = skipped = 0
    failures = []
    total_batches = (len(todo) + args.batch - 1) // args.batch

    for bi in range(total_batches):
        chunk = todo[bi * args.batch : (bi + 1) * args.batch]
        log(f"バッチ {bi + 1}/{total_batches} ({len(chunk)} 銘柄) を取得中...")
        result = download_batch([r["ticker"] for r in chunk], period=f"{YEARS}y")

        for r in chunk:
            df = result.get(r["ticker"])
            if df is None or df.empty:
                failures.append(r)
                skipped += 1
                continue
            df.to_csv(price_path(r["code"]), index=False, encoding=ENCODING)
            incomplete.discard(r["code"])
            saved += 1

        save_incomplete(incomplete)
        log(f"  進捗 {min((bi + 1) * args.batch, len(todo))}/{len(todo)} "
            f"— 保存 {saved} / データなし {skipped}")
        if bi + 1 < total_batches:
            time.sleep(SLEEP)

    # データが取れなかった銘柄を1件ずつ再試行
    if failures:
        log(f"データなしだった {len(failures)} 銘柄を個別に再試行します...")
        recovered = 0
        for r in failures:
            result = download_batch([r["ticker"]], period=f"{YEARS}y")
            df = result.get(r["ticker"])
            if df is not None and not df.empty:
                df.to_csv(price_path(r["code"]), index=False, encoding=ENCODING)
                incomplete.discard(r["code"])
                recovered += 1
            time.sleep(0.4)
        save_incomplete(incomplete)
        log(f"  再試行で {recovered} 銘柄を回収")
        saved += recovered
        still = [r for r in failures if not price_path(r["code"]).exists()]
        if still:
            log("最終的にデータが取得できなかった銘柄（新規上場直後などの可能性）:")
            for r in still[:50]:
                log(f"  {r['code']} {r['name']}")
            if len(still) > 50:
                log(f"  ... 他 {len(still) - 50} 銘柄")

    log(f"完了: {saved} 銘柄を保存しました。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
