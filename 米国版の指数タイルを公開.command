#!/bin/bash
# 米国版のトップ画面（マーケット概況の指数タイル）を今すぐ公開（2026-11-25）
#   5分足を取る → トップ画面を作り直す → GitHub（us-charts）に公開。個別チャートは作り直さないので数分で終わる。
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
PY="$HOME/株分析/.venv/bin/python"
log(){ echo "[$(date '+%H:%M:%S')] $*"; }
cd "$HOME/米国株分析" || exit 1
log "米国版：5分足を取得"
"$PY" fetch_mkt_intraday.py 2>&1 | tee logs/intraday_now.log
log "米国版：トップ画面を作り直し"
"$PY" make_home.py 2>&1 | tail -2
log "米国版：GitHub に公開"
bash deploy_github.sh && log "✔ 米国版：公開しました（数分後にサイトに反映）" || log "✘ 米国版：公開に失敗しました"
echo; read -n 1 -s -r -p "何かキーを押すと、この画面を閉じられます"
