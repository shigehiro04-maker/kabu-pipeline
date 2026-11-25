#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
アナリスト予想ランキング（東証株）。通信なし。

入力
  fundamentals/analyst.csv                    fetch_analyst.py の出力（1行=1銘柄）
  tickers/tse_tickers.csv, tickers/sectors.csv 市場・業種（fetch_sectors.py の出力）
  fundamentals/fundamentals_latest.csv        時価総額（円）
  fundamentals/earnings_calendar.csv          次回決算日
出力
  data/charts/analyst.html          ランキング・業種別・読み方（analyst.html#コード でその銘柄を先頭に出す）
  data/charts/analyst_summary.json  トップ画面のカード用の要約

使い方
  python アナリスト予想/analyst_page.py
"""
import csv
import json
import math
import statistics
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
FUND = BASE / "fundamentals"
SITE = BASE / "data" / "charts"
STYLE = BASE / "需給分析" / "jukyu_style.css"   # 需給分析ページと同じ見た目


def read(p):
    if not p.exists():
        return []
    with open(p, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def num(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def r(v, d=1):
    return None if v is None else round(v, d)


def med(xs, d=1):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), d) if xs else None


def day_change(code):
    """株価CSVの最後の2行から前日比(%)"""
    p = BASE / "data" / "prices" / f"{code}.csv"
    try:
        with open(p, "rb") as f:
            try:
                f.seek(-400, 2)
            except OSError:
                f.seek(0)
            ls = f.read().decode("utf-8", "ignore").strip().splitlines()
        a, b = num(ls[-2].split(",")[4]), num(ls[-1].split(",")[4])
        return round((b / a - 1) * 100, 2) if a and b else None
    except Exception:
        return None


def build():
    tick = {t["code"]: t for t in read(BASE / "tickers" / "tse_tickers.csv")}
    sec = {t["code"]: t.get("sector33") or "未分類" for t in read(BASE / "tickers" / "sectors.csv")}
    lat = {x["コード"]: x for x in read(FUND / "fundamentals_latest.csv")}
    cal = {x["コード"]: x for x in read(FUND / "earnings_calendar.csv")}
    rows, asof = [], ""
    for a in read(FUND / "analyst.csv"):
        c = a["コード"]
        if c not in tick:
            continue
        g = lambda k: num(a.get(k))
        n_t, n_e = g("アナリスト人数"), g("今期EPS予想人数")
        if not (n_t or n_e):
            continue
        mc = num(lat.get(c, {}).get("時価総額"))
        asof = max(asof, a.get("取得日", ""))
        t = tick[c]
        rows.append([c, t["name"], t["market"], sec.get(c, "未分類"), g("株価"), g("目標株価_平均"),
                     r(g("上昇余地(%)")), r(g("上昇余地_安値(%)")), int(n_t) if n_t else None,
                     r(g("投資判断(1強い買い〜5強い売り)"), 2), r(g("買い比率(%)"), 0), r(g("投資判断_3か月の変化"), 2),
                     r(g("今期EPS修正_30日(%)")), r(g("今期EPS修正_90日(%)")), r(g("来期EPS成長率(%)")),
                     r(g("来期売上成長率(%)")), r(g("サプライズ_4期平均(%)")), a.get("予想超え回数(直近4期)", ""),
                     int(g("格上げ数_90日") or 0), int(g("格下げ数_90日") or 0),
                     r(mc / 1e8, 4) if mc else None, cal.get(c, {}).get("次回決算日", ""),
                     r(g("今期売上成長率(%)")), g("今期_上方修正数_30日"), g("今期_下方修正数_30日"),
                     r(g("今期EPS成長率(%)")), int(n_e) if n_e else None, g("今期EPS予想"),
                     int((g("強い買い") or 0) + (g("買い") or 0)), int(g("中立") or 0), int((g("売り") or 0) + (g("強い売り") or 0)),
                     day_change(c),
                     a.get("直近の判断変更日", "")])
    return rows, asof


def summary(rows, asof):
    cov = [x for x in rows if x[5] is not None and (x[8] or 0) >= 3]
    big = sorted([x for x in cov if x[20]], key=lambda x: -x[20])[:500]
    rev = [x for x in rows if x[23] is not None and x[24] is not None and (x[23] + x[24]) > 0]
    S = {"asof": asof, "銘柄数": len(rows), "目標株価あり": len(cov),
         "上位500の上昇余地中央値": med([x[6] for x in big]),
         "全体の上昇余地中央値": med([x[6] for x in cov]),
         "買い判断の割合": r(sum(1 for x in cov if x[9] is not None and x[9] <= 2.5) / len(cov) * 100) if cov else None,
         "上方修正が多い割合": r(sum(1 for x in rev if x[23] > x[24]) / len(rev) * 100) if rev else None,
         "上昇余地30%以上": sum(1 for x in cov if x[6] is not None and x[6] >= 30),
         "目標株価割れ": sum(1 for x in cov if x[6] is not None and x[6] < 0)}
    secs = {}
    for x in cov:
        secs.setdefault(x[3], []).append(x)
    S["業種"] = sorted([[k, len(v), med([y[6] for y in v]), med([y[9] for y in v], 2), med([y[12] for y in v]),
                        med([y[14] for y in v]), med([y[15] for y in v]),
                        r(sum(1 for y in v if (y[23] or 0) > (y[24] or 0)) / len(v) * 100, 0)] for k, v in secs.items()],
                      key=lambda z: -(z[2] if z[2] is not None else -999))
    return S


REDIRECT = """<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="0;url=./fundamentals.html#analyst"><title>アナリスト予想</title></head>
<body><p>アナリスト予想ランキングはスクリーニングの「アナリスト予想」タブに移りました。<a href="./fundamentals.html#analyst">開く</a></p>
<script>location.replace('./fundamentals.html#analyst');</script></body></html>
"""

def main():
    rows, asof = build()
    if not rows:
        print("アナリスト予想: fundamentals/analyst.csv にデータがありません（fetch_analyst.py を先に実行）")
        return
    S = summary(rows, asof)
    css = STYLE.read_text(encoding="utf-8") + EXTRA_CSS
    gen = datetime.now().strftime("%Y-%m-%d %H:%M")
    page = (PAGE.replace("/*CSS*/", css)
            .replace("/*DATA*/", json.dumps({"rows": rows, "sum": S}, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"))
            .replace("__ASOF__", asof).replace("__GEN__", gen))
    SITE.mkdir(parents=True, exist_ok=True)
    # 2026-11-15：ランキングの表はスクリーニング（fundamentals.html の「アナリスト予想」タブ）に移した。
    # analyst.html は古いリンク用の転送ページだけにする（page は使わない）
    (SITE / "analyst.html").write_text(REDIRECT, encoding="utf-8")
    (SITE / "analyst_summary.json").write_text(json.dumps({k: v for k, v in S.items() if k != "業種"}, ensure_ascii=False, indent=1),
                                               encoding="utf-8")
    print(f"アナリスト予想: {len(rows):,}銘柄（目標株価あり {S['目標株価あり']:,}・{asof} 取得）→ スクリーニングのタブで表示（要約 analyst_summary.json）")


EXTRA_CSS = """
.panel{background:var(--surface);border:0;border-radius:14px;padding:14px 16px;margin-bottom:14px}
.chips.sm{margin-top:6px}
.fl{display:flex;flex-wrap:wrap;gap:4px 18px;align-items:center;margin-top:6px}
.fl .chips{margin:0}.fl .cap{font-size:12px;color:var(--muted);margin-right:4px}
.dn3{display:inline-flex;align-items:center;gap:8px;text-align:left}
.dn3 svg{width:38px;height:38px;flex:none}.dn3 .c{font-size:11px;line-height:1.35;color:var(--ink2);white-space:nowrap}
.dn3 .c i{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:4px}
.rk td.rkno{color:var(--muted);font-weight:700;text-align:center;width:34px}
.rk td small.chg{display:block;font-size:11px}
select.sel{font:inherit;font-size:12.5px;padding:4px 8px;border-radius:8px;border:1px solid var(--border);background:var(--surface);color:var(--ink)}
.rec{display:inline-block;font-size:12px;font-weight:700;padding:1px 8px;border-radius:999px;background:var(--zb);color:var(--zc);white-space:nowrap}
.rk td.nm small{display:block;color:var(--muted);font-size:11px;font-weight:400}
.rk td.nm{max-width:300px;overflow:hidden;text-overflow:ellipsis}
.tblw{overflow-x:auto;-webkit-overflow-scrolling:touch}
@media (min-width:701px){#rank{min-width:1150px}#rank td.nm{white-space:nowrap;max-width:230px;overflow:hidden;text-overflow:ellipsis}#rank th,#rank td{padding-left:4px;padding-right:4px}}
#pick{border:2px solid var(--s1)}
#pick h2{display:flex;flex-wrap:wrap;gap:4px 12px;align-items:baseline}
#pick h2 a{font-size:13px;font-weight:600;color:var(--s1);text-decoration:none}
.kv{display:grid;grid-template-columns:repeat(6,1fr);gap:8px}.kv>div{border:1px solid var(--border);border-radius:10px;padding:7px 10px}
.kv .k{font-size:11.5px;color:var(--ink2)}.kv .v{font-size:18px;font-weight:800}.kv .s{font-size:11.5px;color:var(--muted)}
@media (max-width:900px){.kv{grid-template-columns:repeat(3,1fr)}}@media (max-width:520px){.kv{grid-template-columns:repeat(2,1fr)}}
"""

PAGE = r"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>アナリスト予想ランキング</title>
<script>(function(){try{var t=localStorage.getItem('fdb-theme');if(t)document.documentElement.setAttribute('data-theme',t);}catch(e){}})();</script>
<style>/*CSS*/</style></head><body><div class="wrap">
<header><h1><a href="./index.html" title="トップへ" style="text-decoration:none;color:inherit;margin-right:8px">‹</a>アナリスト予想ランキング</h1>
<div class="meta">予想は __ASOF__ 取得（週1回更新）・上昇余地は最新の終値で毎日計算・作成 __GEN__・データ：Yahoo Finance（証券会社アナリストの予想の集計）</div></header>

<div class="panel" id="mood"></div>
<div class="panel" id="qbox"><input type="search" id="q" placeholder="銘柄を探す — コード・銘柄名（例: 7203、トヨタ）" autocomplete="off"><div id="sugg"></div></div>
<div class="panel" id="pick" hidden></div>

<nav class="tabs" id="tabs"><a href="#rank" data-s="rank" class="on">ランキング</a><a href="#sector" data-s="sector">業種別</a><a href="#guide" data-s="guide">読み方</a></nav>

<section class="sec on" id="s-rank"><div class="panel">
<div class="chips" id="chips"></div>
<div class="fl"><div><span class="cap">市場</span><span class="chips sm" id="mkt"></span></div><div><span class="cap">規模</span><span class="chips sm" id="size"></span></div><div><span class="cap">アナリスト</span><span class="chips sm" id="minn"></span></div><div><span class="cap">セクター</span><select class="sel" id="secsel"></select></div></div>
<p class="hl z-neu" id="rankdesc" style="margin-top:10px"></p>
<div class="rkbar"><span class="meta" id="rcount"></span></div>
<div class="tblw"><table class="tbl rk" id="rank"></table></div><p class="tip">行を押すと、その銘柄の株式分析ダッシュボードを別画面で開きます。列名を押すと並べ替えできます。最大200件。色：<span class="up">赤＝上昇・強気</span>、<span class="dn">緑＝下落・弱気</span>。</p>
</div></section>

<section class="sec" id="s-sector"><div class="panel"><h2>業種別（セクター）のアナリスト予想</h2>
<div class="tblw"><table class="tbl" id="sect"></table></div><p class="tip">アナリスト3人以上の銘柄の中央値。投資判断は 1（強い買い）〜5（強い売り）。「上方修正が優勢」は直近30日に今期 EPS 予想の引き上げが引き下げより多かった銘柄の割合。</p></div></section>

<section class="sec" id="s-guide"><div class="panel"><h2>読み方</h2>
<h3>目標株価と上昇余地</h3><p>証券会社のアナリストが出している「12か月先の目標株価」の平均です。<b>上昇余地</b>は（目標株価の平均 ÷ 最新の終値 − 1）。アナリストは強気に偏りやすく、全体では平均で1〜2割ほど上に出るのがふつうなので、<b>プラスだから割安とは限りません</b>。株価が急落した直後は、目標株価の引き下げが追いつかず上昇余地が大きく見えます。</p>
<h3>投資判断</h3><p>強い買い＝1、買い＝2、中立＝3、売り＝4、強い売り＝5 として平均した点数です。<b>小さいほど強気</b>。「売り」判断は少なく、平均2.5より上（中立寄り）なら相対的に弱い評価です。「投資判断が改善」は3か月前の人数分布と比べた点数の変化です。</p>
<h3>EPS 予想の修正（リビジョン）</h3><p>今期の1株あたり利益（EPS）の平均予想が30日前・90日前からどれだけ上下したか。<b>予想の引き上げが続く銘柄は株価も上がりやすい</b>ことが知られており、目標株価よりも実績と結びつきやすい指標です。予想 EPS が小さい銘柄は%が極端になるため、ランキングでは今期 EPS 予想10円以上に限っています。</p>
<h3>成長率の予想</h3><p>来期の EPS・売上高の平均予想が今期の予想からどれだけ増えるか。</p>
<h3>決算サプライズ</h3><p>直近4四半期の EPS の実績が、決算前の平均予想をどれだけ上回ったか（%）。毎回上回る会社は、会社側の見通しが控えめな傾向があります。</p>
<h3>アナリスト人数</h3><p>人数が少ない銘柄は1人の予想で平均が大きく動きます。初期設定では3人以上の銘柄だけを出しています。</p>
<p class="tip">予想は Yahoo Finance が集計した値で、週1回取り直します。過去の予想は Yahoo に残らないため、取得のたびに手元に控えを残しています。売買を勧めるものではありません。</p></div></section>
</div>
<script>
const DATA=/*DATA*/;
const R=DATA.rows,S=DATA.sum;
// 0 code,1 name,2 mkt,3 sec,4 株価,5 目標株価,6 上昇余地,7 安値目標の上昇余地,8 人数,9 投資判断,10 買い比率,11 判断の3か月変化,12 今期EPS修正30日,13 同90日,
// 28 買い人数,29 中立人数,30 売り人数,31 前日比%,32 直近の判断変更日
// 14 来期EPS成長,15 来期売上成長,16 サプライズ4期平均,17 予想超え回数,18 格上げ90日,19 格下げ90日,20 時価総額(億ドル),21 次回決算,22 今期売上成長,23 上方修正数,24 下方修正数,25 今期EPS成長,26 EPS予想人数,27 今期EPS予想
const $=id=>document.getElementById(id);
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const f=(v,d=1)=>v==null?'—':Number(v).toLocaleString('ja-JP',{minimumFractionDigits:d,maximumFractionDigits:d});
const sg=(v,d=1,u='%')=>v==null?'—':`<span class="${v>0?'up':v<0?'dn':''}">${v>0?'+':''}${f(v,d)}${u}</span>`;
const usd=v=>v==null?'—':f(v,Math.abs(v)>=1000?0:1)+'円';
const cap=v=>v==null?'—':v>=10000?(v/10000).toFixed(2)+'兆円':Math.round(v).toLocaleString()+'億円';
const nn=x=>Math.max(x[8]||0,x[26]||0);
const recName=v=>v==null?'—':v<=1.5?'強い買い':v<=2.5?'買い':v<=3.5?'中立':v<=4.5?'売り':'強い売り';
const recZ=v=>v==null?'neu':v<=2.5?'bull':v<=3.5?'neu':'bear';
const rec=v=>v==null?'—':`<span class="rec z-${recZ(v)}">${recName(v)} ${f(v,2)}</span>`;

/* 全体のようす */
(function(){const m=S['上位500の上昇余地中央値'],u=S['上方修正が多い割合'];
 const z=u==null?'neu':u>=55?'bull':u<=45?'bear':'neu';
 $('mood').innerHTML=`<div class="mood"><div class="verdict z-${z}"><div class="w">${z==='bull'?'上方修正が優勢':z==='bear'?'下方修正が優勢':'修正は拮抗'}</div><div class="s">今期 EPS 予想の引き上げが引き下げより多い銘柄 ${f(u)}%（直近30日）</div></div>
 <div class="sig"><div class="z-neu"><div class="k"><span class="dot"></span>時価総額上位500社の上昇余地</div><div class="v">${sg(m)}</div><div class="s">目標株価の平均まで（中央値）</div></div>
 <div class="z-neu"><div class="k"><span class="dot"></span>買い判断の割合</div><div class="v">${f(S['買い判断の割合'])}%</div><div class="s">投資判断の平均が2.5以下</div></div>
 <div class="z-bull"><div class="k"><span class="dot"></span>上昇余地30%以上</div><div class="v">${S['上昇余地30%以上'].toLocaleString()}</div><div class="s">銘柄（アナリスト3人以上）</div></div>
 <div class="z-bear"><div class="k"><span class="dot"></span>株価が目標株価より上</div><div class="v">${S['目標株価割れ'].toLocaleString()}</div><div class="s">銘柄（上昇余地がマイナス）</div></div></div></div>`;})();

/* 検索 */
const nk=s=>String(s||'').normalize('NFKC').toLowerCase();
const BY={};R.forEach(x=>{x._s=nk(x[0]+' '+x[1]);BY[x[0]]=x;});
$('q').addEventListener('input',e=>{const q=nk(e.target.value).trim();if(!q){$('sugg').innerHTML='';return;}
 const hit=R.filter(x=>x._s.includes(q)).sort((a,b)=>(a[0].toLowerCase()===q?-1:0)-(b[0].toLowerCase()===q?-1:0)||(b[20]||0)-(a[20]||0)).slice(0,12);
 $('sugg').innerHTML=hit.map(x=>`<button data-c="${esc(x[0])}">${esc(x[0])} ${esc(x[1])}</button>`).join('');});
$('q').addEventListener('keydown',e=>{if(e.key==='Enter'){const b=$('sugg').querySelector('button');if(b)location.hash=encodeURIComponent(b.dataset.c);}});
$('sugg').addEventListener('click',e=>{const b=e.target.closest('button');if(b){location.hash=encodeURIComponent(b.dataset.c);$('sugg').innerHTML='';$('q').value='';}});

/* 選んだ銘柄 */
function pick(c){const x=BY[c],p=$('pick');if(!x){p.hidden=!c;if(c)p.innerHTML=`<b>${esc(c)}</b> のアナリスト予想はありません（カバーするアナリストがいない銘柄）。`;return;}
 p.hidden=false;const kv=(k,v,s)=>`<div><div class="k">${k}</div><div class="v">${v}</div><div class="s">${s||''}</div></div>`;
 p.innerHTML=`<h2><span>${esc(x[0])} ${esc(x[1])}</span><a href="./one/${encodeURIComponent(x[0])}.html">株式分析ダッシュボード ›</a><a href="./${encodeURIComponent(x[0])}.html">チャート ›</a></h2>
 <div class="meta" style="margin:-6px 0 8px">${esc(x[2])}・${esc(x[3])}・時価総額 ${cap(x[20])}${x[21]?'・次回決算 '+esc(x[21]):''}</div>
 <div class="kv">${kv('目標株価（平均）',usd(x[5]),'株価 '+usd(x[4])+'・'+(x[8]||'—')+'人')}${kv('上昇余地',sg(x[6]),'最も低い目標まで '+sg(x[7]))}
 ${kv('投資判断',rec(x[9]),'買い推奨 '+f(x[10],0)+'%')}${kv('今期 EPS 予想の変化',sg(x[12]),'30日前比・90日 '+sg(x[13]))}
 ${kv('来期の成長予想',sg(x[14]),'EPS・売上高 '+sg(x[15]))}${kv('決算サプライズ',sg(x[16]),'4期平均・予想超え '+(x[17]||'—'))}</div>`;}

/* ランキング */
const E=x=>x[27]!=null&&x[27]>=10;
const RK=[
 ['cnt','アナリスト注目度','担当するアナリストの人数が多い順。多くの証券会社が見ている銘柄ほど、予想の平均があてになります。',x=>nn(x),-1,28],
 ['up','上昇余地が大きい','目標株価の平均が、いまの株価より高い順。急落した直後の銘柄は目標株価の引き下げが追いついていないことがあります。上昇余地が200%を超える銘柄は、目標株価が古い（急落や株式併合の前のまま）とみて外しています。',x=>x[5]!=null&&x[6]<=200?x[6]:null,-1,6],
 ['dn','株価が目標を超えた','目標株価の平均より株価が高い順（上昇余地がマイナス）。期待が先行しているか、目標株価の引き上げ待ちの銘柄です。',x=>x[5]!=null&&x[6]<0?x[6]:null,1,6],
 ['lo','弱気な目標より安い','いちばん低い目標株価よりも、いまの株価が安い銘柄。最も弱気なアナリストから見ても上昇余地があります。（平均の上昇余地が200%を超える銘柄は外しています）',x=>x[7]!=null&&x[7]>0&&x[6]<=200?x[7]:null,-1,7],
 ['rec','投資判断が強い','投資判断の平均点が小さい（強い買いに近い）順。',x=>x[9],1,9],
 ['recw','投資判断が弱い','投資判断の平均点が大きい（売りに近い）順。',x=>x[9],-1,9],
 ['reci','投資判断が改善','3か月前と比べて投資判断の点数が下がった（強気に傾いた）順。',x=>x[11]!=null&&x[11]<0?x[11]:null,1,11],
 ['rvu','EPS 予想の上方修正','今期の EPS の平均予想が30日前から上がった順（今期 EPS 予想10円以上）。',x=>E(x)&&x[12]>0?x[12]:null,-1,12],
 ['rvd','EPS 予想の下方修正','今期の EPS の平均予想が30日前から下がった順（30日前の予想がプラスの銘柄）。',x=>x[12]!=null&&x[12]<0?x[12]:null,1,12],
 ['ge','来期の利益成長','来期の EPS 予想が今期の予想からどれだけ増えるか（今期 EPS 予想10円以上）。',x=>E(x)?x[14]:null,-1,14],
 ['gs','来期の売上成長','来期の売上高予想が今期の予想からどれだけ増えるか。',x=>x[15],-1,15],
 ['sp','決算サプライズ','直近4四半期の EPS 実績が予想を上回った幅の平均。4回とも予想を上回った銘柄に限る。',x=>x[17]==='4/4'&&E(x)?x[16]:null,-1,16],
 ['ug','格上げが多い','直近90日の格上げの数が多い順（格下げを引いた数）。',x=>x[18]-x[19]>0?x[18]-x[19]:null,-1,18],
];
// 判断変更の履歴が5%以上の銘柄にあるときだけ、その列・ランキングを出す（東証銘柄はほとんど無い）
const HASDT=R.filter(x=>x[32]).length>=R.length*0.05,HASUD=HASDT&&R.some(x=>x[18]||x[19]);
if(!HASUD)RK.splice(RK.findIndex(r=>r[0]==='ug'),1);
const MKT=['全市場','プライム','スタンダード','グロース'];
const SIZE=[['all','すべて',0,1e12],['L','大型（5,000億円〜）',5000,1e12],['M','中型（500億〜5,000億円）',500,5000],['S','小型（〜500億円）',0,500]];
const MINN=[3,5,10,20];
let st={rk:'cnt',mk:'全市場',sz:'all',mn:3,sec:'',sk:null,asc:false};
const SECS=[...new Set(R.map(x=>x[3]))].sort();
$('secsel').innerHTML='<option value="">全セクター</option>'+SECS.map(s=>`<option>${esc(s)}</option>`).join('');
$('secsel').onchange=e=>{st.sec=e.target.value;rank();};
// 買い・中立・売りの人数の小さな円グラフ
function donut(x){const a=[x[28]||0,x[29]||0,x[30]||0],n=a[0]+a[1]+a[2];if(!n)return '—';const C=2*Math.PI*15,col=['var(--bull)','var(--muted)','var(--bear)'];let o=0,s='';
 a.forEach((v,i)=>{if(!v)return;const l=v/n*C;s+=`<circle cx="20" cy="20" r="15" fill="none" stroke-width="5" style="stroke:${col[i]}" stroke-dasharray="${l.toFixed(2)} ${(C-l).toFixed(2)}" stroke-dashoffset="${(-o).toFixed(2)}" transform="rotate(-90 20 20)"/>`;o+=l;});
 return `<span class="dn3"><svg viewBox="0 0 40 40">${s}<text x="20" y="24" text-anchor="middle" font-size="12" font-weight="800" style="fill:var(--ink)">${n}</text></svg><span class="c"><i style="background:var(--bull)"></i>${a[0]} 買い<br><i style="background:var(--muted)"></i>${a[1]} 中立<br><i style="background:var(--bear)"></i>${a[2]} 売り</span></span>`;}
const chips=(id,html,key,fn)=>{$(id).innerHTML=html;$(id).onclick=e=>{const b=e.target.closest('button');if(!b)return;fn(b.dataset.k);[...$(id).children].forEach(x=>x.classList.toggle('on',x===b));rank();};};
chips('chips',RK.map(r=>`<button data-k="${r[0]}"${r[0]===st.rk?' class="on"':''}>${r[1]}</button>`).join(''),'rk',k=>{st.rk=k;st.sk=null;});
chips('mkt',MKT.map(m=>`<button data-k="${m}"${m===st.mk?' class="on"':''}>${m}</button>`).join(''),'mk',k=>{st.mk=k;});
chips('size',SIZE.map(m=>`<button data-k="${m[0]}"${m[0]===st.sz?' class="on"':''}>${m[1]}</button>`).join(''),'sz',k=>{st.sz=k;});
chips('minn',MINN.map(m=>`<button data-k="${m}"${m===st.mn?' class="on"':''}>${m}人以上</button>`).join(''),'mn',k=>{st.mn=+k;});
const COLS0=[['順位',null],['銘柄',null],['前日終値',31],['アナリスト予想',28],['投資判断',9],['目標株価の平均',5],['かい離率',6],['EPS修正30日',12],['来期EPS成長',14],['サプライズ',16],['予想更新日',32],['時価総額',20]];
function rank(){const R0=RK.find(r=>r[0]===st.rk),sz=SIZE.find(s=>s[0]===st.sz);$('rankdesc').textContent=R0[2];
 let L=R.filter(x=>(st.mk==='全市場'||x[2]===st.mk)&&nn(x)>=st.mn&&(st.sz==='all'||(x[20]!=null&&x[20]>=sz[2]&&x[20]<sz[3]))&&(!st.sec||x[3]===st.sec)&&R0[3](x)!=null);
 if(st.sk!=null){const i=st.sk;L.sort((a,b)=>a[i]==null?1:b[i]==null?-1:(typeof a[i]==='string'?a[i].localeCompare(b[i]):(a[i]-b[i]))*(st.asc?1:-1));}
 else L.sort((a,b)=>(R0[3](a)-R0[3](b))*R0[4]||(b[20]||0)-(a[20]||0));
 $('rcount').textContent=`該当 ${L.length.toLocaleString()} 銘柄`+(L.length>200?'（上位200件を表示）':'');
 const k=R0[5],td=(l,v,i,cls='')=>`<td class="n${cls}${i===k?' key':''}" data-l="${l}">${v}</td>`;
 const slot=k===15?['来期売上成長',15,x=>sg(x[15])]:k===18?['格上げ／下げ（90日）',18,x=>`<span class="up">↑${x[18]}</span> <span class="dn">↓${x[19]}</span>`]:['サプライズ',16,x=>sg(x[16])+(x[17]?` <small style="color:var(--muted)">${esc(x[17])}</small>`:'')];
 const COLS=COLS0.filter(c=>HASDT||c[0]!=='予想更新日').map(c=>c[0]==='サプライズ'?[slot[0],slot[1]]:c[0]==='かい離率'&&k===7?['安値目標まで',7]:c);
 $('rank').innerHTML='<thead><tr>'+COLS.map(([h,i])=>`<th class="${i==null?'':'n'}${st.sk===i&&i!=null?' sorted'+(st.asc?' asc':''):''}" data-i="${i==null?'':i}">${h}</th>`).join('')+'</tr></thead><tbody>'+
  L.slice(0,200).map((x,n)=>`<tr class="rw" data-c="${esc(x[0])}"><td class="rkno hide-sp">${n+1}</td><td class="nm"><b>${esc(x[0])}</b> ${esc(x[1])}<small>${esc(x[2])}・${esc(x[3])}</small></td>`+
   td('前日終値',usd(x[4])+`<small class="chg">${sg(x[31],2)}</small>`,31,' hide-sp')+td('アナリスト予想',donut(x),28)+
   td('投資判断',rec(x[9])+(k===11?' '+sg(x[11],2,''):''),k===11?11:9)+td('目標株価の平均',usd(x[5]),5)+td(k===7?'安値目標まで':'かい離率',sg(k===7?x[7]:x[6]),k===7?7:6)+
   td('EPS修正30日',sg(x[12]),12,' hide-sp')+td('来期EPS成長',sg(x[14]),14,' hide-sp')+td(slot[0],slot[2](x),slot[1],' hide-sp')+
   (HASDT?td('予想更新日',x[32]?esc(x[32].replace(/-/g,'/')):'—',32,' hide-sp'):'')+td('時価総額',cap(x[20]),20,' hide-sp')+'</tr>').join('')+'</tbody>';}
$('rank').addEventListener('click',e=>{const th=e.target.closest('th');if(th&&th.dataset.i!==''){const i=+th.dataset.i;if(st.sk===i)st.asc=!st.asc;else{st.sk=i;st.asc=false;}rank();return;}
 const tr=e.target.closest('tr.rw');if(tr)window.open('./one/'+encodeURIComponent(tr.dataset.c)+'.html','_blank');});
rank();

/* 業種別 */
$('sect').innerHTML='<thead><tr><th>業種</th><th class="n">銘柄数</th><th class="n">上昇余地</th><th class="n">投資判断</th><th class="n">EPS修正30日</th><th class="n">来期EPS成長</th><th class="n">来期売上成長</th><th class="n">上方修正が優勢</th></tr></thead><tbody>'+
 S['業種'].map(s=>`<tr><td>${esc(s[0])}</td><td class="n">${s[1]}</td><td class="n">${sg(s[2])}</td><td class="n">${rec(s[3])}</td><td class="n">${sg(s[4])}</td><td class="n">${sg(s[5])}</td><td class="n">${sg(s[6])}</td><td class="n">${f(s[7],0)}%</td></tr>`).join('')+'</tbody>';

/* 画面の切り替え：#rank #sector #guide はタブ、それ以外は銘柄コード（その銘柄を上に出す） */
function route(){const h=decodeURIComponent(location.hash.slice(1));const tabs=['rank','sector','guide'];
 const t=tabs.includes(h)?h:'rank';
 document.querySelectorAll('.sec').forEach(s=>s.classList.toggle('on',s.id==='s-'+t));
 document.querySelectorAll('#tabs a').forEach(a=>a.classList.toggle('on',a.dataset.s===t));
 pick(tabs.includes(h)?'':h);}
addEventListener('hashchange',route);route();
</script></body></html>
"""

if __name__ == "__main__":
    main()
