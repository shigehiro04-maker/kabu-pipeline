#!/bin/bash
# チャートを外出先のスマホからも見られるように公開する
# 使い方: bash ~/株分析/share_charts.sh
set -u
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"
PORT="${PORT:-8080}"

if ! command -v cloudflared >/dev/null 2>&1; then
  cat <<'MSG'
cloudflared が見つかりません。外部公開には一度だけインストールが必要です。

  brew install cloudflared

Homebrew が無い場合は https://brew.sh の手順でインストールしてください。
インストール後、もう一度このスクリプトを実行してください。
（自宅Wi-Fi内だけで良ければ、このままでも下記のローカルURLで見られます）
MSG
fi

# 1) ローカルWebサーバーを起動
python3 serve_charts.py "$PORT" &
SRV=$!
trap 'kill $SRV 2>/dev/null' EXIT
sleep 2

# 2) 外部からアクセスできる一時URLを発行
if command -v cloudflared >/dev/null 2>&1; then
  echo ""
  echo "外部公開URLを発行します（下の https://....trycloudflare.com をスマホで開いてください）"
  echo "Macがスリープすると切れます。長時間つなぐ場合は  caffeinate -s bash share_charts.sh  で起動してください。"
  echo ""
  cloudflared tunnel --url "http://localhost:$PORT"
else
  wait $SRV
fi
