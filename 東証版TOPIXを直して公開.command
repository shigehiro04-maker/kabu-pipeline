#!/bin/bash
# 東証版：TOPIX を指数そのものの値（Yahoo!ファイナンス 998405.T）に直して公開（2026-11-25）
#   主要指数の取得（初回は TOPIX を2009年から取り直すので数分）→ マーケット概況 → トップ画面 → GitHub（kabu-charts）に公開
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
cd "$HOME/株分析" || exit 1
PY="$HOME/株分析/.venv/bin/python"
log(){ echo "[$(date '+%H:%M:%S')] $*"; }
log "主要指数を取得（TOPIX の取り直しで数分かかります）"
bash 株価指数/run_indices.sh
grep -E "TOPIX|998405" "logs/indices_$(date +%Y%m).log" | tail -6
tail -3 株価指数/data/topix.csv
log "マーケット概況・トップ画面を作り直し"
"$PY" make_market.py | tail -1
"$PY" make_home.py | tail -1
log "GitHub に公開"
bash deploy_github.sh && log "✔ 公開しました（数分後にサイトに反映）" || log "✘ 公開に失敗しました"
log "クラウドの日次更新用にプログラムを送る（kabu-pipeline）"
bash cloud/push_code.sh "概況の指数タイル（日中グラフ）・TOPIX を Yahoo!ファイナンスから" && log "✔ 送りました" || log "✘ 送れませんでした"
echo; read -n 1 -s -r -p "何かキーを押すと、この画面を閉じられます"
