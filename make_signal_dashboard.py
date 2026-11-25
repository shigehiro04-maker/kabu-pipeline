#!/usr/bin/env python3
"""テクニカル／ファンダメンタルの売買シグナルを全銘柄で計算し、
速度メーター型のダッシュボード（data/charts/signals.html）を作る。

    python3 make_signal_dashboard.py            # 全銘柄
    python3 make_signal_dashboard.py --days 60  # メーター推移の日数（既定60）

入力:
    data/prices/<code>.csv                       日足（分割・配当調整済み）
    fundamentals/analysis/スコア一覧.csv           analyze_fundamentals.py の出力
    tickers/tse_tickers.csv, tickers/sectors.csv  銘柄名・市場・業種
出力:
    data/charts/signals.html                     ダッシュボード本体
    fundamentals/analysis/シグナル一覧.csv          全銘柄のスコアと内訳

スコアはどちらも −100（避ける）〜 +100（良好）。
各指標を −1〜+1 に換算し、重みを掛けて足し合わせ、100倍したもの。
値が無い指標は除いて重みを配り直す（ファンダは3指標以上そろわない銘柄は出さない）。
"""
import os, sys, json, glob, datetime, math
import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
PRICES = os.path.join(BASE, "data", "prices")
SCORE = os.path.join(BASE, "fundamentals", "analysis", "スコア一覧.csv")
TICKERS = os.path.join(BASE, "tickers", "tse_tickers.csv")
SECTORS = os.path.join(BASE, "tickers", "sectors.csv")
OUT_HTML = os.path.join(BASE, "data", "charts", "signals.html")
# 銘柄ごとのチャート用データ（ローソク足・一目・出来高）。開いた銘柄の分だけ読み込むので本体は重くならない
OUT_SIG = os.path.join(BASE, "data", "charts", "sig")
CHART_DAYS = 100   # 売買の目安チャートに出す営業日数
OUT_CSV = os.path.join(BASE, "fundamentals", "analysis", "シグナル一覧.csv")
LOG = os.path.join(BASE, "logs", "signals.log")

# ---------------------------------------------------------------- 重み
# 2026-10-13 見直し（シグナル再評価_20261013/）。2017-2026年の過去検証で、旧式（移動平均・MACD・一目 各20、
# RSI・ボリンジャー 各15、出来高10）は先のリターンをほぼ当てなかった（20日先IC 0.002）。
# 当たっていた「52週高値への近さ」と「値動きの小ささ」を足し、効かなかった指標の重みを下げた（同IC 0.046、3期間ともプラス）。
TECH_W = {"hi52": .25, "lv": .25, "ma": .15, "ichi": .10, "macd": .05, "rsi": .05, "bb": .05, "vol": .10}
# ファンダは2022-2026年の検証で割安（特にPBR・EV/EBITDA）だけが効き、収益性・安全性は効かないかマイナスだったので、割安度に寄せた
FUND_W = {"val": .55, "prof": .10, "grow": .05, "safe": .10, "fs": .10, "cash": .10}
# テクニカルは順張り（移動平均・MACD・一目）と逆張り（RSI・ボリンジャー）が打ち消し合うため、
# 重み付き平均のままだと振れ幅が小さい（全銘柄の5〜95%点がおよそ−22〜+28）。
# メーターの幅を使い切るよう2倍して表示する（±100で頭打ち）。
# 新しい式では全銘柄の5〜95%点がおよそ−60〜+60になるので、伸ばしはしない
TECH_GAIN = 1.0
# 判定の区切り [良好, やや良好, 弱い, 避ける] の境目。
#   ファンダは絶対評価がベースなので、市場全体が割安なら良好側に寄る。
#   過去検証では効き目が下位側に集中していた（上位はほぼ市場並み）。下位約2割が「避ける」に入るよう区切る
LEVELS = {"t": [40, 15, -15, -30], "f": [45, 20, -5, -20],
          "tr": [50, 20, -20, -50],
          # オシレーター系は RSI 30/70・ボリンジャー±2σ で±100。±70≒RSI 36/64かつ%B 15/85%あたり
          "os": [70, 35, -35, -70],
          # 騰落レシオは 100−(レシオ−100)×2 をスコアにしてメーターに載せる（150%→−100、50%→+100）。
          # 70%以下で底値圏（+60）、80%以下（+40）、120%以上（−40）、130%以上で過熱（−60）
          "ad": [60, 40, -40, -60]}
# テクニカルの内訳を2つに分けて見る（合計のテクニカルスコアとは別に表示）
#   トレンド系: 移動平均・MACD・一目均衡表・出来高（出来高は上昇／下落の勢いの裏付けとしてこちらに入れる）
#   オシレーター系: RSI・ボリンジャー（売られすぎ＝買い、買われすぎ＝売りの逆張り）
TREND_KEYS = ["ma", "macd", "ichi", "vol"]
OSC_KEYS = ["rsi", "bb"]
# 「強い買い」は過去検証で裏付けが無かったため使わない。下位（避ける）を重く見る呼び方にした（2026-10-13）
NAMES = ["良好", "やや良好", "中立", "弱い", "避ける"]
# トレンド系・オシレーター系は売買ではなく状態で呼ぶ（スコアの向きは同じ：プラス＝買い側）
TREND_NAMES = ["強い上昇トレンド", "上昇トレンド", "横ばい", "下降トレンド", "強い下降トレンド"]
OSC_NAMES = ["強く売られすぎ", "売られすぎ", "中立", "買われすぎ", "強く買われすぎ"]


def label(s, kind):
    if s is None or (isinstance(s, float) and math.isnan(s)):
        return None
    sb, b, se, ss = LEVELS[kind]
    nm = TREND_NAMES if kind == "tr" else OSC_NAMES if kind == "os" else NAMES
    return nm[0] if s >= sb else nm[1] if s >= b else nm[2] if s > se else nm[3] if s > ss else nm[4]


def log(msg):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    line = f"[{datetime.datetime.now():%F %T}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def r(x, n=2):
    if x is None:
        return None
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) or math.isinf(x) else round(x, n)


def sig(x):
    """NaN を保ったまま符号を返す"""
    return np.sign(x)


# ---------------------------------------------------------------- テクニカル
def technical(df, days):
    """日足DataFrame（date,open,high,low,close,volume）から、各日のスコアと最新の内訳を返す。"""
    c = df["close"].astype(float)
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    v = df["volume"].astype(float)
    n = len(c)

    # 値動きの物差し: 直近20日の日々の値幅（円）の標準偏差。銘柄ごとの値動きの大きさをそろえるのに使う
    sigma = c.diff().rolling(20).std().replace(0, np.nan)
    th = lambda x: np.tanh(x)   # 符号だけで判定すると日々の小さな上下でスコアが大きく跳ねるので、なめらかに−1〜+1へ

    # 1) 移動平均（トレンド）: 終値と25/75/200日線の乖離、25日線と75日線の並び、25日線の向き
    ma25 = c.rolling(25).mean()
    ma75 = c.rolling(75).mean()
    ma200 = c.rolling(200).mean()
    ma_parts = pd.concat([th((c - ma25) / (2 * sigma)), th((c - ma75) / (3 * sigma)),
                          th((ma25 - ma75) / (2 * sigma)), th((ma25 - ma25.shift(5)) / sigma),
                          th((c - ma200) / (4 * sigma))], axis=1)
    s_ma = ma_parts.mean(axis=1, skipna=True).where(ma75.notna())

    # 2) MACD(12,26,9): ヒストグラムの大きさ（半分）と、3日前からの変化（半分）
    macd = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    sigl = macd.ewm(span=9, adjust=False).mean()
    hist = macd - sigl
    s_macd = (0.5 * th(hist / (0.4 * sigma)) + 0.5 * th((hist - hist.shift(3)) / (0.3 * sigma)))
    s_macd = s_macd.where(pd.Series(np.arange(n) >= 35, index=c.index))

    # 3) 一目均衡表: 雲との位置(0.5)、転換線と基準線(0.25)、遅行スパン(0.25)
    tenkan = (h.rolling(9).max() + l.rolling(9).min()) / 2
    kijun = (h.rolling(26).max() + l.rolling(26).min()) / 2
    spanA = ((tenkan + kijun) / 2).shift(26)
    spanB = ((h.rolling(52).max() + l.rolling(52).min()) / 2).shift(26)
    top = pd.concat([spanA, spanB], axis=1).max(axis=1, skipna=False)
    bot = pd.concat([spanA, spanB], axis=1).min(axis=1, skipna=False)
    cloud = np.where(c > top, 1.0, np.where(c < bot, -1.0, 0.0))
    cloud = pd.Series(cloud, index=c.index).where(top.notna())
    cpos = pd.Series(np.where(c > top, th((c - top) / (2 * sigma)), np.where(c < bot, th((c - bot) / (2 * sigma)), 0.0)),
                     index=c.index).where(top.notna())
    s_ichi = 0.5 * cpos + 0.25 * th((tenkan - kijun) / (1.5 * sigma)) + 0.25 * th((c - c.shift(25)) / (3 * sigma))

    # 4) RSI(14, Wilder): 30で+1、70で−1（逆張り）
    ch = c.diff()
    ag = ch.clip(lower=0).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    al = (-ch).clip(lower=0).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    rsi = 100 - 100 / (1 + ag / al.replace(0, np.nan))
    rsi = rsi.where(al != 0, 100.0).where(ag.notna())
    s_rsi = ((50 - rsi) / 20).clip(-1, 1)

    # 5) ボリンジャーバンド(20日, ±2σ): 下限で+1、上限で−1（逆張り）
    mid = c.rolling(20).mean()
    sd = c.rolling(20).std(ddof=0)
    pb = (c - (mid - 2 * sd)) / (4 * sd).replace(0, np.nan)
    s_bb = ((0.5 - pb) * 2).clip(-1, 1)

    # 6) 出来高: 直近20日で、上げた日の出来高の割合（75%で+1、25%で−1）
    upv = v.where(ch > 0, 0.0).rolling(20).sum()
    dnv = v.where(ch < 0, 0.0).rolling(20).sum()
    tot = (upv + dnv).replace(0, np.nan)
    upr = upv / tot
    s_vol = ((upr - 0.5) * 4).clip(-1, 1)

    # 7) 52週高値への近さ: 終値÷52週高値（高値ベース）。0.82で0、0.97以上で+1、0.67以下で−1
    hi52 = h.rolling(252, min_periods=120).max()
    near = c / hi52
    s_hi = ((near - 0.82) / 0.15).clip(-1, 1)
    # 8) 値動きの小ささ: 60日の日次変化率の標準偏差（年率%）。35%で0、15%以下で+1、55%以上で−1
    vol60 = c.pct_change().rolling(60, min_periods=40).std() * np.sqrt(245) * 100
    s_lv = ((35 - vol60) / 20).clip(-1, 1)

    comp = pd.concat({"hi52": s_hi, "lv": s_lv, "ma": s_ma, "macd": s_macd, "ichi": s_ichi,
                      "rsi": s_rsi, "bb": s_bb, "vol": s_vol}, axis=1)[list(TECH_W)]
    w = pd.Series(TECH_W)
    have = comp.notna()
    wsum = (have * w).sum(axis=1)
    score = ((comp.fillna(0) * w).sum(axis=1) / wsum.replace(0, np.nan) * 100 * TECH_GAIN).clip(-100, 100)
    score = score.where(have.sum(axis=1) >= 5)

    i = n - 1
    last = comp.iloc[i]

    def ev_cross(a, b, look):
        """直近 look 日以内の a と b のクロス（+1: 上抜け、−1: 下抜け）"""
        d = sig(a - b)
        for k in range(i, max(i - look, 0), -1):
            if not (np.isnan(d.iloc[k]) or np.isnan(d.iloc[k - 1])) and d.iloc[k] != d.iloc[k - 1] and d.iloc[k] != 0:
                return int(d.iloc[k]), i - k
        return None, None

    events = []
    when = lambda a: f"{a}日前" if a else "最新日"
    gc, ago = ev_cross(ma25, ma75, 10)
    if gc:
        events.append(f"{'ゴールデン' if gc > 0 else 'デッド'}クロス（25日×75日・{when(ago)}）")
    mc_, ago = ev_cross(macd, sigl, 5)
    if mc_:
        events.append(f"MACD{'買い' if mc_ > 0 else '売り'}転換（{when(ago)}）")
    if not np.isnan(rsi.iloc[i]):
        if rsi.iloc[i] <= 30: events.append("RSI売られすぎ")
        elif rsi.iloc[i] >= 70: events.append("RSI買われすぎ")
    if not np.isnan(pb.iloc[i]):
        if pb.iloc[i] <= 0: events.append("ボリンジャー−2σ割れ")
        elif pb.iloc[i] >= 1: events.append("ボリンジャー+2σ超え")

    v5 = v.iloc[-5:].mean()
    v25 = v.iloc[-25:].mean()
    cl = cloud.iloc[i]
    raw = {
        "hi52": {"near": r(near.iloc[i] * 100, 1), "hi": r(hi52.iloc[i], 1)},
        "lv": {"vol": r(vol60.iloc[i], 1)},
        "ma": {"dev25": r((c.iloc[i] / ma25.iloc[i] - 1) * 100, 1), "dev75": r((c.iloc[i] / ma75.iloc[i] - 1) * 100, 1),
               "dev200": r((c.iloc[i] / ma200.iloc[i] - 1) * 100, 1),
               "up25": None if np.isnan(ma25.iloc[i - 5]) else bool(ma25.iloc[i] > ma25.iloc[i - 5])},
        "macd": {"hist": r(hist.iloc[i] / c.iloc[i] * 100, 2), "rise": bool(hist.iloc[i] > hist.iloc[i - 3]) if n > 3 else None},
        "ichi": {"cloud": None if np.isnan(cl) else int(cl),
                 "tk": None if np.isnan(tenkan.iloc[i] - kijun.iloc[i]) else int(sig(tenkan.iloc[i] - kijun.iloc[i]))},
        "rsi": {"rsi": r(rsi.iloc[i], 1)},
        "bb": {"pb": r(pb.iloc[i] * 100, 0)},
        "vol": {"upr": r(upr.iloc[i] * 100, 0), "surge": r(v5 / v25, 2) if v25 else None},
    }
    def group(keys):
        sub = comp[keys]
        ww = pd.Series({k: TECH_W[k] for k in keys})
        hv = sub.notna()
        g = (sub.fillna(0) * ww).sum(axis=1) / (hv * ww).sum(axis=1).replace(0, np.nan) * 100
        return g.where(hv.sum(axis=1) >= max(1, len(keys) - 1))
    groups = {"tr": group(TREND_KEYS).iloc[i], "os": group(OSC_KEYS).iloc[i]}
    hist_sc = score.iloc[-days:]
    # 売買の目安（IN・利確・損切り）に使う価格帯
    tr_ = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr_.ewm(alpha=1/14, adjust=False, min_periods=14).mean().iloc[i]
    lv_in = {"c": c.iloc[i], "atr": atr, "ma25": ma25.iloc[i], "ma75": ma75.iloc[i], "ma200": ma200.iloc[i],
             "bbl": (mid - 2 * sd).iloc[i], "bbu": (mid + 2 * sd).iloc[i], "kijun": kijun.iloc[i],
             "top": top.iloc[i], "bot": bot.iloc[i],
             "low20": l.iloc[-20:].min(), "low60": l.iloc[-60:].min(),
             "high20": h.iloc[-20:].max(), "high60": h.iloc[-60:].max(), "high250": h.iloc[-250:].max()}
    return score.iloc[i], last.to_dict(), raw, events, hist_sc, groups, lv_in


def load_prices(code):
    p = os.path.join(PRICES, f"{code}.csv")
    try:
        df = pd.read_csv(p)
    except Exception:
        return None
    df = df.dropna(subset=["close"])
    df = df[df["close"] > 0]
    return df.tail(320).reset_index(drop=True) if len(df) else None


# ---------------------------------------------------------------- ファンダメンタル
def num(row, col):
    v = pd.to_numeric(row.get(col), errors="coerce")
    return None if v is None or pd.isna(v) else float(v)


def fundamental(row):
    grade = lambda x: None if x is None else max(-1.0, min(1.0, (x - 3) / 2))
    clip = lambda x: max(-1.0, min(1.0, x))

    def avg(*xs):
        xs = [x for x in xs if x is not None]
        return sum(xs) / len(xs) if xs else None

    fin = str(row.get("金融")).lower() == "true"
    per, pbr = num(row, "PER"), num(row, "PBR")
    roe = num(row, "ROE(%)")
    gr = num(row, "売上高成長率(%)")
    cagr = num(row, "売上高CAGR(%)")
    eq = num(row, "自己資本比率(%)")
    fs = num(row, "Fスコア")
    fcfy = num(row, "FCF利回り(%)")
    dy = num(row, "配当利回り(%)")
    evm = num(row, "EV/EBITDA")

    comp = {
        # 割安度: 四季報式の割安度評価(1〜5)。PER基準、赤字はPBR基準
        # （2026-10-13）割安度評価に PBR（1倍で0、0.5倍で+1、2倍で−1）と EV/EBITDA（10倍で0、5倍で+1、15倍で−1）を加えた平均
        "val": avg(grade(num(row, "割安度評価")),
                   None if (pbr is None or pbr <= 0) else clip(-math.log2(pbr)),
                   None if (evm is None or evm <= 0 or fin) else clip((10 - evm) / 5)),
        # 収益性: 収益性評価(1〜5) と ROE（8%を中立、16%で+1、0%で−1）の平均
        "prof": avg(grade(num(row, "収益性評価")), None if roe is None else clip((roe - 8) / 8)),
        # 成長性: 成長性評価(1〜5) と 直近の増収率（±10%で±1）の平均
        "grow": avg(grade(num(row, "成長性評価")), None if gr is None else clip(gr / 10)),
        # 安全性: 安全性評価(1〜5)（金融は業法の健全性指標ベース）
        "safe": grade(num(row, "安全性評価")),
        # Fスコア(0〜9): 4.5を中立
        "fs": None if fs is None else clip((fs - 4.5) / 4.5),
        # キャッシュ創出: FCF利回り（±6%で±1）。金融はFCFの意味が薄いので使わない
        "cash": None if (fcfy is None or fin) else clip(fcfy / 6),
    }
    have = {k: v for k, v in comp.items() if v is not None}
    if len(have) < 3:
        score = None
    else:
        ws = sum(FUND_W[k] for k in have)
        score = sum(FUND_W[k] * v for k, v in have.items()) / ws * 100
    raw = {
        "val": {"per": r(per, 1), "pbr": r(pbr, 2), "evm": None if fin else r(evm, 1), "g": num(row, "割安度評価"), "base": row.get("割安度の基準") if isinstance(row.get("割安度の基準"), str) else None},
        "prof": {"roe": r(roe, 1), "g": num(row, "収益性評価"), "opm": r(num(row, "営業利益率(%)"), 1)},
        "grow": {"gr": r(gr, 1), "cagr": r(cagr, 1), "g": num(row, "成長性評価")},
        "safe": {"eq": r(eq, 1), "g": num(row, "安全性評価")},
        "fs": {"fs": fs},
        "cash": {"fcfy": r(fcfy, 1), "dy": r(dy, 2), "fin": fin},
    }
    flags = [k for k in ("赤字", "決算が古い", "一時要因の疑い") if str(row.get(k)).lower() == "true"]
    return score, comp, raw, flags


# ---------------------------------------------------------------- チャート用データ
def write_chart_data(code, df):
    """直近 CHART_DAYS 日のローソク足・出来高・一目均衡表（雲は26日先まで）を sig/<code>.js に書く。
    file:// で開いても読めるよう JSON ではなく SIGC("コード",{...}) を呼ぶスクリプトにする。
    価格は 0〜9999 の整数に詰める（p0 + 値 × pk で円に戻す）。"""
    o, h, l, c, v = (df[k].astype(float) for k in ("open", "high", "low", "close", "volume"))
    n = len(c)
    if n < 30:
        return
    tenkan = (h.rolling(9).max() + l.rolling(9).min()) / 2
    kijun = (h.rolling(26).max() + l.rolling(26).min()) / 2
    mid_tk = ((tenkan + kijun) / 2).tolist()
    mid_52 = ((h.rolling(52).max() + l.rolling(52).min()) / 2).tolist()
    N = min(CHART_DAYS, n)
    st = n - N
    # 先行スパン: 位置 p の値は 26本前に計算した値。p は st..n-1+26（26日先まで）
    sa = [mid_tk[a - 26] if 0 <= a - 26 < n else None for a in range(st, n + 26)]
    sb = [mid_52[a - 26] if 0 <= a - 26 < n else None for a in range(st, n + 26)]
    win = lambda x: x.iloc[st:].tolist()
    cols = {"o": win(o), "h": win(h), "l": win(l), "c": win(c), "tk": win(tenkan), "kj": win(kijun), "sa": sa, "sb": sb}
    vals = [x for a in cols.values() for x in a if x is not None and np.isfinite(x)]
    lo, hi = min(vals), max(vals)
    k = (hi - lo) / 9999 if hi > lo else 1.0
    enc = lambda a: [None if (x is None or not np.isfinite(x)) else int(round((x - lo) / k)) for x in a]
    vv = win(v)
    vmax = max(vv) or 1
    out = {"p0": float(f"{lo:.6g}"), "pk": float(f"{k:.6g}"),
           "d": [str(x)[5:].replace("-", "") for x in df["date"].iloc[st:]],
           **{key: enc(a) for key, a in cols.items()},
           "vk": float(f"{vmax / 999:.6g}"), "v": [int(round(x / vmax * 999)) if np.isfinite(x) else 0 for x in vv]}
    os.makedirs(OUT_SIG, exist_ok=True)
    with open(os.path.join(OUT_SIG, f"{code}.js"), "w", encoding="utf-8") as fh:
        fh.write(f'SIGC("{code}",{json.dumps(out, separators=(",", ":"))});')


# ---------------------------------------------------------------- 売買の目安
def tick(p):
    """東証の呼値（おおまか）。目安の価格をこの単位に丸める"""
    return 0.1 if p < 100 else 1 if p <= 3000 else 5 if p <= 5000 else 10 if p <= 30000 else 50 if p <= 50000 else 100


def rnd(x, p, how="near"):
    t = tick(p)
    f = math.floor if how == "down" else math.ceil if how == "up" else round
    v = f(x / t) * t
    return round(v, 1) if t < 1 else int(v)


def trade_levels(v, tt, to):
    """移動平均・ボリンジャー・一目・直近高安値とATR(14)から、IN・利確・損切りの目安を機械的に出す。
    モード: now=現値付近でIN可 / dip=押し目待ち（指値の目安） / wait=下落トレンドなので転換待ち"""
    c, atr = v["c"], v["atr"]
    if atr is None or not np.isfinite(atr) or atr <= 0 or tt is None:
        return None
    ok = lambda x: x is not None and np.isfinite(x)
    sup_c = [("25日線", v["ma25"]), ("75日線", v["ma75"]), ("200日線", v["ma200"]), ("ボリンジャー−2σ", v["bbl"]),
             ("一目 基準線", v["kijun"]), ("20日安値", v["low20"]), ("60日安値", v["low60"])]
    if ok(v["top"]) and c > v["top"]:
        sup_c.append(("一目 雲の上限", v["top"]))
    res_c = [("ボリンジャー+2σ", v["bbu"]), ("20日高値", v["high20"]), ("60日高値", v["high60"]), ("52週高値", v["high250"]),
             ("25日線", v["ma25"]), ("75日線", v["ma75"]), ("200日線", v["ma200"]), ("一目 基準線", v["kijun"])]
    if ok(v["bot"]) and c < v["bot"]:
        res_c.append(("一目 雲の下限", v["bot"]))

    def cluster(cands, below):
        xs = sorted([(p, n) for n, p in cands if ok(p) and ((p < c) if below else (p > c))], reverse=below)
        out = []
        for p, n in xs:   # 0.4ATR 以内に重なる水準は1つにまとめる（重なるほど意識されやすい）
            if out and abs(out[-1][0] - p) <= 0.4 * atr:
                out[-1][1].append(n)
            else:
                out.append([p, [n]])
        return out
    sups = [x for x in cluster(sup_c, True) if c - x[0] <= 5 * atr]
    ress = cluster(res_c, False)

    up, down = tt >= LEVELS["tr"][1], tt <= LEVELS["tr"][2]
    lv = {"atr": rnd(atr, c), "atrp": r(atr / c * 100, 1)}
    if down:
        # 下落トレンド: 25日線や基準線などの上抜けを確認してから
        trig = next((x for x in ress if any(n in ("25日線", "一目 基準線", "一目 雲の下限", "75日線") for n in x[1])), None)
        lv["mode"] = "wait"
        if trig:
            lv["trig"], lv["trigB"] = rnd(trig[0], c, "up"), "・".join(trig[1])
        base = c
        lo, hi = None, None
    else:
        s1 = sups[0] if sups else None
        oversold = to is not None and to >= LEVELS["os"][1]
        # 現値でINしてよいのは「上昇トレンドで支持線のすぐ上」か「売られすぎ」のとき。横ばいは押し目を待つ
        if (up and (s1 is None or c - s1[0] <= 0.6 * atr)) or oversold:
            lv["mode"] = "now"
            lo = max(s1[0], c - atr) if s1 else c - 0.7 * atr
            hi = c
            lv["inB"] = ("・".join(s1[1]) + "の上" if s1 and c - s1[0] <= 1.2 * atr else "現値付近") +                         ("（売られすぎ）" if to is not None and to >= LEVELS["os"][1] else "")
        else:
            lv["mode"] = "dip"
            if s1 is None:   # 近くに支持線が無いときは、現値から1ATR下あたり
                lo, hi = c - 1.3 * atr, c - 0.7 * atr
                lv["inB"] = "現値から1ATRほど押したら"
            else:
                lo, hi = s1[0] - 0.3 * atr, min(s1[0] + 0.3 * atr, c)   # 上限は現値を超えない
                lv["inB"] = "・".join(s1[1]) + "付近まで押したら"
        lv["in"] = [rnd(lo, c, "down"), c if lv["mode"] == "now" else min(rnd(hi, c), c)]
        base = (lo + hi) / 2
        # 損切り: INゾーン下限から1.5ATR下。その間に次の支持線があれば、その少し下
        nxt = next((x for x in sups if x[0] < lo - 0.3 * atr), None)
        stop = lo - 1.5 * atr
        if nxt and nxt[0] - 0.3 * atr > stop and nxt[0] > lo - 2.5 * atr:
            stop, lv["stopB"] = nxt[0] - 0.3 * atr, "・".join(nxt[1]) + "割れ"
        else:
            lv["stopB"] = "INゾーン下限−1.5ATR"
        lv["stop"] = rnd(stop, c, "down")
    # 利確: IN基準から1ATR以上上の抵抗線。無ければ値幅（2ATR・4ATR）
    # 遠すぎる抵抗線（利確1は6ATR超、利確2は10ATR超）は現実的でないので値幅の目安に置き換える
    tg = [x for x in ress if x[0] >= base + atr]
    t1 = tg[0] if tg and tg[0][0] <= base + 6 * atr else [base + 2 * atr, ["値幅 2ATR"]]
    t2 = next((x for x in tg if x[0] >= t1[0] + atr and x[0] <= base + 10 * atr),
              [max(t1[0] + 1.5 * atr, base + 4 * atr), ["値幅 4ATR"]])
    lv["t1"], lv["t1B"] = rnd(t1[0], c, "up"), "・".join(t1[1])
    lv["t2"], lv["t2B"] = rnd(t2[0], c, "up"), "・".join(t2[1])
    if lv.get("stop") is not None and base > lv["stop"]:
        lv["rr"] = r((lv["t1"] - base) / (base - lv["stop"]), 1)
    # 保有中の手じまい（トレーリング）: 終値がこれを割ったら。上昇中は25日線も考慮
    trail = c - 2.5 * atr
    if up and ok(v["ma25"]) and v["ma25"] < c:
        trail = max(trail, v["ma25"] - 0.3 * atr)
    lv["trail"] = rnd(trail, c, "down")
    lv["trailB"] = "25日線割れ" if up and ok(v["ma25"]) and v["ma25"] < c and trail > c - 2.5 * atr else "終値−2.5ATR"
    lv["hot"] = bool(to is not None and to <= LEVELS["os"][3])
    return lv


def level_cols(lv):
    lv = lv or {}
    mode = {"now": "現値付近でIN可", "dip": "押し目待ち", "wait": "転換待ち"}.get(lv.get("mode"), "")
    return {"IN判定": mode, "IN下限": (lv.get("in") or [None, None])[0], "IN上限": (lv.get("in") or [None, None])[1],
            "IN転換ライン": lv.get("trig"), "損切り": lv.get("stop"), "利確1": lv.get("t1"), "利確2": lv.get("t2"),
            "リスクリワード": lv.get("rr"), "保有中の手じまい": lv.get("trail"), "ATR": lv.get("atr")}


AD_DAYS = 120   # 騰落レシオのグラフに出す営業日数


def advance_decline(adv):
    """市場ごとの25日・10日騰落レシオ（値上がり銘柄数の合計÷値下がり銘柄数の合計×100）"""
    out = {}
    for mk in sorted({m for m, _ in adv}):
        days = sorted(d for m, d in adv if m == mk)
        cnt = pd.DataFrame([adv[(mk, d)] for d in days], index=days, columns=["up", "dn", "fl"])
        # 休場日にデータが紛れた日（銘柄数が普段の半分未満）は除く
        tot = cnt.sum(axis=1)
        cnt = cnt[tot >= tot.rolling(20, min_periods=1).median() * 0.5]
        r25 = cnt["up"].rolling(25).sum() / cnt["dn"].rolling(25).sum().replace(0, np.nan) * 100
        r10 = cnt["up"].rolling(10).sum() / cnt["dn"].rolling(10).sum().replace(0, np.nan) * 100
        cnt = cnt.assign(r25=r25, r10=r10).dropna(subset=["r25"]).tail(AD_DAYS)
        out[mk] = {"d": [d[5:] for d in cnt.index], "y": cnt.index[-1][:4] if len(cnt) else "",
                   "r25": [r(x, 1) for x in cnt["r25"]], "r10": [r(x, 1) for x in cnt["r10"]],
                   "up": cnt["up"].astype(int).tolist(), "dn": cnt["dn"].astype(int).tolist(),
                   "fl": cnt["fl"].astype(int).tolist()}
    return out


def compact(o):
    """JSONを小さくする: 整数値の小数は整数に、真偽値は1/0に"""
    if isinstance(o, dict):
        return {k: compact(v) for k, v in o.items()}
    if isinstance(o, list):
        return [compact(v) for v in o]
    if isinstance(o, bool):
        return int(o)
    if isinstance(o, float):
        if math.isnan(o) or math.isinf(o):
            return None
        return int(o) if o.is_integer() and abs(o) < 1e15 else o
    return o


# ---------------------------------------------------------------- 本体
def main(argv):
    days = 60
    if "--days" in argv:
        days = int(argv[argv.index("--days") + 1])
    t0 = datetime.datetime.now()

    tk = pd.read_csv(TICKERS, dtype=str, encoding="utf-8-sig")
    sec = pd.read_csv(SECTORS, dtype=str)[["code", "sector33"]] if os.path.exists(SECTORS) else pd.DataFrame(columns=["code", "sector33"])
    tk = tk.merge(sec, on="code", how="left")
    sc = pd.read_csv(SCORE, dtype={"コード": str}, encoding="utf-8-sig") if os.path.exists(SCORE) else pd.DataFrame(columns=["コード"])
    sc = sc.set_index("コード")

    rows, csv_rows, asof = [], [], None
    adv = {}   # 騰落の集計 {(市場, 日付): [値上がり, 値下がり, 変わらず]}
    for _, t in tk.iterrows():
        code = t["code"]
        df = load_prices(code)
        if df is None or len(df) < 30:
            continue
        rec = {"c": code, "n": t["name"], "m": t["market"],
               "s": t.get("sector33") if isinstance(t.get("sector33"), str) else "",
               "d": str(df["date"].iloc[-1]), "p": r(df["close"].iloc[-1], 1),
               "chg": r((df["close"].iloc[-1] / df["close"].iloc[-2] - 1) * 100, 2) if len(df) > 1 else None}
        asof = max(asof or "", rec["d"])
        # 騰落レシオ用に、日ごとの値上がり・値下がりを数える（全体と市場別）
        dd = df["date"].astype(str).tolist()[-(AD_DAYS + 40):]
        cc = df["close"].astype(float).tolist()[-(AD_DAYS + 40):]
        for j in range(1, len(cc)):
            k = 0 if cc[j] > cc[j - 1] else 1 if cc[j] < cc[j - 1] else 2
            for mk in ("", t["market"]):
                adv.setdefault((mk, dd[j]), [0, 0, 0])[k] += 1

        ts, tcomp, traw, tev, th, tg, lvin = technical(df, days)
        rec["ts"] = r(ts, 0)
        rec["tt"] = r(tg["tr"], 0)   # トレンド系
        rec["to"] = r(tg["os"], 0)   # オシレーター系
        rec["lv"] = trade_levels(lvin, rec["tt"], rec["to"])
        # write_chart_data(code, df)   # 2026-11: 売買シグナルの個別表示を廃止（分析ダッシュボードで見る）
        rec["tc"] = [r(tcomp[k], 2) for k in TECH_W]
        rec["tr"] = [traw["ma"]["dev25"], traw["ma"]["dev75"], traw["ma"]["dev200"], traw["ma"]["up25"],
                     traw["macd"]["hist"], traw["macd"]["rise"], traw["ichi"]["cloud"], traw["ichi"]["tk"],
                     traw["rsi"]["rsi"], traw["bb"]["pb"], traw["vol"]["upr"], traw["vol"]["surge"],
                     traw["hi52"]["near"], traw["hi52"]["hi"], traw["lv"]["vol"]]
        rec["te"] = tev
        # 株価の推移は 0〜999 の整数に詰める（hp0 + hp × hpk で円に戻す）
        closes = df["close"].iloc[-days:].astype(float)
        lo, hi = float(closes.min()), float(closes.max())
        k = (hi - lo) / 999 if hi > lo else 1.0
        rec["hp0"], rec["hpk"] = lo, float(f"{k:.6g}")
        rec["hp"] = [int(round((x - lo) / k)) for x in closes]
        rec["hs"] = [None if pd.isna(x) else int(round(x)) for x in th.tolist()]

        if code in sc.index:
            row = sc.loc[code]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]
            fsc, fcomp, fraw, flags = fundamental(row.to_dict())
            if not rec["s"] and isinstance(row.get("業種"), str):
                rec["s"] = row.get("業種")
            rec["fs"] = r(fsc, 0)
            rec["fc"] = [r(fcomp[k], 2) for k in FUND_W]
            rec["fr"] = [fraw["val"]["per"], fraw["val"]["pbr"], fraw["val"]["g"], fraw["val"]["base"],
                         fraw["prof"]["roe"], fraw["prof"]["g"], fraw["prof"]["opm"],
                         fraw["grow"]["gr"], fraw["grow"]["cagr"], fraw["grow"]["g"],
                         fraw["safe"]["eq"], fraw["safe"]["g"], fraw["fs"]["fs"],
                         fraw["cash"]["fcfy"], fraw["cash"]["dy"], fraw["cash"]["fin"], fraw["val"]["evm"]]
            rec["ff"] = flags
            rec["fp"] = row.get("決算期") if isinstance(row.get("決算期"), str) else None
            rec["dv"] = r(num(row.to_dict(), "業種内偏差値"), 1)
            rec["mc"] = r(num(row.to_dict(), "時価総額(億円)"), 0)
        else:
            rec["fs"] = None
        rows.append(rec)
        csv_rows.append({
            "コード": code, "銘柄名": rec["n"], "市場": rec["m"], "業種": rec["s"], "株価": rec["p"], "日付": rec["d"],
            "テクニカルスコア": rec["ts"], "テクニカル判定": label(rec["ts"], "t"),
            "トレンド系スコア": rec["tt"], "トレンド系判定": label(rec["tt"], "tr"),
            "オシレーター系スコア": rec["to"], "オシレーター系判定": label(rec["to"], "os"),
            **{f"T_{k}": v for k, v in zip(TECH_W, rec["tc"])},
            "ファンダスコア": rec.get("fs"), "ファンダ判定": label(rec.get("fs"), "f"),
            **{f"F_{k}": v for k, v in zip(FUND_W, rec.get("fc") or [None] * len(FUND_W))},
            "イベント": " / ".join(tev),
            **level_cols(rec.get("lv")),
        })

    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    pd.DataFrame(csv_rows).to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    ad = advance_decline(adv)
    # 目安の根拠の文字列は銘柄間で重複が多いので、一覧にして番号で持つ（HTMLを軽くする）
    basis = []
    bidx = {}
    for x in rows:
        lv = x.get("lv")
        if not lv:
            continue
        for k in ("inB", "stopB", "t1B", "t2B", "trailB", "trigB"):
            if k in lv:
                t = lv[k]
                if t not in bidx:
                    bidx[t] = len(basis)
                    basis.append(t)
                lv[k] = bidx[t]
    meta = {"bs": basis, "ad": ad, "asof": asof, "built": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "days": days,
            "tw": TECH_W, "fw": FUND_W, "levels": LEVELS, "names": NAMES}
    data = json.dumps({"meta": meta, "rows": compact(rows)}, ensure_ascii=False, separators=(",", ":"))
    html = TEMPLATE.replace("/*__DATA__*/null", data.replace("</", "<\\/"))
    os.makedirs(os.path.dirname(OUT_HTML), exist_ok=True)
    with open(OUT_HTML, "w", encoding="utf-8") as fh:
        fh.write(html)

    ts = pd.Series([x["ts"] for x in rows], dtype=float)
    fs = pd.Series([x.get("fs") for x in rows], dtype=float)
    dist = lambda s, k: {n: int(v) for n, v in s.dropna().map(lambda x: label(x, k)).value_counts().items()}
    tt = pd.Series([x["tt"] for x in rows], dtype=float)
    to = pd.Series([x["to"] for x in rows], dtype=float)
    log(f"シグナル {len(rows)}銘柄（基準日 {asof}） テクニカル {dist(ts, 't')} ／ トレンド {dist(tt, 'tr')} ／ "
        f"オシレーター {dist(to, 'os')} ／ ファンダ {dist(fs, 'f')} "
        f"→ {OUT_HTML}（{os.path.getsize(OUT_HTML)/1e6:.1f}MB, {(datetime.datetime.now()-t0).seconds}秒）")


TEMPLATE = r"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>売買シグナル メーター</title>
<script>
/* ?theme=dark|light → 保存済みの設定 → OSの設定 の順で明るさを決める */
(function(){var m=/[?&#]theme=(dark|light)/.exec(location.search+location.hash),t=m&&m[1];
 if(!t){try{t=localStorage.getItem('fdb-theme')}catch(e){}}
 if(t)document.documentElement.setAttribute('data-theme',t);})();
</script>
<style>
@import url("https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap");
:root{
  --bg:#f9f9f7;--card:#fcfcfb;--fg:#0b0b0b;--fg2:#52514e;--mut:#898781;--line:#e1e0d9;--axis:#c3c2b7;
  --ring:rgba(11,11,11,.10);--hover:rgba(11,11,11,.04);
  --z0:#0f7f63;--z1:#9fd6c4;--z2:#d6d8dc;--z3:#efa3a7;--z4:#c8323a;
  --z0t:#08705a;--z4t:#b91c24;--price:#52514e;--acc:#2a78d6;
  --candleU:#D14343;--candleD:#2E7D6B;--tenkan:#8E5BA6;--kijun:#C98A00;--chikou:#9a9890;--cloudU:#7fb0e0;--cloudD:#e09a9a;
  color-scheme:light;
}
@media (prefers-color-scheme:dark){
  :root:where(:not([data-theme="light"])){
    --bg:#0d0d0d;--card:#1a1a19;--fg:#fff;--fg2:#c3c2b7;--mut:#898781;--line:#2c2c2a;--axis:#383835;
    --ring:rgba(255,255,255,.10);--hover:rgba(255,255,255,.05);
    --z0:#2fb58c;--z1:#1f5a4a;--z2:#30343d;--z3:#8a3a3e;--z4:#e0555c;
    --z0t:#3fd0a4;--z4t:#ff7378;--price:#c3c2b7;--acc:#3987e5;color-scheme:dark;
    --candleU:#E06060;--candleD:#3FA58C;--tenkan:#B48AD0;--kijun:#E0A830;--chikou:#77766f;--cloudU:#3d6fa3;--cloudD:#9a4d4d;}
}
:root[data-theme="dark"]{
  --bg:#0d0d0d;--card:#1a1a19;--fg:#fff;--fg2:#c3c2b7;--mut:#898781;--line:#2c2c2a;--axis:#383835;
  --ring:rgba(255,255,255,.10);--hover:rgba(255,255,255,.05);
  --z0:#2fb58c;--z1:#1f5a4a;--z2:#30343d;--z3:#8a3a3e;--z4:#e0555c;
  --z0t:#3fd0a4;--z4t:#ff7378;--price:#c3c2b7;--acc:#3987e5;color-scheme:dark;
    --candleU:#E06060;--candleD:#3FA58C;--tenkan:#B48AD0;--kijun:#E0A830;--chikou:#77766f;--cloudU:#3d6fa3;--cloudD:#9a4d4d;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.55 system-ui,-apple-system,"Hiragino Sans","Segoe UI",sans-serif;
  font-variant-numeric:tabular-nums}
.wrap{max-width:1120px;margin:0 auto;padding:16px 16px 48px}
a{color:var(--acc)}
header{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:baseline;justify-content:space-between}
h1{font-size:20px;margin:0}
.sub{color:var(--fg2);font-size:12.5px}
.nav{display:flex;gap:12px;flex-wrap:wrap;font-size:13px;align-items:center}
button,select,input{font:inherit;color:inherit}
.btn{background:var(--card);border:1px solid var(--ring);border-radius:8px;padding:5px 10px;cursor:pointer}
.btn:hover{background:var(--hover)}
.card{background:var(--card);border:1px solid var(--ring);border-radius:12px;padding:16px}
.search{position:relative;margin:16px 0 12px}
.search input{width:100%;padding:11px 14px;border-radius:10px;border:1px solid var(--ring);background:var(--card);font-size:15px}
.sugg{position:absolute;left:0;right:0;top:100%;margin-top:4px;background:var(--card);border:1px solid var(--ring);
  border-radius:10px;z-index:5;max-height:360px;overflow:auto;display:none;box-shadow:0 6px 24px rgba(0,0,0,.12)}
.sugg div{padding:8px 14px;cursor:pointer;display:flex;gap:10px;align-items:baseline}
.sugg div.on,.sugg div:hover{background:var(--hover)}
.sugg .cd{color:var(--fg2);width:44px;flex:none}
.sugg .mk{color:var(--mut);font-size:12px;margin-left:auto;white-space:nowrap}
.stock{display:flex;flex-wrap:wrap;gap:6px 16px;align-items:baseline;margin:4px 2px 12px}
.stock .nm{font-size:22px;font-weight:700}
.stock .cd{color:var(--fg2);font-size:15px}
.stock .px{font-size:18px;font-weight:600}
.meta{color:var(--fg2);font-size:13px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media (max-width:760px){.grid2{grid-template-columns:1fr}}
.gh{display:flex;justify-content:space-between;align-items:baseline}
.gh h2{font-size:15px;margin:0}
.gauge{display:block;width:100%;max-width:340px;margin:4px auto 0}
.readout{text-align:center;margin-top:-6px}
.readout .sc{font-size:34px;font-weight:700;letter-spacing:-.5px}
.pill{display:inline-block;padding:2px 12px;border-radius:999px;font-weight:700;font-size:14px;margin-left:6px;vertical-align:6px;border:1.5px solid}
.chips{display:flex;flex-wrap:wrap;gap:6px;justify-content:center;margin:8px 0 2px;min-height:4px}
.chip{font-size:12px;padding:2px 9px;border-radius:999px;border:1px solid var(--ring);color:var(--fg2)}
.parts{margin-top:14px;border-top:1px solid var(--line)}
.subg{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:12px;padding-top:12px;border-top:1px solid var(--line)}
.subg .sg{text-align:center}
.subg .sg h4{margin:0;font-size:13px}
.subg .sg .cap{color:var(--mut);font-size:11px}
.subg svg{display:block;width:100%;max-width:190px;margin:2px auto 0}
.subg .ro{margin-top:-4px}
.subg .ro b{font-size:22px}
.subg .ro .pill{font-size:12px;padding:1px 9px;vertical-align:4px}
.subg .cm{grid-column:1/-1;background:var(--hover);border-radius:8px;padding:8px 10px;font-size:13px;text-align:left}
.subg .cm b{margin-right:6px}
.subg .cm span{color:var(--fg2)}
.pgh{font-size:12px;font-weight:700;color:var(--fg2);padding:10px 0 2px;border-bottom:1px solid var(--line)}
.pgh small{font-weight:400;color:var(--mut);margin-left:6px}
.part{display:grid;grid-template-columns:112px 1fr 44px;gap:4px 10px;align-items:center;padding:8px 0;border-bottom:1px solid var(--line)}
.part .pn{font-weight:600;font-size:13px}
.part .pn small{display:block;font-weight:400;color:var(--mut);font-size:11px}
.part .pv{text-align:right;font-weight:600;font-size:13px}
.part .pd{grid-column:1/-1;color:var(--fg2);font-size:12px;margin-top:-2px}
.dbar{position:relative;height:10px}
.dbar .ax{position:absolute;left:50%;top:-3px;bottom:-3px;width:1px;background:var(--axis)}
.dbar .tr{position:absolute;left:0;right:0;top:4px;height:2px;background:var(--line);border-radius:1px}
.dbar .f{position:absolute;top:0;height:10px;border-radius:4px}
.na{color:var(--mut)}
.verdict{margin:12px 0;display:flex;gap:14px;align-items:center;flex-wrap:wrap}
.verdict .vt{font-weight:700;font-size:15px}
.verdict .vd{color:var(--fg2);font-size:13px}
.spark{margin-top:12px}
.spark .lb{display:flex;justify-content:space-between;color:var(--mut);font-size:11.5px}
.spark svg{display:block;width:100%;height:auto;touch-action:none}
.tip{position:fixed;pointer-events:none;background:var(--card);border:1px solid var(--ring);border-radius:8px;padding:6px 9px;
  font-size:12px;box-shadow:0 4px 16px rgba(0,0,0,.15);display:none;z-index:9;white-space:nowrap}
h3{font-size:15px;margin:28px 0 10px}
.breadth{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media (max-width:760px){.breadth{grid-template-columns:1fr}}
.stack{display:flex;height:14px;gap:2px;margin:8px 0 6px}
.stack div{border-radius:3px;min-width:2px}
.stack div:first-child{border-radius:4px 3px 3px 4px}
.leg{display:flex;flex-wrap:wrap;gap:4px 12px;font-size:12px;color:var(--fg2)}
.leg i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:4px;vertical-align:-1px}
.avg{font-size:12.5px;color:var(--fg2)}
.strip{display:flex;flex-wrap:wrap;align-items:center;gap:10px 18px;padding:12px 16px;margin-top:14px}
.stripHead{display:flex;align-items:center;gap:8px}
.stripHead select{padding:3px 6px;border-radius:8px;border:1px solid var(--ring);background:var(--card);font-size:12.5px}
.stripBody{display:flex;flex-wrap:wrap;gap:8px 22px;flex:1;align-items:center}
.si{display:flex;flex-direction:column;gap:2px;min-width:120px}
.si .k{font-size:11.5px;color:var(--mut)}
.si .v{font-size:15px;font-weight:700;display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.si .v small{font-weight:400;color:var(--fg2);font-size:12px}
.si .stack{height:6px;margin:2px 0 0;width:130px}
#mktBtn,#detBtn{font-size:12.5px}
@media (max-width:760px){
  .strip{display:grid;grid-template-columns:1fr auto;gap:10px}
  .stripBody{grid-column:1/-1;grid-row:2;display:grid;grid-template-columns:1fr 1fr;gap:12px 14px}
  #mktBtn{grid-column:2;grid-row:1}
  .si{min-width:0}.si .stack{width:100%}
}
#mktBtn[aria-expanded="true"],#detBtn[aria-expanded="true"]{background:var(--fg);color:var(--bg);border-color:var(--fg)}
.hero{margin-top:0}
.hero .stock{margin:0 0 6px}
.big{display:flex;align-items:center;gap:14px;flex-wrap:wrap;padding:10px 0 12px;border-bottom:1px solid var(--line)}
.big .lab{font-size:30px;font-weight:800;padding:2px 20px;border-radius:12px;border:2px solid;line-height:1.35}
.big .hd{font-weight:700;font-size:15px}
.big .ds{color:var(--fg2);font-size:13px}
.quad{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;padding:10px 0;border-bottom:1px solid var(--line)}
@media (max-width:760px){.quad{grid-template-columns:1fr 1fr}}
.quad .q{text-align:center}
.quad .q h4{margin:0;font-size:13px}
.quad .q .cap{font-size:10.5px;color:var(--mut);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.quad svg{display:block;width:100%;max-width:170px;margin:2px auto 0}
.quad .ro{margin-top:-4px}.quad .ro b{font-size:20px}
.quad .ro .pill{font-size:11.5px;padding:1px 8px;vertical-align:3px;margin-left:4px}
.plan{padding:12px 0 14px;border-top:1px solid var(--line);margin-bottom:10px}
.plan .ph{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.plan .ph h4{margin:0;font-size:14px}
.plan .ps{font-size:13.5px;margin:6px 0 4px;line-height:1.7}
.plan .ps b{font-weight:700}
.plan .lvc{margin:8px 0 6px;min-height:120px}
.lvleg{display:flex;flex-wrap:wrap;gap:4px 12px;font-size:12px;color:var(--fg2);align-items:center;margin-bottom:4px}
.lvleg label{display:flex;align-items:center;gap:4px;cursor:pointer;font-weight:600;color:var(--fg)}
.lvleg i{display:inline-block;width:14px;height:3px;border-radius:2px;margin-right:4px;vertical-align:3px}
.lvleg i.sq{height:9px;width:12px;vertical-align:-1px;opacity:.6}
.plan .lvc svg{display:block;width:100%;height:auto;touch-action:none}
#planBtn{font-size:12.5px;margin-top:2px}
#planBtn[aria-expanded="true"]{background:var(--fg);color:var(--bg);border-color:var(--fg)}
#planDet{margin-top:8px}
.lvt{display:grid;grid-template-columns:auto auto auto 1fr;gap:0 14px;font-size:13px;align-items:baseline}
.lvt>div{padding:5px 0;border-bottom:1px solid var(--line)}
.lvt .rl{font-weight:600;white-space:nowrap}
.lvt .pr{text-align:right;font-weight:700;white-space:nowrap}
.lvt .pc{text-align:right;color:var(--fg2);white-space:nowrap}
.lvt .bs{color:var(--fg2);font-size:12px}
.lvt .cur{color:var(--fg)}.lvt .rl.cur,.lvt .pr.cur{text-decoration:underline;text-underline-offset:3px}
.plan .caveat{color:var(--mut);font-size:11.5px;margin-top:6px}
@media (max-width:760px){.lvt{grid-template-columns:auto auto auto;}.lvt .bs{grid-column:1/-1;border-bottom:1px solid var(--line);padding-top:0}.lvt .x{border-bottom:0}}
.notes{padding:10px 0 12px;font-size:13px;display:flex;flex-direction:column;gap:6px}
.notes .n1 b{margin-right:6px}.notes .n1 span{color:var(--fg2)}
.notes .chips{justify-content:flex-start;margin:2px 0 0}
table.sig th[data-k]{cursor:pointer;user-select:none}
table.sig th.c,table.sig td.c{text-align:center;padding-left:4px;padding-right:4px}
table.sig th .ar{color:var(--mut);font-size:10px;margin-left:2px}
table.sig .sm{display:none}
table.sig .bd{white-space:nowrap}
/* スマホ縦画面: 列を詰めず、1行の高さをそろえて横スクロールで全列を見る。コードと銘柄名は左に固定 */
@media (max-width:760px){
  .sigwrap{padding:0!important;overflow-x:auto;-webkit-overflow-scrolling:touch}
  table.sig{font-size:12.5px;width:max-content;min-width:100%}
  table.sig td,table.sig th{white-space:nowrap;padding:8px 8px}
  table.sig .hide-sm{display:table-cell}
  /* コード・銘柄名は左に固定。銘柄名と業種は固定幅で、はみ出す分は「…」で省略（タップ前でも全文は title で確認できる） */
  table.sig th:nth-child(1),table.sig td:nth-child(1){position:sticky;left:0;z-index:1;background:var(--card);width:34px;min-width:34px;max-width:34px;box-sizing:content-box}
  table.sig th:nth-child(2),table.sig td:nth-child(2){position:sticky;left:50px;z-index:1;background:var(--card);box-shadow:1px 0 0 var(--line);
    width:84px;min-width:84px;max-width:84px;box-sizing:content-box;overflow:hidden;text-overflow:ellipsis}
  table.sig th:nth-child(3),table.sig td:nth-child(3){width:64px;min-width:64px;max-width:64px;box-sizing:content-box;overflow:hidden;text-overflow:ellipsis;font-size:11.5px}
  table.sig tbody tr:hover td{background:var(--card)}
}
.scrollhint{display:none;font-size:11.5px;color:var(--mut);margin:0 0 6px}
@media (max-width:760px){.scrollhint{display:block}}
.bd{display:inline-block;min-width:32px;padding:2px 5px;border-radius:6px;font-size:11.5px;font-weight:700;text-align:center;border:1.5px solid transparent;line-height:1.3}
.bd.b0{background:var(--z4);color:#fff;border-color:var(--z4)}
.bd.b1{color:var(--z4t);border-color:var(--z4)}
.bd.b2{color:var(--mut);border-color:var(--line)}
.bd.b3{color:var(--z0t);border-color:var(--z0)}
.bd.b4{background:var(--z0);color:#fff;border-color:var(--z0)}
.bd.ov{min-width:56px}
.bdw{display:inline-flex;align-items:center;gap:4px;white-space:nowrap}
.scn{min-width:28px;text-align:right;font-size:11.5px;color:var(--fg2);font-variant-numeric:tabular-nums}
table.sig td.ev{min-width:150px;max-width:260px}
table.sig td.ev{white-space:normal}
@media (max-width:760px){table.sig td.ev{white-space:nowrap;max-width:none}}
.evc{display:inline-block;font-size:11.5px;color:var(--fg2);border:1px solid var(--line);border-radius:999px;padding:0 7px;margin:1px 3px 1px 0;white-space:nowrap}
.evc.warn{color:var(--z0t);border-color:var(--z1)}

.adcard{margin-top:12px;display:grid;grid-template-columns:minmax(220px,300px) 1fr;gap:12px 20px;align-items:start}
@media (max-width:760px){.adcard{grid-template-columns:1fr}}
.adcard .gauge{max-width:280px}
.adcard .rd{text-align:center;margin-top:-6px}
.adcard .rd .sc{font-size:28px;font-weight:700}
.adcard .rd .sub{margin-top:4px}
.adcard .adc svg{display:block;width:100%;height:auto;touch-action:none}
.adcard .cm{background:var(--hover);border-radius:8px;padding:8px 10px;font-size:13px;margin-top:8px}
.adcard .cm b{margin-right:6px}.adcard .cm span{color:var(--fg2)}
.h3row{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center;margin:28px 0 10px}
.h3row h3{margin:0}
#sectBtn[aria-expanded="true"]{background:var(--fg);color:var(--bg);border-color:var(--fg)}
.h3row select{padding:4px 8px;border-radius:8px;border:1px solid var(--ring);background:var(--card);font-size:13px}
.srow{display:grid;grid-template-columns:minmax(120px,1.1fr) 48px 2fr 118px 2fr 118px;gap:4px 12px;align-items:center;
  padding:8px 4px;border-bottom:1px solid var(--line)}
#sb .srow{cursor:pointer}
#sb .srow:hover{background:var(--hover)}
#sb .srow:last-child{border-bottom:0}
.shead{color:var(--fg2);font-weight:600;font-size:13px;border-bottom:1px solid var(--axis)}
.srow .sn{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.srow .sc2{text-align:right;color:var(--fg2)}
.srow .stack{margin:0;height:12px}
.srow .av{text-align:right;white-space:nowrap}
.srow .av b{font-weight:600}
.srow .av small{display:block;font-size:11px;color:var(--mut)}
.srow .kl{display:none;color:var(--fg2);font-size:12px}
@media (max-width:760px){
  .shead{display:none}
  .srow{grid-template-columns:62px 1fr 96px;padding:10px 2px}
  .srow .kl{white-space:nowrap;font-size:11.5px}
  .srow .sn{grid-column:1/3}
  .srow .kl{display:block}
}
.tabs{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px}
.tabs button{border:1px solid var(--ring);background:var(--card);border-radius:999px;padding:5px 12px;cursor:pointer;font-size:13px}
.tabs button.on{background:var(--fg);color:var(--bg);border-color:var(--fg)}
.filters{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px;align-items:center}
.filters select{padding:5px 8px;border-radius:8px;border:1px solid var(--ring);background:var(--card)}
.tabdesc{color:var(--fg2);font-size:12.5px;margin:0 0 8px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{color:var(--fg2);font-weight:600;text-align:left;padding:6px 8px;border-bottom:1px solid var(--axis);white-space:nowrap}
td{padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:middle}
tbody tr{cursor:pointer}
tbody tr:hover{background:var(--hover)}
td.num,th.num{text-align:right}
.mini{display:flex;align-items:center;gap:6px;justify-content:flex-end}
.mini .dbar{width:64px;height:8px}.mini .dbar .f{height:8px;border-radius:3px}.mini .dbar .tr{top:3px}
.mini b{width:30px;text-align:right}
.lbl{font-size:11.5px;color:var(--fg2);min-width:52px;text-align:left;white-space:nowrap}
.ev{color:var(--fg2);font-size:12px}
@media (max-width:760px){.hide-sm{display:none}}
.more{margin:10px auto 0;display:block}
details{margin-top:28px}
details summary{cursor:pointer;font-weight:600}
.expl{color:var(--fg2);font-size:13px}
.expl table{font-size:12.5px;margin:8px 0}
.expl td,.expl th{padding:5px 6px}
.note{color:var(--mut);font-size:12px;margin-top:24px}
/* ===== 2026-11 デザイン刷新（トップ画面と共通）：黒／白地、枠線なしのカード、数字は Inter の極太、4指標のメーターは横一本 ===== */
:root{--bg:#f3f4f6;--card:#fff;--fg:#0c0d10;--fg2:#3d4148;--mut:#5b6068;--line:#dfe2e7;--axis:#c0c4cc;--ring:rgba(12,13,16,.13);--hover:rgba(12,13,16,.05);--price:#3d4148}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){
  --bg:#050608;--card:#101216;--fg:#f2f4f8;--fg2:#c6cbd6;--mut:#8f96a3;--line:#23262d;--axis:#30343d;--ring:rgba(255,255,255,.13);--hover:rgba(255,255,255,.06);--price:#c6cbd6}}
:root[data-theme="dark"]{
  --bg:#050608;--card:#101216;--fg:#f2f4f8;--fg2:#c6cbd6;--mut:#8f96a3;--line:#23262d;--axis:#30343d;--ring:rgba(255,255,255,.13);--hover:rgba(255,255,255,.06);--price:#c6cbd6}
body{font-family:Inter,"Hiragino Sans","Hiragino Kaku Gothic ProN","Noto Sans JP",system-ui,-apple-system,"Segoe UI",sans-serif;-webkit-font-smoothing:antialiased}
h1{font-weight:800;letter-spacing:.02em}
.card{border:0;border-radius:14px}
.search input{border:0;border-radius:14px;font-weight:600}
.strip .si .v{font-size:24px;font-weight:800;letter-spacing:-.02em}.strip .si .v small{font-size:13px;letter-spacing:0}
.mktHead{display:flex;align-items:center;gap:12px;margin:18px 0 0}.mktHead h3{margin:0}
.mktHead select{padding:4px 8px;border-radius:8px;border:1px solid var(--ring);background:var(--card);font-size:12.5px}
.search{margin-top:24px}
table.sig tbody tr{cursor:pointer}
.quad{gap:14px 28px}
.quad .q{text-align:left;min-width:0}
.quad .q h4{font-weight:800}
.quad .ro{margin-top:2px;display:flex;align-items:baseline;gap:4px 8px;flex-wrap:wrap}
.quad .ro b{font-size:30px;font-weight:800;letter-spacing:-.03em;line-height:1.1}
.quad .ro .pill{vertical-align:0;margin-left:0}
.quad svg{width:100%;max-width:none;height:18px;margin:5px 0 0}
.quad .qe{display:flex;justify-content:space-between;font-size:10.5px;font-weight:700;margin-top:1px}
.quad .qe span:first-child{color:var(--z0t)}.quad .qe span:last-child{color:var(--z4t)}
.q.q-os .qe span:first-child{color:var(--z4t)!important}.q.q-os .qe span:last-child{color:var(--z0t)!important}
.gauge,.adcard .gauge{max-width:none;height:62px;margin:12px 0 0}
.readout,.adcard .rd{text-align:left;margin-top:8px}
.readout .sc,.adcard .rd .sc{font-size:38px;font-weight:800;letter-spacing:-.03em;line-height:1.1;margin-right:8px}
.readout .pill,.adcard .rd .pill{vertical-align:6px}
#cardT .chips,#cardF .chips{justify-content:flex-start}
@media (min-width:761px){h1{font-size:24px}.quad{grid-template-columns:repeat(4,minmax(0,224px));justify-content:space-between}}
</style>
</head>
<body>
<div class="wrap">
<header>
  <div>
    <h1>売買シグナル</h1>
    <div class="sub" id="sub"></div>
  </div>
  <div class="nav">
    <a href="./index.html">トップ</a>
    <a href="./one/index.html">分析ダッシュボード</a>
    <a href="./charts.html">チャート一覧</a>
    <a href="./fundamentals.html">ファンダメンタル分析</a>
    <button class="btn" id="themeBtn" type="button" aria-label="明るさの切り替え">明暗</button>
  </div>
</header>

<!-- 市場全体（1行） -->
<div class="mktHead"><h3>市場全体</h3><select id="bMk" aria-label="市場"></select></div>
<div id="mktMore">
<div class="card adcard" id="bAD"></div>
<div class="h3row" style="margin:14px 0 6px">
  <button class="btn" id="sectBtn" type="button" aria-expanded="false" aria-controls="sectWrap">業種別 ▾</button></div>
<div id="sectWrap" hidden>
<div class="h3row" style="margin-top:8px"><h3>業種別のシグナル分布</h3>
  <select id="bSort" aria-label="業種の並べ方">
    <option value="t">テクニカル平均が高い順</option><option value="f">ファンダ平均が高い順</option>
    <option value="tb">テクニカル良好比率が高い順</option><option value="fb">ファンダ良好比率が高い順</option>
    <option value="n">銘柄数が多い順</option><option value="name">業種名順</option>
  </select></div>
<p class="tabdesc">帯は左から 避ける・弱い・中立・やや良好・良好 の銘柄数の割合。業種をタップすると、その業種だけの一覧に移ります。</p>
<div class="card sect" style="padding:4px 10px">
  <div class="srow shead"><span class="sn">業種</span><span class="sc2">銘柄数</span><span class="tl">テクニカル</span><span></span><span class="tl">ファンダメンタル</span><span></span></div>
  <div id="sb"></div>
</div>
<div class="leg" id="sLeg" style="margin-top:8px"></div>
</div>
</div>

<div class="search">
  <input id="q" type="search" placeholder="コード・銘柄名で検索（例: 7203、トヨタ）" autocomplete="off" aria-label="銘柄検索">
  <div class="sugg" id="sugg" role="listbox"></div>
</div>

<h3>シグナル一覧</h3>
<div class="tabs" id="tabs"></div>
<p class="tabdesc" id="tabdesc"></p>
<div class="filters">
  <select id="fMk" aria-label="市場"></select>
  <select id="fSc" aria-label="業種"></select>
  <select id="fCap" aria-label="時価総額">
    <option value="">時価総額: すべて</option><option value="1000">1,000億円以上</option>
    <option value="300">300億円以上</option><option value="-300">300億円未満</option>
  </select>
  <span class="meta" id="cnt"></span>
</div>
<p class="scrollhint">← 表は横にスクロールできます（コードと銘柄名は左に固定）→</p>
<div class="card sigwrap" style="padding:4px 6px;overflow-x:auto">
<table class="sig">
  <thead id="th"><tr><th data-k="c">コード</th><th data-k="n">銘柄名</th><th class="hide-sm" data-k="s">業種</th><th class="num hide-sm" data-k="p">株価</th>
  <th class="c" data-k="ts"><span class="lg">テクニカル</span><span class="sm">テク</span></th><th class="c" data-k="tt"><span class="lg">トレンド</span><span class="sm">トレ</span></th>
  <th class="c" data-k="to"><span class="lg">オシレーター</span><span class="sm">オシ</span></th>
  <th class="c" data-k="fs"><span class="lg">ファンダ</span><span class="sm">ファ</span></th><th class="c" data-k="ov">総合</th><th class="hide-sm">イベント</th></tr></thead>
  <tbody id="tb"></tbody>
</table>
</div>
<div class="leg" style="margin-top:8px">
  <span><span class="bd b0">良好</span></span><span><span class="bd b1">やや良</span> やや良好</span><span><span class="bd b2">―</span> 中立</span>
  <span><span class="bd b3">弱い</span></span><span><span class="bd b4">避ける</span></span>
  <span>過去の検証では、効き目は「弱い・避ける」側（下位）に集中し、「良好」の銘柄が市場平均を大きく上回ったわけではありません。</span>
  <span>トレンド列は <span class="bd b1">上昇</span>／<span class="bd b3">下降</span>、オシレーター列は <span class="bd b3">売られすぎ</span>／<span class="bd b1">買われすぎ</span>。塗りつぶしは「強い」側（トレンドは強い上昇・下降、オシレーターは強く売られすぎ・買われすぎ）。列見出しで並べ替え。</span>
</div>
<button class="btn more" id="more" type="button">さらに表示</button>

<details>
<summary>スコアの作り方</summary>
<div class="expl" id="expl"></div>
</details>
<p class="note">このページは手元の株価・決算データから機械的に計算した参考指標です。売買の推奨ではありません。
テクニカルは過去の値動きだけ、ファンダは直近の本決算だけを見ており、今期予想やニュースは反映していません。</p>
</div>
<div class="tip" id="tip"></div>

<script>
const D=/*__DATA__*/null;
const M=D.meta, ROWS=D.rows, BY={};
ROWS.forEach(r=>BY[r.c]=r);
const $=id=>document.getElementById(id);
const NAMES=M.names; // 良好,やや良好,中立,弱い,避ける
const ZV=['--z4','--z3','--z2','--z1','--z0']; // NAMES と同じ並び
const css=v=>getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const fmt=(x,d=0)=>x==null?'—':Number(x).toLocaleString('ja-JP',{minimumFractionDigits:d,maximumFractionDigits:d});
const sgn=(x,d=0)=>x==null?'—':(x>0?'+':x<0?'−':'')+fmt(Math.abs(x),d);
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

function lvl(s,k){ if(s==null)return -1; const [sb,b,se,ss]=M.levels[k];
  return s>=sb?0:s>=b?1:s>se?2:s>ss?3:4; }
const TRN=['強い上昇トレンド','上昇トレンド','横ばい','下降トレンド','強い下降トレンド'];
const OSN=['強く売られすぎ','売られすぎ','中立','買われすぎ','強く買われすぎ'];
// メーター両端の言葉（左＝マイナス側、右＝プラス側）
const ENDS={t:['避ける','良好'],f:['避ける','良好'],tr:['下降','上昇'],os:['買われすぎ','売られすぎ']};
function pillHTML(s,k,names){ const i=lvl(s,k); if(i<0)return '<span class="na">評価できません</span>';
  // オシレーター系は水準の色（買われすぎ＝赤、売られすぎ＝緑）。名前は i、色は j で選ぶ
  const j=k==='os'?4-i:i;
  const col=j===0?'var(--z4t)':j===1?'var(--z4t)':j===3?'var(--z0t)':j===4?'var(--z0t)':'var(--fg2)';
  const bg=j===0?'var(--z4)':j===4?'var(--z0)':'transparent';
  const fg=(j===0||j===4)?'#fff':col;
  return `<span class="pill" style="border-color:${j===0?'var(--z4)':j===4?'var(--z0)':col};background:${bg};color:${fg}">${(names||NAMES)[i]}</span>`; }

/* ---------------- 速度メーター ---------------- */
const CX=130,CY=132,R=96,SW=22;
const ang=s=>Math.PI*(1-(s+100)/200);           // −100→左(π)、+100→右(0)
const pt=(s,rr)=>[CX+rr*Math.cos(ang(s)),CY-rr*Math.sin(ang(s))];
function arc(a,b,rr){ const [x1,y1]=pt(a,rr),[x2,y2]=pt(b,rr);
  return `M${x1.toFixed(2)},${y1.toFixed(2)} A${rr},${rr} 0 0 1 ${x2.toFixed(2)},${y2.toFixed(2)}`; }
// 横一本のメーター（4指標用）。左端＝-100、右端＝+100。色の区切りは判定のしきい値（M.levels）と同じ
function meter(svg,s,k){
  const [sb,b,se,ss]=M.levels[k],cuts=[-100,ss,se,b,sb,100],zc=(k==='os'?['--z4','--z3','--z2','--z1','--z0']:['--z0','--z1','--z2','--z3','--z4']);
  const X=v=>4+(Math.max(-100,Math.min(100,v))+100)/200*92;let h='';
  for(let i=0;i<5;i++){const a=X(cuts[i])+(i?.4:0),e=X(cuts[i+1])-(i<4?.4:0);
    h+=`<rect x="${a.toFixed(2)}%" y="6" width="${Math.max(0,e-a).toFixed(2)}%" height="6" fill="var(${zc[i]})"/>`;}
  const on=s!=null,to=on?X(s):50;
  h+=`<circle class="needle" cy="9" r="7" fill="var(--fg)" stroke="var(--card)" stroke-width="3"${on?'':' opacity=".25"'}/>`;
  const prev=+(svg.dataset.pos||50);svg.innerHTML=h;svg.removeAttribute('viewBox');svg.dataset.pos=to;
  svg.setAttribute('aria-label',`スコア ${s==null?'なし':s}`);
  const nd=svg.querySelector('.needle'),set=a=>nd.setAttribute('cx',a.toFixed(2)+'%');
  if(matchMedia('(prefers-reduced-motion: reduce)').matches){set(to);return;}
  const ease=t=>1-Math.pow(1-t,3),t0=performance.now();set(prev);
  const step=now=>{const t=Math.min(1,(now-t0)/700);set(prev+(to-prev)*ease(t));if(t<1)requestAnimationFrame(step);};requestAnimationFrame(step);}
// 「詳しく」用の横一本のメーター。上に区切りの数値、下に区間の名前（隣と重ならないよう2段に振り分け）
function meterFull(svg,s,k,o){
  // rev: 騰落レシオは水準の色（過熱＝赤、売られすぎ＝緑）
  const [sb,b,se,ss]=M.levels[k],cuts=[-100,ss,se,b,sb,100],zc=(o.rev||k==='os')?['--z4','--z3','--z2','--z1','--z0']:['--z0','--z1','--z2','--z3','--z4'];
  const zn=o.names||[NAMES[4],NAMES[3],NAMES[2],NAMES[1],NAMES[0]];
  const X=v=>2+(Math.max(-100,Math.min(100,v))+100)/200*96;let h='';
  for(let i=0;i<5;i++){const a=X(cuts[i])+(i?.3:0),e=X(cuts[i+1])-(i<4?.3:0);
    h+=`<rect x="${a.toFixed(2)}%" y="18" width="${Math.max(0,e-a).toFixed(2)}%" height="10" fill="var(${zc[i]})"/>`;
    const tx=i===0?X(-100):i===4?X(100):(X(cuts[i])+X(cuts[i+1]))/2, anc=i===0?'start':i===4?'end':'middle';
    h+=`<text x="${tx.toFixed(2)}%" y="${i%2?57:45}" text-anchor="${anc}" font-size="10.5" font-weight="600" fill="var(--fg2)">${zn[i]}</text>`;}
  cuts.forEach((c,i)=>{h+=`<text x="${X(c).toFixed(2)}%" y="11" text-anchor="${i===0?'start':i===5?'end':'middle'}" font-size="9" fill="var(--mut)">${o.tick?o.tick(c):(c>0?'+'+c:c)}</text>`;});
  const on=s!=null,to=on?X(s):50;
  h+=`<circle class="needle" cy="23" r="9" fill="var(--fg)" stroke="var(--card)" stroke-width="3"${on?'':' opacity=".25"'}/>`;
  const prev=+(svg.dataset.pos||50);svg.innerHTML=h;svg.removeAttribute('viewBox');svg.dataset.pos=to;
  svg.setAttribute('aria-label',`スコア ${s==null?'なし':s}`);
  const nd=svg.querySelector('.needle'),set=a=>nd.setAttribute('cx',a.toFixed(2)+'%');
  if(matchMedia('(prefers-reduced-motion: reduce)').matches){set(to);return;}
  const ease=t=>1-Math.pow(1-t,3),t0=performance.now();set(prev);
  const step=now=>{const t=Math.min(1,(now-t0)/700);set(prev+(to-prev)*ease(t));if(t<1)requestAnimationFrame(step);};requestAnimationFrame(step);}
function gauge(svg,s,k,opt){
  const o=(opt&&typeof opt==='object')?opt:{mini:!!opt}, mini=o.mini;
  if(mini&&o.ends){meter(svg,s,k);return;}
  if(!mini){meterFull(svg,s,k,o);return;}
  const [sb,b,se,ss]=M.levels[k];
  const cuts=[-100,ss,se,b,sb,100];                       // 左から 避ける…良好
  const zc=(k==='os'?['--z4','--z3','--z2','--z1','--z0']:['--z0','--z1','--z2','--z3','--z4']), zn=o.names||[NAMES[4],NAMES[3],NAMES[2],NAMES[1],NAMES[0]];
  const gap=1.1; let h='';
  for(let i=0;i<5;i++){
    const a=cuts[i]+(i?gap:0), e=cuts[i+1]-(i<4?gap:0);
    h+=`<path d="${arc(a,e,R)}" stroke="var(${zc[i]})" stroke-width="${SW}" fill="none"/>`;
    if(mini)continue;
    // 両端の区間は弧の外側へ寄せ、文字が弧にかからないようにする
    const m=(cuts[i]+cuts[i+1])/2, [lx,ly]=pt(m,R+SW/2+(i===0||i===4?5:13));
    const anc=i===0?'end':i===4?'start':'middle';
    h+=`<text x="${lx.toFixed(1)}" y="${(ly+3).toFixed(1)}" text-anchor="${anc}" font-size="10" fill="var(--fg2)">${zn[i]}</text>`;
  }
  // 目盛り（区切りの数値）
  if(!mini) cuts.forEach(c=>{ const [x1,y1]=pt(c,R-SW/2-2),[x2,y2]=pt(c,R-SW/2-7);
    h+=`<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="var(--axis)" stroke-width="1.5"/>`;
    const [tx,ty]=pt(c,R-SW/2-16);
    h+=`<text x="${tx.toFixed(1)}" y="${(ty+3).toFixed(1)}" text-anchor="middle" font-size="8.5" fill="var(--mut)">${o.tick?o.tick(c):(c>0?'+'+c:c)}</text>`; });
  const on=s!=null, deg=on?Math.max(-100,Math.min(100,s))*0.9:0;
  h+=`<g class="needle"${on?'':' opacity=".25"'}>
      <path d="M${CX-5},${CY} L${CX},${CY-R+6} L${CX+5},${CY} Z" fill="var(--fg)"/></g>
      <circle cx="${CX}" cy="${CY}" r="9" fill="var(--fg)"/><circle cx="${CX}" cy="${CY}" r="3.5" fill="var(--card)"/>`;
  // 針は SVG の rotate(角度 中心x 中心y) で回す（viewBox を切り詰めても中心がずれない）。
  // 描き直しでも前回の角度から少し行き過ぎて戻るように動かす
  const prev=+(svg.dataset.deg||0);
  svg.innerHTML=h; svg.setAttribute('aria-label',`スコア ${s==null?'なし':s}`);
  if(mini&&o.ends){  // 両端の言葉（何のメーターかがひと目で分かるように）
    svg.insertAdjacentHTML('beforeend',`<text x="${CX-R-SW/2}" y="${CY+24}" text-anchor="start" font-size="15" fill="var(--z0t)" font-weight="700">${o.ends[0]}</text>
      <text x="${CX+R+SW/2}" y="${CY+24}" text-anchor="end" font-size="15" fill="var(--z4t)" font-weight="700">${o.ends[1]}</text>`); }
  if(mini) svg.setAttribute('viewBox',o.ends?'16 18 228 148':'16 18 228 128');
  const nd=svg.querySelector('.needle'); svg.dataset.deg=deg;
  const set=a=>nd.setAttribute('transform',`rotate(${a.toFixed(2)} ${CX} ${CY})`);
  const ease=t=>{const c=1.4;return 1+(c+1)*Math.pow(t-1,3)+c*Math.pow(t-1,2);};  // easeOutBack
  if(matchMedia('(prefers-reduced-motion: reduce)').matches){set(deg);return;}
  const t0=performance.now(), dur=800; set(prev);
  const step=now=>{const t=Math.min(1,(now-t0)/dur); set(prev+(deg-prev)*ease(t)); if(t<1)requestAnimationFrame(step);};
  requestAnimationFrame(step);
}

/* ---------------- 内訳 ---------------- */
function dbar(v){ if(v==null)return '<div class="dbar"><div class="tr"></div><div class="ax"></div></div>';
  const w=Math.abs(v)*50, left=v>=0?50:50-w, c=v>=0.001?'var(--z4)':v<=-0.001?'var(--z0)':'var(--axis)';
  return `<div class="dbar"><div class="tr"></div><div class="f" style="left:${left}%;width:${Math.max(w,1)}%;background:${c}"></div><div class="ax"></div></div>`; }
function part(name,sub,v,desc){
  return `<div class="part"><div class="pn">${name}<small>${sub}</small></div>${dbar(v)}
   <div class="pv">${v==null?'<span class="na">—</span>':sgn(v*100)}</div><div class="pd">${desc}</div></div>`; }
const pct=x=>x==null?'—':sgn(x,1)+'%';
const TNAME={hi52:['52週高値への近さ','高値圏'],lv:['値動きの小ささ','低ボラ'],ma:['移動平均','トレンド'],macd:['MACD','トレンド'],ichi:['一目均衡表','トレンド'],rsi:['RSI(14)','逆張り'],bb:['ボリンジャー','逆張り'],vol:['出来高','勢いの裏付け']};
const FNAME={val:['割安度','PER・PBR'],prof:['収益性','ROE'],grow:['成長性','増収率'],safe:['安全性','自己資本'],fs:['Fスコア','財務改善'],cash:['キャッシュ','FCF']};
const TKEYS=Object.keys(M.tw), FKEYS=Object.keys(M.fw);
function trObj(a){ if(!a)return null; const [dev25,dev75,dev200,up25,hist,rise,cloud,tk,rsi,pb,upr,surge,near,hi,vol]=a;
  return {hi52:{near,hi},lv:{vol},ma:{dev25,dev75,dev200,up25},macd:{hist,rise},ichi:{cloud,tk},rsi:{rsi},bb:{pb},vol:{upr,surge}}; }
function frObj(a){ if(!a)return null; const [per,pbr,vg,base,roe,pg,opm,gr,cagr,gg,eq,sg,fs,fcfy,dy,fin,evm]=a;
  return {val:{per,pbr,evm,g:vg,base},prof:{roe,g:pg,opm},grow:{gr,cagr,g:gg},safe:{eq,g:sg},fs:{fs},cash:{fcfy,dy,fin}}; }
function tDesc(k,x){ if(!x)return '';
  switch(k){
  case 'hi52': return `終値は52週高値（${fmt(x.hi,x.hi<100?1:0)}円）の ${fmt(x.near,1)}%（97%以上で+1、67%以下で−1）`;
  case 'lv': return `60日の値動き 年率${fmt(x.vol,1)}%（15%以下で+1、55%以上で−1）`;
  case 'ma': return `25日線乖離 ${pct(x.dev25)}・75日線 ${pct(x.dev75)}・200日線 ${pct(x.dev200)}・25日線は${x.up25==null?'—':x.up25?'上向き':'下向き'}`;
  case 'macd': return `ヒストグラム ${x.hist==null?'—':(x.hist>0?'プラス':'マイナス')}（株価比 ${pct(x.hist)}）・${x.rise==null?'—':x.rise?'拡大／改善中':'縮小／悪化中'}`;
  case 'ichi': return `株価は雲の${x.cloud==null?'—':x.cloud>0?'上':x.cloud<0?'下':'中'}・転換線${x.tk==null?'—':x.tk>0?'＞':x.tk<0?'＜':'＝'}基準線`;
  case 'rsi': return `RSI ${fmt(x.rsi,1)}（30以下で売られすぎ＝買い、70以上で買われすぎ＝売り）`;
  case 'bb': return `%B ${fmt(x.pb)}%（0%＝−2σ、100%＝+2σ）`;
  case 'vol': return `直近20日の上昇日出来高比率 ${fmt(x.upr)}%・5日/25日出来高 ${fmt(x.surge,2)}倍`; } }
function fDesc(k,x,r){ if(!x)return ''; const g=v=>v==null?'':`（評価${v}）`;
  switch(k){
  case 'val': return `PER ${fmt(x.per,1)}倍・PBR ${fmt(x.pbr,2)}倍${x.evm!=null?'・EV/EBITDA '+fmt(x.evm,1)+'倍':''}${g(x.g)}${x.base?'・'+esc(x.base)+'基準':''}`;
  case 'prof': return `ROE ${fmt(x.roe,1)}%・営業利益率 ${fmt(x.opm,1)}%${g(x.g)}`;
  case 'grow': return `増収率 ${pct(x.gr)}・売上高CAGR ${pct(x.cagr)}${g(x.g)}`;
  case 'safe': return `自己資本比率 ${fmt(x.eq,1)}%${g(x.g)}`;
  case 'fs': return x.fs==null?'算出対象外':`${fmt(x.fs)} / 9 点`;
  case 'cash': return x.fin?'金融業のため使いません':`FCF利回り ${fmt(x.fcfy,1)}%・配当利回り ${fmt(x.dy,2)}%`; } }

/* ---------------- メーター推移（株価とスコア、横軸共通） ---------------- */
function spark(el,r){
  const hp=(r.hp||[]).map(v=>r.hp0+v*r.hpk), hs=r.hs||[], n=hp.length; if(n<2){el.innerHTML='';return;}
  const W=320,H1=46,H2=56,G=8,H=H1+G+H2, X=i=>i/(n-1)*W;
  const pmin=Math.min(...hp),pmax=Math.max(...hp), PY=v=>H1-2-(v-pmin)/((pmax-pmin)||1)*(H1-4);
  const SY=v=>H1+G+H2/2-v/100*(H2/2);
  const [sb,b,se,ss]=M.levels.t;
  let p='',s=''; hp.forEach((v,i)=>p+=(i?'L':'M')+X(i).toFixed(1)+','+PY(v).toFixed(1));
  let pen=false; hs.forEach((v,i)=>{ if(v==null){pen=false;return;} s+=(pen?'L':'M')+X(i).toFixed(1)+','+SY(v).toFixed(1); pen=true; });
  el.innerHTML=`<div class="lb"><span>株価（上）とスコア（下）・${n}営業日</span><span>${fmt(pmin)}〜${fmt(pmax)}円</span></div>
  <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" style="height:${H}px">
    <rect x="0" y="${SY(100)}" width="${W}" height="${SY(b)-SY(100)}" fill="var(--z3)" opacity=".18"/>
    <rect x="0" y="${SY(se)}" width="${W}" height="${SY(-100)-SY(se)}" fill="var(--z1)" opacity=".22"/>
    <line x1="0" x2="${W}" y1="${SY(0)}" y2="${SY(0)}" stroke="var(--axis)" stroke-width="1" vector-effect="non-scaling-stroke"/>
    <path d="${p}" fill="none" stroke="var(--price)" stroke-width="1.6" vector-effect="non-scaling-stroke"/>
    <path d="${s}" fill="none" stroke="var(--acc)" stroke-width="2" vector-effect="non-scaling-stroke"/>
    <line class="xh" x1="0" x2="0" y1="0" y2="${H}" stroke="var(--mut)" stroke-width="1" vector-effect="non-scaling-stroke" style="display:none"/>
    <rect x="0" y="0" width="${W}" height="${H}" fill="transparent"/>
  </svg><div class="lb"><span>${n-1}日前</span><span>赤帯＝やや良好以上・緑帯＝弱い以下</span><span>最新</span></div>`;
  const svg=el.querySelector('svg'), xh=svg.querySelector('.xh'), tip=$('tip');
  const move=e=>{ const bb=svg.getBoundingClientRect(), cx=(e.touches?e.touches[0].clientX:e.clientX);
    const i=Math.max(0,Math.min(n-1,Math.round((cx-bb.left)/bb.width*(n-1))));
    xh.setAttribute('x1',X(i));xh.setAttribute('x2',X(i));xh.style.display='';
    const ago=n-1-i;
    tip.innerHTML=`<b>${ago?ago+'営業日前':'最新日'}</b><br>株価 ${fmt(hp[i],hp[i]<100?1:0)}円<br>スコア ${hs[i]==null?'—':sgn(hs[i])}（${hs[i]==null?'—':NAMES[lvl(hs[i],'t')]}）`;
    tip.style.display='block';
    const ty=(e.touches?e.touches[0].clientY:e.clientY);
    tip.style.left=Math.min(innerWidth-tip.offsetWidth-8,cx+12)+'px'; tip.style.top=(ty-tip.offsetHeight-12)+'px'; };
  const out=()=>{xh.style.display='none';tip.style.display='none';};
  svg.addEventListener('pointermove',move); svg.addEventListener('pointerleave',out);
  svg.addEventListener('touchmove',move,{passive:true}); svg.addEventListener('touchend',out);
}

/* ---------------- トレンド系／オシレーター系 ---------------- */
function trendOscComment(tt,to){
  const t=lvl(tt,'tr'), o=lvl(to,'os'); if(t<0||o<0)return ['判定できません','データが足りません。'];
  // トレンドが強いほどオシレーターは逆側に振れやすい（上昇中はRSIが高い）ので、
  // 押し目／戻りは「オシレーターが中心線（0）より逆張り側まで戻ったか」で判定する
  const up=t<=1, dn=t>=3, cheap=o<=1, hot=o>=3;
  if(up&&to>=0) return ['上昇トレンド中の押し目','上昇基調の中で過熱が抜け、RSI・ボリンジャーが中心より下まで調整した形。順張りの買い場になりやすい局面です。'];
  if(up&&hot)   return ['上昇トレンドだが過熱','勢いはあるものの短期的には買われすぎ。高値づかみに注意。'];
  if(up)        return ['上昇トレンド','上向きの流れで、行き過ぎた過熱感はありません。'];
  if(dn&&to<=0) return ['下降トレンド中の戻り','下降基調の中で一時的に戻した形。戻り売りが出やすい局面です。'];
  if(dn&&cheap) return ['下降トレンド中の売られすぎ','反発はあり得ますが、流れは下向き。逆張りは慎重に。'];
  if(dn)        return ['下降トレンド','下向きの流れが続いています。'];
  if(cheap)     return ['方向感なし・売られすぎ','トレンドははっきりしませんが、短期的には売られすぎ。'];
  if(hot)       return ['方向感なし・買われすぎ','トレンドははっきりしませんが、短期的には買われすぎ。'];
  return ['方向感なし','トレンド・過熱感ともに中立圏です。'];
}
function oscPill(s){ return pillHTML(s,'os',OSN); }
/* テクニカルとファンダを合わせた総合判定: [ラベル, 段階0〜4（買い候補…避ける）] */
function overall(r){
  const d=(s,k)=>{const i=lvl(s,k); return i<0?null:i<=1?1:i>=3?-1:0;};
  const t=d(r.ts,'t'), f=d(r.fs,'f');
  if(t==null&&f==null) return ['評価なし',-1];
  if(f==null) return t>0?['やや良好',1]:t<0?['注意',3]:['中立',2];
  const a=(t||0)+f;
  if(a===2) return ['買い候補',0]; if(a===1) return ['やや良好',1];
  if(a===-2) return ['避ける',4]; if(a===-1) return ['注意',3];
  return t!==0&&f!==0?['様子見',2]:['中立',2];
}
function ovScore(r){ return (r.ts??0)+(r.fs??0); }
/* ---------------- 売買の目安（IN・利確・損切り） ---------------- */
const yen=v=>v==null?'—':fmt(v,v<100?1:0)+'円';
function planRender(r){
  const el=$('plan'), lv=r.lv?{...r.lv}:null;
  if(lv) ['inB','stopB','t1B','t2B','trailB','trigB'].forEach(k=>{ if(lv[k]!=null) lv[k]=M.bs[lv[k]]; });
  if(!lv){ el.innerHTML='<div class="ph"><h4>売買の目安</h4></div><p class="na">値動きのデータが足りないため出せません。</p>'; return; }
  const c=r.p, pc=v=>v==null?'':sgn((v/c-1)*100,1)+'%';
  const fweak=lvl(r.fs,'f')>=3;
  let tag,txt;
  if(lv.mode==='now'){ tag=['IN可','b0'];
    txt=`<b>${yen(lv.in[0])}〜${yen(lv.in[1])}</b>（${esc(lv.inB)}）の現値付近でIN可。利確の目安は <b>${yen(lv.t1)}</b>（${esc(lv.t1B)}）、次に ${yen(lv.t2)}。<b>${yen(lv.stop)}</b> を割ったら損切り。`; }
  else if(lv.mode==='dip'){ tag=['押し目待ち','b1'];
    txt=`<b>${yen(lv.in[0])}〜${yen(lv.in[1])}</b>（${esc(lv.inB)}）で指値のIN。利確の目安は <b>${yen(lv.t1)}</b>（${esc(lv.t1B)}）、次に ${yen(lv.t2)}。IN後 <b>${yen(lv.stop)}</b> を割ったら損切り。`; }
  else { tag=['様子見','b3'];
    txt=`下降トレンド中のためINは待ち。${lv.trig?`<b>${yen(lv.trig)}</b>（${esc(lv.trigB)}）を終値で上抜けたら検討。`:'トレンド転換を確認してから。'}保有中なら戻りの <b>${yen(lv.t1)}</b>（${esc(lv.t1B)}）付近で売り、<b>${yen(lv.trail)}</b> 割れで手じまい。`; }
  if(lv.rr!=null&&lv.rr<1&&lv.mode!=='wait') txt+=` リスクリワードが${fmt(lv.rr,1)}倍と1倍未満で、利幅に比べて損切り幅が大きめ。`;
  if(lv.hot) txt+=' <b>短期的に強く買われすぎ</b>のため、保有中なら一部利確も選択肢。';
  if(fweak) txt+=' ファンダが弱い側なので、長く持つより短期売買向き。';
  const wait=lv.mode==='wait';
  const row=(cls,rl,pr,pcv,bs)=>`<div class="rl ${cls}">${rl}</div><div class="pr ${cls}">${pr}</div><div class="pc ${cls}">${pcv}</div><div class="bs">${bs}</div>`;
  let t=wait?row('x','戻り売りの目安',yen(lv.t1),pc(lv.t1),esc(lv.t1B))
       :row('x','利確2',yen(lv.t2),pc(lv.t2),esc(lv.t2B))+row('x','利確1',yen(lv.t1),pc(lv.t1),esc(lv.t1B)+(lv.rr!=null?`・リスクリワード ${fmt(lv.rr,1)}倍`:''));
  t+=row('x cur','現在値',yen(c),'',r.d+' 終値');
  if(lv.in) t+=row('x','IN目安',`${yen(lv.in[0])}〜${yen(lv.in[1])}`,pc((lv.in[0]+lv.in[1])/2),esc(lv.inB));
  if(lv.trig) t+=row('x','転換ライン',yen(lv.trig),pc(lv.trig),esc(lv.trigB)+'を終値で上抜け');
  if(lv.stop!=null) t+=row('x','損切り',yen(lv.stop),pc(lv.stop),esc(lv.stopB));
  t+=row('x','保有中の手じまい',yen(lv.trail),pc(lv.trail),'終値でここを割ったら（'+esc(lv.trailB)+'）');
  el.innerHTML=`<div class="ph"><h4>売買の目安</h4><span class="bd ${tag[1]}" style="min-width:auto;padding:2px 10px">${tag[0]}</span>
     <span class="meta">ATR（1日の値幅の目安）${fmt(lv.atr,lv.atr<10?1:0)}円・${fmt(lv.atrp,1)}%</span></div>
   <div id="lvChart" class="lvc"></div>
   <button class="btn" id="planBtn" type="button" aria-expanded="${PLAN_OPEN}" aria-controls="planDet">${PLAN_OPEN?'目安の詳細を閉じる ▴':'目安の詳細 ▾'}</button>
   <div id="planDet"${PLAN_OPEN?'':' hidden'}>
     <p class="ps">${txt}</p>
     <div class="lvt">${t}</div>
     <p class="caveat">移動平均・ボリンジャー・一目・直近高安値とATRから機械的に出した目安です。決算発表や地合いの急変は考えていません。売買の推奨ではありません。</p>
   </div>`;
  $('planBtn').addEventListener('click',()=>{ PLAN_OPEN=!PLAN_OPEN; $('planDet').hidden=!PLAN_OPEN;
    $('planBtn').setAttribute('aria-expanded',PLAN_OPEN); $('planBtn').textContent=PLAN_OPEN?'目安の詳細を閉じる ▴':'目安の詳細 ▾'; });
  const box=$('lvChart'); box.innerHTML='<p class="na" style="padding:40px 0;text-align:center">チャートを読み込み中…</p>';
  loadChartData(r.c,d=>{ if(CUR!==r.c)return; if(d) candleChart(box,r,lv,d); else levelChart(box,r,lv); });
}
/* 銘柄ごとのチャートデータ（sig/<コード>.js）を必要なときだけ読み込む */
const SIGDATA={}, SIGWAIT={};
window.SIGC=(code,d)=>{ SIGDATA[code]=d; (SIGWAIT[code]||[]).forEach(f=>f(d)); delete SIGWAIT[code]; };
function loadChartData(code,cb){
  if(SIGDATA[code]!==undefined) return cb(SIGDATA[code]);
  (SIGWAIT[code]=SIGWAIT[code]||[]).push(cb); if(SIGWAIT[code].length>1)return;
  const sc=document.createElement('script'); sc.src='sig/'+code+'.js?v='+M.built.replace(/\D/g,'');
  sc.onerror=()=>{ SIGDATA[code]=null; (SIGWAIT[code]||[]).forEach(f=>f(null)); delete SIGWAIT[code]; };
  document.head.appendChild(sc);
}
let SHOW_ICHI=true, SHOW_LV=true;
/* ローソク足＋一目均衡表＋出来高に、売買の目安を重ねる */
function candleChart(el,r,lv,D){
  const W=Math.max(300,Math.round(el.clientWidth||600)), narrow=W<520;
  // スマホ幅では直近60本に絞る（ろうそくが細くなりすぎないように）
  const cut=narrow?Math.max(0,D.c.length-60):0;
  const P=a=>a.slice(cut).map(x=>x==null?null:D.p0+x*D.pk);
  const o=P(D.o),h=P(D.h),l=P(D.l),c=P(D.c),tk=P(D.tk),kj=P(D.kj),sa=P(D.sa),sb=P(D.sb), vol=D.v.slice(cut).map(x=>x*D.vk), dd=D.d.slice(cut), n=c.length, F=sa.length;
  // 遅行スパンは切った後ろの終値を使う
  const wait=lv.mode==='wait', cur=r.p;
  // 左の縦軸の数値の幅（一番大きい価格の桁数から）
  const maxP=Math.max(cur,...h.filter(x=>x!=null)), dec=maxP<100;
  // 出来高の目盛り（万株・億株）。数値の幅も左余白の計算に使う
  const vfmt=v=>v>=1e8?fmt(v/1e8,v%1e8?1:0)+'億':v>=1e4?fmt(v/1e4,v%1e4&&v<1e5?1:0)+'万':fmt(v);
  const vmax=Math.max(...vol)||1, vs=niceStep(vmax/2), vticks=[]; for(let v=vs; v<=vmax*1.0001; v+=vs) vticks.push(v);
  const tw=t=>[...String(t)].reduce((a,ch)=>a+(/[^\x00-\x7f]/.test(ch)?10:6.2),0);
  const L=Math.ceil(Math.max(30,tw(fmt(maxP,dec?1:0)),...vticks.map(v=>tw(vfmt(v)))))+10, LB=narrow?100:118, T=10, PH=narrow?220:270, GAP=10, VH=narrow?52:70, B=18, H=T+PH+GAP+VH+B;
  const PW=W-L-LB, slot=PW/F, X=i=>L+slot*(i+0.5);
  const lines=!SHOW_LV?[]:(wait
      ?[['転換',lv.trig,'var(--fg2)','5 4'],['戻り売り',lv.t1,'var(--fg)','5 4'],['手じまい',lv.trail,'var(--fg)','2 3']]
      :[['利確2',lv.t2,'var(--z4)','6 4'],['利確1',lv.t1,'var(--z4)','6 4'],['損切り',lv.stop,'var(--fg)',''],['手じまい',lv.trail,'var(--fg)','2 3']])
      .filter(x=>x[1]!=null);
  if(SHOW_LV&&wait&&lv.trig!=null&&lv.trig===lv.t1) lines.splice(0,2,['転換/戻り',lv.t1,'var(--fg)','5 4']);
  let core=h.concat(l).concat([cur]);
  if(SHOW_ICHI) core=core.concat(tk,kj,sa,sb);
  if(SHOW_LV) core=core.concat(lv.in||[]).concat(lines.filter(x=>x[0]!=='利確2').map(x=>x[1]));
  core=core.filter(x=>x!=null&&isFinite(x));
  let lo=Math.min(...core), hi=Math.max(...core); const span=hi-lo||cur*0.05;
  lines.forEach(x=>{ if(x[1]>hi&&x[1]<=hi+span*0.35)hi=x[1]; });
  lo-=span*0.04; hi+=span*0.04;
  const Y=v=>T+(hi-v)/(hi-lo)*PH, inR=v=>v>=lo&&v<=hi;
  let g='';
  const stp=niceStep((hi-lo)/5);
  for(let v=Math.ceil(lo/stp)*stp; v<=hi; v+=stp) g+=`<line x1="${L}" x2="${L+PW}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--line)"/>
      <text x="${L-5}" y="${Y(v)+3.5}" font-size="10" fill="var(--mut)" text-anchor="end">${fmt(v,stp<1?1:0)}</text>`;
  g+=`<line x1="${L}" x2="${L}" y1="${T}" y2="${T+PH}" stroke="var(--axis)"/>`;
  g+=`<line x1="${X(n-1)+slot/2}" x2="${X(n-1)+slot/2}" y1="${T}" y2="${T+PH}" stroke="var(--line)" stroke-dasharray="2 3"/>`;
  const pl=(a,col,w,dash)=>{let d='',pen=false;a.forEach((v,i)=>{if(v==null||!isFinite(v)){pen=false;return;}d+=(pen?'L':'M')+X(i).toFixed(1)+','+Y(v).toFixed(1);pen=true;});
      return `<path d="${d}" fill="none" stroke="${col}" stroke-width="${w}"${dash?` stroke-dasharray="${dash}"`:''}/>`;};
  if(SHOW_ICHI){
    // 雲（先行スパン1が上＝陽雲、2が上＝陰雲）。26日先まで描く
    for(let i=0;i<F-1;i++){ const a1=sa[i],b1=sb[i],a2=sa[i+1],b2=sb[i+1]; if([a1,b1,a2,b2].some(x=>x==null))continue;
      const up=(a1+a2)>=(b1+b2);
      g+=`<path d="M${X(i)},${Y(a1)} L${X(i+1)},${Y(a2)} L${X(i+1)},${Y(b2)} L${X(i)},${Y(b1)} Z" fill="${up?'var(--cloudU)':'var(--cloudD)'}" opacity=".4"/>`; }
    g+=pl(sa,'var(--cloudU)',1)+pl(sb,'var(--cloudD)',1);
    const ch=c.map((_,i)=>i+26<n?c[i+26]:null);   // 遅行スパン: 終値を26本前の位置に
    g+=pl(ch,'var(--chikou)',1.2)+pl(tk,'var(--tenkan)',1.4)+pl(kj,'var(--kijun)',1.6);
  }
  if(SHOW_LV&&lv.in){ const y1=Y(Math.min(hi,lv.in[1])), y2=Y(Math.max(lo,lv.in[0]));
    g+=`<rect x="${L}" y="${y1}" width="${PW}" height="${Math.max(3,y2-y1)}" fill="var(--z3)" opacity=".3"/>`; }
  lines.forEach(([nm,v,col,dash])=>{ if(!inR(v))return;
    g+=`<line x1="${L}" x2="${L+PW}" y1="${Y(v)}" y2="${Y(v)}" stroke="${col}" stroke-width="${nm==='損切り'?2:1.5}"${dash?` stroke-dasharray="${dash}"`:''}/>`; });
  // ローソク足（陽線＝赤、陰線＝緑。個別チャートと同じ色）
  const bw=Math.max(1.5,slot*0.62);
  for(let i=0;i<n;i++){ if(c[i]==null)continue; const up=c[i]>=o[i], col=up?'var(--candleU)':'var(--candleD)';
    const yt=Y(Math.max(o[i],c[i])), yb=Y(Math.min(o[i],c[i]));
    g+=`<line x1="${X(i)}" x2="${X(i)}" y1="${Y(h[i])}" y2="${Y(l[i])}" stroke="${col}" stroke-width="1"/>
        <rect x="${X(i)-bw/2}" y="${yt}" width="${bw}" height="${Math.max(1,yb-yt)}" fill="${col}"/>`; }
  const vt=T+PH+GAP;
  g+=`<line x1="${L}" x2="${L+PW}" y1="${vt+VH}" y2="${vt+VH}" stroke="var(--axis)"/>
      <line x1="${L}" x2="${L}" y1="${vt}" y2="${vt+VH}" stroke="var(--axis)"/>
      <text x="${L-5}" y="${vt+VH+3.5}" font-size="10" fill="var(--mut)" text-anchor="end">0</text>`;
  vticks.forEach(v=>{ const y=vt+VH-v/vmax*VH;
    g+=`<line x1="${L}" x2="${L+PW}" y1="${y}" y2="${y}" stroke="var(--line)" stroke-dasharray="2 3"/>
        <text x="${L-5}" y="${y+3.5}" font-size="10" fill="var(--mut)" text-anchor="end">${vfmt(v)}</text>`; });
  for(let i=0;i<n;i++){ const hh=vol[i]/vmax*VH; if(hh<=0)continue;
    g+=`<rect x="${X(i)-bw/2}" y="${vt+VH-hh}" width="${bw}" height="${hh}" fill="${c[i]>=o[i]?'var(--candleU)':'var(--candleD)'}" opacity=".55"/>`; }
  g+=`<text x="${L+4}" y="${vt+9}" font-size="10" fill="var(--mut)">出来高（株）</text>`;
  const labs=lines.map(([nm,v,col])=>({nm,v,col,y:inR(v)?Y(v):(v>hi?T+4:T+PH-4),out:!inR(v)}));
  if(SHOW_LV&&lv.in) labs.push({txt:`IN ${fmt(lv.in[0])}〜`,col:'var(--z3)',y:(Y(Math.min(hi,lv.in[1]))+Y(Math.max(lo,lv.in[0])))/2,zone:1});
  labs.push({nm:'現在',v:cur,col:'var(--fg)',y:Y(cur),cur:1});
  labs.sort((a,b)=>a.y-b.y);
  const gap=13; for(let k=1;k<labs.length;k++) if(labs[k].y-labs[k-1].y<gap) labs[k].y=labs[k-1].y+gap;
  const over=labs.length?labs[labs.length-1].y-(T+PH):0; if(over>0) labs.forEach(x=>x.y-=over);
  for(let k=labs.length-2;k>=0;k--) if(labs[k+1].y-labs[k].y<gap) labs[k].y=labs[k+1].y-gap;
  labs.forEach(x=>{ const tx=L+PW+8, txt=x.txt||`${x.out?(x.v>hi?'↑':'↓'):''}${x.nm} ${fmt(x.v,x.v<100?1:0)}`;
    g+=`<rect x="${tx}" y="${x.y-4}" width="8" height="${x.zone?8:3}" rx="1.5" fill="${x.col}"/>
        <text x="${tx+12}" y="${x.y+4}" font-size="${narrow?10.5:11.5}" fill="${x.cur?'var(--fg)':'var(--fg2)'}"${x.cur?' font-weight="700"':''}>${txt}</text>`; });
  const md=s=>s?(+s.slice(0,2))+'/'+(+s.slice(2)):'';
  const every=Math.max(1,Math.round(n/(narrow?3:5)));
  for(let i=0;i<n-every/2;i+=every) g+=`<text x="${Math.max(L+12,X(i))}" y="${H-4}" font-size="10" fill="var(--mut)" text-anchor="middle">${md(dd[i])}</text>`;
  if(SHOW_ICHI&&!narrow) g+=`<text x="${X(n-1)+slot}" y="${H-4}" font-size="10" fill="var(--mut)">→雲26日先</text>`;
  g+=`<line class="xh" x1="0" x2="0" y1="${T}" y2="${vt+VH}" stroke="var(--mut)" stroke-width="1" style="display:none"/>
      <rect x="${L}" y="0" width="${PW}" height="${H}" fill="transparent"/>`;
  el.innerHTML=`<div class="lvleg">
      <label><input type="checkbox" id="cbIchi" ${SHOW_ICHI?'checked':''}> 一目均衡表</label>
      ${SHOW_ICHI?`<span><i style="background:var(--tenkan)"></i>転換線</span><span><i style="background:var(--kijun)"></i>基準線</span><span><i style="background:var(--chikou)"></i>遅行スパン</span><span><i class="sq" style="background:var(--cloudU)"></i>陽雲</span><span><i class="sq" style="background:var(--cloudD)"></i>陰雲</span>`:''}
      <label><input type="checkbox" id="cbLv" ${SHOW_LV?'checked':''}> 売買の目安</label></div>
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="ローソク足・一目均衡表・出来高と売買の目安">${g}</svg>`;
  $('cbIchi').addEventListener('change',e=>{SHOW_ICHI=e.target.checked;candleChart(el,r,lv,D);});
  $('cbLv').addEventListener('change',e=>{SHOW_LV=e.target.checked;candleChart(el,r,lv,D);});
  const svg=el.querySelector('svg'), xh=svg.querySelector('.xh'), tip=$('tip');
  const move=e=>{ const bb=svg.getBoundingClientRect(), cx=(e.touches?e.touches[0].clientX:e.clientX), cy=(e.touches?e.touches[0].clientY:e.clientY);
    const ux=(cx-bb.left)/bb.width*W, i=Math.max(0,Math.min(n-1,Math.floor((ux-L)/slot)));
    xh.setAttribute('x1',X(i));xh.setAttribute('x2',X(i));xh.style.display='';
    const f=v=>v==null?'—':fmt(v,v<100?1:0);
    tip.innerHTML=`<b>${md(dd[i])}</b><br>始 ${f(o[i])}　高 ${f(h[i])}<br>安 ${f(l[i])}　終 <b>${f(c[i])}</b><br>出来高 ${fmt(vol[i])}`+
      (SHOW_ICHI?`<br>転換線 ${f(tk[i])}・基準線 ${f(kj[i])}`:'');
    tip.style.display='block'; tip.dataset.src='lv';
    tip.style.left=Math.min(innerWidth-tip.offsetWidth-8,cx+12)+'px'; tip.style.top=(cy-tip.offsetHeight-12)+'px'; };
  const out=()=>{xh.style.display='none';tip.style.display='none';};
  svg.addEventListener('pointermove',move); svg.addEventListener('pointerleave',out);
  svg.addEventListener('touchmove',move,{passive:true}); svg.addEventListener('touchend',out);
}
function niceStep(x){ const p=Math.pow(10,Math.floor(Math.log10(x))), m=x/p; return (m<1.5?1:m<3?2:m<7?5:10)*p; }
let PLAN_OPEN=false;
/* 直近の終値の推移に、IN・利確・損切りなどの目安を横線で重ねる */
function levelChart(el,r,lv){
  const hp=(r.hp||[]).map(v=>r.hp0+v*r.hpk), n=hp.length, c=r.p, wait=lv.mode==='wait';
  if(n<2){el.innerHTML='';return;}
  const W=Math.max(300,Math.round(el.clientWidth||600)), narrow=W<520, H=narrow?210:250, LB=narrow?96:118, T=12, B=20;
  const L=Math.max(30,Math.ceil(fmt(Math.max(c,...hp),c<100?1:0).length*6.2)+10);
  const PW=W-L-LB;   // 右側はラベル欄
  // 線の定義 [名前, 価格, 色, 破線]
  const lines=(wait
      ?[['転換',lv.trig,'var(--fg2)','5 4'],['戻り売り',lv.t1,'var(--z0)','5 4'],['手じまい',lv.trail,'var(--z0)','']]
      :[['利確2',lv.t2,'var(--z4)','5 4'],['利確1',lv.t1,'var(--z4)','5 4'],['損切り',lv.stop,'var(--z0)',''],['手じまい',lv.trail,'var(--z0)','2 3']])
      .filter(x=>x[1]!=null);
  if(wait&&lv.trig!=null&&lv.trig===lv.t1){ lines.splice(0,2,['転換/戻り',lv.t1,'var(--fg2)','5 4']); }
  // 縦軸: 終値と近い目安が収まる範囲。遠すぎる目安（範囲の外）は上下の端に矢印で示す
  const core=hp.concat([c]).concat(lv.in||[]).concat(lines.filter(x=>x[0]!=='利確2').map(x=>x[1]));
  let lo=Math.min(...core), hi=Math.max(...core); const span=hi-lo||c*0.05;
  lines.forEach(x=>{ if(x[1]>hi&&x[1]<=hi+span*0.35)hi=x[1]; });
  lo-=span*0.06; hi+=span*0.06;
  const X=i=>L+i/(n-1)*PW, Y=v=>T+(hi-v)/(hi-lo)*(H-T-B), inR=v=>v>=lo&&v<=hi;
  let g='';
  // 目盛り（横線4本）
  const st=niceStep((hi-lo)/5); for(let v=Math.ceil(lo/st)*st; v<=hi; v+=st){
    g+=`<line x1="${L}" x2="${L+PW}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--line)" stroke-width="1"/>
        <text x="${L-5}" y="${Y(v)+3.5}" font-size="10" fill="var(--mut)" text-anchor="end">${fmt(v,st<1?1:0)}</text>`; }
  g+=`<line x1="${L}" x2="${L}" y1="${T}" y2="${H-B}" stroke="var(--axis)"/>`;
  // INゾーン
  if(lv.in){ const y1=Y(Math.min(hi,lv.in[1])), y2=Y(Math.max(lo,lv.in[0]));
    g+=`<rect x="${L}" y="${y1}" width="${PW}" height="${Math.max(3,y2-y1)}" fill="var(--z3)" opacity=".35"/>`; }
  // 目安の横線
  lines.forEach(([nm,v,col,dash])=>{ if(!inR(v))return;
    g+=`<line x1="${L}" x2="${L+PW}" y1="${Y(v)}" y2="${Y(v)}" stroke="${col}" stroke-width="1.6"${dash?` stroke-dasharray="${dash}"`:''}/>`; });
  // 終値の線と現在値
  let d=''; hp.forEach((v,i)=>d+=(i?'L':'M')+X(i).toFixed(1)+','+Y(v).toFixed(1));
  g+=`<path d="${d}" fill="none" stroke="var(--fg)" stroke-width="1.8"/>
      <circle cx="${X(n-1)}" cy="${Y(c)}" r="4" fill="var(--fg)" stroke="var(--card)" stroke-width="2"/>`;
  // 右側のラベル（重ならないように上下にずらす）
  const labs=lines.map(([nm,v,col])=>({nm,v,col,y:inR(v)?Y(v):(v>hi?T+4:H-B-4),out:!inR(v)}));
  if(lv.in) labs.push({nm:'IN',v:null,txt:`IN ${fmt(lv.in[0])}〜`,col:'var(--z3)',y:(Y(Math.min(hi,lv.in[1]))+Y(Math.max(lo,lv.in[0])))/2,zone:1});
  labs.push({nm:'現在',v:c,col:'var(--fg)',y:Y(c),cur:1});
  labs.sort((a,b)=>a.y-b.y);
  const gap=13; for(let k=1;k<labs.length;k++) if(labs[k].y-labs[k-1].y<gap) labs[k].y=labs[k-1].y+gap;
  const over=labs.length?labs[labs.length-1].y-(H-B+2):0; if(over>0) labs.forEach(x=>x.y-=over);
  for(let k=labs.length-2;k>=0;k--) if(labs[k+1].y-labs[k].y<gap) labs[k].y=labs[k+1].y-gap;
  labs.forEach(x=>{ const tx=L+PW+8;
    const txt=x.txt||`${x.out?(x.v>hi?'↑':'↓'):''}${x.nm} ${fmt(x.v,x.v<100?1:0)}`;
    g+=`<rect x="${tx}" y="${x.y-4}" width="8" height="${x.zone?8:3}" rx="1.5" fill="${x.col}" ${x.zone?'opacity=".7"':''}/>
        <text x="${tx+12}" y="${x.y+4}" font-size="${narrow?10.5:11.5}" fill="${x.cur?'var(--fg)':'var(--fg2)'}" ${x.cur?'font-weight="700"':''}>${txt}</text>`; });
  g+=`<text x="${L}" y="${H-5}" font-size="10" fill="var(--mut)">${n-1}営業日前</text>
      <text x="${L+PW}" y="${H-5}" font-size="10" fill="var(--mut)" text-anchor="end">${r.d.slice(5).replace('-','/')}</text>
      <line class="xh" x1="0" x2="0" y1="${T}" y2="${H-B}" stroke="var(--mut)" stroke-width="1" style="display:none"/>
      <rect x="${L}" y="0" width="${PW}" height="${H}" fill="transparent"/>`;
  el.innerHTML=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="終値の推移と売買の目安">${g}</svg>`;
  const svg=el.querySelector('svg'), xh=svg.querySelector('.xh'), tip=$('tip');
  const move=e=>{ const bb=svg.getBoundingClientRect(), cx=(e.touches?e.touches[0].clientX:e.clientX), cy=(e.touches?e.touches[0].clientY:e.clientY);
    const ux=(cx-bb.left)/bb.width*W, i=Math.max(0,Math.min(n-1,Math.round((ux-L)/PW*(n-1))));
    xh.setAttribute('x1',X(i));xh.setAttribute('x2',X(i));xh.style.display='';
    const ago=n-1-i; tip.innerHTML=`<b>${ago?ago+'営業日前':'最新日'}</b><br>終値 ${yen(hp[i])}`;
    tip.style.display='block'; tip.dataset.src='lv';
    tip.style.left=Math.min(innerWidth-tip.offsetWidth-8,cx+12)+'px'; tip.style.top=(cy-tip.offsetHeight-12)+'px'; };
  const out=()=>{xh.style.display='none';tip.style.display='none';};
  svg.addEventListener('pointermove',move); svg.addEventListener('pointerleave',out);
  svg.addEventListener('touchmove',move,{passive:true}); svg.addEventListener('touchend',out);
}
function heroRender(r){
  const [lab,li]=overall(r), [head,desc]=verdictText(r);
  const col=li<0||li===2?'var(--fg2)':li<2?'var(--z4)':'var(--z0)';
  const bg=li===0?'var(--z4)':li===4?'var(--z0)':'transparent', fg=li===0||li===4?'#fff':li===1?'var(--z4t)':li===3?'var(--z0t)':'var(--fg2)';
  $('big').innerHTML=`<span class="lab" style="border-color:${col};background:${bg};color:${fg}">${lab}</span>
    <div><div class="hd">${head}</div><div class="ds">${desc}</div></div>`;
  const q=(id,title,cap,s,k,pill)=>`<div class="q q-${k}"><h4>${title}</h4><div class="cap">${cap}</div>
     <div class="ro"><b>${sgn(s)}</b>${pill}</div><svg id="${id}" role="img"></svg>
     <div class="qe"><span>${ENDS[k][0]}</span><span>${ENDS[k][1]}</span></div></div>`;
  $('quad').innerHTML=q('qT','テクニカル','総合',r.ts,'t',pillHTML(r.ts,'t'))
    +q('qTT','トレンド系','移動平均・MACD・一目',r.tt,'tr',pillHTML(r.tt,'tr',TRN))
    +q('qTO','オシレーター系','RSI・ボリンジャー',r.to,'os',oscPill(r.to))
    +q('qF','ファンダメンタル',r.fp?r.fp.slice(0,7).replace('-','年')+'月期':'決算',r.fs,'f',pillHTML(r.fs,'f'));
  [['qT',r.ts,'t'],['qTT',r.tt,'tr'],['qTO',r.to,'os'],['qF',r.fs,'f']].forEach(([id,v,k])=>gauge($(id),v,k,{mini:true,ends:ENDS[k]}));
  const [th,td]=trendOscComment(r.tt,r.to);
  const chips=(r.te||[]).map(e=>`<span class="chip">${esc(e)}</span>`).join('')+(r.ff||[]).map(e=>`<span class="chip">⚠ ${esc(e)}</span>`).join('');
  $('notes').innerHTML=`<div class="n1"><b>値動き：${th}</b><span>${td}</span></div>${chips?`<div class="chips">${chips}</div>`:''}`;
  planRender(r);
}
/* ---------------- 総合コメント ---------------- */
function verdictText(r){
  const t=lvl(r.ts,'t'), f=lvl(r.fs,'f');
  const tb=t===0||t===1, ts=t===3||t===4, fb=f===0||f===1, fsell=f===3||f===4;
  let head,desc;
  if(f<0){head='ファンダ評価なし';desc='決算データが足りないため、テクニカルだけで判断してください。';}
  else if(tb&&fb){head='両方とも良好';desc='割安さも値動き（高値圏・落ち着いた値動き）も良好な組み合わせです。';}
  else if(fb&&ts){head='割安だが値動きは弱い';desc='割安度は良好。ただし過去の検証では、テクニカル下位の銘柄はその後も市場に負けやすい傾向がありました。';}
  else if(fsell&&tb){head='値動きは良いが割高';desc='値動きは良好ですが、割安さの裏付けが薄い組み合わせです。';}
  else if(fsell&&ts){head='両方とも弱い（避ける候補）';desc='割安さ・値動きとも弱い組み合わせです。過去の検証で最も差が出たのはこちら側です。';}
  else if(fb){head='割安・値動きは普通';desc='ファンダは良好側、テクニカルは中立です。';}
  else if(tb){head='値動きは良好・割安さは普通';desc='テクニカルは良好側、ファンダは中立です。';}
  else if(fsell){head='割高・中身が弱い';desc='ファンダが弱い側、テクニカルは中立です。';}
  else if(ts){head='値動きが弱い';desc='テクニカルが弱い側（安値圏・荒い値動きなど）、ファンダは中立です。';}
  else {head='決め手なし';desc='どちらも中立圏です。';}
  return [head,desc];
}

/* ---------------- 銘柄表示 ---------------- */
let CUR=null;
function show(code,push){
  const r=BY[code]; if(!r)return; CUR=code;
  $('stock').innerHTML=`<span class="nm">${esc(r.n)}</span><span class="cd">${r.c}</span>
    <span class="px">${fmt(r.p,r.p<100?1:0)}円</span>
    <span class="meta">${r.chg==null?'':'前日比 '+(r.chg>0?'▲':r.chg<0?'▼':'')+fmt(Math.abs(r.chg),2)+'%'}</span>
    <span class="meta">${esc(r.m)}・${esc(r.s||'業種不明')}${r.mc!=null?'・時価総額 '+fmt(r.mc)+'億円':''}</span>
    <a href="./one/${r.c}.html">分析ダッシュボード →</a>　<a href="./${r.c}.html">チャートを開く →</a>`;
  $('tAsOf').textContent=r.d+' 終値';
  $('fAsOf').textContent=r.fp?r.fp.slice(0,7).replace('-','年')+'月期':'';
  gauge($('gT'),r.ts,'t'); gauge($('gF'),r.fs,'f');
  $('rT').innerHTML=`<span class="sc">${sgn(r.ts)}</span>${pillHTML(r.ts,'t')}`;
  $('rF').innerHTML=`<span class="sc">${sgn(r.fs)}</span>${pillHTML(r.fs,'f')}`;
  $('evT').innerHTML=(r.te||[]).map(e=>`<span class="chip">${esc(e)}</span>`).join('');
  $('evF').innerHTML=(r.ff||[]).map(e=>`<span class="chip">⚠ ${esc(e)}</span>`).join('')+
    (r.dv!=null?`<span class="chip">業種内偏差値 ${fmt(r.dv,1)}</span>`:'');
  heroRender(r);
  spark($('spT'),r);
  const TR=trObj(r.tr), FR=frObj(r.fr);
  const tpart=k=>{ const j=TKEYS.indexOf(k); return part(TNAME[k][0],`${TNAME[k][1]}・重み${Math.round(M.tw[k]*100)}`,r.tc?r.tc[j]:null,tDesc(k,TR&&TR[k])); };
  $('pT').innerHTML=`<div class="pgh">高値圏・値動き<small>重み${Math.round(((M.tw.hi52||0)+(M.tw.lv||0))*100)}%</small></div>`+['hi52','lv'].filter(k=>k in M.tw).map(tpart).join('')
    +`<div class="pgh">トレンド系<small>${sgn(r.tt)}</small></div>`+['ma','macd','ichi','vol'].map(tpart).join('')
    +`<div class="pgh">オシレーター系<small>${sgn(r.to)}</small></div>`+['rsi','bb'].map(tpart).join('');
  $('pF').innerHTML=r.fc?FKEYS.map((k,j)=>part(FNAME[k][0],`${FNAME[k][1]}・重み${Math.round(M.fw[k]*100)}`,r.fc[j],fDesc(k,FR&&FR[k],r))).join('')
    :'<p class="na" style="padding:10px 0">決算データがありません。</p>';
  if(push!==false){ try{history.replaceState(null,'','#'+r.c);}catch(e){} }
  try{localStorage.setItem('sig-last',r.c)}catch(e){}
}

/* ---------------- 検索 ---------------- */
const norm=s=>String(s||'').normalize('NFKC').toLowerCase();
ROWS.forEach(r=>r._k=norm(r.c+' '+r.n));
let sel=0, hits=[];
function suggest(){
  const q=norm($('q').value.trim()); const box=$('sugg');
  if(!q){box.style.display='none';return;}
  const pre=[],inc=[];
  for(const r of ROWS){ if(norm(r.c).startsWith(q)||norm(r.n).startsWith(q))pre.push(r); else if(r._k.includes(q))inc.push(r);
    if(pre.length>=15)break; }
  hits=pre.concat(inc).slice(0,15); sel=0;
  box.innerHTML=hits.length?hits.map((r,i)=>`<div data-c="${r.c}" class="${i===sel?'on':''}" role="option"><span class="cd">${r.c}</span><span>${esc(r.n)}</span>
    <span class="mk">T ${sgn(r.ts)}・F ${sgn(r.fs)}</span></div>`).join(''):'<div class="na">見つかりません</div>';
  box.style.display='block';
}
function pick(c){ $('sugg').style.display='none'; $('q').value=''; window.open('./one/'+c+'.html','_blank','noopener'); }
$('q').addEventListener('input',suggest);
$('q').addEventListener('keydown',e=>{ const box=$('sugg');
  if(e.key==='ArrowDown'||e.key==='ArrowUp'){ if(!hits.length)return; e.preventDefault();
    sel=(sel+(e.key==='ArrowDown'?1:hits.length-1))%hits.length;
    [...box.children].forEach((d,i)=>d.classList.toggle('on',i===sel)); box.children[sel].scrollIntoView({block:'nearest'}); }
  else if(e.key==='Enter'){ if(hits[sel])pick(hits[sel].c); }
  else if(e.key==='Escape'){ box.style.display='none'; } });
$('sugg').addEventListener('click',e=>{ const d=e.target.closest('[data-c]'); if(d)pick(d.dataset.c); });
document.addEventListener('click',e=>{ if(!e.target.closest('.search'))$('sugg').style.display='none'; });

/* ---------------- 市場全体 ---------------- */
function breadth(el,key,k,title,rows){
  const cnt=[0,0,0,0,0]; let sum=0,n=0;
  rows.forEach(r=>{ const i=lvl(r[key],k); if(i>=0){cnt[i]++;sum+=r[key];n++;} });
  const order=[4,3,2,1,0];
  if(!n){el.innerHTML=`<div class="gh"><h2>${title}</h2></div><p class="na">該当なし</p>`;return;}
  el.innerHTML=`<div class="gh"><h2>${title}</h2><span class="avg">平均 ${sgn(sum/n,1)}（${fmt(n)}銘柄）</span></div>
   <div class="stack">${order.map(i=>cnt[i]?`<div data-tip="${title}｜${NAMES[i]} ${cnt[i]}銘柄（${fmt(cnt[i]/n*100)}%）" style="flex:${cnt[i]};background:var(${ZV[i]})"></div>`:'').join('')}</div>
   <div class="leg">${order.map(i=>`<span><i style="background:var(${ZV[i]})"></i>${NAMES[i]} ${fmt(cnt[i])}（${fmt(cnt[i]/n*100,0)}%）</span>`).join('')}</div>`;
}

/* ---------------- 騰落レシオ ---------------- */
const ADN=['底値圏','売られすぎ','中立','過熱気味','過熱'];   // NAMES と同じ並び（良好…避ける）
const adScore=v=>v==null?null:Math.max(-100,Math.min(100,(100-v)*2));
function renderAD(mk){
  const A=(M.ad||{})[mk||'']; const el=$('bAD');
  if(!A||!A.r25.length){el.innerHTML='<p class="na">騰落レシオを計算できるデータがありません。</p>';return;}
  const n=A.r25.length, i=n-1, v=A.r25[i], sc=adScore(v), li=lvl(sc,'ad');
  const pill=li<0?'':`<span class="pill" style="border-color:${li===2?'var(--fg2)':li<2?'var(--z4)':'var(--z0)'};background:${li===0?'var(--z4)':li===4?'var(--z0)':'transparent'};color:${li===0||li===4?'#fff':li<2?'var(--z4t)':li>2?'var(--z0t)':'var(--fg2)'}">${ADN[li]}</span>`;
  const com=[['底値圏','25日騰落レシオが70%以下。売りが出尽くしやすく、相場全体の底打ちのサインとされる水準です。'],
             ['売られすぎ','70〜80%。値下がり銘柄が多く、全体に売られすぎ気味です。'],
             ['中立','80〜120%。値上がりと値下がりが釣り合っています。'],
             ['過熱気味','120〜130%。値上がり銘柄が多く、相場全体が過熱し始めています。'],
             ['過熱','130%以上。買われすぎで、相場全体の天井圏のサインとされる水準です。']][li]||['',''];
  el.innerHTML=`<div>
     <div class="gh"><h2>騰落レシオ（25日）</h2><span class="meta">${esc(mk||'全市場')}</span></div>
     <svg class="gauge" id="gAD" viewBox="-34 0 328 150" role="img"></svg>
     <div class="rd"><span class="sc">${fmt(v,1)}%</span>${pill}
       <div class="sub">10日騰落レシオ ${fmt(A.r10[i],1)}%<br>${A.y}/${A.d[i].replace('-','/')}　値上がり ${fmt(A.up[i])}・値下がり ${fmt(A.dn[i])}・変わらず ${fmt(A.fl[i])}</div></div>
   </div>
   <div class="adc">
     <div class="spark" style="margin:0"><div class="lb"><span>直近${n}営業日の推移</span>
       <span><i style="display:inline-block;width:14px;height:2px;background:var(--acc);vertical-align:3px"></i> 25日　
       <i style="display:inline-block;width:14px;height:2px;background:var(--mut);vertical-align:3px"></i> 10日</span></div></div>
     <div id="adChart"></div>
     <div class="cm"><b>${com[0]}</b><span>${com[1]}</span></div>
   </div>`;
  gauge($('gAD'),sc,'ad',{rev:true,names:[ADN[4],ADN[3],ADN[2],ADN[1],ADN[0]],tick:c=>Math.round(100-c/2)});
  adChart($('adChart'),A);
}
function adChart(el,A){
  // 画面幅に合わせて描く（文字を縮ませない）
  const n=A.r25.length, W=Math.max(280,Math.round(el.clientWidth||600)), H=W<500?170:190, L=34, Rr=8, T=8, B=22;
  const all=A.r25.concat(A.r10).filter(v=>v!=null);
  const lo=Math.min(60,Math.floor(Math.min(...all)/10)*10), hi=Math.max(140,Math.ceil(Math.max(...all)/10)*10);
  const X=i=>L+i/(n-1)*(W-L-Rr), Y=v=>T+(hi-v)/(hi-lo)*(H-T-B);
  const path=a=>{let d='',pen=false;a.forEach((v,i)=>{if(v==null){pen=false;return;}d+=(pen?'L':'M')+X(i).toFixed(1)+','+Y(v).toFixed(1);pen=true;});return d;};
  let g='';
  [lo,70,80,100,120,130,hi].filter((v,j,a)=>v>=lo&&v<=hi&&a.indexOf(v)===j).forEach(v=>{
    g+=`<line x1="${L}" x2="${W-Rr}" y1="${Y(v)}" y2="${Y(v)}" stroke="${v===100?'var(--axis)':'var(--line)'}" stroke-width="1"/>
        <text x="${L-5}" y="${Y(v)+3}" text-anchor="end" font-size="10" fill="var(--mut)">${v}</text>`; });
  const step=Math.max(1,Math.round(n/(W<500?4:6))); let xl='';
  for(let i=0;i<n;i+=step) xl+=`<text x="${X(i)}" y="${H-6}" text-anchor="middle" font-size="10" fill="var(--mut)">${A.d[i].replace('-','/')}</text>`;
  el.innerHTML=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="騰落レシオの推移">
    <rect x="${L}" y="${Y(hi)}" width="${W-L-Rr}" height="${Y(120)-Y(hi)}" fill="var(--z3)" opacity=".22"/>
    <rect x="${L}" y="${Y(80)}" width="${W-L-Rr}" height="${Y(lo)-Y(80)}" fill="var(--z1)" opacity=".25"/>
    ${g}${xl}
    <text x="${W-Rr-4}" y="${Y(hi)+12}" text-anchor="end" font-size="10" fill="var(--fg2)">過熱圏（120%以上）</text>
    <text x="${W-Rr-4}" y="${Y(lo)-5}" text-anchor="end" font-size="10" fill="var(--fg2)">売られすぎ圏（80%以下）</text>
    <path d="${path(A.r10)}" fill="none" stroke="var(--mut)" stroke-width="1.3"/>
    <path d="${path(A.r25)}" fill="none" stroke="var(--acc)" stroke-width="2"/>
    <circle cx="${X(n-1)}" cy="${Y(A.r25[n-1])}" r="4" fill="var(--acc)" stroke="var(--card)" stroke-width="2"/>
    <line class="xh" x1="0" x2="0" y1="${T}" y2="${H-B}" stroke="var(--mut)" stroke-width="1" style="display:none"/>
    <circle class="dot" r="4" fill="var(--acc)" stroke="var(--card)" stroke-width="2" style="display:none"/>
    <rect x="${L}" y="0" width="${W-L-Rr}" height="${H}" fill="transparent"/></svg>`;
  const svg=el.querySelector('svg'), xh=svg.querySelector('.xh'), dot=svg.querySelector('.dot'), tip=$('tip');
  const move=e=>{ const bb=svg.getBoundingClientRect(), cx=(e.touches?e.touches[0].clientX:e.clientX), cy=(e.touches?e.touches[0].clientY:e.clientY);
    const ux=(cx-bb.left)/bb.width*W, i=Math.max(0,Math.min(n-1,Math.round((ux-L)/(W-L-Rr)*(n-1))));
    xh.setAttribute('x1',X(i));xh.setAttribute('x2',X(i));xh.style.display='';
    if(A.r25[i]!=null){dot.setAttribute('cx',X(i));dot.setAttribute('cy',Y(A.r25[i]));dot.style.display='';}
    tip.innerHTML=`<b>${A.d[i].replace('-','/')}</b><br>25日 ${fmt(A.r25[i],1)}%（${ADN[lvl(adScore(A.r25[i]),'ad')]||'—'}）<br>10日 ${fmt(A.r10[i],1)}%<br>値上がり ${fmt(A.up[i])}／値下がり ${fmt(A.dn[i])}／変わらず ${fmt(A.fl[i])}`;
    tip.style.display='block'; tip.dataset.src='ad';
    tip.style.left=Math.min(innerWidth-tip.offsetWidth-8,cx+12)+'px'; tip.style.top=(cy-tip.offsetHeight-12)+'px'; };
  const out=()=>{xh.style.display='none';dot.style.display='none';tip.style.display='none';};
  svg.addEventListener('pointermove',move); svg.addEventListener('pointerleave',out);
  svg.addEventListener('touchmove',move,{passive:true}); svg.addEventListener('touchend',out);
}

let adT; addEventListener('resize',()=>{clearTimeout(adT);adT=setTimeout(()=>{renderAD($('bMk').value); if(CUR)planRender(BY[CUR]);},150);});

/* ---------------- 業種別 ---------------- */
function tally(rows,key,k){ const c=[0,0,0,0,0]; let sum=0,n=0;
  rows.forEach(r=>{ const i=lvl(r[key],k); if(i>=0){c[i]++;sum+=r[key];n++;} });
  return {c,n,avg:n?sum/n:null,buy:n?(c[0]+c[1])/n:null,sell:n?(c[3]+c[4])/n:null}; }
function stackHTML(t,kind,sec){ if(!t.n)return '<span class="na">評価なし</span>';
  return `<div class="stack">${[4,3,2,1,0].map(i=>t.c[i]?`<div data-tip="${esc(sec)}｜${kind}｜${NAMES[i]} ${t.c[i]}銘柄（${fmt(t.c[i]/t.n*100)}%）" style="flex:${t.c[i]};background:var(${ZV[i]})"></div>`:'').join('')}</div>`; }
function avgCell(t,k){ if(!t.n)return '—'; const i=lvl(t.avg,k);
  return `<b>平均 ${sgn(t.avg,1)}</b><small>良好${fmt(t.buy*100)}%・弱い${fmt(t.sell*100)}%</small>`; }
function renderSectors(rows){
  const g={}; rows.forEach(r=>{ const k=r.s||'業種不明'; (g[k]=g[k]||[]).push(r); });
  let list=Object.entries(g).map(([s,rs])=>({s,n:rs.length,t:tally(rs,'ts','t'),f:tally(rs,'fs','f')}));
  const key=$('bSort').value, nz=v=>v==null?-1e9:v;
  const cmp={t:(a,b)=>nz(b.t.avg)-nz(a.t.avg), f:(a,b)=>nz(b.f.avg)-nz(a.f.avg), tb:(a,b)=>nz(b.t.buy)-nz(a.t.buy),
             fb:(a,b)=>nz(b.f.buy)-nz(a.f.buy), n:(a,b)=>b.n-a.n, name:(a,b)=>a.s.localeCompare(b.s,'ja')}[key];
  list.sort(cmp);
  $('sb').innerHTML=list.map(x=>`<div class="srow" data-s="${esc(x.s)}" title="${esc(x.s)}のランキングを開く">
    <span class="sn">${esc(x.s)}</span><span class="sc2">${fmt(x.n)}社</span>
    <span class="kl">テクニカル</span>${stackHTML(x.t,'テクニカル',x.s)}<span class="av">${avgCell(x.t,'t')}</span>
    <span class="kl">ファンダ</span>${stackHTML(x.f,'ファンダ',x.s)}<span class="av">${avgCell(x.f,'f')}</span></div>`).join('');
  $('sLeg').innerHTML=[4,3,2,1,0].map(i=>`<span><i style="background:var(${ZV[i]})"></i>${NAMES[i]}</span>`).join('');
}
$('sb').addEventListener('click',e=>{ const tr=e.target.closest('[data-s]'); if(!tr)return;
  const sc=tr.dataset.s; if([...$('fSc').options].some(o=>o.value===sc))$('fSc').value=sc;
  $('fMk').value=$('bMk').value; limit=50; sortK=null; tab=TABS[0];
  [...$('tabs').children].forEach((x,i)=>x.classList.toggle('on',i===0)); renderTable();
  $('tabs').scrollIntoView({behavior:'smooth',block:'start'}); });
// 帯にカーソルを載せると銘柄数を出す（スマホはタップ）
document.addEventListener('pointerover',e=>{ const d=e.target.closest&&e.target.closest('[data-tip]'), tip=$('tip');
  if(!d){ if(tip.dataset.src==='seg'){tip.style.display='none';tip.dataset.src='';} return; }
  tip.textContent=d.dataset.tip; tip.dataset.src='seg'; tip.style.display='block';
  const b=d.getBoundingClientRect();
  tip.style.left=Math.max(8,Math.min(innerWidth-tip.offsetWidth-8,b.left+b.width/2-tip.offsetWidth/2))+'px';
  tip.style.top=(b.top-tip.offsetHeight-8)+'px'; });
addEventListener('scroll',()=>{ const tip=$('tip'); if(tip.dataset.src==='seg'){tip.style.display='none';tip.dataset.src='';} },{passive:true});

/* ---------------- ランキング ---------------- */
const isB=(s,k)=>{const i=lvl(s,k);return i>=0&&i<=1;}, isS=(s,k)=>lvl(s,k)>=3;
const TABS=[
  {name:'すべて',desc:'全銘柄。列見出しで並べ替えできます（既定はテクニカルの高い順）。',f:r=>true,s:(a,b)=>(b.ts??-999)-(a.ts??-999)},
  {name:'総合で良好',desc:'テクニカルとファンダを合わせた総合判定が「買い候補」「やや良好」。2つの合計が高い順。',f:r=>{const i=overall(r)[1];return i===0||i===1;},s:(a,b)=>ovScore(b)-ovScore(a)},
  {name:'総合で避ける',desc:'総合判定が「避ける」「注意」。2つの合計が低い順。過去の検証で最も差が出たのはこちら側です。',f:r=>overall(r)[1]>=3,s:(a,b)=>ovScore(a)-ovScore(b)},
  {name:'上昇トレンドの押し目',desc:'上昇トレンド（トレンド系が20以上）で、オシレーター系が0以上（中心より売られた側まで調整）。',f:r=>isB(r.tt,'tr')&&r.to!=null&&r.to>=0,s:(a,b)=>(b.tt+b.to)-(a.tt+a.to)},
  {name:'INゾーン到達',desc:'上昇トレンド（トレンド系が20以上）で、株価がINの目安に入っている銘柄。リスクリワード（利確1までの値幅÷損切りまでの値幅）が大きい順。',f:r=>r.lv&&r.lv.mode==='now'&&isB(r.tt,'tr'),s:(a,b)=>(b.lv.rr??-9)-(a.lv.rr??-9)},
  {name:'売られすぎ',desc:'オシレーター系が「売られすぎ」以上（RSI・ボリンジャー）。',f:r=>isB(r.to,'os'),s:(a,b)=>b.to-a.to},
  {name:'買われすぎ',desc:'オシレーター系が「買われすぎ」以上（RSI・ボリンジャー）。',f:r=>isS(r.to,'os'),s:(a,b)=>a.to-b.to},
  {name:'ファンダ良好・株価軟調',desc:'ファンダが「やや良好」以上で、テクニカルが「弱い」以下（押し目待ちの候補。ただし過去検証ではテクニカル下位は負けやすい）。',f:r=>isB(r.fs,'f')&&isS(r.ts,'t'),s:(a,b)=>b.fs-a.fs},
  {name:'ゴールデンクロス',desc:'10日以内に25日線と75日線のゴールデンクロスが出た銘柄。',f:r=>(r.te||[]).some(e=>e.startsWith('ゴールデン')),s:(a,b)=>b.ts-a.ts},
];
let tab=TABS[1], limit=50, sortK=null, sortDir=-1;
const BDS={t:['良好','やや良','―','弱い','避ける'],f:['良好','やや良','―','弱い','避ける'],
  tr:['上昇','上昇','―','下降','下降'],os:['売られすぎ','売られすぎ','―','買われすぎ','買われすぎ']};   // 強い側は塗りつぶしで区別
function badge(s,k){ const i=lvl(s,k); if(i<0)return '<span class="na">·</span>';
  const t=(k==='os'?OSN:k==='tr'?TRN:NAMES)[i];
  // オシレーターは言葉を省略しない（パソコン幅は「強く」まで、スマホ幅は色の塗りで強弱を示す）
  const txt=k==='os'&&i!==2?`<span class="lg">${OSN[i]}</span><span class="sm">${BDS.os[i]}</span>`:BDS[k][i];
  return `<span class="bdw"><span class="bd b${k==='os'?4-i:i}" title="${t}（${sgn(s)}）">${txt}</span><small class="scn">${sgn(s)}</small></span>`; }
// 直近のイベント（クロス・過熱など）と決算の注意
function evText(r){ return (r.te||[]).concat((r.ff||[]).map(x=>'⚠'+x)); }
function ovBadge(r){ const [lab,i]=overall(r); if(i<0)return '<span class="na">·</span>';
  return `<span class="bd ov b${i}">${lab}</span>`; }
const SK={c:r=>r.c,n:r=>r.n,s:r=>r.s||'',p:r=>r.p,ts:r=>r.ts,tt:r=>r.tt,to:r=>r.to,fs:r=>r.fs,ov:r=>r.fs==null&&r.ts==null?null:ovScore(r)};
function renderTable(){
  const mk=$('fMk').value, sc=$('fSc').value, cap=+$('fCap').value||0;
  let list=ROWS.filter(r=>tab.f(r)&&(!mk||r.m===mk)&&(!sc||r.s===sc)&&
     (!cap||(cap>0?(r.mc!=null&&r.mc>=cap):(r.mc!=null&&r.mc<-cap))));
  if(sortK){ const g=SK[sortK]; list.sort((a,b)=>{const x=g(a),y=g(b); if(x==null)return 1; if(y==null)return -1;
      return (typeof x==='string'?x.localeCompare(y,'ja'):x-y)*sortDir;}); }
  else list.sort(tab.s);
  $('cnt').textContent=fmt(list.length)+'銘柄';
  $('tabdesc').textContent=tab.desc;
  [...$('th').querySelectorAll('th[data-k]')].forEach(th=>{ const k=th.dataset.k; th.querySelector('.ar')?.remove();
    if(k===sortK) th.insertAdjacentHTML('beforeend',`<span class="ar">${sortDir<0?'▼':'▲'}</span>`); });
  $('tb').innerHTML=list.slice(0,limit).map(r=>{ const ev=evText(r); return `<tr data-c="${r.c}"><td>${r.c}</td><td title="${esc(r.n)}">${esc(r.n)}</td>
    <td class="hide-sm meta" title="${esc(r.s)}">${esc(r.s)}</td><td class="num hide-sm">${fmt(r.p,r.p<100?1:0)}</td>
    <td class="c">${badge(r.ts,'t')}</td><td class="c">${badge(r.tt,'tr')}</td><td class="c">${badge(r.to,'os')}</td>
    <td class="c">${badge(r.fs,'f')}</td><td class="c">${ovBadge(r)}</td>
    <td class="hide-sm ev">${ev.map(e=>`<span class="evc${e[0]==='⚠'?' warn':''}">${esc(e)}</span>`).join('')}</td></tr>`;}).join('')||'<tr><td colspan="10" class="na">該当なし</td></tr>';
  $('more').style.display=list.length>limit?'':'none';
}
$('th').addEventListener('click',e=>{ const th=e.target.closest('th[data-k]'); if(!th)return; const k=th.dataset.k;
  if(sortK===k) sortDir=-sortDir; else { sortK=k; sortDir=(k==='c'||k==='n'||k==='s')?1:-1; }
  limit=50; renderTable(); });
$('tabs').innerHTML=TABS.map((t,i)=>`<button type="button" data-i="${i}" class="${t===tab?'on':''}">${t.name}</button>`).join('');
$('tabs').addEventListener('click',e=>{ const b=e.target.closest('button'); if(!b)return;
  tab=TABS[+b.dataset.i]; limit=50; sortK=null; [...$('tabs').children].forEach(x=>x.classList.toggle('on',x===b)); renderTable(); });
const uniq=a=>[...new Set(a.filter(Boolean))];
$('fMk').innerHTML='<option value="">市場: すべて</option>'+uniq(ROWS.map(r=>r.m)).map(m=>`<option>${esc(m)}</option>`).join('');
$('fSc').innerHTML='<option value="">業種: すべて</option>'+uniq(ROWS.map(r=>r.s)).sort((a,b)=>a.localeCompare(b,'ja')).map(m=>`<option>${esc(m)}</option>`).join('');
['fMk','fSc','fCap'].forEach(id=>$(id).addEventListener('change',()=>{limit=50;renderTable();}));
$('more').addEventListener('click',()=>{limit+=100;renderTable();});
$('tb').addEventListener('click',e=>{ const tr=e.target.closest('tr[data-c]'); if(tr)pick(tr.dataset.c); });

/* ---------------- 説明 ---------------- */
(function(){
  const L=M.levels, w=o=>Math.round(o*100)+'%';
  $('expl').innerHTML=`
  <p>どちらのスコアも各指標を −1（悪い）〜 +1（良い）に換算し、重みを掛けて合計したものを100倍しています（−100〜+100）。
  値が取れない指標は除き、残りで重みを配り直します。</p>
  <p><b>2026-10-13 の見直し：</b>2017〜2026年の株価で過去にさかのぼって検証したところ、旧式（移動平均・MACD・一目 各20%、RSI・ボリンジャー 各15%、出来高10%）は
  その後20日の値動きをほぼ当てていませんでした（順位相関 0.002）。当たっていた「52週高値への近さ」「値動きの小ささ」を加えて重みを組み直し、
  同じ検証で 0.046（2017-20／2021-23／2024- の3期間ともプラス）になりました。効き目は下位側に集中しているため、判定は「避ける」を重く見る呼び方にしています。</p>
  <table><thead><tr><th>テクニカル</th><th>重み</th><th>+1（良い）になる条件</th></tr></thead><tbody>
  <tr><td>52週高値への近さ</td><td>${w(M.tw.hi52)}</td><td>終値÷52週高値が97%以上で+1、82%で0、67%以下で−1</td></tr>
  <tr><td>値動きの小ささ</td><td>${w(M.tw.lv)}</td><td>60日の日次変化率の標準偏差（年率）が15%以下で+1、35%で0、55%以上で−1</td></tr>
  <tr><td>移動平均</td><td>${w(M.tw.ma)}</td><td>終値が25・75・200日線より上、25日線＞75日線、25日線が上向き（5項目の平均。離れているほど±1に近づく）</td></tr>
  <tr><td>MACD(12,26,9)</td><td>${w(M.tw.macd)}</td><td>MACDがシグナルより上（半分）、ヒストグラムが3日前より拡大（半分）</td></tr>
  <tr><td>一目均衡表</td><td>${w(M.tw.ichi)}</td><td>株価が雲の上（半分。雲の中は0）、転換線＞基準線、遅行スパンが26日前の株価より上</td></tr>
  <tr><td>RSI(14)</td><td>${w(M.tw.rsi)}</td><td>30以下で+1、50で0、70以上で−1（逆張り）</td></tr>
  <tr><td>ボリンジャー(20,±2σ)</td><td>${w(M.tw.bb)}</td><td>−2σで+1、中心線で0、+2σで−1（逆張り）</td></tr>
  <tr><td>出来高</td><td>${w(M.tw.vol)}</td><td>直近20日で上げた日の出来高が75%以上で+1、25%以下で−1</td></tr>
  </tbody></table>
  <p>乖離や差の大きさは、その銘柄の直近20日の値動きの大きさ（日々の値幅の標準偏差）で割ってから −1〜+1 に換算します。
  値動きの荒い銘柄と穏やかな銘柄を同じ物差しで比べるためと、わずかな上下でスコアが跳ねないようにするためです。</p>
  <p>合計は伸ばさずにそのまま表示します（全銘柄の5〜95%点がおよそ−60〜+60）。</p>
  <p><b>トレンド系とオシレーター系：</b>メーターの下の2つの小さなメーターは、上の指標の一部を2つに分けて集計し直したものです（52週高値・値動きの小ささは入りません）。
  トレンド系＝移動平均・MACD・一目均衡表・出来高、オシレーター系＝RSI・ボリンジャー。いずれも過去検証では単独の予測力はほぼありませんでした。
  オシレーター系のプラスは「売られすぎ（逆張りの買い）」、マイナスは「買われすぎ」を意味します。
  区切りはトレンド系が ${L.tr[0]}／${L.tr[1]}／${L.tr[2]}／${L.tr[3]}、オシレーター系が ${L.os[0]}／${L.os[1]}／${L.os[2]}／${L.os[3]}。
  オシレーターは逆張りなので、強いトレンドの銘柄ほど「買われすぎ」側に出ます（2つは強く逆向きに動きます）。
  2つの組み合わせで「上昇トレンド中の押し目」「上昇トレンドだが過熱」「下降トレンド中の戻り」などのコメントを出します。
  押し目は「上昇トレンド（トレンド系が20以上）、かつオシレーター系が0以上（中心より売られた側）」、戻りはその逆です。</p>
  <p><b>騰落レシオ：</b>直近25営業日（10日版も併記）の値上がり銘柄数の合計÷値下がり銘柄数の合計×100。手元の株価CSV（調整後終値の前日比）から、
  全市場と市場別に数えています。一般に120%以上で過熱（天井圏）、70%以下で底値圏とされ、相場全体の逆張りの目安に使われます。
  メーターの区切りは 70／80／120／130%。</p>
  <p><b>売買の目安（IN・利確・損切り）：</b>25・75・200日線、ボリンジャー±2σ、一目の基準線と雲、20・60日の高値安値、52週高値を「支持線（下）」「抵抗線（上）」として並べ、
  ATR（14日の平均的な1日の値幅）で距離を測って出しています。0.4ATR以内に重なる線は1つにまとめます。
  <br>・<b>IN可</b>：上昇トレンド（トレンド系が20以上）で株価が一番近い支持線から0.6ATR以内、またはオシレーターが売られすぎ（下降トレンド中を除く）。IN目安は支持線〜現値。
  <br>・<b>押し目待ち</b>：それ以外でトレンドが下向きでないとき。一番近い支持線±0.3ATRを指値の目安に。
  <br>・<b>様子見</b>：下降トレンド（トレンド系が−20以下）。25日線・基準線などを終値で上抜けるのを待つ。
  <br>・<b>損切り</b>：INゾーン下限から1.5ATR下（その間に次の支持線があれば、その0.3ATR下）。<b>利確</b>：IN基準から1〜6ATR上の抵抗線（無ければ2ATR・4ATRの値幅）。
  <br>・<b>保有中の手じまい</b>：終値−2.5ATR。上昇トレンド中で25日線の方が上ならそちらを優先（25日線−0.3ATR）。価格は呼値の単位に丸めています。</p>
  <p>判定の区切り（テクニカル）: 良好 ${L.t[0]}以上／やや良好 ${L.t[1]}以上／弱い ${L.t[2]}以下／避ける ${L.t[3]}以下（避けるは全体の下位約2割）。
</p>
  <table><thead><tr><th>ファンダメンタル</th><th>重み</th><th>元データ</th></tr></thead><tbody>
  <tr><td>割安度</td><td>${w(M.fw.val)}</td><td>次の3つの平均：四季報式の割安度評価（1〜5、3が0、5が+1）、PBR（1倍で0、0.5倍以下で+1、2倍以上で−1）、EV/EBITDA（10倍で0、5倍以下で+1、15倍以上で−1。金融は使わない）</td></tr>
  <tr><td>収益性</td><td>${w(M.fw.prof)}</td><td>収益性評価（1〜5）と ROE（8%で0、16%以上で+1、0%以下で−1）の平均</td></tr>
  <tr><td>成長性</td><td>${w(M.fw.grow)}</td><td>成長性評価（売上高CAGR、1〜5）と 直近の増収率（±10%で±1）の平均</td></tr>
  <tr><td>安全性</td><td>${w(M.fw.safe)}</td><td>安全性評価（自己資本比率、金融は業法の健全性指標、1〜5）</td></tr>
  <tr><td>Fスコア</td><td>${w(M.fw.fs)}</td><td>ピオトロスキーFスコア（0〜9）。4.5が0、9で+1</td></tr>
  <tr><td>キャッシュ</td><td>${w(M.fw.cash)}</td><td>FCF利回り（±6%で±1）。金融業は使わない</td></tr>
  </tbody></table>
  <p>判定の区切り（ファンダ）: 良好 ${L.f[0]}以上／やや良好 ${L.f[1]}以上／弱い ${L.f[2]}以下／避ける ${L.f[3]}以下。
  2022〜2026年の検証では割安（特にPBR・EV/EBITDA）が効き、収益性・安全性は効かないかマイナスだったため、割安度の重みを55%にしています（日本のバリュー相場の時期のため、相場が変われば見直しが必要です）。
  1〜5の評価は決まった基準で区切る絶対評価（ファンダメンタル分析と同じ）なので、市場全体が割安な局面では買い側に寄ります。
  3指標以上そろわない銘柄は評価しません。</p>`;
})();

/* ---------------- 明るさ ---------------- */
const root=document.documentElement;
$('themeBtn').addEventListener('click',()=>{
  const cur=root.getAttribute('data-theme')||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');
  const nx=cur==='dark'?'light':'dark'; root.setAttribute('data-theme',nx);
  try{localStorage.setItem('fdb-theme',nx)}catch(e){} });

/* ---------------- 起動 ---------------- */
$('sub').textContent=`株価 ${M.asof} 終値・${fmt(ROWS.length)}銘柄・作成 ${M.built}`;
$('bMk').innerHTML='<option value="">市場: すべて</option>'+uniq(ROWS.map(r=>r.m)).map(m=>`<option>${esc(m)}</option>`).join('');
function renderStrip(rows,mk){
  const A=(M.ad||{})[mk||''], cnt=(key,k)=>{const c=[0,0,0,0,0];let n=0;rows.forEach(r=>{const i=lvl(r[key],k);if(i>=0){c[i]++;n++;}});return {c,n};};
  const T=cnt('ts','t'), F=cnt('fs','f');
  const ov=[0,0,0]; rows.forEach(r=>{const i=overall(r)[1]; if(i<0)return; ov[i<=1?0:i>=3?2:1]++;});
  const st=x=>`<div class="stack">${[4,3,2,1,0].map(i=>x.c[i]?`<div data-tip="${NAMES[i]} ${fmt(x.c[i])}銘柄（${fmt(x.c[i]/x.n*100)}%）" style="flex:${x.c[i]};background:var(${ZV[i]})"></div>`:'').join('')}</div>`;
  let ad='';
  if(A&&A.r25.length){ const v=A.r25[A.r25.length-1], li=lvl(adScore(v),'ad');
    const c=li===2?'var(--fg2)':li<2?'var(--z4t)':'var(--z0t)';
    ad=`<div class="si"><span class="k">騰落レシオ（25日）</span><span class="v">${fmt(v,1)}% <small style="color:${c};font-weight:700">${ADN[li]||''}</small></span></div>`; }
  const pct=(a,n)=>n?fmt(a/n*100)+'%':'—';

}
function renderBreadth(){
  const mk=$('bMk').value, rows=ROWS.filter(r=>!mk||r.m===mk);
  renderStrip(rows,mk);
  renderSectors(rows);
  renderAD(mk);
}
$('bMk').addEventListener('change',renderBreadth);
// 業種別は普段は閉じておき、ボタンで開く
$('sectBtn').addEventListener('click',()=>{ const w=$('sectWrap'), open=w.hidden;
  w.hidden=!open; $('sectBtn').setAttribute('aria-expanded',open);
  $('sectBtn').textContent=open?'業種別 ▴':'業種別 ▾'; });
$('bSort').addEventListener('change',renderBreadth);
function toggler(btn,box,openTxt,closeTxt,onOpen){ $(btn).addEventListener('click',()=>{ const w=$(box), open=w.hidden;
  w.hidden=!open; $(btn).setAttribute('aria-expanded',open); $(btn).textContent=open?openTxt:closeTxt; if(open&&onOpen)onOpen(); }); }
renderBreadth();
renderTable();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main(sys.argv[1:])
