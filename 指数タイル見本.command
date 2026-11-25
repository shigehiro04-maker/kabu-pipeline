#!/bin/bash
# マーケット概況の指数タイル（前日比％＋日中グラフ）の見本を作って開く（2026-11-25。公開はしない）
PY="$HOME/株分析/.venv/bin/python"
OUT="$HOME/株分析/Claude outputs/market_preview"
mkdir -p "$OUT"
for D in "$HOME/株分析" "$HOME/米国株分析"; do
  N=$(basename "$D")
  echo "== $N：5分足を取得 =="
  cd "$D" && "$PY" fetch_mkt_intraday.py
  KB_HOME_OUT="$OUT/${N}_spark.html" "$PY" make_home_spark.py 2>&1 | tail -1
done
open "$OUT/株分析_spark.html" "$OUT/米国株分析_spark.html"
echo "完了。このウィンドウは閉じてかまいません。"
