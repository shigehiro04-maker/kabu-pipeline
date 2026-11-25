#!/usr/bin/env python3
"""デイトレ チャートパターンのページ data/charts/daytrade.html を作る（中身は daytrade/*.json を読み込んで表示）。

  python dtp_page.py --market jp
  python dtp_page.py --market us
"""
import argparse
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dtp_core as C  # noqa: E402
import dtp_data as D  # noqa: E402

RULES = {
    "U1": "下げてきて、ほぼ同じ高さの安値を2回つけた形。間の高値（ネックライン）を終値で上抜けたら買い。目標＝ネックライン＋底からネックラインまでの値幅、損切り＝2つの安値の低い方。",
    "U2": "真ん中の安値（頭）が一番低い3つの安値。左右の肩の間の高値を結んだネックラインを上抜けたら買い。目標＝ネックライン＋頭からネックラインまでの値幅、損切り＝右肩の安値。",
    "U3": "高値がほぼ水平、安値が切り上がる三角形。水平の高値を上抜けたら買い。目標＝高値＋三角形の高さ、損切り＝直近の安値。",
    "U4": "左右の縁がほぼ同じ高さで底が丸いカップ（ATR×4以上の深さ・2時間以上の幅）の後、浅い押し（取っ手）。縁の高さを上抜けたら買い。目標＝縁＋カップの深さ、損切り＝取っ手の安値。",
    "U5": "短時間の急上昇（旗ざお：ATR×5以上）の後、平行に下がる小さな値動き（旗）。旗の上の線を上抜けたら買い。目標＝抜けた所＋旗ざおの高さ、損切り＝旗の安値。",
    "U6": "旗ざおの後、高値切り下げ・安値切り上げで小さく収束（ペナント）。上の線を上抜けたら買い。目標＝抜けた所＋旗ざおの高さ、損切り＝直近の安値。",
    "U7": "高値・安値とも切り下がりながら値幅が縮む形（拡大しない）。上の線を上抜けたら買い。目標＝形の始まりの高値、損切り＝直近の安値。",
    "U8": "抵抗線（前の高値）を上抜けた後、その高さまで押して反発（サポート反発）。安値からの反発が確定した足で買い。目標＝直近の高値、損切り＝押した安値。",
    "U9": "上向きの移動平均線（5分足25本）の上で推移していた株価が、線まで押して陽線で反発した足で買い。目標＝直近20本の高値、損切り＝直近3本の安値（または線の少し下）。",
    "U10": "2回以上はね返された水平の抵抗線を終値で上抜けたら買い。目標＝抵抗線＋そこまでの値幅、損切り＝直近の安値。",
    "D1": "上げてきて、ほぼ同じ高さの高値を2回つけた形。間の安値（ネックライン）を終値で下抜けたら売り。",
    "D2": "真ん中の高値（頭）が一番高い3つの高値。ネックラインを下抜けたら売り。",
    "D3": "安値がほぼ水平、高値が切り下がる三角形（直前は上昇・もみ合い＝天井圏で出たもの）。水平の安値を下抜けたら売り。",
    "D4": "安値がほぼ水平、高値が切り下がる三角形のうち、下落の途中で出たもの（直前3時間で ATR×2 以上の下落）。水平の安値を下抜けたら売り。",
    "D5": "短時間の急落（旗ざお）の後、平行に上がる小さな値動き。旗の下の線を下抜けたら売り。",
    "D6": "急落の後、小さな三角形に収束。下の線を下抜けたら売り。",
    "D7": "高値・安値とも切り上がりながら値幅が縮む形。下の線を下抜けたら売り。",
    "D8": "支持線を下抜けた後、その高さまで戻して反落（レジスタンス反発）。高値からの反落が確定した足で売り。",
    "D9": "下向きの移動平均線の下で推移していた株価が、線まで戻して陰線で反落した足で売り。",
    "D10": "2回以上支えられた水平の支持線を終値で下抜けたら売り。",
    "O1+": "高値と安値がそれぞれ2回以上そろう箱（ボックス圏）。上の線を上抜けたら買い。損切り＝箱の真ん中。",
    "O1-": "ボックス圏の下の線を下抜けたら売り。損切り＝箱の真ん中。",
    "O2+": "平行に上がる2本の線（上昇チャネル）の下の線まで押して反発したら買い。目標＝上の線。",
    "O2-": "平行に下がる2本の線（下降チャネル）の上の線まで戻して反落したら売り。目標＝下の線。",
    "O3+": "前日の終値から ATR×1.5・0.4%以上の窓を開けて寄り付き、窓を埋めずに最初の15分の高値を上抜けたら買い（寄り付きから1時間以内）。目標＝窓の幅、損切り＝最初の15分の安値。",
    "O3-": "窓を開けて下に寄り付き、窓を埋めずに最初の15分の安値を下抜けたら売り。",
    "O4+": "旗ざおの無い三角保ち合い（高値切り下げ・安値切り上げ）を上抜けたら買い。目標＝三角形の高さ。",
    "O4-": "三角保ち合いを下抜けたら売り。",
}

TV = {"jp": [["すべて", 0], ["1億円以上", 100], ["10億円以上", 1000], ["50億円以上", 5000]],
      "us": [["すべて", 0], ["100万ドル以上", 1], ["1,000万ドル以上", 10], ["1億ドル以上", 100]]}
TVDEF = {"jp": 100, "us": 10}

HTML = r"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>デイトレ チャートパターン（5分足）— __MKT__</title>
<style>
:root{--bg:#f3f4f6;--card:#fff;--fg:#0c0d10;--fg2:#3d4148;--mut:#5b6068;--line:#dfe2e7;--up:#b91c24;--dn:#08705a;--upb:#c8323a;--dnb:#0f7f63;--hl:#2563eb;--tg:#b45309;color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#050608;--card:#101216;--fg:#f2f4f8;--fg2:#c6cbd6;--mut:#8f96a3;--line:#23262d;--up:#ff7378;--dn:#3fd0a4;--upb:#e0484f;--dnb:#20a882;--hl:#7aa7ff;--tg:#f0b44c;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#050608;--card:#101216;--fg:#f2f4f8;--fg2:#c6cbd6;--mut:#8f96a3;--line:#23262d;--up:#ff7378;--dn:#3fd0a4;--upb:#e0484f;--dnb:#20a882;--hl:#7aa7ff;--tg:#f0b44c;color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.55 Inter,"Hiragino Sans","Hiragino Kaku Gothic ProN","Noto Sans JP",system-ui,-apple-system,sans-serif;font-variant-numeric:tabular-nums;-webkit-font-smoothing:antialiased}
main{max-width:1400px;margin:0 auto;padding:22px 18px 60px}
h1{font-size:22px;margin:0 0 4px;display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
h1 a{color:var(--fg);text-decoration:none;font-weight:400}
h1 small{font-size:12.5px;color:var(--mut);font-weight:600}
.st{font-size:13px;color:var(--fg2);margin:2px 0 14px}.st b{font-weight:800}
.live{display:inline-block;background:var(--upb);color:#fff;border-radius:6px;padding:0 7px;font-size:11.5px;font-weight:800;margin-right:6px}
.closed{display:inline-block;background:var(--fg);color:var(--bg);border-radius:6px;padding:0 7px;font-size:11.5px;font-weight:800;margin-right:6px}
.tabs{display:flex;gap:4px;border-bottom:2px solid var(--fg);margin:10px 0 12px;overflow-x:auto}
.tabs button{border:0;background:transparent;color:var(--mut);font:inherit;font-weight:800;padding:8px 12px;cursor:pointer;white-space:nowrap;border-radius:10px 10px 0 0}
.tabs button.on{background:var(--fg);color:var(--bg)}
.tabs button small{font-weight:700;margin-left:4px;opacity:.8}
.bar{display:flex;flex-wrap:wrap;gap:8px 12px;align-items:center;margin-bottom:10px}
.seg{display:inline-flex;background:var(--card);border-radius:10px;padding:3px;gap:2px}
.seg button{border:0;background:transparent;color:var(--fg);font:inherit;font-size:13px;font-weight:700;padding:5px 11px;border-radius:8px;cursor:pointer}
.seg button.on{background:var(--fg);color:var(--bg)}
select,input[type=search]{font:inherit;font-size:13px;background:var(--card);color:var(--fg);border:1px solid var(--line);border-radius:8px;padding:5px 8px;height:34px}
input[type=search]{width:200px}
label.ck{font-size:13px;display:inline-flex;gap:5px;align-items:center;cursor:pointer;user-select:none}
.cnt{font-size:12.5px;color:var(--mut)}
.tw{overflow-x:auto;background:var(--card);border-radius:14px}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:7px 9px;text-align:right;white-space:nowrap;border-top:1px solid var(--line)}
thead th{border-top:0;border-bottom:2px solid var(--fg);font-size:11.5px;font-weight:800;cursor:pointer;user-select:none;position:sticky;top:0;background:var(--card)}
th.l,td.l{text-align:left}
tbody tr.r{cursor:pointer}tbody tr.r:hover{background:color-mix(in srgb,var(--fg) 5%,transparent)}
tbody tr.open{background:color-mix(in srgb,var(--fg) 7%,transparent)}
td.nm{max-width:15em;overflow:hidden;text-overflow:ellipsis}td.nm b{font-weight:800;margin-right:6px}td.nm span{color:var(--fg2)}
.pt{font-weight:700}.pt i{font-style:normal;margin-right:3px}
.b{display:inline-block;border-radius:6px;padding:0 7px;font-size:11.5px;font-weight:800;color:#fff}
.b.u{background:var(--upb);color:#fff}.b.d{background:var(--dnb);color:#fff}
.u{color:var(--up)}.d{color:var(--dn)}.m{color:var(--mut)}
.res{font-weight:700}
.det td{padding:10px 12px;white-space:normal;text-align:left;background:var(--bg)}
.dw{display:grid;grid-template-columns:minmax(0,1.7fr) minmax(260px,1fr);gap:14px}
.ch{background:var(--card);border-radius:12px;padding:8px}
.ch svg{width:100%;height:auto;display:block}
.ch .lg{font-size:11.5px;color:var(--mut);display:flex;gap:12px;flex-wrap:wrap;padding:2px 4px}
.info{background:var(--card);border-radius:12px;padding:10px 12px;font-size:13px}
.info h4{margin:0 0 6px;font-size:14px}
.info table{font-size:12.5px}.info td,.info th{padding:4px 6px}
.info p{margin:6px 0;color:var(--fg2)}
.lk{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}
.lk a{font-size:12.5px;font-weight:800;color:var(--fg);text-decoration:none;border:1px solid var(--line);border-radius:8px;padding:4px 10px}
.more{display:block;margin:10px auto 0;border:0;background:var(--card);color:var(--fg);font:inherit;font-weight:800;padding:8px 18px;border-radius:10px;cursor:pointer}
.note{font-size:12.5px;color:var(--mut)}
.doc{background:var(--card);border-radius:14px;padding:14px 18px;font-size:13.5px;color:var(--fg2)}
.doc h3{color:var(--fg);font-size:15px;margin:16px 0 6px}.doc h3:first-child{margin-top:0}
.doc dl{margin:0}.doc dt{font-weight:800;color:var(--fg);margin-top:8px}.doc dd{margin:2px 0 0 0}
.warn{background:color-mix(in srgb,var(--tg) 14%,var(--card));border-radius:12px;padding:10px 14px;font-size:13px;margin:0 0 12px;color:var(--fg)}
.grp td{background:var(--bg);font-weight:800;text-align:left;font-size:12.5px}
.empty{padding:30px;text-align:center;color:var(--mut)}
@media(max-width:860px){.dw{grid-template-columns:minmax(0,1fr)}}
@media(max-width:760px){main{padding:14px 8px 50px}h1{font-size:18px}.hs{display:none}td.nm{max-width:9em}
 select,input[type=search]{font-size:16px;height:36px}input[type=search]{width:100%}th,td{padding:7px 6px}
 .det td{padding:8px 6px}.det .dw{position:sticky;left:6px;width:calc(100vw - 32px)}td.nm span{display:none}}
</style></head><body><main>
<h1><a href="../../charts/index.html" title="トップへ">‹</a>デイトレ チャートパターン<small>5分足・__MKT__・22パターン</small></h1>
<div class="st" id="st">読み込み中…</div>
<div class="tabs" id="tabs">
 <button data-t="sig" class="on">シグナル<small id="nSig"></small></button>
 <button data-t="form">形成中（ブレイク待ち）<small id="nForm"></small></button>
 <button data-t="stat">パターン別の成績</button>
 <button data-t="doc">見方</button>
</div>
<section id="p-list">
 <div class="bar">
  <div class="seg" id="dir"><button data-v="0" class="on">すべて</button><button data-v="1">買い</button><button data-v="-1">売り</button></div>
  <select id="pat"></select>
  <select id="tv" title="1日の売買代金（直近5日の平均）"></select>
  <label class="ck"><input type="checkbox" id="vol">出来高増加（1.5倍以上）</label>
  <label class="ck"><input type="checkbox" id="good">成績がプラスのパターンだけ</label>
  <label class="ck" id="newL" hidden><input type="checkbox" id="newOnly">直近15分だけ</label>
  <input type="search" id="q" placeholder="コード・銘柄名" autocomplete="off">
  <span class="cnt" id="cnt"></span>
 </div>
 <div class="tw"><table><thead id="th"></thead><tbody id="tb"></tbody></table></div>
 <button class="more" id="more" type="button" hidden>さらに表示</button>
 <p class="note" id="lnote"></p>
</section>
<section id="p-stat" hidden></section>
<section id="p-doc" hidden></section>
</main>
<script>
const CH='../../charts/', MK=__MK__, RULES=__RULES__, TVS=__TVS__, TVDEF=__TVDEF__, GROUPN={U:'上昇パターン（買い）',D:'下落パターン（売り）',O:'その他・継続パターン'};
const $=id=>document.getElementById(id);
const LS=(k,v)=>{try{if(v===undefined)return localStorage.getItem(k);localStorage.setItem(k,v)}catch(e){return null}};
const SK='dtp-'+MK.key+'-';
let D=null,S=null,tab=LS(SK+'tab')||'sig',sortK=null,sortA=false,shown=200,openKey=null;
const st={dir:+(LS(SK+'dir')||0),pat:LS(SK+'pat')||'',tv:LS(SK+'tv')!==null?+LS(SK+'tv'):TVDEF,vol:LS(SK+'vol')==='1',good:LS(SK+'good')==='1',newOnly:false,q:''};
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function px(v){ if(v==null)return '―'; const a=Math.abs(v);
  if(MK.key==='jp') return a>=1000?v.toLocaleString('ja-JP',{maximumFractionDigits:0}):v.toLocaleString('ja-JP',{maximumFractionDigits:1});
  return a>=1?v.toFixed(2):v.toFixed(4); }
function pct(v,dg=2){ if(v==null||!isFinite(v))return '―'; return (v>0?'+':'')+v.toFixed(dg)+'%'; }
function cls(v){ return v>0?'u':v<0?'d':'m'; }
function tvTxt(m){ if(m==null)return '―'; if(MK.key==='jp'){ return m>=100?(m/100).toLocaleString('ja-JP',{maximumFractionDigits:m>=1000?0:1})+'億円':Math.round(m*100)/100+'百万円'; }
  return m>=100?(m/100).toFixed(m>=1000?0:1)+'億ドル':m>=1?m.toFixed(1)+'百万ドル':(m*100).toFixed(0)+'万ドル'; }
function pn(k){ const p=D.patterns[k]; return p?p[0]+' '+p[1]:k; }
function pdir(k){ const p=D.patterns[k]; return p?p[2]:0; }
function sOf(k){ return S&&S.patterns&&S.patterns[k]; }

async function load(){
  const bust='?t='+Math.floor(Date.now()/60000);
  try{
    const [a,b]=await Promise.all([fetch('./daytrade/latest.json'+bust).then(r=>r.json()),fetch('./daytrade/stats.json'+bust).then(r=>r.ok?r.json():null).catch(()=>null)]);
    D=a;S=b;
  }catch(e){ $('st').textContent='データを読み込めませんでした（'+e+'）'; return; }
  head(); setupFilters(); setTab(tab); render();
  if(D.live) setTimeout(()=>location.reload(),5*60*1000);
}
function head(){
  const md=D.day.slice(5).replace('-','/');
  const tag=D.live?'<span class="live">取引中</span>':'<span class="closed">'+(D.mode==='live'?'取引終了':'大引け後')+'</span>';
  const dly=D.live&&MK.key==='jp'?'（Yahoo の株価は約20分遅れ）':D.live?'（Yahoo の株価。数分の遅れがあります）':'';
  $('st').innerHTML=tag+md+' '+esc(D.asof)+'（'+MK.tz+'）までの5分足で判定'+dly+'　<span class="m">作成 '+esc(D.made)+'（日本時間）・'+D.scanned.toLocaleString()+'銘柄</span>';
  $('nSig').textContent=D.sig.length.toLocaleString(); $('nForm').textContent=D.form.length.toLocaleString();
  $('newL').hidden=!D.live;
}
function setupFilters(){
  const ps=Object.keys(D.patterns);
  let h='<option value="">パターン：すべて</option>';
  for(const g of ['U','D','O']){ h+='<optgroup label="'+GROUPN[g]+'">'; for(const k of ps.filter(k=>k[0]===g)) h+='<option value="'+k+'">'+esc(pn(k))+'</option>'; h+='</optgroup>'; }
  $('pat').innerHTML=h; $('pat').value=st.pat;
  $('tv').innerHTML=TVS.map(([n,v])=>'<option value="'+v+'">売買代金：'+n+'</option>').join(''); $('tv').value=String(st.tv);
  if(!$('tv').value){ st.tv=TVDEF; $('tv').value=String(TVDEF); }
  $('vol').checked=st.vol; $('good').checked=st.good;
  for(const b of $('dir').children) b.classList.toggle('on',+b.dataset.v===st.dir);
  $('dir').onclick=e=>{const b=e.target.closest('button'); if(!b)return; st.dir=+b.dataset.v; LS(SK+'dir',st.dir); for(const x of $('dir').children)x.classList.toggle('on',x===b); shown=200; render();};
  $('pat').onchange=()=>{st.pat=$('pat').value;LS(SK+'pat',st.pat);shown=200;render();};
  $('tv').onchange=()=>{st.tv=+$('tv').value;LS(SK+'tv',st.tv);shown=200;render();};
  $('vol').onchange=()=>{st.vol=$('vol').checked;LS(SK+'vol',st.vol?'1':'0');shown=200;render();};
  $('good').onchange=()=>{st.good=$('good').checked;LS(SK+'good',st.good?'1':'0');shown=200;render();};
  $('newOnly').onchange=()=>{st.newOnly=$('newOnly').checked;shown=200;render();};
  $('q').oninput=()=>{st.q=$('q').value.trim().toLowerCase();shown=200;render();};
  $('more').onclick=()=>{shown+=200;render();};
  $('tabs').onclick=e=>{const b=e.target.closest('button'); if(b) setTab(b.dataset.t);};
}
function setTab(t){
  tab=t; LS(SK+'tab',t);
  for(const b of $('tabs').children) b.classList.toggle('on',b.dataset.t===t);
  $('p-list').hidden=!(t==='sig'||t==='form'); $('p-stat').hidden=t!=='stat'; $('p-doc').hidden=t!=='doc';
  sortK=null; shown=200; openKey=null;
  if(t==='stat') renderStat(); else if(t==='doc') renderDoc(); else render();
}
function pass(code,key,volr){
  const inf=D.info[code]||[];
  if(st.dir&&pdir(key)!==st.dir) return false;
  if(st.pat&&key!==st.pat) return false;
  if(st.tv&&(inf[2]==null||inf[2]<st.tv)) return false;
  if(st.good){ const s=sOf(key); if(!s||!(s.avg>0)) return false; }
  if(st.q){ const n=(code+' '+(inf[0]||'')).toLowerCase(); if(!n.includes(st.q)) return false; }
  return true;
}
function resTxt(hit,pnl,ago){
  if(D.mode==='close'&&hit==='open') return '<span class="m">大引けの足</span>';
  if(hit==='target') return '<span class="res u">目標到達 '+pct(pnl)+'</span>';
  if(hit==='stop') return '<span class="res d">損切り '+pct(pnl)+'</span>';
  if(hit==='open') return '<span class="m">直後</span>';
  const lab=D.live&&D.mode==='live'?'途中 ':'大引け ';
  return '<span class="res '+cls(pnl)+'">'+lab+pct(pnl)+'</span>';
}
function statTxt(k){ const s=sOf(k); if(!s) return '<span class="m">―</span>';
  return '<span title="過去'+s.n.toLocaleString()+'回">'+s.win.toFixed(0)+'%・<span class="'+cls(s.avg)+'">'+pct(s.avg,2)+'</span></span>'; }
const COLS_SIG=[['時刻','l',r=>r[1]],['銘柄','l',r=>r[0]],['パターン','l',r=>r[2]],['エントリー','',r=>r[3]],['目標','hs',r=>r[4]],['損切り','hs',r=>r[5]],
  ['結果','',r=>r[9]],['過去の勝率・平均損益','',r=>(sOf(r[2])||{}).avg??-99],['出来高','hs',r=>r[7]??0],['売買代金','hs',r=>(D.info[r[0]]||[])[2]??0]];
const COLS_FORM=[['銘柄','l',r=>r[0]],['パターン','l',r=>r[1]],['現在値','',r=>(D.info[r[0]]||[])[3]],['抜ける線','',r=>r[2]],['あと','',r=>Math.abs(r[5])],
  ['目標','hs',r=>r[3]],['損切り','hs',r=>r[4]],['過去の勝率・平均損益','',r=>(sOf(r[1])||{}).avg??-99],['売買代金','hs',r=>(D.info[r[0]]||[])[2]??0]];
function render(){
  if(!D) return;
  const isSig=tab==='sig', cols=isSig?COLS_SIG:COLS_FORM;
  let rows=isSig?D.sig.filter(r=>pass(r[0],r[2],r[7])&&(!st.vol||(r[7]||0)>=1.5)&&(!st.newOnly||r[10]<=3)):D.form.filter(r=>pass(r[0],r[1]));
  if(sortK!==null){ const f=cols[sortK][2]; rows=rows.slice().sort((a,b)=>{const x=f(a),y=f(b); return (x<y?-1:x>y?1:0)*(sortA?1:-1);}); }
  else if(!isSig) rows=rows.slice().sort((a,b)=>Math.abs(a[6])-Math.abs(b[6]));
  $('th').innerHTML='<tr>'+cols.map((c,i)=>'<th class="'+c[1]+'" data-i="'+i+'">'+c[0]+(sortK===i?(sortA?' ▲':' ▼'):'')+'</th>').join('')+'</tr>';
  $('th').onclick=e=>{const th=e.target.closest('th'); if(!th)return; const i=+th.dataset.i; if(sortK===i)sortA=!sortA; else {sortK=i;sortA=false;} render();};
  const out=[];
  for(const r of rows.slice(0,shown)){
    const code=r[0], inf=D.info[code]||[], key=isSig?r[2]:r[1], dd=pdir(key), ky=isSig?key+'|'+r[1]:key+'|形成中';
    const nm='<td class="l nm"><b>'+esc(code)+'</b><span>'+esc(inf[0]||'')+'</span></td>';
    const pt='<td class="l"><span class="b '+(dd>0?'u':'d')+'">'+(dd>0?'買い':'売り')+'</span> <span class="pt">'+esc(pn(key))+'</span></td>';
    const id=code+'|'+ky;
    let tr;
    if(isSig){
      tr='<td class="l">'+esc(r[1])+'</td>'+nm+pt+'<td>'+px(r[3])+'</td><td class="hs">'+px(r[4])+'</td><td class="hs">'+px(r[5])+'</td><td>'+resTxt(r[8],r[9],r[10])+'</td><td>'+statTxt(key)+'</td>'
        +'<td class="hs">'+(r[7]==null?'―':(r[7]>=1.5?'<b>':'')+r[7].toFixed(1)+'倍'+(r[7]>=1.5?'</b>':''))+'</td><td class="hs">'+tvTxt(inf[2])+'</td>';
    }else{
      tr=nm+pt+'<td>'+px(inf[3])+'</td><td>'+px(r[2])+'</td><td>'+(Math.abs(r[5]).toFixed(2))+'%</td><td class="hs">'+px(r[3])+'</td><td class="hs">'+px(r[4])+'</td><td>'+statTxt(key)+'</td><td class="hs">'+tvTxt(inf[2])+'</td>';
    }
    out.push('<tr class="r'+(openKey===id?' open':'')+'" data-id="'+esc(id)+'">'+tr+'</tr>');
    if(openKey===id) out.push('<tr class="det"><td colspan="'+cols.length+'" id="detc"></td></tr>');
  }
  $('tb').innerHTML=out.join('')||'<tr><td class="empty" colspan="'+cols.length+'">条件に合う銘柄はありません</td></tr>';
  $('more').hidden=rows.length<=shown;
  $('cnt').textContent=rows.length.toLocaleString()+'件'+(rows.length>shown?'（'+shown+'件を表示）':'');
  $('lnote').innerHTML=isSig
    ?'エントリー＝シグナルが出た5分足の終値。結果＝その後、目標と損切りのどちらに先に届いたか（どちらも無ければ大引けの値）。「過去の勝率・平均損益」は同じパターンの過去の成績（パターン別の成績のタブ）。行を押すとチャート。'
    :'形があと少しで完成する銘柄（抜ける線まで ATR×1.5 以内）。「あと」＝現在値から抜ける線までの距離。線を終値で抜けたらシグナルになります。行を押すとチャート。';
  $('tb').onclick=e=>{const tr=e.target.closest('tr.r'); if(!tr)return; openKey=openKey===tr.dataset.id?null:tr.dataset.id; render(); if(openKey) detail(openKey);};
}

// ---------------- 詳細（チャート）
const shardCache={}, intraCache={};
function shardOf(code){ let s=0; for(const ch of code) s+=ch.codePointAt(0); return s%D.nshard; }
function getShard(i){ if(!shardCache[i]) shardCache[i]=fetch('./daytrade/b'+i+'.json?t='+Math.floor(Date.now()/60000)).then(r=>r.json()); return shardCache[i]; }
function getIntra(code){
  if(!intraCache[code]) intraCache[code]=new Promise(res=>{ const s=document.createElement('script'); window.INTRA=undefined;
    s.src=CH+'intra/'+encodeURIComponent(code)+'.js'; s.onload=()=>{res(window.INTRA||null);}; s.onerror=()=>res(null); document.head.appendChild(s); });
  return intraCache[code];
}
const hm=n=>{n=String(n).padStart(4,'0'); return n.slice(0,2)+':'+n.slice(2);};
async function detail(id){
  const [code,key,tm]=id.split('|');
  const box=$('detc'); if(!box) return;
  box.innerHTML='<div class="dw"><div class="ch" id="chb">チャートを読み込み中…</div><div class="info" id="inb"></div></div>';
  $('inb').innerHTML=infoHtml(code,key,tm);
  const [sh,it]=await Promise.all([getShard(shardOf(code)),getIntra(code)]);
  if(openKey!==id) return;
  const rec=(sh||{})[code]||{}; const dr=(rec.d||[]).find(x=>x.k===key+'|'+tm);
  let bars=[];
  if(it&&it.r){ for(const r of it.r) bars.push({t:it.d[r[0]]+' '+hm(r[1]),o:r[2],h:r[3],l:r[4],c:r[5]}); }
  if(rec.t){ const seen=new Set(bars.map(b=>b.t)); for(const r of rec.t){ const t=D.day+' '+hm(r[0]); if(!seen.has(t)) bars.push({t,o:r[1],h:r[2],l:r[3],c:r[4]}); } }
  bars.sort((a,b)=>a.t<b.t?-1:a.t>b.t?1:0);
  if(!bars.length||!dr){ $('chb').textContent='チャートのデータがありません'; return; }
  $('chb').innerHTML=chartSvg(bars,dr,code,key,tm);
}
function infoHtml(code,key,tm){
  const inf=D.info[code]||[], s=sOf(key), dd=pdir(key);
  const sig=tm==='形成中'?D.form.find(r=>r[0]===code&&r[1]===key):D.sig.find(r=>r[0]===code&&r[2]===key&&r[1]===tm);
  let h='<h4>'+esc(code)+' '+esc(inf[0]||'')+'</h4>';
  h+='<div><span class="b '+(dd>0?'u':'d')+'">'+(dd>0?'買い':'売り')+'</span> <b>'+esc(pn(key))+'</b>'+(tm==='形成中'?'（形成中）':'　'+esc(tm))+'</div>';
  h+='<p>'+esc(RULES[key]||'')+'</p>';
  if(inf[3]!=null) h+='<div>現在値 <b>'+px(inf[3])+'</b>'+(inf[4]!=null?'　前日比 <b class="'+cls(inf[4])+'">'+pct(inf[4])+'</b>':'')+'　売買代金 '+tvTxt(inf[2])+'/日</div>';
  if(sig&&tm!=='形成中') h+='<div>エントリー <b>'+px(sig[3])+'</b>　目標 <b class="u">'+px(sig[4])+'</b>　損切り <b class="d">'+px(sig[5])+'</b></div>';
  if(sig&&tm==='形成中') h+='<div>抜ける線 <b>'+px(sig[2])+'</b>（あと '+Math.abs(sig[5]).toFixed(2)+'%）　目標 '+px(sig[3])+'　損切り '+px(sig[4])+'</div>';
  if(s){
    const row=(n,x)=>x?'<tr><td class="l">'+n+'</td><td>'+x.n.toLocaleString()+'</td><td>'+x.win.toFixed(1)+'%</td><td>'+x.tgt.toFixed(0)+'%</td><td>'+x.stp.toFixed(0)+'%</td><td class="'+cls(x.avg)+'">'+pct(x.avg,3)+'</td></tr>':'';
    h+='<p style="margin-top:10px"><b>このパターンの過去の成績</b>（'+esc(S.from)+'〜'+esc(S.to)+'・'+MK.name+'）</p>';
    h+='<table><thead><tr><th class="l"></th><th>回数</th><th>勝率</th><th>目標</th><th>損切</th><th>平均損益</th></tr></thead><tbody>'
      +row('全体',s)+row('出来高1.5倍以上',s.vol)+row(MK.tod[0],s.am)+row(MK.tod[1],s.mid)+row(MK.tod[2],s.pm)+'</tbody></table>';
    h+='<p class="note">1時間後に'+(dd>0?'上がっていた':'下がっていた')+'割合 '+s.w60.toFixed(1)+'%（平均 '+pct(s.a60,3)+'）。比較：どの足で入っても1時間後に上がっていた割合 '+S.baseline.up60+'%・下がっていた割合 '+S.baseline.down60+'%。手数料は含みません。</p>';
  }
  h+='<div class="lk"><a href="'+CH+encodeURIComponent(code)+'.html">チャート ›</a><a href="'+CH+'one/'+encodeURIComponent(code)+'.html">株式分析ダッシュボード ›</a></div>';
  return h;
}
function chartSvg(bars,dr,code,key,tm){
  const idx=new Map(bars.map((b,i)=>[b.t,i]));
  const ptsI=dr.p.map(p=>idx.get(p[0])).filter(i=>i!=null), lnI=dr.l.flatMap(l=>[idx.get(l[0]),idx.get(l[2])]).filter(i=>i!=null);
  const ei=dr.e?idx.get(dr.e):null;
  let i0=Math.min(...ptsI,...lnI,ei??Infinity,bars.length-1)-8, i1=ei!=null?Math.min(bars.length-1,ei+40):bars.length-1;
  if(D.mode==='live'&&ei!=null) i1=bars.length-1;
  i0=Math.max(0,Math.min(i0,i1-50)); if(i1-i0>170) i0=i1-170;
  const B=bars.slice(i0,i1+1), n=B.length;
  const sig=tm==='形成中'?D.form.find(r=>r[0]===code&&r[1]===key):D.sig.find(r=>r[0]===code&&r[2]===key&&r[1]===tm);
  const lev=[]; if(sig){ if(tm==='形成中'){lev.push(['抜ける線',sig[2],'var(--hl)'],['目標',sig[3],'var(--tg)'],['損切り',sig[4],'var(--mut)']);} else {lev.push(['目標',sig[4],'var(--tg)'],['損切り',sig[5],'var(--mut)']);} }
  let lo=Infinity,hi=-Infinity; for(const b of B){lo=Math.min(lo,b.l);hi=Math.max(hi,b.h);}
  for(const [,v] of lev){ if(v!=null){lo=Math.min(lo,v);hi=Math.max(hi,v);} }
  const pad=(hi-lo)*0.06||1; lo-=pad; hi+=pad;
  const W=760,H=300,L=8,R=58,T=10,Bt=26, cw=(W-L-R)/n, X=i=>L+(i-i0+0.5)*cw, Y=v=>T+(hi-v)/(hi-lo)*(H-T-Bt);
  let g='';
  // 目盛り
  for(let k=0;k<=4;k++){ const v=lo+(hi-lo)*k/4, y=Y(v); g+='<line x1="'+L+'" x2="'+(W-R)+'" y1="'+y+'" y2="'+y+'" stroke="var(--line)"/><text x="'+(W-R+4)+'" y="'+(y+4)+'" font-size="11" fill="var(--mut)">'+px(v)+'</text>'; }
  let pd=''; for(let i=i0;i<=i1;i++){ const d=bars[i].t.slice(0,10); if(d!==pd){ if(pd){ const x=X(i)-cw/2; g+='<line x1="'+x+'" x2="'+x+'" y1="'+T+'" y2="'+(H-Bt)+'" stroke="var(--mut)" stroke-dasharray="2 3" opacity=".6"/>'; }
      g+='<text x="'+(X(i)-cw/2+3)+'" y="'+(H-8)+'" font-size="11" fill="var(--mut)">'+d.slice(5).replace('-','/')+'</text>'; pd=d; }
    else if(bars[i].t.slice(14)==='00'&&cw*12>40){ g+='<text x="'+X(i)+'" y="'+(H-8)+'" font-size="10" fill="var(--mut)" text-anchor="middle">'+bars[i].t.slice(11,13)+'時</text>'; } }
  // ローソク足（赤＝上昇・緑＝下落）
  for(let i=i0;i<=i1;i++){ const b=bars[i], up=b.c>=b.o, col=up?'var(--upb)':'var(--dnb)', x=X(i), w=Math.max(1,cw*0.66);
    g+='<line x1="'+x+'" x2="'+x+'" y1="'+Y(b.h)+'" y2="'+Y(b.l)+'" stroke="'+col+'"/>';
    const y1=Y(Math.max(b.o,b.c)), y2=Y(Math.min(b.o,b.c)); g+='<rect x="'+(x-w/2)+'" y="'+y1+'" width="'+w+'" height="'+Math.max(1,y2-y1)+'" fill="'+col+'"/>'; }
  // パターンの線と山・谷
  for(const l of dr.l){ const a=idx.get(l[0]), b=idx.get(l[2]); if(a==null||b==null)continue; g+='<line x1="'+X(a)+'" y1="'+Y(l[1])+'" x2="'+X(b)+'" y2="'+Y(l[3])+'" stroke="var(--hl)" stroke-width="2"/>'; }
  const pp=dr.p.map(p=>[idx.get(p[0]),p[1]]).filter(p=>p[0]!=null);
  if(pp.length>1) g+='<polyline points="'+pp.map(p=>X(p[0])+','+Y(p[1])).join(' ')+'" fill="none" stroke="var(--fg)" stroke-width="1.4" stroke-dasharray="4 3" opacity=".75"/>';
  for(const p of pp) g+='<circle cx="'+X(p[0])+'" cy="'+Y(p[1])+'" r="3.5" fill="var(--card)" stroke="var(--fg)" stroke-width="1.5"/>';
  // 目標・損切りの水平線
  const xs=ei!=null?X(ei):X(i1)-cw*12;
  for(const [nm,v,col] of lev){ if(v==null)continue; const y=Y(v); g+='<line x1="'+xs+'" x2="'+(W-R)+'" y1="'+y+'" y2="'+y+'" stroke="'+col+'" stroke-width="1.5" stroke-dasharray="6 4"/><text x="'+(W-R-4)+'" y="'+(y-4)+'" font-size="11" font-weight="700" fill="'+col+'" text-anchor="end">'+nm+' '+px(v)+'</text>'; }
  // エントリー
  if(ei!=null&&sig&&tm!=='形成中'){ const dd=pdir(key), x=X(ei), y=Y(sig[3]), s=8;
    g+='<path d="'+(dd>0?'M'+x+' '+(y+4)+'l'+(-s)+' '+(s*1.6)+'h'+(2*s)+'z':'M'+x+' '+(y-4)+'l'+(-s)+' '+(-s*1.6)+'h'+(2*s)+'z')+'" fill="'+(dd>0?'var(--up)':'var(--dn)')+'"/>'; }
  return '<svg viewBox="0 0 '+W+' '+H+'" role="img" aria-label="5分足チャート">'+g+'</svg><div class="lg"><span>5分足（'+MK.tz+'）</span><span style="color:var(--hl)">━ パターンの線</span><span>┅ 山・谷</span><span>▲▼ エントリー</span></div>';
}

// ---------------- パターン別の成績
function renderStat(){
  const el=$('p-stat');
  if(!S||!S.patterns){ el.innerHTML='<div class="doc">成績のデータがまだありません。</div>'; return; }
  const P=S.patterns;
  let h='<div class="warn">'+S.from+'〜'+S.to+'（'+S.sessions+'営業日）の5分足で、'+S.codes.toLocaleString()+'銘柄（売買代金 '+(MK.key==='jp'?'1日1億円':'1日100万ドル')+'以上）に出た '+S.signals.toLocaleString()+'回のシグナルを、'
    +'<b>シグナルの足の終値で入り、目標か損切りに先に届いた方、どちらも無ければ大引けで手じまう</b>として集計しました（手数料・スリッページは含まず）。'
    +'比較：どの足で買っても1時間後に上がっていた割合は '+S.baseline.up60+'%、下がっていた割合は '+S.baseline.down60+'%。平均損益が0%前後なら、パターンを使わない場合と大きな差はありません。</div>';
  h+='<div class="tw"><table><thead><tr><th class="l">パターン</th><th>回数</th><th>勝率</th><th>目標到達</th><th>損切り</th><th>平均損益</th><th class="hs">平均の利益</th><th class="hs">平均の損失</th><th>1時間後の勝率</th><th>出来高増加時</th><th class="hs">'+MK.tod[0]+'</th><th class="hs">'+MK.tod[1]+'</th><th class="hs">'+MK.tod[2]+'</th></tr></thead><tbody>';
  const ks=Object.keys(D.patterns);
  for(const g of ['U','D','O']){
    h+='<tr class="grp"><td colspan="13">'+GROUPN[g]+'</td></tr>';
    for(const k of ks.filter(k=>k[0]===g)){ const s=P[k]; const dd=pdir(k);
      if(!s){ h+='<tr><td class="l"><span class="b '+(dd>0?'u':'d')+'">'+(dd>0?'買':'売')+'</span> '+esc(pn(k))+'</td><td colspan="12" class="m">該当なし</td></tr>'; continue; }
      const t=x=>x?'<span class="'+cls(x.avg)+'">'+pct(x.avg,3)+'</span>':'<span class="m">―</span>';
      h+='<tr><td class="l"><span class="b '+(dd>0?'u':'d')+'">'+(dd>0?'買':'売')+'</span> '+esc(pn(k))+'</td><td>'+s.n.toLocaleString()+'</td><td>'+s.win.toFixed(1)+'%</td><td>'+s.tgt.toFixed(1)+'%</td><td>'+s.stp.toFixed(1)+'%</td>'
        +'<td><b class="'+cls(s.avg)+'">'+pct(s.avg,3)+'</b></td><td class="hs u">'+pct(s.avg_win,2)+'</td><td class="hs d">'+pct(s.avg_loss,2)+'</td><td>'+s.w60.toFixed(1)+'%</td>'
        +'<td>'+(s.vol?s.vol.win.toFixed(0)+'%・'+t(s.vol):'<span class="m">―</span>')+'</td><td class="hs">'+t(s.am)+'</td><td class="hs">'+t(s.mid)+'</td><td class="hs">'+t(s.pm)+'</td></tr>';
    }
  }
  h+='</tbody></table></div>';
  h+='<p class="note">勝率＝手じまいの損益がプラスだった割合。目標到達・損切り＝その日のうちに先に届いた割合（残りは大引けで手じまい）。平均損益＝1回あたりの損益の平均（売りは下がると利益）。'
    +'出来高増加時＝シグナルの足の出来高が直近20本平均の1.5倍以上だったとき（勝率・平均損益）。時間帯＝シグナルが出た時刻。集計 '+esc(S.made)+'。</p>';
  el.innerHTML=h;
}
function renderDoc(){
  const ks=Object.keys(D.patterns);
  let h='<div class="doc"><h3>このページでわかること</h3><p>画像の「勝てるチャートパターン一覧」の22パターン（上昇10・下落10・その他4）を、全銘柄の5分足から自動で探します。'
   +'<b>シグナル</b>はパターンが完成して線を抜けた（エントリーの合図が出た）銘柄、<b>形成中</b>はあと少しで線を抜けそうな銘柄です。'
   +'それぞれに、同じパターンが過去にどれくらい当たったか（勝率・目標到達率・平均損益）を添えています。</p>'
   +'<h3>更新のタイミング</h3><p>'+MK.when+'</p>'
   +'<h3>判定のしかた</h3><p>値動きの物差しに ATR（5分足14本の平均的な値幅）を使い、高値・安値から ATR×2.5 以上戻したところで山・谷を確定させます。'
   +'山・谷の並びが下の条件に合ったら「どの線を抜けたらエントリーか」を決め、その後の5分足の終値が線を抜けたらシグナルです（その時点までの足だけで判定し、後から当てはめ直すことはしません）。'
   +'抜ける前に損切りの価格を割ったら、そのパターンは取り消します。</p><dl>';
  for(const g of ['U','D','O']){ h+='</dl><h3>'+GROUPN[g]+'</h3><dl>'; for(const k of ks.filter(k=>k[0]===g)) h+='<dt>'+esc(pn(k))+'</dt><dd>'+esc(RULES[k]||'')+'</dd>'; }
  h+='</dl><h3>注意</h3><p>パターンは100%ではなく、ダマシもあります。成績は過去の数か月の結果で、この先も同じとは限りません。手数料・スリッページ・空売りの費用は入れていません。'
   +'取引中の株価は無料の Yahoo Finance から取るため遅れがあります（'+(MK.key==='jp'?'東証は約20分':'米国は数分')+'）。売買の判断はご自身で。</p></div>';
  $('p-doc').innerHTML=h;
}
load();
</script>
</body></html>
"""

WHEN = {
    "jp": "取引中（平日 9:20〜15:20）は約15分おきに、その時点までの5分足で判定し直します（Yahoo の株価が約20分遅れなので、実際の時刻より20分ほど前までの値動きです）。大引け後（16:30・19:00）にその日の全体を判定し直し、結果（目標到達・損切り・大引け）をつけます。取引中に開いていると5分ごとに自動で読み込み直します。取引中の更新は Mac で動かしているので、Mac がスリープ中・電源オフのときは止まります。",
    "us": "取引中（日本時間 23:30〜翌6:00。夏時間は1時間早い）は約15分おきに、その時点までの5分足で判定し直します。翌朝7:30の更新でその日の全体を判定し直し、結果（目標到達・損切り・大引け）をつけます。取引中に開いていると5分ごとに自動で読み込み直します。取引中の更新は Mac で動かしているので、Mac がスリープ中・電源オフのときは止まります。",
}
TODN = {"jp": ["9:00〜10:00", "10:00〜14:00", "14:00〜大引け"], "us": ["9:30〜10:30", "10:30〜14:30", "14:30〜大引け"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", required=True, choices=["jp", "us"])
    a = ap.parse_args()
    m = D.cfg(a.market)
    mk = {"key": a.market, "name": m["name"], "tz": "日本時間" if a.market == "jp" else "米東部時間",
          "when": WHEN[a.market], "tod": TODN[a.market]}
    html = (HTML.replace("__MKT__", "東証" if a.market == "jp" else "米国株")
            .replace("__MK__", json.dumps(mk, ensure_ascii=False))
            .replace("__RULES__", json.dumps(RULES, ensure_ascii=False))
            .replace("__TVS__", json.dumps(TV[a.market], ensure_ascii=False))
            .replace("__TVDEF__", str(TVDEF[a.market])))
    os.makedirs(m["pub"], exist_ok=True)
    out = os.path.join(m["pub"], "daytrade.html")
    old = open(out, encoding="utf-8").read() if os.path.exists(out) else None
    # 公開前の後処理（明暗スイッチなど）で手を加えたページは中身が変わるので、生成元が同じなら書き直さない
    stamp = "<!--dtp:" + hashlib.md5(html.encode("utf-8")).hexdigest()[:10] + "-->"
    if old and stamp in old:
        print("daytrade.html: 変更なし")
        return 0
    with open(out, "w", encoding="utf-8") as f:
        f.write(html.replace("<html lang=\"ja\">", "<html lang=\"ja\">" + stamp, 1))
    print(f"daytrade.html を作成（{out}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
