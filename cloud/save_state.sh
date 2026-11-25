#!/bin/bash
# 作業データ一式（株価・ファンダ・需給などの蓄積）を圧縮・暗号化して GitHub に保存する。
#   保存先: kabu-pipeline リポジトリのリリース「state」（中身は暗号化済みで、パスワードなしでは読めない）
#   GitHub Actions の日次更新の最後に呼ばれる。Mac から最新データを送り直すときも使える:
#     bash ~/株分析/cloud/save_state.sh
#   パスワード: 環境変数 KABU_STATE_PASS、なければ ~/.config/kabu/state_pass
#   世代: state_YYYYMMDD_HHMM.enc を KEEP 個残し、最新を state_latest.enc として置く
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="${KABU_STATE_REPO:-shigehiro04-maker/kabu-pipeline}"
TAG=state
KEEP="${KABU_KEEP:-7}"
STAMP=$(TZ=Asia/Tokyo date +%Y%m%d_%H%M)
WORK="${RUNNER_TEMP:-/tmp}/kabu_state_$$"
mkdir -p "$WORK"; trap 'rm -rf "$WORK"' EXIT
OUT="$WORK/state_$STAMP.enc"
[ -n "${KABU_STATE_PASS:-}" ] || KABU_STATE_PASS="$(cat "$HOME/.config/kabu/state_pass")"
export KABU_STATE_PASS
OPENSSL=/opt/homebrew/opt/openssl@3/bin/openssl
[ -x "$OPENSSL" ] || OPENSSL=$(command -v openssl)
COMP="gzip -6"; command -v pigz >/dev/null 2>&1 && COMP="pigz -6"
cd "$DIR"

echo "▶ 作業データを圧縮・暗号化しています"
tar --exclude-from=cloud/state_excludes.txt --exclude='__pycache__' --exclude='*.pre_*' \
    --exclude='*.zip' --exclude='.DS_Store' --exclude='_to_delete' -cf - . \
  | $COMP \
  | "$OPENSSL" enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass env:KABU_STATE_PASS > "$OUT"
BYTES=$(wc -c < "$OUT" | tr -d ' ')
SIZE="$((BYTES / 1048576))MB"
# 壊れた・極端に小さいファイルで最新版を上書きしないための点検（復号して gzip として読めるか）
"$OPENSSL" enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass env:KABU_STATE_PASS < "$OUT" | gzip -t
if [ "$BYTES" -lt 200000000 ]; then
  echo "✘ 保存ファイルが小さすぎます（${SIZE}）。保存を中止します" >&2; exit 1
fi
if [ "$BYTES" -gt 2000000000 ]; then
  echo "✘ 保存ファイルが2GBを超えました（${SIZE}）。GitHubの上限のため保存を中止します" >&2; exit 1
fi

gh release view "$TAG" -R "$REPO" >/dev/null 2>&1 || \
  gh release create "$TAG" -R "$REPO" --title "作業データ（暗号化）" \
     --notes "日次更新の作業データ。暗号化されており、パスワードなしでは読めません。" >/dev/null
echo "▶ GitHub へ送っています（${SIZE}）"
for i in 1 2 3; do
  gh release upload "$TAG" "$OUT" -R "$REPO" --clobber && break
  [ "$i" = 3 ] && { echo "✘ 送信に失敗しました" >&2; exit 1; }
  sleep 20
done
cp "$OUT" "$WORK/state_latest.enc"
for i in 1 2 3; do
  gh release upload "$TAG" "$WORK/state_latest.enc" -R "$REPO" --clobber && break
  [ "$i" = 3 ] && { echo "✘ 最新版の置き換えに失敗しました（日付つきの版は保存済み）" >&2; exit 1; }
  sleep 20
done

# 古い世代を消す
gh release view "$TAG" -R "$REPO" --json assets --jq '.assets[].name' \
  | grep -E '^state_2[0-9_]+\.enc$' | sort -r | awk -v k="$KEEP" 'NR>k' \
  | while read -r f; do gh release delete-asset "$TAG" "$f" -R "$REPO" -y >/dev/null && echo "   古い世代を削除: $f"; done
echo "✅ 保存しました: state_$STAMP.enc（${SIZE}）"
