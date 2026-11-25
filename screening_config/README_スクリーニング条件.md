# スクリーニング条件の定義表（screening_config）

楽天証券 MARKETSPEED II の「ランキング」「スーパースクリーナー」「チャート形状検索」と、
EDINET DB のメソドロジーを参考に、東証株分析の絞り込み条件を1か所で定義した設定ファイルです。
**正本は CSV**（Excel で開いて編集できます）。SQLite は CSV から自動生成します。

## ファイル

| ファイル | 中身 |
|---|---|
| `screening_conditions.csv` | 条件の定義（131件）。条件ID・計算式・データ源・既存CSVの列・NULLの扱い・状態 |
| `ranking_definitions.csv` | ランキングの定義（MarketSpeedの28種＋独自5種） |
| `data_sources.csv` | データ源と無料枠の制約 |
| `null_policies.csv` | NULLの扱い5種類の意味 |
| `statuses.csv` | 状態5種類の意味 |
| `build_config.py` | CSVを検証して `screening_config.sqlite` を作る |
| `screening_engine.py` | 定義表どおりに絞り込み・ランキングを実行する |

## 使い方（~/株分析 で実行）

```bash
# 1) 定義表を検証して SQLite を作る（CSVを編集したら毎回）
.venv/bin/python screening_config/build_config.py

# 2) 絞り込み（ID:下限:上限、片側は空欄。比較記号も可。記号を使うときは引用符で囲む）
.venv/bin/python screening_config/screening_engine.py screen FIN_PER:0:15 FIN_PBR::1 TEC_RSI14::40 --market プライム
.venv/bin/python screening_config/screening_engine.py screen "FIN_ROE>=10" FLT_FIN_EXCLUDE "FIN_DE<=100" --top 30
.venv/bin/python screening_config/screening_engine.py screen "FLT_SIZE=中型|小型" FIN_DY:3: --out 高配当中小型.csv

# 3) ランキング
.venv/bin/python screening_config/screening_engine.py rank R16 --top 30     # 低PER上位
.venv/bin/python screening_config/screening_engine.py rank X02              # 理論株価の割安順（信頼度=高）

# 4) 使える条件の一覧（--all で未実装・対象外も表示）
.venv/bin/python screening_config/screening_engine.py list --category 財務
```

IDだけを書くと（例 `FLT_PRICE_MIN`）、定義表の「既定の下限・上限」で判定します。
真偽の条件（例 `FLT_FIN_EXCLUDE`、`FLT_N225`）はIDだけで「当てはまる銘柄」を残します。

## 列の意味（screening_conditions.csv）

| 列 | 意味 |
|---|---|
| 条件ID | 接頭辞で区分がわかる（FLT=共通フィルタ, FIN=財務, EDB=EDINET独自, CNS/VAL=予想・理論株価, SUP=需給, PRC/VOL=値動き・出来高, TEC=テクニカル, SHP=チャート形状, NA=対象外） |
| MarketSpeed名 | 対応する MarketSpeed の項目名（無いものは空欄） |
| 良い向き | 高いほど良い／低いほど良い／中立。screen の並べ替えに使う |
| 計算式 | 人が読むための式。実装は既存列そのもの、または `screening_engine.py` の `DERIVED` |
| 入力項目 | `ファイル:列` を `;` 区切り。build_config.py が列の存在を照合する |
| データ源 | yahoo / edinetdb / jpx / jquants_free / derived / none（data_sources.csv） |
| 既存ファイル・既存列 | 状態=active の値の取り出し元 |
| EDINET_DBフィールド | EDINET DB で対応する項目名（今後の取り込み・照合用） |
| NULLの扱い | exclude / pass / zero / fallback / scope_pass（下表） |
| NULL化ガード | 異常値として NULL にする条件（EDINET DB の基準に合わせた） |
| 状態 | active / derived / approx / new / unsupported（下表） |

### NULLの扱い

| 値 | 意味 |
|---|---|
| exclude | NULLの銘柄は落とす（既定。「NULL > 不正確値」） |
| pass | NULLの銘柄は通す（無借金のICR、空売り報告の無い銘柄など） |
| zero | 0として評価（無配の配当利回り、無借金のD/E） |
| fallback | 代替条件IDの値で評価（IFRSの経常利益→税引前利益） |
| scope_pass | IFRS・US基準の銘柄はNULLでも通し、日本基準でNULLなら落とす |

### 状態

| 値 | 件数 | 意味 |
|---|---|---|
| active | 96 | 既存CSVの列をそのまま使う |
| derived | 20 | 既存列から計算（実装済み） |
| approx | 8 | 近似で計算（実装済み） |
| new | 0 | 新しい取得・計算が必要。指定すると警告して、その条件を使わずに絞り込む |
| unsupported | 7 | 無料では再現しない（寄前気配・ティック数・訂正取消・楽天テーマなど） |

## 条件を足す・直すとき

1. `screening_conditions.csv` に1行足す（IDは重複不可）。
2. 既存CSVの列をそのまま使うなら 状態=active、既存ファイル・既存列を記入。
3. 計算が必要なら 状態=derived にし、`screening_engine.py` の `DERIVED` に同じIDで式を書く。
4. `build_config.py` を実行。列名の打ち間違いや、既存スクリプトの列名変更があるとエラーで知らせます。

## EDINET DB 由来の条件（2026-10-13 実装済み）

FIN_KEIJO_CHG, FIN_QUICK, FIN_REC_TURN, FIN_INV_TURN, EDB_ROIC, EDB_CCC, EDB_DIV_STREAK,
EDB_RECORD_NI, EDB_DOE, EDB_NETCASH_RATIO, EDB_SPLIT_HEURISTIC の11件。

- `fetch_cost_of_sales.py` が売上原価のために取っている同じ応答から、`edinet_metrics.py` が
  生の項目を `fundamentals/edinet_metrics_by_year.csv`（最大6期）に保存し、指標を
  `fundamentals/edinet_metrics_latest.csv` に書き出す。**呼び出し回数は増えない**（既定90回/日のまま）。
- 実装前に取得済みだった銘柄（約1,800社）は「項目補充」の待ち行列に入り、再取得・初回収集で
  枠が余った日にだけ取り直す。初回収集（残り約1,900社、約21日）の後に補充（約20日）が続くので、
  **全銘柄がそろうのは約6週間後**。それまでは値の無い銘柄が NULL として落ちる。
- 進み具合: `.venv/bin/python fetch_cost_of_sales.py --status` の「スクリーニング項目の補充待ち」。
- 指標だけ作り直す（通信なし）: `.venv/bin/python edinet_metrics.py`
- 連続増配・最高益は取得6期の範囲で数える近似（状態=approx）。

## 元データの整合性チェック（FLT_DATA_OK）

Yahoo由来の `fundamentals_latest.csv` には桁ずれが混じることがある（例: 売上高の1桁欠け、
EPSと株数のずれでPERが1倍前後になる）。次のどれかに当たる銘柄は、PER・EPS・ROE・ROA・
売上高・売上高変化率・営業利益変化率・PSR・営業利益率・売上高経常利益率を NULL にする（NULL > 不正確値）。

- PER と「時価総額 ÷ 当期純利益」の比が0.5〜2倍の外
- 売上高の前期比・前期の前々期比が0.2〜5倍の外、または営業利益 > 売上高
- 決算年度が同じとき、売上高が EDINET DB（有報）と0.8〜1.25倍の外（金融業は除く）
  ※ 2026-10-13 時点で比べられた1,616社のうち99%以上が完全一致、ずれは7社（いずれも Yahoo 側の誤り）
- 決算年度が同じとき、当期純利益が EDINET DB と0.5〜2倍の外、または符号が逆
  （EDINET DB の項目補充が進むにつれて効き始める）

条件 `FLT_DATA_OK` を指定すると、これらに当たる銘柄そのものを外せる。EDINET DB 未取得で
同じ元データの中で辻褄が合ってしまう誤り（純利益とEPSが両方10倍など）は、取得されるまで残る。

## テクニカル追加分・寄付比・チャート形状・変化率（2026-10-13 実装）

`compute_technical_extra.py`（run_fundamentals.sh から毎営業日、通信なし・約20秒）→ `fundamentals/technical_extra.csv`

- テクニカル14種: CCI(20)、ウィリアムズ%R(14)、ROC(25)、モメンタム(10)、ATR(14)%、VR(25)、強弱Aレシオ(26)、
  アルーンOSC(14)、UOS、ボラティリティレシオ(14)、DPO(20)、HLバンド位置(20)、エンベロープ乖離(25)、パラボリック
- 寄付比騰落率（PRC_CHG_OPEN）: 引け後の値。ランキング R05・R06 が使える
- チャート形状: 20・60・120日で判定。`SHP_SHAPE20/60/120=上昇|急上昇` のように区分で指定するか、
  `SHP_UP` など9種の真偽条件（60日で判定）を使う。60日では約36%が「その他」（どの形にも当たらない）
- PER・PBR・配当利回りの20日変化率: `fundamentals/valuation_history.csv` に毎日の値を貯め、
  20営業日前と比べる。たまるまで（約1か月）は株価比の近似（列「変化率の方式」=近似）

## JPX日経400（FLT_JPX400）

`fetch_jpx400.py` が JPX の公開ページから構成銘柄一覧を取得 → `fundamentals/jpx400.csv`（run_daily.sh から25日に1回）。
銘柄数が380〜420で東証リストと9割以上一致したときだけ上書きする。取得できない場合は JPX のページから
一覧をダウンロードして `./.venv/bin/python fetch_jpx400.py --file ダウンロードしたファイル` で作れる。
一覧が無い間、FLT_JPX400 は全銘柄 NULL（絞り込むと0件）。

## 注意

- PER・PBR・配当利回りは**現在株価**で計算した値を使います。EDINET DB の per・dividendYield は有報の期末株価ベースなので混ぜません。
- 経常利益系は日本基準だけの区分です。IFRS・US基準は NULL になるため、fallback / scope_pass で扱います。
- 会計基準は `cost_of_sales_latest.csv`（収集済みの銘柄のみ）から取ります。未収集の銘柄は「日本基準または不明」として扱います。
- MarketSpeed との定義差（RCI・ストキャスの期間、棚卸資産回転率の分母、信用残の週次と前回比など）は各行の「備考」に書いています。

## 東証スクリーニングのページとのつながり（2026-10-13）

`make_fundamental_dashboard.py` がページを作るときに `dashboard_bridge.py` の `augment()` を呼び、定義表をページに入れる。
run_fundamentals.sh はそのままでよい（毎営業日の更新で反映される）。

- **ランキング**タブ：総合評価ランキングをやめ、`ranking_definitions.csv` の状態が active / derived / approx のもの（27種）を
  「値動き・出来高・売買代金・株価指標・信用残・独自」のボタンで切り替える。並べる値・並び順・表示件数・既定で除外・対象の絞り込みは CSV のとおり。
  作れない6種（寄前気配4種・ティック数・訂正取消）は名前だけ下に出す。「株価100円未満を除く」（FLT_PRICE_MIN）は画面で外せる。
- **スクリーニング**タブ：「条件を追加」を定義表の区分（共通フィルタ・財務・EDINET独自・予想・理論株価・需給・値動き・出来高・テクニカル・チャート形状）の順に並べ、
  表示名は条件名にした。定義表に無い既存の指標は「定義表外：…」として後ろに残している。区分・真偽の条件（チャート形状・パラボリック・会計基準・日経225採用など）は値のボタンで選ぶ。
- ページに無かった列（45列）は `screening_engine.condition_values` で計算して足す。円の金額は億円に直す。
- **整合性チェック（FLT_DATA_OK）**：当たった銘柄は PER・EPS・ROE・ROA・売上系・利益率系の列を空欄にし、「データ不整合」列を立てる。
  絞り込み欄の「データ不整合を除く」（既定でオン）で外せる。銘柄名の横の印は「D」。
- 列名の対応は `dashboard_bridge.py` の SAME_AS / NEW_NAME。条件を足したときに名前を変えたいならここを直す。
- 元に戻すときは `make_fundamental_dashboard.py.pre_teigi` を戻す（bridge は呼ばれなくなるだけ）。
