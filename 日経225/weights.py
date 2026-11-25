#!/usr/bin/env python3
"""日経平均のウエート・寄与度・キャップ監視と、計算の検証（日経の公表値と一致するか）。

  日経平均 ＝ Σ（株価 × キャップ調整済み株価換算係数）÷ 除数
  ウエート ＝ 株価 × 係数 ÷ Σ（株価 × 係数）
  寄与度   ＝ 係数 × 株価の変化 ÷ 除数（日経平均を何円動かしたか）

株価は data/prices（分割調整済み）の終値。分割調整済みの株価に「いまの係数」を掛けるので、
過去にさかのぼった寄与度は分割の影響を受けない（キャップ調整比率の変更・銘柄入れ替えは反映しない近似）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from nk_common import F_DIVISOR, effective_factor, read_csv_str

CAP_LEVEL = 10.0     # キャップ水準（%）
CAP_RELEASE = 5.0    # キャップ調整比率を0.1引き上げる水準（%）
TOL = 0.0005         # 検証の許容誤差（0.05%）


def build(factors: pd.DataFrame, closes: pd.DataFrame) -> pd.DataFrame:
    """closes: 日付×コードの終値（分割調整済み）。戻り値: 日付×コードの「株価×係数」"""
    eff = {r.code: effective_factor(r.factor, r.cap_ratio) for r in factors.itertuples()}
    cols = [c for c in eff if c in closes.columns]
    adj = closes[cols].ffill() * pd.Series({c: eff[c] for c in cols})
    return adj


def divisor_on(day) -> tuple[float, str]:
    """day に有効な除数の公表値（公表日の翌営業日から有効）"""
    d = read_csv_str(F_DIVISOR)
    d = d[d["divisor"].notna()]
    d = d[pd.to_datetime(d["date"]) < pd.Timestamp(day)]
    if d.empty:
        return np.nan, ""
    r = d.iloc[-1]
    return float(r["divisor"]), str(r["date"])


def validate(adj: pd.DataFrame, nikkei: pd.Series, factors_asof: str, members: list[str]) -> dict:
    """係数表の検証。係数表の基準日以降の各日で Σ÷除数 と日経平均の終値を比べる"""
    out = {"ok": None, "rows": [], "message": "", "diagnosis": []}
    missing = [c for c in members if c not in adj.columns]
    if missing:
        out["message"] = f"株価が無い構成銘柄: {', '.join(missing)}"
    days = [d for d in adj.index if d >= pd.Timestamp(factors_asof) and d in nikkei.index]
    days = days[-10:]
    if not days or missing:
        out["ok"] = None if not missing else False
        return out
    errs = []
    for d in days:
        s = float(adj.loc[d].sum())
        D, ddate = divisor_on(d)
        calc = s / D if D > 0 else np.nan
        act = float(nikkei.loc[d])
        err = calc / act - 1 if act > 0 else np.nan
        out["rows"].append({"日付": d.strftime("%Y-%m-%d"), "日経平均(公表)": act, "計算値": calc,
                            "誤差(%)": err * 100, "除数(公表)": D, "除数の公表日": ddate,
                            "逆算した除数": s / act if act > 0 else np.nan})
        errs.append(abs(err))
    out["ok"] = bool(max(errs) <= TOL)
    last = out["rows"][-1]
    out["message"] = (f"直近{len(days)}日の誤差は最大 {max(errs) * 100:.3f}%"
                      + ("（一致）" if out["ok"] else "（ずれあり。下の推定原因を確認）"))
    if not out["ok"]:
        out["diagnosis"] = diagnose(adj, nikkei, days[-1], last["除数(公表)"])
    return out


def diagnose(adj: pd.DataFrame, nikkei: pd.Series, day, D: float) -> list[dict]:
    """ずれの原因の推定：Σの不足額（円）を、どの銘柄の係数を何倍にすれば説明できるか"""
    s = float(adj.loc[day].sum())
    gap = float(nikkei.loc[day]) * D - s          # 足りない「株価×係数」の合計
    cands = []
    for c in adj.columns:
        v = float(adj.loc[day, c])
        if not v > 0:
            continue
        for k in (2, 3, 4, 5, 6, 7, 8, 10, 15, 20, 25, 1 / 2, 1 / 3, 1 / 4, 1 / 5, 1 / 10, 0.9, 0.8):
            delta = v * (k - 1)
            if abs(delta - gap) <= max(abs(gap) * 0.02, 30):
                cands.append({"コード": c, "倍率": round(k, 4), "説明できる額": delta, "不足額": gap})
    cands.sort(key=lambda x: abs(x["説明できる額"] - x["不足額"]))
    return cands[:5]


def table(adj: pd.DataFrame, factors: pd.DataFrame, closes: pd.DataFrame, D: float) -> pd.DataFrame:
    """最新日のウエートと寄与度（1日・5日・20日・年初来）"""
    last = adj.index[-1]
    s = adj.loc[last]
    w = s / s.sum() * 100
    f = factors.set_index("code")

    def contrib(n):
        if len(adj) <= n:
            return pd.Series(np.nan, index=adj.columns)
        return (adj.iloc[-1] - adj.iloc[-1 - n]) / D

    ytd0 = adj[adj.index < pd.Timestamp(last.year, 1, 1)]
    ytd = (adj.iloc[-1] - ytd0.iloc[-1]) / D if len(ytd0) else pd.Series(np.nan, index=adj.columns)
    px = closes[adj.columns].ffill().iloc[-1]
    px1 = closes[adj.columns].ffill().iloc[-2] if len(closes) > 1 else px
    t = pd.DataFrame({
        "株価": px, "前日比(%)": (px / px1 - 1) * 100,
        "株価換算係数": f["factor"].reindex(adj.columns),
        "キャップ調整比率": f["cap_ratio"].reindex(adj.columns),
        "採用株価": s, "ウエート(%)": w,
        "寄与度1日(円)": contrib(1), "寄与度5日(円)": contrib(5), "寄与度20日(円)": contrib(20),
        "寄与度年初来(円)": ytd,
    })
    t["キャップ調整済み係数"] = [effective_factor(a, b) for a, b in zip(t["株価換算係数"], t["キャップ調整比率"].fillna(1.0))]
    t.index.name = "コード"
    return t.sort_values("ウエート(%)", ascending=False)


def cap_watch(w: pd.DataFrame, next_base: pd.Timestamp) -> pd.DataFrame:
    """キャップ監視：いまのウエートで次の基準日を迎えたらどうなるか（ルール：10%超で0.1引き下げ、5%未満で0.1引き上げ）"""
    rows = []
    for code, r in w.iterrows():
        cap = r["キャップ調整比率"]
        capped = pd.notna(cap) and abs(float(cap) - 1.0) > 1e-9
        wt = r["ウエート(%)"]
        if wt > CAP_LEVEL:
            new = round((float(cap) if capped else 1.0) - 0.1, 1)
            act = f"{'設定' if not capped else '引き下げ'} → {new}"
        elif capped and wt < CAP_RELEASE:
            new = round(float(cap) + 0.1, 1)
            act = "解除" if new >= 1.0 else f"引き上げ → {new}"
        elif capped:
            act = "据え置き"
        else:
            continue
        rows.append({"コード": code, "ウエート(%)": wt, "現在のキャップ調整比率": cap if capped else "未設定",
                     f"{next_base:%Y-%m-%d}の基準日に今の水準なら": act,
                     "10%までの余裕(%pt)": CAP_LEVEL - wt})
    return pd.DataFrame(rows)


def weight_history(adj: pd.DataFrame, top: list[str], days: int = 260) -> pd.DataFrame:
    a = adj.iloc[-days:]
    w = a.div(a.sum(axis=1), axis=0) * 100
    return w[top]


def sector_contrib(t: pd.DataFrame, sector_of: dict) -> pd.DataFrame:
    x = t.copy()
    x["セクター"] = [sector_of.get(c, "") for c in x.index]
    g = x.groupby("セクター")[["ウエート(%)", "寄与度1日(円)", "寄与度5日(円)", "寄与度20日(円)", "寄与度年初来(円)"]].sum()
    g["銘柄数"] = x.groupby("セクター").size()
    return g.sort_values("ウエート(%)", ascending=False)
