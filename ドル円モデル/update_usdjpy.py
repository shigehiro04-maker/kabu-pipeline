#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
 update_usdjpy.py — ドル円ページのデータを丸ごと自動更新する
================================================================================

run_daily.sh から毎営業日呼ばれます。手で実行することもできます。

    python3 update_usdjpy.py                 # 取得 → 更新 → ページ再生成 → 公開用にコピー
    python3 update_usdjpy.py --no-publish    # ページは作るが data/charts へはコピーしない
    python3 update_usdjpy.py --dry-run       # 通信せず、手元のファイルだけで動きを確認する

--------------------------------------------------------------------------------
 何をどこから取ってくるか
--------------------------------------------------------------------------------
  data.csv          FRED（ドル円・米2年・米10年・VIX）＋ 財務省（日本2年・10年）
                    ※ fetch_data.py の処理をそのまま呼んでいます
  usdjpy_ohlc.csv   Yahoo Finance の1時間足を、UTCの日付で日次に組み直したもの
  policy.json       FRED（EFFR・1年債・2年債）／財務省（1年・2年）／日銀（コールO/N）
  us_macro.csv      FRED（CPI・雇用者数・失業率・平均時給）の**実績だけ**

  ※ us_macro.csv の「市場予想」（_f で終わる列）と policy.json の「会合日程」
    （meetings）は自動では触りません。出どころが無料で機械取得できないためです。
    ここだけは手で更新してください。

--------------------------------------------------------------------------------
 設計方針 — 毎日ほったらかしで回すために
--------------------------------------------------------------------------------
  1. **取得元ごとに独立して失敗する。** どれか1つが落ちても、残りは更新し、
     ページは必ず作り直します。全部落ちたときだけ異常終了します。
  2. **既存データを減らさない。** 書き込む前に行数と最終日を必ず確認し、
     短くなる・古くなるような更新は捨てます（サイトの仕様変更で空データが
     返ってきたときに、積み上げた履歴を壊さないため）。
  3. **書き込みは原子的に。** 一時ファイルに書いてから置き換えます。
     途中で落ちても中途半端なCSVは残りません。直前の版は .bak に残します。
  4. **黙って古くならない。** 取得に失敗した箇所はログに WARN で出し、
     最後にまとめを出します。ページの更新日時を見れば動いているかも分かります。
================================================================================
"""

from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fetch_data as fd          # noqa: E402  （同じフォルダの取得部品を再利用）

JST = timezone(timedelta(hours=9))

# data.csv を取り直す期間。長すぎると毎回重く、短すぎると連休明けに穴が開く。
WINDOW_DAYS = 400

YAHOO_URL = ("https://query1.finance.yahoo.com/v8/finance/chart/JPY=X"
             "?interval=1h&range=2y")
# 財務省の「全期間」ファイルは月に1回しか更新されない。当月ぶんは別ファイルに
# あるので、2つ落として繋ぐ。片方だけだと最大1か月ぶん日本の金利が古くなる。
MOF_CURRENT_URL = "https://www.mof.go.jp/jgbs/reference/interest_rate/jgbcm.csv"
BOJ_INDEX = "https://www.boj.or.jp/statistics/market/short/mutan/index.htm"
BOJ_HOST = "https://www.boj.or.jp"

# 1日ぶんのローソクとして採用する1時間足の最低本数。
# 為替は24時間動くので平日なら20本以上ある。少ない日は
# 「途中までの当日」か「日曜の数本」なので落とす。
MIN_BARS_PER_DAY = 12

# 1リクエストあたりの待ち時間と、やり直しの回数。
# fetch_data.py の既定（90秒×2回×3方法）だと、相手が黙り込んだとき
# 1系列で最大18分待つことになる。毎日回すには長すぎるので短くする。
HTTP_TIMEOUT = 20
HTTP_RETRIES = 1

WARNINGS: list[str] = []


def _load_cffi():
    """
    curl_cffi の get 関数を返す。無ければ None。

    FREDとYahooは素のpythonからの接続を拒否する（FREDは接続を受けてから
    黙って切り、Yahooは429を返す）。ブラウザと同じTLSの振る舞いをする
    curl_cffi だけが通るので、この2つには事実上これが必須。
    """
    try:
        from curl_cffi import requests as c
    except Exception:
        return None

    def get(url: str, timeout: int) -> bytes:
        r = c.get(url, impersonate="chrome", timeout=timeout)
        r.raise_for_status()
        return r.content

    return get


def tighten_fetch_data() -> None:
    """
    fetch_data.py の通信を、この実行のあいだだけ差し替える。

      ・curl_cffi があれば必ず最初に試す
      ・待ち時間を短くする（既定の90秒×2回×3方法では、相手が黙り込むと
        1系列で18分待つことになり、毎日回すには長すぎる）

    fetch_data.py 側の TRANSPORTS に足すだけでは効かない。http_get が
    試す順番を持っているためで、ここでは順番ごと自前で面倒を見る。
    """
    orig = fd.http_get
    cffi_get = _load_cffi()

    def patched(url, timeout=HTTP_TIMEOUT, retries=HTTP_RETRIES,
                transport=None, quiet=True):
        t = min(timeout, HTTP_TIMEOUT)
        if cffi_get is not None and transport is None:
            for i in range(HTTP_RETRIES + 1):
                try:
                    return cffi_get(url, t)
                except Exception:
                    if i < HTTP_RETRIES:
                        time.sleep(1)
            # curl_cffi で駄目だったものは、従来の方法でも一応試す
        return orig(url, timeout=t, retries=min(retries, HTTP_RETRIES),
                    transport=transport, quiet=quiet)

    patched.uses_cffi = cffi_get is not None      # ログ表示用
    fd.http_get = patched

    if cffi_get is None:
        # ここに来ると FRED と Yahoo はほぼ確実に取得できない。
        # 気づかずに「日本の金利だけ新しいページ」が出来るのが最悪なので警告する。
        warn("curl_cffi が使えません。FREDとYahooは素のpythonからの接続を拒否するため、"
             "ドル円・米金利・米CPIは更新できない見込みです。"
             "株分析/.venv の python で実行しているか確認してください"
             "（入っていなければ .venv/bin/pip install curl_cffi）")


def log(msg: str) -> None:
    print(f"[{datetime.now(JST):%F %T}] {msg}", flush=True)


def warn(msg: str) -> None:
    WARNINGS.append(msg)
    log(f"WARN  {msg}")


# ==============================================================================
# 書き込み — 壊さないための共通処理
# ==============================================================================

def write_atomic(path: Path, text: str) -> None:
    """一時ファイルに書いてから置き換える。直前の版は .bak に残す。"""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    if path.exists():
        path.replace(path.with_suffix(path.suffix + ".bak"))
    tmp.replace(path)


def save_frame(path: Path, new: pd.DataFrame, old: pd.DataFrame | None,
               label: str) -> bool:
    """
    行数が減らない・最終日が戻らないことを確かめてから保存する。
    サイト側の仕様変更で空や短いデータが返ってきたときの保険。
    """
    if old is not None and len(old):
        if len(new) < len(old):
            warn(f"{label}: 行数が {len(old)} → {len(new)} と減るため更新を見送りました")
            return False
        if str(new["date"].max()) < str(old["date"].max()):
            warn(f"{label}: 最終日が {old['date'].max()} → {new['date'].max()} と"
                 f"戻るため更新を見送りました")
            return False
    write_atomic(path, new.to_csv(index=False))
    added = len(new) - (len(old) if old is not None else 0)
    log(f"      {label}: {len(new)}行（+{added}）  最終日 {new['date'].max()}")
    return True


def read_csv_or_none(path: Path) -> pd.DataFrame | None:
    try:
        return pd.read_csv(path) if path.exists() else None
    except Exception as e:
        warn(f"{path.name} が読めませんでした: {e}")
        return None


# ==============================================================================
# 1) data.csv — 価格と金利
# ==============================================================================

def update_data_csv(jgb_file: Path | None, ohlc: pd.DataFrame | None = None) -> None:
    """直近 WINDOW_DAYS 日ぶんを取り直し、その範囲だけ差し替える。"""
    today = date.today()
    start = (today - timedelta(days=WINDOW_DAYS)).isoformat()
    end = (today + timedelta(days=1)).isoformat()

    fresh = fd.build(start, end, jgb_file=str(jgb_file) if jgb_file else None)
    if fresh.empty:
        raise RuntimeError("取得できた行が0件でした")

    # --- FREDのドル円の遅れを埋める --------------------------------------
    # DEXJPUS は金利より2〜4営業日遅れて公表される。fetch_data.py は
    # 欠けたぶんを前日値で埋めるので、そのままだと「金利は動いているのに
    # ドル円だけ数日間まったく同じ」という行ができる。乖離の計算が狂うので、
    # 実測が無い日はYahooの終値（同じ日の実際の終値）で置き換える。
    if ohlc is not None and len(ohlc):
        try:
            real = fd._fetch_one_series("DEXJPUS", "usdjpy", start, end, None)
            last_real = real.dropna(subset=["usdjpy"])["date"].max().strftime("%Y-%m-%d")
        except Exception:
            last_real = None
        if last_real:
            close = dict(zip(ohlc["date"], ohlc["close"]))
            gap = fresh["date"] > last_real
            filled = [d for d in fresh.loc[gap, "date"] if d in close]
            if filled:
                fresh.loc[fresh["date"].isin(filled), "usdjpy"] = \
                    [round(close[d], 2) for d in filled]
                log(f"      FREDのドル円は {last_real} まで。"
                    f"{filled[0]}〜{filled[-1]} の{len(filled)}日はYahooの終値で補いました")

    path = HERE / "data.csv"
    old = read_csv_or_none(path)
    if old is None:
        merged = fresh
    else:
        # 取り直した範囲は新しいほうで置き換える。確報化で過去の値が
        # 微修正されることがあるので、単純な追記にはしない。
        cut = fresh["date"].min()
        merged = pd.concat([old[old["date"] < cut], fresh], ignore_index=True)
    merged = merged.drop_duplicates(subset="date", keep="last").sort_values("date")
    save_frame(path, merged.reset_index(drop=True), old, "data.csv")


# ==============================================================================
# 2) usdjpy_ohlc.csv — ローソク足と、いまのレート
# ==============================================================================

def fetch_yahoo() -> tuple[pd.DataFrame, float | None, str | None]:
    """
    Yahoo の1時間足を日次の四本値にまとめる。

    日足APIは終値が始値のコピーになっている日が多く、そのままではローソクに
    使えない。1時間足から組み直すのが唯一まともに動く方法（README参照）。
    """
    raw = fd.http_get(YAHOO_URL, timeout=45, quiet=True)
    j = json.loads(raw.decode("utf-8", errors="replace"))
    res = j["chart"]["result"][0]
    q = res["indicators"]["quote"][0]

    rows: dict[str, dict] = {}
    for i, ts in enumerate(res["timestamp"]):
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if None in (o, h, l, c):
            continue
        d = datetime.fromtimestamp(ts, timezone.utc)
        if d.weekday() >= 5:            # 土日は薄商いなので使わない
            continue
        key = d.strftime("%Y-%m-%d")
        a = rows.setdefault(key, {"open": o, "high": h, "low": l, "close": c, "n": 0})
        a["high"] = max(a["high"], h)
        a["low"] = min(a["low"], l)
        a["close"] = c
        a["n"] += 1

    recs = [{"date": k, "open": round(v["open"], 3), "high": round(v["high"], 3),
             "low": round(v["low"], 3), "close": round(v["close"], 3)}
            for k, v in sorted(rows.items()) if v["n"] >= MIN_BARS_PER_DAY]
    df = pd.DataFrame(recs)

    meta = res.get("meta", {})
    spot = meta.get("regularMarketPrice")
    asof = None
    if meta.get("regularMarketTime"):
        asof = (datetime.fromtimestamp(meta["regularMarketTime"], timezone.utc)
                .astimezone(JST).strftime("%Y-%m-%d %H:%M JST"))
    return df, spot, asof


def update_ohlc() -> tuple[pd.DataFrame, float | None, str | None]:
    df, spot, asof = fetch_yahoo()
    if df.empty:
        raise RuntimeError("Yahooから四本値を組み立てられませんでした")

    # 高値・安値が実体をはみ出している行は捨てる（壊れたデータの混入対策）
    body_hi = df[["open", "close"]].max(axis=1)
    body_lo = df[["open", "close"]].min(axis=1)
    df = df[(df["high"] >= body_hi) & (df["low"] <= body_lo)]

    path = HERE / "usdjpy_ohlc.csv"
    old = read_csv_or_none(path)
    if old is not None:
        # 取得できた期間だけ差し替え、それより前の履歴はそのまま残す
        merged = pd.concat([old[~old["date"].isin(df["date"])], df], ignore_index=True)
    else:
        merged = df
    merged = merged.sort_values("date").reset_index(drop=True)
    save_frame(path, merged, old, "usdjpy_ohlc.csv")
    return merged, spot, asof


# ==============================================================================
# 3) policy.json — 政策金利と市場金利
# ==============================================================================

def fetch_jgb_bytes() -> bytes:
    """
    財務省の国債金利情報を「全期間ファイル＋当月ファイル」で取り、1本に繋ぐ。

    全期間ファイル（jgbcm_all.csv）は月に1度しか差し替えられないため、
    これだけを見ていると当月ぶんの日本の金利がまるごと抜ける。当月ファイル
    （jgbcm.csv）のデータ行を後ろに足して、その穴を埋める。
    どちらもShift-JIS・同じ列並びなので、テキストとして繋げば済む。
    """
    all_raw = fd.http_get(fd.MOF_URL, timeout=60, quiet=True)
    all_text = all_raw.decode("cp932", errors="replace")
    try:
        cur_text = fd.http_get(MOF_CURRENT_URL, timeout=30, quiet=True) \
            .decode("cp932", errors="replace")
    except Exception as e:
        warn(f"財務省の当月ファイルを取得できませんでした（{type(e).__name__}）。"
             f"日本の金利が最大1か月ぶん古いままになります")
        return all_raw

    have = {ln.split(",", 1)[0] for ln in all_text.splitlines()}
    extra = [ln for ln in cur_text.splitlines()
             if re.match(r"^[SHR]\d+\.\d+\.\d+,", ln) and ln.split(",", 1)[0] not in have]
    if not extra:
        return all_raw
    log(f"      財務省: 当月ファイルから {len(extra)}営業日ぶんを追加"
        f"（{extra[0].split(',')[0]} 〜 {extra[-1].split(',')[0]}）")
    return (all_text.rstrip("\r\n") + "\n" + "\n".join(extra) + "\n").encode("cp932",
                                                                            errors="replace")


def fred_last(sid: str) -> tuple[str, float] | None:
    """FREDの1系列から、値が入っている最後の日付と値を取る。"""
    start = (date.today() - timedelta(days=60)).isoformat()
    end = (date.today() + timedelta(days=1)).isoformat()
    df = fd._fetch_one_series(sid, sid, start, end, None)
    df = df.dropna(subset=[sid])
    if df.empty:
        return None
    r = df.iloc[-1]
    return r["date"].strftime("%Y-%m-%d"), float(r[sid])


def jgb_last(raw: bytes) -> tuple[str, dict] | None:
    """財務省CSVから、最新営業日の1年・2年の利回りを取る。"""
    text = raw.decode("cp932", errors="replace")
    lines = text.splitlines()
    header = next((i for i, ln in enumerate(lines[:20]) if "基準日" in ln), None)
    if header is None:
        return None
    df = pd.read_csv(io.StringIO(text), skiprows=header)
    df.columns = [str(c).strip() for c in df.columns]
    df["_d"] = df[df.columns[0]].map(fd._wareki_to_date)
    for c in ("1年", "2年"):
        if c not in df.columns:
            return None
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["_d", "1年", "2年"]).sort_values("_d")
    if df.empty:
        return None
    r = df.iloc[-1]
    return r["_d"].strftime("%Y-%m-%d"), {"y1": float(r["1年"]), "y2": float(r["2年"])}


def _xlsx_cells(raw: bytes) -> tuple[list[str], dict[str, str]]:
    """xlsx（中身はZIP）を開いて、共有文字列とセルの値を取り出す。"""
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        # ファイル名は決め打ちにしない。シート名も共有文字列の場所も、
        # Excelの書き出し方によって変わることがある。
        names = z.namelist()
        sheet = next((n for n in names if re.search(r"worksheets/sheet\d*\.xml$", n)), None)
        if sheet is None:
            raise ValueError(f"シートが見つかりません: {names[:8]}")
        sheet_xml = z.read(sheet).decode("utf-8", errors="replace")
        sst = next((n for n in names if re.search(r"sharedstrings\.xml$", n, re.I)), None)
        shared_xml = z.read(sst).decode("utf-8", errors="replace") if sst else ""
    # 名前空間の接頭辞（x:）が付くことがあるので、どちらでも拾えるようにする
    strings = [re.sub(r"<[^>]+>", "", m.group(1))
               for m in re.finditer(r"<(?:\w+:)?si>([\s\S]*?)</(?:\w+:)?si>", shared_xml)]
    cells: dict[str, str] = {}
    for m in re.finditer(r'<(?:\w+:)?c r="([A-Z]+\d+)"([^>]*)>([\s\S]*?)</(?:\w+:)?c>', sheet_xml):
        vm = re.search(r"<(?:\w+:)?v>([\s\S]*?)</(?:\w+:)?v>", m.group(3))
        if not vm:
            continue
        v = vm.group(1)
        if 't="s"' in m.group(2):
            v = strings[int(v)] if v.isdigit() and int(v) < len(strings) else v
        cells[m.group(1)] = v
    return strings, cells


def boj_call_rate() -> tuple[str, float] | None:
    """
    日銀の「無担保コールO/N物レート（確報）」から、直近営業日の平均を取る。

    FREDにも日本のコールレートはあるが、数か月遅れて更新されることがあり、
    利上げ後にしばらく古い値のままになる。ここだけは日銀から直接取る。
    """
    html_txt = fd.http_get(BOJ_INDEX, timeout=60, quiet=True).decode("utf-8", errors="replace")
    # 確報（md）のリンクを新しい順に拾う。速報（mp）は後で数字が動くので使わない。
    hits = sorted(set(re.findall(r'href="(/statistics/[^"]*?/md/\d{4}/md(\d{8})\.xlsx)"', html_txt)),
                  key=lambda t: t[1], reverse=True)
    if not hits:
        return None
    href, ymd = hits[0]
    raw = fd.http_get(BOJ_HOST + href, timeout=60, quiet=True)
    strings, cells = _xlsx_cells(raw)

    # 「平均 / Average」の行を探し、同じ行の数値セルを読む。
    # 列や行の位置は決め打ちにしない（様式が変わっても拾えるように）。
    for ref, val in cells.items():
        if "平均" in str(val) or "Average" in str(val):
            row = re.sub(r"[A-Z]", "", ref)
            for col in "BCDEF":
                v = cells.get(col + row)
                try:
                    return f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}", float(v)
                except (TypeError, ValueError):
                    continue
    # 「平均」の見出しが読めなかったとき（共有文字列の形式が変わった等）の保険。
    # 平均・最高・最低はこの順に並ぶので、最初に出てくる金利らしい数値が平均。
    for ref in sorted(cells, key=lambda r: (int(re.sub(r"[A-Z]", "", r) or 0), r)):
        try:
            v = float(cells[ref])
        except (TypeError, ValueError):
            continue
        if -1.0 < v < 5.0 and "." in str(cells[ref]):
            return f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}", v
    return None


def update_policy(jgb_raw: bytes | None) -> None:
    path = HERE / "policy.json"
    if not path.exists():
        warn("policy.json が無いので金利の更新は飛ばしました")
        return
    pol = json.loads(path.read_text(encoding="utf-8"))
    changed = []

    # --- 米国 ---------------------------------------------------------------
    for sid, key in (("EFFR", "policy_rate"), ("DGS1", "y1"), ("DGS2", "y2")):
        try:
            got = fred_last(sid)
        except Exception as e:
            warn(f"FRED {sid} を取得できませんでした: {type(e).__name__}")
            continue
        if got is None:
            warn(f"FRED {sid} に有効な値がありませんでした")
            continue
        d, v = got
        pol["us"][key] = round(v, 3)
        pol["us"]["policy_date" if key == "policy_rate" else "market_date"] = d
        changed.append(f"米{key}={v}")

    # FF金利の誘導目標レンジ。FOMCが動くとここが変わるので自動で取る。
    # （EFFRだけ見ていると「実勢は動いたがレンジの表記は古いまま」になる）
    try:
        lo, hi = fred_last("DFEDTARL"), fred_last("DFEDTARU")
        if lo and hi:
            pol["us"]["target_range"] = f"{lo[1]:.2f}〜{hi[1]:.2f}%"
            changed.append(f"米レンジ={pol['us']['target_range']}")
    except Exception as e:
        warn(f"FF金利の誘導目標レンジを取得できませんでした: {type(e).__name__}")

    # それでも実勢がレンジの外なら、取得か公表のどちらかがおかしい
    rng = pol["us"].get("target_range") or ""
    nums = [float(x) for x in re.findall(r"\d+\.\d+", rng)]
    if len(nums) == 2 and not (nums[0] - 0.05 <= pol["us"]["policy_rate"] <= nums[1] + 0.05):
        warn(f"米EFFR {pol['us']['policy_rate']}% が target_range「{rng}」の外に出ています。"
             f"FOMCで変更があったかもしれません（policy.json を手で直してください）")

    # --- 日本 ---------------------------------------------------------------
    if jgb_raw:
        got = jgb_last(jgb_raw)
        if got:
            d, y = got
            pol["jp"].update(y1=y["y1"], y2=y["y2"], market_date=d)
            changed.append(f"日y1={y['y1']} y2={y['y2']}")
        else:
            warn("財務省CSVから1年・2年の利回りを読み取れませんでした")

    try:
        got = boj_call_rate()
    except Exception as e:
        got = None
        warn(f"日銀のコールレートを取得できませんでした: {type(e).__name__}")
    if got:
        d, v = got
        before = pol["jp"].get("policy_rate")
        pol["jp"]["policy_rate"] = round(v, 3)
        pol["jp"]["policy_date"] = d
        changed.append(f"日コールO/N={v}")
        if before is not None and abs(v - before) > 0.15:
            warn(f"日本のコールレートが {before}% → {v}% と大きく動いています。"
                 f"日銀が政策を変更した可能性があります")
    else:
        warn("日銀のコールレートは前回の値のままです")

    # --- 会合日程の鮮度 ------------------------------------------------------
    today = date.today().isoformat()
    if not any(m.get("end", "") >= today for m in pol.get("meetings", [])):
        warn("policy.json の会合日程がすべて過去になりました。次回以降の日程を"
             "手で追記してください（FOMC・日銀とも1年ぶんの予定が公表されています）")

    pol["as_of"] = date.today().isoformat()
    write_atomic(path, json.dumps(pol, ensure_ascii=False, indent=2) + "\n")
    log(f"      policy.json: {', '.join(changed) if changed else '更新なし'}")


# ==============================================================================
# 4) us_macro.csv — 米CPIと雇用統計（実績だけ）
# ==============================================================================

# FREDの系列 → 意味
MACRO_SERIES = {
    "CPIAUCNS": "cpi_ns",       # CPI 総合（非季節調整）  前年比の計算に使う
    "CPILFENS": "core_ns",      # CPI コア（非季節調整）
    "CPIAUCSL": "cpi_sa",       # CPI 総合（季節調整）    前月比の計算に使う
    "CPILFESL": "core_sa",      # CPI コア（季節調整）
    "PAYEMS": "payrolls",       # 非農業部門雇用者数（千人・水準）
    "UNRATE": "unemp",          # 失業率
    "CES0500000003": "ahe",     # 平均時給
}

# 自動で書き換えてよい列。市場予想（_f）やサプライズ（_s）、発表日には触らない。
MACRO_ACTUAL_COLS = ["cpi_yoy", "core_cpi_yoy", "cpi_mom", "core_cpi_mom",
                     "payrolls_chg", "unemp", "ahe_yoy"]


def update_macro() -> None:
    path = HERE / "us_macro.csv"
    old = read_csv_or_none(path)

    start = (date.today() - timedelta(days=365 * 3 + 120)).isoformat()
    end = (date.today() + timedelta(days=1)).isoformat()

    frames, failed = [], []
    for sid, col in MACRO_SERIES.items():
        try:
            frames.append(fd._fetch_one_series(sid, col, start, end, None))
        except Exception as e:
            failed.append(f"{sid}({type(e).__name__})")
    if failed:
        warn(f"FREDの月次系列を取得できませんでした: {', '.join(failed)}")
    if not frames:
        raise RuntimeError("月次系列がひとつも取得できませんでした")

    m = frames[0]
    for f in frames[1:]:
        m = pd.merge(m, f, on="date", how="outer")
    m = m.sort_values("date").reset_index(drop=True)
    for c in MACRO_SERIES.values():
        if c not in m.columns:
            m[c] = pd.NA

    calc = pd.DataFrame({"date": m["date"].dt.strftime("%Y-%m-%d")})
    calc["cpi_yoy"] = (m["cpi_ns"] / m["cpi_ns"].shift(12) - 1) * 100
    calc["core_cpi_yoy"] = (m["core_ns"] / m["core_ns"].shift(12) - 1) * 100
    calc["cpi_mom"] = (m["cpi_sa"] / m["cpi_sa"].shift(1) - 1) * 100
    calc["core_cpi_mom"] = (m["core_sa"] / m["core_sa"].shift(1) - 1) * 100
    calc["payrolls_chg"] = m["payrolls"] - m["payrolls"].shift(1)
    calc["unemp"] = m["unemp"]
    calc["ahe_yoy"] = (m["ahe"] / m["ahe"].shift(12) - 1) * 100
    for c in MACRO_ACTUAL_COLS:
        calc[c] = pd.to_numeric(calc[c], errors="coerce").round(3)

    if old is None:
        merged = calc
    else:
        merged = old.copy()
        merged["date"] = merged["date"].astype(str)
        idx = calc.set_index("date")
        # 実績列だけを上書きする。市場予想・発表日は手で入れたものを守る。
        for c in MACRO_ACTUAL_COLS:
            if c not in merged.columns:
                merged[c] = pd.NA
            merged[c] = merged["date"].map(idx[c]).combine_first(merged[c])
        # まだ無い月（＝新しく発表された月）を足す。
        # いまあるいちばん古い月より前には遡らない。遡ると図の横軸が急に
        # 伸びて、前と違うページに見えてしまうため。
        floor = merged["date"].min()
        add = calc[(~calc["date"].isin(merged["date"])) & (calc["date"] >= floor)]
        add = add[add[MACRO_ACTUAL_COLS].notna().any(axis=1)]
        if len(add):
            merged = pd.concat([merged, add], ignore_index=True)
        merged = merged.sort_values("date").reset_index(drop=True)

    # 実績も予想も発表日も無い行は落とす（計算の都合で出る先頭の空行対策）
    keep = merged[MACRO_ACTUAL_COLS].notna().any(axis=1)
    for c in merged.columns:
        if c.endswith("_f") or c.endswith("_release"):
            keep = keep | merged[c].notna()
    merged = merged[keep].reset_index(drop=True)

    save_frame(path, merged, old, "us_macro.csv")


# ==============================================================================
# 5) ページの再生成
# ==============================================================================

def rebuild_page(spot: float | None, asof: str | None, publish: Path | None) -> None:
    cmd = [sys.executable, str(HERE / "usdjpy_model.py"),
           "--csv", str(HERE / "data.csv"), "--html"]
    if spot:
        cmd += ["--spot", f"{spot:.3f}"]
        if asof:
            cmd += ["--spot-asof", asof]
    if publish:
        cmd += ["--publish", str(publish)]
    log(f"      {' '.join(cmd[1:])}")
    r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-3000:], file=sys.stderr)
        print(r.stderr[-3000:], file=sys.stderr)
        raise RuntimeError(f"usdjpy_model.py が異常終了しました（終了コード {r.returncode}）")
    for ln in r.stdout.splitlines():
        if "警告" in ln or "公開" in ln or "Webページ" in ln:
            log(f"      {ln.strip()}")


# ==============================================================================

def main() -> int:
    ap = argparse.ArgumentParser(description="ドル円ページのデータを自動更新する")
    ap.add_argument("--no-publish", action="store_true",
                    help="data/charts へのコピーをしない（手元で確認したいとき）")
    ap.add_argument("--dry-run", action="store_true",
                    help="通信せず、手元のファイルだけでページを作り直す")
    ap.add_argument("--publish-to", default=None,
                    help="公開先のHTMLのパス（既定は ../data/charts/usdjpy.html）")
    args = ap.parse_args()

    publish = None
    if not args.no_publish:
        publish = Path(args.publish_to) if args.publish_to \
            else HERE.parent / "data" / "charts" / "usdjpy.html"
        if not publish.parent.exists():
            warn(f"公開先 {publish.parent} が無いので、コピーは飛ばします")
            publish = None

    tighten_fetch_data()
    log("ドル円ページの更新を開始します"
        + ("（curl_cffi を最優先で使います）" if getattr(fd.http_get, "uses_cffi", False)
           else "（curl_cffi なし）"))
    ok, spot, asof = 0, None, None

    if args.dry_run:
        log("  --dry-run: 通信はしません")
    else:
        # 財務省のCSVは data.csv と policy.json の両方で使うので、1回だけ落とす
        jgb_raw, jgb_file = None, None
        try:
            jgb_raw = fetch_jgb_bytes()
            # 一時ファイルはシステムのtempへ。利用者のフォルダに残さない。
            jgb_file = Path(tempfile.gettempdir()) / "usdjpy_jgb_cache.csv"
            jgb_file.write_bytes(jgb_raw)
        except Exception as e:
            warn(f"財務省の国債金利情報を取得できませんでした: {type(e).__name__}: {e}")

        # data.csv のドル円の穴埋めに四本値を使うので、Yahooを先に取る
        log("  1/4 ローソク足と実勢レート（usdjpy_ohlc.csv）")
        ohlc = None
        try:
            ohlc, spot, asof = update_ohlc()
            ok += 1
        except Exception as e:
            warn(f"usdjpy_ohlc.csv の更新に失敗: {type(e).__name__}: {str(e)[:200]}")

        log("  2/4 価格と金利（data.csv）")
        try:
            update_data_csv(jgb_file, ohlc)
            ok += 1
        except Exception as e:
            warn(f"data.csv の更新に失敗: {type(e).__name__}: {str(e)[:200]}")

        log("  3/4 政策金利と市場金利（policy.json）")
        try:
            update_policy(jgb_raw)
            ok += 1
        except Exception as e:
            warn(f"policy.json の更新に失敗: {type(e).__name__}: {str(e)[:200]}")

        log("  4/4 米CPI・雇用統計の実績（us_macro.csv）")
        try:
            update_macro()
            ok += 1
        except Exception as e:
            warn(f"us_macro.csv の更新に失敗: {type(e).__name__}: {str(e)[:200]}")

        if jgb_file and jgb_file.exists():
            try:
                jgb_file.unlink()
            except OSError:
                pass          # 消せなくても実害はない

        if ok == 0:
            log("すべての取得に失敗しました。ネットワークかサイト側の問題の可能性があります。")
            return 1

    log("  ページを作り直します")
    try:
        rebuild_page(spot, asof, publish)
    except Exception as e:
        warn(f"ページの再生成に失敗: {type(e).__name__}: {str(e)[:300]}")
        return 1

    if WARNINGS:
        log(f"完了（気になる点 {len(WARNINGS)}件）")
        for w in WARNINGS:
            log(f"  - {w}")
    else:
        log("完了（すべて正常）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
