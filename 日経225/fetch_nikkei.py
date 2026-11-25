#!/usr/bin/env python3
"""日経平均プロフィル（indexes.nikkei.co.jp）から無料で取れるデータを取得する。

  1. 構成銘柄一覧（コード・銘柄名・社名・日経業種）      → data/components.csv
  2. ニュース一覧（日経平均タグ）                        → 除数の公表値 data/divisor.csv
  3. 入れ替え・株価換算係数・キャップのお知らせPDF       → data/events.csv に追記
  4. 株価換算係数の表を作り直す                          → data/factors.csv
       基準（data/factors_seed.csv：2026-10-01時点、日経平均と一致を確認済み）に、
       それ以降の events.csv の変更を実施日順に当てはめる。発表に無い株式分割は
       data/splits.csv（株価CSVの分割台帳）から「係数×分割比率」で補う

指数の日次・月次CSV（日経平均・VI）は 株価指数/fetch_indices.py が取得済みなので、ここでは取らない。
アクセスは1回の実行でページ数枚＋新しいPDFだけ（通常は数秒）。
"""
from __future__ import annotations

import csv
import io
import json
import re
import sys
import time
import unicodedata
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import requests

from nk_common import (DATA, F_COMPONENTS, F_DIVISOR, F_EVENTS, F_FACTORS, F_NEWS_STATE, SPLITS,
                       load_events, read_csv_str, save_json)

SITE = "https://indexes.nikkei.co.jp"
COMPONENT_URL = SITE + "/nkave/index/component?idx=nk225"
NEWS_URL = SITE + "/nkave/newsroom?evt=&idxtag%5B%5D=00001&idxtag%5B%5D=ja&year={year}"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
F_SEED = DATA / "factors_seed.csv"
TIMEOUT = 30


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def get(url: str) -> requests.Response:
    for i in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=TIMEOUT)
            r.raise_for_status()
            return r
        except Exception as e:  # noqa: BLE001
            if i == 2:
                raise
            log(f"  再試行 {i + 1}/2: {e}")
            time.sleep(3)
    raise RuntimeError("unreachable")


# ------------------------------------------------------------------ 1. 構成銘柄
def fetch_components() -> pd.DataFrame | None:
    from bs4 import BeautifulSoup

    html = get(COMPONENT_URL).text
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for h in soup.find_all("h3"):
        tb = h.find_next_sibling()
        if tb is None or tb.name != "table":
            continue
        industry = h.get_text(strip=True)
        for tr in tb.select("tbody tr"):
            td = [t.get_text(strip=True) for t in tr.find_all("td")]
            if len(td) >= 3 and re.fullmatch(r"\d{3}[0-9A-Z]", td[0]):
                rows.append({"code": td[0], "name": td[1], "company": td[2], "industry": industry})
    df = pd.DataFrame(rows).drop_duplicates("code")
    if len(df) != 225:
        log(f"※ 構成銘柄が {len(df)} 件しか読めませんでした（ページの形が変わった可能性）。前回の一覧を使います")
        return None
    old = set(read_csv_str(F_COMPONENTS)["code"]) if F_COMPONENTS.exists() else set()
    new = set(df["code"])
    if old and old != new:
        log(f"構成銘柄が変わりました: 採用 {sorted(new - old)} / 除外 {sorted(old - new)}")
    df.to_csv(F_COMPONENTS, index=False, encoding="utf-8-sig")
    log(f"構成銘柄一覧を保存: {len(df)}銘柄")
    return df


# ------------------------------------------------------------------ 2. ニュース一覧・除数
def fetch_news(years) -> list[dict]:
    from bs4 import BeautifulSoup

    items = []
    for y in years:
        soup = BeautifulSoup(get(NEWS_URL.format(year=y)).text, "lxml")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not re.search(r"/archives/news/\w+\.pdf$", href):
                continue
            row = a.find_parent(["tr", "li", "div"])
            text = re.sub(r"\s+", " ", (row.get_text(" ") if row else a.get_text(" "))).strip()
            m = re.search(r"(\d{4})\.(\d{2})\.(\d{2})", text)
            if not m:
                continue
            title = re.sub(r"^\d{4}\.\d{2}\.\d{2}\s*", "", text).strip()
            items.append({"date": f"{m[1]}-{m[2]}-{m[3]}", "title": title,
                          "url": href if href.startswith("http") else SITE + href})
    # 重複除去（同じPDFが複数の枠に出ることがある）
    seen, out = set(), []
    for it in items:
        if it["url"] not in seen:
            seen.add(it["url"])
            out.append(it)
    return out


def update_divisor(news: list[dict]) -> None:
    rows = []
    if F_DIVISOR.exists():
        rows = list(csv.DictReader(open(F_DIVISOR, encoding="utf-8-sig")))
    have = {r["date"] for r in rows}
    added = 0
    for it in news:
        if "除数" not in it["title"]:
            continue
        m = re.search(r"除数[、,]\s*([\d.]+)", it["title"])
        if not m or it["date"] in have:
            continue
        rows.append({"date": it["date"], "divisor": m[1], "title": it["title"]})
        added += 1
    if added:
        rows.sort(key=lambda r: r["date"])
        with open(F_DIVISOR, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["date", "divisor", "title"])
            w.writeheader()
            w.writerows(rows)
        log(f"除数の公表値を {added} 件追加")


# ------------------------------------------------------------------ 3. お知らせPDFの読み取り
RELEVANT = re.compile(r"入れ替え|入替|取り扱い|株価換算係数|キャップ|スピンオフ")


def pdf_text(url: str) -> str:
    import pdfplumber

    data = get(url).content
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


def normalize(t: str) -> str:
    t = unicodedata.normalize("NFKC", t)
    t = t.replace("⇒", "→").replace("－", "-")
    t = re.sub(r"[ \t\u3000]+", " ", t)
    return t


def _num(s: str) -> str:
    """"0. 5" "2 2.5" のように数字の中に入った空白を詰める"""
    return re.sub(r"\s+", "", s)


def _md(text: str, year: int, pat: str):
    """「株価換算係数変更（10 月 1 日）」などの見出しの日付（数字の中の空白も許す）"""
    m = re.search(pat + r"\s*\(\s*(\d[\d ]*?)\s*月\s*(\d[\d ]*?)\s*日\s*\)", text)
    if not m:
        return None
    return f"{year}-{int(_num(m[1])):02d}-{int(_num(m[2])):02d}"


CODE = r"\d{3}[0-9A-Z]"
NUM = r"\d[\d. ]*?"
NAME = r"((?:(?!" + CODE + r"\s)[^()\n])+?)"


def parse_notice(text: str, announced: str) -> list[dict]:
    """お知らせ（2024年以降の形式）から、入れ替え・係数変更・キャップ変更を読み取る"""
    t = normalize(text)
    year = int(announced[:4])
    ann_m = int(announced[5:7])
    events = []

    def fix_year(d):
        # 12月発表の1月実施など、年をまたぐ場合
        if d and int(d[5:7]) + 6 < ann_m:
            return f"{year + 1}{d[4:]}"
        return d

    # 株価換算係数の変更（分割・併合・分割採用）
    eff = fix_year(_md(t, year, r"株価換算係数変更"))
    pat = (r"(" + CODE + r")\s+" + NAME + r"\s+(" + NUM + r")\s*→\s*(" + NUM + r")\s+"
           r"(1\s*:\s*" + NUM + r"\s*分割|" + NUM + r"\s*:\s*1\s*併合|分割採用[^\n]*)")
    for m in re.finditer(pat, t):
        events.append({"effective": eff or "", "announced": announced, "type": "factor",
                       "code": m[1], "name": m[2].strip(), "old": _num(m[3]), "new": _num(m[4]),
                       "reason": re.sub(r"\s", "", m[5])})
    # キャップ調整比率
    eff_c = fix_year(_md(t, year, r"キャップ調整比率\s*の?設定\s*・?\s*変更"))
    for m in re.finditer(r"(" + CODE + r")\s+" + NAME + r"\s+(未設定|" + NUM + r")\s*→\s*(解除|" + NUM + r")\s*キャップ", t):
        events.append({"effective": eff_c or "", "announced": announced, "type": "cap",
                       "code": m[1], "name": m[2].strip(),
                       "old": "1" if m[3] == "未設定" else _num(m[3]),
                       "new": "1" if m[4] == "解除" else _num(m[4]), "reason": "キャップ調整（ウエート10%超）"})
    # 銘柄入れ替え：採用は「コード 名前（係数）」、除外はカッコなし
    eff_s = fix_year(_md(t, year, r"銘柄入れ替え"))
    if eff_s:
        i = re.search(r"銘柄入れ替え\s*\(", t).start()
        block = t[i:]
        block = block[block.find(")") + 1:]
        end = re.search(r"注\)|定期見直し基準|ニュースタグ|\n\s*\d\.\s", block)
        block = block[: end.start()] if end else block[:800]
        adds = {}
        for m in re.finditer(r"(" + CODE + r")\s+((?:(?!" + CODE + r"\s)[^()])+?)\s*\(\s*(" + NUM + r")\s*\)", block):
            adds[m[1]] = (re.sub(r"\s+", "", m[2]), _num(m[3]))
        for code, (name, f) in adds.items():
            events.append({"effective": eff_s, "announced": announced, "type": "add", "code": code,
                           "name": name, "old": "", "new": f, "reason": _reason(t, name)})
        for line in block.split("\n"):
            m = re.match(r"\s*(" + CODE + r")\s+([^()]+?)\s*$", line)
            if m and m[1] not in adds:
                events.append({"effective": eff_s, "announced": announced, "type": "del", "code": m[1],
                               "name": m[2].strip(), "old": "", "new": "", "reason": _reason(t, m[2].strip())})
    # 臨時の入れ替え（上場廃止・特別注意銘柄・TOBなど）
    if re.search(r"上場廃止|特別注意|TOB|株式公開買い付け", t) and not re.search(r"定期", t):
        for e in events:
            if e["type"] in ("add", "del"):
                e["reason"] = "臨時"
    return [e for e in events if e["effective"]]


def _reason(t: str, name: str) -> str:
    """説明文で、その銘柄名の直前に出てくるのが「流動性」か「過不足調整」かで理由を判定"""
    body = t[t.find("定期見直し基準"):] if "定期見直し基準" in t else ""
    flat = re.sub(r"\s+", "", body)
    i = flat.find(re.sub(r"\s+", "", name)[:4])
    if not body or i < 0:
        return "定期・不明"
    a, b = flat.rfind("流動性", 0, i), flat.rfind("過不足", 0, i)
    if a < 0 and b < 0:
        return "定期・不明"
    return "定期・市場流動性" if a > b else "定期・セクター間の過不足調整"


def update_events(news: list[dict]) -> int:
    state = json.loads(F_NEWS_STATE.read_text(encoding="utf-8")) if F_NEWS_STATE.exists() else {"done": {}}
    ev = list(csv.DictReader(open(F_EVENTS, encoding="utf-8-sig")))
    keys = {(e["effective"], e["type"], e["code"]) for e in ev}
    fields = ["effective", "announced", "type", "code", "name", "old", "new", "reason"]
    added = 0
    for it in sorted(news, key=lambda x: x["date"]):
        if it["url"] in state["done"] or not RELEVANT.search(it["title"]) or "除数" in it["title"]:
            continue
        if not re.search(r"日経平均", it["title"]) and "入れ替え" not in it["title"]:
            state["done"][it["url"]] = {"title": it["title"], "events": 0, "skip": "対象外"}
            continue
        try:
            text = pdf_text(it["url"])
        except Exception as e:  # noqa: BLE001
            log(f"※ PDFを読めませんでした（次回また試します）: {it['title']} {e}")
            continue
        found = parse_notice(text, it["date"])
        n = 0
        for e in found:
            k = (e["effective"], e["type"], e["code"])
            if k in keys:
                continue
            ev.append({f: e.get(f, "") for f in fields})
            keys.add(k)
            n += 1
        state["done"][it["url"]] = {"title": it["title"], "date": it["date"], "events": n}
        if found:
            log(f"お知らせを読み取り: {it['date']} {it['title']} → {len(found)}件（新規 {n}）")
        elif re.search(r"入れ替え|株価換算係数|キャップ", it["title"]):
            log(f"※ お知らせから変更を読み取れませんでした。PDFを確認して events.csv に手で足してください: "
                f"{it['date']} {it['title']} {it['url']}")
            state["done"][it["url"]]["needs_review"] = True
        added += n
    if added:
        ev.sort(key=lambda e: (e["effective"], e["type"], e["code"]))
        with open(F_EVENTS, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(ev)
    save_json(F_NEWS_STATE, state)
    return added


# ------------------------------------------------------------------ 4. 株価換算係数の表
def rebuild_factors(asof: str, members: list[str]) -> pd.DataFrame:
    """seed に、seed より後で asof までに実施された変更を当てはめる"""
    seed = read_csv_str(F_SEED)
    seed_asof = str(seed["asof"].max())
    F = {r.code: float(r.factor) for r in seed.itertuples()}
    cap = {r.code: float(r.cap_ratio) for r in seed.itertuples() if pd.notna(r.cap_ratio)}
    src = {c: "基準表（2026-10-01）" for c in F}
    changed = seed_asof          # 最後に係数・構成が変わった日（検証はこの日以降で行う）
    ev = load_events()
    ev = ev[(ev["effective"] > seed_asof) & (ev["effective"] <= asof)].sort_values("effective")
    for e in ev.itertuples():
        changed = max(changed, e.effective)
        if e.type == "add":
            F[e.code] = float(e.new) if pd.notna(e.new) else float("nan")
            cap.pop(e.code, None)
            src[e.code] = f"{e.effective} 採用（発表 {e.announced}）"
        elif e.type == "del":
            F.pop(e.code, None)
            cap.pop(e.code, None)
        elif e.type == "factor" and pd.notna(e.new):
            F[e.code] = float(e.new)
            src[e.code] = f"{e.effective} {e.reason}（発表 {e.announced}）"
        elif e.type == "cap" and pd.notna(e.new):
            if abs(float(e.new) - 1.0) < 1e-9:
                cap.pop(e.code, None)
            else:
                cap[e.code] = float(e.new)
            src[e.code] = f"{e.effective} キャップ調整比率 {e.new}（発表 {e.announced}）"
    # 発表の取り込み漏れに備えて、分割台帳（data/splits.csv）からも補う
    if SPLITS.exists():
        sp = pd.read_csv(SPLITS, dtype={"code": str})
        sp = sp[(sp["ex_date"] > seed_asof) & (sp["ex_date"] <= asof)]
        for s in sp.itertuples():
            if s.code not in F or not (s.ratio > 0):
                continue
            near = ev[(ev["code"] == s.code) & (ev["type"] == "factor")]
            near = near[(pd.to_datetime(near["effective"]) - pd.Timestamp(s.ex_date)).abs() <= pd.Timedelta(days=7)]
            if len(near):
                continue
            newf = round(F[s.code] * float(s.ratio), 4)
            log(f"※ {s.code} の株式分割（{s.ex_date}・{s.ratio}倍）が日経の発表から読めていないため、係数を {F[s.code]}→{newf} と推定")
            F[s.code] = newf
            src[s.code] = f"{s.ex_date} 分割台帳から推定（×{s.ratio}）"
            changed = max(changed, s.ex_date)
    rows = []
    for c in members:
        f = F.get(c, float("nan"))
        if pd.isna(f):
            log(f"※ {c} の株価換算係数が分かりません（暫定で1）。発表資料を確認して events.csv に足してください")
        rows.append({"code": c, "factor": 1.0 if pd.isna(f) else f, "cap_ratio": cap.get(c, ""),
                     "asof": changed, "source": src.get(c, "不明（暫定1）")})
    out = pd.DataFrame(rows)
    out.to_csv(F_FACTORS, index=False, encoding="utf-8-sig")
    return out


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--asof", default=date.today().isoformat(), help="この日までの変更を係数表に反映")
    ap.add_argument("--offline", action="store_true", help="通信せず、手元のデータで係数表だけ作り直す")
    a = ap.parse_args(argv)
    if not F_SEED.exists():
        log("data/factors_seed.csv がありません")
        return 1
    ok = True
    if not a.offline:
        try:
            fetch_components()
        except Exception as e:  # noqa: BLE001
            ok = False
            log(f"※ 構成銘柄一覧を取得できませんでした（前回の一覧を使います）: {e}")
        try:
            y = date.today().year
            news = fetch_news([y - 1, y])
            update_divisor(news)
            n = update_events(news)
            log(f"ニュース {len(news)} 件を確認（変更の新規登録 {n} 件）")
        except Exception as e:  # noqa: BLE001
            ok = False
            log(f"※ ニュースを取得できませんでした: {e}")
    members = read_csv_str(F_COMPONENTS)["code"].tolist()
    f = rebuild_factors(a.asof, members)
    log(f"株価換算係数の表を更新: {len(f)}銘柄（{a.asof} 時点）")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
