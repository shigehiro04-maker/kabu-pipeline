#!/bin/bash
# 日経225 入れ替え予想・ウエート分析の更新（run_daily.sh から毎営業日呼ばれます。約30秒）
#   日経平均プロフィルから構成銘柄・お知らせ・除数を取得 → 株価換算係数を更新して日経平均と照合
#   → 次回の定期見直しの予想・ウエート・寄与度 → Excel・ダッシュボード・fundamentals/nikkei225.csv
# 手動で実行: bash ~/株分析/日経225/run_nikkei225.sh
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE="$(dirname "$DIR")"
mkdir -p "$BASE/logs"
LOG="$BASE/logs/nikkei225_$(date +%Y%m).log"
echo "===== $(date '+%F %T') =====" >> "$LOG"
"$BASE/.venv/bin/python" "$DIR/run_nikkei225.py" "$@" >> "$LOG" 2>&1
STATUS=$?
# 古いExcelは60日で消す（予想の記録 output/history は残す）
find "$DIR/output" -maxdepth 1 -name '日経225_*.xlsx' -mtime +60 -delete 2>/dev/null
exit $STATUS
