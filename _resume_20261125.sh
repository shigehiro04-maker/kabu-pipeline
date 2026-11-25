#!/bin/bash
# 日次更新（launchd から毎営業日16:30、およびPC起動・ログイン時に呼ばれます）
#   0) 銘柄リストの確認（JPXの一覧・新規上場・上場廃止を突き合わせ、追加・除外を反映）
#   1) 株価CSVの取得（--catchup: 最新なら何もせず、遅れていれば不足分だけ取得）
#   1b) 分割の検出・修正、1b-2) 株価CSVの点検（ありえない値・分割の日ずれ）
#   2) 業種一覧の更新
#   2a) 日経225 入れ替え予想・ウエート分析
#   2a-2) 需給分析（信用残・空売り・投資部門別）
#   2b) ファンダメンタル（決算数値・スコア・ダッシュボード）の更新
#   2c) 理論株価（5手法＋需給・心理補正）
#   3) チャートHTML＋銘柄一覧の再生成（3a 売買シグナル、3a-2 株式分析ダッシュボード）
#   3b) ドル円ページの更新
#   3b-2) 株価指数ダッシュボードの更新
#   3b-3) セクターローテーションの更新
#   3b-4) ヒートマップの更新
#   3b-5) 寄り前ギャップ（Buy-on-Gap 試験運用：答え合わせ・翌朝の候補）
#   3b-6) 業種モメンタム（第6章の試験運用：月末の順位・日々の記録）
#   3c) トップ画面の再生成（株式分析ダッシュボードを公開フォルダへ複製）
#   4) GitHub Pages へ公開
# launchd はPATHが最小構成なので、Homebrew等を明示的に足しておく
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"
PY="./.venv/bin/python"
mkdir -p logs

# 二重起動を防ぐ。16:30の処理が長引いても19:00の回が重ならないようにする。
# mkdir は同時実行でも片方しか成功しないので、ロックとして使える。
LOCK="$DIR/logs/run_daily.lock"
# 6時間以上前のロックは、異常終了で残ったものとみなして消す
if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +360 2>/dev/null)" ]; then
  rmdir "$LOCK" 2>/dev/null
fi
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "[$(date '+%F %T')] 前回の処理が実行中のためスキップ" >> logs/run_daily.log
  exit 0
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

# --- ネット切れ対策と通知のための共通関数（2026-11-11 追加） ---
# この回の実行で run_daily.log に書かれた行だけを見るため、開始時の行数を覚えておく
RUN_LOG_START=$(wc -l < logs/run_daily.log 2>/dev/null || echo 0)
RUN_LOG_START=${RUN_LOG_START//[!0-9]/}
this_run_log() { tail -n +$((RUN_LOG_START + 1)) logs/run_daily.log 2>/dev/null; }
failed_this_run() { this_run_log | grep -F "$1" | grep -vqF "再試行で成功" ; }
note() { echo "[$(date '+%F %T')] $1" >> logs/run_daily.log; }
# Yahoo・GitHub・JPX のどれにもつながればネットありとみなす
net_ok() {
  /usr/bin/curl -s -m 10 -o /dev/null https://github.com \
  && /usr/bin/curl -s -m 10 -o /dev/null https://query1.finance.yahoo.com/
}
# ネットが戻るまで最大 $1 分待つ（1分おきに確認）。戻れば0、戻らなければ1
wait_net() {
  local max=${1:-30} i
  net_ok && return 0
  # この回ですでに待ちきれなかったなら、もう待たない（何度も30分待って処理が長引かないように）
  [ -n "$NET_GAVE_UP" ] && return 1
  note "ネットにつながらないため、最大${max}分待ちます"
  for i in $(seq 1 "$max"); do
    sleep 60
    if net_ok; then note "ネットが戻りました（${i}分待ち）"; return 0; fi
  done
  note "ネットが${max}分戻らなかったため、再試行をあきらめます"
  NET_GAVE_UP=1
  return 1
}
# Macの通知センターに出す
mac_notify() {
  # クラウド（GitHub Actions）では通知センターが無いので、ファイルに書いて終了時にまとめて報告する
  if [ -n "${KABU_CLOUD:-}" ]; then echo "$1：$2" >> logs/cloud_notify.txt; return 0; fi
  /usr/bin/osascript -e "display notification \"$2\" with title \"$1\" sound name \"Basso\"" >/dev/null 2>&1 || true
}

note "11/25 昼：会社情報の作成以降を手動で再実行"
"$PY" make_company_links.py --market jp >> logs/company_info.log 2>&1 \
  || echo "[$(date '+%F %T')] 会社情報の作成に失敗（logs/company_info.log）" >> logs/run_daily.log
"$PY" make_one_screen.py >> logs/one_screen.log 2>&1 \
  || echo "[$(date '+%F %T')] 株式分析ダッシュボードの再生成に失敗（logs/one_screen.log）" >> logs/run_daily.log

# 3b) ドル円ページの更新（FRED・財務省・日銀・Yahooから取得 → ページ再生成）
#     失敗しても株チャートの公開は止めない。詳細は logs/usdjpy_YYYYMM.log。
bash "$DIR/run_usdjpy.sh" \
  || echo "[$(date '+%F %T')] ドル円ページの更新に失敗（logs/usdjpy_*.log）" >> logs/run_daily.log

# 3b-2) 株価指数ダッシュボードの更新（日経平均・TOPIX・日経VI・ダウ・S&P500・NASDAQ100・VIX）
#       Yahoo・stooq・日経・CBOE から全期間を取得して 株価指数/data/ に蓄積 → data/charts/indices.html を作る。
#       失敗しても公開は止めない。詳細は logs/indices_YYYYMM.log。
bash "$DIR/株価指数/run_indices.sh" \
  || echo "[$(date '+%F %T')] 株価指数ダッシュボードの更新に失敗（logs/indices_*.log）" >> logs/run_daily.log

# 3b-3) セクターローテーション（日米の業種RRG・ヒートマップ・相場の四季）の更新（約1〜2分）
#       Yahoo・multpl・財務省から取得し、data/charts/sector.html と sector_summary.json を作る。
#       日付付きの HTML・Excel は sector_rotation/output/ に残る。失敗しても公開は止めない。詳細は logs/sector.log。
"$PY" sector_rotation/sector_rotation.py >> logs/sector.log 2>&1 \
  || echo "[$(date '+%F %T')] セクターローテーションの更新に失敗（logs/sector.log）" >> logs/run_daily.log

# 3b-4) ヒートマップ（プライム・スタンダード・グロース・日経225／業種×銘柄、通信なし・数秒）
#       株価CSV・時価総額・日経225採用銘柄から data/charts/heatmap.html と heatmap_summary.json を作る。
#       失敗しても公開は止めない。詳細は logs/heatmap.log。
"$PY" ヒートマップ/make_heatmap.py >> logs/heatmap.log 2>&1 \
  || echo "[$(date '+%F %T')] ヒートマップの更新に失敗（logs/heatmap.log）" >> logs/run_daily.log

# 3b-5a) JPX「決算発表予定日」の Excel（承認済み・無料、数秒）。寄り前ギャップの「決算翌日」の印に使う。
#        決算発表予定日/ に保存（新しいか中身が変わったものだけ）。失敗しても前回までのファイルで続ける。詳細は logs/gap.log。
"$PY" 寄り前ギャップ/fetch_kessan_schedule.py >> logs/gap.log 2>&1 \
  || echo "[$(date '+%F %T')] 決算発表予定日の取得に失敗（logs/gap.log）" >> logs/run_daily.log

# 3b-5) 寄り前ギャップ（Buy-on-Gap 試験運用、通信なし・数十秒）
#       前日に作った候補を今日の始値・終値で答え合わせして記録し（お金は動かさない）、明日の寄り前に確認する候補を作る。
#       寄り前ギャップ/output/ に候補・記録、data/charts/gap.html と gap_summary.json を作る。詳細は logs/gap.log。
{ "$PY" 寄り前ギャップ/gap_record.py && "$PY" 寄り前ギャップ/gap_candidates.py && "$PY" 寄り前ギャップ/gap_page.py; } >> logs/gap.log 2>&1 \
  || echo "[$(date '+%F %T')] 寄り前ギャップの更新に失敗（logs/gap.log）" >> logs/run_daily.log
#       売り側（上の窓を売る、紙の記録。2026-10-12 追加）：答え合わせと画面 data/charts/gap_short.html。
#       候補は上の gap_candidates.py が同じファイルに作る。失敗しても買い側には影響しない。
{ "$PY" 寄り前ギャップ/gap_short_record.py && "$PY" 寄り前ギャップ/gap_short_page.py; } >> logs/gap.log 2>&1 \
  || echo "[$(date '+%F %T')] 寄り前ギャップ（売り側）の更新に失敗（logs/gap.log）" >> logs/run_daily.log

# 3b-6) 業種モメンタム（第6章の試験運用、通信なし・十数秒）。ルールは 業種モメンタム/PREREG.md（2026-10-12 固定）
#       月末の営業日だけ業種の順位を作り（取りこぼした月末も後から作る）、日々の記録を足し、data/charts/sector_mom.html を作る。詳細は logs/sector_mom.log。
{ "$PY" 業種モメンタム/sm_signal.py && "$PY" 業種モメンタム/sm_record.py && "$PY" 業種モメンタム/sm_page.py; } >> logs/sector_mom.log 2>&1 \
  || echo "[$(date '+%F %T')] 業種モメンタムの更新に失敗（logs/sector_mom.log）" >> logs/run_daily.log

# 3b-7) ネット切れで失敗した取得系ステップのやり直し（2026-11-11 追加）
#        業種一覧・ドル円・株価指数・セクターローテーションは、夜中や寝起きの回線切れで失敗しやすい。
#        この回に失敗していたら、ネットが戻るまで最大30分待ってから1回だけやり直す。
retry_step() {   # $1=失敗時のメッセージの一部、$2…=やり直すコマンド
  local key="$1"; shift
  failed_this_run "$key" || return 0
  wait_net 30 || return 1
  if "$@"; then note "${key}（再試行で成功）"; else note "${key}（再試行でも失敗）"; fi
}
if [ -x "$JPXPY" ]; then
  retry_step "業種一覧の更新に失敗" sh -c "\"$JPXPY\" fetch_sectors.py >> logs/sectors.log 2>&1"
fi
retry_step "ドル円ページの更新に失敗" bash "$DIR/run_usdjpy.sh"
retry_step "株価指数ダッシュボードの更新に失敗" bash "$DIR/株価指数/run_indices.sh"
retry_step "セクターローテーションの更新に失敗" sh -c "\"$PY\" sector_rotation/sector_rotation.py >> logs/sector.log 2>&1"

# 3b-2) 監視銘柄の初期設定の一覧表＝指数の採用銘柄（日経225・TOPIX・読売333。入れ替えを自動で反映。数秒）
"$PY" fetch_index_members.py >> logs/index_members.log 2>&1 \
  || echo "[$(date '+%F %T')] 指数の採用銘柄の取得に失敗（logs/index_members.log）" >> logs/run_daily.log

# 3b-8) マーケット概況（トップ画面の最上部。2026-11-16 追加）
#        海外の指数・金利・為替・商品とニュースの見出し（Yahoo・Google ニュース RSS、十数秒）→ 文章と数字の要約 market_summary.json（通信なし・数秒）。
#        取得に失敗しても手元のデータで概況は作る。詳細は logs/market.log。
"$PY" fetch_market.py >> logs/market.log 2>&1 \
  || echo "[$(date '+%F %T')] 概況用の指数・為替・ニュースの取得に失敗（logs/market.log）" >> logs/run_daily.log
"$PY" make_market.py >> logs/market.log 2>&1 \
  || echo "[$(date '+%F %T')] マーケット概況の作成に失敗（logs/market.log）" >> logs/run_daily.log

# 3c) トップ画面（4画面への入口）の再生成と、株式分析ダッシュボードを公開フォルダへ複製（数十秒）
#     dashboards/one/ → data/charts/one/、data/charts/index.html を作る。チャート一覧は charts.html。
"$PY" make_home.py >> logs/home.log 2>&1 \
  || echo "[$(date '+%F %T')] トップ画面の再生成に失敗（logs/home.log）" >> logs/run_daily.log

# 4) GitHub Pages へ公開（初回に deploy_github.sh を一度実行してあれば自動で走る）
# 全ページの明暗ボタンの見た目・表記・保存先をそろえる（ボタンが無いページには追加）
"$PY" unify_theme_button.py >> logs/theme_button.log 2>&1 \
  || echo "[$(date '+%F %T')] 明暗ボタンの統一に失敗（logs/theme_button.log）" >> logs/run_daily.log
DEPLOY_OK=1
if [ -d "$DIR/data/charts/.git" ]; then
  wait_net 30
  if bash "$DIR/deploy_github.sh" >> logs/deploy.log 2>&1; then
    :
  else
    note "GitHub Pages への公開に失敗（logs/deploy.log）"
    # 回線が戻るのを待ってから1回だけやり直す
    if wait_net 30 && sleep 60 && bash "$DIR/deploy_github.sh" >> logs/deploy.log 2>&1; then
      note "GitHub Pages への公開に失敗（再試行で成功）"
    else
      note "GitHub Pages への公開に失敗（再試行でも失敗）"
      DEPLOY_OK=0
    fi
  fi
fi

# 5) この回の失敗をまとめて Mac に通知（2026-11-11 追加）。再試行で成功したものは数えない。
# 失敗の行を「（」より前の文言ごとにまとめ、あとで「再試行で成功」が出たものは除いて数える
LEFT=$(this_run_log | grep -F "失敗" | sed -E 's/^\[[^]]*\] //' | awk '
  { key=$0; sub(/（.*/, "", key); sub(/: .*/, "", key)
    if ($0 ~ /再試行で成功/) ok[key]=1; else bad[key]=1 }
  END { n=0; for (k in bad) if (!(k in ok)) n++; print n }')
LEFT=${LEFT:-0}
if [ "$DEPLOY_OK" = 0 ]; then
  mac_notify "株分析：サイトを公開できませんでした" "GitHub への公開に失敗しました（logs/deploy.log）。ネットを確認して、もう一度実行してください"
elif [ "$LEFT" -gt 0 ]; then
  mac_notify "株分析：更新の一部が失敗" "${LEFT}件の処理が失敗しました（logs/run_daily.log）。サイトの公開はできています"
fi

# クラウド実行の結果（GitHub Actions が読んで、失敗ならメールで知らせる）
if [ -n "${KABU_CLOUD:-}" ]; then
  printf 'STATUS=%s\nLEFT=%s\nDEPLOY_OK=%s\n' "$STATUS" "$LEFT" "$DEPLOY_OK" > logs/cloud_result.env
fi

exit $STATUS
