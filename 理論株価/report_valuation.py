"""理論株価のダッシュボード data/charts/valuation.html と、トップ画面のカード用 valuation_summary.json を作る。
valuation.py の結果（fundamentals/valuation.csv・理論株価/data/meta.json）を読むだけ。通信なし・数秒。
見た目は需給分析と共通（需給分析/jukyu_style.css を読み込む）。ページ本体は valuation_page.html。"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

DIR = Path(__file__).resolve().parent
BASE = DIR.parent
SITE = BASE / "data" / "charts"

# ページに渡す列（短い名前 → CSVの列名）
HM_FIELDS = [('hbr', '事業比率(%)'), ('hal', '最新α値(%)'), ('hav', '平均α値(%)'), ('hp10', '10年来株価(%)'), ('hphi', '株価高値比(%)'), ('hphm', '株価高値後(月)'), ('ht10', '10年来理論(%)'), ('htud', '理論増減数'), ('htn', '理論の遷移回数'), ('hthi', '理論高値比(%)'), ('hthm', '理論高値後(月)'), ('htp', '理論の期間'), ('hca', '全相関度(%)'), ('hc1', '1年相関度(%)'), ('hrt', '直近理論(%)'), ('hrp', '直近株価(%)'), ('hrv', '直近出来高(%)'), ('hto', '月間回転率(%)'), ('hvh', '出来高過熱'), ('hin', 'イナゴ指数(%)'), ('hij', 'イナゴ判定'), ('hliq', '流動性(万)'), ('hdud', '配当増減数'), ('hdn', '配当の遷移回数'), ('hdhi', '配当高値比(%)'), ('hfy', '決算期'), ('hly', '上場年数'), ('k1', '正相関度〇'), ('k2', '割安修正〇'), ('k3', '持続成長〇'), ('k4', '配当成長〇'), ('k', 'コア4条件'), ('hcls', '割安･収益性'), ('hds', 'データ開始日'), ('hdy', '配当利回り(%)')]

FIELDS = [
    ("c", "コード"), ("n", "銘柄名"), ("m", "市場"), ("s", "業種"), ("fin", "金融"), ("px", "株価"),
    ("cap", "時価総額(億円)"),
    ("per", "PER法"), ("pbr", "PBR法"), ("dcf", "DCF法"), ("ddm", "DDM"),
    ("nm", "有効手法数"), ("f", "理論株価(ファンダ)"), ("disp", "手法のばらつき(%)"),
    ("js", "需給スコア"), ("jv", "需給判定"), ("fj", "需給係数"), ("psy", "心理指数"), ("fp", "心理係数"),
    ("vj", "理論株価(需給補正)"), ("vp", "理論株価(心理補正)"), ("va", "理論株価(需給・心理込み)"),
    ("lo", "業種PER帯_弱気"), ("mid", "業種PER帯_中立"), ("hi", "業種PER帯_強気"),
    ("fper", "予想PER"), ("sper", "業種予想PER中央値"),
    ("ig", "織り込み成長率(%)"), ("g1", "想定成長率(%)"), ("gap", "期待ギャップ(%pt)"),
    ("ke", "株主資本コスト(%)"), ("wacc", "WACC(%)"), ("jpbr", "理論PBR"), ("gd", "配当成長率(%)"),
    ("spbr", "業種PBR中央値"), ("seve", "業種EV/EBITDA中央値"), ("rel", "信頼度"), ("note", "注意"), ("hpbr", "過去3期のPBR"), ("ccr", "利益の現金化率(%)"),
    ("f0", "理論株価(引き下げ前)"), ("adj", "引き下げ"), ("adju", "引き上げ"), ("pm", "PER法の倍率"), ("pbs", "PER法の基準"), ("oper", "自社過去PER(加重平均)"), ("pbm", "PBR法の倍率"), ("pbb", "PBR法の基準"), ("fbps", "BPS(実績)"), ("proe", "PBR法のROE(%)"),
    ("cfcf", "計算_DCF_FCF(億円)"), ("cfs", "計算_DCF_FCFの基準"), ("cev", "計算_DCF_事業価値(億円)"), ("cnd", "計算_純有利子負債(億円)"),
    ("csh", "計算_株数(百万株)"), ("cd0", "計算_DDM_配当(円)"), ("cpo", "計算_配当性向(%)"), ("ceb", "計算_EBITDA(億円)"),
    ("cer", "計算_自己資本比率(%)"), ("crt", "計算_割引評価率"),
    ("che", "計算_はっしゃん_EPS"), ("chr", "計算_はっしゃん_ROA(%)"), ("clv", "計算_レバレッジ補正"), ("ckj", "計算_経常利益(億円)"),
    ("ctg", "計算_RIM_目標ROE(%)"), ("cex", "計算_除外した手法"), ("epsv", "予想EPS"), ("epss", "予想EPSの出所"), ("hmed", "自社過去PBR(中央値)"), ("anc", "自社PBR基準の株価"),
    ("h", "はっしゃん式"), ("hcap", "はっしゃん式_上限"), ("ha", "はっしゃん式_資産価値"), ("hb", "はっしゃん式_事業価値"), ("hr", "はっしゃん式_リスク評価率"),
    ("mean", "理論株価_平均値"), ("mode", "理論株価_最頻値"), ("mode_n", "最頻値の手法数"), ("sd", "理論株価_標準偏差"), ("cv", "変動係数(%)"),
    ("tk", "東洋経済式"), ("tpv", "東洋経済式_超過利益の現在価値"), ("tke", "計算_東洋_株主資本コスト(%)"), ("tb", "計算_東洋_ベータ"),
    ("te2", "計算_東洋_来期EPS"), ("te2s", "計算_東洋_来期EPSの出所"), ("tb1", "計算_東洋_今期予想BPS"), ("tdv", "計算_東洋_配当"),
    ("tr1", "計算_東洋_超過利益1"), ("tr2", "計算_東洋_超過利益2"), ("tcap", "計算_東洋_上限適用"), ("tn", "計算_東洋_n期"), ("tbps", "計算_東洋_BPS"), ("tbs", "計算_東洋_BPSの出所"), ("troe", "計算_東洋_延長ROE(%)"),
    ("tr3", "計算_東洋_超過利益3"), ("tr4", "計算_東洋_超過利益4"), ("tr5", "計算_東洋_超過利益5"), ("tr6", "計算_東洋_超過利益6"), ("tr7", "計算_東洋_超過利益7"), ("tr8", "計算_東洋_超過利益8"), ("tr9", "計算_東洋_超過利益9"), ("tr10", "計算_東洋_超過利益10"), ("tpv3", "計算_東洋_超過利益(3期目以降)の現在価値"), ("traw", "計算_東洋_上限前"),
    ("rim", "RIM"), ("rpv", "RIM_残余利益の現在価値"), ("rtv", "RIM_継続価値"), ("roe1", "今期予想ROE(%)"), ("sroe", "業種ROE中央値(%)"), ("iroe", "織り込みROE(%)"),
]


def clean(v):
    if v is None:
        return None
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
        return round(v, 2) if abs(v) < 1000 else round(v)
    if isinstance(v, (bool,)):
        return int(v)
    try:
        import numpy as np
        if isinstance(v, np.generic):
            return clean(v.item())
    except Exception:
        pass
    return v


def main() -> int:
    d = pd.read_csv(BASE / "fundamentals" / "valuation.csv", dtype={"コード": str}, low_memory=False)
    meta = json.loads((DIR / "data" / "meta.json").read_text(encoding="utf-8"))
    d["金融"] = d["金融"].astype(str).str.lower().isin(["true", "1"])
    hmf = BASE / "fundamentals" / "hashang_metrics.csv"
    if hmf.exists():
        hm = pd.read_csv(hmf, dtype={"コード": str}, low_memory=False)
        d = d.merge(hm[["コード"] + [c for _, c in HM_FIELDS if c in hm.columns]], on="コード", how="left")
    for _, c in HM_FIELDS:
        if c not in d.columns:
            d[c] = None
    FIELDS_ALL = FIELDS + HM_FIELDS
    rows = [[clean(r[c]) for _, c in FIELDS_ALL] for _, r in d.iterrows()]

    ok = d[d["理論株価(ファンダ)"].notna()]
    lens = {"ファンダ": "乖離率(ファンダ)(%)", "需給補正": "乖離率(需給補正)(%)",
            "心理補正": "乖離率(心理補正)(%)", "需給・心理込み": "乖離率(需給・心理込み)(%)",
            "はっしゃん式": "乖離率(はっしゃん式)(%)", "RIM": "乖離率(RIM)(%)", "東洋経済式": "乖離率(東洋経済式)(%)",
            "平均値": "乖離率(平均値)(%)", "最頻値": "乖離率(最頻値)(%)"}
    summ = {"asof": meta.get("asof"), "生成": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "銘柄数": int(len(d)), "算出数": int(len(ok)), "rf": meta.get("rf"), "rf_src": meta.get("rf_src"),
            "lens": {}}
    for k, c in lens.items():
        v = ok[c].dropna()
        summ["lens"][k] = {"中央値": round(float(v.median()), 1), "割安20": int((v >= 20).sum()),
                           "割高20": int((v <= -20).sum()), "割安率": round(float((v > 0).mean() * 100), 1)}
    summ["変動係数中央値"] = round(float(ok["変動係数(%)"].median()), 1)
    (SITE / "valuation_summary.json").write_text(json.dumps(summ, ensure_ascii=False, indent=1), encoding="utf-8")

    css = (BASE / "需給分析" / "jukyu_style.css").read_text(encoding="utf-8")
    css += (DIR / "valuation_extra.css").read_text(encoding="utf-8")
    page = (DIR / "valuation_page.html").read_text(encoding="utf-8")
    # RIM の長期ROE：自社の過去の平均ROEへ戻る（2026-11-27 から。valuation.py の own_roe）
    page = page.replace("3〜10年目に業種のROE中央値へ直線で収れん（競争で超過利益が薄れる想定）",
                        "3〜10年目に自社の過去の平均ROE（純利益÷平均自己資本の平均）へ直線で収れん。過去のROEが無い銘柄は業種のROE中央値＋上回る分の半分")
    data = {"f": [k for k, _ in FIELDS_ALL], "rows": rows, "meta": meta, "sum": summ}
    page = (page.replace("/*CSS*/", css)
                .replace("/*DATA*/", json.dumps(data, ensure_ascii=False, separators=(",", ":")))
                .replace("__ASOF__", str(meta.get("asof")))
                .replace("__GEN__", summ["生成"]))
    (SITE / "valuation.html").write_text(page, encoding="utf-8")
    print(f"理論株価ページを作成: {SITE/'valuation.html'}（{len(ok)} 銘柄）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
