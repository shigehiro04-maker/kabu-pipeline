#!/usr/bin/env python3
"""検証1〜7の結果をレポート（非公開の HTML）にまとめる。

  python dtp_report.py
出力: ~/株分析/data/daytrade/検証レポート.html（東証・米国の両方。公開フォルダには置かない）
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dtp_core as C  # noqa: E402
import dtp_data as D  # noqa: E402


def load(mk):
    rd = os.path.join(D.cfg(mk)["out"], "research")
    p = os.path.join(rd, "results.json")
    if not os.path.exists(p):
        return None
    R = json.load(open(p, encoding="utf-8"))
    fp = os.path.join(rd, "forward", "result.json")
    R["forward"] = json.load(open(fp, encoding="utf-8")) if os.path.exists(fp) else None
    return R


HTML = r"""<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>デイトレ チャートパターン 検証レポート</title>
<style>
:root{--bg:#f3f4f6;--card:#fff;--fg:#0c0d10;--fg2:#3d4148;--mut:#5b6068;--line:#dfe2e7;--up:#b91c24;--dn:#08705a;--hl:#fff7e0;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#050608;--card:#101216;--fg:#f2f4f8;--fg2:#c6cbd6;--mut:#8f96a3;--line:#23262d;--up:#ff7378;--dn:#3fd0a4;--hl:#2a2410;color-scheme:dark}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.6 "Hiragino Sans","Noto Sans JP",system-ui,sans-serif;font-variant-numeric:tabular-nums}
main{max-width:1180px;margin:0 auto;padding:22px 16px 60px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;border-top:3px solid var(--fg);padding-top:10px;margin:30px 0 8px}
h3{font-size:14.5px;margin:18px 0 6px}
.sub{color:var(--mut);font-size:12.5px}
.box{background:var(--card);border-radius:14px;padding:12px 16px;margin:10px 0}
.key{background:var(--hl)}
.box p{margin:6px 0}.box ul{margin:6px 0;padding-left:20px}
.tabs{display:flex;gap:6px;margin:14px 0 4px;position:sticky;top:0;background:var(--bg);padding:6px 0;z-index:5}
.tabs button{border:0;border-radius:10px;padding:7px 16px;font:inherit;font-weight:800;background:var(--card);color:var(--fg);cursor:pointer}
.tabs button.on{background:var(--fg);color:var(--bg)}
.tw{overflow-x:auto;background:var(--card);border-radius:12px;margin:6px 0}
table{border-collapse:collapse;width:100%;font-size:12.5px}
th,td{padding:5px 8px;text-align:right;white-space:nowrap;border-top:1px solid var(--line)}
thead th{border-top:0;border-bottom:2px solid var(--fg);font-size:11.5px}
th.l,td.l{text-align:left}
.u{color:var(--up)}.d{color:var(--dn)}.m{color:var(--mut)}
b.u,b.d{font-weight:800}
.g{background:color-mix(in srgb,var(--up) 10%,transparent)}
.note{font-size:12px;color:var(--mut)}
</style></head><body><main>
<h1>デイトレ チャートパターン 検証レポート</h1>
<div class="sub">作成 __MADE__ ・ 非公開（Mac の中だけ）。数字は5分足の保管庫（2026年8月〜）と日足（約10年）から計算。</div>
<div class="box key" id="concl"></div>
<div class="box"><b>前提</b>
<ul>
<li>エントリー＝シグナルが出た足の終値。手じまい＝目標か損切りの先に届いた方、どちらも無ければ大引け（日足は最長20営業日）。</li>
<li><b>売買コスト</b>＝往復2ティック（買うときと売るときにそれぞれ1ティック不利に約定）。東証は呼値（TOPIX500 は細かい呼値）、米国は1セント。手数料0円、空売りの費用は入れていません。</li>
<li>損益は「1回あたりの％」。<b>net＝コストを引いた後</b>、gross＝コストを引く前。売りは下がると＋。</li>
<li><b>t値</b>は、同じ日（日足は同じ月）のシグナルがそろって動く分を考えた値。おおむね <b>2以上</b>で「偶然とは言いにくい」。</li>
<li>対象は売買代金が1日 東証1億円・米国100万ドル以上の銘柄。今上場している銘柄だけなので、日足の買いは少し良く出やすい（上場廃止を含まない）。</li>
</ul></div>
<div class="tabs" id="tabs"><button data-m="jp" class="on">東証</button><button data-m="us">米国</button></div>
<div id="body"></div>
</main><script>
const ALL=__DATA__, PN=__PN__;
const $=id=>document.getElementById(id);
const f=(v,dg=3)=>v==null?'<span class="m">―</span>':'<span class="'+(v>0?'u':v<0?'d':'')+'">'+(v>0?'+':'')+v.toFixed(dg)+'</span>';
const fp=(v,dg=3)=>v==null?'<span class="m">―</span>':f(v,dg)+'<span class="m">%</span>';
const ft=v=>v==null?'<span class="m">―</span>':(Math.abs(v)>=2?'<b class="'+(v>0?'u':'d')+'">'+v.toFixed(1)+'</b>':v.toFixed(1));
const nf=v=>v==null?'―':v.toLocaleString();
const pn=k=>PN[k]?PN[k][0]+' '+PN[k][1]+(k[0]==='U'||k.endsWith('+')?'（買）':'（売）'):k;
function tbl(head,rows){ return '<div class="tw"><table><thead><tr>'+head.map((h,i)=>'<th class="'+(i===0?'l':'')+'">'+h+'</th>').join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+r.map((c,i)=>'<td class="'+(i===0?'l':'')+'">'+c+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>'; }
function concl(){
  let h='<b>結論</b><ul>';
  for(const mk of ['jp','us']){ const R=ALL[mk]; if(!R) continue; const nm=mk==='jp'?'東証':'米国';
    const best=R.patterns.slice().sort((a,b)=>b.net-a.net)[0];
    h+='<li><b>'+nm+'（5分足）</b>：22パターン全体でコスト前 '+fp(R.all.gross)+'、<b>コスト後 '+fp(R.all.net)+'</b>（t '+ft(R.all.t)+'）。コスト後にプラスのパターンは '+R.patterns.filter(p=>p.net>0).length+'個（一番良いのは '+pn(best.key)+' の '+fp(best.net)+'）。'
      +'条件を '+nf(R.rules.tested)+'通り試し、前半でコスト後に有望だったのは '+R.rules.selected+'個、後半でも t≥2 だったのは <b>'+R.rules.held_t2+'個</b>。'
      +(R.rules_gross?'コスト前なら '+R.rules_gross.selected+'個 → 後半でも t≥2 は '+R.rules_gross.held_t2+'個。':'')
      +(R.ml?' 機械学習の予測上位10%は確認期間でコスト後 '+fp(R.ml.top.net)+'（t '+ft(R.ml.top.t)+'・'+R.ml.split[2]+'〜の'+'少ない日数）。':'')+'</li>';
  }
  for(const mk of ['jp','us']){ const R=ALL[mk]; if(!R||!R.daily) continue; const nm=mk==='jp'?'東証':'米国';
    const P=R.daily.patterns.filter(p=>p.excess20!=null), b=P.filter(p=>p.key[0]==='U'||p.key.endsWith('+')), s=P.filter(p=>p.key[0]==='D'||p.key.endsWith('-'));
    const av=a=>a.length?a.reduce((x,p)=>x+p.excess20*p.n,0)/a.reduce((x,p)=>x+p.n,0):null;
    const bx=av(b), sx=av(s);
    const sb=sx==null?null:-sx, diff=(bx==null||sb==null)?null:bx-sb;
    h+='<li><b>'+nm+'（日足10年）</b>：20日後の株価の市場平均との差は、買いのパターンの後 '+fp(bx,2)+'、売りのパターンの後 '+fp(sb,2)+'。'
      +(diff!=null&&diff<0?'<b>売りのパターンの後のほうが株価が良く、パターンの「向き」は逆に出ています</b>（日足ではむしろ逆張りの傾向）。'
        :'買いのパターンの後のほうが '+fp(diff,2)+' 良く、向きは合っています。')
      +'今上場している銘柄だけで調べているので、全体に少し上振れしています。</li>';
  }
  h+='</ul><p>5分足のパターンは、<b>コストを引く前でもほぼ0%</b>で、コスト（中央値で0.06〜0.1%）を引くとほぼすべてマイナスです。条件を絞っても、前半で良かった条件が後半でも効く例はコスト後にはほとんどありません。'
   +'例外的に<b>米国の「戻り売り」（損益比2以上・VWAPより下など）はコスト前に前半・後半ともプラス</b>で、流動性の高い銘柄なら手数料後もわずかに残る可能性があります。機械学習も米国では上位10%がコスト後プラスでしたが、確認期間が短いので<b>フォワードテストで確かめてから</b>判断するのが安全です。</p>';
  $('concl').innerHTML=h;
}
function render(mk){
  const R=ALL[mk]; if(!R){ $('body').innerHTML='<div class="box">この市場の結果がまだありません</div>'; return; }
  let h='<div class="sub">5分足：'+R.period[0]+'〜'+R.period[1]+'（'+R.period[2]+'営業日）・'+nf(R.n_codes)+'銘柄・シグナル '+nf(R.n_events)+'回</div>';
  // 4 コスト
  h+='<h2>4. 売買コストを入れた評価</h2><div class="box"><p>1回あたりのコストは平均 '+R.cost.mean+'%・中央値 '+R.cost.median+'%（上位25%は '+R.cost.p75+'%超）。パターンの損益の大きさ（絶対値の平均 '+R.cost.gross_abs_mean+'%）に比べて小さくない割合です。値段が安い株ほど1ティックの比率が大きく、コストが重くなります。</p></div>';
  h+=tbl(['コストの大きさ','回数の割合','回数','コスト前','コスト後','t値','勝率','プラスの日'],R.cost.buckets.map(b=>[b.name,b.share+'%',nf(b.n),fp(b.gross),fp(b.net),ft(b.t),b.win+'%',b.days_pos+'%']));
  h+='<h3>パターン別（コスト前・後）</h3>';
  h+=tbl(['パターン','回数','コスト前','コスト後','t値','勝率','流動性が高い銘柄（コスト0.05%以下）のコスト後','逆方向に入ったら（1時間後・コスト後）'],R.patterns.map(p=>[pn(p.key),nf(p.n),fp(p.gross),fp(p.net),ft(p.t),p.win+'%',p.liquid?fp(p.liquid.net)+' <span class="m">('+nf(p.liquid.n)+'回)</span>':'―',fp(p.rev_r60)]));
  // 1 条件
  const rr=(nm,r)=>r?'<tr><td class="l">'+nm+'</td><td>'+nf(r.tested)+'</td><td>'+r.selected+'</td><td>'+r.held_pos+'</td><td><b>'+r.held_t2+'</b></td></tr>':'';
  h+='<h2>1. 条件つきの検証（前半で選び、後半で確かめる）</h2><div class="box"><p>地合い・日足トレンド・5日騰落・相対出来高・時間帯・窓・当日騰落・VWAP・値動きの大きさ・売買代金・損益比・コストの24条件を、1つまたは2つ組み合わせて、パターンごとに試しました。'
   +'前半（'+R.rules.train_days+'営業日、'+R.rules.split+'より前）で「プラスかつ t≥2」を選び、後半（'+R.rules.test_days+'営業日）でも効くかを見ています。たくさん試すほど偶然良く見える条件が混ざるため、後半での確認が大事です。</p></div>';
  h+='<div class="tw"><table><thead><tr><th class="l">対象</th><th>試した数</th><th>前半で有望</th><th>後半もプラス</th><th>後半も t≥2</th></tr></thead><tbody>'
   +rr('コスト後（全銘柄）',R.rules)+rr('コスト後（コスト0.05%以下の銘柄だけ）',R.rules_liquid)+rr('参考：コスト前',R.rules_gross)+'</tbody></table></div>';
  const surv=(R.rules_gross&&R.rules_gross.top||[]).filter(x=>x.net_te>0).slice(0,15);
  if(surv.length){ h+='<h3>コスト前で前半に有望だった条件（後半もプラスのもの）</h3>'+tbl(['パターン','条件','前半 回数','前半','前半 t','後半 回数','後半','後半 t'],surv.map(x=>[pn(x.key),x.cond,nf(x.n_tr),fp(x.net_tr),ft(x.t_tr),nf(x.n_te),fp(x.net_te),ft(x.t_te)])); }
  const lq=(R.rules_liquid&&R.rules_liquid.top||[]).slice(0,10);
  if(lq.length){ h+='<h3>コスト後（流動性の高い銘柄）で前半に有望だった条件</h3>'+tbl(['パターン','条件','前半 回数','前半','前半 t','後半 回数','後半','後半 t'],lq.map(x=>[pn(x.key),x.cond,nf(x.n_tr),fp(x.net_tr),ft(x.t_tr),nf(x.n_te),fp(x.net_te),ft(x.t_te)])); }
  // 2 逆張り
  h+='<h2>2. 逆張り・パターン以外の仕組み</h2><div class="box"><ul><li><b>窓の逆張り</b>：1%以上の窓で寄り付き、15分後に窓と逆へ。目標＝前日終値。</li><li><b>VWAP回帰</b>：VWAP から ATR×3 以上離れて向きが変わったら VWAP へ向けて。</li><li><b>ブレイク失敗の逆張り</b>：ブレイク型のシグナルが6本以内に線の内側へ戻ったら逆へ（目標1.5R）。</li><li><b>寄り付き30分の勢い</b>：前日終値→寄り付き30分後の方向に、大引け30分前に入り大引けで手じまう。</li></ul></div>';
  h+=tbl(['仕組み','回数','コスト前','コスト後','t値','勝率','前半（コスト後）','後半（コスト後）','流動性が高い銘柄のコスト後'],R.strat.map(s=>[s.kind,nf(s.n),fp(s.gross),fp(s.net),ft(s.t),s.win+'%',s.train?fp(s.train.net):'―',s.test?fp(s.test.net):'―',s.liquid?fp(s.liquid.net)+' <span class="m">(t '+(s.liquid.t??'―')+')</span>':'―']));
  const subs=[]; for(const s of R.strat) for(const x of s.sub) subs.push([s.kind,x.name,nf(x.n),fp(x.gross),fp(x.net),ft(x.t)]);
  h+='<h3>条件を変えた場合</h3>'+tbl(['仕組み','条件','回数','コスト前','コスト後','t値'],subs);
  // 3 日足
  const d=R.daily;
  if(d){
    h+='<h2>3. 日足（約10年）で同じパターン</h2><div class="box"><p>'+d.period[0]+'〜'+d.period[1]+'・シグナル '+nf(d.n)+'回。最長20営業日保有。比較：どの日に買っても12営業日後に上がっていた割合 '+d.base.up12+'%、平均 '+fp(d.base.avg12)+'（この期間は株価が上がったので、<b>買いは何もしなくてもプラス・売りはマイナスになりやすい</b>）。'
      +'そこで「市場平均との差」＝パターンの20日後の騰落から、同じ期間の全銘柄平均の騰落を差し引いた値も出しています。前半＝2021年まで、後半＝2022年から。</p></div>';
    h+=tbl(['パターン','回数','目標・損切り（コスト後）','t値','目標到達','損切り','20日後（コスト後）','市場平均との差','差の t値','前半','後半','プラスの年'],d.patterns.map(p=>[pn(p.key),nf(p.n),fp(p.net),ft(p.t),p.tgt+'%',p.stp+'%',fp(p.r20),fp(p.excess20),ft(p.excess20_t),p.train?fp(p.train.net):'―',p.test?fp(p.test.net):'―',p.pos_years+'/'+d.years.length]));
  }
  // 6 出口
  const ex=['目標・損切り','目標1R','目標2R','損切りのみ→大引け','30分後','1時間後','大引け'];
  h+='<h2>6. 出口ルールの比較・期待値（5分足・コスト後）</h2><div class="box"><p>同じエントリーで、手じまい方だけを変えたときの1回あたりの損益（コスト後）。勝率・損益比（平均の利益÷平均の損失）・最大の落ち込み（日ごとの平均損益を足していったときの最大下落、1回あたり％の累計）。勝率が低くても損益比が大きければプラスになり得ますが、ここではどの出口でもほぼマイナスです。</p></div>';
  h+=tbl(['パターン'].concat(ex),R.patterns.map(p=>[pn(p.key)].concat(ex.map(k=>{const x=p.exits[k]; return x?fp(x.net)+' <span class="m">'+x.win+'%</span>':'―';}))));
  h+='<h3>「目標・損切り」の勝率・損益比・最大の落ち込み</h3>'+tbl(['パターン','勝率','損益比','期待値（コスト後）','最大の落ち込み'],R.patterns.map(p=>{const x=p.exits['目標・損切り']; return [pn(p.key),x.win+'%',x.payoff==null?'―':x.payoff.toFixed(2),fp(x.net),x.dd==null?'―':x.dd.toFixed(1)+'%'];}));
  // 7 機械学習
  const ml=(x,nm)=>{ if(!x) return ''; let s='<h3>'+nm+'</h3><div class="box"><p>学習 '+x.split[0]+'〜'+x.split[1]+'、調整 〜'+x.split[2]+'、<b>確認 '+x.split[2]+'〜'+x.split[3]+'</b>（'+nf(x.n_test)+'回）。予測と実際の順位相関 '+x.spearman+'。確認期間の全体平均 '+fp(x.all_test)+' に対し、<b>予測の上位10%は '+fp(x.top.net)+'</b>（t '+ft(x.top.t)+'・プラスの日 '+(x.top.days_pos??'―')+'%）。</p></div>';
    s+=tbl(['予測の順位（10＝最も良い）','予測','実際（コスト後）','回数'],x.deciles.map(q=>[q.d,fp(q.pred),fp(q.net),nf(q.n)]));
    s+='<p class="note">効いている特徴：'+x.importance.map(i=>i.f+' '+i.share+'%').join('、')+'（cost＝コスト、riskp＝損切りまでの幅、key＝パターン、mkt＝地合い、atrp＝値動きの大きさ、logtv＝売買代金）</p>'; return s; };
  h+='<h2>7. 機械学習（LightGBM）</h2><div class="box"><p>パターン・条件・コストなどを入力に「コスト後の損益」を予測し、時間で分けた確認期間だけで評価しました（未来のデータは学習に使っていません）。</p></div>'+ml(R.ml,'5分足')+ml(R.ml_daily,'日足');
  // 5 フォワード
  const F=R.forward;
  h+='<h2>5. 記録だけの売買（フォワードテスト）</h2><div class="box"><p>'+(F?('<b>'+F.freeze+' までのデータで条件と機械学習のモデルを固定</b>しました。これより後の営業日のシグナルだけで、固定した条件・モデルの成績を毎日の更新で数えます（今は '+F.n_days+'営業日）。')
    :'まだ固定していません')+'</p>';
  if(F&&F.n_days){ h+='<p>全パターン：'+nf(F.all.n)+'回・コスト後 '+fp(F.all.net)+'。機械学習の上位10%：'+(F.ml&&F.ml.n!=null?nf(F.ml.n)+'回・コスト後 '+fp(F.ml.net)+'（t '+ft(F.ml.t)+'）':'―')+'</p>'; }
  h+='</div>';
  if(F&&F.rules&&F.rules.length) h+=tbl(['パターン','条件','種類','検証の後半','固定後 回数','固定後','固定後 t'],F.rules.map(x=>[pn(x.key),x.cond,x.src==='gross'?'コスト前':'コスト後',fp(x.bt_net_te),nf(x.n),fp(x.value),ft(x.t)]));
  $('body').innerHTML=h;
}
concl();
let cur='jp'; $('tabs').onclick=e=>{const b=e.target.closest('button'); if(!b)return; cur=b.dataset.m; for(const x of $('tabs').children)x.classList.toggle('on',x===b); render(cur);};
render(cur);
</script></body></html>
"""


def main():
    data = {mk: load(mk) for mk in ("jp", "us")}
    out = os.path.join(D.cfg("jp")["out"], "検証レポート.html")
    pn = {k: [v[0], v[1]] for k, v in C.PATTERNS.items()}
    html = (HTML.replace("__DATA__", json.dumps(data, ensure_ascii=False))
            .replace("__PN__", json.dumps(pn, ensure_ascii=False))
            .replace("__MADE__", time.strftime("%Y-%m-%d %H:%M")))
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"レポート: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
