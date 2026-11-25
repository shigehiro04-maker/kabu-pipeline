#!/bin/bash
# デイトレ チャートパターンの「取引中の判定」を launchd に登録する（東証・米国それぞれ15分おき）
#   bash install_live.sh            登録
#   bash install_live.sh --remove   登録を外す
# 取引時間外は run_live.sh がすぐ終わるので、15分おきに呼ばれても負担はほとんどない。
# Mac がスリープ中・電源オフの間は動かない。
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for MK in jp us; do
  LABEL="com.kabu.daytrade.$MK"
  PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
  launchctl unload "$PLIST" 2>/dev/null
  if [ "$1" = "--remove" ]; then rm -f "$PLIST"; echo "外しました: ${LABEL}"; continue; fi
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$DIR/run_live.sh</string><string>$MK</string></array>
  <key>StartInterval</key><integer>900</integer>
  <key>StandardOutPath</key><string>/tmp/$LABEL.out</string>
  <key>StandardErrorPath</key><string>/tmp/$LABEL.err</string>
</dict></plist>
EOF
  launchctl load "$PLIST" && echo "登録しました: ${LABEL}（15分おきに run_live.sh ${MK}）"
done
