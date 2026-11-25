#!/bin/bash
# ==============================================================================
# run_usdjpy.sh — ドル円ページを自動更新する
# ==============================================================================
#   単体で動かす:   bash ~/株分析/run_usdjpy.sh
#   様子だけ見る:   bash ~/株分析/run_usdjpy.sh --no-publish
#   run_daily.sh からも毎営業日呼ばれます（16:30 / 19:00 / 22:00）。
#
#   ログ:  ~/株分析/logs/usdjpy_YYYYMM.log   （月ごとに分けています）
# ==============================================================================

# launchd から呼ばれるとPATHが最小構成になり、Homebrew版のツールが見つからない
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
# 画面の無い環境でmatplotlibが止まらないようにする
export MPLBACKEND=Agg

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR" || exit 1
mkdir -p logs

# python は 株分析/.venv のものを優先する（pandas・matplotlibが入っているため）
PY="$DIR/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
if [ ! -x "$PY" ]; then
  echo "[$(date '+%F %T')] python3 が見つかりません" >> logs/run_daily.log
  exit 1
fi

LOG="$DIR/logs/usdjpy_$(date +%Y%m).log"
echo "================ $(date '+%F %T') ================" >> "$LOG"

# 進行状況を画面とログの両方に出す。
# launchd から呼ばれたとき（画面が無いとき）はログだけ。
if [ -t 1 ]; then
  "$PY" -u "$DIR/ドル円モデル/update_usdjpy.py" "$@" 2>&1 | tee -a "$LOG"
  rc=${PIPESTATUS[0]}
else
  "$PY" -u "$DIR/ドル円モデル/update_usdjpy.py" "$@" >> "$LOG" 2>&1
  rc=$?
fi

echo "終了コード: $rc" >> "$LOG"
if [ $rc -ne 0 ]; then
  echo "[$(date '+%F %T')] ドル円ページの更新に失敗（logs/$(basename "$LOG")）" \
    >> logs/run_daily.log
fi
exit $rc
