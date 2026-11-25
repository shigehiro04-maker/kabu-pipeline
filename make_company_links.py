#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""株式分析ダッシュボードの「会社情報」（従業員・同業他社・関連企業）をまとめる。通信なし。東証版・米国版で共通。

入力（東証 --market jp）
  fundamentals/employees.json          従業員数・平均年齢・平均勤続年数・平均年収（fetch_employees.py）
  fundamentals/raw_affiliates/*.json.gz 有報「関係会社の状況」「親会社等の情報」の文章（同）
  fundamentals/shareholders.json       大株主上位10名（fetch_shareholders.py）
  fundamentals/yahoo_related.json      Yahoo の業種・よく一緒に見られている銘柄（fetch_related_yahoo.py）
  fundamentals/fundamentals_latest.csv 銘柄名・業種（33業種）・時価総額
入力（米国 --market us）
  fundamentals/company_profile.csv     従業員数（Yahoo）
  fundamentals/fundamentals_latest.csv 業種(詳細)＝Yahoo の業種・時価総額
  fundamentals/yahoo_related.json      よく一緒に見られている銘柄

出力  fundamentals/company_info.json
  {コード: {"emp": {...}, "peers": [コード,...], "rel": [[コード, 種類, 割合%またはnull], ...], "rec": [コード,...]}}

決めごと
  同業他社：Yahoo の業種（約145分類。東証は Yahoo の業種が無い銘柄は東証33業種）が同じ銘柄のうち、
            時価総額が近い順に6社（東証は33業種も違えば少し遠いとみなす）。同じ業種が3社未満なら、
            東証33業種（米国はセクター）で足す。
  関連企業（東証）：有報「関係会社の状況」に書かれた上場会社を見出し（親会社・連結子会社・持分法適用関連会社・
            その他の関係会社など）で分ける。相手側の有報に書かれた関係も逆向きに足す（子会社⇔親会社、
            関連会社⇔出資元）。大株主上位10名に入っている上場会社（＝大株主）と、その逆（＝出資先）も足し、割合を付ける。
            社名は EDINET の正式名から「株式会社」などを外して、「(株)」「株式会社」と隣り合う場所だけで照合する。
  関連銘柄：Yahoo の「よく一緒に見られている銘柄」（同じ市場で、ページのある銘柄だけ）。

  ./.venv/bin/python make_company_links.py --market jp [--show 7203]
"""
from __future__ import annotations

import argparse
import csv
import glob
import gzip
import json
import math
import os
import re
import unicodedata
from pathlib import Path

DIRS = {"jp": Path.home() / "株分析", "us": Path.home() / "米国株分析"}
TOPN = 4            # 同業他社は4社まで（2026-11-18 利用者の指定。6→4）
MIN_HOLD = 5.0      # 大株主・出資先は保有割合5%以上（大量保有報告の基準）だけ

# 見出し → 種類（自分から見た相手）
HEAD = {
    "親会社": "親会社", "その他の関係会社": "出資元", "その他の関係会社の親会社": "出資元",
    "同一の親会社を持つ会社": "兄弟会社",
    "連結子会社": "子会社", "非連結子会社": "非連結子会社", "子会社": "子会社", "孫会社": "子会社",
    "持分法適用子会社": "非連結子会社", "持分法適用非連結子会社": "非連結子会社",
    "持分法適用関連会社": "関連会社", "持分法適用関連会社等": "関連会社", "持分法適用会社": "関連会社",
    "持分法適用の関連会社": "関連会社", "関連会社": "関連会社",
}
REV = {"親会社": "子会社", "子会社": "親会社", "非連結子会社": "親会社", "関連会社": "出資元", "出資元": "関連会社", "兄弟会社": "兄弟会社",
       "大株主": "出資先", "出資先": "大株主"}
# 画面に出す種類（2026-11-18 利用者の指定。見出しの分からない「関係会社」と Yahoo の関連銘柄は出さない）
SHOW_KINDS = ("親会社", "出資元", "大株主", "子会社", "非連結子会社", "関連会社", "出資先", "兄弟会社")
ORDER = {"親会社": 0, "出資元": 1, "大株主": 2, "子会社": 3, "非連結子会社": 4, "関連会社": 5, "出資先": 6, "兄弟会社": 7, "関係会社": 8}
_KW = "|".join(sorted(map(re.escape, HEAD), key=len, reverse=True))
# 「(連結子会社)」「【親会社】」のほか、「(2)連結子会社」「② 持分法適用関連会社」「2. 子会社」の形も見出しとみなす
RE_HEAD = re.compile(r"[\(\[【〔<]\s*(" + _KW + r")[^\(\)\[\]【】〔〕<>]{0,20}[\)\]】〕>]"
                     r"|(?:\(\d{1,2}\)|[①-⑳]|(?<!\d)\d{1,2}\.)\s*(" + _KW + r")")
MARK = r"(?:\(株\)|株式会社)"
# 関係会社の表は「名称 → 住所」の順。社名のすぐ後ろ（注記の番号を除く）が住所のものだけを表の行とみなす
# （事業内容の説明の中に出てくる社名＝「○○との合弁」などを拾わないため）
RE_NOTE = re.compile(r"^(?:\s|\(注[^)]{0,12}\)|注\d[\d,]*|[※*＊]+\d*|\d[\d,]*|\)|\(|,)*")
RE_ADDR = re.compile(r"(?:[一-龥ァ-ヶー]{1,7}?(?:都|道|府|県|市|区|町|村|郡|国|州)"
                     r"|[A-Za-z][A-Za-z .'-]{1,40},"
                     r"|米国|中国|英国|韓国|台湾|香港|タイ|インド|ドイツ|フランス|シンガポール|ベトナム|インドネシア"
                     r"|マレーシア|フィリピン|オランダ|スイス|メキシコ|ブラジル|カナダ|豪州|オーストラリア|イタリア|スペイン)")
RE_RATIO = re.compile(r"(?<![\d,.])(\d{1,3}\.\d{1,2})(?![\d,])")


WORD = re.compile(r"[一-龥ぁ-んァ-ヶーA-Za-z0-9&・]")


def edge_ok(t, m):
    """社名の前後が別の語に続いていないこと（「サポート(株)」の中の「ポート」などを外す）"""
    if not m.group(1):
        s = m.start(2)
        # 表の前のセルの終わり（有・無・あり・なし・。・数字・括弧）にそのまま続くのは許す
        if s > 0 and WORD.match(t[s - 1]) and not re.match(r"[有無りしす\d]", t[s - 1]):
            return False
    if not m.group(3):
        e = m.end(2)
        if e < len(t) and WORD.match(t[e]):
            return False
    return True


def nfkc(s):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s or "")).strip()


def core(name):
    """社名の本体（株式会社・(株)・空白・ホールディングスの表記ゆれは残す）"""
    s = nfkc(name)
    s = re.sub(r"株式会社|\(株\)|有限会社|合同会社", "", s)
    return re.sub(r"\s+", "", s).strip()


def read_csv(p):
    if not Path(p).exists():
        return []
    with open(p, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def num(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def fix_salary(s, n):
    """平均年間給与（円）。XBRL の単位の付け違い（千円のまま・千倍）を直し、直しても不自然な値は捨てる。"""
    if not s or s <= 0:
        return None
    while s > 1e8:
        s /= 1000
    if s < 1e5:
        s *= 1000
    if 1.5e6 <= s <= 4e7 or (n is not None and n <= 20 and 1e6 <= s <= 1e8):
        return round(s)
    return None


STOP_EXTRA = """japan japanese tokyo osaka nagoya company companies co ltd inc corp corporation group holdings holding
segment segments business businesses engages engaged operates operating operation operations provides provide
offers offer products product services service related various other including include includes well also
addition additionally internationally worldwide globally international domestic overseas states united america
american asia china europe based headquartered founded incorporated formerly known name changed subsidiary
subsidiaries principal primarily mainly main sells sale sales manufacture manufactures manufacturing develops
development rest world customers""".split()


# 日本語の事業概要で、どの会社にも出てくる言い回し（似ている度合いを水増しするので外す）
JA_GENERIC = re.compile("幅広い分野|幅広い|多角的|分野|製品|サービス|総合|関連|開発|運営|主力|強み|議決権[^ ]{0,4}株|クラス ?[A-ZＡ-Ｚ]|普通株|優先株|米国預託証券|預託証券|ADR|ADS|株式|世界最大級|世界最大手|世界最大|世界有数|世界的|国内最大手|国内最大|国内大手|最大手|大手|老舗|中堅|"
                        "を手掛ける|手掛ける|を展開|展開する|を中心に|中心|を提供|提供する|の製造販売|製造販売|を製造|を販売|"
                        "事業も|事業|会社|企業|グループ|持株会社|メーカー|米国|日本|世界|向け|など|ほか|ため|として|"
                        "の|を|に|が|は|と|で|も|する|した|や")


def peers_by_text(texts, rows, topn=TOPN, ja=None, names=None, rec=None, w_rec=0.08, w_ja=0.5, w_ind=0.07, w_sec=0.02, w_cap=0.035, min_sim=0.06):
    """事業内容の説明文（Yahoo の英文の事業概要）が似ている順に同業他社を選ぶ（2026-11-18）。
    似ている度合い＝TF-IDF（単語と2語の組）のコサイン類似度。同じ業種・セクターと時価総額の近さは少しだけ加点。
    texts: {コード: 英文}, rows: {コード: (業種, セクター, 時価総額)}。説明文が無い銘柄は返さない。"""
    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer, ENGLISH_STOP_WORDS
    codes = [c for c in rows if len(texts.get(c) or "") >= 80]
    docs = []
    for c in codes:
        t = texts[c]
        # 設立・本社・社名変更などの決まり文句の文は外す（会社の中身と関係ないのに似て見えるため）
        ss = [s for s in re.split(r"(?<=[.!?])\s+", t)
              if not re.search(r"\b(founded|incorporated|headquartered|formerly known|changed its name|is a subsidiary of)\b", s, re.I)]
        docs.append(" ".join(ss) or t)
    vec = TfidfVectorizer(stop_words=list(ENGLISH_STOP_WORDS.union(STOP_EXTRA)), ngram_range=(1, 2), min_df=2,
                          max_df=0.08, sublinear_tf=True, token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z\-]{2,}\b")
    X = vec.fit_transform(docs)
    S = (X @ X.T).toarray()
    if ja:
        # 日本語の事業概要（1〜2文。中心の事業がはっきり書いてある）も文字の2〜3字の組で比べて混ぜる
        jd = [re.sub(JA_GENERIC, " ", re.sub(r"[、。・「」（）()\s]", " ", ja.get(c) or "")) for c in codes]
        jv = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 3), min_df=2, max_df=0.05, sublinear_tf=True)
        J = jv.fit_transform(jd)
        SJ = (J @ J.T).toarray()
        S = (1 - w_ja) * S + w_ja * SJ
    ind = [rows[c][0] for c in codes]
    sec = [rows[c][1] for c in codes]
    names = [re.sub(r"[\s,.]|class [a-z]|inc|corp|co|ltd", "", (names or {}).get(c, c).lower()) or c for c in codes]
    NAMEKEY.update(zip(codes, names))
    lm = np.array([math.log10(rows[c][2]) if rows[c][2] and rows[c][2] > 0 else np.nan for c in codes])
    pos = {c: i for i, c in enumerate(codes)}
    out = {}
    for i, c in enumerate(codes):
        sc = S[i].copy()
        # Yahoo の「Conglomerates（複合企業）」は総合商社と総合電機が同じ分類になるので加点しない
        same_ind = np.array([x == ind[i] and bool(x) and x != "Conglomerates" for x in ind])
        same_sec = np.array([x == sec[i] and bool(x) for x in sec])
        dm = np.abs(lm - lm[i])
        sc = sc + w_ind * same_ind + w_sec * same_sec - w_cap * np.nan_to_num(dm, nan=3.0)
        for o in (rec or {}).get(c, []):            # Yahoo の「よく一緒に見られている銘柄」なら少し加点
            j = pos.get(o)
            if j is not None and S[i, j] >= 0.08:  # 説明文もある程度似ているときだけ
                sc[j] += w_rec
        sc[i] = -9
        sc[S[i] < min_sim] = -9                     # 説明文がほとんど似ていないものは採らない
        pick, seen_n = [], {names[i]}
        for j in np.argsort(-sc)[:topn * 3]:
            if sc[j] <= -9 or len(pick) >= topn:
                break
            if names[j] in seen_n:                  # 同じ会社の別の株式（UA と UAA など）は1つだけ
                continue
            seen_n.add(names[j])
            pick.append(codes[j])
        out[c] = pick
        WEAK[c] = float(np.mean([S[i, pos[x]] for x in pick])) if pick else 0.0
    return out


NAMEKEY = {}  # コード → 社名を縮めたもの（同じ会社の別の株式を1つにするため）
WEAK = {}     # 選んだ同業他社との説明文の似ている度合いの平均（低いと説明文が大まかな会社＝複合企業など）


def mix_peers(tp, op=None):
    """同業他社は説明文が似ている会社だけ（2026-11-18 利用者の指定：時価総額が近い会社で埋めない）。
    同じ会社の別の株式は1つにする。op（従来の業種＋時価総額の方法）は使わない。"""
    out = {}
    for c, p in tp.items():
        q, seen_n = [], {NAMEKEY.get(c, c)}
        for x in p:
            k = NAMEKEY.get(x, x)
            if k not in seen_n:
                seen_n.add(k)
                q.append(x)
        out[c] = q[:TOPN]
    return out


def peers_of(rows, market):
    """rows: {code: (ind, sec, mcap)}"""
    by_ind, by_sec = {}, {}
    for c, (ind, sec, mc) in rows.items():
        if ind:
            by_ind.setdefault(ind, []).append(c)
        if sec:
            by_sec.setdefault(sec, []).append(c)
    out = {}
    for c, (ind, sec, mc) in rows.items():
        lm = math.log(mc) if mc and mc > 0 else None

        def dist(o):
            om = rows[o][2]
            d = abs(math.log(om) - lm) if lm is not None and om and om > 0 else 9
            if market == "jp" and rows[o][1] != sec:
                d += 0.7
            return d
        cand = [o for o in by_ind.get(ind, []) if o != c] if ind else []
        pick = sorted(cand, key=dist)[:TOPN]
        if len(pick) < 3 and sec:
            more = [o for o in by_sec.get(sec, []) if o != c and o not in pick]
            pick += sorted(more, key=dist)[:TOPN - len(pick)]
        out[c] = pick
    return out


def build_jp(base):
    F = base / "fundamentals"
    latest = {r["コード"]: r for r in read_csv(F / "fundamentals_latest.csv")}
    emp = json.loads((F / "employees.json").read_text(encoding="utf-8")) if (F / "employees.json").exists() else {}
    sh = json.loads((F / "shareholders.json").read_text(encoding="utf-8")) if (F / "shareholders.json").exists() else {}
    yr = json.loads((F / "yahoo_related.json").read_text(encoding="utf-8")) if (F / "yahoo_related.json").exists() else {}

    # 社名 → コード（EDINET の正式名を優先。JPX の略称は4文字以上だけ）
    names = {}
    for c in latest:
        for nm, mn in (((emp.get(c) or {}).get("name"), 2), ((sh.get(c) or {}).get("name"), 2), (latest[c].get("銘柄名"), 4)):
            k = core(nm)
            if len(k) >= mn and k not in names:
                names[k] = c
    # 同じ本体名が複数のコードに当たるもの（社名変更前後など）は使わない
    dup = {}
    for c in latest:
        for nm in ((emp.get(c) or {}).get("name"), (sh.get(c) or {}).get("name")):
            k = core(nm)
            if k:
                dup.setdefault(k, set()).add(c)
    for k, cs in dup.items():
        if len(cs) > 1:
            names.pop(k, None)
    alt = "|".join(re.escape(k) for k in sorted(names, key=len, reverse=True))
    RE_N = re.compile(rf"({MARK})?\s?({alt})\s?({MARK})?")

    rel = {}   # rel[a][b] = [種類, 割合, 出どころの強さ]

    def add(a, b, kind, ratio=None, own=True):
        if a == b or a not in latest or b not in latest:
            return
        if not ratio:
            ratio = None
        cur = rel.setdefault(a, {}).get(b)
        if cur is None:
            rel[a][b] = [kind, ratio, own]
            return
        if own and not cur[2]:                       # 自社の有報の記載を優先
            cur[0], cur[2] = kind, True
            cur[1] = ratio if ratio is not None else cur[1]
            return
        if not cur[2] and cur[0] in ("大株主", "出資先") and kind not in ("大株主", "出資先"):
            cur[0] = kind                            # 持株だけより資本関係（親子・関連）の記載を優先
        if cur[1] is None and ratio is not None:
            cur[1] = ratio

    claims, seen = [], {}
    for f in glob.glob(str(F / "raw_affiliates" / "*.json.gz")):
        a = Path(f).name.split(".")[0]
        try:
            d = json.load(gzip.open(f, "rt", encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        for key, default in (("aff", "関係会社"), ("parent", "親会社")):
            t = nfkc(d.get(key))
            if not t:
                continue
            heads = [(m.start(), HEAD[m.group(1) or m.group(2)]) for m in RE_HEAD.finditer(t)]
            ms = [m for m in RE_N.finditer(t) if (m.group(1) or m.group(3)) and edge_ok(t, m)
                  and (key == "parent" or RE_ADDR.match(RE_NOTE.sub("", t[m.end():m.end() + 40])))]
            for i, m in enumerate(ms):
                b = names[m.group(2)]
                # 議決権の所有（被所有）割合：社名の後ろ（次の社名・見出しまで、最大250字）で最初の小数
                end = min(ms[i + 1].start() if i + 1 < len(ms) else len(t), m.end() + 250)
                nh = [p for p, _ in heads if m.end() < p < end]
                win = t[m.end():nh[0] if nh else end]
                rm = RE_RATIO.search(win)
                ratio = float(rm.group(1)) if rm and float(rm.group(1)) <= 100 else None
                kind = default
                for p, k in heads:
                    if p < m.start():
                        kind = k
                    else:
                        break
                if key == "parent" and "親会社等はありません" in t:
                    continue
                claims.append((a, b, kind, ratio))
            # 文章のどこかに名前が出てくる会社（相手側の確認に使う）
            for m in RE_N.finditer(t):
                if (m.group(1) or m.group(3)) and edge_ok(t, m):
                    seen.setdefault(a, set()).add(names[m.group(2)])

    # 同名の別会社（例：初穂商事の子会社「株式会社アイシン」）を外すため、相手の有報にもこちらの名前があるか、
    # どちらかの大株主にもう一方が入っているときだけ採る。相手の有報の文章が無いときは採る。
    holds = {a: {names.get(core(h[0])) for h in (x.get("holders") or [])} for a, x in sh.items()}
    # 間接の子会社（例：ソフトバンクグループ→LINEヤフー→ZOZO）は、相手の有報にこちらの子会社の名前があれば採る
    kids = {}
    for a, b, kind, _ in claims:
        if kind in ("子会社", "非連結子会社", "関連会社"):
            kids.setdefault(a, set()).add(b)
    dropped = 0
    for a, b, kind, ratio in claims:
        # 確かめるのは「子会社・関連会社」と書いた側だけ（子会社が親会社を書き違えることはほぼ無い）
        if kind in ("子会社", "非連結子会社", "関連会社") and b in seen and not (seen[b] - {b}) & ({a} | kids.get(a, set())) \
                and b not in holds.get(a, ()) and a not in holds.get(b, ()):
            dropped += 1
            if os.environ.get("CL_DEBUG"):
                print("  外した:", a, latest[a].get("銘柄名"), "→", b, latest[b].get("銘柄名"), kind, ratio)
            continue
        add(a, b, kind, ratio, own=True)
        add(b, a, REV.get(kind, "関係会社"), ratio, own=False)
    print(f"関係会社の記載 {len(claims)} 件（相手側で確認できず外した {dropped} 件）")

    # 大株主（上位10名）に入っている上場会社
    for a, x in sh.items():
        for h in x.get("holders") or []:
            b = names.get(core(h[0]))
            if not b:
                continue
            r = round(h[2] * 100, 2) if h[2] is not None and h[2] <= 1 else h[2]
            if r is None or r < MIN_HOLD:
                continue
            # 既に親会社・出資元なら割合だけ付ける
            ca = rel.get(a, {}).get(b)
            if ca and ca[0] in ("親会社", "出資元"):
                ca[1] = ca[1] if ca[1] is not None else r
            else:
                add(a, b, "大株主", r, own=False)
            cb = rel.get(b, {}).get(a)
            if cb and cb[0] in ("子会社", "関連会社"):
                cb[1] = cb[1] if cb[1] is not None else r
            else:
                add(b, a, "出資先", r, own=False)

    # 兄弟会社：同じ親会社を持つ上場子会社（親会社の連結子会社どうし。2026-11-18）
    sib = {}
    for a in list(rel):
        for pc, v in list(rel[a].items()):
            if v[0] != "親会社":
                continue
            for b, w in (rel.get(pc) or {}).items():
                if w[0] == "子会社" and b != a and b not in rel[a]:
                    sib.setdefault(a, set()).add(b)
    for a, bs in sib.items():
        for b in bs:
            add(a, b, "兄弟会社", None, own=False)

    mcap = {c: num(latest[c].get("時価総額")) for c in latest}
    rows = {c: ((yr.get(c) or {}).get("ind") or ("東証:" + (latest[c].get("業種") or "")),
                latest[c].get("業種") or "", mcap[c]) for c in latest}
    # 同業他社：事業内容の説明文が似ている順（足りなければ従来の「同じ業種で時価総額が近い順」で補う）
    texts = {r["コード"]: r.get("事業概要(英文)") for r in read_csv(F / "company_profile.csv")}
    ja = {r["コード"]: r.get("事業概要") for r in read_csv(F / "company_profile.csv")}
    nms = {c: latest[c].get("銘柄名") for c in latest}
    ysym = {c.replace(".", "-"): c for c in latest}
    rec_c = {c: [(x[0][:-2] if x[0].endswith(".T") else ysym.get(x[0], x[0])) for x in (v.get("rec") or [])]
             for c, v in yr.items()}
    peers = mix_peers(peers_by_text(texts, rows, ja=ja, names=nms, rec=rec_c, w_sec=0.09), peers_of(rows, "jp"))
    out = {}
    for c in latest:
        e = emp.get(c) or {}
        ed = {k: e.get(k) for k in ("emp", "emp_nc", "temp", "age", "tenure", "salary", "asof") if e.get(k) is not None}
        if "salary" in ed:
            ed["salary"] = fix_salary(ed["salary"], e.get("emp_nc"))
            if ed["salary"] is None:
                del ed["salary"]
        h = e.get("hist") or []
        # 推移の表の今期が従業員数（連結）と一致するときだけ（連結と単体が混ざるのを防ぐ）
        cur0 = dict((k, v) for k, v in h).get(0)
        if len(h) >= 2 and h[0][1] and e.get("emp") and cur0 == e.get("emp"):
            ed["h0"] = [h[0][0], h[0][1]]          # [何期前, 人数]（5年前比を出す）
        if not ed.get("emp") and (yr.get(c) or {}).get("emp"):
            ed = {"emp": yr[c]["emp"], "src": "yahoo"}
        rl = sorted(((b, v[0], v[1]) for b, v in (rel.get(c) or {}).items() if v[0] in SHOW_KINDS),
                    key=lambda x: (ORDER.get(x[1], 9), -(x[2] or 0), -(mcap.get(x[0]) or 0)))
        rec = [s[0][:-2] for s in (yr.get(c) or {}).get("rec") or [] if s[0].endswith(".T") and s[0][:-2] in latest]
        out[c] = {"emp": ed, "peers": peers.get(c, []), "rel": [list(x) for x in rl], "rec": [],
                  "ind": (yr.get(c) or {}).get("ind")}
    return out


def build_us(base):
    F = base / "fundamentals"
    latest = {r["コード"]: r for r in read_csv(F / "fundamentals_latest.csv")}
    prof = {r["コード"]: r for r in read_csv(F / "company_profile.csv")}
    yr = json.loads((F / "yahoo_related.json").read_text(encoding="utf-8")) if (F / "yahoo_related.json").exists() else {}
    ysym = {c.replace(".", "-"): c for c in latest}
    rows = {c: (latest[c].get("業種(詳細)") or "", latest[c].get("業種") or "", num(latest[c].get("時価総額"))) for c in latest}
    # 同業他社：事業内容の説明文が似ている順（足りなければ従来の「同じ業種で時価総額が近い順」で補う）
    texts = {r["コード"]: r.get("事業概要(英文)") for r in read_csv(F / "company_profile.csv")}
    ja = {r["コード"]: r.get("事業概要") for r in read_csv(F / "company_profile.csv")}
    nms = {c: latest[c].get("銘柄名") for c in latest}
    ysym = {c.replace(".", "-"): c for c in latest}
    rec_c = {c: [(x[0][:-2] if x[0].endswith(".T") else ysym.get(x[0], x[0])) for x in (v.get("rec") or [])]
             for c, v in yr.items()}
    peers = mix_peers(peers_by_text(texts, rows, ja=ja, names=nms, rec=rec_c), peers_of(rows, "us"))
    out = {}
    for c in latest:
        e = num((prof.get(c) or {}).get("従業員数"))
        rec = [ysym.get(s[0], s[0]) for s in (yr.get(c) or {}).get("rec") or []]
        rec = [s for s in rec if s in latest and s != c]
        out[c] = {"emp": {"emp": e} if e else {}, "peers": peers.get(c, []), "rel": [], "rec": [],
                  "ind": latest[c].get("業種(詳細)") or None}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", choices=["jp", "us"], required=True)
    ap.add_argument("--show", default="")
    a = ap.parse_args()
    base = DIRS[a.market]
    out = build_jp(base) if a.market == "jp" else build_us(base)
    p = base / "fundamentals" / "company_info.json"
    p.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    n_emp = sum(1 for x in out.values() if x["emp"].get("emp"))
    n_sal = sum(1 for x in out.values() if x["emp"].get("salary"))
    n_rel = sum(1 for x in out.values() if x["rel"])
    n_rec = sum(1 for x in out.values() if x["rec"])
    n_peer = sum(1 for x in out.values() if x["peers"])
    print(f"{a.market}: {len(out)} 銘柄 / 従業員数 {n_emp} / 平均年収 {n_sal} / 同業他社 {n_peer} / 関連企業 {n_rel} / 関連銘柄 {n_rec} → {p}")
    for c in [s for s in a.show.split(",") if s]:
        print(c, json.dumps(out.get(c), ensure_ascii=False))


if __name__ == "__main__":
    main()
