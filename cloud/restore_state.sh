#!/bin/bash
# GitHub に保存した最新の作業データを取り出し、復号して展開する。
#   GitHub Actions の日次更新のはじめに呼ばれる。
#   Mac でクラウドの最新データを取り込みたいときは（手元のデータが上書きされるので注意）:
#     bash ~/株分析/cloud/restore_state.sh
#   特定の世代を使うとき: KABU_STATE=state_20261125_1700.enc bash cloud/restore_state.sh
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIR="${KABU_STATE_DIR:-$(dirname "$HERE")}"
TAG="${KABU_STATE_TAG:-state}"
REPO="${KABU_STATE_REPO:-shigehiro04-maker/kabu-pipeline}"
NAME="${KABU_STATE:-state_latest.enc}"
WORK="${RUNNER_TEMP:-/tmp}/kabu_restore_$$"
mkdir -p "$WORK"; trap 'rm -rf "$WORK"' EXIT
[ -n "${KABU_STATE_PASS:-}" ] || KABU_STATE_PASS="$(cat "$HOME/.config/kabu/state_pass")"
export KABU_STATE_PASS
OPENSSL=/opt/homebrew/opt/openssl@3/bin/openssl
[ -x "$OPENSSL" ] || OPENSSL=$(command -v openssl)
DEC="gzip -dc"; command -v pigz >/dev/null 2>&1 && DEC="pigz -dc"

echo "▶ GitHub から $NAME を取り出しています"
for i in 1 2 3; do
  gh release download "$TAG" -R "$REPO" -p "$NAME" -D "$WORK" --clobber && break
  [ "$i" = 3 ] && { echo "✘ 取り出しに失敗しました" >&2; exit 1; }
  sleep 20
done
"$OPENSSL" enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass env:KABU_STATE_PASS < "$WORK/$NAME" \
  | $DEC | tar -xf - -C "${KABU_TARGET:-$DIR}"
echo "✅ 展開しました（$(du -sh "${KABU_TARGET:-$DIR}" | cut -f1)）"
