#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
東証ファンダメンタル分析の「かんたん表示」ページを作る。

入力  fundamentals/analysis/dashboard_data.json   （analyze_fundamentals.py の出力）
出力  data/charts/fundamentals_simple.html          （1ファイルで完結・外部読み込みなし）

画面は3つだけ:
  ランキング     … 総合評価の上位を、6項目の評価を色の帯で並べて一目で比較
  スクリーニング … 定番の条件（割安株・高配当株など）＋スライダーで絞り込み
  業種マップ     … 33業種 × 主要指標の中央値を色の濃さで表示（濃いほど良い）

使い方
  ./.venv/bin/python make_fundamental_simple.py
  ./.venv/bin/python make_fundamental_simple.py --src fundamentals/analysis_nofin/dashboard_data.json \
        --out data/charts/fundamentals_simple_nofin.html
標準ライブラリのみ・通信なし・数秒で終わります。
"""
import argparse, json, math
from pathlib import Path

BASE = Path(__file__).resolve().parent

# ページに埋め込む列（短い名前 ← dashboard_data.json の列名）
COLS = [
    ("c", "コード"), ("n", "銘柄名"), ("m", "市場"), ("s", "業種"), ("biz", "事業概要"),
    ("px", "株価"), ("cap", "時価総額(億円)"),
    ("per", "PER"), ("pbr", "PBR"), ("roe", "ROE(%)"), ("dy", "配当利回り(%)"), ("doe", "DOE(%)"), ("nh", "新高値からの日数"), ("ath", "上場来高値からの日数"),
    ("eq", "自己資本比率(%)"), ("gr", "売上高成長率(%)"), ("opm", "営業利益率(%)"),
    ("r1", "成長性評価"), ("r2", "収益性評価"), ("r3", "安全性評価"),
    ("r4", "規模評価"), ("r5", "割安度評価"), ("r6", "値上がり評価"),
    ("tot", "総合評価"), ("avg", "評価平均"), ("dev", "業種内偏差値"), ("fs", "Fスコア"), ("rank", "総合順位"),
    ("old", "決算が古い"), ("loss", "赤字"),
]


def clean(v, key):
    if v is None:
        return None
    if isinstance(v, bool):
        return 1 if v else 0
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
        if key in ("r1", "r2", "r3", "r4", "r5", "r6", "tot", "fs"):
            return int(round(v))
        return round(v, 2)
    if key == "biz" and isinstance(v, str):
        return v[:70]
    if isinstance(v, str) and v.lower() in ("true", "false"):
        return 1 if v.lower() == "true" else 0
    return v


def build(src: Path, out: Path, title: str, full_url: str, other_url: str = "", other_label: str = ""):
    d = json.loads(src.read_text(encoding="utf-8"))
    idx = {f: i for i, f in enumerate(d["fields"])}
    missing = [f for _, f in COLS if f not in idx]
    if missing:
        raise SystemExit(f"dashboard_data.json に列がありません: {missing}")

    rows = [[clean(r[idx[f]], k) for k, f in COLS] for r in d["stocks"]]
    screens = {name: {"desc": s["説明"], "rows": s["行"]} for name, s in d["screens"].items()}
    payload = {
        "cols": [k for k, _ in COLS],
        "rows": rows,
        "screens": screens,
        "gen": d.get("生成日", ""),
        "pxdate": d.get("株価日付", ""),
        "ver": d.get("版", ""),
    }
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = (TEMPLATE.replace("__TITLE__", title)
                    .replace("__FULL_URL__", full_url)
                    .replace("__OTHER__", f'<a class="btn" href="{other_url}">{other_label}</a>' if other_url else "")
                    .replace("__DATA__", data))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"✔ {out}  ({len(rows):,}銘柄, {out.stat().st_size/1e6:.1f}MB)")


TEMPLATE = r"""<!DOCTYPE html>
<html lang="ja"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<script>(function(){try{var t=localStorage.getItem('fdb-theme');if(t)document.documentElement.setAttribute('data-theme',t)}catch(e){}})();</script>
<style>
@import url("https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap");
:root{--surface:#fcfcfb;--page:#f5f5f2;--text:#0b0b0b;--text2:#52514e;--muted:#898781;--grid:#e1e0d9;
--border:rgba(11,11,11,.10);--accent:#2a78d6;--good:#0b8a0b;--bad:#d03b3b;--hover:rgba(11,11,11,.04);
--h1:#e8f0fb;--h2:#c9dcf5;--h3:#9cc0ec;--h4:#5f98de;--h5:#2a78d6;--hfg5:#fff;--hfg4:#fff;color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--surface:#1a1a19;--page:#0d0d0d;--text:#fff;--text2:#c3c2b7;
--muted:#898781;--grid:#2c2c2a;--border:rgba(255,255,255,.10);--accent:#3987e5;--good:#3cc23c;--bad:#e86060;--hover:rgba(255,255,255,.05);
--h1:#1b2635;--h2:#1f3a5e;--h3:#27528a;--h4:#306cb8;--h5:#3987e5;color-scheme:dark}}
:root[data-theme="dark"]{--surface:#1a1a19;--page:#0d0d0d;--text:#fff;--text2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;
--border:rgba(255,255,255,.10);--accent:#3987e5;--good:#3cc23c;--bad:#e86060;--hover:rgba(255,255,255,.05);
--h1:#1b2635;--h2:#1f3a5e;--h3:#27528a;--h4:#306cb8;--h5:#3987e5;color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--text);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Hiragino Sans","Noto Sans JP",sans-serif;-webkit-text-size-adjust:100%}
a{color:var(--accent);text-decoration:none}
.wrap{max-width:1100px;margin:0 auto;padding:16px}
header{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:12px}
h1{font-size:20px;margin:0;font-weight:700}
.sub{color:var(--muted);font-size:12px}
.hdr-r{margin-left:auto;display:flex;gap:8px;align-items:center}
.btn{border:1px solid var(--border);background:var(--surface);color:var(--text2);border-radius:8px;padding:5px 10px;font-size:12px;cursor:pointer}
.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:14px}
/* フィルタ */
.filters{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center}
.seg{display:inline-flex;border:1px solid var(--border);border-radius:8px;overflow:hidden}
.seg button{border:0;background:transparent;color:var(--text2);padding:6px 11px;font-size:13px;cursor:pointer}
.seg button+button{border-left:1px solid var(--border)}
.seg button.on{background:var(--accent);color:#fff}
select,input[type=search]{font:inherit;font-size:13px;padding:6px 8px;border:1px solid var(--border);border-radius:8px;background:var(--surface);color:var(--text)}
input[type=search]{width:180px}
label.ck{font-size:13px;color:var(--text2);display:inline-flex;gap:4px;align-items:center;cursor:pointer}
/* KPI */
.kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin:12px 0}
.kpi{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:10px 12px}
.kpi .l{font-size:11px;color:var(--muted)}
.kpi .v{font-size:22px;font-weight:700;font-variant-numeric:tabular-nums;line-height:1.2}
.kpi .v small{font-size:12px;font-weight:500;color:var(--text2);margin-left:2px}
/* タブ */
.tabs{display:flex;gap:4px;margin:4px 0 12px;border-bottom:1px solid var(--grid)}
.tabs button{border:0;background:none;padding:9px 14px;font-size:14px;color:var(--text2);cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-1px}
.tabs button.on{color:var(--text);font-weight:700;border-bottom-color:var(--accent)}
.pane{display:none}.pane.on{display:block}
/* 並び替えチップ */
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px}
.chip{border:1px solid var(--border);background:var(--surface);color:var(--text2);border-radius:999px;padding:5px 11px;font-size:12.5px;cursor:pointer}
.chip.on{background:var(--accent);border-color:var(--accent);color:#fff}
.hint{font-size:12px;color:var(--muted);margin:0 0 8px}
/* 銘柄リスト */
.list{display:flex;flex-direction:column}
.row{display:grid;grid-template-columns:34px minmax(0,1fr) 44px 148px 250px;gap:12px;align-items:center;padding:9px 6px;border-bottom:1px solid var(--grid)}
.row:hover{background:var(--hover)}
.lhead{font-size:11px;color:var(--muted);padding-top:0;padding-bottom:6px}
.lhead:hover{background:none}
.rk{color:var(--muted);font-variant-numeric:tabular-nums;text-align:right;font-size:13px}
.nm{min-width:0}
.nm a{font-weight:600;color:var(--text)}
.nm a:hover{color:var(--accent)}
.nm .cd{color:var(--muted);font-size:12px;margin-left:6px;font-variant-numeric:tabular-nums}
.nm .meta{font-size:11.5px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tag{display:inline-block;font-size:10.5px;padding:0 6px;border-radius:4px;background:var(--hover);color:var(--text2);margin-right:4px;border:1px solid var(--border)}
.tag.w{color:var(--bad)}
.tot{width:38px;height:38px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:18px;font-weight:700}
.strip{display:grid;grid-template-columns:repeat(6,1fr);gap:3px}
.strip i{height:22px;border-radius:4px;display:flex;align-items:center;justify-content:center;font-style:normal;font-size:11px;font-weight:600}
.strip.h i{height:auto;background:none!important;color:var(--muted);font-weight:400;font-size:10.5px}
.s0{background:var(--hover);color:var(--muted)}
.s1{background:var(--h1);color:var(--text2)}.s2{background:var(--h2);color:var(--text)}.s3{background:var(--h3);color:var(--text)}
.s4{background:var(--h4);color:#fff}.s5{background:var(--h5);color:#fff}
.mets{display:grid;grid-template-columns:repeat(4,1fr);gap:4px;font-variant-numeric:tabular-nums;text-align:right}
.mets b{display:block;font-size:13px;font-weight:600}
.mets span{font-size:10.5px;color:var(--muted)}
.row:not(.lhead) .mets span{display:none}
.more{display:block;margin:12px auto 0;padding:8px 20px}
.empty{padding:30px;text-align:center;color:var(--muted)}
/* スクリーニング */
.scr-grid{display:grid;grid-template-columns:300px 1fr;gap:14px;align-items:start}
.sl{margin-bottom:12px}
.sl .t{display:flex;justify-content:space-between;font-size:12.5px;color:var(--text2)}
.sl .t b{color:var(--text);font-variant-numeric:tabular-nums}
.sl input[type=range]{width:100%;accent-color:var(--accent)}
.sl.off .t b{color:var(--muted);font-weight:400}
.presets .chip{font-size:12px}
.desc{font-size:12px;color:var(--text2);background:var(--hover);border-radius:8px;padding:8px 10px;margin:0 0 12px}
.count{font-size:13px;color:var(--text2);margin-bottom:6px}
.count b{font-size:22px;color:var(--text);margin-right:2px}
.bar{height:6px;background:var(--grid);border-radius:3px;overflow:hidden;margin:4px 0 10px}
.bar div{height:100%;background:var(--accent)}
/* 業種マップ */
.hm-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
table.hm{border-collapse:separate;border-spacing:2px;width:100%;min-width:760px;font-variant-numeric:tabular-nums}
.hm th{font-size:11px;color:var(--muted);font-weight:500;padding:4px;cursor:pointer;white-space:nowrap;text-align:center}
.hm th.on{color:var(--text);font-weight:700}
.hm th:first-child,.hm td:first-child{position:sticky;left:0;background:var(--surface);z-index:1;text-align:left}
.hm td{padding:6px 6px;text-align:center;font-size:12.5px;border-radius:4px}
.hm td:first-child{font-size:12.5px;white-space:nowrap;cursor:pointer;color:var(--text)}
.hm td:first-child:hover{color:var(--accent)}
.hm td.n{color:var(--muted);font-size:11.5px}
.legend{display:flex;align-items:center;gap:6px;font-size:11px;color:var(--muted);margin:0 0 8px}
.legend i{width:22px;height:10px;border-radius:2px;display:inline-block}
footer{color:var(--muted);font-size:11px;margin:20px 0 10px;line-height:1.7}
@media (max-width:760px){
 .wrap{padding:12px 16px}
 .kpis{grid-template-columns:repeat(3,1fr)}.kpi:nth-child(n+4){display:none}
 .kpi .v{font-size:18px}
 .row{grid-template-columns:26px minmax(0,1fr) 40px;gap:4px 10px;padding:10px 2px}
 .row .strip{grid-column:2/4;grid-row:2}
 .row .mets{grid-column:2/4;grid-row:3;text-align:left}
 .lhead{padding:0 2px 4px}
 .lhead>div:nth-child(2),.lhead>div:nth-child(3),.lhead .mets{display:none}
 .lhead .strip{grid-row:1}
 .row:not(.lhead) .mets span{display:block}
 .strip i{height:18px;font-size:10px}
 .strip:not(.h)::before{content:none}
 .scr-grid{grid-template-columns:1fr}
 input[type=search]{width:100%}
 .filters>*{flex:0 1 auto}
 .tabs button{padding:9px 10px}
}
/* ===== 2026-11 デザイン刷新（トップ画面と共通）：黒／白地、枠線なしのカード、数字は Inter ===== */
:root{--surface:#fff;--page:#f3f4f6;--text:#0c0d10;--text2:#3d4148;--muted:#5b6068;--grid:#dfe2e7;--border:rgba(12,13,16,.13);--hover:rgba(12,13,16,.05)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--surface:#101216;--page:#050608;--text:#f2f4f8;--text2:#c6cbd6;--muted:#8f96a3;--grid:#23262d;--border:rgba(255,255,255,.13);--hover:rgba(255,255,255,.06)}}
:root[data-theme="dark"]{--surface:#101216;--page:#050608;--text:#f2f4f8;--text2:#c6cbd6;--muted:#8f96a3;--grid:#23262d;--border:rgba(255,255,255,.13);--hover:rgba(255,255,255,.06)}
body{font-family:Inter,"Hiragino Sans","Hiragino Kaku Gothic ProN","Noto Sans JP",system-ui,-apple-system,sans-serif;font-variant-numeric:tabular-nums;-webkit-font-smoothing:antialiased}
h1{font-weight:800}
</style></head>
<body><div class="wrap">
<header>
 <h1>__TITLE__</h1>
 <span class="sub" id="stamp"></span>
 <div class="hdr-r"><a class="btn" href="index.html">トップ</a>__OTHER__<button class="btn" id="thm" type="button">表示切替</button></div>
</header>

<div class="card filters">
 <div class="seg" id="mkt"><button class="on" data-m="">全市場</button><button data-m="プライム">プライム</button><button data-m="スタンダード">スタンダード</button><button data-m="グロース">グロース</button></div>
 <select id="sec"><option value="">すべての業種</option></select>
 <input type="search" id="q" placeholder="コード・銘柄名">
 <label class="ck"><input type="checkbox" id="xold" checked>決算が古い銘柄を除く</label>
 <label class="ck"><input type="checkbox" id="xloss">赤字を除く</label>
</div>

<div style="height:12px"></div>

<nav class="tabs" id="tabs">
 <button class="on" data-p="rank">ランキング</button><button data-p="scr">スクリーニング</button><button data-p="sec">業種マップ</button>
</nav>

<section class="pane on" id="p-rank">
 <div class="chips" id="sortchips"></div>
 <p class="hint" id="rankhint"></p>
 <div class="list" id="ranklist"></div>
 <button class="btn more" id="rankmore" type="button">さらに50件</button>
</section>

<section class="pane" id="p-scr">
 <div class="scr-grid">
  <div class="card">
   <div class="hint" style="margin-bottom:6px">定番の条件</div>
   <div class="chips presets" id="presets"></div>
   <details id="adj"><summary class="hint" style="margin:10px 0 6px;cursor:pointer">自分で調整（端＝条件なし）</summary>
   <div id="sliders"></div></details>
   <button class="btn" id="sreset" type="button">条件をリセット</button>
  </div>
  <div>
   <p class="desc" id="pdesc" hidden></p>
   <div class="count" style="display:flex;align-items:center;gap:8px;flex-wrap:wrap"><span><b id="scount">0</b>銘柄が該当 <span id="sshare"></span></span><button class="btn" id="scsv" type="button" style="margin-left:auto">CSVで保存</button></div>
   <div class="bar"><div id="sbar" style="width:0"></div></div>
   <div class="list" id="scrlist"></div>
   <button class="btn more" id="scrmore" type="button">さらに50件</button>
  </div>
 </div>
</section>

<section class="pane" id="p-sec">
 <div class="card">
  <div class="legend">業種ごとの中央値。色が濃いほど良い水準（PER・PBRは低いほど濃い）<span style="margin-left:auto"></span>
   <i class="s1"></i><i class="s2"></i><i class="s3"></i><i class="s4"></i><i class="s5"></i></div>
  <p class="hint">列名で並べ替え、業種名でその業種のランキングへ移動します。</p>
  <div class="hm-wrap"><table class="hm" id="hm"></table></div>
 </div>
</section>

<footer id="foot"></footer>
</div>

<script>
const D=__DATA__;
const K={};D.cols.forEach((c,i)=>K[c]=i);
const S=D.rows.map((r,i)=>{const o={i};D.cols.forEach((c,j)=>o[c]=r[j]);return o});
const AX=[['r1','成長','成長'],['r2','収益','収益'],['r3','安全','安全'],['r4','規模','規模'],['r5','割安','割安'],['r6','値上がり','値上']];
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const nz=v=>v!==null&&v!==undefined&&!Number.isNaN(v);
const f1=(v,d=1)=>nz(v)?v.toLocaleString('ja-JP',{minimumFractionDigits:d,maximumFractionDigits:d}):'—';
const capf=v=>!nz(v)?'—':v>=10000?f1(v/10000,1)+'兆':Math.round(v).toLocaleString('ja-JP')+'億';
function median(a){a=a.filter(nz).sort((x,y)=>x-y);if(!a.length)return null;const m=a.length>>1;return a.length%2?a[m]:(a[m-1]+a[m])/2}
function theme(){const t=document.documentElement.getAttribute('data-theme');return t||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light')}
$('thm').onclick=()=>{const r=document.documentElement;r.setAttribute('data-theme',theme()==='dark'?'light':'dark');try{localStorage.setItem('fdb-theme',r.getAttribute('data-theme'))}catch(e){}};
$('stamp').textContent=`株価 ${D.pxdate} 時点・${S.length.toLocaleString()}銘柄・生成 ${D.gen}`+(D.ver&&D.ver!=='標準版'?`・${D.ver}`:'');

/* ---------- 共通フィルタ ---------- */
const F={m:'',s:'',q:'',xold:true,xloss:false};
[...new Set(S.map(x=>x.s).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'ja')).forEach(s=>{const o=document.createElement('option');o.value=o.textContent=s;$('sec').appendChild(o)});
$('mkt').onclick=e=>{const b=e.target.closest('button');if(!b)return;F.m=b.dataset.m;[...$('mkt').children].forEach(x=>x.classList.toggle('on',x===b));render()};
$('sec').onchange=e=>{F.s=e.target.value;render()};
$('q').oninput=e=>{F.q=e.target.value.trim();render()};
$('xold').onchange=e=>{F.xold=e.target.checked;render()};
$('xloss').onchange=e=>{F.xloss=e.target.checked;render()};
function base(){const q=F.q.toLowerCase();return S.filter(x=>(!F.m||x.m===F.m)&&(!F.s||x.s===F.s)&&(!F.xold||!x.old)&&(!F.xloss||!x.loss)&&(!q||String(x.c).toLowerCase().includes(q)||String(x.n).toLowerCase().includes(q)))}


/* ---------- 銘柄行 ---------- */
const HEAD=`<div class="row lhead"><div class="rk">#</div><div>銘柄</div><div style="text-align:center">総合</div><div class="strip h">${AX.map(a=>`<i>${a[2]}</i>`).join('')}</div><div class="mets"><span>PER</span><span>PBR</span><span>ROE</span><span>利回り</span></div></div>`;
function row(x,n){
 const tags=(x.old?'<span class="tag w">決算古</span>':'')+(x.loss?'<span class="tag w">赤字</span>':'');
 const cell=v=>`<i class="s${nz(v)?v:0}">${nz(v)?v:'–'}</i>`;
 return `<div class="row"><div class="rk">${n}</div>
 <div class="nm"><a href="${esc(x.c)}.html?theme=${theme()}">${esc(x.n)}</a><span class="cd">${esc(x.c)}</span>
  <div class="meta">${tags}${esc(x.s)}・${esc(x.m)}・${capf(x.cap)}${x.biz?'｜'+esc(x.biz):''}</div></div>
 <div class="tot s${nz(x.tot)?x.tot:0}">${nz(x.tot)?x.tot:'–'}</div>
 <div class="strip" title="${AX.map(a=>a[1]+':'+(x[a[0]]??'–')).join(' ')}">${AX.map(a=>cell(x[a[0]])).join('')}</div>
 <div class="mets"><div><b>${x.per>0?f1(x.per):'—'}</b><span>PER</span></div><div><b>${f1(x.pbr,2)}</b><span>PBR</span></div><div><b>${f1(x.roe)}%</b><span>ROE</span></div><div><b>${f1(x.dy,2)}%</b><span>利回り</span></div></div></div>`}

/* ---------- ランキング ---------- */
const SORTS=[
 ['総合評価',(a,b)=>cmp(a.rank,b.rank)||dsc(a.tot,b.tot)||dsc(a.avg,b.avg),'総合評価（1〜5）→ 6項目の平均の順'],
 ['業種内偏差値',(a,b)=>dsc(a.dev,b.dev),'同じ業種の中でどれだけ優れているか（50が平均）'],
 ...AX.map(([k,l])=>[l,(a,b)=>dsc(a[k],b[k])||dsc(a.avg,b.avg)||dsc(a.dev,b.dev),`${l}の評価（1〜5）→ 6項目の平均の順`]),
 ['Fスコア',(a,b)=>dsc(a.fs,b.fs)||dsc(a.avg,b.avg),'ピオトロスキーFスコア（0〜9、財務の改善度）'],
 ['配当利回り',(a,b)=>dsc(a.dy,b.dy),'実績の配当利回りが高い順'],
 ['ROE',(a,b)=>dsc(a.roe,b.roe),'ROE（自己資本利益率）が高い順'],
 ['PER（低い順）',(a,b)=>cmp(a.per,b.per),'実績PERが低い順（赤字は除外）'],
];
function cmp(a,b){const A=nz(a),B=nz(b);if(!A&&!B)return 0;if(!A)return 1;if(!B)return -1;return a-b}   // 昇順・欠損は最後
function dsc(a,b){const A=nz(a),B=nz(b);if(!A&&!B)return 0;if(!A)return 1;if(!B)return -1;return b-a}   // 降順・欠損は最後
let sortI=0,rankN=50;
$('sortchips').innerHTML=SORTS.map((s,i)=>`<button class="chip${i?'':' on'}" data-i="${i}">${s[0]}</button>`).join('');
$('sortchips').onclick=e=>{const b=e.target.closest('.chip');if(!b)return;sortI=+b.dataset.i;rankN=50;[...$('sortchips').children].forEach(x=>x.classList.toggle('on',x===b));renderRank()};
$('rankmore').onclick=()=>{rankN+=50;renderRank()};
function renderRank(a=base()){
 const s=SORTS[sortI];let v=a.slice();
 if(s[0]==='PER（低い順）')v=v.filter(x=>x.per>0);
 v.sort(s[1]);
 $('rankhint').textContent=`並び: ${s[2]}。銘柄名をタップするとチャートが開きます。`;
 $('ranklist').innerHTML=v.length?HEAD+v.slice(0,rankN).map((x,i)=>row(x,i+1)).join(''):'<div class="empty">該当する銘柄がありません</div>';
 $('rankmore').hidden=v.length<=rankN}

/* ---------- スクリーニング ---------- */
// [key, ラベル, min, max, step, 単位, 方向('<='|'>='), 条件なしの位置]
const SL=[
 ['per','PER','≦',3,50,1,'倍'],['pbr','PBR','≦',0.3,5,0.1,'倍'],
 ['roe','ROE','≧',0,30,1,'%'],['dy','配当利回り','≧',0,7,0.25,'%'],['doe','DOE','≧',0,8,0.25,'%'],['nh','52週新高値からの日数','≦',0,60,1,'日'],
 ['eq','自己資本比率','≧',0,90,5,'%'],['gr','売上高成長率','≧',-10,40,1,'%'],
 ['opm','営業利益率','≧',0,40,1,'%'],['cap','時価総額','≧',0,20000,100,'億円'],
];
const SV={};SL.forEach(s=>SV[s[0]]=null);
let preset='',scrN=50,scrRes=[];
$('sliders').innerHTML=SL.map(([k,l,d,mn,mx,st])=>{const off=d==='≦'?mx:mn;return `<div class="sl off" id="sl-${k}"><div class="t"><span>${l} ${d}</span><b id="sv-${k}">条件なし</b></div><input type="range" min="${mn}" max="${mx}" step="${st}" value="${off}" data-k="${k}"></div>`}).join('');
$('sliders').oninput=e=>{const t=e.target;if(t.type!=='range')return;const s=SL.find(x=>x[0]===t.dataset.k);const v=+t.value;const off=s[2]==='≦'?s[4]:s[3];SV[s[0]]=v===off?null:v;slLabel(s);scrN=50;renderScr()};
function slLabel(s){const v=SV[s[0]];$('sl-'+s[0]).classList.toggle('off',v===null);$('sv-'+s[0]).textContent=v===null?'条件なし':(s[0]==='cap'?capf(v):f1(v,s[5]<1?(s[5]<.5?2:1):0)+s[6])}
const PRE=Object.entries(D.screens);
const PSET={};PRE.forEach(([n,s])=>PSET[n]=new Set(s.rows));
$('presets').innerHTML=`<button class="chip on" data-p="">なし</button>`+PRE.map(([n,s])=>`<button class="chip" data-p="${esc(n)}">${esc(n)}</button>`).join('');
$('presets').onclick=e=>{const b=e.target.closest('.chip');if(!b)return;preset=b.dataset.p;scrN=50;[...$('presets').children].forEach(x=>x.classList.toggle('on',x===b));renderScr()};
$('sreset').onclick=()=>{SL.forEach(s=>{SV[s[0]]=null;$('sl-'+s[0]).querySelector('input').value=s[2]==='≦'?s[4]:s[3];slLabel(s)});preset='';[...$('presets').children].forEach((x,i)=>x.classList.toggle('on',!i));renderScr()};
$('scrmore').onclick=()=>{scrN+=50;renderScr()};
/* CSV保存（Excelで文字化けしないようBOM付きUTF-8） */
const CSVC=[['順位',null],['コード','c'],['銘柄名','n'],['市場','m'],['業種','s'],['株価','px'],['時価総額(億円)','cap'],['PER','per'],['PBR','pbr'],['ROE(%)','roe'],['配当利回り(%)','dy'],['DOE(%)','doe'],['新高値からの日数','nh'],['上場来高値からの日数','ath'],['自己資本比率(%)','eq'],['売上高成長率(%)','gr'],['営業利益率(%)','opm'],['成長性評価','r1'],['収益性評価','r2'],['安全性評価','r3'],['規模評価','r4'],['割安度評価','r5'],['値上がり評価','r6'],['総合評価','tot'],['業種内偏差値','dev'],['Fスコア','fs'],['決算が古い','old'],['赤字','loss'],['事業概要','biz']];
function csvCell(v){if(v===null||v===undefined)return '';v=String(v);return /[",\n\r]/.test(v)?'"'+v.replace(/"/g,'""')+'"':v}
function condText(){const c=[];if(preset)c.push(preset);if(F.m)c.push(F.m);if(F.s)c.push(F.s);if(F.q)c.push('検索:'+F.q);
 SL.forEach(s=>{const v=SV[s[0]];if(v!==null)c.push(`${s[1]}${s[2]}${s[0]==='cap'?v+'億円':v+s[6]}`)});
 if(F.xold)c.push('決算が古い銘柄を除く');if(F.xloss)c.push('赤字を除く');return c.join(' / ')||'条件なし'}
$('scsv').onclick=()=>{
 const lines=[['# 条件',condText()],['# 株価日付',D.pxdate],['# 生成',D.gen],CSVC.map(c=>c[0])]
  .concat(scrRes.map((x,i)=>CSVC.map(([,k])=>k===null?i+1:(k==='old'||k==='loss')?(x[k]?'○':''):x[k])));
 const csv='﻿'+lines.map(r=>r.map(csvCell).join(',')).join('\r\n');
 const EN={'割安株':'value','成長株':'growth','高配当株':'dividend','安定優良株':'stable','高収益企業':'profitable','なごちょう式':'nagochou','DOE安定配当株':'doe','連続増配株':'div_growth','PEG割安成長株':'peg','新高値ブレイク株':'new_high','上場来高値更新株':'all_time_high','成長ブレイク株':'growth_breakout','マルチバガー候補':'multibagger','マルチバガー論文準拠':'multibagger_paper'}; // 論文スコア
 const name=`screening_${preset?(EN[preset]||'preset'):'custom'}_${D.pxdate}.csv`;  // 日本語名は一部ブラウザで無視されるため英字
 const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));a.download=name;
 document.body.appendChild(a);a.click();setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove()},1000)};
function renderScr(a=base()){
 const all=a.length;
 let v=a.filter(x=>!preset||PSET[preset].has(x.i));
 for(const s of SL){const t=SV[s[0]];if(t===null)continue;v=v.filter(x=>{const y=x[s[0]];if(!nz(y))return false;if(s[0]==='per'&&y<=0)return false;return s[2]==='≦'?y<=t:y>=t})}
 v.sort(SORTS[0][1]);
 scrRes=v;$('scsv').disabled=!v.length;
 const pd=$('pdesc');pd.hidden=!preset;if(preset)pd.textContent=D.screens[preset].desc;
 $('scount').textContent=v.length.toLocaleString();
 $('sshare').textContent=`／ ${all.toLocaleString()}銘柄中（${all?f1(v.length/all*100):0}%）・総合評価の高い順`;
 $('sbar').style.width=(all?v.length/all*100:0)+'%';
 $('scrlist').innerHTML=v.length?HEAD+v.slice(0,scrN).map((x,i)=>row(x,i+1)).join(''):'<div class="empty">条件に合う銘柄がありません。条件をゆるめてください。</div>';
 $('scrmore').hidden=v.length<=scrN}

/* ---------- 業種マップ ---------- */
// [key, ラベル, 良い向き(+1高いほど良い / -1低いほど良い / 0色なし), 小数桁, 単位]
const HC=[['n','銘柄数',0,0,''],['tot','総合評価',1,1,''],['per','PER',-1,1,'倍'],['pbr','PBR',-1,2,'倍'],['roe','ROE',1,1,'%'],['opm','営業利益率',1,1,'%'],['gr','売上成長率',1,1,'%'],['dy','配当利回り',1,2,'%'],['eq','自己資本比率',1,0,'%']];
let hmSort='tot',hmDir=-1;
function renderSec(){
 // 業種マップは業種フィルタ・検索を無視（市場・古い・赤字だけ効かせる）
 const a=S.filter(x=>(!F.m||x.m===F.m)&&(!F.xold||!x.old)&&(!F.xloss||!x.loss));
 const g={};a.forEach(x=>{(g[x.s]=g[x.s]||[]).push(x)});
 const rows=Object.entries(g).map(([s,xs])=>{const o={s,n:xs.length};HC.slice(1).forEach(([k])=>o[k]=median(xs.map(x=>(k==='per'||k==='pbr')?(x[k]>0?x[k]:null):x[k])));return o});
 // 業種間の順位で5段階の濃さ
 const lvl={};HC.forEach(([k,,dir])=>{if(!dir)return;const vs=rows.map(r=>r[k]).filter(nz).sort((x,y)=>x-y);lvl[k]=v=>{if(!nz(v)||vs.length<2)return 0;let p=vs.indexOf(v)/(vs.length-1);if(dir<0)p=1-p;return 1+Math.min(4,Math.floor(p*5))}});
 rows.sort((x,y)=>hmSort==='s'?x.s.localeCompare(y.s,'ja')*hmDir:(hmDir<0?dsc(x[hmSort],y[hmSort]):cmp(x[hmSort],y[hmSort])));
 $('hm').innerHTML=`<thead><tr><th data-k="s" class="${hmSort==='s'?'on':''}">業種</th>${HC.map(([k,l])=>`<th data-k="${k}" class="${hmSort===k?'on':''}">${l}${hmSort===k?(hmDir<0?' ▼':' ▲'):''}</th>`).join('')}</tr></thead><tbody>`+
  rows.map(r=>`<tr><td data-s="${esc(r.s)}">${esc(r.s)}</td>${HC.map(([k,,dir,dg,u])=>dir?`<td class="s${lvl[k](r[k])}">${f1(r[k],dg)}${nz(r[k])?u:''}</td>`:`<td class="n">${r[k]}</td>`).join('')}</tr>`).join('')+'</tbody>';
}
$('hm').onclick=e=>{const th=e.target.closest('th');if(th){const k=th.dataset.k;if(hmSort===k)hmDir*=-1;else{hmSort=k;hmDir=(k==='per'||k==='pbr'||k==='s')?1:-1}renderSec();return}
 const td=e.target.closest('td[data-s]');if(td){F.s=td.dataset.s;$('sec').value=F.s;go('rank');render();window.scrollTo({top:0,behavior:'smooth'})}};

/* ---------- タブ・描画 ---------- */
function go(p){[...$('tabs').children].forEach(b=>b.classList.toggle('on',b.dataset.p===p));document.querySelectorAll('.pane').forEach(x=>x.classList.toggle('on',x.id==='p-'+p));try{sessionStorage.setItem('fs-tab',p)}catch(e){}}
$('tabs').onclick=e=>{const b=e.target.closest('button');if(b)go(b.dataset.p)};
function render(){const a=base();renderRank(a);renderScr(a);renderSec()}
try{const t=sessionStorage.getItem('fs-tab');if(t)go(t)}catch(e){}
$('foot').innerHTML='評価は1〜5の5段階（5が最良）。成長=売上高CAGR、収益=経常利益率の平均（IFRS等は税引前利益）、安全=自己資本比率（金融は業法指標）、規模=時価総額、割安=会社予想PER（予想なしは実績PER、赤字はPBR）、値上がり=250日騰落率の順位。<br>一覧のPERは実績ベース。会社予想は決算短信（J-Quants と TDnet。発表当日の値）。データ元: Yahoo Finance ほか。投資判断はご自身の責任で行ってください。';
if(innerWidth>760)$('adj').open=true;
render();
</script>
</body></html>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", default="fundamentals/analysis/dashboard_data.json")
    ap.add_argument("--out", default="data/charts/fundamentals_simple.html")
    ap.add_argument("--title", default="東証スクリーニング")
    ap.add_argument("--full-url", default="fundamentals.html", help="詳細版ページへのリンク先")
    ap.add_argument("--other-url", default="", help="もう一方の版（金融除外版など）へのリンク先")
    ap.add_argument("--other-label", default="")
    a = ap.parse_args()
    src = Path(a.src) if Path(a.src).is_absolute() else BASE / a.src
    out = Path(a.out) if Path(a.out).is_absolute() else BASE / a.out
    build(src, out, a.title, a.full_url, a.other_url, a.other_label)


if __name__ == "__main__":
    main()
