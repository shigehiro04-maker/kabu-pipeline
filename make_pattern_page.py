#!/usr/bin/env python3
"""チャート形状検索（25通りの形）の一覧ページ data/charts/patterns.html を作る。

  python make_pattern_page.py

  個別チャートの「トレンド（直近3か月の形）」と同じ計算：
    直近60営業日の終値（対数）を 2次式 a + b·t + q·t²（t は −1〜1）で当てはめ、
    縦＝60営業日の騰落率（％）、横＝2次の項 q（％）で 5×5 に分類する。
  チャートの形を選ぶと、その形の銘柄が一覧表で出る（銘柄を押すと個別チャート）。
  data/charts/patterns_summary.json（トップ画面のカード用）も書く。
"""
import datetime
import json
import math
import unicodedata
import os

import numpy as np

import make_chart_html as mc

N = 60
NAMES = [["上昇一服", "そろそろ天井", "上昇", "まだ上昇", "急上昇"],
         ["売り？", "上昇ストップ？", "上昇基調", "強含み", "しっかり"],
         ["行って来い", "戻らない？", "もみ合い", "戻ってくる？", "リバウンド"],
         ["下押す", "弱含み", "下落基調", "下落ストップ？", "これから上昇？"],
         ["急落", "まだ下落", "下落", "下げ渋る", "下げ止まった？"]]


def classify(c):
    """c: 終値の配列（古い→新しい）。戻り値 (行, 列, 騰落率%, 曲がり%) または None"""
    n = len(c)
    if n < N + 30:
        return None
    t = np.linspace(-1, 1, N)
    X = np.vstack([np.ones(N), t, t * t]).T
    _, _, q = np.linalg.lstsq(X, np.log(c[-N:]), rcond=None)[0]
    pS = math.log(c[-1] / c[n - N]) * 100
    pK = q * 100
    pr = 0 if pS >= 15 else 1 if pS >= 5 else 2 if pS > -5 else 3 if pS > -15 else 4
    pk = 0 if pK <= -8 else 1 if pK <= -3 else 2 if pK < 3 else 3 if pK < 8 else 4
    return pr, pk, pS, pK


def main():
    cat = mc.catalog()
    recs, last_dates = [], []
    for code, info in sorted(cat.items()):
        try:
            df, _ = mc.load_prices(code)
        except Exception:
            continue
        if df is None or len(df) < N + 30:
            continue
        c = df["close"].to_numpy(float)
        r = classify(c)
        if r is None:
            continue
        d = df["date"].iloc[-1]
        last_dates.append(d)
        ma25 = c[-25:].mean()
        pct = lambda k: round((c[-1] / c[-1 - k] - 1) * 100, 1) if len(c) > k else None
        recs.append({"d": d, "row": [code, unicodedata.normalize("NFKC", info.get("name", code)), info.get("market", ""), info.get("sector", ""),
                     round(float(c[-1]), 1), pct(1), pct(21), pct(63), round((c[-1] / ma25 - 1) * 100, 1),
                     r[0], r[1], round(r[2], 1), round(r[3], 1)]})
    if not recs:
        print("分類できる銘柄がありませんでした"); return
    newest = max(last_dates)
    # 取引が止まっている銘柄（最新日から10日以上古い）は除く
    rows = [x["row"] for x in recs if (newest - x["d"]).days <= 10]
    cnt = [[0] * 5 for _ in range(5)]
    for r in rows:
        cnt[r[9]][r[10]] += 1
    asof = newest.strftime("%Y-%m-%d")
    html = (TMPL.replace("__DATA__", json.dumps(rows, ensure_ascii=False, separators=(",", ":")))
                .replace("__NAMES__", json.dumps(NAMES, ensure_ascii=False))
                .replace("__ASOF__", asof)
                .replace("__BUILT__", datetime.datetime.now().strftime("%Y-%m-%d %H:%M")))
    out = os.path.join(mc.OUTDIR, "patterns.html")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)
    flat = sorted(((cnt[i][j], i, j) for i in range(5) for j in range(5)), reverse=True)
    up = sum(cnt[0]) + sum(cnt[1]); dn = sum(cnt[3]) + sum(cnt[4])
    summ = {"asof": asof, "n": len(rows), "counts": cnt, "top": [NAMES[flat[0][1]][flat[0][2]], flat[0][0]],
            "up": up, "flat": sum(cnt[2]), "down": dn}
    with open(os.path.join(mc.OUTDIR, "patterns_summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summ, fh, ensure_ascii=False)
    print(f"チャート形状検索: {out}（{len(rows)}銘柄・{asof}、最多は {summ['top'][0]} {summ['top'][1]}銘柄）")


TMPL = r"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>チャート形状検索</title>
<script>(function(){var m=/[?&]theme=(dark|light)/.exec(location.search),t=m&&m[1];
if(!t){try{t=localStorage.getItem('fdb-theme')}catch(e){}}if(t)document.documentElement.setAttribute('data-theme',t);})();</script>
<style>
@import url("https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap");
:root{--bg:#f3f4f6;--card:#fff;--fg:#0c0d10;--fg2:#3d4148;--mut:#5b6068;--line:#dfe2e7;--up:#b91c24;--dn:#08705a;--upb:#c8323a;--dnb:#0f7f63;color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#050608;--card:#101216;--fg:#f2f4f8;--fg2:#c6cbd6;--mut:#8f96a3;--line:#23262d;--up:#ff7378;--dn:#3fd0a4;--upb:#c8323a;--dnb:#0f7f63;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#050608;--card:#101216;--fg:#f2f4f8;--fg2:#c6cbd6;--mut:#8f96a3;--line:#23262d;--up:#ff7378;--dn:#3fd0a4;--upb:#c8323a;--dnb:#0f7f63;color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.55 Inter,"Hiragino Sans","Hiragino Kaku Gothic ProN","Noto Sans JP",system-ui,-apple-system,sans-serif;font-variant-numeric:tabular-nums;-webkit-font-smoothing:antialiased}
main{max-width:1180px;margin:0 auto;padding:24px 20px 56px}
h1{font-size:24px;font-weight:800;margin:0;display:flex;align-items:baseline;gap:12px;flex-wrap:wrap}
h1 a{color:var(--mut);text-decoration:none;font-weight:400}
h1 small{font-size:12.5px;font-weight:400;color:var(--mut)}
.u{color:var(--up)}.d{color:var(--dn)}
.bar{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin:16px 0 12px}
.seg{display:inline-flex;background:var(--card);border-radius:10px;padding:3px;gap:2px}
.seg button{border:0;background:transparent;color:var(--mut);font:inherit;font-size:13px;font-weight:700;padding:6px 12px;border-radius:8px;cursor:pointer}
.seg button.on{background:var(--fg);color:var(--bg)}
.sum{font-size:13px;color:var(--fg2)}.sum b{font-weight:800}
.ax{display:grid;grid-template-columns:28px minmax(0,1fr);gap:6px}
.ax .yl{writing-mode:vertical-rl;text-orientation:upright;font-size:11px;font-weight:800;letter-spacing:.2em;color:var(--mut);display:flex;justify-content:space-between;align-items:center;padding:6px 0}
.ax .xl{grid-column:2;display:flex;justify-content:space-between;font-size:11px;font-weight:800;color:var(--mut);letter-spacing:.06em;padding:0 4px}
.grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px}
.pc{background:transparent;border:0;padding:0;cursor:pointer;color:var(--fg);font:inherit;text-align:left;display:flex;flex-direction:column;gap:3px;min-width:0}
.pc .ib{background:var(--card);border-radius:12px;padding:10px 12px;box-shadow:inset 0 0 0 2px transparent;transition:box-shadow .1s,transform .08s}
.pc:hover .ib{transform:translateY(-1px)}
.pc svg.ar{width:100%;height:58px;display:block}
.pc .nm{font-size:13.5px;font-weight:800;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:4px}
.pc .ct{display:flex;align-items:center;gap:8px}
.pc .ct b{font-size:18px;font-weight:800;letter-spacing:-.02em;line-height:1.1;min-width:2.6em}
.pc .dots{display:grid;grid-template-columns:repeat(10,4px);grid-template-rows:repeat(2,4px);gap:2px}
.pc .dots i{background:var(--line)}.pc .dots i.f{background:var(--fg)}
.pc.zero{opacity:.45}
.pc.on .ib{box-shadow:inset 0 0 0 2px var(--fg)}
.pc.on .nm{text-decoration:underline;text-underline-offset:3px;text-decoration-thickness:2px}
h2{font-size:14px;font-weight:800;letter-spacing:.08em;border-top:3px solid var(--fg);padding-top:12px;margin:30px 0 10px;display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
h2 big{font-size:22px;letter-spacing:0}
h2 small{font-weight:400;letter-spacing:0;color:var(--mut);font-size:12.5px}
.q{width:100%;max-width:420px;height:42px;font:inherit;font-size:15px;font-weight:700;border:0;border-bottom:3px solid var(--fg);background:transparent;color:var(--fg);outline:none;margin-bottom:8px}
.tw{overflow-x:auto;background:var(--card);border-radius:14px}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:8px 10px;text-align:right;white-space:nowrap;border-top:1px solid var(--line)}
thead th{border-top:0;border-bottom:2px solid var(--fg);font-size:11.5px;font-weight:800;cursor:pointer;user-select:none;position:sticky;top:0;background:var(--card)}
thead th.s::after{content:" ▼";font-size:9px}thead th.s.a::after{content:" ▲"}
th.l,td.l{text-align:left}
tbody tr{cursor:pointer}tbody tr:hover{background:rgba(127,127,127,.08)}
td.c{font-weight:800}td.n{font-weight:700;max-width:16em;overflow:hidden;text-overflow:ellipsis}
td.m{color:var(--mut);font-size:12px}
.more{display:block;margin:10px auto 0;border:0;background:var(--card);color:var(--fg);font:inherit;font-weight:800;padding:8px 18px;border-radius:10px;cursor:pointer}
details{margin-top:24px;font-size:13px;color:var(--fg2)}details summary{cursor:pointer;font-weight:800;color:var(--fg)}
.note{font-size:12px;color:var(--mut)}
@media(max-width:760px){main{padding:16px 10px 40px}h1{font-size:19px}.grid{gap:4px}.ax{grid-template-columns:16px minmax(0,1fr);gap:3px}.ax .yl{font-size:9.5px;letter-spacing:.05em}
 .pc .ib{padding:6px 4px;border-radius:8px}.pc .nm{font-size:10px;margin-top:2px}.pc svg.ar{height:28px}
 .pc .ct b{font-size:13px;min-width:0}.pc .dots{display:none}
 td.n{max-width:9em}.hide-s{display:none}}
</style></head><body><main>
<h1><a href="./index.html" title="トップへ">‹</a>チャート形状検索<small>直近3か月（60営業日）の値動きを25通りに分類　__ASOF__ 時点</small></h1>
<div class="bar"><div class="seg" id="mk"></div><div class="sum" id="sum"></div></div>
<div class="ax"><div class="yl"><span>上昇</span><span>下落</span></div><div class="grid" id="grid"></div>
<div class="xl"><span>← 上に凸（伸び悩み・天井型）</span><span>まっすぐ</span><span>下に凸（加速・底打ち型） →</span></div></div>

<h2 id="h"><big id="hn">—</big><span id="hc"></span><small id="hd"></small></h2>
<input class="q" id="q" type="search" placeholder="この形の中から探す — コード・銘柄名・業種" autocomplete="off">
<div class="tw"><table><thead><tr>
<th class="l" data-k="0">コード</th><th class="l" data-k="1">銘柄名</th><th class="l hide-s" data-k="2">市場</th><th class="l hide-s" data-k="3">業種</th>
<th data-k="4">終値</th><th data-k="5">前日比</th><th data-k="6">1か月</th><th data-k="7">3か月</th><th class="hide-s" data-k="8">25日線乖離</th>
</tr></thead><tbody id="tb"></tbody></table></div>
<button class="more" id="more" type="button" hidden>もっと見る</button>

<details><summary>分類のしかた</summary>
<p>直近60営業日の終値（対数）に、なめらかな曲線（2次式）を当てはめて形を決めています。個別チャートの「トレンド（直近3か月の形）」と同じ計算です。</p>
<p><b>縦（上がり方）</b>：60営業日の騰落率。＋15%以上／＋5%以上／±5%未満／−5%以下／−15%以下の5段階。<br>
<b>横（曲がり方）</b>：曲線の2次の項の大きさ。−8%以下（大きく上に凸）／−3%以下／±3%未満（まっすぐ）／＋3%以上／＋8%以上（大きく下に凸）の5段階。</p>
<p class="note">形はあくまで過去3か月の値動きの要約で、この先を予想するものではありません。投資判断はご自身で。作成 __BUILT__</p>
</details>
</main><script>
const R=__DATA__;  // [コード,銘柄名,市場,業種,終値,前日比%,1か月%,3か月%,25日線乖離%,行,列,騰落率%,曲がり%]
const PN=__NAMES__;
const $=id=>document.getElementById(id);
function arrow(r,k){ const s=[1.4,.8,0,-.8,-1.4][r], q=(r===0||r===4?[-.7,-.35,0,.35,.7]:[-1,-.5,0,.5,1])[k], W=62, H=44, P=5;
    const f=x=>s*x+q*x*x, ys=[]; for(let i=0;i<=40;i++){ const x=-1+i/20; ys.push(f(x)); }
    const m0=Math.min(...ys), m1=Math.max(...ys), mid=(m0+m1)/2, sp=Math.max(m1-m0,1.6)/2, lo=mid-sp, hi=mid+sp, X=x=>P+(x+1)/2*(W-2*P-4), Y=v=>P+(hi-v)/(hi-lo)*(H-2*P);
    let pts=ys.map((v,i)=>[X(-1+i/20),Y(v)]);
    if(k===2){ pts=[]; for(let i=0;i<=8;i++){ const x=-1+i/4; pts.push([X(x),Y(f(x)+(i%2?-.3:.3)*(s<0?-1:1)*(i&&i<8?1:0))]); } }
    const [x1,y1]=pts[pts.length-1], [x0,y0]=pts[pts.length-(k===2?2:3)], ang=Math.atan2(y1-y0,x1-x0), L2=8;
    const h=[[x1-L2*Math.cos(ang-.5),y1-L2*Math.sin(ang-.5)],[x1-L2*Math.cos(ang+.5),y1-L2*Math.sin(ang+.5)]];
    const col=r<2?'var(--up)':r>2?'var(--dn)':'var(--fg)';
    return `<svg class="ar" viewBox="0 0 ${W} ${H}" aria-hidden="true"><path d="M${pts.map(p=>p[0].toFixed(1)+','+p[1].toFixed(1)).join('L')}" fill="none" stroke="${col}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/><path d="M${h[0][0].toFixed(1)},${h[0][1].toFixed(1)}L${x1.toFixed(1)},${y1.toFixed(1)}L${h[1][0].toFixed(1)},${h[1][1].toFixed(1)}" fill="none" stroke="${col}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>`; }
const MK=[["","全市場"],["プライム","プライム"],["スタンダード","スタンダード"],["グロース","グロース"]];
let mk="", sel=null, sk=7, asc=false, lim=200;
try{ const m=localStorage.getItem("pat-mk"); if(MK.some(x=>x[0]===m)) mk=m; }catch(e){}
(function(){ const m=/^#(\d)-(\d)$/.exec(location.hash); if(m) sel=[+m[1],+m[2]]; })();
const fx=v=>v==null?'—':v>=1000?Math.round(v).toLocaleString():v.toLocaleString(undefined,{maximumFractionDigits:1});
const pc=v=>v==null?'—':`<span class="${v>0?'u':v<0?'d':''}">${v>0?'+':''}${v.toFixed(1)}%</span>`;
const nk=s=>String(s).normalize("NFKC").toLowerCase();
const pool=()=>R.filter(r=>!mk||r[2]===mk);
function drawGrid(){
  const P=pool(), C=[0,1,2,3,4].map(()=>[0,0,0,0,0]); P.forEach(r=>C[r[9]][r[10]]++);
  const mx=Math.max(1,...C.flat());
  if(!sel){ let b=[2,2],v=-1; C.forEach((row,i)=>row.forEach((x,j)=>{ if(x>v){v=x;b=[i,j];} })); sel=b; }
  $("grid").innerHTML=[0,1,2,3,4].map(i=>[0,1,2,3,4].map(j=>{ const n=C[i][j], on=sel[0]===i&&sel[1]===j;
    const f=n?Math.max(1,Math.round(n/mx*20)):0;
    return `<button type="button" class="pc${on?' on':''}${n?'':' zero'}" data-r="${i}" data-k="${j}" title="${PN[i][j]}：${n.toLocaleString()}銘柄（${P.length?(n/P.length*100).toFixed(1):0}%）"><div class="ib">${arrow(i,j)}</div><div class="nm">${PN[i][j]}</div>
      <div class="ct"><b>${n.toLocaleString()}</b><span class="dots">${Array.from({length:20},(_,x)=>`<i class="${(x%10)*2+(x<10?0:1)<f?'f':''}"></i>`).join('')}</span></div></button>`; }).join('')).join('');
  const up=C[0].concat(C[1]).reduce((a,b)=>a+b,0), dn=C[3].concat(C[4]).reduce((a,b)=>a+b,0);
  $("sum").innerHTML=`対象 <b>${P.length.toLocaleString()}</b>銘柄　<span class="u">上昇側 <b>${up.toLocaleString()}</b></span>　横ばい <b>${C[2].reduce((a,b)=>a+b,0).toLocaleString()}</b>　<span class="d">下落側 <b>${dn.toLocaleString()}</b></span>`;
}
function drawTable(){
  const q=nk($("q").value.trim());
  let L=pool().filter(r=>r[9]===sel[0]&&r[10]===sel[1]);
  const tot=L.length;
  if(q) L=L.filter(r=>nk(r[0]+" "+r[1]+" "+r[3]).includes(q));
  L.sort((a,b)=>{ const x=a[sk],y=b[sk]; if(x==null) return 1; if(y==null) return -1;
    const c=typeof x==="string"?x.localeCompare(y,"ja"):x-y; return asc?c:-c; });
  $("hn").textContent=PN[sel[0]][sel[1]];
  $("hc").innerHTML=`<b>${tot.toLocaleString()}</b>銘柄`+(q?`（うち該当 ${L.length.toLocaleString()}）`:'');
  $("hd").textContent=(mk?mk+"・":"")+"銘柄を押すと個別チャート";
  $("tb").innerHTML=L.slice(0,lim).map(r=>`<tr data-c="${r[0]}"><td class="l c">${r[0]}</td><td class="l n">${r[1]}</td><td class="l m hide-s">${r[2]}</td><td class="l m hide-s">${r[3]}</td>
    <td>${fx(r[4])}</td><td>${pc(r[5])}</td><td>${pc(r[6])}</td><td>${pc(r[7])}</td><td class="hide-s">${pc(r[8])}</td></tr>`).join('')
    || '<tr><td colspan="9" class="l m">該当する銘柄がありません</td></tr>';
  $("more").hidden=L.length<=lim; $("more").textContent=`もっと見る（残り ${(L.length-lim).toLocaleString()}）`;
  document.querySelectorAll("thead th").forEach(th=>{ th.classList.toggle("s",+th.dataset.k===sk); th.classList.toggle("a",+th.dataset.k===sk&&asc); });
}
$("mk").innerHTML=MK.map(([k,l])=>`<button type="button" data-m="${k}" class="${k===mk?'on':''}">${l}</button>`).join('');
$("mk").onclick=e=>{ const b=e.target.closest("button"); if(!b) return; mk=b.dataset.m; try{localStorage.setItem("pat-mk",mk)}catch(e){}
  document.querySelectorAll("#mk button").forEach(x=>x.classList.toggle("on",x===b)); lim=200; drawGrid(); drawTable(); };
$("grid").onclick=e=>{ const b=e.target.closest(".pc"); if(!b) return; sel=[+b.dataset.r,+b.dataset.k]; lim=200;
  history.replaceState(null,"","#"+sel[0]+"-"+sel[1]); drawGrid(); drawTable();
  if(innerWidth<760) $("h").scrollIntoView({behavior:"smooth"}); };
$("q").oninput=()=>{ lim=200; drawTable(); };
$("more").onclick=()=>{ lim+=300; drawTable(); };
document.querySelector("thead").onclick=e=>{ const th=e.target.closest("th"); if(!th) return; const k=+th.dataset.k;
  if(k===sk) asc=!asc; else { sk=k; asc=k<=3; } drawTable(); };
$("tb").onclick=e=>{ const tr=e.target.closest("tr[data-c]"); if(tr) location.href="./"+tr.dataset.c+".html"; };
addEventListener("hashchange",()=>{ const m=/^#(\d)-(\d)$/.exec(location.hash); if(m){ sel=[+m[1],+m[2]]; drawGrid(); drawTable(); } });
drawGrid(); drawTable();
</script></body></html>"""


if __name__ == "__main__":
    main()
