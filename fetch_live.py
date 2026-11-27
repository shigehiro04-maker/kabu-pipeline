#!/usr/bin/env python3
"""主要指数の「いまの値」を取り直して公開する（取引時間中に15分おき。2026-11-24 作成。東証版・米国版で同じファイル）

フォルダ名で市場を切り替える（~/米国株分析＝米国、それ以外＝東証）。
- Yahoo（yfinance・無料）から指数の最新値と前日終値だけを取り、data/charts/live_indices.json に書く。
- そのファイルだけを GitHub Pages のリポジトリに送る（gh api。サイト全体は公開し直さない）。
- 取引時間外は何もしないで終わる。米国＝米東部時間の平日 9:25〜16:20（夏時間・冬時間は自動）、
  東証＝日本時間の平日 9:00〜15:40（祝日は日経平均の日足に当日が無いので送らない）。
- --force で時間外も実行。--no-push で送らずにファイルだけ作る（確認用）。
ページ側は add_live.py（このファイルの日付がページの株価データの日付より新しいときだけ値を書き換える）。
"""
import base64, csv, datetime, json, subprocess, sys
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = Path(__file__).resolve().parent
SITE = BASE / "data" / "charts"
OUT = SITE / "live_indices.json"
JST = ZoneInfo("Asia/Tokyo")
US = BASE.name == "米国株分析"

if US:
    REPO, TZ = "shigehiro04-maker/us-charts", ZoneInfo("America/New_York")
    OPEN, CLOSE = (9, 25), (16, 20)
    # make_market.py のタイルと同じ12枚
    KEYS = {"dow": "^DJI", "sp500": "^GSPC", "nasdaq": "^IXIC", "ndx": "^NDX", "sox": "^SOX", "rut": "^RUT",
            "vix": "^VIX", "us10y": "^TNX", "usdjpy": "JPY=X", "wti": "CL=F", "gold": "GC=F", "btc": "BTC-USD"}
else:
    REPO, TZ = "shigehiro04-maker/kabu-charts", JST
    OPEN, CLOSE = (9, 0), (15, 40)
    # 東京の取引時間に動くものだけ（米国の指数・金利・VIXは東京時間に新しい値が無いので今の表示のまま）
    # TOPIX は Yahoo(米) に無いので、Yahoo!ファイナンス（日本）の現在値を使う（2026-11-25〜。取れないときは ETF（1306.T）の前日比で前日の TOPIX 終値を換算）
    # 日経平均VI は Yahoo の ^NKVI.OS（前日終値が日経の公式CSVと一致することを確認、2026-11-24）
    KEYS = {"nikkei225": "^N225", "topix": "1306.T", "nikkei_vi": "^NKVI.OS", "usdjpy": "JPY=X", "wti": "CL=F", "gold": "GC=F", "btc": "BTC-USD"}


DAILY_PREV = ("JPY=X", "BTC-USD")   # 日足の1本前の終値
FUT_PREV = ("CL=F", "GC=F")         # 先物：取引所の区切り（米東部 17:00）より前の最後の値（＝前日の清算に近い終値）
NYT = ZoneInfo("America/New_York")


def fut_prev(yf, sym):
    now = datetime.datetime.now(NYT)
    b = now.replace(hour=17, minute=0, second=0, microsecond=0)
    if now < b:
        b -= datetime.timedelta(days=1)
    while b.weekday() >= 5:            # 土日の区切りは金曜の 17:00
        b -= datetime.timedelta(days=1)
    h = yf.Ticker(sym).history(period="5d", interval="1h")["Close"].dropna()
    h = h[h.index < b]
    return float(h.iloc[-1]) if len(h) else float("nan")


def in_session(now):
    if now.weekday() >= 5:
        return False
    t = now.hour * 60 + now.minute
    return OPEN[0] * 60 + OPEN[1] <= t <= CLOSE[0] * 60 + CLOSE[1]


def topix_prev(today):
    """主要指数ダッシュボードのデータから、今日より前の TOPIX の終値"""
    p = BASE / "株価指数" / "data" / "topix.csv"
    last = None
    try:
        with open(p, encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                d = (r.get("Date") or r.get("date") or "")[:10]
                if d and d < today and r.get("Close"):
                    last = float(r["Close"])
    except Exception:
        pass
    return last


def fetch(today):
    import yfinance as yf
    tiles = {}
    for k, sym in KEYS.items():
        try:
            fi = yf.Ticker(sym).fast_info
            last = float(fi["last_price"])
            prev = float(fi["regular_market_previous_close"] or "nan")   # 公式の前日終値（日足の終値と一致）
            if sym in FUT_PREV:
                prev = fut_prev(yf, sym)
            elif sym in DAILY_PREV:
                # 先物・為替・暗号資産は Yahoo の前日終値が1日古いことがあるので、日足の1本前（いまの足の前）の終値
                c = yf.Ticker(sym).history(period="5d", interval="1d")["Close"].dropna()
                prev = float(c.iloc[-2]) if len(c) >= 2 else float("nan")
            elif not prev > 0:
                prev = float(fi["previous_close"])
        except Exception as ex:
            print(f"  {k}（{sym}）取れませんでした: {ex}")
            continue
        if not (last > 0 and prev > 0):
            continue
        if k == "topix":
            # 2026-11-25：TOPIX そのものの現在値（Yahoo!ファイナンス 998405.T、株価指数/topix_yjp.py）。取れないときは ETF 換算
            try:
                sys.path.insert(0, str(BASE / "株価指数"))
                import topix_yjp
                q = topix_yjp.quote()
                last, prev = q["price"], round(q["price"] - q["chg"], 2)
            except Exception as ex:
                print(f"  topix（Yahoo!ファイナンス）取れませんでした: {ex}（ETF 換算を使う）")
                base = topix_prev(today)
                if not base:
                    continue
                last, prev = base * last / prev, base
        rate = k == "us10y"
        diff = last - prev
        chg = diff if rate or k in ("vix", "nikkei_vi", "usdjpy") else diff / prev * 100
        tiles[k] = {"close": round(last, 4), "prev": round(prev, 4), "chg": round(chg, 4),
                    "dir": 1 if diff > 0 else -1 if diff < 0 else 0,
                    "nd": 0 if k == "btc" else 2, "suf": "%" if rate else "",
                    "csuf": "pt" if rate else "" if k in ("vix", "nikkei_vi") else "円" if k == "usdjpy" else "%"}
    return tiles


def jp_trading_today(today):
    """祝日の判定：日経平均の日足に今日の行があるか（寄り付き後）"""
    try:
        import yfinance as yf
        h = yf.Ticker("^N225").history(period="5d", interval="1d")
        return len(h) and str(h.index[-1])[:10] == today
    except Exception:
        return True


def push(text):
    path = OUT.name
    r = subprocess.run(["gh", "api", f"repos/{REPO}/contents/{path}", "--jq", ".sha"],
                       capture_output=True, text=True)
    sha = r.stdout.strip() if r.returncode == 0 else ""
    args = ["gh", "api", "-X", "PUT", f"repos/{REPO}/contents/{path}",
            "-f", f"message=live {datetime.datetime.now(JST):%Y-%m-%d %H:%M}",
            "-f", "content=" + base64.b64encode(text.encode()).decode()]
    if sha:
        args += ["-f", f"sha={sha}"]
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        print("  送信に失敗:", (r.stderr or r.stdout).strip()[-300:])
        return False
    return True


def main():
    force, nopush = "--force" in sys.argv, "--no-push" in sys.argv
    now = datetime.datetime.now(TZ)
    today = now.strftime("%Y-%m-%d")
    if not force and not in_session(now):
        return
    jst = datetime.datetime.now(JST)
    if not US and not force and not jp_trading_today(today):
        print(f"{jst:%m/%d %H:%M} 東証は休場のようなので送りません")
        return
    tiles = fetch(today)
    if len(tiles) < len(KEYS) // 2:
        print(f"{jst:%m/%d %H:%M} 取れた指数が少ないので送りません（{len(tiles)}件）")
        return
    data = {"at": jst.strftime("%Y-%m-%d %H:%M"), "day": today, "ny": now.strftime("%Y-%m-%d %H:%M"),
            "market": "us" if US else "jp", "open": in_session(now), "tiles": tiles}
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    OUT.write_text(text, encoding="utf-8")
    ok = True if nopush else push(text)
    print(f"{jst:%m/%d %H:%M}（現地 {now:%H:%M}）{len(tiles)}指数 " + ("作成のみ" if nopush else "公開" if ok else "公開失敗"))


if __name__ == "__main__":
    main()
