#!/bin/bash
# 理論株価の更新（run_daily.sh から毎営業日、ファンダメンタル更新の後に呼ばれます。通信なし・十数秒）
#   fetch_forecast_yahoo.py 最新の予想EPS（Yahoo・アナリスト予想）→ fundamentals/forecast_yahoo.csv
#   valuation.py        5手法の理論株価＋需給・心理補正 → fundamentals/valuation.csv・output/・data/valuation.sqlite
#   hashang_metrics.py  はっしゃん式の指標（α値・相関度・コア4条件など）→ fundamentals/hashang_metrics.csv
#   report_valuation.py ダッシュボード data/charts/valuation.html と valuation_summary.json
# 手動で実行: bash ~/株分析/理論株価/run_valuation.sh
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE="$(dirname "$DIR")"
PY="$BASE/.venv/bin/python"
[ -x "$PY" ] || PY="python3"
mkdir -p "$BASE/logs"
LOG="$BASE/logs/valuation_$(date +%Y%m).log"
echo "===== $(date '+%F %T') =====" >> "$LOG"
cd "$BASE"
# 最新の予想EPS（Yahoo のアナリスト予想）を古い順に最大1000件・15分まで取り足す。失敗しても続行
"$PY" "$DIR/fetch_forecast_yahoo.py" --max 1000 --minutes 15 >> "$LOG" 2>&1 \
  || echo "最新の予想EPSの取得に失敗（手元のファイルで続行）" >> "$LOG"
"$PY" "$DIR/valuation.py" >> "$LOG" 2>&1 \
  && { "$PY" "$DIR/hashang_metrics.py" >> "$LOG" 2>&1 || echo "はっしゃん式の指標の計算に失敗（続行）" >> "$LOG"; } \
  && "$PY" "$DIR/report_valuation.py" >> "$LOG" 2>&1
