# スマホ・タブレットからチャートを見る（GitHub Pages）

チャートはMacの `~/株分析/data/charts/` にある約3,700個のHTMLです。
これを **GitHub Pages** に置いて、固定URLでどの端末からでも見られるようにします。
（Macを閉じていても見られます。スマホ側に入れるアプリはありません）

公開後のURL:

| 画面 | URL |
|---|---|
| **トップ画面**（4画面への入口・銘柄検索・お気に入り） | `https://<ユーザー名>.github.io/kabu-charts/` |
| 株式分析ダッシュボード | `https://<ユーザー名>.github.io/kabu-charts/one/` |
| チャート一覧 | `https://<ユーザー名>.github.io/kabu-charts/charts.html` |
| 東証ファンダメンタル分析 | `https://<ユーザー名>.github.io/kabu-charts/fundamentals.html`（シンプル版 `fundamentals_simple.html`） |
| 売買シグナル | `https://<ユーザー名>.github.io/kabu-charts/signals.html` |
| 株価指数ダッシュボード | `https://<ユーザー名>.github.io/kabu-charts/indices.html` |
| セクターローテーション（日米） | `https://<ユーザー名>.github.io/kabu-charts/sector.html`（`sector_rotation/sector_rotation.py` が作る。`run_daily.sh` の 3b-3） |

どの画面にも「トップ」（または左上の「‹」）があり、トップ画面から4つの画面を行き来できます。
トップ画面をホーム画面に入れておくのがおすすめです。
トップ画面は `make_home.py` が作ります（`run_daily.sh` の 3c。`dashboards/one/` を公開フォルダ `data/charts/one/` に複製する処理も兼ねます）。

---

## 初回セットアップ（Macで1回だけ）

### 1. GitHubアカウントを用意する

まだなら https://github.com/signup （無料）

### 2. GitHub CLI を入れてログインする

```bash
brew install gh
gh auth login
```

`gh auth login` は対話式です。次のように答えてください。

- What account do you want to log into? → **GitHub.com**
- What is your preferred protocol? → **HTTPS**
- Authenticate Git with your GitHub credentials? → **Yes**
- How would you like to authenticate? → **Login with a web browser**
- 表示された8桁のコードをブラウザに入力して承認

### 3. 公開する

```bash
bash ~/株分析/deploy_github.sh
```

- リポジトリ `kabu-charts` の作成、アップロード、GitHub Pages の有効化まで自動で進みます
- 初回のアップロードは約490MBあるため、回線によっては10〜30分かかります
- 完了後、数分待つと `https://<ユーザー名>.github.io/kabu-charts/` が開けるようになります

---

## 毎日の自動更新

`run_daily.sh` に組み込み済みです。上の初回セットアップさえ済ませておけば、
平日16:30・19:00・22:00の自動更新のたびに公開まで自動で走ります。

    株価取得 → チャート生成 → GitHub Pages へ公開

公開ログは `logs/deploy.log` に残ります。

履歴は**常に1コミットだけ**に保つ設計（`--amend` ＋ 強制push）なので、
毎日更新してもリポジトリが際限なく膨らむことはありません。

---

## スマホでの使い方

1. ブラウザで `https://<ユーザー名>.github.io/kabu-charts/` を開く
2. 銘柄一覧から、検索・市場フィルタ・RSIの絞り込みで銘柄を選ぶ
3. 行をタップすると個別チャート。期間ボタンで1週間〜10年を切り替え、
   チャートをタップすると四本値・指標の数値が出ます

**ホーム画面に追加**しておくとアプリのように開けます。

- iPhone (Safari): 共有ボタン → 「ホーム画面に追加」
- Android (Chrome): 右上の︙ → 「ホーム画面に追加」

### ファンダメンタル分析の画面

`fundamentals.html` では、PER・PBR・ROE・配当利回り・自己資本比率などで全銘柄を並べ替え、
市場・業種・時価総額で絞り込めます。**銘柄をタップすると株価チャートと全指標が全画面で開きます。**
バリュー株・高配当株・グロース株などの条件別リストも入っています。

右上の「表示切替」（チャートを開いている間は ◐ ボタン）で明るさを変えられます。
チャートの色も一緒に切り替わります。

---

## Macだけで完結させたい場合（おまけ）

外部に出さず、自宅Wi-Fi内だけで見る方法も残してあります。

```bash
python3 ~/株分析/serve_charts.py
```

表示された `http://192.168.x.x:8080/` に同じWi-FiのスマホからアクセスするとBasic認証つきで見られます
（ユーザー名・パスワードは `~/株分析/.chart_auth`）。

---

## 注意

- 無料プランでは**公開リポジトリ**でのみGitHub Pagesが使えます。
  URLを知っている人は誰でも閲覧できます（株価という公開情報のみですが、共有範囲にはご注意ください）
- GitHub Pagesの上限は「公開サイト1GB」「転送量 月100GB（ソフト上限）」。
  現在は約490MBなので収まっていますが、余裕を持たせたい場合は保有期間を5年に縮められます

```bash
python3 ~/株分析/make_all_charts.py --years 5   # 約310MBに減る
```

- Cloudflare Pages は使わない設定に変更しました。関連スクリプトは
  `deploy_pages.sh.disabled` などにリネームしてあります（動作しません）。
  Cloudflare側に作られたプロジェクト `kabu-charts` が残っている場合は、
  https://dash.cloudflare.com → Workers & Pages から削除してください

---

## 監視銘柄（トップ画面）

株式分析ダッシュボードの各銘柄ページで **「☆ 監視に追加」** を押すと、その時点の
IN・利確1・利確2・損切り（下落トレンドの銘柄は「転換ライン」）の値段を記録します。
トップ画面の **「監視銘柄一覧」カード**（タップで `watch.html`）と、その銘柄のページで、追加日の翌営業日以降に到達したかを表示します。

- 判定は日足の高値・安値（毎営業日の自動更新後に反映）。通知は出さず、サイトを開いたときに分かる方式です
- 新しく到達した水準には **NEW**、トップのカードと一覧の見出しに「新たに到達 N件」。「確認済みにする」で消えます
- **極端な急騰・急落は除外**：前日終値から ATR(14) の3倍を超えて動いた日に到達した水準は「急変で通過」として数えません（株価が元の側に戻ったら再び見張ります）
- 追加した時点で既に水準の先にある場合（例: 株価がINゾーンの中）は、いったん離れてから来たときに到達とします
- 保存先はブラウザ（この端末）です。Macとスマホで監視銘柄は別々になります。やめるときは × か「★ 監視中」をもう一度押す
- 仕組み: `watch_common.js`（判定）→ `make_one_screen.py` が `one/assets/watch.js` にコピー。画面は `one_screen_template.html` と `make_home.py`
