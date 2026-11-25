#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""株式分割・併合の台帳（data/splits.csv）を読み、1株あたりの数字を「いまの株数ベース」にそろえる共通処理

台帳を作るのは fix_splits.py（日々の検出）と backfill_splits.py（過去の分割履歴の取り込み）。
使うのは fetch_fundamentals.py（決算の1株指標・株数）と forecast_extra.py（会社予想の1株指標）。

考え方:
  ある時点 t の数字を今の株数ベースに直す係数は「t より後に権利落ちした分割比の積」。
  ただし日本の決算は、期末後・発表前に分割するとEPSを分割後ベースで開示する
  （期首に分割したとみなして計算する）など、日付だけでは「調整済みかどうか」が決まらない。
  そこで、純利益÷EPS（＝そのEPSが前提にしている株数）が、今の株数ベースの株数と
  最も合う係数を候補の中から選ぶ（整合チェック）。確かめられないときだけ日付で決める。
"""
import csv
import math
from datetime import date, timedelta
from pathlib import Path

LEDGER = Path(__file__).resolve().parent / "data" / "splits.csv"
TOL = 0.2          # 整合チェックの許容幅（log で ±0.2 ≒ ±22%）。分割比は1.5以上なので取り違えない

_CACHE = None


def ledger(path=LEDGER):
    """{code: [(ex_date 'YYYY-MM-DD', ratio), ...]}（日付順）。ratio は「1株→ratio株」。併合は1未満。"""
    global _CACHE
    if _CACHE is not None and path == LEDGER:
        return _CACHE
    out = {}
    if Path(path).exists():
        with open(path, encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                try:
                    ratio = float(r["ratio"])
                    ex = str(r["ex_date"])[:10]
                except (KeyError, ValueError, TypeError):
                    continue
                if ratio <= 0 or ratio == 1 or not ex:
                    continue
                out.setdefault(str(r["code"]).strip(), {})[ex] = ratio   # 同じ日の重複は後勝ち
    out = {c: sorted(v.items()) for c, v in out.items()}
    if path == LEDGER:
        _CACHE = out
    return out


def factor_after(code, when, margin_days=0):
    """when（日付文字列）より後に権利落ちした分割比の積。margin_days だけ手前にずらして判定できる。"""
    sp = ledger().get(str(code), [])
    if not sp or not when:
        return 1.0
    t = str(when)[:10]
    if margin_days:
        try:
            t = (date.fromisoformat(t) - timedelta(days=margin_days)).isoformat()
        except ValueError:
            pass
    f = 1.0
    for ex, r in sp:
        if ex > t:
            f *= r
    return f


def candidates(code):
    """ありうる係数（1＝もう調整済み、…、全分割の積＝まったく未調整）"""
    sp = ledger().get(str(code), [])
    c = {1.0}
    f = 1.0
    for ex, r in reversed(sp):
        f *= r
        c.add(round(f, 10))
    return sorted(c)


def choose(code, implied_shares, ref_shares, fallback):
    """implied_shares（純利益÷EPS など、その1株指標が前提にしている株数）× 係数 が
    ref_shares（今の株数ベースの株数）に最も近くなる係数を返す。確かめられなければ fallback。
    戻り値: (係数, 'check' or 'date')"""
    try:
        ok = implied_shares and ref_shares and implied_shares > 0 and ref_shares > 0 \
            and math.isfinite(implied_shares) and math.isfinite(ref_shares)
    except TypeError:
        ok = False
    if not ok:
        return fallback, "date"
    best = min(candidates(code), key=lambda g: abs(math.log(implied_shares * g / ref_shares)))
    if abs(math.log(implied_shares * best / ref_shares)) <= TOL:
        return best, "check"
    return fallback, "date"
