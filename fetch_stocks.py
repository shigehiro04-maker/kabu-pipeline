#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
東証（プライム・スタンダード・グロース）全銘柄の日足データ
（始値・高値・安値・終値・出来高）を取得して CSV 保存する。

対象は普通株のみ。優先株・社債型種類株（5桁コード）と、
ETF・REIT・出資証券など株式3市場以外の銘柄は除外する。
2024年以降に採番された英数字コード（例: 130A）も対象に含む。

使い方:
    python3 fetch_stocks.py --init          # 過去10年分を一括取得（初回のみ）
    python3 fetch_stocks.py                 # 日次更新（当日分を追記＋その日の一覧CSVを保存）
    python3 fetch_stocks.py --init --skip-existing   # 未取得の銘柄だけ追加取得
    python3 fetch_stocks.py --markets プライム       # 市場を絞る（カンマ区切りで複数可）
    python3 fetch_stocks.py --raw           # 分割・配当調整をしない実際の株価で取得
    python3 fetch_stocks.py --years 5       # 取得年数を変更（--init と併用）

出力:
    data/prices/<銘柄コード>.csv   … 銘柄ごとの時系列（date,open,high,low,close,volume）
    data/daily/<YYYY-MM-DD>.csv    … その日の全銘柄スナップショット
                                     （code,name,market,date,open,high,low,close,volume）
    tickers/tse_tickers.csv        … 対象銘柄の一覧（code,name,market）
    logs/fetch_<YYYY-MM-DD>.log    … 実行ログ
"""

import argparse
import csv
import fcntl
import io
import logging
import os
import socket
import sys
import time
from collections import Counter
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PRICES_DIR = os.path.join(BASE_DIR, "data", "prices")
DAILY_DIR = os.path.join(BASE_DIR, "data", "daily")
TICKERS_DIR = os.path.join(BASE_DIR, "tickers")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
TICKERS_CSV = os.path.join(TICKERS_DIR, "tse_tickers.csv")

# JPX の上場銘柄一覧のURLは update_tickers.py が一覧ページから毎回探す（2026年9月に .xlsx へ変更された）

# 対象とする市場区分（JPX一覧の「市場・商品区分」の先頭一致で判定）
MARKETS = ["プライム", "スタンダード", "グロース"]

LOCK_FILE = os.path.join(LOGS_DIR, "fetch.lock")

BATCH_SIZE = 100          # yfinance に一度に渡す銘柄数
SLEEP_BETWEEN_BATCH = 1.5  # バッチ間の待機秒数（レート制限対策）
CSV_HEADER = ["date", "open", "high", "low", "close", "volume"]

CLOSE_HOUR = 16           # 大引け15:30 ＋ 余裕。この時刻以降なら当日分が確定とみなす


# --------------------------------------------------------------------------
# 準備
# --------------------------------------------------------------------------
def setup_dirs():
    for d in (PRICES_DIR, DAILY_DIR, TICKERS_DIR, LOGS_DIR):
        os.makedirs(d, exist_ok=True)


def setup_logging():
    logfile = os.path.join(LOGS_DIR, f"fetch_{datetime.now():%Y-%m-%d}.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(logfile, encoding="utf-8"),
                  logging.StreamHandler(sys.stdout)],
    )
    return logfile


# --------------------------------------------------------------------------
# 営業日・キャッチアップ判定（PC起動時の自動実行で使う）
# --------------------------------------------------------------------------
def is_trading_day(d):
    """東証の営業日か判定する（土日・祝日・年末年始を除く）。"""
    if d.weekday() >= 5:
        return False
    # 年末年始（12/31〜1/3）は取引所休業
    if (d.month == 12 and d.day == 31) or (d.month == 1 and d.day <= 3):
        return False
    try:
        import jpholiday
        if jpholiday.is_holiday(d):
            return False
    except ImportError:
        pass       # 未インストールなら土日と年末年始のみで判定
    return True


def last_expected_session(now=None):
    """今の時点で「データが揃っているはずの最終営業日」を返す。"""
    now = now or datetime.now()
    d = now.date()
    if now.hour < CLOSE_HOUR:
        d -= timedelta(days=1)      # 大引け前なら前営業日まで
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d


def _last_date_in_csv(path):
    """CSVの最終行の日付を返す（ファイル末尾だけ読む）。"""
    try:
        with open(path, "rb") as f:
            try:
                f.seek(-4096, os.SEEK_END)
            except OSError:
                f.seek(0)
            lines = f.read().decode("utf-8", "ignore").strip().split("\n")
        for ln in reversed(lines):
            d = ln.split(",")[0]
            if len(d) == 10 and d[4] == "-":
                return d
    except Exception:
        pass
    return None


def latest_data_date(sample=30):
    """保存済みCSVのうち最も新しい日付を返す（先頭・末尾から標本抽出）。"""
    if not os.path.isdir(PRICES_DIR):
        return None
    files = sorted(f for f in os.listdir(PRICES_DIR) if f.endswith(".csv"))
    if not files:
        return None
    picked = files[:sample] + files[-sample:]
    dates = [d for d in (_last_date_in_csv(os.path.join(PRICES_DIR, f))
                         for f in picked) if d]
    return max(dates) if dates else None


# 最新日の株価がこの割合未満の銘柄にしか無ければ「取りこぼし」とみなして取り直す
MIN_COVERAGE = 0.9
RETRY_WAIT_SEC = 60
# 当日の株価を確定値として保存してよい時刻（15:45 を分で表したもの）
MARKET_SETTLED_MIN = 15 * 60 + 45


def daily_coverage(day):
    """data/daily/{day}.csv の銘柄数と、銘柄リストの銘柄数を返す。"""
    n_have = 0
    path = os.path.join(DAILY_DIR, f"{day}.csv")
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig") as f:
            n_have = max(sum(1 for _ in f) - 1, 0)
    n_all = 0
    try:
        with open(TICKERS_CSV, encoding="utf-8-sig") as f:
            n_all = max(sum(1 for _ in f) - 1, 0)
    except Exception:
        pass
    return n_have, n_all


def wait_for_network(timeout=180):
    """起動直後はネットワークが未接続のことがあるので、つながるまで待つ。"""
    deadline = time.time() + timeout
    waited = False
    while time.time() < deadline:
        try:
            socket.create_connection(("query1.finance.yahoo.com", 443),
                                     timeout=5).close()
            if waited:
                logging.info("ネットワーク接続を確認しました")
            return True
        except OSError:
            if not waited:
                logging.info("ネットワーク待機中 ...")
                waited = True
            time.sleep(5)
    return False


def acquire_lock():
    """二重起動を防ぐ（16:30の定期実行とログイン時実行が重なる場合など）。"""
    os.makedirs(LOGS_DIR, exist_ok=True)
    f = open(LOCK_FILE, "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return None
    return f      # プロセス終了まで保持し続ける


# --------------------------------------------------------------------------
# 銘柄リスト
# --------------------------------------------------------------------------
def fetch_tickers(force_refresh=False):
    """対象銘柄のリストを返す。{"code", "name", "market"} の辞書のリスト。

    リストの更新は update_tickers.py が担当する（run_daily.sh が毎日先に実行）。
    ここでは、リストが無いか1日以上古いときだけ update_tickers を呼び、
    失敗しても保存済みリストで続行する。
    """
    if not force_refresh and os.path.exists(TICKERS_CSV):
        age_days = (time.time() - os.path.getmtime(TICKERS_CSV)) / 86400
        if age_days < 1:
            return load_tickers()

    try:
        sys.path.insert(0, BASE_DIR)
        import update_tickers
        logging.info("銘柄リストを更新します（update_tickers.py）")
        saved_argv = sys.argv
        sys.argv = [saved_argv[0]]
        try:
            update_tickers.main()
        finally:
            sys.argv = saved_argv
    except Exception as e:
        logging.warning("銘柄リストの更新に失敗: %s", e)
    if os.path.exists(TICKERS_CSV):
        rows = load_tickers()
        by_mkt = Counter(r["market"] for r in rows)
        logging.info("対象 %d 銘柄 (%s)", len(rows),
                     " ".join(f"{m}:{by_mkt.get(m, 0)}" for m in MARKETS))
        return rows
    raise RuntimeError(f"銘柄リストがありません: {TICKERS_CSV}")


def load_tickers():
    with open(TICKERS_CSV, encoding="utf-8-sig") as f:
        return [{"code": r["code"], "name": r["name"],
                 "market": r.get("market", "")} for r in csv.DictReader(f)]


# --------------------------------------------------------------------------
# 価格取得
# --------------------------------------------------------------------------
def download_batch(codes, start=None, period=None, auto_adjust=True):
    """yfinance でまとめて取得し {code: DataFrame} を返す。"""
    import pandas as pd
    import yfinance as yf

    symbols = [f"{c}.T" for c in codes]
    kwargs = dict(interval="1d", auto_adjust=auto_adjust, group_by="ticker",
                  threads=True, progress=False, actions=False)
    if period:
        kwargs["period"] = period
    else:
        kwargs["start"] = start

    data = yf.download(symbols, **kwargs)

    out = {}
    for code, sym in zip(codes, symbols):
        try:
            if isinstance(data.columns, pd.MultiIndex):
                if sym not in data.columns.get_level_values(0):
                    continue
                sub = data[sym]
            else:
                sub = data
            sub = sub.dropna(subset=["Close"])
            if sub.empty:
                continue
            out[code] = sub
        except Exception:
            continue
    return out


def _num(v, nd=2):
    """NaN は空文字、それ以外は丸めた float にする。"""
    try:
        if v != v:      # NaN
            return ""
        return round(float(v), nd)
    except Exception:
        return ""


def df_to_rows(df):
    rows = []
    for idx, r in df.iterrows():
        try:
            cl = r["Close"]
            if cl != cl:  # NaN の日はスキップ
                continue
            vol = r["Volume"]
            rows.append([
                idx.strftime("%Y-%m-%d"),
                _num(r["Open"]),
                _num(r["High"]),
                _num(r["Low"]),
                round(float(cl), 2),
                "" if vol != vol else int(vol),
            ])
        except Exception:
            continue
    return rows


def write_csv(code, rows):
    path = os.path.join(PRICES_DIR, f"{code}.csv")
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)
        w.writerows(rows)


def upsert_csv(code, rows):
    """既存CSVを更新する。

    新しい日付は追加し、既に入っている日付は取得し直した値で「上書き」する。
    ザラ場中に実行して未確定の値が入った場合や、取引所側で値が訂正された場合に、
    次回の実行で正しい値に直るようにするため。
    戻り値は (新規追加した日数, 値が変わった日数)。
    """
    path = os.path.join(PRICES_DIR, f"{code}.csv")
    existing = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for r in csv.reader(f):
                if r and r[0] != "date":
                    existing[r[0]] = r

    added = changed = 0
    for r in rows:
        old = existing.get(r[0])
        if old is None:
            added += 1
        elif [str(v) for v in old] != [str(v) for v in r]:
            changed += 1
        existing[r[0]] = r

    if added or changed:
        with open(path, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(CSV_HEADER)
            w.writerows(existing[d] for d in sorted(existing))
    return added, changed


# --------------------------------------------------------------------------
# モード
# --------------------------------------------------------------------------
def run_init(tickers, years, auto_adjust, skip_existing=False):
    start = (datetime.now() - timedelta(days=int(365.25 * years) + 5)).strftime("%Y-%m-%d")

    codes = [t["code"] for t in tickers]
    if skip_existing:
        have = {f[:-4] for f in os.listdir(PRICES_DIR) if f.endswith(".csv")}
        before = len(codes)
        codes = [c for c in codes if c not in have]
        logging.info("既存 %d 銘柄をスキップします", before - len(codes))
        if not codes:
            logging.info("追加取得が必要な銘柄はありません")
            return 0, 0

    logging.info("=== 初回取得: %d 銘柄 / %s 以降 / 調整=%s ===",
                 len(codes), start, auto_adjust)
    ok = fail = 0
    for i in range(0, len(codes), BATCH_SIZE):
        batch = codes[i:i + BATCH_SIZE]
        try:
            data = download_batch(batch, start=start, auto_adjust=auto_adjust)
        except Exception as e:
            logging.error("バッチ %d 失敗: %s", i // BATCH_SIZE + 1, e)
            fail += len(batch)
            continue

        for code in batch:
            df = data.get(code)
            if df is None:
                fail += 1
                continue
            rows = df_to_rows(df)
            if rows:
                write_csv(code, rows)
                ok += 1
            else:
                fail += 1

        logging.info("進捗 %d/%d  (成功 %d / 失敗 %d)",
                     min(i + BATCH_SIZE, len(codes)), len(codes), ok, fail)
        time.sleep(SLEEP_BETWEEN_BATCH)

    logging.info("=== 初回取得 完了: 成功 %d / 失敗 %d ===", ok, fail)
    return ok, fail


def check_schema():
    """既存CSVの列構成が現在の仕様と合っているか確認する。"""
    files = [f for f in os.listdir(PRICES_DIR) if f.endswith(".csv")] if os.path.isdir(PRICES_DIR) else []
    if not files:
        return True
    path = os.path.join(PRICES_DIR, files[0])
    with open(path, encoding="utf-8") as f:
        header = next(csv.reader(f), [])
    if header != CSV_HEADER:
        logging.error("既存CSVの列が古い形式です (%s)。", ",".join(header))
        logging.error("列構成が変わったため、一度 --init で取り直してください:")
        logging.error("  ./.venv/bin/python fetch_stocks.py --init --years 10")
        return False
    return True


def run_daily(tickers, auto_adjust, lookback="10d", start=None):
    if not check_schema():
        sys.exit(1)
    logging.info("=== 日次更新: %d 銘柄 / %s ===",
                 len(tickers), f"{start} 以降" if start else f"直近 {lookback}")
    info = {t["code"]: t for t in tickers}
    codes = [t["code"] for t in tickers]

    today = datetime.now().strftime("%Y-%m-%d")
    snapshot = {}      # date -> list of rows
    appended = updated = 0
    fail = 0

    # 大引け（15:30）＋余裕の15:45より前なら、当日の株価は確定していない
    now = datetime.now()
    drop_today = now.hour * 60 + now.minute < MARKET_SETTLED_MIN
    if drop_today:
        logging.info("取引時間中（%s）のため、本日 %s の株価は保存しません", now.strftime("%H:%M"), today)

    def fetch_codes(target, label=""):
        """target の銘柄を取得して保存し、取れなかった銘柄のリストを返す。"""
        nonlocal appended, updated
        failed = []
        for i in range(0, len(target), BATCH_SIZE):
            batch = target[i:i + BATCH_SIZE]
            try:
                if start:
                    data = download_batch(batch, start=start, auto_adjust=auto_adjust)
                else:
                    data = download_batch(batch, period=lookback, auto_adjust=auto_adjust)
            except Exception as e:
                logging.error("バッチ %d 失敗: %s", i // BATCH_SIZE + 1, e)
                failed += batch
                continue

            for code in batch:
                df = data.get(code)
                rows = df_to_rows(df) if df is not None else None
                if rows and drop_today:
                    # 取引時間中は当日の値が途中経過なので保存しない（引け後の実行で確定値を取る）
                    rows = [r for r in rows if r[0] != today]
                if not rows:
                    failed.append(code)
                    continue
                a, c = upsert_csv(code, rows)
                appended += a
                updated += c
                t = info.get(code, {})
                for r in rows:
                    snapshot.setdefault(r[0], []).append(
                        [code, t.get("name", ""), t.get("market", "")] + r)

            logging.info("%s進捗 %d/%d", label, min(i + BATCH_SIZE, len(target)), len(target))
            time.sleep(SLEEP_BETWEEN_BATCH)
        return failed

    failed = fetch_codes(codes)
    # 取れなかった銘柄は、少し待ってから1回だけ取り直す（Yahooの一時的な制限・通信断対策）
    if failed:
        logging.warning("%d 銘柄が取得できませんでした。%d秒待って取り直します",
                        len(failed), RETRY_WAIT_SEC)
        time.sleep(RETRY_WAIT_SEC)
        failed = fetch_codes(failed, label="取り直し ")
    fail = len(failed)
    if fail:
        logging.warning("取り直し後も取得できなかった銘柄: %d（上場廃止などの可能性）", fail)

    # 取得した各営業日のスナップショットを保存する。最新日だけでなく、取り直した過去の日も
    # 書き直す（一部しか取れていなかった日のファイルが欠けたまま残らないように）。
    # 既存ファイルの行と合わせ、同じ銘柄は今回取れた値で上書きするので、取得に一部失敗しても行は減らない。
    if snapshot:
        latest = max(snapshot.keys())
        for day in sorted(snapshot.keys()):
            path = os.path.join(DAILY_DIR, f"{day}.csv")
            merged = {}
            if os.path.exists(path):
                try:
                    with open(path, encoding="utf-8-sig", newline="") as f:
                        r = csv.reader(f)
                        next(r, None)
                        for row in r:
                            if row:
                                merged[row[0]] = row
                except Exception as e:
                    logging.warning("既存の日次ファイルを読めませんでした（作り直します）: %s: %s", path, e)
            before = len(merged)
            for row in snapshot[day]:
                merged[row[0]] = row
            rows = [merged[c] for c in sorted(merged)]
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(["code", "name", "market"] + CSV_HEADER)
                w.writerows(rows)
            if day == latest:
                logging.info("日次ファイルを保存: %s (%d 銘柄)", path, len(rows))
            elif len(rows) != before:
                logging.info("過去の日次ファイルを補充: %s (%d → %d 銘柄)", path, before, len(rows))
        if latest != today:
            logging.info("※本日(%s)は休場または未確定のため、最新営業日 %s のデータです", today, latest)
    else:
        logging.warning("データを取得できませんでした（休場日の可能性）")

    logging.info("=== 日次更新 完了: 新規 %d 行 / 上書き %d 行 / 取得失敗 %d 銘柄 ===",
                 appended, updated, fail)
    return appended, updated, fail


# --------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(description="東証銘柄の株価CSV取得")
    p.add_argument("--init", action="store_true", help="過去N年分を一括取得")
    p.add_argument("--years", type=int, default=10, help="取得年数（--init時、既定10年）")
    p.add_argument("--skip-existing", action="store_true",
                   help="--init時、既にCSVがある銘柄をスキップする")
    p.add_argument("--markets", default=",".join(MARKETS),
                   help="対象市場をカンマ区切りで指定（既定: 全3市場）")
    p.add_argument("--raw", action="store_true",
                   help="分割・配当調整をしない実際の株価で取得")
    p.add_argument("--refresh-tickers", action="store_true", help="銘柄リストを強制再取得")
    p.add_argument("--catchup", action="store_true",
                   help="不足分だけ取得する（自動実行用）。最新なら何もせず終了する")
    args = p.parse_args()

    setup_dirs()
    logfile = setup_logging()

    lock = acquire_lock()
    if lock is None:
        logging.info("別の取得処理が実行中のため終了します")
        return
    logging.info("ログ: %s", logfile)

    start = None
    if args.catchup:
        expected = last_expected_session()
        have = latest_data_date()
        if have and have >= expected.isoformat():
            n_have, n_all = daily_coverage(expected.isoformat())
            if n_all and n_have >= n_all * MIN_COVERAGE:
                logging.info("データは最新です（最終営業日 %s / 保存済み %s / %d/%d 銘柄）。何もしません",
                             expected, have, n_have, n_all)
                return
            logging.warning("最終営業日 %s の株価が %d/%d 銘柄しかありません。取り直します",
                            expected, n_have, n_all)
            have = (expected - timedelta(days=1)).isoformat()
        if not wait_for_network():
            logging.warning("ネットワークに接続できないため中止します")
            return
        if have:
            behind = (expected - datetime.strptime(have, "%Y-%m-%d").date()).days
            logging.info("保存済み %s → 最終営業日 %s（%d日分の遅れ）",
                         have, expected, behind)
            # 取りこぼしを防ぐため、最終保存日の3日前から取り直す
            start = (datetime.strptime(have, "%Y-%m-%d").date()
                     - timedelta(days=3)).isoformat()

    tickers = fetch_tickers(force_refresh=args.refresh_tickers)

    want = [m.strip() for m in args.markets.split(",") if m.strip()]
    unknown = [m for m in want if m not in MARKETS]
    if unknown:
        logging.error("不明な市場区分: %s （指定できるのは %s）",
                      ", ".join(unknown), " / ".join(MARKETS))
        sys.exit(1)
    if set(want) != set(MARKETS):
        tickers = [t for t in tickers if t["market"] in want]
        logging.info("市場を絞り込み: %s → %d 銘柄", ",".join(want), len(tickers))

    if not tickers:
        logging.error("対象銘柄が0件です")
        sys.exit(1)

    auto_adjust = not args.raw

    if args.init:
        run_init(tickers, args.years, auto_adjust, skip_existing=args.skip_existing)
    else:
        run_daily(tickers, auto_adjust, start=start)


if __name__ == "__main__":
    main()
