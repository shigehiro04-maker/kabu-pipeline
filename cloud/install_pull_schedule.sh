#!/bin/bash
# Mac をクラウド運用に切り替える（2026-11-26）
#   1) Mac の日次更新（com.stockfetch.daily）を止める（plist は ~/株分析/backup/ に退避）
#   2) Mac からは公開しない目印 cloud/MAC_NO_DEPLOY を置く
#   3) クラウドのデータを取り込む com.kabu.pullstate を登録（ログイン時と1時間おき。新しい版が無ければ何もしない）
# 元に戻す: bash ~/株分析/cloud/install_pull_schedule.sh --undo
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LA="$HOME/Library/LaunchAgents"
OLD="$LA/com.stockfetch.daily.plist"
NEW="$LA/com.kabu.pullstate.plist"
BK="$DIR/backup/com.stockfetch.daily.plist"
UID_=$(id -u)

if [ "${1:-}" = "--undo" ]; then
  launchctl bootout "gui/$UID_" "$NEW" 2>/dev/null || true
  rm -f "$NEW" "$DIR/cloud/MAC_NO_DEPLOY"
  [ -f "$BK" ] && cp -p "$BK" "$OLD" && launchctl bootstrap "gui/$UID_" "$OLD" 2>/dev/null || true
  echo "✅ Mac の日次更新に戻しました"; exit 0
fi

if [ -d "$DIR/logs/run_daily.lock" ]; then
  echo "✘ Mac の run_daily.sh が実行中です。終わってから実行してください" >&2; exit 1
fi
mkdir -p "$DIR/backup" "$DIR/logs"
if [ -f "$OLD" ]; then
  cp -p "$OLD" "$BK"
  launchctl bootout "gui/$UID_" "$OLD" 2>/dev/null || launchctl unload "$OLD" 2>/dev/null || true
  rm -f "$OLD"
  echo "▶ Mac の日次更新（com.stockfetch.daily）を止めました（設定は backup/ に退避）"
fi
touch "$DIR/cloud/MAC_NO_DEPLOY"
echo "▶ Mac からは公開しません（cloud/MAC_NO_DEPLOY）"

cat > "$NEW" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.kabu.pullstate</string>
    <key>ProgramArguments</key>
    <array><string>/bin/bash</string><string>$DIR/cloud/pull_state.sh</string></array>
    <key>WorkingDirectory</key><string>$DIR</string>
    <key>RunAtLoad</key><true/>
    <key>StartInterval</key><integer>3600</integer>
    <key>StandardOutPath</key><string>$DIR/logs/pull_state.out.log</string>
    <key>StandardErrorPath</key><string>$DIR/logs/pull_state.err.log</string>
    <key>ProcessType</key><string>Background</string>
</dict>
</plist>
PLIST
launchctl bootstrap "gui/$UID_" "$NEW" 2>/dev/null || launchctl load "$NEW"
echo "✅ クラウドのデータの取り込み（com.kabu.pullstate、ログイン時と1時間おき）を登録しました"
