#!/bin/bash
# Mac の米国版をクラウド運用に切り替える
#   1) Mac の米国版の日次更新（com.usstockfetch.daily）を止める（plist は ~/米国株分析/backup/ に退避）
#   2) Mac からは公開しない目印 ~/米国株分析/MAC_NO_DEPLOY を置く
#   3) クラウドの米国版データを取り込む com.kabu.pullstate.us を登録（ログイン時と1時間おき。新しい版が無ければ何もしない）
#   「いまの値」（com.usstockfetch.live）はそのまま残す。
# 元に戻す: bash ~/株分析/cloud/install_us_pull_schedule.sh --undo
set -euo pipefail
US="$HOME/米国株分析"
CLOUD="$HOME/株分析/cloud"
LA="$HOME/Library/LaunchAgents"
OLD="$LA/com.usstockfetch.daily.plist"
NEW="$LA/com.kabu.pullstate.us.plist"
BK="$US/backup/com.usstockfetch.daily.plist"
UID_=$(id -u)

if [ "${1:-}" = "--undo" ]; then
  launchctl bootout "gui/$UID_" "$NEW" 2>/dev/null || true
  rm -f "$NEW" "$US/MAC_NO_DEPLOY"
  [ -f "$BK" ] && cp -p "$BK" "$OLD" && launchctl bootstrap "gui/$UID_" "$OLD" 2>/dev/null || true
  echo "✅ Mac の米国版の日次更新に戻しました"; exit 0
fi

if [ -d "$US/logs/run_daily.lock" ]; then
  echo "✘ Mac の米国版の run_daily.sh が実行中です。終わってから実行してください" >&2; exit 1
fi
mkdir -p "$US/backup" "$US/logs"
if [ -f "$OLD" ]; then
  cp -p "$OLD" "$BK"
  launchctl bootout "gui/$UID_" "$OLD" 2>/dev/null || launchctl unload "$OLD" 2>/dev/null || true
  rm -f "$OLD"
  echo "▶ Mac の米国版の日次更新（com.usstockfetch.daily）を止めました（設定は ~/米国株分析/backup/ に退避）"
fi
touch "$US/MAC_NO_DEPLOY"
echo "▶ Mac からは米国版を公開しません（~/米国株分析/MAC_NO_DEPLOY）"

cat > "$NEW" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.kabu.pullstate.us</string>
    <key>ProgramArguments</key>
    <array><string>/bin/bash</string><string>$CLOUD/pull_state.sh</string></array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>KABU_STATE_TAG</key><string>us-state</string>
        <key>KABU_PULL_DIR</key><string>$US</string>
    </dict>
    <key>WorkingDirectory</key><string>$US</string>
    <key>RunAtLoad</key><true/>
    <key>StartInterval</key><integer>3600</integer>
    <key>StandardOutPath</key><string>$US/logs/pull_state.out.log</string>
    <key>StandardErrorPath</key><string>$US/logs/pull_state.err.log</string>
    <key>ProcessType</key><string>Background</string>
</dict>
</plist>
PLIST
launchctl bootstrap "gui/$UID_" "$NEW" 2>/dev/null || launchctl load "$NEW"
echo "✅ クラウドの米国版データの取り込み（com.kabu.pullstate.us、ログイン時と1時間おき）を登録しました"
