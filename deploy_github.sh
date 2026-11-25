#!/bin/bash
# チャート一式を GitHub Pages に公開する
#   初回:  bash ~/株分析/deploy_github.sh
#   以降:  同じコマンド（run_daily.sh からも自動実行）
#
# 大量ファイル（約3,700件・140MB超）を一度に送ると回線が切れやすいため、
# 400ファイルずつに分けてアップロードし、最後に1コミットへまとめ直します。
# これにより履歴は常に1コミットのままで、リポジトリが日々肥大化しません。
set -uo pipefail
# launchd から実行されるとPATHが最小構成になり、Homebrew版のgh/gitが見つからないため補う
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SITE="$DIR/data/charts"
REPO="${PAGES_REPO:-kabu-charts}"
CHUNK="${PAGES_CHUNK:-400}"

command -v git >/dev/null 2>&1 || { echo "git が見つかりません: xcode-select --install" >&2; exit 1; }
if ! command -v gh >/dev/null 2>&1; then
  echo "GitHub CLI が必要です:  brew install gh  →  gh auth login" >&2; exit 1
fi
gh auth status >/dev/null 2>&1 || { echo "GitHub にログインしていません:  gh auth login" >&2; exit 1; }
gh auth setup-git >/dev/null 2>&1 || true

# スマホ（iPhoneのホーム画面から開いたとき）で最下部まで見られるよう、全HTMLに余白の補正を入れる
# 全ページの明暗ボタンをそろえる（run_daily.sh 以外から公開したときも反映されるように）
python3 "$DIR/unify_theme_button.py" || echo "明暗ボタンの統一に失敗（公開は続行）"
python3 "$DIR/add_mobile_fix.py" || echo "mobile-fix に失敗（公開は続行）"
python3 "$DIR/pc_wide.py" || echo "pc-wide に失敗（公開は続行）"
python3 "$DIR/ux_fix.py" || echo "ux-fix に失敗（公開は続行）"
python3 "$DIR/add_live.py" || echo "live（いまの値）の追加に失敗（公開は続行）"
python3 "$DIR/site_icon.py" || echo "アイコンの追加に失敗（公開は続行）"

# 公開容量の点検（上限1GB。950MB超なら5分足を自動で減らし、1GB超なら中止）→ site_size_guard.py
python3 "$DIR/site_size_guard.py" || { echo "✘ 公開容量が上限を超えるため公開を中止します" >&2; exit 1; }

cd "$SITE" || exit 1
touch .nojekyll

[ -d .git ] || { echo "▶ リポジトリを初期化します"; git init -b main >/dev/null; }
git config user.name  >/dev/null 2>&1 || git config user.name  "kabu-charts bot"
git config user.email >/dev/null 2>&1 || git config user.email "kabu-charts@localhost"
git config http.version HTTP/1.1     # 大きなpushでの切断対策
git config http.postBuffer 52428800

if ! git remote get-url origin >/dev/null 2>&1; then
  echo "▶ GitHub にリポジトリ '$REPO' を作成します（公開リポジトリ）"
  gh repo create "$REPO" --public --source=. --remote=origin \
     --description "東証プライム・スタンダード・グロースの株価チャート" || exit 1
fi

# ---------- ローカルのGitデータが壊れたときの自動修復 ----------
# 症状: push が「could not parse commit」「Could not read」などで毎回失敗する。
# 対処: GitHub上の最新版を浅く取り直して .git を差し替え、最初から送り直す（1回だけ）。
#       壊れた .git は backup/ に退避（容量節約のため、自動退避分は最新の1つだけ残す）。
GIT_BROKEN_RE='could not parse commit|Could not read|bad object|invalid object|is corrupt|corrupt loose|missing (blob|tree|commit)|unable to read|Failed to traverse|did not send all necessary objects|packfile .* cannot be accessed|loose object .* corrupt|fatal: bad tree'
repair_git_and_restart() {
  local why="$1"
  if [ "${KABU_GIT_REPAIRED:-0}" = "1" ]; then
    echo "✘ Gitデータを修復しましたが、まだ失敗します（${why}）。公開を中止します。" >&2
    exit 1
  fi
  echo "⚠ ローカルのGitデータが壊れているようです（${why}）。GitHubから取り直して修復します"
  local url stamp tmp bk
  url=$(git -C "$SITE" remote get-url origin 2>/dev/null || echo "https://github.com/shigehiro04-maker/${REPO}.git")
  stamp=$(date '+%Y%m%d_%H%M%S')
  mkdir -p "$DIR/backup"
  tmp="$DIR/backup/fresh_clone_${stamp}.git"
  if ! git clone -q --bare --depth 1 "$url" "$tmp"; then
    rm -rf "$tmp"
    echo "✘ GitHubからの取り直しに失敗しました（回線を確認してください）。公開を中止します。" >&2
    exit 1
  fi
  # 前回までの自動退避分は消す（1つ約1GBあるため）
  for bk in "$DIR"/backup/charts_git_broken_auto_*; do [ -e "$bk" ] && rm -rf "$bk"; done
  mv "$SITE/.git" "$DIR/backup/charts_git_broken_auto_${stamp}" || { rm -rf "$tmp"; exit 1; }
  mv "$tmp" "$SITE/.git"
  ( cd "$SITE" && git config --bool core.bare false \
      && git config remote.origin.fetch "+refs/heads/*:refs/remotes/origin/*" \
      && git config user.name "kabu-charts bot" && git config user.email "kabu-charts@localhost" \
      && git config http.version HTTP/1.1 && git config http.postBuffer 52428800 \
      && git reset -q ) || { echo "✘ 修復後の設定に失敗しました。" >&2; exit 1; }
  echo "▶ 修復しました（壊れたデータは backup/charts_git_broken_auto_${stamp} に退避）。最初から送り直します"
  exec env KABU_GIT_REPAIRED=1 /bin/bash "$DIR/deploy_github.sh"
}

# 送る前の点検：手元の履歴と、GitHub上の最新コミットの履歴がたどれるか
if git rev-parse -q --verify HEAD >/dev/null 2>&1; then
  if ! _err=$(git rev-list --count HEAD 2>&1 >/dev/null) || echo "$_err" | grep -Eqi "$GIT_BROKEN_RE"; then
    repair_git_and_restart "$(echo "$_err" | tail -1)"
  fi
  _rh=$(git ls-remote origin main 2>/dev/null | cut -f1)
  if [ -n "$_rh" ] && git cat-file -e "$_rh" 2>/dev/null; then
    if ! _err=$(git rev-list --count "$_rh" 2>&1 >/dev/null) || echo "$_err" | grep -Eqi "$GIT_BROKEN_RE"; then
      repair_git_and_restart "$(echo "$_err" | tail -1)"
    fi
  fi
fi

# 3回まで自動リトライしながらpush
try_push() {
  local i
  for i in 1 2 3; do
    if git push -q "$@" origin main 2>/tmp/gitpush.err; then return 0; fi
    echo "   push失敗（$i/3回目）: $(tail -1 /tmp/gitpush.err)"
    if grep -Eqi "$GIT_BROKEN_RE" /tmp/gitpush.err; then
      repair_git_and_restart "$(tail -1 /tmp/gitpush.err)"
    fi
    sleep 5
  done
  echo "✘ アップロードに失敗しました。回線状況を確認して、もう一度実行してください。" >&2
  return 1
}

# リモートがまだ空（前回のpushが途中で切れた場合を含む）なら、履歴を作り直して
# 1チャンク目から順に送れる状態にする
if ! git ls-remote --exit-code --heads origin main >/dev/null 2>&1; then
  echo "▶ リモートが空です。最初から送り直します"
  git checkout -q --orphan __fresh 2>/dev/null || true
  git reset -q                       # 索引を空にする（作業ファイルはそのまま）
  git commit -q --allow-empty -m "init"
  git branch -q -M main
fi

# まだ1つもコミットが無ければ、まとめ先になる空コミットを作る
git rev-parse HEAD >/dev/null 2>&1 || git commit -q --allow-empty -m "init"

# .gitignore に載っているファイル（.DS_Store などの隠しファイル・*.pre_* のバックアップ）が
# 過去に公開済みなら、公開対象から外す（Mac上のファイル自体は消さない）
IGN=$(git ls-files -ci --exclude-standard | wc -l | tr -d ' ')
if [ "$IGN" -gt 0 ]; then
  echo "▶ 公開しないファイル ${IGN}件を公開対象から外します"
  git ls-files -ci --exclude-standard -z | xargs -0 git rm -q --cached -- \
    && git commit -q -m "remove ignored files" \
    || { echo "✘ 隠しファイルの除外に失敗しました。公開を中止します。" >&2; exit 1; }
fi

# macOS標準のbash 3.2には mapfile が無いのでwhile読みで配列に入れる
CHANGED=()
while IFS= read -r _f; do
  [ -n "$_f" ] && CHANGED[${#CHANGED[@]}]="$_f"
done < <(git status --porcelain -uall | awk '{print $NF}')
TOTAL=${#CHANGED[@]}
if [ "$TOTAL" -eq 0 ]; then
  echo "▶ 変更はありません"
  # 前回のpushが途中で失敗していると、ローカルにだけコミットが残っていて変更なし扱いになる。
  # リモートとずれていれば、ここで送り直す。
  REMOTE_HEAD=$(git ls-remote origin main 2>/dev/null | cut -f1)
  if [ -n "$REMOTE_HEAD" ] && [ "$(git rev-parse HEAD)" != "$REMOTE_HEAD" ]; then
    echo "▶ 前回送れなかった分を送ります"
    try_push -f || exit 1
  fi
else
  echo "▶ ${TOTAL}ファイルを ${CHUNK}件ずつアップロードします"
  n=0
  for ((i=0; i<TOTAL; i+=CHUNK)); do
    n=$((n+1))
    if ! git add -- "${CHANGED[@]:i:CHUNK}"; then
      repair_git_and_restart "git add に失敗"
    fi
    if ! git diff --cached --quiet; then
      git commit -q -m "part $n" || repair_git_and_restart "コミットに失敗"
    fi
    printf "   %d/%d 件目まで送信中…\n" $(( i+CHUNK > TOTAL ? TOTAL : i+CHUNK )) "$TOTAL"
    # リモートはこのMacの内容をそのまま写す運用なので、毎回上書きで送る
    # （前回が途中で切れて履歴が食い違っていても、これで復旧できる）
    try_push -f || exit 1
  done
  # 途中のコミットを1つにまとめ直す（中身は同じなので送信量はごくわずか）
  ROOT=$(git rev-list --max-parents=0 HEAD | tail -1)
  if [ -z "$ROOT" ]; then
    repair_git_and_restart "履歴の整理に失敗"
  fi
  git reset -q --soft "$ROOT"
  git commit -q --amend -m "charts $(date '+%Y-%m-%d %H:%M')"
  echo "▶ 履歴を1コミットに整理しています"
  try_push -f || exit 1
fi

OWNER=$(gh api user --jq .login 2>/dev/null)
gh api -X POST "repos/$OWNER/$REPO/pages" \
   -f "source[branch]=main" -f "source[path]=/" >/dev/null 2>&1 \
  && echo "▶ GitHub Pages を有効化しました" \
  || echo "▶ GitHub Pages は設定済みです"

echo ""
echo "✅ 完了しました。数分後に次のURLで見られます:"
echo "   https://${OWNER}.github.io/${REPO}/"
