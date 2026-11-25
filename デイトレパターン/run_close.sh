#!/bin/bash
# デイトレ チャートパターン：引け後の更新（毎日の更新から呼ぶ。通信なし。東証 約2分・米国 約3分）
#   bash run_close.sh jp|us
#   1) 保管庫の5分足で各パターンの過去の成績を集計（dtp_backtest.py）
#   2) その日の5分足でシグナル（結果つき）と形成中のパターンを判定（dtp_scan.py --mode close）
#   3) ページ（dtp_page.py）。出力は data/daytrade/site/（非公開。公開は検証後に判断：2026-11-16 利用者の指定）
#   4) 検証1〜7の再計算（dtp_features.py・dtp_daily.py・dtp_research.py）、
#      フォワードテストの集計（dtp_forward.py）、検証レポート（dtp_report.py → ~/株分析/data/daytrade/検証レポート.html）
MK="$1"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$HOME/株分析/.venv/bin/python"
echo "===== $(date '+%F %T') デイトレ チャートパターン（$MK）"
"$PY" "$DIR/dtp_backtest.py" --market "$MK" > /dev/null || echo "成績の集計に失敗（前回の成績で続行）"
"$PY" "$DIR/dtp_scan.py" --market "$MK" --mode close || echo "判定に失敗"
"$PY" "$DIR/dtp_page.py" --market "$MK" || echo "ページの作成に失敗"
"$PY" "$DIR/dtp_features.py" --market "$MK" | tail -1 || echo "検証用データの作成に失敗"
"$PY" "$DIR/dtp_daily.py" --market "$MK" | tail -1 || echo "日足の検証に失敗"
"$PY" "$DIR/dtp_research.py" --market "$MK" | tail -3 || echo "検証の再計算に失敗"
"$PY" "$DIR/dtp_forward.py" --market "$MK" || echo "フォワードテストの集計に失敗"
"$PY" "$DIR/dtp_report.py" || echo "レポートの作成に失敗"
