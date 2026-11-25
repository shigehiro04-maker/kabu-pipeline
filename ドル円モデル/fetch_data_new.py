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
    cmd = [exe, "-sS", "--fail", "--location", "--compressed",
           "--max-time", str(timeout),
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


def http_get(url: str, timeout: int = 60, retries: int = 2,
             transport: str | None = None) -> bytes:
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

def fetch_fred(start: str, end: str, local_file: str | None = None,
               transport: str | None = None) -> pd.DataFrame:
    """FREDから4系列をまとめて取得する。APIキーは不要。"""
    if local_file:
        print(f"  [FRED] ローカルファイルを読み込み: {local_file}")
        raw = Path(local_file).read_bytes()
    else:
        ids = ",".join(FRED_SERIES)
        url = f"{FRED_URL}?id={ids}&cosd={start}&coed={end}"
        print(f"  [FRED] 取得中: {', '.join(FRED_SERIES)}  ({start} 〜 {end})")
        raw = http_get(url, transport=transport)

    df = pd.read_csv(io.StringIO(raw.decode("utf-8", errors="replace")))
    if df.empty:
        raise SystemExit("[エラー] FREDから空のデータが返りました。期間指定を見直してください。")

    # 日付列の名前はFRED側の仕様変更で "DATE" だったり "observation_date" だったりする
    datecol = df.columns[0]
    df = df.rename(columns={datecol: "date"})
    df["date"] = pd.to_datetime(df["date"], errors="coerce")

    missing = [s for s in FRED_SERIES if s not in df.columns]
    if missing:
        raise SystemExit(
            f"[エラー] FREDの応答に系列 {missing} が含まれていませんでした。\n"
            f"        返ってきた列: {list(df.columns)}\n"
            f"        系列IDが変更された可能性があります。"
        )

    df = df.rename(columns=FRED_SERIES)
    for c in FRED_SERIES.values():
        # FREDは休場日を "." で返すので数値化してNaNに落とす
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.dropna(subset=["date"])[["date"] + list(FRED_SERIES.values())]
    print(f"         → {len(df)}行 取得（{df['date'].min():%Y-%m-%d} 〜 {df['date'].max():%Y-%m-%d}）")
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
        targets = [("FRED", f"{FRED_URL}?id=DEXJPUS&cosd=2026-08-25"),
                   ("財務省", "https://www.mof.go.jp/jgbs/reference/interest_rate/jgbcm.csv")]
        for site, url in targets:
            print(f"  [{site}]")
            for name, fn in TRANSPORTS.items():
                try:
                    data = fn(url, 30)
                    head = data[:60].decode("utf-8", "replace").replace("\n", " ")
                    print(f"    {name:9s} OK    {len(data):>8,} bytes   {head[:44]}")
                except ImportError:
                    print(f"    {name:9s} 未インストール")
                except Exception as e:
                    print(f"    {name:9s} NG    {type(e).__name__}: {str(e)[:90]}")
            print()
        print("  1つでも OK があれば fetch_data.py は動きます。")
        print("  全部 NG なら、ネットワーク側（プロキシ・ファイアウォール）の問題です。\n")
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
