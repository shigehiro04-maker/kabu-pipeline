#!/usr/bin/env python3
"""日経225ツールの共通部品（パス・業種とセクターの対応・データの読み込み）。

日経平均の構成銘柄の選定は「日経業種分類（36業種）」を7つのセクターに集約して行う。
東証の33業種しか持っていない銘柄（＝未採用銘柄）は、33業種→日経36業種の対応表で近似し、
採用銘柄は日経平均プロフィルの構成銘柄一覧に載っている公式の業種で上書きする。
"""
from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent            # ~/株分析/日経225
BASE = HERE.parent                                # ~/株分析
DATA = HERE / "data"
OUT = HERE / "output"
PRICES = BASE / "data" / "prices"
DAILY = BASE / "data" / "daily"
SPLITS = BASE / "data" / "splits.csv"
SECTORS = BASE / "tickers" / "sectors.csv"
NIKKEI_IDX = BASE / "株価指数" / "data" / "nikkei225.csv"
TOPIX_IDX = BASE / "株価指数" / "data" / "topix.csv"
SITE = BASE / "data" / "charts"
FUND = BASE / "fundamentals"

# データファイル（日経225/data/）
F_COMPONENTS = DATA / "components.csv"      # 現在の構成銘柄（code,name,company,industry）公式ページから
F_FACTORS = DATA / "factors.csv"            # 株価換算係数（code,factor,cap_ratio,asof,source）
F_EVENTS = DATA / "events.csv"              # 入れ替え・係数変更の履歴（2021年10月〜）
F_DIVISOR = DATA / "divisor.csv"            # 除数の公表値（date,divisor,title）
F_NEWS_STATE = DATA / "news_state.json"     # 読み込み済みのニュースPDF
F_OVERRIDE = DATA / "industry_override.csv" # 日経業種の手動上書き（code,industry,from,note）
F_EXCLUDE = DATA / "exclude.csv"            # 採用候補から外す銘柄（特別注意銘柄・上場廃止予定など）

# ------------------------------------------------------------------ 業種とセクター
NK36_TO_SECTOR7 = {   # 2026年10月1日適用の選定基準（7セクター）
    "電気機器": "技術", "自動車": "技術", "精密機器": "技術",
    "情報通信": "情報通信",
    "銀行": "金融", "その他金融": "金融", "証券": "金融", "保険": "金融",
    "水産": "消費", "食品": "消費", "医薬品": "消費", "小売業": "消費", "サービス": "消費",
    "鉱業": "素材", "繊維": "素材", "パルプ・紙": "素材", "化学": "素材", "石油": "素材",
    "ゴム": "素材", "窯業": "素材", "鉄鋼": "素材", "非鉄・金属": "素材", "商社": "素材",
    "建設": "資本財・その他", "機械": "資本財・その他", "造船": "資本財・その他",
    "輸送用機器": "資本財・その他", "その他製造": "資本財・その他", "不動産": "資本財・その他",
    "鉄道・バス": "運輸・公共", "陸運": "運輸・公共", "海運": "運輸・公共", "空運": "運輸・公共",
    "倉庫": "運輸・公共", "電力": "運輸・公共", "ガス": "運輸・公共",
}
# 2026年9月以前（6セクター）：医薬品・通信は「技術」、サービスは「消費」。情報通信セクターは無い
NK36_TO_SECTOR6 = dict(NK36_TO_SECTOR7)
NK36_TO_SECTOR6.update({"医薬品": "技術", "通信": "技術", "サービス": "消費", "情報通信": "消費"})
SECTOR7 = ["技術", "情報通信", "金融", "消費", "素材", "資本財・その他", "運輸・公共"]
SECTOR6 = ["技術", "金融", "消費", "素材", "資本財・その他", "運輸・公共"]
SEVEN_SECTOR_FROM = "2026-10-01"   # この日以降に実施される見直しは7セクター

TSE33_TO_NK36 = {
    "水産・農林業": "水産", "鉱業": "鉱業", "建設業": "建設", "食料品": "食品",
    "繊維製品": "繊維", "パルプ・紙": "パルプ・紙", "化学": "化学", "医薬品": "医薬品",
    "石油・石炭製品": "石油", "ゴム製品": "ゴム", "ガラス・土石製品": "窯業", "鉄鋼": "鉄鋼",
    "非鉄金属": "非鉄・金属", "金属製品": "非鉄・金属", "機械": "機械", "電気機器": "電気機器",
    "輸送用機器": "自動車", "精密機器": "精密機器", "その他製品": "その他製造",
    "電気・ガス業": "電力", "陸運業": "陸運", "海運業": "海運", "空運業": "空運",
    "倉庫・運輸関連業": "倉庫", "情報・通信業": "情報通信", "卸売業": "商社", "小売業": "小売業",
    "銀行業": "銀行", "証券、商品先物取引業": "証券", "保険業": "保険", "その他金融業": "その他金融",
    "不動産業": "不動産", "サービス業": "サービス",
}
# 旧基準（〜2026年9月）で「通信（技術セクター）」だった通信キャリア等。それ以外の情報通信は「サービス（消費）」
OLD_TELECOM = {"9432", "9433", "9434", "9984", "9613"}

RAIL_WORDS = ("鉄道", "電鉄", "旅客", "急行", "阪急", "東急", "近鉄", "小田急", "京王", "京成",
              "西武", "東武", "名鉄", "南海", "京阪", "相鉄", "西日本鉄道", "メトロ", "地下鉄")


def nk36_from_tse(tse33: str, name: str = "") -> str:
    ind = TSE33_TO_NK36.get(str(tse33), "")
    if ind == "電力" and "ガス" in str(name):
        ind = "ガス"
    if ind == "陸運" and any(w in str(name) for w in RAIL_WORDS):
        ind = "鉄道・バス"
    return ind


def sector_of(industry: str, code: str, effective: str) -> str:
    """日経36業種 → セクター。effective（見直しの実施日）で6/7セクターを切り替える"""
    if not industry:
        return ""
    if str(effective) >= SEVEN_SECTOR_FROM:
        if industry == "通信":
            industry = "情報通信"
        return NK36_TO_SECTOR7.get(industry, "")
    if industry in ("情報通信", "通信"):
        return "技術" if code in OLD_TELECOM else "消費"
    return NK36_TO_SECTOR6.get(industry, "")


# ------------------------------------------------------------------ 読み込み
def read_csv_str(path: Path, **kw) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"code": str}, encoding="utf-8-sig", **kw)


def load_components() -> pd.DataFrame:
    return read_csv_str(F_COMPONENTS)


def load_factors() -> pd.DataFrame:
    f = read_csv_str(F_FACTORS)
    f["factor"] = f["factor"].astype(float)
    f["cap_ratio"] = f["cap_ratio"].fillna(1.0).astype(float)
    return f


def effective_factor(factor: float, cap_ratio: float) -> float:
    """キャップ調整済み株価換算係数（小数点以下第1位で切り捨て。キャップ未設定なら係数そのもの）"""
    if cap_ratio is None or np.isnan(cap_ratio) or abs(cap_ratio - 1.0) < 1e-9:
        return float(factor)
    return float(np.floor(factor * cap_ratio * 10 + 1e-9) / 10)


def load_events() -> pd.DataFrame:
    e = read_csv_str(F_EVENTS)
    for c in ("old", "new"):
        e[c] = pd.to_numeric(e[c], errors="coerce")
    return e


def load_sectors_table() -> pd.DataFrame:
    """tickers/sectors.csv（JPXの銘柄一覧）に日経36業種の近似を付ける"""
    s = pd.read_csv(SECTORS, dtype=str, encoding="utf-8-sig")
    s["code"] = s["code"].str.strip()
    s["nk_industry"] = [nk36_from_tse(a, b) for a, b in zip(s.get("sector33", ""), s["name"])]
    s["is_prime"] = s["market"].fillna("").str.contains("プライム")
    # 公式の業種（構成銘柄一覧）と手動上書きで差し替える
    over = industry_overrides()
    s["nk_industry"] = [over.get(c, i) for c, i in zip(s["code"], s["nk_industry"])]
    return s


def industry_overrides() -> dict:
    """日経36業種の上書き。構成銘柄一覧（公式）＞ industry_override.csv の順で優先"""
    m = {}
    if F_OVERRIDE.exists():
        for r in csv.DictReader(open(F_OVERRIDE, encoding="utf-8-sig")):
            if r.get("code") and r.get("industry"):
                m[r["code"].strip()] = r["industry"].strip()
    if F_COMPONENTS.exists():
        c = load_components()
        for code, ind in zip(c["code"], c["industry"]):
            if isinstance(ind, str) and ind:
                m[code] = ind
    return m


def load_excludes(on: str | None = None) -> dict:
    """採用候補から外す銘柄 {code: reason}。on（YYYY-MM-DD）を渡すとその日に有効なものだけ"""
    if not F_EXCLUDE.exists():
        return {}
    out = {}
    for r in csv.DictReader(open(F_EXCLUDE, encoding="utf-8-sig")):
        c = (r.get("code") or "").strip()
        if not c:
            continue
        frm, until = (r.get("from") or "").strip(), (r.get("until") or "").strip()
        if on and ((frm and on < frm) or (until and on > until)):
            continue
        out[c] = (r.get("reason") or "").strip()
    return out


def load_index(path: Path) -> pd.Series:
    d = pd.read_csv(path)
    d["Date"] = pd.to_datetime(d["Date"])
    return d.set_index("Date")["Close"].astype(float).sort_index()


def load_price_panel(codes=None, start: str | None = None) -> pd.DataFrame:
    """data/prices/<code>.csv を縦長に読み込む（date,code,high,low,close,volume,tv）。
    tv（売買代金の近似）＝終値×出来高。分割調整済みの株価×出来高なので分割の前後で連続する。"""
    frames = []
    files = sorted(PRICES.glob("*.csv")) if codes is None else [PRICES / f"{c}.csv" for c in codes]
    for p in files:
        if not p.exists():
            continue
        try:
            d = pd.read_csv(p, usecols=["date", "high", "low", "close", "volume"])
        except Exception:
            continue
        if start:
            d = d[d["date"] >= start]
        if d.empty:
            continue
        d["code"] = p.stem
        frames.append(d)
    if not frames:
        return pd.DataFrame(columns=["date", "code", "high", "low", "close", "volume", "tv"])
    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])
    df["tv"] = df["close"] * df["volume"]
    return df


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)
