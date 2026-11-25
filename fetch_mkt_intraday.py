#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""マーケット概況の指数タイルに描く「日中の動き」（5分足）を取る（Yahoo Finance・無料。2026-11-25 作成）

東証版・米国版で同じファイル（フォルダ名 米国株分析＝米国、それ以外＝東証）。
  出力: data/market/intraday.json  {"built":…, "s": {キー: {日付: {"v":[値…], "t0":"9:30", "t1":"16:00"}}}}
  各キーの直近3日分（タイルの日付に合うものを make_home.py が選ぶ）。点は多くても約100個に間引く。
  1日の区切り：米国の指数・金利＝米東部の日付、日本の指数＝日本の日付、原油・金の先物＝米東部 18:00〜翌17:00、
  VIX＝米東部 9:30〜16:15、ビットコイン・ドル円（米国版）＝世界標準時の日付、ドル円（東証版）＝その日の最後の値までの24時間。
  TOPIX は Yahoo に無いので ETF（1306.T）の5分足で形だけ取る（数字はタイルの終値に合わせて描く）。
  失敗したキーは前回の値を残す。
  手動: ~/株分析/.venv/bin/python ~/株分析/fetch_mkt_intraday.py
"""
import datetime, json, sys, time
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = Path(__file__).resolve().parent
OUT = BASE / "data" / "market" / "intraday.json"
US = BASE.name == "米国株分析"
NY, JST, UTC = ZoneInfo("America/New_York"), ZoneInfo("Asia/Tokyo"), datetime.timezone.utc

if US:
    KEYS = {"dow": ("^DJI", "ny"), "sp500": ("^GSPC", "ny"), "nasdaq": ("^IXIC", "ny"), "ndx": ("^NDX", "ny"),
            "sox": ("^SOX", "ny"), "rut": ("^RUT", "ny"), "vix": ("^VIX", "nyreg"), "us10y": ("^TNX", "ny"),
            "usdjpy": ("JPY=X", "utc"), "wti": ("CL=F", "fut"), "gold": ("GC=F", "fut"), "btc": ("BTC-USD", "utc")}
else:
    KEYS = {"nikkei225": ("^N225", "jst"), "topix": ("1306.T", "jst"), "nikkei_vi": ("^NKVI.OS", "jst"),
            "usdjpy": ("JPY=X", "last24"), "dow": ("^DJI", "ny"), "sp500": ("^GSPC", "ny"), "nasdaq": ("^IXIC", "ny"),
            "sox": ("^SOX", "ny"), "us10y": ("^TNX", "ny"), "wti": ("CL=F", "fut"), "gold": ("GC=F", "fut"),
            "btc": ("BTC-USD", "utc")}
MAXPT = 100


def sessions(ser, mode):
    """5分足（index は時刻つき）を 日付→[(時刻, 値)] に分ける"""
    out = {}
    for ts, v in ser.items():
        if v != v:
            continue
        if mode in ("ny", "nyreg"):
            t = ts.astimezone(NY); d = t.date()
            if mode == "nyreg" and not (9 * 60 + 30 <= t.hour * 60 + t.minute <= 16 * 60 + 15):
                continue      # VIX は時間外（米東部 3:15〜）も計算されるので、株式の取引時間（9:30〜16:15）だけにする
        elif mode in ("jst", "last24"):
            t = ts.astimezone(JST); d = t.date()
        elif mode == "fut":           # 米東部 18:00 から次の日の取引
            t = ts.astimezone(NY); d = (t + datetime.timedelta(hours=6)).date()
        else:
            t = ts.astimezone(UTC); d = t.date()
        out.setdefault(d.isoformat(), []).append((t, float(v)))
    if mode == "last24":              # その日の最後の値までの24時間（前の日の分も使う）
        allp = sorted((p for ps in out.values() for p in ps), key=lambda p: p[0])
        out = {d: [p for p in allp if ps[-1][0] - datetime.timedelta(hours=24) < p[0] <= ps[-1][0]] for d, ps in out.items()}
    return out


def thin(ps):
    if len(ps) <= MAXPT:
        return ps
    step = len(ps) / MAXPT
    idx = sorted({int(i * step) for i in range(MAXPT)} | {len(ps) - 1})
    return [ps[i] for i in idx]


def main():
    import yfinance as yf
    try:
        old = json.load(open(OUT, encoding="utf-8")).get("s", {})
    except Exception:
        old = {}
    res, bad = dict(old), 0
    for k, (sym, mode) in KEYS.items():
        ser = None
        for i in range(3):
            try:
                df = yf.Ticker(sym).history(period="5d", interval="5m", auto_adjust=False)
                if df is not None and len(df):
                    ser = df["Close"]; break
            except Exception as ex:
                print(f"{k}: 再試行 {ex}")
            time.sleep(2 + 2 * i)
        if ser is None:
            print(f"{k}（{sym}）: 失敗（前回分を残す）"); bad += 1; continue
        S = sessions(ser, mode)
        keep = {}
        for d in sorted(S)[-3:]:
            ps = thin(S[d])
            if len(ps) < 3:
                continue
            keep[d] = {"v": [round(v, 6) for _, v in ps], "t0": f"{ps[0][0].hour}:{ps[0][0].minute:02d}",
                       "t1": f"{ps[-1][0].hour}:{ps[-1][0].minute:02d}"}
        res[k] = keep
        print(f"{k}（{sym}）: " + "、".join(f"{d} {len(x['v'])}点" for d, x in keep.items()))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    json.dump({"built": datetime.datetime.now(JST).strftime("%Y-%m-%d %H:%M"), "s": res},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    return 1 if bad == len(KEYS) else 0


if __name__ == "__main__":
    sys.exit(main())
