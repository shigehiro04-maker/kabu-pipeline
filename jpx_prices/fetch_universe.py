"""JPXの上場銘柄一覧(data_j.xls)から スタンダード・グロース 全銘柄を抽出する。

出力: data/tickers.csv  (code, name, market, sector33, ticker)
"""
import io
import re
import sys

import pandas as pd
import requests

from common import TICKERS_CSV, ENCODING, log

INDEX_URL   = "https://www.jpx.co.jp/markets/statistics-equities/misc/01.html"
FALLBACK_XLS = ("https://www.jpx.co.jp/markets/statistics-equities/misc/"
                "tvdivq0000001vg2-att/data_j.xlsx")
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

# 対象とする市場区分（"スタンダード（内国株式）" 等を部分一致で拾う）
TARGET_MARKET_RE = re.compile(r"(?:スタンダード|グロース)")


def find_xls_url() -> str:
    """一覧ページから data_j.xls のリンクを探す。失敗したら既知URLを使う。"""
    try:
        r = requests.get(INDEX_URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
        # 2026年9月に .xls → .xlsx へ変わった。両方拾い、.xlsx を優先する
        hits = re.findall(r'href="([^"]*data_j\.xlsx?)"', r.text)
        hits.sort(key=lambda h: h.endswith(".xlsx"), reverse=True)
        if hits:
            href = hits[0]
            url = href if href.startswith("http") else "https://www.jpx.co.jp" + href
            log(f"銘柄一覧URLを検出: {url}")
            return url
        log("ページ内にdata_j.xlsのリンクが見つからず。既定URLを使用します。")
    except Exception as e:
        log(f"一覧ページの取得に失敗({e})。既定URLを使用します。")
    return FALLBACK_XLS


def main() -> int:
    url = find_xls_url()
    log("銘柄一覧をダウンロード中...")
    r = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()

    df = pd.read_excel(io.BytesIO(r.content), dtype=str)
    df.columns = [str(c).strip() for c in df.columns]

    col_code   = next(c for c in df.columns if "コード" in c and "業種" not in c and "規模" not in c)
    col_name   = next(c for c in df.columns if "銘柄名" in c)
    col_market = next(c for c in df.columns if "市場" in c)
    col_sector = next((c for c in df.columns if "33業種区分" in c), None)

    log(f"全上場銘柄: {len(df)} 件")
    sub = df[df[col_market].fillna("").str.contains(TARGET_MARKET_RE)].copy()
    log(f"スタンダード・グロース該当: {len(sub)} 件")
    for mk, n in sub[col_market].value_counts().items():
        log(f"  - {mk}: {n} 件")

    out = pd.DataFrame({
        "code":     sub[col_code].str.strip(),
        "name":     sub[col_name].str.strip(),
        "market":   sub[col_market].str.strip(),
        "sector33": (sub[col_sector].fillna("").str.strip() if col_sector else ""),
    })
    out["ticker"] = out["code"] + ".T"
    out = out.drop_duplicates(subset="code").sort_values("code")

    TICKERS_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(TICKERS_CSV, index=False, encoding=ENCODING)
    log(f"保存しました: {TICKERS_CSV} ({len(out)} 銘柄)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
