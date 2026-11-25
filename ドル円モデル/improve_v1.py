#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
 improve.py — 的中率を上げるための、正直な探索
================================================================================

  python3 improve.py --csv data.csv

--------------------------------------------------------------------------------
 なぜ「シグナルを足して的中率を見る」だけでは駄目なのか
--------------------------------------------------------------------------------
 候補をたくさん試して一番良いものを選ぶと、その数字は必ず良く見えます。
 20個試せば、たまたま55%を出すものが1つくらい出るからです（多重比較）。
 それを「改善した」と言うのは自分を騙しているだけです。

 そこでこのスクリプトは、数字を出す前に検証の枠組みを固めています。

   1. ウォークフォワード検証
      係数は「その時点までのデータだけ」で推定し、次の期間を予測します。
      未来を一度も見ないので、先読みバイアスが入りません。

   2. 重複しないサンプルで有意性を測る
      20営業日先を毎日予測すると、隣り合う予測は19日分ぶん中身が同じです。
      これを独立扱いすると有意性が19倍に水増しされます。
      そこで的中率の検定は、h日ごとに間引いた重複なしサンプルで行います。

   3. 多重比較の申告
      試した候補の数を必ず表示し、Bonferroni補正後の基準も併記します。

   4. 取引コストを引く
      的中率が上がってもコスト後で負けるなら、改善ではありません。

--------------------------------------------------------------------------------
 試す候補（すべて経済的な理由があるものだけ。総当たりはしません）
--------------------------------------------------------------------------------
   value    乖離の平均回帰      … 行き過ぎは戻る
   carry    金利差そのもの      … 金利差が正なら円安方向にドリフトする
   mom      トレンド            … 為替で最も頑健とされるアノマリー
   dspread  金利差の変化        … 「水準ではなく変化」というモデルの主張そのもの
   合成     value+mom / carry+mom / 全部
   フィルタ VIXが高いときは張らない
================================================================================
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import usdjpy_model as M

HORIZONS = [1, 5, 10, 20, 60]
COST_BP = 1.0          # 往復の取引コスト（bp）。ドル円のスプレッド0.2〜0.5銭相当
BURN_IN = 500          # 最初の推定に使う最低行数


# ==============================================================================
# 統計（scipy を使わずに済ませる）
# ==============================================================================

def binom_p(hits: int, n: int, p0: float = 0.5) -> float:
    """的中率が p0 と違うと言えるか（両側）。正規近似、n>30 で十分。"""
    if n < 10:
        return float("nan")
    se = math.sqrt(p0 * (1 - p0) / n)
    z = (hits / n - p0) / se
    # 標準正規の両側p値
    return math.erfc(abs(z) / math.sqrt(2))


def sharpe(returns: np.ndarray, periods_per_year: float) -> float:
    r = returns[np.isfinite(returns)]
    if len(r) < 10 or r.std(ddof=1) == 0:
        return float("nan")
    return r.mean() / r.std(ddof=1) * math.sqrt(periods_per_year)


# ==============================================================================
# シグナル
# ==============================================================================

def build_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    各シグナルは「＋なら円安（ドル買い）、−なら円高（ドル売り）」の向きに揃える。
    すべて時点tまでの情報だけで作る（先読みなし）。
    """
    s = pd.DataFrame(index=df.index)
    px = df["usdjpy"]

    # value: 乖離の平均回帰。zが＋（円安に行き過ぎ）なら、これから下がると読む
    s["value"] = -df["z"]

    # carry: 金利差が大きいほど、円を売ってドルを持つ動機が強い
    s["carry"] = df["spread2"]

    # momentum: 過去N営業日のリターン（為替で最も頑健とされるアノマリー）
    for n in (20, 60, 120):
        s[f"mom{n}"] = px.pct_change(n) * 100

    # 金利差モメンタム: 「水準ではなく変化」というこのモデルの主張そのもの
    for n in (5, 20):
        s[f"dspread{n}"] = df["spread2"].diff(n)

    # 平均を引いた版。carry も value も、この期間は符号が固定されてしまい
    # 「常にドル買い」と同じになる。過去平均との差にすれば符号が変わるので、
    # 本当に情報があるのかを切り分けられる。
    s["carry_相対"] = df["spread2"] - df["spread2"].expanding(250).mean()
    s["mom60_相対"] = s["mom60"] - s["mom60"].expanding(250).mean()

    return s


def zscore_expanding(x: pd.Series, min_periods: int = 250) -> pd.Series:
    """その時点までの平均・標準偏差で標準化する（未来を使わない）。"""
    mu = x.expanding(min_periods=min_periods).mean()
    sd = x.expanding(min_periods=min_periods).std()
    return (x - mu) / sd


# ==============================================================================
# 検証
# ==============================================================================

def evaluate(sig: pd.Series, fwd: pd.Series, h: int, cost_bp: float = COST_BP,
             base_rate: float = 0.5) -> dict:
    """
    シグナルの符号で方向を当てにいったとき、どうだったかを測る。

    重複しないサンプル（h日ごとに間引く）だけで的中率と有意性を出す。
    毎日の予測は中身がほとんど重なっていて、独立ではないため。
    """
    d = pd.concat([sig.rename("s"), fwd.rename("f")], axis=1).dropna()
    if len(d) < BURN_IN:
        return {"ok": False, "n": len(d)}

    # 重複なしサンプル: h営業日ごとに1点だけ拾う
    nol = d.iloc[::h]
    pos = np.sign(nol["s"].values)
    ret = nol["f"].values
    live = pos != 0
    pos, ret = pos[live], ret[live]
    if len(pos) < 20:
        return {"ok": False, "n": len(pos)}

    hits = int((np.sign(ret) == pos).sum())
    n = len(pos)
    hit = hits / n

    # シグナルが実際に向きを変えているか。ずっと同じ符号なら、それは
    # 「シグナル」ではなく固定ポジション（＝ただのバイ・アンド・ホールド）。
    flip = float(np.mean(pos != np.roll(pos, 1))) if n > 1 else 0.0
    long_share = float(np.mean(pos > 0))

    # 戦略リターン（コスト差引後）。ポジションを取り直すたびにコストがかかる
    strat = pos * ret - cost_bp / 100.0
    ppy = 252.0 / h

    return {
        "ok": True, "n": n, "hits": hits, "hit_rate": hit,
        "flip": flip, "long_share": long_share,
        "edge": hit - base_rate,
        # 帰無仮説は「コイン投げ(50%)」ではなく「常にドル買いした場合の勝率」。
        # 上昇トレンドの期間では、何もしなくても勝率がベースレートまで出るため。
        "p": binom_p(hits, n, base_rate),
        "mean": float(np.mean(strat)),
        "sharpe": sharpe(strat, ppy),
        "total": float(np.sum(strat)),
    }


def walk_forward_combo(df: pd.DataFrame, sig: pd.DataFrame, cols: list[str],
                       fwd: pd.Series, h: int) -> pd.Series:
    """
    複数シグナルを回帰で合成する。係数はその時点までのデータだけで推定し、
    次の1点を予測する（ウォークフォワード）。未来は一切使わない。
    """
    X = sig[cols].apply(zscore_expanding)
    d = pd.concat([X, fwd.rename("y")], axis=1)
    pred = pd.Series(index=df.index, dtype=float)

    valid = d.dropna()
    if len(valid) < BURN_IN + h + 50:
        return pred

    idx = valid.index
    for i in range(BURN_IN, len(idx)):
        # 学習に使えるのは「予測時点の h 日前まで」に結果が出ている分だけ。
        # ここを t までにすると、まだ判明していない答えを使うことになる。
        train = valid.iloc[:max(0, i - h)]
        if len(train) < BURN_IN:
            continue
        A = np.column_stack([np.ones(len(train))] + [train[c].values for c in cols])
        try:
            coef, *_ = np.linalg.lstsq(A, train["y"].values, rcond=None)
        except np.linalg.LinAlgError:
            continue
        row = valid.iloc[i]
        pred.loc[idx[i]] = coef[0] + sum(c * row[k] for c, k in zip(coef[1:], cols))
    return pred


def run(df: pd.DataFrame, cost_bp: float) -> tuple[pd.DataFrame, list]:
    rows, notes = [], []

    for h in HORIZONS:
        fwd = (df["usdjpy"].shift(-h) / df["usdjpy"] - 1.0) * 100.0
        sig = build_signals(df)

        # ベースレート = 「常にドル買い」で持っていた場合の勝率。
        # この期間のドル円は一貫して上昇したので、これが 60〜65% になる。
        # 予測力の有無は、50% ではなくこの数字を超えられるかで判定する。
        nol_fwd = fwd.dropna().iloc[::h]
        base = float((nol_fwd > 0).mean())
        rows.append({"horizon": h, "signal": "◆常にドル買い（基準）", "type": "基準",
                     **evaluate(pd.Series(1.0, index=df.index), fwd, h, cost_bp, 0.5)})
        rows[-1]["edge"] = 0.0
        rows[-1]["p"] = float("nan")

        # --- 単独シグナル ------------------------------------------------------
        singles = ["value", "carry", "carry_相対", "mom20", "mom60", "mom60_相対",
                   "mom120", "dspread5", "dspread20"]
        for name in singles:
            r = evaluate(sig[name], fwd, h, cost_bp, base)
            if r["ok"]:
                rows.append({"horizon": h, "signal": name, "type": "単独", **r})

        # --- 合成（ウォークフォワード回帰） ------------------------------------
        combos = {
            "value+mom60": ["value", "mom60"],
            "carry+mom60": ["carry", "mom60"],
            "全部": ["value", "carry", "mom60", "dspread20"],
        }
        for name, cols in combos.items():
            p = walk_forward_combo(df, sig, cols, fwd, h)
            r = evaluate(p, fwd, h, cost_bp, base)
            if r["ok"]:
                rows.append({"horizon": h, "signal": name, "type": "合成WF", **r})

        # --- VIXフィルター（落ち着いている時だけ張る） --------------------------
        if df["vix"].notna().sum() > 500:
            calm = df["vix"] < df["vix"].expanding(250).quantile(0.75)
            for b in ["mom60", "value"]:
                f = sig[b].where(calm, 0.0)
                r = evaluate(f, fwd, h, cost_bp, base)
                if r["ok"]:
                    rows.append({"horizon": h, "signal": f"{b}+VIX静穏時のみ",
                                 "type": "フィルタ", **r})

    res = pd.DataFrame(rows)
    return res, notes


# ==============================================================================
# 出力
# ==============================================================================

def report(res: pd.DataFrame, df: pd.DataFrame, cost_bp: float) -> str:
    L = []
    A = L.append
    n_tested = len(res)
    alpha_bonf = 0.05 / max(n_tested, 1)

    A("=" * 84)
    A(" 的中率を上げられるか — ウォークフォワード検証")
    A("=" * 84)
    A(f" 期間        : {df['date'].iloc[0]:%Y-%m-%d} 〜 {df['date'].iloc[-1]:%Y-%m-%d}"
      f"  ({len(df)}営業日)")
    A(f" 取引コスト  : 往復 {cost_bp:.1f}bp を毎回差し引き")
    A(f" 試した候補  : {n_tested} 通り")
    A(f" 有意水準    : 素の5% / 多重比較を補正すると {alpha_bonf*100:.3f}%")
    A("")
    A(" ※ 的中率は「重複しないサンプル」で計算しています。20日先を毎日予測すると")
    A("    隣同士が19日ぶん重なるため、そのまま数えると有意性が水増しされます。")
    A("")

    for h in sorted(res["horizon"].unique()):
        sub = res[res["horizon"] == h].sort_values("hit_rate", ascending=False)
        A("─" * 84)
        A(f" {h}営業日先を予測")
        A("─" * 84)
        A(f"  {M.wpad('シグナル',22)}{M.wpad('種別',10)}{'的中率':>7}{'基準差':>8}"
          f"{'反転率':>7}{'n':>6}{'p値':>8}{'Sharpe':>8}{'累計%':>8}")
        for _, r in sub.iterrows():
            mark = ""
            if np.isfinite(r["p"]):
                if r["p"] < alpha_bonf and r["edge"] > 0:
                    mark = " ★"      # 基準を、多重比較の補正後も有意に上回る
                elif r["p"] < 0.05 and r["edge"] > 0:
                    mark = " †"      # 素では有意だが、補正すると消える
            flag = ""
            if r["flip"] < 0.02:
                flag = " ◇固定"      # 符号がほぼ変わらない＝実質バイ&ホールド
            pv = "  —  " if not np.isfinite(r["p"]) else f"{r['p']:.3f}"
            A(f"  {M.wpad(str(r['signal']),22)}{M.wpad(str(r['type']),10)}"
              f"{r['hit_rate']*100:>6.1f}%{r['edge']*100:>+7.1f}pt"
              f"{r['flip']*100:>6.0f}%{r['n']:>6.0f}{pv:>8}"
              f"{r['sharpe']:>8.2f}{r['total']:>8.1f}{mark}{flag}")
        A("")

    # ---- 総括 ----------------------------------------------------------------
    A("=" * 84)
    A(" 結論")
    A("=" * 84)

    real = res[(res["type"] != "基準") & (res["flip"] >= 0.02)]
    strong = real[(real["p"] < alpha_bonf) & (real["edge"] > 0)].sort_values("sharpe", ascending=False)
    weak = real[(real["p"] < 0.05) & (real["p"] >= alpha_bonf) & (real["edge"] > 0)]
    fixed = res[(res["type"] != "基準") & (res["flip"] < 0.02)]

    A("  【最重要】「常にドル買い」が基準です。")
    A("")
    for h in sorted(res["horizon"].unique()):
        b = res[(res["horizon"] == h) & (res["type"] == "基準")]
        if len(b):
            A(f"    {h:>3}日先 : 何も考えずドル買いを持っていただけで "
              f"{b.iloc[0]['hit_rate']*100:.1f}% 当たっていました")
    A("")
    A("    この期間のドル円は115円→160円（+38.8%）と一貫して上がったからです。")
    A("    したがって「的中率60%」は予測力ではありません。上の表の的中率は")
    A("    この基準と比べてください（基準差の列）。")
    if len(fixed):
        A("")
        A(f"  ◇固定 が {len(fixed)} 件。符号がほとんど変わらないシグナルで、")
        A("     実質「常にドル買い」と同じものです。数字が良く見えても中身は基準です。")
    A("")

    if len(strong) == 0:
        A("  ★（基準を、多重比較の補正後も有意に上回る）は1つもありませんでした。")
        A("")
        A("  つまり、ここで試した範囲では「基準（常にドル買い）を超えた」と")
        A("  言える候補はありませんでした。表で高く見える数字は、")
        A("  (a) 上昇トレンドのベースレート、または")
        A(f"  (b) {n_tested}通り試したことによる見かけ上のばらつき、のどちらかです。")
    else:
        A(f"  多重比較を補正しても有意だった候補が {len(strong)} 件あります:")
        A("")
        for _, r in strong.head(6).iterrows():
            A(f"    {r['horizon']:>3}日先  {M.wpad(r['signal'], 22)}"
              f"的中率 {r['hit_rate']*100:.1f}%  Sharpe {r['sharpe']:.2f}"
              f"  n={r['n']:.0f}  p={r['p']:.4f}")
        A("")
        A("  ただし、これでも「使える」と決めつけないでください。次を確認します:")
        A("    ・n が小さくないか（30未満なら偶然の可能性が高い）")
        A("    ・Sharpe が 0.3 未満なら、実運用のブレに埋もれます")
        A("    ・同じ系統のシグナルが複数上位に来ているか（1つだけなら疑わしい）")

    if len(weak):
        A("")
        A(f"  † （素の5%では有意だが補正すると消える）が {len(weak)} 件。")
        A("     これらは「見込みあり」ではなく「区別がつかない」と読むのが正しいです。")

    best_h = res.groupby("horizon")["hit_rate"].max()
    A("")
    A("  期間別の最高的中率:")
    for h, v in best_h.items():
        A(f"    {h:>3}営業日先 : {v*100:.1f}%")

    A("")
    A("─" * 84)
    A(" 的中率を上げる前に知っておくべきこと")
    A("─" * 84)
    A("  ・的中率と儲けは別物です。的中率52%でも、外したときの損が大きければ負けます。")
    A("    逆に的中率45%でも、当たったときに大きく取れれば勝てます。")
    A("    表のSharpeと累計%のほうが、的中率より実態に近い指標です。")
    A("  ・為替でコスト後に安定して55%を超えるのは、極めて難しいことが知られています。")
    A("    60%や70%を謳うものを見たら、まず先読みか多重比較を疑ってください。")
    A("  ・ここで有意に見えたものも、次の1年でそのまま効く保証はありません。")
    A("    実運用の前に、必ず紙の上で数か月追いかけてください。")
    A("")
    A("=" * 84)
    A(" 本ツールは教育・分析目的であり、投資助言ではありません。")
    A("=" * 84)
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="的中率を上げられるかの検証")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--cost-bp", type=float, default=COST_BP,
                    help=f"往復の取引コスト(bp)。既定 {COST_BP}")
    ap.add_argument("--out", default="output")
    args = ap.parse_args()

    df = M.fair_value(M.add_features(M.load_data(args.csv)))
    res, _ = run(df, args.cost_bp)
    if res.empty:
        raise SystemExit("[エラー] 検証できる候補がありませんでした。データ量を確認してください。")

    txt = report(res, df, args.cost_bp)
    print(txt)

    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    (out / "improve_report.txt").write_text(txt, encoding="utf-8")
    res.sort_values(["horizon", "hit_rate"], ascending=[True, False]) \
       .to_csv(out / "improve_results.csv", index=False, encoding="utf-8-sig")
    print(f"\n[出力] {out.resolve()} に improve_report.txt / improve_results.csv")


if __name__ == "__main__":
    main()
