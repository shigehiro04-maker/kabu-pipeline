#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
トップ画面（data/charts/index.html）を作る。4つの画面への入口＋銘柄検索＋お気に入り。

  株式分析ダッシュボード   one/index.html   （dashboards/one/ を data/charts/one/ に複製して公開）
  業績ダッシュボード(通期) gyoseki/<コード>.html（dashboards/ を data/charts/gyoseki/ に複製して公開）
  チャート一覧             charts.html
  東証ファンダメンタル分析 fundamentals.html（詳細版。シンプル版 fundamentals_simple.html）
  売買シグナル             signals.html
  主要指数ダッシュボード   indices.html（株価指数/run_indices.sh が作る。要約 indices_summary.json）
  セクターローテーション   sector.html（sector_rotation/sector_rotation.py が作る。要約 sector_summary.json）
  日米リードラグ予想     GitHub の jp-us-leadlag（~/jp-us-leadlag が毎朝公開）へのリンクカード。
                         要約 docs/summary.json を、作成時はローカルの clone から、表示時は公開ページから読む
  日経225 入れ替え予想    nikkei225.html（日経225/run_nikkei225.sh が作る。要約 nikkei225_summary.json）
  理論株価                 valuation.html（理論株価/run_valuation.sh が作る。要約 valuation_summary.json）
  需給分析                 jukyu.html（需給分析/run_jukyu.sh が作る。要約 jukyu_summary.json）
  ヒートマップ             heatmap.html（ヒートマップ/make_heatmap.py が作る。要約 heatmap_summary.json）

入力: data/charts/_summary.json（銘柄コード・名前・市場・業種・最終日）
通信なし・標準ライブラリのみ。run_daily.sh の最後（公開の直前）で呼ぶ。
"""
import json, os, datetime, shutil
from pathlib import Path

BASE = Path(__file__).resolve().parent
SITE = BASE / "data" / "charts"
ONE_SRC = BASE / "dashboards" / "one"
ONE_DST = SITE / "one"


GYO_SRC = BASE / "dashboards"          # 通期の業績ダッシュボード（make_company_dashboards.py）
GYO_DST = SITE / "gyoseki"


def sync_one():
    """dashboards/one/ → data/charts/one/"""
    return sync_dir(ONE_SRC, ONE_DST)


def sync_gyoseki():
    """dashboards/（one/ を除く）→ data/charts/gyoseki/。ファンダ分析の詳細からリンクする"""
    return sync_dir(GYO_SRC, GYO_DST, skip={"one"})


def sync_dir(SRC, DST, skip=()):
    """SRC → DST（差分だけコピーし、消えたファイルは消す）。skip は SRC 直下で除外するフォルダ名"""
    if not SRC.exists():
        return 0
    n = 0
    keep = set()
    for src in SRC.rglob("*"):
        rel = src.relative_to(SRC)
        if rel.parts and rel.parts[0] in skip:
            continue
        dst = DST / rel
        keep.add(rel)
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            continue
        if (not dst.exists() or dst.stat().st_size != src.stat().st_size
                or dst.stat().st_mtime < src.stat().st_mtime):
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            n += 1
    if DST.exists():
        for dst in sorted(DST.rglob("*"), reverse=True):
            if dst.relative_to(DST) not in keep:
                dst.rmdir() if dst.is_dir() else dst.unlink()
    return n


def link_usdjpy():
    """ドル円ページ（別スクリプトで毎日作り直される）に、トップへ戻るリンクを差し込む"""
    f = SITE / "usdjpy.html"
    if not f.exists():
        return
    t = f.read_text(encoding="utf-8")
    if 'id="home-link"' in t:
        return
    a = '<p class="kick">'
    link = ('<a id="home-link" href="./index.html" title="トップへ" style="display:inline-block;'
            'text-decoration:none;color:inherit;font-size:14px;margin:0 0 6px">‹ トップ</a>' + a)
    if a in t:
        f.write_text(t.replace(a, link, 1), encoding="utf-8")


def _cls(v):
    """騰落の色クラス（u＝上昇・赤、d＝下落・緑）"""
    return "u" if v > 0 else "d" if v < 0 else ""


# カードの見せ方（KB_CARD=text：文字だけで簡潔に／info：強調の数字と補足つき）。どちらでも説明は下の短い1行にそろえる
MKT_STYLE = "merged"  # 概況の出し方：merged＝地合い・指数・業種を概況1枚にまとめる（2026-11-16 から）／split＝従来の3枚
CARD_STYLE = os.environ.get("KB_CARD", "text")   # 2026-11-13 A案（文字で簡潔）に決定
SHORT = {
    "監視銘柄": "タイトル別の一覧表で銘柄情報を確認", "決算カレンダー": "決算発表の予定と結果を月のカレンダーで", "ダッシュボード": "1銘柄の分析を1画面で",
    "チャート": "全銘柄のチャートを検索・絞り込み", "チャート形状検索": "3か月の値動きの形で銘柄を探す",
    "スクリーニング": "財務指標で全銘柄を比較", "売買シグナル": "テクニカルとファンダで売買判定",
    "ヒートマップ": "業種×銘柄の騰落を色で一覧", "主要指数": "日米の指数・金利・為替・商品と騰落レシオ",
    "需給": "信用残・空売り・投資部門別の売買", "理論株価": "7手法の理論株価と株価の乖離",
    "セクターローテーション": "日米の相場局面と主導業種", "日米リードラグ予想": "米国業種ETFから今日の東京の業種を予想",
    "日経225 入れ替え予想": "採用・除外の候補とウエート", "寄り前ギャップ": "翌朝の候補と試験運用の記録",
    "業種モメンタム": "上位業種と試験運用の記録", "ドル円動向": "ドル円の妥当水準と方向感",
}


def card(href, title, desc="", big=None, rest="", foot="", cid=""):
    """トップのタイル1枚。big=(ラベル, 値, 色クラス) は大きく見せる値、rest は補足（<span>…</span> の並び）"""
    desc = SHORT.get(title, desc)
    kv = ""
    if big:
        lab, val, c = big
        small = " s" if len(val) > 9 else ""
        kv = f'<div class="kv"><span class="k">{lab}</span><b class="v{small} {c}">{val}</b></div>'
    ida = f' id="{cid}"' if cid else ""
    return (f'<a class="card"{ida} href="{href}"><div class="t">{title}</div>'
            + (f'<p>{desc}</p>' if desc else "") + kv
            + (f'<div class="ixs">{rest}</div>' if rest else "")
            + f'<div class="ft"><span>{foot}</span><span>ひらく →</span></div></a>')


HERO_KEYS = {"nikkei225", "topix", "nikkei_vi", "dow", "sp500", "nasdaq100", "vix"}   # 最上部の指数カードに出すもの


def hero():
    """トップ最上部の3枚：その日の地合い（プライムの時価総額加重の前日比と騰落銘柄数）、主要指数、業種別の騰落率。
    戻り値は (HTML, 地合いを出したか, 指数を出したか)。出せなかった分は従来どおりカードで出す"""
    try:
        S = json.load(open(SITE / "heatmap_summary.json", encoding="utf-8"))
    except Exception:
        S = {}
    M = S.get("markets") or {}
    left = right = strip = ""
    p = M.get("プライム")
    if (SITE / "heatmap.html").exists() and p and p.get("chg") is not None:
        flat = max(p.get("n", 0) - p["up"] - p["down"], 0)
        rows = ""
        for k, m in M.items():
            if k == "プライム" or m.get("chg") is None:
                continue
            rows += (f'<div class="mk"><span class="mn">{k}</span><b class="{_cls(m["chg"])}">{m["chg"]:+.2f}%</b>'
                     f'<div class="bar s"><i class="bu" style="flex:{m["up"]}"></i><i class="bd" style="flex:{m["down"]}"></i></div>'
                     f'<span class="mc">{m["up"]} / {m["down"]}</span></div>')
        # 見出しは「今日」ではなく株価データの日付（例: 11/12（木）の地合い）
        try:
            _d = datetime.date.fromisoformat(str(S.get("asof", ""))[:10])
            day = f'{_d.month}/{_d.day}（{"月火水木金土日"[_d.weekday()]}）の地合い'
        except Exception:
            day = "直近の地合い"
        left = (f'<a class="card hA" href="./heatmap.html"><div class="hl">{day} — プライム（時価総額加重）</div>'
                f'<div class="hrow"><b class="hbig {_cls(p["chg"])}">{p["chg"]:+.2f}%</b>'
                f'<div class="hcnt"><span>値上がり <b>{p["up"]}</b></span><span>変わらず <b>{flat}</b></span><span>値下がり <b>{p["down"]}</b></span></div></div>'
                f'<div class="bar"><i class="bu" style="flex:{p["up"]}"></i><i class="bn" style="flex:{flat}"></i><i class="bd" style="flex:{p["down"]}"></i></div>'
                f'<div class="mks">{rows}</div></a>')
        sx = ""
        for nm, v, _n in S.get("sectors_prime") or []:
            pw = round(20 + 80 * min(abs(v) / 3.0, 1))
            sx += f'<div class="sx {"su" if v >= 0 else "sd"}" style="--p:{pw}"><span>{nm}</span><b>{v:+.2f}%</b></div>'
        if sx:
            strip = ('<a class="card strip" href="./heatmap.html"><div class="hl">業種別の騰落率（プライム・1日・時価総額加重）'
                     f'<span>ヒートマップをひらく →</span></div><div class="sxs">{sx}</div></a>')
    if (SITE / "indices.html").exists():
        try:
            rows = ""
            for x in json.load(open(SITE / "indices_summary.json", encoding="utf-8")):
                # 最上部のカードは株価指数と恐怖指数だけ（金利・為替・商品などは主要指数ダッシュボードとマーケット概況で見る）
                if x.get("close") is None or x.get("key") not in HERO_KEYS:
                    continue
                c = x.get("chgPct")
                chg = ("<em></em>" if c is None else
                       f'<em class="{_cls(c)}">{"▲" if c > 0 else "▼" if c < 0 else ""}{abs(c):.2f}%</em>')
                note = x.get("band") or x.get("note")
                note = f'<small>{note}</small>' if note else ""
                name = str(x["name"]).replace("&", "&amp;")
                rows += f'<div class="ix"><span>{name}{note}</span><b>{x["close"]:,.2f}</b>{chg}</div>'
            if rows:
                right = ('<a class="card hB" href="./indices.html"><div class="hl">主要指数</div>'
                         f'{rows}<div class="ft"><span>更新 {mtime(SITE / "indices.html")}</span><span>ひらく →</span></div></a>')
        except Exception:
            pass
    html = (f'<div class="hero">{left}{right}</div>' if (left or right) else "") + strip
    return html, bool(left), bool(right)


def market_overview():
    """マーケット概況（make_market.py が作る market_summary.json）。株価データの日付の市況を、
    主な指数の数字と文章で最上部に出す。要約が無い・古い（株価の日付と違う）ときは出さない"""
    try:
        M = json.load(open(SITE / "market_summary.json", encoding="utf-8"))
        H = json.load(open(SITE / "heatmap_summary.json", encoding="utf-8"))
    except Exception:
        return ""
    if not M.get("paras") or str(M.get("asof")) != str(H.get("asof", ""))[:10]:
        return ""
    e = lambda s: str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    tiles = ""
    for t in M.get("tiles", []):
        c = "u" if t["dir"] > 0 else "d" if t["dir"] < 0 else ""
        arrow = "▲" if t["dir"] > 0 else "▼" if t["dir"] < 0 else ""
        nm = e(t["name"]) + (f'（{int(t["date"][5:7])}/{int(t["date"][8:10])}）' if t.get("date") and t["date"] != M["asof"] else "")
        tiles += (f'<div class="mi" data-k="{t["k"]}"><span>{nm}</span><b>{t["close"]:,.{t["nd"]}f}{t["suf"]}</b>'
                  f'<em class="{c}">{arrow}{abs(t["chg"]):,.2f}{t["csuf"]}</em></div>')
    P = M["paras"]
    para = lambda p: f'<div class="mpp"><span class="ph">{e(p["h"])}</span>{p["t"]}</div>'   # p["t"] は make_market.py が作った HTML
    first, rest = "".join(para(p) for p in P[:1]), "".join(para(p) for p in P[1:])
    if M.get("news"):      # 値動きの背景＝引け後に出た市況の見出し（fetch_news.py。見出しとリンクだけ）
        li = "".join(f'<a href="{e(x["url"])}" target="_blank" rel="noopener noreferrer"><time>{e(x["at"])}</time>'
                     f'<span>{e(x["t"])}</span><em>{e(x["src"])}</em></a>' for x in M["news"])
        first += ('<div class="mnews"><div class="mvh">ニュースの見出し<small>値動きの背景。押すと各社の記事が開きます（Google ニュース経由）</small></div>'
                  f'{li}</div>')
    mv = ""
    V = M.get("movers") or {}
    for key, lab in (("up", "値上がり率の上位"), ("down", "値下がり率の上位")):
        if V.get(key):
            li = "".join(f'<a href="./one/{e(r[0])}.html"><b>{e(r[0])}</b><span>{e(r[1])}</span>'
                         f'<em class="{_cls(r[2])}">{r[2]:+.2f}%</em></a>' for r in V[key])
            mv += f'<div class="mvc"><div class="mvh">{lab}（時価総額上位500社）</div>{li}</div>'
    if mv:
        rest += f'<div class="mv">{mv}</div>'
    more = (f'<div class="mmore" id="mkmore">{rest}</div>'
            '<button class="btn mbtn" id="mkbtn" type="button">続きを表示</button>' if rest else "")
    return (f'<section class="card mkt" id="mkt"><div class="hl">{e(M["day"])}のマーケット概況 — {e(M.get("market", "東京株式市場"))}'
            f'<span>株価データの日付の市況・作成 {e(M.get("built", "")[5:].replace("-", "/"))}</span></div>'
            + (f'<div class="mh">{e(M["headline"])}</div>' if M.get("headline") else "")
            + f'<div class="mis">{tiles}</div><div class="mps">{first}{more}</div></section>')


def _spark_tiles(M):
    """概況の指数タイル（2026-11-25）：前日比％を大きく、その日の日中の動き（5分足、fetch_mkt_intraday.py）を小さなグラフで。
    点線が前日終値、それより上は上げの色・下は下げの色で塗る。右に日中の高値・安値。5%以上動いた日は％を色の帯に。
    日中の点が無いキーはグラフ無しで出す。数字はその日の終値（15分ごとの値には書き換えない）"""
    e = lambda x: str(x).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    try:
        I = json.load(open(BASE / "data" / "market" / "intraday.json", encoding="utf-8")).get("s", {})
    except Exception:
        I = {}
    out = ""
    for t in M.get("tiles", []):
        close, chg, nd = float(t["close"]), float(t["chg"]), int(t["nd"])
        prev = close / (1 + chg / 100) if t["csuf"] == "%" else close - chg
        pct = (close / prev - 1) * 100 if prev else 0.0
        c = "u" if pct > 0 else "d" if pct < 0 else ""
        big = " x" if abs(pct) >= 5 else ""
        dt = t.get("date") or M["asof"]
        dl = f'<small>{int(dt[5:7])}/{int(dt[8:10])}</small>' if dt != M["asof"] else ""
        cs = "%" if t["csuf"] == "%" else t["csuf"]
        dv = close - prev
        chs = (f'{dv:+,.{nd}f}' if t["csuf"] == "%" else f'{chg:+,.{3 if t["csuf"] == "pt" else nd}f}{cs}')
        svg = ""
        x = (I.get(t["k"]) or {}).get(dt)
        if x and len(x.get("v", [])) >= 3:
            v = list(x["v"])
            r = close / v[-1] if v[-1] else 1
            v = [a * r for a in v] if abs(r - 1) > 0.02 else v[:-1] + [close]   # TOPIX は ETF の形を終値に合わせる
            W, H, R, T, B = 220, 66, 44, 5, 5
            hi, lo = max(v), min(v)
            y1, y0 = max(hi, prev), min(lo, prev)
            pad = (y1 - y0) * 0.06 or abs(prev) * 0.001 or 1
            y1, y0 = y1 + pad, y0 - pad
            Y = lambda a: T + (y1 - a) / (y1 - y0) * (H - T - B)
            X = lambda i: i / (len(v) - 1) * (W - R)
            pts = " ".join(f"{X(i):.1f},{Y(a):.1f}" for i, a in enumerate(v))
            yp = Y(prev)
            area = f"M0,{yp:.1f} L{pts.replace(' ', ' L')} L{X(len(v) - 1):.1f},{yp:.1f} Z"
            k = e(t["k"])
            fm = lambda a: f"{a:,.{nd}f}"
            ly = lambda yy, up: min(max(yy + (8 if up else -2), 9), H - 1)
            yh, yl = ly(Y(hi), True), ly(Y(lo), False)
            if yl - yh < 11:      # 日中の値幅が狭い（窓を開けた日など）と高値・安値の数字が重なるので離す
                m = (yh + yl) / 2
                yh, yl = max(m - 5.5, 9), min(m + 5.5, H - 1)
                if yl - yh < 11:
                    yh, yl = (yl - 11, yl) if yl >= H - 1 else (yh, yh + 11)
            svg = (f'<svg viewBox="0 0 {W} {H}" aria-hidden="true"><defs>'
                   f'<clipPath id="ca_{k}"><rect width="{W}" height="{yp:.1f}"/></clipPath>'
                   f'<clipPath id="cb_{k}"><rect y="{yp:.1f}" width="{W}" height="{H}"/></clipPath></defs>'
                   f'<path d="{area}" class="fu" clip-path="url(#ca_{k})"/><path d="{area}" class="fd" clip-path="url(#cb_{k})"/>'
                   f'<line x1="0" x2="{W - R}" y1="{yp:.1f}" y2="{yp:.1f}" class="pv"/>'
                   f'<polyline points="{pts}" class="ln"/>'
                   f'<circle cx="{X(len(v) - 1):.1f}" cy="{Y(v[-1]):.1f}" r="2.2" class="dt"/>'
                   f'<text x="{W - R + 4}" y="{yh:.1f}">{fm(hi)}</text>'
                   f'<text x="{W - R + 4}" y="{yl:.1f}">{fm(lo)}</text></svg>'
                   f'<div class="tm"><span>{e(x.get("t0", ""))}</span><span>{e(x.get("t1", ""))}</span></div>')
        else:
            svg = '<div class="nos"></div>'
        out += (f'<div class="mi mt" data-k="{e(t["k"])}"><div class="nm"><span>{e(t["name"])}</span>{dl}</div>'
                f'<div class="pc {c}{big}">{pct:+.2f}<i>%</i></div>{svg}'
                f'<div class="cv"><b>{close:,.{nd}f}{e(t["suf"])}</b><em class="{c}">{chs}</em></div></div>')
    return out



def market_merged():
    """マーケット概況に地合い・株価指数・業種別の騰落率を取り込んだ1枚（KB_MKT=merged のとき）。
    同じ数字は1回だけ出す：指数＝タイル、値上がり・値下がり＝帯グラフ、業種＝色つきのタイル。
    文章は図に無い話だけ残す。作れないときは "" を返し、従来の並び（概況＋地合い＋業種）で出す"""
    try:
        M = json.load(open(SITE / "market_summary.json", encoding="utf-8"))
        H = json.load(open(SITE / "heatmap_summary.json", encoding="utf-8"))
    except Exception:
        return ""
    if not M.get("paras") or str(M.get("asof")) != str(H.get("asof", ""))[:10]:
        return ""
    e = lambda s: str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    has_ix = (SITE / "indices.html").exists()
    has_hm = (SITE / "heatmap.html").exists()
    P = {p["h"]: p["t"] for p in M["paras"]}
    para = lambda h, t: f'<div class="mpp"><span class="ph">{e(h)}</span>{t}</div>'

    # 指数のタイル（株価指数カードの代わり。主要指数ダッシュボードがあれば押すと開く）
    tiles = _spark_tiles(M)
    tiles = (f'<a class="mis mig" href="./indices.html" title="主要指数ダッシュボードをひらく">{tiles}</a>' if has_ix
             else f'<div class="mis mig">{tiles}</div>')

    # 主要指数の文章＋ニュースの見出し
    top = para("主要指数", P["主要指数"]) if P.get("主要指数") else ""
    if M.get("news"):
        li = "".join(f'<a href="{e(x["url"])}" target="_blank" rel="noopener noreferrer"><time>{e(x["at"])}</time>'
                     f'<span>{e(x["t"])}</span><em>{e(x["src"])}</em></a>' for x in M["news"])
        top += ('<div class="mnews"><div class="mvh">ニュースの見出し<small>値動きの背景。押すと各社の記事が開きます（Google ニュース経由）</small></div>'
                f'{li}</div>')

    # 地合い：値上がり・値下がりの帯グラフと市場別（地合いカードの代わり）。文章は52週高値・安値、25日線、売買代金だけ
    K = H.get("markets") or {}
    key = "全市場" if "全市場" in K else "プライム"
    p = K.get(key)
    lk = '<a class="mlk" href="./heatmap.html">ヒートマップをひらく →</a>' if has_hm else ""
    mood = ""
    if p and p.get("chg") is not None:
        flat = max(p.get("n", 0) - p["up"] - p["down"], 0)
        rows = ""
        for k, m in K.items():
            if k == key or m.get("chg") is None:
                continue
            rows += (f'<div class="mk"><span class="mn">{e(k)}</span><b class="{_cls(m["chg"])}">{m["chg"]:+.2f}%</b>'
                     f'<div class="bar s"><i class="bu" style="flex:{m["up"]}"></i><i class="bd" style="flex:{m["down"]}"></i></div>'
                     f'<span class="mc">{m["up"]} / {m["down"]}</span></div>')
        t = P.get("騰落・売買代金", "")
        i = t.find("全市場で52週高値") if "全市場で52週高値" in t else t.find("52週高値を更新")
        extra = t[i:] if i >= 0 else ""
        lab = "米国全市場" if key == "全市場" else key
        mood = (f'<div class="msec"><div class="mst"><span class="ph">地合い</span><span class="msl">{lab}（時価総額加重）</span>{lk}</div>'
                f'<div class="mgrow"><b class="mgbig {_cls(p["chg"])}">{p["chg"]:+.2f}%</b>'
                f'<div class="mgr"><div class="hcnt"><span>値上がり <b>{p["up"]:,}</b></span><span>変わらず <b>{flat:,}</b></span>'
                f'<span>値下がり <b>{p["down"]:,}</b></span></div>'
                f'<div class="bar"><i class="bu" style="flex:{p["up"]}"></i><i class="bn" style="flex:{flat}"></i><i class="bd" style="flex:{p["down"]}"></i></div></div></div>'
                f'<div class="mks mk2">{rows}</div>'
                + (f'<div class="mpp">{extra}</div>' if extra else "") + '</div>')

    # 業種：色つきのタイル（業種別の騰落率の帯の代わり）。文章は上昇・下落の業種数だけ
    sec = H.get("sectors_prime") or []
    sect = ""
    if sec:
        sx = ""
        for nm, v, _n in sec:
            pw = round(20 + 80 * min(abs(v) / 3.0, 1))
            sx += f'<div class="sx {"su" if v >= 0 else "sd"}" style="--p:{pw}"><span>{e(nm)}</span><b>{v:+.2f}%</b></div>'
        ups, dns = sum(s[1] > 0 for s in sec), sum(s[1] < 0 for s in sec)
        sxs = f'<a class="sxs" href="./heatmap.html">{sx}</a>' if has_hm else f'<div class="sxs">{sx}</div>'
        sect = (f'<div class="msec"><div class="mst"><span class="ph">業種</span>'
                f'<span class="msl">{len(sec)}業種のうち上昇 {ups}・下落 {dns}（{"全市場" if key == "全市場" else "プライム"}・1日・時価総額加重）</span>{lk}</div>{sxs}</div>')

    # 続き：個別銘柄・為替商品・決算予定・値上がり率／値下がり率の上位（スマホではボタンで開く）
    rest = "".join(para(p["h"], p["t"]) for p in M["paras"] if p["h"] not in ("主要指数", "騰落・売買代金", "業種"))
    mv = ""
    V = M.get("movers") or {}
    for k2, lab in (("up", "値上がり率の上位"), ("down", "値下がり率の上位")):
        if V.get(k2):
            li = "".join(f'<a href="./one/{e(r[0])}.html"><b>{e(r[0])}</b><span>{e(r[1])}</span>'
                         f'<em class="{_cls(r[2])}">{r[2]:+.2f}%</em></a>' for r in V[k2])
            mv += f'<div class="mvc"><div class="mvh">{lab}（時価総額上位500社）</div>{li}</div>'
    if mv:
        rest += f'<div class="mv">{mv}</div>'
    more = (f'<div class="mmore" id="mkmore">{rest}</div>'
            '<button class="btn mbtn" id="mkbtn" type="button">続きを表示</button>' if rest else "")
    return (f'<section class="card mkt mgd" id="mkt"><div class="hl">{e(M["day"])}のマーケット概況 — {e(M.get("market", ""))}'
            f'<span>株価データの日付の市況・作成 {e(M.get("built", "")[5:].replace("-", "/"))}</span></div>'
            + (f'<div class="mh">{e(M["headline"])}</div>' if M.get("headline") else "")
            + f'{tiles}<div class="mps">{top}{mood}{sect}{more}</div></section>')


def indices_card():
    """主要指数ダッシュボード（株価指数/run_indices.sh が作る）へのカード。最上部に指数を出せなかったときの控え"""
    f = SITE / "indices.html"
    if not f.exists():
        return ""
    return card("./indices.html", "主要指数", "日米の株価指数・VIX・米10年金利・ドル円・原油・金・ビットコインの現在値と推移",
                foot=f"更新 {mtime(f)}")


def sector_card():
    """セクターローテーション（sector_rotation/sector_rotation.py が作る sector.html）へのカード。
    相場の四季の判定とスコア上位業種を添える"""
    f = SITE / "sector.html"
    if not f.exists():
        return ""
    desc, big, rest = "日米の業種の強弱（RRG）・ヒートマップ・相場の四季（金融／業績／逆金融／逆業績）", None, ""
    try:
        S = json.load(open(SITE / "sector_summary.json", encoding="utf-8"))
        P = S.get("phases", {})
        if P.get("jp"):
            big = ("日本", f'{P["jp"]["season"]}・{P["jp"]["phase"]}', "")
            rest += f'<span>移行サイン <b>{P["jp"]["signals"]}</b></span>'
        if P.get("us"):
            rest += f'<span>米国 <b>{P["us"]["season"]}・{P["us"]["phase"]}</b>（移行サイン {P["us"]["signals"]}）</span>'
        for k, lab in (("us", "米国上位"), ("jp33", "日本上位")):
            t = S.get("top", {}).get(k)
            if t:
                rest += f'<span>{lab} <b>{"・".join(t)}</b></span>'
        if big or rest:
            desc = "日米の相場局面と主導業種"
    except Exception:
        pass
    return card("./sector.html", "セクターローテーション", desc, big, rest, f"更新 {mtime(f)}")


def nikkei_card():
    """日経225 入れ替え予想（日経225/run_nikkei225.py が作る nikkei225.html）へのカード。次回の予想を添える"""
    f = SITE / "nikkei225.html"
    if not f.exists():
        return ""
    desc, big, rest = "日経平均の選定基準を再現した次回の採用・除外予想、ウエート・寄与度・キャップ監視", None, ""
    try:
        S = json.load(open(SITE / "nikkei225_summary.json", encoding="utf-8"))
        big = ("次回", S["next_effective"][5:].replace("-", "/"), "")
        rest = f'<span>基準日 <b>{S["next_base"][5:].replace("-", "/")}</b></span>'
        if S.get("adds"):
            rest += '<span>採用予想 <b>' + "・".join(f'{a[1]}' for a in S["adds"][:3]) + '</b></span>'
        if S.get("dels"):
            rest += '<span>除外予想 <b>' + "・".join(f'{a[1]}' for a in S["dels"][:3]) + '</b></span>'
        if S.get("top"):
            t = S["top"][0]
            rest += f'<span>ウエート1位 <b>{t[1]} {t[2]:.1f}%</b></span>'
        desc = "採用・除外の候補とウエート"
    except Exception:
        pass
    return card("./nikkei225.html", "日経225 入れ替え予想", desc, big, rest, f"更新 {mtime(f)}")


def valuation_card():
    """理論株価（理論株価/report_valuation.py が作る valuation.html）へのカード。市場全体の乖離を添える"""
    f = SITE / "valuation.html"
    if not f.exists():
        return ""
    desc = "PER・PBR（自社の過去倍率）・DCF・DDM・RIM・はっしゃん式・東洋経済式（四季報）の7手法で全銘柄の理論株価。需給・心理・市場の織り込みでどう変わるかを比較"
    big, rest = None, ""
    try:
        S = json.load(open(SITE / "valuation_summary.json", encoding="utf-8"))
        a, b = S["lens"]["ファンダ"], S["lens"]["需給・心理込み"]
        big = ("乖離の中央値", f'{a["中央値"]:+.1f}%', "")
        rest = (f'<span>需給・心理込み <b>{b["中央値"]:+.1f}%</b></span>'
                f'<span>+20%以上割安 <b>{a["割安20"]:,}銘柄</b></span>'
                f'<span>無リスク金利 <b>{S["rf"]*100:.2f}%</b></span>')
        desc = "7手法の理論株価と、いまの株価との乖離"
    except Exception:
        pass
    return card("./valuation.html", "理論株価", desc, big, rest, f"更新 {mtime(f)}")


def jukyu_card():
    """需給分析（需給分析/analyze_jukyu.py が作る jukyu.html）へのカード。市場の信用倍率・空売り比率などを添える"""
    f = SITE / "jukyu.html"
    if not f.exists():
        return ""
    desc, big, rest = "銘柄ごとの信用買残・売残・信用倍率、日証金・逆日歩、大口空売り、空売り比率、投資部門別の売買", None, ""
    try:
        S = json.load(open(SITE / "jukyu_summary.json", encoding="utf-8"))
        if S.get("信用倍率") is not None:
            big = ("信用倍率", f'{S["信用倍率"]:.2f}倍', "")
        if S.get("評価損益率") is not None:
            rest += f'<span>買い方評価損益 <b class="{_cls(S["評価損益率"])}">{S["評価損益率"]:+.1f}%</b></span>'
        if S.get("空売り比率") is not None:
            rest += f'<span>空売り比率 <b>{S["空売り比率"]:.1f}%</b></span>'
        if S.get("海外") is not None:
            rest += f'<span>海外（週） <b>{S["海外"]:+,.0f}億円</b></span>'
        if S.get("踏み上げ候補"):
            rest += '<span>踏み上げ候補 <b>' + "・".join(a[1] for a in S["踏み上げ候補"][:3]) + '</b></span>'
        if big or rest:
            desc = "信用残・空売り・投資部門別の売買"
    except Exception:
        pass
    return card("./jukyu.html", "需給", desc, big, rest, f"更新 {mtime(f)}")


def analyst_card():
    """アナリスト予想ランキング（アナリスト予想/analyst_page.py が作る analyst.html）へのカード"""
    f = SITE / "analyst.html"
    if not f.exists():
        return ""
    desc, big, rest = "目標株価・投資判断・業績予想の修正", None, ""
    try:
        S = json.load(open(SITE / "analyst_summary.json", encoding="utf-8"))
        if S.get("上位500の上昇余地中央値") is not None:
            big = ("上位500社の上昇余地", f'{S["上位500の上昇余地中央値"]:+.1f}%', "")
        if S.get("上方修正が多い割合") is not None:
            rest += f'<span>上方修正が優勢な銘柄 <b>{S["上方修正が多い割合"]:.0f}%</b></span>'
        rest += f'<span>上昇余地30%以上 <b>{S.get("上昇余地30%以上", 0):,}</b></span><span>目標株価あり <b>{S.get("目標株価あり", 0):,}</b></span>'
    except Exception:
        pass
    return card("./fundamentals.html#analyst", "アナリスト予想", desc, big, rest, f"更新 {mtime(f)}")


def heatmap_card():
    """ヒートマップ（ヒートマップ/make_heatmap.py が作る heatmap.html）へのカード。最上部に地合いを出せなかったときの控え"""
    f = SITE / "heatmap.html"
    if not f.exists():
        return ""
    return card("./heatmap.html", "ヒートマップ", "プライム・スタンダード・グロース・日経225を業種×銘柄で一覧。色＝騰落率、大きさ＝時価総額／売買代金",
                foot=f"更新 {mtime(f)}")


def gap_card():
    """寄り前ギャップ（寄り前ギャップ/gap_page.py が作る gap.html）へのカード。翌朝の候補数と試験運用の累計を添える"""
    f = SITE / "gap.html"
    if not f.exists():
        return ""
    desc, big, rest = "前日安値より大きく下に寄り付いた銘柄を寄付きで買い大引けで売る（Buy-on-Gap）。翌朝の候補と試験運用の記録", None, ""
    try:
        S = json.load(open(SITE / "gap_summary.json", encoding="utf-8"))
        big = (f'{S["target"][5:].replace("-", "/")} の候補（k=1）', f'{S["n1"]}銘柄', "")
        L = S.get("live") or {}
        if L.get("日数"):
            v = L.get("累計_pct") or 0
            rest = f'<span>試験運用 {L["日数"]}日・{L["取引"]}取引 累計 <b class="{_cls(v)}">{v:+.1f}%</b></span>'
        else:
            rest = '<span>試験運用 <b>記録待ち</b></span>'
        desc = "翌朝の候補と試験運用の記録"
    except Exception:
        pass
    return card("./gap.html", "寄り前ギャップ", desc, big, rest, f"更新 {mtime(f)}")


def sector_mom_card():
    """業種モメンタム（業種モメンタム/sm_page.py が作る sector_mom.html）へのカード。上位業種と試験運用の累計を添える"""
    f = SITE / "sector_mom.html"
    if not f.exists():
        return ""
    desc, big, rest = "東証33業種を過去12か月の上がり方で並べ、上位5業種を持つ（第6章）。お金を入れない試験運用", None, ""
    try:
        S = json.load(open(SITE / "sector_mom_summary.json", encoding="utf-8"))
        lab = "上位" if S.get("skind") == "判断" else "いまの上位（参考）"
        big = (lab, "・".join(S.get("top", [])[:3]) + " ほか", "")
        L = (S.get("live") or {}).get("LS") or {}
        if L.get("n", 0) > 1:
            v = L.get("cum") or 0
            rest = f'<span>試験運用 {S["live"]["days"]}日 LS累計 <b class="{_cls(v)}">{v:+.1f}%</b></span>'
        else:
            rest = f'<span>次の判断 <b>{S.get("next", "")[5:].replace("-", "/")}</b>（記録待ち）</span>'
        desc = "過去12か月の上位業種と試験運用の記録"
    except Exception:
        pass
    return card("./sector_mom.html", "業種モメンタム", desc, big, rest, f"更新 {mtime(f)}")

def stock_cards(rows):
    """「銘柄を見る」の5枚（ダッシュボード・チャート・チャート形状検索・スクリーニング・売買シグナル）"""
    out = [card("./one/index.html", "ダッシュボード", "", ("対象", f"{len(rows):,}銘柄", ""),
                '<span>売買シグナル・チャート・ファンダを1画面に</span>', f"更新 {mtime(ONE_DST / 'index.html')}")]
    big, rest = None, ""
    try:
        rs = [r.get("rsi") for r in rows if r.get("rsi") is not None]
        dv = [r.get("dev25") for r in rows if r.get("dev25") is not None]
        big = ("RSI 70以上（買われすぎ）", f"{sum(v >= 70 for v in rs):,}銘柄", "u")
        rest = (f'<span>RSI 30以下（売られすぎ） <b class="d">{sum(v <= 30 for v in rs):,}</b></span>'
                f'<span>25日線から+10%超 <b>{sum(v >= 10 for v in dv):,}</b>・−10%超 <b>{sum(v <= -10 for v in dv):,}</b></span>')
    except Exception:
        pass
    out.append(card("./charts.html", "チャート", "", big, rest, f"更新 {mtime(SITE / 'charts.html')}"))
    out.append(pattern_card())
    out.append(daytrade_card())
    big, rest = None, ""
    try:
        d = json.load(open(BASE / "fundamentals" / "analysis_nofin" / "dashboard_data.json", encoding="utf-8"))
        sm = d.get("summary", {})
        big = ("PER中央値（全銘柄）", f'{sm["PER中央値"]:.1f}倍', "")
        n_cheap = (d.get("screens", {}).get("割安株") or {}).get("件数")
        rest = (f'<span>PBR <b>{sm["PBR中央値"]:.2f}倍</b></span><span>配当利回り <b>{sm["配当利回り中央値(%)"]:.2f}%</b></span>'
                + (f'<span>割安株 <b>{n_cheap:,}件</b></span>' if n_cheap is not None else ""))
    except Exception:
        pass
    out.append(card("./fundamentals.html", "スクリーニング", "", big, rest, f"更新 {mtime(SITE / 'fundamentals.html')}"))
    big, rest = None, ""
    try:
        t = (SITE / "signals.html").read_text(encoding="utf-8")
        D, _ = json.JSONDecoder().raw_decode(t[t.index("const D=") + 8:])
        ts = [r.get("ts") for r in D.get("rows", []) if r.get("ts") is not None]
        fs = [r.get("fs") for r in D.get("rows", []) if r.get("fs") is not None]
        big = ("テクニカル「良好」", f"{sum(v >= 40 for v in ts):,}銘柄", "u")
        rest = (f'<span>「避ける」 <b class="d">{sum(v <= -30 for v in ts):,}</b></span>'
                + (f'<span>ファンダ「良好」 <b>{sum(v >= 45 for v in fs):,}</b></span>' if fs else "")
                + f'<span>対象 <b>{len(ts):,}</b></span>')
    except Exception:
        pass
    out.append(card("./signals.html", "売買シグナル", "", big, rest, f"更新 {mtime(SITE / 'signals.html')}"))
    return "\n".join(c for c in out if c)


def usd_card():
    """ドル円動向へのカード。公開中の usdjpy.html から実勢・水準・次のイベントを拾う"""
    f = SITE / "usdjpy.html"
    if not f.exists():
        return ""
    big, rest = None, ""
    try:
        import re
        t = f.read_text(encoding="utf-8")
        big = ("ドル円（実勢）", re.search(r'class="hbig">([0-9.]+)', t).group(1), "")
        lv = re.search(r'<span class="cl">水準</span><b class="([a-z]*)">([^<]+)</b>', t)
        if lv:
            c = {"up": "u", "dn": "d"}.get(lv.group(1), "")
            rest += f'<span>水準 <b class="{c}">{lv.group(2)}</b></span>'
        ev = re.search(r'"events":\[\{"date":"([0-9-]+)","kind":"[a-z]+","label":"([^"]+)"', t)
        if ev:
            rest += f'<span>次 <b>{ev.group(2)}</b> {ev.group(1)[5:].replace("-", "/")}</span>'
    except Exception:
        pass
    return card("./usdjpy.html", "ドル円動向", "", big, rest, f"更新 {mtime(f)}")


def pattern_card():
    """チャートの形（make_pattern_page.py が作る patterns.html）へのカード。最も多い形と上昇側・下落側の銘柄数を添える"""
    f = SITE / "patterns.html"
    if not f.exists():
        return ""
    big, rest = None, ""
    try:
        S = json.load(open(SITE / "patterns_summary.json", encoding="utf-8"))
        big = ("最も多い形", f'{S["top"][0]}（{S["top"][1]:,}）', "")
        rest = (f'<span class="u">上昇側 <b>{S["up"]:,}</b></span><span>横ばい <b>{S["flat"]:,}</b></span>'
                f'<span class="d">下落側 <b>{S["down"]:,}</b></span>')
    except Exception:
        pass
    return card("./patterns.html", "チャート形状検索", "直近3か月の値動きを25通りの形に分類。形を選ぶとその形の銘柄が一覧で出る",
                big, rest, f"更新 {mtime(f)}")

def daytrade_card():
    """デイトレ チャートパターン（デイトレパターン/dtp_scan.py が作る daytrade/latest.json）へのカード"""
    f = SITE / "daytrade.html"
    if not f.exists():
        return ""
    big, rest, foot = None, "", f"更新 {mtime(f)}"
    try:
        D = json.load(open(SITE / "daytrade" / "latest.json", encoding="utf-8"))
        sig = D.get("sig", [])
        up = sum(1 for s in sig if D["patterns"].get(s[2], [0, 0, 0])[2] > 0)
        lab = "取引中のシグナル" if D.get("live") else f'{D["day"][5:].replace("-", "/")}のシグナル'
        big = (lab, f"{len(sig):,}件", "")
        rest = (f'<span class="u">買い <b>{up:,}</b></span><span class="d">売り <b>{len(sig) - up:,}</b></span>'
                f'<span>形成中 <b>{len(D.get("form", [])):,}</b></span>')
        foot = f'更新 {D.get("made", "")[5:].replace("-", "/")}'
    except Exception:
        pass
    return card("./daytrade.html", "デイトレ チャートパターン",
                "5分足でダブルボトム・三尊・フラッグなど22パターンを自動で検出。過去の勝率・値幅つき",
                big, rest, foot)



LEADLAG_URL = "https://shigehiro04-maker.github.io/jp-us-leadlag/"
LEADLAG_LOCAL = Path.home() / "jp-us-leadlag" / "docs" / "summary.json"

LEADLAG_JS = r"""<script>(function(){
fetch("__URL__summary.json",{cache:"no-store"}).then(function(r){return r.ok?r.json():null}).then(function(S){
  if(!S||!S.long||!S.long.length)return;
  var e=function(s){return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")};
  var p=(S.perf||{})[S.main]||null, w=e(S.mood.word);
  var h='<p>前夜の米国業種ETFから、今日の東京の業種の強弱を予想</p>'
    +'<div class="kv"><span class="k">'+e(S.target.slice(5).replace("-","/"))+' の地合い</span><b class="v'+(S.mood.word.length>9?' s':'')+'">'+w+'</b></div>'
    +'<div class="ixs"><span>▲ <b>'+S.long.map(e).join("・")+'</b></span><span>▼ <b>'+S.short.map(e).join("・")+'</b></span>'
    +(p?'<span>'+e(S.main_label)+' 累積 <b>'+(p.cum>=0?"+":"")+(p.cum*100).toFixed(1)+'%</b>（'+p.n+'日）</span>':'')+'</div>';
  document.getElementById("llbody").innerHTML=h;
  document.getElementById("llupd").textContent="更新 "+S.created;
}).catch(function(){});
})();</script>"""


# トップから開く日米リードラグのページ。公開先（jp-us-leadlag、同じ github.io）の最新ページを読み込み、
# このページ自体の中身として表示する（iframe は iPhone で高さが崩れ、下部が黒くなるため使わない）。
# 同じサイト内のページなので、ホーム画面に追加したアプリから開いても別ブラウザ（上に URL が出る画面）にならない。
# 中身は毎朝 7:30 に更新される公開ページそのものなので、このトップの公開（夕方）を待たずに最新が出る。
LEADLAG_PAGE = r"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>日米リードラグ予想 | 東証 株分析</title>
<script>(function(){var d=document.documentElement,t;try{t=localStorage.getItem('fdb-theme')}catch(e){}
if(t==='dark'||t==='light')d.setAttribute('data-theme',t)})();</script>
<style>body{font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans",sans-serif;padding:24px 16px;color:#52514e;background:#f6f7fb}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) body{background:#000;color:#8f8e88}}
:root[data-theme="dark"] body{background:#000;color:#8f8e88}
a{color:#2a78d6}</style></head><body>
<p id="msg">読み込み中…</p>
<script>(function(){
var SRC="__URL__", HOME=new URL("./index.html", location.href).href;
var BAR='<div style="max-width:560px;margin:0 auto 6px;padding:4px 4px 0">'
  +'<a href="'+HOME+'" style="color:var(--muted);text-decoration:none;font-size:14px">‹ トップ</a></div>';
fetch(SRC+"index.html",{cache:"no-store"}).then(function(r){if(!r.ok)throw 0;return r.text()}).then(function(h){
  h=h.replace(/<head>/i,'<head><base href="'+SRC+'">').replace(/(<body[^>]*>)/i,'$1'+BAR);
  document.open();document.write(h);document.close();
}).catch(function(){
  document.getElementById("msg").innerHTML='読み込めませんでした。<a href="'+SRC+'">予想ページを直接開く</a> ／ <a href="'+HOME+'">トップへ戻る</a>';
});
})();</script>
</body></html>
"""


def leadlag_card():
    """日米業種リードラグ予想（jp-us-leadlag）へのカード。
    中身は作成時点のローカルの要約で埋め、ページを開いたときに公開中の summary.json で差し替える
    （予想は毎朝 7:30 に更新されるが、このトップの公開は夕方のため）"""
    S = {}
    try:
        S = json.load(open(LEADLAG_LOCAL, encoding="utf-8"))
    except Exception:
        pass

    def body(S):
        desc = '<p>前夜の米国業種ETFから、今日の東京の業種の強弱を予想</p>'
        if not S.get("long"):
            return desc
        perf = S.get("perf", {}).get(S.get("main", "SCS"), {})
        pf = (f'<span>{S.get("main_label","")} 累積 <b>{perf["cum"]*100:+.1f}%</b>（{perf["n"]}日）</span>'
              if perf else "")
        word = S["mood"]["word"]
        return (desc
                + f'<div class="kv"><span class="k">{S["target"][5:].replace("-","/")} の地合い</span>'
                + f'<b class="v{" s" if len(word) > 9 else ""}">{word}</b></div>'
                + '<div class="ixs">'
                + f'<span>▲ <b>{"・".join(S["long"])}</b></span>'
                + f'<span>▼ <b>{"・".join(S["short"])}</b></span>{pf}</div>')

    upd = S.get("created", "-")
    return ('<a class="card" id="llcard" href="./leadlag.html">'
            '<div class="t">日米リードラグ予想</div>'
            f'<div id="llbody">{body(S)}</div>'
            f'<div class="ft"><span id="llupd">更新 {upd}</span><span>ひらく →</span></div></a>'
            + LEADLAG_JS.replace("__URL__", LEADLAG_URL))


def group(title, note, *cards):
    """見出しつきのタイル群。タイルが1枚も無ければ見出しごと出さない"""
    body = "\n".join(c for c in cards if c)
    if not body:
        return ""
    return f'<div class="grp">{title} <small>{note}</small></div>\n<div class="grid">\n{body}\n</div>'



def kessan_card():
    """決算カレンダー（kessan.html）を作り、トップのカードを返す。2026-11-24 追加"""
    big, rest = None, ""
    try:
        import make_kessan_cal as KC
        import kessan_cal_page as KP
        KC.build(TMPL[TMPL.index("<script>(function(){var m="):TMPL.index("</style>") + len("</style>")])
        big, rest = KP.card_info(SITE)
    except Exception as ex:
        print(f"決算カレンダーを作れませんでした: {ex}")
    return card("./kessan.html", "決算カレンダー", "", big, rest, f"更新 {mtime(SITE / 'kessan.html')}")

def mtime(p):
    try:
        return datetime.datetime.fromtimestamp(p.stat().st_mtime).strftime("%m/%d %H:%M")
    except OSError:
        return "-"


TMPL = r"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>東証 株分析ホーム</title>
<script>(function(){var m=/[?&#]theme=(dark|light)/.exec(location.search+location.hash),t=m&&m[1];
if(!t){try{t=localStorage.getItem('fdb-theme')}catch(e){}}if(t)document.documentElement.setAttribute('data-theme',t);})();</script>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap">
<style>
/* 2026-11 デザイン刷新：ダーク＝黒、ライト＝白地に黒。色は地・文字・騰落（赤＝上昇／緑＝下落）だけ。数字は Inter の極太 */
:root{--bg:#f3f4f6;--card:#fff;--fg:#0c0d10;--fg2:#3d4148;--mut:#5b6068;--line:#c9ccd2;
--hover:rgba(12,13,16,.05);--acc:#0c0d10;--up:#b91c24;--dn:#08705a;--upb:#c8323a;--dnb:#0f7f63;--sxfg:#0c0d10;--k:.6;color-scheme:light}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){
--bg:#050608;--card:#101216;--fg:#f2f4f8;--fg2:#c6cbd6;--mut:#8f96a3;--line:#23262d;
--hover:rgba(255,255,255,.06);--acc:#5cc8ff;--up:#ff7378;--dn:#3fd0a4;--sxfg:#fff;--k:1;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#050608;--card:#101216;--fg:#f2f4f8;--fg2:#c6cbd6;--mut:#8f96a3;--line:#23262d;
--hover:rgba(255,255,255,.06);--acc:#5cc8ff;--up:#ff7378;--dn:#3fd0a4;--sxfg:#fff;--k:1;color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.55 Inter,"Hiragino Sans","Hiragino Kaku Gothic ProN","Noto Sans JP",system-ui,-apple-system,"Segoe UI",sans-serif;font-variant-numeric:tabular-nums;-webkit-font-smoothing:antialiased}
.wrap{max-width:1180px;margin:0 auto;padding:28px 20px 56px}
header{display:flex;align-items:baseline;justify-content:space-between;gap:8px;flex-wrap:wrap}
h1{font-size:24px;font-weight:800;letter-spacing:.02em;margin:0}
.sub{color:var(--mut);font-size:12px;margin-top:2px}
.btn{border:1px solid var(--line);background:transparent;color:var(--fg);border-radius:8px;padding:5px 11px;font:inherit;font-size:12.5px;cursor:pointer}
.u{color:var(--up)}.d{color:var(--dn)}
.search{position:relative;margin:20px 0 8px}
.search input{width:100%;height:52px;padding:0 2px;font:inherit;font-size:17px;font-weight:700;border:0;border-bottom:3px solid var(--fg);border-radius:0;background:transparent;color:var(--fg);outline:none;-webkit-appearance:none;appearance:none}
.search input::placeholder{color:var(--mut);font-weight:600}
.search input:focus{border-bottom-color:var(--acc)}
#res{margin-top:8px;border-radius:14px;background:var(--card);overflow:hidden}
#res:empty{display:none}
.row{display:flex;align-items:center;gap:10px;padding:10px 14px;border-top:1px solid var(--line)}
.row:first-child{border-top:0}
.row b{font-size:13px;min-width:42px}
.row .nm{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.row small{color:var(--mut);font-size:11.5px}
.row .go{display:flex;gap:6px;flex-shrink:0}
.row .go a{font-size:12px;text-decoration:none;border:1px solid var(--line);border-radius:7px;padding:3px 8px;color:var(--fg)}
.row .go a:hover{border-color:var(--fg)}
/* 見出しとタイル */
.grp{margin-top:40px;padding-top:12px;border-top:3px solid var(--fg);display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;font-size:14px;font-weight:800;letter-spacing:.08em}
.grp small{font-weight:400;letter-spacing:0;color:var(--mut);font-size:12px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:14px;margin-top:14px}
.grid.g5{grid-template-columns:repeat(auto-fill,minmax(200px,1fr))}
.grid.g6{grid-template-columns:repeat(3,minmax(0,1fr))}
.card{display:flex;flex-direction:column;gap:6px;min-height:150px;min-width:0;text-decoration:none;color:inherit;background:var(--card);border-radius:14px;padding:20px 22px 16px;transition:background .15s}
.card:hover{background:color-mix(in srgb,var(--fg) 7%,var(--card))}
.card .t{font-size:16px;font-weight:800;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.card p{margin:0;color:var(--mut);font-size:12px;line-height:1.5}
.kv{display:flex;flex-direction:column;gap:1px;margin-top:8px}
.kv .k{font-size:11.5px;color:var(--mut)}
.kv .v{font-size:28px;font-weight:800;letter-spacing:-.03em;line-height:1.15}
.kv .v.s{font-size:17px;letter-spacing:0;line-height:1.35}
.ixs{display:flex;flex-wrap:wrap;gap:2px 12px;margin-top:4px;font-size:12px;color:var(--mut)}
.ixs b{color:var(--fg);font-weight:700}.ixs b.u{color:var(--up)}.ixs b.d{color:var(--dn)}
/* カードの見せ方：text＝見出し＋1行だけ、info＝見出し・1行・強調の数字・補足2行。高さをそろえる */
.cards-text .card .kv,.cards-text .card .ixs{display:none}
.cards-text .card{min-height:118px}
.card p{display:-webkit-box;-webkit-line-clamp:1;-webkit-box-orient:vertical;overflow:hidden}
.cards-info .card{min-height:214px}
.cards-info .card .ixs{max-height:38px;overflow:hidden}
.card .ft{margin-top:auto;padding-top:10px;display:flex;justify-content:space-between;align-items:center;gap:8px;color:var(--mut);font-size:11.5px}
.card .ft span:last-child{color:var(--fg);font-weight:700;font-size:12px;white-space:nowrap}
#llbody{display:flex;flex-direction:column;gap:6px}
/* 最上部：今日の地合い・株価指数・業種別の騰落率 */
.hero{display:flex;flex-wrap:wrap;gap:14px;margin-top:22px}
.hero>.hA{flex:2 1 520px;gap:16px;padding:22px 24px}
.hero>.hB{flex:1 1 300px;gap:0;padding:22px 24px 16px}
.hl{font-size:12px;font-weight:800;letter-spacing:.1em;display:flex;flex-wrap:wrap;justify-content:space-between;align-items:baseline;gap:4px 12px}
.hl span{font-weight:400;letter-spacing:0;color:var(--mut)}
.hB .hl{margin-bottom:10px}
.hrow{display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:space-between;gap:8px 24px}
.hbig{font-size:clamp(60px,9vw,112px);font-weight:800;letter-spacing:-.045em;line-height:.95}
.hcnt{display:flex;flex-wrap:wrap;gap:2px 16px;font-size:13px;color:var(--mut)}.hcnt b{color:var(--fg);font-weight:800}
.bar{display:flex;gap:2px;height:12px;overflow:hidden}.bar i{display:block;min-width:0}
.bar .bu{background:var(--upb)}.bar .bd{background:var(--dnb)}.bar .bn{background:var(--line)}
.bar.s{height:6px;flex:1 1 auto}
.mks{display:flex;flex-direction:column;gap:10px}
.mk{display:flex;align-items:center;gap:12px}
.mk .mn{flex:0 0 92px;font-size:12.5px;color:var(--mut)}
.mk b{flex:0 0 66px;font-size:15px;font-weight:800;letter-spacing:-.02em}
.mk .mc{flex:0 0 74px;text-align:right;font-size:12px;color:var(--mut)}
.ix{display:flex;align-items:baseline;gap:10px;padding:8px 0;border-top:1px solid var(--line)}
.ix span{font-size:13px;color:var(--mut)}.ix small{font-size:11px;margin-left:6px}
.ix b{margin-left:auto;font-size:18px;font-weight:800;letter-spacing:-.02em}
.ix em{flex:0 0 64px;text-align:right;font-style:normal;font-size:13px;font-weight:700}
.strip{margin-top:14px;gap:14px;min-height:0;padding:22px 24px}
.sxs{display:grid;grid-template-columns:repeat(auto-fill,minmax(98px,1fr));gap:4px}
.sx{min-height:54px;min-width:0;padding:7px 9px;border-radius:6px;color:var(--sxfg);display:flex;flex-direction:column;justify-content:space-between;gap:2px}
.sx.su{background:color-mix(in srgb,var(--upb) calc(var(--p)*var(--k)*1%),var(--card))}
.sx.sd{background:color-mix(in srgb,var(--dnb) calc(var(--p)*var(--k)*1%),var(--card))}
.sx span{font-size:11.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sx b{font-size:15px;font-weight:800;letter-spacing:-.02em}
/* マーケット概況（最上部。make_market.py の要約） */
.mkt{margin-top:22px;gap:14px;min-height:0;padding:22px 24px}
.mkt .mh{font-size:20px;font-weight:800;line-height:1.4;letter-spacing:.01em}
.mis{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:1px;background:var(--line);border:1px solid var(--line);border-radius:10px;overflow:hidden}
.mi{background:var(--card);padding:9px 11px;display:flex;flex-direction:column;gap:1px;min-width:0}
.mi span{font-size:11.5px;color:var(--mut);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.mi b{font-size:16px;font-weight:800;letter-spacing:-.02em}
.mi em{font-style:normal;font-size:12px;font-weight:700}
.mps{display:flex;flex-direction:column;gap:10px}
.mmore{display:flex;flex-direction:column;gap:10px}
.mpp{font-size:13.5px;line-height:1.85;color:var(--fg2)}
.mpp b{color:var(--fg);font-weight:700}.mpp b.u{color:var(--up)}.mpp b.d{color:var(--dn)}
.mpp .ph{display:inline-block;margin-right:10px;padding:0 8px;border:1px solid var(--line);border-radius:6px;font-size:11.5px;font-weight:800;color:var(--fg);line-height:1.7;vertical-align:1px}
.mv{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px 24px;margin-top:4px}
.mvh{font-size:11.5px;font-weight:800;letter-spacing:.06em;padding-bottom:4px}
.mvc a{display:flex;align-items:baseline;gap:10px;padding:5px 0;border-top:1px solid var(--line);text-decoration:none;color:inherit;font-size:13px}
.mvc a:hover span{text-decoration:underline}
.mvc a b{flex:0 0 52px;font-weight:800}.mvc a span{flex:1;min-width:0;color:var(--fg2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mvc a em{font-style:normal;font-weight:800}
.mnews{margin:2px 0 4px}.mnews .mvh small{font-weight:400;letter-spacing:0;color:var(--mut);margin-left:10px}
.mnews a{display:flex;align-items:baseline;gap:12px;padding:6px 0;border-top:1px solid var(--line);text-decoration:none;color:inherit;font-size:13.5px;line-height:1.6}
.mnews a time{flex:0 0 78px;color:var(--mut);font-size:12px}.mnews a span{flex:1;min-width:0;font-weight:600}
.mnews a em{flex:0 0 auto;max-width:170px;font-style:normal;color:var(--mut);font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.mnews a:hover span{text-decoration:underline}
.mbtn{display:none;align-self:flex-start}
@media(max-width:760px){.mkt{margin-top:16px;padding:16px 14px;gap:12px}.mkt .mh{font-size:16.5px}
.mis{grid-template-columns:repeat(3,minmax(0,1fr))}.mi{padding:7px 8px}.mi b{font-size:14px}.mi em{font-size:11px}.mi span{font-size:10.5px}
.mpp{font-size:13px;line-height:1.8}.mv{grid-template-columns:1fr}
.mnews a{flex-wrap:wrap;gap:0 10px;font-size:13px}.mnews a span{flex:1 1 100%;order:3}.mnews a time{flex:0 0 auto}.mnews .mvh small{display:block;margin:2px 0 0}
.mbtn{display:inline-block}.mkt:not(.open) .mmore{display:none}}
/* 概況に地合い・指数・業種をまとめた1枚（KB_MKT=merged） */
a.mis{text-decoration:none;color:inherit}
.mig{grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;background:transparent;border:0;border-radius:0;overflow:visible}.mt{border:1px solid var(--line);border-radius:12px;padding:10px 12px 9px;gap:2px;transition:background .15s}a.mis .mt:hover{background:color-mix(in srgb,var(--fg) 5%,var(--card))}.mt .nm{display:flex;align-items:baseline;gap:6px;font-size:12px;font-weight:700;color:var(--fg2);white-space:nowrap;overflow:hidden}.mt .nm span{font-size:12px;color:var(--fg2);overflow:hidden;text-overflow:ellipsis}.mt .nm small{font-size:10.5px;color:var(--mut);font-weight:600}.mt .pc{align-self:flex-start;font-size:24px;font-weight:800;letter-spacing:-.03em;line-height:1.2}.mt .pc i{font-style:normal;font-size:14px;margin-left:1px}.mt .pc.x{color:#fff;border-radius:7px;padding:0 7px}.mt .pc.x.u{background:var(--upb)}.mt .pc.x.d{background:var(--dnb)}.mt svg{display:block;width:100%;height:auto;margin-top:4px;overflow:visible}.mt svg .fu{fill:var(--upb);fill-opacity:calc(.18 + .1*var(--k))}.mt svg .fd{fill:var(--dnb);fill-opacity:calc(.18 + .1*var(--k))}.mt svg .pv{stroke:var(--mut);stroke-width:1;stroke-dasharray:3 3}.mt svg .ln{fill:none;stroke:var(--fg);stroke-width:1.4;stroke-linejoin:round}.mt svg .dt{fill:var(--fg)}.mt svg text{font-size:9.5px;font-weight:700;fill:var(--mut)}.mt .tm{display:flex;justify-content:space-between;padding-right:20%;font-size:9.5px;color:var(--mut);margin-top:1px}.mt .nos{height:52px}.mt .cv{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;margin-top:3px}.mt .cv b{font-size:15px;font-weight:800;letter-spacing:-.02em}.mt .cv em{font-style:normal;font-size:12px;font-weight:700}@media(max-width:700px){.mig{grid-template-columns:repeat(2,minmax(0,1fr));gap:6px}.mt{padding:8px 9px 7px}.mt .pc{font-size:20px}.mt .cv b{font-size:13.5px}.mt .cv em{font-size:11px}.mt svg text{font-size:14px}.mt .tm{font-size:9px}}
.msec{display:flex;flex-direction:column;gap:10px;padding-top:12px;border-top:1px solid var(--line)}
.mst{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 10px;font-size:12.5px;color:var(--mut)}
.mst .ph{display:inline-block;padding:0 8px;border:1px solid var(--line);border-radius:6px;font-size:11.5px;font-weight:800;color:var(--fg);line-height:1.7}
.mst .mlk{margin-left:auto;color:var(--fg);font-weight:700;font-size:12px;text-decoration:none;white-space:nowrap}.mst .mlk:hover{text-decoration:underline}
.mgrow{display:flex;align-items:center;gap:10px 28px;flex-wrap:wrap}
.mgbig{font-size:46px;font-weight:800;letter-spacing:-.04em;line-height:1}
.mgr{flex:1 1 320px;display:flex;flex-direction:column;gap:8px;min-width:0}
.mk2{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px 36px}
.mgd a.sxs{text-decoration:none}
@media(max-width:760px){.mgbig{font-size:36px}.mk2{grid-template-columns:1fr}.mst .mlk{margin-left:0}}
/* 目次の付箋（2026-11-16）。選んだ付箋の中身だけを出す。付箋の列は画面の上に貼りつく */
.tabs{position:sticky;top:0;z-index:20;display:flex;gap:4px;margin:18px -2px 0;padding:8px 2px 0;background:var(--bg);border-bottom:3px solid var(--fg);overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:none}
.tabs::-webkit-scrollbar{display:none}.tabs:empty{display:none}
.tab{flex:0 0 auto;white-space:nowrap;border:0;border-radius:10px 10px 0 0;padding:10px 18px 9px;font:inherit;font-size:14px;font-weight:800;letter-spacing:.04em;cursor:pointer;color:var(--mut);background:color-mix(in srgb,var(--fg) 8%,var(--bg))}
.tab:hover{color:var(--fg)}
.tab.on{background:var(--fg);color:var(--bg)}
.tp>.grp:first-child{margin-top:16px;padding-top:0;border-top:0}
.tp>.grp:first-child{font-size:0;letter-spacing:0}.tp>.grp:first-child small{font-size:12px}
.tp>.mkt:first-child,.tp>.hero:first-child{margin-top:16px}
@media(max-width:640px){.tabs{margin-top:12px}.tab{padding:9px 13px 8px;font-size:13px}.tp>.grp:first-child{margin-top:10px}.tp>.mkt:first-child,.tp>.hero:first-child{margin-top:10px}}
/* お気に入り・注記 */
.sec{margin-top:40px;padding-top:12px;border-top:3px solid var(--fg);font-size:14px;font-weight:800;letter-spacing:.08em}
.sec small{font-weight:400;letter-spacing:0;color:var(--mut);font-size:12px}
.links{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
.links a{font-size:12.5px;text-decoration:none;border-radius:8px;padding:6px 11px;color:var(--fg);background:var(--card);font-weight:600}
.links a:hover{background:color-mix(in srgb,var(--fg) 7%,var(--card))}
#fav:empty::before{content:"チャート一覧の ★ で登録した銘柄がここに出ます";color:var(--mut);font-size:12.5px}
.note{margin-top:28px;color:var(--mut);font-size:11.5px}
/* 監視銘柄 */
#watch{margin-top:18px}
#watch .hd{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:13px;font-weight:700;color:var(--fg2)}
#watch .hd small{font-weight:400;color:var(--mut)}
#watch .hd .btn{margin-left:auto;padding:3px 9px;font-size:12px}
.badge{display:inline-block;background:var(--upb);color:#fff;border-radius:99px;font-size:11px;font-weight:700;padding:1px 8px}
#wl{margin-top:8px;border-radius:14px;background:var(--card);overflow:hidden}
.wr{display:grid;grid-template-columns:minmax(150px,210px) 1fr auto;gap:6px 12px;align-items:center;padding:10px 14px;border-top:1px solid var(--line)}
.wr:first-child{border-top:0}
.wr.isnew{background:var(--hover)}
.wr .nm a{color:var(--fg);text-decoration:none;font-weight:700}.wr .nm a:hover{text-decoration:underline}
.wr .nm small{display:block;color:var(--mut);font-size:11.5px;font-weight:400}
.wr .lv{display:flex;flex-wrap:wrap;gap:4px 6px}
.wl{font-size:12px;padding:2px 8px;border-radius:7px;border:1px solid var(--line);white-space:nowrap;color:var(--fg2)}
.wl b{color:var(--fg)}
.wl.hitB{background:var(--acc);border-color:var(--acc);color:var(--bg)}.wl.hitR{background:var(--upb);border-color:var(--upb);color:#fff}.wl.hitB b{color:var(--bg)}.wl.hitR b{color:#fff}
.wl.skip{text-decoration:line-through;opacity:.7}.wl.wait{border-style:dashed}
.wl .new{font-size:10px;font-weight:800;margin-left:4px}
.wr .x{border:0;background:transparent;color:var(--mut);font-size:16px;cursor:pointer;padding:2px 6px}.wr .x:hover{color:var(--up)}
#wl .empty{padding:10px 14px;color:var(--mut);font-size:12.5px}
@media(max-width:640px){.wr{grid-template-columns:1fr auto}.wr .lv{grid-column:1/-1;grid-row:2}}
@media(max-width:640px){.wrap{padding:16px 12px 40px}h1{font-size:19px}
.search input{height:46px;font-size:16px}
.grid,.grid.g5{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-top:10px}.grp,.sec{margin-top:28px}
.card{padding:13px 13px 11px;border-radius:12px;min-height:0;gap:4px}
.card .t{font-size:13.5px;line-height:1.3}
.card p{font-size:11.5px;line-height:1.45;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.cards-text .card,.cards-info .card{min-height:0}.cards-info .card .ixs{max-height:50px}
.kv{margin-top:4px}.kv .k{font-size:10.5px}.kv .v{font-size:21px}.kv .v.s{font-size:13.5px}
.card .ixs{flex-direction:column;gap:1px;font-size:11.5px;line-height:1.45}
.card .ft{font-size:10.5px;padding-top:6px}.card .ft span:last-child{display:none}
#llbody{gap:4px}
.hero{gap:8px;margin-top:16px}.hero>.hA,.hero>.hB{flex-basis:100%;padding:16px 14px 14px}
.hero>.hA{gap:12px}.hl{font-size:11px}.hcnt{font-size:12px;gap:2px 12px}
.strip{margin-top:8px;padding:16px 14px}
.mk{gap:8px}.mk .mn{flex-basis:78px;font-size:11.5px}.mk b{flex-basis:56px;font-size:13.5px}.mk .mc{flex-basis:60px;font-size:11px}
.ix b{font-size:16px}
.sxs{grid-template-columns:repeat(auto-fill,minmax(76px,1fr))}.sx{min-height:48px;padding:6px 7px}.sx span{font-size:10.5px}.sx b{font-size:13px}}
</style></head><body class="cards-__CARDSTYLE__"><div class="wrap">
<header><div><h1>東証 株分析</h1>
<div class="sub">__COUNT__銘柄 ／ 株価データ最終日 __ASOF__ ／ 更新 __BUILT__</div></div>
<div style="display:flex;gap:8px;align-items:center;flex:0 0 auto"><a class="btn" href="https://shigehiro04-maker.github.io/us-charts/" title="米国株分析（us-charts）へ" style="text-decoration:none;display:inline-flex;align-items:center;font-weight:700">米国株分析 →</a><button class="btn" id="theme" type="button">明暗</button></div></header>

<div class="search"><input type="search" id="q" placeholder="銘柄を探す — コード・銘柄名・業種（例: 7203 / トヨタ）" autocomplete="off">
<div id="res"></div></div>

<nav class="tabs" id="tabs" role="tablist" aria-label="目次"></nav>
<section class="tp" id="tab-market" data-tab="マーケット">
__MKT__
__HERO__
</section>
<section class="tp" id="tab-stock" data-tab="銘柄を見る" hidden>
<div class="grp">銘柄を見る <small>個別銘柄の分析・売買判断</small></div>
<div class="grid g5 g6">
<a class="card" id="wcard" href="./watch.html"><div class="t">監視銘柄</div>
<p>タイトル別の一覧表で銘柄情報を確認</p>
<div class="kv"><span class="k">監視中</span><b class="v" id="wbig">なし</b></div>
<div class="ixs"><span id="wsum">一覧表を作って銘柄を入れる</span></div>
<div class="ft"><span id="wcnt">この端末に保存</span><span>ひらく →</span></div></a>
__STOCKCARDS__
</div>
</section>
<section class="tp" id="tab-all" data-tab="市場全体" hidden>
__MARKET__
</section>
<section class="tp" id="tab-macro" data-tab="マクロ・為替" hidden>
__MACRO__
</section>


<p class="note">株価・決算は公開情報をもとに毎営業日自動更新しています。投資判断はご自身でお願いします。</p>
</div>
<script src="./one/assets/watch.js"></script>
<script>
const S=__DATA__;  // [code,name,market,sector]
const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const norm=s=>s.normalize('NFKC').toLowerCase();
const IX=S.map(x=>norm(x.join(' ')));
function row(x){return `<div class="row"><b>${esc(x[0])}</b><span class="nm">${esc(x[1])} <small>${esc(x[2])}・${esc(x[3])}</small></span>
<span class="go"><a href="./one/${esc(x[0])}.html">分析</a><a href="./${esc(x[0])}.html">チャート</a></span></div>`}
function show(){const q=norm($('q').value.trim());if(!q){$('res').innerHTML='';return;}
 const t=q.split(/\s+/),out=[];for(let i=0;i<S.length&&out.length<12;i++){if(t.every(w=>IX[i].includes(w)))out.push(S[i]);}
 $('res').innerHTML=out.map(row).join('')||'<div class="row"><small>見つかりません</small></div>';}
$('q').addEventListener('input',show);
$('q').addEventListener('keydown',e=>{if(e.key==='Enter'){const a=$('res').querySelector('a');if(a)location.href=a.href;}});
// 監視銘柄カード（タイトル別の一覧表。one/assets/watch.js）
(function(){const K=window.KW;if(!K)return;const L=K.lists();
 if(!L.length){$('wcnt').textContent='まだありません・この端末に保存';return;}
 $('wcnt').textContent='この端末に保存';$('wbig').textContent=L.length+'表・'+K.count()+'銘柄';
 $('wsum').textContent=L.map(l=>l.ix?l.t:l.t+'（'+l.c.length+'）').slice(0,8).join('、')+(L.length>8?' ほか':'');})();
// 目次の付箋：マーケット／銘柄を見る／市場全体／マクロ・為替。最後に選んだ付箋をこの端末に保存。index.html#stock などで直接開ける
(function(){const tb=$('tabs');if(!tb)return;
 const P=[...document.querySelectorAll('.tp')].filter(p=>p.querySelector('a,section,.card'));
 document.querySelectorAll('.tp').forEach(p=>{if(!P.includes(p))p.remove();});
 if(P.length<2){tb.remove();P.forEach(p=>p.hidden=false);return;}
 const KEY='home-tab-'+(location.pathname.split('/')[1]||'');
 tb.innerHTML=P.map(p=>`<button type="button" class="tab" role="tab" data-id="${p.id}">${esc(p.dataset.tab)}</button>`).join('');
 const set=(id,jump)=>{if(!P.some(p=>p.id===id))id=P[0].id;
  P.forEach(p=>p.hidden=p.id!==id);
  tb.querySelectorAll('.tab').forEach(b=>{const on=b.dataset.id===id;b.classList.toggle('on',on);b.setAttribute('aria-selected',on);});
  try{localStorage.setItem(KEY,id)}catch(e){}
  if(jump&&scrollY>tb.offsetTop)scrollTo({top:tb.offsetTop});};
 let first=(location.hash||'').replace('#','');first=first?'tab-'+first:'';
 if(!first){try{first=localStorage.getItem(KEY)||''}catch(e){}}
 set(first,false);
 tb.addEventListener('click',e=>{const b=e.target.closest('.tab');if(b){set(b.dataset.id,true);history.replaceState(null,'','#'+b.dataset.id.slice(4));}});
 addEventListener('hashchange',()=>{const h=location.hash.replace('#','');if(h)set('tab-'+h,true);});})();
// マーケット概況：スマホでは主要指数の段落だけ出し、続きはボタンで開く（開閉はこの端末に保存）
(function(){const m=$('mkt'),b=$('mkbtn');if(!m||!b)return;let o=false;try{o=localStorage.getItem('home-mkt-open')==='1'}catch(e){}
 const set=v=>{m.classList.toggle('open',v);b.textContent=v?'たたむ':(m.classList.contains('mgd')?'続きを表示（個別銘柄・為替商品・決算予定・値上がり値下がり上位）':'続きを表示（騰落・業種・個別銘柄・為替商品・決算予定）');};set(o);
 b.addEventListener('click',()=>{o=!o;set(o);try{localStorage.setItem('home-mkt-open',o?'1':'0')}catch(e){}});})();
$('theme').addEventListener('click',()=>{const d=document.documentElement;
 const cur=d.getAttribute('data-theme')||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');
 const n=cur==='dark'?'light':'dark';d.setAttribute('data-theme',n);try{localStorage.setItem('fdb-theme',n)}catch(e){}});
</script></body></html>"""


# 以下の WATCH_TMPL・WATCH_LIST_JS は 2026-11-15 から未使用（監視銘柄は make_watch.py）。変更前は make_home.py.pre_lists
WATCH_TMPL = r"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>監視銘柄一覧 | 東証 株分析</title>
__HEAD__
</head><body><div class="wrap">
<header><div><h1><a href="./index.html" title="トップへ" style="text-decoration:none;color:inherit;margin-right:8px">‹</a>監視銘柄一覧</h1>
<div class="sub">「☆ 監視に追加」した時点の IN・利確・損切りに、その後の株価が来たか（日足の高値・安値、毎営業日の更新後に反映）</div></div>
<button class="btn" id="theme" type="button">明暗</button></header>
<section id="watch" hidden><div class="hd"><span id="wnew"></span><small id="wsub"></small><button class="btn" id="wackall" hidden>すべて確認済みにする</button></div>
<div id="wl"></div></section>
<p class="note">極端な急騰・急落（前日終値から ATR(14) の3倍超）の日に到達した水準は「急変で通過」として数えません。
追加時点で既に水準の先にあった場合は、いったん離れてから来たときに到達とします。監視銘柄はこの端末（ブラウザ）に保存されます。</p>
</div>
<script src="./one/assets/watch.js"></script>
<script>
const S=__DATA__;
const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
__LISTJS__$('theme').addEventListener('click',()=>{const d=document.documentElement;
 const cur=d.getAttribute('data-theme')||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');
 const n=cur==='dark'?'light':'dark';d.setAttribute('data-theme',n);try{localStorage.setItem('fdb-theme',n)}catch(e){}});
</script></body></html>"""

WATCH_LIST_JS = r"""// 監視銘柄（株式分析ダッシュボードの「☆ 監視に追加」。判定は one/assets/watch.js）
function drawWatch(){const K=window.KW,box=$('watch');if(!K)return;box.hidden=false;
 const W=K.list(),by={};S.forEach(x=>by[x[0]]=x);
 const dd=s=>s?s.slice(5).replace('-','/'):'',n0=v=>v==null?'―':Number(v).toLocaleString('ja-JP',{maximumFractionDigits:1});
 const val=s=>s.dir==='zone'?n0(s.lo)+'〜'+n0(s.hi):n0(s.p);
 if(!W.length){$('wl').innerHTML='<div class="empty">株式分析ダッシュボードの各銘柄で「☆ 監視に追加」を押すと、その時点の IN・利確・損切りの値段を記録し、到達したらここに表示します（この端末に保存）。</div>';
  $('wnew').innerHTML='';$('wsub').textContent='';$('wackall').hidden=true;return;}
 $('wsub').textContent=W.length+'銘柄・日足の高値・安値で判定（毎営業日の更新後に反映）';
 $('wl').innerHTML=W.map(w=>`<div class="wr" id="w-${esc(w.code)}"><div class="nm"><a href="./one/${esc(w.code)}.html">${esc(w.code)} ${esc(w.name)}</a><small>${dd(w.asof)}の目安で監視・読み込み中…</small></div><div class="lv"></div>
  <button class="x" title="監視をやめる" data-c="${esc(w.code)}">×</button></div>`).join('');
 $('wl').querySelectorAll('.x').forEach(b=>b.onclick=()=>{if(confirm(b.dataset.c+' の監視をやめますか？')){K.remove(b.dataset.c);drawWatch();}});
 let nNew=0,done=0;const evs={};
 const fin=()=>{$('wnew').innerHTML=nNew?`<span class="badge">新たに到達 ${nNew}件</span>`:'';$('wackall').hidden=!nNew;};
 W.forEach(w=>K.loadPx(w.code,'./one/').then(P=>{const ev=K.evaluate(w,P),row=$('w-'+w.code);evs[w.code]=ev;
   const nw=ev.levels.filter(s=>K.isNew(w,s)).length;nNew+=nw;row.classList.toggle('isnew',nw>0);
   const last=ev.last,chg=w.px?(last.c/w.px-1)*100:null;
   row.querySelector('small').textContent=`${dd(w.asof)}の目安（当時 ${n0(w.px)}円）→ 現在 ${n0(last.c)}円${chg==null?'':'（'+(chg>=0?'+':'')+chg.toFixed(1)+'%）'}・${dd(last.d)}終値`;
   row.querySelector('.lv').innerHTML=ev.levels.map(s=>{
    if(s.state==='hit')return `<span class="wl ${s.k==='stop'?'hitR':'hitB'}">${s.label} <b>${val(s)}</b> ${dd(s.date)}到達${K.isNew(w,s)?'<span class="new">NEW</span>':''}</span>`;
    if(s.state==='skipped')return `<span class="wl skip" title="極端な値動きの日（前日終値からATRの3倍超）に通過したため数えていません">${s.label} ${val(s)} 急変で通過 ${dd(s.date)}</span>`;
    return `<span class="wl${s.state==='wait'?' wait':''}" title="${s.state==='wait'?'追加時点で既にこの水準の先にあったため、いったん離れてから判定します':'未到達'}">${s.label} <b>${val(s)}</b></span>`;}).join('')
    +(ev.extreme.length?`<span class="wl" title="この期間に前日終値からATRの3倍を超えて動いた日">急変日 ${ev.extreme.map(x=>dd(x.d)+'('+(x.chg>=0?'+':'')+x.chg.toFixed(1)+'%)').join('・')}</span>`:'');
  }).catch(()=>{const row=$('w-'+w.code);if(row)row.querySelector('small').textContent='株価を読み込めませんでした';}).finally(()=>{if(++done===W.length)fin();}));
 $('wackall').onclick=()=>{W.forEach(w=>{if(evs[w.code])K.ack(w.code,evs[w.code].levels);});drawWatch();};}
drawWatch();
"""


def main():
    PREVIEW = os.environ.get("KB_HOME_OUT")   # 見本用：公開フォルダには書かず、このファイルだけ作る
    n = 0
    if not PREVIEW:
        n = sync_one()
        link_usdjpy()
        sync_gyoseki()
    rows = []
    try:
        rows = json.load(open(SITE / "_summary.json", encoding="utf-8"))
    except Exception:
        pass
    data = [[r.get("code", ""), r.get("name", ""), r.get("mk", ""), r.get("sc", "")] for r in rows]
    asof = max((r.get("date", "") for r in rows), default="-")
    usd = usd_card()
    top, has_heat, has_idx = hero()
    mkt = market_overview()
    # merged：概況に地合い・主要指数・業種をまとめた1枚にする（環境変数 KB_MKT=split で従来の3枚）。
    # 「市場全体」の付箋には、ヒートマップと主要指数ダッシュボードのカードを出す
    if os.environ.get("KB_MKT", MKT_STYLE) == "merged":
        mg = market_merged()
        if mg:
            mkt, top, has_heat, has_idx = mg, "", False, False
    page = (TMPL.replace("__DATA__", json.dumps(data, ensure_ascii=False, separators=(",", ":")))
            .replace("__COUNT__", f"{len(rows):,}").replace("__ASOF__", asof)
            .replace("__BUILT__", datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
            .replace("__T_ONE__", mtime(ONE_DST / "index.html"))
            .replace("__T_CHARTS__", mtime(SITE / "charts.html"))
            .replace("__T_FUND__", mtime(SITE / "fundamentals.html"))
            .replace("__T_SIG__", mtime(SITE / "signals.html"))
            .replace("__MKT__", mkt)
            .replace("__HERO__", top).replace("__CARDSTYLE__", CARD_STYLE)
            .replace("__STOCKCARDS__", kessan_card() + "\n" + stock_cards(rows))
            .replace("__MARKET__", group("市場全体を見る", "指数・業種・需給の地合い",
                                         "" if has_heat else heatmap_card(), "" if has_idx else indices_card(),
                                         jukyu_card(), valuation_card(), sector_card(), leadlag_card(), nikkei_card(), gap_card(), sector_mom_card()))
            .replace("__MACRO__", group("マクロ・為替", "金利差・為替の方向感", usd)))
    if PREVIEW:
        Path(PREVIEW).parent.mkdir(parents=True, exist_ok=True)
        Path(PREVIEW).write_text(page.replace('href="./', 'href="' + SITE.as_uri() + '/').replace('src="./', 'src="' + SITE.as_uri() + '/'), encoding="utf-8")
        print(f"見本を作成: {PREVIEW}")
        return
    (SITE / "index.html").write_text(page, encoding="utf-8")
    (SITE / "leadlag.html").write_text(LEADLAG_PAGE.replace("__URL__", LEADLAG_URL), encoding="utf-8")
    # 監視銘柄（タイトル別の一覧表。2026-11-15 から make_watch.py で作る）
    head = TMPL[TMPL.index("<script>(function(){var m="):TMPL.index("</style>") + len("</style>")]
    try:
        import make_watch
        make_watch.build(head)
    except Exception as ex:
        print(f"監視銘柄ページを作れませんでした: {ex}")
    print(f"トップ画面を作成: {SITE/'index.html'}（ダッシュボード {n} ファイルを更新）")


if __name__ == "__main__":
    main()
