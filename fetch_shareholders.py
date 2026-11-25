#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
東証全銘柄の大株主（有価証券報告書「大株主の状況」上位10名）を EDINET API v2 から集める。

業績ダッシュボードと株式分析ダッシュボード（1画面）の「株主構成」円グラフの元データ。
無料の EDINET API（金融庁）だけを使う。キーは ~/株分析/edinet_key.txt。

しくみ
  1. 書類一覧（documents.json, type=2）を1日1ファイルで控える（直近 DAYS_BACK 日。過去日は一度だけ取得、
     直近 REFRESH_DAYS 日は毎回取り直す）。有価証券報告書（docTypeCode=120）で証券コードのあるものだけ残す。
  2. 銘柄ごとに一番新しい有報を選び、まだ読んでいなければ XBRL→CSV（type=5）を取得して
     大株主10名・発行済株式数・自己株式数を取り出す。
  3. fundamentals/shareholders.json（ダッシュボード用）と shareholders.csv（Excel 用）に保存する。
  4. 同じ書類から貸借対照表（当期末・前期末）も取り出し、fundamentals/balance_sheet.json に期末日ごとに蓄積する。

出力
  fundamentals/shareholders.json   {コード: {doc, filed, asof, issued, treasury, holders:[[名称, 株式数, 割合], ...]}}
  fundamentals/shareholders.csv    1行 = 銘柄 × 株主
  fundamentals/edinet_days/        書類一覧の控え（有報だけ、日別）
  fundamentals/shareholders_state.json  失敗した書類の記録
  fundamentals/balance_sheet.json  {コード: {期末日: {std, ta, cash, recv, inv, ca, ppe, pay, cl, tl, na, eq}}}（円。直近6期）

使い方
  ./.venv/bin/python fetch_shareholders.py               # 差分だけ（毎日の実行。新しい有報が出た銘柄だけ取りに行く）
  ./.venv/bin/python fetch_shareholders.py --max 50      # 1回で取りに行く有報の上限（既定 300）
  ./.venv/bin/python fetch_shareholders.py --workers 4   # 並列数（既定 1。初回の一括取得用）
  ./.venv/bin/python fetch_shareholders.py --status      # 通信せず件数だけ表示
"""
from __future__ import annotations

import argparse
import csv
import html
import datetime as dt
import io
import json
import re
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = Path(__file__).resolve().parent
FUND = BASE / "fundamentals"
DAYS_DIR = FUND / "edinet_days"
OUT_JSON = FUND / "shareholders.json"
OUT_CSV = FUND / "shareholders.csv"
STATE = FUND / "shareholders_state.json"
BS_JSON = FUND / "balance_sheet.json"
BS_KEEP = 6            # 貸借対照表は直近6期まで残す
KEY_FILE = BASE / "edinet_key.txt"
API = "https://api.edinet-fsa.go.jp/api/v2"

DAYS_BACK = 400        # 有報は年1回。13か月ほど見れば全社の最新が入る
REFRESH_DAYS = 3       # 直近の書類一覧は取り下げ・追加があるので毎回取り直す
SLEEP = 0.4            # APIへの思いやり（1スレッドあたり）
MAX_FAILS = 3

LOCK = threading.Lock()


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def key():
    k = KEY_FILE.read_text(encoding="utf-8").strip() if KEY_FILE.exists() else ""
    if not k:
        sys.exit("EDINET API のキーがありません（~/株分析/edinet_key.txt に1行で書いてください）")
    return k


def http(url, binary=False, tries=5):
    err = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=180) as r:
                b = r.read()
            if binary:
                if b[:1] == b"{":           # エラーは JSON で返ってくる
                    raise RuntimeError(b[:200].decode("utf-8", "ignore"))
                return b
            return json.loads(b)
        except Exception as e:  # noqa: BLE001
            err = e
            time.sleep(60 if "429" in str(e) else 4 * (i + 1))
    raise err


# ------------------------------------------------------------------ 書類一覧
def code_of(sec):
    s = (sec or "").strip()
    return s[:4] if len(s) == 5 else s


def update_days(k):
    DAYS_DIR.mkdir(parents=True, exist_ok=True)
    today = dt.date.today()
    got = 0
    for n in range(DAYS_BACK, -1, -1):
        d = today - dt.timedelta(n)
        f = DAYS_DIR / f"{d:%Y%m%d}.json"
        if f.exists() and n > REFRESH_DAYS:
            continue
        js = http(f"{API}/documents.json?date={d:%Y-%m-%d}&type=2&Subscription-Key={k}")
        if str(js.get("metadata", {}).get("status")) != "200":
            log(f"書類一覧 {d} 取得失敗: {js.get('metadata', {}).get('message')}")
            continue
        keep = [{"doc": x["docID"], "code": code_of(x.get("secCode")), "name": x.get("filerName"),
                 "filed": (x.get("submitDateTime") or "")[:10], "pe": x.get("periodEnd"),
                 "csv": x.get("csvFlag"), "wd": x.get("withdrawalStatus")}
                for x in js.get("results", [])
                if x.get("docTypeCode") == "120" and x.get("secCode")]
        f.write_text(json.dumps(keep, ensure_ascii=False), encoding="utf-8")
        got += 1
        time.sleep(SLEEP)
    # 古すぎる控えは捨てる
    cut = f"{today - dt.timedelta(DAYS_BACK + 30):%Y%m%d}"
    for f in DAYS_DIR.glob("*.json"):
        if f.stem < cut:
            f.unlink()
    return got


def latest_docs():
    """銘柄ごとに一番新しい有報（取り下げ・CSVなしを除く）"""
    best = {}
    for f in sorted(DAYS_DIR.glob("*.json")):
        for x in json.loads(f.read_text(encoding="utf-8")):
            if x.get("wd") not in ("0", None) or x.get("csv") != "1" or not x.get("code"):
                continue
            cur = best.get(x["code"])
            if cur is None or (x["pe"] or "", x["filed"]) >= (cur["pe"] or "", cur["filed"]):
                best[x["code"]] = x
    return best


# ------------------------------------------------------------------ 有報の読み取り
def clean_name(s):
    s = unicodedata.normalize("NFKC", html.unescape(s or "")).strip()
    s = re.sub(r"\s+", " ", s)
    # 「(常任代理人 ○○銀行)」の注記は落とす。信託口などの口座名は残す
    s = re.sub(r"\s*[(]\s*常任代理人.*$", "", s)
    return s.strip()


def to_num(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse_doc(b):
    z = zipfile.ZipFile(io.BytesIO(b))
    rows = []
    for n in z.namelist():
        if n.startswith("XBRL_TO_CSV/jpcrp") and n.endswith(".csv"):
            t = z.read(n).decode("utf-16", "ignore")
            rows.extend(csv.reader(io.StringIO(t), delimiter="\t"))
    H = {}
    issued = treasury = None
    for r in rows:
        if len(r) < 9:
            continue
        e, ctx, v = r[0], r[2], r[8]
        # 基準日が期末と違う会社は RecordDateInstant_… になる
        m = re.match(r"(?:CurrentYear|RecordDate)Instant_No(\d+)MajorShareholdersMember$", ctx)
        if m:
            h = H.setdefault(int(m.group(1)), {})
            if e == "jpcrp_cor:NameMajorShareholders":
                h["name"] = clean_name(v)
            elif e == "jpcrp_cor:NumberOfSharesHeld":
                h["shares"] = to_num(v)
            elif e == "jpcrp_cor:ShareholdingRatio":
                h["ratio"] = to_num(v)
            continue
        if e == "jpcrp_cor:NumberOfSharesIssuedSharesVotingRights" and ctx in ("CurrentYearInstant", "RecordDateInstant"):
            issued = to_num(v) or issued
        elif e == "jpcrp_cor:TotalNumberOfSharesHeldTreasurySharesEtc" and ctx in ("CurrentYearInstant", "RecordDateInstant"):
            treasury = to_num(v) if to_num(v) is not None else treasury
        elif issued is None and e == "jpcrp_cor:NumberOfIssuedSharesAsOfFiscalYearEndIssuedSharesTotalNumberOfSharesEtc" \
                and ctx == "FilingDateInstant":
            issued = to_num(v)
    holders = []
    for i in sorted(H):
        h = H[i]
        if h.get("name") and (h.get("shares") or h.get("ratio")):
            holders.append([h["name"], h.get("shares"), h.get("ratio")])
    return {"issued": issued, "treasury": treasury, "holders": holders, "bs": parse_bs(rows)}


# ------------------------------------------------------------------ 貸借対照表（当期末・前期末）
# 日本基準（jppfs_cor）と IFRS（jpigp_cor）の科目を、ダッシュボードの区分にまとめる。
# 値はすべて円。区分：資産＝現金預金・売上債権・棚卸資産・その他流動資産・有形固定資産・その他固定資産、
#               負債純資産＝買入債務・その他流動負債・固定負債・その他純資産（非支配株主持分など）・自己資本
JP = {
    "cash": [["CashAndDeposits"], ["CashAndCashEquivalents"]],
    "recv": [["NotesAndAccountsReceivableTradeAndContractAssets", "ElectronicallyRecordedMonetaryClaimsOperatingCA"],
             ["NotesAndAccountsReceivableTrade", "ElectronicallyRecordedMonetaryClaimsOperatingCA", "ContractAssets"],
             ["AccountsReceivableTradeAndContractAssets", "NotesReceivableTrade", "ElectronicallyRecordedMonetaryClaimsOperatingCA"],
             ["NotesReceivableTrade", "AccountsReceivableTrade", "ElectronicallyRecordedMonetaryClaimsOperatingCA", "ContractAssets",
              "NotesReceivableAccountsReceivableFromCompletedConstructionContractsAndOther",
              "AccountsReceivableFromCompletedConstructionContracts"]],
    "inv": [["Inventories"],
            ["MerchandiseAndFinishedGoods", "Merchandise", "FinishedGoods", "SemiFinishedGoods", "WorkInProcess",
             "RawMaterialsAndSupplies", "RawMaterials", "Supplies", "CostsOnUncompletedConstructionContracts",
             "RealEstateForSale", "RealEstateForSaleInProcess"]],
    "ca": [["CurrentAssets"]], "ppe": [["PropertyPlantAndEquipment"]], "ta": [["Assets"]],
    "pay": [["NotesAndAccountsPayableTrade", "ElectronicallyRecordedObligationsOperatingCL"],
            ["NotesPayableTrade", "AccountsPayableTrade", "ElectronicallyRecordedObligationsOperatingCL",
             "NotesPayableAccountsPayableForConstructionContractsAndOther", "AccountsPayableForConstructionContracts"]],
    "cl": [["CurrentLiabilities"]], "tl": [["Liabilities"]], "na": [["NetAssets"]],
    "nci": [["NonControllingInterests"]], "sub": [["SubscriptionRightsToShares"]],
}
IFRS = {
    "cash": [["CashAndCashEquivalentsIFRS"]],
    "recv": [["TradeAndOtherReceivablesCAIFRS", "ContractAssetsCAIFRS"], ["TradeReceivablesCAIFRS", "ContractAssetsCAIFRS"]],
    "inv": [["InventoriesCAIFRS"]],
    "ca": [["CurrentAssetsIFRS"]], "ppe": [["PropertyPlantAndEquipmentIFRS"]], "ta": [["AssetsIFRS"]],
    "pay": [["TradeAndOtherPayablesCLIFRS"], ["TradePayablesCLIFRS"]],
    "cl": [["TotalCurrentLiabilitiesIFRS"], ["CurrentLiabilitiesIFRS"]], "tl": [["LiabilitiesIFRS"]],
    "na": [["EquityIFRS"]], "own": [["EquityAttributableToOwnersOfParentIFRS"]],
    "nci": [["NonControllingInterestsIFRS"]],
}


def parse_bs(rows):
    vals = {}
    dei = {}
    for r in rows:
        if len(r) < 9:
            continue
        e, ctx, v = r[0], r[2], r[8]
        if e.startswith("jpdei_cor:"):
            dei[e[10:]] = v
            continue
        if not e.startswith(("jppfs_cor:", "jpigp_cor:")):
            continue
        m = re.match(r"(CurrentYear|Prior1Year)Instant(_NonConsolidatedMember)?$", ctx)
        if not m:
            continue
        x = to_num(v)
        if x is None:
            continue
        vals[(e.split(":", 1)[1], m.group(1), bool(m.group(2)))] = x

    def period(when):
        out = None
        for std, M in (("IFRS", IFRS), ("JP", JP)):
            for nc in (False, True):            # 連結を優先、無ければ個別
                if (M["ta"][0][0], when, nc) not in vals:
                    continue

                def g(k):
                    # 候補の組を順に試す。組の先頭科目があればその組の合計。最後の組は内訳の足し上げ（どれか1つでもあれば）
                    groups = M.get(k, [])
                    for i, group in enumerate(groups):
                        got = [vals[(n, when, nc)] for n in group if (n, when, nc) in vals]
                        if got and ((group[0], when, nc) in vals or i == len(groups) - 1):
                            return sum(got)
                    return None
                d = {k: g(k) for k in M}
                d["std"] = std
                d["nc"] = nc
                out = d
                break
            if out:
                break
        if not out:
            return None
        ta, ca, cl, tl, na = out.get("ta"), out.get("ca"), out.get("cl"), out.get("tl"), out.get("na")
        own = out.get("own")
        if own is None and na is not None:
            own = na - (out.get("nci") or 0) - (out.get("sub") or 0)
        if tl is None and ta is not None and na is not None:
            tl = ta - na
        if na is None and ta is not None and tl is not None:
            na = ta - tl
        res = {"std": out["std"], "ta": ta, "cash": out.get("cash"), "recv": out.get("recv"), "inv": out.get("inv"),
               "ca": ca, "ppe": out.get("ppe"), "pay": out.get("pay"), "cl": cl, "tl": tl, "na": na, "eq": own}
        return res

    cur_end = (dei.get("CurrentFiscalYearEndDateDEI") or "")[:10]
    cur_st = (dei.get("CurrentFiscalYearStartDateDEI") or "")[:10]
    out = {}
    c = period("CurrentYear")
    if c and cur_end:
        out[cur_end] = c
    p = period("Prior1Year")
    if p and cur_st:
        try:
            out[(dt.date.fromisoformat(cur_st) - dt.timedelta(days=1)).isoformat()] = p
        except ValueError:
            pass
    return out


# ------------------------------------------------------------------ 保存
def load_json(p, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def merge_bs(bstore, code, bs):
    """当期末・前期末の貸借対照表を銘柄の記録に足す（同じ期末は新しい書類で上書き）。"""
    if not bs:
        return
    rec = bstore.setdefault(code, {})
    rec.update(bs)
    for k in sorted(rec)[:-BS_KEEP]:
        del rec[k]


def save_bs(bstore):
    tmp = BS_JSON.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(bstore, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(BS_JSON)


def save(store):
    tmp = OUT_JSON.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(OUT_JSON)
    tmp = OUT_CSV.with_suffix(".csv.tmp")
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["コード", "社名", "基準日", "提出日", "書類ID", "順位", "株主名", "所有株式数",
                    "所有割合(%)", "発行済株式数", "自己株式数"])
        for code in sorted(store):
            s = store[code]
            for i, (nm, sh, ra) in enumerate(s["holders"], 1):
                w.writerow([code, s.get("name", ""), s.get("asof", ""), s.get("filed", ""), s["doc"], i, nm,
                            "" if sh is None else int(sh), "" if ra is None else round(ra * 100, 2),
                            "" if s.get("issued") is None else int(s["issued"]),
                            "" if s.get("treasury") is None else int(s["treasury"])])
    tmp.replace(OUT_CSV)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=300)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--no-list", action="store_true", help="書類一覧の更新を省く")
    a = ap.parse_args()

    store = load_json(OUT_JSON, {})
    bstore = load_json(BS_JSON, {})
    state = load_json(STATE, {"fails": {}})
    if a.status:
        best = latest_docs() if DAYS_DIR.exists() else {}
        todo = [c for c, x in best.items() if store.get(c, {}).get("doc") != x["doc"]]
        print(f"株主データ {len(store)} 銘柄 / 有報あり {len(best)} 銘柄 / 未取得 {len(todo)}")
        return
    k = key()
    if not a.no_list:
        n = update_days(k)
        log(f"書類一覧を {n} 日分更新")
    best = latest_docs()
    fails = state.setdefault("fails", {})
    todo = [x for c, x in best.items()
            if store.get(c, {}).get("doc") != x["doc"] and fails.get(x["doc"], 0) < MAX_FAILS]
    todo.sort(key=lambda x: x["filed"], reverse=True)
    todo = todo[:a.max]
    log(f"取得対象 {len(todo)} 件（有報あり {len(best)} 銘柄・取得済み {len(store)} 銘柄）")
    cnt = {"ok": 0, "ng": 0}

    def one(x):
        try:
            b = http(f"{API}/documents/{x['doc']}?type=5&Subscription-Key={k}", binary=True)
            r = parse_doc(b)
            bs = r.pop("bs", None)
            r.update(doc=x["doc"], filed=x["filed"], asof=x["pe"], name=x["name"])
            with LOCK:
                merge_bs(bstore, x["code"], bs)
                if r["holders"]:
                    store[x["code"]] = r
                    cnt["ok"] += 1
                else:
                    fails[x["doc"]] = MAX_FAILS     # 大株主の記載が無い書類（再取得しない）
                    cnt["ng"] += 1
        except Exception as e:  # noqa: BLE001
            with LOCK:
                fails[x["doc"]] = fails.get(x["doc"], 0) + 1
                cnt["ng"] += 1
                log(f"失敗 {x['code']} {x['doc']}: {str(e)[:120]}")
        with LOCK:
            done = cnt["ok"] + cnt["ng"]
            if done % 100 == 0:
                save(store)
                save_bs(bstore)
                STATE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
                log(f"  {done} / {len(todo)}")
        time.sleep(SLEEP)

    with ThreadPoolExecutor(max(1, a.workers)) as ex:
        list(ex.map(one, todo))
    save(store)
    save_bs(bstore)
    STATE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    log(f"貸借対照表 {len(bstore)} 銘柄 → {BS_JSON.relative_to(BASE)}")
    log(f"株主データ: 取得 {cnt['ok']} / 失敗 {cnt['ng']} / 保有 {len(store)} 銘柄 → {OUT_JSON.relative_to(BASE)}")


if __name__ == "__main__":
    main()
