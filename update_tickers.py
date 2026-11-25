#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
銘柄リスト（tickers/tse_tickers.csv）を最新にする。run_daily.sh から毎日呼ばれる。

JPX の3つのページを突き合わせて、東証プライム・スタンダード・グロースの普通株を揃える。
  1) 上場銘柄一覧（data_j.xlsx）… 月末時点の全銘柄。月1回しか更新されない
  2) 新規上場会社情報           … 月末以降に上場した会社（テクニカル上場を含む）を足す
  3) 上場廃止銘柄一覧           … 月末以降に上場廃止になった会社を外す

JPX はファイルのURLや拡張子を変えることがある（2026年9月に .xls → .xlsx）。
URLは一覧ページから毎回探すので、手直しは要らない。

取得に失敗したときは保存済みのリストを使い続け、logs/run_daily.log に警告を残す。
（以前は失敗が静かに続き、9月から1か月間リストが古いままだった）

出力:
    tickers/tse_tickers.csv        対象銘柄（code,name,market）
    tickers/tickers_status.json    各ページの最終取得成功日時など
    tickers/missing_prices.txt     リストにあって株価CSVが無い銘柄（run_daily.sh が過去分を取得）
    logs/tickers_changes.csv       追加・除外の履歴（日付,区分,コード,銘柄名,市場,理由）
    logs/tickers.log               実行ログ

使い方:
    ./.venv/bin/python update_tickers.py           # 更新
    ./.venv/bin/python update_tickers.py --dry-run # 変更内容を表示するだけ
"""

import argparse
import csv
import html
import io
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
TICKERS_CSV = os.path.join(BASE, "tickers", "tse_tickers.csv")
STATUS_JSON = os.path.join(BASE, "tickers", "tickers_status.json")
MISSING_TXT = os.path.join(BASE, "tickers", "missing_prices.txt")
PRICES_DIR = os.path.join(BASE, "data", "prices")
LOGS_DIR = os.path.join(BASE, "logs")
CHANGES_CSV = os.path.join(LOGS_DIR, "tickers_changes.csv")
DAILY_LOG = os.path.join(LOGS_DIR, "run_daily.log")
LOG_FILE = os.path.join(LOGS_DIR, "tickers.log")

INDEX_URL = "https://www.jpx.co.jp/markets/statistics-equities/misc/01.html"
FALLBACK_URL = ("https://www.jpx.co.jp/markets/statistics-equities/misc/"
                "tvdivq0000001vg2-att/data_j.xlsx")
NEW_URL = "https://www.jpx.co.jp/listing/stocks/new/index.html"
DELISTED_URL = "https://www.jpx.co.jp/listing/stocks/delisted/index.html"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

MARKETS = ["プライム", "スタンダード", "グロース"]
CODE_RE = re.compile(r"^[0-9][0-9A-Z]{3}$")   # 4桁の普通株（英数字コード含む）
DATE_RE = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})")

# 一覧が壊れていたときの歯止め：前回より1割以上減ったら差し替えない
MIN_RATIO = 0.9
# 上場銘柄一覧の取得失敗がこの日数続いたら毎回警告する
STALE_DAYS = 10


# ------------------------------------------------------------------ 共通
def log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def warn_daily(msg):
    """run_daily.log にも残す（毎日の処理の失敗一覧と同じ場所）"""
    log("警告: " + msg)
    try:
        with open(DAILY_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] 銘柄リスト: {msg}\n")
    except OSError:
        pass


def notify(title, msg):
    """Mac の通知センターに出す（失敗しても無視）"""
    if sys.platform != "darwin":
        return
    msg = msg.replace('"', "'")[:200]
    try:
        subprocess.run(["osascript", "-e",
                        f'display notification "{msg}" with title "{title}"'],
                       timeout=10, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def get(url, timeout=60):
    import requests
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return r


def page_text(url):
    r = get(url, timeout=30)
    if not r.encoding or r.encoding.lower() in ("iso-8859-1", "ascii"):
        r.encoding = r.apparent_encoding or "utf-8"
    return r.text


def market_of(raw):
    raw = str(raw or "").strip()
    return next((m for m in MARKETS if raw.startswith(m)), None)


def load_csv(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8-sig") as f:
        return {r["code"].strip(): {"code": r["code"].strip(),
                                    "name": (r.get("name") or "").strip(),
                                    "market": (r.get("market") or "").strip()}
                for r in csv.DictReader(f) if (r.get("code") or "").strip()}


def load_status():
    try:
        with open(STATUS_JSON, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# ------------------------------------------------------------------ 1) 上場銘柄一覧
def find_list_url():
    """一覧ページから data_j.xls / data_j.xlsx のリンクを探す（.xlsx 優先）。
    他のスクリプト（audit_coverage.py など）からも使う。"""
    try:
        hits = re.findall(r'href="([^"]*data_j\.xlsx?)"', page_text(INDEX_URL))
        if hits:
            hits.sort(key=lambda h: h.endswith(".xlsx"), reverse=True)
            h = hits[0]
            return h if h.startswith("http") else "https://www.jpx.co.jp" + h
        log("一覧ページに data_j のリンクが見つかりません。既定URLを使います")
    except Exception as e:
        log(f"一覧ページの取得に失敗（{e}）。既定URLを使います")
    return FALLBACK_URL


def fetch_master():
    """JPX の上場銘柄一覧（月末時点）→ {code: row}"""
    import pandas as pd
    url = find_list_url()
    log(f"上場銘柄一覧を取得: {url}")
    df = pd.read_excel(io.BytesIO(get(url).content), dtype=str)
    df.columns = [str(c).strip() for c in df.columns]
    c_code = next(c for c in df.columns if "コード" in c and "業種" not in c and "規模" not in c)
    c_name = next(c for c in df.columns if "銘柄名" in c)
    c_mkt = next(c for c in df.columns if "市場" in c)
    # 一覧の日付（ファイル先頭列が「日付」）
    asof = ""
    c_date = next((c for c in df.columns if c == "日付"), None)
    if c_date is not None and len(df):
        asof = str(df[c_date].iloc[0]).strip()

    rows, skipped = {}, 0
    for _, r in df.iterrows():
        mk = market_of(r[c_mkt])
        if mk is None:
            continue                     # ETF・REIT・PRO Market など
        code = str(r[c_code]).strip()
        if not CODE_RE.match(code):
            skipped += 1                 # 5桁は優先株など
            continue
        rows[code] = {"code": code, "name": str(r[c_name]).strip(), "market": mk}
    if not rows:
        raise RuntimeError("対象銘柄が0件でした")
    log(f"  一覧（{asof or '日付不明'}時点）: {len(rows)} 銘柄 / 優先株等 {skipped} 件を除外")
    return rows, asof


# ------------------------------------------------------------------ 2)3) 新規上場・上場廃止
def table_rows(text):
    """HTMLの表を [[セル文字列, ...], ...] にする（タグを除いた素朴な解析）"""
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", text, flags=re.S | re.I):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, flags=re.S | re.I)
        cells = [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", c))).strip()
                 for c in cells]
        out.append(cells)
    return out


def first_date(cells):
    for c in cells:
        m = DATE_RE.search(c)
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                pass
    return None


def first_code(cells):
    for c in cells:
        c2 = c.replace("　", " ").strip()
        if CODE_RE.match(c2):
            return c2
    return None


def clean_name(s):
    s = s.replace("*", "").replace("＊", "").strip()
    s = re.sub(r"[（(]株[）)]", "", s).strip()
    # JPXの新規上場ページは会社名のセルにリンクの文言（「代表者インタビュー」など）が
    # 一緒に入ることがある（2026-11 648A「ルクレ 代表者インタビュー」）。それを落とす。
    s = re.sub(r"[\s　]*(代表者インタビュー|会社概要|新規上場会社情報|上場会社情報|動画|PDF)[\s　]*$", "", s).strip()
    return s


def parse_listing_page(text):
    """新規上場・上場廃止どちらのページも、
    「日付・会社名・コード（・市場区分）」が並ぶ行を拾う。
    新規上場ページは1社2行（2行目に市場区分）なので、次の行も見る。"""
    rows = table_rows(text)
    found = []
    for i, cells in enumerate(rows):
        d = first_date(cells[:1]) or first_date(cells[:2])
        code = first_code(cells)
        if not d or not code:
            continue
        ci = next(j for j, c in enumerate(cells) if c.replace("　", " ").strip() == code)
        name = clean_name(cells[ci - 1]) if ci >= 1 else ""
        mk = None
        for c in cells[ci + 1:]:
            mk = market_of(c)
            if mk:
                break
        if mk is None and i + 1 < len(rows):
            for c in rows[i + 1]:
                mk = market_of(c)
                if mk:
                    break
        found.append({"date": d, "code": code, "name": name, "market": mk})
    return found


def fetch_new_listings(today):
    items = parse_listing_page(page_text(NEW_URL))
    done = [x for x in items if x["date"] <= today and x["market"]]
    log(f"  新規上場ページ: {len(items)} 件（上場済み・対象市場 {len(done)} 件）")
    return done


def fetch_delisted(today):
    items = parse_listing_page(page_text(DELISTED_URL))
    done = [x for x in items if x["date"] <= today]
    log(f"  上場廃止ページ: {len(items)} 件（廃止日を過ぎたもの {len(done)} 件）")
    return done


# ------------------------------------------------------------------ 本体
def _asof_date(v):
    """一覧の基準日（例 "20260930"）を date にする"""
    m = re.match(r"(\d{4})-?(\d{2})-?(\d{2})", str(v or ""))
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def write_tickers(rows):
    tmp = TICKERS_CSV + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["code", "name", "market"])
        w.writeheader()
        w.writerows(sorted(rows.values(), key=lambda r: r["code"]))
    os.replace(tmp, TICKERS_CSV)


def append_changes(changes):
    new = not os.path.exists(CHANGES_CSV)
    with open(CHANGES_CSV, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["日付", "区分", "コード", "銘柄名", "市場", "理由"])
        w.writerows(changes)


def main():
    p = argparse.ArgumentParser(description="東証の銘柄リストを最新にする")
    p.add_argument("--dry-run", action="store_true", help="書き換えずに変更内容だけ表示")
    args = p.parse_args()

    today = date.today()
    now = datetime.now().isoformat(timespec="seconds")
    status = load_status()
    prev = load_csv(TICKERS_CSV)
    log(f"=== 銘柄リストの確認（現在 {len(prev)} 銘柄） ===")

    errors = []
    reason = {}            # code -> 追加・除外の理由

    # 1) 上場銘柄一覧
    master = None
    try:
        master, asof = fetch_master()
        if prev and len(master) < len(prev) * MIN_RATIO:
            raise RuntimeError(f"件数が前回の{MIN_RATIO:.0%}未満（{len(master)}／{len(prev)}）"
                               "のため一覧が壊れている可能性。差し替えません")
        status["master_ok"] = now
        status["master_asof"] = asof
    except Exception as e:
        master = None
        errors.append(f"上場銘柄一覧の取得に失敗: {e}")

    cur = dict(master) if master is not None else dict(prev)
    if master is not None:
        for c in set(master) - set(prev):
            reason[c] = "JPX上場銘柄一覧に掲載"
        for c in set(prev) - set(master):
            reason[c] = "JPX上場銘柄一覧から消えた"

    # 2) 月末以降の新規上場を足す
    try:
        for x in fetch_new_listings(today):
            if x["code"] not in cur:
                cur[x["code"]] = {"code": x["code"], "name": x["name"], "market": x["market"]}
                reason[x["code"]] = f"新規上場（{x['date']:%Y/%m/%d}）"
        status["new_ok"] = now
    except Exception as e:
        errors.append(f"新規上場ページの取得に失敗: {e}")

    # 3) 月末以降の上場廃止を外す。
    #    一覧の基準日より前の廃止は一覧に反映済み。古い廃止まで当てると、
    #    同じコードが別の会社に振り直された場合に誤って外してしまうので、基準日より後だけにする。
    cutoff = _asof_date(status.get("master_asof")) or (today - timedelta(days=45))
    try:
        for x in fetch_delisted(today):
            if x["date"] <= cutoff:
                continue
            if x["code"] in cur:
                cur.pop(x["code"])
                reason[x["code"]] = f"上場廃止（{x['date']:%Y/%m/%d}）"
        status["delisted_ok"] = now
    except Exception as e:
        errors.append(f"上場廃止ページの取得に失敗: {e}")

    added = sorted(set(cur) - set(prev))
    removed = sorted(set(prev) - set(cur))
    changes = ([[today.isoformat(), "追加", c, cur[c]["name"], cur[c]["market"],
                 reason.get(c, "")] for c in added]
               + [[today.isoformat(), "除外", c, prev[c]["name"], prev[c]["market"],
                   reason.get(c, "")] for c in removed])
    for ch in changes:
        log(f"  {ch[1]} {ch[2]} {ch[3]}（{ch[4]}）{ch[5]}")

    have = {f[:-4] for f in os.listdir(PRICES_DIR) if f.endswith(".csv")} \
        if os.path.isdir(PRICES_DIR) else set()
    missing = sorted(c for c in cur if c not in have)

    if args.dry_run:
        log(f"（dry-run）追加 {len(added)} / 除外 {len(removed)} → {len(cur)} 銘柄。"
            f"株価CSVが無い銘柄 {len(missing)}")
        for e in errors:
            log("  " + e)
        return 0

    if changes:
        write_tickers(cur)
        append_changes(changes)
    elif not os.path.exists(TICKERS_CSV):
        write_tickers(cur)
    else:
        os.utime(TICKERS_CSV)   # 「確認済み」の印として更新日時だけ進める

    with open(MISSING_TXT, "w", encoding="utf-8") as f:
        f.write("".join(c + "\n" for c in missing))

    status["checked"] = now
    status["count"] = len(cur)
    status["last_added"] = added
    status["last_removed"] = removed
    status["errors"] = errors
    with open(STATUS_JSON, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=1)

    for e in errors:
        warn_daily(e + "（保存済みのリストで続行）")
    ok = status.get("master_ok")
    if ok:
        age = (datetime.now() - datetime.fromisoformat(ok)).days
        if age >= STALE_DAYS:
            warn_daily(f"上場銘柄一覧の取得が {age} 日間成功していません。"
                       "JPXのページ構成が変わった可能性があります（logs/tickers.log）")
            notify("株分析：銘柄リスト", f"JPX一覧の取得が{age}日間失敗しています")

    log(f"=== 完了: 追加 {len(added)} / 除外 {len(removed)} → {len(cur)} 銘柄。"
        f"株価CSVが無い銘柄 {len(missing)}{'（' + ' '.join(missing[:10]) + '）' if missing else ''} ===")

    if changes:
        parts = []
        if added:
            parts.append("追加 " + "、".join(cur[c]["name"] for c in added[:5])
                         + (f" ほか{len(added) - 5}" if len(added) > 5 else ""))
        if removed:
            parts.append(f"除外 {len(removed)}社")
        notify("株分析：銘柄リストを更新", " ／ ".join(parts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
