"""需給分析：JPX・日本証券金融の無料公開データを取得して 需給分析/data/ に蓄積する。

  取得するもの（すべて無料・ログイン不要）
    1. 銘柄別信用取引残高（JPX、毎営業日16時ごろ、全銘柄PDF）   → data/margin/申込日.csv・margin_total.csv
       ※ JPXのページには直近5営業日分しか置かれないので、毎日取って貯める
    2. 日々公表銘柄等信用取引残高（JPX、Excel）の規制・注意の印   → data/flags.csv
    3. 日証金 貸借取引残高・品貸料（逆日歩）（毎営業日）          → data/taisyaku/・data/shina/
    4. 空売り残高に関する情報（JPX、残高割合0.5%以上、17時ごろ）  → data/short_positions/計算日.csv
    5. 空売り集計（JPX、市場全体・業種別、日次）                  → data/short_market.csv・short_sector.csv
    6. 投資部門別 株式売買状況（JPX、週次・木曜15時半）           → data/investor_weekly.csv
    7. 信用取引現在高 過去推移表（JPX、週次・2002年〜の市場全体） → data/margin_market_weekly.csv

  python fetch_jukyu.py             通常（新しいファイルだけ取る）
  python fetch_jukyu.py --backfill  バックナンバー（約1年分）も取る。初回に1回だけ
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jk_parse as P  # noqa: E402

DIR = Path(__file__).resolve().parent
DATA = DIR / "data"
RAW = DIR / "raw"
STATE = DATA / "state.json"
JPX = "https://www.jpx.co.jp"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) kabu-bunseki/1.0 (personal use)"}
S = requests.Session()
S.headers.update(UA)


def log(*a):
    print(f"[{datetime.now():%H:%M:%S}]", *a, flush=True)


def get(url: str, binary=False, tries=3):
    for i in range(tries):
        try:
            r = S.get(url, timeout=60)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            time.sleep(0.4)                  # 取引所サイトへの配慮
            return r.content if binary else r.content.decode("utf-8", errors="replace")
        except requests.RequestException as e:
            if i == tries - 1:
                log(f"取得に失敗: {url} ({e})")
                return None
            time.sleep(3 * (i + 1))


def links(page: str, pat: str) -> list[str]:
    html = get(urljoin(JPX, page))
    if not html:
        return []
    found = re.findall(r'(?:href|value)="([^"]+)"', html)
    out = []
    for h in found:
        if re.search(pat, h):
            u = urljoin(JPX, h)
            if u not in out:
                out.append(u)
    return out


def download(url: str, dest: Path) -> Path | None:
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    b = get(url, binary=True)
    if not b:
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b)
    return dest


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(st: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def upsert_csv(path: Path, df: pd.DataFrame, keys: list[str]) -> None:
    """keys が同じ行は新しいほうで置き換えて追記する"""
    if df is None or df.empty:
        return
    df = df.copy()
    for k in keys:
        df[k] = df[k].astype(str)
    if path.exists():
        old = pd.read_csv(path, encoding="utf-8-sig", dtype={k: str for k in keys})
        df = pd.concat([old, df]).drop_duplicates(keys, keep="last")
    df.sort_values(keys).to_csv(path, index=False, encoding="utf-8-sig")


# ------------------------------------------------------------ 1. 銘柄別信用取引残高

def fetch_margin(st: dict) -> int:
    urls = links("/markets/statistics-equities/margin/01.html", r"_mtall\.pdf$")
    n = 0
    for u in sorted(urls):
        d8 = re.search(r"(\d{8})_mtall", u)[1]
        day = f"{d8[:4]}-{d8[4:6]}-{d8[6:]}"
        out = DATA / "margin" / f"{day}.csv"
        if out.exists():
            continue
        pdf = download(u, RAW / f"{d8}_mtall.pdf")
        if not pdf:
            continue
        try:
            df, sub, asof = P.parse_margin_pdf(pdf)
        except Exception as e:
            log(f"信用残PDFの読み取りに失敗 {pdf.name}: {e}")
            continue
        if asof and asof.isoformat() != day:
            log(f"※ ファイル名の日付 {day} とPDFの申込日 {asof} がちがいます。PDFの日付を使います")
            day = asof.isoformat()
            out = DATA / "margin" / f"{day}.csv"
        out.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out, index=False, encoding="utf-8-sig")
        if not sub.empty:
            sub.insert(0, "申込日", day)
            upsert_csv(DATA / "margin_total.csv", sub, ["申込日", "区分"])
        tot = sub.loc[sub["区分"] == "総合計"]
        cov = ""
        if len(tot):
            cov = f"（総合計の買残に対する読み取り率 {df['買残'].sum() / tot['買残'].iat[0] * 100:.2f}%）"
        log(f"信用残 {day}: {len(df):,}銘柄 {cov}")
        pdf.unlink(missing_ok=True)          # 読み取ったPDFは消す（1日1.7MB）
        n += 1
    return n


# ------------------------------------------------------------ 2. 日々公表銘柄等（印）

def fetch_flags(st: dict) -> None:
    urls = links("/markets/statistics-equities/margin/index.html", r"_mtdaily\.xlsx?$")
    if not urls:
        return
    u = sorted(urls)[-1]
    if st.get("flags_url") == u and (DATA / "flags.csv").exists():
        return
    f = download(u, RAW / Path(u).name)
    if not f:
        return
    try:
        fl = P.parse_daily_flags(f)
        fl.insert(0, "日付", re.search(r"(\d{8})", u)[1])
        fl.to_csv(DATA / "flags.csv", index=False, encoding="utf-8-sig")
        st["flags_url"] = u
        log(f"日々公表銘柄等: {len(fl)}銘柄")
    except Exception as e:
        log(f"日々公表銘柄等の読み取りに失敗: {e}")
    f.unlink(missing_ok=True)


# ------------------------------------------------------------ 3. 日証金

def fetch_taisyaku(st: dict) -> None:
    for name, parser, sub in (("zandaka.csv", P.parse_taisyaku, "taisyaku"),
                              ("shina.csv", P.parse_shina, "shina")):
        b = get(f"https://www.taisyaku.jp/data/{name}", binary=True)
        if not b:
            continue
        tmp = RAW / name
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(b)
        try:
            df = parser(tmp)
        except Exception as e:
            log(f"日証金 {name} の読み取りに失敗: {e}")
            continue
        # 申込日（ファイルの中身）で保存
        if "申込日" in df.columns:
            day = str(max(df["申込日"]))
        else:
            raw = P._read_csv_jp(tmp, header=None, dtype=str, skiprows=4)
            day = pd.to_datetime(raw.iloc[:, 0].dropna().astype(str).str[:8], format="%Y%m%d",
                                 errors="coerce").max().date().isoformat()
        out = DATA / sub / f"{day}.csv"
        out.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out, index=False, encoding="utf-8-sig")
        log(f"日証金 {name}: {day} {len(df):,}銘柄")
        tmp.unlink(missing_ok=True)


# ------------------------------------------------------------ 4. 空売り残高（0.5%以上）

def fetch_short_positions(st: dict, backfill: bool) -> None:
    pages = ["/markets/public/short-selling/index.html"]
    if backfill:
        pages += [f"/markets/public/short-selling/00-archives-{i:02d}.html" for i in range(1, 13)]
    urls = []
    for p in pages:
        urls += links(p, r"_Short_Positions\.xlsx?$")
    n = 0
    for u in sorted(set(urls)):
        d8 = re.search(r"(\d{8})_Short", u)[1]
        out = DATA / "short_positions" / f"{d8[:4]}-{d8[4:6]}-{d8[6:]}.csv"
        if out.exists():
            continue
        f = download(u, RAW / Path(u).name)
        if not f:
            continue
        try:
            df = P.parse_short_positions(f)
            out.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(out, index=False, encoding="utf-8-sig")
            n += 1
        except Exception as e:
            log(f"空売り残高の読み取りに失敗 {f.name}: {e}")
        f.unlink(missing_ok=True)
    if n:
        log(f"空売り残高（0.5%以上の報告）: {n}日分を追加")


# ------------------------------------------------------------ 5. 空売り集計（日次）

def fetch_short_selling(st: dict, backfill: bool) -> None:
    pages = ["/markets/statistics-equities/short-selling/index.html"]
    if backfill:
        pages += [f"/markets/statistics-equities/short-selling/00-archives-{i:02d}.html" for i in range(1, 13)]
    urls = []
    for p in pages:
        urls += links(p, r"\d{6}-[mg]\.pdf$")
    done = set(st.get("short_selling_done", []))
    mk_rows, sec_rows = [], []
    for u in sorted(set(urls)):
        key = Path(u).name
        if key in done:
            continue
        f = download(u, RAW / key)
        if not f:
            continue
        try:
            if key.endswith("-m.pdf"):
                day, rec = P.parse_short_market(f)
                if day:
                    mk_rows.append({"日付": day.isoformat(), **rec})
            else:
                day, g = P.parse_short_sector(f)
                if day and not g.empty:
                    g.insert(0, "日付", day.isoformat())
                    sec_rows.append(g)
            done.add(key)
        except Exception as e:
            log(f"空売り集計の読み取りに失敗 {key}: {e}")
        f.unlink(missing_ok=True)
    if mk_rows:
        upsert_csv(DATA / "short_market.csv", pd.DataFrame(mk_rows), ["日付"])
    if sec_rows:
        upsert_csv(DATA / "short_sector.csv", pd.concat(sec_rows), ["日付", "業種"])
    st["short_selling_done"] = sorted(done)[-1500:]
    if mk_rows or sec_rows:
        log(f"空売り集計: 市場 {len(mk_rows)}日・業種別 {len(sec_rows)}日を追加")


# ------------------------------------------------------------ 6. 投資部門別（週次）

def fetch_investor(st: dict, backfill: bool) -> None:
    pages = ["/markets/statistics-equities/investor-type/index.html"]
    if backfill:
        pages += [f"/markets/statistics-equities/investor-type/00-00-archives-{i:02d}.html" for i in range(0, 3)]
    urls = []
    for p in pages:
        urls += links(p, r"(stock_val_1_\d{6}\.xls|stock_1_w_\d{8}_\d{8}\.xlsx)$")
    done = set(st.get("investor_done", []))
    rows = []
    for u in sorted(set(urls)):
        key = Path(u).name
        if key in done or "YYYY" in key:
            continue
        f = download(u, RAW / key)
        if not f:
            continue
        try:
            if key.startswith("stock_1_w_"):
                e = re.search(r"_(\d{8})\.xlsx$", key)[1]
                df = P.parse_investor_new(f, date(int(e[:4]), int(e[4:6]), int(e[6:])))
            else:
                df = P.parse_investor_old(f)
            if not df.empty:
                rows.append(df)
                done.add(key)
        except Exception as ex:
            log(f"投資部門別の読み取りに失敗 {key}: {ex}")
        f.unlink(missing_ok=True)
    if rows:
        d = pd.concat(rows)
        d["週末"] = d["週末"].astype(str)
        upsert_csv(DATA / "investor_weekly.csv", d, ["週末", "市場"])
        log(f"投資部門別: {d['週末'].nunique()}週分を追加")
    st["investor_done"] = sorted(done)


# ------------------------------------------------------------ 7. 信用取引現在高 過去推移表（市場全体・週次）

def fetch_market_weekly(st: dict) -> None:
    urls = links("/markets/statistics-equities/margin/05.html", r"\.xls$")
    # 2つのxlsのうち「信用取引現在高」（一般・制度別ではない方）を見出しで見分ける
    for u in urls:
        f = download(u, RAW / Path(u).name)
        if not f:
            continue
        try:
            x = pd.read_excel(f, header=None)
            title = str(x.iat[0, 0])
            if "一般" in " ".join(str(v) for v in x.iloc[0:4].to_numpy().ravel()):
                f.unlink(missing_ok=True)
                continue
            d = x.iloc[10:, :13].copy()
            d.columns = ["申込日", "委託売株", "委託売金額", "委託買株", "委託買金額", "自己売株", "自己売金額",
                         "自己買株", "自己買金額", "売残株", "売残金額", "買残株", "買残金額"]
            d["申込日"] = pd.to_datetime(d["申込日"], errors="coerce")
            d = d[d["申込日"].notna()]
            for c in d.columns[1:]:
                d[c] = pd.to_numeric(d[c], errors="coerce")
            d["申込日"] = d["申込日"].dt.date.astype(str)
            d.to_csv(DATA / "margin_market_weekly.csv", index=False, encoding="utf-8-sig")
            log(f"信用取引現在高（週次・市場全体）: {d['申込日'].iat[0]}〜{d['申込日'].iat[-1]} {len(d)}週（{title}）")
        except Exception as e:
            log(f"信用取引現在高の読み取りに失敗 {f.name}: {e}")
        f.unlink(missing_ok=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true", help="バックナンバー（約1年分）も取る")
    ap.add_argument("--only", default="", help="カンマ区切りで一部だけ: margin,flags,taisyaku,sp,ss,inv,mkt")
    a = ap.parse_args()
    DATA.mkdir(parents=True, exist_ok=True)
    st = load_state()
    only = set(filter(None, a.only.split(",")))
    jobs = [("margin", lambda: fetch_margin(st)), ("flags", lambda: fetch_flags(st)),
            ("taisyaku", lambda: fetch_taisyaku(st)),
            ("sp", lambda: fetch_short_positions(st, a.backfill)),
            ("ss", lambda: fetch_short_selling(st, a.backfill)),
            ("inv", lambda: fetch_investor(st, a.backfill)), ("mkt", lambda: fetch_market_weekly(st))]
    for name, fn in jobs:
        if only and name not in only:
            continue
        try:
            fn()
        except Exception as e:                 # 1つ失敗しても残りは続ける
            log(f"{name} で想定外のエラー: {e!r}")
        save_state(st)
    return 0


if __name__ == "__main__":
    sys.exit(main())
