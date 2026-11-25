#!/usr/bin/env python3
"""決算カレンダー（東証版。data/charts/kessan.html と kessan_data.js）。2026-11-24 作成、同日 表の列を利用者の指定に変更。

月のカレンダー（土日も）に日ごとの発表社数と主な銘柄、日を押すとその日の全銘柄の表。
表の列（利用者の指定）：コード・銘柄名・発表時間・種別（本決算・中間決算・四半期決算・月次）・
  今期経常の会社予想達成率（％と ☀️☁️☂️）・会社予想経常利益（百万円）
  ※コンセンサス経常は無料のデータ源が無いので載せない（利用者が「列ごと外す」を選択）

データ元（すべて手元のファイル。通信なし）
  これからの予定  JPX「決算発表予定日」（決算発表予定日/*.xlsx。日付・種別・決算期末）＝「予定」。
                  まだ載っていない銘柄は昨年の同じ時期の発表日から推定＝「予想」（make_watch._earnings。4か月先まで）
  発表済み        8/28 までは J-Quants（fundamentals/jq_summary）、それより後は TDnet 決算短信（fundamentals/kessan_tanshin.csv）
  月次            TDnet の開示一覧（fundamentals/tdnet/list）で表題に「月次」を含むもの（取り込み開始の 8/25 以降）
達成率
  四半期・中間  累計の経常利益 ÷ その決算短信の今期の会社予想
  本決算        経常利益の実績 ÷ その期の最後の会社予想（期中の決算短信・業績予想の修正のうち最新）
  経常利益が無い会社（IFRS など）は税引前利益で計算し「税前」と付ける
天気
  本決算  ☀️ 100%以上（予想達成）／☁️ 95〜100%／☂️ 95%未満
  四半期  前年の同じ四半期の達成率（無ければ 25・50・75%）と比べて ☀️ 上回る／☁️ 5ポイント以内の下回り／☂️ それ以上の下回り
"""
from __future__ import annotations

import bisect
import csv
import datetime
import json
import re
import unicodedata
from pathlib import Path

BASE = Path(__file__).resolve().parent
SITE = BASE / "data" / "charts"
PRICES = BASE / "data" / "prices"
FUND = BASE / "fundamentals"
SINCE = "2026-05-01"   # この日より前の発表は載せない（ページを軽くするため）
KIND = {"1": "四半期決算", "2": "中間決算", "3": "四半期決算", "4": "本決算"}


def _f(v):
    try:
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def slot_of(hm: str) -> int:
    """0=時刻不明 1=寄り前 2=取引中 3=引け後（東証は 9:00〜15:30）"""
    if not hm:
        return 0
    return 1 if hm < "09:00" else 2 if hm < "15:30" else 3


def fy_next(fy: str) -> str:
    try:
        return str(int(fy[:4]) + 1) + fy[4:]
    except Exception:
        return ""


def fy_prev(fy: str) -> str:
    try:
        return str(int(fy[:4]) - 1) + fy[4:]
    except Exception:
        return ""


class Px:
    """日足の終値（株価の反応の計算用。米国版も使う）"""
    def __init__(self, folder):
        self.folder, self.cache = folder, {}

    def get(self, code):
        if code not in self.cache:
            d, c = [], []
            p = self.folder / f"{code}.csv"
            if p.exists():
                with open(p, encoding="utf-8") as fh:
                    rd = csv.reader(fh); next(rd, None)
                    for r in rd:
                        if r and r[0] >= "2025-01-01" and r[4]:
                            d.append(r[0][:10]); c.append(float(r[4]))
            self.cache[code] = (d, c)
        return self.cache[code]

    def react(self, code, day, slot):
        d, c = self.get(code)
        if not d:
            return None
        i = bisect.bisect_left(d, day)
        if slot == 3 and i < len(d) and d[i] == day:
            i += 1
        if i >= len(d) or i == 0:
            return None
        return round((c[i] / c[i - 1] - 1) * 100, 2)


def disclosures():
    """決算短信と業績予想の修正を1つの形に：
    recs  [dict(code, date, hm, fy, q('1'〜'4'), od, basis, fc)]   od＝累計の経常（無ければ税前）、fc＝その短信の今期予想（本決算は翌期）
    fcs   {(code, 決算期末): [(日付, 予想経常, 基準)]}   その期の会社予想の推移"""
    jq = sorted((FUND / "jq_summary").glob("*.json"))
    jq_last = jq[-1].stem if jq else "0000"
    recs, fcs, seen = [], {}, set()

    def addfc(code, fy, d, v, basis):
        if fy and v is not None:
            fcs.setdefault((code, fy), []).append((d, v, basis))

    for f in jq:
        if f.stem < "2024-04-01":
            continue
        for r in json.load(open(f, encoding="utf-8")):
            dt = r.get("DocType", "")
            code = r["Code"][:4] if len(r["Code"]) == 5 and r["Code"].endswith("0") else r["Code"]
            d, fy = r["DiscDate"], r.get("CurFYEn", "")
            if "EarnForecastRevision" in dt:
                addfc(code, fy, d, _f(r.get("FOdP")), "経常")
                continue
            if "FinancialStatements" not in dt or dt.startswith("OtherPeriod"):
                continue
            q = {"1Q": "1", "2Q": "2", "3Q": "3", "FY": "4"}.get(r.get("CurPerType", ""))
            if not q or (code, fy, q) in seen:
                continue
            seen.add((code, fy, q))
            fc = _f(r.get("NxFOdP")) if q == "4" else _f(r.get("FOdP"))
            addfc(code, fy_next(fy) if q == "4" else fy, d, fc, "経常")
            recs.append(dict(code=code, date=d, hm=(r.get("DiscTime") or "")[:5], fy=fy, q=q,
                             od=_f(r.get("OdP")), basis="経常", fc=fc))
    with open(FUND / "kessan_tanshin.csv", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            if r["訂正"] or r["開示日"] <= jq_last:
                continue
            code, d, fy, q = r["コード"], r["開示日"], r["決算期末"], r["四半期"]
            od, fod, basis = _f(r["経常利益"]), _f(r["予想_経常利益"]), "経常"
            if od is None and fod is None:
                od, fod, basis = _f(r["税引前利益"]), _f(r["予想_税引前利益"]), "税前"
            if r["種別"] == "予想修正":
                addfc(code, fy, d, fod, basis)
                continue
            if r["種別"] != "決算短信" or q not in KIND or (code, fy, q) in seen:
                continue
            seen.add((code, fy, q))
            addfc(code, fy_next(fy) if q == "4" else fy, d, fod, basis)
            recs.append(dict(code=code, date=d, hm=r["時刻"][:5], fy=fy, q=q, od=od, basis=basis, fc=fod))
    for v in fcs.values():
        v.sort()
    return recs, fcs, jq_last


def fc_at(fcs, code, fy, before=None):
    """その期の会社予想（before より前の最新。before が None なら今の最新）"""
    v = [x for x in fcs.get((code, fy), []) if before is None or x[0] < before]
    return v[-1] if v else None


def achieve(r, fcs):
    """達成率（％）"""
    if r["od"] is None:
        return None
    if r["q"] == "4":
        p = fc_at(fcs, r["code"], r["fy"], r["date"])
        if not p or not p[1] or p[1] <= 0 or p[2] != r["basis"]:
            return None
        return round(r["od"] / p[1] * 100, 1)
    fc = r["fc"]
    if not fc or fc <= 0:
        p = fc_at(fcs, r["code"], r["fy"], r["date"] + "~")
        fc = p[1] if p and p[2] == r["basis"] else None
    if not fc or fc <= 0:
        return None
    return round(r["od"] / fc * 100, 1)


def weather(q, ach, base):
    """1=☀️ 2=☁️ 3=☂️ 0=なし"""
    if ach is None:
        return 0
    if q == "4":
        return 1 if ach >= 100 else 2 if ach >= 95 else 3
    b = base if base is not None else {"1": 25, "2": 50, "3": 75}[q]
    return 1 if ach >= b else 2 if ach >= b - 5 else 3


def monthly():
    """TDnet の開示一覧から月次の開示：[(コード, 日付, 時刻)]"""
    out = []
    pat = re.compile(r"月次|\d+月度|\d+月(の|分の?)(業績|売上|営業)")
    for f in sorted((FUND / "tdnet" / "list").glob("*.json")):
        if f.stem < SINCE:
            continue
        try:
            L = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        for r in L:
            t = unicodedata.normalize("NFKC", r.get("表題", ""))
            if pat.search(t) and not re.search(r"決算|訂正|四半期|予想|配当", t):
                c = r.get("コード", "")
                c = c[:4] if len(c) == 5 and c.endswith("0") else c
                out.append((c, r["日付"], r.get("時刻", "")[:5]))
    return out


def jpx_schedule():
    """JPX の決算発表予定日：{(コード, 日付): (q, 決算期末)}。同じ一覧に同じ銘柄が何度も出るときは作成日の新しいファイル"""
    import pandas as pd
    files = sorted(set(BASE.glob("kessan*.xlsx")) | set((BASE / "決算発表予定日").glob("*.xlsx")))
    best = {}
    for f in files:
        try:
            x = pd.read_excel(f, header=None)
        except Exception:
            continue
        title = str(x.iat[0, 0])
        mm = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", str(x.iat[2, 0]))
        asof = (int(mm[1]), int(mm[2]), int(mm[3])) if mm else (0, 0, 0)
        for _, r in x.iloc[5:].iterrows():
            d = pd.to_datetime(r.iloc[0], errors="coerce")
            c = str(r.iloc[1]).strip().upper()
            if pd.isna(d) or not re.fullmatch(r"\d{3}[0-9A-Z]", c):
                continue
            k = unicodedata.normalize("NFKC", str(r.iloc[7]))
            q = "1" if "1" in k else "2" if "2" in k else "3" if "3" in k else "4"
            fe = pd.to_datetime(r.iloc[4], errors="coerce")
            key = (title, c)
            if key not in best or asof > best[key][0]:
                best[key] = (asof, d.strftime("%Y-%m-%d"), q, fe.strftime("%Y-%m-%d") if not pd.isna(fe) else "")
    return {(c, d): (q, fe) for (_, c), (_, d, q, fe) in best.items()}


def stocks():
    rows = json.load(open(SITE / "_summary.json", encoding="utf-8"))
    dd = json.load(open(FUND / "analysis" / "dashboard_data.json", encoding="utf-8"))
    ix = {k: i for i, k in enumerate(dd["fields"])}
    mc = {str(r[0]): _f(r[ix["時価総額(億円)"]]) for r in dd["stocks"]}
    S = []
    for s in rows:
        c = str(s.get("code", ""))
        if c:
            S.append([c, unicodedata.normalize("NFKC", s.get("name", "")), s.get("mk", ""),
                      round(mc[c], 1) if mc.get(c) is not None else None, _f(s.get("close")), _f(s.get("chg"))])
    asof = max((s.get("date", "") for s in rows), default="")
    return S, asof


def mil(v):
    return round(v / 1e6) if v is not None else None   # 百万円


def build_data():
    """E: [S の番号, 日付, 時刻, 区分, 状態(0発表済み 1予定 2予想), 種別, 達成率, 天気(1☀️2☁️3☂️), 会社予想経常(百万円), 基準('経常'/'税前')]"""
    today = datetime.date.today().isoformat()
    S, asof = stocks()
    si = {s[0]: i for i, s in enumerate(S)}
    recs, fcs, jq_last = disclosures()
    prog = {}
    for r in recs:
        r["ach"] = achieve(r, fcs)
        prog[(r["code"], r["fy"], r["q"])] = r["ach"]
    E, last = [], {}
    for r in sorted(recs, key=lambda r: r["date"]):
        last[r["code"]] = r
        if r["date"] < SINCE or r["code"] not in si:
            continue
        base = prog.get((r["code"], fy_prev(r["fy"]), r["q"])) if r["q"] != "4" else None
        fc = r["fc"]
        if fc is None:   # 予想を出していない短信は、その時点の最新の予想
            p = fc_at(fcs, r["code"], fy_next(r["fy"]) if r["q"] == "4" else r["fy"], r["date"] + "~")
            fc = p[1] if p and p[2] == r["basis"] else None
        E.append([si[r["code"]], r["date"], r["hm"], slot_of(r["hm"]), 0, KIND[r["q"]],
                  r["ach"], weather(r["q"], r["ach"], base), mil(fc), r["basis"]])
    have = {(e[0], e[1]) for e in E}
    for c, d, hm in monthly():
        if c in si and (si[c], d) not in have and d < today:
            have.add((si[c], d))
            E.append([si[c], d, hm, slot_of(hm), 0, "月次", None, 0, None, ""])
    # これから
    got = set()
    for (c, d), (q, fe) in jpx_schedule().items():
        if d >= today and c in si:
            got.add(c)
            p = fc_at(fcs, c, fe)
            E.append([si[c], d, "", 0, 1, KIND[q], None, 0, mil(p[1]) if p else None, p[2] if p else ""])
    import make_watch as W
    lim = (datetime.date.today() + datetime.timedelta(days=120)).isoformat()
    for c, (d, k) in W._earnings().items():
        if k != 2 or c in got or c not in si or not (today <= d <= lim):
            continue
        r = last.get(c)
        if r:
            q, fy = ("1", fy_next(r["fy"])) if r["q"] == "4" else (str(int(r["q"]) + 1), r["fy"])
            p = fc_at(fcs, c, fy)
        else:
            q, p = None, None
        E.append([si[c], d, "", 0, 2, KIND[q] if q else "", None, 0, mil(p[1]) if p else None, p[2] if p else ""])
    E.sort(key=lambda e: (e[1], -(S[e[0]][3] or 0)))
    n_f = sum(1 for e in E if e[4])
    print(f"決算カレンダー: 発表済み {len(E) - n_f}件（{SINCE}〜、うち月次 {sum(1 for e in E if e[5] == '月次')}）・これから {n_f}件"
          f"（予定 {sum(1 for e in E if e[4] == 1)}・予想 {sum(1 for e in E if e[4] == 2)}）")
    return {"site": "jp", "asof": asof, "today": today, "built": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "since": SINCE, "src": {"jq": jq_last}, "S": S, "E": E}


NOTE = ("日付を押すとその日に決算を発表する（した）銘柄の一覧が出ます。コード・銘柄名を押すと株式分析ダッシュボードを開きます。"
        "これからの日付は JPX の「決算発表予定日」に載っている日、まだ載っていない銘柄は昨年の同じ時期の発表日から推定した日（発表時間の欄に「予想」）です。"
        "達成率は、四半期・中間決算は期首からの累計の経常利益が今期の会社予想の何％に達したか、本決算は経常利益の実績がその期の最後の会社予想の何％だったかです"
        "（経常利益が無い IFRS などの会社は税引前利益で計算し「税前」と表示）。"
        "天気は、本決算は ☀️ 100%以上・☁️ 95〜100%・☂️ 95%未満、四半期・中間決算は前年の同じ四半期の達成率（無ければ 25・50・75%）と比べて ☀️ 上回る・☁️ 5ポイント以内の下回り・☂️ それ以上の下回りです。"
        "会社予想経常利益は、発表済みの行はその決算短信の今期の予想（本決算は新しい期の予想）、これからの行は今の最新の予想です。"
        "数字は __JQ__ までは J-Quants、それより後は TDnet の決算短信から読んだ値。月次は TDnet の開示一覧で表題に「月次」とあるものです。"
        "時価総額・市場・監視銘柄の一覧表で絞り込めます。")


def build(head: str, site_name: str = "東証 株分析"):
    import kessan_cal_page as K
    data = build_data()
    note = NOTE.replace("__JQ__", data["src"]["jq"].replace("-", "/")[5:])
    return K.write(SITE, data, head, site_name, note)


if __name__ == "__main__":
    import make_home
    t = make_home.TMPL
    head = t[t.index("<script>(function(){var m="):t.index("</style>") + len("</style>")]
    p = build(head)
    print(f"決算カレンダーを作成: {p}")
