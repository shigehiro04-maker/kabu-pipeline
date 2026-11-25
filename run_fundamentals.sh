#!/bin/bash
# ファンダメンタルの更新（run_daily.sh から毎営業日呼ばれます）
#
#   水曜        : 次の本決算が出ているはずの銘柄だけ Yahoo から取り直す（数分）
#   その他の平日 : 通信せず、当日終値でCSVを作り直すだけ（数秒。PER・PBR・配当利回りが最新に）
#
# 手動で決算の再取得をしたいとき:  bash ~/株分析/run_fundamentals.sh --due
# 全銘柄を取り直したいとき:        ./.venv/bin/python fetch_fundamentals.py --refresh

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR" || exit 1
PY="./.venv/bin/python"
LOG="$DIR/logs/fundamentals_$(date +%Y-%m-%d).log"

if [ "$1" = "--due" ] || [ "$(date +%u)" = "3" ]; then
  MODE="--due-only"
else
  MODE="--rebuild-only"
fi

# 新規上場銘柄（株価履歴1年未満）のいまの株数を Yahoo の銘柄情報から取る（数秒〜十数秒）。
# 決算データの株数が上場前のまま・空のときに fetch_fundamentals.py がこれを使う。
"$PY" fetch_new_listing_shares.py >> "$LOG" 2>&1 \
  || echo "新規上場銘柄の株数取得に失敗しました（$LOG を確認）" >&2

# --years 4 は総合評価の成長性・収益性が直近4期を使うため。ここを減らすと評価が変わります。
"$PY" fetch_fundamentals.py $MODE --years 4 >> "$LOG" 2>&1
STATUS=$?

# Yahoo の財務数値を公式値に合わせる（通信なし・数秒）。優先順位は 有報（EDINET DB で取得済みの分）＞
# 決算短信（J-Quants 決算短信サマリー）＞ Yahoo。短信が出ているのに Yahoo に無い新しい本決算は行を追加する。
# Yahoo は営業利益に売上総利益を入れる・IFRSの営業利益を独自に組み替える・決算期を1年ずらすことがある（2026-11-02 の照合で320銘柄）。
"$PY" reconcile_edinet.py >> "$LOG" 2>&1 \
  || echo "有報との突き合わせに失敗しました（$LOG を確認）" >&2

# 発行済株式数の照合。まず公式値（決算短信・有報の株数×その後の分割）と突き合わせ（通信なし・数秒）、
# ずれた銘柄だけ株探の「いまの株数」を取りに行く（1件3秒）。毎週土曜は分割台帳の銘柄＋無作為50件も。
# 結果（fundamentals/shares_external.csv）は次回以降の reconcile_edinet.py が使う。
"$PY" shares_crosscheck.py >> "$LOG" 2>&1 || echo "株数の突き合わせに失敗しました（$LOG を確認）" >&2
if [ "$(date +%u)" = "6" ]; then
  nohup sh -c "\"$PY\" verify_shares.py --codes-file fundamentals/verify/shares_suspects.txt; \"$PY\" verify_shares.py --sample 50" >> "$DIR/logs/verify_shares.log" 2>&1 &
elif [ -s "$DIR/fundamentals/verify/shares_suspects.txt" ]; then
  nohup "$PY" verify_shares.py --codes-file fundamentals/verify/shares_suspects.txt >> "$DIR/logs/verify_shares.log" 2>&1 &
fi

# JPX上場銘柄一覧・EDINETコードリスト・有報との照合結果を fundamentals/verify/ に出す（約1分）。
# 有報が未取得の疑わしい銘柄は edinet_priority.txt に書き、売上原価の取得（EDINET DB）で先に取る。
"$PY" verify_data.py >> "$LOG" 2>&1 \
  || echo "データ照合に失敗しました（$LOG を確認）" >&2

# 銀行のバーゼル自己資本比率（年1回しか更新されないので、月1回だけ様子を見る）
# 索引ページから最新年度を自分で探すので、URLの手直しは要りません。
# 取得に失敗しても手元のCSVがそのまま使われ、日次の処理は止まりません。
if [ "$1" = "--banks" ] || [ -z "$(find "$DIR/fundamentals/bank_capital.csv" -mtime -25 2>/dev/null)" ]; then
  "$PY" fetch_bank_capital.py --download >> "$LOG" 2>&1 \
    || echo "銀行の自己資本比率の更新に失敗しました（$LOG を確認）" >&2
fi

# 証券会社の自己資本規制比率（日本取引所グループが四半期ごとに公表。月1回だけ様子を見る）
# 索引ページから最新PDFを自分で探すので、四半期が変わってもURLの手直しは要りません。
if [ "$1" = "--banks" ] || [ -z "$(find "$DIR/fundamentals/securities_capital.csv" -mtime -25 2>/dev/null)" ]; then
  "$PY" fetch_securities_capital.py >> "$LOG" 2>&1 \
    || echo "証券会社の自己資本規制比率の更新に失敗しました（$LOG を確認）" >&2
fi

# 新高値（52週・上場来）の判定（株価データだけを使うので通信不要・約20秒）
"$PY" compute_new_high.py >> "$LOG" 2>&1 \
  || echo "新高値の計算に失敗しました（$LOG を確認）" >&2

# ベータ値の再計算（株価データだけを使うので通信不要・約8秒）
"$PY" compute_beta.py >> "$LOG" 2>&1 \
  || echo "ベータ値の計算に失敗しました（$LOG を確認）" >&2

# テクニカル指標（SBI証券スクリーナーの株価パフォーマンス・テクニカル相当。RSI・MACD・GC/DC・一目など。
# 株価データだけを使うので通信不要・約1分）
"$PY" compute_technical.py >> "$LOG" 2>&1 \
  || echo "テクニカル指標の計算に失敗しました（$LOG を確認）" >&2

# スクリーニング定義表の追加指標（CCI・ATR・VR などのテクニカル14種、寄付比、チャート形状、
# PER・PBR・配当利回りの20日変化率）。株価データだけを使うので通信不要・約20秒。
# PER などの変化率のため fundamentals/valuation_history.csv に毎日の値を貯める。
"$PY" compute_technical_extra.py >> "$LOG" 2>&1 \
  || echo "スクリーニング用の追加指標の計算に失敗しました（$LOG を確認）" >&2

# 会社予想（J-Quants fins summary）を取り足す。予想Fスコア＝復活Fスコア戦略に使う。
# 通常は1日1件・十数秒。jquants が無い・失敗した日も手元のファイルで続行します。
bash "$DIR/fetch_jq_summary.sh" >> "$LOG" 2>&1 \
  || echo "会社予想の取得に失敗しました（$LOG を確認）" >&2

# TDnet から読んだ決算短信の数字（fetch_tdnet.py）を J-Quants の決算短信サマリーで答え合わせする（通信なし・数秒）。
# J-Quants は12週遅れなので、12週前の開示から順に確かめていく。食い違いは fundamentals/verify/tdnet_vs_jquants.csv。
"$PY" verify_tdnet_jq.py >> "$LOG" 2>&1 \
  || echo "TDnet と J-Quants の突き合わせに失敗しました（$LOG を確認）" >&2

# 大株主と貸借対照表（有価証券報告書、EDINET API・無料）を差分だけ取り足す。株主構成の円グラフと貸借対照表のグラフ用。
# 新しい有報が出た銘柄だけ取りに行く（通常は数件・数十秒。6月下旬の提出集中期は1回300件まで）。失敗しても続行。
"$PY" fetch_shareholders.py --max 300 >> "$LOG" 2>&1 \
  || echo "大株主の取得に失敗しました（$LOG を確認）" >&2

# 従業員の状況（従業員数・平均年齢・平均勤続年数・平均年収）と関係会社の状況（同じ有報、EDINET API・無料）。
# 書類一覧は上の fetch_shareholders.py が更新したものを使い、新しい有報が出た銘柄だけ取りに行く（2026-11-18）。
"$PY" fetch_employees.py --max 300 >> "$LOG" 2>&1 \
  || echo "従業員・関係会社の取得に失敗しました（$LOG を確認）" >&2

# 業績ダッシュボード（dashboards/<コード>.html。通期・CF・四半期・配当・株主構成。通信なし・数十秒）
# make_home.py が data/charts/gyoseki/ に複製して公開する。
"$PY" make_company_dashboards.py >> "$LOG" 2>&1 \
  || echo "業績ダッシュボードの再生成に失敗しました（$LOG を確認）" >&2

# スコアリングとダッシュボードの再生成（通信しないので数秒。取得に失敗した日も手元のCSVから作り直す）
#
# 公開するページは「金融4業種の安全性と収益性を評価しない版」だけ（2026-09-24 に標準版のページを廃止）。
#   金融4業種＝銀行・保険・証券商品先物・その他金融（東洋経済60業種の大手銀行・地方銀行・証券先物・
#   リース消費者金融・損害保険・生命保険にあたる168社）
# 標準版の分析（fundamentals/analysis）は、Excel・CSV と、ひと目でわかる画面・シグナルの元データとして
# 作り続ける。ページのURL（fundamentals.html / fundamentals_simple.html）は変えていない。
"$PY" analyze_fundamentals.py >> "$LOG" 2>&1 \
  || echo "ファンダメンタル分析（標準版のデータ）の再生成に失敗しました（$LOG を確認）" >&2

"$PY" analyze_fundamentals.py --no-financial-safety --no-excel \
       --out fundamentals/analysis_nofin >> "$LOG" 2>&1 \
  && "$PY" make_fundamental_dashboard.py \
       --src fundamentals/analysis_nofin/dashboard_data.json \
       --out data/charts/fundamentals.html \
       --title "東証スクリーニング" \
       --badge "金融の安全性・収益性は評価しない" >> "$LOG" 2>&1 \
  || echo "ファンダメンタル分析のページの再生成に失敗しました（$LOG を確認）" >&2

# かんたん表示（ランキング・スクリーニング・業種マップだけの軽いページ。通信なし・数秒）
"$PY" make_fundamental_simple.py \
       --src fundamentals/analysis_nofin/dashboard_data.json \
       --out data/charts/fundamentals_simple.html \
       --full-url fundamentals.html >> "$LOG" 2>&1 \
  || echo "かんたん表示の再生成に失敗しました（$LOG を確認）" >&2

# 以前の金融除外版のURL（ブックマーク用）は、同じ内容の新しいページへ転送する
for pair in "fundamentals_nofin.html:fundamentals.html" "fundamentals_simple_nofin.html:fundamentals_simple.html"; do
  old="${pair%%:*}"; new="${pair##*:}"
  printf '<!doctype html><meta charset="utf-8"><title>移動しました</title><meta http-equiv="refresh" content="0;url=%s"><link rel="canonical" href="%s"><p><a href="%s">東証スクリーニングへ移動しました</a></p>\n' \
    "$new" "$new" "$new" > "$DIR/data/charts/$old"
done

# 30日より古いログは掃除する
find "$DIR/logs" -name 'fundamentals_*.log' -mtime +30 -delete 2>/dev/null

if [ $STATUS -ne 0 ]; then
  echo "ファンダメンタルの更新に失敗しました（$LOG を確認）" >&2
fi
exit $STATUS
