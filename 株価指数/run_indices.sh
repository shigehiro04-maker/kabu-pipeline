#!/bin/bash
# ==============================================================================
# run_indices.sh — 主要指数ダッシュボード（旧 株価指数ダッシュボード）を自動更新する
# ==============================================================================
#   単体で動かす:   bash ~/株分析/株価指数/run_indices.sh
#   run_daily.sh からも毎営業日呼ばれます（3b-2）。
#
#   データ:  ~/株分析/株価指数/data/<指標>.csv（全期間を蓄積。all_close.csv は終値一覧）
#   出力:    ~/株分析/data/charts/indices.html（トップ画面の「主要指数ダッシュボード」。指数・金利・為替・商品）
#   ログ:    ~/株分析/logs/indices_YYYYMM.log
# ==============================================================================
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # 株価指数/
BASE="$(dirname "$HERE")"                               # 株分析/
cd "$BASE" || exit 1
mkdir -p logs

PY="$BASE/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"

LOG="$BASE/logs/indices_$(date +%Y%m).log"
echo "================ $(date '+%F %T') ================" >> "$LOG"

# 米国の騰落レシオ（ダウ・S&P500・NASDAQ100 の構成銘柄から計算）。失敗しても前回分でページは作る
"$PY" -u "$HERE/fetch_us_breadth.py" >> "$LOG" 2>&1 \
  || echo "[$(date '+%F %T')] 米国の騰落レシオの更新に失敗（前回分を使用）" >> "$LOG"

ARGS=(--outdir "$HERE/data" --html "$BASE/data/charts/indices.html" --home ./index.html)
if [ -t 1 ]; then
  "$PY" -u "$HERE/fetch_indices.py" "${ARGS[@]}" "$@" 2>&1 | tee -a "$LOG"
  rc=${PIPESTATUS[0]}
else
  "$PY" -u "$HERE/fetch_indices.py" "${ARGS[@]}" "$@" >> "$LOG" 2>&1
  rc=$?
fi
echo "終了コード: $rc" >> "$LOG"
exit $rc
