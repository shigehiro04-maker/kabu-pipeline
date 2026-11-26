#!/bin/bash
# クラウド（GitHub Actions）が集めた最新の作業データを Mac の ~/株分析 に取り込む。
#   データ（株価・ファンダ・需給・指数など）だけを上書きし、プログラム（.py .sh .js など）・
#   ログ・研究用フォルダには触れない。手元にだけあるファイルは消さない。
#   使い方:  bash ~/株分析/cloud/pull_state.sh        （launchd からも定時に呼ぶ）
#   すでに取り込み済みの版なら何もしない（--force で取り込み直す）。
set -uo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# 米国版: KABU_STATE_TAG=us-state KABU_PULL_DIR=~/米国株分析 で同じように取り込む
DIR="${KABU_PULL_DIR:-$(dirname "$HERE")}"
TAG="${KABU_STATE_TAG:-state}"
REPO="${KABU_STATE_REPO:-shigehiro04-maker/kabu-pipeline}"
LOG="$DIR/logs/pull_state.log"
STAMP_FILE="$DIR/logs/pull_state.last"
mkdir -p "$DIR/logs"
note() { echo "[$(date '+%F %T')] $1" >> "$LOG"; }

# Mac 側で日次処理が動いている間は取り込まない
if [ -d "$DIR/logs/run_daily.lock" ]; then note "run_daily.sh が実行中のため見送り"; exit 0; fi
LOCK="$DIR/logs/pull_state.lock"
mkdir "$LOCK" 2>/dev/null || { note "前回の取り込みが実行中のため見送り"; exit 0; }
trap 'rmdir "$LOCK" 2>/dev/null; rm -rf "${WORK:-/nonexistent}"' EXIT

# いちばん新しい世代の名前（state_YYYYMMDD_HHMM.enc）
LATEST=$(gh release view "$TAG" -R "$REPO" --json assets --jq '.assets[].name' 2>>"$LOG" \
         | grep -E '^state_2[0-9_]+\.enc$' | sort | tail -1)
[ -n "$LATEST" ] || { note "クラウドの保存データが見つかりません（ネット接続・gh のログインを確認）"; exit 1; }
if [ "${1:-}" != "--force" ] && [ "$(cat "$STAMP_FILE" 2>/dev/null)" = "$LATEST" ]; then
  exit 0
fi

WORK=$(mktemp -d /tmp/kabu_pull.XXXXXX)
mkdir -p "$WORK/tree"
note "取り込み開始: $LATEST"
if ! KABU_STATE_TAG="$TAG" KABU_STATE="$LATEST" KABU_TARGET="$WORK/tree" RUNNER_TEMP="$WORK" \
     bash "$HERE/restore_state.sh" >> "$LOG" 2>&1; then
  note "取り込み失敗（ダウンロードまたは展開）"; exit 1
fi
# データだけを上書き（プログラム・ログ・キー類・Python環境は手元のものを残す）
if rsync -a \
     --exclude='*.py' --exclude='*.sh' --exclude='*.js' --exclude='*.css' --exclude='*.md' \
     --exclude='*.command' --exclude='*.yml' --exclude='/cloud/' --exclude='/.github/' \
     --exclude='/logs/' --exclude='.venv' --exclude='/edinet_key.txt' --exclude='/.edinetdb_key' \
     --exclude='/.chart_auth' --exclude='secret/' \
     "$WORK/tree/" "$DIR/" >> "$LOG" 2>&1; then
  echo "$LATEST" > "$STAMP_FILE"
  note "取り込み完了: $LATEST（最新の日次ファイル $(ls "$DIR/data/daily" 2>/dev/null | sort | tail -1)）"
else
  note "取り込み失敗（コピー）"; exit 1
fi
exit 0
