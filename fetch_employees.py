#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""東証全銘柄の従業員の状況と関係会社の状況を、有価証券報告書（EDINET API v2）から集める。

株式分析ダッシュボードの「会社情報」（従業員数・平均年齢・平均年収・関連企業）の元データ。
無料の EDINET API（金融庁）だけを使う。キーは ~/株分析/edinet_key.txt。
書類一覧は fetch_shareholders.py が作る fundamentals/edinet_days/ をそのまま使う（一覧は取りに行かない）。

取り出す項目（XBRL→CSV、type=5）
  従業員数（連結）   jpcrp_cor:NumberOfEmployees  CurrentYearInstant
  従業員数（単体）   同 CurrentYearInstant_NonConsolidatedMember
  臨時従業員（平均） jpcrp_cor:AverageNumberOfTemporaryWorkers（連結→無ければ単体）
  平均年齢・平均勤続年数・平均年間給与（提出会社＝単体）
      jpcrp_cor:AverageAge… / AverageLengthOfService… / AverageAnnualSalary…InformationAboutReportingCompanyInformationAboutEmployees
  関係会社の状況     jpcrp_cor:OverviewOfAffiliatedEntitiesTextBlock（文章のまま gzip で保存）
  親会社等の情報     jpcrp_cor:InformationAboutParentCompanyEtcOfReportingCompanyTextBlock（同）
  過去5期の従業員数  jpcrp_cor:NumberOfEmployees…SummaryOfBusinessResults（経営指標等の推移。連結→単体）

出力
  fundamentals/employees.json        {コード: {doc, filed, asof, emp, emp_nc, temp, age, tenure, salary, hist:[[期, 人数],...]}}
  fundamentals/employees.csv         Excel 用（1行=1銘柄）
  fundamentals/raw_affiliates/<コード>.json.gz  {"doc", "aff": 関係会社の状況の文章, "parent": 親会社等の情報の文章}
  関連企業の照合は make_company_links.py が行う（通信なし）。

使い方
  ./.venv/bin/python fetch_employees.py               # 差分だけ（新しい有報が出た銘柄）
  ./.venv/bin/python fetch_employees.py --max 50      # 1回の上限（既定 300）
  ./.venv/bin/python fetch_employees.py --workers 4   # 並列数（初回の一括取得用）
  ./.venv/bin/python fetch_employees.py --status
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import re
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import fetch_shareholders as fs

BASE = Path(__file__).resolve().parent
FUND = BASE / "fundamentals"
OUT_JSON = FUND / "employees.json"
OUT_CSV = FUND / "employees.csv"
STATE = FUND / "employees_state.json"
AFF_DIR = FUND / "raw_affiliates"
MAX_FAILS = 3
LOCK = threading.Lock()
log = fs.log

E_AGE = "jpcrp_cor:AverageAgeYearsInformationAboutReportingCompanyInformationAboutEmployees"
E_TEN = "jpcrp_cor:AverageLengthOfServiceYearsInformationAboutReportingCompanyInformationAboutEmployees"
E_SAL = "jpcrp_cor:AverageAnnualSalaryInformationAboutReportingCompanyInformationAboutEmployees"
PRIOR = {"CurrentYearDuration": 0, "Prior1YearDuration": 1, "Prior2YearDuration": 2,
         "Prior3YearDuration": 3, "Prior4YearDuration": 4}


def num(v):
    v = fs.to_num(v)
    return v


def parse_doc(b):
    z = zipfile.ZipFile(io.BytesIO(b))
    rows = []
    for n in z.namelist():
        if n.startswith("XBRL_TO_CSV/jpcrp") and n.endswith(".csv"):
            t = z.read(n).decode("utf-16", "ignore")
            rows.extend(csv.reader(io.StringIO(t), delimiter="\t"))
    r = {}
    hist_c, hist_n = {}, {}
    aff = parent = ""
    for x in rows:
        if len(x) < 9:
            continue
        e, ctx, v = x[0], x[2], x[8]
        loc = e.split(":", 1)[-1]
        if e == "jpcrp_cor:NumberOfEmployees":
            if ctx == "CurrentYearInstant":
                r["emp"] = num(v)
            elif ctx == "CurrentYearInstant_NonConsolidatedMember":
                r["emp_nc"] = num(v)
            m = re.fullmatch(r"(CurrentYear|Prior[1-4]Year)Instant(_NonConsolidatedMember)?", ctx)
            if m:
                k = PRIOR[m.group(1) + "Duration"]
                (hist_n if m.group(2) else hist_c)[k] = num(v)
        elif e == "jpcrp_cor:AverageNumberOfTemporaryWorkers":
            if ctx == "CurrentYearInstant":
                r["temp"] = num(v)
            elif ctx == "CurrentYearInstant_NonConsolidatedMember":
                r.setdefault("temp_nc", num(v))
        elif e == E_AGE and ctx.startswith("CurrentYearInstant"):
            r.setdefault("age", num(v))
        elif e == E_TEN and ctx.startswith("CurrentYearInstant"):
            r.setdefault("tenure", num(v))
        elif e == E_SAL and ctx.startswith("CurrentYearInstant"):
            r.setdefault("salary", num(v))
        elif loc.startswith("NumberOfEmployees") and "SummaryOfBusinessResults" in loc:
            # 経営指標等の推移（連結の表は ctx に NonConsolidated が付かない）
            base = ctx.split("_")[0]
            if base in PRIOR and ctx in (base, base + "_NonConsolidatedMember"):
                (hist_n if "NonConsolidated" in ctx else hist_c).setdefault(PRIOR[base], num(v))
        elif e == "jpcrp_cor:OverviewOfAffiliatedEntitiesTextBlock":
            aff = v
        elif e == "jpcrp_cor:InformationAboutParentCompanyEtcOfReportingCompanyTextBlock":
            parent = v
    if r.get("temp") is None and r.get("temp_nc") is not None:
        r["temp"] = r["temp_nc"]
    r.pop("temp_nc", None)
    if r.get("emp") is None and r.get("emp_nc") is not None:
        r["emp"] = r["emp_nc"]
    h = hist_c if len(hist_c) >= len(hist_n) else hist_n
    r["hist"] = [[k, h[k]] for k in sorted(h, reverse=True) if h[k] is not None]   # k=何期前
    return r, aff, parent


def save(store):
    OUT_JSON.write_text(json.dumps(store, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["コード", "社名", "決算期末", "提出日", "書類ID", "従業員数(連結)", "従業員数(単体)",
                    "臨時従業員(平均)", "平均年齢(歳)", "平均勤続年数(年)", "平均年間給与(円)"])
        for c in sorted(store):
            x = store[c]
            w.writerow([c, x.get("name"), x.get("asof"), x.get("filed"), x.get("doc"), x.get("emp"),
                        x.get("emp_nc"), x.get("temp"), x.get("age"), x.get("tenure"), x.get("salary")])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=300)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()
    store = fs.load_json(OUT_JSON, {})
    state = fs.load_json(STATE, {"fails": {}})
    best = fs.latest_docs()
    fails = state.setdefault("fails", {})
    todo = [x for c, x in best.items()
            if store.get(c, {}).get("doc") != x["doc"] and fails.get(x["doc"], 0) < MAX_FAILS]
    if a.status:
        print(f"従業員データ {len(store)} 銘柄 / 有報あり {len(best)} 銘柄 / 未取得 {len(todo)}")
        return
    k = fs.key()
    AFF_DIR.mkdir(parents=True, exist_ok=True)
    todo.sort(key=lambda x: x["filed"], reverse=True)
    todo = todo[:a.max]
    log(f"取得対象 {len(todo)} 件（有報あり {len(best)} 銘柄・取得済み {len(store)} 銘柄）")
    cnt = {"ok": 0, "ng": 0}

    def one(x):
        try:
            b = fs.http(f"{fs.API}/documents/{x['doc']}?type=5&Subscription-Key={k}", binary=True)
            r, aff, parent = parse_doc(b)
            r.update(doc=x["doc"], filed=x["filed"], asof=x["pe"], name=x["name"])
            with gzip.open(AFF_DIR / f"{x['code']}.json.gz", "wt", encoding="utf-8") as f:
                json.dump({"doc": x["doc"], "aff": aff, "parent": parent}, f, ensure_ascii=False)
            with LOCK:
                store[x["code"]] = r
                cnt["ok"] += 1
        except Exception as e:  # noqa: BLE001
            with LOCK:
                fails[x["doc"]] = fails.get(x["doc"], 0) + 1
                cnt["ng"] += 1
                log(f"失敗 {x['code']} {x['doc']}: {str(e)[:120]}")
        with LOCK:
            done = cnt["ok"] + cnt["ng"]
            if done % 100 == 0:
                save(store)
                STATE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
                log(f"  {done} / {len(todo)}")
        time.sleep(fs.SLEEP)

    with ThreadPoolExecutor(max(1, a.workers)) as ex:
        list(ex.map(one, todo))
    save(store)
    STATE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    log(f"従業員データ: 取得 {cnt['ok']} / 失敗 {cnt['ng']} / 保有 {len(store)} 銘柄 → {OUT_JSON.relative_to(BASE)}")


if __name__ == "__main__":
    main()
