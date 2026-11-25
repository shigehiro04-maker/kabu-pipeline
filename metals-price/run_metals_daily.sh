#!/bin/bash
# 貴金属価格の日次取得（launchd から毎日18:00に呼ばれます）
# launchd はPATHが最小構成なので、Homebrew等を明示的に足しておく
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"
mkdir -p logs

echo "[$(date '+%F %T')] ---- run_metals_daily.sh 開始 ----" >> logs/run_metals_daily.log
python3 fetch_metals.py >> logs/run_metals_daily.log 2>&1
STATUS=$?
echo "[$(date '+%F %T')] ---- 終了 (exit $STATUS) ----" >> logs/run_metals_daily.log

exit $STATUS
