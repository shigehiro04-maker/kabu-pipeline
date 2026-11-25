#!/usr/bin/env python3
"""JPXの上場銘柄一覧(data_j.xls)から、全市場の 銘柄名・市場区分・33業種 を取得する。

出力: tickers/sectors.csv  (code, name, market, sector33, listed, size=規模区分)
プライム銘柄には業種情報が無かったため、これで全市場ぶんを揃えます。

実行:
    ~/株分析/jpx_prices/.venv/bin/python ~/株分析/fetch_sectors.py
"""
import io, os, re, sys
import pandas as pd
import requests

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "tickers", "sectors.csv")
INDEX_URL = "https://www.jpx.co.jp/markets/statistics-equities/misc/01.html"
# JPXは2026年9月に data_j.xls から data_j.xlsx へ切り替えた。
# 拡張子も変わりうるので、索引ページから拾うのを基本にし、これは保険。
FALLBACK = ("https://www.jpx.co.jp/markets/statistics-equities/misc/"
            "tvdivq0000001vg2-att/data_j.xlsx")
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


def xls_url():
    try:
        r = requests.get(INDEX_URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
        # .xls / .xlsx どちらでも拾う。新しい方を優先する
        hits = re.findall(r'href="([^"]*data_j\.xlsx?)"', r.text)
        m = None
        if hits:
            hits.sort(key=lambda h: h.endswith('.xlsx'), reverse=True)
            m = re.match(r'(.*)', hits[0])
        if m:
            h = m.group(1)
            return h if h.startswith("http") else "https://www.jpx.co.jp" + h
    except Exception as e:
        print(f"一覧ページの取得に失敗（{e}）。既定URLを使います。")
    return FALLBACK


def main():
    url = xls_url()
    print("銘柄一覧をダウンロード中…")
    r = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    df = pd.read_excel(io.BytesIO(r.content), dtype=str)
    df.columns = [str(c).strip() for c in df.columns]

    c_code = next(c for c in df.columns if "コード" in c and "業種" not in c and "規模" not in c)
    c_name = next(c for c in df.columns if "銘柄名" in c)
    c_mkt = next(c for c in df.columns if "市場" in c)
    c_sec = next((c for c in df.columns if "33業種区分" in c), None)
    # 規模区分（TOPIX Core30 / Large70 / Mid400 / Small 1 / Small 2 / -）。スクリーニングの「規模」に使う
    c_size = next((c for c in df.columns if "規模区分" in c), None)

    out = pd.DataFrame({
        "code": df[c_code].str.strip(),
        "name": df[c_name].str.strip(),
        "market": df[c_mkt].fillna("").str.strip(),
        "sector33": (df[c_sec].fillna("").str.strip() if c_sec else ""),
        "size": (df[c_size].fillna("").str.strip() if c_size else ""),
        # 今回のJPX一覧に載っている＝現在上場中
        "listed": "1",
    }).drop_duplicates(subset="code").sort_values("code")
    # 「-」など業種が無いものは空にする
    out["sector33"] = out["sector33"].replace({"-": "", "―": "", "－": ""})
    out["size"] = out["size"].replace({"-": "", "―": "", "－": ""})

    # JPXの一覧はその月末時点のものなので、上場廃止・統合で消えた銘柄は載らない。
    # 単純に上書きすると、手元にまだ株価がある銘柄の業種だけ空になってしまうため、
    # 前回のファイルに居て今回消えた銘柄はそのまま引き継ぐ。
    carried = 0
    if os.path.exists(OUT):
        prev = pd.read_csv(OUT, dtype=str).fillna("")
        missing = prev[~prev["code"].isin(out["code"])].copy()
        missing = missing[missing["sector33"] != ""]
        if len(missing):
            carried = len(missing)
            # 業種は引き継ぐが、いまは上場していない印を付ける。
            # analyze_fundamentals.py はこの列を見て上場廃止銘柄を外す。
            missing["listed"] = "0"
            out = pd.concat([out, missing], ignore_index=True).sort_values("code")

    # JPXの一覧（月末時点）にまだ載っていない新規上場（テクニカル上場など）の業種を補う。
    # tickers/sector_overrides.csv に手で書いたもの。JPXの一覧に載った月からはJPXの値が優先される。
    ov_path = os.path.join(BASE, "tickers", "sector_overrides.csv")
    if os.path.exists(ov_path):
        ov = pd.read_csv(ov_path, dtype=str).fillna("")
        ov = ov[~ov["code"].isin(out["code"])]
        if len(ov):
            ov = ov[["code", "name", "market", "sector33", "size"]].copy()
            ov["listed"] = "1"
            out = pd.concat([out[out["code"].isin(ov["code"]) == False], ov],
                            ignore_index=True).sort_values("code")
            print(f"  ※ JPX一覧に未掲載の{len(ov)}銘柄の業種を sector_overrides.csv から補いました")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    out = out.fillna("")
    out.to_csv(OUT, index=False, encoding="utf-8")
    print(f"保存しました: {OUT}（{len(out)}銘柄）")
    if carried:
        print(f"  ※ 今回のJPX一覧に無い{carried}銘柄は、業種を引き継ぎ listed=0 を付けました")
    for mk, n in out["market"].value_counts().head(8).items():
        print(f"  - {mk}: {n}")
    print(f"  業種が入っている銘柄: {(out['sector33'] != '').sum()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
