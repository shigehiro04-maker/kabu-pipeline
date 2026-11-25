#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
企業別「1画面」ダッシュボード（売買シグナル＋チャート＋ファンダメンタル）を生成する。

入力（すべて手元のデータ。通信なし・標準ライブラリのみ）
  data/prices/<コード>.csv                      日足
  data/charts/signals.html                       売買シグナル（make_signal_dashboard.py の出力）
  fundamentals/fundamentals_latest.csv           株価・PER/PBR など
  fundamentals/fundamentals_by_year.csv          通期の時系列（最大4期）
  fundamentals/analysis/スコア一覧.csv            ROE・評価・Fスコア・業種比較用
  one_screen_template.html                       画面のひな形

出力（~/株分析/dashboards/one/）
  <コード>.html                                  銘柄ごとのページ（データだけ埋め込み）
  assets/one.css, assets/one.js                  全銘柄共通の見た目と描画処理
  index.html                                     コード・銘柄名で探す入口

テクニカル指標（移動平均・ボリンジャー・RSI・MACD・一目均衡表）はページを開いたときに
ブラウザ側で日足から計算する（ファイルを小さく保つため）。

使い方
  python3 make_one_screen.py            # 全銘柄
  python3 make_one_screen.py 7203 6758  # 銘柄指定
  python3 make_one_screen.py --index    # 一覧（市場・業種で絞り込み／時価総額順）だけ作り直す
"""
import csv, json, sys, datetime, statistics, html, time
from pathlib import Path

BASE = Path(__file__).resolve().parent
FUND = BASE / "fundamentals"
OUT = Path(__import__("os").environ["ONE_OUT"]) if __import__("os").environ.get("ONE_OUT") else BASE / "dashboards" / "one"
SHOW_DAYS = 750          # 画面で最大3年分を表示
WARMUP = 210             # 200日線などの計算用に前へ足す日数
# アナリスト予想のカードを出す銘柄（None＝全銘柄。2026-11-15 全銘柄に展開。試すときは {"7203"} のように絞る）
ANALYST_ONLY = None


def num(s):
    if s is None:
        return None
    s = str(s).strip().replace(",", "")
    if s == "" or s.lower() in ("nan", "none", "-", "--", "false", "true"):
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return None if v != v else v


def read_csv(p):
    if not p.exists():
        return []
    with open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def compact(v):
    """JSON を小さくするため、整数になる値は整数で持つ。"""
    if v is None:
        return None
    r = round(v, 1)
    return int(r) if r == int(r) else r


def load_signal_rows():
    """signals.html から銘柄ごとの行と判定の区切りを読む（シグナルのページと表示をそろえる）。"""
    f = BASE / "data" / "charts" / "signals.html"
    if not f.exists():
        return {}, None
    t = f.read_text(encoding="utf-8")
    i = t.find("const D=")
    if i < 0:
        return {}, None
    j = t.index("\n", i)
    D = json.loads(t[i + 8:j].rstrip().rstrip(";"))
    meta = {k: D["meta"][k] for k in ("tw", "fw", "levels", "names") if k in D["meta"]}
    return {r["c"]: r for r in D["rows"]}, meta


def load_tables():
    T = dict(latest={r["コード"]: r for r in read_csv(FUND / "fundamentals_latest.csv")},
             score={r["コード"]: r for r in read_csv(FUND / "analysis" / "スコア一覧.csv")},
             years={})
    for r in read_csv(FUND / "fundamentals_by_year.csv"):
        T["years"].setdefault(r["コード"], []).append(r)
    T["sigrows"], T["sigmeta"] = load_signal_rows()
    # 通期・四半期・会社予想・配当・株主構成（業績ダッシュボードと同じ組み立て）
    try:
        import make_company_dashboards as mcd
        T["kb"] = mcd.load()
    except Exception as e:  # 失敗してもページは作る（グラフが「データなし」になるだけ）
        print("業績グラフ用データの読み込みに失敗:", e, file=sys.stderr)
        T["kb"] = {}
    T["tickers"] = {r["code"]: r for r in read_csv(BASE / "tickers" / "tse_tickers.csv")}
    # 需給（需給分析/analyze_jukyu.py の出力）
    T["jukyu"] = {r["コード"]: r for r in read_csv(FUND / "jukyu.csv")}
    # アナリスト予想（fetch_analyst.py の出力）
    try:
        T["analyst"] = json.loads((FUND / "analyst.json").read_text(encoding="utf-8")).get("data", {})
    except Exception:
        T["analyst"] = {}
    # 最新の決算短信（fetch_tdnet.py の出力。TDnet・発表当日の値）
    T["ks"] = {r["コード"]: r for r in read_csv(FUND / "kessan_latest.csv")} if (FUND / "kessan_latest.csv").exists() else {}
    # 理論株価（理論株価/valuation.py の出力）
    T["val"] = {r["コード"]: r for r in read_csv(FUND / "valuation.csv")}
    # 会社情報：従業員・同業他社・関連企業（make_company_links.py の出力。2026-11-18）
    try:
        T["co"] = json.loads((FUND / "company_info.json").read_text(encoding="utf-8"))
    except Exception:
        T["co"] = {}
    # 業種ごとの中央値
    by_sec = {}
    for r in T["score"].values():
        by_sec.setdefault(r.get("業種", ""), []).append(r)
    T["secmed"] = {}
    for sec, rows in by_sec.items():
        m = {}
        for k in ["PER", "PBR", "ROE(%)", "営業利益率(%)", "配当利回り(%)", "自己資本比率(%)"]:
            xs = [num(r.get(k)) for r in rows]
            xs = [x for x in xs if x is not None and 0 < x < 200]
            m[k] = statistics.median(xs) if xs else None
        T["secmed"][sec] = m
    return T


def price_on_or_before(D, C, d):
    lo = None
    for i, x in enumerate(D):
        if x <= d:
            lo = i
        else:
            break
    return C[lo] if lo is not None else None


def revenue_label(elems):
    """決算短信で使われた要素名から、売上の呼び方を決める（銀行・保険は経常収益、IFRS は売上収益 など）。"""
    if "OrdinaryRevenues" in elems:
        return "経常収益"
    if "OperatingRevenues" in elems:
        return "営業収益"
    if "RevenueIFRS" in elems or "RevenuesIFRS" in elems:
        return "売上収益"
    return "売上高"


def co_block(code, T):
    """会社情報（従業員・同業他社・関連企業）。比べる行は [コード, 銘柄名, 時価総額(億), PER, PBR, ROE, 営業利益率, 配当利回り, 平均年収]"""
    ci = T.get("co", {}).get(code)
    if not ci:
        return None
    us = BASE.name == "米国株分析"

    def mc(c):
        lt, sc = T["latest"].get(c, {}), T["score"].get(c, {})
        if us:
            v = num(lt.get("時価総額"))
            return v / 1e8 if v else None
        return num(sc.get("時価総額(億円)"))

    def nm(c):
        lt, sc = T["latest"].get(c, {}), T["score"].get(c, {})
        return lt.get("銘柄名") or sc.get("銘柄名") or T["tickers"].get(c, {}).get("name") or c

    def ok(c):
        return c in T["latest"] or c in T["score"]

    def row(c):
        lt, sc = T["latest"].get(c, {}), T["score"].get(c, {})
        e = (T["co"].get(c) or {}).get("emp") or {}
        return [c, nm(c), compact(mc(c)), compact(num(lt.get("PER"))), (round(num(lt.get("PBR")), 2) if num(lt.get("PBR")) is not None else None), compact(num(sc.get("ROE(%)"))),
                compact(num(sc.get("営業利益率(%)"))), compact(num(sc.get("配当利回り(%)"))), e.get("salary")]
    peers = [row(c) for c in ci.get("peers") or [] if ok(c)]
    return dict(cur="ドル" if us else "円", ind=ci.get("ind"), emp=ci.get("emp") or {},
                peers=[row(code)] + peers if peers else [],
                rel=[[c, nm(c), k, r] for c, k, r in ci.get("rel") or [] if ok(c)],
                rec=[[c, nm(c)] for c in ci.get("rec") or [] if ok(c)])


def build(code, T):
    prows = [r for r in read_csv(BASE / "data" / "prices" / f"{code}.csv") if num(r.get("close")) is not None]
    if len(prows) < 2:
        return None
    D = [r["date"] for r in prows]
    C = [num(r["close"]) for r in prows]
    keep = prows[-(SHOW_DAYS + WARMUP):]
    px = dict(show=SHOW_DAYS,
              d=[r["date"] for r in keep],
              o=[compact(num(r["open"]) or num(r["close"])) for r in keep],
              h=[compact(num(r["high"]) or num(r["close"])) for r in keep],
              l=[compact(num(r["low"]) or num(r["close"])) for r in keep],
              c=[compact(num(r["close"])) for r in keep],
              v=[int(num(r["volume"]) or 0) for r in keep])

    lt, sc = T["latest"].get(code, {}), T["score"].get(code, {})
    sr, tk = T["sigrows"].get(code) or {}, T["tickers"].get(code, {})
    sector = lt.get("業種") or sc.get("業種") or sr.get("s") or ""
    sec = T["secmed"].get(sector, {})
    per, pbr = num(lt.get("PER")), num(lt.get("PBR"))
    years = sorted(T["years"].get(code, []), key=lambda r: r["決算期"])
    fy = []
    for y in years:
        p = price_on_or_before(D, C, y["決算期"])
        e, b = num(y.get("EPS")), num(y.get("BPS"))
        ni, eq = num(y.get("当期純利益")), num(y.get("自己資本"))
        fy.append(dict(fy=y["決算期"][:7], sales=num(y.get("売上高")), op=num(y.get("営業利益")), ni=ni,
                       opm=num(y.get("営業利益率(%)")), ocf=num(y.get("営業CF")), fcf=num(y.get("フリーCF")),
                       eqr=num(y.get("自己資本比率(%)")), roe=(ni / eq * 100) if ni is not None and eq else None,
                       per=round(p / e, 1) if p and e and e > 0 else None))

    n = len(C) - 1
    chg = C[n] - C[n - 1]
    info = dict(code=code, name=lt.get("銘柄名") or sc.get("銘柄名") or sr.get("n") or tk.get("name") or code,
                market=lt.get("市場") or sc.get("市場") or sr.get("m") or tk.get("market") or "",
                sector=sector, date=D[n], price=C[n], chg=chg, chgp=chg / C[n - 1] * 100 if C[n - 1] else 0,
                biz=sc.get("事業概要", ""), url=(sc.get("会社URL") or "").strip(), fdate=lt.get("決算期") or sc.get("決算期") or "")
    extra = dict(mcap=num(sc.get("時価総額(億円)")), ev_ebitda=num(sc.get("EV/EBITDA")), fscore=num(sc.get("Fスコア")),
                 payout=num(sc.get("配当性向(%)")), beta=num(sc.get("ベータ")), cagr=num(sc.get("売上高CAGR(%)")),
                 dy=num(sc.get("配当利回り(%)")), roe=num(sc.get("ROE(%)")), opm=num(sc.get("営業利益率(%)")),
                 eqr=num(sc.get("自己資本比率(%)")), per=per, pbr=pbr,
                 sec_per=sec.get("PER"), sec_pbr=sec.get("PBR"), sec_roe=sec.get("ROE(%)"),
                 sec_opm=sec.get("営業利益率(%)"), sec_eqr=sec.get("自己資本比率(%)"),
                 rank=sc.get("業種内順位", ""), nsec=sc.get("業種内銘柄数", ""))
    j = T["jukyu"].get(code)
    jk = None
    if j:
        jk = {k: num(j.get(c)) for k, c in (
            ("score", "需給スコア"), ("ratio", "信用倍率(倍)"), ("buy", "信用買残(株)"), ("sell", "信用売残(株)"),
            ("dbuy", "買残前日比(株)"), ("dsell", "売残前日比(株)"), ("days", "買残回転日数(日)"),
            ("pl", "信用買い評価損益率(%)"), ("lend", "貸借倍率(倍)"), ("short", "大口空売り比率(%)"))}
        jk.update(judge=j.get("需給判定", ""), memo=j.get("需給メモ", ""), asof=j.get("信用残の申込日", ""),
                  flag=j.get("規制等", ""), kind=j.get("信用区分", ""))
    v = T["val"].get(code)
    vl = None
    if v and num(v.get("理論株価(ファンダ)")) is not None:
        vl = {k: compact(num(v.get(c))) for k, c in (
            ("f", "理論株価(ファンダ)"), ("mean", "理論株価_平均値"), ("mode", "理論株価_最頻値"),
            ("sd", "理論株価_標準偏差"), ("cv", "変動係数(%)"), ("va", "理論株価(需給・心理込み)"),
            ("lo", "手法の最小"), ("f0", "理論株価(引き下げ前)"), ("hi", "手法の最大"), ("nm", "有効手法数"), ("px", "株価"),
            ("per", "PER法"), ("pbr", "PBR法"), ("dcf", "DCF法"), ("ddm", "DDM"),
            ("h", "はっしゃん式"), ("rim", "RIM"), ("tk", "東洋経済式"))}
        vl.update(adj=str(v.get("引き下げ", "")).lower() == "true", adju=str(v.get("引き上げ", "")).lower() == "true", rel=v.get("信頼度", ""), note=v.get("注意", ""), asof=v.get("基準日", ""))
    kc = T["kb"].get(code)
    kb = None
    if kc:
        KEYS = ("fy", "fyEnd", "fc", "disc", "rev", "op", "odp", "ni", "opm", "ocf", "icf", "fcf", "cash", "frcf",
                "dps", "payout", "eps")
        kb = dict(annual=[{k: a.get(k) for k in KEYS} for a in kc["annual"]],
                  fc=kc.get("fc"), quarters=kc.get("quarters") or [], odpName=kc.get("odpName"),
                  holders=kc.get("holders"), bs=kc.get("bs") or [])
    # チャート形状（チャート形状検索・個別チャートと同じ計算）
    shape = None
    try:
        import numpy as np
        from make_pattern_page import classify, NAMES
        cs = np.array([c for c in C if c and c > 0], dtype=float)
        sh = classify(cs)
        if sh:
            shape = dict(r=sh[0], k=sh[1], name=NAMES[sh[0]][sh[1]], s=round(sh[2], 1), q=round(sh[3], 1))
    except Exception:
        shape = None
    an = T.get("analyst", {}).get(code)
    if an and (ANALYST_ONLY is None or code in ANALYST_ONLY):
        an = {k: v for k, v in an.items() if k != "px"}
        an["ud"] = (an.get("ud") or [])[:20]
        an["pc"] = "JPY"
    else:
        an = None
    ks = None
    k = T.get("ks", {}).get(code)
    if k and k.get("期間末"):
        g = lambda c: num(k.get(c))
        ks = dict(d=k["開示日"], t=k.get("時刻", ""), fye=k.get("決算期末", ""), q=int(num(k.get("四半期")) or 4),
                  pe=k["期間末"], std=k.get("会計基準", ""), cons=k.get("連結", ""), fix=k.get("訂正", ""),
                  rev=g("売上高"), revy=g("売上高_前年比(%)"), op=g("営業利益"), opy=g("営業利益_前年比(%)"),
                  odp=g("経常利益"), odpy=g("経常利益_前年比(%)"), pbt=g("税引前利益"), pbty=g("税引前利益_前年比(%)"),
                  ni=g("純利益"), niy=g("純利益_前年比(%)"), eps=g("EPS"),
                  frev=g("予想_売上高"), fop=g("予想_営業利益"), fodp=g("予想_経常利益"), fpbt=g("予想_税引前利益"),
                  fni=g("予想_純利益"), fdps=g("予想_年間配当"), fdate=k.get("予想修正日", ""),
                  rl=revenue_label(k.get("要素", "")))
    return dict(info=info, px=px, fy=fy, extra=extra, kb=kb, ks=ks, srow=T["sigrows"].get(code), smeta=T["sigmeta"], jk=jk, val=vl, shape=shape, an=an, co=co_block(code, T),
                gen=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))


def split_template():
    """ひな形から共通の CSS / JS を取り出し、ページ本体のひな形を返す。"""
    t = (BASE / "one_screen_template.html").read_text(encoding="utf-8")
    s0 = t.index("<style>"); s1 = t.index("</style>") + len("</style>")
    css = t[s0 + 7:s1 - 8]
    marker = "const DATA=/*__DATA__*/null;"
    j0 = t.index("<script>\n" + marker); j1 = t.index("</script>", j0) + len("</script>")
    js = t[j0 + len("<script>\n" + marker):j1 - len("</script>")]
    # 共通の CSS・JS は版番号を付けて読む（ブラウザに古い版が残らないように。2026-11-18）
    ver = datetime.datetime.now().strftime("%Y%m%d%H%M")
    page = (t[:s0] + f'<link rel="stylesheet" href="assets/one.css?v={ver}">' + t[s1:j0]
            + f"<script>const DATA=__DATA__;</script>\n<script src=\"assets/one.js?v={ver}\"></script>" + t[j1:])
    (OUT / "assets").mkdir(parents=True, exist_ok=True)
    (OUT / "assets" / "one.css").write_text(css, encoding="utf-8")
    # 株探風の複合グラフ・株主構成の円グラフ（業績ダッシュボードと共通の部品）
    js += "\n" + (BASE / "kb_charts.js").read_text(encoding="utf-8")
    (OUT / "assets" / "one.js").write_text(js, encoding="utf-8")
    # 監視銘柄の判定（トップ画面と共通。トップ画面は one/assets/watch.js を読む）
    (OUT / "assets" / "watch.js").write_text((BASE / "watch_common.js").read_text(encoding="utf-8"), encoding="utf-8")
    return page


def write_index(rows):
    """銘柄一覧。rows = [コード, 銘柄名, 市場, 業種, 時価総額(億円)]。
    検索欄に加えて、市場・業種での絞り込みと、時価総額・コード順の並べ替えができる。"""
    items = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    page = f"""<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>株式分析ダッシュボード | 銘柄一覧</title><link rel="stylesheet" href="assets/one.css">
<style>.wrap{{max-width:900px}}
#q,.flt select{{font:inherit;border:1px solid var(--line);border-radius:10px;background:var(--card);color:var(--fg)}}
#q{{width:100%;font-size:15px;padding:10px 12px;margin:8px 0 8px}}
.flt{{display:grid;grid-template-columns:1fr 1.4fr 1.2fr auto;gap:8px;align-items:center;margin:0 0 8px}}
.flt select{{font-size:13.5px;padding:7px 8px;min-width:0;width:100%}}
.flt button{{font:inherit;font-size:12.5px;border:1px solid var(--line);background:var(--card);color:var(--fg2);border-radius:10px;padding:7px 10px;cursor:pointer;white-space:nowrap}}
.cnt{{font-size:12px;color:var(--mut);margin:0 2px 6px}}
.list a{{display:grid;grid-template-columns:56px 1fr auto auto;gap:10px;align-items:baseline;padding:7px 10px;border-bottom:1px solid var(--line);color:var(--fg);text-decoration:none}}
.list a:hover{{background:var(--neubg)}}.list small{{color:var(--mut)}}
.list .mc{{font-variant-numeric:tabular-nums;color:var(--fg2);font-size:13px;text-align:right;min-width:72px}}
.list .nm{{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
#more{{display:block;width:100%;margin:8px 0;font:inherit;font-size:13px;padding:8px;border:1px solid var(--line);border-radius:10px;background:var(--card);color:var(--fg2);cursor:pointer}}
@media (max-width:600px){{.flt{{grid-template-columns:1fr 1fr}}.flt .srt{{grid-column:1/2}}
.list a{{grid-template-columns:48px 1fr auto;row-gap:0}}.list a small{{grid-column:2/3}}.list .mc{{grid-row:1;grid-column:3/4}}}}</style></head>
<body><div class="wrap"><header><h1><a href="../index.html" title="トップへ" style="text-decoration:none;color:inherit;margin-right:8px">‹</a>株式分析ダッシュボード</h1><span class="meta">{len(rows):,}銘柄 ・ 生成 {datetime.datetime.now():%Y-%m-%d %H:%M}</span></header>
<input id="q" type="search" placeholder="コード・銘柄名で検索（例: 7203、トヨタ）" autocomplete="off" autofocus>
<div class="flt"><select id="fm" aria-label="市場"></select><select id="fs" aria-label="業種"></select>
<select id="so" class="srt" aria-label="並び順"><option value="mcap">時価総額が大きい順</option><option value="mcapa">時価総額が小さい順</option><option value="code">コード順</option></select>
<button id="clr" type="button">条件をクリア</button></div>
<div class="cnt" id="cnt"></div><div class="card list" id="list"></div><button id="more" type="button" hidden></button></div>
<script>const R={items};const $=id=>document.getElementById(id);
const L=$('list'),Q=$('q'),FM=$('fm'),FS=$('fs'),SO=$('so');const STEP=200;let lim=STEP;
const KEY='oneIndexFilter';
function opts(sel,label,vals){{const c={{}};R.forEach(x=>{{const v=x[vals];c[v]=(c[v]||0)+1;}});
 let ks=Object.keys(c);ks=vals===2?['プライム','スタンダード','グロース'].filter(k=>c[k]).concat(ks.filter(k=>!['プライム','スタンダード','グロース'].includes(k)).sort()):ks.sort((a,b)=>a==='―'?1:b==='―'?-1:a.localeCompare(b,'ja'));
 sel.innerHTML=`<option value="">${{label}}（すべて）</option>`+ks.map(k=>`<option value="${{k}}">${{k}}（${{c[k].toLocaleString()}}）</option>`).join('');}}
opts(FM,'市場',2);opts(FS,'業種',3);
function fmtMc(v){{if(v==null)return'―';if(v>=10000)return(v/10000).toFixed(v>=100000?1:2)+'兆円';return Math.round(v).toLocaleString()+'億円';}}
function save(){{try{{localStorage.setItem(KEY,JSON.stringify({{m:FM.value,s:FS.value,o:SO.value}}));}}catch(e){{}}}}
function load(){{try{{const v=JSON.parse(localStorage.getItem(KEY)||'null');if(v){{FM.value=v.m||'';FS.value=v.s||'';SO.value=v.o||'mcap';if(FM.value!==(v.m||''))FM.value='';if(FS.value!==(v.s||''))FS.value='';}}}}catch(e){{}}}}
function show(){{const q=Q.value.trim().toLowerCase(),m=FM.value,s=FS.value,o=SO.value;
 let r=R.filter(x=>(!m||x[2]===m)&&(!s||x[3]===s)&&(!q||x[0].toLowerCase().startsWith(q)||x[1].toLowerCase().includes(q)));
 if(o==='code')r.sort((a,b)=>a[0].localeCompare(b[0]));
 else{{const d=o==='mcap'?-1:1;r.sort((a,b)=>a[4]==null?1:b[4]==null?-1:d*(a[4]-b[4]));}}
 const n=r.length;const v=r.slice(0,lim);
 $('cnt').textContent=n?`${{n.toLocaleString()}}銘柄`+(n>v.length?`（${{v.length.toLocaleString()}}件を表示）`:''):'';
 L.innerHTML=v.map(x=>`<a href="${{x[0]}}.html"><b>${{x[0]}}</b><span class="nm">${{x[1]}}</span><small>${{x[2]}}・${{x[3]}}</small><span class="mc">${{fmtMc(x[4])}}</span></a>`).join('')||'<p style="padding:10px;color:var(--mut)">見つかりません</p>';
 const mb=$('more');mb.hidden=n<=v.length;mb.textContent=`さらに表示（残り ${{(n-v.length).toLocaleString()}}件）`;}}
function reset(){{lim=STEP;show();}}
Q.oninput=reset;[FM,FS,SO].forEach(e=>e.onchange=()=>{{save();reset();}});
$('more').onclick=()=>{{lim+=STEP;show();}};
$('clr').onclick=()=>{{Q.value='';FM.value='';FS.value='';SO.value='mcap';save();reset();}};
Q.onkeydown=e=>{{if(e.key==='Enter'){{const a=L.querySelector('a');if(a)location.href=a.href;}}}};load();show();</script></body></html>"""
    (OUT / "index.html").write_text(page, encoding="utf-8")


def index_only(T):
    """銘柄ページは作り直さず、一覧（index.html）だけを手元のデータから作る（数秒）。"""
    codes = sorted(p.stem for p in OUT.glob("*.html") if p.stem != "index")
    rows = []
    for code in codes:
        lt, sc = T["latest"].get(code, {}), T["score"].get(code, {})
        sr, tk = T["sigrows"].get(code) or {}, T["tickers"].get(code, {})
        rows.append([code, lt.get("銘柄名") or sc.get("銘柄名") or sr.get("n") or tk.get("name") or code,
                     lt.get("市場") or sc.get("市場") or sr.get("m") or tk.get("market") or "",
                     lt.get("業種") or sc.get("業種") or sr.get("s") or "―",
                     compact(num(sc.get("時価総額(億円)")))])
    write_index(rows)
    print(f"一覧のみ作成 {len(rows)} 銘柄 → {(OUT / 'index.html').relative_to(BASE)}")


def main(codes):
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    T = load_tables()
    if codes == ["--index"]:
        index_only(T)
        return
    page = split_template()
    full = not codes
    if full:
        codes = sorted(p.stem for p in (BASE / "data" / "prices").glob("*.csv"))
    ok, skip, rows = 0, [], []
    for code in codes:
        try:
            d = build(code, T)
        except Exception as e:  # 1銘柄の不具合で全体を止めない
            skip.append(f"{code}:{e}")
            continue
        if d is None:
            skip.append(f"{code}:株価なし")
            continue
        title = html.escape(f"{d['info']['name']}（{code}）")
        data = json.dumps(d, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
        (OUT / f"{code}.html").write_text(page.replace("__TITLE__", title).replace("__DATA__", data), encoding="utf-8")
        rows.append([code, d["info"]["name"], d["info"]["market"], d["info"]["sector"] or "―", compact(d["extra"]["mcap"])])
        ok += 1
    if full:
        write_index(rows)
    print(f"作成 {ok} 銘柄 / スキップ {len(skip)} / {time.time() - t0:.0f}秒 → {OUT.relative_to(BASE)}")
    if skip:
        print("スキップ:", ", ".join(skip[:20]) + (" ほか" if len(skip) > 20 else ""))


if __name__ == "__main__":
    main(sys.argv[1:])
