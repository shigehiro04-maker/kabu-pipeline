"""共通設定・ユーティリティ"""
from pathlib import Path
import datetime as dt

BASE_DIR    = Path(__file__).resolve().parent
DATA_DIR    = BASE_DIR / "data"
PRICES_DIR  = DATA_DIR / "prices"
DAILY_DIR   = DATA_DIR / "daily"
LOG_DIR     = BASE_DIR / "logs"
TICKERS_CSV = DATA_DIR / "tickers.csv"
LOCK_FILE   = DATA_DIR / ".lock"
INCOMPLETE  = DATA_DIR / "incomplete.txt"   # 履歴が不完全な銘柄コード

for _d in (DATA_DIR, PRICES_DIR, DAILY_DIR, LOG_DIR):
    _d.mkdir(parents=True, exist_ok=True)

ENCODING = "utf-8"          # CSVの文字コード
YEARS    = 10               # ヒストリカル取得年数
BATCH    = 40               # yfinance 1回あたりの銘柄数
SLEEP    = 1.5              # バッチ間の待機秒数（レート制限対策）
RETRY    = 3                # バッチ失敗時のリトライ回数

# 出力するCSVの列（調整前OHLC + 調整後終値 + 出来高）
COLUMNS  = ["Date", "Open", "High", "Low", "Close", "AdjClose", "Volume"]

_lock_handle = None


def log(msg: str) -> None:
    ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def acquire_lock() -> bool:
    """二重実行を防ぐ。取得できたら True。"""
    global _lock_handle
    import fcntl
    f = LOCK_FILE.open("w")
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return False
    _lock_handle = f          # プロセス終了まで保持
    return True


def load_tickers() -> "list[dict]":
    """tickers.csv を読み込んで [{code, name, market, ticker}, ...] を返す"""
    import csv
    if not TICKERS_CSV.exists():
        raise SystemExit(
            f"銘柄リストがありません: {TICKERS_CSV}\n"
            f"先に `./.venv/bin/python fetch_universe.py` を実行してください。"
        )
    with TICKERS_CSV.open(encoding=ENCODING, newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise SystemExit("銘柄リストが空です。fetch_universe.py を再実行してください。")
    return rows


def price_path(code: str) -> Path:
    return PRICES_DIR / f"{code}.csv"


def load_incomplete() -> set:
    if not INCOMPLETE.exists():
        return set()
    return {l.strip() for l in INCOMPLETE.read_text(encoding=ENCODING).splitlines() if l.strip()}


def save_incomplete(codes) -> None:
    codes = sorted(set(codes))
    if codes:
        INCOMPLETE.write_text("\n".join(codes) + "\n", encoding=ENCODING)
    elif INCOMPLETE.exists():
        INCOMPLETE.unlink()


def mark_incomplete(code: str) -> None:
    s = load_incomplete()
    s.add(code)
    save_incomplete(s)
