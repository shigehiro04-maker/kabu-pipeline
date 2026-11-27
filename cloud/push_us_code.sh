#!/bin/bash
# Mac の ~/米国株分析 にあるプログラム（.py .sh .js .html の型紙など）を GitHub の us-pipeline に送る。
# 米国版のプログラムを直したら実行する（クラウドの米国版の更新は、次の回からこの内容で動く）:
#     bash ~/株分析/cloud/push_us_code.sh "変更の説明"
# データ・ログ・backup は送らない。Git の管理情報は ~/.us-pipeline.git に置き、~/米国株分析 の中には .git を作らない。
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
DIR="$HOME/米国株分析"
GD="$HOME/.us-pipeline.git"
REPO="shigehiro04-maker/us-pipeline"
MSG="${1:-update $(date '+%Y-%m-%d %H:%M')}"
g() { git --git-dir="$GD" --work-tree="$DIR" -c core.quotepath=false "$@"; }

gh repo view "$REPO" >/dev/null 2>&1 || \
  gh repo create "$REPO" --public --description "米国株分析サイトの日次更新用プログラム（GitHub Actions は kabu-pipeline で動く）" >/dev/null
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
LIST=$(mktemp)
find . \( -path ./.venv -o -path ./backup -o -path ./data -o -path ./fundamentals -o -path ./dashboards \
          -o -path ./logs -o -path ./tickers -o -path "./*/data" -o -name __pycache__ -o -name output \
          -o -name secret -o -name _to_delete \) -prune -o \
       -type f \( -name '*.py' -o -name '*.sh' -o -name '*.js' -o -name '*.css' -o -name '*.md' \
          -o -name '*.command' -o -name '*_template.html' -o -name '*.svg' -o -name 'requirements*.txt' \) \
       ! -name '*.pre_*' ! -name '*.disabled' ! -name '*.v1' -print | sed 's|^\./||' | sort > "$LIST"
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
echo "✅ GitHub（${REPO}）へ送りました"
