#!/usr/bin/env python3
"""日経225 入れ替え予想・ウエート分析（毎営業日 run_daily.sh から呼ばれる）

  1. 日経平均プロフィルから構成銘柄・お知らせ・除数を取得し、株価換算係数の表を更新（fetch_nikkei.py）
  2. 株価換算係数×株価で日経平均を再計算し、公表値と一致するか検証。ウエート・寄与度・キャップ監視
  3. 選定基準（流動性上位450・絶対採用75位・セクター採用妥当数）を再現して、次回の定期見直しを予想
  4. 過去の定期見直しの再現テストと、採用・除外銘柄の値動き（イベント分析）
  5. 出力
       日経225/output/日経225_YYYY-MM-DD.xlsx   … Excel（連動資産額を変えると需給インパクトが再計算）
       data/charts/nikkei225.html              … ダッシュボード（トップ画面からリンク）
       data/charts/nikkei225_summary.json      … トップ画面のカード用
       fundamentals/nikkei225.csv              … 銘柄ごとの「日経225」列（ファンダメンタル分析のスコア一覧に結合）
       日経225/output/history/予想_YYYY-MM-DD.csv … 予想の記録（予想が日々どう変わったか）

実行:
  ~/株分析/.venv/bin/python ~/株分析/日経225/run_nikkei225.py            # 取得あり
  ~/株分析/.venv/bin/python ~/株分析/日経225/run_nikkei225.py --offline  # 通信なし
"""
from __future__ import annotations

import argparse
import sys
import time
import warnings
from datetime import date

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

import backtest  # noqa: E402
import fetch_nikkei  # noqa: E402
import report  # noqa: E402
import weights  # noqa: E402
from history import members_on, periodic_reviews  # noqa: E402
from nk_common import (FUND, NIKKEI_IDX, OUT, SITE, TOPIX_IDX, load_components, load_events,  # noqa: E402
                       load_excludes, load_factors, load_index, load_price_panel, load_sectors_table,
                       save_json, sector_of)
from selection import (ABS_ADD, HIGH_LIQ, decisions_frame, liquidity_table, review_schedule,  # noqa: E402
                       simulate)

AUM_DEFAULT = 10.0   # 日経平均連動の運用資産（兆円）の仮置き。Excelの「需給インパクト」シートで変えられる


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="日経のサイトにアクセスしない")
    ap.add_argument("--no-backtest", action="store_true", help="イベント分析と売買ルール検証を省く")
    ap.add_argument("--aum", type=float, default=AUM_DEFAULT, help="日経平均連動の運用資産（兆円・仮置き）")
    a = ap.parse_args(argv)
    t0 = time.time()
    today = date.today().isoformat()

    # 1) 日経のデータ
    rc = fetch_nikkei.main(["--offline"] if a.offline else [])
    if rc == 1:
        return 1

    comp = load_components()
    members = comp["code"].tolist()
    factors = load_factors()
    events = load_events()
    sec = load_sectors_table()
    names = dict(zip(sec["code"], sec["name"]))
    names.update(dict(zip(comp["code"], comp["company"].str.replace(r"[（(]株[）)]", "", regex=True).str.strip())))
    industry = dict(zip(sec["code"], sec["nk_industry"]))
    prime = set(sec[sec["is_prime"]]["code"])

    # 2) 株価
    ev_codes = set(events["code"])
    start = (pd.Timestamp(today) - pd.DateOffset(years=9)).strftime("%Y-%m-%d")
    panel = load_price_panel(sorted(prime | set(members) | ev_codes), start=start)
    if panel.empty:
        log("株価データがありません")
        return 1
    last_day = panel["date"].max()
    log(f"株価 {panel['code'].nunique():,}銘柄 {len(panel):,}行（最終日 {last_day:%Y-%m-%d}）")
    closes = panel.pivot_table(index="date", columns="code", values="close")
    nikkei = load_index(NIKKEI_IDX)
    topix = load_index(TOPIX_IDX)

    # 3) ウエート・寄与度・検証
    adj = weights.build(factors, closes)
    val = weights.validate(adj, nikkei, str(factors["asof"].max()) if "asof" in factors else today, members)
    D, d_date = weights.divisor_on(last_day + pd.Timedelta(days=1))
    if not (D > 0):
        D = float(adj.iloc[-1].sum() / nikkei.iloc[-1])
    wt = weights.table(adj, factors, closes, D)
    eff_next = review_schedule(pd.Timestamp(today))
    nxt = eff_next[0]
    sec_now = {c: sector_of(industry.get(c, ""), c, nxt["effective"].strftime("%Y-%m-%d")) for c in closes.columns}
    wt.insert(0, "銘柄名", [names.get(c, "") for c in wt.index])
    wt.insert(1, "業種", [industry.get(c, "") for c in wt.index])
    wt.insert(2, "セクター", [sec_now.get(c, "") for c in wt.index])
    capw = weights.cap_watch(wt, nxt["base"])
    secw = weights.sector_contrib(wt, sec_now)
    whist = weights.weight_history(adj, list(wt.index[:8]))
    log(f"検証: {val['message']}")

    # 4) 次回の定期見直しの予想（いまの株価データで基準日を迎えたと仮定）
    excl = load_excludes(today)
    rep = backtest.replay(panel, industry, prime)   # 前回見送りの判定にも使うので常に実行（約10秒）
    passed = set(rep[-1]["passed_over"]) if rep else set()
    passed -= set(members)
    mem_now = set(members)
    asof = min(last_day, nxt["base"])
    liq = liquidity_table(panel, asof, universe=prime | mem_now)
    sim = simulate(liq, mem_now, industry, nxt["effective"], excluded=set(excl), passed_over=passed)
    dec = decisions_frame(sim, names)
    # 順位の変化（1か月前・3か月前）
    trend = {}
    for lab, m in (("1か月前", 1), ("3か月前", 3)):
        prev = liquidity_table(panel, asof - pd.DateOffset(months=m), universe=prime | mem_now)
        trend[lab] = prev["liq_rank"]
    ranks = sim.ranks.copy()
    ranks["銘柄名"] = ranks["code"].map(names)
    for lab, s in trend.items():
        ranks[f"順位({lab})"] = ranks["code"].map(s)
    ranks["売買代金(億円/日)"] = ranks["tv_mean"] / 1e8
    tv20 = panel[panel["date"] > last_day - pd.Timedelta(days=30)].groupby("code")["tv"].mean()

    # 需給インパクト（予想採用銘柄）
    sum_adj = float(adj.iloc[-1].sum())
    imp_rows = []
    for d in sim.decisions:
        if d.action != "採用":
            continue
        px = float(closes[d.code].dropna().iloc[-1]) if d.code in closes.columns else np.nan
        f = 1.0
        if px / (sum_adj + px) > 0.01:   # 採用時のウエートが1%を超えるなら0.1〜0.9に（日経の規定）
            f = max(0.1, min(0.9, np.floor(sum_adj * 0.01 / px * 10) / 10))
        w_in = px * f / (sum_adj + px * f) * 100
        imp_rows.append({"コード": d.code, "銘柄名": names.get(d.code, ""), "確度": d.confidence,
                         "株価": px, "想定係数": f, "想定ウエート(%)": w_in,
                         "売買代金20日平均(億円)": tv20.get(d.code, np.nan) / 1e8})
    for d in sim.decisions:
        if d.action != "除外":
            continue
        imp_rows.append({"コード": d.code, "銘柄名": names.get(d.code, ""), "確度": d.confidence,
                         "株価": float(closes[d.code].dropna().iloc[-1]) if d.code in closes.columns else np.nan,
                         "想定係数": float(factors.set_index("code")["factor"].get(d.code, np.nan)),
                         "想定ウエート(%)": -float(wt["ウエート(%)"].get(d.code, np.nan)),
                         "売買代金20日平均(億円)": tv20.get(d.code, np.nan) / 1e8})
    impact = pd.DataFrame(imp_rows)

    # 5) 過去の検証
    bt = {}
    if rep and not a.no_backtest:
        bt["replay"] = backtest.replay_frame(rep, names)
        ev_p = events[events["type"].isin(["add", "del"]) & events["reason"].fillna("").str.startswith("定期")]
        es = backtest.event_study(closes, topix, ev_p, {r["effective"]: r["base"] for r in rep})
        bt["events"] = es
        bt["event_summary"] = backtest.summarize_events(es)
        st = backtest.strategy(rep, closes, topix)
        bt["strategy"] = st
        n_add = sum(len(r["adds"]) for r in rep)
        n_del = sum(len(r["dels"]) for r in rep)
        bt["hit"] = {"採用": (sum(len(r["hit_adds"]) for r in rep), n_add,
                              sum(len(r["pred_adds"]) for r in rep)),
                     "除外": (sum(len(r["hit_dels"]) for r in rep), n_del,
                              sum(len(r["pred_dels"]) for r in rep))}

    # 6) 銘柄ごとの列（ファンダメンタル分析に結合）
    score = per_stock(sim, wt, ranks, names, excl, passed)
    FUND.mkdir(parents=True, exist_ok=True)
    score.to_csv(FUND / "nikkei225.csv", index=False, encoding="utf-8-sig")

    ctx = dict(today=today, last_day=last_day, nxt=nxt, schedule=eff_next, val=val, D=D, d_date=d_date,
               wt=wt, capw=capw, secw=secw, whist=whist, sim=sim, dec=dec, ranks=ranks, impact=impact,
               aum=a.aum, bt=bt, events=events, excl=excl, passed=passed, names=names, factors=factors,
               nikkei=nikkei, asof=asof, comp=comp)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "history").mkdir(exist_ok=True)
    dec.assign(基準=f"{asof:%Y-%m-%d}時点").to_csv(OUT / "history" / f"予想_{last_day:%Y-%m-%d}.csv",
                                                index=False, encoding="utf-8-sig")
    xlsx = OUT / f"日経225_{last_day:%Y-%m-%d}.xlsx"
    try:
        report.write_excel(xlsx, ctx)
        log(f"Excel: {xlsx}")
    except Exception as e:  # noqa: BLE001
        log(f"※ Excelの作成に失敗: {e}")
    SITE.mkdir(parents=True, exist_ok=True)
    report.write_html(SITE / "nikkei225.html", ctx)
    save_json(SITE / "nikkei225_summary.json", report.summary(ctx))
    log(f"ダッシュボード: {SITE / 'nikkei225.html'}（{time.time() - t0:.0f}秒）")
    return 0


def per_stock(sim, wt, ranks, names, excl, passed) -> pd.DataFrame:
    """銘柄ごとの日経225の情報。日経225入替スコア：予想採用 高90・中70・低50、予想除外は負、
    予想には入らないが近い候補（流動性100位以内 or 不足セクターの上位）は30"""
    dec = {d.code: d for d in sim.decisions}
    r = ranks.set_index("code")
    rows = []
    for c, x in r.iterrows():
        d = dec.get(c)
        member = bool(x["member"])
        lab, sc = "", 0
        if d is not None:
            sc = {"高": 90, "中": 70, "低": 50}[d.confidence] * (1 if d.action == "採用" else -1)
            lab = f"{d.action}予想（{d.confidence}）"
        elif not member and pd.notna(x["liq_rank"]) and c not in excl:
            under = sim.add_candidates is not None and c in set(sim.add_candidates["code"])
            if x["liq_rank"] <= 100 or under:
                sc, lab = 30, "採用候補"
        elif member and pd.notna(x["liq_rank"]) and x["liq_rank"] > 400:
            sc, lab = -30, "除外候補"
        rows.append({"コード": c, "日経225採用": int(member),
                     "日経225ウエート(%)": round(float(wt["ウエート(%)"].get(c, np.nan)), 3) if member else np.nan,
                     "日経225流動性順位": x["liq_rank"], "日経225セクター": x["sector"],
                     "日経225入替予想": lab, "日経225入替スコア": sc})
    # 順位が付かない構成銘柄も載せる
    have = {x["コード"] for x in rows}
    for c in wt.index:
        if c not in have:
            rows.append({"コード": c, "日経225採用": 1, "日経225ウエート(%)": round(float(wt.loc[c, "ウエート(%)"]), 3),
                         "日経225流動性順位": np.nan, "日経225セクター": wt.loc[c, "セクター"],
                         "日経225入替予想": "", "日経225入替スコア": 0})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    sys.exit(main())
