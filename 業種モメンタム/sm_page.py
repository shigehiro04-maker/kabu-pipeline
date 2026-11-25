#!/usr/bin/env python3
"""業種モメンタムの画面 data/charts/sector_mom.html と、トップ画面のカード用 sector_mom_summary.json（通信なし・十数秒）"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

from sm_common import (DAILY, GAP_DAILY, OUT, SIG, SITE, START, W_GAP, W_SM, is_month_end, load_panel,
                       load_sectors, make_signal, next_business_day)

STOP_DD = -25.0


def monthly(d: pd.DataFrame, col: str) -> pd.Series:
    x = d[col] / 100
    return (1 + x).groupby(pd.to_datetime(d["日付"]).dt.to_period("M")).prod() - 1


def stats(x: pd.Series, ppy: int) -> dict:
    x = x.dropna()
    if len(x) < 2:
        return dict(n=int(len(x)))
    eq = (1 + x).cumprod()
    return dict(n=int(len(x)), cum=round(float((eq.iloc[-1] - 1) * 100), 2), ann=round(float(x.mean() * ppy * 100), 2),
                sharpe=round(float(x.mean() / x.std() * np.sqrt(ppy)), 2) if x.std() > 0 else None,
                dd=round(float((eq / eq.cummax() - 1).min() * 100), 2))


def curve(d: pd.DataFrame, cols: list[str]) -> list:
    out = []
    eq = {c: 1.0 for c in cols}
    for _, r in d.iterrows():
        row = [str(r["日付"])]
        for c in cols:
            eq[c] *= 1 + (r[c] if np.isfinite(r[c]) else 0) / 100
            row.append(round((eq[c] - 1) * 100, 3))
        out.append(row)
    return out


def thin(v: list, n: int = 700) -> list:
    if len(v) <= n:
        return v
    step = int(np.ceil(len(v) / n)); return v[::step] + ([v[-1]] if (len(v) - 1) % step else [])


def main():
    sec = load_sectors()
    P = load_panel(sec.index)
    days = P["close"].index; last = days[-1]
    files = sorted(SIG.glob("*.csv"))
    if files:
        s = pd.read_csv(files[-1], dtype={"コード": str}); s_date = files[-1].stem; s_kind = "判断"
    else:
        s = make_signal(P, sec, last); s_date = str(last.date()); s_kind = "参考"
    rk = (s.groupby("業種").agg(順位=("業種の順位", "first"), 点数=("業種の点数_pct", "first"), 区分=("区分", "first"),
                               銘柄数=("コード", "size")).sort_values("順位").reset_index())
    lead = {g: s[s["業種"] == g].sort_values("銘柄の12か月_pct", ascending=False).head(3)["銘柄名"].tolist() for g in rk["業種"]}
    rank = [[int(r.順位), r.業種, round(float(r.点数), 2), r.区分, int(r.銘柄数), "・".join(map(str, lead[r.業種]))] for r in rk.itertuples()]
    # 次の判断日
    nd = last
    while True:
        nd = next_business_day(nd)
        if next_business_day(nd).month != nd.month:
            break
    if last >= START and is_month_end(days, last):
        nd = last
    nd = max(nd, START)
    # 試験運用の記録
    d = pd.read_csv(DAILY, dtype={"判断日": str}) if DAILY.exists() else pd.DataFrame()
    live = {}
    if len(d):
        g = pd.read_csv(GAP_DAILY) if GAP_DAILY.exists() else pd.DataFrame(columns=["日付", "k", "損益_pct"])
        g = g[g["k"] == 1.0].set_index("日付")["損益_pct"] if len(g) else pd.Series(dtype=float)
        d["ギャップ_pct"] = d["日付"].map(g)
        d["組み合わせ_pct"] = W_GAP * d["ギャップ_pct"].fillna(0) + W_SM * d["LS_pct"]
        eq = (1 + d["LS_pct"] / 100).cumprod(); dd_now = float((eq.iloc[-1] / eq.cummax().iloc[-1] - 1) * 100)
        mL, mE, mG, mC = (monthly(d, c) for c in ["LS_pct", "超過_pct", "ギャップ_pct", "組み合わせ_pct"])
        corr = float(mL.corr(mG)) if len(mL.dropna()) >= 3 and mG.notna().sum() >= 3 else None
        live = dict(days=int(len(d)), months=int(len(mL)), first=str(d["日付"].iloc[0]), lastd=str(d["日付"].iloc[-1]),
                    LS=stats(d["LS_pct"] / 100, 245), EX=stats(d["超過_pct"] / 100, 245), CB=stats(d["組み合わせ_pct"] / 100, 245),
                    GP=stats(d["ギャップ_pct"].dropna() / 100, 245), corr=None if corr is None or np.isnan(corr) else round(corr, 2),
                    dd_now=round(dd_now, 2), stop=bool((eq / eq.cummax() - 1).min() * 100 <= STOP_DD),
                    eq=curve(d, ["LS_pct", "超過_pct", "組み合わせ_pct"]))
    # 再現（参考）
    rp = OUT / "replay_daily.csv"; rep = {}
    if rp.exists():
        r = pd.read_csv(rp)
        rep = dict(first=str(r["日付"].iloc[0]), lastd=str(r["日付"].iloc[-1]), LS=stats(monthly(r, "LS_pct"), 12),
                   EX=stats(monthly(r, "超過_pct"), 12), eq=thin(curve(r, ["LS_pct", "超過_pct"])))
    data = dict(sdate=s_date, skind=s_kind, next=str(nd.date()), start=str(START.date()), rank=rank, live=live, rep=rep,
                w=[W_GAP, W_SM], stop=STOP_DD)
    SITE.mkdir(parents=True, exist_ok=True)
    (SITE / "sector_mom.html").write_text(TMPL.replace("__DATA__", json.dumps(data, ensure_ascii=False, allow_nan=False, default=lambda o: None)), encoding="utf-8")
    json.dump(dict(sdate=s_date, skind=s_kind, next=data["next"], top=[x[1] for x in rank[:5]],
                   live={k: live.get(k) for k in ("days", "months", "LS", "EX", "stop")} if live else {}),
              open(SITE / "sector_mom_summary.json", "w", encoding="utf-8"), ensure_ascii=False)
    print(f"sector_mom.html: {s_kind} {s_date}（上位 {'・'.join(x[1] for x in rank[:5])}）、記録 {live.get('days', 0)}日、次の判断日 {data['next']}")
    return 0


TMPL = r"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>業種モメンタム</title>
<script>(function(){var m=/[?&#]theme=(dark|light)/.exec(location.search+location.hash),t=m&&m[1];
if(!t){try{t=localStorage.getItem('fdb-theme')}catch(e){}}if(t)document.documentElement.setAttribute('data-theme',t);})();</script>
<style>
@import url("https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap");
/* 2026-11 デザイン刷新（トップ画面と共通）：黒／白地、枠線なしのカード、数字は Inter の極太。開いた瞬間に「いま持つ5業種」「次の判断日」「成績」が分かる並び */
:root{--bg:#f3f4f6;--card:#fff;--fg:#0c0d10;--fg2:#3d4148;--mut:#5b6068;--line:#dfe2e7;--grid:#eceef2;
--hover:rgba(12,13,16,.05);--s1:#2a78d6;--s2:#eb6834;--up:#b91c24;--dn:#08705a;--upb:#c8323a;--dnb:#0f7f63;color-scheme:light}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){
--bg:#050608;--card:#101216;--fg:#f2f4f8;--fg2:#c6cbd6;--mut:#8f96a3;--line:#23262d;--grid:#1b1e24;
--hover:rgba(255,255,255,.06);--s1:#4a93ea;--s2:#ef7d4e;--up:#ff7378;--dn:#3fd0a4;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#050608;--card:#101216;--fg:#f2f4f8;--fg2:#c6cbd6;--mut:#8f96a3;--line:#23262d;--grid:#1b1e24;
--hover:rgba(255,255,255,.06);--s1:#4a93ea;--s2:#ef7d4e;--up:#ff7378;--dn:#3fd0a4;color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.6 Inter,"Hiragino Sans","Hiragino Kaku Gothic ProN","Noto Sans JP",system-ui,-apple-system,sans-serif;font-variant-numeric:tabular-nums;-webkit-font-smoothing:antialiased}
main{max-width:1180px;margin:0 auto;padding:24px 16px 56px}
h1{font-size:24px;font-weight:800;letter-spacing:.02em;margin:0}
h1 a{color:var(--mut);text-decoration:none;margin-right:8px}
h1 small{font-size:12px;font-weight:400;color:var(--mut);letter-spacing:0;margin-left:8px}
h2{font-size:14px;font-weight:800;letter-spacing:.08em;margin:40px 0 12px;padding-top:12px;border-top:3px solid var(--fg)}
h2 small{font-weight:400;letter-spacing:0;color:var(--mut);font-size:12px;margin-left:8px}
.sub{color:var(--mut);font-size:12px;margin:2px 0 0}.note{color:var(--mut);font-size:12px}
a{color:inherit}
.card{background:var(--card);border-radius:14px;padding:22px 24px}
.k{font-size:12px;font-weight:800;letter-spacing:.1em}.k .meta{font-weight:400;letter-spacing:0;color:var(--mut);margin-left:8px}
/* 最上部：いま持つ5業種 */
.two{display:grid;grid-template-columns:minmax(0,7fr) minmax(0,5fr);gap:14px;margin-top:16px}
.two.r{grid-template-columns:minmax(0,5fr) minmax(0,7fr);margin-top:14px}
.col{display:flex;flex-direction:column;gap:14px}.col>.card{flex:1}
.h-date{font-size:15px;font-weight:700;color:var(--fg2);margin-top:4px}
.t5{display:flex;flex-direction:column;margin-top:10px}
.t5r{display:grid;grid-template-columns:54px minmax(0,1fr) auto;gap:0 14px;align-items:center;padding:12px 0;border-top:1px solid var(--line)}
.t5r .rk{font-size:44px;font-weight:800;letter-spacing:-.04em;line-height:1;grid-row:1/3}
.t5r .nm{font-size:22px;font-weight:800;line-height:1.25}
.t5r .sc{font-size:22px;font-weight:800;letter-spacing:-.02em;text-align:right}
.t5r .br{grid-column:2/4;height:8px;background:var(--line);margin-top:6px;position:relative}
.t5r .br i{position:absolute;left:0;top:0;bottom:0;background:var(--upb)}
.t5r .ld{grid-column:2/4;font-size:11.5px;color:var(--mut);margin-top:5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.big{font-size:clamp(48px,6vw,76px);font-weight:800;letter-spacing:-.04em;line-height:1;margin-top:6px}
.big small{font-size:20px;letter-spacing:0;margin-left:4px}
.kv{font-size:12.5px;color:var(--fg2);margin-top:8px}.kv b{font-weight:800;color:var(--fg)}
.b5{display:flex;flex-direction:column;margin-top:6px}
.b5 div{display:grid;grid-template-columns:30px minmax(0,1fr) auto;gap:8px;padding:6px 0;border-top:1px solid var(--line);font-size:14px;font-weight:800;align-items:baseline}
.b5 div>span{color:var(--mut);font-size:12px;font-weight:600}
.last{display:flex;flex-direction:column;margin-top:10px}
.last div{display:flex;justify-content:space-between;gap:10px;padding:6px 0;border-top:1px solid var(--line);font-size:13px;color:var(--fg2)}
.last b{font-weight:800;font-size:15px}
.mt{margin-top:16px}.mt .tr{position:relative;height:10px;background:var(--line);margin-top:6px}
.mt .tr i{position:absolute;left:0;top:0;bottom:0;background:var(--fg)}
.mt .tr u{position:absolute;right:0;top:-4px;bottom:-4px;width:3px;background:var(--up)}
.mt .lb{display:flex;justify-content:space-between;font-size:11.5px;color:var(--mut);margin-top:4px}
.warn{color:var(--up);font-weight:800}
td .bar{display:inline-block;width:130px;height:8px;background:var(--line);position:relative;vertical-align:middle;margin-right:10px}
td .bar i{position:absolute;left:0;top:0;bottom:0;background:var(--upb)}td .bar i.n{background:var(--dnb)}
tr.top td{font-weight:800}tr.top td:first-child{box-shadow:inset 3px 0 var(--fg)}tr.bot td{color:var(--mut)}
.tag{font-size:11px;font-weight:800;padding:1px 7px;border-radius:4px;background:var(--fg);color:var(--bg)}
.tag.b{background:transparent;color:var(--mut);box-shadow:inset 0 0 0 1px var(--line)}
td.nm{white-space:normal;min-width:18em;font-weight:400;color:var(--fg2)}
.kpis{display:flex;flex-wrap:wrap;gap:10px}.kpi{background:var(--card);border-radius:14px;padding:14px 18px;min-width:220px}
.kpi b{display:block;font-size:30px;font-weight:800;letter-spacing:-.03em;line-height:1.2}.kpi span{color:var(--mut);font-size:12px}
.tw{overflow-x:auto;border-radius:14px;background:var(--card)}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:6px 10px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th{position:sticky;top:0;background:var(--card);color:var(--fg);font-weight:800;font-size:12px;cursor:pointer;border-bottom:2px solid var(--fg)}
td{font-weight:600}td.l,th.l{text-align:left}td.nm{white-space:normal;min-width:8em;max-width:13em;font-weight:800}tr:hover td{background:var(--hover)}
.u{color:var(--up)}.d{color:var(--dn)}.band{font-weight:800}
.lg{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:12px;color:var(--fg2);margin:0 0 4px}.lg i{display:inline-block;width:14px;height:2px;vertical-align:middle;margin-right:5px}
svg text{fill:var(--mut);font-size:11px}
#tip{position:fixed;pointer-events:none;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:6px 9px;font-size:12px;display:none;box-shadow:0 2px 8px rgba(0,0,0,.2);z-index:9}
details{background:var(--card);border-radius:14px;padding:14px 18px;margin-top:14px}
details summary{cursor:pointer;font-weight:800;font-size:13px}
details ol{padding-left:20px;margin:8px 0}
.kpi b span{font-size:inherit;color:inherit}.kpi b .u{color:var(--up)}.kpi b .d{color:var(--dn)}
details p{font-size:13px;color:var(--fg2);margin:8px 0}
@media (max-width:820px){.two,.two.r{grid-template-columns:1fr}
 main{padding:16px 12px 40px}h1{font-size:19px}.card{padding:16px 14px}h2{margin-top:28px}.kpi{min-width:0;flex:1 1 150px}
 .t5r{grid-template-columns:40px minmax(0,1fr) auto;gap:0 10px}.t5r .rk{font-size:32px}.t5r .nm,.t5r .sc{font-size:18px}td .bar{width:70px}td.nm{white-space:nowrap}}
</style></head><body><main>
<h1><a href="./index.html" title="トップへ">‹</a>業種モメンタム<small>上位5業種を持つ・お金を入れない試験運用</small></h1>
<p class="sub"><a href="./gap.html">寄り前ギャップ（組み合わせの相手）→</a></p>

<section class="two">
 <div class="card"><div class="k">いま持つ5業種<span class="meta">12か月の上がり方が大きい順</span></div>
  <div class="h-date" id="sd"></div>
  <div class="t5" id="top5"></div></div>
 <div class="col">
  <div class="card"><div class="k">次の判断日</div>
   <div class="big" id="cd">—</div><div class="h-date" id="nd"></div>
   <p class="note" style="margin:8px 0 0">その日の引け後に順位を作り直し、翌営業日の終値から記録します（月に1回・最終営業日）。</p></div>
  <div class="card"><div class="k">参考：下位5業種<span class="meta">LS の売り側（持たない）</span></div><div class="b5" id="bot5"></div></div>
 </div>
</section>

<section class="two r">
 <div class="card"><div class="k">試験運用の成績<span class="meta">LS（上位5−下位5）・累計・コスト前</span></div>
  <div class="big" id="lv">—</div><div class="kv" id="lvs"></div>
  <div class="last" id="cmp"></div>
  <div class="mt" id="ddm"></div><div class="mt" id="prg"></div></div>
 <div class="card"><div class="lg"><span><i style="background:var(--s1)"></i>LS（上位5−下位5）</span><span><i style="background:var(--mut)"></i>超過（上位5−全業種）</span><span><i style="background:var(--s2)"></i><span id="lgc" style="display:contents">組み合わせ</span></span><span>累計（%）</span></div>
  <div id="ch"></div><p class="note" id="stopnote"></p></div>
</section>

<h2>業種の順位<small id="sd2"></small></h2>
<div class="tw"><table><thead><tr><th>順位</th><th class="l">業種</th><th class="l">12か月（業種内の銘柄の平均）</th><th class="l">区分</th><th>対象銘柄数</th><th class="l">上昇の大きい銘柄</th></tr></thead><tbody id="rk"></tbody></table></div>

<h2>参考：同じスクリプトで過去を再現<small id="rpd"></small></h2>
<div class="kpis" id="kp2"></div>
<div class="card" style="margin-top:10px"><div class="lg"><span><i style="background:var(--s1)"></i>LS</span><span><i style="background:var(--mut)"></i>超過</span><span>累計（%、コスト前）</span></div><div id="ch2"></div></div>
<p class="note">各月末、その日までの株価だけで判断（先読みなし）。第6章の検証（21営業日ごと）との月次相関 0.94。効いたのは主に 2021年以降で、2017〜20年はほぼゼロ。株価CSVは現在上場の銘柄だけ。投資判断はご自身で。</p>

<details><summary>何をしているか・注意</summary>
<p>毎月の最終営業日に、東証33業種を「過去12か月の上がり方（業種内の銘柄の平均）」で並べ、<b>上位5業種を持つ</b>とした場合を記録します（参考に下位5業種も）。
<b>お金を入れない試験運用</b>で、寄り前ギャップ（逆張り）と混ぜたときに値動きが打ち消し合うかを確かめるのが目的です。</p>
<p>ルールは <code>業種モメンタム/PREREG.md</code>（2026-10-12 固定）。判定は 24か月目（2028-10末）に1回だけ。コストは引いていません。LS の最高値からの下落が停止基準に達したら記録を止めます。</p>
<p class="note">33業種の等加重のかごはそのまま買えません。第6章の検証では弱いプラス（t≈1.5）、TOPIX-17業種ETF（時価加重）での別の検証では効いていない点に注意。</p></details>
<div id="tip"></div>
</main><script>
const D=__DATA__;
const $=id=>document.getElementById(id);
const sg=x=>x>0?'u':x<0?'d':'';
const pc=(x,n=2)=>x==null?'—':`<span class="${sg(x)}">${x>0?'+':''}${x.toFixed(n)}%</span>`;
const WD='日月火水木金土';
const jd=s=>{const d=new Date(s+'T00:00:00');return `${d.getMonth()+1}/${d.getDate()}（${WD[d.getDay()]}）`};
const judged=D.skind==='判断';
$('lgc').textContent=`組み合わせ（ギャップ×${D.w[0]}＋LS×${D.w[1]}）`;
$('sd').textContent=judged?`${jd(D.sdate)} の判断`:`参考：${jd(D.sdate)} の終値で計算（判断日ではない）`;
$('sd2').textContent=judged?`判断日 ${D.sdate}`:`参考：${D.sdate} の終値で計算`;
const top5=D.rank.filter(r=>r[3]==='上位'),bot=D.rank.filter(r=>r[3]==='下位');
const mx=Math.max(1,...D.rank.map(r=>Math.abs(r[2])));
$('top5').innerHTML=top5.map(r=>`<div class="t5r"><div class="rk">${r[0]}</div><div class="nm">${r[1]}</div><div class="sc">${pc(r[2],1)}</div>
<div class="br"><i style="width:${Math.abs(r[2])/mx*100}%${r[2]<0?';background:var(--dnb)':''}"></i></div><div class="ld">${r[4]}銘柄　${r[5]}</div></div>`).join('');
$('bot5').innerHTML=bot.map(r=>`<div><span>${r[0]}</span>${r[1]}<b>${pc(r[2],1)}</b></div>`).join('');
(function(){const t=new Date();t.setHours(0,0,0,0);const n=Math.round((new Date(D.next+'T00:00:00')-t)/864e5);
 $('cd').innerHTML=n>0?`あと${n}<small>日</small>`:n===0?'きょう':'更新待ち';$('nd').textContent=jd(D.next)+' の引け後';})();
$('rk').innerHTML=D.rank.map(r=>`<tr class="${r[3]==='上位'?'top':r[3]==='下位'?'bot':''}"><td>${r[0]}</td><td class="l">${r[1]}</td><td class="l"><span class="bar"><i class="${r[2]<0?'n':''}" style="width:${Math.abs(r[2])/mx*100}%"></i></span>${pc(r[2],1)}</td><td class="l">${r[3]==='中'?'':`<span class="tag${r[3]==='下位'?' b':''}">${r[3]}5</span>`}</td><td>${r[4]}</td><td class="l nm">${r[5]}</td></tr>`).join('');
const ok=s=>s&&s.n>1;
function k(t,s){return `<div class="kpi"><span>${t}</span><b>${ok(s)?pc(s.cum,1):'—'}</b><span>${ok(s)?`年率 ${pc(s.ann,1)}・シャープ ${s.sharpe??'—'}・最大DD ${s.dd.toFixed(1)}%`:'記録待ち'}</span></div>`}
const L=D.live;
if(L&&L.days){
 $('lv').innerHTML=ok(L.LS)?pc(L.LS.cum,1):'—';
 $('lvs').innerHTML=`${L.first} 〜 ${L.lastd}（<b>${L.days}日</b>・${L.months}か月目）`+(ok(L.LS)&&L.months>=3?`<br>年率 ${pc(L.LS.ann,1)}・シャープ <b>${L.LS.sharpe??'—'}</b>・最大DD <b>${L.LS.dd.toFixed(1)}%</b>`:'');
 const row=(t,s)=>`<div><span>${t}</span><b>${ok(s)?pc(s.cum,1):'—'}</b></div>`;
 $('cmp').innerHTML=row('超過（上位5−全業種）',L.EX)+row(`組み合わせ（ギャップ×${D.w[0]}＋LS×${D.w[1]}）`,L.CB)+row('寄り前ギャップ k=1（同じ日）',L.GP)+`<div><span>LS とギャップの月次相関</span><b>${L.corr??'—'}</b></div>`;
 const u=Math.min(100,Math.abs(L.dd_now)/Math.abs(D.stop)*100);
 $('ddm').innerHTML=`<div class="k">最高値からの下落<span class="meta">${L.stop?'<span class="warn">停止基準に達しました</span>':`いま ${L.dd_now.toFixed(1)}%`}</span></div><div class="tr"><i style="width:${u}%;background:var(--dnb)"></i><u></u></div><div class="lb"><span>0%</span><span>停止基準 ${D.stop}%</span></div>`;
 $('prg').innerHTML=`<div class="k">判定までの進み<span class="meta">${L.months} / 24か月</span></div><div class="tr"><i style="width:${Math.min(100,L.months/24*100)}%"></i></div><div class="lb"><span>記録開始 ${D.start}</span><span>判定 2028-10末（1回だけ）</span></div>`;
 $('stopnote').textContent=L.months<3?'記録が3か月たまるまでは、年率・シャープ・相関は表示しません（数日分では意味のある数字にならないため）。':'';
}else{$('lvs').textContent=`最初の判断は ${D.start}、記録はその2営業日後の終値から始まります。`;}
const R=D.rep;if(R&&R.LS){$('rpd').textContent=`${R.first} 〜 ${R.lastd}`;$('kp2').innerHTML=k('LS（上位5−下位5）',R.LS)+k('超過（上位5−全業種）',R.EX);}
const tip=$('tip');
function chart(el,E,cols,names,H){const box=$(el);
 if(!E||!E.length){box.innerHTML='<p class="note">まだ記録がありません。</p>';return;}
 const W=Math.min(1100,box.clientWidth||700),m={l:48,r:60,t:10,b:24},iw=W-m.l-m.r,ih=H-m.t-m.b;
 const all=[0];E.forEach(p=>cols.forEach((c,j)=>all.push(p[j+1])));let lo=Math.min(...all),hi=Math.max(...all);const pad=(hi-lo)*.08||1;lo-=pad;hi+=pad;
 const n=E.length,X=i=>m.l+(n<2?iw/2:i*iw/(n-1)),Y=v=>m.t+ih*(1-(v-lo)/(hi-lo));
 const raw=(hi-lo)/4,p10=Math.pow(10,Math.floor(Math.log10(raw))),step=[1,2,5,10].map(x=>x*p10).find(x=>x>=raw);const tk=[];for(let v=Math.ceil(lo/step)*step;v<=hi;v+=step)tk.push(v);
 let s=`<svg width="${W}" height="${H}" role="img" aria-label="累計">`;
 tk.forEach(v=>{const z=Math.abs(v)<1e-9;s+=`<line x1="${m.l}" x2="${m.l+iw}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--${z?'mut':'grid'})" stroke-width="1"/><text x="${m.l-6}" y="${Y(v)+4}" text-anchor="end">${+v.toFixed(4)}%</text>`});
 [0,Math.floor((n-1)/2),n-1].filter((v,i,a)=>a.indexOf(v)===i).forEach((i,q,a)=>s+=`<text x="${X(i)}" y="${H-6}" text-anchor="${q===0?'start':q===a.length-1?'end':'middle'}">${E[i][0]}</text>`);
 cols.forEach((c,j)=>{s+=`<path d="${E.map((p,i)=>(i?'L':'M')+X(i).toFixed(1)+','+Y(p[j+1]).toFixed(1)).join('')}" fill="none" stroke="${c}" stroke-width="${j?1.6:2.6}" stroke-linejoin="round"/>`;
  if(n<40)E.forEach((p,i)=>s+=`<circle cx="${X(i).toFixed(1)}" cy="${Y(p[j+1]).toFixed(1)}" r="${j?2:3}" fill="${c}"/>`)});
 const lb=cols.map((c,j)=>({v:E[n-1][j+1],y:Y(E[n-1][j+1])+4,c})).sort((a,b)=>a.y-b.y);for(let i=1;i<lb.length;i++)if(lb[i].y-lb[i-1].y<13)lb[i].y=lb[i-1].y+13;
 lb.forEach(o=>s+=`<text x="${X(n-1)+8}" y="${o.y}" style="fill:${o.c};font-weight:800">${o.v>0?'+':''}${o.v.toFixed(1)}%</text>`);
 s+=`<line id="${el}x" y1="${m.t}" y2="${m.t+ih}" stroke="var(--mut)" stroke-dasharray="3 3" style="display:none"/><rect x="${m.l}" y="${m.t}" width="${iw}" height="${ih}" fill="transparent"/></svg>`;
 box.innerHTML=s;const sv=box.querySelector('svg'),xl=$(el+'x');
 sv.onmousemove=e=>{const r=sv.getBoundingClientRect(),i=Math.max(0,Math.min(n-1,Math.round((e.clientX-r.left-m.l)/iw*(n-1))));
  xl.setAttribute('x1',X(i));xl.setAttribute('x2',X(i));xl.style.display='';
  tip.innerHTML=`<b>${E[i][0]}</b><br>`+names.map((t,j)=>`${t}: ${pc(E[i][j+1],1)}`).join('<br>');
  tip.style.display='block';tip.style.left=Math.min(e.clientX+14,innerWidth-240)+'px';tip.style.top=(e.clientY+14)+'px';};
 sv.onmouseleave=()=>{tip.style.display='none';xl.style.display='none'};}
function draw(){chart('ch',L&&L.eq,['var(--s1)','var(--mut)','var(--s2)'],['LS','超過','組み合わせ'],300);chart('ch2',R&&R.eq,['var(--s1)','var(--mut)'],['LS','超過'],260);}
draw();addEventListener('resize',draw);
</script></body></html>"""

if __name__ == "__main__":
    sys.exit(main())
