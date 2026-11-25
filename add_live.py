#!/usr/bin/env python3
"""主要指数の「いまの値」をページに足す公開前の後処理（2026-11-24 作成。deploy_github.sh から毎回実行・何度実行しても同じ）
東証版・米国版で同じファイル（フォルダ名で切り替え。~/米国株分析＝米国、それ以外＝東証）

 トップ画面（index.html）：相場ウィジェット（TradingView の無料ティッカー帯）だけを目次の上（銘柄を探すの上）に置く。
   マーケット概況はその日の終値の話なので、タイルの数値は書き換えない（利用者の指定、2026-11-24）。
 主要指数ダッシュボード（indices.html）：相場ウィジェット＋指数カードと騰落率・テクニカルの表を live_indices.json（fetch_live.py が取引時間中に
   15分おきに公開）の値で計算し直す。ページの株価データの日付より新しい取引日の値のときだけ。グラフは終値のまま。
"""
import json, re
from pathlib import Path

BASE = Path(__file__).resolve().parent
SITE = BASE / "data" / "charts"
US = BASE.name == "米国株分析"
RE_BLOCK = re.compile(r"<!--live:v1-->.*?<!--/live-->", re.S)

# 無料ウィジェットで出せる銘柄（指数そのものではなく CFD・先物の値。米10年金利 TVC:US10Y は出せなかった）
if US:
    TV_SYMBOLS = [
        ("FOREXCOM:DJI", "NYダウ"), ("FOREXCOM:SPXUSD", "S&P500"), ("FOREXCOM:NSXUSD", "NASDAQ100"),
        ("FOREXCOM:US2000", "ラッセル2000"), ("FX:USDJPY", "ドル円"),
        ("TVC:USOIL", "WTI原油"), ("TVC:GOLD", "金"), ("BITSTAMP:BTCUSD", "ビットコイン"),
        ("OANDA:JP225USD", "日経225"),
    ]
    SESSION = "米国の取引時間中に15分ごとに更新"
    IDX_KEY = "sp500"
else:
    TV_SYMBOLS = [
        ("OANDA:JP225USD", "日経225"), ("FX:USDJPY", "ドル円"), ("FOREXCOM:DJI", "NYダウ"),
        ("FOREXCOM:SPXUSD", "S&P500"), ("FOREXCOM:NSXUSD", "NASDAQ100"),
        ("TVC:USOIL", "WTI原油"), ("TVC:GOLD", "金"), ("BITSTAMP:BTCUSD", "ビットコイン"),
    ]
    SESSION = "東証の取引時間中に15分ごとに更新。TOPIXはETF（1306）の値動きで換算"
    IDX_KEY = "nikkei225"
# ダッシュボードのキー → live_indices.json のキー（同じ名前のものは省略）
LVK = {"nasdaq100": "ndx", "russell2000": "rut"}

CSS = """<style id="live-css">
.tvw{margin:0 0 10px;min-height:46px;color-scheme:light;border:1px solid var(--line,var(--border,#d6d5ce));border-radius:10px;overflow:hidden}
.tvw .tradingview-widget-copyright{display:none}
.tvw.tvtop{margin:4px 0 12px}
.lvn{font-size:11.5px;color:var(--mut,var(--muted,#777));margin:0 2px 10px}
.lvn b{color:inherit;font-weight:700}
.lvdot{display:inline-block;width:6px;height:6px;border-radius:50%;background:#e0453a;margin-right:4px;vertical-align:1px;animation:lvp 2s infinite}
@keyframes lvp{50%{opacity:.25}}
</style>"""

# ウィジェットを明暗に合わせて作る（明暗スイッチを押したら作り直す）
JS_WIDGET = """
function tvTheme(){var t=document.documentElement.getAttribute('data-theme');
 if(t!=='dark'&&t!=='light')t=matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';return t}
function tvBuild(){var box=document.getElementById('tvw');if(!box)return;var th=tvTheme();if(box.dataset.th===th)return;box.dataset.th=th;
 box.innerHTML='<div class="tradingview-widget-container"><div class="tradingview-widget-container__widget"></div></div>';
 var s=document.createElement('script');s.src='https://s3.tradingview.com/external-embedding/embed-widget-ticker-tape.js';s.async=true;
 s.textContent=JSON.stringify({symbols:__SYMS__,showSymbolLogo:false,isTransparent:true,displayMode:'adaptive',colorTheme:th,locale:'ja'});
 box.firstChild.appendChild(s)}
tvBuild();new MutationObserver(function(){setTimeout(tvBuild,50)}).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
""".replace("__SYMS__", json.dumps([{"proName": p, "title": t} for p, t in TV_SYMBOLS], ensure_ascii=False))

# 主要指数ダッシュボード：指数カード（DATA の m）を差し替えて描き直す（明暗の切り替え・カードを押したときの描き直しでも残る）
JS_IDX = """
var LVK=__LVK__;
// 恐怖指数の水準の目安（株価指数/make_dashboard.py の BANDS と同じ）。15分ごとの値で区分を付け直す
var LVB={vix:[[15,'安定','good'],[20,'平常','good'],[30,'警戒','warning'],[1e9,'恐怖','critical']],
 nikkei_vi:[[20,'安定','good'],[25,'平常','good'],[35,'警戒','warning'],[1e9,'恐怖','critical']]};
// 騰落率・テクニカルの指標（株価指数/make_dashboard.py の metrics と同じ計算）。日足に「いまの値」を当日分として足して計算する
function lvMet(x,today,close,prevClose){
 var d=x.d.slice(),c=x.c.slice();
 while(d.length&&d[d.length-1]>=today){d.pop();c.pop()}
 d.push(today);c.push(close);
 var vob=function(day){var lo=0,hi=d.length-1,r=-1;while(lo<=hi){var mid=(lo+hi)>>1;if(d[mid]<=day){r=mid;lo=mid+1}else hi=mid-1}return r<0?null:c[r]};
 var shift=function(day,my,mm){var t=new Date(day*86400000),y=t.getUTCFullYear()-my,mo=t.getUTCMonth()-mm;while(mo<0){mo+=12;y--}
  var dim=new Date(Date.UTC(y,mo+1,0)).getUTCDate();return Math.round(Date.UTC(y,mo,Math.min(t.getUTCDate(),dim))/86400000)};
 var pct=function(a,b){return a==null||b==null||b===0?null:(a/b-1)*100};
 var mean=function(n){if(c.length<n)return null;var s=0;for(var i=c.length-n;i<c.length;i++)s+=c[i];return s/n};
 var y=new Date(today*86400000).getUTCFullYear(),pye=vob(Math.round(Date.UTC(y-1,11,31)/86400000));
 var hi=-Infinity,lo=Infinity;for(var i=d.length-1;i>=0&&d[i]>today-365;i--){if(c[i]>hi)hi=c[i];if(c[i]<lo)lo=c[i]}
 var prev=prevClose;
 var m={close:close,chg:close-prev,chgPct:pct(close,prev),r1w:pct(close,vob(today-7)),r1m:pct(close,vob(shift(today,0,1))),
  ytd:pct(close,pye),r1y:pct(close,vob(shift(today,1,0))),hi52:hi,lo52:lo,fromHi:pct(close,hi),ma25:pct(close,mean(25)),ma200:pct(close,mean(200))};
 if(x.m&&x.m.unit==='pt'){var df=function(a,b){return a==null||b==null?null:a-b};
  m.chgPct=m.chg;m.r1w=df(close,vob(today-7));m.r1m=df(close,vob(shift(today,0,1)));m.ytd=df(close,pye);m.r1y=df(close,vob(shift(today,1,0)));m.fromHi=close-hi}
 return m}
fetch('./live_indices.json?'+Date.now(),{cache:'no-store'}).then(function(r){return r.ok?r.json():null}).then(function(L){
 var day=String(L&&(L.day||L.ny)||'').slice(0,10);
 if(!L||!L.tiles||!(day>ASOF))return;
 if(typeof DATA==='undefined'||typeof renderCards!=='function')return;
 var today=Math.round(Date.UTC(+day.slice(0,4),+day.slice(5,7)-1,+day.slice(8,10))/86400000);
 var t=L.at.slice(11),n=0;
 DATA.forEach(function(x){var v=L.tiles[LVK[x.key]||x.key];if(!v||x.missing||x.monthly||!x.m||!(v.prev>0))return;
  var mm;try{mm=x.d&&x.c?lvMet(x,today,v.close,v.prev):null}catch(e){mm=null}
  if(!mm)mm={close:v.close,chg:v.close-v.prev,chgPct:(v.close/v.prev-1)*100};
  x.m=Object.assign({},x.m,mm,{stale:false,date:'<span class="lvdot"></span>'+t+' 時点'});
  if(LVB[x.key]&&x.m.band){var z=LVB[x.key].find(function(r){return v.close<r[0]});if(z){x.m.band=z[1];x.m.bandStatus=z[2]}}
  n++});
 if(!n)return;renderCards();
 if(typeof renderTable==='function'){renderTable();   // 表の日付欄は先頭を切り取って出すので、目印の欄だけ描き直す
  document.querySelectorAll('#perf td').forEach(function(td){if(td.textContent.indexOf('lvdot')>=0)td.innerHTML='<span class="lvdot"></span>'+t+' 時点'})}
 var d=L.at.slice(5,10).replace('-','/').replace(/^0/,'');
 var nt=document.getElementById('lvn');if(nt)nt.innerHTML='<span class="lvdot"></span>印の指数は <b>'+d+' '+t+'</b> 時点の値（__SESSION__）。'
  +'カードと「騰落率・テクニカル」の表をこの値で計算し直しています。終値は次の日次更新で確定します。グラフは前日までの終値です。'}).catch(function(){});
""".replace("__LVK__", json.dumps(LVK)).replace("__SESSION__", SESSION)


def script(asof, body):
    return f'<!--live:v1--><script>(function(){{var ASOF={json.dumps(asof)};{JS_WIDGET}{body}}})();</script><!--/live-->'


def clean(h):
    h = RE_BLOCK.sub("", h)
    return re.sub(r'<style id="live-css">.*?</style>', "", h, flags=re.S)


def do_home():
    p = SITE / "index.html"
    if not p.exists():
        return "index.html なし"
    h = clean(p.read_text(encoding="utf-8"))
    k = h.find('<div class="search">')
    if k < 0:
        return "index.html の検索欄が見つからない（変更せず）"
    h = h[:k] + '<!--live:v1--><div class="tvw tvtop" id="tvw"></div><!--/live-->' + h[k:]
    h = h.replace("</head>", CSS + "</head>", 1)
    h = h.replace("</body>", script("", "") + "</body>", 1)
    p.write_text(h, encoding="utf-8")
    return "index.html（相場ウィジェット）"


def do_indices():
    p = SITE / "indices.html"
    if not p.exists():
        return "indices.html なし"
    h = clean(p.read_text(encoding="utf-8"))
    m = re.search(r'"key":"' + IDX_KEY + r'".*?"date":"(\d{4}-\d{2}-\d{2})"', h)
    asof = m.group(1) if m else "9999"
    tag = '<div id="cards"></div>'
    if tag not in h:
        return "indices.html の目印なし（変更せず）"
    h = h.replace(tag, '<!--live:v1--><div class="tvw" id="tvw"></div><div class="lvn" id="lvn"></div><!--/live-->' + tag, 1)
    h = h.replace("</head>", CSS + "</head>", 1)
    h = h.replace("</body>", script(asof, JS_IDX) + "</body>", 1)
    p.write_text(h, encoding="utf-8")
    return f"indices.html（{IDX_KEY} {asof}）"


if __name__ == "__main__":
    print("live:", do_home(), "／", do_indices())
