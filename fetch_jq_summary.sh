#!/bin/bash
# J-Quants fins summary（決算短信サマリー＝会社予想を含む）を1日1ファイルで取り足す。
# 予想Fスコア（復活Fスコア戦略）と、四季報式スコアの経常利益・会社予想PER（keijo_yosou.py）用。run_fundamentals.sh から毎日呼ばれます。
#
#   保存先 : fundamentals/jq_summary/YYYY-MM-DD.json（開示日ごと。土日・休日は "[]"）
#   範囲   : Freeプランで取れる「12週間前」までの、直近約2年分
#            （2年分あると本決算が2期そろい、四季報式の収益性を経常利益で測れる期が増える）
#   冪等   : 既にあるファイルは取り直さない。通常は1日1件だけ取得
#   上限   : 1回の実行で最大 MAX_CALLS 件（初回の取りこぼし分は数日かけて埋まる）
#
# 手動で一気に埋めたいとき: MAX_CALLS=400 bash fetch_jq_summary.sh
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="$DIR/fundamentals/jq_summary"
MAX_CALLS="${MAX_CALLS:-40}"
mkdir -p "$OUT"

if ! command -v jquants >/dev/null 2>&1; then
  echo "jquants コマンドが見つからないため、会社予想の取得を見送ります" >&2
  exit 0
fi

END=$(date -v-84d +%Y-%m-%d)          # Freeプランの上限（12週間前）
START=$(date -v-84d -v-730d +%Y-%m-%d)
calls=0; got=0
d="$END"
# 新しい日付から古い日付へ（最新の予想修正を優先して埋める）
while [[ "$d" > "$START" || "$d" == "$START" ]]; do
  dow=$(date -j -f %Y-%m-%d "$d" +%u)
  f="$OUT/$d.json"
  if [ "$dow" -le 5 ] && [ ! -s "$f" ]; then
    [ "$calls" -ge "$MAX_CALLS" ] && break
    if jquants --output json --save "$f" fins summary --date "$d" >/dev/null 2>&1; then
      got=$((got + 1))
    else
      rm -f "$f"
    fi
    calls=$((calls + 1))
    sleep 13                             # Freeプランの呼び出し回数制限への配慮
  fi
  d=$(date -j -v-1d -f %Y-%m-%d "$d" +%Y-%m-%d)
done
echo "J-Quants fins summary: ${got}日分を取得（呼び出し ${calls}回、範囲 ${START}〜${END}）"
