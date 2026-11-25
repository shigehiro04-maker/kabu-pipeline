#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
マーケット概況に添えるニュースの見出しを取る（Google ニュースの RSS・無料・登録なし）。
東証版（~/株分析）と米国版（~/米国株分析）で同じファイル。置いたフォルダの名前で市場を切り替える。

  出力: data/market/news.json（見出し・配信元・リンク・配信時刻。10日分をためる）
  載せるのは見出しとリンクだけ（本文は取らない・載せない）。リンク先は各社の記事。
  make_market.py が pick() で「株価データの日付の引け後に出た市況の見出し」を選ぶ。
  失敗しても前回までの見出しで続ける。数秒。

  手動: ~/株分析/.venv/bin/python fetch_news.py          （取得）
        ~/株分析/.venv/bin/python fetch_news.py 2026-11-13 （その日の概況に選ばれる見出しを表示）
"""
import datetime, email.utils, json, re, sys, time, unicodedata, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

BASE = Path(__file__).resolve().parent
MARKET = "us" if "米国" in BASE.name else "jp"
OUT = BASE / "data" / "market" / "news.json"
JST = datetime.timezone(datetime.timedelta(hours=9))

QUERIES = {
    "us": ["米国株式市場 NYダウ", "NY株 ナスダック 終値", "米国株 ウォール街"],
    "jp": ["東京株式市場 日経平均", "日経平均 大引け", "東証 日経平均 終値"],
}[MARKET]
# 見出しに1つは入っていること（市況の記事に絞る）
CORE = {
    "us": ["NYダウ", "NY株", "米国株", "米株", "米国市場", "ナスダック", "ウォール街", "S&P", "ダウ平均", "ダウ"],
    "jp": ["日経平均", "東証", "東京株", "TOPIX", "大引け", "東京市場", "日本株"],
}[MARKET]
# 米国版では日本株の記事、東証版では米国株だけの記事を外す
OTHER = {"us": ["日経平均", "東証", "東京株", "大引け", "日本株"], "jp": []}[MARKET]
SKIP = ["マレーシア", "香港", "上海", "中国株", "韓国", "インド株", "欧州株", "アジア株", "ベトナム", "台湾株", "仮想通貨", "暗号資産", "FX"]   # 別の市場の記事
WRAP = ["反落", "反発", "続伸", "続落", "ドル安", "ドル高", "円安", "円高", "上昇", "下落", "最高値", "大引け", "終値",
        "急落", "急騰", "急伸", "大幅", "小幅", "高値", "安値", "売り", "買い", "重荷", "嫌気", "好感", "警戒"]
AHEAD = ["見通し", "展望", "予想", "来週", "今週の", "今後", "戦略", "注目銘柄", "おすすめ", "ランキング", "始値", "寄り付き", "前場", "午前", "時台", "始まる", "推移"]
REASON = ["重荷", "嫌気", "好感", "警戒", "懸念", "期待", "受け", "背景", "伸び悩", "ストップ高", "ストップ安", "買い", "売り",
          "重し", "支え", "けん引", "牽引", "主導", "利上げ", "利下げ", "金利", "決算", "円安", "円高", "関税", "原油", "半導体", "AI"]
GOOD = ["日本経済新聞", "ロイター", "Reuters", "Bloomberg", "ブルームバーグ", "NHK", "時事", "共同", "株探", "みんかぶ",
        "Yahoo!ファイナンス", "読売新聞", "朝日新聞", "毎日新聞", "産経", "マネクリ", "日経CNBC", "QUICK", "トレーダーズ", "フィスコ", "テレ東"]


def norm(s):
    return unicodedata.normalize("NFKC", s or "")


def fetch_one(q):
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": q + " when:4d", "hl": "ja", "gl": "JP", "ceid": "JP:ja"})
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh) market-overview"})
    with urllib.request.urlopen(req, timeout=30) as r:
        root = ET.fromstring(r.read())
    out = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        src = (it.findtext("source") or "").strip()
        link = (it.findtext("link") or "").strip()
        try:
            ts = email.utils.parsedate_to_datetime(it.findtext("pubDate")).timestamp()
        except Exception:
            continue
        if src and title.endswith(" - " + src):
            title = title[: -len(src) - 3].strip()
        title = re.sub(r"\s*投稿日時[:：].*$", "", title).strip()
        if title and link.startswith("https://") and src and not src.startswith("http"):
            out.append({"t": title, "src": src, "url": link, "ts": int(ts)})
    return out


def main():
    old = {}
    try:
        for x in json.load(open(OUT, encoding="utf-8")).get("items", []):
            old[x["url"]] = x
    except Exception:
        pass
    n0, bad = len(old), 0
    for q in QUERIES:
        try:
            for x in fetch_one(q):
                old.setdefault(x["url"], x)
        except Exception as ex:
            bad += 1
            print(f"取得できません（{q}）: {ex}")
        time.sleep(1)
    lim = time.time() - 10 * 86400
    items = sorted((x for x in old.values() if x["ts"] >= lim), key=lambda x: -x["ts"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"fetched": datetime.datetime.now(JST).strftime("%Y-%m-%d %H:%M"), "items": items},
                              ensure_ascii=False), encoding="utf-8")
    print(f"ニュースの見出し: {len(items)}件（新規 {max(len(old) - n0, 0)}）")
    return 1 if bad == len(QUERIES) else 0


def pick(asof, k=5):
    """株価データの日付 asof の引け後に出た市況の見出しを k 件まで（古い順）。
    米国＝引け後の翌朝4時45分（日本時間）〜15時、東証＝大引けの15時25分〜翌朝6時。少なければ2日先まで広げる"""
    try:
        items = json.load(open(OUT, encoding="utf-8")).get("items", [])
    except Exception:
        return []
    d = datetime.datetime.fromisoformat(asof).replace(tzinfo=JST)
    if MARKET == "us":
        st, en = d + datetime.timedelta(days=1, hours=4, minutes=45), d + datetime.timedelta(days=1, hours=15)
    else:
        st, en = d.replace(hour=15, minute=25), d + datetime.timedelta(days=1, hours=6)
    core = [norm(w) for w in CORE]

    def cands(end):
        out = []
        for x in items:
            if not (st.timestamp() <= x["ts"] <= end.timestamp()):
                continue
            t = norm(x["t"])
            if not any(w in t for w in core) or any(w in t for w in SKIP):
                continue
            if OTHER and any(w in t for w in OTHER) and not any(w in t for w in core[:8]):
                continue
            # 引けの値動き＋2、理由にあたる言葉＋2（数字だけの速報より上に）、主な配信元＋1、見通し・途中経過−3
            sc = (2 if any(w in t for w in WRAP) else 0) + (2 if any(w in t for w in REASON) else 0) \
                + (1 if any(g in x["src"] for g in GOOD) else 0) - (3 if any(w in t for w in AHEAD) else 0)
            if sc >= 2:
                out.append((sc, x))
        return out

    c = cands(en)
    if len(c) < 3:
        c = cands(en + datetime.timedelta(days=2))
    c.sort(key=lambda z: (-z[0], z[1]["ts"]))
    sel, seen, per = [], [], {}
    for sc, x in c:
        key = re.sub(r"[\s　、。・「」【】()（）:：]", "", norm(x["t"]))[:14]
        if any(key[:8] == s[:8] for s in seen) or per.get(x["src"], 0) >= 2:
            continue
        seen.append(key)
        per[x["src"]] = per.get(x["src"], 0) + 1
        sel.append(x)
        if len(sel) >= k:
            break
    sel.sort(key=lambda x: x["ts"])
    return [{"t": x["t"], "src": x["src"], "url": x["url"],
             "at": datetime.datetime.fromtimestamp(x["ts"], JST).strftime("%-m/%-d %H:%M")} for x in sel]


if __name__ == "__main__":
    if len(sys.argv) > 1 and re.match(r"\d{4}-\d\d-\d\d$", sys.argv[1]):
        for x in pick(sys.argv[1]):
            print(x["at"], x["t"], "—", x["src"])
        sys.exit(0)
    sys.exit(main())
