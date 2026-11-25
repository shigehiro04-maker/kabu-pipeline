"""スクリーニング条件の定義表（screening_conditions.csv ほか）を読み、
東証株分析の既存CSVを結合して、絞り込みとランキングを行う。

使い方（~/株分析 で実行）:
  # 条件で絞り込む（ID:下限:上限。片側は空欄でよい）
  .venv/bin/python screening_config/screening_engine.py screen \
      FIN_PER:0:15 FIN_PBR::1 TEC_RSI14::40 --market プライム --top 50

  # 区分の条件は ID=値1|値2
  .venv/bin/python screening_config/screening_engine.py screen FLT_SIZE=中型|小型 FIN_DY:3:

  # ランキング（ranking_definitions.csv のID）
  .venv/bin/python screening_config/screening_engine.py rank R16 --top 30

  # 定義の一覧
  .venv/bin/python screening_config/screening_engine.py list --category 財務

条件の値は「既存列」をそのまま使うか（状態=active）、DERIVED の計算で作る
（状態=derived / approx）。状態=new / unsupported の条件は警告を出して使わない。
NULLの扱いは null_policies.csv の5種類（exclude / pass / zero / fallback / scope_pass）。
"""
from __future__ import annotations

import argparse
import csv
import math
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

CONF_DIR = Path(__file__).resolve().parent
BASE = CONF_DIR.parent                      # ~/株分析
KEY = "コード"
MAIN_FILE = "fundamentals/fundamentals_latest.csv"
ACCT_COL = "fundamentals/cost_of_sales_latest.csv:会計基準"

NUMERIC_UNITS_EXCLUDED = {"区分", "真偽"}
USABLE = {"active", "derived", "approx"}


# ---------------------------------------------------------------- 定義の読み込み

def read_csv_rows(name: str) -> list[dict]:
    with open(CONF_DIR / name, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_config() -> tuple[dict, dict]:
    conds = {r["条件ID"]: r for r in read_csv_rows("screening_conditions.csv")}
    ranks = {r["ランキングID"]: r for r in read_csv_rows("ranking_definitions.csv")}
    return conds, ranks


def to_float(s: str):
    s = (s or "").strip()
    if s == "":
        return None
    return float(s)


# ---------------------------------------------------------------- データの読み込み

def norm_code(c) -> str:
    c = str(c).strip().upper()
    if len(c) == 5 and c.endswith("0"):
        c = c[:4]
    return c


def needed_files(conds: dict) -> set[str]:
    files = {MAIN_FILE}
    for r in conds.values():
        if r["状態"] not in USABLE:
            continue
        if r["既存ファイル"]:
            files.add(r["既存ファイル"])
        for item in filter(None, r["入力項目"].split(";")):
            if ":" in item and item.split(":", 1)[0].endswith(".csv"):
                files.add(item.split(":", 1)[0])
    files.add(ACCT_COL.split(":", 1)[0])
    return files


def load_universe(conds: dict, base: Path = BASE) -> pd.DataFrame:
    """主ファイル（fundamentals_latest.csv）の銘柄を土台に、各CSVを
    「ファイル名:列名」という列名でコード結合する。"""
    frames = {}
    for rel in sorted(needed_files(conds)):
        p = base / rel
        if not p.exists():
            print(f"[警告] {rel} が見つからないため、この表の条件はNULLになります", file=sys.stderr)
            continue
        df = pd.read_csv(p, dtype=str, encoding="utf-8-sig")
        if KEY not in df.columns and "code" in df.columns:
            df = df.rename(columns={"code": KEY})
        if KEY not in df.columns:
            print(f"[警告] {rel} にコード列が無いため読み飛ばします", file=sys.stderr)
            continue
        df[KEY] = df[KEY].map(norm_code)
        df = df.drop_duplicates(KEY, keep="last").set_index(KEY)
        df.columns = [f"{rel}:{c}" for c in df.columns]
        frames[rel] = df
    if MAIN_FILE not in frames:
        raise SystemExit(f"{MAIN_FILE} が読めません。~/株分析 で実行しているか確認してください")
    out = frames.pop(MAIN_FILE)
    for df in frames.values():
        out = out.join(df, how="left")
    return out


# ---------------------------------------------------------------- 計算式（derived / approx）

def num(df: pd.DataFrame, ref: str) -> pd.Series:
    if ref not in df.columns:
        return pd.Series(np.nan, index=df.index)
    return pd.to_numeric(df[ref], errors="coerce")


F = "fundamentals/fundamentals_latest.csv"
J = "fundamentals/jukyu.csv"
V = "fundamentals/valuation.csv"
S = "tickers/sectors.csv"
K = "fundamentals/nikkei225.csv"
EM = "fundamentals/edinet_metrics_latest.csv"


def _within(r, lo=0.5, hi=2.0):
    """比 r が [lo, hi] の外なら True（＝不整合）。判定できなければ False。"""
    return ((r < lo) | (r > hi)).fillna(False)


def eps_suspect(d):
    """PER と 時価総額÷当期純利益 が食い違う（EPS・株数・純利益のどれかが桁ずれ）、
    または当期純利益が EDINET DB と大きくずれる。"""
    ni = num(d, f"{F}:当期純利益")
    implied = num(d, f"{F}:時価総額") / ni.where(ni > 0)
    return _within(num(d, f"{F}:PER") / implied) | edinet_ni_suspect(d)


def sales_suspect(d):
    """売上高が前期・前々期から不自然に飛ぶ（1桁欠けなど）。"""
    s0, s1, s2 = (num(d, f"{F}:{c}") for c in ("売上高", "売上高_前期", "売上高_前々期"))
    return (_within(s0 / s1.where(s1 > 0), 0.2, 5) | _within(s1 / s2.where(s2 > 0), 0.2, 5)
            | (num(d, f"{F}:営業利益") > s0) | edinet_sales_suspect(d))


COS = "fundamentals/cost_of_sales_latest.csv"


def _same_year(d, file):
    """Yahoo の決算期と EDINET DB の年度が同じ年か（年度=2026 は 2026年3月期など）。"""
    y = d.get(f"{F}:決算期", pd.Series(np.nan, index=d.index)).astype(str).str[:4]
    e = d.get(f"{file}:年度", pd.Series(np.nan, index=d.index)).astype(str).str[:4]
    return (y == e) & e.str.fullmatch(r"\d{4}").fillna(False)


def edinet_sales_suspect(d):
    """売上高が EDINET DB（有報）と2割以上ずれる。金融業は売上の定義が違うので見ない。"""
    fin = d.get(f"{F}:業種", pd.Series("", index=d.index)).isin(
        ["銀行業", "保険業", "証券、商品先物取引業", "その他金融業"])
    e = num(d, f"{COS}:売上高")
    r = num(d, f"{F}:売上高") / e.where(e > 0)
    return _within(r, 0.8, 1.25) & _same_year(d, COS) & ~fin


def edinet_ni_suspect(d):
    """当期純利益が EDINET DB と2倍以上ずれる（符号が逆も含む）。"""
    e = num(d, f"{EM}:当期純利益")
    y = num(d, f"{F}:当期純利益")
    r = y / e.where(e.abs() > 0)
    flip = (np.sign(y) != np.sign(e)) & e.notna() & y.notna() & (e.abs() > 0)
    return (_within(r, 0.5, 2.0) | flip) & _same_year(d, EM)


def _data_ok(d):
    return ~(eps_suspect(d) | sales_suspect(d))


# 元データの不整合が疑われる銘柄は、その値に依存する条件を NULL にする（NULL > 不正確値）
EPS_DEPENDENT = {"FIN_PER", "FIN_EPS", "FIN_ROE", "FIN_ROA"}
SALES_DEPENDENT = {"FIN_SALES", "FIN_SALES_CHG", "FIN_PSR", "FIN_OPM", "FIN_KEIJO_MARGIN", "FIN_OP_CHG"}


def _roe(d):
    eq = num(d, f"{F}:自己資本")
    x = num(d, f"{F}:当期純利益") / eq.where(eq > 0) * 100
    return x.where(x.abs() <= 100)


def _de(d):
    eq = num(d, f"{F}:自己資本")
    return num(d, f"{F}:有利子負債").fillna(0) / eq.where(eq > 0) * 100


def _ev_ebitda(d):
    ebitda = num(d, f"{F}:EBITDA")
    ev = num(d, f"{F}:時価総額") + num(d, f"{F}:純有利子負債").fillna(0)
    return ev / ebitda.where(ebitda > 0)


def _pcfr(d):
    ocf = num(d, f"{F}:営業CF")
    return num(d, f"{F}:時価総額") / ocf.where(ocf > 0)


def _icr(d):
    it = num(d, f"{F}:支払利息")
    return num(d, f"{F}:営業利益") / it.where(it > 0)


def _keijo_margin(d):
    sales = num(d, f"{F}:売上高")
    x = num(d, f"{V}:計算_経常利益(億円)") * 1e8 / sales.where(sales > 0) * 100
    return x.where(x.abs() <= 100)


def _netcash_ratio(d):
    mcap = num(d, f"{F}:時価総額")
    return num(d, f"{EM}:ネットキャッシュ(円)") / mcap.where(mcap > 0)


def _topix100(d):
    s = d.get(f"{S}:size", pd.Series(np.nan, index=d.index))
    return s.isin(["TOPIX Core30", "TOPIX Large70"]).where(s.notna())


X = "fundamentals/technical_extra.csv"
SHAPES = {"SHP_SURGE": "急上昇", "SHP_UP": "上昇", "SHP_UPSTOP": "上昇ストップ", "SHP_PULLBACK": "調整",
          "SHP_RANGE": "もみ合い", "SHP_REBOUND": "リバウンド", "SHP_BOTTOM": "下げとまった",
          "SHP_DOWN": "下落", "SHP_PLUNGE": "急落"}


def _shape_is(name):
    def f(d):
        s = d.get(f"{X}:チャート形状(60日)", pd.Series(np.nan, index=d.index))
        return (s == name).where(s.notna())
    return f


DERIVED = {
    **{cid: _shape_is(name) for cid, name in SHAPES.items()},
    "FLT_INVEST": lambda d: num(d, f"{F}:株価") * 100,
    "FLT_TOPIX100": _topix100,
    "FIN_ROE": _roe,
    "FIN_ROA": lambda d: num(d, f"{F}:当期純利益")
    / num(d, f"{F}:総資産").where(lambda x: x > 0) * 100,
    "FIN_PRETAX_OKU": lambda d: num(d, f"{F}:税引前利益") / 1e8,
    "FIN_KEIJO_MARGIN": _keijo_margin,
    "FIN_DE": _de,
    "FIN_EV_EBITDA": _ev_ebitda,
    "FIN_PCFR": _pcfr,
    "FIN_ICR": _icr,
    "FLT_DATA_OK": _data_ok,
    "EDB_NETCASH_RATIO": _netcash_ratio,
    "VOL_DEV": lambda d: (num(d, f"{J}:出来高倍率(当日/25日)") - 1) * 100,
}

# 既存列をそのまま使う条件に、定義表の「NULL化ガード」を当てる
GUARDS = {
    "FIN_PER": lambda x: x.where(x > 0),
    "FIN_PBR": lambda x: x.where(x > 0),
    "FIN_DY": lambda x: x.where(x <= 10),
    "FIN_OPM": lambda x: x.where(x.abs() <= 1000),
    "FIN_PSR": lambda x: x.where(x > 0),
    "SUP_MARGIN_RATIO": lambda x: x.where(np.isfinite(x)),
    "CNS_FWD_PER": lambda x: x.where(x > 0),
}

SIZE_MAP = {"TOPIX Core30": "大型", "TOPIX Large70": "大型", "TOPIX Mid400": "中型"}


def condition_values(df: pd.DataFrame, cond: dict) -> pd.Series:
    cid, unit = cond["条件ID"], cond["単位"]
    if cid in DERIVED:
        v = DERIVED[cid](df)
    else:
        ref = f"{cond['既存ファイル']}:{cond['既存列']}"
        raw = df[ref] if ref in df.columns else pd.Series(np.nan, index=df.index)
        if cid == "FLT_SIZE":
            v = raw.map(lambda s: SIZE_MAP.get(s, "小型") if isinstance(s, str) else np.nan)
        elif cid == "FLT_N225":
            v = pd.to_numeric(raw, errors="coerce").fillna(0) == 1
        elif cid == "FLT_JPX400":
            # 一覧が未取得（空ファイル）の間は判定不能として NULL にする
            x = pd.to_numeric(raw, errors="coerce")
            v = (x.fillna(0) == 1) if x.notna().any() else pd.Series(np.nan, index=df.index)
        elif cid == "FLT_FIN_EXCLUDE":
            # True = 金融業ではない（＝残す銘柄）
            v = raw.map({"True": False, "False": True})
        elif unit == "区分":
            v = raw
        elif unit == "真偽":
            v = raw.map({"True": True, "False": False, "1": True, "0": False})
        else:
            v = pd.to_numeric(raw, errors="coerce")
    if cid in GUARDS:
        v = GUARDS[cid](v)
    if cid in EPS_DEPENDENT or cid in SALES_DEPENDENT:
        # どちらかの不整合に当たった銘柄は、同じ行の財務値全体が信用できないとみなす
        v = v.where(_data_ok(df))
    if unit not in NUMERIC_UNITS_EXCLUDED:
        v = pd.to_numeric(v, errors="coerce").replace([np.inf, -np.inf], np.nan)
    return v


# ---------------------------------------------------------------- 絞り込み

class Selection:
    """1つの条件指定。lo/hi は数値、values は区分の候補、want は真偽の期待値。"""

    def __init__(self, cid, lo=None, hi=None, values=None, want=True):
        self.cid, self.lo, self.hi, self.values, self.want = cid, lo, hi, values, want

    def __repr__(self):
        if self.values:
            return f"{self.cid}={'|'.join(self.values)}"
        return f"{self.cid}:{'' if self.lo is None else self.lo}:{'' if self.hi is None else self.hi}"


def parse_selection(text: str, conds: dict) -> Selection:
    m = re.fullmatch(r"([A-Z0-9_]+)\s*(>=|<=|>|<|=|:)?(.*)", text.strip())
    if not m or m.group(1) not in conds:
        raise SystemExit(f"条件IDが見つかりません: {text}")
    cid, op, rest = m.group(1), m.group(2), m.group(3)
    cond = conds[cid]
    if op is None:   # 既定の上下限を使う
        return Selection(cid, to_float(cond["既定の下限"]), to_float(cond["既定の上限"]))
    if op == ":":
        parts = (rest.split(":") + [""])[:2]
        return Selection(cid, to_float(parts[0]), to_float(parts[1]))
    if op == "=":
        if cond["単位"] == "真偽":
            return Selection(cid, want=rest.strip().lower() not in ("0", "false", "偽", "no"))
        if cond["単位"] == "区分":
            return Selection(cid, values=[x for x in rest.split("|") if x])
        v = float(rest)
        return Selection(cid, v, v)
    v = float(rest)
    if op in (">", ">="):
        return Selection(cid, lo=v + (1e-12 if op == ">" else 0))
    return Selection(cid, hi=v - (1e-12 if op == "<" else 0))


def apply_selection(df: pd.DataFrame, sel: Selection, conds: dict,
                    notes: list[str]) -> tuple[pd.Series, pd.Series | None]:
    """条件を満たす行の真偽Seriesと、表示用の値Seriesを返す。"""
    cond = conds[sel.cid]
    status, policy = cond["状態"], cond["NULLの扱い"]
    if status not in USABLE:
        notes.append(f"{sel.cid}（{cond['条件名']}）は状態={status} のため使いませんでした: {cond['備考']}")
        return pd.Series(True, index=df.index), None

    v = condition_values(df, cond)
    if policy == "fallback" and cond["代替条件ID"]:
        v = v.fillna(condition_values(df, conds[cond["代替条件ID"]]))
    if policy == "zero":
        v = v.fillna(0)
    isnull = v.isna()

    if sel.values:
        ok = v.isin(sel.values)
    elif cond["単位"] == "真偽" and sel.lo is None and sel.hi is None:
        ok = v == sel.want
    else:
        ok = pd.Series(True, index=df.index)
        if sel.lo is not None:
            ok &= v >= sel.lo
        if sel.hi is not None:
            ok &= v <= sel.hi
    ok = ok.fillna(False).astype(bool)

    if policy == "pass":
        ok |= isnull
    elif policy == "scope_pass":
        acct = df.get(ACCT_COL, pd.Series(np.nan, index=df.index))
        out_of_scope = acct.isin(["IFRS", "US"])
        # 範囲内（日本基準・不明）はNULLを落とす。範囲外はNULLのときだけ不問で通す
        ok = (ok & ~isnull) | (out_of_scope & isnull)
    else:  # exclude / zero / fallback（代替もNULLなら落とす）
        ok &= ~isnull
    return ok, v


def screen(df, selections, conds, market=None):
    notes: list[str] = []
    mask = pd.Series(True, index=df.index)
    shown = {}
    if market:
        sels = [Selection("FLT_MARKET", values=market)] + list(selections)
    else:
        sels = list(selections)
    for sel in sels:
        ok, v = apply_selection(df, sel, conds, notes)
        mask &= ok
        if v is not None and sel.cid != "FLT_MARKET":
            shown[conds[sel.cid]["条件名"]] = v
    out = base_columns(df).loc[mask].copy()
    for name, v in shown.items():
        out[name] = v.loc[mask]
    return out, notes


def base_columns(df):
    cols = {f"{F}:銘柄名": "銘柄名", f"{F}:市場": "市場", f"{F}:業種": "業種", f"{F}:株価": "株価"}
    out = df[[c for c in cols if c in df.columns]].rename(columns=cols)
    if "株価" in out:
        out["株価"] = pd.to_numeric(out["株価"], errors="coerce")
    return out


# ---------------------------------------------------------------- ランキング

def rank(df, rid, conds, ranks, top=None, market=None):
    r = ranks[rid]
    cid = r["並べる条件ID"]
    cond = conds[cid]
    notes: list[str] = []
    if r["状態"] not in USABLE or cond["状態"] not in USABLE:
        return None, [f"{rid}（{r['ランキング名']}）は状態={r['状態']} のため作れません: {r['備考'] or cond['備考']}"]

    sels = [parse_selection(x, conds) for x in filter(None, r["既定で除外"].split("|"))]
    sels += [parse_selection(x, conds) for x in filter(None, r["対象の絞り込み"].split("|"))]
    sels.append(Selection(cid))  # 並べる値がNULLの銘柄は自然に落ちる
    picked, notes = screen(df, sels, conds, market)
    base = base_columns(df).loc[picked.index]   # 絞り込み用の列は表示しない
    v = condition_values(df, cond)
    if cond["NULLの扱い"] == "zero":
        v = v.fillna(0)
    base = base.assign(**{cond["条件名"]: v.loc[base.index]}).dropna(subset=[cond["条件名"]])
    base = base.sort_values(cond["条件名"], ascending=(r["並び順"] == "asc"))
    n = top or int(r["表示件数"] or 100)
    base = base.head(n)
    base.insert(0, "順位", range(1, len(base) + 1))
    return base, notes


# ---------------------------------------------------------------- CLI

def main(argv=None):
    ap = argparse.ArgumentParser(description="定義表にもとづくスクリーニングとランキング")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("screen")
    p1.add_argument("conditions", nargs="+", help="例: FIN_PER:0:15 / FLT_SIZE=中型|小型 / FIN_ROE>=10")
    p2 = sub.add_parser("rank")
    p2.add_argument("ranking_id")
    for p in (p1, p2):
        p.add_argument("--market", nargs="*", help="プライム スタンダード グロース")
        p.add_argument("--top", type=int)
        p.add_argument("--out", help="結果をCSVに保存するパス")
    p3 = sub.add_parser("list")
    p3.add_argument("--category")
    p3.add_argument("--all", action="store_true", help="new / unsupported も表示")
    a = ap.parse_args(argv)

    conds, ranks = load_config()
    if a.cmd == "list":
        for r in conds.values():
            if a.category and r["区分"] != a.category:
                continue
            if not a.all and r["状態"] not in USABLE:
                continue
            print(f"{r['条件ID']:<20} {r['状態']:<11} {r['区分']:<8} {r['条件名']}（{r['単位']}）")
        return 0

    df = load_universe(conds)
    if a.cmd == "screen":
        sels = [parse_selection(x, conds) for x in a.conditions]
        out, notes = screen(df, sels, conds, a.market)
        # 並べ替えは、指定した順で最初の「数値の条件」の良い向きに従う
        for sel in sels:
            cond = conds[sel.cid]
            name = cond["条件名"]
            if (cond["単位"] not in NUMERIC_UNITS_EXCLUDED and name in out.columns
                    and pd.api.types.is_numeric_dtype(out[name])):
                out = out.sort_values(name, ascending=cond["良い向き"] != "高いほど良い")
                break
        total = len(out)
        if a.top:
            out = out.head(a.top)
        shown = f"（上位{len(out)}件を表示）" if len(out) < total else ""
        title = f"スクリーニング: {' '.join(map(str, sels))}  →  {total}銘柄{shown}"
    else:
        if a.ranking_id not in ranks:
            raise SystemExit(f"ランキングIDが見つかりません: {a.ranking_id}")
        out, notes = rank(df, a.ranking_id, conds, ranks, a.top, a.market)
        if out is None:
            print(notes[0])
            return 1
        title = f"ランキング {a.ranking_id}: {ranks[a.ranking_id]['ランキング名']}"

    for n in notes:
        print("[注意]", n, file=sys.stderr)
    print(title)
    with pd.option_context("display.max_rows", 200, "display.width", 200,
                           "display.unicode.east_asian_width", True):
        print(out.round(2).to_string())
    if a.out:
        out.to_csv(a.out, encoding="utf-8-sig")
        print(f"保存しました: {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
