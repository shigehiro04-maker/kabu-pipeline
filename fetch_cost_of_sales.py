#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""東証全銘柄 通期売上原価（EDINET DB REST API）

無料プラン（100リクエスト/日）の枠を必ず守りながら、上場企業の通期
売上原価を少しずつ集めて CSV に蓄積します。

  ・1日の上限（既定90件）に達したら、その日はそこで終了
  ・翌日の実行で、止まったところの続きから再開
  ・初回はプライム→スタンダード→グロースの順に全銘柄を埋める（1社1リクエスト）
  ・埋め終わったあとは、本決算（有価証券報告書）が出る頃合いの銘柄だけ取り直す

出力
  fundamentals/cost_of_sales_by_year.csv   1行 = 銘柄 × 決算期（直近4期）
  fundamentals/cost_of_sales_latest.csv    1行 = 銘柄（直近4期を横並び、集計・screening用）
  fundamentals/cost_of_sales_failed.csv    取得できなかった銘柄
  fundamentals/edinet_companies.csv        証券コード→EDINETコード対応表（月1回だけ更新）
  fundamentals/edinet_state.json           進捗・当日の使用リクエスト数・次回取得予定日
  fundamentals/raw_edinet/<コード>.json    直近レスポンスの控え（--probe / --keep-raw 時）
  fundamentals/edinet_metrics_by_year.csv  同じ応答から保存するスクリーニング用の生項目（edinet_metrics.py）
  fundamentals/edinet_metrics_latest.csv   その指標（経常利益変化率・当座比率・回転率・CCC・ROIC・連続増配・DOE など）

  スクリーニング用の項目は、売上原価と同じ1回の応答から保存するので呼び出し回数は増えない。
  保存を始める前に取得済みだった銘柄は、再取得・初回収集で枠が余った日にだけ順に取り直す。

使い方
  ./.venv/bin/python fetch_cost_of_sales.py              # 当日の枠まで取得
  ./.venv/bin/python fetch_cost_of_sales.py --status     # 通信せず進捗だけ表示
  ./.venv/bin/python fetch_cost_of_sales.py --probe 7203 # 1社だけ取得して生レスポンスを確認
  ./.venv/bin/python fetch_cost_of_sales.py --budget 30  # その回だけ上限を変える

APIキー
  環境変数 EDINETDB_API_KEY、または ~/株分析/.edinetdb_key（1行だけ書く）
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import socket
import sys
import time
import datetime as dt
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import edinet_metrics as em

BASE = Path(__file__).resolve().parent
TICKERS_CSV = BASE / "tickers" / "tse_tickers.csv"
SECTORS_CSV = BASE / "tickers" / "sectors.csv"
OUT_DIR = BASE / "fundamentals"
RAW_DIR = OUT_DIR / "raw_edinet"
LOG_DIR = BASE / "logs"

BY_YEAR_CSV = OUT_DIR / "cost_of_sales_by_year.csv"
LATEST_CSV = OUT_DIR / "cost_of_sales_latest.csv"
FAILED_CSV = OUT_DIR / "cost_of_sales_failed.csv"
MASTER_CSV = OUT_DIR / "edinet_companies.csv"
STATE_JSON = OUT_DIR / "edinet_state.json"

API_BASE = "https://edinetdb.jp/v1"
KEY_FILE = BASE / ".edinetdb_key"

# 無料プランは 100リクエスト/日。既定では 90 までに抑え、
# 残りはチャット（MCP）からの利用ぶんとして空けておく。
DEFAULT_BUDGET = 90
YEARS_KEEP = 4          # CSV に残す決算期の数
YEARS_FETCH = 6         # APIから取る年数（余裕をもって）
SLEEP_SEC = 0.5         # APIへの思いやり
MASTER_MAX_AGE_DAYS = 30
MAX_FAILS = 3           # これ以上失敗したら、その銘柄はしばらく諦める
MISSING_RECHECK_DAYS = 120   # 直近期の売上原価が空だった銘柄を見に行く間隔
DUE_SHARE_WHILE_BACKFILL = 0.3   # 初回収集中に再取得へ回す枠の割合

MARKET_ORDER = {"プライム": 0, "スタンダード": 1, "グロース": 2}


# ------------------------------------------------------------------ 小道具

def today() -> dt.date:
    return dt.date.today()


def log(msg: str) -> None:
    line = f"[{dt.datetime.now():%F %T}] {msg}"
    print(line, flush=True)


def norm_code(code: str) -> str:
    """証券コードを4桁に揃える。EDINET側は末尾0付きの5桁（72030）が多い。"""
    c = (code or "").strip().upper()
    if len(c) == 5 and c.endswith("0"):
        c = c[:4]
    return c


def pick(row: dict, *names, default=None):
    """キー名の揺れ（snake_case / camelCase）を吸収して値を取り出す。"""
    for n in names:
        if n in row and row[n] not in (None, ""):
            return row[n]
    lowered = {k.lower().replace("_", ""): v for k, v in row.items()}
    for n in names:
        k = n.lower().replace("_", "")
        if k in lowered and lowered[k] not in (None, ""):
            return lowered[k]
    return default


def as_num(v):
    if v in (None, "", "-"):
        return None
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def fmt_num(v):
    if v is None:
        return ""
    if abs(v - round(v)) < 1e-6:
        return str(int(round(v)))
    return f"{v:.2f}"


def find_rows(obj, must_have) -> list:
    """レスポンスのどこかにある「辞書のリスト」を探す。
    must_have のいずれかのキー（大文字小文字・アンダースコア無視）を持つものを採用。"""
    want = {m.lower().replace("_", "") for m in must_have}

    def has(d):
        keys = {k.lower().replace("_", "") for k in d.keys()}
        return bool(keys & want)

    stack = [obj]
    while stack:
        cur = stack.pop(0)
        if isinstance(cur, list):
            dicts = [x for x in cur if isinstance(x, dict)]
            if dicts and any(has(d) for d in dicts):
                return dicts
            stack.extend(cur)
        elif isinstance(cur, dict):
            stack.extend(cur.values())
    return []


# ------------------------------------------------------------------ 通信

class QuotaExhausted(Exception):
    """その日のAPI枠を使い切った（サーバ側 429 / 上限応答）。"""


class NetworkDown(Exception):
    """ネットに繋がっていない（スリープ復帰直後など）。その回は中断して次の起動で再開。"""


def network_ok() -> bool:
    """APIを叩かずに、名前解決だけで回線の有無を確かめる（枠は消費しない）。"""
    try:
        socket.getaddrinfo("edinetdb.jp", 443)
        return True
    except OSError:
        return False


class Fetcher:
    def __init__(self, state: dict, budget: int, dry: bool = False):
        self.state = state
        self.budget = budget
        self.dry = dry
        self.api_key = self._load_key()

    @staticmethod
    def _load_key() -> str | None:
        k = os.environ.get("EDINETDB_API_KEY", "").strip()
        if k:
            return k
        if KEY_FILE.exists():
            k = KEY_FILE.read_text(encoding="utf-8").strip()
            if k:
                return k
        return None

    # ---- その日の使用量 ----
    def quota(self) -> dict:
        q = self.state.setdefault("quota", {})
        d = today().isoformat()
        if q.get("date") != d:
            q.clear()
            q.update({"date": d, "used": 0, "exhausted": False})
        return q

    def remaining(self) -> int:
        q = self.quota()
        if q.get("exhausted"):
            return 0
        return max(0, self.budget - int(q.get("used", 0)))

    def get(self, path: str, params: dict | None = None):
        """APIを1回叩く。枠を使い切っていたら QuotaExhausted。"""
        if self.remaining() <= 0:
            raise QuotaExhausted("本日の取得上限に達しました")

        url = API_BASE + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={
            "Accept": "application/json",
            "User-Agent": "kabu-bunseki/1.0 (personal research)",
        })
        if self.api_key:
            req.add_header("X-API-Key", self.api_key)

        q = self.quota()
        q["used"] = int(q.get("used", 0)) + 1     # 投げた時点で1回ぶん計上する
        save_state(self.state)

        try:
            with urllib.request.urlopen(req, timeout=60) as res:
                body = res.read().decode("utf-8", "replace")
            return json.loads(body)
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")[:500]
            except Exception:
                pass
            if e.code in (429,) or "rate" in body.lower() or "limit" in body.lower():
                q["exhausted"] = True
                save_state(self.state)
                raise QuotaExhausted(f"HTTP {e.code}: {body[:200]}")
            raise
        except urllib.error.URLError as e:
            # DNS失敗・接続拒否など「サーバに届いていない」失敗は枠を使っていないので戻す。
            # 接続タイムアウトは届いた可能性があるので、安全側に倒して計上したままにする。
            if not isinstance(e.reason, (TimeoutError, socket.timeout)):
                q["used"] = max(0, int(q.get("used", 0)) - 1)
                save_state(self.state)
            raise NetworkDown(str(e.reason))
        except (TimeoutError, socket.timeout) as e:
            raise NetworkDown(f"応答タイムアウト {e}")
        finally:
            time.sleep(SLEEP_SEC)


# ------------------------------------------------------------------ 状態

def load_state() -> dict:
    if STATE_JSON.exists():
        try:
            return json.loads(STATE_JSON.read_text(encoding="utf-8"))
        except Exception:
            log("state ファイルが壊れていたので作り直します")
    return {"quota": {}, "companies": {}, "master_updated": None}


def save_state(state: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_JSON.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, STATE_JSON)


# ------------------------------------------------------------------ 銘柄一覧

def load_universe() -> dict:
    """tickers/tse_tickers.csv（東証の全銘柄）＋ sectors.csv の業種。"""
    uni = {}
    with open(TICKERS_CSV, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            code = norm_code(r.get("code", ""))
            if not code:
                continue
            uni[code] = {
                "コード": code,
                "銘柄名": (r.get("name") or "").strip(),
                "市場": (r.get("market") or "").strip(),
                "業種": "",
            }
    if SECTORS_CSV.exists():
        with open(SECTORS_CSV, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                code = norm_code(r.get("code", ""))
                if code in uni:
                    uni[code]["業種"] = (r.get("sector33") or "").strip()
    return uni


def load_master() -> dict:
    """証券コード → EDINETコード の対応表（CSVキャッシュ）。"""
    m = {}
    if MASTER_CSV.exists():
        with open(MASTER_CSV, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                code = norm_code(r.get("コード", ""))
                ec = (r.get("EDINETコード") or "").strip()
                if code and ec:
                    m[code] = ec
    return m


def refresh_master(fetcher: Fetcher, state: dict) -> dict:
    """EDINET DB の企業一覧を取得して対応表を作り直す（1〜2リクエスト）。"""
    rows = []
    for page in range(1, 4):                     # 5000件/ページ。通常1ページで足りる
        data = fetcher.get("/companies", {"per_page": 5000, "page": page})
        got = find_rows(data, ["edinet_code", "edinetCode", "code"])
        rows.extend(got)
        if len(got) < 5000:
            break

    master = {}
    for r in rows:
        ec = pick(r, "edinet_code", "edinetCode", "code")
        sec = pick(r, "sec_code", "secCode", "securities_code", "securitiesCode", "ticker")
        if not ec or not sec:
            continue
        ec = str(ec).strip()
        if not ec.upper().startswith("E"):
            continue
        master[norm_code(str(sec))] = ec

    if not master:
        log("警告: 企業一覧から証券コードを取り出せませんでした。前回の対応表を使います")
        return load_master()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = MASTER_CSV.with_suffix(".csv.tmp")
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["コード", "EDINETコード"])
        for code in sorted(master):
            w.writerow([code, master[code]])
    os.replace(tmp, MASTER_CSV)
    state["master_updated"] = today().isoformat()
    save_state(state)
    log(f"対応表を更新しました: {len(master)}社")
    return master


# ------------------------------------------------------------------ 蓄積CSV

FIELDS = ["コード", "銘柄名", "市場", "業種", "EDINETコード", "年度", "会計基準",
          "売上高", "売上原価", "売上総利益", "原価率(%)", "提出日", "取得日"]


def load_store() -> dict:
    """{コード: {年度: 行}} の形で既存CSVを読み込む。"""
    store = {}
    if BY_YEAR_CSV.exists():
        with open(BY_YEAR_CSV, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                code = (r.get("コード") or "").strip()
                fy = (r.get("年度") or "").strip()
                if code and fy:
                    store.setdefault(code, {})[fy] = r
    return store


def save_store(store: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = BY_YEAR_CSV.with_suffix(".csv.tmp")
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for code in sorted(store):
            for fy in sorted(store[code], reverse=True)[:YEARS_KEEP]:
                w.writerow({k: store[code][fy].get(k, "") for k in FIELDS})
    os.replace(tmp, BY_YEAR_CSV)


def save_latest(store: dict) -> None:
    """直近4期を横に並べた集計用CSV。"""
    cols = ["コード", "銘柄名", "市場", "業種", "EDINETコード", "会計基準", "取得日"]
    for i in range(YEARS_KEEP):
        suf = "" if i == 0 else f"({i}期前)"
        cols += [f"年度{suf}", f"売上高{suf}", f"売上原価{suf}", f"原価率(%){suf}"]

    tmp = LATEST_CSV.with_suffix(".csv.tmp")
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for code in sorted(store):
            years = sorted(store[code], reverse=True)[:YEARS_KEEP]
            if not years:
                continue
            head = store[code][years[0]]
            row = {k: head.get(k, "") for k in
                   ["コード", "銘柄名", "市場", "業種", "EDINETコード", "会計基準", "取得日"]}
            for i in range(YEARS_KEEP):
                suf = "" if i == 0 else f"({i}期前)"
                src = store[code][years[i]] if i < len(years) else {}
                row[f"年度{suf}"] = src.get("年度", "")
                row[f"売上高{suf}"] = src.get("売上高", "")
                row[f"売上原価{suf}"] = src.get("売上原価", "")
                row[f"原価率(%){suf}"] = src.get("原価率(%)", "")
            w.writerow(row)
    os.replace(tmp, LATEST_CSV)


def save_failed(state: dict, uni: dict) -> None:
    rows = []
    for ec, info in state.get("companies", {}).items():
        if info.get("fails", 0) >= MAX_FAILS:
            code = info.get("sec", "")
            u = uni.get(code, {})
            rows.append([code, u.get("銘柄名", ""), ec,
                         info.get("last_error", ""), info.get("last_try", "")])
    tmp = FAILED_CSV.with_suffix(".csv.tmp")
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["コード", "銘柄名", "EDINETコード", "理由", "最終試行日"])
        w.writerows(sorted(rows))
    os.replace(tmp, FAILED_CSV)


# ------------------------------------------------------------------ 決算の解釈

def parse_financials(data: dict) -> list[dict]:
    """APIレスポンスから「決算期・売上高・売上原価」の行を取り出す。"""
    rows = find_rows(data, ["cost_of_sales", "costOfSales", "fiscal_year",
                            "fiscalYear", "fiscal_year_end", "fiscalYearEnd"])
    out = []
    for r in rows:
        fy = pick(r, "fiscal_year", "fiscalYear", "year")
        label = str(fy or "").strip()[:10]
        if not label:
            continue
        submit = str(pick(r, "submit_date", "submitDate", "submitDateTime", default="") or "")[:10]
        cost = as_num(pick(r, "cost_of_sales", "costOfSales", "costOfRevenue"))
        rev = as_num(pick(r, "revenue", "net_sales", "netSales", "sales", "operating_revenue"))
        gross = as_num(pick(r, "gross_profit", "grossProfit"))
        if cost is None and rev is not None and gross is not None:
            cost = rev - gross
        if gross is None and rev is not None and cost is not None:
            gross = rev - cost
        std = pick(r, "accounting_standard", "accountingStandard", default="")
        out.append({"年度": label, "会計基準": std, "提出日": submit,
                    "売上高": rev, "売上原価": cost, "売上総利益": gross})
    out.sort(key=lambda x: x["年度"], reverse=True)
    return out


def next_due_from(fy_label: str, submit: str) -> str:
    """次の本決算（有価証券報告書）が出そうな日。
    前回の提出日の約1年後を目安にする（決算期末の3か月後に出るため）。"""
    try:
        d = dt.date.fromisoformat(submit[:10])
        return (d + dt.timedelta(days=355)).isoformat()
    except (ValueError, TypeError):
        pass
    try:                       # 提出日が分からないときは「年度＋1年の6月末」
        return dt.date(int(fy_label[:4]) + 1, 6, 30).isoformat()
    except Exception:
        return (today() + dt.timedelta(days=180)).isoformat()


# ------------------------------------------------------------------ 本体

def build_queue(uni: dict, master: dict, state: dict) -> tuple[list, list, list]:
    """(決算が出た頃の再取得, 未取得の初回収集, スクリーニング項目の補充) の3本の待ち行列を作る。
    補充は、edinet_metrics の保存を始める前に取得済みだった銘柄。枠が余った日にだけ回す。"""
    comps = state.setdefault("companies", {})
    t = today().isoformat()
    due, backfill, refill = [], [], []
    # verify_data.py が書く「Yahoo の数値が疑わしいのに有報が未取得」の銘柄は、初回収集の先頭に回す
    prio_path = OUT_DIR / "verify" / "edinet_priority.txt"
    prio = set(prio_path.read_text(encoding="utf-8").split()) if prio_path.exists() else set()
    for code, u in uni.items():
        ec = master.get(code)
        if not ec:
            continue
        info = comps.get(ec)
        rank = (-1 if code in prio else MARKET_ORDER.get(u["市場"], 9), code)
        if not info or not info.get("last_fy"):
            if info and info.get("fails", 0) >= MAX_FAILS and info.get("retry_after", "") > t:
                continue
            backfill.append((rank, code, ec))
        elif info.get("next_due", "9999") <= t:
            due.append(((info.get("next_due", ""), rank), code, ec))
        elif info.get("ext_v") != em.VERSION:
            refill.append((rank, code, ec))
    due.sort(key=lambda x: x[0])
    backfill.sort(key=lambda x: x[0])
    refill.sort(key=lambda x: x[0])
    return due, backfill, refill


def fetch_one(fetcher: Fetcher, code: str, ec: str, uni: dict,
              store: dict, state: dict, keep_raw: bool, ext_store: dict | None = None) -> str:
    comps = state.setdefault("companies", {})
    info = comps.setdefault(ec, {"sec": code})
    info["sec"] = code
    info["last_try"] = today().isoformat()

    try:
        data = fetcher.get(f"/companies/{ec}/financials",
                           {"period": "annual", "years": YEARS_FETCH})
    except urllib.error.HTTPError as e:
        info["fails"] = info.get("fails", 0) + 1
        info["last_error"] = f"HTTP {e.code}"
        info["retry_after"] = (today() + dt.timedelta(days=30)).isoformat()
        return f"失敗 HTTP {e.code}"
    # NetworkDown は銘柄のせいではないので、ここでは捕まえず呼び出し元で回ごと中断する

    if keep_raw:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        (RAW_DIR / f"{code}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    if ext_store is not None:
        # スクリーニング用の生項目も同じ応答から保存する（追加の呼び出しなし）
        if em.update(ext_store, code, ec, data):
            info["ext_v"] = em.VERSION

    rows = parse_financials(data)
    if not rows:
        info["fails"] = info.get("fails", 0) + 1
        info["last_error"] = "決算データなし"
        info["retry_after"] = (today() + dt.timedelta(days=60)).isoformat()
        info["next_due"] = (today() + dt.timedelta(days=60)).isoformat()
        return "決算データなし"

    u = uni.get(code, {})
    kept = store.setdefault(code, {})
    n_new = 0
    for r in rows[:YEARS_KEEP]:
        rev, cost, gross = r["売上高"], r["売上原価"], r["売上総利益"]
        ratio = round(cost / rev * 100, 2) if (cost is not None and rev) else None
        fy = r["年度"]
        if fy not in kept:
            n_new += 1
        kept[fy] = {
            "コード": code,
            "銘柄名": u.get("銘柄名", ""),
            "市場": u.get("市場", ""),
            "業種": u.get("業種", ""),
            "EDINETコード": ec,
            "年度": fy,
            "会計基準": r["会計基準"] or "",
            "売上高": fmt_num(rev),
            "売上原価": fmt_num(cost),
            "売上総利益": fmt_num(gross),
            "原価率(%)": "" if ratio is None else f"{ratio:.2f}",
            "提出日": r["提出日"],
            "取得日": today().isoformat(),
        }
    # 古い期は捨てて直近4期だけ残す
    for fy in sorted(kept, reverse=True)[YEARS_KEEP:]:
        del kept[fy]

    latest = rows[0]["年度"]
    info["last_fy"] = latest
    info["last_fetch"] = today().isoformat()
    info["fails"] = 0
    info.pop("last_error", None)
    info.pop("retry_after", None)
    info["next_due"] = next_due_from(latest, rows[0]["提出日"])
    # 直近期の売上原価がまだ入っていない銘柄は、DB側の補完を待って少し早めに見に行く
    if rows[0]["売上原価"] is None:
        recheck = (today() + dt.timedelta(days=MISSING_RECHECK_DAYS)).isoformat()
        info["next_due"] = min(info["next_due"], recheck)
        info["cost_missing"] = True
    else:
        info.pop("cost_missing", None)
    n_cost = sum(1 for r in rows[:YEARS_KEEP] if r["売上原価"] is not None)
    return f"FY{latest}まで{len(rows[:YEARS_KEEP])}期（売上原価あり{n_cost}期）新規{n_new}"


def print_status(uni: dict, master: dict, state: dict, budget: int) -> None:
    comps = state.get("companies", {})
    done = sum(1 for v in comps.values() if v.get("last_fy"))
    target = sum(1 for c in uni if c in master)
    q = state.get("quota", {})
    used = q.get("used", 0) if q.get("date") == today().isoformat() else 0
    due, backfill, refill = build_queue(uni, master, state)
    log(f"対象 {target}社 / 取得済み {done}社 / 未取得 {len(backfill)}社 / 本日再取得対象 {len(due)}社"
        f" / スクリーニング項目の補充待ち {len(refill)}社")
    log(f"本日の使用 {used}/{budget} 件"
        + ("（上限到達）" if q.get("exhausted") or used >= budget else ""))
    if backfill:
        days = -(-len(backfill) // max(1, budget))
        log(f"この調子だと初回収集はあと約 {days} 日で終わります")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=int, default=DEFAULT_BUDGET, help="その日に使うリクエスト数の上限")
    ap.add_argument("--status", action="store_true", help="通信せず進捗だけ表示")
    ap.add_argument("--probe", metavar="CODE", help="1社だけ取得して生レスポンスを保存")
    ap.add_argument("--keep-raw", action="store_true", help="生レスポンスも残す")
    ap.add_argument("--refresh-master", action="store_true", help="対応表を取り直す")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    state = load_state()
    # 以前の版は通信エラーを「銘柄の失敗」として数えていたので、その分を帳消しにする
    for info in state.get("companies", {}).values():
        if str(info.get("last_error", "")).startswith("通信エラー"):
            info["fails"] = 0
            info.pop("last_error", None)
            info.pop("retry_after", None)
    fetcher = Fetcher(state, args.budget)
    if not fetcher.api_key:
        log(f"警告: APIキーが見つかりません（{KEY_FILE.name} か EDINETDB_API_KEY）。匿名枠で試します")

    uni = load_universe()
    master = load_master()

    if args.status:
        print_status(uni, master, state, args.budget)
        return 0

    # その日の枠を使い切っているなら、1行だけ残してすぐ終わる。
    # （Mac起動時や1時間ごとの実行で、ログが無駄に長くならないように）
    if not args.probe and fetcher.remaining() <= 0:
        q = fetcher.quota()
        reason = "サーバ側の上限に到達" if q.get("exhausted") else f"{q.get('used', 0)}/{args.budget}件 使用済み"
        log(f"本日の取得は完了しています（{reason}）。続きは明日")
        return 0

    # 回線が無ければ、APIを1回も叩かずに見送る（スリープ復帰直後など）
    if not network_ok():
        log("ネットワークに繋がっていないため今回は見送ります（枠は消費していません）")
        return 0

    # 対応表（月1回だけ取り直す）
    stale = (not master or args.refresh_master
             or not state.get("master_updated")
             or (today() - dt.date.fromisoformat(state["master_updated"])).days >= MASTER_MAX_AGE_DAYS)
    if stale:
        try:
            master = refresh_master(fetcher, state)
        except QuotaExhausted as e:
            log(f"本日はここまで（{e}）")
            return 0
        except NetworkDown as e:
            log(f"通信できないため今回は見送ります（{e}）")
            return 0

    if args.probe:
        code = norm_code(args.probe)
        ec = master.get(code)
        if not ec:
            log(f"{code} のEDINETコードが対応表にありません")
            return 1
        store = load_store()
        ext_store = em.load_store()
        msg = fetch_one(fetcher, code, ec, uni, store, state, keep_raw=True, ext_store=ext_store)
        save_state(state)
        save_store(store)
        save_latest(store)
        em.save_store(ext_store)
        em.save_latest(ext_store, {c: u.get("業種", "") for c, u in uni.items()})
        log(f"{code} {ec}: {msg}")
        log(f"生レスポンス: {RAW_DIR / (code + '.json')}")
        return 0

    due, backfill, refill = build_queue(uni, master, state)
    # 初回収集がまだ終わっていない間は、再取得に使う枠を一部だけに絞って
    # 「いつまでも初回が終わらない」状態にならないようにする。
    due_list = [(c, e) for _, c, e in due]
    if backfill:
        cap = max(1, int(fetcher.remaining() * DUE_SHARE_WHILE_BACKFILL))
        due_list = due_list[:cap]
    # スクリーニング項目の補充は最後尾（再取得・初回収集で枠が余ったときだけ使われる）
    queue = due_list + [(c, e) for _, c, e in backfill] + [(c, e) for _, c, e in refill]
    log(f"待ち行列: 再取得 {len(due)}社（本日 {len(due_list)}社）+ 初回 {len(backfill)}社"
        f" + 項目補充 {len(refill)}社 / 本日の残り枠 {fetcher.remaining()}件")

    if not queue:
        log("取得するものはありません（すべて最新です）")
        return 0

    store = load_store()
    ext_store = em.load_store()
    n = 0
    try:
        for code, ec in queue:
            if fetcher.remaining() <= 0:
                raise QuotaExhausted("本日の上限に達しました")
            msg = fetch_one(fetcher, code, ec, uni, store, state, args.keep_raw, ext_store)
            n += 1
            log(f"  {code} {ec}: {msg}")
            if n % 10 == 0:
                save_state(state)
                save_store(store)
                em.save_store(ext_store)
    except QuotaExhausted as e:
        log(f"本日はここまで（{e}）。続きは明日の実行で自動的に再開します")
    except NetworkDown as e:
        log(f"通信できなくなったため中断（{e}）。届かなかった分は枠に数えず、次の起動時に続きから再開します")
    except KeyboardInterrupt:
        log("中断しました")
    finally:
        save_state(state)
        save_store(store)
        save_latest(store)
        save_failed(state, uni)
        em.save_store(ext_store)
        em.save_latest(ext_store, {c: u.get("業種", "") for c, u in uni.items()})

    log(f"{n}社を取得しました")
    print_status(uni, master, state, args.budget)
    return 0


if __name__ == "__main__":
    sys.exit(main())
