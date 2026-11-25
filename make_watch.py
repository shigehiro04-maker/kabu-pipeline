#!/usr/bin/env python3
"""監視銘柄ページ（data/charts/watch.html）と、その元データ（data/charts/watch_data.js）を作る。

2026-11-15 作り直し：タイトルを付けた一覧表をいくつでも作り、銘柄情報を表で見る。
  表の列：株価・前日比・出来高・売買代金・VWAP・PER・PBR・ROE・時価総額・逆日歩・単位株数・配当利回り・決算発表日
  （以前の IN・利確・損切りの到達判定はやめた。リストの保存は watch_lists.js、この端末のブラウザに保存）

データ元（すべて手元のファイル。通信なし）
  株価・前日比(%)・出来高   data/charts/_summary.json
  前日比(円)・PER・PBR・ROE・時価総額・配当利回り・逆日歩   fundamentals/analysis/dashboard_data.json（スクリーニングと同じ値）
  VWAP     5分足（data/intraday/<コード>.csv）の最新日について Σ(高値+安値+終値)/3×出来高 ÷ Σ出来高
           5分足が無い・日付が合わない銘柄は 日足の (高値+安値+終値)/3
  売買代金 VWAP × 出来高
  単位株数 100株（東証は全銘柄100株）
  決算発表日 次の決算発表日。JPX「決算発表予定日」に今日以降の日があれば「予定」、まだ無ければ昨年同期の発表日（J-Quants の開示実績）から推定して「予想」

使い方:  .venv/bin/python make_watch.py            → watch.html / watch_data.js
         .venv/bin/python make_watch.py --preview  → 見本入りの1ファイル（Claude outputs/watch_preview/watch_preview.html。公開しない確認用）
"""
from __future__ import annotations

import csv
import datetime
import json
import math
import sys
import unicodedata
from pathlib import Path

BASE = Path(__file__).resolve().parent
SITE = BASE / "data" / "charts"
INTRA = BASE / "data" / "intraday"
PRICES = BASE / "data" / "prices"
DASH = BASE / "fundamentals" / "analysis" / "dashboard_data.json"


def _num(v, nd=None):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(x) or math.isinf(x):
        return None
    return round(x, nd) if nd is not None else x


def _vwap_intraday(code: str, date: str):
    """5分足の最新日が date のとき、その日の VWAP。無ければ None"""
    f = INTRA / f"{code}.csv"
    if not f.exists():
        return None
    pv = v = 0.0
    try:
        with open(f, encoding="utf-8") as fh:
            rd = csv.reader(fh)
            next(rd, None)
            for r in rd:
                if not r or not r[0].startswith(date):
                    continue
                vol = float(r[5] or 0)
                if vol <= 0:
                    continue
                pv += (float(r[2]) + float(r[3]) + float(r[4])) / 3 * vol
                v += vol
    except Exception:
        return None
    return pv / v if v > 0 else None


def _vwap_daily(code: str, date: str):
    f = PRICES / f"{code}.csv"
    if not f.exists():
        return None
    try:
        with open(f, "rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - 400))
            last = fh.read().decode("utf-8", "ignore").strip().splitlines()[-1].split(",")
        if last[0] != date:
            return None
        return (float(last[2]) + float(last[3]) + float(last[4])) / 3
    except Exception:
        return None


def _jpx_dates():
    """JPX「決算発表予定日」の全ファイルから (日付, コード)。同じ一覧（○月期）に同じ銘柄が何度も出るときは、作成日の新しいファイルの日付。
    （gap_common._jpx_schedule は一覧ごとに最新の1ファイルだけ読むが、JPX の kessan.xlsx は発表前の会社しか載らないので、
      発表済みの日付も残るよう、ここでは銘柄ごとに見る）"""
    import re
    import pandas as pd
    files = sorted(set(BASE.glob("kessan*.xlsx")) | set((BASE / "決算発表予定日").glob("*.xlsx")))
    best = {}
    for f in files:
        try:
            x = pd.read_excel(f, header=None)
        except Exception:
            continue
        title = str(x.iat[0, 0])
        m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", str(x.iat[2, 0]))
        a = pd.Timestamp(int(m[1]), int(m[2]), int(m[3])) if m else pd.Timestamp(f.stat().st_mtime, unit="s")
        y = x.iloc[5:, :2].copy(); y.columns = ["date", "code"]
        y["date"] = pd.to_datetime(y["date"], errors="coerce")
        y["code"] = y["code"].astype(str).str.strip().str.upper()
        y = y[y["date"].notna() & y["code"].str.fullmatch(r"\d{3}[0-9A-Z]")]
        for d, c in zip(y["date"].dt.strftime("%Y-%m-%d"), y["code"]):
            k = (title, c)
            if k not in best or a > best[k][0]:
                best[k] = (a, d)
    return [(d, c) for (_, c), (_, d) in best.items()]


def _earnings():
    """コード → (次の決算発表日, 1=予定（JPX が発表した予定日）／2=予想（未発表。昨年の同じ時期の発表日から推定）)
    予想：過去の発表日（JPX 予定表＋J-Quants の開示実績）を 52週（364日＝同じ曜日）後ろへずらしたもののうち、
          今日以降で一番早い日。ただし直近の発表日から45日以内は同じ決算の重複とみて使わない"""
    pairs = []
    try:
        pairs += _jpx_dates()
    except Exception as ex:
        print(f"JPX の決算発表予定日を読めませんでした: {ex}")
    try:
        sys.path.insert(0, str(BASE / "寄り前ギャップ"))
        import gap_common as g
        q = g._jq_disclosures()
        pairs += list(zip(q["date"].dt.strftime("%Y-%m-%d"), q["code"]))
    except Exception as ex:  # 無くてもページは作る
        print(f"開示実績（J-Quants）を読めませんでした: {ex}")
    today = datetime.date.today()
    by = {}
    for d, c in pairs:
        try:
            by.setdefault(c, set()).add(datetime.date.fromisoformat(d))
        except ValueError:
            pass
    out = {}
    for c, ds in by.items():
        fut = [d for d in ds if d >= today]
        if fut:
            out[c] = (min(fut).isoformat(), 1)
            continue
        last = max(ds)
        for k in (1, 2):  # まず1年前の発表日から。無ければ2年前から
            cand = [d + datetime.timedelta(days=364 * k) for d in ds]
            cand = [d for d in cand if d >= today and (d - last).days > 45]
            if cand:
                out[c] = (min(cand).isoformat(), 2)
                break
    return out


def build_data() -> dict:
    rows = json.load(open(SITE / "_summary.json", encoding="utf-8"))
    dd = json.load(open(DASH, encoding="utf-8"))
    ix = {k: i for i, k in enumerate(dd["fields"])}
    fund = {str(r[0]): r for r in dd["stocks"]}
    earn = _earnings()
    g = lambda r, k, nd=None: _num(r[ix[k]], nd) if r is not None and k in ix else None
    out, n_intra = [], 0
    for s in rows:
        code = str(s.get("code", ""))
        if not code:
            continue
        px, vol, date = _num(s.get("close")), _num(s.get("vol")), s.get("date", "")
        chgp = _num(s.get("chg"), 2)
        f = fund.get(code)
        chg = g(f, "前日比(円)", 1)
        if chg is None and px is not None and chgp is not None:
            chg = round(px - px / (1 + chgp / 100), 1)
        vw = _vwap_intraday(code, date)
        if vw is not None:
            n_intra += 1
        else:
            vw = _vwap_daily(code, date)
        val = round(vw * vol / 1e6, 1) if vw is not None and vol else None  # 百万円
        e = earn.get(code)
        out.append([code, unicodedata.normalize("NFKC", s.get("name", "")), s.get("mk", ""), px, chg, chgp,
                    int(vol) if vol is not None else None, val, round(vw, 1) if vw is not None else None,
                    g(f, "PER", 1), g(f, "PBR", 2), g(f, "ROE(%)", 1), g(f, "時価総額(億円)", 1),
                    g(f, "逆日歩(円)", 2), 100, g(f, "配当利回り(%)", 2),
                    e[0] if e else None, e[1] if e else None])
    asof = max((s.get("date", "") for s in rows), default="")
    print(f"監視銘柄データ: {len(out)}銘柄（VWAP 5分足 {n_intra}・次の決算発表日 予定 {sum(1 for r in out if r[17] == 1)}・予想 {sum(1 for r in out if r[17] == 2)}）")
    idx = {}
    try:  # 指数の採用銘柄（fetch_index_members.py）。データの無い銘柄は除く
        have = {r[0] for r in out}
        for x in json.load(open(SITE.parent / "index_members.json", encoding="utf-8"))["lists"]:
            idx[x["k"]] = {"t": x["t"], "asof": x.get("asof", ""), "c": [c for c in x["c"] if c in have]}
    except Exception as ex:
        print(f"指数の採用銘柄を読めませんでした: {ex}")
    return {"idx": idx, "asof": asof, "built": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "cur": "円", "S": out}


PAGE = r"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>監視銘柄 | __SITE__</title>
__HEAD__
<style>
.wrap{max-width:1680px}
.newl{display:flex;gap:8px;flex-wrap:wrap;margin:22px 0 0}
.newl input{flex:1 1 240px;min-width:0;height:44px;padding:0 12px;font:inherit;font-size:15px;font-weight:600;border:1px solid var(--line);border-radius:10px;background:var(--card);color:var(--fg);outline:none}
.newl input:focus,.add input:focus{border-color:var(--fg)}
.btn.pri{height:44px;padding:0 16px;font-size:13.5px;font-weight:700;background:var(--fg);color:var(--bg);border-color:var(--fg);border-radius:10px}
.tabs{display:flex;gap:4px;margin-top:20px;padding:0;overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:none}
.tabs::-webkit-scrollbar{display:none}.tabs:empty{display:none}
.tab{flex:0 0 auto;max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;border:0;border-radius:10px 10px 0 0;padding:10px 16px 9px;font:inherit;font-size:13.5px;font-weight:700;cursor:pointer;color:var(--mut);background:color-mix(in srgb,var(--fg) 9%,var(--bg));box-shadow:inset 0 3px 0 transparent}
.tab:hover{color:var(--fg)}.tab small{font-weight:400;font-size:11px;margin-left:6px}
.tab.on{background:var(--card);color:var(--fg);box-shadow:inset 0 3px 0 var(--fg)}
.lst{background:var(--card);border-radius:0 14px 14px 14px}
.lh{display:flex;align-items:center;gap:6px 10px;flex-wrap:wrap;padding:14px 16px 8px}
.lh h2{margin:0;font-size:17px;font-weight:800;letter-spacing:.02em}
.lh .ren{font:inherit;font-size:16px;font-weight:800;height:34px;padding:0 8px;border:1px solid var(--fg);border-radius:8px;background:var(--bg);color:var(--fg);min-width:0;flex:0 1 260px}
.lh .cnt{color:var(--mut);font-size:12px}
.lh .ops{margin-left:auto;display:flex;gap:6px;flex-wrap:wrap}
.ob{border:1px solid var(--line);background:transparent;color:var(--fg2);border-radius:7px;padding:3px 9px;font:inherit;font-size:12px;cursor:pointer}
.ob:hover{border-color:var(--fg);color:var(--fg)}.ob.warn{background:var(--upb);border-color:var(--upb);color:#fff}
.add{position:relative;padding:0 16px 12px}
.add input{width:100%;max-width:440px;height:36px;padding:0 10px;font:inherit;font-size:13px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--fg);outline:none;-webkit-appearance:none;appearance:none}
.sg{position:absolute;z-index:20;left:16px;top:40px;width:min(440px,calc(100% - 32px));max-height:320px;overflow:auto;background:var(--card);border:1px solid var(--fg);border-radius:10px;box-shadow:0 10px 28px rgba(0,0,0,.25)}
.sg div{display:flex;gap:8px;align-items:baseline;padding:8px 11px;cursor:pointer;border-top:1px solid var(--line);font-size:13px}
.sg div:first-child{border-top:0}.sg div:hover,.sg div.on{background:var(--hover)}
.sg b{min-width:44px}.sg small{color:var(--mut);margin-left:auto;font-size:11px;white-space:nowrap}.sg .in{color:var(--mut)}
.tw{overflow-x:auto;-webkit-overflow-scrolling:touch;border-radius:0 0 14px 14px}
table{border-collapse:collapse;width:100%;min-width:1390px;table-layout:fixed;font-size:13px;white-space:nowrap}
col.c0{width:210px}col.c3{width:84px}col.c5{width:130px}col.c6{width:105px}col.c7{width:95px}col.c8{width:90px}col.c9,col.c10,col.c11{width:64px}
col.c12{width:105px}col.c13{width:72px}col.c14{width:78px}col.c15{width:88px}col.c16{width:146px}col.cx{width:34px}
th,td{padding:9px 11px;text-align:right;border-top:1px solid var(--line)}
th{font-size:11.5px;font-weight:600;color:var(--mut);cursor:pointer;user-select:none;-webkit-user-select:none}
th:hover{color:var(--fg)}th.on{color:var(--fg);font-weight:800}th small{font-weight:400;margin-left:1px}
td{font-weight:600}td small{font-weight:400;font-size:11.5px}
th:first-child,td:first-child{position:sticky;left:0;z-index:1;text-align:left;background:var(--card);padding-left:16px}
tbody tr:hover td{background:color-mix(in srgb,var(--fg) 5%,var(--card))}
td.nm{overflow:hidden;text-overflow:ellipsis}
td.nm a{color:var(--fg);text-decoration:none}td.nm a:hover span{text-decoration:underline}
td.nm b{font-weight:800;margin-right:6px}td.nm span{font-weight:600}
td.px{font-weight:800;font-size:14px}td.px a{color:var(--fg);text-decoration:none;border-bottom:1px dotted var(--mut)}td.px a:hover{border-bottom-style:solid}
.na{color:var(--mut);font-weight:400}
.tg{display:inline-block;font-size:10.5px;padding:0 5px;border-radius:5px;border:1px solid var(--line);color:var(--mut);margin-left:3px}
.tg.on{background:var(--fg);border-color:var(--fg);color:var(--bg);font-weight:700}
.x{border:0;background:transparent;color:var(--mut);font-size:16px;line-height:1;cursor:pointer;padding:2px 6px}.x:hover{color:var(--up)}
td:last-child,th:last-child{padding-left:0;padding-right:8px;text-align:center}
.empty{padding:4px 16px 16px;color:var(--mut);font-size:12.5px}
.ixn{padding:0 16px 12px;color:var(--mut);font-size:12px}.ixn b{color:var(--fg2);font-weight:700}
.tab .ixm{display:inline-block;width:6px;height:6px;border-radius:50%;background:currentColor;opacity:.5;margin-right:6px;vertical-align:2px}
.more{display:flex;gap:8px;justify-content:center;padding:12px 16px 16px}.more .ob{padding:6px 14px;font-size:12.5px}
.empty0{margin-top:18px;padding:22px 18px;border:1px dashed var(--line);border-radius:14px;color:var(--mut);font-size:13px}
.note{margin-top:22px;color:var(--mut);font-size:11.5px;line-height:1.7}
@media(max-width:760px){.wrap{padding:16px 10px 40px}.newl input,.add input{font-size:16px}.btn.pri{flex:1 1 100%}
.tab{padding:11px 13px 10px;font-size:13px;max-width:170px}.lh{padding:12px 12px 8px}.lh h2{font-size:15.5px}.add{padding:0 12px 10px}.sg{left:12px;width:calc(100% - 24px)}
table{font-size:12.5px}th,td{padding:8px 9px}th:first-child,td:first-child{padding-left:12px}
table{min-width:1250px}col.c0{width:128px}col.c5{width:118px}col.c6{width:98px}td.nm b{display:block;margin:0;font-size:12px}td.nm span{font-size:11.5px}
.ob{padding:6px 10px}.x{padding:6px 8px}}
</style>
</head><body><div class="wrap">
<header><div><h1><a href="./index.html" title="トップへ" style="text-decoration:none;color:inherit;margin-right:8px">‹</a>監視銘柄</h1>
<div class="sub" id="sub"></div></div>
<button class="btn" id="theme" type="button">明暗</button></header>
<form class="newl" id="newl"><input id="nt" type="text" maxlength="40" autocomplete="off" placeholder="タイトルを入力して一覧表を作る（例：高配当・デイトレ候補・決算待ち）">
<button class="btn pri" type="submit">＋ 一覧表を作る</button></form>
<div class="tabs" id="tabs"></div>
<div id="lists"></div>
<p class="note">__NOTE__</p>
</div>
__SCRIPTS__
<script>
const $=id=>document.getElementById(id),K=window.KW,WD=window.WD;
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const norm=s=>String(s).normalize('NFKC').toLowerCase();
const BY={};WD.S.forEach(r=>BY[r[0]]=r);
const IX=WD.S.map(r=>norm(r[0]+' '+r[1]));
const nf=(v,d=0)=>Number(v).toLocaleString('ja-JP',{minimumFractionDigits:d,maximumFractionDigits:d});
const fx=v=>nf(v,Math.abs(v%1)>1e-9?1:0),sg=v=>v>0?'+':'',cl=v=>v>0?'u':v<0?'d':'';
const NA='<span class="na">―</span>',Y=WD.asof.slice(0,4),CH=WD.ch||'./',ONE=WD.one||'./one/';
/* 列：i は WD.S の何番目か */
const COLS=[
 {l:'株価',i:3,c:'px',f:(v,r)=>`<a href="${CH}${encodeURIComponent(r[0])}.html" title="チャートを開く">${fx(v)}</a>`},
 {l:'前日比',i:5,f:(v,r)=>`<span class="${cl(v)}">${r[4]==null?'':sg(r[4])+fx(r[4])+' '}<small>(${sg(v)}${v.toFixed(2)}%)</small></span>`},
 {l:'出来高',u:'株',i:6,f:v=>nf(v)},
 {l:'売買代金',u:'億円',i:7,f:v=>nf(v/100,v<1000?2:1)},
 {l:'VWAP',i:8,f:v=>nf(v,1)},
 {l:'PER',u:'倍',i:9,f:v=>v>0?nf(v,1):'<span class="na">赤字</span>'},
 {l:'PBR',u:'倍',i:10,f:v=>nf(v,2)},
 {l:'ROE',u:'%',i:11,f:v=>nf(v,1)},
 {l:'時価総額',i:12,f:v=>v>=1e4?nf(v/1e4,2)+'<small>兆円</small>':nf(v,v<10?1:0)+'<small>億円</small>'},
 {l:'逆日歩',u:'円',i:13,f:v=>nf(v,2)},
 {l:'単位株数',u:'株',i:14,f:v=>nf(v)},
 {l:'配当利回り',u:'%',i:15,f:v=>nf(v,2)},
 {l:'決算発表日',i:16,f:(v,r)=>`<span title="${r[17]===1?'JPX が発表した予定日':'まだ発表されていないため、昨年の同じ時期の発表日から推定'}">`+v.replace(/-/g,'/')+`<span class="tg${r[17]===1?' on':''}">${r[17]===1?'予定':'予想'}</span></span>`},
];
const ST={};   // 並べ替え（一覧表ごと。{i:列, d:1昇順/-1降順}。無ければ追加した順）
function order(l){const c=l.c.slice(),st=ST[l.id];if(!st)return c;
 const v=x=>{const r=BY[x];return r?r[st.i]:null;};
 return c.sort((a,b)=>{const x=v(a),y=v(b);if(x==null&&y==null)return 0;if(x==null)return 1;if(y==null)return -1;return (x<y?-1:x>y?1:0)*st.d;});}
const IXNOTE={n225:'日経225データ',topix:'JPX のTOPIX構成銘柄ウエイト一覧',y333:'読売新聞の構成銘柄一覧'},SHOW={},STEP=300;
function sec(l,n,N){const st=ST[l.id],th=(i,h)=>`<th data-i="${i}"${st&&st.i===i?' class="on"':''}>${h}${st&&st.i===i?(st.d>0?' ▲':' ▼'):''}</th>`;
 const head='<tr>'+th(0,'銘柄')+COLS.map(c=>th(c.i,c.l+(c.u?`<small>(${c.u})</small>`:''))).join('')+'<th></th></tr>';
 const all=order(l),lim=SHOW[l.id]||STEP,rest=all.length-lim;
 const body=all.slice(0,lim).map(code=>{const r=BY[code],x=l.ix?'<td></td>':`<td><button class="x" type="button" title="この一覧表から外す" data-rm="${esc(code)}">×</button></td>`;
  if(!r)return `<tr><td class="nm"><b>${esc(code)}</b><span class="na">データなし</span></td><td colspan="${COLS.length}"></td>${x}</tr>`;
  return `<tr><td class="nm"><a href="${ONE}${encodeURIComponent(code)}.html" title="${esc(r[1])}（${esc(r[2])}）"><b>${esc(code)}</b><span>${esc(r[1])}</span></a></td>`
   +COLS.map(c=>`<td${c.c?` class="${c.c}"`:''}>${r[c.i]==null?NA:c.f(r[c.i],r)}</td>`).join('')+x+'</tr>';}).join('');
 return `<section class="lst" data-id="${l.id}"><div class="lh"><h2>${esc(l.t)}</h2><span class="cnt">${l.c.length}銘柄</span>
<span class="ops"><button class="ob" type="button" data-op="ren">名前を変える</button>${l.c.length?'<button class="ob" type="button" data-op="csv" title="この一覧表を CSV ファイルに保存（Excel で開けます）">CSVに保存</button>':''}${n>0?'<button class="ob" type="button" data-op="up" title="付箋を左へ移動">←</button>':''}${n<N-1?'<button class="ob" type="button" data-op="dn" title="付箋を右へ移動">→</button>':''}<button class="ob" type="button" data-op="del">削除</button></span></div>
${l.ix?`<div class="ixn">指数の採用銘柄（<b>${esc((WD.idx[l.ix]||{}).asof||"")}</b> 時点${IXNOTE[l.ix]?"・"+IXNOTE[l.ix]:""}）。採用銘柄が入れ替わると、この表も自動で入れ替わります。</div>`:`<div class="add"><input type="search" placeholder="銘柄を追加 — __ADDPH__" autocomplete="off"><div class="sg" hidden></div></div>`}
${l.c.length?`<div class="tw"><table><colgroup><col class="c0">${COLS.map(c=>`<col class="c${c.i}">`).join('')}<col class="cx"></colgroup><thead>${head}</thead><tbody>${body}</tbody></table></div>${rest>0?`<div class="more"><button class="ob" type="button" data-op="more">さらに表示（残り ${rest.toLocaleString()}）</button><button class="ob" type="button" data-op="all">すべて表示</button></div>`:''}`:(l.ix?'<div class="empty">採用銘柄のデータがまだありません。</div>':'<div class="empty">上の欄に入力して、この一覧表に銘柄を追加してください。</div>')}</section>`;}
const SELK=WD.selKey||'kabuListSel';let SEL=null;try{SEL=localStorage.getItem(SELK);}catch(e){}
function setSel(id){SEL=id;try{localStorage.setItem(SELK,id);}catch(e){}}
function render(focusId){const L=K.lists(),box=$('lists'),tb=$('tabs');
 if(!L.length){tb.innerHTML='';box.innerHTML='<div class="empty0">まだ一覧表がありません。上の欄にタイトル（例：高配当、デイトレ候補）を入れて「＋ 一覧表を作る」を押すと、銘柄を入れる表ができます。一覧表はいくつでも作れ、付箋（タブ）で切り替えます。</div>';return;}
 if(!L.some(l=>l.id===SEL))SEL=L[0].id;
 const n=L.findIndex(l=>l.id===SEL);
 tb.innerHTML=L.map(l=>`<button type="button" class="tab${l.id===SEL?' on':''}" data-id="${l.id}" title="${esc(l.t)}${l.ix?'（指数の採用銘柄・自動で入れ替え）':''}">${l.ix?'<i class="ixm"></i>':''}${esc(l.t)}<small>${l.c.length.toLocaleString()}</small></button>`).join('');
 box.innerHTML=sec(L[n],n,L.length);
 const on=tb.querySelector('.on');if(on)tb.scrollLeft=Math.max(0,on.offsetLeft-tb.clientWidth/2+on.offsetWidth/2);
 if(focusId){const s=box.querySelector('.add input');if(s)s.focus();}}
$('tabs').addEventListener('click',e=>{const b=e.target.closest('.tab');if(b){setSel(b.dataset.id);render();}});
/* CSV（表示中の並び順。Excel で文字化けしないよう BOM 付き UTF-8） */
const CSVH=['コード','銘柄名','市場','株価','前日比(円)','前日比(%)','出来高(株)','売買代金(百万円)','VWAP','PER(倍)','PBR(倍)','ROE(%)','時価総額(億円)','逆日歩(円)','単位株数','配当利回り(%)','次の決算発表日','予定/予想'];
function saveCsv(l){const q=v=>v==null?'':/[",\n]/.test(String(v))?'"'+String(v).replace(/"/g,'""')+'"':String(v);
 const rows=order(l).map(c=>{const r=BY[c];return r?r.slice(0,17).concat(r[16]?(r[17]===1?'予定':'予想'):''):[c];});
 const txt='﻿'+[CSVH].concat(rows).map(r=>r.map(q).join(',')).join('\r\n')+'\r\n';
 const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([txt],{type:'text/csv;charset=utf-8'}));
 a.download='監視銘柄_'+l.t.replace(/[\\/:*?"<>|\s]+/g,'_')+'_'+WD.asof+'.csv';
 document.body.appendChild(a);a.click();setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove();},1500);}
const idOf=el=>el.closest('.lst').dataset.id;
function suggest(inp){const box=inp.nextElementSibling,q=norm(inp.value.trim());
 if(!q){box.hidden=true;box.innerHTML='';return;}
 const t=q.split(/\s+/),id=idOf(inp),have=new Set((K.lists().find(x=>x.id===id)||{c:[]}).c),out=[];
 for(let i=0;i<WD.S.length&&out.length<12;i++)if(t.every(w=>IX[i].includes(w)))out.push(WD.S[i]);
 box.innerHTML=out.map((r,i)=>`<div data-c="${esc(r[0])}"${i?'':' class="on"'}><b>${esc(r[0])}</b><span>${esc(r[1])}</span><small>${have.has(r[0])?'<span class="in">追加済み</span>':esc(r[2])}</small></div>`).join('')
  ||'<div><span class="in">見つかりません</span></div>';box.hidden=false;}
function addTo(id,code){if(!code)return;K.addCode(id,code);render(id);}
$('lists').addEventListener('input',e=>{if(e.target.matches('.add input'))suggest(e.target);});
$('lists').addEventListener('keydown',e=>{const t=e.target;
 if(t.matches('.add input')&&e.key==='Enter'){e.preventDefault();const d=t.nextElementSibling.querySelector('[data-c]');if(d)addTo(idOf(t),d.dataset.c);}
 if(t.matches('.add input')&&e.key==='Escape'){t.value='';suggest(t);}
 if(t.matches('.ren')&&e.key==='Enter'){e.preventDefault();t.blur();}});
$('lists').addEventListener('mousedown',e=>{const d=e.target.closest('.sg [data-c]');if(d){e.preventDefault();addTo(idOf(d),d.dataset.c);}});
$('lists').addEventListener('focusout',e=>{const t=e.target;
 if(t.matches('.add input'))setTimeout(()=>{const b=t.nextElementSibling;if(b&&document.activeElement!==t)b.hidden=true;},150);
 if(t.matches('.ren')){K.rename(idOf(t),t.value);render();}});
$('lists').addEventListener('click',e=>{const t=e.target;
 const th=t.closest('th[data-i]');
 if(th){const id=idOf(th),i=+th.dataset.i,st=ST[id];
  const d0=i===0||i===16?1:-1;if(!st||st.i!==i)ST[id]={i,d:d0};else if(st.d===d0)st.d=-st.d;else delete ST[id];
  render();return;}
 if(t.dataset.rm){K.rmCode(idOf(t),t.dataset.rm);render();return;}
 const op=t.dataset.op;if(!op)return;const id=idOf(t);
 if(op==='up'||op==='dn'){K.move(id,op==='up'?-1:1);render();}
 else if(op==='more'||op==='all'){SHOW[id]=op==='all'?1e9:(SHOW[id]||STEP)+STEP;render();}
 else if(op==='csv'){const l=K.lists().find(x=>x.id===id);if(l)saveCsv(l);}
 else if(op==='ren'){const h=t.closest('.lh').querySelector('h2');if(!h)return;const l=K.lists().find(x=>x.id===id);
  h.outerHTML=`<input class="ren" type="text" maxlength="40" value="${esc(l.t)}">`;const i=t.closest('.lh').querySelector('.ren');i.focus();i.select();}
 else if(op==='del'){if(t.classList.contains('warn')){K.del(id);delete ST[id];render();}
  else{t.classList.add('warn');t.textContent='本当に削除する';setTimeout(()=>{if(t.isConnected){t.classList.remove('warn');t.textContent='削除';}},4000);}}});
$('newl').addEventListener('submit',e=>{e.preventDefault();const l=K.create($('nt').value);if(!l){$('nt').focus();return;}$('nt').value='';setSel(l.id);render(l.id);});
$('theme').addEventListener('click',()=>{const d=document.documentElement;
 const cur=d.getAttribute('data-theme')||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');
 const n=cur==='dark'?'light':'dark';d.setAttribute('data-theme',n);try{localStorage.setItem('fdb-theme',n)}catch(e){}});
if(WD.demo&&!K.lists().length)K.seed(WD.demo);
K.sync(WD.idx);
$('sub').textContent=`株価 ${WD.asof} 終値 ／ 更新 ${WD.built} ／ 一覧表はこの端末（ブラウザ）に保存`;
render();
</script></body></html>"""

NOTE = ("銘柄名を押すと株式分析ダッシュボード、株価を押すとチャートを開きます。一覧表は上の付箋（タブ）で切り替え、「CSVに保存」で表示中の一覧表をファイルに保存できます。最初から入っている指数の一覧表（付箋に ● 印）は採用銘柄が入れ替わると自動で入れ替わり、銘柄を手で足したり外したりはできません（表ごと削除はできます）。列名を押すと並べ替え（もう一度で逆順、3回目で追加した順に戻る）。"
        "VWAP は5分足から計算した当日の出来高加重平均（5分足が無い銘柄は日足の高値・安値・終値の平均）、売買代金は VWAP×出来高。"
        "PER・PBR・ROE・配当利回り・時価総額はスクリーニングと同じ値。逆日歩は日証金の1株あたり品貸料（貸借銘柄以外・発生なしの日は「―」か 0）。"
        "決算発表日は次の発表日で、JPX が発表済みの日は「予定」、まだ発表されていない銘柄は昨年の同じ時期の発表日から推定した「予想」です。")

DEMO = [{"id": "d1", "t": "主力株", "c": ["7203", "6758", "8306", "9984", "6861", "8035", "9983"]},
        {"id": "d2", "t": "高配当", "c": ["8058", "2914", "9433", "8316", "5401", "1605"]},
        {"id": "d3", "t": "デイトレ候補", "c": ["6920", "7011", "5803", "6146"]}]


def build(head: str, site_name: str = "東証 株分析", preview: bool = False) -> Path:
    data = build_data()
    js = "window.WD=" + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";"
    page = (PAGE.replace("__SITE__", site_name).replace("__HEAD__", head).replace("__NOTE__", NOTE)
            .replace("__ADDPH__", "コード・銘柄名（例: 7203 / トヨタ）"))
    if preview:
        data["demo"] = DEMO
        data["ch"] = "../../data/charts/"; data["one"] = "../../data/charts/one/"
        js = "window.WD=" + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";"
        lib = (BASE / "watch_common.js").read_text(encoding="utf-8")
        out = BASE / "Claude outputs" / "watch_preview" / "watch_preview.html"   # 確認用（公開フォルダには置かない）
        out.parent.mkdir(parents=True, exist_ok=True)
        page = page.replace('href="./index.html"', 'href="../../data/charts/index.html"')
        out.write_text(page.replace("__SCRIPTS__", f"<script>{js}</script>\n<script>{lib}</script>"), encoding="utf-8")
        return out
    (SITE / "watch_data.js").write_text(js, encoding="utf-8")
    out = SITE / "watch.html"
    out.write_text(page.replace("__SCRIPTS__", '<script src="./watch_data.js"></script>\n<script src="./one/assets/watch.js"></script>'),
                   encoding="utf-8")
    return out


if __name__ == "__main__":
    import make_home
    t = make_home.TMPL
    head = t[t.index("<script>(function(){var m="):t.index("</style>") + len("</style>")]
    p = build(head, preview="--preview" in sys.argv)
    print(f"監視銘柄ページを作成: {p}（{p.stat().st_size/1024:.0f} KB）")
