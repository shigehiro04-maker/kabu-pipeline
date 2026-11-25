#!/bin/bash
# デイトレ チャートパターン：取引中の判定と公開（launchd から15分おきに呼ばれる）
#   bash run_live.sh jp    東証（9:00〜15:40 の間だけ動く。それ以外はすぐ終わる）
#   bash run_live.sh us    米国（米東部時間 9:30〜16:10 の間だけ動く）
# 1) Yahoo から当日の5分足を取り、前日までの手元の5分足とつないで全銘柄を判定（dtp_scan.py --mode live）
# 2) 公開リポジトリには daytrade/ のデータだけを追加で送る（毎日の deploy_github.sh が履歴を1コミットにまとめ直す）
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
MK="$1"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
case "$MK" in
  jp) BASE="$HOME/株分析" ;;
  us) BASE="$HOME/米国株分析" ;;
  *) echo "使い方: run_live.sh jp|us" >&2; exit 1 ;;
esac
PY="$HOME/株分析/.venv/bin/python"
LOGD="$BASE/logs"; mkdir -p "$LOGD"
LOG="$LOGD/daytrade_live_$(date +%F).log"
LOCK="$LOGD/daytrade_live.lock"
[ -n "$(find "$LOCK" -maxdepth 0 -mmin +40 2>/dev/null)" ] && rmdir "$LOCK" 2>/dev/null
mkdir "$LOCK" 2>/dev/null || exit 0
trap 'rmdir "$LOCK" 2>/dev/null' EXIT
find "$LOGD" -name 'daytrade_live_*.log' -mtime +14 -delete 2>/dev/null

"$PY" "$DIR/dtp_scan.py" --market "$MK" --mode live >> "$LOG" 2>&1
rc=$?
[ $rc -eq 3 ] && exit 0                      # 取引時間外・休場日
echo "[$(date '+%F %T')] 判定 終了コード $rc" >> "$LOG"
[ $rc -ne 0 ] && exit 0

# 公開は検証後に判断する（2026-11-16 利用者の指定）ので、ここでは送らない。出力は data/daytrade/site/（非公開）
exit 0
