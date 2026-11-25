#!/bin/bash
LABEL="com.jpxprices.daily"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
launchctl unload "$PLIST" 2>/dev/null || true
rm -f "$PLIST"
echo "✅ 自動実行を解除しました。"
