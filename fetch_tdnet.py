#!/usr/bin/env python3
"""TDnet（適時開示情報閲覧サービス）から決算短信の数字を取り込む。無料・登録不要。

  - 開示一覧（https://www.release.tdnet.info/inbs/I_list_NNN_YYYYMMDD.html）を日ごとに読み、
    fundamentals/tdnet/list/<日付>.json に保存（全開示の表題・時刻・リンク）。
  - 決算短信と業績予想の修正のうち XBRL があるものは zip を取り、要約（Summary の iXBRL）だけを
    fundamentals/tdnet/summary/<日付>/<zip名>.htm.gz に保存（ほかは捨てる）。
  - 保存した要約をすべて読み直して、次の2つを作る（通信なし）。
      fundamentals/kessan_tanshin.csv   1行 = 1開示（決算短信・予想修正）
      fundamentals/kessan_latest.csv    1行 = 1銘柄（最新の決算短信。予想は予想修正があればそれで上書き）

TDnet で見られるのは開示日を含む31日分。毎日動かして手元にためていく（消さない・公開しない）。

使い方:
  python fetch_tdnet.py                 # 直近31日のうち、まだ取っていない日・今日を取る → CSV を作る
  python fetch_tdnet.py --days 3        # 直近3日だけ
  python fetch_tdnet.py --date 2026-11-13
  python fetch_tdnet.py --parse-only    # 通信せず CSV だけ作り直す
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import io
import json
import re
import sys
import time
import zipfile
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent
OUT = BASE / "fundamentals"
TD = OUT / "tdnet"
LIST_DIR = TD / "list"
SUM_DIR = TD / "summary"
JQ_OUT = OUT / "jq_summary_tdnet"   # J-Quants と同じ形式（jq_files.py が J-Quants の後ろにつなぐ）
URL = "https://www.release.tdnet.info/inbs/"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) kabu-bunseki personal use"}
INTERVAL = 0.8   # 1リクエストごとの間隔（秒）

_last = [0.0]
_sess = requests.Session()


def log(msg):
    print(f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def get(url, tries=3):
    for i in range(tries):
        wait = _last[0] + INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.monotonic()
        try:
            r = _sess.get(url, headers=UA, timeout=30)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.content
        except Exception as e:  # noqa
            if i == tries - 1:
                raise
            time.sleep(3 * (i + 1))


def tdcode(c):
    """TDnet の5桁コード（72030・130A0）を4桁（7203・130A）に。"""
    c = c.strip()
    return c[:4] if len(c) == 5 and c.endswith("0") else c


# ---------------------------------------------------------------- 開示一覧

def fetch_list(day: dt.date) -> list[dict]:
    rows = []
    for p in range(1, 200):
        b = get(f"{URL}I_list_{p:03d}_{day:%Y%m%d}.html")
        if b is None:
            break
        h = b.decode("utf-8", "replace")
        for tr in re.findall(r"<tr>(.*?)</tr>", h, re.S):
            c = re.search(r'kjCode" noWrap>(\w+)\s*<', tr)
            if not c:
                continue
            tm = re.search(r'kjTime" noWrap>([\d:]+)<', tr)
            nm = re.search(r'kjName" noWrap>(.*?)<', tr, re.S)
            t = re.search(r'kjTitle".*?href="([^"]+)".*?>(.*?)</a>', tr, re.S)
            x = re.search(r'href="([^"]+\.zip)"', tr)
            pl = re.search(r'kjPlace" noWrap align="left">(.*?)<', tr, re.S)
            rows.append({
                "日付": day.isoformat(), "時刻": tm.group(1) if tm else "",
                "コード": tdcode(c.group(1)), "社名": (nm.group(1) if nm else "").strip(),
                "表題": re.sub(r"\s+", " ", t.group(2)).strip() if t else "",
                "pdf": t.group(1) if t else "", "xbrl": x.group(1) if x else "",
                "取引所": (pl.group(1) if pl else "").strip(),
            })
        if "I_list_%03d_%s.html" % (p + 1, day.strftime("%Y%m%d")) not in h:
            break
    return rows


def is_target(r):
    t = r["表題"]
    return bool(r["xbrl"]) and ("決算短信" in t or ("予想" in t and "修正" in t))


YANOSHIN = "https://webapi.yanoshin.jp/webapi/tdnet/list/{d}.json?limit=5000&hasXBRL=1"
ARCHIVE = "https://www2.jpx.co.jp/disc/{code5}/{file}"   # 東証上場会社情報サービス（過去分のファイルが残っている）


def fetch_list_yanoshin(day: dt.date) -> list[dict]:
    """31日より前の日の一覧。やのしん TDnet WEB-API（非公式・無料・登録不要）から XBRL のある開示だけ。
    TDnet 本体の一覧と 2026-10-20・11-13 で完全に一致することを確認済み（2026-11-16）。"""
    b = get(YANOSHIN.format(d=day.strftime("%Y%m%d")))
    if b is None:
        return []
    rows = []
    for it in json.loads(b.decode("utf-8")).get("items", []):
        x = it.get("Tdnet", {})
        u = x.get("url_xbrl") or ""
        if not u.endswith(".zip"):
            continue
        pub = x.get("pubdate", "")
        rows.append({"日付": day.isoformat(), "時刻": pub[11:16], "コード": tdcode(x.get("company_code", "")),
                     "社名": (x.get("company_name") or "").strip(), "表題": re.sub(r"\s+", " ", x.get("title", "")).strip(),
                     "pdf": "", "xbrl": u.rsplit("/", 1)[-1], "取引所": "", "出典": "yanoshin"})
    return rows


def save_summary(r) -> bool:
    d = SUM_DIR / r["日付"]
    out = d / (r["xbrl"].replace(".zip", "") + ".htm.gz")
    if out.exists():
        return False
    b = get(URL + r["xbrl"])
    if b is None:
        # 31日を過ぎて TDnet 本体から消えたものは、東証上場会社情報サービスに残っている
        c = r["コード"]
        b = get(ARCHIVE.format(code5=c + "0" if len(c) == 4 else c, file=r["xbrl"]))
    if b is None:
        return False
    z = zipfile.ZipFile(io.BytesIO(b))
    names = [n for n in z.namelist() if "/Summary/" in n and n.endswith("-ixbrl.htm")]
    if not names:
        # 予想修正などで Summary が無い形式もある → 最初の ixbrl を保存
        names = [n for n in z.namelist() if n.endswith("-ixbrl.htm")][:1]
    if not names:
        return False
    d.mkdir(parents=True, exist_ok=True)
    out.write_bytes(gzip.compress(z.read(names[0])))
    return True


# ---------------------------------------------------------------- 要約の読み取り

# 値の無い項目は <ix:nonFraction ... /> と自分で閉じるので、それを先に見分ける（後ろの数字を飲み込まない）
FACT = re.compile(r"<ix:(nonFraction|nonNumeric)\b([^>]*?)(?:/>|>(.*?)</ix:\1>)", re.S)


def parse_facts(h: str):
    num, txt = {}, {}
    for m in FACT.finditer(h):
        if m.group(3) is None:
            continue
        a = m.group(2)
        nm = re.search(r'name="([^"]+)"', a)
        cx = re.search(r'contextRef="([^"]+)"', a)
        if not nm or not cx:
            continue
        name = nm.group(1).split(":")[-1]
        ctx = cx.group(1)
        raw = re.sub(r"<[^>]+>", "", m.group(3)).strip()
        if m.group(1) == "nonNumeric":
            txt.setdefault((name, ctx), html_unescape(raw))
            continue
        if re.search(r'xsi:nil="true"', a) or not re.search(r"\d", raw):
            continue
        s = re.sub(r"[^\d.]", "", raw)
        try:
            v = float(s)
        except ValueError:
            continue
        sc = re.search(r'scale="(-?\d+)"', a)
        if sc:
            v *= 10 ** int(sc.group(1))
        if re.search(r'sign="-"', a):
            v = -v
        num[(name, ctx)] = v
    return num, txt


def html_unescape(s):
    import html
    return html.unescape(s).replace("\xa0", " ").strip()


# 指標ごとの要素名（先に書いたものを優先）。日本基準・IFRS・米国基準・業種別の接尾辞はまとめて扱う。
PAT = {
    "売上高": r"(NetSales|Revenue|Revenues|OperatingRevenues|OrdinaryRevenues|GrossOperatingRevenues|"
            r"NetRevenue|TotalRevenue|Sales|NetSalesOfCompletedConstructionContracts)",
    "営業利益": r"(OperatingIncome|OperatingProfit|OperatingIncomeLoss)",
    "経常利益": r"(OrdinaryIncome|OrdinaryProfit)",
    "税引前利益": r"(ProfitBeforeTax|IncomeBeforeIncomeTaxes|ProfitLossBeforeTax)",
    "純利益": r"(ProfitAttributableToOwnersOfParent|NetIncomeAttributableToOwnersOfParent|"
             r"NetIncomeAttributableTo\w*Parent|NetIncome|ProfitLoss|Profit)",
    "EPS": r"(NetIncomePerShare|BasicEarningsPerShare|BasicEarningsLossPerShare|EarningsPerShare)",
}
SUFFIX = r"(Specific)?(IFRS|US|JMIS|BK|IN|SE|ST|BKIFRS|INIFRS|SEIFRS|SECIFRS)?$"


def pick(num, metric, period, cons, kind="Result", change=False):
    """period: 'CurrentYearDuration' など。cons: 'Consolidated' / 'NonConsolidated'。"""
    alts = PAT[metric][1:-1].split("|")
    for alt in alts:
        rx = re.compile(("ChangeIn" if change else "") + "(" + alt + ")" + SUFFIX)
        for (name, ctx), v in num.items():
            if not rx.match(name):
                continue
            if not change and name.startswith(("Change", "Diluted")):
                continue
            parts = ctx.split("_")
            if parts[0] != period:
                continue
            mem = set(parts[1:])
            if f"{cons}Member" not in mem:
                continue
            if f"{kind}Member" not in mem:
                continue
            if any(m.endswith("SegmentMember") or m.startswith("Reportable") for m in mem):
                continue
            if "PreviousMember" in mem:   # 業績予想の修正の「前回発表予想」は読まない（修正後は CurrentMember）
                continue
            return v, name
    return None, None


def pick_forecast(num, metric, period, cons, change=False):
    v, n = pick(num, metric, period, cons, "Forecast", change)
    if v is not None:
        return v
    lo, _ = pick(num, metric, period, cons, "Lower", change)
    up, _ = pick(num, metric, period, cons, "Upper", change)
    if lo is not None and up is not None:
        return (lo + up) / 2
    return lo if lo is not None else up


Z2H = str.maketrans("０１２３４５６７８９", "0123456789")


def fye_from_title(title):
    """表題の「2027年３月期」「令和9年3月期」から決算期末を作る。"""
    s = title.translate(Z2H)
    m = re.search(r"(20\d\d)年\s*(\d{1,2})月期", s)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
    else:
        m = re.search(r"令和\s*(\d{1,2})年\s*(\d{1,2})月期", s)
        if not m:
            return ""
        y, mo = 2018 + int(m.group(1)), int(m.group(2))
    if not 1 <= mo <= 12:
        return ""
    return month_end(y, mo).isoformat()


def month_end(y, m):
    nxt = dt.date(y + (m == 12), m % 12 + 1, 1)
    return nxt - dt.timedelta(days=1)


def parse_summary(h: str, r: dict) -> dict | None:
    num, txt = parse_facts(h)
    if not num and not txt:
        return None
    t = {k[0]: v for k, v in txt.items()}
    title = r["表題"]
    kind = "決算短信" if "決算短信" in title else "予想修正"
    fye = t.get("FiscalYearEnd", "")
    if not fye:
        fye = fye_from_title(title)
    q = None
    for (name, ctx), v in num.items():
        if name == "QuarterlyPeriod":
            q = int(v)
    # 連結があれば連結
    cons = "Consolidated" if any("_ConsolidatedMember" in c for (_, c) in num) else "NonConsolidated"
    if kind == "決算短信":
        if q and q < 4:
            per = f"CurrentAccumulatedQ{q}Duration"
            fper = "CurrentYearDuration"
        else:
            q = 4
            per = "CurrentYearDuration"
            fper = "NextYearDuration"
    else:
        per = None
        fper = "CurrentYearDuration"
    row = {
        "開示日": r["日付"], "時刻": r["時刻"], "コード": r["コード"], "社名": r["社名"],
        "種別": kind, "表題": title, "訂正": "1" if "訂正" in title else "",
        "決算期末": fye, "四半期": q or "", "期間末": "", "連結": "連結" if cons == "Consolidated" else "単体",
        "会計基準": "IFRS" if "IFRS" in title or "ＩＦＲＳ" in title else
                    ("米国基準" if "米国" in title else ("日本基準" if "日本基準" in title else "")),
    }
    if fye and q:
        try:
            y, m = int(fye[:4]), int(fye[5:7])
            mm = m - 3 * (4 - q)
            while mm <= 0:
                mm += 12
                y -= 1
            row["期間末"] = month_end(y, mm).isoformat()
        except ValueError:
            pass
    used = []
    for k in PAT:
        if per:
            v, n = pick(num, k, per, cons)
            row[k] = v
            if n:
                used.append(n)
            if k != "EPS":
                row[k + "_前年比(%)"], _ = pick(num, k, per, cons, change=True)
        row["予想_" + k] = pick_forecast(num, k, fper, cons)
    if per:
        pi = per.replace("Duration", "Instant")
        for k, rx in (("総資産", r"TotalAssets"), ("純資産", r"(NetAssets|TotalEquity|Equity)"),
                      ("自己資本比率(%)", r"(CapitalAdequacyRatio|EquityToAssetRatio|"
                                        r"RatioOfOwnersEquityToGrossAssets|"
                                        r"RatioOfEquityAttributableToOwnersOfParentToTotalAssets|"
                                        r"EquityAttributableToOwnersOfParentToTotalAssetsRatio)")):
            v = None
            for (name, ctx), val in num.items():
                parts = ctx.split("_")
                if parts[0] == pi and f"{cons}Member" in parts and "PreviousMember" not in parts and re.match(rx + SUFFIX, name):
                    v = val
                    break
            row[k] = v
    # 年間配当（実績・予想）
    dv = dvf = None
    for (name, ctx), v in num.items():
        if not name.startswith("DividendPerShare"):
            continue
        parts = ctx.split("_")
        if "AnnualMember" not in parts or "PreviousMember" in parts:
            continue
        if q == 4 and parts[0] == "CurrentYearDuration" and "ResultMember" in parts:
            dv = v
        if parts[0] == fper and "ForecastMember" in parts:
            dvf = v
    # 前年比・自己資本比率は XBRL では小数（0.16＝16%）なので % に直す
    for k in list(row):
        if k.endswith("(%)") and isinstance(row[k], float):
            row[k] = round(row[k] * 100, 2)
    row["年間配当"] = dv
    row["予想_年間配当"] = dvf
    row["要素"] = ",".join(sorted(set(used)))
    row["xbrl"] = r["xbrl"]
    row["_jq"] = to_jq(num, row, cons, per, fper, q, kind)
    return row


# ---------------------------------------------------------------- J-Quants と同じ形式

def _val(num, rx, period, cons, kind="Result", extra=None):
    """要素名（正規表現）・期間・連結/単体・実績/予想で値を1つ探す。extra は追加で必要なメンバー。"""
    r = re.compile(rx + SUFFIX)
    order = [cons, None] if cons else [None]
    for want in order:
        for (name, ctx), v in num.items():
            parts = ctx.split("_")
            if parts[0] != period or not r.match(name):
                continue
            mem = set(parts[1:])
            if "PreviousMember" in mem:
                continue
            if want and f"{want}Member" not in mem:
                continue
            if kind and f"{kind}Member" not in mem:
                continue
            if extra and extra not in mem:
                continue
            return v
    return None


def _s(v):
    if v is None:
        return ""
    if abs(v - round(v)) < 1e-9 and abs(v) >= 1:
        return str(int(round(v)))
    return ("%.6f" % v).rstrip("0").rstrip(".")


def to_jq(num, row, cons, per, fper, q, kind):
    """fundamentals/jq_summary（J-Quants 決算短信サマリー）と同じ項目名の dict を作る。
    サイトの画面を作るスクリプト（jq_files.py 経由）が J-Quants の後ろにつないで読む。"""
    fye = row["決算期末"]
    if not fye:
        return None
    try:
        e = dt.date.fromisoformat(fye)
    except ValueError:
        return None
    st = (month_end(e.year - 1, e.month) + dt.timedelta(days=1)).isoformat()
    title = row["表題"]
    names = " ".join(n for (n, _) in num)
    std = ("IFRS" if ("IFRS" in title or "ＩＦＲＳ" in title or "IFRS" in names) else
           "US" if ("米国" in title or re.search(r"\w+US\b", names)) else
           "JMIS" if "JMIS" in title or "修正国際" in title else "JP")
    con = "Consolidated" if cons == "Consolidated" else "NonConsolidated"
    x = {"DiscDate": row["開示日"], "DiscTime": (row["時刻"] + ":00") if row["時刻"] else "",
         "Code": (row["コード"] + "0") if len(row["コード"]) == 4 else row["コード"],
         "DiscNo": row["xbrl"].replace(".zip", ""), "CurFYSt": st, "CurFYEn": fye, "Source": "TDnet"}
    F = {"Sales": "売上高", "OP": "営業利益", "OdP": "経常利益", "NP": "純利益", "EPS": "EPS"}
    if kind == "決算短信":
        pt = "FY" if q == 4 else f"{q}Q"
        x.update(DocType=f"{pt}FinancialStatements_{con}_{std}", CurPerType=pt, CurPerSt=st,
                 CurPerEn=row["期間末"])
        for k, c in F.items():
            x[k] = _s(row.get(c))
        if std != "JP":
            x["OdP"] = ""
        pi = per.replace("Duration", "Instant")
        x["TA"] = _s(row.get("総資産"))
        x["Eq"] = _s(row.get("純資産"))
        r = row.get("自己資本比率(%)")
        x["EqAR"] = _s(r / 100) if r is not None else ""
        x["ShEq"] = _s(_val(num, r"(OwnersEquity|EquityAttributableToOwnersOfParent)", pi, cons))
        x["BPS"] = _s(_val(num, r"(NetAssetsPerShare|EquityAttributableToOwnersOfParentPerShare)", pi, cons))
        x["DEPS"] = _s(_val(num, r"(DilutedNetIncomePerShare|DilutedEarningsPerShare|DilutedEarningsLossPerShare)", per, cons))
        # キャッシュフローは本決算と、中間期・四半期で載せている会社の分（あれば読む）
        for k, rx in (("CFO", r"CashFlowsFromOperatingActivities"), ("CFI", r"CashFlowsFromInvestingActivities"),
                      ("CFF", r"CashFlowsFromFinancingActivities"),
                      ("CashEq", r"(CashAndEquivalentsEndOfPeriod|CashAndCashEquivalentsEndOfPeriod|"
                                r"CashAndCashEquivalentsAtEndOfPeriod)")):
            x[k] = _s(_val(num, rx, per if k != "CashEq" else pi, cons))
        if q == 4:
            x["NxtFYSt"] = (e + dt.timedelta(days=1)).isoformat()
            x["NxtFYEn"] = month_end(e.year + 1, e.month).isoformat()
            x["DivAnn"] = _s(row.get("年間配当"))
            x["PayoutRatioAnn"] = _s(_val(num, r"PayoutRatio", "CurrentYearDuration", None, "Result"))
            pre = "NxF"
        else:
            pre = "F"
        sh = _val(num, r"NumberOfIssuedAndOutstandingSharesAtTheEndOfFiscalYearIncludingTreasuryStock", pi, None)
        tr = _val(num, r"NumberOfTreasuryStockAtTheEndOfFiscalYear", pi, None)
        av = _val(num, r"AverageNumberOfShares", per, None)
        x.update(ShOutFY=_s(sh), TrShFY=_s(tr), AvgSh=_s(av))
    else:
        has_earn = any(row.get("予想_" + c) is not None for c in ("売上高", "営業利益", "経常利益", "純利益"))
        x.update(DocType="EarnForecastRevision" if has_earn else "DividendForecastRevision",
                 CurPerType="FY", CurPerSt=st, CurPerEn=fye)
        pre = "F"
    for k, c in F.items():
        kk = pre + ("Np" if (k == "NP" and pre == "NxF") else k)
        x[kk] = _s(row.get("予想_" + c))
    if std != "JP":
        x[pre + "OdP"] = ""
    x[pre + "DivAnn"] = _s(row.get("予想_年間配当"))
    return x


COLS = ["開示日", "時刻", "コード", "社名", "種別", "表題", "訂正", "決算期末", "四半期", "期間末", "連結",
        "会計基準", "売上高", "売上高_前年比(%)", "営業利益", "営業利益_前年比(%)", "経常利益",
        "経常利益_前年比(%)", "税引前利益", "税引前利益_前年比(%)", "純利益", "純利益_前年比(%)", "EPS",
        "総資産", "純資産", "自己資本比率(%)", "年間配当",
        "予想_売上高", "予想_営業利益", "予想_経常利益", "予想_税引前利益", "予想_純利益", "予想_EPS",
        "予想_年間配当", "要素", "xbrl"]


def fmt(v):
    if v is None:
        return ""
    if isinstance(v, float):
        return ("%.0f" % v) if abs(v) >= 1000 or v == int(v) else ("%.2f" % v)
    return v


def build_csv():
    lists = {}
    for f in sorted(LIST_DIR.glob("*.json")):
        for r in json.loads(f.read_text(encoding="utf-8")):
            if r.get("xbrl"):
                lists[r["xbrl"].replace(".zip", "")] = r
    rows = []
    for f in sorted(SUM_DIR.glob("*/*.htm.gz")):
        key = f.name.replace(".htm.gz", "")
        r = lists.get(key)
        if not r:
            continue
        try:
            row = parse_summary(gzip.decompress(f.read_bytes()).decode("utf-8", "replace"), r)
        except Exception as e:  # noqa
            log(f"読み取り失敗 {f.name}: {e}")
            continue
        if row:
            rows.append(row)
    rows.sort(key=lambda x: (x["開示日"], x["時刻"], x["コード"]))
    with (OUT / "kessan_tanshin.csv").open("w", encoding="utf-8-sig", newline="") as fo:
        w = csv.writer(fo)
        w.writerow(COLS)
        for x in rows:
            w.writerow([fmt(x.get(c)) for c in COLS])
    # 銘柄ごとの最新（決算短信。訂正は同じ期の値を置き換える）。予想はその後の予想修正で上書き。
    latest = {}
    for x in rows:
        # 数字の入っていない訂正（本文の注記だけなど）は最新の扱いにしない
        if x["種別"] == "決算短信" and x["期間末"] and any(
                x.get(k) is not None for k in ("売上高", "営業利益", "経常利益", "純利益")):
            cur = latest.get(x["コード"])
            if cur is None or (x["期間末"], x["開示日"], x["時刻"]) >= (cur["期間末"], cur["開示日"], cur["時刻"]):
                latest[x["コード"]] = dict(x)
    for x in rows:
        if x["種別"] == "予想修正" and x["コード"] in latest:
            cur = latest[x["コード"]]
            if (x["開示日"], x["時刻"]) > (cur["開示日"], cur["時刻"]):
                for k in PAT:
                    if x.get("予想_" + k) is not None:
                        cur["予想_" + k] = x["予想_" + k]
                if x.get("予想_年間配当") is not None:
                    cur["予想_年間配当"] = x["予想_年間配当"]
                cur["予想修正日"] = x["開示日"]
    # J-Quants と同じ形式（開示日ごと）→ fundamentals/jq_summary_tdnet/<日付>.json
    JQ_OUT.mkdir(parents=True, exist_ok=True)
    byday = {}
    for x in rows:
        j = x.get("_jq")
        # 数字の無い開示（注記だけの訂正、配当も利益も予想が空の修正）は書かない（読む側で値を空に上書きしないように）
        if j and x["種別"] == "決算短信":
            ok = bool(x["期間末"]) and any(j.get(k) for k in ("Sales", "OP", "OdP", "NP"))
        elif j:
            ok = any(v for k, v in j.items() if k.startswith(("F", "NxF")) and k not in ("FY",))
        else:
            ok = False
        if ok:
            byday.setdefault(x["開示日"], []).append(j)
    for d, js in byday.items():
        p = JQ_OUT / f"{d}.json"
        s = json.dumps(js, ensure_ascii=False)
        if not p.exists() or p.read_text(encoding="utf-8") != s:
            p.write_text(s, encoding="utf-8")
    cols2 = COLS[:-1] + ["予想修正日"]   # 要素（売上の呼び方の判定に使う）は残す
    with (OUT / "kessan_latest.csv").open("w", encoding="utf-8-sig", newline="") as fo:
        w = csv.writer(fo)
        w.writerow(cols2)
        for c in sorted(latest):
            w.writerow([fmt(latest[c].get(k)) for k in cols2])
    log(f"CSV: 開示 {len(rows)} 件 → kessan_tanshin.csv、銘柄 {len(latest)} → kessan_latest.csv")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=31)
    ap.add_argument("--date")
    ap.add_argument("--parse-only", action="store_true")
    ap.add_argument("--backfill", metavar="開始:終了",
                    help="31日より前の期間（例 2026-08-25:2026-10-16）。一覧はやのしん API、XBRL は東証上場会社情報サービスから")
    a = ap.parse_args()
    LIST_DIR.mkdir(parents=True, exist_ok=True)
    SUM_DIR.mkdir(parents=True, exist_ok=True)
    if not a.parse_only:
        today = dt.date.today()
        if a.backfill:
            s0, s1 = (dt.date.fromisoformat(x) for x in a.backfill.split(":"))
            days = [s0 + dt.timedelta(days=i) for i in range((s1 - s0).days + 1)]
        else:
            days = [dt.date.fromisoformat(a.date)] if a.date else \
                [today - dt.timedelta(days=i) for i in range(a.days)]
        for day in sorted(days):
            lf = LIST_DIR / f"{day}.json"
            # 2日以上前の一覧は確定済みとみなして取り直さない
            if lf.exists() and (today - day).days >= 2:
                rows = json.loads(lf.read_text(encoding="utf-8"))
            else:
                try:
                    # TDnet 本体に一覧が残るのは31日分。それより前はやのしん API（XBRL のある開示だけ）
                    rows = fetch_list(day) if (today - day).days <= 29 else fetch_list_yanoshin(day)
                except Exception as e:  # noqa
                    log(f"{day} 一覧の取得に失敗: {e}")
                    continue
                if rows or (today - day).days >= 1:
                    lf.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
            tg = [r for r in rows if is_target(r)]
            new = 0
            for r in tg:
                try:
                    new += save_summary(r)
                except Exception as e:  # noqa
                    log(f"{day} {r['コード']} XBRL の取得に失敗: {e}")
            if rows:
                log(f"{day} 開示 {len(rows)} 件、決算短信・予想修正 {len(tg)} 件（新規 {new}）")
    build_csv()


if __name__ == "__main__":
    sys.exit(main())
