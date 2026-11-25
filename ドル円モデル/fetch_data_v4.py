#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
 fetch_data.py — ドル円モデル用データの自動取得
================================================================================

FRED（米セントルイス連銀）と財務省から、必要なデータを自動でダウンロードして
1本のCSVにまとめます。**APIキーもアカウント登録も不要**です。

  取得元1  FRED    ドル円 / 米2年債 / 米10年債 / VIX
           https://fred.stlouisfed.org/graph/fredgraph.csv
  取得元2  財務省  日本2年債 / 日本10年債（国債金利情報 昭和49年〜）
           https://www.mof.go.jp/jgbs/reference/interest_rate/data/jgbcm_all.csv

--------------------------------------------------------------------------------
 使い方
--------------------------------------------------------------------------------
  # 直近4年分を data.csv に保存
  python3 fetch_data.py

  # 期間を指定
  python3 fetch_data.py --start 2018-01-01 --end 2026-09-08 --out mydata.csv

  # 取得してそのまま分析まで走らせる
  python3 usdjpy_model.py --fetch

  必要パッケージ: pandas （requests は不要。標準ライブラリだけで通信します）

--------------------------------------------------------------------------------
 うまくいかないとき
--------------------------------------------------------------------------------
  ・社内ネットワークなどでプロキシが必要な場合は、環境変数を設定してください
        export HTTPS_PROXY=http://proxy.example.com:8080
  ・財務省サイトは日本時間の深夜にメンテナンスで落ちることがあります。
    時間をおいて再実行してください。
  ・どうしても通らない場合は、両サイトからブラウザで手動ダウンロードして
    --fred-file / --jgb-file にそのファイルを渡せば、同じ処理ができます。
================================================================================
"""

from __future__ import annotations

import argparse
import io
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
MOF_URL = "https://www.mof.go.jp/jgbs/reference/interest_rate/data/jgbcm_all.csv"

# FREDの系列IDと、このモデルでの列名の対応
FRED_SERIES = {
    "DEXJPUS": "usdjpy",   # ドル円（東京時間ではなくNY終値ベース）
    "DGS2":    "us2y",     # 米2年債利回り
    "DGS10":   "us10y",    # 米10年債利回り
    "VIXCLS":  "vix",      # VIX指数
}

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# 素の urllib は CDN に弾かれることがあるので、ブラウザ相当のヘッダーを付ける
BROWSER_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/csv,text/plain,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
}

# 和暦→西暦のオフセット（令和1年=2019年, 平成1年=1989年, 昭和1年=1926年）
ERA_OFFSET = {"R": 2018, "H": 1988, "S": 1925}
ERA_RE = re.compile(r"^\s*([SHR])(\d+)\.(\d+)\.(\d+)\s*$")


# ==============================================================================
# 通信
# ==============================================================================

def _via_requests(url: str, timeout: int) -> bytes:
    """requests があればこれを使う。ヘッダーとgzipの扱いが最も素直。"""
    import requests  # 未インストールなら ImportError で次の手段へ
    s = requests.Session()
    s.headers.update(BROWSER_HEADERS)
    r = s.get(url, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    return r.content


def _via_urllib(url: str, timeout: int) -> bytes:
    """標準ライブラリのみ。gzipを要求しないので解凍不要。"""
    h = dict(BROWSER_HEADERS)
    h.pop("Accept-Encoding", None)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _via_curl(url: str, timeout: int) -> bytes:
    """macOS/Linuxに標準で入っている curl を使う最後の手段。"""
    import shutil
    import subprocess
    exe = shutil.which("curl")
    if not exe:
        raise FileNotFoundError("curl が見つかりません")
    # --http1.1 は必須。FREDのCDNはHTTP/2で "stream not closed cleanly (err 92)"
    # を返すことがあり、その場合HTTP/1.1に落とすと通る。
    cmd = [exe, "-sS", "--fail", "--location", "--compressed", "--http1.1",
           "--retry", "1", "--retry-delay", "1",
           "--connect-timeout", "20", "--max-time", str(timeout),
           "-A", BROWSER_HEADERS["User-Agent"],
           "-H", f"Accept: {BROWSER_HEADERS['Accept']}",
           url]
    p = subprocess.run(cmd, capture_output=True, timeout=timeout + 15)
    if p.returncode != 0:
        raise RuntimeError(f"curl 終了コード {p.returncode}: "
                           f"{p.stderr.decode('utf-8', 'replace').strip()[:200]}")
    if not p.stdout:
        raise RuntimeError("curl は成功しましたが中身が空でした")
    return p.stdout


TRANSPORTS = {"requests": _via_requests, "urllib": _via_urllib, "curl": _via_curl}


class FetchError(Exception):
    """取得に失敗したが、呼び出し側で握って別の手段を試したい場合に使う。"""


def http_get(url: str, timeout: int = 60, retries: int = 2,
             transport: str | None = None, quiet: bool = False) -> bytes:
    """
    URLからバイト列を取得する。

    サイト側（CDN）が素の urllib を弾くことがあるため、requests → urllib → curl の
    順に自動で試します。--transport で1つに固定することもできます。
    """
    order = [transport] if transport else ["requests", "urllib", "curl"]
    errors = []

    for name in order:
        fn = TRANSPORTS.get(name)
        if fn is None:
            raise SystemExit(f"[エラー] 未知の通信方法: {name}  "
                             f"（{', '.join(TRANSPORTS)} のいずれか）")
        for i in range(retries):
            try:
                data = fn(url, timeout)
                if data:
                    if name != order[0] or i > 0:
                        print(f"    （{name} で取得できました）", file=sys.stderr)
                    return data
                raise RuntimeError("応答が空でした")
            except ImportError:
                errors.append(f"{name}: 未インストール（スキップ）")
                break
            except Exception as e:                # 接続断・タイムアウト・HTTPエラー全般
                errors.append(f"{name}: {type(e).__name__}: {str(e)[:120]}")
                if i < retries - 1:
                    time.sleep(2 ** i)

    detail = "\n".join(f"          - {e}" for e in errors)
    if quiet:
        raise FetchError(f"{url}\n{detail}")
    raise SystemExit(
        f"[エラー] {url} からデータを取得できませんでした。\n"
        f"        試した方法と結果:\n{detail}\n\n"
        f"        よくある原因と対処:\n"
        f"        1) requests が未インストール → pip install requests\n"
        f"        2) 会社・学校のネットワークでプロキシが必要\n"
        f"             export HTTPS_PROXY=http://proxy.example.com:8080\n"
        f"        3) サイト側が一時的に落ちている → 時間をおいて再実行\n"
        f"        4) それでも駄目なら、ブラウザで手動ダウンロードして\n"
        f"             python3 fetch_data.py --fred-file <保存先> --jgb-file <保存先>\n"
        f"           のように渡せば、同じ処理が使えます。\n"
        f"           FRED  : {FRED_URL}?id=DEXJPUS,DGS2,DGS10,VIXCLS&cosd=2022-01-01\n"
        f"           財務省: {MOF_URL}"
    )


# ==============================================================================
# FRED
# ==============================================================================

def _parse_fred_txt(raw: bytes, colname: str) -> pd.DataFrame:
    """
    https://fred.stlouisfed.org/data/<ID>.txt の形式をパースする。

        Title:               Japanese Yen to U.S. Dollar Spot Exchange Rate
        Series ID:           DEXJPUS
        ...
        DATE          VALUE
        1971-01-04    357.7300
    """
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    start_i = None
    for i, ln in enumerate(lines):
        parts = ln.split()
        if len(parts) >= 2 and parts[0].upper() == "DATE" and parts[1].upper() == "VALUE":
            start_i = i + 1
            break
    if start_i is None:
        raise ValueError("DATE/VALUE の見出し行が見つかりません")

    rows = []
    for ln in lines[start_i:]:
        parts = ln.split()
        if len(parts) >= 2:
            rows.append((parts[0], parts[1]))
    if not rows:
        raise ValueError("データ行がありません")

    df = pd.DataFrame(rows, columns=["date", colname])
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df[colname] = pd.to_numeric(df[colname], errors="coerce")  # 休場日の "." は NaN に
    return df.dropna(subset=["date"])


def _parse_fred_csv(raw: bytes) -> pd.DataFrame:
    """fredgraph.csv 形式（1列目が日付、以降が系列）をパースする。"""
    df = pd.read_csv(io.StringIO(raw.decode("utf-8", errors="replace")))
    if df.empty:
        raise ValueError("空のCSVです")
    df = df.rename(columns={df.columns[0]: "date"})
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for c in df.columns[1:]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna(subset=["date"])


def _fetch_one_series(sid: str, colname: str, start: str, end: str,
                      transport: str | None) -> pd.DataFrame:
    """
    1系列だけ取得する。まず軽いテキスト版、駄目ならCSV版を試す。

    4系列をまとめて1本のURLで取ると、FRED側がその場でCSVを生成するため
    重く、接続を切られたりタイムアウトしたりすることがある。1系列ずつなら
    キャッシュの効いた軽いリクエストになるので、通りやすい。
    """
    attempts = [
        ("テキスト版", f"https://fred.stlouisfed.org/data/{sid}.txt",
         lambda r: _parse_fred_txt(r, colname)),
        ("CSV版", f"{FRED_URL}?id={sid}&cosd={start}&coed={end}",
         lambda r: _parse_fred_csv(r).rename(columns={sid: colname})[["date", colname]]),
    ]
    errs = []
    for label, url, parse in attempts:
        try:
            raw = http_get(url, timeout=90, transport=transport, quiet=True)
            return parse(raw)
        except FetchError as e:
            # 通信の失敗理由（方法ごと）をそのまま残す
            for ln in str(e).splitlines()[1:]:
                errs.append(f"{label} {ln.strip()}")
        except Exception as e:
            errs.append(f"{label} 解析エラー: {type(e).__name__}: {str(e)[:90]}")
    raise RuntimeError("\n".join(f"           {e}" for e in errs))


def fetch_fred(start: str, end: str, local_file: str | None = None,
               transport: str | None = None) -> pd.DataFrame:
    """FREDから4系列を取得する。APIキーは不要。"""
    if local_file:
        print(f"  [FRED] ローカルファイルを読み込み: {local_file}")
        df = _parse_fred_csv(Path(local_file).read_bytes())
        df = df.rename(columns=FRED_SERIES)
    else:
        print(f"  [FRED] 取得中（1系列ずつ）")
        frames, failed = [], []
        for sid, col in FRED_SERIES.items():
            try:
                f = _fetch_one_series(sid, col, start, end, transport)
                print(f"         {sid:<8} → {len(f):>6,}行")
                frames.append(f)
            except Exception as e:
                print(f"         {sid:<8} → 失敗:\n{e}", file=sys.stderr)
                failed.append(sid)

        essential = [s for s in ("DEXJPUS", "DGS2") if s in failed]
        if essential:
            raise SystemExit(
                f"\n[エラー] 必須の系列 {essential} を取得できませんでした。\n"
                f"        `python3 fetch_data.py --probe` で、どの通信方法なら\n"
                f"        届くのかを先に確認してください。\n"
                f"        全部駄目な場合は、ブラウザで下記を開いて保存し\n"
                f"        --fred-file で渡してください:\n"
                f"        {FRED_URL}?id=DEXJPUS,DGS2,DGS10,VIXCLS&cosd={start}"
            )
        if failed:
            print(f"  [FRED] {failed} は取得できませんでしたが、補助的な系列なので続行します。",
                  file=sys.stderr)

        df = frames[0]
        for f in frames[1:]:
            df = pd.merge(df, f, on="date", how="outer")

    for c in FRED_SERIES.values():
        if c not in df.columns:
            df[c] = float("nan")

    df = df.sort_values("date")
    df = df[(df["date"] >= pd.Timestamp(start)) & (df["date"] <= pd.Timestamp(end))]
    df = df[["date"] + list(FRED_SERIES.values())].reset_index(drop=True)
    if df.empty:
        raise SystemExit("[エラー] 指定期間のFREDデータが0行でした。期間を見直してください。")
    print(f"         → 合計 {len(df)}行（{df['date'].min():%Y-%m-%d} 〜 {df['date'].max():%Y-%m-%d}）")
    return df


# ==============================================================================
# 財務省（国債金利情報）
# ==============================================================================

def _wareki_to_date(s: str):
    """'R7.4.25' のような和暦表記を datetime に変換する。"""
    m = ERA_RE.match(str(s))
    if not m:
        return pd.NaT
    era, y, mo, d = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))
    try:
        return pd.Timestamp(year=ERA_OFFSET[era] + y, month=mo, day=d)
    except (ValueError, KeyError):
        return pd.NaT


def fetch_jgb(local_file: str | None = None,
              transport: str | None = None) -> pd.DataFrame:
    """財務省の国債金利情報から2年債・10年債の利回りを取り出す。"""
    if local_file:
        print(f"  [財務省] ローカルファイルを読み込み: {local_file}")
        raw = Path(local_file).read_bytes()
    else:
        print(f"  [財務省] 取得中: 国債金利情報（昭和49年〜の全期間）")
        raw = http_get(MOF_URL, timeout=120, transport=transport)

    # 財務省のCSVはShift-JIS(cp932)。先頭にタイトル行が入るが、行数が変わることが
    # あるので「基準日」を含む行を探してヘッダー行として使う（決め打ちしない）。
    text = raw.decode("cp932", errors="replace")
    lines = text.splitlines()
    header_row = None
    for i, ln in enumerate(lines[:20]):
        if "基準日" in ln:
            header_row = i
            break
    if header_row is None:
        raise SystemExit(
            "[エラー] 財務省CSVの中に「基準日」の見出し行が見つかりませんでした。\n"
            f"        先頭5行: {lines[:5]}\n"
            "        ファイル形式が変更された可能性があります。"
        )
    df = pd.read_csv(io.StringIO(text), skiprows=header_row)
    df.columns = [str(c).strip() for c in df.columns]

    datecol = df.columns[0]          # "基準日"
    need = {"2年": "jp2y", "10年": "jp10y"}
    missing = [c for c in need if c not in df.columns]
    if missing:
        raise SystemExit(
            f"[エラー] 財務省CSVに列 {missing} が見つかりませんでした。\n"
            f"        返ってきた列（先頭15個）: {list(df.columns)[:15]}\n"
            f"        ファイル形式が変更された可能性があります。"
        )

    out = pd.DataFrame({"date": df[datecol].map(_wareki_to_date)})
    for src, dst in need.items():
        # 未発行・休場は "-" などで入っているので数値化してNaNに
        out[dst] = pd.to_numeric(df[src], errors="coerce")

    out = out.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    print(f"         → {len(out)}行 取得（{out['date'].min():%Y-%m-%d} 〜 {out['date'].max():%Y-%m-%d}）")
    return out


# ==============================================================================
# 結合
# ==============================================================================

def build(start: str, end: str, fred_file=None, jgb_file=None,
          transport=None) -> pd.DataFrame:
    fred = fetch_fred(start, end, fred_file, transport)
    jgb = fetch_jgb(jgb_file, transport)

    df = pd.merge(fred, jgb, on="date", how="outer").sort_values("date")
    df = df[(df["date"] >= pd.Timestamp(start)) & (df["date"] <= pd.Timestamp(end))]

    # 日米で休場日が違うので、片側だけ欠ける日は前日値で埋める
    cols = ["usdjpy", "us2y", "jp2y", "us10y", "jp10y", "vix"]
    before = df[cols].isna().sum().sum()
    df[cols] = df[cols].ffill()
    after = df[cols].isna().sum().sum()

    # モデルが必須とする4列がそろっている行だけ残す
    df = df.dropna(subset=["usdjpy", "us2y", "jp2y"]).reset_index(drop=True)
    df = df[["date", "usdjpy", "us2y", "jp2y", "us10y", "jp10y", "vix"]]
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")

    print(f"  [結合] 欠損セルを前日値で補完: {before} → {after}")
    return df


def main():
    today = date.today()
    ap = argparse.ArgumentParser(description="ドル円モデル用データの自動取得")
    ap.add_argument("--start", default=str(today - timedelta(days=365 * 4 + 30)),
                    help="取得開始日 YYYY-MM-DD（既定: 4年前）")
    ap.add_argument("--end", default=str(today), help="取得終了日 YYYY-MM-DD（既定: 今日）")
    ap.add_argument("--out", default="data.csv", help="出力CSV（既定: data.csv）")
    ap.add_argument("--fred-file", help="FREDのCSVを手動ダウンロード済みなら、そのパス")
    ap.add_argument("--jgb-file", help="財務省のCSVを手動ダウンロード済みなら、そのパス")
    ap.add_argument("--transport", choices=["requests", "urllib", "curl"], default=None,
                    help="通信方法を1つに固定する（既定: requests→urllib→curl の順に自動）")
    ap.add_argument("--probe", action="store_true",
                    help="2つのサイトへの疎通だけを確認する（データは保存しない）")
    args = ap.parse_args()

    if args.probe:
        print("\n疎通確認: どの通信方法でどのサイトに届くかを調べます\n")
        targets = [
            ("FRED テキスト版", "https://fred.stlouisfed.org/data/DGS2.txt"),
            ("FRED CSV版", f"{FRED_URL}?id=DGS2&cosd=2026-08-01"),
            ("FRED CSV版(4系列)", f"{FRED_URL}?id=DEXJPUS,DGS2,DGS10,VIXCLS&cosd=2026-08-01"),
            ("財務省", "https://www.mof.go.jp/jgbs/reference/interest_rate/jgbcm.csv"),
        ]
        for site, url in targets:
            print(f"  [{site}]")
            for name, fn in TRANSPORTS.items():
                try:
                    data = fn(url, 45)
                    head = data[:60].decode("utf-8", "replace").replace("\n", " ")
                    print(f"    {name:9s} OK    {len(data):>8,} bytes   {head[:44]}")
                except ImportError:
                    print(f"    {name:9s} 未インストール")
                except Exception as e:
                    print(f"    {name:9s} NG    {type(e).__name__}: {str(e)[:90]}")
            print()
        print("  『FRED テキスト版』と『財務省』が1つでもOKなら、fetch_data.py は動きます。")
        print("  特定の方法だけ通る場合は  --transport curl  のように固定してください。")
        print("  全部NGなら、ネットワーク側（プロキシ・セキュリティソフト）の問題です。\n")
        return

    print(f"\nデータを取得します（{args.start} 〜 {args.end}）\n")
    df = build(args.start, args.end, args.fred_file, args.jgb_file, args.transport)

    if len(df) == 0:
        raise SystemExit("[エラー] 結合後のデータが0行でした。期間指定を見直してください。")

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False, encoding="utf-8")

    last = df.iloc[-1]
    print(f"\n[完了] {args.out} に {len(df)}行 保存しました。")
    print(f"       期間: {df['date'].iloc[0]} 〜 {df['date'].iloc[-1]}")
    print(f"       最新: ドル円 {last['usdjpy']}  "
          f"米2年 {last['us2y']}%  日2年 {last['jp2y']}%  "
          f"金利差 {float(last['us2y']) - float(last['jp2y']):.2f}pt")
    print(f"\n  次のステップ:")
    print(f"    python3 usdjpy_model.py --csv {args.out}")
    print(f"    （Excelで使う場合は {args.out} を開き、A2セル以降をコピーして")
    print(f"      ワークブックの「データ」シートのA2に貼り付けてください）\n")


if __name__ == "__main__":
    main()
