#!/bin/bash
# 需給分析の更新（run_daily.sh から毎営業日呼ばれます。約2〜3分）
#   JPX・日証金から信用残・空売り・投資部門別を取得して 需給分析/data/ に蓄積
#   → 銘柄ごとの需給指標 fundamentals/jukyu.csv（ファンダメンタル分析のスコア一覧に結合）
#   → Excel（需給分析/output）・ダッシュボード data/charts/jukyu.html
# 手動で実行: bash ~/株分析/需給分析/run_jukyu.sh
# 初回だけ（約1年分のバックナンバーも取る）: bash ~/株分析/需給分析/run_jukyu.sh --backfill
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE="$(dirname "$DIR")"
PY="$BASE/.venv/bin/python"
mkdir -p "$BASE/logs"
LOG="$BASE/logs/jukyu_$(date +%Y%m).log"
echo "===== $(date '+%F %T') =====" >> "$LOG"
cd "$DIR"
"$PY" fetch_jukyu.py "$@" >> "$LOG" 2>&1 \
  || echo "[$(date '+%F %T')] 取得でエラー（続けて分析します）" >> "$LOG"
"$PY" analyze_jukyu.py >> "$LOG" 2>&1
STATUS=$?
# 古いExcelは60日で消す（data/ の蓄積は消さない）
find "$DIR/output" -maxdepth 1 -name '需給分析_*.xlsx' -mtime +60 -delete 2>/dev/null
exit $STATUS
