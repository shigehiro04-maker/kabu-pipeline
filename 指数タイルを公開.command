#!/bin/bash
# マーケット概況の指数タイル（前日比％＋日中グラフ）を今すぐ公開（2026-11-25）
#   5分足を取る → トップ画面を作り直す → GitHub に公開（東証版 → 米国版）。個別チャートは作り直さないので数分で終わる。
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
PY="$HOME/株分析/.venv/bin/python"
log(){ echo "[$(date '+%H:%M:%S')] $*"; }
for D in "$HOME/株分析" "$HOME/米国株分析"; do
  N=$(basename "$D"); cd "$D" || continue
  log "$N：5分足を取得"
  "$PY" fetch_mkt_intraday.py 2>&1 | tee logs/intraday_now.log
  log "$N：トップ画面を作り直し"
  "$PY" make_home.py 2>&1 | tail -2
  log "$N：GitHub に公開"
  bash deploy_github.sh && log "✔ $N：公開しました" || log "✘ $N：公開に失敗しました"
done
log "完了。数分後に公開サイトに反映されます。"
echo; read -n 1 -s -r -p "何かキーを押すと、この画面を閉じられます"
