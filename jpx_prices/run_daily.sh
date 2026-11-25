#!/bin/bash
# launchd から呼ばれる日次更新ランナー
cd "$(dirname "$0")"
LOG="logs/daily_$(date +%Y-%m).log"

# ネットワークが復帰していない場合に備えて最大5分待つ
for i in $(seq 1 10); do
  if /usr/bin/curl -s -m 10 -o /dev/null https://query1.finance.yahoo.com/ ; then break; fi
  echo "[$(date '+%F %T')] ネットワーク待機中 ($i/10)" >> "$LOG"
  sleep 30
done

echo "" >> "$LOG"
./.venv/bin/python daily_update.py >> "$LOG" 2>&1
echo "[$(date '+%F %T')] exit=$?" >> "$LOG"
