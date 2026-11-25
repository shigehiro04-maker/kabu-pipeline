#!/usr/bin/env python3
"""日経平均の構成銘柄選定基準を再現して、次回の定期見直しの採用・除外を予想する。

日経の選定基準（2026年10月1日適用）
  1. 東証プライムの銘柄を「過去5年間の売買代金」と「売買代金当たりの価格変動率（高値÷安値／売買代金）」
     で測った市場流動性の順に並べ、上位450銘柄を「高流動性銘柄群」とする
  2. 採用銘柄のうち流動性451位以下は除外（絶対除外）
  3. 未採用銘柄のうち流動性75位以内は採用（絶対採用）
  4. 高流動性銘柄群をセクターに分け、各セクターの半数を「採用妥当数」とする。
     過剰なセクターからは流動性の低い順に除外、不足するセクターには流動性の高い順に採用
  5. 同一セクター内で「既採用の最下位」と「未採用の最上位」の順位差が最大のセクターで入れ替え
  6. 入れ替えは1回の定期見直しで3銘柄まで（企業再編による入れ替えは別枠）

日経は2指標の合成方法や順位差の閾値を公表していないので、このプログラムでは
  ・売買代金＝終値×出来高 の1日平均（5年。上場1年以上の銘柄が対象）
  ・価格変動率＝(高値÷安値−1) の1日平均 ÷ 売買代金の1日平均（小さいほど流動性が高い）
  ・2指標の順位の和で並べ直したものを「流動性順位」
とした。2023〜2026年の8回の定期見直しで、絶対除外（451位以下）と絶対採用（75位以内）が
実際の発表とほぼ一致することを確かめている（backtest.py の「再現テスト」）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from nk_common import SECTOR6, SECTOR7, SEVEN_SECTOR_FROM, sector_of

HIGH_LIQ = 450        # 高流動性銘柄群
ABS_ADD = 75          # 絶対採用
MAX_SWAPS = 3         # 1回の定期見直しの入れ替え上限
MAX_PURE_SECTOR_SWAPS = 1   # 銘柄数合わせ以外の「セクター間の過不足調整」だけの入れ替え（実績は毎回0〜1組）
YEARS = 5
MIN_DAYS = 240        # 上場1年未満（240営業日未満）の銘柄は順位付けしない
GAP_DAYS = 60         # これより長く売買が途切れたら「再上場」とみなし、そこから数える


def review_schedule(today: pd.Timestamp) -> list[dict]:
    """今日以降の定期見直し（基準日・発表の目安・実施日）を2回分返す"""
    out = []
    for y in range(today.year, today.year + 2):
        for base_m, eff_m in ((1, 4), (7, 10)):
            base = pd.Timestamp(y, base_m, 1) + pd.offsets.MonthEnd(0)
            eff = first_business_day(y, eff_m)
            if eff > today:
                ann = eff - pd.offsets.BDay(18)   # 例年、実施日の約1か月前（3月初旬・9月初旬）に発表
                out.append({"base": base, "announce_est": ann, "effective": eff})
    return out[:2]


def first_business_day(y: int, m: int) -> pd.Timestamp:
    d = pd.Timestamp(y, m, 1)
    while d.weekday() >= 5:
        d += pd.Timedelta(days=1)
    return d


def liquidity_table(panel: pd.DataFrame, asof, universe: set | None = None,
                    years: int = YEARS, min_days: int = MIN_DAYS) -> pd.DataFrame:
    """asof（基準日）までの years 年で流動性順位を計算する。
    panel: date,code,high,low,close,volume,tv（nk_common.load_price_panel）
    universe: 順位付けの対象にする銘柄コード（東証プライム＋その時点の採用銘柄）"""
    asof = pd.Timestamp(asof)
    start = asof - pd.DateOffset(years=years)
    w = panel[(panel["date"] > start) & (panel["date"] <= asof)]
    if universe is not None:
        w = w[w["code"].isin(universe)]
    w = w[(w["volume"] > 0) & (w["low"] > 0) & (w["high"] >= w["low"])]
    if w.empty:
        return pd.DataFrame()
    # 再上場（長い空白）の後から数える
    w = w.sort_values(["code", "date"])
    gap = w.groupby("code")["date"].diff().dt.days.fillna(0)
    seg = (gap > GAP_DAYS).groupby(w["code"]).cumsum()
    last_seg = seg.groupby(w["code"]).transform("max")
    w = w[seg == last_seg]
    hl = w["high"] / w["low"] - 1.0
    g = w.assign(hl=hl).groupby("code")
    t = pd.DataFrame({
        "days": g.size(),
        "first": g["date"].min(),
        "last": g["date"].max(),
        "tv_mean": g["tv"].mean(),
        "hl_mean": g["hl"].mean(),
    })
    # 基準日の近くまで売買のある銘柄だけ（上場廃止・売買停止を除く）
    t = t[t["last"] >= asof - pd.Timedelta(days=10)]
    t["eligible"] = t["days"] >= min_days
    e = t[t["eligible"]].copy()
    e["impact"] = e["hl_mean"] / e["tv_mean"]
    e["rank_tv"] = e["tv_mean"].rank(ascending=False, method="min")
    e["rank_impact"] = e["impact"].rank(ascending=True, method="min")
    e["score"] = e["rank_tv"] + e["rank_impact"]
    e["liq_rank"] = e["score"].rank(method="first").astype(int)
    t = t.join(e[["impact", "rank_tv", "rank_impact", "score", "liq_rank"]])
    return t.sort_values("liq_rank", na_position="last")


@dataclass
class Decision:
    code: str
    action: str          # 採用 / 除外
    rule: str            # 絶対採用・絶対除外・セクター調整・同一セクター入替・銘柄数調整
    sector: str
    liq_rank: float
    confidence: str      # 高・中・低
    note: str = ""


@dataclass
class Simulation:
    base: pd.Timestamp
    effective: pd.Timestamp
    decisions: list = field(default_factory=list)
    sector_table: pd.DataFrame | None = None
    ranks: pd.DataFrame | None = None
    add_candidates: pd.DataFrame | None = None
    del_candidates: pd.DataFrame | None = None


def simulate(liq: pd.DataFrame, members: set, industry: dict, effective,
             excluded: set | None = None, passed_over: set | None = None,
             max_swaps: int = MAX_SWAPS) -> Simulation:
    """定期見直しを1回シミュレーションする。
    liq: liquidity_table の結果、members: 見直し前の採用銘柄、industry: code→日経36業種
    excluded: 採用しない銘柄（特別注意銘柄など。exclude.csv）
    passed_over: 前回の見直しでこのプログラムの順位では75位以内だったのに採用されなかった銘柄。
                 日経の実際の流動性指標では基準に届いていない可能性が高いので「絶対採用」扱いにしない"""
    effective = pd.Timestamp(effective)
    eff_s = effective.strftime("%Y-%m-%d")
    excluded = excluded or set()
    passed_over = passed_over or set()
    sectors = SECTOR7 if eff_s >= SEVEN_SECTOR_FROM else SECTOR6
    r = liq.copy()
    r["code"] = r.index.astype(str)
    r["member"] = r["code"].isin(members)
    r["industry"] = r["code"].map(lambda c: industry.get(c, ""))
    r["sector"] = [sector_of(i, c, eff_s) for i, c in zip(r["industry"], r["code"])]
    ranked = r[r["liq_rank"].notna()]
    H = ranked[ranked["liq_rank"] <= HIGH_LIQ]

    # 採用妥当数（高流動性銘柄群のセクター別銘柄数の半数）
    target = H.groupby("sector").size().reindex(sectors, fill_value=0) / 2.0

    cur = set(members)
    rank_of = r["liq_rank"].to_dict()
    sec_of = r["sector"].to_dict()
    for c in cur:
        if c not in sec_of:
            sec_of[c] = sector_of(industry.get(c, ""), c, eff_s)
    sim = Simulation(base=None, effective=effective)
    dec = []

    def rk(c):
        v = rank_of.get(c, np.nan)
        return 10_000 if pd.isna(v) else v

    # 1) 絶対除外：451位以下。順位が付かない銘柄（上場1年未満の持ち株会社など、データ不足）は対象にしない
    must_del = sorted([c for c in cur if HIGH_LIQ < rank_of.get(c, np.nan) < 10_000], key=rk, reverse=True)
    # 2) 絶対採用：未採用で75位以内
    must_add = [c for c in ranked[(ranked["liq_rank"] <= ABS_ADD) & ~ranked["member"]]["code"]
                if c not in excluded and c not in passed_over]

    # 上限3銘柄。絶対採用・絶対除外を優先し、余った枠でセクター調整
    adds, dels = [], []
    for c in must_del[:max_swaps]:
        dels.append(c)
        conf = "高" if rank_of.get(c, 0) >= HIGH_LIQ + 15 else "中"
        dec.append(Decision(c, "除外", "絶対除外（流動性451位以下）", sec_of.get(c, ""), rank_of.get(c, np.nan), conf,
                            "" if conf == "高" else "450位の境界に近い"))
    for c in must_add[:max_swaps]:
        adds.append(c)
        conf = "高" if rank_of.get(c, 99) <= ABS_ADD - 15 else "中"
        dec.append(Decision(c, "採用", "絶対採用（流動性75位以内）", sec_of.get(c, ""), rank_of.get(c, np.nan), conf,
                            "" if conf == "高" else "75位の境界に近い（日経の実際の指標とのずれで外れることがある）"))

    def counts(s):
        return pd.Series([sec_of.get(c, "") for c in s]).value_counts().reindex(sectors, fill_value=0)

    def pick_add(sector_order):
        for s in sector_order:
            cand = ranked[(ranked["sector"] == s) & ~ranked["code"].isin(cur | set(adds))
                          & (ranked["liq_rank"] <= HIGH_LIQ) & ~ranked["code"].isin(excluded)]
            if len(cand):
                return cand.iloc[0]["code"]
        return None

    def pick_del(sector_order):
        for s in sector_order:
            mem = [c for c in cur if sec_of.get(c) == s and c not in dels]
            if mem:
                return max(mem, key=rk)
        return None

    # 3) 銘柄数を225にそろえる（採用と除外の数の差をセクターの過不足で埋める）
    while len(adds) < len(dels) and len(adds) < max_swaps:
        now = counts((cur - set(dels)) | set(adds))
        gap = (now - target).sort_values()          # 不足（マイナス）が大きい順
        c = pick_add(list(gap.index))
        if c is None:
            break
        adds.append(c)
        dec.append(Decision(c, "採用", "セクター調整（不足セクターの最上位）", sec_of[c], rank_of[c], "中",
                            f"{sec_of[c]}：採用妥当数 {target[sec_of[c]]:.1f}・現在 {now[sec_of[c]]}"))
    while len(dels) < len(adds) and len(dels) < max_swaps:
        now = counts((cur - set(dels)) | set(adds))
        gap = (now - target).sort_values(ascending=False)   # 過剰が大きい順
        c = pick_del(list(gap.index))
        if c is None:
            break
        dels.append(c)
        dec.append(Decision(c, "除外", "セクター調整（過剰セクターの最下位）", sec_of.get(c, ""), rank_of.get(c, np.nan), "中",
                            f"{sec_of.get(c, '')}：採用妥当数 {target.get(sec_of.get(c, ''), 0):.1f}・現在 {now.get(sec_of.get(c, ''), 0)}"))

    # 4) 余った枠で、セクター間の過不足調整（過剰1以上 かつ 不足1以上のときだけ）。
    #    2023〜2026年の実績では、純粋なセクター調整の入れ替えは1回の見直しで最大1組だったので1組に限る
    pure = 0
    while len(adds) < max_swaps and len(dels) < max_swaps and pure < MAX_PURE_SECTOR_SWAPS:
        pure += 1
        now = counts((cur - set(dels)) | set(adds))
        diff = now - target
        over = diff[diff >= 1.0].sort_values(ascending=False)
        under = diff[diff <= -1.0].sort_values()
        if over.empty or under.empty:
            break
        a = pick_add(list(under.index))
        d = pick_del(list(over.index))
        if a is None or d is None:
            break
        adds.append(a)
        dels.append(d)
        dec.append(Decision(a, "採用", "セクター調整（不足セクターの最上位）", sec_of[a], rank_of[a], "中",
                            f"{sec_of[a]}：採用妥当数 {target[sec_of[a]]:.1f}・現在 {now[sec_of[a]]}"))
        dec.append(Decision(d, "除外", "セクター調整（過剰セクターの最下位）", sec_of.get(d, ""), rank_of.get(d, np.nan), "中",
                            f"{sec_of.get(d, '')}：採用妥当数 {target.get(sec_of.get(d, ''), 0):.1f}・現在 {now.get(sec_of.get(d, ''), 0)}"))

    # 5) 同一セクター内の入れ替え（2026年10月の新基準）。順位差が最大のセクターで1組だけ候補に挙げる
    if eff_s >= SEVEN_SECTOR_FROM and len(adds) < max_swaps:
        best = None
        for s in sectors:
            mem = [c for c in cur if sec_of.get(c) == s and c not in dels]
            non = ranked[(ranked["sector"] == s) & ~ranked["code"].isin(cur | set(adds))
                         & ~ranked["code"].isin(excluded | passed_over)]
            if not mem or non.empty:
                continue
            worst = max(mem, key=rk)
            top = non.iloc[0]["code"]
            gap = rk(worst) - rk(top)
            if gap > 0 and (best is None or gap > best[0]):
                best = (gap, s, top, worst)
        if best is not None and best[0] >= 150:
            gap, s, top, worst = best
            adds.append(top)
            dels.append(worst)
            dec.append(Decision(top, "採用", "同一セクター内の入れ替え", s, rk(top), "低",
                                f"{s}：既採用の最下位 {worst}（{rk(worst):.0f}位）と順位差 {gap:.0f}"))
            dec.append(Decision(worst, "除外", "同一セクター内の入れ替え", s, rk(worst), "低",
                                f"{s}：未採用の最上位 {top}（{rk(top):.0f}位）と順位差 {gap:.0f}"))

    sim.decisions = dec
    after = (cur - set(dels)) | set(adds)
    st = pd.DataFrame({
        "高流動性銘柄数": H.groupby("sector").size().reindex(sectors, fill_value=0),
        "採用妥当数": target,
        "見直し前": counts(cur),
        "予想後": counts(after),
    })
    st["過不足(見直し前)"] = st["見直し前"] - st["採用妥当数"]
    st["過不足(予想後)"] = st["予想後"] - st["採用妥当数"]
    sim.sector_table = st
    sim.ranks = r

    # 候補表（予想に入らなかったものも含めて、近い順に）
    non = ranked[~ranked["member"] & ~ranked["code"].isin(excluded)].copy()
    sec_gap = (st["見直し前"] - st["採用妥当数"]).to_dict()
    non["セクター過不足"] = non["sector"].map(sec_gap)
    non["セクター内順位"] = non.groupby("sector")["liq_rank"].rank(method="first")
    non["予想"] = non["code"].isin(adds)
    sim.add_candidates = non[(non["liq_rank"] <= 150) | ((non["セクター内順位"] <= 3) & (non["liq_rank"] <= HIGH_LIQ))]
    mem = r[r["code"].isin(cur)].copy()
    mem["liq_rank"] = mem["liq_rank"].fillna(10_000)
    mem["セクター過不足"] = mem["sector"].map(sec_gap)
    mem["セクター内順位(下から)"] = mem.groupby("sector")["liq_rank"].rank(method="first", ascending=False)
    mem["予想"] = mem["code"].isin(dels)
    sim.del_candidates = mem[(mem["liq_rank"] > 350) | (mem["セクター内順位(下から)"] <= 2)].sort_values("liq_rank", ascending=False)
    return sim


def decisions_frame(sim: Simulation, names: dict) -> pd.DataFrame:
    rows = [{"区分": d.action, "コード": d.code, "銘柄名": names.get(d.code, ""), "セクター": d.sector,
             "流動性順位": d.liq_rank, "根拠": d.rule, "確度": d.confidence, "補足": d.note}
            for d in sim.decisions]
    return pd.DataFrame(rows, columns=["区分", "コード", "銘柄名", "セクター", "流動性順位", "根拠", "確度", "補足"])
