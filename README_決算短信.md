# TDnet 決算短信の取り込み（2026-11-16 作成）

発表当日の決算（売上・利益・前年比・会社予想・配当予想）を、TDnet（東証の適時開示情報閲覧サービス）の
決算短信 XBRL から取る。無料・登録不要。Yahoo は東証銘柄の最新四半期の反映が遅い（下記）ため。

## 使い方
```bash
cd ~/株分析
./.venv/bin/python fetch_tdnet.py              # 直近31日のうち未取得の日と今日・昨日を取る（初回 約40分）
./.venv/bin/python fetch_tdnet.py --days 4     # 毎日の更新（run_daily.sh の 2a-4 で実行）
./.venv/bin/python fetch_tdnet.py --parse-only # 通信せず CSV だけ作り直す（数秒）
```
TDnet に残るのは開示日を含む31日分。手元の `fundamentals/tdnet/` にためていく（消さない・公開しない）。

## 出力
- `fundamentals/kessan_tanshin.csv`：1行＝1開示（決算短信・業績予想の修正）。
- `fundamentals/kessan_latest.csv`：1行＝1銘柄。最新の決算短信。その後に予想修正があれば予想を上書き（予想修正日）。
- 列：開示日・時刻・コード・社名・種別・表題・訂正・決算期末・四半期（4＝通期）・期間末・連結/単体・会計基準、
  売上高・営業利益・経常利益・税引前利益・純利益（それぞれ前年比%）・EPS・総資産・純資産・自己資本比率(%)・年間配当、
  予想_売上高〜予想_年間配当（四半期決算は今期、本決算は来期の会社予想。幅で出ている会社は中央値）。
- 金額は円（1円単位）。第1〜3四半期は**累計**の値（決算短信の表記どおり）。
- `fundamentals/tdnet/list/<日付>.json`：その日の全開示（表題・PDF・XBRL のリンク）。
- `fundamentals/tdnet/summary/<日付>/*.htm.gz`：決算短信の要約 iXBRL だけを保存（zip の残りは捨てる）。

## 読み取りの決めごと
- 売上高は NetSales・OperatingRevenues・OrdinaryRevenues（銀行・保険）・Revenue（IFRS）などを順に探す。接尾辞（IFRS・US・BK・Specific など）はまとめて扱う。
- 連結があれば連結、無ければ単体。セグメント別の値は使わない。
- 値の無い項目（`<ix:nonFraction … />`）を飛ばす（最初の版はこれで後ろの数字を取りこぼしていた）。
- 決算期末が XBRL に無いときは表題（「2027年３月期」「令和9年3月期」）から作る。
- 数値の入っていない訂正（本文の注記だけ）は最新の扱いにしない。
- 取れる割合（初回 3,161件）：売上 98%、営業利益 96%（銀行・保険は概念なし）、純利益 99%、会社予想 91〜94%（予想を出さない会社がある）。

## Yahoo との比較（yahoo_quarter_check.py、2026-11-16）
直近31日に決算短信を出した 2,989銘柄のうち、その期が Yahoo の四半期データに入っていたのは 20%。
- 発表から 4〜7日 18%、8〜14日 34%、15〜21日 42%。プライム 38%、スタンダード 6%、グロース 3%。
- 入っていない銘柄の多くは1期前（4〜6月）で止まっている。四半期データが全く無い銘柄 357。
- 入っている分の売上は 597件中 577件が決算短信と0.5%未満の差。大きくずれたのは Yahoo 側の通貨（三井海洋開発がドル建て）や決算期変更など。
- 結果：`fundamentals/verify/yahoo_quarter_check.csv`、Yahoo の生データ `fundamentals/raw_quarterly/`。

## 変更したファイル
- `run_daily.sh` に 2a-4 を追加（変更前 `run_daily.sh.pre_tdnet`）。サイトの画面にはまだ使っていない。

## サイトの画面への反映（2026-11-16 夜）
- `fetch_tdnet.py` が J-Quants と同じ項目名のファイルも書く：`fundamentals/jq_summary_tdnet/<開示日>.json`（数字の無い訂正・空の予想修正は書かない）。
- `jq_files.py`：J-Quants（`jq_summary/`、12週遅れ）の最新日より後の日だけ TDnet のファイルを後ろにつなぐ（同じ開示を二重にしない。`KB_JQ_ONLY=1` で J-Quants だけ）。
  使っているのは make_company_dashboards.py（四半期決算・会社予想のグラフ）、reconcile_edinet.py（新しい本決算の追加）、forecast_fscore.py・keijo_yosou.py・forecast_extra.py（予想PER・予想Fスコア・予想修正率）、理論株価/bps_official.py。研究用フォルダ（モメンタム・寄り前ギャップの検証など）は J-Quants だけのまま。
- 株式分析ダッシュボード：ファンダメンタルの見出しの下に「最新の決算」の帯（発表日時・期・売上〜純利益と前年比・通期予想と進捗率、本決算は来期予想。発表7日以内は NEW）。売上の呼び方は決算短信に合わせる（銀行・保険＝経常収益、営業収益、IFRS の売上収益）。make_one_screen.py・one_screen_template.html。
- スクリーニング：条件に「決算発表からの日数」「累計増収率」「累計営業増益率（営業利益の無い会社は経常利益）」「累計純益増益率」「営業益進捗率」、プリセット「直近の好決算」（14日以内・増収10%以上・営業増益20%以上、営業増益率の大きい順）、銘柄詳細の全指標に「最新の決算（TDnet 決算短信）」。make_fundamental_dashboard.py の add_kessan()。
- 効果：9月決算の196社と8月決算の2社で、1年前のままだった本決算が11月発表の最新の本決算に置き換わった（PER なども更新）。四半期グラフ・会社予想は直近31日に決算を出した銘柄で最新に。
- 8/25〜10/16 の抜け（J-Quants 無料版は 8/24 開示まで、TDnet 本体は 10/17 から）は同日夜に埋めた：`python fetch_tdnet.py --backfill 2026-08-25:2026-10-16`。
  - 一覧：やのしん TDnet WEB-API（https://webapi.yanoshin.jp 、非公式・無料・登録不要。XBRL のある開示だけ `hasXBRL=1`）。TDnet 本体の一覧と 10/20・11/13 で件数・ファイル名とも完全に一致。
  - XBRL：TDnet 本体は31日で消える（やのしんのリンクも 404）が、東証上場会社情報サービス `https://www2.jpx.co.jp/disc/<5桁コード>/<zip名>` に残っている。`save_summary()` は本体で 404 なら自動でこちらを読む。
  - 毎日の更新でも、手元に一覧の無い30日より前の日はやのしん API で一覧を取る（`fetch_list_yanoshin()`）。
  - 画面の注意書き「会社予想の出どころ」もこの形に直した。
- 変更前：make_company_dashboards.py・reconcile_edinet.py・forecast_fscore.py・keijo_yosou.py・forecast_extra.py・理論株価/bps_official.py・make_one_screen.py・one_screen_template.html・make_fundamental_dashboard.py・analyze_fundamentals.py の各 `.pre_tdnet`、`fundamentals/fundamentals_latest.csv.pre_tdnet`・`fundamentals_by_year.csv.pre_tdnet`。
- 公開：2026-11-16 21:19 に deploy_github.sh（logs/publish_tdnet_*.log）。以後は毎日の自動更新（16:30・19:00）で TDnet の取り込み → 画面の作り直し → 公開まで流れる。

## J-Quants で答え合わせ（verify_tdnet_jq.py、2026-11-16 夜）
利用者の指定：J-Quants は決算データの確認に使う。
- J-Quants（12週遅れ）が追いついた開示日について、TDnet から読んだ値（jq_summary_tdnet）と J-Quants（jq_summary）を開示番号（J-Quants の DiscNo ＝ zip 名の後ろ14桁）で対応づけ、売上・営業利益・経常利益・純利益・EPS・総資産・純資産・自己資本比率・BPS・本決算の CF・株数・配当・会社予想（今期・来期）を比べる。許容差は相対0.1%か丸めの差。
- 出力：`fundamentals/verify/tdnet_vs_jquants.csv`（食い違い・片方にしか無い開示）、`tdnet_vs_jquants_summary.json`（一致率・項目別）。
- 毎日：`run_fundamentals.sh` で J-Quants の取得（fetch_jq_summary.sh）の直後に実行（通信なし・数秒）。変更前 `run_fundamentals.sh.pre_jqverify`。
- 比べない項目：中間期・四半期の CF（決算短信の要約に無く、添付の財務諸表にだけある。サイトは本決算の CF しか使わない）。
- 最初の検証（8/7 の 755件を TDnet からも取って比べた）で見つかって直したこと：
  1. 業績予想の修正で「前回発表予想（PreviousMember）」を読んでいた → 修正後（CurrentMember）を読むよう修正。8/25〜11/16 の予想修正 598件のうち 392件（382銘柄）の会社予想が修正前の値になっていた（例：KNT-CT 営業利益予想 62億→正しくは50億円）。サイトを作り直して公開し直した。
  2. IFRS の自己資本比率（EquityAttributableToOwnersOfParentToTotalAssetsRatio）、建設業の売上（NetSalesOfCompletedConstructionContracts）、IFRS の期末現金（CashAndCashEquivalentsAtEndOfPeriod）の要素名を追加。
- 直したあとの結果：対応がついた 731件のうち 730件が全項目一致、値 12,092個の一致率 99.992%。残り1件はキリンの営業利益（要約に載っていない）。TDnet 側に無い 24件は、東証上場会社情報サービスにもファイルが無い 22件と、中間期だけの予想修正 2件（今期の予想が無いので書き出していない）。
- 8/7 の分は検証用（jq_files.py は J-Quants がある日は J-Quants を使うので画面には影響しない）。

## 株式分析ダッシュボード：「最新の決算」の帯をやめてグラフに入れた（2026-11-16 23:00ごろ、利用者の指定）
- 帯（#kss）と描画・CSS を外した。DATA.ks（kessan_latest の値）はグラフの説明に使うので残す。
- 通期決算：説明を「右端の薄い棒は今期の会社予想（11/5 発表）・中間期の進捗 営業利益 56%」に（進捗は営業利益→経常利益→純利益→売上の順に最初の1つ。2行に収めるため）。予想の棒のツールチップに全項目の進捗。
- 四半期決算：説明に「最新 27/2Q（〜9/30、11/5 発表）」、ツールチップの見出しに発表日。make_company_dashboards.py の四半期の行に disc（開示日）を追加。
- 確認：PC 3列・iPad 2列（左右の下端が一致）・スマホ。変更前 `one_screen_template.html.pre_nokss`、`make_company_dashboards.py.pre_disc`。

## 「12週遅れ」の表示を消した（2026-11-16 23:30ごろ、利用者の依頼）
- スクリーニング「読むときの注意」：会社予想の出どころ＝「発表当日に TDnet から取り込み、あとから J-Quants の値で答え合わせ（3か月より前の開示は J-Quants の値）」。
- 予想Fスコアの注記：「今期の会社予想が無い（未開示・レンジ予想）」（forecast_fscore.py）。
- かんたん表示の説明：「会社予想は決算短信（J-Quants と TDnet。発表当日の値）」（make_fundamental_simple.py）。
- 収益性の注記：経常利益は決算短信（J-Quants と TDnet）（analyze_fundamentals.py）。
- 理論株価の EPS の出どころ：「会社予想(J-Quants)」→「会社予想(決算短信)」（理論株価/valuation.py）。
- 業績ダッシュボードの注記も同様（make_company_dashboards.py）。
- 変更前：各 `.pre_12w`。公開済み（スクリーニング・かんたん表示とも「12週」の文字は0件）。

## 株式分析ダッシュボード：切れている文字を流して見せる（2026-11-16 23:40ごろ、利用者の依頼）
- ファンダメンタル欄（#fundcard）の中で text-overflow:ellipsis で「…」になっている文字に、カーソルを当てると左へ流れて全文が見え、少し止まって戻る（繰り返し）。カーソルを外すと元の「…」表示に戻る。スマホは指で触れると流れ、もう一度触れると止まる。
- 今は上段の評価カード5枚の説明行（「自己資本比率 ・ 業種 51.0%」など）が対象。PC 3列で切れる。スマホ幅は切れていないので動かない。動きを減らす設定（prefers-reduced-motion）の端末では流さない。
- one_screen_template.html の fundMarquee（CSS は .mq と @keyframes mqslide）。変更前 `one_screen_template.html.pre_marquee`。
