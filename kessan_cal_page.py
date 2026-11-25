"""決算カレンダーのページ（東証版・米国版で共通の見た目）。2026-11-24 作成、同日 土日の列・表の列を利用者の指定に変更。
make_kessan_cal.py（東証）・~/米国株分析/us_make_kessan_cal.py（米国）が write() を呼ぶ。
出力: <SITE>/kessan.html（ページ）と <SITE>/kessan_data.js（データ）

データ（window.KC）
  S: [コード, 銘柄名, 市場, 時価総額(東証=億円・米国=億ドル), 株価, 前日比(%)]
  E: [S の番号, 日付, 時刻, 区分(0不明 1寄り前 2取引中 3引け後), 状態(0発表済み 1予定 2予想), 種別, 達成率(%), 天気(1☀️ 2☁️ 3☂️ 0なし), ...]
     東証 [8] 会社予想経常利益(百万円) [9] 基準（'経常'／'税前'）
     米国 [8] EPS実績 [9] コンセンサスEPS [10] 売上高(百万ドル) [11] コンセンサス売上高(百万ドル)
表の列（利用者の指定）
  東証 コード・銘柄名・発表時間・種別・今期経常 会社予想達成率・会社予想経常利益（百万円）
  米国 コード・銘柄名・発表時間・種別・EPS実績・コンセンサスEPS・達成率・売上高・コンセンサス売上高（百万ドル）
"""
from __future__ import annotations

import json
from pathlib import Path

PAGE = r"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>決算カレンダー | __SITE__</title>
__HEAD__
<style>
.wrap{max-width:1680px}
.bar1{display:flex;flex-wrap:wrap;align-items:center;gap:10px 14px;margin-top:22px}
.mnav{display:flex;align-items:center;gap:6px}
.mnav h2{margin:0 6px;font-size:22px;font-weight:800;letter-spacing:.02em;min-width:150px;text-align:center}
.nb{width:38px;height:38px;border:1px solid var(--line);border-radius:10px;background:var(--card);color:var(--fg);font:inherit;font-size:18px;font-weight:700;cursor:pointer}
.nb:hover:not(:disabled){border-color:var(--fg)}.nb:disabled{opacity:.3;cursor:default}
.tb{height:38px;padding:0 14px;border:1px solid var(--line);border-radius:10px;background:var(--card);color:var(--fg);font:inherit;font-size:13px;font-weight:700;cursor:pointer}
.tb:hover{border-color:var(--fg)}
.flt{display:flex;flex-wrap:wrap;gap:8px;margin-left:auto;align-items:center}
.flt select,.flt input{height:38px;padding:0 10px;border:1px solid var(--line);border-radius:10px;background:var(--card);color:var(--fg);font:inherit;font-size:13px;font-weight:600;outline:none;max-width:220px}
.flt input{width:220px;-webkit-appearance:none;appearance:none}
.flt select:focus,.flt input:focus{border-color:var(--fg)}
.cal{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:6px;margin-top:14px}
.dw{font-size:11.5px;font-weight:700;color:var(--mut);padding:0 4px 2px;letter-spacing:.08em}
.dw.we{opacity:.7}
.dc{position:relative;min-height:112px;background:var(--card);border-radius:12px;padding:9px 10px 8px;cursor:pointer;border:2px solid transparent;display:flex;flex-direction:column;gap:3px;min-width:0;transition:background .12s}
.dc:hover{background:color-mix(in srgb,var(--fg) 6%,var(--card))}
.dc.we{background:color-mix(in srgb,var(--fg) 3%,var(--bg))}
.dc.out{opacity:.35}.dc.emp{cursor:default}.dc.emp:hover{background:var(--card)}.dc.we.emp:hover{background:color-mix(in srgb,var(--fg) 3%,var(--bg))}
.dc.today{border-color:var(--line)}.dc.today .dn::after{content:'今日';margin-left:6px;font-size:10px;font-weight:700;padding:1px 6px;border-radius:5px;background:var(--fg);color:var(--bg);vertical-align:2px}
.dc.sel{border-color:var(--fg)}
.dc .heat{position:absolute;left:0;right:0;bottom:0;height:4px;border-radius:0 0 10px 10px;background:var(--fg);opacity:0}
.dn{font-size:13px;font-weight:800}.dc.past .dn{color:var(--mut)}
.cnt{font-size:24px;font-weight:800;letter-spacing:-.03em;line-height:1.05}.cnt small{font-size:11px;font-weight:600;color:var(--mut);margin-left:2px;letter-spacing:0}
.tops{font-size:11.5px;line-height:1.45;color:var(--fg2);overflow:hidden;margin-top:2px}
.tops div{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tops b{font-weight:700;margin-right:4px;color:var(--fg)}
.lgd{display:flex;flex-wrap:wrap;gap:4px 16px;margin-top:10px;font-size:11.5px;color:var(--mut)}
.pane{margin-top:22px;background:var(--card);border-radius:14px;overflow:hidden}
.ph{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 14px;padding:16px 16px 10px}
.ph h3{margin:0;font-size:18px;font-weight:800}.ph .c{color:var(--mut);font-size:12.5px}
.ph .sm{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:12.5px;color:var(--mut);margin-left:auto}.ph .sm b{color:var(--fg);font-weight:800}
.tw{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{border-collapse:collapse;width:100%;font-size:13px;white-space:nowrap}
th,td{padding:9px 12px;text-align:right;border-top:1px solid var(--line)}
th{font-size:11.5px;font-weight:600;color:var(--mut);cursor:pointer;user-select:none;-webkit-user-select:none;line-height:1.35}
th:hover{color:var(--fg)}th.on{color:var(--fg);font-weight:800}th small{font-weight:400;display:block;font-size:10.5px}
td{font-weight:600}td small{font-weight:400;font-size:11.5px;color:var(--mut)}
th.l,td.l{text-align:left}
th:first-child,td:first-child{position:sticky;left:0;z-index:1;background:var(--card);padding-left:16px}
tbody tr:hover td{background:color-mix(in srgb,var(--fg) 5%,var(--card))}
td a{color:var(--fg);text-decoration:none}td a:hover{text-decoration:underline}
td.cd{font-weight:800}
td.nm{max-width:320px;overflow:hidden;text-overflow:ellipsis}
.sn{display:none}
td.ac{font-weight:800}td.ac .wx{font-size:17px;margin-right:6px;vertical-align:-2px}
.na{color:var(--mut);font-weight:400}
.tg{display:inline-block;font-size:10.5px;padding:0 6px;border-radius:5px;border:1px solid var(--line);color:var(--mut);font-weight:600;margin-left:4px}
.kd{display:inline-block;font-size:11.5px;padding:1px 8px;border-radius:6px;background:color-mix(in srgb,var(--fg) 8%,var(--card));font-weight:700}
.kd.fy{background:var(--fg);color:var(--bg)}.kd.mo{background:transparent;border:1px solid var(--line);color:var(--mut);font-weight:600}
.more{display:flex;justify-content:center;gap:8px;padding:12px 16px 16px}
.ob{border:1px solid var(--line);background:transparent;color:var(--fg2);border-radius:8px;padding:6px 14px;font:inherit;font-size:12.5px;cursor:pointer}.ob:hover{border-color:var(--fg);color:var(--fg)}
.empty{padding:6px 16px 18px;color:var(--mut);font-size:13px}
.note{margin-top:22px;color:var(--mut);font-size:11.5px;line-height:1.7}
@media(max-width:1000px){.flt{margin-left:0;width:100%}.flt select,.flt input{flex:1 1 140px;max-width:none}}
@media(max-width:760px){.wrap{padding:16px 10px 40px}.mnav h2{font-size:18px;min-width:120px}
.flt select,.flt input{font-size:16px}
.cal{gap:3px}.dw{padding:0 1px;font-size:10.5px;text-align:center;letter-spacing:0}
.dc{min-height:58px;padding:5px 2px 6px;border-radius:8px;align-items:center;text-align:center;gap:1px}
.dn{font-size:11px}.dc.today .dn::after{display:none}.dc.today{border-color:var(--fg2)}
.cnt{font-size:15px}.cnt small{display:none}.tops{display:none}
.ph{padding:14px 12px 8px}.ph h3{font-size:16px}.ph .sm{margin-left:0}
table{font-size:12.5px}th,td{padding:8px 8px}th:first-child,td:first-child{padding-left:12px}
th.nmh,td.nm{display:none}.sn{display:block;font-size:11px;font-weight:600;color:var(--fg2);max-width:118px;overflow:hidden;text-overflow:ellipsis}
.kd{font-size:10.5px;padding:1px 5px}td.ac .wx{font-size:15px;margin-right:3px}
th{white-space:normal;min-width:52px;vertical-align:bottom}td{padding-left:6px;padding-right:6px}}
</style>
</head><body><div class="wrap">
<header><div><h1><a href="./index.html" title="トップへ" style="text-decoration:none;color:inherit;margin-right:8px">‹</a>決算カレンダー</h1>
<div class="sub" id="sub"></div></div>
<button class="btn" id="theme" type="button">明暗</button></header>
<div class="bar1">
 <div class="mnav"><button class="nb" id="pm" type="button" title="前の月">‹</button><h2 id="mt"></h2><button class="nb" id="nm" type="button" title="次の月">›</button>
 <button class="tb" id="td" type="button">今日</button></div>
 <div class="flt">
  <select id="fm" title="時価総額で絞る"></select>
  <select id="fk" title="市場で絞る"></select>
  <select id="fw" title="監視銘柄の一覧表で絞る"><option value="">全銘柄</option></select>
  <input id="q" type="search" placeholder="__QPH__" autocomplete="off">
 </div>
</div>
<div class="cal" id="cal"></div>
<div class="lgd"><span>数字＝その日に決算を発表する社数（時価総額の大きい順に3銘柄）</span><span>下の線の濃さ＝社数の多さ</span></div>
<div class="pane" id="pane"></div>
<p class="note">__NOTE__</p>
</div>
<script src="./kessan_data.js"></script>
<script src="./one/assets/watch.js"></script>
<script>
const $=id=>document.getElementById(id),D=window.KC,US=D.site==='us',S=D.S,E=D.E;
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const norm=s=>String(s).normalize('NFKC').toLowerCase();
const nf=(v,d=0)=>Number(v).toLocaleString('ja-JP',{minimumFractionDigits:d,maximumFractionDigits:d});
const NA='<span class="na">―</span>',WD=['日','月','火','水','木','金','土'],SL=['','寄り前','取引中','引け後'];
const WX=['','☀️','☁️','☂️'],WXT=['','好調','やや弱い','不調'];
const BY={};E.forEach((e,i)=>{(BY[e[1]]=BY[e[1]]||[]).push(i);});
const IX=S.map(s=>norm(s[0]+' '+s[1]));
const pd=s=>{const[y,m,d]=s.split('-').map(Number);return new Date(y,m-1,d);};
const ymd=t=>t.getFullYear()+'-'+String(t.getMonth()+1).padStart(2,'0')+'-'+String(t.getDate()).padStart(2,'0');
const md=s=>{const t=pd(s);return `${t.getMonth()+1}/${t.getDate()}(${WD[t.getDay()]})`;};
const dates=Object.keys(BY).sort(),M0=D.since.slice(0,7),M1=dates.length?dates[dates.length-1].slice(0,7):D.today.slice(0,7);
/* 絞り込み */
const MC=US?[[0,'時価総額：すべて'],[10,'時価総額 10億ドル以上'],[100,'100億ドル以上'],[1000,'1000億ドル以上']]
 :[[0,'時価総額：すべて'],[300,'時価総額 300億円以上'],[1000,'1000億円以上'],[1e4,'1兆円以上']];
$('fm').innerHTML=MC.map(([v,t])=>`<option value="${v}">${t}</option>`).join('');
const MK=[...new Set(S.map(s=>s[2]).filter(Boolean))].sort();
$('fk').innerHTML='<option value="">市場：すべて</option>'+MK.map(m=>`<option>${esc(m)}</option>`).join('');
const K=window.KW;let WL=[];
try{if(K){WL=K.lists();$('fw').innerHTML+=WL.map(l=>`<option value="${esc(l.id)}">監視：${esc(l.t)}（${l.c.length}）</option>`).join('');}}catch(e){}
if(!WL.length)$('fw').hidden=true;
const F={m:0,k:'',w:null};
function load(){try{const x=JSON.parse(localStorage.getItem('kc-flt-'+D.site)||'{}');if(x.m!=null)$('fm').value=x.m;if(x.k)$('fk').value=x.k;if(x.w&&WL.some(l=>l.id===x.w))$('fw').value=x.w;}catch(e){}}
function apply(){F.m=+$('fm').value;F.k=$('fk').value;const l=WL.find(x=>x.id===$('fw').value);F.w=l?new Set(l.c):null;
 try{localStorage.setItem('kc-flt-'+D.site,JSON.stringify({m:F.m,k:F.k,w:$('fw').value}));}catch(e){}}
const ok=e=>{const s=S[e[0]];if(F.m&&!(s[3]>=F.m))return false;if(F.k&&s[2]!==F.k)return false;if(F.w&&!F.w.has(s[0]))return false;return true;};
/* カレンダー（日曜〜土曜） */
let CUR=D.today.slice(0,7),SEL=null;
function cal(){const[y,m]=CUR.split('-').map(Number);$('mt').textContent=`${y}年${m}月`;
 $('pm').disabled=CUR<=M0;$('nm').disabled=CUR>=M1;
 const f=new Date(y,m-1,1),st=new Date(f);st.setDate(1-f.getDay());
 const last=new Date(y,m,0);let h=WD.map((w,i)=>`<div class="dw${i===0||i===6?' we':''}">${w}</div>`).join('');
 const cells=[];let mx=1;
 for(let t=new Date(st);t<=last||t.getDay()!==0;t.setDate(t.getDate()+1)){
  const ds=ymd(t),L=(BY[ds]||[]).map(i=>E[i]).filter(ok);mx=Math.max(mx,L.length);cells.push([ds,t.getMonth()===m-1,L,t.getDay()]);}
 for(const[ds,inm,L,w] of cells){const n=L.length,c=['dc'];if(w===0||w===6)c.push('we');if(!inm)c.push('out');if(!n)c.push('emp');if(ds<D.today)c.push('past');
  if(ds===D.today)c.push('today');if(ds===SEL)c.push('sel');
  const tops=L.slice().sort((a,b)=>(S[b[0]][3]||0)-(S[a[0]][3]||0)).slice(0,3);
  h+=`<div class="${c.join(' ')}" data-d="${ds}"><div class="dn">${+ds.slice(8)}</div>`+
   (n?`<div class="cnt">${n}<small>社</small></div><div class="tops">${tops.map(e=>`<div><b>${esc(S[e[0]][0])}</b>${esc(S[e[0]][1])}</div>`).join('')}</div>`:'')+
   `<i class="heat" style="opacity:${n?(.15+.85*n/mx).toFixed(2):0}"></i></div>`;}
 $('cal').innerHTML=h;}
/* 表の列 */
const kind=e=>e[5]?`<span class="kd${e[5]==='本決算'?' fy':e[5]==='月次'?' mo':''}">${esc(e[5])}</span>`:NA;
const tm=e=>{let s;if(US)s=e[3]?(e[2]&&e[2]!=='08:30'&&e[2]!=='16:00'?esc(e[2])+' ':'')+SL[e[3]]:'';else s=e[2]?esc(e[2]):'';
 return (s||(e[4]?'<span class="na">未定</span>':NA))+(e[4]===2?'<span class="tg" title="会社の発表前。昨年の同じ時期などから推定した日">予想</span>':'');};
const ach=e=>{if(e[6]==null)return e[7]?`<span class="wx" title="${WXT[e[7]]}">${WX[e[7]]}</span>`+NA:NA;return `<span class="wx" title="${WXT[e[7]]}">${WX[e[7]]||''}</span>${nf(e[6],1)}%`+(e[9]==='税前'&&!US?'<small> 税前</small>':'');};
const mil=v=>v==null?NA:nf(v);
const eps=v=>v==null?NA:nf(v,2);
const COLS=US?[
 {l:'発表時間',k:2,c:'l',f:tm},{l:'種別',k:5,c:'l',f:kind},
 {l:'EPS実績',u:'ドル',k:8,f:e=>eps(e[8])},{l:'コンセンサスEPS',u:'ドル',k:9,f:e=>eps(e[9])},
 {l:'達成率',u:'実績÷コンセンサス',k:6,c:'ac',f:ach},
 {l:'売上高',u:'百万ドル',k:10,f:e=>mil(e[10])},{l:'コンセンサス売上高',u:'百万ドル',k:11,f:e=>mil(e[11])}]
:[{l:'発表時間',k:2,c:'l',f:tm},{l:'種別',k:5,c:'l',f:kind},
 {l:'今期経常 会社予想達成率',u:'％',k:6,c:'ac',f:ach},{l:'会社予想経常利益',u:'百万円',k:8,f:e=>mil(e[8])}];
const ST={i:'m',d:-1};let LIM=100;
const val=(e,k)=>k==='m'?S[e[0]][3]:k==='n'?S[e[0]][0]:k==='nm'?S[e[0]][1]:k==='dt'?e[1]:e[k];
function table(L,showDate){
 L=L.slice().sort((a,b)=>{const x=val(a,ST.i),y=val(b,ST.i);if(x==null&&y==null)return 0;if(x==null||x==='')return 1;if(y==null||y==='')return -1;
  const r=(x<y?-1:x>y?1:0)*ST.d;return r||((S[b[0]][3]||0)-(S[a[0]][3]||0));});
 const th=(k,h,c)=>`<th data-k="${k}"${c?` class="${c}${ST.i===k?' on':''}"`:ST.i===k?' class="on"':''}>${h}${ST.i===k?(ST.d>0?' ▲':' ▼'):''}</th>`;
 let h='<div class="tw"><table><thead><tr>'+th('n','コード','l')+th('nm','銘柄名','l nmh')+(showDate?th('dt','発表日','l'):'')+
  COLS.map(x=>th(String(x.k),x.l+(x.u?`<small>${x.u}</small>`:''),x.c==='l'?'l':'')).join('')+'</tr></thead><tbody>';
 h+=L.slice(0,LIM).map(e=>{const s=S[e[0]],u=`./one/${encodeURIComponent(s[0])}.html`;
  return `<tr><td class="cd l"><a href="${u}">${esc(s[0])}<span class="sn">${esc(s[1])}</span></a></td><td class="nm l"><a href="${u}" title="${esc(s[1])}（${esc(s[2])}）">${esc(s[1])}</a></td>`+
  (showDate?`<td class="l">${md(e[1])}</td>`:'')+COLS.map(x=>`<td${x.c?` class="${x.c}"`:''}>${x.f(e)}</td>`).join('')+'</tr>';}).join('');
 h+='</tbody></table></div>';
 if(L.length>LIM)h+=`<div class="more"><button class="ob" data-more="1">さらに表示（残り ${nf(L.length-LIM)}社）</button><button class="ob" data-more="all">すべて表示</button></div>`;
 return h;}
function wsum(L){const p=L.filter(e=>e[7]);if(!p.length)return '';
 return [1,2,3].map(w=>`<span>${WX[w]} <b>${p.filter(e=>e[7]===w).length}</b></span>`).join('');}
function pane(){const q=norm($('q').value.trim());
 if(q){const hit=new Set();S.forEach((s,i)=>{if(q.split(/\s+/).every(w=>IX[i].includes(w)))hit.add(i);});
  const L=E.filter(e=>hit.has(e[0])&&ok(e));
  $('pane').innerHTML=`<div class="ph"><h3>「${esc($('q').value.trim())}」の決算</h3><span class="c">${hit.size>200?'候補が多すぎます。コードか銘柄名をもう少し入れてください':L.length+'件'}</span></div>`+
   (hit.size>200?'':L.length?table(L,true):'<div class="empty">見つかりません（'+D.since.replace(/-/g,'/')+' より前の発表は載せていません）</div>');return;}
 if(!SEL){$('pane').innerHTML='<div class="empty" style="padding:16px">カレンダーの日付を押すと、その日の銘柄の一覧が出ます。</div>';return;}
 const L=(BY[SEL]||[]).map(i=>E[i]).filter(ok);
 const pl=SEL<D.today?'決算発表':SEL===D.today?'今日の決算発表':'決算発表の予定';
 $('pane').innerHTML=`<div class="ph"><h3>${md(SEL)} ${pl}</h3><span class="c">${L.length}社${F.m||F.k||F.w?'（絞り込み中）':''}</span><div class="sm">${wsum(L)}</div></div>`+(L.length?table(L,false):'<div class="empty">この日の発表はありません。</div>');}
function draw(){cal();pane();}
$('cal').addEventListener('click',e=>{const c=e.target.closest('.dc');if(!c||c.classList.contains('emp'))return;
 SEL=c.dataset.d;LIM=100;$('q').value='';if(SEL.slice(0,7)!==CUR)CUR=SEL.slice(0,7);try{history.replaceState(null,'','#'+SEL);}catch(x){}draw();
 if(innerWidth<=760)$('pane').scrollIntoView({behavior:'smooth',block:'start'});});
$('pane').addEventListener('click',e=>{const t=e.target,th=t.closest('th[data-k]');
 if(th){let k=th.dataset.k;if(/^\d+$/.test(k))k=+k;const d0=(k==='n'||k==='nm'||k==='dt'||k===2||k===5)?1:-1;
  if(ST.i!==k){ST.i=k;ST.d=d0;}else if(ST.d===d0)ST.d=-d0;else{ST.i='m';ST.d=-1;}pane();return;}
 if(t.dataset.more){LIM=t.dataset.more==='all'?1e9:LIM+200;pane();}});
const mv=k=>{const[y,m]=CUR.split('-').map(Number),t=new Date(y,m-1+k,1);CUR=ymd(t).slice(0,7);cal();};
$('pm').onclick=()=>mv(-1);$('nm').onclick=()=>mv(1);
function goToday(){const t=dates.find(d=>d>=D.today)||D.today;SEL=BY[D.today]?D.today:t;CUR=SEL.slice(0,7);draw();}
$('td').onclick=goToday;
['fm','fk','fw'].forEach(id=>$(id).addEventListener('change',()=>{apply();LIM=100;draw();}));
$('q').addEventListener('input',()=>{LIM=100;pane();});
$('theme').addEventListener('click',()=>{const d=document.documentElement;
 const cur=d.getAttribute('data-theme')||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');
 const n=cur==='dark'?'light':'dark';d.setAttribute('data-theme',n);try{localStorage.setItem('fdb-theme',n)}catch(e){}});
load();apply();
$('sub').textContent=`更新 ${D.built} ／ ${D.since.replace(/-/g,'/')} 以降の発表と今後の予定`;
const h0=location.hash.slice(1);if(/^\d{4}-\d\d-\d\d$/.test(h0)&&BY[h0]){SEL=h0;CUR=h0.slice(0,7);draw();}else goToday();
</script></body></html>"""


def card_info(site: Path):
    """トップのカード用：(大きく出す値, 補足の HTML)。今週（土日なら来週）の月〜日に発表する社数と時価総額の大きい銘柄"""
    import datetime
    import html
    t = (site / "kessan_data.js").read_text(encoding="utf-8")
    D = json.loads(t[t.index("=") + 1:].rstrip().rstrip(";"))
    today = datetime.date.fromisoformat(D["today"])
    mon = today - datetime.timedelta(days=today.weekday())
    if today.weekday() >= 5:
        mon += datetime.timedelta(days=7)
    sun = (mon + datetime.timedelta(days=6)).isoformat()
    S, E = D["S"], [e for e in D["E"] if mon.isoformat() <= e[1] <= sun and e[5] != "月次"]
    E.sort(key=lambda e: -(S[e[0]][3] or 0))
    n_today = sum(1 for e in D["E"] if e[1] == D["today"] and e[5] != "月次")
    tops = "・".join(f"<b>{html.escape(S[e[0]][0])}</b>" for e in E[:4])
    rest = (f'<span>今日 <b>{n_today:,}</b>社</span>' + (f'<span>主な銘柄 {tops}</span>' if tops else ""))
    lab = "今週の決算" if today.weekday() < 5 else "来週の決算"
    return (lab, f"{len(E):,}社", ""), rest


def write(site: Path, data: dict, head: str, site_name: str, note: str) -> Path:
    js = "window.KC=" + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";"
    (site / "kessan_data.js").write_text(js, encoding="utf-8")
    qph = "銘柄を探す（例: AAPL / Apple）" if data.get("site") == "us" else "銘柄を探す（例: 7203 / トヨタ）"
    out = site / "kessan.html"
    out.write_text(PAGE.replace("__SITE__", site_name).replace("__HEAD__", head).replace("__NOTE__", note)
                   .replace("__QPH__", qph), encoding="utf-8")
    print(f"  kessan_data.js {len(js)/1024:.0f} KB（{len(data['E']):,}件）")
    return out
