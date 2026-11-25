# 東証プライム 株価CSV 取得ツール

## 何をするもの？

東証の**プライム・スタンダード・グロース**全銘柄（約3,700）について、日足の
**日付 / 始値 / 高値 / 安値 / 終値 / 出来高** を CSV で保存します。

対象は普通株のみです。優先株・社債型種類株（5桁コード）と、ETF・REIT・出資証券は
除外します。2024年以降に採番された英数字コード（例: `130A`）も対象に含みます。

- 初回に **過去10年分** を一括取得
- 以降は **Macを起動したとき** と **平日16:30** に自動更新

データ元は Yahoo Finance（`yfinance` ライブラリ）です。

---

## 使い方（最初の1回だけ）

ターミナルを開いて、次の2行を順に実行してください。

```bash
bash ~/株分析/setup.sh            # 環境構築 ＋ 過去10年分の取得
bash ~/株分析/install_schedule.sh # 自動更新（起動時＋平日16:30）を登録
```

`setup.sh` は途中で止めても大丈夫です。もう一度実行すれば取得し直します。

---

## 保存されるファイル

```
~/株分析/
├── data/
│   ├── prices/7203.csv          銘柄ごとの時系列
│   │         130A.csv           date,open,high,low,close,volume （約3,700ファイル）
│   └── daily/2026-09-01.csv     その日の全銘柄一覧
│                                code,name,market,date,open,high,low,close,volume
├── tickers/tse_tickers.csv      対象銘柄の一覧 code,name,market（週1回自動更新）
├── coverage_report.csv          取得漏れ監査の結果
└── logs/                        実行ログ
```

---

## 手動で実行したいとき

```bash
cd ~/株分析

./.venv/bin/python fetch_stocks.py              # 日次更新（直近10営業日を取得）
./.venv/bin/python fetch_stocks.py --catchup    # 不足分だけ取得（自動実行と同じ動作）
./.venv/bin/python fetch_stocks.py --init       # 過去10年分を取り直す
./.venv/bin/python fetch_stocks.py --init --skip-existing   # 未取得の銘柄だけ追加
./.venv/bin/python fetch_stocks.py --init --years 20        # 20年分
./.venv/bin/python fetch_stocks.py --markets プライム        # 市場を絞る
./.venv/bin/python fetch_stocks.py --raw        # 株式分割の調整をしない実際の株価
./.venv/bin/python fetch_stocks.py --refresh-tickers   # 銘柄リストを再取得
```

## 取得漏れの確認

```bash
./.venv/bin/python audit_coverage.py --probe
```

JPXの上場銘柄一覧と保存済みCSVを突き合わせ、市場別の取得状況と未取得銘柄を
`coverage_report.csv` に出力します。`--probe` を付けると、未取得銘柄が
Yahoo Finance で実際に取得できるかも確認します。

---

## 株価の「調整」について

既定では **分割・配当調整済み** の株価を保存します。
過去に株式分割をした銘柄（例：NTT）でも時系列が途切れず、
リターン計算やチャート分析にそのまま使えます。

当時実際に付いていた値段が必要な場合は `--raw` を付けてください。

---

## 自動更新まわり

| やりたいこと | コマンド |
|---|---|
| 今すぐ実行 | `launchctl start com.stockfetch.daily` |
| 停止 | `launchctl unload ~/Library/LaunchAgents/com.stockfetch.daily.plist` |
| 再開 | `launchctl load ~/Library/LaunchAgents/com.stockfetch.daily.plist` |
| 時刻を変更 | `install_schedule.sh` の `Hour` / `Minute` を編集して再実行 |

### いつ動くか

| タイミング | 動作 |
|---|---|
| Macを起動・ログインしたとき | 不足分があれば取得。最新なら数秒で終了 |
| 平日16:30 | その日の分を取得 |
| スリープからの復帰 | 16:30を寝過ごしていれば復帰後に実行 |

### 何日休んでも自動で埋まります

実行時に「保存済みの最終日」と「本来揃っているはずの最終営業日」を比べ、
遅れている分だけを取得します。土日・祝日・年末年始は営業日から除外して判定するので、
連休明けに無駄な取得は走りません。1週間Macを止めていた場合も、
起動すればその期間分をまとめて取得します。

既に入っている日付は最新の値で**上書き**します。ザラ場中に実行して未確定の値が
入った場合や、取引所側で値が訂正された場合も、次の実行で正しい値に直ります。

16:30の定期実行と起動時の実行が重なった場合は、ロックファイルで二重起動を防ぎます。
起動直後でネットワークが未接続のときは、最大3分間つながるのを待ってから取得します。

---

## 注意

- Yahoo Finance は非公式APIです。仕様変更で取得できなくなる可能性があります。
  その場合は `./.venv/bin/pip install -U yfinance` で更新してください。
- 一部の銘柄（新規上場直後など）はデータが取得できないことがあります。
  ログに失敗銘柄数が記録されます。
- 業務・商用でより確実なデータが必要な場合は、JPX公式の **J-Quants API**（有料プラン）への
  切り替えを検討してください。

---

## アナリスト予想（2026-11-14 追加。米国株分析と同じ作り）

Yahoo Finance（無料）が集計している証券会社アナリストの予想を、1銘柄1リクエストで取ります（Yahoo のコードは `<コード>.T`）。

- **取得**：`fetch_analyst.py`（全銘柄で約20分。`run_daily.sh` が水曜に全銘柄を取り直し、他の日は新規銘柄だけ。毎回、最新の終値で上昇余地を計算し直す）
  - 目標株価（平均・中央値・高値・安値）、投資判断の人数分布（今月〜3か月前）、EPS・売上高の予想（今四半期・来四半期・今期・来期）、EPS 予想の推移と修正件数、過去4四半期の決算サプライズ
  - 東証銘柄は Yahoo に証券会社ごとの判断変更の履歴が無いため、その表・ランキング・列は出ない
  - 今期の売上高の前年比は、手元の決算（fundamentals_latest.csv の前期売上高）で計算し直す（Yahoo の前年値が通期でないことがあるため）
  - `fundamentals/analyst.csv`・`analyst.json`・`raw_analyst/`・`analyst_history/<日付>.csv.gz`（取得日の控え。公開しない）
- **ランキング**：`アナリスト予想/analyst_page.py` → `data/charts/analyst.html`。トップ画面にカード
- **株式分析ダッシュボード**：`make_one_screen.py` の `ANALYST_ONLY = {"7203"}` のあいだは試作の1銘柄だけ。全銘柄に出すときは `None`
- 変更前のファイルは `*.pre_analyst`
- 2026-11-15：ランキングの独立ページをやめ、スクリーニング（fundamentals.html）の「アナリスト予想」タブに表だけを入れた（`make_fundamental_dashboard.py` が `アナリスト予想/*analyst_page.py` の `build()` を読む）。上部の絞り込み（市場・業種など）が効く。`fundamentals.html#analyst` で直接開ける。`analyst.html` は転送ページ
