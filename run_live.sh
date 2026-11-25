#!/bin/bash
# 主要指数の「いまの値」を公開（launchd com.kabucharts.live から15分おき。米国の取引時間外は何もしない）
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$DIR/logs"
"$HOME/株分析/.venv/bin/python" "$DIR/fetch_live.py" >> "$DIR/logs/live.log" 2>&1
# ログは直近2000行だけ残す
tail -n 2000 "$DIR/logs/live.log" > "$DIR/logs/live.log.tmp" 2>/dev/null && mv "$DIR/logs/live.log.tmp" "$DIR/logs/live.log"
