#!/usr/bin/env python3
"""寄り前ギャップの画面 data/charts/gap.html と、トップ画面のカード用の要約 gap_summary.json を作る（通信なし・数秒）"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

from gap_common import CAND, DAILY, OUT, REC, SITE, next_business_day


def stats(d: pd.DataFrame, t: pd.DataFrame, k: float) -> dict:
    x = d[d["k"] == k]; tt = t[t["k"] == k] if len(t) else t
    if x.empty:
        return dict(日数=0, 買った日=0, 取引=0)
    r = x["損益_pct"] / 100
    return dict(日数=int(len(x)), 買った日=int((x["買った数"] > 0).sum()), 取引=int(len(tt)),
                累計_pct=round(float(((1 + r).prod() - 1) * 100), 2),
                取引平均_bp=round(float(tt["損益_pct"].mean() * 100), 1) if len(tt) else None,
                勝率_pct=round(float((tt["損益_pct"] > 0).mean() * 100), 1) if len(tt) else None,
                決算除く_pct=round(float(((1 + x["決算除く_損益_pct"].fillna(x["損益_pct"]) / 100).prod() - 1) * 100), 2) if "決算除く_損益_pct" in x else None)


def series(d: pd.DataFrame, k: float) -> list:
    x = d[d["k"] == k].sort_values("日付")
    eq = (1 + x["損益_pct"] / 100).cumprod() - 1
    return [[str(a), round(float(b) * 100, 3), int(n), round(float(p), 3)] for a, b, n, p in zip(x["日付"], eq, x["買った数"], x["損益_pct"])]


def main():
    files = sorted(CAND.glob("*.csv"))
    if not files:
        print("候補ファイルがありません"); return 1
    f = files[-1]
    c = pd.read_csv(f, dtype={"コード": str})
    for k in ("候補_k1", "候補_k0.5"):
        c[k] = c[k].astype(str).str.lower().isin(["true", "1"])
    c["決算翌日"] = c["決算翌日"].astype(str).str.lower().isin(["true", "1"]) if "決算翌日" in c else False
    asof = pd.Timestamp(f.stem); nb = next_business_day(asof)
    c = c[c["候補_k0.5"]].copy()
    c["必要な下落_k1"] = (c["上限_k1"] / c["終値"] - 1) * 100
    c["必要な下落_k05"] = (c["上限_k0.5"] / c["終値"] - 1) * 100
    c = c.sort_values("必要な下落_k05", ascending=False)
    cand = []
    for _, r in c.iterrows():
        cand.append([r["コード"], r["銘柄名"], r["業種"], float(r["終値"]), float(r["前日安値"]), float(r["20日線"]),
                     float(r["上限_k1"]) if r["候補_k1"] else None, float(r["上限_k0.5"]), float(r["σ90_pct"]),
                     round(float(r["必要な下落_k1"]), 2) if r["候補_k1"] else None, round(float(r["必要な下落_k05"]), 2), bool(r["決算翌日"])])
    d = pd.read_csv(DAILY) if DAILY.exists() else pd.DataFrame(columns=["日付", "k", "買った数", "損益_pct"])
    t = pd.read_csv(REC, dtype={"コード": str}) if REC.exists() else pd.DataFrame(columns=["日付", "k", "損益_pct"])
    rp = OUT / "replay_buy_earn_daily.csv" if (OUT / "replay_buy_earn_daily.csv").exists() else OUT / "replay_daily.csv"
    rpd = pd.read_csv(rp) if rp.exists() else pd.DataFrame(columns=["日付", "k", "買った数", "損益_pct"])
    rpt = OUT / "replay_trades.csv"
    rptt = pd.read_csv(rpt, dtype={"コード": str}) if rpt.exists() else pd.DataFrame(columns=["日付", "k", "損益_pct"])
    recent = t.sort_values(["日付", "k", "順位"], ascending=[False, True, True]).head(60) if len(t) else t
    data = dict(asof=str(asof.date()), target=str(nb.date()), n1=int(c["候補_k1"].sum()), n05=len(c), cand=cand,
                live={str(k): dict(s=stats(d, t, k), eq=series(d, k)) for k in (1.0, 0.5)},
                replay={str(k): dict(s=stats(rpd, rptt, k), eq=series(rpd, k)) for k in (1.0, 0.5)},
                recent=[[str(r["日付"]), float(r["k"]), int(r["順位"]), r["コード"], r["銘柄名"], float(r["始値"]), float(r["終値"]),
                         float(r["ギャップ_pct"]), float(r["損益_pct"]), str(r.get("決算翌日", "")).lower() in ("true", "1")] for _, r in recent.iterrows()])
    html = TMPL.replace("__DATA__", json.dumps(data, ensure_ascii=False, allow_nan=False, default=lambda o: None))
    SITE.mkdir(parents=True, exist_ok=True)
    (SITE / "gap.html").write_text(html, encoding="utf-8")
    sl = data["live"]["1.0"]["s"]
    json.dump(dict(asof=data["asof"], target=data["target"], n1=data["n1"], n05=data["n05"],
                   top=[[x[0], x[1]] for x in cand if x[6] is not None][:3], live=sl),
              open(SITE / "gap_summary.json", "w", encoding="utf-8"), ensure_ascii=False)
    print(f"gap.html: 対象日 {nb.date()} 候補 k=1 {data['n1']} / k=0.5 {data['n05']}、記録 {sl.get('日数', 0)}日")
    return 0


TMPL = r"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>寄り前ギャップ</title>
<script>(function(){var m=/[?&#]theme=(dark|light)/.exec(location.search+location.hash),t=m&&m[1];
if(!t){try{t=localStorage.getItem('fdb-theme')}catch(e){}}if(t)document.documentElement.setAttribute('data-theme',t);})();</script>
<style>
@import url("https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap");
/* 2026-11 デザイン刷新（トップ画面と共通）：黒／白地、枠線なしのカード、数字は Inter の極太。開いた瞬間に「あすの朝やること」と「成績」が分かる並び */
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
/* 最上部：あすの朝の候補 */
.hero{margin-top:16px}
.h-top{display:flex;flex-wrap:wrap;gap:16px 40px;align-items:flex-end;justify-content:space-between}
.h-date{font-size:15px;font-weight:700;color:var(--fg2);margin-top:4px}
.h-n{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;line-height:1}
.h-n b{font-size:clamp(64px,9vw,112px);font-weight:800;letter-spacing:-.045em}
.h-n span{font-size:22px;font-weight:800}.h-n small{font-size:12.5px;color:var(--mut);margin-left:6px}
.steps{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;flex:1 1 560px;max-width:720px;counter-reset:s}
.steps li{counter-increment:s;background:var(--bg);border-radius:12px;padding:12px 14px;font-size:12px;color:var(--fg2);line-height:1.5}
.steps li::before{content:counter(s);display:block;font-size:11px;font-weight:800;color:var(--mut)}
.steps li b{display:block;font-size:15px;font-weight:800;color:var(--fg);line-height:1.35;margin:1px 0 2px}
.t5{display:flex;flex-direction:column;margin-top:8px}
.t5r{display:grid;grid-template-columns:minmax(150px,230px) minmax(0,1fr) minmax(250px,300px);gap:6px 20px;align-items:center;padding:11px 0;border-top:1px solid var(--line);text-decoration:none}
.t5r .nm{font-size:17px;font-weight:800;line-height:1.25}.t5r .cd{font-size:11.5px;color:var(--mut)}
.bd{position:relative;height:30px}
.bd .tr{position:absolute;left:0;right:0;top:12px;height:6px;background:var(--line)}
.bd .zn{position:absolute;top:8px;height:14px;background:var(--upb);min-width:3px}
.bd .cl{position:absolute;top:4px;width:2px;height:22px;background:var(--fg)}
.bd .ar{position:absolute;top:14px;height:2px;background:repeating-linear-gradient(90deg,var(--mut) 0 4px,transparent 4px 7px)}
.t5r .nums{font-size:12px;color:var(--fg2);display:flex;justify-content:space-between;gap:12px;align-items:baseline}
.t5r .nums b{font-size:15px;font-weight:800;color:var(--fg)}
.t5r .need{font-size:19px;font-weight:800;letter-spacing:-.02em;white-space:nowrap}
.bdl{display:flex;flex-wrap:wrap;gap:4px 18px;font-size:11.5px;color:var(--mut);margin-top:10px}
.bdl i{display:inline-block;vertical-align:middle;margin-right:5px}
/* 成績 */
.two{display:grid;grid-template-columns:minmax(0,5fr) minmax(0,7fr);gap:14px;margin-top:14px}
.big{font-size:clamp(48px,6vw,76px);font-weight:800;letter-spacing:-.04em;line-height:1;margin-top:6px}
.kv{display:flex;flex-wrap:wrap;gap:4px 18px;font-size:12.5px;color:var(--fg2);margin-top:8px}.kv b{font-weight:800;color:var(--fg)}
.alt{font-size:12.5px;color:var(--fg2);margin-top:10px;padding-top:10px;border-top:1px solid var(--line);display:flex;flex-direction:column;gap:2px}
.last{display:flex;flex-direction:column;margin-top:6px}
.last div{display:flex;justify-content:space-between;gap:10px;padding:5px 0;border-top:1px solid var(--line);font-size:13px}
.last b{font-weight:800}
.kpis{display:flex;flex-wrap:wrap;gap:10px}.kpi{background:var(--card);border-radius:14px;padding:14px 18px;min-width:220px}
.kpi b{display:block;font-size:30px;font-weight:800;letter-spacing:-.03em;line-height:1.2}.kpi span{color:var(--mut);font-size:12px}
.tabs{display:inline-flex;background:var(--card);border-radius:10px;overflow:hidden}
.tabs button{font:inherit;font-size:12.5px;font-weight:600;padding:6px 12px;border:0;background:transparent;color:var(--fg2);cursor:pointer}
.tabs button.on{background:var(--fg);color:var(--bg);font-weight:800}
input[type=search]{font:inherit;font-weight:600;padding:6px 2px;border:0;border-bottom:3px solid var(--fg);border-radius:0;background:transparent;color:var(--fg);width:240px;outline:0;-webkit-appearance:none;appearance:none}
input[type=search]::placeholder{color:var(--mut)}
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
.ek{display:inline-block;font-size:11px;line-height:1.4;padding:0 5px;margin-left:4px;border:1px solid var(--s2);color:var(--s2);border-radius:4px;vertical-align:1px;font-weight:600}
@media (max-width:820px){.two{grid-template-columns:1fr}.steps{grid-template-columns:1fr;max-width:none;flex-basis:100%}
 .t5r{grid-template-columns:1fr auto;gap:2px 12px}.t5r .bd{grid-column:1/-1;grid-row:2}.t5r .nums{grid-column:1/-1;grid-row:3}.t5r .need{font-size:17px}
 main{padding:16px 12px 40px}h1{font-size:19px}.card{padding:16px 14px}h2{margin-top:28px}.kpi{min-width:0;flex:1 1 150px}}
</style></head><body><main>
<h1><a href="./index.html" title="トップへ">‹</a>寄り前ギャップ<small>Buy-on-Gap・お金を入れない試験運用</small></h1>
<p class="sub"><span id="hd"></span>　<a href="./gap_short.html">売り側（上の窓を売る・紙の記録）→</a></p>

<section class="card hero">
 <div class="h-top">
  <div><div class="k">次の寄付きの候補</div><div class="h-date" id="tgd"></div>
   <div class="h-n"><b id="n1"></b><span>銘柄</span><small id="n05"></small></div></div>
  <ol class="steps"><li><b>8:50〜8:59</b>寄り前の気配を見る</li>
   <li><b>下限 ＜ 気配 ＜ 上限</b>この間なら条件成立。寄らず・ストップ安は買わない</li>
   <li><b>寄りで買い、大引けで売る</b>同額ずつ・最大10銘柄・持ち越さない</li></ol>
 </div>
 <div class="k" style="margin-top:20px">条件に入りやすい5銘柄<span class="meta">前日終値から上限までの下げが小さい順（k=1）</span></div>
 <div class="t5" id="top5"></div>
 <div class="bdl"><span><i style="width:14px;height:10px;background:var(--upb)"></i>買いゾーン（下限＝20日線 〜 上限）</span><span><i style="width:2px;height:14px;background:var(--fg)"></i>前日の終値</span><span>点線＝寄付きまでに必要な下げ</span></div>
</section>

<section class="two">
 <div class="card"><div class="k">試験運用の成績<span class="meta">k=1・累計・コスト前</span></div>
  <div class="big" id="lv">—</div><div class="kv" id="lvs"></div><div class="alt" id="lva"></div>
  <div class="k" style="margin-top:18px">直近の答え合わせ<span class="meta" id="lastd"></span></div><div class="last" id="last"></div></div>
 <div class="card"><div class="lg"><span><i style="background:var(--s1)"></i>k=1</span><span><i style="background:var(--s2)"></i>k=0.5</span><span>累計損益（コスト前、%）</span></div>
  <div id="ch"></div><p class="note" id="lvnote"></p></div>
</section>

<h2>候補の一覧<small><span id="tg"></span> の寄付き</small></h2>
<div style="display:flex;gap:14px;flex-wrap:wrap;align-items:center;margin-bottom:10px">
<span class="tabs"><button data-k="1" class="on">k=1 のみ</button><button data-k="0.5">k=0.5 も含める</button></span>
<input type="search" id="q" placeholder="コード・銘柄名・業種"></div>
<p class="note">並び順＝上限までの下げ幅が小さい順（＝条件に入りやすい順）。「上限まで」＝前日終値から上限までの下落率。価格はすべて分割・配当調整済み。</p>
<div class="tw" style="max-height:480px"><table id="ct"><thead><tr>
<th class="l">コード</th><th class="l">銘柄名</th><th>下限（20日線）</th><th>上限 k=1</th><th>上限まで k=1</th><th>上限 k=0.5</th><th>上限まで k=0.5</th><th>終値</th><th>前日安値</th><th class="l">業種</th><th>σ90</th></tr></thead><tbody></tbody></table></div>

<h2>直近の取引</h2>
<div class="tw" style="max-height:360px"><table id="rt"><thead><tr><th class="l">日付</th><th>k</th><th>順位</th><th class="l">コード</th><th class="l">銘柄名</th><th>始値</th><th>終値</th><th>ギャップ</th><th>損益</th></tr></thead><tbody></tbody></table></div>

<h2>参考：同じスクリプトで過去1年を再現した成績</h2>
<div class="kpis" id="kp2"></div>
<div class="card" style="margin-top:10px"><div id="ch2"></div></div>
<p class="note">各日、その日までの株価だけで候補を作り、翌営業日の始値・終値で答え合わせ（先読みなし）。2016-12〜2026-10 の検証では k=1 で年率26%・R/R 0.95・最大DD約37%、負けた年（2018・2021・2025）あり。
詳細は 株分析/平均回帰_株とETF_第4章_20261010/README_株とETFの平均回帰.md。投資判断はご自身で。</p>

<details><summary>くわしい使い方と注意</summary>
<ol><li>候補の<b>寄り前の気配</b>を見る。気配が<b>「下限（20日線）より上、上限より下」</b>なら条件成立。</li>
<li>成立した銘柄を寄付きの成行で同額ずつ買い、<b>大引けの成行で売る</b>（持ち越さない）。10銘柄を超えたら、気配÷前日安値が小さい順に10銘柄。</li>
<li>寄らず（特別気配のまま）・ストップ安は買わない。</li></ol>
<p class="note">主は k=1（本書の既定）。k=0.5 は条件がゆるく、候補・取引が増える（検証では成績も良かったが、多くの設定から選んだ結果なので参考）。
<span class="ek">決算</span>＝対象日の寄りまでに決算発表（予定）がある銘柄。第7章の検証では、決算翌日の窓は戻りにくく続きやすい（2024/9〜、件数が少なく未確定）。買う条件は変えず、「決算翌日を除いて選んだ場合」も並べて記録しています。
いまは<b>お金を入れない試験運用</b>：毎日の処理が翌営業日の実際の始値・終値で答え合わせし、記録します。コストは引いていません（検証の損益分岐は片道約18bp）。</p></details>
<div id="tip"></div>
</main><script>
const D=__DATA__;
const $=id=>document.getElementById(id);
const f1=(x,n=1)=>x==null?'—':x.toLocaleString(undefined,{minimumFractionDigits:n,maximumFractionDigits:n});
const pc=(x,n=2)=>x==null?'—':`<span class="${x>0?'u':x<0?'d':''}">${x>0?'+':''}${x.toFixed(n)}%</span>`;
const md=s=>{const d=new Date(s+'T00:00:00');return isNaN(d)?s:`${d.getMonth()+1}/${d.getDate()}（${'日月火水木金土'[d.getDay()]}）`;};
$('hd').textContent=`判断日 ${D.asof}（引け後に作成）`;
$('tg').textContent=D.target;$('tgd').textContent=md(D.target)+' の寄付き';
$('n1').textContent=D.n1.toLocaleString();$('n05').textContent=`k=0.5 も含めると ${D.n05.toLocaleString()}銘柄`;
/* 条件に入りやすい5銘柄：買いゾーン（下限〜上限）と前日終値の位置 */
(function(){const r=D.cand.filter(x=>x[6]!=null).sort((a,b)=>b[9]-a[9]).slice(0,5);
 $('top5').innerHTML=r.map(x=>{const lo=x[5],up=x[6],cl=x[3],span=Math.max(cl-lo,1e-9),a=lo-span*.12,b=cl+span*.06,P=v=>Math.max(0,Math.min(100,(v-a)/(b-a)*100));
  return `<a class="t5r" href="./one/${x[0]}.html" target="_blank" rel="noopener"><div><div class="nm">${x[1]||x[0]}${x[11]?'<span class="ek">決算</span>':''}</div><div class="cd">${x[0]}・${x[2]||''}</div></div>
  <div class="bd" role="img" aria-label="買いゾーン ${f1(lo)}〜${f1(up)}、前日終値 ${f1(cl)}"><div class="tr"></div><div class="ar" style="left:${P(up).toFixed(2)}%;width:${(P(cl)-P(up)).toFixed(2)}%"></div><div class="zn" style="left:${P(lo).toFixed(2)}%;width:${(P(up)-P(lo)).toFixed(2)}%"></div><div class="cl" style="left:${P(cl).toFixed(2)}%"></div></div>
  <div class="nums"><span>買いゾーン <b>${f1(lo)}</b> 〜 <b>${f1(up)}</b><br>前日の終値 ${f1(cl)}</span><span class="need">${pc(x[9])}</span></div></a>`}).join('')||'<p class="note">候補はありません</p>';})();
/* 成績 */
(function(){const a=D.live['1.0'].s,b=D.live['0.5'].s;
 if(!a.日数){$('lvs').textContent='まだ記録がありません（最初の答え合わせは対象日の翌日の処理で入ります）';return;}
 $('lv').innerHTML=pc(a.累計_pct);
 $('lvs').innerHTML=`<span><b>${a.日数}</b>日</span><span>買った日 <b>${a.買った日}</b></span><span><b>${a.取引}</b>取引</span><span>勝率 <b>${a.勝率_pct==null?'—':a.勝率_pct+'%'}</b></span><span>1取引平均 <b>${a.取引平均_bp==null?'—':(a.取引平均_bp>0?'+':'')+a.取引平均_bp+'bp'}</b></span>`;
 $('lva').innerHTML=(a.決算除く_pct==null?'':`<span>決算翌日を除いて選んだ場合 ${pc(a.決算除く_pct)}</span>`)+(b.日数?`<span>k=0.5 では ${pc(b.累計_pct)}（${b.取引}取引・勝率 ${b.勝率_pct==null?'—':b.勝率_pct+'%'}）</span>`:'')+'<span style="color:var(--mut)">コスト（片道約18bp）は引いていません</span>';
 const k1=D.recent.filter(x=>x[1]===1);if(k1.length){const d0=k1[0][0],rows=k1.filter(x=>x[0]===d0);
  $('lastd').textContent=md(d0)+'・k=1';
  $('last').innerHTML=rows.map(x=>`<div><span><b>${x[4]||x[3]}</b> <span class="note">${x[3]}・始値 ${f1(x[5])} → 終値 ${f1(x[6])}</span></span><b>${pc(x[8])}</b></div>`).join('');}
 else $('last').innerHTML='<div><span class="note">まだ取引はありません</span></div>';})();
let K='1',sortCol=9,sortAsc=false;
function drawCand(){const q=$('q').value.trim();
 let r=D.cand.filter(x=>(K==='0.5'||x[6]!=null)&&(!q||(x[0]+x[1]+(x[2]||'')).includes(q)));
 const sc=(K==='1'&&sortCol===10)?9:sortCol;
 r.sort((a,b)=>{const u=a[sc],v=b[sc];if(u==null)return 1;if(v==null)return -1;return (typeof u==='string'?u.localeCompare(v):u-v)*(sortAsc?1:-1)});
 document.querySelector('#ct tbody').innerHTML=r.map(x=>`<tr><td class="l">${x[0]}</td><td class="l nm">${x[1]||''}${x[11]?'<span class="ek">決算</span>':''}</td><td class="band">${f1(x[5])}</td><td class="band">${f1(x[6])}</td><td>${pc(x[9])}</td><td>${f1(x[7])}</td><td>${pc(x[10])}</td>
 <td>${f1(x[3])}</td><td>${f1(x[4])}</td><td class="l">${x[2]||''}</td><td>${f1(x[8],2)}%</td></tr>`).join('')||'<tr><td class="l" colspan="11">候補はありません</td></tr>';}
document.querySelectorAll('.tabs button').forEach(b=>b.onclick=()=>{document.querySelectorAll('.tabs button').forEach(x=>x.classList.remove('on'));b.classList.add('on');K=b.dataset.k;sortCol=K==='1'?9:10;drawCand();});
$('q').oninput=drawCand;
document.querySelectorAll('#ct th').forEach((th,i)=>th.onclick=()=>{const map=[0,1,5,6,9,7,10,3,4,2,8];const c=map[i];sortAsc=(sortCol===c)?!sortAsc:(c<3);sortCol=c;drawCand();});
drawCand();
function kpis(el,S){const a=S['1.0'].s,b=S['0.5'].s;const one=(t,s)=>`<div class="kpi"><span>${t}</span><b>${s.日数?pc(s.累計_pct):'—'}</b><span>${s.日数}日・買った日 ${s.買った日}・${s.取引}取引<br>1取引平均 ${s.取引平均_bp==null?'—':(s.取引平均_bp>0?'+':'')+s.取引平均_bp+'bp'}・勝率 ${s.勝率_pct==null?'—':s.勝率_pct+'%'}${s.決算除く_pct==null?'':'<br>決算翌日を除いて選んだ場合 '+pc(s.決算除く_pct)}</span></div>`;
 $(el).innerHTML=one('k=1 累計',a)+one('k=0.5 累計',b);}
kpis('kp2',D.replay);
const tip=$('tip');
function chart(el,S){const box=$(el),A=S['1.0'].eq,B=S['0.5'].eq;
 if(!A.length){box.innerHTML='<p class="note">まだ記録がありません（最初の答え合わせは対象日の翌日の処理で入ります）。</p>';return;}
 const W=Math.min(1100,box.clientWidth||700),H=260,m={l:44,r:92,t:10,b:24},iw=W-m.l-m.r,ih=H-m.t-m.b;
 const all=A.concat(B).map(x=>x[1]).concat([0]);let lo=Math.min(...all),hi=Math.max(...all);const pad=(hi-lo)*.08||1;lo-=pad;hi+=pad;
 const n=Math.max(A.length,B.length),X=i=>m.l+(n<2?iw/2:i*iw/(n-1)),Y=v=>m.t+ih*(1-(v-lo)/(hi-lo));
 const p10=Math.pow(10,Math.floor(Math.log10((hi-lo)/4))),step=[1,2,2.5,5,10].map(k=>k*p10).find(s=>(hi-lo)/s<=6)||10*p10;const tk=[];for(let v=Math.ceil(lo/step)*step;v<=hi+1e-9;v+=step)tk.push(+v.toFixed(6));   /* 目盛りは6本以内に収まる間隔で全範囲に（2026-11-16 修正） */
 let s=`<svg width="${W}" height="${H}" role="img" aria-label="累計損益">`;
 tk.forEach(v=>{s+=`<line x1="${m.l}" x2="${m.l+iw}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--${v===0?'line':'grid'})" stroke-width="${v===0?1.5:1}"/><text x="${m.l-6}" y="${Y(v)+4}" text-anchor="end">${(+v.toFixed(6))}%</text>`});
 const lab=A.length?A:B;[0,Math.floor((lab.length-1)/2),lab.length-1].forEach(i=>{if(lab[i])s+=`<text x="${X(i)}" y="${H-6}" text-anchor="middle">${lab[i][0]}</text>`});
 const path=(E,c)=>E.length?`<path d="${E.map((p,i)=>(i?'L':'M')+X(i).toFixed(1)+','+Y(p[1]).toFixed(1)).join('')}" fill="none" stroke="${c}" stroke-width="2" stroke-linejoin="round"/>`:'';
 s+=path(B,'var(--s2)')+path(A,'var(--s1)');
 [[A,'var(--s1)','k=1'],[B,'var(--s2)','k=0.5']].forEach(([E,c,t])=>{if(E.length){const p=E[E.length-1];s+=`<text x="${X(E.length-1)+6}" y="${Y(p[1])+4}" style="fill:var(--fg);font-weight:700">${t} ${p[1]>0?'+':''}${p[1].toFixed(1)}%</text>`}});
 s+=`<line id="${el}x" y1="${m.t}" y2="${m.t+ih}" stroke="var(--mut)" stroke-dasharray="3 3" style="display:none"/><rect x="${m.l}" y="${m.t}" width="${iw}" height="${ih}" fill="transparent"/></svg>`;
 box.innerHTML=s;const sv=box.querySelector('svg'),xl=$(el+'x');
 sv.onmousemove=e=>{const r=sv.getBoundingClientRect(),i=Math.max(0,Math.min(n-1,Math.round((e.clientX-r.left-m.l)/iw*(n-1))));
  xl.setAttribute('x1',X(i));xl.setAttribute('x2',X(i));xl.style.display='';const a=A[i],b=B[i];
  tip.innerHTML=`<b>${(a||b)[0]}</b><br>k=1: 累計 ${a?pc(a[1],1):'—'}（当日 ${a?pc(a[3]):'—'}・${a?a[2]:0}銘柄）<br>k=0.5: 累計 ${b?pc(b[1],1):'—'}（当日 ${b?pc(b[3]):'—'}・${b?b[2]:0}銘柄）`;
  tip.style.display='block';tip.style.left=Math.min(e.clientX+14,innerWidth-260)+'px';tip.style.top=(e.clientY+14)+'px';};
 sv.onmouseleave=()=>{tip.style.display='none';xl.style.display='none'};}
function both(){chart('ch',D.live);chart('ch2',D.replay);}both();addEventListener('resize',both);
$('lvnote').textContent=D.live['1.0'].s.日数?'記録は毎日の処理で自動的に増えます。':'';
document.querySelector('#rt tbody').innerHTML=D.recent.map(x=>`<tr><td class="l">${x[0]}</td><td>${x[1]}</td><td>${x[2]}</td><td class="l">${x[3]}</td><td class="l">${x[4]||''}${x[9]?'<span class="ek">決算</span>':''}</td><td>${f1(x[5])}</td><td>${f1(x[6])}</td><td>${pc(x[7])}</td><td>${pc(x[8])}</td></tr>`).join('')||'<tr><td class="l" colspan="9">まだ取引はありません</td></tr>';
</script></body></html>"""

if __name__ == "__main__":
    sys.exit(main())
