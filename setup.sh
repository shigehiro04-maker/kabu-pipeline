#!/bin/bash
# 初回セットアップ: 仮想環境を作り、必要ライブラリを入れ、過去10年分を取得します。
# 使い方:  bash ~/株分析/setup.sh
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "==> 作業フォルダ: $DIR"

if [ ! -d ".venv" ]; then
  echo "==> Python 仮想環境を作成中 ..."
  python3 -m venv .venv
fi

echo "==> ライブラリをインストール中 ..."
./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet --upgrade "yfinance>=0.2.40" pandas requests xlrd openpyxl jpholiday

echo "==> 過去10年分の取得を開始します（プライム約1,600銘柄・30〜60分ほどかかります）"
echo "    途中で止めても、もう一度実行すれば続きから取得できます。"
./.venv/bin/python fetch_stocks.py --init --years 10

echo ""
echo "==> 完了しました。保存先: $DIR/data/prices/"
echo "    毎日の自動更新を有効にするには次を実行してください:"
echo "      bash \"$DIR/install_schedule.sh\""
