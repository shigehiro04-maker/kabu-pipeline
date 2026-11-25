#!/bin/bash
# 売上原価の日次取得を自動実行する launchd ジョブを登録します。
#   ・Macの起動（ログイン）直後  … RunAtLoad
#   ・スリープ復帰後や、日中に電源を入れた場合 … StartInterval（1時間ごとに様子見）
#   ・毎日 08:00 と 21:00        … StartCalendarInterval
# その日の枠を使い切っていれば1行ログを残して数秒で終了するので、
# 何度起動しても無駄な取得は走りません（1日に取るのは枠の分だけ）。
# 使い方:  bash ~/株分析/install_cost_of_sales_schedule.sh
# 解除:    launchctl unload ~/Library/LaunchAgents/com.edinetdb.costofsales.plist
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LABEL="com.edinetdb.costofsales"
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
        <string>$DIR/run_cost_of_sales.sh</string>
    </array>
    <key>StartCalendarInterval</key>
    <array>
        <dict><key>Hour</key><integer>8</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Hour</key><integer>21</integer><key>Minute</key><integer>0</integer></dict>
    </array>
    <key>StartInterval</key>
    <integer>3600</integer>
    <key>WorkingDirectory</key>
    <string>$DIR</string>
    <key>StandardOutPath</key>
    <string>$DIR/logs/cost_of_sales.launchd.out.log</string>
    <key>StandardErrorPath</key>
    <string>$DIR/logs/cost_of_sales.launchd.err.log</string>
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
echo "    Mac起動（ログイン）直後・スリープ復帰後（1時間ごとの様子見）・毎日08:00/21:00に"
echo "    自動で続きを取得します。枠を使い切っていれば数秒で終わります。"
echo "    進捗の確認:  cd ~/株分析 && ./.venv/bin/python fetch_cost_of_sales.py --status"
echo "    今すぐ動かす: launchctl start $LABEL"
echo "    ログ: $DIR/logs/cost_of_sales_YYYYMM.log"
