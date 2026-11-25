#!/bin/bash
# 今すぐ公開（2026-11-14 作成）
#   個別チャートを作り直してから、東証版（kabu-charts）・米国版（us-charts）を GitHub Pages に公開する。
#   ダブルクリックで実行（ターミナルが開きます）。毎日の自動更新を待たずに公開したいときに使う。
#   中身は毎日の自動更新と同じ手順（make_all_charts.py → deploy_github.sh）です。
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
JP="$HOME/株分析"; US="$HOME/米国株分析"
PY="$JP/.venv/bin/python"; [ -x "$PY" ] || PY="python3"
STAMP=$(date +%Y%m%d_%H%M)
log(){ echo "[$(date '+%H:%M:%S')] $*"; }
fail=0

run_site(){   # run_site 表示名 フォルダ
  local name="$1" dir="$2" lg="$2/logs/publish_now_charts_$STAMP.log"
  mkdir -p "$dir/logs"
  log "$name：個別チャートを作り直しています（数分〜十数分かかります）"
  if ! (cd "$dir" && "$PY" make_all_charts.py > "$lg" 2>&1); then
    log "✘ $name：チャートの作り直しに失敗しました。公開はしません（記録: $lg）"; fail=1; return
  fi
  log "$name：GitHub に公開しています"
  if (cd "$dir" && bash deploy_github.sh); then log "✔ $name：公開しました"
  else log "✘ $name：公開に失敗しました（ネットの接続を確認して、もう一度ダブルクリックしてください）"; fail=1; fi
}

log "公開を始めます（東証版 → 米国版）"
run_site "東証版" "$JP"
run_site "米国版" "$US"
echo
if [ $fail -eq 0 ]; then
  log "すべて完了しました。数分後に公開サイトに反映されます。"
  osascript -e 'display notification "東証版・米国版とも公開しました" with title "株分析"' 2>/dev/null
else
  log "一部うまくいきませんでした。上のメッセージを確認してください。"
fi
echo; read -n 1 -s -r -p "何かキーを押すと、この画面を閉じられます"
