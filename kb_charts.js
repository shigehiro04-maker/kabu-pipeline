/* 東証株分析 共通グラフ部品（業績ダッシュボード dashboards/ と 1画面 dashboards/one/ の両方で使う）
   make_company_dashboards.py と make_one_screen.py が、それぞれの JS の末尾にこのファイルをそのまま連結する。
   前提：ページ側に css(変数名) と niceTicks(lo,hi,n) があること。 */
/* ---------- 複合グラフ：棒（左軸）＋折れ線（左軸 or 右軸）。会社予想の行(fc)は薄く描く ---------- */
function smoothD(p){
  if(p.length<3) return p.map(function(q,i){return (i?"L":"M")+q[0].toFixed(1)+" "+q[1].toFixed(1);}).join(" ");
  var n=p.length,i,dx=[],m=[],t=[];
  for(i=0;i<n-1;i++){ dx[i]=p[i+1][0]-p[i][0]; m[i]=dx[i]?(p[i+1][1]-p[i][1])/dx[i]:0; }
  t[0]=m[0]; t[n-1]=m[n-2];
  for(i=1;i<n-1;i++){ t[i]=(m[i-1]*m[i]<=0)?0:3*(dx[i-1]+dx[i])/((2*dx[i]+dx[i-1])/m[i-1]+(dx[i]+2*dx[i-1])/m[i]); }
  var d="M"+p[0][0].toFixed(1)+" "+p[0][1].toFixed(1);
  for(i=0;i<n-1;i++){ var h=dx[i]/3;
    d+=" C"+(p[i][0]+h).toFixed(1)+" "+(p[i][1]+t[i]*h).toFixed(1)+" "+(p[i+1][0]-h).toFixed(1)+" "
      +(p[i+1][1]-t[i+1]*h).toFixed(1)+" "+p[i+1][0].toFixed(1)+" "+p[i+1][1].toFixed(1); }
  return d;
}

function Combo(host, cfg){
  var wrap=document.createElement("div"); wrap.className="kbplot";
  var tip=document.createElement("div"); tip.className="kbtip";
  host.appendChild(wrap); wrap.appendChild(tip);
  var rows=cfg.rows, bars=cfg.bars||[], lines=cfg.lines||[];
  function draw(){
    var W=wrap.clientWidth||460; if(W<40) return;
    var narrow=W<420, H=cfg.height||(narrow?240:290);
    var hasR=lines.some(function(s){return s.axis==="R";});
    var mL=narrow?40:52, mR=hasR?(narrow?36:44):10, mT=12, mB=26;
    var n=rows.length; if(!n) return;
    var iw=Math.max(40,W-mL-mR), ih=Math.max(40,H-mT-mB);
    var lv=[], rv=[];
    rows.forEach(function(r){
      bars.forEach(function(s){ if(r[s.key]!=null) lv.push(r[s.key]); });
      lines.forEach(function(s){ if(r[s.key]!=null) (s.axis==="R"?rv:lv).push(r[s.key]); });
    });
    if(!lv.length && !rv.length){ wrap.innerHTML='<div class="empty">データなし</div>'; return; }
    var lo=Math.min(0,Math.min.apply(null,lv.length?lv:[0])), hi=Math.max(0,Math.max.apply(null,lv.length?lv:[1]));
    var sp=(hi-lo)||1; hi+= hi>0?sp*0.06:0; lo-= lo<0?sp*0.06:0;
    var lt=niceTicks(lo,hi,narrow?4:5); lo=Math.min(lo,lt[0]); hi=Math.max(hi,lt[lt.length-1]);
    lt=lt.filter(function(t){return t>=lo-1e-9 && t<=hi+1e-9;});
    function Y(v){ return mT+ih-(v-lo)/(hi-lo)*ih; }
    var rlo=0, rhi=1, rt=[];
    if(rv.length){
      var mn=Math.min.apply(null,rv), mx=Math.max.apply(null,rv), rs=(mx-mn)||Math.abs(mx)||0.1;
      rlo=mn-rs*0.25; rhi=mx+rs*0.25; if(mn>=0 && rlo<0) rlo=0;
      rt=niceTicks(rlo,rhi,narrow?4:5); rlo=Math.min(rlo,rt[0]); rhi=Math.max(rhi,rt[rt.length-1]);
      rt=rt.filter(function(t){return t>=rlo-1e-9 && t<=rhi+1e-9;});
    }
    function YR(v){ return mT+ih-(v-rlo)/(rhi-rlo)*ih; }
    var band=iw/n; function Xc(i){ return mL+band*(i+0.5); }
    var g=[], fs=narrow?9:10, mono='font-family="ui-monospace,monospace"';

    rows.forEach(function(r,i){ if(r.fc)
      g.push('<rect x="'+(mL+band*i).toFixed(1)+'" y="'+mT+'" width="'+band.toFixed(1)+'" height="'+ih+'" fill="'+css("--band")+'"/>'); });
    lt.forEach(function(t){
      var y=Y(t).toFixed(1);
      g.push('<line x1="'+mL+'" x2="'+(mL+iw)+'" y1="'+y+'" y2="'+y+'" stroke="'+css("--grid")+'" stroke-width="1"/>');
      g.push('<text x="'+(mL-6)+'" y="'+y+'" text-anchor="end" dominant-baseline="middle" font-size="'+fs+'" '+mono+' fill="'+css("--ink-3")+'">'+cfg.yl(t,lt)+'</text>');
    });
    rt.forEach(function(t){
      g.push('<text x="'+(mL+iw+6)+'" y="'+YR(t).toFixed(1)+'" text-anchor="start" dominant-baseline="middle" font-size="'+fs+'" '+mono+' fill="'+css("--ink-3")+'">'+cfg.yr(t,rt)+'</text>');
    });
    for(var k=1;k<n;k++){ var vx=(mL+band*k).toFixed(1);
      g.push('<line x1="'+vx+'" x2="'+vx+'" y1="'+mT+'" y2="'+(mT+ih)+'" stroke="'+css("--grid")+'" stroke-width="1" opacity=".6"/>'); }
    var every=Math.max(1,Math.ceil(n/(narrow?5:10)));
    rows.forEach(function(r,i){
      if(i%every!==0 && i!==n-1) return;
      g.push('<text x="'+Xc(i).toFixed(1)+'" y="'+(mT+ih+15)+'" text-anchor="middle" font-size="'+fs+'" '+mono+' fill="'+css(r.fc?"--ink-2":"--ink-3")+'">'+cfg.xtick(r)+'</text>');
    });

    var nb=bars.length, gw=band*(nb>2?0.84:0.6), slot=nb?gw/nb:0;
    bars.forEach(function(s,si){
      var col=css(s.color);
      rows.forEach(function(r,i){
        var v=r[s.key]; if(v==null) return;
        var y0=Y(Math.max(0,v)), y1=Y(Math.min(0,v));
        var x=mL+band*i+(band-gw)/2+slot*si+slot*0.07, w=Math.max(1.5,slot*0.86);
        g.push('<rect x="'+x.toFixed(1)+'" y="'+y0.toFixed(1)+'" width="'+w.toFixed(1)+'" height="'+Math.max(1,Math.abs(y1-y0)).toFixed(1)+'" fill="'+col+'"'
          +(r.fc?' fill-opacity=".42" stroke="'+col+'" stroke-width="1" stroke-dasharray="3 2"':'')+'/>');
      });
    });
    g.push('<line x1="'+mL+'" x2="'+(mL+iw)+'" y1="'+Y(0).toFixed(1)+'" y2="'+Y(0).toFixed(1)+'" stroke="'+css("--rule-s")+'" stroke-width="1"/>');

    lines.forEach(function(s){
      var col=css(s.color), dot=css(s.dot||s.color), YY=s.axis==="R"?YR:Y, seg=[], parts=[];
      rows.forEach(function(r,i){
        if(r[s.key]==null){ if(seg.length){parts.push(seg); seg=[];} return; }
        seg.push([Xc(i),YY(r[s.key]),r]);
      });
      if(seg.length) parts.push(seg);
      parts.forEach(function(p){
        if(p.length>1) g.push('<path d="'+smoothD(p)+'" fill="none" stroke="'+col+'" stroke-width="'+(s.w||2.5)+'" stroke-linecap="round"/>');
      });
      parts.forEach(function(p){ p.forEach(function(q){
        g.push(q[2].fc
          ? '<circle cx="'+q[0].toFixed(1)+'" cy="'+q[1].toFixed(1)+'" r="3.4" fill="'+css("--surface")+'" stroke="'+dot+'" stroke-width="2"/>'
          : '<circle cx="'+q[0].toFixed(1)+'" cy="'+q[1].toFixed(1)+'" r="3.4" fill="'+dot+'" stroke="'+css("--surface")+'" stroke-width="1"/>');
      }); });
    });
    g.push('<line id="xh" x1="0" x2="0" y1="'+mT+'" y2="'+(mT+ih)+'" stroke="'+css("--rule-s")+'" stroke-width="1" opacity="0"/>');

    wrap.querySelectorAll("svg").forEach(function(s){s.remove();});
    wrap.insertAdjacentHTML("afterbegin",
      '<svg viewBox="0 0 '+W+' '+H+'" width="'+W+'" height="'+H+'" role="img" aria-label="'+cfg.aria+'">'+g.join("")+'</svg>');

    var el=wrap.querySelector("svg"), xh=el.querySelector("#xh");
    if(!cfg.zoomed) kbZoomable(el, host, function(body,BH){
      var ph=document.createElement("div"); body.appendChild(ph);
      Combo(ph, Object.assign({}, cfg, {height:Math.round(BH*0.7), zoomed:true}));
      kbTable(body, cfg, rows, bars, lines);          // 拡大表示では表でも見られる
    });
    function move(ev){
      var rect=el.getBoundingClientRect();
      var x=(ev.touches?ev.touches[0].clientX:ev.clientX)-rect.left;
      var i=Math.max(0,Math.min(n-1,Math.floor((x-mL)/band))), r=rows[i];
      xh.setAttribute("x1",Xc(i).toFixed(1)); xh.setAttribute("x2",Xc(i).toFixed(1)); xh.setAttribute("opacity","0.8");
      tip.innerHTML='<h4>'+cfg.tipTitle(r)+'</h4>'
        +bars.map(function(s){ return '<div class="row"><i><span class="sw" style="background:'+css(s.color)+'"></span>'+s.name+'</i><b>'+cfg.tipL(r[s.key],r,s)+'</b></div>'; }).join("")
        +lines.map(function(s){ return '<div class="row"><i><span class="sw ln" style="background:'+css(s.dot||s.color)+'"></span>'+s.name+'</i><b>'+(s.axis==="R"?cfg.tipR:cfg.tipL)(r[s.key],r,s)+'</b></div>'; }).join("");
      tip.style.opacity="1";
      tip.style.left=Math.max(2,Math.min(W-tip.offsetWidth-2,Xc(i)-tip.offsetWidth/2))+"px";
      tip.style.top="4px";
    }
    function leave(){ tip.style.opacity="0"; xh.setAttribute("opacity","0"); }
    el.addEventListener("mousemove",move); el.addEventListener("mouseleave",leave);
    el.addEventListener("touchstart",move,{passive:true});
    el.addEventListener("touchmove",move,{passive:true});
    el.addEventListener("touchend",leave);
  }
  cfg.redraw=draw;   // 高さ（cfg.height）を変えたあとに描き直すため（株式分析ダッシュボードの2列表示で使う）
  new ResizeObserver(draw).observe(wrap);
  return {redraw:draw};
}


/* ---------- 株主構成の円グラフ ----------
   S = {asof, issued, treasury, holders:[[名称, 株式数, 割合(自己株除く)], ...]}（fetch_shareholders.py の出力）
   発行済株式数に対する割合で、上位10名・自己株式・その他（浮動株など）に分ける。 */
function holderSlices(S){
  // 色はこの関数の中に置く（1画面では本ファイルが末尾に連結され、先に呼ばれるため）
  var KB_PIE=["#5a78a6","#a9cbe6","#e5944a","#f4c290","#67a05a","#9ccf86","#b49c45","#e8d47c","#5e9790","#98c0b9"];
  var out=[], iss=S.issued, tr=S.treasury>0?S.treasury:0, used=0;
  var adj=(iss&&tr)?(iss-tr)/iss:1;      // 大株主の「割合」は自己株を除いた株数が分母
  (S.holders||[]).forEach(function(h,i){
    var p=(iss&&h[1]!=null)? h[1]/iss : (h[2]!=null? h[2]*adj : null);
    if(p==null||!(p>0)) return;
    out.push({name:h[0],p:p,shares:h[1],color:KB_PIE[i%KB_PIE.length]}); used+=p;
  });
  if(iss&&tr){ out.push({name:"自己株式",p:tr/iss,shares:tr,color:"#c9625d"}); used+=tr/iss; }
  if(used>1){ out.forEach(function(o){o.p/=used;}); used=1; }
  if(1-used>0.0005) out.push({name:"その他（浮動株など）",p:1-used,color:"#f0a7a1",other:true});
  return out;
}
/* 拡大表示の下に出す表（行＝期、列＝グラフの各項目。値の書式はツールチップと同じ） */
function kbTable(host, cfg, rows, bars, lines){
  var cols=bars.map(function(s){return [s,cfg.tipL];}).concat(lines.map(function(s){return [s,s.axis==="R"?cfg.tipR:cfg.tipL];}));
  if(!rows.length||!cols.length) return;
  var bd='1px solid '+css("--rule"), th='padding:6px 10px;text-align:right;white-space:nowrap;font-weight:600;color:'+css("--ink-2")+';border-bottom:'+bd;
  var h='<div class="kbtbl" style="overflow-x:auto;margin-top:10px"><table style="border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums">'
    +'<thead><tr><th style="'+th+';text-align:left">'+(cfg.tblHead||'決算期')+'</th>'
    +cols.map(function(c){return '<th style="'+th+'"><span style="display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:5px;background:'+css(c[0].dot||c[0].color)+'"></span>'+c[0].name+'</th>';}).join("")
    +'</tr></thead><tbody>';
  rows.slice().reverse().forEach(function(r){
    h+='<tr'+(r.fc?' style="color:'+css("--ink-2")+';font-style:italic"':'')+'><td style="padding:5px 10px;white-space:nowrap;border-bottom:'+bd+'">'+cfg.tipTitle(r)+'</td>'
      +cols.map(function(c){return '<td style="padding:5px 10px;text-align:right;white-space:nowrap;border-bottom:'+bd+'">'+c[1](r[c[0].key],r,c[0])+'</td>';}).join("")+'</tr>';
  });
  host.insertAdjacentHTML("beforeend", h+'</tbody></table></div>');
}

function kbPie(host, S, opt){
  opt=opt||{};
  var sl=(S&&S.holders&&S.holders.length)?holderSlices(S):[];
  if(!sl.length){ host.insertAdjacentHTML("beforeend",'<div class="kbempty">株主データなし（有価証券報告書が未取得）</div>'); return; }
  var R=100, cx=110, cy=110, a=-Math.PI/2, g=[], sur=css(opt.surface||"--surface")||"#fff";
  function pt(r,t){ return (cx+r*Math.cos(t)).toFixed(2)+" "+(cy+r*Math.sin(t)).toFixed(2); }
  sl.forEach(function(o){ o.name=String(o.name).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];}); });
  sl.forEach(function(o){
    var b=a+o.p*2*Math.PI, big=(b-a)>Math.PI?1:0, tt=o.name+"："+(o.p*100).toFixed(2)+"%";
    if(o.p>=0.9999) g.push('<circle cx="'+cx+'" cy="'+cy+'" r="'+R+'" fill="'+o.color+'"><title>'+tt+'</title></circle>');
    else g.push('<path d="M'+cx+' '+cy+' L'+pt(R,a)+' A'+R+' '+R+' 0 '+big+' 1 '+pt(R,b)+' Z" fill="'+o.color+'" stroke="'+sur+'" stroke-width="1.5"><title>'+tt+'</title></path>');
    if(o.p>=0.045){ var m=(a+b)/2;
      g.push('<text x="'+(cx+R*0.64*Math.cos(m)).toFixed(1)+'" y="'+(cy+R*0.64*Math.sin(m)).toFixed(1)+'" text-anchor="middle" dominant-baseline="middle" font-size="11" font-weight="700" fill="#fff" style="paint-order:stroke" stroke="rgba(0,0,0,.25)" stroke-width="2">'+(o.p*100).toFixed(o.p>=0.1?0:1)+'%</text>'); }
    a=b;
  });
  var fmtSh=function(v){ return v==null?"":(v>=1e8?(v/1e8).toFixed(2)+"億株":v>=1e4?Math.round(v/1e4).toLocaleString()+"万株":Math.round(v).toLocaleString()+"株"); };
  host.insertAdjacentHTML("beforeend",'<div class="kbpie"><svg viewBox="0 0 220 220" role="img" aria-label="株主構成">'+g.join("")+'</svg>'
    +'<ol class="kbleg">'+sl.map(function(o){
      return '<li'+(o.other?' class="oth"':'')+'><i style="background:'+o.color+'"></i><span class="nm" title="'+o.name+'">'+o.name+'</span>'
        +'<span class="sh">'+fmtSh(o.shares)+'</span><span class="pc">'+(o.p*100).toFixed(2)+'%</span></li>';}).join("")+'</ol></div>');
  if(!opt.zoomed){ var pies=host.querySelectorAll(".kbpie svg");
    kbZoomable(pies[pies.length-1], host, function(body){ kbPie(body, S, Object.assign({}, opt, {zoomed:true})); }); }
}

/* ---------- 貸借対照表（資産と負債・純資産の積み上げ棒を期ごとに並べる） ----------
   rows = [{fy, fyEnd, ta, cash, recv, inv, oca, ppe, onca, pay, ocl, ncl, oeq, eq, noCA}]（百万円）
   計上額／構成比はグラフ右上の切り替えで。色は --b-* （現金預金はキャッシュフローの「現預金等」と同じ色） */
function kbBSA(){ return [["onca","その他固定資産","--b-onca"],["ppe","有形固定資産","--b-ppe"],["oca","その他流動資産","--b-oca"],
             ["inv","棚卸資産","--b-inv"],["recv","売上債権","--b-recv"],["cash","現金預金","--b-cash"]]; }
function kbBSL(){ return [["eq","自己資本","--b-eq"],["oeq","非支配株主持分等","--b-oeq"],["ncl","固定負債","--b-ncl"],
             ["ocl","その他流動負債","--b-ocl"],["pay","買入債務","--b-pay"]]; }
function kbMoney(v){ if(v==null) return "—"; var a=Math.abs(v);
  return a>=1e6? (v/1e6).toFixed(2)+"兆円" : a>=100? Math.round(v/100).toLocaleString()+"億円" : Math.round(v).toLocaleString()+"百万円"; }
function kbDec(st){ /* 目盛り間隔に必要な小数桁（0.25 → 2） */
  for(var d=0; d<3; d++){ var x=st*Math.pow(10,d); if(Math.abs(x-Math.round(x))<1e-6) return d; } return 2; }
function kbInk(hex){ var m=/^#?([0-9a-f]{6})$/i.exec(String(hex).trim()); if(!m) return "#1d1d1b";
  var n=parseInt(m[1],16), r=n>>16&255, g=n>>8&255, b=n&255; return (0.299*r+0.587*g+0.114*b)>150?"#1d1d1b":"#ffffff"; }
function kbBS(host, rows, opt){
  opt=opt||{};
  var KB_BS_A=kbBSA(), KB_BS_L=kbBSL();  // 関数内で作る（1画面では本ファイルが末尾に連結されるため）
  if(!rows||!rows.length){ host.insertAdjacentHTML("beforeend",'<div class="kbempty">貸借対照表のデータなし（有価証券報告書が未取得）</div>'); return; }
  var mode=opt.mode||"amt";
  var bar=document.createElement("div"); bar.className="kbseg";
  bar.innerHTML='<button type="button" data-m="amt">計上額</button><button type="button" data-m="pct">構成比</button>';
  var leg=document.createElement("div"); leg.className="kblegend";
  leg.innerHTML=KB_BS_A.slice().reverse().concat(KB_BS_L.slice().reverse())
    .filter(function(s){ return rows.some(function(r){ return r[s[0]]>0; }); })   // 数値の無い区分（銀行の売上債権など）は凡例から外す
    .map(function(s){
    return '<span><i style="background:'+css(s[2])+'"></i>'+s[1]+'</span>';}).join("")
    +(rows.some(function(r){ return r.na!=null && r.na<0; })
      ? '<span><i style="background:transparent;border:1.5px dashed '+css("--bad")+'"></i>債務超過（負債が資産を上回る分）</span>' : "");
  var wrap=document.createElement("div"); wrap.className="kbplot";
  var tip=document.createElement("div"); tip.className="kbtip";
  var head=host.querySelector(".p-head,.fh");     // 見出しの右端に切り替えを置く
  if(head) head.appendChild(bar); else host.appendChild(bar);
  host.appendChild(leg); host.appendChild(wrap); wrap.appendChild(tip);
  function setMode(m){ mode=m; bar.querySelectorAll("button").forEach(function(b){ b.setAttribute("aria-pressed", String(b.dataset.m===m)); }); draw(); }
  bar.querySelectorAll("button").forEach(function(b){ b.addEventListener("click",function(){ setMode(b.dataset.m); }); });
  function val(r,k){ var v=r[k]; return v==null||v<0?0:v; }
  function draw(){
    var W=wrap.clientWidth||460; if(W<40) return;
    var narrow=W<460, H=opt.height||(narrow?260:330), mL=narrow?40:52, mR=8, mT=18, mB=36;
    var n=rows.length, iw=W-mL-mR, ih=H-mT-mB, band=iw/n;
    function lTot(r){ return (r.na!=null && r.na<0) ? (r.tl||0) : (r.tl||0)+(r.na||0); }   // 債務超過なら負債合計まで積む
    var hi=mode==="pct"?1:Math.max.apply(null,rows.map(function(r){return Math.max(r.ta||0,lTot(r));}))*1.06;
    var tk=niceTicks(0,hi,narrow?4:5); hi=Math.max(hi,tk[tk.length-1]);
    function Y(v){ return mT+ih-v/hi*ih; }
    var st=tk.length>1?tk[1]-tk[0]:1, g=[], fs=narrow?9:10, mono='font-family="ui-monospace,monospace"';
    tk.forEach(function(t){ var y=Y(t).toFixed(1);
      var lab=mode==="pct"? Math.round(t*100)+"%" : (hi>=1e6? (t/1e6).toFixed(kbDec(st/1e6))+(t?"兆":"") : (t/100).toFixed(kbDec(st/100)));
      g.push('<line x1="'+mL+'" x2="'+(mL+iw)+'" y1="'+y+'" y2="'+y+'" stroke="'+css(t===0?"--rule-s":"--grid")+'"/>');
      g.push('<text x="'+(mL-6)+'" y="'+y+'" text-anchor="end" dominant-baseline="middle" font-size="'+fs+'" '+mono+' fill="'+css("--ink-3")+'">'+lab+'</text>'); });
    var bw=Math.min(band*0.4, 92);
    rows.forEach(function(r,i){
      var cx=mL+band*(i+0.5), xs=[cx-bw-1, cx+1];
      [[KB_BS_A, r.ta],[KB_BS_L, lTot(r)]].forEach(function(side,si){
        var tot=side[1]||0, acc=0, x=xs[si];
        if(!tot) return;
        side[0].forEach(function(s){
          var v=val(r,s[0]); if(!v) return;
          var p=mode==="pct"? v/tot : v, y0=Y(acc), y1=Y(acc+p), col=css(s[2]); acc+=p;
          g.push('<rect x="'+x.toFixed(1)+'" y="'+y1.toFixed(1)+'" width="'+bw.toFixed(1)+'" height="'+Math.max(0.5,y0-y1).toFixed(1)+'" fill="'+col+'" stroke="'+css("--surface")+'" stroke-width=".6"/>');
          var nm=(r.noCA&&s[0]==="onca")?"その他資産":(r.noCA&&s[0]==="ncl")?"負債":s[1];
          var negTop=(si===1 && r.na!=null && r.na<0 && r.ta && tot>r.ta)? Y(mode==="pct"? r.ta/tot : r.ta) : null;
          if(y0-y1>=15 && bw>=40 && !(negTop!=null && (y0+y1)/2<negTop+8)){   // 債務超過の枠と重なる区分名は出さない
            var fz=Math.min(11, bw/Math.max(4,nm.length)*1.05);
            g.push('<text x="'+(x+bw/2).toFixed(1)+'" y="'+((y0+y1)/2).toFixed(1)+'" text-anchor="middle" dominant-baseline="middle" font-size="'+fz.toFixed(1)+'" font-weight="600" fill="'+kbInk(col)+'">'+nm+'</text>');
          }
        });
        if(si===1 && r.na!=null && r.na<0 && r.ta && tot>r.ta){   // 債務超過：資産を上回る負債の部分に破線の枠
          var yA=Y(mode==="pct"? r.ta/tot : r.ta), yT=Y(acc), bad=css("--bad");
          g.push('<rect x="'+x.toFixed(1)+'" y="'+yT.toFixed(1)+'" width="'+bw.toFixed(1)+'" height="'+Math.max(0.5,yA-yT).toFixed(1)+'" fill="'+bad+'" fill-opacity=".22" stroke="'+bad+'" stroke-width="1.5" stroke-dasharray="4 3"/>');
          if(yA-yT>=14 && bw>=34) g.push('<text x="'+(x+bw/2).toFixed(1)+'" y="'+((yA+yT)/2).toFixed(1)+'" text-anchor="middle" dominant-baseline="middle" font-size="'+Math.min(11,bw/4.2).toFixed(1)+'" font-weight="700" fill="'+bad+'">債務超過</text>');
        }
        if(mode==="amt" && si===0) g.push('<text x="'+cx.toFixed(1)+'" y="'+(Math.min(Y(acc),Y(lTot(r)))-5).toFixed(1)+'" text-anchor="middle" font-size="'+(narrow?8.5:9.5)+'" '+mono+' fill="'+css("--ink-2")+'">'+kbMoney(tot).replace("円","")+'</text>');
        g.push('<text x="'+(x+bw/2).toFixed(1)+'" y="'+(mT+ih+12)+'" text-anchor="middle" font-size="'+(narrow?8.5:9.5)+'" fill="'+css("--ink-3")+'">'+(si?(narrow?"負・純":"負債・純資産"):"資産")+'</text>');
      });
      g.push('<text x="'+cx.toFixed(1)+'" y="'+(mT+ih+28)+'" text-anchor="middle" font-size="'+fs+'" font-weight="700" '+mono+' fill="'+css("--ink-2")+'">'+r.fy+'</text>');
    });
    wrap.querySelectorAll("svg").forEach(function(s){s.remove();});
    wrap.insertAdjacentHTML("afterbegin",'<svg viewBox="0 0 '+W+' '+H+'" width="'+W+'" height="'+H+'" role="img" aria-label="貸借対照表">'+g.join("")+'</svg>');
    var el=wrap.querySelector("svg");
    if(!opt.zoomed) kbZoomable(el, host, function(body,BH){ kbBS(body, rows, {height:BH, mode:mode, zoomed:true}); }, true);
    function move(ev){
      var rect=el.getBoundingClientRect(), x=(ev.touches?ev.touches[0].clientX:ev.clientX)-rect.left;
      var i=Math.max(0,Math.min(n-1,Math.floor((x-mL)/band))), r=rows[i];
      function line(s,tot){ var v=r[s[0]]; if(v==null||(s[0]==="oeq"&&!v)) return "";
        var nm=(s[0]==="eq"&&v<0)?"純資産（マイナス＝債務超過）":s[1];
        return '<div class="row"><i><span class="sw" style="background:'+css(s[2])+'"></span>'+nm+'</i><b>'+kbMoney(v)+(tot?'（'+(v/tot*100).toFixed(1)+'%）':'')+'</b></div>'; }
      tip.innerHTML='<h4>'+r.fy+'（'+r.fyEnd+'）・総資産 '+kbMoney(r.ta)+'</h4>'
        +KB_BS_A.slice().reverse().map(function(s){return line(s,r.ta);}).join("")
        +'<div style="height:5px"></div>'+KB_BS_L.slice().reverse().map(function(s){return line(s,r.ta);}).join("");
      tip.style.opacity="1";
      var cx=mL+band*(i+0.5); tip.style.left=Math.max(2,Math.min(W-tip.offsetWidth-2,cx-tip.offsetWidth/2))+"px"; tip.style.top="4px";
    }
    function leave(){ tip.style.opacity="0"; }
    el.addEventListener("mousemove",move); el.addEventListener("mouseleave",leave);
    el.addEventListener("touchstart",move,{passive:true}); el.addEventListener("touchend",leave);
  }
  opt.redraw=draw;   // 高さ（opt.height）を変えたあとに描き直すため（株式分析ダッシュボードの2列表示で使う）
  new ResizeObserver(draw).observe(wrap);
  setMode(mode);
}

/* ---------- タップ（クリック）で拡大表示 ----------
   各グラフの svg に付ける。拡大画面には元のパネルの見出し・凡例を複製し、同じデータで大きく描き直す。
   閉じる：×ボタン・背景のタップ・Escキー。 */
function kbZoomable(svg, host, render, keepHeadOnly){
  if(!svg) return;
  svg.classList.add("kbzoomable");
  svg.addEventListener("click", function(){
    var panel=host.closest(".panel,.fp")||host;
    kbOpenZoom(function(body,BH){
      body.appendChild(kbHeadClone(panel, keepHeadOnly));
      render(body, BH);
    });
  });
}
function kbHeadClone(panel, headOnly){
  var out=document.createElement("div");
  [].forEach.call(panel.children, function(ch){
    if(ch.hidden || ch.classList.contains("kbplot") || ch.classList.contains("kbpie") || ch.classList.contains("kbempty")
       || (ch.querySelector && ch.querySelector(".kbplot,table"))) return;
    if(headOnly && !ch.matches(".p-head,.fh")) return;            // 貸借対照表は凡例・切り替えを描き直すので見出しだけ
    var c=ch.cloneNode(true);
    c.querySelectorAll("button,.kbseg").forEach(function(b){ b.remove(); });
    out.appendChild(c);
  });
  out.className=panel.className+" kbzhead";   // 元のパネルと同じクラスにして、見出し・凡例の見た目をそろえる
  out.removeAttribute("id");
  return out;
}
function kbOpenZoom(render){
  var ov=document.createElement("div"); ov.className="kbzoom"; ov.setAttribute("role","dialog"); ov.setAttribute("aria-modal","true");
  var box=document.createElement("div"); box.className="kbzbox";
  var cl=document.createElement("button"); cl.type="button"; cl.className="kbzclose"; cl.setAttribute("aria-label","閉じる"); cl.textContent="×";
  var body=document.createElement("div"); body.className="kbzbody";
  box.appendChild(cl); box.appendChild(body); ov.appendChild(box); document.body.appendChild(ov);
  document.documentElement.classList.add("kbz-open");
  var BH=Math.round(Math.max(240, Math.min(innerHeight*0.66, 640)));
  render(body, BH);
  function done(){ ov.remove(); document.documentElement.classList.remove("kbz-open"); removeEventListener("keydown", key); }
  function key(e){ if(e.key==="Escape") done(); }
  ov.addEventListener("click", function(e){ if(e.target===ov) done(); });
  cl.addEventListener("click", done); addEventListener("keydown", key);
  try{ cl.focus({preventScroll:true}); }catch(e){}
}
