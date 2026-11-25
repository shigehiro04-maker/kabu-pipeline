#!/usr/bin/env python3
"""保有銘柄×終値＋現金で総資産を計算し、日次で記録する（run_daily.sh から毎日実行）。

置き場所: ~/株分析/record_assets.py
入力:  ポートフォリオ最適化/マルチファクター少額_20260926/保有銘柄.csv（コード,株数）
       同 現金.txt（円）・元本.txt（累計入金, 円。無ければ前回の記録の値）
       日次の株価CSV（fetch_stocks.py の出力。fix_splits.py の修正後）
出力:  同 総資産/総資産の推移.csv  … 日付ごとに1行（同じ日付は上書き）
       同 総資産/ボード取り込み.txt … クオンツ運用ボードの「Mac の記録を取り込む」に貼る

使い方:
  ./.venv/bin/python record_assets.py --check          # 株価ファイルの場所と読み取り結果を確認（書き込まない）
  ./.venv/bin/python record_assets.py                  # 記録する
  ./.venv/bin/python record_assets.py --principal 130000   # 入金した月は元本を更新してから記録
  ./.venv/bin/python record_assets.py --prices-dir data/xxx  # 株価フォルダを自動で見つけられないとき
"""
import argparse, csv, datetime as dt, glob, hashlib, json, os, sys

ROOT = os.path.expanduser('~/株分析')
MF = os.path.join(ROOT, 'ポートフォリオ最適化', 'マルチファクター少額_20260926')
HOLD = os.path.join(MF, '保有銘柄.csv')
CASH = os.path.join(MF, '現金.txt')
PRIN = os.path.join(MF, '元本.txt')
OUT = os.path.join(MF, '総資産')
HIST = os.path.join(OUT, '総資産の推移.csv')
BOARD = os.path.join(OUT, 'ボード取り込み.txt')
STATE = os.path.join(OUT, 'state.json')
SPLITS = os.path.join(ROOT, 'data', 'splits.csv')
PRICE_DIRS = ['data/prices', 'data/stocks', 'data/price', 'data/ohlcv', 'data/daily_prices', 'data']
DATE_COLS = ['Date', 'date', '日付', 'datetime', 'Datetime']
CLOSE_COLS = ['Close', 'close', '終値', 'close_price', 'Adj Close', 'adj_close']
HIST_HEAD = ['日付', '総資産', '元本', '現金', '株式評価額', '銘柄数', '株価が古い銘柄']


def die(msg):
    print('エラー: ' + msg, file=sys.stderr)
    sys.exit(1)


def read_holdings():
    if not os.path.exists(HOLD):
        die(f'{HOLD} がありません。約定後に make_orders.py --no-refresh --apply を実行してください。')
    h = {}
    with open(HOLD, encoding='utf-8-sig') as f:
        for row in csv.reader(f):
            if len(row) < 2 or not row[0].strip() or not row[1].strip().replace('.', '').isdigit():
                continue  # 見出し・空行
            c = row[0].strip().replace('.T', '')
            h[c] = h.get(c, 0) + int(float(row[1]))
    return {c: n for c, n in h.items() if n > 0}


def read_num(path):
    if not os.path.exists(path):
        return None
    s = open(path, encoding='utf-8').read().strip().replace(',', '')
    return float(s) if s else None


def find_price_file(code, dirs):
    for d in dirs:
        base = d if os.path.isabs(d) else os.path.join(ROOT, d)
        for name in (f'{code}.csv', f'{code}.T.csv', f'{code}_T.csv', f'{code}.csv.gz', f'{code}.T.csv.gz'):
            p = os.path.join(base, name)
            if os.path.exists(p):
                return p
    return None


def last_close(path):
    """(日付文字列 YYYY-MM-DD, 終値) を返す。出来高0や空の行は飛ばす。"""
    import pandas as pd
    df = pd.read_csv(path)
    dcol = next((c for c in DATE_COLS if c in df.columns), df.columns[0])
    ccol = next((c for c in CLOSE_COLS if c in df.columns), None)
    if ccol is None:
        raise ValueError(f'終値の列が見つかりません（列: {list(df.columns)[:10]}）')
    df = df[[dcol, ccol] + (['Volume'] if 'Volume' in df.columns else [])].dropna(subset=[ccol])
    if 'Volume' in df.columns:
        df = df[df['Volume'].fillna(0) > 0] if (df['Volume'].fillna(0) > 0).any() else df
    df['_d'] = pd.to_datetime(df[dcol]).dt.strftime('%Y-%m-%d')
    df = df.sort_values('_d')
    r = df.iloc[-1]
    return r['_d'], float(r[ccol])


def load_state():
    try:
        return json.load(open(STATE, encoding='utf-8'))
    except Exception:
        return {}


def split_factor(code, basis, until):
    """保有を登録した日（basis）より後〜until までに権利落ちした分割の倍率。"""
    if not os.path.exists(SPLITS):
        return 1.0, []
    f, hits = 1.0, []
    with open(SPLITS, encoding='utf-8-sig') as fh:
        for r in csv.DictReader(fh):
            if r.get('code', '').strip() != code:
                continue
            ex = (r.get('ex_date') or '')[:10]
            if basis < ex <= until:
                ratio = float(r.get('ratio') or 1)
                f *= ratio
                hits.append(f'{ex} ×{ratio:g}')
    return f, hits


def read_hist():
    if not os.path.exists(HIST):
        return {}
    with open(HIST, encoding='utf-8-sig') as f:
        return {r['日付']: r for r in csv.DictReader(f)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true', help='読み取り結果を表示するだけ（書き込まない）')
    ap.add_argument('--principal', type=float, help='元本（累計入金）を更新する')
    ap.add_argument('--prices-dir', help='銘柄ごとの株価CSVのフォルダ（~/株分析 からの相対パスでも可）')
    a = ap.parse_args()

    dirs = [a.prices_dir] if a.prices_dir else PRICE_DIRS
    hold = read_holdings()
    cash = read_num(CASH)
    if cash is None:
        die(f'{CASH} がありません。')

    # 保有ファイルが変わったら、その日を「株数の基準日」にする（それ以降の分割だけ株数に反映）
    state = load_state()
    hh = hashlib.sha256(open(HOLD, 'rb').read()).hexdigest()
    today = dt.date.today().isoformat()
    basis = state.get('basis_date', today) if state.get('holdings_hash') == hh else today

    rows, bad = [], []
    for c, n in sorted(hold.items()):
        p = find_price_file(c, dirs)
        if not p:
            bad.append(f'{c}: 株価ファイルが見つかりません'); continue
        try:
            d, px = last_close(p)
        except Exception as e:
            bad.append(f'{c}: {p} を読めません（{e}）'); continue
        rows.append([c, n, d, px, p])
    if bad:
        print('\n'.join(bad), file=sys.stderr)
        die('株価を読めない銘柄があります。--check で確認し、必要なら --prices-dir でフォルダを指定してください。')

    rec_date = max(r[2] for r in rows)
    stock, stale, notes = 0.0, [], []
    for r in rows:
        c, n, d, px, p = r
        f, hits = split_factor(c, basis, rec_date)
        if f != 1.0:
            n2 = round(n * f)
            notes.append(f'{c}: 分割（{", ".join(hits)}）で株数を {n}→{n2} として計算。保有銘柄.csv も更新してください')
            n = n2
        if d < rec_date:
            stale.append(c)
        stock += n * px
        r[1] = n

    hist = read_hist()
    if a.principal is not None:
        prin = a.principal
    else:
        prin = read_num(PRIN)
        if prin is None:
            prev = [hist[k] for k in sorted(hist) if k < rec_date]
            prin = float(prev[-1]['元本']) if prev else None
    if prin is None and not a.check:
        die(f'元本がわかりません。初回は --principal 100000 のように指定してください（{PRIN} に保存されます）。')

    total = stock + cash
    print(f'記録日 {rec_date}（株数の基準日 {basis}）')
    for c, n, d, px, p in rows:
        print(f'  {c}  {n:>5}株 × {px:>10,.1f}円 = {n*px:>12,.0f}円  （{d}{" 古い" if d < rec_date else ""}）  {os.path.relpath(p, ROOT)}')
    print(f'  株式 {stock:,.0f}円 ＋ 現金 {cash:,.0f}円 ＝ 総資産 {total:,.0f}円' + (f'（元本 {prin:,.0f}円、{(total/prin-1)*100:+.2f}%）' if prin else '（元本は未設定。初回は --principal で指定）'))
    for s in notes:
        print('  注意: ' + s)
    if a.check:
        print('--check のため書き込みません。')
        return

    os.makedirs(OUT, exist_ok=True)
    if a.principal is not None:
        open(PRIN, 'w', encoding='utf-8').write(f'{a.principal:.0f}\n')
    hist[rec_date] = {'日付': rec_date, '総資産': f'{total:.0f}', '元本': f'{prin:.0f}', '現金': f'{cash:.0f}',
                      '株式評価額': f'{stock:.0f}', '銘柄数': str(len(rows)), '株価が古い銘柄': ' '.join(stale)}
    with open(HIST, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=HIST_HEAD)
        w.writeheader()
        for k in sorted(hist):
            w.writerow({h: hist[k].get(h, '') for h in HIST_HEAD})
    json.dump({'holdings_hash': hh, 'basis_date': basis}, open(STATE, 'w', encoding='utf-8'))

    # ボードに貼る用: 総資産の推移（全件）＋ 最新終値
    with open(BOARD, 'w', encoding='utf-8') as f:
        f.write('# 総資産の推移（日付,総資産,元本）\n')
        for k in sorted(hist):
            f.write(f"{k},{hist[k]['総資産']},{hist[k]['元本']}\n")
        f.write(f'# 最新終値 {rec_date}（コード,株価）\n')
        for c, n, d, px, p in rows:
            f.write(f'{c},{px:g}\n')
    print(f'記録しました: {os.path.relpath(HIST, ROOT)}（{len(hist)}件）')
    print(f'ボード用: pbcopy < "{BOARD}"')


if __name__ == '__main__':
    main()
