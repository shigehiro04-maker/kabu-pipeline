#!/bin/bash
# 貴金属価格の日次取得を自動実行する launchd ジョブを登録します。
#   ・毎日 18:00（金属市場向けなので曜日は問わず毎日実行）
# 使い方:  bash ~/株分析/metals-price/install_metals_schedule.sh
# 解除:    launchctl unload ~/Library/LaunchAgents/com.metalsprice.daily.plist
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LABEL="com.metalsprice.daily"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

mkdir -p "$HOME/Library/LaunchAgents" "$DIR/logs"

cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$DIR/run_metals_daily.sh</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>18</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>WorkingDirectory</key>
    <string>$DIR</string>
    <key>StandardOutPath</key>
    <string>$DIR/logs/launchd.out.log</string>
    <key>StandardErrorPath</key>
    <string>$DIR/logs/launchd.err.log</string>
    <key>ProcessType</key>
    <string>Background</string>
</dict>
</plist>
PLISTEOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo "==> 登録しました: $PLIST"
echo "    毎日18:00に自動実行されます（Macがスリープ中だった場合は復帰後に実行）。"
echo "    今すぐ手動で試す場合:  launchctl start $LABEL"
echo "    ログ: $DIR/logs/"
