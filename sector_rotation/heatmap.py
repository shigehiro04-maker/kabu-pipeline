#!/usr/bin/env python3
"""セクター別パフォーマンスの時系列ヒートマップ（sector_rotation.py から呼ばれる）

行＝業種、列＝月（直近24ヶ月）または週（直近26週）。
表示は「対市場（業種−市場）」「絶対リターン」「順位（1位＝最も強い）」を切り替え可能。
月次の上段には、相場の四季（market_phase.py）の判定を色帯で重ねる。
"""
import json

import numpy as np
import pandas as pd

MONTHS = 24
WEEKS = 26


def _period_returns(px, bench, rule, n):
    p = px.ffill().resample(rule).last()
    b = bench.ffill().resample(rule).last()
    r = p.pct_change() * 100
    rb = b.pct_change() * 100
    r, rb = r.iloc[-n:], rb.iloc[-n:]
    rel = r.sub(rb, axis=0)
    return r, rel, rb


def heat_data(px, bench, order, names):
    """order: 表示順（コードのリスト）、names: コード→業種名"""
    out = {}
    last = px.dropna(how="all").index[-1]
    for key, rule, n in [("m", "ME", MONTHS), ("w", "W-FRI", WEEKS)]:
        r, rel, rb = _period_returns(px[order], bench, rule, n)
        if key == "m":
            labels = [d.strftime("%y/%m") for d in r.index]
            if last < r.index[-1]:
                labels[-1] += "*"                 # 月の途中
        else:
            labels = [d.strftime("%m/%d") for d in r.index]
        rank = rel.rank(axis=1, ascending=False)
        rnd = lambda df: [[None if pd.isna(v) else round(float(v), 2) for v in df[c]] for c in order]
        out[key] = {"labels": labels, "periods": [str(d.date()) for d in r.index],
                    "rel": rnd(rel), "abs": rnd(r),
                    "rank": [[None if pd.isna(v) else int(v) for v in rank[c]] for c in order],
                    "bench": [None if pd.isna(v) else round(float(v), 2) for v in rb]}
    out["rows"] = [names.get(c, c) for c in order]
    return out


def heat_html(results, phases=None):
    from market_phase import PH_COLOR
    data = {}
    for key, res in results.items():
        if "heat" not in res:
            continue
        h = dict(res["heat"])
        h["label"] = res["label"]
        pk = "us" if key == "us" else "jp"
        if phases and pk in phases:
            hist = phases[pk]["history"]
            ph = {d.strftime("%y/%m"): p for d, p in zip(hist.index, hist["局面"])}
            h["phase"] = [ph.get(l.rstrip("*")) for l in h["m"]["labels"]]
        data[key] = h
    if not data:
        return ""
    short = {'us': '米国', 'jp17': '日本17業種', 'jp33': '日本33業種'}
    tabs = "".join(f"<button data-k='{k}'{' class=on' if i == 0 else ''}>{short.get(k, v['label'])}</button>"
                   for i, (k, v) in enumerate(data.items()))
    css = """<style>
.hmctl{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;margin:4px 0 10px}
.hmctl .grp{display:inline-flex;border:1px solid var(--line);border-radius:8px;overflow:hidden}
.hmctl button{background:var(--card);color:var(--ink);border:0;padding:5px 11px;font:inherit;font-size:12.5px;cursor:pointer}
.hmctl button+button{border-left:1px solid var(--line)}
.hmctl button.on{background:var(--ink);color:var(--card)}
.hmwrap{overflow-x:auto}
table.hm{border-collapse:separate;border-spacing:2px;font-size:11px;white-space:nowrap}
table.hm th{font-weight:500;color:var(--sub);padding:2px 3px;text-align:center}
table.hm th.rn{position:sticky;left:0;background:var(--card);text-align:right;padding-right:8px;color:var(--ink);z-index:1}
table.hm td{width:38px;min-width:38px;height:22px;text-align:center;border-radius:3px;font-variant-numeric:tabular-nums;cursor:default}
table.hm tr.phr td{height:10px;border-radius:2px}
table.hm tr.bm td{color:var(--sub);background:transparent!important}
.hmleg{display:flex;align-items:center;gap:8px;font-size:11.5px;color:var(--sub);margin-top:8px;flex-wrap:wrap}
.hmleg .bar{width:180px;height:10px;border-radius:3px}
@media (max-width:760px){table.hm{font-size:10px;border-spacing:1px}table.hm td{width:30px;min-width:30px;height:20px}
 table.hm th.rn{max-width:92px;overflow:hidden;text-overflow:ellipsis;font-size:10.5px;padding-right:4px}
 .hmctl{gap:6px}.hmctl button{padding:5px 8px;font-size:12px}}
#hmtip{position:fixed;pointer-events:none;background:var(--card);color:var(--ink);border:1px solid var(--line);
 border-radius:6px;padding:6px 9px;font-size:12px;box-shadow:0 4px 14px rgba(0,0,0,.15);display:none;z-index:10}
</style>"""
    body = f"""
<h2>セクター別パフォーマンスの推移（ヒートマップ）</h2>
<p class='note'>行＝業種（総合スコア順）、列＝期間。赤＝市場より強い／緑＝市場より弱い。色の帯が横に移っていく様子が「ローテーション」です。
月次の最上段の色帯は相場の四季の判定（緑＝金融、黄＝業績、橙＝逆金融、紺＝逆業績）。* は月の途中。</p>
<div class='card'>
<div class='hmctl'><div class='grp' id='hmMk'>{tabs}</div>
<div class='grp' id='hmMode'><button data-v='rel' class='on'>対市場</button><button data-v='abs'>絶対</button><button data-v='rank'>順位</button></div>
<div class='grp' id='hmFq'><button data-v='m' class='on'>月次</button><button data-v='w'>週次</button></div></div>
<div class='hmwrap'><table class='hm' id='hmT'></table></div>
<div class='hmleg' id='hmLeg'></div>
</div><div id='hmtip'></div>"""
    js = f"""<script>
(function(){{
const HM={json.dumps(data, ensure_ascii=False)};
const PHC={json.dumps(PH_COLOR, ensure_ascii=False)};
let st={{k:Object.keys(HM)[0],mode:'rel',fq:'m'}};
const POS=[200,50,58], NEG=[15,127,99];   // 赤＝強い（上昇）／緑＝弱い（下落）。他のページと同じ向き
function mid(){{const t=document.documentElement.getAttribute('data-theme'),d=t?t==='dark':matchMedia('(prefers-color-scheme: dark)').matches;return d?[30,32,38]:[234,236,240];}}
function mix(a,b,t){{return a.map((x,i)=>Math.round(x+(b[i]-x)*t));}}
function color(v,lim){{if(v==null)return 'transparent';const t=Math.min(Math.abs(v)/lim,1);
 const c=mix(mid(),v>=0?POS:NEG,Math.pow(t,0.8));return `rgb(${{c}})`;}}
function ink(v,lim){{if(v==null)return '';const t=Math.min(Math.abs(v)/lim,1);return t>0.55?'#fff':'';}}
function q(arr,p){{const s=arr.filter(x=>x!=null).map(Math.abs).sort((a,b)=>a-b);return s.length?s[Math.floor((s.length-1)*p)]:1;}}
function render(){{
 const d=HM[st.k], f=d[st.fq], n=d.rows.length;
 let vals, lim, fmt;
 if(st.mode==='rank'){{vals=f.rank.map(r=>r.map(x=>x==null?null:((n+1)/2-x)));lim=(n-1)/2;}}
 else{{vals=f[st.mode];lim=Math.max(q(vals.flat(),0.95),0.5);}}
 const show=st.mode==='rank'?f.rank:f[st.mode];
 let h='<thead><tr><th class="rn"></th>'+f.labels.map(l=>`<th>${{l}}</th>`).join('')+'</tr></thead><tbody>';
 if(st.fq==='m'&&d.phase){{h+='<tr class="phr"><th class="rn">相場の四季</th>'+d.phase.map((p,i)=>`<td style="background:${{p?PHC[p]:'transparent'}}" data-tip="${{f.labels[i]}}｜${{p||'判定なし'}}"></td>`).join('')+'</tr>';}}
 d.rows.forEach((nm,i)=>{{h+=`<tr><th class="rn">${{nm}}</th>`+vals[i].map((v,j)=>{{const s=show[i][j];
  const txt=s==null?'':(st.mode==='rank'?s:(Math.abs(s)>=10?s.toFixed(0):s.toFixed(1)));
  const tip=`${{nm}}｜${{f.labels[j]}}<br>対市場 ${{fmt2(f.rel[i][j])}}%　絶対 ${{fmt2(f.abs[i][j])}}%　順位 ${{f.rank[i][j]??'–'}}/${{n}}`;
  return `<td style="background:${{color(v,lim)}};color:${{ink(v,lim)}}" data-tip="${{tip}}">${{txt}}</td>`;}}).join('')+'</tr>';}});
 h+='<tr class="bm"><th class="rn">市場（ベンチマーク）</th>'+f.bench.map(v=>`<td>${{v==null?'':v.toFixed(1)}}</td>`).join('')+'</tr></tbody>';
 document.getElementById('hmT').innerHTML=h;
 const w=document.querySelector('.hmwrap');w.scrollLeft=w.scrollWidth;   // 最新の列が見えるように右端へ
 const unit=st.mode==='rank'?'順位（1位＝最も強い）':(st.mode==='rel'?'対市場リターン(%)':'絶対リターン(%)');
 const a=st.mode==='rank'?n:'−'+lim.toFixed(1), b=st.mode==='rank'?1:'+'+lim.toFixed(1);
 document.getElementById('hmLeg').innerHTML=`<span>${{a}}</span><span class="bar" style="background:linear-gradient(90deg,rgb(${{NEG}}),rgb(${{mid()}}),rgb(${{POS}}))"></span><span>${{b}}</span><span>${{unit}}（色の上限は上位5%を除いた値）</span>`;
}}
function fmt2(v){{return v==null?'–':(v>0?'+':'')+v.toFixed(1);}}
function bind(id,key,attr){{document.querySelectorAll('#'+id+' button').forEach(b=>b.onclick=()=>{{
 document.querySelectorAll('#'+id+' button').forEach(x=>x.classList.remove('on'));b.classList.add('on');st[key]=b.dataset[attr];render();}});}}
bind('hmMk','k','k');bind('hmMode','mode','v');bind('hmFq','fq','v');
const tip=document.getElementById('hmtip');
document.getElementById('hmT').addEventListener('mousemove',e=>{{const td=e.target.closest('td[data-tip]');
 if(!td){{tip.style.display='none';return;}}tip.innerHTML=td.dataset.tip;tip.style.display='block';
 const x=Math.min(e.clientX+14,innerWidth-tip.offsetWidth-8);tip.style.left=x+'px';tip.style.top=(e.clientY+14)+'px';}});
document.getElementById('hmT').addEventListener('mouseleave',()=>tip.style.display='none');
document.getElementById('hmT').addEventListener('click',e=>{{const td=e.target.closest('td[data-tip]');if(!td)return;
 tip.innerHTML=td.dataset.tip;tip.style.display='block';const r=td.getBoundingClientRect();
 tip.style.left=Math.max(8,Math.min(r.left,innerWidth-tip.offsetWidth-8))+'px';tip.style.top=(r.bottom+6)+'px';
 clearTimeout(window._hmt);window._hmt=setTimeout(()=>tip.style.display='none',2500);}});
render();
}})();
</script>"""
    return css + body + js


def heat_excel(wb, results):
    from openpyxl.formatting.rule import ColorScaleRule
    from openpyxl.styles import Font, PatternFill, Alignment
    H = Font(bold=True, color="FFFFFF")
    HF = PatternFill("solid", fgColor="1F3A5F")
    ws = wb.create_sheet("ヒートマップ")
    ws["A1"] = "セクター別 月次リターンの推移（上段＝対市場、下段＝絶対）。青＝強い／赤＝弱い。* は月の途中"
    ws["A1"].font = Font(bold=True)
    row = 3
    for key, res in results.items():
        if "heat" not in res:
            continue
        h = res["heat"]
        f = h["m"]
        for mode, title in [("rel", "対市場リターン(%)"), ("abs", "絶対リターン(%)")]:
            ws.cell(row=row, column=1, value=f"{res['label']}｜{title}").font = Font(bold=True)
            row += 1
            ws.cell(row=row, column=1, value="業種").font = H
            ws.cell(row=row, column=1).fill = HF
            for j, l in enumerate(f["labels"]):
                c = ws.cell(row=row, column=2 + j, value=l)
                c.font, c.fill = H, HF
                c.alignment = Alignment(horizontal="center")
            row += 1
            r0 = row
            for i, nm in enumerate(h["rows"]):
                ws.cell(row=row, column=1, value=nm)
                for j, v in enumerate(f[mode][i]):
                    c = ws.cell(row=row, column=2 + j, value=v)
                    c.number_format = "0.0"
                row += 1
            r1 = row - 1
            last = ws.cell(row=r0, column=1 + len(f["labels"])).column_letter
            ws.conditional_formatting.add(f"B{r0}:{last}{r1}", ColorScaleRule(
                start_type="percentile", start_value=5, start_color="DC2626",
                mid_type="num", mid_value=0, mid_color="F0EFEC",
                end_type="percentile", end_value=95, end_color="2563EB"))
            ws.cell(row=row, column=1, value="市場（ベンチマーク）").font = Font(italic=True)
            for j, v in enumerate(f["bench"]):
                ws.cell(row=row, column=2 + j, value=v).number_format = "0.0"
            row += 3
    ws.column_dimensions["A"].width = 22
    for j in range(2, 2 + MONTHS):
        ws.column_dimensions[ws.cell(row=1, column=j).column_letter].width = 7
    ws.freeze_panes = "B3"
