# 東証スタンダード・グロース 株価CSV自動保存

Yahoo Finance (yfinance) から、東証スタンダード市場・グロース市場の全銘柄の
日足（始値・高値・安値・終値・調整後終値・出来高）を取得し、CSVで保存します。

## 保存先

```
株分析/jpx_prices/
├── data/
│   ├── tickers.csv           対象銘柄リスト（JPX公式の上場銘柄一覧から自動生成）
│   ├── prices/               ★銘柄ごとの時系列CSV  例: 1301.csv
│   └── daily/                ★当日分の全銘柄まとめCSV 例: 2026-09-01.csv
└── logs/                     実行ログ
```

**prices/<コード>.csv の中身**

```
Date,Open,High,Low,Close,AdjClose,Volume
2016-09-01,2870.0,2895.0,2860.0,2881.0,2455.31,15400
```

- `Open/High/Low/Close` … 実際の取引値（調整前）
- `AdjClose` … 分割・配当で遡及調整した終値
- 文字コード UTF-8

**daily/YYYY-MM-DD.csv の中身**

```
Code,Name,Market,Date,Open,High,Low,Close,AdjClose,Volume
```

---

## 初回セットアップ（1回だけ）

ターミナルを開いて、この順に実行してください。

> ⚠️ ターミナル（zsh）に貼り付けるときは **`#` から始まるコメントを付けないでください**。
> zshの対話シェルはコメントを解釈せず、引数として渡してしまいエラーになります。

```bash
cd ~/株分析/jpx_prices
./setup.sh
./.venv/bin/python fetch_universe.py
./.venv/bin/python backfill.py --limit 20
caffeinate -i ./.venv/bin/python backfill.py
./install_schedule.sh
```

1. `setup.sh` … Python環境の用意（2〜3分）
2. `fetch_universe.py` … 対象銘柄リストの作成（数十秒）
3. `backfill.py --limit 20` … 動作確認。まず20銘柄だけ（1分ほど）
4. `backfill.py` … 過去10年分をまとめて取得（★数時間）
5. `install_schedule.sh` … 平日16:30の自動実行を登録

> **4) について**
> 対象は約2,200銘柄あります。Yahoo Financeのレート制限を避けるため
> 40銘柄ずつ、間隔を空けて取得するので **2〜4時間程度** かかります。
> 途中で止めても大丈夫です。もう一度 `backfill.py` を実行すると、
> **未取得の銘柄だけ** 続きから取得します（取得済みはスキップ）。
> `caffeinate -i ./.venv/bin/python backfill.py` で実行すると、
> 途中でMacがスリープしません。

---

## 毎日の自動実行について

`install_schedule.sh` を実行すると、macOSのlaunchdに登録され
**平日16:30** に `run_daily.sh` が自動で走ります。

その日の処理内容:

1. 銘柄リストが7日以上古ければ自動で更新（新規上場・市場変更に追随）
2. 全銘柄の直近データを取得
3. 銘柄別CSVに、まだ無い日付の行を追記
4. 当日分を `data/daily/YYYY-MM-DD.csv` にまとめて出力

休場日（祝日など）に起動した場合は、データが無いことを検知して
一括CSVを作らずに終了します。

### 未確定値の自動訂正

日次更新は直近10営業日分を取得し、既存CSVの **同じ日付の行を置き換えます**
（追記ではなく上書き）。そのため:

- 場中（引け前）に取得してしまった未確定の行は、引け後の実行で確定値に直ります。
- Yahoo側があとから修正した値も自動的に反映されます。
- 何度実行しても行が重複しません。

**注意**: 場中に `backfill.py` を実行すると、その日の行は未確定値になります。
実行後に `./.venv/bin/python daily_update.py` を1回流せば確定値に訂正されます。

### 二重実行の防止と、履歴の取りこぼし対策

- `backfill.py` と `daily_update.py` は同時に走りません。
  片方が実行中なら、もう片方は何もせず終了します
  （`backfill.py` の途中で16:30を迎えても安全です）。
- 日次更新の時点でまだCSVが無い銘柄（新規上場・backfill未完了）は、
  直近分だけを保存したうえで `data/incomplete.txt` に記録されます。
  次に `backfill.py` を実行すると、その銘柄は **10年分を取り直します**。
  → 新規上場銘柄を取り込みたいときは、たまに `backfill.py` を実行してください。

**Macがスリープ／電源オフだった場合** … 起動後に自動で実行されます。
その日のうちにMacを起動しなかった場合は、翌日以降に手動で
`./.venv/bin/python daily_update.py --date 2026-09-01` のように
日付を指定して取得してください。

### 自動実行の確認・操作

```bash
launchctl list | grep com.jpxprices.daily   # 登録されているか確認
launchctl start com.jpxprices.daily         # 今すぐ1回実行
tail -f logs/daily_$(date +%Y-%m).log       # ログを見る
./uninstall_schedule.sh                     # 自動実行を解除
```

### 時刻を変えたい

`install_schedule.sh` の中の `<integer>16</integer>` `<integer>30</integer>` を
書き換えて、`./install_schedule.sh` を実行し直してください。

---

## 手動実行のコマンド一覧

```bash
cd ~/株分析/jpx_prices

./.venv/bin/python fetch_universe.py              # 銘柄リスト更新
./.venv/bin/python backfill.py                    # 未取得銘柄の10年分を取得
./.venv/bin/python backfill.py --force            # 全銘柄を取り直す
./.venv/bin/python daily_update.py                # 本日分を更新
./.venv/bin/python daily_update.py --date 2026-08-31  # 日付を指定して更新
```

`--date` で遡れるのは **直近10営業日ほど** です。それより前の抜けを埋めたい場合は、
該当銘柄のCSVを削除して `backfill.py` を実行し直してください。

## 設定の変更

`common.py` の先頭で調整できます。

| 項目 | 既定 | 説明 |
|---|---|---|
| `YEARS` | 10 | 一括取得する年数 |
| `BATCH` | 40 | 1回にまとめて取得する銘柄数 |
| `SLEEP` | 1.5 | バッチ間の待機秒数。429エラーが出るなら増やす |
| `ENCODING` | utf-8 | CSVの文字コード |

## 注意事項

- Yahoo Financeのデータは個人利用向けの参考値です。まれに欠損・誤りがあります。
- 16:30時点ではYahoo側の当日データ反映が間に合わないことがあります。
  その場合は翌営業日の実行時に、抜けていた日付が自動で追記されます。
- 短時間に大量アクセスすると一時的にブロックされます。`SLEEP` を大きくして対応してください。
