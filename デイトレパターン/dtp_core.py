#!/usr/bin/env python3
"""デイトレード用チャートパターン（teu式 勝てるチャートパターン一覧の22種）を5分足から検出する。

考え方（すべて「その時点までの足」だけで判定する＝後から見た当てはめはしない）
  1) ATR（14本）を値動きの物差しにする。
  2) ジグザグ：高値・安値から ATR×K_ZZ 以上戻したところで山・谷を確定（確定した足の番号も持つ）。
  3) 山・谷が1つ確定するたびに、直近の山・谷の並びからパターンを判定し「どの線を抜けたらエントリーか」を決める。
     次の山・谷が確定するまでに終値がその線を抜けたら、その足の終値でエントリー（シグナル）。
     抜ける前に損切りの価格を割ったら取り消し。
  4) 下落パターンは価格の符号を反転して同じ判定をする（上昇パターンの鏡像）。
  5) 結果：30分後・1時間後・大引け、目標（パターンの値幅）と損切りのどちらに先に届いたか（同じ足なら損切り）。
     デイトレードなので、その日の大引けで必ず手じまう。
"""
import math

import numpy as np
import pandas as pd

import os
K_ZZ = float(os.environ.get("DTP_K", "2.5"))   # ジグザグの山・谷を確定させる戻り幅（ATR の何倍か）
MIN_ZZ_PCT = 0.0015  # 戻り幅の下限（価格の0.15%）
MA_N = 25           # 移動平均線（5分足25本）
MAX_WAIT = 36       # 山・谷が確定してから線を抜けるまで待つ最大の本数（3時間）

# パターンのキー → (番号, 名前, 方向)。O は上抜け(+)・下抜け(-)で別々に集計する
PATTERNS = {
    "U1": ("❶", "ダブルボトム", 1), "U2": ("❷", "逆ヘッドアンドショルダー", 1),
    "U3": ("❸", "上昇トライアングル", 1), "U4": ("❹", "カップウィズハンドル", 1),
    "U5": ("❺", "フラッグ（強気フラッグ）", 1), "U6": ("❻", "ペナント（三角持合い）", 1),
    "U7": ("❼", "上昇ウェッジ（拡大しない）", 1), "U8": ("❽", "押し目買い（サポート反発）", 1),
    "U9": ("❾", "移動平均線の反発（上向き）", 1), "U10": ("❿", "ブレイクアウト（レジスタンス上抜け）", 1),
    "D1": ("❶", "ダブルトップ", -1), "D2": ("❷", "ヘッドアンドショルダー", -1),
    "D3": ("❸", "下降トライアングル", -1), "D4": ("❹", "ディセンディングトライアングル", -1),
    "D5": ("❺", "フラッグ（弱気フラッグ）", -1), "D6": ("❻", "ペナント（三角持合い）", -1),
    "D7": ("❼", "下降ウェッジ（拡大しない）", -1), "D8": ("❽", "戻り売り（レジスタンス反発）", -1),
    "D9": ("❾", "移動平均線の反発（下向き）", -1), "D10": ("❿", "ブレイクダウン（サポート割れ）", -1),
    "O1+": ("❶", "レクタングル（ボックス圏）上抜け", 1), "O1-": ("❶", "レクタングル（ボックス圏）下抜け", -1),
    "O2+": ("❷", "上昇チャネル（下値で押し目買い）", 1), "O2-": ("❷", "下降チャネル（上値で戻り売り）", -1),
    "O3+": ("❸", "ギャップ（窓）上・継続", 1), "O3-": ("❸", "ギャップ（窓）下・継続", -1),
    "O4+": ("❹", "三角保ち合い 上抜け", 1), "O4-": ("❹", "三角保ち合い 下抜け", -1),
}
GROUP = {"U": "上昇パターン（買い）", "D": "下落パターン（売り）", "O": "その他・継続パターン"}


def pkey(base, d):
    """正規化した判定のキー（'1'〜'10'、'O1' など）と方向から、PATTERNS のキーを作る"""
    if base.startswith("O"):
        return base + ("+" if d > 0 else "-")
    return ("U" if d > 0 else "D") + base


# ---------------------------------------------------------------- 準備
def prepare(df, hold=None):
    """df: 列 dt,o,h,l,c,v（古い→新しい）。numpy の辞書にする。
    hold を指定すると日足モード：全体を1つの続いた系列として扱い、結果は最長 hold 本先まで（大引けの代わり）"""
    dt = df["dt"].astype(str).to_numpy()
    o, h, l, c = (df[k].to_numpy(float) for k in ("o", "h", "l", "c"))
    v = df["v"].to_numpy(float)
    day = np.array([s[:10] for s in dt])
    newsess = np.r_[True, day[1:] != day[:-1]] if hold is None else np.r_[True, np.zeros(len(dt) - 1, bool)]
    # 各足が属するセッションの最後の足の番号
    starts = np.flatnonzero(newsess)
    ends = np.r_[starts[1:] - 1, len(dt) - 1]
    sess_end = np.repeat(ends, np.diff(np.r_[starts, len(dt)]))
    sess_start = np.repeat(starts, np.diff(np.r_[starts, len(dt)]))
    if hold is not None:
        sess_end = np.minimum(np.arange(len(dt)) + hold, len(dt) - 1)
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    tr[newsess] = (h - l)[newsess]          # 寄り付きの窓は ATR に入れない
    tr = np.where(tr > 0, tr, np.nan)
    atr = pd.Series(tr).ewm(alpha=1 / 14, adjust=False, ignore_na=True).mean().bfill().to_numpy()
    atr = np.where(np.isfinite(atr) & (atr > 0), atr, np.maximum(np.abs(c) * 0.002, 1e-9))
    vs = pd.Series(np.where(v > 0, v, np.nan))
    vavg = vs.shift(1).rolling(20, min_periods=5).mean().to_numpy()
    volr = np.where(vavg > 0, v / vavg, np.nan)
    return {"dt": dt, "o": o, "h": h, "l": l, "c": c, "v": v, "atr": atr, "volr": volr,
            "newsess": newsess, "sess_end": sess_end, "sess_start": sess_start, "n": len(dt)}


def negate(A):
    """下落パターン用に価格を反転（高値と安値も入れ替える）"""
    B = dict(A)
    B["o"], B["c"] = -A["o"], -A["c"]
    B["h"], B["l"] = -A["l"], -A["h"]
    return B


# ---------------------------------------------------------------- ジグザグ
def zigzag(A):
    """戻り：[(足の番号, 価格, +1=山/-1=谷, 確定した足の番号), …]"""
    h, l, c, atr, n = A["h"], A["l"], A["c"], A["atr"], A["n"]
    thr = np.maximum(K_ZZ * atr, MIN_ZZ_PCT * np.abs(c))
    piv = []
    if n < 3:
        return piv
    d = 0
    hi, hi_i, lo, lo_i = h[0], 0, l[0], 0
    for t in range(1, n):
        if d == 0:
            if h[t] > hi:
                hi, hi_i = h[t], t
            if l[t] < lo:
                lo, lo_i = l[t], t
            if hi - lo >= thr[t]:
                if hi_i < lo_i:     # 先に高値→その後に下げた：山を確定、谷を追う
                    piv.append((hi_i, hi, 1, t)); d = -1; ext, ei = lo, lo_i
                    opp, oi = max(h[lo_i:t + 1]), lo_i + int(np.argmax(h[lo_i:t + 1]))
                else:
                    piv.append((lo_i, lo, -1, t)); d = 1; ext, ei = hi, hi_i
                    opp, oi = min(l[hi_i:t + 1]), hi_i + int(np.argmin(l[hi_i:t + 1]))
            continue
        if d == 1:                  # 山を追っている
            if h[t] >= ext:
                ext, ei = h[t], t
                opp, oi = l[t], t
            else:
                if l[t] < opp:
                    opp, oi = l[t], t
                if ext - opp >= thr[t]:
                    piv.append((ei, ext, 1, t)); d = -1
                    ext, ei = opp, oi
                    seg_h = h[oi:t + 1]
                    opp, oi = float(seg_h.max()), oi + int(np.argmax(seg_h))
        else:                       # 谷を追っている
            if l[t] <= ext:
                ext, ei = l[t], t
                opp, oi = h[t], t
            else:
                if h[t] > opp:
                    opp, oi = h[t], t
                if opp - ext >= thr[t]:
                    piv.append((ei, ext, -1, t)); d = 1
                    ext, ei = opp, oi
                    seg_l = l[oi:t + 1]
                    opp, oi = float(seg_l.min()), oi + int(np.argmin(seg_l))
    return piv


# ---------------------------------------------------------------- 判定の部品
def _line(i0, p0, i1, p1):
    s = (p1 - p0) / (i1 - i0) if i1 != i0 else 0.0
    return (i0, p0, s)


def _at(line, t):
    i0, p0, s = line
    return p0 + s * (t - i0)


def _setup(base, kind, level=None, line=None, height=None, target=None, stop=None, pts=(), lines=(), tag=None):
    return {"base": base, "kind": kind, "line": line if line is not None else ((0, level, 0.0) if level is not None else None),
            "height": height, "target": target, "stop": stop, "pts": list(pts), "lines": list(lines), "tag": tag}


def _pole(P, j, a):
    """P[j] が山のとき、その前の谷から山までが「旗ざお」（短時間に ATR×5 以上の上昇）か。戻り：ざおの高さ or None"""
    if j < 1 or P[j][2] != 1 or P[j - 1][2] != -1:
        return None
    hgt = P[j][1] - P[j - 1][1]
    bars = P[j][0] - P[j - 1][0]
    if hgt >= 5 * a and 0 < bars <= 30 and hgt / bars >= 0.25 * a:
        return hgt
    return None


def setups_at(P, k, A):
    """山・谷 P[0..k] が確定した時点の、パターンの候補（正規化した上昇方向）"""
    out = []
    i_now = P[k][3]
    a = A["atr"][i_now]
    c = A["c"]
    tol = max(0.6 * a, 0.0008 * abs(c[i_now]))
    Q = P[:k + 1]
    m = len(Q)

    def g(j):                       # 後ろから j 番目（1 が最新）
        return Q[m - j]

    last_kind = Q[-1][2]

    # ---- ❶ ダブルボトム：山0・谷1・山1・谷2（谷がほぼ同じ高さ、上から下りてきた）
    if m >= 4 and last_kind == -1:
        H0, L1, H1, L2 = g(4), g(3), g(2), g(1)
        bot = min(L1[1], L2[1])
        if (abs(L1[1] - L2[1]) <= tol and H1[1] - max(L1[1], L2[1]) >= 2.5 * a
                and H0[1] >= H1[1] + 0.5 * a and 6 <= L2[0] - L1[0] <= 150):
            out.append(_setup("1", "cross", level=H1[1], height=H1[1] - bot, stop=bot,
                              pts=[H0, L1, H1, L2], lines=[(L1[0], H1[1], i_now, H1[1])]))

    # ---- ❷ 逆ヘッドアンドショルダー：山0・谷1・山1・谷2(頭)・山2・谷3
    if m >= 6 and last_kind == -1:
        H0, L1, H1, L2, H2, L3 = g(6), g(5), g(4), g(3), g(2), g(1)
        if (L2[1] < min(L1[1], L3[1]) - 0.5 * a and abs(L1[1] - L3[1]) <= 2 * tol
                and min(H1[1], H2[1]) - L2[1] >= 2.5 * a and H0[1] >= max(H1[1], H2[1]) - tol
                and L3[0] - L1[0] <= 200):
            nk = _line(H1[0], H1[1], H2[0], H2[1])
            if abs(nk[2]) * (L3[0] - L1[0]) <= 2.5 * a:          # ネックラインが寝ている
                out.append(_setup("2", "cross", line=nk, height=_at(nk, L2[0]) - L2[1], stop=L3[1],
                                  pts=[H0, L1, H1, L2, H2, L3], lines=[(H1[0], H1[1], i_now, _at(nk, i_now))]))

    # 三角形・ウェッジ・フラッグ用：山1・谷1・山2・谷2
    if m >= 4 and last_kind == -1:
        H1, L1, H2, L2 = g(4), g(3), g(2), g(1)
        rng1, rng2 = H1[1] - L1[1], H2[1] - L2[1]
        top_line = _line(H1[0], H1[1], H2[0], H2[1])
        bot_line = _line(L1[0], L1[1], L2[0], L2[1])
        span = L2[0] - H1[0]
        pole = _pole(Q, m - 4, a)
        if 4 <= span <= 150 and rng1 >= 2.5 * a:
            # ---- ❸ 上昇トライアングル：上値が水平・下値切り上げ
            if abs(H1[1] - H2[1]) <= tol and L2[1] >= L1[1] + 0.5 * a:
                top = max(H1[1], H2[1])
                i_pre = max(0, H1[0] - 36)
                tag = "trend" if c[H1[0]] - c[i_pre] >= 2 * a else "range"   # 直前に（正規化で）上げていたか
                out.append(_setup("3", "cross", level=top, height=top - L1[1], stop=L2[1], tag=tag,
                                  pts=[H1, L1, H2, L2], lines=[(H1[0], top, i_now, top), (L1[0], L1[1], i_now, _at(bot_line, i_now))]))
            conv = H2[1] < H1[1] - 0.3 * a and L2[1] > L1[1] + 0.3 * a
            falling = H2[1] < H1[1] - 0.3 * a and L2[1] < L1[1] - 0.3 * a
            if pole is not None and H1[1] - min(L1[1], L2[1]) <= 0.6 * pole:
                # ---- ❺ フラッグ：旗ざおの後、平行に下がる
                sh, sl = top_line[2], bot_line[2]
                if falling and abs(sh - sl) <= 0.5 * max(abs(sh), abs(sl)) + 0.02 * a:
                    out.append(_setup("5", "cross", line=top_line, height=pole, stop=L2[1],
                                      pts=[Q[m - 5], H1, L1, H2, L2], lines=[(H1[0], H1[1], i_now, _at(top_line, i_now)),
                                                                            (L1[0], L1[1], i_now, _at(bot_line, i_now))]))
                # ---- ❻ ペナント：旗ざおの後、三角に収束
                if conv:
                    out.append(_setup("6", "cross", line=top_line, height=pole, stop=L2[1],
                                      pts=[Q[m - 5], H1, L1, H2, L2], lines=[(H1[0], H1[1], i_now, _at(top_line, i_now)),
                                                                            (L1[0], L1[1], i_now, _at(bot_line, i_now))]))
            elif conv:
                # ---- その他❹ 三角保ち合い（旗ざお無し）
                out.append(_setup("O4", "cross", line=top_line, height=rng1, stop=L2[1],
                                  pts=[H1, L1, H2, L2], lines=[(H1[0], H1[1], i_now, _at(top_line, i_now)),
                                                               (L1[0], L1[1], i_now, _at(bot_line, i_now))]))
            # ---- ❼ ウェッジ：両方下がりながら値幅が縮む（拡大しない）→ 上抜け
            if falling and rng2 < 0.85 * rng1 and top_line[2] < bot_line[2]:
                out.append(_setup("7", "cross", line=top_line, target=H1[1], stop=L2[1],
                                  pts=[H1, L1, H2, L2], lines=[(H1[0], H1[1], i_now, _at(top_line, i_now)),
                                                               (L1[0], L1[1], i_now, _at(bot_line, i_now))]))

    # ---- ❹ カップウィズハンドル：左の縁・丸い底・右の縁・取っ手の押し
    if m >= 4 and last_kind == -1:
        Hr, Lh = g(2), g(1)
        for j in range(m - 4, max(-1, m - 14), -1):
            Hl = Q[j]
            if Hl[2] != 1:
                continue
            width = Hr[0] - Hl[0]
            if width > 200:
                break
            if width < 24 or abs(Hl[1] - Hr[1]) > 1.5 * tol:
                continue
            mid = Q[j + 1:m - 2]
            if any(p[2] == 1 and p[1] > min(Hl[1], Hr[1]) + tol for p in mid):
                break
            seg = A["l"][Hl[0]:Hr[0] + 1]
            bi = Hl[0] + int(np.argmin(seg))
            B = float(seg.min())
            rim = max(Hl[1], Hr[1])
            D = min(Hl[1], Hr[1]) - B
            if D < 4 * a or not (0.25 <= (bi - Hl[0]) / width <= 0.75):
                continue
            cc = c[Hl[0]:Hr[0] + 1]
            if np.mean(cc <= B + D / 3) < 0.2:          # 底が丸い（V字ではない）
                continue
            if not (0 < Hr[1] - Lh[1] <= 0.5 * D and Lh[0] - Hr[0] <= width / 2):
                continue
            out.append(_setup("4", "cross", level=rim, height=D, stop=Lh[1],
                              pts=[Hl, (bi, B, -1, bi), Hr, Lh], lines=[(Hl[0], rim, i_now, rim)]))
            break

    # ---- ❽ 押し目買い：抜けた抵抗線（山a）まで押して反発（谷c が確定した足で入る）
    if m >= 4 and last_kind == -1:
        Ha, Lx, Hb, Lc = g(4), g(3), g(2), g(1)
        if (Hb[1] >= Ha[1] + 1.0 * a and abs(Lc[1] - Ha[1]) <= 1.2 * tol and Lc[1] > Lx[1] + 0.5 * a
                and Hb[1] - c[i_now] >= 0.5 * a and Lc[0] - Ha[0] <= 150):
            out.append(_setup("8", "now", target=Hb[1], stop=Lc[1],
                              pts=[Ha, Lx, Hb, Lc], lines=[(Ha[0], Ha[1], i_now, Ha[1])]))

    # ---- ❿ ブレイクアウト：2回以上はね返された水平の抵抗線を上抜け
    if m >= 4 and last_kind == -1:
        tops = [p for p in Q[-9:] if p[2] == 1 and i_now - p[0] <= 120]
        if len(tops) >= 2:
            R = max(p[1] for p in tops[-2:])
            touch = [p for p in tops if abs(p[1] - R) <= tol]
            newer_higher = any(p[1] > R + tol for p in tops if p[0] > touch[0][0]) if touch else True
            if len(touch) >= 2 and not newer_higher and touch[-1][0] - touch[0][0] >= 6:
                base = float(A["l"][touch[0][0]:i_now + 1].min())
                if R - base >= 2.5 * a:
                    out.append(_setup("10", "cross", level=R, height=R - base, stop=g(1)[1],
                                      pts=touch + [g(1)], lines=[(touch[0][0], R, i_now, R)]))

    # ---- その他❶ レクタングル：上値と下値がそれぞれ2回以上そろう箱 → 上抜け
    if m >= 5 and last_kind == -1:
        last = Q[-6:] if m >= 6 else Q[-5:]
        hs = [p[1] for p in last if p[2] == 1]
        ls = [p[1] for p in last if p[2] == -1]
        if len(hs) >= 2 and len(ls) >= 2:
            T, Bm = max(hs), min(ls)
            if (max(hs) - min(hs) <= 1.5 * tol and max(ls) - min(ls) <= 1.5 * tol and T - Bm >= 3 * a
                    and i_now - last[0][0] <= 200):
                out.append(_setup("O1", "cross", level=T, height=T - Bm, stop=(T + Bm) / 2,
                                  pts=last, lines=[(last[0][0], T, i_now, T), (last[0][0], Bm, i_now, Bm)]))

    # ---- その他❷ 上昇チャネル：平行に上がる2本の線の下側で反発（谷が確定した足で入る）
    if m >= 5 and last_kind == -1:
        L0, H1, L1, H2, L2 = g(5), g(4), g(3), g(2), g(1)
        lo_line = _line(L0[0], L0[1], L1[0], L1[1])
        hi_line = _line(H1[0], H1[1], H2[0], H2[1])
        sl, sh = lo_line[2], hi_line[2]
        if (sl > 0.04 * a and sh > 0.04 * a and abs(sh - sl) <= 0.35 * max(sl, sh)
                and abs(L2[1] - _at(lo_line, L2[0])) <= 1.2 * tol and L2[0] - L0[0] <= 200
                and _at(hi_line, i_now) - c[i_now] >= 1.0 * a):
            out.append(_setup("O2", "now", target=_at(hi_line, i_now), stop=L2[1] - 0.3 * a,
                              pts=[L0, H1, L1, H2, L2], lines=[(L0[0], L0[1], i_now, _at(lo_line, i_now)),
                                                               (H1[0], H1[1], i_now, _at(hi_line, i_now))]))
    return out


# ---------------------------------------------------------------- 足ごとの判定（移動平均・窓）
def bar_events(A, t_from=0):
    """❾ 移動平均線の反発・その他❸ ギャップ（窓）。戻り：[(t, base, setup)]"""
    o, h, l, c, atr, n = A["o"], A["h"], A["l"], A["c"], A["atr"], A["n"]
    ev = []
    ma = pd.Series(c).rolling(MA_N).mean().to_numpy()
    above = pd.Series((c > ma).astype(float)).rolling(20).mean().to_numpy()
    last = -99
    ss = A["sess_start"]
    for t in range(max(t_from, MA_N + 20), n):
        a = atr[t]
        if t - ss[t] < 2 or t - last < 10:
            continue
        if (ma[t] - ma[t - 5] > 0.15 * a and above[t - 1] >= 0.7 and l[t] <= ma[t] + 0.1 * a
                and l[t] >= ma[t] - 1.0 * a and c[t] > ma[t] and c[t] > o[t]):
            tgt = float(h[max(0, t - 20):t].max())
            stp = float(min(l[max(0, t - 2):t + 1].min(), ma[t] - 0.3 * a))
            if tgt - c[t] >= 0.5 * a:
                ev.append((t, "9", _setup("9", "now", target=tgt, stop=stp,
                                          lines=[(t - 30, ma[t - 30], t, ma[t])])))
                last = t
    # 窓：寄り付きが前日終値から ATR×1.5・0.4% 以上離れ、最初の15分の高値を上抜け、窓を埋めずに
    starts = np.flatnonzero(A["newsess"])
    for s in starts:
        if s == 0 or s < t_from - 12:
            continue
        pc = c[s - 1]
        gap = o[s] - pc
        if gap < max(1.5 * atr[s - 1], 0.004 * abs(pc)):
            continue
        e = A["sess_end"][s]
        if s + 3 > e:
            continue
        orh, orl = float(h[s:s + 3].max()), float(l[s:s + 3].min())
        if orl <= pc:
            continue
        for t in range(s + 3, min(s + 13, e + 1)):
            if l[t] <= pc or l[s:t + 1].min() <= pc:
                break
            if c[t] > orh:
                if t >= t_from:
                    ev.append((t, "O3", _setup("O3", "now", height=gap, stop=orl,
                                               lines=[(s - 3, pc, t, pc), (s, orh, t, orh)])))
                break
    return ev


# ---------------------------------------------------------------- 結果
def outcome(A, t, E, target, stop):
    """エントリー（足 t の終値 E）の結果。正規化した上昇方向で計算"""
    c, h, l, o = A["c"], A["h"], A["l"], A["o"]
    se = A["sess_end"][t]
    if t >= se:
        return None
    base = abs(E)
    r = lambda p: (p - E) / base
    res = {"r30": r(c[min(t + 6, se)]), "r60": r(c[min(t + 12, se)]), "rc": r(c[se])}
    hit, pnl = "close", r(c[se])
    for j in range(t + 1, se + 1):
        if l[j] <= stop:
            hit, pnl = "stop", r(min(stop, o[j]))
            break
        if h[j] >= target:
            hit, pnl = "target", r(target)
            break
    res["hit"], res["pnl"] = hit, pnl
    return res


# ---------------------------------------------------------------- 1方向の判定
def _scan_dir(A, d, t_from, want_outcome):
    """正規化した系列 A（d=+1 そのまま、-1 反転）で、t_from 以降のシグナルと、最後の時点で形成中の候補を返す"""
    c, h, l, atr, n = A["c"], A["h"], A["l"], A["atr"], A["n"]
    P = zigzag(A)
    events, forming = [], []
    for k in range(len(P)):
        t0 = P[k][3]
        t_end = P[k + 1][3] if k + 1 < len(P) else n
        t_end = min(t_end, t0 + MAX_WAIT + 1, n)
        if t_end <= t_from and not (k == len(P) - 1):
            continue
        for S in setups_at(P, k, A):
            if S["kind"] == "now":
                if t0 >= t_from:
                    events.append((t0, S))
                continue
            lv0 = _at(S["line"], t0)
            if c[t0] >= lv0:                      # 確定した時点ですでに抜けている → 見送り
                continue
            trig = None
            for t in range(t0 + 1, t_end):
                if l[t] <= S["stop"]:
                    trig = -1
                    break
                if c[t] > _at(S["line"], t):
                    trig = t
                    break
            if trig is not None and trig >= 0:
                if trig >= t_from:
                    events.append((trig, S))
            elif trig is None and k == len(P) - 1 and t_end == n and n - 1 - t0 <= MAX_WAIT:
                forming.append(S)
    for t, base, S in bar_events(A, t_from):
        events.append((t, S))
    out_ev = []
    seen = set()
    for t, S in sorted(events, key=lambda x: x[0]):
        base = S["base"]
        if base == "3":
            key = "U3" if d > 0 else ("D4" if S["tag"] == "trend" else "D3")
        else:
            key = pkey(base, d)
        if (key, t) in seen:
            continue
        seen.add((key, t))
        E = c[t]
        lv = _at(S["line"], t) if S["line"] is not None else E
        tgt = S["target"] if S["target"] is not None else lv + (S["height"] or atr[t])
        stp = S["stop"]
        if tgt <= E + 0.2 * atr[t]:
            tgt = E + max(1.0 * atr[t], 0.5 * (S["height"] or atr[t]))
        if stp >= E - 0.2 * atr[t]:
            stp = E - 1.0 * atr[t]
        ev = {"t": int(t), "key": key, "d": d, "E": E * d, "level": lv * d, "target": tgt * d, "stop": stp * d,
              "volr": None if not np.isfinite(A["volr"][t]) else round(float(A["volr"][t]), 2),
              "atr": float(atr[t]), "S": S}
        if want_outcome:
            ev["res"] = outcome(A, t, E, tgt, stp)
        out_ev.append(ev)
    out_fm = []
    for S in forming:
        base = S["base"]
        key = ("U3" if d > 0 else ("D4" if S["tag"] == "trend" else "D3")) if base == "3" else pkey(base, d)
        lv = _at(S["line"], n - 1)
        dist = (lv - c[-1]) / atr[-1]
        if dist > 1.5:
            continue
        tgt = S["target"] if S["target"] is not None else lv + (S["height"] or atr[-1])
        out_fm.append({"key": key, "d": d, "level": lv * d, "target": tgt * d, "stop": S["stop"] * d,
                       "dist_atr": round(float(dist), 2), "dist_pct": round(float((lv - c[-1]) / abs(c[-1]) * 100), 2), "S": S})
    return out_ev, out_fm


def analyze(df, t_from=0, want_outcome=True, hold=None):
    """1銘柄の5分足 df を判定。戻り：(シグナル一覧, 形成中一覧, 準備した配列)。hold を指定すると日足モード"""
    A = prepare(df, hold)
    if A["n"] < 60:
        return [], [], A
    ev1, fm1 = _scan_dir(A, 1, t_from, want_outcome)
    ev2, fm2 = _scan_dir(negate(A), -1, t_from, want_outcome)
    return sorted(ev1 + ev2, key=lambda e: e["t"]), fm1 + fm2, A


def drawing(ev_or_fm, d):
    """画面のチャートに描く点と線（元の価格に戻す）"""
    S = ev_or_fm["S"]
    pts = [(int(p[0]), round(float(p[1]) * d, 6)) for p in S["pts"]]
    lines = [(int(a), round(float(b) * d, 6), int(x), round(float(y) * d, 6)) for a, b, x, y in S["lines"]]
    return pts, lines
