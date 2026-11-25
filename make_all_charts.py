#!/usr/bin/env python3
"""全銘柄のチャートHTMLを一括生成し、検索できる銘柄一覧ページを作る。

    python3 make_all_charts.py              # data/prices の全CSV
    python3 make_all_charts.py 7203 6758    # 指定銘柄だけ再生成（indexも更新）
出力:
    data/charts/<code>.html   銘柄ごとのチャート
    data/charts/charts.html   検索・並べ替えできる一覧（トップ画面 index.html は make_home.py）
"""
import json, os, sys, time, datetime
from collections import Counter
import numpy as np
import pandas as pd
import make_chart_html as mc

BASE = mc.BASE
OUTDIR = mc.OUTDIR
LOG = os.path.join(BASE, "logs", "build_charts.log")


def log(msg):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    line = f"[{datetime.datetime.now():%H:%M:%S}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def rsi14(c):
    ch = pd.Series(c).diff()
    ag = ch.clip(lower=0).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    al = (-ch).clip(lower=0).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    v = (100 - 100/(1 + ag/al)).iloc[-1]
    return None if pd.isna(v) else round(float(v), 1)


def rci(c, w):
    if len(c) < w:
        return None
    win = np.asarray(c[-w:][::-1], dtype=float)
    tr = np.arange(1, w + 1)
    pr = pd.Series(win).rank(ascending=False, method="first").values
    return round(float((1 - 6*((tr - pr)**2).sum()/(w**3 - w))*100), 1)


def summarize(code, info, df):
    c = df["close"].values
    last, prev = float(c[-1]), (float(c[-2]) if len(c) > 1 else None)
    ma25 = float(pd.Series(c).rolling(25).mean().iloc[-1]) if len(c) >= 25 else None
    return {
        "code": code, "name": info.get("name", code),
        "mk": info.get("market", ""), "sc": info.get("sector", ""),
        "date": df["date"].iloc[-1].strftime("%Y-%m-%d"),
        "close": round(last, 1),
        "chg": round((last/prev - 1)*100, 2) if prev else None,
        "vol": int(df["volume"].iloc[-1]),
        "rsi": rsi14(c),
        "rci9": rci(c, 9), "rci26": rci(c, 26),
        "dev25": round((last/ma25 - 1)*100, 2) if ma25 else None,
    }


INDEX_TMPL = r"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>東証市場チャート一覧</title>
<style>
@import url("https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap");
:root{--bg:#f3f4f6;--fg:#0c0d10;--mut:#5b6068;--line:#d5d8de;--up:#b91c24;--dn:#08705a;--hl:#e6e8ec}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font-family:"Hiragino Sans","Hiragino Kaku Gothic ProN","Yu Gothic",system-ui,sans-serif;font-size:14px}
.wrap{max-width:1180px;margin:0 auto;padding:22px 18px 60px}
h1{font-size:20px;margin:0 0 4px;font-weight:650}
.sub{color:var(--mut);font-size:13px;margin-bottom:16px}
/* 関連ページへのリンクはカード状に並べる */
.links{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:0 0 14px}
.lk{position:relative;display:flex;flex-direction:column;gap:3px;padding:11px 30px 11px 14px;
border:1px solid var(--line);border-radius:10px;text-decoration:none;color:var(--fg);
transition:border-color .15s,background .15s}
.lk:hover{border-color:#4A6FA5;background:var(--hl)}
.lk b{font-size:14px;font-weight:650;color:#2a78d6}
.lk span{font-size:12px;color:var(--mut);line-height:1.45}
.lk i{position:absolute;right:12px;top:50%;transform:translateY(-50%);font-style:normal;
font-size:20px;color:var(--mut)}
.lk em{display:none}
.tools{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:12px;
position:sticky;top:0;background:var(--bg);padding:10px 0;z-index:2}
input[type=search]{flex:1;min-width:240px;padding:9px 13px;border:1px solid var(--line);
border-radius:9px;background:transparent;color:var(--fg);font:inherit}
input[type=search]:focus{outline:2px solid #4A6FA5;outline-offset:-1px}
.chips{display:inline-flex;background:var(--hl);border-radius:9px;padding:3px;gap:2px}
.chips button{border:0;background:transparent;color:var(--mut);font:inherit;font-size:13px;
padding:6px 12px;border-radius:7px;cursor:pointer;white-space:nowrap}
.chips button.on{background:var(--bg);color:var(--fg);font-weight:600;box-shadow:0 1px 2px rgba(0,0,0,.12)}
.count{color:var(--mut);font-size:13px;white-space:nowrap}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
/* ★は中央、コード・銘柄名・市場は左詰め、数値は右詰め */
th:nth-child(2),td:nth-child(2),th:nth-child(3),td:nth-child(3),
th:nth-child(4),td:nth-child(4){text-align:left}
th{position:sticky;top:56px;background:var(--bg);cursor:pointer;color:var(--mut);
font-weight:600;font-size:12.5px;user-select:none;z-index:1}
th:hover{color:var(--fg)}
th.sorted::after{content:" ▾";font-size:10px}
th.sorted.asc::after{content:" ▴"}
tbody tr:hover{background:var(--hl)}
td a{color:inherit;text-decoration:none;font-weight:600}
td a:hover{text-decoration:underline}
.up{color:var(--up)}.dn{color:var(--dn)}
th.star,td.star{display:none}/* お気に入り★は 2026-11-15 に廃止（監視銘柄へ）。列の番号を変えないため列は残して非表示 */
.star-btn{background:none;border:0;font-size:17px;line-height:1;color:var(--line);
cursor:pointer;padding:6px 2px}
.star-btn:hover{color:#c9a227}
.star-btn.on{color:#E8A33D}
.tag{display:inline-block;padding:1px 6px;border-radius:5px;font-size:11.5px}
.tag.hot{background:rgba(209,67,67,.12);color:var(--up)}
.tag.cool{background:rgba(46,125,107,.14);color:var(--dn)}
.more{margin:18px 0;text-align:center}
.more button{padding:9px 20px;border:1px solid var(--line);border-radius:9px;
background:transparent;color:var(--fg);font:inherit;cursor:pointer}
/* 2026-11 デザイン刷新（トップ画面と共通）：黒／白地、数字は Inter の極太、色は騰落の赤緑だけ */
body{font-family:Inter,"Hiragino Sans","Hiragino Kaku Gothic ProN","Noto Sans JP","Yu Gothic",system-ui,sans-serif;-webkit-font-smoothing:antialiased}
.wrap{padding-top:28px}
h1{font-size:24px;font-weight:800;letter-spacing:.02em}
.sub{font-size:12px;margin-bottom:10px}
.tools{gap:10px 14px}
input[type=search]{padding:11px 2px;border:0;border-bottom:3px solid var(--fg);border-radius:0;font-size:16px;font-weight:700}
input[type=search]::placeholder{color:var(--mut);font-weight:600}
input[type=search]:focus{outline:0}
.chips{border-radius:10px}
.chips button{font-weight:600}
.chips button.on{background:var(--fg);color:var(--bg);font-weight:800;box-shadow:none}
th{font-weight:800;font-size:12px;letter-spacing:.04em;border-bottom:2px solid var(--fg)}
td{font-weight:600}
td:nth-child(2) a,td:nth-child(3) a{font-weight:800}
td:nth-child(4){color:var(--mut);font-weight:400;font-size:12.5px}
td.up,td.dn{font-weight:700}
.star-btn{color:color-mix(in srgb,var(--mut) 45%,transparent)}
.tag{font-weight:800}
.tag.hot{background:color-mix(in srgb,var(--up) 16%,transparent)}
.tag.cool{background:color-mix(in srgb,var(--dn) 18%,transparent)}
.more button{border:0;background:var(--fg);color:var(--bg);font-weight:800;border-radius:10px}
.lk{border:0;background:var(--hl)}.lk b,.lk em{color:var(--fg)}
@media(prefers-color-scheme:dark){
:root{--bg:#050608;--fg:#f2f4f8;--mut:#8f96a3;--line:#23262d;--up:#ff7378;--dn:#3fd0a4;--hl:#14171c}
}
@media(max-width:700px){
.wrap{padding:14px 10px 40px}
h1{font-size:17px}
/* スマホでは短い名前だけのボタンを横に3つ並べる（説明は省略） */
.links{grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;margin-bottom:10px}
.lk{padding:9px 4px;align-items:center;justify-content:center;text-align:center;min-height:44px}
.lk b,.lk span,.lk i{display:none}
.lk em{display:block;font-style:normal;font-size:12.5px;font-weight:650;color:#2a78d6;line-height:1.3}
.lk em small{display:block;font-size:10.5px;font-weight:600;color:var(--mut)}
.tools{gap:8px;padding:8px 0}
input[type=search]{min-width:100%;font-size:16px}   /* 16px未満はiOSで自動ズームする */
.chips{width:100%;overflow-x:auto}
.chips button{flex:1;padding:8px 6px;font-size:12.5px}
.count{width:100%}
table{table-layout:fixed;width:100%}
th,td{padding:11px 4px;font-size:12.5px}
.tools{position:static}
th{position:static}
th:nth-child(2),td:nth-child(2){width:52px}
th:nth-child(5),td:nth-child(5){width:62px}
th:nth-child(6),td:nth-child(6){width:52px}
th:nth-child(8),td:nth-child(8){width:60px}
td:nth-child(3){overflow:hidden;text-overflow:ellipsis}
/* 市場・25日線乖離・RCI(26)・出来高はスマホでは非表示 */
th:nth-child(4),td:nth-child(4),th:nth-child(7),td:nth-child(7),
th:nth-child(10),td:nth-child(10),th:nth-child(11),td:nth-child(11){display:none}
}
@media(max-width:420px){
th:nth-child(9),td:nth-child(9){display:none}       /* RCI(9)も隠す */
}
</style></head><body><div class="wrap">
<h1><a href="./index.html" title="トップへ" style="text-decoration:none;color:inherit;margin-right:8px">‹</a>東証市場チャート一覧</h1>
<div class="sub">__COUNT__銘柄（__BREAKDOWN__） ／ データ最終日 __ASOF__ ／ 生成 __BUILT__</div>
<div class="tools">
  <input type="search" id="q" placeholder="コード・銘柄名・業種で検索（例: 7203 / トヨタ / 医薬品）" autofocus>
  <div class="chips" id="markets">
    <button data-m="all" class="on">全市場</button>
    <button data-m="プライム">プライム</button>
    <button data-m="スタンダード">スタンダード</button>
    <button data-m="グロース">グロース</button>
  </div>
  <div class="chips" id="filters">
    <button data-f="all" class="on">すべて</button>
    <button data-f="os">RSI30以下</button>
    <button data-f="ob">RSI70以上</button>
    <button data-f="up">上昇</button>
    <button data-f="dn">下落</button>
  </div>
  <span class="count" id="count"></span>
</div>
<table>
<thead><tr>
  <th class="star"></th><th data-k="code">コード</th><th data-k="name">銘柄名</th><th data-k="mk">市場</th>
  <th data-k="close">終値</th><th data-k="chg">前日比%</th>
  <th data-k="dev25">25日線乖離%</th><th data-k="rsi">RSI(14)</th>
  <th data-k="rci9">RCI(9)</th><th data-k="rci26">RCI(26)</th>
  <th data-k="vol">出来高</th>
</tr></thead>
<tbody id="rows"></tbody></table>
<div class="more"><button id="more">さらに表示</button></div>
</div>
<script>
const DATA = __DATA__;
const PAGE = 200;
let sortK="code", asc=true, filter="all", market="all", shown=PAGE, list=DATA;
const num=v=>v==null?"—":v.toLocaleString("ja-JP",{minimumFractionDigits:0,maximumFractionDigits:2});
const vol=v=>v>=1e8?(v/1e8).toFixed(2)+"億":v>=1e4?(v/1e4).toFixed(1)+"万":String(v);
const sign=v=>v==null?"":(v>0?"up":v<0?"dn":"");
const pct=v=>v==null?"—":(v>0?"+":"")+v.toFixed(2);
// 銘柄名の全角英数は半角にそろえて表示する。検索は全角・半角どちらで打っても当たる
const nk=s=>String(s==null?"":s).normalize("NFKC");
DATA.forEach(r=>{r.nm=nk(r.name);r._s=(r.code+" "+r.nm+" "+nk(r.sc)).toLowerCase();});

function apply(){
  const q=nk(document.getElementById("q").value).trim().toLowerCase();
  list=DATA.filter(r=>{
    if(market!=="all" && r.mk!==market) return false;
    if(q && !r._s.includes(q)) return false;
    if(filter==="os") return r.rsi!=null && r.rsi<=30;
    if(filter==="ob") return r.rsi!=null && r.rsi>=70;
    if(filter==="up") return r.chg!=null && r.chg>0;
    if(filter==="dn") return r.chg!=null && r.chg<0;
    return true;});
  list=[...list].sort((a,b)=>{
    const x=a[sortK],y=b[sortK];
    if(x==null)return 1; if(y==null)return -1;
    const c=(typeof x==="string")?x.localeCompare(y,"ja"):x-y;
    return asc?c:-c;});
  shown=PAGE; render();
}
function render(){
  const rows=list.slice(0,shown).map(r=>{
    const tag=r.rsi==null?"":r.rsi>=70?'<span class="tag hot">高</span>'
      :r.rsi<=30?'<span class="tag cool">低</span>':"";
    return "<tr><td class='star'></td>"+
      "<td><a href='./"+r.code+".html'>"+r.code+"</a></td>"+
      "<td><a href='./"+r.code+".html'>"+r.nm+"</a></td>"+
      "<td>"+(r.mk||"")+"</td>"+
      "<td>"+num(r.close)+"</td>"+
      "<td class='"+sign(r.chg)+"'>"+pct(r.chg)+"</td>"+
      "<td class='"+sign(r.dev25)+"'>"+pct(r.dev25)+"</td>"+
      "<td>"+(r.rsi==null?"—":r.rsi.toFixed(1))+" "+tag+"</td>"+
      "<td class='"+sign(r.rci9)+"'>"+(r.rci9==null?"—":r.rci9.toFixed(1))+"</td>"+
      "<td class='"+sign(r.rci26)+"'>"+(r.rci26==null?"—":r.rci26.toFixed(1))+"</td>"+
      "<td>"+vol(r.vol)+"</td></tr>";}).join("");
  document.getElementById("rows").innerHTML = rows ||
    "<tr><td colspan='11' style='padding:28px;text-align:center;color:var(--mut)'>"+
    "該当する銘柄がありません"+"</td></tr>";
  document.getElementById("count").textContent=list.length+"件"+
    (shown<list.length?"（"+shown+"件表示中）":"");
  document.getElementById("more").style.display=shown<list.length?"":"none";
  document.querySelectorAll("th").forEach(th=>{
    th.classList.toggle("sorted",th.dataset.k===sortK);
    th.classList.toggle("asc",th.dataset.k===sortK&&asc);});
}
document.getElementById("q").addEventListener("input",apply);
document.getElementById("more").addEventListener("click",()=>{shown+=PAGE;render();});
document.querySelectorAll("th[data-k]").forEach(th=>th.addEventListener("click",()=>{
  const k=th.dataset.k;
  if(k===sortK) asc=!asc; else {sortK=k; asc=(k==="code"||k==="name");}
  apply();}));
document.getElementById("markets").addEventListener("click",e=>{
  const b=e.target.closest("button"); if(!b)return;
  market=b.dataset.m;
  [...e.currentTarget.children].forEach(x=>x.classList.toggle("on",x===b));
  apply();});
document.getElementById("filters").addEventListener("click",e=>{
  const b=e.target.closest("button"); if(!b)return;
  filter=b.dataset.f;
  [...e.currentTarget.children].forEach(x=>x.classList.toggle("on",x===b));
  apply();});
apply();
</script></body></html>
"""


def main(codes=None, years=0):
    names = mc.load_names()
    cat = mc.catalog()
    targets = codes if codes else sorted(cat.keys())
    os.makedirs(OUTDIR, exist_ok=True)
    log(f"開始: {len(targets)}銘柄" + (f" / 直近{years}年ぶん" if years else ""))

    summaries, t0, ng, dirty = [], time.time(), 0, []
    for i, code in enumerate(targets, 1):
        try:
            df, dropped = mc.load_prices(code)          # 異常値を除外して読む
            if df is None or len(df) < 10:
                ng += 1; continue
            if dropped:
                dirty.append((code, dropped))
            mc.build(code, years=years)
            summaries.append(summarize(code, cat.get(code, {}), df))
        except Exception as e:
            ng += 1
            log(f"  失敗 {code}: {e}")
        if i % 100 == 0:
            el = time.time() - t0
            log(f"  {i}/{len(targets)}  経過{el:.0f}秒  残り約{el/i*(len(targets)-i):.0f}秒")

    # 一部だけ再生成した場合も、既存の一覧データを引き継いでindexを更新
    idx_json = os.path.join(OUTDIR, "_summary.json")
    merged = {}
    if codes and os.path.exists(idx_json):
        for r in json.load(open(idx_json, encoding="utf-8")):
            merged[r["code"]] = r
    for r in summaries:
        merged[r["code"]] = r
    rows = sorted(merged.values(), key=lambda r: r["code"])
    json.dump(rows, open(idx_json, "w", encoding="utf-8"), ensure_ascii=False)

    asof = max((r["date"] for r in rows), default="-")
    html = (INDEX_TMPL
            .replace("__DATA__", json.dumps(rows, ensure_ascii=False, separators=(",", ":")))
            .replace("__COUNT__", f"{len(rows):,}")
            .replace("__BREAKDOWN__", " ・ ".join(
                f"{m} {c:,}" for m, c in
                sorted(Counter(r.get("mk", "") for r in rows).items(),
                       key=lambda kv: -kv[1]) if m))
            .replace("__ASOF__", asof)
            .replace("__BUILT__", datetime.datetime.now().strftime("%Y-%m-%d %H:%M")))
    with open(os.path.join(OUTDIR, "charts.html"), "w", encoding="utf-8") as fh:
        fh.write(html)

    tot = sum(os.path.getsize(os.path.join(OUTDIR, f)) for f in os.listdir(OUTDIR))
    log(f"完了: {len(summaries)}銘柄生成 / 失敗{ng} / 合計{tot/1e6:.0f}MB / {time.time()-t0:.0f}秒")
    log(f"一覧ページ: {os.path.join(OUTDIR,'charts.html')}（トップ画面 index.html は make_home.py が作成）")
    if dirty:
        log("元CSVに異常値があり除外した銘柄: " +
            ", ".join(f"{c}({n}行)" for c, n in dirty))


if __name__ == "__main__":
    # 使い方: python3 make_all_charts.py [--years 5] [銘柄コード ...]
    argv = sys.argv[1:]
    yrs = 0
    if "--years" in argv:
        i = argv.index("--years")
        yrs = int(argv[i + 1])
        del argv[i:i + 2]
    main(argv or None, yrs)
