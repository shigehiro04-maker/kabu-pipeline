#!/bin/bash
# 売上原価（EDINET DB）の日次取得
#   ・その日の枠（既定90件）まで取得したら終了
#   ・サーバ側の上限（無料プラン100件/日）に先に当たった場合も、そこで静かに終了
#   ・翌日の実行で、止まったところの続きから自動的に再開
#   ・全銘柄が埋まったあとは、本決算が出る頃合いの銘柄だけを取り直す
# launchd から毎日 08:00 / 21:00、およびログイン時に呼ばれます。
# 手動で動かす場合:  bash ~/株分析/run_cost_of_sales.sh
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR" || exit 1
PY="./.venv/bin/python"
[ -x "$PY" ] || PY="/usr/bin/python3"
mkdir -p logs
LOG="$DIR/logs/cost_of_sales_$(date +%Y%m).log"

# 二重起動よけ（08:00の回が長引いても21:00の回と重ならないように）
LOCK="$DIR/logs/cost_of_sales.lock"
if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +180 2>/dev/null)" ]; then
  rmdir "$LOCK" 2>/dev/null
fi
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "[$(date '+%F %T')] 前回の処理が実行中のためスキップ" >> "$LOG"
  exit 0
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

# ネットワーク復帰を最大5分待つ（Mac起動直後の実行に備える）
for i in $(seq 1 10); do
  /usr/bin/curl -s -m 10 -o /dev/null https://edinetdb.jp/ && break
  echo "[$(date '+%F %T')] ネットワーク待機中 ($i/10)" >> "$LOG"
  sleep 30
done

"$PY" fetch_cost_of_sales.py --budget "${BUDGET:-90}" >> "$LOG" 2>&1
STATUS=$?

# 3か月より古いログは片づける
find "$DIR/logs" -name 'cost_of_sales_*.log' -mtime +100 -delete 2>/dev/null

exit $STATUS
