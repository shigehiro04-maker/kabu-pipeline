#!/usr/bin/env python3
"""5分足を Yahoo Finance（yfinance・無料）からまとめて取得し、data/intraday/<コード>.csv に保存する。

  東証版:  python fetch_intraday.py            （~/株分析 に置く。銘柄コード 7203 → 7203.T）
  米国株版: python fetch_intraday.py            （~/米国株分析 に置く。BRK.B → BRK-B）
  一部だけ: python fetch_intraday.py --codes 7203,6758

- Yahoo の5分足は直近60日まで。毎回「直近1か月」を取り、手元のCSVと合わせて直近 KEEP_SESSIONS 営業日分を残す（チャート用）。
- 取った5分足は data/intraday_archive/<年-月>/<コード>.csv.gz にも全部残す（このPCだけ。公開しない・消さない）。
- 時刻は取引所の現地時間（東証=日本時間、米国=米東部時間）。時間外取引は含めない。
- 東証版は大引け（15:25〜15:30）の足が Yahoo に無いので、日足（調整なし）の終値で15:25の足を1本足す。
- 1回のリクエストで BATCH 銘柄ずつ。失敗したまとまりは小さく分けて1回だけやり直す。
"""
import argparse
import csv
import os
import sys
import time

import pandas as pd
import yfinance as yf

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "data", "intraday")
ARCHIVE = os.path.join(BASE, "data", "intraday_archive")   # 全期間の保存先（公開しない）
TICKERS = os.path.join(BASE, "tickers", "tse_tickers.csv")
US = os.path.isfile(os.path.join(BASE, "us_fetch_stocks.py"))       # 米国株版のフォルダかどうか
TZ = "America/New_York" if US else "Asia/Tokyo"
KEEP_SESSIONS = 20
BATCH = 150


def sym(code):
    return code.replace(".", "-") if US else f"{code}.T"


def load_codes():
    with open(TICKERS, encoding="utf-8-sig") as f:
        return [r["code"].strip() for r in csv.DictReader(f) if r.get("code", "").strip()]


def archive(code, df):
    """5分足をすべてこのPCに残す（公開はしない）。data/intraday_archive/<年-月>/<コード>.csv.gz に月ごと・圧縮で追記。"""
    for mo, g in df.groupby(df["dt"].str[:7]):
        d = os.path.join(ARCHIVE, mo)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"{code}.csv.gz")
        if os.path.exists(path):
            try:
                old = pd.read_csv(path, dtype={"dt": str})
                g = pd.concat([old[~old["dt"].isin(g["dt"])], g]).sort_values("dt")
            except Exception:
                pass
        tmp = path + ".tmp"
        g.to_csv(tmp, index=False, compression="gzip")
        os.replace(tmp, path)


def merge_save(code, df):
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    df = df[(df[["Open", "High", "Low", "Close"]] > 0).all(axis=1)]
    if df.empty:
        return False
    idx = df.index.tz_convert(TZ) if df.index.tz is not None else df.index
    new = pd.DataFrame({"dt": idx.strftime("%Y-%m-%d %H:%M"),
                        "o": df["Open"].round(4).values, "h": df["High"].round(4).values,
                        "l": df["Low"].round(4).values, "c": df["Close"].round(4).values,
                        "v": df["Volume"].fillna(0).astype("int64").values})
    path = os.path.join(OUT, f"{code}.csv")
    if os.path.exists(path):
        try:
            old = pd.read_csv(path, dtype={"dt": str})
            new = pd.concat([old[~old["dt"].isin(new["dt"])], new])
        except Exception:
            pass
    new = new.sort_values("dt")
    archive(code, new)
    days = sorted(new["dt"].str[:10].unique())[-KEEP_SESSIONS:]
    new = new[new["dt"].str[:10].isin(days)]
    tmp = path + ".tmp"
    new.to_csv(tmp, index=False)
    os.replace(tmp, path)
    return True


def _pick(data, s):
    if isinstance(data.columns, pd.MultiIndex):
        return data[s] if s in data.columns.get_level_values(0) else None
    return data


def add_closing_bar(sub, daily):
    """東証版：Yahoo の5分足には大引け（15:25〜15:30）の足が無いので、日足（調整なし）の終値で1本足す。
    始値＝高値＝安値＝終値＝日足の終値、出来高＝日足の出来高−その日の5分足の出来高合計（マイナスなら0）。"""
    if daily is None or daily.empty or sub is None or sub.empty:
        return sub
    idx = sub.index.tz_convert(TZ) if sub.index.tz is not None else sub.index
    sub = sub.copy(); sub.index = idx
    now = pd.Timestamp.now(tz=TZ)
    add = []
    for day, g in sub.groupby(sub.index.date):
        if g.index.max().strftime("%H%M") >= "1525":
            continue
        if day == now.date() and now.strftime("%H%M") < "1535":
            continue                      # 当日の大引け前は足さない
        dd = daily[daily.index.date == day] if len(daily) else daily
        if dd.empty or pd.isna(dd["Close"].iloc[-1]):
            continue
        cl = float(dd["Close"].iloc[-1])
        vol = max(0, int((dd["Volume"].iloc[-1] or 0) - g["Volume"].fillna(0).sum()))
        t = pd.Timestamp(f"{day} 15:25", tz=TZ)
        add.append(pd.DataFrame({"Open": [cl], "High": [cl], "Low": [cl], "Close": [cl], "Volume": [vol]}, index=[t]))
    return pd.concat([sub] + add).sort_index() if add else sub


def fetch(codes, period="1mo"):
    syms = [sym(c) for c in codes]
    data = yf.download(syms, period=period, interval="5m", group_by="ticker", auto_adjust=False,
                       prepost=False, threads=True, progress=False, actions=False)
    daily = None
    if not US:                            # 大引けの足に使う日足（調整なし）
        try:
            daily = yf.download(syms, period=period, interval="1d", group_by="ticker", auto_adjust=False,
                                threads=True, progress=False, actions=False)
        except Exception:
            daily = None
    got = 0
    for c, s in zip(codes, syms):
        try:
            sub = _pick(data, s)
            if sub is None:
                continue
            if daily is not None:
                dsub = _pick(daily, s)
                if dsub is not None:
                    dsub = dsub.dropna(subset=["Close"])
                    dsub.index = pd.to_datetime(dsub.index).tz_localize(None) if getattr(dsub.index, "tz", None) is not None else pd.to_datetime(dsub.index)
                    sub = add_closing_bar(sub, dsub)
            if merge_save(c, sub):
                got += 1
        except Exception:
            continue
    return got


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", default="")
    ap.add_argument("--period", default="1mo", help="取得期間（Yahoo の5分足は最長 60d）。初回の保存用に 60d も可")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    codes = [c.strip() for c in a.codes.split(",") if c.strip()] or load_codes()
    t0, ok = time.time(), 0
    for i in range(0, len(codes), BATCH):
        part = codes[i:i + BATCH]
        try:
            n = fetch(part, a.period)
        except Exception as e:
            print(f"  {i}: 失敗（{e}）→ 小分けにしてやり直し", flush=True)
            n = 0
            for j in range(0, len(part), 30):
                try:
                    n += fetch(part[j:j + 30], a.period)
                except Exception:
                    pass
        ok += n
        print(f"[{time.strftime('%H:%M:%S')}] {min(i + BATCH, len(codes))}/{len(codes)}  取得 {ok}  経過{time.time() - t0:.0f}秒", flush=True)
        time.sleep(1)
    print(f"5分足: {ok}/{len(codes)} 銘柄を保存（{OUT}）")
    return 0 if ok > len(codes) * 0.5 else 1


if __name__ == "__main__":
    sys.exit(main())
