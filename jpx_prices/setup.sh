#!/bin/bash
# 初回セットアップ: 専用のPython仮想環境を作り、必要なライブラリを入れる
set -e
cd "$(dirname "$0")"

echo "▶ Python仮想環境を作成中 (.venv) ..."
/usr/bin/python3 -m venv .venv

echo "▶ ライブラリをインストール中 ..."
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install "yfinance>=0.2.54" pandas numpy scipy requests xlrd openpyxl

echo
echo "✅ セットアップ完了"
./.venv/bin/python -c "import yfinance,pandas;print('  yfinance',yfinance.__version__,'/ pandas',pandas.__version__)"
echo
echo "次の手順:"
echo "  1) ./.venv/bin/python fetch_universe.py   # 銘柄リスト作成"
echo "  2) ./.venv/bin/python backfill.py         # 過去10年分の取得（数時間かかります）"
echo "  3) ./install_schedule.sh                  # 平日16:30の自動実行を登録"
