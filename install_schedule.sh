#!/bin/bash
# 日次更新を自動実行する launchd ジョブを登録します。
#   ・PC起動（ログイン）時
#   ・平日 16:30 / 19:00 / 22:00（16:30に取りこぼしても後で拾い直す）
# 実行中はスリープさせず（caffeinate -i）、ProcessType=Standard で
# バックグラウンド抑制がかからないようにしています。
# どちらもデータが最新なら即終了するので、無駄な取得は走りません。
# 使い方:  bash ~/株分析/install_schedule.sh
# 解除:    launchctl unload ~/Library/LaunchAgents/com.stockfetch.daily.plist
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LABEL="com.stockfetch.daily"
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
        <string>/usr/bin/caffeinate</string>
        <string>-i</string>
        <string>/bin/bash</string>
        <string>$DIR/run_daily.sh</string>
    </array>
    <key>StartCalendarInterval</key>
    <array>
        <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>3</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>19</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>19</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Weekday</key><integer>3</integer><key>Hour</key><integer>19</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>19</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>19</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>22</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>22</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Weekday</key><integer>3</integer><key>Hour</key><integer>22</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>22</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>22</integer><key>Minute</key><integer>0</integer></dict>
    </array>
    <key>WorkingDirectory</key>
    <string>$DIR</string>
    <key>StandardOutPath</key>
    <string>$DIR/logs/launchd.out.log</string>
    <key>StandardErrorPath</key>
    <string>$DIR/logs/launchd.err.log</string>
    <key>RunAtLoad</key>
    <true/>
    <key>ProcessType</key>
    <string>Standard</string>
    <key>LowPriorityIO</key>
    <false/>
</dict>
</plist>
PLISTEOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo "==> 登録しました: $PLIST"
echo "    次のタイミングで自動更新されます:"
echo "      ・Macを起動（ログイン）したとき"
echo "      ・平日 16:30 / 19:00 / 22:00（最新なら数秒で終わります）"
echo "    データが最新のときは数秒で終了するので、何度起動しても無駄になりません。"
echo "    今すぐ手動で試す場合:  launchctl start $LABEL"
echo "    ログ: $DIR/logs/"
