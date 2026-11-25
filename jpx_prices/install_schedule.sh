#!/bin/bash
# 平日16:30の自動実行を macOS の launchd に登録する
set -e
cd "$(dirname "$0")"
DIR="$(pwd)"
LABEL="com.jpxprices.daily"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

if [ ! -x "$DIR/.venv/bin/python" ]; then
  echo "❌ .venv がありません。先に ./setup.sh を実行してください。"; exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents"
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
        <string>$DIR/run_daily.sh</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$DIR</string>
    <key>StartCalendarInterval</key>
    <array>
        <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>3</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>30</integer></dict>
    </array>
    <key>StandardOutPath</key>
    <string>$DIR/logs/launchd.out.log</string>
    <key>StandardErrorPath</key>
    <string>$DIR/logs/launchd.err.log</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
PLISTEOF

chmod +x "$DIR/run_daily.sh"
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo "✅ 登録しました: $PLIST"
echo "   平日 16:30 に $DIR/run_daily.sh が実行されます。"
echo
echo "確認 : launchctl list | grep $LABEL"
echo "即実行: launchctl start $LABEL"
echo "解除 : ./uninstall_schedule.sh"
