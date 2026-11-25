#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""会社予想（J-Quants fins summary）から、SBI証券スクリーナーの「コンセンサス」欄に近い項目を作る

アナリスト予想（コンセンサス・目標株価・レーティング）は手元に無いので、代わりに
**会社予想**で同じ考え方の数字を出す。analyze_fundamentals.py から attach_forecast_extra() を呼ぶ。

  予想EPS(円)                 今期（予想が出ている一番新しい期）の会社予想EPS
  予想1株配当(円)             同じ期の年間配当予想
  予想配当利回り(%)           予想1株配当 ÷ 株価
  予想売上高成長率(%)         今期予想売上高 ÷ 前期実績 − 1
  予想営業増益率(%)           今期予想営業利益 ÷ 前期実績 − 1（前期が赤字なら空欄）
  予想純利益率(%)             今期予想純利益 ÷ 今期予想売上高
  業績予想修正率(%)           最後に営業利益予想を変えたときの変化率（＋上方修正・−下方修正）
                              営業利益の予想が無い会社（銀行など）は経常利益、それも無ければ純利益
  期初予想比(%)               いまの予想 ÷ その期で最初に出た予想 − 1（期中の修正の累計）
  予想修正からの日数          その修正を開示してから今日までの日数（暦日）
  配当予想修正率(%)           最後に年間配当予想を変えたときの変化率
  決算サプライズ(%)           直近の本決算の営業利益 ÷ 決算発表直前の会社予想 − 1

注意: J-Quants の Free プランは12週間遅れなので、ここ3か月の修正はまだ入っていない。
"""

from __future__ import annotations
import jq_files  # J-Quants＋TDnet の決算短信サマリー

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import splits_util  # noqa: E402  株式分割の台帳（data/splits.csv）

EXTRA_COLS = ["予想EPS(円)", "予想1株配当(円)", "予想配当利回り(%)", "予想売上高成長率(%)",
              "予想営業増益率(%)", "予想純利益率(%)", "業績予想修正率(%)", "期初予想比(%)",
              "予想修正からの日数", "予想修正の開示日", "配当予想修正率(%)", "決算サプライズ(%)"]


def _num(v) -> float:
    try:
        x = float(v)
        return x if np.isfinite(x) else np.nan
    except (TypeError, ValueError):
        return np.nan


def _pick(r, key):
    """連結が無ければ個別（NC〜）"""
    v = _num(r.get(key))
    return v if not np.isnan(v) else _num(r.get("NC" + key))


def _code(c) -> str:
    c = str(c)
    return c[:4] if len(c) == 5 and c.endswith("0") else c


def load(jq_dir: Path):
    fc, act = [], []
    for f in jq_files.files(jq_dir):
        try:
            rows = json.loads(f.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if not isinstance(rows, list):
            continue
        for r in rows:
            doc = r.get("DocType", "")
            if "REIT" in doc:
                continue
            code = _code(r.get("Code", ""))
            when = pd.to_datetime(f"{r.get('DiscDate', '')} {r.get('DiscTime', '') or '00:00'}",
                                  errors="coerce")
            cur = str(r.get("CurFYEn") or "")[:7]
            if not cur or pd.isna(when):
                continue
            if doc.startswith("FY") and "FinancialStatements" in doc:
                act.append(dict(コード=code, 期=cur, 開示=when, 売上高=_pick(r, "Sales"),
                                営業利益=_pick(r, "OP"), 経常利益=_pick(r, "OdP"),
                                純利益=_pick(r, "NP")))
                nxt = str(r.get("NxtFYEn") or "")[:7] or \
                    (pd.Timestamp(r["CurFYEn"]) + pd.DateOffset(years=1)).strftime("%Y-%m")
                fc.append(dict(コード=code, 期=nxt, 開示=when, 売上高=_pick(r, "NxFSales"),
                               営業利益=_pick(r, "NxFOP"), 経常利益=_pick(r, "NxFOdP"),
                               純利益=_num(r.get("NxFNp")) if not np.isnan(_num(r.get("NxFNp")))
                               else _num(r.get("NCNxFNp")),
                               EPS=_pick(r, "NxFEPS"), 配当=_num(r.get("NxFDivAnn"))))
            else:
                # 四半期決算・業績予想の修正・配当予想の修正に載る「当期の通期予想」
                fc.append(dict(コード=code, 期=cur, 開示=when, 売上高=_pick(r, "FSales"),
                               営業利益=_pick(r, "FOP"), 経常利益=_pick(r, "FOdP"),
                               純利益=_pick(r, "FNP"), EPS=_pick(r, "FEPS"),
                               配当=_num(r.get("FDivAnn"))))
    fc = pd.DataFrame(fc)
    act = pd.DataFrame(act)
    return fc, act


def _last_change(vals: list[tuple]) -> tuple[float, pd.Timestamp | None]:
    """(開示, 値) を時系列に並べ、最後に値が変わったときの変化率と開示日"""
    prev, rate, when = None, np.nan, None
    for t, v in vals:
        if np.isnan(v):
            continue
        if prev is not None and v != prev:
            rate = (v / prev - 1) * 100 if prev > 0 else np.nan
            when = t
        prev = v
    return rate, when


def adjust_for_splits(fc: pd.DataFrame, d: pd.DataFrame) -> pd.DataFrame:
    """予想EPS・予想1株配当を、台帳 data/splits.csv の分割で「いまの株数ベース」にそろえる。

    J-Quants Free は12週遅れなので、開示のあとに分割した銘柄では予想が分割前ベースのまま残り、
    予想配当利回りが分割比倍に見えたり、分割後ベースの次の予想との差が「配当予想の下方修正」に
    見えたりする。分割を発表した短信では予想を分割後ベースで出す会社もあるため、
    予想純利益 ÷ 予想EPS がいまの株数（決算の株数を分割調整したもの）と合う係数で割る。
    確かめられないときは「開示日より後に権利落ちした分割比の積」で割る。"""
    led = splits_util.ledger()
    if fc.empty or not led:
        return fc
    shares = {}
    if "発行済株式数" in d.columns:
        shares = pd.to_numeric(d["発行済株式数"], errors="coerce").set_axis(d["コード"].astype(str)).to_dict()
    fc = fc.copy()
    n = 0
    for i in fc.index[fc["コード"].isin(list(led))]:
        code = fc.at[i, "コード"]
        when = fc.at[i, "開示"].strftime("%Y-%m-%d")
        F = splits_util.factor_after(code, when)
        eps, np_ = fc.at[i, "EPS"], fc.at[i, "純利益"]
        implied = np_ / eps if (np.isfinite(eps) and np.isfinite(np_) and eps != 0) else None
        g, _ = splits_util.choose(code, implied, shares.get(code), F)
        if g != 1.0:
            fc.at[i, "EPS"] = eps / g
            fc.at[i, "配当"] = fc.at[i, "配当"] / g
            n += 1
    if n:
        print(f"会社予想: 株式分割の調整 {n:,}件（予想EPS・予想1株配当を分割後の株数ベースに）")
    return fc


def attach_forecast_extra(d: pd.DataFrame, jq_dir: Path, today=None) -> pd.DataFrame:
    d = d.copy()
    for c in EXTRA_COLS:
        d[c] = "" if c == "予想修正の開示日" else np.nan
    if not jq_dir.exists() or not any(jq_dir.glob("*.json")):
        print("※ 会社予想が無いため、予想配当・予想修正・サプライズは空欄", file=sys.stderr)
        return d
    today = pd.Timestamp(today or pd.Timestamp.today().normalize())
    fc, act = load(jq_dir)
    if fc.empty:
        return d
    fc = adjust_for_splits(fc, d)
    fc = fc.sort_values("開示")
    act = act.sort_values("開示")
    fc_g = dict(tuple(fc.groupby("コード")))
    act_g = dict(tuple(act.groupby("コード")))
    price = d.set_index(d["コード"].astype(str))["株価"]

    out = {}
    for code, g in fc_g.items():
        rec = {}
        a = act_g.get(code)
        # 今期＝本決算がまだ出ていない一番新しい期
        done = set(a["期"]) if a is not None else set()
        pending = g[~g["期"].isin(done)]
        if len(pending):
            ki = pending["期"].max()
            cur = pending[pending["期"] == ki]
            last = lambda k: (cur[k].dropna().iloc[-1] if cur[k].notna().any() else np.nan)
            eps, div = last("EPS"), last("配当")
            rec["予想EPS(円)"] = eps
            rec["予想1株配当(円)"] = div
            p = price.get(code, np.nan)
            if np.isfinite(div) and p and p > 0:
                rec["予想配当利回り(%)"] = div / p * 100
            s, op, np_ = last("売上高"), last("営業利益"), last("純利益")
            if s and s > 0 and np.isfinite(np_):
                rec["予想純利益率(%)"] = np_ / s * 100
            # 前期実績（期末がちょうど1年前の本決算）
            if a is not None:
                prev_ki = (pd.Period(ki, "M") - 12).strftime("%Y-%m")
                pa = a[a["期"] == prev_ki]
                if len(pa):
                    pa = pa.iloc[-1]
                    if pa["売上高"] > 0 and np.isfinite(s):
                        rec["予想売上高成長率(%)"] = (s / pa["売上高"] - 1) * 100
                    if pa["営業利益"] > 0 and np.isfinite(op):
                        rec["予想営業増益率(%)"] = (op / pa["営業利益"] - 1) * 100
            # 修正（営業利益 → 経常利益 → 純利益 の順で予想がある項目を使う）
            for k in ("営業利益", "経常利益", "純利益"):
                if cur[k].notna().sum() >= 1:
                    seq = list(zip(cur["開示"], cur[k]))
                    rate, when = _last_change(seq)
                    first = cur[k].dropna().iloc[0]
                    now = cur[k].dropna().iloc[-1]
                    rec["業績予想修正率(%)"] = rate if when is not None else 0.0
                    if when is not None:
                        rec["予想修正からの日数"] = (today - when.normalize()).days
                        rec["予想修正の開示日"] = when.strftime("%Y-%m-%d")
                    if first > 0:
                        rec["期初予想比(%)"] = (now / first - 1) * 100
                    break
            if cur["配当"].notna().sum() >= 1:
                rate, when = _last_change(list(zip(cur["開示"], cur["配当"])))
                rec["配当予想修正率(%)"] = rate if when is not None else 0.0
        # 決算サプライズ: 直近の本決算 vs 発表前の最後の会社予想
        if a is not None and len(a):
            fa = a.iloc[-1]
            before = g[(g["期"] == fa["期"]) & (g["開示"] < fa["開示"])]
            for k in ("営業利益", "経常利益", "純利益"):
                b = before[k].dropna()
                if len(b) and b.iloc[-1] > 0 and np.isfinite(fa[k]):
                    rec["決算サプライズ(%)"] = (fa[k] / b.iloc[-1] - 1) * 100
                    break
        out[code] = rec

    ex = pd.DataFrame.from_dict(out, orient="index")
    idx = d["コード"].astype(str)
    for c in EXTRA_COLS:
        if c in ex.columns:
            v = idx.map(ex[c])
            d[c] = v.fillna("") if c == "予想修正の開示日" else pd.to_numeric(v, errors="coerce")
    up = (d["業績予想修正率(%)"] > 0).sum()
    dn = (d["業績予想修正率(%)"] < 0).sum()
    print(f"会社予想: 予想配当利回り {int(d['予想配当利回り(%)'].notna().sum()):,}銘柄／"
          f"最後の修正が上方 {up:,}・下方 {dn:,}／決算サプライズ {int(d['決算サプライズ(%)'].notna().sum()):,}銘柄"
          f"（J-Quants Free は12週遅れ）")
    return d
