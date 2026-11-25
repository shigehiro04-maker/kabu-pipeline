#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ヒートマップ（data/charts/heatmap.html）を作る。

  市場   : プライム / スタンダード / グロース / 日経225 / TOPIX / 全市場（タブで切替）
  区分け : 東証33業種 → 銘柄（業種の枠をタップすると拡大）
  色     : 騰落率（1日・1週・1ヶ月・3ヶ月・年初来・1年 を切替）  上昇＝赤／下落＝緑
  大きさ : 時価総額 / 売買代金（当日） / 売買代金（20日平均） を切替

入力（すべて既存の東証株分析のデータ。通信なし・標準ライブラリのみ）
  tickers/tse_tickers.csv            対象銘柄（コード・名前・市場）
  tickers/sectors.csv                33業種
  fundamentals/fundamentals_latest.csv  時価総額（最新終値で引き直す）
  fundamentals/nikkei225.csv         日経225採用銘柄
  data/prices/<コード>.csv           株価（末尾300行だけ読む）
出力
  data/charts/heatmap.html           ページ本体
  data/charts/heatmap_summary.json   トップ画面のカード用の要約

run_daily.sh の 3b-4 から呼ばれる（約10〜30秒）。手動なら:
  ~/株分析/.venv/bin/python ~/株分析/ヒートマップ/make_heatmap.py
"""
import base64, csv, datetime, json, math, os, sys, unicodedata
from array import array
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SITE = BASE / "data" / "charts"
PRICES = BASE / "data" / "prices"
MARKETS = ["プライム", "スタンダード", "グロース"]
TAIL = 520                     # 時間スライダー（約1年）＋3ヶ月の遡り＋前年末に足りる行数
HIST_DAYS = 250               # スライダーで動かせる営業日数（約1年）
HIST_LOOK = 63                # 期間騰落率（最長3ヶ月）の計算に使う遡り日数
PERIODS = [("d1", 1), ("w1", 5), ("m1", 21), ("m3", 63), ("y1", 245)]


def read_csv(p):
    try:
        with open(p, encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        return []


def num(s):
    try:
        v = float(s)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def tail_rows(path, n=TAIL):
    """CSVの末尾 n 行だけを読む（全期間を読むと遅いため）"""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            block = min(size, 72 * n + 4096)
            f.seek(size - block)
            data = f.read().decode("utf-8", "ignore")
    except OSError:
        return []
    lines = data.splitlines()
    if block < size:
        lines = lines[1:]                       # 途中で切れた先頭行を捨てる
    out = []
    for ln in lines[-n:]:
        p = ln.split(",")
        if len(p) < 6 or not p[0][:1].isdigit():
            continue
        c, v = num(p[4]), num(p[5])
        if c is None or c <= 0:
            continue
        out.append((p[0], c, v or 0.0))
    return out


def pct(a, b):
    return None if not a or not b else round((a / b - 1) * 100, 2)


def load():
    tick = [r for r in read_csv(BASE / "tickers" / "tse_tickers.csv") if r.get("market") in MARKETS]
    secrows = read_csv(BASE / "tickers" / "sectors.csv")
    sec = {r["code"]: r.get("sector33") or "" for r in secrows}
    # TOPIX の規模区分（JPXの銘柄一覧の「規模区分」）。区分があれば TOPIX 構成銘柄
    TPX = {"TOPIX Core30": 1, "TOPIX Large70": 2, "TOPIX Mid400": 3, "TOPIX Small 1": 4, "TOPIX Small 2": 5}
    tpx = {r["code"]: TPX.get((r.get("size") or "").strip(), 0) for r in secrows}
    fund = {r["コード"]: r for r in read_csv(BASE / "fundamentals" / "fundamentals_latest.csv")}
    n225 = {r["コード"]: num(r.get("日経225ウエート(%)")) for r in read_csv(BASE / "fundamentals" / "nikkei225.csv")
            if str(r.get("日経225採用", "")).strip() in ("1", "1.0", "True")}

    rows, asof_all = [], []
    for t in tick:
        code = t["code"]
        px = tail_rows(PRICES / f"{code}.csv")
        if len(px) < 2:
            continue
        rows.append((t, px))
        asof_all.append(px[-1][0])
    if not rows:
        sys.exit("株価データが見つかりません")
    asof = max(asof_all)
    asof_d = datetime.date.fromisoformat(asof)
    ystart = f"{asof_d.year}-01-01"
    stale = (asof_d - datetime.timedelta(days=10)).isoformat()

    sectors, stocks, pxs = [], [], []
    sidx = {}
    for t, px in rows:
        code = t["code"]
        last_d, close, vol = px[-1]
        if last_d < stale:                      # 売買停止・上場廃止予定などで止まっている銘柄は除く
            continue
        f = fund.get(code, {})
        sc = sec.get(code) or f.get("業種") or "その他"
        # 時価総額：決算データの値を最新終値で引き直す（無ければ株数×終値）
        mc = num(f.get("時価総額"))
        fpx = num(f.get("株価"))
        if mc and fpx:
            mc = mc * close / fpx
        elif num(f.get("発行済株式数")):
            mc = num(f.get("発行済株式数")) * close
        else:
            mc = None
        tv1 = close * vol if last_d == asof else 0.0
        tv20 = sum(c * v for _, c, v in px[-20:]) / min(20, len(px))
        rets = []
        for _, k in PERIODS:
            rets.append(pct(close, px[-1 - k][1]) if len(px) > k else None)
        prev = [c for d, c, _ in px if d < ystart]
        ytd = pct(close, prev[-1]) if prev else None
        if last_d != asof:                      # 当日に約定が無い銘柄の1日騰落は0扱いにしない
            rets[0] = None
        if sc not in sidx:
            sidx[sc] = len(sectors)
            sectors.append(sc)
        stocks.append([
            code, unicodedata.normalize("NFKC", t.get("name", "")), MARKETS.index(t["market"]), sidx[sc],
            1 if code in n225 else 0,
            round(mc / 1e8, 1) if mc else 0,           # 億円
            round(tv1 / 1e8, 2), round(tv20 / 1e8, 2),  # 億円
            rets[0], rets[1], rets[2], rets[3], ytd, rets[4], close,
            tpx.get(code, 0),                          # 15: TOPIX規模区分（0=非構成）
        ])
        pxs.append(px)
    return asof, sectors, stocks, len(n225), pxs


def b64(arr):
    return base64.b64encode(arr.tobytes()).decode("ascii")


def build_hist(stocks, pxs):
    """時間スライダー用の過去データ（heatmap_hist.js）。
    日付×銘柄の並びで、終値は「最新終値に対する対数比×2000」の int16、売買代金は log10 を1/32刻みにした 1バイト。
    期間騰落率・時価総額・売買代金はブラウザ側でこれから計算する（ページ本体を軽くするため別ファイル）"""
    cnt = {}
    for px in pxs:
        for d, _, _ in px[-(HIST_DAYS + HIST_LOOK + 40):]:
            cnt[d] = cnt.get(d, 0) + 1
    need = max(50, len(pxs) // 5)                 # 一部の銘柄だけにある日付（祝日のずれ等）は使わない
    dates = sorted(d for d, c in cnt.items() if c >= need)[-(HIST_DAYS + HIST_LOOK):]
    if len(dates) < HIST_LOOK + 2:
        return None
    di = {d: i for i, d in enumerate(dates)}
    N, T = len(stocks), len(dates)
    years = sorted({int(d[:4]) for d in dates[HIST_LOOK:]})
    C = array("h", [-32768]) * (N * T)
    V = array("B", [0]) * (N * T)
    YE = {y: array("h", [-32768]) * N for y in years}
    for i, (s, px) in enumerate(zip(stocks, pxs)):
        last = s[14]
        bymap = {d: (c, v) for d, c, v in px}
        prev = None
        for d in dates:
            if d in bymap:
                c, v = bymap[d]
                prev = c
                q = int(round(math.log(c / last) * 2000))
                C[di[d] * N + i] = max(-32767, min(32767, q))
                tv = c * v
                if tv > 0:
                    V[di[d] * N + i] = max(1, min(255, int(round((math.log10(tv) - 5) * 32))))
            elif prev is not None and d > px[0][0]:   # 取引の無い日は前日の終値のまま（売買代金0）
                C[di[d] * N + i] = C[(di[d] - 1) * N + i] if di[d] else -32768
        for y in years:                                # 年初来の基準＝前年最終営業日の終値
            pv = [c for d, c, _ in px if d < f"{y}-01-01"]
            if pv:
                YE[y][i] = max(-32767, min(32767, int(round(math.log(pv[-1] / last) * 2000))))
    return {"n": N, "dates": dates, "start": HIST_LOOK,
            "c": b64(C), "v": b64(V), "ye": {str(y): b64(a) for y, a in YE.items()}}


def summary(asof, stocks, sectors=None):
    """トップ画面のカード用：市場ごとの時価総額加重の前日比と値上がり銘柄数"""
    out = {"asof": asof, "markets": {}}
    groups = {"プライム": lambda s: s[2] == 0, "スタンダード": lambda s: s[2] == 1,
              "グロース": lambda s: s[2] == 2, "日経225": lambda s: s[4] == 1, "TOPIX": lambda s: s[15] > 0}
    for name, fn in groups.items():
        xs = [s for s in stocks if fn(s) and s[8] is not None]
        w = sum(s[5] for s in xs)
        avg = sum(s[5] * s[8] for s in xs) / w if w else None
        up = sum(1 for s in xs if s[8] > 0)
        dn = sum(1 for s in xs if s[8] < 0)
        out["markets"][name] = {"chg": None if avg is None else round(avg, 2), "up": up, "down": dn, "n": len(xs)}
    # トップ画面の「業種別の騰落率」用：プライムの33業種ごとの時価総額加重の前日比（[業種, 騰落率%, 銘柄数]、大きい順）
    sec = []
    for i, nm in enumerate(sectors or []):
        xs = [s for s in stocks if s[2] == 0 and s[3] == i and s[8] is not None and s[5]]
        w = sum(s[5] for s in xs)
        if w:
            sec.append([nm, round(sum(s[5] * s[8] for s in xs) / w, 2), len(xs)])
    out["sectors_prime"] = sorted(sec, key=lambda x: -x[1])
    return out


def main():
    asof, sectors, stocks, n225, pxs = load()
    S = summary(asof, stocks, sectors)
    H = build_hist(stocks, pxs)
    data = {"asof": asof, "sectors": sectors, "stocks": stocks,
            "hdates": H["dates"] if H else [], "hstart": H["start"] if H else 0}
    page = (TMPL.replace("__DATA__", json.dumps(data, ensure_ascii=False, separators=(",", ":")))
            .replace("__ASOF__", asof)
            .replace("__BUILT__", datetime.datetime.now().strftime("%Y-%m-%d %H:%M")))
    SITE.mkdir(parents=True, exist_ok=True)
    (SITE / "heatmap.html").write_text(page, encoding="utf-8")
    if H:   # 過去データは別ファイル（スライダーを触ったときだけ読み込む）
        hj = {"n": H["n"], "c": H["c"], "v": H["v"], "ye": H["ye"]}
        (SITE / "heatmap_hist.js").write_text("window.HM_HIST=" + json.dumps(hj, separators=(",", ":")) + ";\n", encoding="utf-8")
    (SITE / "heatmap_summary.json").write_text(json.dumps(S, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"ヒートマップを作成: {SITE/'heatmap.html'}（{len(stocks)}銘柄・{len(sectors)}業種・日経225 {n225}銘柄・株価 {asof}）")


TMPL = r"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ヒートマップ</title>
<script>(function(){var m=/[?&#]theme=(dark|light)/.exec(location.search+location.hash),t=m&&m[1];
if(!t){try{t=localStorage.getItem('fdb-theme')}catch(e){}}if(t)document.documentElement.setAttribute('data-theme',t);})();</script>
<style>
@import url("https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap");
:root{--bg:#f9f9f7;--card:#fcfcfb;--fg:#0b0b0b;--fg2:#52514e;--mut:#898781;--line:#e1e0d9;
--hover:rgba(11,11,11,.04);--acc:#2a78d6;--up:#c93a3a;--dn:#2E7D6B;--gap:#f9f9f7;--sech:#3d3d3a;color-scheme:light}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){
--bg:#0d0d0d;--card:#1a1a19;--fg:#fff;--fg2:#c3c2b7;--mut:#898781;--line:#2c2c2a;
--hover:rgba(255,255,255,.05);--acc:#3987e5;--up:#e66767;--dn:#3FA58C;--gap:#0d0d0d;--sech:#262624;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#0d0d0d;--card:#1a1a19;--fg:#fff;--fg2:#c3c2b7;--mut:#898781;--line:#2c2c2a;
--hover:rgba(255,255,255,.05);--acc:#3987e5;--up:#e66767;--dn:#3FA58C;--gap:#0d0d0d;--sech:#262624;color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,-apple-system,"Hiragino Sans","Segoe UI",sans-serif;font-variant-numeric:tabular-nums}
.wrap{max-width:1400px;margin:0 auto;padding:18px 16px 48px}
header{display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap}
h1{font-size:20px;margin:0}h1 a{text-decoration:none;color:inherit;margin-right:8px}
.sub{color:var(--fg2);font-size:12.5px}
.btn{border:1px solid var(--line);background:transparent;color:var(--fg);border-radius:8px;padding:5px 11px;font:inherit;font-size:12.5px;cursor:pointer}
.ctl{display:flex;flex-wrap:wrap;gap:8px 18px;margin:14px 0 8px;align-items:center}
.ctl label{font-size:11.5px;color:var(--mut);margin-right:6px}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:9px;overflow:hidden;background:var(--card)}
.seg button{border:0;background:transparent;color:var(--fg2);font:inherit;font-size:12.5px;padding:6px 11px;cursor:pointer;border-left:1px solid var(--line);white-space:nowrap}
.seg button:first-child{border-left:0}
.seg button.on{background:var(--acc);color:#fff;font-weight:600}
.tabs{display:flex;gap:4px;margin-top:14px;border-bottom:1px solid var(--line);overflow-x:auto}
.tabs button{border:0;background:transparent;color:var(--fg2);font:inherit;font-size:14px;padding:8px 14px;cursor:pointer;border-bottom:3px solid transparent;margin-bottom:-1px;white-space:nowrap}
.tabs button.on{color:var(--fg);font-weight:700;border-bottom-color:var(--acc)}
.tabs small{color:var(--mut);font-weight:400;font-size:11px;margin-left:4px}
.tl{display:flex;align-items:center;gap:6px;margin:4px 0 2px;flex-wrap:wrap}
.tl button{border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:8px;min-width:34px;height:32px;font:inherit;font-size:13px;cursor:pointer;padding:0 9px}
.tl button.pl{background:var(--acc);border-color:var(--acc);color:#fff;font-weight:700;min-width:64px}
.tl button:disabled{opacity:.4;cursor:default}
.tl input[type=range]{flex:1;min-width:160px;accent-color:var(--acc);height:28px}
.tl select{border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:8px;height:32px;font:inherit;font-size:12.5px;padding:0 6px}
.tl .lab{font-weight:700;font-size:14px;min-width:150px}.tl .lab small{font-weight:400;color:var(--mut);font-size:11.5px;margin-left:4px}
.tlx{display:flex;justify-content:space-between;font-size:11px;color:var(--mut);margin:-2px 0 4px;padding:0 0 0 0}
.past .stats{background:color-mix(in srgb,var(--acc) 8%,transparent);border-radius:8px;padding:4px 8px}
.seg button.na{opacity:.35}
@media(max-width:640px){.tl .lab{min-width:0;flex-basis:100%;order:-1}.tl input[type=range]{min-width:0}}
.stats{display:flex;flex-wrap:wrap;gap:4px 18px;font-size:12.5px;color:var(--fg2);margin:10px 0 8px}
.stats b{color:var(--fg);font-weight:600}.u{color:var(--up)}.d{color:var(--dn)}
.crumb{font-size:13px;margin:4px 0 6px;min-height:20px}
.crumb a{color:var(--acc);cursor:pointer;text-decoration:none}
#map{position:relative;width:100%;background:var(--gap);border-radius:10px;overflow:hidden;user-select:none;-webkit-user-select:none;touch-action:pan-y}
#map.zoomed{touch-action:none;cursor:grab}#map.drag{cursor:grabbing}#map.drag .t{cursor:grabbing}
#mapIn{position:absolute;left:0;top:0;transform-origin:0 0}
.mapbox{position:relative}
.zc{position:absolute;right:8px;bottom:8px;z-index:6;display:flex;gap:5px;align-items:center}
.zc button{width:36px;height:36px;border-radius:10px;border:1px solid rgba(255,255,255,.28);background:rgba(18,18,18,.74);color:#fff;font:600 19px/1 system-ui,sans-serif;cursor:pointer;-webkit-backdrop-filter:blur(4px);backdrop-filter:blur(4px);-webkit-tap-highlight-color:transparent}
.zc button:disabled{opacity:.35;cursor:default}
.zc button.rs{width:auto;padding:0 11px;font-size:12.5px;font-weight:600}
.zc .zl{font-size:12px;color:#fff;background:rgba(18,18,18,.74);border-radius:8px;padding:4px 7px}
.mini{position:absolute;left:8px;bottom:8px;z-index:6;border:1px solid rgba(255,255,255,.5);background:rgba(18,18,18,.35);border-radius:4px;pointer-events:none}
.mini i{position:absolute;border:1.5px solid #fff;background:rgba(255,255,255,.18);border-radius:2px}
.sc{position:absolute;overflow:hidden}
.sh{position:absolute;z-index:3;height:16px;background:var(--sech);color:#eee;font-size:11px;line-height:16px;padding:0 4px;
 white-space:nowrap;overflow:hidden;text-overflow:ellipsis;cursor:zoom-in}
.sh b{font-weight:600}
.t{position:absolute;overflow:hidden;color:#fff;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;
 line-height:1.15;cursor:pointer;outline:1px solid var(--gap);outline-offset:-1px;text-shadow:0 1px 1px rgba(0,0,0,.35)}
.t:hover{outline:2px solid #fff;z-index:2}
.t .n{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:96%}
.t .p{opacity:.95}
.legend{display:flex;align-items:center;gap:6px;font-size:11.5px;color:var(--mut);margin:8px 0 0;flex-wrap:wrap}
.legend .bar{display:flex;border-radius:4px;overflow:hidden}
.legend .bar span{width:34px;height:16px;display:grid;place-items:center;color:#fff;font-size:10.5px}
#tip{position:fixed;z-index:20;pointer-events:none;background:var(--card);color:var(--fg);border:1px solid var(--line);border-radius:10px;
 padding:9px 11px;font-size:12.5px;box-shadow:0 6px 24px rgba(0,0,0,.18);min-width:200px;display:none}
#tip h3{margin:0 0 4px;font-size:13.5px}#tip table{border-collapse:collapse;width:100%}
#tip td{padding:1px 0}#tip td:last-child{text-align:right;font-weight:600}
#tip .cur td{background:var(--hover)}
#panel{position:fixed;left:0;right:0;bottom:0;z-index:30;background:var(--card);border-top:1px solid var(--line);padding:12px 16px 18px;
 box-shadow:0 -8px 24px rgba(0,0,0,.18);display:none;font-size:13px}
#panel .hd{display:flex;align-items:center;gap:8px}#panel h3{margin:0;font-size:15px;flex:1}
#panel .x{border:0;background:transparent;color:var(--mut);font-size:20px;cursor:pointer}
#panel .g{display:grid;grid-template-columns:repeat(3,1fr);gap:4px 12px;margin:8px 0 10px}
#panel .g div{display:flex;justify-content:space-between}#panel .g span{color:var(--mut)}
#panel .go{display:flex;gap:8px}#panel .go a{flex:1;text-align:center;text-decoration:none;border:1px solid var(--line);border-radius:9px;padding:8px;color:var(--fg)}
#panel .go a:first-child{background:var(--acc);border-color:var(--acc);color:#fff}
h2{font-size:15px;margin:26px 0 8px}
.rank{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:2px 24px}
.rk{display:grid;grid-template-columns:110px 1fr 58px;align-items:center;gap:8px;font-size:12.5px;padding:3px 0;cursor:pointer;border-radius:6px}
.rk:hover{background:var(--hover)}
.rk .nm{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.rk .br{position:relative;height:12px}.rk .br i{position:absolute;top:0;height:12px;border-radius:2px}
.rk .br:before{content:"";position:absolute;left:50%;top:-2px;bottom:-2px;border-left:1px solid var(--line)}
.rk .v{text-align:right;font-weight:600}
.movers{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.mv{border:1px solid var(--line);border-radius:12px;background:var(--card);overflow:hidden}
.mv .h{padding:8px 12px;font-weight:700;font-size:13px;border-bottom:1px solid var(--line)}
.mv a{display:grid;grid-template-columns:46px 1fr auto auto;gap:8px;padding:6px 12px;border-top:1px solid var(--line);text-decoration:none;color:var(--fg);font-size:12.5px}
.mv a:first-of-type{border-top:0}.mv a:hover{background:var(--hover)}
.mv .nm{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.mv small{color:var(--mut)}
.note{margin-top:26px;color:var(--mut);font-size:11.5px;line-height:1.7}
/* ===== 2026-11 デザイン刷新（トップ画面と共通）：黒／白地、数字は Inter の極太。タイルの色（赤＝上昇／緑＝下落）は変えない ===== */
:root{--bg:#f3f4f6;--card:#fff;--fg:#0c0d10;--fg2:#3d4148;--mut:#5b6068;--line:#d5d8de;--hover:rgba(12,13,16,.05);--acc:#0c0d10;--up:#b91c24;--dn:#08705a;--gap:#f3f4f6;--sech:#2b303b}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){
--bg:#050608;--card:#101216;--fg:#f2f4f8;--fg2:#c6cbd6;--mut:#8f96a3;--line:#23262d;--hover:rgba(255,255,255,.06);--acc:#5cc8ff;--up:#ff7378;--dn:#3fd0a4;--gap:#050608;--sech:#171a20}}
:root[data-theme="dark"]{--bg:#050608;--card:#101216;--fg:#f2f4f8;--fg2:#c6cbd6;--mut:#8f96a3;--line:#23262d;--hover:rgba(255,255,255,.06);--acc:#5cc8ff;--up:#ff7378;--dn:#3fd0a4;--gap:#050608;--sech:#171a20}
body{font-family:Inter,"Hiragino Sans","Hiragino Kaku Gothic ProN","Noto Sans JP",system-ui,-apple-system,"Segoe UI",sans-serif;-webkit-font-smoothing:antialiased}
h1{font-size:24px;font-weight:800;letter-spacing:.02em}
h2{font-weight:800}
.sub{color:var(--mut)}
.seg{border:0;border-radius:10px;background:var(--card)}
.seg button{font-weight:600}
.seg button.on{background:var(--fg);color:var(--bg);font-weight:800}
.tabs button{font-weight:600}
.tabs button.on{font-weight:800;border-bottom-color:var(--fg)}
.tl button.pl{background:var(--fg);border-color:var(--fg);color:var(--bg);font-weight:800}
.tl .lab{font-weight:800}
.stats b{font-weight:800}
@media(max-width:640px){.wrap{padding:12px 10px 40px}h1{font-size:17px}
.ctl{gap:8px}.ctl>div{width:100%;display:flex;align-items:center}.ctl label{min-width:44px}
.seg{flex:1;overflow-x:auto}.seg button{padding:6px 8px;font-size:12px;flex:1}
.tabs button{padding:8px 9px;font-size:13px}.tabs small{display:none}
.movers{grid-template-columns:1fr}#panel .g{grid-template-columns:repeat(2,1fr)}}
</style></head><body><div class="wrap">
<header><div><h1><a href="./index.html" title="トップへ">‹</a>ヒートマップ</h1>
<div class="sub">株価データ __ASOF__ 時点 ／ 更新 __BUILT__</div></div>
<button class="btn" id="theme" type="button">明暗</button></header>

<div class="tabs" id="tabs"></div>
<div class="ctl">
 <div><label>騰落率</label><span class="seg" id="segP"></span></div>
 <div><label>大きさ</label><span class="seg" id="segS"></span></div>
</div>
<div class="tl" id="tl"><span class="lab" id="tLab"></span>
 <button id="tPlay" class="pl" type="button" title="再生（1営業日ずつ進める）">▶ 再生</button>
 <button id="tPrev" type="button" title="1営業日戻す">‹</button>
 <input type="range" id="tR" min="0" max="0" step="1" aria-label="日付">
 <button id="tNext" type="button" title="1営業日進める">›</button>
 <select id="tSp" title="再生の速さ"><option value="700">遅く</option><option value="350" selected>ふつう</option><option value="150">速く</option></select>
 <button id="tNow" type="button">最新</button></div>
<div class="tlx" id="tlx"></div>
<div class="stats" id="stats"></div>
<div class="crumb" id="crumb"></div>
<div class="mapbox"><div id="map"><div id="mapIn"></div></div><div class="mini" id="mini" hidden><i id="miniV"></i></div><div class="zc"><span class="zl" id="zl" hidden></span><button id="zr" class="rs" type="button" hidden>全体に戻す</button><button id="zo" type="button" aria-label="縮小" title="縮小">−</button><button id="zi" type="button" aria-label="拡大" title="拡大">＋</button></div></div>
<div class="legend" id="legend"></div>

<h2 id="h2r">業種別の騰落率</h2>
<div class="rank" id="rank"></div>
<h2 id="h2m">値上がり・値下がり上位</h2>
<div class="movers" id="movers"></div>

<p class="note">色＝選んだ期間の騰落率（赤＝上昇、緑＝下落。濃いほど大きい）。大きさ＝時価総額または売買代金。
業種の帯をタップするとその業種だけを拡大、銘柄をタップすると詳細と分析ページへのリンクが出ます。小さくて見えない所は、右下の＋（スマホは2本指で広げる、PCはトラックパッドのピンチまたはCtrl＋ホイール）で拡大し、ドラッグで移動できます。<br>
業種の騰落率は、選んだ「大きさ」の指標で加重した平均です。時価総額は決算データの値を最新終値で引き直した概算、売買代金は終値×出来高の概算です。
株価は分割調整済み。直近10日以上取引の無い銘柄は除いています。<br>日付スライダー：約1年前までの各営業日の時点で描き直します（▶で1営業日ずつ再生）。過去の日付の時価総額は最新の時価総額を株価の変化で引き戻した概算、市場区分・業種・日経225の構成銘柄はいまの区分のままです（当時は未上場の銘柄は出ません）。過去の日付では「1年」は計算できません。</p>
</div>
<div id="tip"></div>
<div id="panel"></div>
<script>
const D=__DATA__;
const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
// stock: 0 code,1 name,2 mkt,3 sec,4 n225,5 mcap,6 tv1,7 tv20,8 d1,9 w1,10 m1,11 m3,12 ytd,13 y1,14 close,15 TOPIX規模区分(0=非構成)
const MK=[["prime","プライム",s=>s[2]===0],["standard","スタンダード",s=>s[2]===1],["growth","グロース",s=>s[2]===2],
 ["n225","日経225",s=>s[4]===1],["topix","TOPIX",s=>s[15]>0],["all","全市場",s=>true]];
const TPXN=["","TOPIX Core30","TOPIX Large70","TOPIX Mid400","TOPIX Small 1","TOPIX Small 2"];
const PER=[["d1","1日",8,3],["w1","1週",9,6],["m1","1ヶ月",10,10],["m3","3ヶ月",11,15],["ytd","年初来",12,25],["y1","1年",13,30]];
const SZ=[["mcap","時価総額",5],["tv1","売買代金（当日）",6],["tv20","売買代金（20日平均）",7]];
const MKN=["プライム","スタンダード","グロース"];
let st={mk:"prime",p:"d1",s:"mcap",sec:null};
try{const q=new URLSearchParams(location.hash.slice(1));for(const k of["mk","p","s"])if(q.get(k))st[k]=q.get(k);
 if(q.get("sec"))st.sec=+q.get("sec");}catch(e){}
try{if(!location.hash){const v=JSON.parse(localStorage.getItem('hm-state')||'{}');Object.assign(st,v,{sec:null});}}catch(e){}
function save(){const h=`mk=${st.mk}&p=${st.p}&s=${st.s}`+(st.sec!=null?`&sec=${st.sec}`:"")+(typeof TI!=="undefined"&&TI<LASTI?`&dt=${D.hdates[TI]}`:"");history.replaceState(null,"","#"+h);
 try{localStorage.setItem('hm-state',JSON.stringify({mk:st.mk,p:st.p,s:st.s}))}catch(e){}}
const P=()=>PER.find(x=>x[0]===st.p)||PER[0], S=()=>SZ.find(x=>x[0]===st.s)||SZ[0], M=()=>MK.find(x=>x[0]===st.mk)||MK[0];
const fmt=(v,d=2)=>v==null?"—":(v>0?"+":"")+v.toFixed(d)+"%";
const oku=v=>v>=10000?(v/10000).toFixed(v>=100000?0:1)+"兆円":v>=1?Math.round(v).toLocaleString()+"億円":(v*100).toFixed(0)+"百万円";
// 色：上昇＝赤、下落＝緑（日本式）。±scale で最も濃くなる
const C0=[72,72,68],CU=[214,48,49],CD=[24,150,104];
function col(r,sc){if(r==null)return"rgb(110,110,106)";let t=Math.max(-1,Math.min(1,r/sc));const c=t>=0?CU:CD;t=Math.pow(Math.abs(t),.8);
 return`rgb(${C0.map((v,i)=>Math.round(v+(c[i]-v)*t)).join(",")})`;}

// squarified treemap
function squarify(items,x,y,w,h){const out=[];const tot=items.reduce((a,b)=>a+b.v,0);if(tot<=0||w<=0||h<=0)return out;
 const sc=w*h/tot;let rest=items.map(it=>({it,a:it.v*sc}));
 while(rest.length){const short=Math.min(w,h);let row=[],best=Infinity,i=0;
  for(;i<rest.length;i++){const r2=row.concat(rest[i]);const s=r2.reduce((a,b)=>a+b.a,0);
   const mx=Math.max(...r2.map(z=>z.a)),mn=Math.min(...r2.map(z=>z.a));
   const worst=Math.max(short*short*mx/(s*s),(s*s)/(short*short*mn));
   if(worst>best)break;best=worst;row=r2;}
  const s=row.reduce((a,b)=>a+b.a,0);
  if(w>=h){const cw=s/h;let yy=y;for(const z of row){const ch=z.a/cw;out.push({it:z.it,x,y:yy,w:cw,h:ch});yy+=ch;}x+=cw;w-=cw;}
  else{const ch=s/w;let xx=x;for(const z of row){const cw=z.a/ch;out.push({it:z.it,x:xx,y,w:cw,h:ch});xx+=cw;}y+=ch;h-=ch;}
  rest=rest.slice(row.length);}
 return out;}

// ---- 時間スライダー ----
// CUR＝いま表示している日付の銘柄データ（最新日は D.stocks そのもの、過去日は heatmap_hist.js から作る）
let CUR=D.stocks,TI=D.hdates.length-1,HL=null,HLOAD=null,PLAY=null;const LASTI=D.hdates.length-1;
const IDX={};D.stocks.forEach((s,i)=>IDX[s[0]]=i);
function dec(b){const s=atob(b),u=new Uint8Array(s.length);for(let i=0;i<s.length;i++)u[i]=s.charCodeAt(i);return u.buffer;}
function loadHist(){if(HL)return Promise.resolve(HL);if(HLOAD)return HLOAD;
 $("tLab").innerHTML=`読み込み中… <small>過去データ（数MB）</small>`;
 HLOAD=new Promise((ok,ng)=>{const sc=document.createElement("script");sc.src="./heatmap_hist.js?v="+D.asof;
  sc.onload=()=>{const h=window.HM_HIST;if(!h){ng();return;}
   HL={n:h.n,c:new Int16Array(dec(h.c)),v:new Uint8Array(dec(h.v)),ye:{}};for(const y in h.ye)HL.ye[y]=new Int16Array(dec(h.ye[y]));window.HM_HIST=null;ok(HL);};
  sc.onerror=()=>{HLOAD=null;$("tLab").innerHTML=`過去データを読み込めませんでした`;ng();};document.head.appendChild(sc);});
 return HLOAD;}
function viewAt(t){if(t>=LASTI||!HL)return D.stocks;const N=HL.n,C=HL.c,V=HL.v,st0=D.hstart;
 const y=D.hdates[t].slice(0,4),YE=HL.ye[y];const out=[];const K=[1,5,21,63];
 for(let i=0;i<N;i++){const q=C[t*N+i];if(q===-32768)continue;const s=D.stocks[i];const x=s.slice();const e=Math.exp(q/2000);
  x[5]=s[5]*e;x[14]=Math.round(s[14]*e*10)/10;
  const b=V[t*N+i];x[6]=b?Math.pow(10,b/32+5)/1e8:0;let sm=0;for(let k=0;k<20&&t-k>=0;k++){const bb=V[(t-k)*N+i];if(bb)sm+=Math.pow(10,bb/32+5);}x[7]=sm/20/1e8;
  K.forEach((k,j)=>{const p=t-k>=0?C[(t-k)*N+i]:-32768;x[8+j]=p===-32768?null:(Math.exp((q-p)/2000)-1)*100;});
  if(!b)x[8]=null;
  const yq=YE?YE[i]:-32768;x[12]=yq===-32768?null:(Math.exp((q-yq)/2000)-1)*100;x[13]=null;out.push(x);}
 return out;}
let BY={};function setView(){CUR=viewAt(TI);BY={};for(const s of CUR)BY[s[0]]=s;
 document.body.classList.toggle("past",TI<LASTI);}
function tlUI(){const r=$("tR");r.max=LASTI;r.min=Math.min(D.hstart,LASTI);r.value=TI;const d=D.hdates[TI]||D.asof;
 const wd="日月火水木金土"[new Date(d+"T00:00:00").getDay()];
 $("tLab").innerHTML=`${d}（${wd}）`+(TI>=LASTI?`<small>最新</small>`:`<small>${LASTI-TI}営業日前</small>`);
 $("tPrev").disabled=TI<=+r.min;$("tNext").disabled=TI>=LASTI;$("tNow").disabled=TI>=LASTI;
 $("tPlay").textContent=PLAY?"❚❚ 停止":"▶ 再生";
 const a=D.hdates[+r.min]||"",z=D.hdates[LASTI]||"";$("tlx").innerHTML=`<span>${a}</span><span>${z}</span>`;
 document.querySelectorAll('#segP button[data-k="y1"]').forEach(b=>b.classList.toggle("na",TI<LASTI));}
async function goTo(t,keep){t=Math.max(+$("tR").min,Math.min(LASTI,t));if(t<LASTI&&!HL){try{await loadHist();}catch(e){return;}}
 TI=t;if(!keep)stop();setView();render();}
function stop(){if(PLAY){clearTimeout(PLAY);PLAY=null;}tlUI();}
async function play(){if(PLAY){stop();return;}if(!HL){try{await loadHist();}catch(e){return;}}
 if(TI>=LASTI)TI=+$("tR").min;PLAY=1;const step=()=>{if(!PLAY)return;setView();render();
  if(TI>=LASTI){PLAY=null;tlUI();return;}PLAY=setTimeout(()=>{if(!PLAY)return;TI++;step();},+$("tSp").value);};step();}
$("tR").addEventListener("input",e=>goTo(+e.target.value));
$("tR").addEventListener("pointerdown",()=>{loadHist().catch(()=>{});});
$("tPrev").onclick=()=>goTo(TI-1);$("tNext").onclick=()=>goTo(TI+1);$("tNow").onclick=()=>goTo(LASTI);$("tPlay").onclick=play;
addEventListener("keydown",e=>{if(e.target.closest("input,select,textarea"))return;
 if(e.key==="ArrowLeft"){goTo(TI-1);e.preventDefault();}else if(e.key==="ArrowRight"){goTo(TI+1);e.preventDefault();}});
if(!D.hdates.length)$("tl").style.display="none";

function universe(){const f=M()[2];return CUR.filter(f);}
function groups(list){const si=S()[2],pi=P()[2];const g={};
 for(const s of list){const v=s[si]||0;if(v<=0)continue;(g[s[3]]=g[s[3]]||{sec:s[3],v:0,list:[],wr:0,wv:0}).list.push({s,v});g[s[3]].v+=v;
  if(s[pi]!=null){g[s[3]].wr+=v*s[pi];g[s[3]].wv+=v;}}
 const arr=Object.values(g);const L=s=>{const z=D.stocks[IDX[s[0]]];return z?z[si]||0:0;};
 for(const x of arr){x.r=x.wv?x.wr/x.wv:null;x.o=0;for(const y of x.list){y.o=L(y.s);x.o+=y.o;}
  x.list.sort((a,b)=>FIX()?b.o-a.o:b.v-a.v);}
 return arr.sort((a,b)=>FIX()?b.o-a.o:b.v-a.v);}
// 時価総額は日々の変化が小さいので、過去日も並び順を最新日で固定する（売買代金は日々大きく変わるので、その日の大きさ順）
function FIX(){return TI<LASTI&&st.s==="mcap";}

function drawMap(){const map=$("map");const W=map.clientWidth;const mob=W<640;
 const key=st.mk+"|"+st.sec;if(key!==ZKEY){ZKEY=key;Z=1;PX=0;PY=0;}
 const H=st.sec!=null?Math.round(mob?W*1.25:Math.min(760,Math.max(480,W*.55))):Math.round(mob?W*1.6:Math.min(860,Math.max(520,W*.6)));
 map.style.height=H+"px";VW=W;VH=H;[PX,PY]=clampXY(Z,PX,PY);const ZW=W*Z,ZH=H*Z;const sc=P()[3],pi=P()[2];let html="";
 let gs=groups(universe());if(st.sec!=null)gs=gs.filter(g=>g.sec===st.sec);
 const rects=squarify(gs,0,0,ZW,ZH);
 // 業種の枠（帯）と銘柄タイルは、どちらも #map 基準の絶対座標で置く
 for(const R of rects){const g=R.it;const hd=R.h>34&&R.w>44?16:0;
  if(hd)html+=`<div class="sh" data-sec="${g.sec}" style="left:${R.x+1}px;top:${R.y+1}px;width:${R.w-2}px;right:auto"><b>${esc(D.sectors[g.sec])}</b> ${fmt(g.r,1)}</div>`;
  const cells=squarify(g.list,R.x+1,R.y+hd+1,R.w-2,R.h-hd-2);
  for(const c of cells){const s=c.it.s;const r=s[pi];const w=c.w,h=c.h;
   let inner="";if(w>22&&h>13){let fs=Math.max(9,Math.min(st.sec!=null?30:24,Math.sqrt(w*h)/5,h/2.6));
    // 銘柄名が枠に収まる文字サイズ（全角1文字≒1em、半角≒0.6em）。小さすぎるときはコードで出す
    const em=[...s[1]].reduce((a,c)=>a+(c.charCodeAt(0)<256?.6:1),0);const fn=Math.min(fs,(w*.9-4)/(em*1.12));
    let lab,lf;if(fn>=Math.min(11,fs)){lab=esc(s[1]);lf=fn;}else{lab=s[0];lf=Math.min(fs,(w-4)/2.5);}
    if(lf>=8)inner=`<span class="n" style="font-size:${lf.toFixed(1)}px">${lab}</span>`+(h>lf*1.2+fs*.85+2?`<span class="p" style="font-size:${Math.max(8.5,Math.min(fs*.8,(w-4)/3.3)).toFixed(1)}px">${fmt(r,1)}</span>`:"");}
   html+=`<div class="t" data-c="${s[0]}" style="left:${c.x.toFixed(1)}px;top:${c.y.toFixed(1)}px;width:${w.toFixed(1)}px;height:${h.toFixed(1)}px;background:${col(r,sc)}">${inner}</div>`;}}
 const inn=$("mapIn");inn.style.width=ZW+"px";inn.style.height=ZH+"px";inn.style.transform=`translate(${PX}px,${PY}px)`;inn.innerHTML=html;
 zoomUI();
}

function drawStats(){const pi=P()[2],si=S()[2];const xs=universe().filter(s=>s[pi]!=null);
 const up=xs.filter(s=>s[pi]>0).length,dn=xs.filter(s=>s[pi]<0).length,eq=xs.length-up-dn;
 let w=0,wr=0;for(const s of xs){w+=s[si];wr+=s[si]*s[pi];}
 const avg=w?wr/w:null;const tot=universe().reduce((a,s)=>a+(s[si]||0),0);
 const med=xs.map(s=>s[pi]).sort((a,b)=>a-b)[Math.floor(xs.length/2)];
 $("stats").innerHTML=`<span>${TI<LASTI?`<b>${D.hdates[TI]}</b> 時点・`:""}${M()[1]}・${P()[1]}</span>`+(TI<LASTI&&st.p==="y1"?`<span class="d">過去の日付では「1年」は計算できません</span>`:"")+`<span>${S()[1]}加重 <b class="${avg>0?'u':avg<0?'d':''}">${fmt(avg)}</b></span>`+
  `<span>中央値 <b class="${med>0?'u':med<0?'d':''}">${fmt(med)}</b></span>`+
  `<span>値上がり <b class="u">${up}</b> ／ 値下がり <b class="d">${dn}</b> ／ 変わらず ${eq}</span>`+
  `<span>${S()[1]}合計 <b>${oku(tot)}</b></span>`;
 $("crumb").innerHTML=st.sec!=null?`<a id="back">‹ 全業種</a> ／ <b>${esc(D.sectors[st.sec])}</b>`:`<span style="color:var(--mut);font-size:12px">業種の帯をタップで業種だけ表示 ／ ＋・ピンチで拡大、ドラッグで移動</span>`;
 if($("back"))$("back").onclick=()=>{st.sec=null;render();};}

function drawLegend(){const sc=P()[3];const steps=[-1,-.66,-.33,0,.33,.66,1];
 $("legend").innerHTML=`<span>下落</span><span class="bar">${steps.map(t=>`<span style="background:${col(t*sc,sc)}">${t===0?"0":(t>0?"+":"")+(t*sc).toFixed(sc<5?1:0)}</span>`).join("")}</span><span>上昇（%）</span>`;}

function drawRank(){const gs=groups(universe()).filter(g=>g.r!=null).sort((a,b)=>b.r-a.r);
 const mx=Math.max(...gs.map(g=>Math.abs(g.r)),.01);
 $("h2r").textContent=`業種別の騰落率（${M()[1]}・${P()[1]}・${S()[1]}加重）`;
 $("rank").innerHTML=gs.map(g=>{const w=Math.abs(g.r)/mx*50;const pos=g.r>=0;
  return`<div class="rk" data-sec="${g.sec}"><span class="nm">${esc(D.sectors[g.sec])} <small style="color:var(--mut)">${g.list.length}</small></span>`+
  `<span class="br"><i style="${pos?'left:50%':'right:50%'};width:${w}%;background:${pos?'var(--up)':'var(--dn)'}"></i></span>`+
  `<span class="v ${pos?'u':'d'}">${fmt(g.r)}</span></div>`;}).join("");}

function drawMovers(){const pi=P()[2];let xs=universe().filter(s=>s[pi]!=null&&s[6]+s[7]>0);
 if(st.sec!=null)xs=xs.filter(s=>s[3]===st.sec);
 // 値動きの上位は、極小の銘柄に偏らないよう20日平均の売買代金1億円以上に限る
 const liq=xs.filter(s=>s[7]>=1);const base=liq.length>=20?liq:xs;
 const top=[...base].sort((a,b)=>b[pi]-a[pi]).slice(0,10),bot=[...base].sort((a,b)=>a[pi]-b[pi]).slice(0,10);
 const row=s=>`<a href="./one/${esc(s[0])}.html"><b>${esc(s[0])}</b><span class="nm">${esc(s[1])} <small>${esc(D.sectors[s[3]])}</small></span><small>${oku(s[7])}</small><b class="${s[pi]>0?'u':'d'}">${fmt(s[pi],1)}</b></a>`;
 $("h2m").textContent=`値上がり・値下がり上位（${M()[1]}${st.sec!=null?"・"+D.sectors[st.sec]:""}・${P()[1]}）`;
 $("movers").innerHTML=`<div class="mv"><div class="h u">値上がり上位</div>${top.map(row).join("")}</div><div class="mv"><div class="h d">値下がり上位</div>${bot.map(row).join("")}</div>`+
  `<div style="grid-column:1/-1;color:var(--mut);font-size:11.5px">${base===liq?"20日平均の売買代金1億円以上の銘柄から。":""}右から2列目は20日平均の売買代金</div>`;}

setView();
function info(s){return`<table>${PER.map(p=>`<tr class="${p[0]===st.p?'cur':''}"><td>${p[1]}</td><td class="${s[p[2]]>0?'u':s[p[2]]<0?'d':''}">${fmt(s[p[2]])}</td></tr>`).join("")}</table>`;}
function tipHtml(s){return`<h3>${esc(s[0])} ${esc(s[1])}</h3><div style="color:var(--mut);font-size:11.5px;margin-bottom:4px">${MKN[s[2]]}${s[4]?"・日経225":""}${s[15]?"・"+TPXN[s[15]]:""}／${esc(D.sectors[s[3]])}</div>`+
 `<div style="margin-bottom:4px">終値 <b>${s[14].toLocaleString()}</b>円</div>`+info(s)+
 `<div style="margin-top:4px;color:var(--fg2);font-size:11.5px">時価総額 ${oku(s[5])}<br>売買代金 当日 ${oku(s[6])} ／ 20日平均 ${oku(s[7])}</div>`;}
const tip=$("tip");const hoverOK=matchMedia("(hover:hover)").matches;
$("map").addEventListener("mousemove",e=>{if(!hoverOK)return;const t=e.target.closest(".t");if(!t){tip.style.display="none";return;}
 tip.innerHTML=tipHtml(BY[t.dataset.c]);tip.style.display="block";const r=tip.getBoundingClientRect();
 let x=e.clientX+14,y=e.clientY+14;if(x+r.width>innerWidth-8)x=e.clientX-r.width-14;if(y+r.height>innerHeight-8)y=innerHeight-r.height-8;
 tip.style.left=x+"px";tip.style.top=y+"px";});
$("map").addEventListener("mouseleave",()=>tip.style.display="none");
$("map").addEventListener("click",e=>{const h=e.target.closest(".sh");if(h){st.sec=+h.dataset.sec;render();window.scrollTo({top:$("tabs").offsetTop-8,behavior:"smooth"});return;}
 const t=e.target.closest(".t");if(!t)return;const s=BY[t.dataset.c];
 if(hoverOK&&!e.shiftKey){if(e.detail>1){clearTimeout(window.__go);return;}clearTimeout(window.__go);window.__go=setTimeout(()=>{location.href=`./one/${s[0]}.html`},260);return;}
 tip.style.display="none";const p=$("panel");
 p.innerHTML=`<div class="hd"><h3>${esc(s[0])} ${esc(s[1])} <small style="color:var(--mut);font-weight:400;font-size:12px">${MKN[s[2]]}・${esc(D.sectors[s[3]])}</small></h3><button class="x" id="px">×</button></div>`+
  `<div class="g">${PER.map(q=>`<div><span>${q[1]}</span><b class="${s[q[2]]>0?'u':s[q[2]]<0?'d':''}">${fmt(s[q[2]])}</b></div>`).join("")}`+
  `<div><span>終値</span><b>${s[14].toLocaleString()}</b></div><div><span>時価総額</span><b>${oku(s[5])}</b></div><div><span>売買代金</span><b>${oku(s[6])}</b></div></div>`+
  `<div class="go"><a href="./one/${esc(s[0])}.html">分析ダッシュボード</a><a href="./${esc(s[0])}.html">チャート</a></div>`;
 p.style.display="block";$("px").onclick=()=>p.style.display="none";});
$("rank").addEventListener("click",e=>{const r=e.target.closest(".rk");if(!r)return;st.sec=+r.dataset.sec;render();window.scrollTo({top:$("tabs").offsetTop-8,behavior:"smooth"});});

function seg(id,list,key){$(id).innerHTML=list.map(x=>`<button data-k="${x[0]}" class="${st[key]===x[0]?'on':''}">${x[1]}</button>`).join("");
 $(id).onclick=e=>{const b=e.target.closest("button");if(!b)return;st[key]=b.dataset.k;render();};}
function tabs(){$("tabs").innerHTML=MK.map(x=>`<button data-k="${x[0]}" class="${st.mk===x[0]?'on':''}">${x[1]}<small>${D.stocks.filter(x[2]).length}</small></button>`).join("");
 $("tabs").onclick=e=>{const b=e.target.closest("button");if(!b)return;st.mk=b.dataset.k;st.sec=null;render();};}
function render(){save();tlUI();tabs();seg("segP",PER,"p");seg("segS",SZ,"s");drawStats();drawMap();drawLegend();drawRank();drawMovers();$("panel").style.display="none";}

// ---- 拡大・移動 ----
// Z=拡大率（1〜ZMAX）、PX/PY=表示位置。拡大すると大きな面積で配置し直すので、小さな銘柄にも名前と騰落率が出る
let MOVED=false,LASTPT="mouse";let Z=1,PX=0,PY=0,VW=0,VH=0,ZKEY=null,T=null,ct=null;const ZMAX=12;
function clampXY(z,px,py){return[Math.min(0,Math.max(VW-VW*z,px)),Math.min(0,Math.max(VH-VH*z,py))];}
function zoomUI(){const m=$("map");m.classList.toggle("zoomed",Z>1);
 $("zl").hidden=Z<=1;$("zl").textContent="×"+(Z<10?Z.toFixed(1):Math.round(Z));$("zr").hidden=Z<=1;
 $("zo").disabled=Z<=1;$("zi").disabled=Z>=ZMAX;
 $("mini").hidden=Z<=1;if(Z>1){const mw=Math.min(84,VW*.22),mh=mw*VH/VW;const mi=$("mini");mi.style.width=mw+"px";mi.style.height=mh+"px";
  const v=$("miniV");v.style.left=(-PX/(VW*Z)*mw)+"px";v.style.top=(-PY/(VH*Z)*mh)+"px";v.style.width=(mw/Z)+"px";v.style.height=(mh/Z)+"px";}}
// 見た目だけ先に動かし（軽い）、操作が終わったら配置し直す
function preview(nz,cx,cy,base){const b=base||T||{z:Z,px:PX,py:PY};nz=Math.max(1,Math.min(ZMAX,nz));
 const wx=(cx-b.px)/b.z,wy=(cy-b.py)/b.z;const [px,py]=clampXY(nz,cx-wx*nz,cy-wy*nz);T={z:nz,px,py};
 $("mapIn").style.transform=`translate(${px}px,${py}px) scale(${nz/Z})`;}
function commit(){clearTimeout(ct);if(!T)return;Z=T.z;PX=T.px;PY=T.py;T=null;drawMap();}
function zoomTo(nz,cx,cy){if(cx==null){cx=VW/2;cy=VH/2;}preview(nz,cx,cy,{z:Z,px:PX,py:PY});commit();}
$("zi").onclick=()=>zoomTo(Z*2);$("zo").onclick=()=>zoomTo(Z/2);$("zr").onclick=()=>zoomTo(1);
{const map=$("map");const rel=e=>{const r=map.getBoundingClientRect();return[e.clientX-r.left,e.clientY-r.top];};
 // PC：トラックパッドのピンチ（ctrlKey付きのwheel）または Ctrl＋ホイール
 map.addEventListener("wheel",e=>{if(!e.ctrlKey&&!e.metaKey)return;e.preventDefault();const [x,y]=rel(e);
  const cur=T?T.z:Z;preview(cur*Math.exp(-e.deltaY*(e.deltaMode?0.05:0.0045)),x,y);clearTimeout(ct);ct=setTimeout(commit,160);},{passive:false});
 map.addEventListener("gesturestart",e=>e.preventDefault());
 // ドラッグで移動（マウス・1本指。拡大中だけ）
 let drag=null,pinch=null;
 map.addEventListener("pointerdown",e=>{LASTPT=e.pointerType;if(e.pointerType==="mouse"&&e.button!==0)return;
  if(!e.isPrimary){drag=null;return;}   // 2本目の指が触れたらドラッグはやめる（拡大縮小は下のタッチ処理）
  MOVED=false;drag=Z>1?{x:e.clientX,y:e.clientY,px:PX,py:PY,id:e.pointerId}:null;});
 map.addEventListener("pointermove",e=>{if(pinch||!drag||e.pointerId!==drag.id)return;
  const dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(!MOVED&&Math.hypot(dx,dy)<5)return;
  if(!MOVED){MOVED=true;map.classList.add("drag");try{map.setPointerCapture(e.pointerId)}catch(_){}}
  [PX,PY]=clampXY(Z,drag.px+dx,drag.py+dy);$("mapIn").style.transform=`translate(${PX}px,${PY}px)`;zoomUI();tip.style.display="none";});
 const up=e=>{if(drag&&e.pointerId===drag.id){drag=null;map.classList.remove("drag");}};
 // 2本指で拡大縮小（スマホ）。実際に画面に触れている指の数（e.touches）で判定するので、1本指では絶対に拡大しない
 const two=e=>{const r=map.getBoundingClientRect(),a=e.touches[0],b=e.touches[1];
  return{d:Math.hypot(a.clientX-b.clientX,a.clientY-b.clientY)||1,c:[(a.clientX+b.clientX)/2-r.left,(a.clientY+b.clientY)/2-r.top]};};
 map.addEventListener("touchstart",e=>{if(e.touches.length===2){const t=two(e);pinch={d:t.d,c:t.c,base:{z:Z,px:PX,py:PY}};drag=null;e.preventDefault();}
  else if(e.touches.length>2)pinch=null;},{passive:false});
 map.addEventListener("touchmove",e=>{if(!pinch||e.touches.length!==2)return;e.preventDefault();const t=two(e),B=pinch.base;
  const nz=Math.max(1,Math.min(ZMAX,B.z*t.d/pinch.d));const wx=(pinch.c[0]-B.px)/B.z,wy=(pinch.c[1]-B.py)/B.z;
  const [px,py]=clampXY(nz,t.c[0]-wx*nz,t.c[1]-wy*nz);T={z:nz,px,py};
  $("mapIn").style.transform=`translate(${px}px,${py}px) scale(${nz/Z})`;MOVED=true;tip.style.display="none";},{passive:false});
 const tend=e=>{if(pinch&&e.touches.length<2){pinch=null;commit();}};
 map.addEventListener("touchend",tend);map.addEventListener("touchcancel",tend);
 map.addEventListener("pointerup",up);map.addEventListener("pointercancel",up);
 // ドラッグ・ピンチの直後のクリック（銘柄を開く動作）は無視する
 map.addEventListener("click",e=>{if(MOVED){e.stopImmediatePropagation();e.preventDefault();MOVED=false;}},true);
 // PC（マウス）だけ：ダブルクリックした所を2倍に拡大。スマホのダブルタップでは拡大しない
 map.addEventListener("dblclick",e=>{if(LASTPT!=="mouse")return;const [x,y]=rel(e);zoomTo(Z*2,x,y);});}
let rt;addEventListener("resize",()=>{clearTimeout(rt);rt=setTimeout(drawMap,150);});
const DT0=new URLSearchParams(location.hash.slice(1)).get("dt");
render();
try{const dt=DT0;const i=D.hdates.indexOf(dt);if(dt&&i>=0&&i<LASTI)goTo(i);}catch(e){}
$('theme').addEventListener('click',()=>{const d=document.documentElement;
 const cur=d.getAttribute('data-theme')||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');
 const n=cur==='dark'?'light':'dark';d.setAttribute('data-theme',n);try{localStorage.setItem('fdb-theme',n)}catch(e){}});
</script></body></html>
"""


if __name__ == "__main__":
    main()
