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

# ネットワーク復帰を最大5分待つ（起動直後の実行に備える）
for i in $(seq 1 10); do
  /usr/bin/curl -s -m 10 -o /dev/null https://query1.finance.yahoo.com/ && break
  echo "[$(date '+%F %T')] ネットワーク待機中 ($i/10)" >> logs/run_daily.log
  sleep 30
done

# 0) 銘柄リストの確認（毎日・数秒）。JPXの上場銘柄一覧（月末時点）に、月末以降の新規上場を足し、
#    上場廃止を外して tickers/tse_tickers.csv を更新する。追加・除外は logs/tickers_changes.csv と
#    Macの通知に出る。JPXから取れなくても保存済みのリストで続行し、続くようなら run_daily.log に警告。
"$PY" update_tickers.py > /dev/null 2>> logs/tickers.log \
  || echo "[$(date '+%F %T')] 銘柄リストの確認に失敗（logs/tickers.log）" >> logs/run_daily.log

# 1) 株価CSVの取得・追記
"$PY" fetch_stocks.py --catchup
STATUS=$?

# 1a) 新しくリストに入った銘柄（新規上場など）の過去10年分を取得。株価CSVが無い銘柄だけ取りに行く。
#     上場当日はYahooにまだ無いことがあるので、取れるまで毎日やり直す。
if [ -s tickers/missing_prices.txt ]; then
  "$PY" fetch_stocks.py --init --skip-existing > /dev/null 2>&1 \
    || echo "[$(date '+%F %T')] 新規銘柄の株価取得に失敗（logs/fetch_*.log）" >> logs/run_daily.log
fi

# 1b) 株式分割・併合の検出と株価CSVの修正（fetch_stocks は直近10日だけ取り直すため、
#     分割があると直近だけ調整済み・過去は未調整の不連続な系列になる。台帳 data/splits.csv は
#     fetch_fundamentals.py が株数・BPS・EPS の調整に使う）。失敗しても日次処理は続ける。詳細は logs/splits.log
"$PY" fix_splits.py > /dev/null 2>> logs/splits.log \
  || echo "[$(date '+%F %T')] 分割の検出・修正に失敗（logs/splits.log）" >> logs/run_daily.log

# 1b-2) 株価CSVの点検（通信なし・十数秒）。Yahoo が返す桁違い・負の値、上場前の埋め値の行を削除し、
#       分割の調整が権利落ち日より前から入った「日ずれ」を直す。修正前は data/prices_backup/<日付>_check/、
#       見つかったものは data/price_check_latest.csv、要約は logs/price_check.log。失敗しても日次処理は続ける。
"$PY" check_prices.py > /dev/null 2>> logs/price_check.log \
  || echo "[$(date '+%F %T')] 株価CSVの点検に失敗（logs/price_check.log）" >> logs/run_daily.log

# 1c) 過去の分割履歴の取り込み（月1回・数分）。台帳に無い過去の分割を Yahoo から足し、
#     未調整のまま残っている株価も直す。台帳は 2b で決算の株数・EPS・BPS・一株配当と
#     会社予想の1株指標を「いまの株数ベース」にそろえるのに使う（splits_util.py）。
if [ -z "$(find data/splits_backfill.stamp -mtime -30 2>/dev/null)" ]; then
  "$PY" backfill_splits.py > /dev/null 2>> logs/splits.log \
    || echo "[$(date '+%F %T')] 過去の分割履歴の取り込みに失敗（logs/splits.log）" >> logs/run_daily.log
fi

# 2) 業種（33業種）の更新。取得できなくても前回のsectors.csvで続行する
JPXPY="$DIR/jpx_prices/.venv/bin/python"
if [ -x "$JPXPY" ]; then
  "$JPXPY" fetch_sectors.py >> logs/sectors.log 2>&1 \
    || echo "[$(date '+%F %T')] 業種一覧の更新に失敗（logs/sectors.log）" >> logs/run_daily.log
fi

# 2-1) JPX日経400 の構成銘柄（入れ替えは年1回なので25日に1回だけ取得。失敗しても前回のファイルで続行）
if [ -z "$(find "$DIR/fundamentals/jpx400.csv" -mtime -25 -size +1k 2>/dev/null)" ]; then
  "$PY" fetch_jpx400.py >> logs/jpx400.log 2>&1 \
    || echo "[$(date '+%F %T')] JPX日経400の構成銘柄の取得に失敗（logs/jpx400.log）" >> logs/run_daily.log
fi

# 2a) 日経225 入れ替え予想・ウエート分析（日経平均プロフィルから構成銘柄・お知らせ・除数を取得、約30秒）
#     fundamentals/nikkei225.csv を作るので 2b のファンダメンタル分析より先に動かす。
#     失敗しても日次処理は続ける。詳細は logs/nikkei225_YYYYMM.log。
bash "$DIR/日経225/run_nikkei225.sh" \
  || echo "[$(date '+%F %T')] 日経225の更新に失敗（logs/nikkei225_*.log）" >> logs/run_daily.log

# 2a-2) 需給分析（JPXの銘柄別信用残・日証金・空売り・投資部門別を取得 → 需給指標・ダッシュボード、約2〜3分）
#       fundamentals/jukyu.csv を作るので 2b のファンダメンタル分析より先に動かす。株価CSV（1）を使う。
#       JPXの銘柄別信用残は直近5営業日分しか置かれないので、毎日取って貯める。詳細は logs/jukyu_YYYYMM.log。
bash "$DIR/需給分析/run_jukyu.sh" \
  || echo "[$(date '+%F %T')] 需給分析の更新に失敗（logs/jukyu_*.log）" >> logs/run_daily.log

# 2a-3) アナリスト予想（Yahoo・無料。目標株価・投資判断・業績予想。水曜に全銘柄を取り直す・約20分。
#        他の日は新規銘柄だけ取り、最新の終値で上昇余地を計算し直す）→ スクリーニングの「アナリスト予想」タブ（2b で作る）
if [ "$(date +%u)" = "3" ]; then AN_AGE=6; else AN_AGE=9999; fi
"$PY" fetch_analyst.py --max-age-days $AN_AGE >> logs/analyst.log 2>&1 \
  || echo "[$(date '+%F %T')] アナリスト予想の取得に失敗（logs/analyst.log）" >> logs/run_daily.log
"$PY" アナリスト予想/analyst_page.py >> logs/analyst.log 2>&1 \
  || echo "[$(date '+%F %T')] アナリスト予想ランキングの作成に失敗（logs/analyst.log）" >> logs/run_daily.log

# 2a-4) TDnet の決算短信（無料・登録不要。発表当日の売上・利益・会社予想を XBRL から取る。直近4日分、数分）
#        → fundamentals/kessan_tanshin.csv（1開示1行）・kessan_latest.csv（1銘柄1行）。TDnet は31日分しか残らないので毎日ためる。
"$PY" fetch_tdnet.py --days 4 >> logs/tdnet.log 2>&1 \
  || echo "[$(date '+%F %T')] TDnet 決算短信の取得に失敗（logs/tdnet.log）" >> logs/run_daily.log

# 2b) ファンダメンタル（決算数値・スコア・ダッシュボード）の更新
#     水曜は決算の再取得、他の日は当日終値でCSVとスコアを作り直すだけ（数秒）
bash "$DIR/run_fundamentals.sh" \
  || echo "[$(date '+%F %T')] ファンダメンタルの更新に失敗（logs/fundamentals_*.log）" >> logs/run_daily.log

# 2c) 理論株価（PER・PBR・DCF・DDM・類似企業の5手法＋需給・心理補正、通信なし・十数秒）
#     2b のスコア一覧.csv と需給スコアを使うので 2b の後に動かす。data/charts/valuation.html を作る。
bash "$DIR/理論株価/run_valuation.sh" \
  || echo "[$(date '+%F %T')] 理論株価の更新に失敗（logs/valuation_*.log）" >> logs/run_daily.log

# 3) チャートHTML＋銘柄一覧の再生成
# 5分足（直近1か月を取り、手元と合わせて20営業日分を保存。チャートの5日・10日に使う。約5分）
"$PY" fetch_intraday.py >> logs/intraday.log 2>&1 \
  || echo "[$(date '+%F %T')] 5分足の取得に失敗（logs/intraday.log）" >> logs/run_daily.log
"$PY" make_all_charts.py

# 3-1) チャートの形（直近3か月の値動きを25通りに分類した一覧、通信なし・約10秒）→ data/charts/patterns.html
"$PY" make_pattern_page.py > /dev/null 2>> logs/patterns.log \
  || echo "[$(date '+%F %T')] チャートの形の再生成に失敗（logs/patterns.log）" >> logs/run_daily.log

# 3a) 売買シグナル（テクニカル／ファンダの速度メーター）の再生成（通信なし・約40秒）
#     株価CSVとスコア一覧.csv から data/charts/signals.html を作る。詳細は logs/signals.log。
"$PY" make_signal_dashboard.py > /dev/null 2>> logs/signals.log \
  || echo "[$(date '+%F %T')] 売買シグナルの再生成に失敗（logs/signals.log）" >> logs/run_daily.log

# 3a-2) 株式分析ダッシュボード（銘柄ごとの1画面：シグナル・チャート・ファンダ）の再生成（通信なし・約1分）
#       signals.html・株価CSV・ファンダのCSVから dashboards/one/ を作る。詳細は logs/one_screen.log。
# 会社情報（従業員・同業他社・関連企業。2026-11-18）。Yahoo の業種・よく一緒に見られている銘柄は水曜に取り直す（約30分）
if [ "$(date +%u)" = "3" ]; then CO_AGE=6; else CO_AGE=9999; fi
"$PY" fetch_related_yahoo.py --market jp --max-age-days $CO_AGE >> logs/company_info.log 2>&1 \
  || echo "[$(date '+%F %T')] 同業他社（Yahoo）の取得に失敗（logs/company_info.log）" >> logs/run_daily.log
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
