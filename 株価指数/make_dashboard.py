#!/usr/bin/env python3
"""
fetch_indices.py が保存したCSVから、主要指数ダッシュボード（dashboard.html）を生成する。
（2026-11-16 に「株価指数ダッシュボード」から改名し、指数・金利・為替・商品を追加。変更前は make_dashboard.py.pre_main）

使い方:
    python3 make_dashboard.py                  # ~/market_data のCSVを読んで dashboard.html を出力
    python3 make_dashboard.py --outdir ./data
    python3 make_dashboard.py --outdir 株価指数/data --html data/charts/indices.html --home ./index.html
    open ~/market_data/dashboard.html          # ブラウザで開く

fetch_indices.py の実行後に自動で呼ばれるので、通常は単体で動かす必要はありません。
外部ライブラリ・通信は不要（HTML単体で完結、オフラインで閲覧可）。
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

import pandas as pd

# (キー, 表示名, 地域, 種別)  種別: price=株価指数 / fear=恐怖指数 / rate=金利（変化は%ではなくpt）/ fx=為替 / cmdty=商品 / crypto=暗号資産
#   株価指数の比較グラフには price だけを出す
INDICES = [
    ("nikkei225", "日経平均", "日本", "price"),
    ("topix", "TOPIX", "日本", "price"),
    ("nikkei_vi", "日経平均VI", "日本", "fear"),
    ("dow", "ダウ平均", "米国", "price"),
    ("sp500", "S&P500", "米国", "price"),
    ("nasdaq", "NASDAQ総合", "米国", "price"),
    ("nasdaq100", "NASDAQ100", "米国", "price"),
    ("sox", "SOX指数", "米国", "price"),
    ("russell2000", "ラッセル2000", "米国", "price"),
    ("vix", "VIX", "米国", "fear"),
    ("us10y", "米10年国債利回り", "金利・為替・商品", "rate"),
    ("usdjpy", "ドル円", "金利・為替・商品", "fx"),
    ("wti", "WTI原油先物", "金利・為替・商品", "cmdty"),
    ("gold", "金先物", "金利・為替・商品", "cmdty"),
    ("btc", "ビットコイン", "金利・為替・商品", "crypto"),
]
# 米国株分析のサイトに載せるとき（環境変数 KB_IDX_MARKET=us）：米国を先頭に、日本は日経平均・日経平均VI（TOPIX なし）、東証の騰落レシオは出さない
MARKET = os.environ.get("KB_IDX_MARKET", "jp")
if MARKET == "us":
    INDICES = [x for x in INDICES if x[0] not in ("topix",)]
REGIONS = ["米国", "金利・為替・商品", "日本"] if MARKET == "us" else ["日本", "米国", "金利・為替・商品"]
RATE_KEYS = {"us10y"}     # 利回りは前日比・期間の変化を「%pt」の差で出す（利回りの何%変化かは意味が薄いため）

# 恐怖指数の水準の目安（上限値, ラベル, 状態）
FEAR_BANDS = {
    "vix": [(15, "安定", "good"), (20, "平常", "good"), (30, "警戒", "warning"), (1e9, "恐怖", "critical")],
    "nikkei_vi": [(20, "安定", "good"), (25, "平常", "good"), (35, "警戒", "warning"), (1e9, "恐怖", "critical")],
}
STALE_DAYS = 7

# TOPIXの長期チャートの予備：世界統計データ（総務省 統計ダッシュボード）の月末値・年末値
#   日足（stooq / J-Quants）が無い期間を、月次（2007年〜）と年次（1949年〜）で埋めて表示する。
#   ~/Documents は自動実行（launchd）から読めないことがあるため、読めたときに data/topix_estat.csv へ写しておく。
ESTAT_CSV = Path(os.environ.get("ESTAT_CSV", Path.home() / "Documents" / "世界統計データ" / "csv" / "2_全国" / "07_企業・家計・経済.csv"))
ESTAT_TOPIX = "0702020590000090010"


def load_estat_topix(outdir: Path) -> pd.DataFrame | None:
    """Date, Close, Freq(月/年) を返す。元CSVが読めなければ前回の写しを使う。"""
    cache = outdir / "topix_estat.csv"
    try:
        df = pd.read_csv(ESTAT_CSV, usecols=["系列コード", "周期", "時点コード", "値"],
                         dtype={"系列コード": str, "時点コード": str})
        df = df[(df["系列コード"] == ESTAT_TOPIX) & df["周期"].isin(["月", "年"])].copy()
        if df.empty:
            raise ValueError("TOPIXの系列が見つかりません")

        def to_date(code: str, freq: str) -> pd.Timestamp:
            y = int(code[:4])
            if freq == "年":
                return pd.Timestamp(y, 12, 31)
            return pd.Timestamp(y, int(code[4:6]), 1) + pd.offsets.MonthEnd(0)

        df["Date"] = [to_date(c, f) for c, f in zip(df["時点コード"], df["周期"])]
        df = (df.rename(columns={"値": "Close", "周期": "Freq"})[["Date", "Close", "Freq"]]
                .dropna().sort_values("Date"))
        df.to_csv(cache, index=False, date_format="%Y-%m-%d")
        return df
    except Exception as e:  # noqa: BLE001  (権限なし・ファイルなし等)
        if cache.exists():
            print(f"世界統計データを読めないため前回の写しを使います: {e}")
            return pd.read_csv(cache, parse_dates=["Date"])
        print(f"世界統計データを読めません（TOPIXの長期予備なし）: {e}")
        return None


def topix_longterm(lt: pd.DataFrame, before: pd.Timestamp | None) -> pd.Series:
    """日足の開始日より前の部分。月次がある期間は月次、それより前は年次。"""
    m = lt[lt["Freq"] == "月"].set_index("Date")["Close"]
    y = lt[lt["Freq"] == "年"].set_index("Date")["Close"]
    if len(m):
        y = y[y.index < m.index[0]]
    s = pd.concat([y, m]).astype(float).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    return s[s.index < before] if before is not None else s


def value_on_or_before(s: pd.Series, when: pd.Timestamp) -> float | None:
    s = s[s.index <= when]
    return float(s.iloc[-1]) if len(s) else None


def pct(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return (a / b - 1) * 100


def metrics(key: str, s: pd.Series, now: pd.Timestamp) -> dict:
    last_d, last = s.index[-1], float(s.iloc[-1])
    prev = float(s.iloc[-2]) if len(s) > 1 else None
    y52 = s[s.index > last_d - pd.Timedelta(days=365)]
    ma25 = s.rolling(25).mean().iloc[-1] if len(s) >= 25 else None
    ma200 = s.rolling(200).mean().iloc[-1] if len(s) >= 200 else None
    prev_year_end = value_on_or_before(s, pd.Timestamp(last_d.year - 1, 12, 31))
    m = {
        "date": last_d.strftime("%Y-%m-%d"),
        "close": last,
        "chg": (last - prev) if prev is not None else None,
        "chgPct": pct(last, prev),
        "r1w": pct(last, value_on_or_before(s, last_d - pd.Timedelta(days=7))),
        "r1m": pct(last, value_on_or_before(s, last_d - pd.DateOffset(months=1))),
        "ytd": pct(last, prev_year_end),
        "r1y": pct(last, value_on_or_before(s, last_d - pd.DateOffset(years=1))),
        "hi52": float(y52.max()),
        "lo52": float(y52.min()),
        "fromHi": pct(last, float(y52.max())),
        "ma25": pct(last, ma25),
        "ma200": pct(last, ma200),
        "first": s.index[0].strftime("%Y-%m-%d"),
        "stale": (now - last_d).days > STALE_DAYS,
    }
    if key in RATE_KEYS:
        diff = lambda a, b: None if a is None or b is None else a - b
        m["unit"] = "pt"
        m["chgPct"] = m["chg"]
        m["r1w"] = diff(last, value_on_or_before(s, last_d - pd.Timedelta(days=7)))
        m["r1m"] = diff(last, value_on_or_before(s, last_d - pd.DateOffset(months=1)))
        m["ytd"] = diff(last, prev_year_end)
        m["r1y"] = diff(last, value_on_or_before(s, last_d - pd.DateOffset(years=1)))
        m["fromHi"] = last - float(y52.max())
    if key in FEAR_BANDS:
        for upper, label, status in FEAR_BANDS[key]:
            if last < upper:
                m["band"], m["bandStatus"] = label, status
                break
    return m


ROOT = Path(__file__).resolve().parent.parent      # 株分析/


def ad_ratio(root: Path = ROOT) -> dict:
    """騰落レシオ（25日・10日）＝値上がり銘柄数の合計÷値下がり銘柄数の合計×100 を、手元の株価CSVから全期間ぶん計算する。
    戻り値 {"all": {...}, "prime": {...}}（d=1970-01-01からの日数）。計算できなければ {}。"""
    import numpy as np
    try:
        tk = pd.read_csv(root / "tickers" / "tse_tickers.csv", dtype=str, encoding="utf-8-sig")
        prime = set(tk.loc[tk["market"].fillna("").str.contains("プライム"), "code"])
        sg_all, sg_pr = {}, {}
        for code in tk["code"]:
            f = root / "data" / "prices" / f"{code}.csv"
            if not f.exists():
                continue
            df = pd.read_csv(f, usecols=["date", "close"]).dropna()
            df = df[df["close"] > 0]
            if len(df) < 2:
                continue
            sg = pd.Series(np.sign(np.diff(df["close"].to_numpy(float))).astype("int8"), index=df["date"].to_numpy()[1:])
            sg = sg[~sg.index.duplicated(keep="last")]
            sg_all[code] = sg
            if code in prime:
                sg_pr[code] = sg
        out = {}
        epoch = pd.Timestamp("1970-01-01")
        for key, d in (("all", sg_all), ("prime", sg_pr)):
            if not d:
                continue
            m = pd.DataFrame(d).sort_index()
            cnt = pd.DataFrame({"up": (m > 0).sum(axis=1), "dn": (m < 0).sum(axis=1), "fl": (m == 0).sum(axis=1)})
            tot = cnt.sum(axis=1)
            cnt = cnt[tot >= tot.rolling(20, min_periods=1).median() * 0.5]      # 休場日にデータが紛れた日は除く
            r25 = cnt["up"].rolling(25).sum() / cnt["dn"].rolling(25).sum().replace(0, np.nan) * 100
            r10 = cnt["up"].rolling(10).sum() / cnt["dn"].rolling(10).sum().replace(0, np.nan) * 100
            cnt = cnt.assign(r25=r25, r10=r10).dropna(subset=["r25", "r10"])
            idx = pd.to_datetime(cnt.index)
            out[key] = {"d": ((idx - epoch).days).tolist(), "r25": [round(float(x), 1) for x in cnt["r25"]],
                        "r10": [round(float(x), 1) for x in cnt["r10"]],
                        "up": cnt["up"].astype(int).tolist(), "dn": cnt["dn"].astype(int).tolist()}
        return out
    except Exception as e:      # 騰落レシオが作れなくても指数のページは出す
        print(f"騰落レシオを計算できませんでした: {e}")
        return {}


def ad_all(outdir: Path) -> dict:
    """東証（全市場・プライム）＋米国（ダウ・S&P500・NASDAQ100。fetch_us_breadth.py が作る us_breadth.json）"""
    out = {} if MARKET == "us" else ad_ratio()
    p = outdir / "us_breadth.json"
    if not p.exists():      # 米国株分析では 株価指数/data/us_breadth.json（fetch_us_breadth.py が作る）を使う
        p = Path(__file__).resolve().parent / "data" / "us_breadth.json"
    if p.exists():
        try:
            us = json.loads(p.read_text(encoding="utf-8"))
            for k in ("dow", "sp500", "nasdaq100"):
                if us.get(k) and us[k].get("d"):
                    out[k] = us[k]
        except Exception as e:
            print(f"米国の騰落レシオを読めませんでした: {e}")
    return out


def build(outdir: Path, html: Path | None = None, home: str | None = None) -> Path:
    """outdir のCSVから HTML を作る。html: 出力先（省略時 outdir/dashboard.html）、
    home: 「‹ トップ」リンクの行き先（東証 株分析サイトに載せるとき "./index.html"）"""
    now = pd.Timestamp(datetime.now()).normalize()
    epoch = pd.Timestamp("1970-01-01")
    days = lambda idx: ((idx - epoch).days).tolist()      # 1970-01-01からの日数
    vals = lambda s: [round(float(v), 2) for v in s.tolist()]
    payload = []
    for key, name, region, kind in INDICES:
        path = outdir / f"{key}.csv"
        item = {"key": key, "name": name, "region": region, "kind": kind}
        s = None
        if path.exists():
            df = pd.read_csv(path, parse_dates=["Date"]).dropna(subset=["Close"])
            s = df.set_index("Date")["Close"].astype(float).sort_index()
            s = s[~s.index.duplicated(keep="last")]
            item["src"] = str(df["Source"].iloc[-1]) if "Source" in df.columns else ""
            if s.empty:
                s = None

        lt = None
        if key == "topix":
            est = load_estat_topix(outdir)
            if est is not None and len(est):
                lt = topix_longterm(est, s.index[0] if s is not None else None)

        if s is not None:
            item["m"] = metrics(key, s, now)
            if "1306" in item.get("src", ""):
                item["m"]["note"] = "ETF換算"
            item["d"], item["c"] = days(s.index), vals(s)
            if lt is not None and len(lt):
                item["ld"], item["lc"] = days(lt.index), vals(lt)   # 日足より前の月末値・年末値
        elif lt is not None and len(lt):
            # 日足が1本も無いときは、月末値の系列だけで表示する（前日比・移動平均などは出さない）
            m = metrics(key, lt, now)
            for k in ("chg", "chgPct", "r1w", "ma25", "ma200"):
                m[k] = None
            m["stale"] = False
            m["note"] = f"{lt.index[-1].month}月末"
            item["m"], item["d"], item["c"] = m, days(lt.index), vals(lt)
            item["monthly"] = True
            item["src"] = "世界統計データ（月末値）"
        else:
            item["missing"] = True
        payload.append(item)

    home_link = (f'<a class="home" href="{home}" title="トップへ">‹</a>' if home else "")
    page = (TEMPLATE.replace("__DATA__", json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
            .replace("__AD__", json.dumps(ad_all(outdir), ensure_ascii=False, separators=(",", ":")))
            .replace("__GENERATED__", datetime.now().strftime("%Y-%m-%d %H:%M"))
            .replace("__HOME__", home_link)
            .replace("__REGIONS__", json.dumps(REGIONS, ensure_ascii=False))
            .replace("__DEFKEY__", "sp500" if MARKET == "us" else "nikkei225")
            .replace("__LSKEY__", "idxdash-us" if MARKET == "us" else "idxdash"))
    out = Path(html) if html else outdir / "dashboard.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    # トップ画面のカード用の要約（make_home.py が読む）
    summary = [{"key": x["key"], "name": x["name"], **{k: x["m"].get(k) for k in ("close", "chgPct", "date", "band", "note")}}
               for x in payload if "m" in x]
    (out.parent / (out.stem + "_summary.json")).write_text(
        json.dumps(summary, ensure_ascii=False), encoding="utf-8")
    return out


TEMPLATE = r"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>主要指数</title>
<script>(function(){var m=/[?&#]theme=(dark|light)/.exec(location.search+location.hash),t=m&&m[1];
if(!t){try{t=localStorage.getItem('fdb-theme')}catch(e){}}if(t)document.documentElement.setAttribute('data-theme',t);})();</script>
<style>
@import url("https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap");
:root{
  color-scheme:light;
  --page:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --axis:#c3c2b7; --border:rgba(11,11,11,.10);
  --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --s4:#eda100; --s5:#e87ba4; --s6:#7b61c9; --s7:#5f8f2a; --s8:#8a6a4a;
  --good:#0ca30c; --good-text:#006300; --warning:#fab219; --critical:#d03b3b;
  --up:#c93a3a; --dn:#2E7D6B;
  --wash:rgba(42,120,214,.08);
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    color-scheme:dark;
    --page:#0d0d0d; --surface:#1a1a19; --ink:#ffffff; --ink2:#c3c2b7; --muted:#898781;
    --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,.10);
    --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500; --s5:#d55181; --s6:#9a84e6; --s7:#7fb04a; --s8:#b08d6a;
    --good-text:#0ca30c; --critical:#e66767; --wash:rgba(57,135,229,.14);
    --up:#e66767; --dn:#3FA58C;
  }
}
:root[data-theme="dark"]{
  color-scheme:dark;
  --page:#0d0d0d; --surface:#1a1a19; --ink:#ffffff; --ink2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,.10);
  --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500; --s5:#d55181; --s6:#9a84e6; --s7:#7fb04a; --s8:#b08d6a;
  --good-text:#0ca30c; --critical:#e66767; --wash:rgba(57,135,229,.14);
    --up:#e66767; --dn:#3FA58C;
}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);
  font:14px/1.5 system-ui,-apple-system,"Hiragino Sans","Segoe UI",sans-serif}
.wrap{max-width:1200px;margin:0 auto;padding:24px 16px 48px}
header{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;gap:8px;margin-bottom:20px}
h1{font-size:22px;margin:0;font-weight:700}
h2{font-size:15px;margin:0 0 12px;font-weight:600}
.meta{color:var(--muted);font-size:12px}
.panel{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:16px;margin-bottom:16px}
.region{color:var(--ink2);font-size:12px;font-weight:600;margin:4px 0 8px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:12px;margin-bottom:16px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:14px 14px 10px;
  cursor:pointer;text-align:left;font:inherit;color:inherit;width:100%}
.card:hover{background:var(--wash)}
.card[aria-pressed="true"]{outline:2px solid var(--s1);outline-offset:-1px}
.card .top{display:flex;justify-content:space-between;align-items:center;gap:8px}
.card .name{font-weight:600}
.card .val{font-size:26px;font-weight:700;margin:4px 0 0;letter-spacing:.01em}
.card .sub{display:flex;justify-content:space-between;color:var(--ink2);font-size:12px;margin-top:2px}
.delta{display:inline-flex;gap:4px;align-items:center;font-variant-numeric:tabular-nums}
.up .arw{color:var(--up)} .dn .arw{color:var(--dn)}
.badge{display:inline-flex;align-items:center;gap:4px;font-size:11px;padding:2px 8px;border-radius:999px;
  border:1px solid var(--border);color:var(--ink2);white-space:nowrap}
.dot{width:8px;height:8px;border-radius:50%;display:inline-block}
.dot.good{background:var(--good)} .dot.warning{background:var(--warning)} .dot.critical{background:var(--critical)}
.stale{color:var(--critical);font-size:11px}
.spark{display:block;width:100%;height:40px;margin-top:6px}
.controls{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:12px}
.seg{display:inline-flex;border:1px solid var(--border);border-radius:8px;overflow:hidden}
.seg button{border:0;background:transparent;color:var(--ink2);font:inherit;font-size:12px;padding:6px 10px;cursor:pointer}
.seg button+button{border-left:1px solid var(--border)}
.seg button[aria-pressed="true"]{background:var(--wash);color:var(--ink);font-weight:600}
select{font:inherit;font-size:13px;padding:5px 8px;border-radius:8px;border:1px solid var(--border);background:var(--surface);color:var(--ink)}
label.chk{display:inline-flex;gap:6px;align-items:center;font-size:12px;color:var(--ink2);cursor:pointer}
.chart{position:relative;width:100%}
.chart svg{display:block;width:100%;overflow:visible}
.chart text{fill:var(--muted);font-size:11px;font-variant-numeric:tabular-nums}
.tip{position:absolute;pointer-events:none;background:var(--surface);border:1px solid var(--border);border-radius:8px;
  padding:6px 10px;font-size:12px;box-shadow:0 4px 12px rgba(0,0,0,.12);white-space:nowrap;display:none;z-index:2}
.tip .d{color:var(--muted);margin-bottom:2px}
.tip .r{display:flex;gap:8px;align-items:center;justify-content:space-between;font-variant-numeric:tabular-nums}
.legend{display:flex;flex-wrap:wrap;gap:12px;margin-top:8px;font-size:12px;color:var(--ink2)}
.legend span{display:inline-flex;align-items:center;gap:6px}
.legend i{width:14px;height:2px;border-radius:1px;display:inline-block}
.tablewrap{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:13px;min-width:760px}
th,td{padding:8px 10px;text-align:right;border-bottom:1px solid var(--grid);font-variant-numeric:tabular-nums;white-space:nowrap}
th{color:var(--muted);font-weight:500;font-size:12px}
th:first-child,td:first-child{text-align:left}
tbody tr:hover{background:var(--wash)}
.pos::before{content:"▲ ";color:var(--up);font-size:9px}
.neg::before{content:"▼ ";color:var(--dn);font-size:9px}
.na{color:var(--muted)}
.note{color:var(--muted);font-size:11px;margin-top:8px}
.two{display:grid;grid-template-columns:1fr;gap:16px}
.home{text-decoration:none;color:inherit;margin-right:8px}
.btn{border:1px solid var(--border);background:transparent;color:var(--ink);border-radius:8px;padding:5px 11px;font:inherit;font-size:12.5px;cursor:pointer}
.hdr-r{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
/* ===== 2026-11 デザイン刷新（トップ画面と共通）：黒／白地、枠線なしのカード、数字は Inter の極太、騰落は赤＝上昇／緑＝下落 ===== */
:root{--page:#f3f4f6;--surface:#fff;--ink:#0c0d10;--ink2:#3d4148;--muted:#5b6068;--grid:#dfe2e7;--axis:#c0c4cc;--border:rgba(12,13,16,.13);--up:#b91c24;--dn:#08705a;--wash:rgba(12,13,16,.05)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--page:#050608;--surface:#101216;--ink:#f2f4f8;--ink2:#c6cbd6;--muted:#8f96a3;--grid:#23262d;--axis:#30343d;--border:rgba(255,255,255,.13);--up:#ff7378;--dn:#3fd0a4;--wash:rgba(255,255,255,.06)}}
:root[data-theme="dark"]{--page:#050608;--surface:#101216;--ink:#f2f4f8;--ink2:#c6cbd6;--muted:#8f96a3;--grid:#23262d;--axis:#30343d;--border:rgba(255,255,255,.13);--up:#ff7378;--dn:#3fd0a4;--wash:rgba(255,255,255,.06)}
body{font-family:Inter,"Hiragino Sans","Hiragino Kaku Gothic ProN","Noto Sans JP",system-ui,-apple-system,"Segoe UI",sans-serif;font-variant-numeric:tabular-nums;-webkit-font-smoothing:antialiased}
h1{font-size:24px;font-weight:800;letter-spacing:.02em}
h2{font-weight:800}
.region{font-size:12px;font-weight:800;letter-spacing:.1em;color:var(--ink)}
.panel,.card{border:0;border-radius:14px}
.card[aria-pressed="true"]{outline:2px solid var(--ink)}
.card .name{font-weight:800}
.card .val{font-size:32px;font-weight:800;letter-spacing:-.03em;line-height:1.15}
.delta{font-weight:700}
.delta.up,.up>.delta,.pos{color:var(--up)}
.delta.dn,.dn>.delta,.neg{color:var(--dn)}
td{font-weight:600}td:first-child{font-weight:800}
th{font-weight:800;letter-spacing:.04em;border-bottom:2px solid var(--ink)}
.seg{border:0;background:var(--surface);border-radius:10px}
.seg button{font-weight:600}
.seg button[aria-pressed="true"]{background:var(--ink);color:var(--page);font-weight:800}
#adBox{margin-top:22px;padding-top:14px;border-top:3px solid var(--ink)}
.adh{display:flex;justify-content:space-between;align-items:flex-end;gap:10px 16px;flex-wrap:wrap;margin-bottom:6px}
.adk{font-size:13px;font-weight:800;letter-spacing:.08em}.adk span{font-weight:400;letter-spacing:0;color:var(--muted);font-size:12px;margin-left:8px}
.adv{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
.adv b{font-size:44px;font-weight:800;letter-spacing:-.04em;line-height:1.1;font-variant-numeric:tabular-nums}
.adv small{font-size:12px;color:var(--muted)}
#adMk{flex-wrap:wrap}
.adp{font-size:13px;font-weight:800;padding:2px 10px;border-radius:6px;background:var(--wash);color:var(--ink)}
.adp.hot{background:var(--up);color:var(--page)}.adp.warm{color:var(--up)}.adp.cool{color:var(--dn)}.adp.cold{background:var(--dn);color:var(--page)}
@media (max-width:640px){h1{font-size:19px}.card .val{font-size:26px}.adv b{font-size:34px}}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>__HOME__主要指数</h1>
    <div class="hdr-r"><span class="meta">更新 __GENERATED__ ・ 各指数の最終取引日の終値</span>
    <button class="btn" id="theme" type="button">明暗</button></div>
  </header>

  <div id="cards"></div>

  <section class="panel">
    <h2>騰落率・テクニカル</h2>
    <div class="tablewrap"><table id="perf"></table></div>
    <div class="note">▲▼は前日比・期間騰落率の方向。移動平均乖離率＝終値÷移動平均−1。米10年国債利回りの前日比・期間の変化と52週高値比は、利回りの差（%pt）です。恐怖指数の水準（VIX: 15/20/30、日経VI: 20/25/35 で区分）は一般的な目安です。<span id="proxyNote"></span></div>
  </section>

  <div class="controls" role="group" aria-label="期間">
    <div class="seg" id="range"></div>
  </div>

  <div class="two">
    <section class="panel">
      <div class="controls">
        <h2 style="margin:0;flex:1" id="mainTitle">推移</h2>
        <label class="chk"><input type="checkbox" id="ma"> 25日・200日移動平均</label>
        <label class="chk"><input type="checkbox" id="log"> 対数目盛</label>
      </div>
      <div class="chart" id="main"></div>
      <div class="legend" id="mainLegend"></div>
      <div id="adBox" style="display:none">
        <div class="adh">
          <div><div class="adk">騰落レシオ（25日）<span>相場全体の過熱感</span></div>
            <div class="adv"><b id="adVal">—</b><span class="adp" id="adPill"></span><small id="adSub"></small></div></div>
          <div class="seg" id="adMk"></div>
        </div>
        <div class="chart" id="adChart"></div>
        <div class="legend"><span><i style="background:var(--ink)"></i>25日</span><span><i style="background:var(--muted)"></i>10日</span>
          <span><i style="background:var(--up);opacity:.35;height:10px"></i>120%以上＝過熱圏</span><span><i style="background:var(--dn);opacity:.35;height:10px"></i>80%以下＝売られすぎ圏</span></div>
        <div class="note" id="adNote"></div>
      </div>
    </section>

    <section class="panel">
      <h2>株価指数の比較（期間初日＝100）</h2>
      <div class="chart" id="cmp"></div>
      <div class="legend" id="cmpLegend"></div>
      <div class="note">比較は株価指数だけです（恐怖指数・金利・為替・商品は値の意味が違うため除外）。</div>
    </section>
  </div>
</div>

<script>
const DATA = __DATA__;
const DAY = 86400000;
DATA.forEach(x => { x.proxy = (x.src || "").includes("1306"); });   // TOPIXをETF(1306.T)から換算した日足
const byKey = Object.fromEntries(DATA.map(x => [x.key, x]));
const avail = DATA.filter(x => !x.missing);
const PRICE = avail.filter(x => x.kind === "price");
const SERIES_VAR = ["--s1","--s2","--s3","--s4","--s5","--s6","--s7","--s8"];
const cmpColor = Object.fromEntries(PRICE.map((x,i) => [x.key, SERIES_VAR[i % SERIES_VAR.length]]));
const dec = x => x.key === "btc" ? 0 : 2;   // 表示の小数桁
const unit = x => x.m && x.m.unit === "pt" ? "pt" : "%";
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

const RANGES = [["1M",30],["3M",91],["6M",182],["1Y",365],["3Y",1096],["5Y",1826],["10Y",3652],["全期間",0]];
const DEFKEY = "__DEFKEY__", LSKEY = "__LSKEY__";   // 東証版と米国版は同じサイト（github.io）なので保存先を分ける
let state = { key: (byKey[DEFKEY] && !byKey[DEFKEY].missing) ? DEFKEY : (avail[0]||{}).key, range: 365, log: false, ma: false };
try { Object.assign(state, JSON.parse(localStorage.getItem(LSKEY) || "{}")); } catch(e) {}
if (!byKey[state.key] || byKey[state.key].missing) state.key = (avail[0]||{}).key;
const save = () => { try { localStorage.setItem(LSKEY, JSON.stringify(state)); } catch(e) {} };

// ---------- format
const nf = (v, d=2) => v == null || isNaN(v) ? "—" : v.toLocaleString("ja-JP", {minimumFractionDigits:d, maximumFractionDigits:d});
const sgn = (v, d=2, suf="") => v == null || isNaN(v) ? "—" : (v > 0 ? "+" : v < 0 ? "−" : "±") + nf(Math.abs(v), d) + suf;
const cls = v => v == null || isNaN(v) ? "na" : v > 0 ? "pos" : v < 0 ? "neg" : "";
const toDate = n => new Date(n * DAY);
const fmtD = n => { const d = toDate(n); return `${d.getUTCFullYear()}/${String(d.getUTCMonth()+1).padStart(2,"0")}/${String(d.getUTCDate()).padStart(2,"0")}`; };
const decimals = x => x.kind === "fear" ? 2 : (x.m && x.m.close > 10000 ? 2 : 2);

// ---------- cards
function renderCards() {
  const root = document.getElementById("cards");
  root.innerHTML = "";
  for (const region of __REGIONS__) {
    const items = DATA.filter(x => x.region === region);
    const h = document.createElement("div"); h.className = "region"; h.textContent = region; root.appendChild(h);
    const g = document.createElement("div"); g.className = "grid"; root.appendChild(g);
    for (const x of items) {
      const b = document.createElement("button");
      b.className = "card"; b.type = "button";
      if (x.missing) {
        b.disabled = true;
        b.innerHTML = `<div class="top"><span class="name">${x.name}</span></div><div class="val na">—</div><div class="sub"><span>データ未取得</span></div>`;
        g.appendChild(b); continue;
      }
      const m = x.m, dir = m.chg > 0 ? "up" : m.chg < 0 ? "dn" : "";
      const deltaHtml = x.monthly ? `<span>月末値（世界統計データ）</span>`
        : x.kind === "rate" ? `<span class="delta ${dir}"><span class="arw">${dir==="up"?"▲":dir==="dn"?"▼":""}</span>${sgn(m.chg,2,"pt")}</span>`
        : `<span class="delta ${dir}"><span class="arw">${dir==="up"?"▲":dir==="dn"?"▼":""}</span>${sgn(m.chg,dec(x))}（${sgn(m.chgPct,2,"%")}）</span>`;
      const badge = m.band ? `<span class="badge"><span class="dot ${m.bandStatus}"></span>${m.band}</span>`
        : x.proxy ? `<span class="badge" title="TOPIX連動ETF（1306.T）から換算した推定値">ETF換算</span>` : "";
      b.setAttribute("aria-pressed", x.key === state.key);
      b.innerHTML = `
        <div class="top"><span class="name">${x.name}</span>${badge}</div>
        <div class="val">${nf(m.close, dec(x))}${x.kind === "rate" ? "%" : ""}</div>
        <div class="sub">
          ${deltaHtml}
          <span>${m.date.replaceAll("-","/")}${m.stale ? ' <span class="stale">更新停止?</span>' : ""}</span>
        </div>
        <svg class="spark" viewBox="0 0 100 40" preserveAspectRatio="none" aria-hidden="true"></svg>`;
      b.onclick = () => { state.key = x.key; save(); renderCards(); renderMain(); b.focus(); document.getElementById("main").scrollIntoView({behavior:"smooth", block:"center"}); };
      g.appendChild(b);
      spark(b.querySelector(".spark"), x);
    }
  }
}
function spark(svg, x) {
  const end = x.d[x.d.length-1], i0 = lowerBound(x.d, end - (x.monthly ? 730 : 91));
  const d = x.d.slice(i0), c = x.c.slice(i0);
  if (c.length < 2) return;
  const lo = Math.min(...c), hi = Math.max(...c), r = hi - lo || 1;
  const pts = c.map((v,i) => `${(i/(c.length-1)*100).toFixed(2)},${(36 - (v-lo)/r*32).toFixed(2)}`).join(" ");
  svg.innerHTML = `<polyline points="${pts}" fill="none" stroke="var(--s1)" stroke-width="1.5" vector-effect="non-scaling-stroke" stroke-linejoin="round"/>`;
}

// ---------- table
function renderTable() {
  const cols = [["前日比","chgPct"],["1週間","r1w"],["1ヶ月","r1m"],["年初来","ytd"],["1年","r1y"],["52週高値比","fromHi"],["25日線乖離","ma25"],["200日線乖離","ma200"]];
  let h = `<thead><tr><th>指数</th><th>終値</th><th>日付</th>${cols.map(c=>`<th>${c[0]}</th>`).join("")}<th>52週レンジ</th></tr></thead><tbody>`;
  for (const x of DATA) {
    if (x.missing) { h += `<tr><td>${x.name}</td><td class="na" colspan="${cols.length+3}">データ未取得</td></tr>`; continue; }
    const m = x.m;
    const pt = k => unit(x) === "pt" && ["chgPct","r1w","r1m","ytd","r1y","fromHi"].includes(k) ? "pt" : "%";
    h += `<tr><td>${x.name}${x.proxy ? "※" : ""}</td><td>${nf(m.close, dec(x))}</td><td>${m.date.slice(5).replace("-","/")}</td>`
       + cols.map(([_,k]) => `<td class="${cls(m[k])}">${sgn(m[k],2,pt(k))}</td>`).join("")
       + `<td>${nf(m.lo52, dec(x))} – ${nf(m.hi52, dec(x))}</td></tr>`;
  }
  document.getElementById("perf").innerHTML = h + "</tbody>";
}

// ---------- range control
function renderRange() {
  const seg = document.getElementById("range");
  seg.innerHTML = RANGES.map(([l,v]) => `<button type="button" data-v="${v}" aria-pressed="${v===state.range}">${l}</button>`).join("");
  seg.onclick = e => { const v = e.target.dataset.v; if (v == null) return; state.range = +v; save(); renderRange(); renderMain(); renderCmp(); };
}

// ---------- chart core
function lowerBound(a, v) { let lo = 0, hi = a.length; while (lo < hi) { const m = (lo+hi) >> 1; if (a[m] < v) lo = m+1; else hi = m; } return lo; }
function niceTicks(lo, hi, n=5) {
  const span = hi - lo || Math.abs(hi) || 1, step0 = span / n, p = Math.pow(10, Math.floor(Math.log10(step0)));
  const step = [1,2,2.5,5,10].map(s => s*p).find(s => span/s <= n) || 10*p;
  const out = []; for (let v = Math.ceil(lo/step)*step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}
function logTicks(lo, hi) {
  const out = [];
  for (let e = Math.floor(Math.log10(lo)); e <= Math.ceil(Math.log10(hi)); e++)
    for (const m of [1,2,5]) { const v = m * Math.pow(10,e); if (v >= lo && v <= hi) out.push(v); }
  return out.length >= 2 ? out : niceTicks(lo, hi);
}
function timeTicks(t0, t1, W) {
  const spanDays = t1 - t0, maxN = Math.max(2, Math.floor(W / 80)), out = [];
  const d0 = toDate(t0);
  if (spanDays <= 400) {
    const stepM = [1,2,3,6].find(s => spanDays/30/s <= maxN) || 6;
    let y = d0.getUTCFullYear(), mo = d0.getUTCMonth() + 1;
    while (true) { if (mo > 11) { y++; mo -= 12; } const t = Date.UTC(y, mo, 1)/DAY; if (t > t1) break;
      if (mo % stepM === 0) out.push([t, mo === 0 ? `${y}年` : `${mo+1}月`]); mo++; }
  } else {
    const years = spanDays/365, stepY = [1,2,5,10,20,25,50].find(s => years/s <= maxN) || 50;
    for (let y = d0.getUTCFullYear()+1; ; y++) { const t = Date.UTC(y,0,1)/DAY; if (t > t1) break; if (y % stepY === 0) out.push([t, `${y}`]); }
  }
  return out;
}
function movingAvg(c, n) { const o = new Array(c.length).fill(null); let s = 0; for (let i = 0; i < c.length; i++) { s += c[i]; if (i >= n) s -= c[i-n]; if (i >= n-1) o[i] = s/n; } return o; }

/* series: [{name, color, d:[days], v:[vals], width, dash}]  opts: {log, fmt} */
function lineChart(el, series, opts) {
  const W = el.clientWidth || 600, H = opts.h || Math.max(240, Math.min(380, W * 0.5));
  const pad = {l: 8, r: 64, t: 12, b: 26};
  const all = series.flatMap(s => s.v.filter(v => v != null));
  if (!all.length) { el.innerHTML = `<div class="na" style="padding:40px 0;text-align:center">この期間のデータがありません</div>`; return; }
  const t0 = opts.t0 != null ? opts.t0 : Math.min(...series.map(s => s.d[0])), t1 = opts.t1 != null ? opts.t1 : Math.max(...series.map(s => s.d[s.d.length-1]));
  let lo = Math.min(...all, ...(opts.incl || [])), hi = Math.max(...all, ...(opts.incl || []));
  const useLog = opts.log && lo > 0;
  const f = useLog ? Math.log : (v => v);
  let flo = f(lo), fhi = f(hi); const m = (fhi - flo) * 0.06 || 1; flo -= m; fhi += m;
  const X = t => pad.l + (t - t0) / Math.max(1, t1 - t0) * (W - pad.l - pad.r);
  const Y = v => pad.t + (1 - (f(v) - flo) / (fhi - flo)) * (H - pad.t - pad.b);
  const yt = useLog ? logTicks(Math.exp(flo), Math.exp(fhi)) : niceTicks(flo, fhi);
  let s = `<svg viewBox="0 0 ${W} ${H}" height="${H}" role="img">`;
  const yT = pad.t, yB = H - pad.b, cy = v => Math.max(yT, Math.min(yB, Y(v)));
  for (const b of (opts.bands || [])) { const a = cy(b.hi == null ? Infinity : b.hi), z = cy(b.lo == null ? -Infinity : b.lo);
    if (z - a > 0.5) s += `<rect x="${pad.l}" y="${a}" width="${W-pad.l-pad.r}" height="${z-a}" fill="${b.color}" opacity="${b.op}"/>`; }
  for (const v of yt) s += `<line x1="${pad.l}" x2="${W-pad.r}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--grid)" stroke-width="1"/><text x="${W-pad.r+8}" y="${Y(v)+4}">${opts.fmt(v)}</text>`;
  for (const [t,l] of timeTicks(t0, t1, W - pad.l - pad.r)) s += `<text x="${X(t)}" y="${H-6}" text-anchor="middle">${l}</text>`;
  s += `<line x1="${pad.l}" x2="${W-pad.r}" y1="${H-pad.b}" y2="${H-pad.b}" stroke="var(--axis)"/>`;
  const maxPts = Math.max(200, Math.floor((W - pad.l - pad.r) * 2));
  for (const sr of series) {
    const step = Math.max(1, Math.floor(sr.d.length / maxPts));
    let p = "", pen = false;
    for (let i = 0; i < sr.d.length; i += step) {
      const v = sr.v[i]; if (v == null) { pen = false; continue; }
      p += (pen ? "L" : "M") + X(sr.d[i]).toFixed(1) + "," + Y(v).toFixed(1); pen = true;
    }
    const li = sr.d.length - 1; if (sr.v[li] != null) p += "L" + X(sr.d[li]).toFixed(1) + "," + Y(sr.v[li]).toFixed(1);
    s += `<path d="${p}" fill="none" stroke="${sr.color}" stroke-width="${sr.width||2}" ${sr.dash?`stroke-dasharray="${sr.dash}"`:""} stroke-linejoin="round" stroke-linecap="round"/>`;
  }
  s += `<g class="hover" style="display:none"><line class="cx" y1="${pad.t}" y2="${H-pad.b}" stroke="var(--axis)" stroke-width="1"/>`
     + series.map((sr,i) => `<circle class="hd${i}" r="4" fill="${sr.color}" stroke="var(--surface)" stroke-width="2"/>`).join("") + `</g>`;
  s += `<rect x="${pad.l}" y="0" width="${W-pad.l-pad.r}" height="${H}" fill="transparent" class="hit"/></svg><div class="tip"></div>`;
  el.innerHTML = s;

  const svg = el.querySelector("svg"), g = svg.querySelector(".hover"), tip = el.querySelector(".tip");
  const move = ev => {
    const r = svg.getBoundingClientRect(), px = (ev.clientX - r.left) * (W / r.width);
    const t = t0 + (px - pad.l) / (W - pad.l - pad.r) * (t1 - t0);
    let rows = "", tx = null;
    series.forEach((sr, i) => {
      let k = lowerBound(sr.d, t); if (k >= sr.d.length) k = sr.d.length-1; if (k > 0 && t - sr.d[k-1] < sr.d[k] - t) k--;
      const dot = g.querySelector(".hd"+i), v = sr.v[k];
      if (v == null || Math.abs(sr.d[k] - t) > (sr.gap || 10) * Math.max(1, (t1 - t0) / 3650)) { dot.style.display = "none"; return; }
      dot.style.display = ""; dot.setAttribute("cx", X(sr.d[k])); dot.setAttribute("cy", Y(v));
      if (tx == null) tx = sr.d[k];
      if (!sr.noTip) rows += `<div class="r"><span><span class="dot" style="background:${sr.color}"></span> ${sr.name}</span><b>${opts.fmt(v, true)}</b></div>`;
    });
    if (tx == null) return;
    g.style.display = ""; g.querySelector(".cx").setAttribute("x1", X(tx)); g.querySelector(".cx").setAttribute("x2", X(tx));
    tip.innerHTML = `<div class="d">${fmtD(tx)}</div>${rows}`; tip.style.display = "block";
    const sx = X(tx) * (r.width / W), tw = tip.offsetWidth;
    tip.style.left = Math.max(0, Math.min(r.width - tw, sx + 12 + tw > r.width ? sx - tw - 12 : sx + 12)) + "px";
    tip.style.top = "8px";
  };
  const hit = svg.querySelector(".hit");
  hit.addEventListener("pointermove", move);
  hit.addEventListener("pointerdown", move);
  hit.addEventListener("pointerleave", () => { g.style.display = "none"; tip.style.display = "none"; });
}

function sliceRange(x) {
  const end = x.d[x.d.length-1];
  const i0 = state.range ? lowerBound(x.d, end - state.range) : 0;
  return { d: x.d.slice(i0), c: x.c.slice(i0), i0 };
}

// ---------- main chart
function renderMain() {
  const x = byKey[state.key], el = document.getElementById("main");
  if (!x || x.missing) { el.innerHTML = ""; return; }
  document.getElementById("mainTitle").textContent = `${x.name} の推移`;
  const r = sliceRange(x);
  const series = [], leg = [];
  const start = state.range ? x.d[x.d.length-1] - state.range : -Infinity;
  if (x.ld) {   // 日足より前は世界統計データの月末値・年末値（点線）
    const j0 = lowerBound(x.ld, start), ld = x.ld.slice(j0), lc = x.lc.slice(j0);
    if (ld.length) {
      // 日足の最初の点までつなぐ
      series.push({ name: `${x.name}（月末・年末値）`, color: "var(--s1)", d: ld.concat(r.d.slice(0,1)), v: lc.concat(r.c.slice(0,1)), dash: "4 3", width: 1.5, gap: 400 });
      leg.push([`${x.name}（日足${x.proxy ? "：1306.T換算" : ""}）`, "--s1"], [`${x.name}（${fmtD(ld[0]).slice(0,4)}年〜：月末値・年末値／世界統計データ）`, "--s1", true]);
    }
  }
  series.push({ name: x.monthly ? `${x.name}（月末値）` : x.name, color: "var(--s1)", d: r.d, v: r.c, gap: x.monthly ? 40 : 10 });
  if (x.proxy && !x.ld) leg.push([`${x.name}（日足：1306.T換算）`, "--s1"]);
  if (x.monthly) leg.push([`${x.name}：月末値・年末値（世界統計データ）。日足が取得できていないため前日比・移動平均は表示しません`, "--s1"]);
  if (state.ma && !x.monthly) {
    const ma25 = movingAvg(x.c, 25).slice(r.i0), ma200 = movingAvg(x.c, 200).slice(r.i0);
    series.push({ name: "25日線", color: "var(--s2)", d: r.d, v: ma25, width: 1.5 });
    series.push({ name: "200日線", color: "var(--s3)", d: r.d, v: ma200, width: 1.5 });
    if (!leg.length) leg.push([x.name,"--s1"]);
    leg.push(["25日移動平均","--s2"],["200日移動平均","--s3"]);
  }
  lineChart(el, series, { log: state.log, fmt: (v, full) => full ? nf(v) : compact(v) });
  mainSpan = [Math.min(...series.map(q => q.d[0])), Math.max(...series.map(q => q.d[q.d.length-1]))];
  renderAD();
  document.getElementById("mainLegend").innerHTML = leg.map(([n,c,dash]) =>
    `<span><i style="${dash ? `background:repeating-linear-gradient(90deg,var(${c}) 0 4px,transparent 4px 7px)` : `background:var(${c})`}"></i>${n}</span>`).join("");
}
// ---------- 騰落レシオ（推移の下。期間・横軸は上のグラフに合わせる）
const AD = __AD__;
const AD_TABS = [["all","東証 全市場"],["prime","東証プライム"],["dow","ダウ平均"],["sp500","S&P500"],["nasdaq100","NASDAQ100"]];
// 米国の指数→騰落レシオを出す構成銘柄（NASDAQ総合・SOX は NASDAQ100、ラッセル2000 は S&P500 で代用）
const AD_US = { dow: "dow", sp500: "sp500", nasdaq100: "nasdaq100", vix: "sp500", nasdaq: "nasdaq100", sox: "nasdaq100", russell2000: "sp500" };
let adKey = "all", adJp = "all", adFor = null, mainSpan = null;
try { const k = localStorage.getItem("idx-ad"); if (k && AD[k] && !AD_US[k]) adJp = adKey = k; } catch(e) {}
const AD_LV = [[130,"過熱","hot","130%以上。買われすぎで、相場全体の天井圏のサインとされる水準です。"],
  [120,"過熱気味","warm","120〜130%。値上がり銘柄が多く、相場全体が過熱し始めています。"],
  [80,"中立","","80〜120%。値上がりと値下がりが釣り合っています。"],
  [70,"売られすぎ","cool","70〜80%。値下がり銘柄が多く、全体に売られすぎ気味です。"],
  [-Infinity,"底値圏","cold","70%以下。売りが出尽くしやすく、相場全体の底打ちのサインとされる水準です。"]];
const adLv = v => AD_LV.find(l => v >= l[0]);
function renderAD() {
  // 金利・為替・商品を選んでいるときは騰落レシオを出さない（株式市場の指標のため）
  const sel = byKey[state.key];
  if (sel && sel.region === "金利・為替・商品") { document.getElementById("adBox").style.display = "none"; return; }
  // 上で選んだ指数に合わせる（米国の指数→その指数の構成銘柄、日本の指数→東証）。ボタンで手動でも切り替えられる
  if (adFor !== state.key) { adFor = state.key; const u = AD_US[state.key]; adKey = u && AD[u] ? u : adJp; }
  const box = document.getElementById("adBox"), A = AD[adKey] || AD.all || AD.prime;
  if (!A || !A.d.length) { box.style.display = "none"; return; }
  box.style.display = "";
  const mk = document.getElementById("adMk");
  mk.innerHTML = AD_TABS.filter(([k]) => AD[k]).map(([k,l]) => `<button type="button" data-k="${k}" aria-pressed="${k===adKey}">${l}</button>`).join("");
  mk.onclick = e => { const k = e.target.dataset.k; if (!k) return; adKey = k; if (!AD_US[k]) { adJp = k; try { localStorage.setItem("idx-ad", k); } catch(e) {} } renderAD(); };
  const n = A.d.length, v = A.r25[n-1], lv = adLv(v);
  document.getElementById("adVal").textContent = nf(v,1) + "%";
  const pill = document.getElementById("adPill"); pill.textContent = lv[1]; pill.className = "adp " + lv[2];
  document.getElementById("adSub").textContent = `${fmtD(A.d[n-1])}　10日 ${nf(A.r10[n-1],1)}%　値上がり ${A.up[n-1].toLocaleString()}・値下がり ${A.dn[n-1].toLocaleString()}`;
  const end = mainSpan ? mainSpan[1] : A.d[n-1], start = mainSpan ? mainSpan[0] : (state.range ? end - state.range : A.d[0]);
  const i0 = lowerBound(A.d, start), d = A.d.slice(i0), el = document.getElementById("adChart");
  lineChart(el, [{ name: "10日", color: "var(--muted)", d, v: A.r10.slice(i0), width: 1.2 }, { name: "25日", color: "var(--ink)", d, v: A.r25.slice(i0), width: 2.2 }],
    { h: Math.max(170, Math.min(230, (el.clientWidth || 600) * 0.3)), t0: start, t1: Math.max(end, d.length ? d[d.length-1] : end), incl: [65, 135],
      bands: [{ lo: 120, color: "var(--up)", op: .13 }, { lo: 130, color: "var(--up)", op: .13 }, { hi: 80, color: "var(--dn)", op: .13 }, { hi: 70, color: "var(--dn)", op: .13 }],
      fmt: (x, full) => full ? nf(x,1) + "%" : nf(x,0) });
  const who = AD_US[adKey] ? `${(AD_TABS.find(t => t[0] === adKey) || [,""])[1]}のいまの構成${A.n || ""}銘柄で` : `東証${adKey === "prime" ? "プライム" : "の全市場"}の銘柄で`;
  const how = AD_US[adKey] ? "株価は Yahoo Finance（調整後終値の前日比）。いまの構成銘柄でさかのぼって数えるため、古い期間ほど目安です（入れ替えで外れた銘柄は入りません）。"
    : "手元の株価（調整後終値の前日比）から計算。いま上場している銘柄だけで数えるため、古い期間ほど目安です。";
  document.getElementById("adNote").innerHTML = `<b style="color:var(--ink)">${lv[1]}</b>：${lv[3]}　／　${who}、直近25営業日の「値上がり銘柄数の合計 ÷ 値下がり銘柄数の合計 × 100」。${how}${AD_US[adKey] && A.n <= 30 ? "　※30銘柄と少ないため、振れが大きくなります。" : ""}`;
}
const compact = v => Math.abs(v) >= 10000 ? (v/10000).toLocaleString("ja-JP",{maximumFractionDigits:2}) + "万" : v.toLocaleString("ja-JP",{maximumFractionDigits:2});

// ---------- comparison chart
function renderCmp() {
  const el = document.getElementById("cmp");
  if (!PRICE.length) { el.innerHTML = ""; return; }
  const full = x => x.ld ? { d: x.ld.concat(x.d), c: x.lc.concat(x.c) } : { d: x.d, c: x.c };
  const end = Math.max(...PRICE.map(x => x.d[x.d.length-1]));
  let start;
  if (state.range) start = end - state.range;
  else start = Math.max(...PRICE.map(x => full(x).d[0]));   // 全期間: 全指数がそろう最初の日から
  const series = PRICE.map(x => {
    const F = full(x), i0 = lowerBound(F.d, start), d = F.d.slice(i0), c = F.c.slice(i0);
    const base = c[0];
    return { name: x.name + (x.monthly ? "（月末値）" : ""), color: `var(${cmpColor[x.key]})`, d, v: c.map(v => v / base * 100), gap: (x.monthly || x.ld) ? 400 : 10 };
  }).filter(s => s.d.length > 1);
  lineChart(el, series, { log: state.range === 0 || state.range >= 3652, fmt: (v, full) => full ? nf(v,1) : nf(v,0) });
  document.getElementById("cmpLegend").innerHTML = series.map(sr => {
    const last = sr.v[sr.v.length-1];
    return `<span><i style="background:${sr.color}"></i>${sr.name} <b style="color:var(--ink)">${nf(last,1)}</b></span>`;
  }).join("") + (state.range === 0 ? `<span class="na">全期間は ${fmtD(start)} 起点（全指数がそろう日）・対数目盛</span>` : "");
}

// ---------- init
document.getElementById("log").checked = state.log;
document.getElementById("ma").checked = state.ma;
document.getElementById("log").onchange = e => { state.log = e.target.checked; save(); renderMain(); };
document.getElementById("ma").onchange = e => { state.ma = e.target.checked; save(); renderMain(); };
document.getElementById("theme").addEventListener("click", () => { const d = document.documentElement;
  const cur = d.getAttribute("data-theme") || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  const n = cur === "dark" ? "light" : "dark"; d.setAttribute("data-theme", n); try { localStorage.setItem("fdb-theme", n); } catch(e) {}
  renderCards(); renderMain(); renderCmp(); });
if (DATA.some(x => x.proxy)) document.getElementById("proxyNote").textContent =
  "　※TOPIXの日足は、TOPIX連動ETF（1306.T）の終値に、世界統計データのTOPIX月末値との比率を掛けて換算した推定値です（月中は分配金落ち等で最大2%程度ずれることがあります）。";
renderCards(); renderTable(); renderRange(); renderMain(); renderCmp();
let rt; addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => { renderMain(); renderCmp(); }, 150); });
</script>
</body>
</html>
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--outdir", default=str(Path.home() / "market_data"), help="CSVのあるフォルダ")
    ap.add_argument("--html", help="出力するHTMLのパス（省略時 <outdir>/dashboard.html）")
    ap.add_argument("--home", help="「‹ トップ」リンクの行き先（例: ./index.html）")
    args = ap.parse_args()
    out = build(Path(args.outdir).expanduser(), Path(args.html).expanduser() if args.html else None, args.home)
    print(f"ダッシュボードを出力しました: {out}")


if __name__ == "__main__":
    main()
