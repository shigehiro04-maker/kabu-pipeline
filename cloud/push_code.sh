#!/bin/bash
# Mac の ~/株分析 にあるプログラム（.py .sh .js など）を GitHub の kabu-pipeline に送る。
# プログラムを直したら実行する（クラウドの日次更新は、次の回からこの内容で動く）:
#     bash ~/株分析/cloud/push_code.sh "変更の説明"
# データ・キー類・研究用フォルダは送らない。Git の管理情報は ~/.kabu-pipeline.git に置き、
# ~/株分析 の中には .git を作らない。
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GD="$HOME/.kabu-pipeline.git"
REPO="shigehiro04-maker/kabu-pipeline"
MSG="${1:-update $(date '+%Y-%m-%d %H:%M')}"
g() { git --git-dir="$GD" --work-tree="$DIR" -c core.quotepath=false "$@"; }

if [ ! -d "$GD" ]; then
  git init -q --bare "$GD"
  git --git-dir="$GD" config core.bare false
  git --git-dir="$GD" config core.worktree "$DIR"
  git --git-dir="$GD" symbolic-ref HEAD refs/heads/main
  g remote add origin "https://github.com/$REPO.git"
fi
g config user.name >/dev/null 2>&1 || g config user.name "shigehiro04-maker"
g config user.email >/dev/null 2>&1 || g config user.email "shigehiro04-maker@users.noreply.github.com"

cd "$DIR"
# 送る対象: パイプラインで使うフォルダのプログラムと設定だけ
LIST=$(mktemp)
find . \( -path ./.venv -o -path ./jpx_prices/.venv -o -path ./backup -o -path "./Claude outputs" \
          -o -path ./data -o -path ./fundamentals -o -path ./dashboards -o -path ./logs -o -path ./tickers \
          -o -path ./jpx_prices/data -o -name __pycache__ -o -name output -o -name secret -o -name _to_delete -o -name .wrangler \
          -o -path ./ポートフォリオ最適化 -o -path "./平均回帰*" -o -path "./日中モメンタム_*" \
          -o -path "./モメンタム_第6章_*" -o -path "./シグナル再評価_*" -o -path "./リスク管理_*" \
          -o -path "./リードラグ検証_*" -o -path "./減損リスク_*" -o -path ./ポジショントレード \
          -o -path ./マクロ分析 -o -path "./原油商社_*" \) -prune -o \
       -type f \( -name '*.py' -o -name '*.sh' -o -name '*.js' -o -name '*.css' -o -name '*.md' \
          -o -name '*.command' -o -name '*.yml' -o -name requirements.txt -o -name state_excludes.txt \) \
       ! -name '*.pre_*' ! -name '*.disabled' -print | sed 's|^\./||' | sort > "$LIST"
g rm -r -q --cached . >/dev/null 2>&1 || true
tr '\n' '\0' < "$LIST" | xargs -0 git --git-dir="$GD" --work-tree="$DIR" add -f --
N=$(wc -l < "$LIST" | tr -d ' '); rm -f "$LIST"
if g diff --cached --quiet 2>/dev/null && g rev-parse HEAD >/dev/null 2>&1; then
  echo "▶ 変更はありません（${N}ファイル）"
else
  g commit -q -m "$MSG"
  echo "▶ ${N}ファイルを記録しました: $MSG"
fi
gh auth setup-git >/dev/null 2>&1 || true
g push -q -u origin main
echo "✅ GitHub（$REPO）へ送りました"
