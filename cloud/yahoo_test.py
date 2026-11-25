"""Yahoo から全銘柄の株価が取れるかの試験（ファイルには何も書かない）。
fetch_stocks.py と同じ取り方（100銘柄ずつ・間に1.5秒）で直近10日分を取り、
前営業日の終値が入っている銘柄数を数える。あわせて、個別銘柄の情報（.info）も数件試す。
    .venv/bin/python cloud/yahoo_test.py
"""
import sys, time, datetime as dt, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import fetch_stocks as fs

tickers = fs.load_tickers()
codes = [t["code"] for t in tickers]
today = dt.date.today()
# 前営業日（取引時間中に動かしても確定値で比べられるように）
d = today - dt.timedelta(days=1)
while not fs.is_trading_day(d):
    d -= dt.timedelta(days=1)
print(f"対象 {len(codes)} 銘柄 / 確認する日 {d}", flush=True)

t0 = time.time(); got = 0; have_day = 0; failed_batches = 0
for i in range(0, len(codes), fs.BATCH_SIZE):
    batch = codes[i:i + fs.BATCH_SIZE]
    try:
        res = fs.download_batch(batch, period="10d")
    except Exception as e:
        failed_batches += 1
        print(f"  バッチ {i // fs.BATCH_SIZE + 1} 失敗: {type(e).__name__}: {e}", flush=True)
        res = {}
    got += len(res)
    have_day += sum(1 for df in res.values() if any(ix.date() == d for ix in df.index))
    if (i // fs.BATCH_SIZE) % 5 == 0:
        print(f"  {min(i + fs.BATCH_SIZE, len(codes))}/{len(codes)}  取得 {got}  {d}あり {have_day}  経過{time.time() - t0:.0f}秒", flush=True)
    time.sleep(fs.SLEEP_BETWEEN_BATCH)

print(f"結果: 取得できた {got}/{len(codes)} 銘柄、{d} の終値あり {have_day} 銘柄、"
      f"失敗バッチ {failed_batches}、{time.time() - t0:.0f}秒", flush=True)

import yfinance as yf
ok = 0
for c in ["7203", "6758", "9984", "8306", "6861"]:
    try:
        info = yf.Ticker(f"{c}.T").info or {}
        ok += bool(info.get("sharesOutstanding") or info.get("marketCap"))
    except Exception as e:
        print(f"  .info {c} 失敗: {type(e).__name__}: {e}")
    time.sleep(1)
print(f"個別情報（.info）: 5件中 {ok} 件取得", flush=True)
sys.exit(0 if have_day >= len(codes) * 0.95 else 1)
