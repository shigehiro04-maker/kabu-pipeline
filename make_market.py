#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
マーケット概況（トップ画面＝目次の最上部に出す、株価データの日付の東京株式市況）を作る。米国版（~/米国株分析/make_market.py）と同じ作り。

  入力（通信なし）
    株価指数/data/{nikkei225,topix,nikkei_vi}.csv  日経平均・TOPIX・日経平均VI（株価指数/run_indices.sh）
    data/market/<キー>.csv              米国の指数・金利・為替・商品（fetch_market.py）
    data/market/news.json               ニュースの見出し（fetch_news.py）
    data/charts/heatmap_summary.json    値上がり・値下がり銘柄数、業種別の騰落率（ヒートマップと同じ数字）
    data/charts/_summary.json           銘柄・市場・業種・25日線乖離
    data/prices/<コード>.csv            52週高値・安値の更新、売買代金
    fundamentals/fundamentals_latest.csv 時価総額
    make_watch._earnings()               今後の決算発表（JPX の決算発表予定日）
  出力
    data/charts/market_summary.json     make_home.py が読んでカードにする

  文章は数字から決まった言い回しで組み立てる。値動きの背景はニュースの見出し（リンク）で補う。
  run_daily.sh のヒートマップ・株価指数の後、トップ画面の前に呼ぶ。数秒。
"""
import csv, datetime, json, os, re, sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
SITE = BASE / "data" / "charts"
MKT = BASE / "data" / "market"
PRICES = BASE / "data" / "prices"
WD = "月火水木金土日"

JA = {}


def num(s):
    try:
        v = float(s)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def series(key):
    """[(日付, 終値)]（古い順）"""
    out = []
    p = MKT / f"{key}.csv"
    if key in ("nikkei225", "topix", "nikkei_vi"):      # 株価指数ダッシュボードのデータ（Date,Open,High,Low,Close,…）
        p = BASE / "株価指数" / "data" / f"{key}.csv"
    try:
        with open(p, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                c = num(r.get("close") or r.get("Close"))
                d = (r.get("date") or r.get("Date") or "")[:10]
                if c and c > 0 and d:
                    out.append((d, c))
    except FileNotFoundError:
        pass
    return out


def upto(s, asof):
    """asof 以前の行だけ"""
    return [x for x in s if x[0] <= asof]


def streak(cl):
    """終値の並びから「3日続落」「4日ぶりに反発」などの言い回しと、続いた日数を返す"""
    d = [(1 if cl[i] > cl[i - 1] else -1 if cl[i] < cl[i - 1] else 0) for i in range(1, len(cl))]
    if not d or d[-1] == 0:
        return "横ばい", 0
    s, n = d[-1], 0
    for x in reversed(d):
        if x != s:
            break
        n += 1
    if n >= 2:
        return f"{n}日{'続伸' if s > 0 else '続落'}", n * s
    m = 0
    for x in reversed(d[:-1]):
        if x != -s:
            break
        m += 1
    w = "反発" if s > 0 else "反落"
    return (f"{m + 1}日ぶりに{w}" if m >= 2 else w), s


def index_info(key, name, asof, unit="", nd=2):
    s = upto(series(key), asof)
    if len(s) < 3:
        return None
    cl = [c for _, c in s]
    c, p = cl[-1], cl[-2]
    st, sn = streak(cl[-40:])
    y0 = [x for d, x in s if d < asof[:4] + "-01-01"]
    return {"k": key, "name": name, "date": s[-1][0], "close": c, "prev": p, "chg": c - p, "pct": (c / p - 1) * 100,
            "streak": st, "sn": sn, "ath": c >= max(cl), "h52": c >= max(cl[-252:]), "l52": c <= min(cl[-252:]),
            "from_high": (c / max(cl) - 1) * 100, "ytd": (c / y0[-1] - 1) * 100 if y0 else None,
            "unit": unit, "nd": nd, "stale": s[-1][0] != asof}


def tail_rows(path, n=262):
    """株価CSVの末尾 n 行（日付, 高値, 安値, 終値, 出来高）"""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            block = min(size, 80 * n + 4096)
            f.seek(size - block)
            data = f.read().decode("utf-8", "ignore")
    except OSError:
        return []
    lines = data.splitlines()
    if block < size:
        lines = lines[1:]
    out = []
    for ln in lines[-n:]:
        p = ln.split(",")
        if len(p) < 6 or not p[0][:1].isdigit():
            continue
        h, l, c, v = num(p[2]), num(p[3]), num(p[4]), num(p[5])
        if c is None or c <= 0:
            continue
        out.append((p[0], h or c, l or c, c, v or 0.0))
    return out


def short_name(code, name):
    if code in JA:
        return JA[code]
    n = re.sub(r"\s*(American Depositary Shares?|Class [A-C]|Common Stock|Ordinary Shares?).*$", "", name or "", flags=re.I)
    n = re.sub(r",?\s+(Inc\.?|Incorporated|Corporation|Corp\.?|Company|Co\.?|Ltd\.?|Limited|plc|PLC|N\.V\.|S\.A\.|SE|AG|Holdings?|Group)\.?$", "", n.strip())
    n = re.sub(r",?\s+(Inc\.?|Corporation|Corp\.?|Holdings?|Group)\.?$", "", n.strip())
    n = re.sub(r"\s+(Sponsored|Sponosred|Unsponsored|ADR|ADS)\b.*$", "", n.strip(), flags=re.I)
    n = n.strip(" ,") or code
    return n if len(n) <= 26 else code


def sp(v, nd=2, suf="%"):
    """騰落の色つきの数字（赤＝上昇・緑＝下落）"""
    c = "u" if v > 0 else "d" if v < 0 else ""
    return f'<b class="{c}">{v:+,.{nd}f}{suf}</b>'


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def stock_stats(asof):
    """全銘柄の株価から：52週高値・安値の更新、売買代金、時価総額上位の値動き"""
    rows = json.load(open(SITE / "_summary.json", encoding="utf-8"))
    fund = {}
    try:
        with open(BASE / "fundamentals" / "fundamentals_latest.csv", encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                fund[r["コード"]] = (num(r.get("時価総額")), num(r.get("株価")))
    except FileNotFoundError:
        pass
    nh = nl = n = 0
    tv = {}
    S = []
    for r in rows:
        code = r.get("code")
        px = tail_rows(PRICES / f"{code}.csv")
        if len(px) < 2 or px[-1][0] != asof:
            continue
        n += 1
        d, h, l, c, v = px[-1]
        if r.get("mk") == "プライム":                 # 売買代金はプライムの合計
            for dd, _, _, cc, vv in px[-21:]:
                tv[dd] = tv.get(dd, 0.0) + cc * vv
        if len(px) >= 200:
            prev = px[-252:-1]
            if h > max(x[1] for x in prev):
                nh += 1
            if l < min(x[2] for x in prev):
                nl += 1
        mc, fpx = fund.get(code, (None, None))
        mc = mc * c / fpx if mc and fpx else None
        chg = (c / px[-2][3] - 1) * 100
        S.append({"code": code, "name": r.get("name", ""), "sc": r.get("sc", ""), "chg": chg, "mc": mc,
                  "tv": c * v, "dev25": r.get("dev25")})
    days = sorted(d for d in tv if d <= asof)
    tv_today = tv.get(asof, 0.0)
    prev20 = [tv[d] for d in days[-21:-1]]
    tv_avg = sum(prev20) / len(prev20) if prev20 else None
    dv = [s["dev25"] for s in S if s["dev25"] is not None]
    big = sorted([s for s in S if s["mc"]], key=lambda s: -s["mc"])
    return {"n": n, "nh": nh, "nl": nl, "tv": tv_today, "tv_avg": tv_avg,
            "above25": sum(v > 0 for v in dv) / len(dv) * 100 if dv else None,
            "top100": big[:100], "top500": big[:500], "all": S}


def earnings_ahead(asof, big, days=7, k=8):
    """asof の翌日から days 日以内に決算発表を予定する銘柄（JPX が発表した予定日だけ。時価総額の大きい順）"""
    a = datetime.date.fromisoformat(asof)
    mc = {s["code"]: (s["mc"], s["name"]) for s in big}
    out = []
    try:
        sys.path.insert(0, str(BASE))
        import make_watch
        for code, v in make_watch._earnings().items():
            d, kind = v[0], v[1]
            if kind != 1 or str(code) not in mc:
                continue
            dd = d if isinstance(d, datetime.date) else datetime.date.fromisoformat(str(d)[:10])
            if 0 < (dd - a).days <= days:
                out.append((mc[str(code)][0], str(code), dd, mc[str(code)][1]))
    except Exception as ex:
        print(f"決算発表予定日を読めませんでした: {ex}")
    out.sort(reverse=True)
    return sorted(out[:k], key=lambda x: (x[2], -x[0]))


def names(lst, k=3):
    return "、".join(f'{esc(nk(s["name"]))}（{sp(s["chg"], 1)}）' for s in lst[:k])


def nk(s):
    """銘柄名の全角英数・全角空白を半角に（ＴＯＹＯ　ＴＩＲＥ → TOYO TIRE）"""
    import unicodedata
    return unicodedata.normalize("NFKC", s or "")


def build():
    H = json.load(open(SITE / "heatmap_summary.json", encoding="utf-8"))
    asof = str(H.get("asof", ""))[:10]
    ad = datetime.date.fromisoformat(asof)
    day = f"{ad.month}/{ad.day}（{WD[ad.weekday()]}）"
    prev_day = (ad - datetime.timedelta(days=1)).isoformat()      # 海外の指数は前日（現地）の終値まで

    ix = {k: index_info(k, nm, a, u, nd) for k, nm, u, nd, a in [
        ("nikkei225", "日経平均", "円", 2, asof), ("topix", "TOPIX", "", 2, asof), ("nikkei_vi", "日経平均VI", "", 2, asof),
        ("usdjpy", "ドル円", "円", 2, asof), ("dow", "NYダウ", "ドル", 2, prev_day), ("sp500", "S&P500", "", 2, prev_day),
        ("nasdaq", "NASDAQ総合", "", 2, prev_day), ("sox", "SOX指数", "", 2, prev_day), ("us10y", "米10年金利", "%", 3, prev_day),
        ("wti", "WTI原油", "ドル", 2, asof), ("gold", "金", "ドル", 1, asof), ("btc", "ビットコイン", "ドル", 0, asof)]}
    paras = []
    M = H.get("markets") or {}

    # ---- 1) 主要指数
    head = ""
    n = ix.get("nikkei225")
    if n and not n["stale"]:
        mag = "大幅に" if abs(n["pct"]) >= 1.5 else "小幅に" if abs(n["pct"]) < 0.3 else ""
        head = f'日経平均は{mag}{n["streak"]}'
        t = (f'{day}の東京株式市場で、日経平均株価は前日比 {abs(n["chg"]):,.2f}円{"高" if n["chg"] > 0 else "安"}'
             f'（{sp(n["pct"])}）の {n["close"]:,.2f}円と{mag}{n["streak"]}')
        t += ("し、終値で過去最高値を更新した。" if n["ath"] else
              f'した（最高値まであと {abs(n["from_high"]):.1f}%）。' if n["from_high"] > -1.0 else "した。")
        x = ix.get("topix")
        if x and not x["stale"]:
            t += f'TOPIXは {x["close"]:,.2f}（{sp(x["pct"])}）と{x["streak"]}' + ("し、過去最高値を更新した。" if x["ath"] else "。")
        mk = [f'{k} {sp(M[k]["chg"])}' for k in ("プライム", "スタンダード", "グロース") if M.get(k) and M[k].get("chg") is not None]
        if mk:
            t += "市場別（時価総額加重）では " + "、".join(mk) + "。"
        y = [f'{x["name"]} {sp(x["ytd"], 1)}' for x in (n, ix.get("topix")) if x and x["ytd"] is not None]
        if y:
            t += "年初来では " + "、".join(y) + "。"
        paras.append({"h": "主要指数", "t": t})

    # ---- 2) 騰落・売買代金（プライム）
    st = stock_stats(asof)
    A = M.get("プライム") or {}
    if A.get("n"):
        up, dn, nn = A["up"], A["down"], A["n"]
        r = up / max(up + dn, 1) * 100
        if r >= 65:
            w = f"値上がりが全体の{up / nn * 100:.0f}%を占める全面高に近い展開"
        elif r <= 35:
            w = f"値下がりが全体の{dn / nn * 100:.0f}%を占め、幅広い銘柄が売られた"
        elif r >= 55:
            w = "値上がり銘柄がやや多かった"
        elif r <= 45:
            w = "値下がり銘柄がやや多かった"
        else:
            w = "値上がりと値下がりがほぼ同数だった"
        t = f'東証プライム {nn:,}銘柄のうち値上がり <b class="u">{up:,}</b>・値下がり <b class="d">{dn:,}</b> で、{w}。'
        t += f'全市場で52週高値を更新したのは <b>{st["nh"]:,}</b>銘柄、52週安値を更新したのは <b>{st["nl"]:,}</b>銘柄。'
        if st["above25"] is not None:
            t += f'25日移動平均線を上回る銘柄は全体の <b>{st["above25"]:.0f}%</b>。'
        if st["tv"] and st["tv_avg"]:
            ratio = st["tv"] / st["tv_avg"] * 100
            t += (f'プライムの売買代金は概算 <b>{st["tv"] / 1e12:,.2f}兆円</b>で、直近20日平均の <b>{ratio:.0f}%</b>'
                  f'（{"商いは膨らんだ" if ratio >= 115 else "商いは細った" if ratio <= 85 else "ほぼ平均並み"}）。')
        paras.append({"h": "騰落・売買代金", "t": t})

    # ---- 3) 業種（東証33業種・プライム）
    sec = H.get("sectors_prime") or []
    if sec:
        ups = [s for s in sec if s[1] > 0]
        dns = sorted([s for s in sec if s[1] < 0], key=lambda s: s[1])
        f = lambda L: "、".join(f"{esc(s[0])}（{sp(s[1])}）" for s in L)
        t = f"東証{len(sec)}業種のうち上昇は <b>{len(ups)}</b>業種、下落は <b>{len(dns)}</b>業種。"
        if ups:
            t += f"上昇率が大きいのは {f(ups[:3])}。"
        if dns:
            t += f"下落率が大きいのは {f(dns[:3])}。"
        paras.append({"h": "業種", "t": t})
        if head and ups and dns:
            head += f"、{ups[0][0]}が高く{dns[0][0]}が安い"
        elif head and dns:
            head += f"、{dns[0][0]}などが安い"
        elif head and ups:
            head += f"、{ups[0][0]}などが高い"

    # ---- 4) 個別銘柄（時価総額上位）
    movers = {}
    if st["top100"]:
        t100 = sorted(st["top100"], key=lambda s: -s["chg"])
        t500 = sorted(st["top500"], key=lambda s: -s["chg"])
        g, l = [s for s in t100 if s["chg"] > 0], [s for s in reversed(t100) if s["chg"] < 0]
        t = ""
        if g:
            t += f"時価総額上位100社では {names(g)} が高い。"
        if l:
            t += f'{"一方、" if g else "時価総額上位100社では "}{names(l)} が安い。'
        tv5 = sorted(st["all"], key=lambda s: -s["tv"])[:5]
        t += "売買代金の上位は " + names(tv5, 5) + "。"
        paras.append({"h": "個別銘柄", "t": t})
        row = lambda s: [s["code"], nk(s["name"]), round(s["chg"], 2), s["sc"]]
        movers = {"up": [row(s) for s in t500[:5] if s["chg"] > 0],
                  "down": [row(s) for s in reversed(t500[-5:]) if s["chg"] < 0]}

    # ---- 5) 海外・為替・商品
    t = ""
    us = [ix[k] for k in ("dow", "sp500", "nasdaq", "sox") if ix.get(k)]
    if us:
        d0 = datetime.date.fromisoformat(us[0]["date"])
        t += (f'前日（{d0.month}/{d0.day}）の米国市場は ' +
              "、".join(f'{esc(x["name"])} {sp(x["pct"])}' for x in us) + "。")
    x = ix.get("us10y")
    if x:
        t += f'米10年国債利回りは <b>{x["close"]:.2f}%</b>（前日比 {sp(x["chg"], 2, "pt")}）。'
    x = ix.get("usdjpy")
    if x:
        d = x["chg"]
        t += (f'ドル円は1ドル＝<b>{x["close"]:.2f}円</b>'
              + (f'と前日比 {abs(d):.2f}円の{"円安・ドル高" if d > 0 else "円高・ドル安"}（更新時点）。' if abs(d) >= 0.005 else "で横ばい。"))
    cm = []
    for k, lab, nd in (("wti", "WTI原油先物", 2), ("gold", "金先物", 1), ("btc", "ビットコイン", 0)):
        x = ix.get(k)
        if x:
            cm.append(f'{lab}は <b>{x["close"]:,.{nd}f}ドル</b>（{sp(x["pct"])}）')
    if cm:
        t += "、".join(cm) + "。"
    x = ix.get("nikkei_vi")
    if x and not x["stale"]:
        lv = x["close"]
        w = ("強い警戒を示す30を上回っている" if lv >= 30 else "警戒の目安とされる20を上回っている" if lv >= 20
             else "警戒の目安とされる20を下回っている")
        t += f'株価の予想変動率を示す日経平均VIは <b>{lv:.2f}</b>（前日比 {sp(x["chg"], 2, "")}）で、{w}。'
    if t:
        paras.append({"h": "海外・為替・商品", "t": t})

    # ---- 6) 今後の決算発表
    ea = earnings_ahead(asof, st["top500"])
    if ea:
        by = {}
        for _, code, dd, nm in ea:
            by.setdefault(dd, []).append(esc(nk(nm)))
        t = "今後1週間に決算発表を予定する主な銘柄（時価総額上位500社から）：" + \
            "／".join(f'{d.month}/{d.day}（{WD[d.weekday()]}）{"、".join(v)}' for d, v in sorted(by.items())) + "。"
        paras.append({"h": "決算予定", "t": t})

    tiles = []
    for k in ("nikkei225", "topix", "nikkei_vi", "usdjpy", "dow", "sp500", "nasdaq", "sox", "us10y", "wti", "gold", "btc"):
        x = ix.get(k)
        if not x:
            continue
        rate = k == "us10y"
        pt = k in ("nikkei_vi",)
        tiles.append({"k": k, "name": x["name"], "close": x["close"], "nd": 0 if k == "btc" else 2,
                      "suf": "%" if rate else "",
                      "chg": x["chg"] if rate or pt or k == "usdjpy" else x["pct"],
                      "csuf": "pt" if rate else "" if pt else "円" if k == "usdjpy" else "%",
                      "dir": 1 if x["chg"] > 0 else -1 if x["chg"] < 0 else 0,
                      "date": x["date"]})
    news = []
    try:
        import fetch_news
        news = fetch_news.pick(asof)
    except Exception as ex:
        print(f"ニュースの見出しを読めませんでした: {ex}")
    out = {"asof": asof, "day": day, "market": "東京株式市場", "headline": head, "tiles": tiles, "paras": paras,
           "movers": movers, "news": news, "built": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}
    (SITE / "market_summary.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


if __name__ == "__main__":
    o = build()
    print(f'マーケット概況を作成: {o["day"]} {o["headline"]}（見出し {len(o["news"])}件）')
    if "--show" in sys.argv:
        for p in o["paras"]:
            print(f'【{p["h"]}】' + re.sub(r"<[^>]+>", "", p["t"]))
        for x in o["news"]:
            print("・", x["at"], x["t"], "—", x["src"])
