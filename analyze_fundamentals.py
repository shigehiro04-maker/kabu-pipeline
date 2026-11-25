#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""東証全銘柄のファンダメンタル分析

fundamentals/fundamentals_latest.csv を入力に、
  1. 派生指標（ROE・ROA・純利益率・FCF利回り・配当性向 ほか）
  2. 四季報式スコア（成長性・収益性・安全性・規模・割安度・値上がりを各1〜5で評価し、
     その平均から総合評価1〜5を出す）
  3. 条件別スクリーニング（バリュー・高配当・グロース・クオリティ・GARP・資産バリュー・DOE・連続増配・PEG）
  4. 業種別／市場別の集計
を作り、CSV・Excel・ダッシュボード用JSON に出力する。

使い方:
    ./.venv/bin/python analyze_fundamentals.py
    ./.venv/bin/python analyze_fundamentals.py --min-cap 100   # 時価総額100億円以上に限定
    ./.venv/bin/python analyze_fundamentals.py --no-excel      # Excelを作らない

出力先: fundamentals/analysis/
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from forecast_fscore import YF_ALL, attach_forecast_fscore
from keijo_yosou import KEIJO_COLS, YOSOU_COLS, attach_keijo_yosou
from forecast_extra import EXTRA_COLS as FC_EXTRA_COLS, attach_forecast_extra

BASE = Path(__file__).resolve().parent
SRC = BASE / "fundamentals" / "fundamentals_latest.csv"
OUT = BASE / "fundamentals" / "analysis"
BANK_CAPITAL = BASE / "fundamentals" / "bank_capital.csv"
SECTORS = BASE / "tickers" / "sectors.csv"
BETA = BASE / "fundamentals" / "beta.csv"
NEW_HIGH = BASE / "fundamentals" / "new_high.csv"
NIKKEI225 = BASE / "fundamentals" / "nikkei225.csv"   # 日経225/run_nikkei225.py（採用・ウエート・入れ替え予想）
JUKYU = BASE / "fundamentals" / "jukyu.csv"           # 需給分析/analyze_jukyu.py（信用残・空売り・出来高の需給指標）
# 需給分析/analyze_jukyu.py の JUKYU_COLS と同じ（ここに直接書いて、需給分析が無くても動くようにする）
JUKYU_COLS = [
    "信用買残(株)", "信用売残(株)", "信用倍率(倍)", "買残前日比(株)", "売残前日比(株)",
    "買残5日変化(%)", "買残20日変化(%)", "売残5日変化(%)", "売残20日変化(%)",
    "買残上場比(%)", "売残上場比(%)", "買残回転日数(日)", "売残回転日数(日)", "一般信用買残比率(%)",
    "信用買い評価損益率(%)", "信用売り評価損益率(%)",
    "貸借倍率(倍)", "日証金差引(株)", "逆日歩(円)", "逆日歩(年率%)",
    "大口空売り比率(%)", "大口空売り報告数", "大口空売り30日変化(%pt)",
    "出来高(株)", "出来高倍率(当日/25日)", "売買代金25日平均(百万円)",
    "価格帯別出来高最多価格(円)", "最多価格帯からの乖離(%)", "上値出来高比率(%)",
    "信用区分", "規制等", "信用残の申込日", "需給スコア", "需給判定", "需給メモ",
]
TECHNICAL = BASE / "fundamentals" / "technical.csv"   # compute_technical.py（SBI式のテクニカル指標）

# compute_technical.py が出す列（SBI証券スクリーナーの「株価パフォーマンス」「テクニカル」相当）
TECH_COLS = [
    "前日比(円)", "前日比(%)", "5日騰落率(%)", "20日騰落率(%)",
    "対市場超過(1日)(%pt)", "対市場超過(20日)(%pt)",
    "売買代金(百万円)", "平均売買代金(百万円)", "売買代金増加率(%)", "出来高増加率(%)",
    "出来高倍率(6日/25日)", "60日ボラティリティ(%)", "52週安値からの上昇率(%)",
    "年初来高値からの日数", "年初来安値からの日数", "年初来高値乖離(%)", "年初来安値からの上昇率(%)",
    "GC(5×25)からの日数", "DC(5×25)からの日数", "GC(25×75)からの日数", "DC(25×75)からの日数",
    "GC(75×200)からの日数", "DC(75×200)からの日数",
    "一目 雲の位置", "雲上抜けからの日数", "雲下抜けからの日数", "ボリンジャー位置(σ)",
    "RSI(14)(%)", "RCI(9)(%)", "RCI(26)(%)", "ストキャス%K(9)", "ストキャス%D", "スローストキャス%D",
    "+DI(14)", "−DI(14)", "ADX(14)", "サイコロジカル(12)(%)", "MACDヒストグラム(%)", "MACD GCからの日数",
    "新値3本足", "新値3本足の転換からの日数", "ベータ(対業種)(1年)", "ドル円感応度(2年)",
]
# SBIの基本条件・財務にあって、手元のデータから作れるもの
SBI_BASIC_COLS = ["規模", "最低投資金額(万円)", "決算月", "PCFR"]
BY_YEAR = BASE / "fundamentals" / "fundamentals_by_year.csv"
JQ_SUMMARY = BASE / "fundamentals" / "jq_summary"   # J-Quants fins summary（会社予想）
SEC_CAPITAL = BASE / "fundamentals" / "securities_capital.csv"
INS_SOLVENCY = BASE / "fundamentals" / "insurance_solvency.csv"
COMPANY_PROFILE = BASE / "fundamentals" / "company_profile.csv"

# 上場廃止の判定。JPXの銘柄一覧から消えていて、かつ株価がこの日数以上止まっている銘柄。
# 片方だけでは足りない。一覧は月末時点なので新規上場は載っておらず（ただし株価は最新）、
# 株価の遅れだけでは売買の薄い銘柄や取引停止中の銘柄まで拾ってしまう。
DELISTED_STALE_DAYS = 7

# バーゼル規制上の最低所要水準。これを何%pt上回っているかで銀行の健全性を測る。
#   国内基準行     コア資本比率 4.0%
#   国際統一基準行 普通株式等Tier1(CET1)比率 4.5% ＋ 資本保全バッファー 2.5% ＝ 7.0%
# 資本保全バッファーは国際統一基準行にのみ適用される。
# G-SIBサーチャージ（三菱UFJ・三井住友・みずほへの1.0〜1.5%上乗せ）は銀行ごとに違い
# 毎年見直されるため含めていない。3メガの余裕度はその分だけ甘めに出る。
MIN_CAPITAL = {"国内基準": 4.0, "国際統一基準": 7.0}

# 決算がこの日数より古い銘柄は「決算が古い」とフラグを立てる
# （期末から13か月＝開示期限45日を大きく超えた時点）
STALE_DAYS = 400

# 金融セクター（営業利益・流動比率の概念が標準化財務諸表に無い）
FINANCIAL_SECTORS = {"銀行業", "保険業", "証券、商品先物取引業", "その他金融業"}

# ------------------------------------------------------- マルチバガー判定
#
# Yartseva (2025) "The Alchemy of Multibagger Stocks"（米国の10倍株464銘柄の
# 動的パネル分析）の実証結果を、日本株と手元のデータに合わせて条件にしたもの。
# 論文の主な結論:
#   ・バリュー（簿価/時価 と FCF利回り）が将来リターンの最大の説明変数
#   ・小型ほど有利（低ベース効果）。収益性はROA・EBITDAマージンが有意
#   ・資産の伸びがEBITDAの伸びを超える「身の丈を超えた投資」は
#     翌年リターンを4〜11%pt下げる（投資そのものは悪ではない）
#   ・52週高値に近いほど翌年リターンが低い。安値圏で拾うほど良い
#   ・増収率・EPS成長率などの「成長」自体には将来リターンの予測力が無い
#   ・PERは予測に役立たない。利上げ局面は翌年リターンを約10%pt下げる
#
# FCF利回りの水準は業種で大きく違うので、基準は業種ごとに変えている。
# （ソフトウェアは複製コストが低く、小売は在庫の改善余地が大きい、など）
#   区分名, 対象業種, FCF利回りの下限(%), 時価総額の下限(億円), 上限(億円)
MB_SECTOR_RULES = [
    ("情報通信", {"情報・通信業"}, 4.0, 500, 3000),
    ("サービス", {"サービス業"}, 5.0, 300, 2000),
    ("小売", {"小売業"}, 6.0, 200, 1500),
    ("製造業", {"食料品", "繊維製品", "パルプ・紙", "化学", "医薬品", "石油・石炭製品",
              "ゴム製品", "ガラス・土石製品", "鉄鋼", "非鉄金属", "金属製品", "機械",
              "電気機器", "輸送用機器", "精密機器", "その他製品"}, 5.0, 500, 5000),
]
# 上のどれにも当てはまらない業種（建設・不動産・卸売・運輸・電気ガスなど）の既定値
MB_DEFAULT_RULE = ("その他", 5.0, 100, 5000)

# 全業種に共通の下限・上限。機関投資家の買いが入る余地がある規模に絞る。
MB_CAP_MIN, MB_CAP_MAX = 100.0, 5000.0
MB_ROE_MIN = 15.0            # 直近期のROE
MB_OPM_MIN = 10.0            # 営業利益率＝価格決定力の裏づけ
MB_REV_GROWTH_MIN = 5.0      # 増収率（前期比・CAGRの両方）

# 金利環境の調整（論文: 利上げ局面は翌年リターンを約10%pt押し下げる）。
# 手元に政策金利のデータが無いので手動で指定する。既定は中立。
MB_RATE_ENV = {"逆風": -10.0, "中立": 0.0, "追い風": 5.0}

MB_YEARS = 4                 # 年次推移で見る最大期数（Yahooの保有期数の上限）
MB_SCORE_PASS = 70.0         # 「エントリー=OK」に必要なスコア
MB_RANGE_MAX = 30.0          # 52週レンジ位置の上限(%)
MB_CHG6M_MAX = 5.0           # 6か月騰落率の上限(%)

# ------------------------------------------------ マルチバガー判定（論文準拠版）
#
# 上の「マルチバガー候補」は実務判断で ROE・増収率などを足しているが、こちらは論文が
# 有意とした変数だけで絞り込み・採点する。論文の Fama-French ソート（B/M>0.40 かつ営業黒字で
# 超過リターンの確率が上がる）と動的パネル回帰（FCF/P・B/M・小型・Invダミー・52週位置・
# 3〜6か月モメンタムの反転・ROA）に対応。増収率・PER・負債比率は予測力が無いので使わない。
MBP_CAP_MIN, MBP_CAP_MAX = 20.0, 3000.0   # 億円。20億未満は流動性が低すぎる
MBP_PBR_MAX = 2.5                         # B/M ≧ 0.40
MBP_FCF_STABLE_MIN = 50.0                 # FCF黒字の期の割合(%)。論文外のノイズ対策
MBP_RANGE_OK, MBP_CHG6M_OK = 30.0, 0.0    # 「安値圏」= 52週位置≦30% かつ 6か月で上がっていない
MBP_FCF_SPIKE = 40.0                      # FCF利回りがこれを超えたら一時要因を疑う
# スコアの重み（候補内パーセンタイル×重み、合計100）。論文の係数の大きさの順を反映した目安
MBP_WEIGHTS = {"FCF利回り(%)": 30, "B/M": 25, "時価総額(億円)": 15,
               "52週レンジ位置(%)": 15, "125日騰落率(%)": 10, "ROA(%)": 5}
MBP_LOWER_IS_BETTER = {"時価総額(億円)", "52週レンジ位置(%)", "125日騰落率(%)"}

# ------------------------------------------------------------ 四季報式スコア
#
# 6項目をそれぞれ1〜5で評価し、その平均をもう一度1〜5に丸めて総合評価にする。
# 順位ではなく絶対的な基準で区切るので、去年と今年の評価を直接見比べられる。
#
# 手元のデータで賄えない部分は次の3つを代わりに使っている（画面の「指標の説明」にも明記）。
#   1. 成長性・収益性は5期ではなく **直近4期**。Yahooの標準化財務諸表が4期しか持っていない。
#   2. 収益性は **経常利益率**。Yahooには経常利益の行が無いので、J-Quantsの決算短信
#      サマリーから期ごとに差し込む（keijo_yosou.py）。取れない期と、経常利益の区分が
#      無いIFRS・米国基準の会社は税引前利益で代える。どちらを使ったかは「収益性の基準」列。
#   3. 割安度は **会社予想PER**（時価総額÷今期予想純利益。短信サマリーから）。
#      予想が無い銘柄だけ実績PER、赤字（予想赤字を含む）はPBRに切り替える。
#
YEARS_FOR_TREND = 4

SHIKIHO_ITEMS = ["成長性", "収益性", "安全性", "規模", "割安度", "値上がり"]

# 各項目の元になる数値と、評価2/3/4/5の下限（昇順）。5を超える上限は無い。
SHIKIHO_BANDS = {
    "成長性": ("売上高CAGR(%)", [0.0, 2.0, 5.0, 10.0]),        # 0%以下は1（増収していない）
    "収益性": ("平均経常利益率(%)", [2.0, 4.0, 7.0, 11.0]),   # 経常利益（無い期は税引前利益）
    "安全性": ("自己資本比率(%)", [20.0, 40.0, 60.0, 80.0]),
    "規模": ("時価総額(億円)", [500.0, 2000.0, 5000.0, 15000.0]),
}

# 割安度は小さいほど良いので、評価5/4/3/2それぞれの上限（昇順）で区切る。
# 80倍以上と、赤字でPERが意味を持たない銘柄は分けて扱う（後者は評価不能）。
SHIKIHO_PER_CUTS = [10.0, 15.0, 30.0, 80.0]

# 赤字などでPERが使えない銘柄は、資産から見た割安さをPBRで測る。
# 利益が出ていない会社の値打ちを何で測るかという問題で、純資産に対する
# 株価というのが昔からの答え（資産バリュー・net-netの考え方）。
# 区切りは解散価値の1.0倍を真ん中に置き、その半値・2倍・4倍を目安にした。
# 赤字銘柄のPBR中央値は1.71倍で黒字銘柄の1.24倍より高く、この区切りだと
# 分布は 1が22%・5が12% と黒字銘柄（1が4%・5が21%）より辛口に出る。
# 利益が無いぶん資産で甘く見てもらえる、という抜け道にはならない。
SHIKIHO_PBR_CUTS = [0.5, 1.0, 2.0, 4.0]

# 金融業の安全性は、業種ごとに別々の物差しで測る。
# 会計上の自己資本比率（純資産÷総資産）は、預金・保険契約準備金・顧客預り金が
# 負債に積み上がる業態では数%にしかならず、80%/60%/40%/20%の基準に当てると
# 全社が最低評価になってしまうため。それぞれの業法が定める健全性指標を使う。
#
#   銀行業   バーゼル規制の資本余裕度(%pt)   規制最低水準を何%pt上回っているか
#   保険業   ソルベンシー・マージン比率(%)   早期是正措置の発動基準は100%（経済価値ベース）
#   証券業   自己資本規制比率(%)             120%未満で業務停止命令、140%未満で届出義務
#   その他金融業  会計上の自己資本比率(%)     リース・クレジット等。事業会社と同じ基準で測る
#
# 銀行は国内基準行（コア資本比率・最低4%）と国際統一基準行（最低7%）で
# 定義が違うので、生の比率ではなく余裕度でそろえる。
# 最低4%を基準に、その半分・1倍・1.5倍・2倍を目安にした。
BANK_SAFETY_CUTS = [2.0, 4.0, 6.0, 8.0]

# 保険は全社が同じ100%基準なので、余裕度に直さず比率そのもので区切る。
#
# 2026年3月31日から経済価値ベースのソルベンシー規制が適用開始された（令和7年金融庁告示
# 第74号・第75号）。従来基準のソルベンシー・マージン比率（平成8年大蔵省告示第50号／
# 平成23年金融庁告示第23号、発動基準200%、水準600〜1,000%）は10社すべてで2026年3月末
# 時点の算出が終了し、同じ「ソルベンシー・マージン比率」という法令上の名称のまま
# 経済価値ベースの数値に置き換わった。発動基準も200%→100%に変わっている。
#
# 新基準の水準は10社で162〜334%（2026年3月末）。発動基準100%の倍数で切ると
# 全社が同じ評価に張り付くので、実際の分布と各社の自社管理目標
# （かんぽ・T&D「適正水準150〜220%」、SOMPO「200%以上」、東京海上「190%以上」、
# MS&AD「180%以上」、アニコム「240%」）に合わせて区切った。
# 新規制の初年度で10社しかないため、分布が動いたら見直す前提の暫定値。
INSURANCE_MIN_SMR = 100.0
INSURANCE_SAFETY_CUTS = [175.0, 195.0, 215.0, 240.0]

# 証券も全社が同じ120%基準。業務停止命令の水準の1.7倍・2.3倍・3.3倍・5倍を目安にした。
# 大手ほど自己勘定のリスク量が大きく比率は低めに出る（野村236%、大和308%）。
# これは指標の性質どおりで、リスクを取っている分だけ低く評価される。
SECURITIES_MIN_RATIO = 120.0
SECURITIES_SAFETY_CUTS = [200.0, 280.0, 400.0, 600.0]

# その他金融業（リース・クレジット・保証・取引所）の安全性は、会計上の自己資本比率では
# 測れない。理由が2つある。
#   1. 日本取引所グループ・日本証券金融は、清算基金や貸借取引の担保金など
#      「他人から預かった資産」が総資産に乗るため、自己資本比率が構造的に極小になる
#      （日本取引所グループ0.48%）。自社のレバレッジとは何の関係もない。
#   2. リース・クレジットはレバレッジが商売そのもので、自己資本比率15%は健全な水準。
#      製造業向けの80/60/40/20%という物差しが最初から合っていない。
# 結果、自己資本比率で採点すると39社中19社が最低評価になり、上位に来るのは
# 赤字の小型株という逆転が起きる。
#
# 代わりに「純有利子負債 ÷ 自己資本」（ネットD/Eレシオ）で測る。預かり資産は借金では
# ないので分子に入らず、実際の借入依存だけを見られる。日本取引所グループは -0.64
# （自己資本の6割を超える手元現金）で最高評価、日本証券金融は14.98で最低評価になる。
# 区分は「実質無借金なら5」を起点に、1倍・3倍・6倍あたりを目安にした。
OTHER_FIN_DE_CUTS = [-0.5, 0.5, 2.0, 5.0]   # 評価5/4/3/2それぞれの上限（小さいほど良い）

# 保険業・証券業に分類されていても、規制上の健全性指標を持たない会社がある。
# 保険業のFPパートナー等は保険代理店、証券業のジャフコ等はPE・資産運用会社で、
# 実態は普通の事業会社。これらは他業種と同じ会計上の自己資本比率で評価する。
# ここに載せた会社だけが「規制指標が要る会社」で、指標が無ければ評価不能にする。
REGULATED_INSURERS = {
    "8766",  # 東京海上ホールディングス
    "8725",  # ＭＳ＆ＡＤインシュアランスグループホールディングス
    "8750",  # 第一ライフグループ
    "8630",  # ＳＯＭＰＯホールディングス
    "8795",  # Ｔ＆Ｄホールディングス
    "7181",  # かんぽ生命保険
    "8729",  # ソニーフィナンシャルグループ
    "7157",  # ライフネット生命保険
    "8715",  # アニコム ホールディングス
    "7326",  # ＳＢＩインシュアランスグループ
}

# 総合評価の区分（6項目の平均をこの基準で1〜5に直す）
SHIKIHO_TOTAL_CUTS = [1.5, 2.5, 3.5, 4.5]

# 総合評価を出すのに必要な有効項目数
SHIKIHO_MIN_ITEMS = 3

# 業種内偏差値を出すのに必要な銘柄数。これ未満の業種は標準偏差が当てにならないので出さない
# （空運業5社・鉱業5社・石油石炭製品9社が該当し、合わせて21銘柄が空欄になる）
MIN_SECTOR_FOR_DEVIATION = 10

# ---------------------------------------------------------------- 派生指標

def safe_div(a: pd.Series, b: pd.Series) -> pd.Series:
    """0除算とinfを黙ってNaNにする割り算"""
    with np.errstate(divide="ignore", invalid="ignore"):
        r = a / b.replace(0, np.nan)
    return r.replace([np.inf, -np.inf], np.nan)


def growth(now: pd.Series, prev: pd.Series) -> pd.Series:
    """前期比成長率(%)。前期が0以下だと率が意味を持たないのでNaN"""
    base = prev.where(prev > 0)
    return safe_div(now - base, base) * 100


def payout_score(payout: pd.Series, dps: pd.Series) -> pd.Series:
    """配当性向の“健全さ”を0-100で表す。
    20〜60%を満点、無配は0点、100%超は持続性に疑問があるので25点。"""
    s = pd.Series(np.nan, index=payout.index, dtype="float64")
    p = payout
    s = s.mask(p.notna() & (p > 100), 25.0)
    s = s.mask(p.notna() & (p > 60) & (p <= 100), 100 - (p - 60) / 40 * 50)
    s = s.mask(p.notna() & (p >= 20) & (p <= 60), 100.0)
    s = s.mask(p.notna() & (p > 0) & (p < 20), 50 + p / 20 * 50)
    s = s.mask(p.notna() & (p <= 0), 0.0)
    # 配当性向が計算できない（EPS<=0）が、配当は出している → 中間評価
    s = s.mask(p.isna() & dps.notna() & (dps > 0), 40.0)
    # 無配がはっきりしている
    s = s.mask(dps.notna() & (dps <= 0), 0.0)
    return s


def add_derived(d: pd.DataFrame, today: date) -> pd.DataFrame:
    d = d.copy()
    # 上場廃止などでJPXの銘柄一覧から消えると業種が空になる。
    # 空のままだと業種別集計やダッシュボードの絞り込みで扱えないのでまとめる。
    d["業種"] = d["業種"].fillna("未分類")
    d["市場"] = d["市場"].fillna("その他")
    equity_pos = d["自己資本"].where(d["自己資本"] > 0)

    # PER は「株価 ÷ EPS（実績）」。元CSVの値をそのまま使う。
    # 参考として時価総額ベースのPERも持ち、桁が合わない銘柄に印を付ける。
    # 株式分割が報告EPSに反映されていない等でごく一部（30銘柄前後）は
    # PER0.5倍のような値になるため、その銘柄のPERだけスコアと
    # スクリーニングから外す（値そのものは表示に残す）。
    # 突き合わせには自己株式を除いた時価総額を使う。表示用の時価総額は
    # Yahoo!やJPXに合わせて自己株式を含むため、そのまま割るとEPSのズレではなく
    # 自己株式の多さを拾ってしまう。
    cap_ex = d["時価総額(自己株式除く)"] if "時価総額(自己株式除く)" in d.columns else d["時価総額"]
    cap_ex = cap_ex.where(cap_ex.notna(), d["時価総額"])
    per_cap = safe_div(cap_ex, d["当期純利益"])
    d["PER(時価総額ベース)"] = per_cap
    ratio = safe_div(d["PER"], per_cap)
    d["EPS乖離"] = (ratio.notna() & ((ratio > 2) | (ratio < 0.5))).fillna(False)
    d["PER(分析用)"] = d["PER"].mask(d["EPS乖離"])

    d["ROE(%)"] = safe_div(d["当期純利益"], equity_pos) * 100
    d["ROA(%)"] = safe_div(d["当期純利益"], d["総資産"]) * 100
    d["純利益率(%)"] = safe_div(d["当期純利益"], d["売上高"]) * 100
    d["営業CFマージン(%)"] = safe_div(d["営業CF"], d["売上高"]) * 100
    d["FCF利回り(%)"] = safe_div(d["フリーCF"], d["時価総額"]) * 100
    d["益回り(%)"] = safe_div(pd.Series(100.0, index=d.index), d["PER"].where(d["PER"] > 0))
    d["配当性向(%)"] = safe_div(d["一株配当"], d["EPS"].where(d["EPS"] > 0)) * 100
    d["配当性向スコア"] = payout_score(d["配当性向(%)"], d["一株配当"])
    d["当期純利益成長率(%)"] = growth(d["当期純利益"], d["当期純利益_前期"])

    # 古い fundamentals_latest.csv には無い列があっても止まらないようにする
    for c in ("有利子負債", "純有利子負債", "現金同等物", "投下資本",
              "EBITDA", "減価償却費", "支払利息"):
        if c not in d.columns:
            d[c] = np.nan

    # --- EV/EBITDA・ROTC・インタレストカバレッジ ---
    # EV（企業価値）＝ 時価総額 ＋ 有利子負債 − 現金同等物。
    # 買収でその会社を丸ごと手に入れるのに実質いくら要るか、という見方。
    # 借金の多い会社はPERより割高に、現金の厚い会社は割安に見える。
    net_debt = d["有利子負債"] - d["現金同等物"]
    net_debt = net_debt.where(net_debt.notna(), d["純有利子負債"])
    # 借入の無い会社は Yahoo 側に有利子負債の行そのものが無い（東京エレクトロンなど）。
    # 欠損＝不明ではなく実質無借金なので、手元の現金をそのままネットキャッシュとみなす。
    net_debt = net_debt.where(net_debt.notna(), -d["現金同等物"])
    d["EV"] = d["時価総額"] + net_debt
    d["EV/EBITDA"] = safe_div(d["EV"], d["EBITDA"].where(d["EBITDA"] > 0))
    d["EV/EBITDA"] = d["EV/EBITDA"].where(d["EV"] > 0)
    # ROTC（投下資本利益率）＝ 営業利益 ÷ 投下資本。
    # ROEは借金を増やすほど高く出るが、こちらは借金も分母に入るので誤魔化しが効かない。
    d["ROTC(%)"] = safe_div(d["営業利益"], d["投下資本"].where(d["投下資本"] > 0)) * 100
    # インタレストカバレッジ＝ 営業利益 ÷ 支払利息。利払いの何倍を稼げているか。
    d["インタレストカバレッジ"] = safe_div(d["営業利益"], d["支払利息"].where(d["支払利息"] > 0))
    # 純有利子負債 ÷ 自己資本（ネットD/Eレシオ）。マイナスは実質無借金。
    # 預かり資産や保険契約準備金が総資産に乗る業態でも、実際の借入依存だけを測れる。
    d["純有利子負債/自己資本"] = safe_div(net_debt, equity_pos).round(2)
    # 負債資本比率（D/Eレシオ）＝ 有利子負債 ÷ 自己資本。買掛金や引当金は含まない。
    # 借入に頼らず稼げているかを見る指標で、スクリーニングの「割安株」「安定優良株」で使う。
    d["負債資本比率"] = safe_div(d["有利子負債"].fillna(0), equity_pos).round(3)
    # 1株当たりフリーCF。配当の原資が実際のキャッシュで賄えているかを見る
    d["1株当たりフリーCF"] = safe_div(d["フリーCF"], d["発行済株式数"]).round(1)
    # EBITDAマージン＝ 償却前営業利益 ÷ 売上高。設備の重さに左右されず本業の稼ぐ力を測る
    d["EBITDAマージン(%)"] = safe_div(d["EBITDA"], d["売上高"].where(d["売上高"] > 0)) * 100

    # --- 設備投資まわり（マルチバガー判定で使う） ---
    # 設備投資額の行は標準化財務諸表に無いので、Yahooのフリーキャッシュフローが
    #   フリーCF ＝ 営業CF − 設備投資
    # の定義であることを使って差し戻している。実データ3,640銘柄すべてで
    # マイナスにならず、売上比の中央値も2.9%と実態に合う。
    capex = (d["営業CF"] - d["フリーCF"]).where(d["営業CF"].notna() & d["フリーCF"].notna())
    d["設備投資額"] = capex.where(capex >= 0)
    d["設備投資/売上(%)"] = safe_div(d["設備投資額"], d["売上高"].where(d["売上高"] > 0)) * 100
    # 設備投資1円あたり何円のフリーCFが残るか。高いほど投資効率が良い。
    d["FCF/設備投資"] = safe_div(d["フリーCF"], d["設備投資額"].where(d["設備投資額"] > 0)).round(2)
    # P/FCF＝時価総額 ÷ フリーCF。FCF利回りの逆数（20倍＝利回り5%）。
    d["P/FCF"] = safe_div(d["時価総額"], d["フリーCF"].where(d["フリーCF"] > 0)).round(1)
    d["ネットキャッシュ(億円)"] = -net_debt / 1e8
    d["EV(億円)"] = d["EV"] / 1e8

    d["時価総額(億円)"] = d["時価総額"] / 1e8
    # 業種別の加重平均PBRを出すのに使う。親会社株主持分（非支配株主持分は含まない）
    d["自己資本(億円)"] = d["自己資本"] / 1e8
    d["売上高(億円)"] = d["売上高"] / 1e8
    d["営業利益(億円)"] = d["営業利益"] / 1e8
    d["当期純利益(億円)"] = d["当期純利益"] / 1e8
    d["営業CF(億円)"] = d["営業CF"] / 1e8
    d["フリーCF(億円)"] = d["フリーCF"] / 1e8

    fy = pd.to_datetime(d["決算期"], errors="coerce")
    d["決算経過日数"] = (pd.Timestamp(today) - fy).dt.days
    d["決算が古い"] = d["決算経過日数"] > STALE_DAYS
    d["金融"] = d["業種"].isin(FINANCIAL_SECTORS)
    d["赤字"] = d["当期純利益"] <= 0
    d["債務超過"] = d["自己資本"] <= 0

    # 資産売却益などの一時要因で利益が膨らむと、PERが1倍を切ったりROEが100%を超えたりする。
    # 見かけ上いちばん割安な銘柄がこれになりがちなので、消さずに印を付けて残す。
    d["一時要因の疑い"] = (
        (d["PER(分析用)"].between(0, 2, inclusive="neither"))
        | (d["ROE(%)"] > 60)
        | (d["当期純利益成長率(%)"] > 300)
    ).fillna(False)
    return d


def attach_bank_capital(d: pd.DataFrame, path: Path) -> pd.DataFrame:
    """銀行のバーゼル自己資本比率を読み込んで結合する。
    ファイルが無ければ列だけ作って空にする（銀行の財務健全性は評価されなくなる）。"""
    d = d.copy()
    new = ["バーゼル自己資本比率(%)", "規制最低水準(%)", "資本余裕度(%pt)", "不良債権比率(%)"]
    for c in new:
        d[c] = np.nan
    d["適用基準"] = pd.NA
    d["バーゼル基準日"] = pd.NA
    d["バーゼル出所"] = pd.NA

    n_bank = int(d["業種"].eq("銀行業").sum())
    if not path.exists():
        if n_bank:
            print(f"※ {path.name} が無いため、銀行{n_bank}行の財務健全性は評価しません。\n"
                  f"  fetch_bank_capital.py で作成してください。", file=sys.stderr)
        return d

    b = pd.read_csv(path, encoding="utf-8-sig", dtype={"コード": str})
    b["コード"] = b["コード"].str.strip()
    b = b.drop_duplicates("コード", keep="last").set_index("コード")

    idx = d["コード"].astype(str)
    for src, dst in [("自己資本比率(%)", "バーゼル自己資本比率(%)"),
                     ("不良債権比率(%)", "不良債権比率(%)"),
                     ("適用基準", "適用基準"),
                     ("基準日", "バーゼル基準日"),
                     ("出所", "バーゼル出所")]:
        if src in b.columns:
            d[dst] = idx.map(b[src])

    d["規制最低水準(%)"] = d["適用基準"].map(MIN_CAPITAL)
    d["資本余裕度(%pt)"] = d["バーゼル自己資本比率(%)"] - d["規制最低水準(%)"]

    got = int(d["資本余裕度(%pt)"].notna().sum())
    print(f"バーゼル自己資本比率: {got}/{n_bank}行")
    if got < n_bank:
        miss = d[d["業種"].eq("銀行業") & d["資本余裕度(%pt)"].isna()]
        names = "、".join(miss["銘柄名"].head(8))
        print(f"  未取得 {n_bank - got}行（{names}{'…' if n_bank - got > 8 else ''}）"
              f"→ 財務健全性は評価しません", file=sys.stderr)
    return d


def attach_beta(d: pd.DataFrame, path: Path) -> pd.DataFrame:
    """compute_beta.py が出したベータ・ボラティリティを結合する"""
    d = d.copy()
    cols = ("ベータ", "ベータ(1年)", "年率ボラティリティ(%)", "250日騰落率(%)",
            "125日騰落率(%)", "52週高値", "52週安値", "52週レンジ位置(%)")
    for c in cols:
        d[c] = np.nan
    if not path.exists():
        print(f"※ {path.name} が無いためベータと騰落率は空欄になります。"
              "compute_beta.py で作成できます。", file=sys.stderr)
        return d
    b = pd.read_csv(path, encoding="utf-8-sig", dtype={"コード": str}).set_index("コード")
    idx = d["コード"].astype(str)
    for c in cols:
        if c in b.columns:
            d[c] = idx.map(b[c])
    print(f"ベータ: {int(d['ベータ'].notna().sum()):,}/{len(d):,}銘柄／"
          f"250日騰落率: {int(d['250日騰落率(%)'].notna().sum()):,}銘柄／"
          f"52週レンジ位置: {int(d['52週レンジ位置(%)'].notna().sum()):,}銘柄")
    return d


def attach_new_high(d: pd.DataFrame, path: Path) -> pd.DataFrame:
    """compute_new_high.py が出した新高値の状況を結合する。

      新高値からの日数      最後に52週新高値（前日までの250営業日の最高値以上の高値）を付けてからの営業日数。
                            0＝最新の営業日に更新。250は「1年間一度も更新していない」
      新高値回数(20日)      直近20営業日で52週新高値を付けた日数。多いほど上昇に勢いがある
      52週高値乖離(%)       終値が52週高値から何%下にあるか（0に近いほど高値圏）
      上場来高値からの日数  上場来高値を最後に更新してからの営業日数（株価データは2016年8月以降）
      上場来高値乖離(%)     終値が上場来高値から何%下にあるか
      出来高倍率(5日/50日)  直近5日の平均出来高 ÷ 直近50日の平均。1.5倍以上なら商いを伴った動き"""
    d = d.copy()
    cols = ("新高値からの日数", "新高値回数(20日)", "52週高値乖離(%)",
            "上場来高値からの日数", "上場来高値乖離(%)", "出来高倍率(5日/50日)",
            "5日線乖離(%)", "25日線乖離(%)", "75日線乖離(%)", "200日線乖離(%)",
            "移動平均線の上の本数", "ボックス幅(%)", "ボックス上抜け(%)", "横ばい上放れ")
    for c in cols:
        d[c] = np.nan
    if not path.exists():
        print(f"※ {path.name} が無いため新高値の判定は空欄になります。"
              "compute_new_high.py で作成できます。", file=sys.stderr)
        return d
    b = pd.read_csv(path, encoding="utf-8-sig", dtype={"コード": str}).set_index("コード")
    idx = d["コード"].astype(str)
    for c in cols:
        if c in b.columns:
            d[c] = idx.map(b[c]).astype("float64")
    print(f"新高値: 5営業日以内に52週新高値 {int((d['新高値からの日数'] <= 4).sum()):,}銘柄／"
          f"上場来高値 {int((d['上場来高値からの日数'] <= 4).sum()):,}銘柄")
    return d


def attach_nikkei225(d: pd.DataFrame, path: Path) -> pd.DataFrame:
    """日経225/run_nikkei225.py が出した日経平均の情報を結合する。

      日経225採用          1＝日経平均の構成銘柄
      日経225ウエート(%)   日経平均に占めるウエート（株価×株価換算係数の比率）
      日経225流動性順位    日経の選定基準（過去5年の売買代金と売買代金当たりの価格変動率）を再現した順位。
                           450位以内＝高流動性銘柄群、未採用で75位以内は次回の採用がほぼ確実
      日経225入替予想      次回の定期見直しの予想（採用予想／除外予想と確度、採用候補・除外候補）
      日経225入替スコア    採用予想 高90・中70・低50、候補30、除外は負の値"""
    d = d.copy()
    cols = ("日経225採用", "日経225ウエート(%)", "日経225流動性順位", "日経225セクター",
            "日経225入替予想", "日経225入替スコア")
    for c in cols:
        d[c] = np.nan
    if not path.exists():
        print(f"※ {path.name} が無いため日経225の列は空欄になります。"
              "日経225/run_nikkei225.py で作成できます。", file=sys.stderr)
        return d
    b = pd.read_csv(path, encoding="utf-8-sig", dtype={"コード": str}).set_index("コード")
    idx = d["コード"].astype(str)
    for c in cols:
        if c in b.columns:
            d[c] = idx.map(b[c])
    d["日経225採用"] = d["日経225採用"].fillna(0).astype(int)
    d["日経225入替スコア"] = d["日経225入替スコア"].fillna(0)
    d["日経225入替予想"] = d["日経225入替予想"].fillna("")
    print(f"日経225: 採用 {int(d['日経225採用'].sum())}銘柄／採用候補・予想 "
          f"{int((d['日経225入替スコア'] >= 30).sum())}銘柄")
    return d


def attach_jukyu(d: pd.DataFrame, path: Path) -> pd.DataFrame:
    """需給分析/analyze_jukyu.py が出した銘柄ごとの需給指標（信用残・信用倍率・日証金・大口空売り・
    価格帯別出来高・需給スコア）を結合する。無ければ空欄のまま続ける。"""
    d = d.copy()
    for c in JUKYU_COLS:
        d[c] = np.nan
    if not path.exists():
        print(f"※ {path.name} が無いため需給の列は空欄になります。需給分析/run_jukyu.sh で作成できます。",
              file=sys.stderr)
        return d
    b = pd.read_csv(path, encoding="utf-8-sig", dtype={"コード": str}).drop_duplicates("コード").set_index("コード")
    idx = d["コード"].astype(str)
    for c in JUKYU_COLS:
        if c in b.columns:
            d[c] = idx.map(b[c])
    for c in ("信用区分", "規制等", "信用残の申込日", "需給判定", "需給メモ"):
        d[c] = d[c].fillna("").astype(str)
    n = int(d["信用買残(株)"].notna().sum())
    asof = b["信用残の申込日"].dropna().max() if "信用残の申込日" in b.columns else "?"
    print(f"需給: 信用残あり {n:,}銘柄（{asof} 申込分）／踏み上げ候補 {int((d['需給判定'] == '踏み上げ候補').sum())}・"
          f"好需給 {int((d['需給判定'] == '好需給').sum())}")
    return d


def add_op_growth_3y(d: pd.DataFrame, path: Path) -> pd.DataFrame:
    """今期を含む3期の営業増益率と、直近2期の営業CFを年次決算から作る。

      営業増益率3期平均(%)  今期（会社予想）・前期・前々期の3つの営業増益率の単純平均。
                            今期予想が無い銘柄は、実績の直近3期（前期・前々期・3期前）で代える。
                            比べる前の期の営業利益が赤字・ゼロだと増益率が出せないので、その銘柄は空欄
      営業増益率3期最低(%)  同じ3つのうち最も低い増益率。平均が1期の急増で押し上げられていないかの確認用
      営業増益率の基準      「予想込み」か「実績3期」か
      営業CF2期黒字         直近2期の営業CFがともにゼロ以上なら1、どちらかが赤字なら0

    今期予想は forecast_fscore.py が J-Quants の決算短信から拾ったもの（12週間遅れ）。"""
    d = d.copy()
    for c in ("営業増益率3期平均(%)", "営業増益率3期最低(%)", "営業CF2期黒字"):
        d[c] = np.nan
    d["営業増益率の基準"] = ""
    if not path.exists():
        return d
    y = pd.read_csv(path, encoding="utf-8-sig", dtype={"コード": str})
    y["決算期"] = pd.to_datetime(y["決算期"], errors="coerce")
    y = y.dropna(subset=["決算期"]).sort_values(["コード", "決算期"])
    y = y.drop_duplicates(["コード", "決算期"], keep="last")
    y = y.groupby("コード", observed=True).tail(4)
    op = y.groupby("コード", observed=True)["営業利益"].apply(
        lambda s: pd.to_numeric(s, errors="coerce").tolist())
    cf = y.groupby("コード", observed=True)["営業CF"].apply(
        lambda s: pd.to_numeric(s, errors="coerce").tolist())

    fc = {}
    if "今期予想営業利益(億円)" in d.columns:
        fc = dict(zip(d["コード"].astype(str), pd.to_numeric(d["今期予想営業利益(億円)"], errors="coerce") * 1e8))

    def rate(now, prev):
        if prev is None or now is None or not np.isfinite(prev) or not np.isfinite(now) or prev <= 0:
            return np.nan
        return (now / prev - 1) * 100

    avg, low, basis, cf2 = {}, {}, {}, {}
    for code, o in op.items():
        f = fc.get(code, np.nan)
        if np.isfinite(f) and len(o) >= 3:
            r = [rate(f, o[-1]), rate(o[-1], o[-2]), rate(o[-2], o[-3])]
            b = "予想込み"
        elif len(o) >= 4:
            r = [rate(o[-1], o[-2]), rate(o[-2], o[-3]), rate(o[-3], o[-4])]
            b = "実績3期"
        else:
            continue
        if all(np.isfinite(r)):
            avg[code], low[code], basis[code] = np.mean(r), min(r), b
    for code, v in cf.items():
        if len(v) >= 2 and all(np.isfinite(v[-2:])):
            cf2[code] = int(min(v[-2:]) >= 0)

    idx = d["コード"].astype(str)
    d["営業増益率3期平均(%)"] = idx.map(avg).astype("float64").round(2)
    d["営業増益率3期最低(%)"] = idx.map(low).astype("float64").round(2)
    d["営業増益率の基準"] = idx.map(basis).fillna("")
    d["営業CF2期黒字"] = idx.map(cf2).astype("float64")
    print(f"営業増益率3期平均: {int(d['営業増益率3期平均(%)'].notna().sum()):,}銘柄"
          f"（予想込み {int((d['営業増益率の基準'] == '予想込み').sum()):,}）／"
          f"営業CF2期黒字 {int((d['営業CF2期黒字'] == 1).sum()):,}銘柄")
    return d


def attach_technical(d: pd.DataFrame, path: Path) -> pd.DataFrame:
    """compute_technical.py が出したテクニカル指標（RSI・MACD・GC/DC・一目など）を結合する"""
    d = d.copy()
    for c in TECH_COLS:
        d[c] = np.nan
    if not path.exists():
        print(f"※ {path.name} が無いためテクニカル指標は空欄になります。"
              "compute_technical.py で作成できます。", file=sys.stderr)
        return d
    b = pd.read_csv(path, encoding="utf-8-sig", dtype={"コード": str}).set_index("コード")
    idx = d["コード"].astype(str)
    for c in TECH_COLS:
        if c in b.columns:
            d[c] = idx.map(b[c]).astype("float64")
    print(f"テクニカル: RSI {int(d['RSI(14)(%)'].notna().sum()):,}銘柄／"
          f"5日以内のGC(5×25) {int((d['GC(5×25)からの日数'] <= 4).sum()):,}銘柄")
    return d


def attach_sbi_basic(d: pd.DataFrame, sectors_path: Path) -> pd.DataFrame:
    """SBIの基本条件（規模・投資金額・決算月）とPCFRを足す

      規模              JPXの規模区分（TOPIX Core30 / Large70 / Mid400 / Small 1 / Small 2）。
                        fetch_sectors.py が sectors.csv の size 列に入れる。無い銘柄は「その他」
      最低投資金額(万円) 株価×100株（単元株数はどの銘柄も100株）
      決算月            決算期の月（1〜12）
      PCFR              時価総額÷営業CF（営業CFが黒字のときだけ）"""
    d = d.copy()
    d["最低投資金額(万円)"] = pd.to_numeric(d["株価"], errors="coerce") * 100 / 1e4
    d["決算月"] = pd.to_datetime(d["決算期"], errors="coerce").dt.month.astype("float64")
    cfo = pd.to_numeric(d.get("営業CF"), errors="coerce")
    d["PCFR"] = np.where(cfo > 0, pd.to_numeric(d["時価総額"], errors="coerce") / cfo, np.nan)
    d["規模"] = "その他"
    if sectors_path.exists():
        t = pd.read_csv(sectors_path, dtype=str).fillna("")
        if "size" in t.columns:
            m = t.drop_duplicates("code").set_index("code")["size"].str.replace("TOPIX ", "", regex=False)
            d["規模"] = d["コード"].astype(str).map(m).replace("", np.nan).fillna("その他")
    print("規模: " + "・".join(f"{k} {v:,}" for k, v in d["規模"].value_counts().items()))
    return d


def attach_regulated_ratio(d: pd.DataFrame, path: Path, value_col: str,
                           dst: str, label: str) -> pd.DataFrame:
    """証券・保険の規制上の健全性指標を結合する。
    ファイルが無ければ列だけ作って空にする（その業種の安全性は評価されなくなる）。"""
    d = d.copy()
    for c in (dst, f"{dst}_基準日", f"{dst}_出所"):
        if c not in d.columns:
            d[c] = pd.NA

    if not path.exists():
        print(f"※ {path.name} が無いため、{label}の安全性は評価しません。", file=sys.stderr)
        return d

    t = pd.read_csv(path, encoding="utf-8-sig", dtype={"コード": str})
    t["コード"] = t["コード"].astype(str).str.strip()
    t = t.dropna(subset=[value_col]).drop_duplicates("コード", keep="last").set_index("コード")

    idx = d["コード"].astype(str)
    d[dst] = pd.to_numeric(idx.map(t[value_col]), errors="coerce")
    for src, suffix in (("基準日", "_基準日"), ("出所", "_出所")):
        if src in t.columns:
            d[f"{dst}{suffix}"] = idx.map(t[src])

    got = int(d[dst].notna().sum())
    asof = t["基準日"].dropna().unique() if "基準日" in t.columns else []
    when = f"／基準日 {'、'.join(map(str, asof))}" if len(asof) else ""
    print(f"{label}: {got}社{when}")
    return d


def attach_profile(d: pd.DataFrame, path: Path) -> pd.DataFrame:
    """公式サイトのURLと、一行の事業概要を結合する。

    数字だけ並んでいても社名から何をしている会社か分からない銘柄が多いので、
    銘柄詳細の先頭に「何の会社か」と公式サイトへのリンクを出すためのものです。
    fetch_company_profile.py が作ります。無くても分析は成立するので、
    ファイルが無ければ列を空にして先に進みます。"""
    d = d.copy()
    for c in ("事業概要", "会社URL"):
        if c not in d.columns:
            d[c] = ""

    if not path.exists():
        print(f"※ {path.name} が無いため、事業概要と会社URLは空欄になります。"
              "fetch_company_profile.py で作成できます。", file=sys.stderr)
        return d

    t = pd.read_csv(path, encoding="utf-8-sig", dtype={"コード": str}).fillna("")
    t["コード"] = t["コード"].astype(str).str.strip()
    t = t.drop_duplicates("コード", keep="last").set_index("コード")

    idx = d["コード"].astype(str)
    for c in ("事業概要", "会社URL"):
        if c in t.columns:
            d[c] = idx.map(t[c]).fillna("")
    # httpで始まらないURLは表示すると壊れるので落とす
    d["会社URL"] = d["会社URL"].where(d["会社URL"].str.startswith("http"), "")

    print(f"会社情報: 事業概要 {int((d['事業概要'] != '').sum()):,}銘柄／"
          f"会社URL {int((d['会社URL'] != '').sum()):,}銘柄")
    return d


def attach_yearly(d: pd.DataFrame, path: Path, periods: int = YEARS_FOR_TREND) -> pd.DataFrame:
    """年次決算の推移から、四季報式の成長性の元になる数値と、税引前利益率を作る。
    （収益性の評価に使う経常利益率は keijo_yosou.attach_keijo_yosou で別に作る）

      売上高CAGR(%)       直近{periods}期の売上高の年平均成長率
      平均税引前利益率(%)  同じ期間の「税引前利益 ÷ 売上高」の平均

    経常利益は手元のデータに無い（IFRSベースの区分のため）ので税引前利益で代える。
    営業外の損益まで含める点は経常利益と同じで、特別損益が入る分だけ振れやすい。"""
    d = d.copy()
    d["売上高CAGR(%)"] = np.nan
    d["平均税引前利益率(%)"] = np.nan
    d["CAGR期数"] = np.nan
    d["換金性資産(億円)"] = np.nan
    d["ネットキャッシュ倍率"] = np.nan

    if not path.exists():
        print(f"※ {path.name} が無いため、成長性と収益性は評価しません。", file=sys.stderr)
        return d

    y = pd.read_csv(path, encoding="utf-8-sig", dtype={"コード": str})
    y["決算期"] = pd.to_datetime(y["決算期"], errors="coerce")
    y = y.dropna(subset=["決算期"]).sort_values(["コード", "決算期"])
    # 同じ期が2行あるデータ（決算期変更など）は後の行を残す
    y = y.drop_duplicates(["コード", "決算期"], keep="last")
    y = y.groupby("コード", observed=True).tail(periods).copy()

    rev = pd.to_numeric(y["売上高"], errors="coerce")
    pre = pd.to_numeric(y["税引前利益"], errors="coerce")
    y["_margin"] = safe_div(pre, rev.where(rev > 0)) * 100
    y["_i"] = y.groupby("コード", observed=True).cumcount()
    y["_n"] = y.groupby("コード", observed=True)["コード"].transform("size")

    first = y[y["_i"] == 0].set_index("コード")
    last = y[y["_i"] == y["_n"] - 1].set_index("コード")

    yrs = (last["決算期"] - first["決算期"]).dt.days / 365.25
    r0 = pd.to_numeric(first["売上高"], errors="coerce")
    r1 = pd.to_numeric(last["売上高"], errors="coerce")
    ratio = safe_div(r1, r0.where(r0 > 0))
    # 1年に満たない（＝実質1期しか無い）銘柄は年率に直せないので出さない
    cagr = (ratio.where(ratio > 0) ** (1 / yrs.where(yrs >= 0.9)) - 1) * 100

    margin = y.groupby("コード", observed=True)["_margin"].mean()
    n_per = last["_n"]

    idx = d["コード"].astype(str)
    d["売上高CAGR(%)"] = idx.map(cagr).astype("float64").round(2)
    d["平均税引前利益率(%)"] = idx.map(margin).astype("float64").round(2)
    d["CAGR期数"] = idx.map(n_per).astype("float64")

    # --- ネットキャッシュ倍率 -------------------------------------------------
    # 「その会社を時価総額で丸ごと買ったら、手元に残る換金しやすい資産だけで
    #   何倍の値がつくか」を見る指標。値が小さいほど資産に対して株価が安い。
    #     換金性資産 ＝ 流動資産 − 負債合計
    #     ネットキャッシュ倍率 ＝ 時価総額 ÷ 換金性資産
    # 現金だけを見る「ネットキャッシュ(億円)」より広く、売掛金や棚卸資産まで
    # 含めたうえで負債を全額引きます。投資有価証券は手元のデータに項目が無いので
    # 足していません（その分だけ辛めに出ます）。
    # 換金性資産がマイナス＝負債が流動資産を上回る会社は、倍率を出さず対象外にします。
    cur_a = pd.to_numeric(last["流動資産"], errors="coerce") if "流動資産" in last.columns else None
    if cur_a is not None:
        liab = pd.to_numeric(d["総資産"], errors="coerce") - pd.to_numeric(d["自己資本"], errors="coerce")
        d["換金性資産(億円)"] = ((idx.map(cur_a).astype("float64") - liab) / 1e8).round(1)
        d["ネットキャッシュ倍率"] = safe_div(
            d["時価総額(億円)"], d["換金性資産(億円)"].where(d["換金性資産(億円)"] > 0)).round(2)

    print(f"年次推移: 売上高CAGR {int(d['売上高CAGR(%)'].notna().sum()):,}銘柄／"
          f"平均税引前利益率 {int(d['平均税引前利益率(%)'].notna().sum()):,}銘柄"
          f"（最大{periods}期）")
    return d


def attach_dividend_quality(d: pd.DataFrame, path: Path, periods: int = YEARS_FOR_TREND) -> pd.DataFrame:
    """配当の質と、利益の伸びを年次決算から作る。スクリーニング用の追加指標。

      DOE(%)            直近期の 配当総額 ÷ 期首・期末の平均自己資本（会社が開示するDOEと同じ定義）
      平均DOE(%)        直近3期のDOEの平均。DOEを配当方針にしている会社は毎年ほぼ一定になる
      DOE変化(%pt)      直近期のDOE − 前期のDOE
      減配回数          手元の期間（最大{periods}期）で1株配当が前期より減った回数
      連続増配期数      直近期から遡って1株配当が前期より増え続けた期数（手元の期間内）
      配当CAGR(%)       1株配当の年平均成長率
      EPS_CAGR(%)       EPSの年平均成長率（始点と終点がともに黒字のときだけ）
      営業利益CAGR(%)   営業利益の年平均成長率（同上）
      平均ROE(%)        期間中のROE（純利益 ÷ 平均自己資本）の平均。一時的な好不調をならした稼ぐ力

    1株配当とEPSは株式分割の調整済みだが、過去の期の発行済株式数は分割前のままなので、
    配当総額は「1株配当 × (当期純利益 ÷ EPS)」＝分割調整後の期中平均株式数で出す。
    EPSが使えない期（ゼロ・符号違い）は期末の発行済株式数（自己株式除く）で代える。
    期首の自己資本が無い最初の期は期末の自己資本で割る。"""
    d = d.copy()
    cols = ["DOE(%)", "平均DOE(%)", "DOE変化(%pt)", "減配回数", "連続増配期数",
            "配当CAGR(%)", "EPS_CAGR(%)", "営業利益CAGR(%)", "平均ROE(%)"]
    for c in cols:
        d[c] = np.nan
    if not path.exists():
        print(f"※ {path.name} が無いため、DOEと配当の推移は計算しません。", file=sys.stderr)
        return d

    y = pd.read_csv(path, encoding="utf-8-sig", dtype={"コード": str})
    y["決算期"] = pd.to_datetime(y["決算期"], errors="coerce")
    y = y.dropna(subset=["決算期"]).sort_values(["コード", "決算期"])
    y = y.drop_duplicates(["コード", "決算期"], keep="last")
    y = y.groupby("コード", observed=True).tail(periods).copy()
    num = lambda c: pd.to_numeric(y[c], errors="coerce")
    dps, eps, ni = num("一株配当"), num("EPS"), num("当期純利益")
    eq, op = num("自己資本"), num("営業利益")
    g = lambda s: s.groupby(y["コード"], observed=True)

    shares = safe_div(ni, eps.where(eps != 0))
    shares = shares.where(shares > 0, num("発行済株式数"))
    eq_pos = eq.where(eq > 0)
    eq_prev = g(eq_pos).shift()
    avg_eq = ((eq_pos + eq_prev) / 2).where(eq_prev.notna(), eq_pos)
    y["_doe"] = safe_div(dps * shares, avg_eq) * 100
    # 自己資本が極端に小さい期や株数の取り違えで数百%以上になる値はデータの誤りとみて外す
    y["_doe"] = y["_doe"].where(y["_doe"] <= 100)
    y["_roe"] = safe_div(ni, avg_eq) * 100
    dps_prev = g(dps).shift()
    y["_cut"] = (dps < dps_prev * 0.995).where(dps.notna() & dps_prev.notna())
    y["_up"] = (dps > dps_prev * 1.005).where(dps.notna() & dps_prev.notna())

    y["_i"] = g(y["コード"]).cumcount()
    y["_n"] = g(y["コード"]).transform("size")
    first = y[y["_i"] == 0].set_index("コード")
    last = y[y["_i"] == y["_n"] - 1].set_index("コード")
    yrs = ((last["決算期"] - first["決算期"]).dt.days / 365.25)
    yrs = yrs.where(yrs >= 0.9)

    def cagr(col, need_pos=True):
        a = pd.to_numeric(first[col], errors="coerce")
        b = pd.to_numeric(last[col], errors="coerce")
        ok = (a > 0) & (b > 0) if need_pos else (a > 0) & (b >= 0)
        r = safe_div(b, a.where(ok))
        return ((r.where(r > 0) ** (1 / yrs) - 1) * 100).where(ok)

    doe_last = last["_doe"]
    doe_prev = g(y["_doe"]).shift().loc[y["_i"] == y["_n"] - 1]
    doe_prev.index = last.index
    doe_avg3 = y[y["_i"] >= y["_n"] - 3].groupby("コード", observed=True)["_doe"].mean()
    cuts = y.groupby("コード", observed=True)["_cut"].sum(min_count=1)

    def streak(s):
        n = 0
        for v in reversed(s.tolist()):
            if v is True or v == 1:
                n += 1
            else:
                break
        return n
    ups = y.groupby("コード", observed=True)["_up"].apply(streak)
    has_div = y.groupby("コード", observed=True)["一株配当"].apply(lambda s: s.notna().sum() >= 2)
    roe_avg = y.groupby("コード", observed=True)["_roe"].mean()

    idx = d["コード"].astype(str)
    m = lambda s: idx.map(s).astype("float64")
    d["DOE(%)"] = m(doe_last).round(2)
    d["平均DOE(%)"] = m(doe_avg3).round(2)
    d["DOE変化(%pt)"] = (m(doe_last) - m(doe_prev)).round(2)
    d["減配回数"] = m(cuts)
    d["連続増配期数"] = m(ups.where(has_div))
    d["配当CAGR(%)"] = m(cagr("一株配当", need_pos=True)).round(2)
    d["EPS_CAGR(%)"] = m(cagr("EPS")).round(2)
    d["営業利益CAGR(%)"] = m(cagr("営業利益")).round(2)
    d["平均ROE(%)"] = m(roe_avg).round(2)

    # --- 最新データから作る補助指標 ---
    # PEG＝PER ÷ EPS成長率(年率)。1倍以下なら成長に対して割安とされる（ピーター・リンチ）
    d["PEG"] = safe_div(d["PER(分析用)"].where(d["PER(分析用)"] > 0),
                        d["EPS_CAGR(%)"].where(d["EPS_CAGR(%)"] > 0)).round(2)
    # ネットキャッシュ比率＝ネットキャッシュ ÷ 時価総額。100%超なら時価総額以上の現金を持つ（清原式の簡易版）
    d["ネットキャッシュ比率(%)"] = safe_div(d["ネットキャッシュ(億円)"],
                                    d["時価総額(億円)"].where(d["時価総額(億円)"] > 0)) * 100
    d["ネットキャッシュ比率(%)"] = d["ネットキャッシュ比率(%)"].round(1)
    # 純有利子負債 ÷ EBITDA。何年分の稼ぎで借金を返せるか。マイナスは実質無借金、3倍超は重め
    d["純有利子負債/EBITDA"] = safe_div(-d["ネットキャッシュ(億円)"] * 1e8,
                                   d["EBITDA"].where(d["EBITDA"] > 0)).round(2)
    # FCF配当性向＝配当総額 ÷ フリーCF。100%以下なら配当を実際のキャッシュで賄えている
    div_total = d["一株配当"] * d["発行済株式数"]
    d["FCF配当性向(%)"] = (safe_div(div_total, d["フリーCF"].where(d["フリーCF"] > 0)) * 100
                          ).where(d["一株配当"] > 0).round(1)

    print(f"配当の推移: DOE {int(d['DOE(%)'].notna().sum()):,}銘柄／"
          f"連続増配期数 {int(d['連続増配期数'].notna().sum()):,}銘柄／"
          f"PEG {int(d['PEG'].notna().sum()):,}銘柄")
    return d


def attach_multibagger_yearly(d: pd.DataFrame, path: Path,
                              periods: int = MB_YEARS) -> pd.DataFrame:
    """年次推移から、マルチバガー判定に使う3つの数値を作る。

      FCF黒字比率(%)     直近{periods}期のうちフリーCFがプラスだった期の割合
      総資産CAGR(%)      同じ期間の総資産の年平均成長率
      EBITDA_CAGR(%)     同じ期間のEBITDAの年平均成長率
      成長ギャップ(%pt)  総資産CAGR − EBITDA_CAGR

    論文の Inv ダミー（資産の伸びがEBITDAの伸びを上回った年は翌年リターンが
    4〜11%pt低い）を、単年ではなく年平均で見ている。単年の資産成長率は
    M&Aや増資で大きく振れるため。手元のデータは最大4期なので3年平均になる。"""
    d = d.copy()
    new_cols = ["FCF黒字比率(%)", "総資産CAGR(%)", "EBITDA_CAGR(%)", "成長ギャップ(%pt)"]
    for c in new_cols:
        d[c] = np.nan
    d["EBITDA赤字"] = False
    d["EBITDA黒字転換"] = False

    if not path.exists():
        print(f"※ {path.name} が無いため、マルチバガー判定の投資効率は評価しません。",
              file=sys.stderr)
        return d

    y = pd.read_csv(path, encoding="utf-8-sig", dtype={"コード": str})
    y["決算期"] = pd.to_datetime(y["決算期"], errors="coerce")
    y = y.dropna(subset=["決算期"]).sort_values(["コード", "決算期"])
    y = y.drop_duplicates(["コード", "決算期"], keep="last")
    y = y.groupby("コード", observed=True).tail(periods).copy()

    y["_i"] = y.groupby("コード", observed=True).cumcount()
    y["_n"] = y.groupby("コード", observed=True)["コード"].transform("size")
    first = y[y["_i"] == 0].set_index("コード")
    last = y[y["_i"] == y["_n"] - 1].set_index("コード")
    yrs = (last["決算期"] - first["決算期"]).dt.days / 365.25
    yrs = yrs.where(yrs >= 0.9)

    def cagr(col):
        a = pd.to_numeric(first[col], errors="coerce")
        b = pd.to_numeric(last[col], errors="coerce")
        ratio = safe_div(b, a.where(a > 0))
        return (ratio.where(ratio > 0) ** (1 / yrs) - 1) * 100

    fcf = pd.to_numeric(y["フリーCF"], errors="coerce")
    y["_fcf_plus"] = (fcf > 0).where(fcf.notna())
    share = y.groupby("コード", observed=True)["_fcf_plus"].mean() * 100

    idx = d["コード"].astype(str)
    d["FCF黒字比率(%)"] = idx.map(share).astype("float64").round(1)
    d["総資産CAGR(%)"] = idx.map(cagr("総資産")).astype("float64").round(2)
    d["EBITDA_CAGR(%)"] = idx.map(cagr("EBITDA")).astype("float64").round(2)
    d["成長ギャップ(%pt)"] = (d["総資産CAGR(%)"] - d["EBITDA_CAGR(%)"]).round(2)

    # EBITDAが赤字だと成長率が出せないので、状態だけ持っておく
    e0 = pd.to_numeric(first["EBITDA"], errors="coerce")
    e1 = pd.to_numeric(last["EBITDA"], errors="coerce")
    d["EBITDA赤字"] = idx.map((e1 <= 0)).fillna(False).astype(bool)
    d["EBITDA黒字転換"] = idx.map(((e0 <= 0) & (e1 > 0))).fillna(False).astype(bool)

    print(f"マルチバガー用の年次指標: FCF黒字比率 {int(d['FCF黒字比率(%)'].notna().sum()):,}銘柄／"
          f"成長ギャップ {int(d['成長ギャップ(%pt)'].notna().sum()):,}銘柄（最大{periods}期）")
    return d


def _mb_sector_rule(sector: str) -> tuple:
    """業種から（区分名, FCF利回り下限, 時価総額下限, 時価総額上限）を引く"""
    for name, members, fcf_min, cap_lo, cap_hi in MB_SECTOR_RULES:
        if sector in members:
            return name, fcf_min, cap_lo, cap_hi
    return MB_DEFAULT_RULE


def _band(value, bands, default=0.0):
    """value が bands の (上限, 点数) のどれに入るかで点数を返す。上限はNoneで無限大。"""
    if pd.isna(value):
        return default
    for limit, point in bands:
        if limit is None or value <= limit:
            return point
    return 0.0


def add_multibagger(d: pd.DataFrame, rate_env: str = "中立") -> pd.DataFrame:
    """論文ベースの適合度スコア（最大95点）と基本条件・エントリー判定を付ける。

      評価値(40点)   FCF利回りの絶対水準28点 ＋ FCFの安定性12点
      エントリー(30点) 52週レンジ位置20点 ＋ 6か月騰落率10点
      品質(20点)     資産成長とEBITDA成長の差12点 ＋ 投資効率8点
      金利調整       逆風 −10点 ／ 中立 0点 ／ 追い風 +5点（--rate-env で指定）

    論文が「成長率には予測力が無い」としている一方で、基本条件には増収率5%以上を
    入れている。10倍になるには売上が伸びる必要があるという実務上の判断で、
    スコアには増収率を入れていない（点数としては効かせない）。"""
    d = d.copy()
    sector = d["業種"].fillna("")
    rules = sector.map(lambda x: _mb_sector_rule(x))
    d["適合業種区分"] = rules.map(lambda r: r[0])
    d["FCF利回り基準(%)"] = rules.map(lambda r: r[1]).astype("float64")
    cap_lo = rules.map(lambda r: r[2]).astype("float64").clip(lower=MB_CAP_MIN)
    cap_hi = rules.map(lambda r: r[3]).astype("float64").clip(upper=MB_CAP_MAX)
    d["適合時価総額レンジ"] = [f"{int(a)}〜{int(b)}億円" for a, b in zip(cap_lo, cap_hi)]

    # --- 1. 評価値スコア（40点） ---
    pfcf = d["P/FCF"]
    v_abs = pfcf.map(lambda v: _band(v, [(10, 28.0), (20, 22.0), (33, 12.0), (None, 4.0)]))
    v_abs = v_abs.where(d["フリーCF"] > 0, 0.0)
    v_stable = (d["FCF黒字比率(%)"].fillna(0) / 100 * 12).round(1)
    d["評価値スコア"] = (v_abs + v_stable).round(1)

    # --- 2. エントリースコア（30点） ---
    e_range = d["52週レンジ位置(%)"].map(
        lambda v: _band(v, [(30, 20.0), (50, 15.0), (70, 8.0), (None, 0.0)], default=8.0))
    def chg_point(v):
        if pd.isna(v):
            return 5.0
        if v < -30:
            return 5.0      # 下げすぎは反発待ちではなく「落ちるナイフ」の可能性
        if v <= -5:
            return 10.0
        if v <= 5:
            return 7.0
        if v <= 15:
            return 3.0
        return 0.0
    e_chg = d["125日騰落率(%)"].map(chg_point)
    d["エントリースコア"] = (e_range + e_chg).round(1)

    # --- 3. 品質スコア（20点） ---
    def gap_point(row):
        if row["EBITDA赤字"]:
            return 0.0
        if row["EBITDA黒字転換"]:
            return 12.0
        g = row["成長ギャップ(%pt)"]
        if pd.isna(g):
            return 6.0
        if g <= 0:
            return 12.0
        if g <= 5:
            return 6.0
        return 0.0
    q_gap = d.apply(gap_point, axis=1)

    def eff_point(row):
        r = row["FCF/設備投資"]
        c = row["設備投資/売上(%)"]
        pts = []
        if pd.notna(r):
            pts.append(_band(-r, [(-2, 8.0), (-1, 6.0), (-0.5, 4.0), (None, 2.0)]))
        if pd.notna(c):
            pts.append(_band(c, [(2, 8.0), (5, 6.0), (10, 4.0), (None, 2.0)]))
        return max(pts) if pts else 4.0
    q_eff = d.apply(eff_point, axis=1)
    d["品質スコア"] = (q_gap + q_eff).round(1)

    # --- 4. 金利調整 ---
    adj = MB_RATE_ENV.get(rate_env, 0.0)
    d["金利環境"] = rate_env
    d["マルチバガースコア"] = (d["評価値スコア"] + d["エントリースコア"]
                              + d["品質スコア"] + adj).round(1)

    # --- 基本条件（ファンダ） ---
    fin = d["業種"].isin(FINANCIAL_SECTORS) | d.get("金融", pd.Series(False, index=d.index)).fillna(False)
    base = (
        (~fin)
        & (~d["決算が古い"].fillna(False))
        & d["時価総額(億円)"].between(cap_lo, cap_hi)
        & (d["ROE(%)"] >= MB_ROE_MIN)
        & (d["営業利益率(%)"] >= MB_OPM_MIN)
        & (d["フリーCF"] > 0)
        & (d["FCF利回り(%)"] >= d["FCF利回り基準(%)"])
        & (d["売上高成長率(%)"] >= MB_REV_GROWTH_MIN)
        & (d["売上高CAGR(%)"] >= MB_REV_GROWTH_MIN)
    )
    d["マルチバガー基本条件"] = base.fillna(False)

    # --- エントリー判定（タイミング） ---
    entry = (
        d["マルチバガー基本条件"]
        & (d["マルチバガースコア"] >= MB_SCORE_PASS)
        & (d["52週レンジ位置(%)"] <= MB_RANGE_MAX)
        & (d["125日騰落率(%)"] <= MB_CHG6M_MAX)
        & (d["フリーCF"] > 0)
    ).fillna(False)
    d["エントリー判定"] = np.where(entry, "OK", "待ち")
    d.loc[~d["マルチバガー基本条件"], "エントリー判定"] = "対象外"

    n_base = int(d["マルチバガー基本条件"].sum())
    n_ok = int((d["エントリー判定"] == "OK").sum())
    print(f"マルチバガー判定: 基本条件 {n_base:,}銘柄／うちエントリーOK {n_ok:,}銘柄"
          f"（金利環境: {rate_env} {adj:+.0f}点）")
    return d


def add_multibagger_paper(d: pd.DataFrame, by_year_path: Path) -> pd.DataFrame:
    """論文準拠のマルチバガー判定（Yartseva 2025 が有意とした変数だけを使う）。

      必須条件  非金融・決算が新しい／時価総額20〜3,000億円／PBR 0超〜2.5（B/M≧0.40）／
               営業黒字／FCF利回り>0／Invダミー=0（直近期の総資産成長率≦EBITDA成長率）／
               FCF黒字の期が半分以上（論文外のノイズ対策）
      論文スコア 候補内パーセンタイル×重み（FCF利回り30・B/M25・小型15・52週安値圏15・
               6か月下落10・ROA5）の100点満点。条件外の銘柄は空欄
      論文エントリー 52週レンジ位置≦30% かつ 6か月騰落率≦0% なら「安値圏」

    Invダミーは論文と同じく単年（直近期の前期比）で見る。前期EBITDAが赤字→今期黒字は
    「EBITDAが追いついた」とみなして0にする。"""
    d = d.copy()
    for c in ("総資産成長率(%)", "EBITDA成長率(%)", "Invダミー", "B/M", "論文スコア"):
        d[c] = np.nan
    d["論文条件"] = False
    d["論文エントリー"] = ""
    d["論文注意"] = ""

    if by_year_path.exists():
        y = pd.read_csv(by_year_path, encoding="utf-8-sig", dtype={"コード": str})
        y["決算期"] = pd.to_datetime(y["決算期"], errors="coerce")
        y = (y.dropna(subset=["決算期"]).sort_values(["コード", "決算期"])
             .drop_duplicates(["コード", "決算期"], keep="last"))
        g = y.groupby("コード", observed=True)
        last = g.nth(-1).set_index("コード")
        prev = g.nth(-2).set_index("コード").reindex(last.index)

        def yoy(col):
            a = pd.to_numeric(prev[col], errors="coerce")
            b = pd.to_numeric(last[col], errors="coerce")
            return (b / a.where(a > 0) - 1) * 100

        ag, eg = yoy("総資産"), yoy("EBITDA")
        e0 = pd.to_numeric(prev["EBITDA"], errors="coerce")
        e1 = pd.to_numeric(last["EBITDA"], errors="coerce")
        inv = (ag > eg).astype("float64").where(ag.notna() & eg.notna())
        inv = inv.mask((e0 <= 0) & (e1 > 0), 0.0)
        idx = d["コード"].astype(str)
        d["総資産成長率(%)"] = idx.map(ag).astype("float64").round(2)
        d["EBITDA成長率(%)"] = idx.map(eg).astype("float64").round(2)
        d["Invダミー"] = idx.map(inv).astype("float64")
    else:
        print(f"※ {by_year_path.name} が無いため、論文準拠のマルチバガー判定を行いません。",
              file=sys.stderr)
        return d

    d["B/M"] = (1 / d["PBR"].where(d["PBR"] > 0)).round(3)
    fin = d["業種"].isin(FINANCIAL_SECTORS) | d.get("金融", pd.Series(False, index=d.index)).fillna(False)
    cond = (
        (~fin)
        & (~d["決算が古い"].fillna(False))
        & d["時価総額(億円)"].between(MBP_CAP_MIN, MBP_CAP_MAX)
        & (d["PBR"] > 0) & (d["PBR"] <= MBP_PBR_MAX)
        & (d["営業利益(億円)"] > 0)
        & (d["FCF利回り(%)"] > 0)
        & (d["Invダミー"] == 0)
        & (d["FCF黒字比率(%)"] >= MBP_FCF_STABLE_MIN)
    ).fillna(False)
    d["論文条件"] = cond

    c = d[cond]
    score = pd.Series(0.0, index=c.index)
    for col, w in MBP_WEIGHTS.items():
        p = c[col].rank(pct=True, ascending=col not in MBP_LOWER_IS_BETTER).fillna(0.5)
        score += p * w
    d.loc[cond, "論文スコア"] = score.round(1)

    low = cond & (d["52週レンジ位置(%)"] <= MBP_RANGE_OK) & (d["125日騰落率(%)"] <= MBP_CHG6M_OK)
    d.loc[low.fillna(False), "論文エントリー"] = "安値圏"

    notes = []
    for mask, text in [
        (d["FCF利回り(%)"] > MBP_FCF_SPIKE, "FCF利回り40%超（一時要因か確認）"),
        ((d["総資産成長率(%)"] > 50) | (d["EBITDA成長率(%)"] > 300), "資産かEBITDAが急変（M&A等か確認）"),
        (d["125日騰落率(%)"] < -40, "6か月で−40%超の急落"),
    ]:
        notes.append(np.where(cond & mask.fillna(False), text, ""))
    d["論文注意"] = ["／".join(t for t in ts if t) for ts in zip(*notes)]

    print(f"マルチバガー判定（論文準拠）: 条件 {int(cond.sum()):,}銘柄／"
          f"うち安値圏 {int((d['論文エントリー'] == '安値圏').sum()):,}銘柄")
    return d


def mark_delisted(d: pd.DataFrame, sectors_path: Path) -> pd.DataFrame:
    """上場廃止とみられる銘柄に印を付ける"""
    d = d.copy()
    pdt = pd.to_datetime(d["株価日付"], errors="coerce")
    d["株価遅延日数"] = (pdt.max() - pdt).dt.days
    d["上場廃止"] = False

    if not sectors_path.exists():
        print(f"※ {sectors_path.name} が無いため、上場廃止の判定を行いません。", file=sys.stderr)
        return d

    t = pd.read_csv(sectors_path, dtype=str)
    if "listed" in t.columns:
        t = t[t["listed"].fillna("1").str.strip() != "0"]
    listed = set(t["code"].astype(str).str.strip())
    if not listed:
        return d

    in_jpx = d["コード"].astype(str).isin(listed)
    d["上場廃止"] = (~in_jpx) & (d["株価遅延日数"] >= DELISTED_STALE_DAYS)
    return d


# ------------------------------------------------------------------- Fスコア

# 9項目の列名。TradingView のピオトロスキーFスコアの並び（収益性4・財務3・効率2）に合わせています。
F_COLS = [
    "F1純利益", "F2営業CF", "F3ROA変化", "F4収益の質",
    "F5長期借入金", "F6流動比率", "F7株式発行",
    "F8売上総利益率", "F9資産回転率",
]
# どの項目を代用データで判定したかを残す列
F_SUBST_COL = "F代用"
# 必ず要る数値。直近期・前期で欠けていないこと、隣り合う期で同値でないことを確かめます。
F_SOURCE_COLS = ["総資産", "売上高", "営業CF", "当期純利益", "流動資産", "流動負債"]
F_YEARS = 3                  # 直近期・前期・前々期の3期を使う（平均総資産に前々期末が要る）
COS_BY_YEAR_NAME = "cost_of_sales_by_year.csv"   # EDINET DB の売上総利益（fetch_cost_of_sales.py）


def _num_col(y: pd.DataFrame, name: str) -> pd.Series:
    """列が無ければ全部NaNの列を返す（新しく足した列が古いCSVに無い場合に備える）"""
    if name in y.columns:
        return pd.to_numeric(y[name], errors="coerce")
    return pd.Series(np.nan, index=y.index, dtype="float64")


def _attach_edinet_gross(y: pd.DataFrame, cos_path: Path) -> pd.Series:
    """Yahoo に売上総利益が無い年度を、EDINET DB の売上総利益で埋める。
    EDINET の「年度」は決算期末日の年と一致する（3月期・12月期・2月期とも確認済み）。
    売上高が2%以上食い違う年度は、別の期を拾っている恐れがあるので使わない。"""
    gross = _num_col(y, "売上総利益")
    if not cos_path.exists():
        return gross
    c = pd.read_csv(cos_path, encoding="utf-8-sig", dtype={"コード": str})
    c["売上総利益"] = pd.to_numeric(c["売上総利益"], errors="coerce")
    c["売上高"] = pd.to_numeric(c["売上高"], errors="coerce")
    c = c.dropna(subset=["売上総利益"]).drop_duplicates(["コード", "年度"], keep="last")
    key = y["コード"].astype(str) + "_" + y["決算期"].dt.year.astype(str)
    c_key = c["コード"].astype(str) + "_" + c["年度"].astype(int).astype(str)
    eg = key.map(pd.Series(c["売上総利益"].values, index=c_key.values))
    es = key.map(pd.Series(c["売上高"].values, index=c_key.values))
    rev = _num_col(y, "売上高")
    same_period = (es - rev).abs() <= rev.abs() * 0.02
    return gross.fillna(eg.where(same_period))


def attach_fscore(d: pd.DataFrame, path: Path) -> pd.DataFrame:
    """ピオトロスキーのFスコアを、TradingView の定義に合わせた9項目で付ける。

    A. 収益性
      F1 純利益        直近期の当期純利益がプラス
      F2 営業CF        直近期の営業CFがプラス
      F3 ROA変化       ROA（当期純利益÷平均総資産）が前期を上回る
      F4 収益の質      営業CFが特別損益前の純利益を上回る
    B. レバレッジ・流動性・資金調達
      F5 長期借入金    長期借入金÷平均総資産が前期より低い
      F6 流動比率      流動比率が前期を上回る
      F7 株式発行      直近期に新株発行が無い
    C. 営業効率
      F8 売上総利益率  売上総利益率が前期を上回る
      F9 資産回転率    総資産回転率（売上高÷平均総資産）が前期を上回る

    条件を満たせば1点、満たさなければ0点。合計0〜9点。すべて実績ベースです。
    会社予想を使う版は forecast_fscore.py の「予想Fスコア」（マネックス証券の定義）を見てください。

    手元のデータで定義どおりに判定できない項目は、次の代用で判定し、
    使った代用を「F代用」列に残します（データが揃い次第、自動で本来の定義に切り替わります）。

      F4  特別損益前の純利益（Yahoo NormalizedIncome）が無い → 当期純利益
      F5  長期借入金（Yahoo LongTermDebt）が無い            → 有利子負債
      F7  株式発行による収入（Yahoo IssuanceOfCapitalStock）が無い
                                                       → 発行済株式総数が増えていないこと
      F8  売上総利益（Yahoo・EDINET DB）が2期そろわない       → 営業利益率

    次のいずれかに当てはまる銘柄はスコアを出さず、理由を「Fデータ品質」に残します。

      ・3期分の決算がそろっていない
      ・判定に使う項目が直近期か前期で欠けている（代用でも埋まらない場合を含む）
      ・隣り合う期で値が完全に一致している（データ元での補完が疑われる。0同士は除く）
      ・金融4業種（売上総利益・流動比率の概念が標準化財務諸表に無いため）"""
    d = d.copy()
    for c in F_COLS:
        d[c] = np.nan
    d["Fスコア"] = np.nan
    d["Fデータ品質"] = ""
    d[F_SUBST_COL] = ""

    if not path.exists():
        print(f"※ {path.name} が無いため、Fスコアは評価しません。", file=sys.stderr)
        return d

    y = pd.read_csv(path, encoding="utf-8-sig", dtype={"コード": str})
    y["決算期"] = pd.to_datetime(y["決算期"], errors="coerce")
    y = y.dropna(subset=["決算期"]).sort_values(["コード", "決算期"])
    y = y.drop_duplicates(["コード", "決算期"], keep="last")
    y = y.groupby("コード", observed=True).tail(F_YEARS).copy()

    for c in F_SOURCE_COLS + ["営業利益", "有利子負債"]:
        y[c] = _num_col(y, c)
    y["_長期借入金"] = _num_col(y, "長期借入金")
    y["_特別損益前純利益"] = _num_col(y, "特別損益前純利益")
    y["_株式発行収入"] = _num_col(y, "株式発行収入")
    y["_売上総利益"] = _attach_edinet_gross(y, path.parent / COS_BY_YEAR_NAME)
    shares = _num_col(y, "発行済株式総数")
    if "発行済株式数" in y.columns:
        shares = shares.fillna(pd.to_numeric(y["発行済株式数"], errors="coerce"))
    y["_株式数"] = shares

    full = y.groupby("コード", observed=True)["コード"].transform("size") == F_YEARS
    short_codes = sorted(set(y.loc[~full, "コード"]))
    y = y[full].copy()
    y["_i"] = y.groupby("コード", observed=True).cumcount()   # 0=前々期 1=前期 2=直近期
    t2 = y[y["_i"] == 0].set_index("コード")
    t1 = y[y["_i"] == 1].set_index("コード")
    t = y[y["_i"] == 2].set_index("コード")

    # --- 定義どおりのデータが無い項目は代用に切り替える ----------------------
    # F4 特別損益前の純利益（直近期だけ要る）
    use_ni_x = t["_特別損益前純利益"].notna()
    ni_before_x = t["_特別損益前純利益"].where(use_ni_x, t["当期純利益"])
    # F5 長期借入金（直近期・前期・前々期の総資産と、直近期・前期の借入金が要る）
    use_ltd = t["_長期借入金"].notna() & t1["_長期借入金"].notna()
    debt = t["_長期借入金"].where(use_ltd, t["有利子負債"])
    debt1 = t1["_長期借入金"].where(use_ltd, t1["有利子負債"])
    # F7 株式発行（CF計算書の株式発行収入。無ければ株数で代用）
    use_iss = t["_株式発行収入"].notna()
    # F8 売上総利益率（2期そろえば使う。無ければ営業利益率）
    use_gp = t["_売上総利益"].notna() & t1["_売上総利益"].notna()
    margin_num = t["_売上総利益"].where(use_gp, t["営業利益"])
    margin_num1 = t1["_売上総利益"].where(use_gp, t1["営業利益"])

    subst = pd.DataFrame(index=t.index)
    subst["F4:当期純利益で代用"] = ~use_ni_x
    subst["F5:有利子負債で代用"] = ~use_ltd
    subst["F7:株式数で代用"] = ~use_iss
    subst["F8:営業利益率で代用"] = ~use_gp
    s_names = np.array(subst.columns)
    subst_note = pd.Series(["; ".join(s_names[row]) for row in subst.to_numpy()], index=t.index)

    # --- データ品質のチェック ----------------------------------------------
    flags = pd.DataFrame(index=t.index)
    for c in F_SOURCE_COLS:
        flags[f"直近期の{c}が欠損"] = t[c].isna()
        flags[f"前期の{c}が欠損"] = t1[c].isna()
    flags["前々期の総資産が欠損"] = t2["総資産"].isna()
    flags["長期借入金・有利子負債が欠損"] = debt.isna() | debt1.isna()
    flags["売上総利益・営業利益が欠損"] = margin_num.isna() | margin_num1.isna()
    flags["発行済株式数が欠損"] = (~use_iss) & (t["_株式数"].isna() | t1["_株式数"].isna())

    def same(a, b):          # 0同士（無借金など）は補完とはみなさない
        return a.notna() & (a == b) & (a != 0)

    for c in F_SOURCE_COLS:
        flags[f"{c}が直近期と前期で同値（補完疑い）"] = same(t[c], t1[c])
        flags[f"{c}が前期と前々期で同値（補完疑い）"] = same(t1[c], t2[c])
    flags["借入金が直近期と前期で同値（補完疑い）"] = same(debt, debt1)
    names = np.array(flags.columns)
    note = pd.Series([("; ".join(names[row])) for row in flags.to_numpy()], index=flags.index)

    # --- 9項目の採点 --------------------------------------------------------
    ta, ta1, ta2 = t["総資産"], t1["総資産"], t2["総資産"]
    avg_ta = (ta + ta1) / 2          # 直近期の平均総資産
    avg_ta1 = (ta1 + ta2) / 2        # 前期の平均総資産
    ni, ni1 = t["当期純利益"], t1["当期純利益"]
    rev, rev1 = t["売上高"], t1["売上高"]
    ocf = t["営業CF"]

    f = pd.DataFrame(index=t.index)
    # A. 収益性
    f["F1純利益"] = ni > 0
    f["F2営業CF"] = ocf > 0
    f["F3ROA変化"] = safe_div(ni, avg_ta) > safe_div(ni1, avg_ta1)
    f["F4収益の質"] = ocf > ni_before_x
    # B. レバレッジ・流動性・資金調達
    f["F5長期借入金"] = safe_div(debt, avg_ta) < safe_div(debt1, avg_ta1)
    f["F6流動比率"] = (safe_div(t["流動資産"], t["流動負債"])
                       > safe_div(t1["流動資産"], t1["流動負債"]))
    f["F7株式発行"] = np.where(use_iss, t["_株式発行収入"].abs() <= 0,
                               t["_株式数"] <= t1["_株式数"])
    # C. 営業効率
    f["F8売上総利益率"] = (safe_div(margin_num, rev.where(rev > 0))
                           > safe_div(margin_num1, rev1.where(rev1 > 0)))
    f["F9資産回転率"] = safe_div(rev, avg_ta) > safe_div(rev1, avg_ta1)
    f = f[F_COLS].astype(float)
    f["Fスコア"] = f[F_COLS].sum(axis=1)
    f = f[note == ""]          # 品質に問題がある銘柄は採点しない

    idx = d["コード"].astype(str)
    for c in F_COLS + ["Fスコア"]:
        d[c] = idx.map(f[c]).astype("float64")
    d[F_SUBST_COL] = idx.map(subst_note[note == ""]).fillna("")

    reason = idx.map(note).fillna("")
    reason = reason.mask(idx.isin(short_codes), "決算が3期分そろっていない")
    reason = reason.mask(reason.eq("") & d["Fスコア"].isna() & ~idx.isin(t.index),
                         "年次決算のデータが無い")
    fin = d["業種"].isin(FINANCIAL_SECTORS)
    for c in F_COLS + ["Fスコア"]:
        d.loc[fin, c] = np.nan
    d.loc[fin, F_SUBST_COL] = ""
    d["Fデータ品質"] = reason.mask(fin, "金融4業種のため対象外")

    n_ok = int(d["Fスコア"].notna().sum())
    n_fin = int(fin.sum())
    n_bad = int((d["Fデータ品質"] != "").sum()) - n_fin
    print(f"Fスコア: {n_ok:,}/{len(d):,}銘柄で算出"
          f"（金融4業種 {n_fin:,}銘柄は対象外／データ品質で見送り {n_bad:,}銘柄）")
    if n_ok:
        ok = d["Fスコア"].notna()
        for k in s_names:
            n = int(d.loc[ok, F_SUBST_COL].str.contains(k, regex=False).sum())
            print(f"  代用 {k}: {n:,}銘柄")
    return d


# ---------------------------------------------------------- 四季報式スコア

def grade_high(v: pd.Series, cuts: list, lowest_exclusive: bool = False) -> pd.Series:
    """高いほど良い指標を1〜5に区分する。cuts は評価2/3/4/5の下限（昇順、下限を含む）。
    lowest_exclusive=True のときだけ、いちばん下の境目は「より大きい」で判定する
    （増収率0%は『増えていない』ので2ではなく1にしたい、というような場合）。"""
    v = pd.to_numeric(v, errors="coerce")
    ok = v.notna()
    s = pd.Series(np.nan, index=v.index, dtype="float64")
    s = s.mask(ok, 1.0)
    for i, c in enumerate(cuts):            # 低い方から上書きするので高い評価が残る
        hit = (v > c) if (i == 0 and lowest_exclusive) else (v >= c)
        s = s.mask(ok & hit, float(i + 2))
    return s


def grade_low(v: pd.Series, cuts: list) -> pd.Series:
    """小さいほど良い指標を1〜5に区分する。cuts は評価5/4/3/2の上限（昇順、上限を含まない）。
    0以下は評価不能にする。赤字でPERがマイナスになったものを『激安』と読むのは誤り。"""
    v = pd.to_numeric(v, errors="coerce")
    ok = v.notna() & (v > 0)
    s = pd.Series(np.nan, index=v.index, dtype="float64")
    s = s.mask(ok, 1.0)
    for i in range(len(cuts) - 1, -1, -1):  # 大きい上限から当てるので小さい方が残る
        s = s.mask(ok & (v < cuts[i]), float(5 - i))
    return s


def grade_low_signed(v: pd.Series, cuts: list) -> pd.Series:
    """小さいほど良い指標を1〜5に区分する。grade_low と違いマイナスも有効な値として扱う。
    ネットD/Eのように「マイナス＝実質無借金＝いちばん良い」指標のための関数。
    cuts は評価5/4/3/2それぞれの上限（昇順、上限を含まない）。"""
    v = pd.to_numeric(v, errors="coerce")
    ok = v.notna()
    s = pd.Series(np.nan, index=v.index, dtype="float64")
    s = s.mask(ok, 1.0)
    for i in range(len(cuts) - 1, -1, -1):  # 大きい上限から当てるので小さい方が残る
        s = s.mask(ok & (v < cuts[i]), float(5 - i))
    return s


def grade_quintile(v: pd.Series) -> pd.Series:
    """全銘柄を5等分して、上位から5〜1を振る。
    値上がり率は市況しだいで水準が丸ごと動くため、絶対値の基準では意味を持たない。
    『同じ相場の中で上位だったか』を見る項目なので、ここだけ順位で区分する。"""
    v = pd.to_numeric(v, errors="coerce")
    r = v.rank(pct=True, na_option="keep")
    q = np.ceil(r * 5)
    return pd.Series(q, index=v.index, dtype="float64").clip(1, 5)


def grading_reference() -> list:
    """画面の「指標の説明」に出す判定基準の一覧。
    コードの定数からそのまま作るので、基準を変えたら説明も自動で追いつく。"""
    def hi(cuts, unit, lowest_exclusive=False):
        lo = "超" if lowest_exclusive else "以上"
        return [f"{cuts[3]:,g}{unit}以上",
                f"{cuts[2]:,g}〜{cuts[3]:,g}{unit}",
                f"{cuts[1]:,g}〜{cuts[2]:,g}{unit}",
                f"{cuts[0]:,g}〜{cuts[1]:,g}{unit}",
                f"{cuts[0]:,g}{unit}以下" if not lowest_exclusive
                else f"{cuts[0]:,g}{unit}以下"]

    g_cuts = SHIKIHO_BANDS["成長性"][1]
    r_cuts = SHIKIHO_BANDS["収益性"][1]
    s_cuts = SHIKIHO_BANDS["安全性"][1]
    c_cuts = SHIKIHO_BANDS["規模"][1]
    p = SHIKIHO_PER_CUTS
    pb = SHIKIHO_PBR_CUTS
    b = BANK_SAFETY_CUTS
    sc = SECURITIES_SAFETY_CUTS
    o = OTHER_FIN_DE_CUTS
    ic = INSURANCE_SAFETY_CUTS
    return [
        {"項目": "成長性", "元にする数値": f"売上高CAGR（直近{YEARS_FOR_TREND}期）",
         "区分": hi(g_cuts, "%", True),
         "注": f"四季報は5期ですが、手元のデータが{YEARS_FOR_TREND}期までのため{YEARS_FOR_TREND}期で計算しています。"},
        {"項目": "収益性", "元にする数値": f"売上高経常利益率の{YEARS_FOR_TREND}期平均",
         "区分": hi(r_cuts, "%"),
         "注": "四季報と同じく経常利益で測ります。経常利益は決算短信（J-Quants と TDnet）から期ごとに取り込み、"
               "まだ取り込めていない期だけ税引前利益で代えます（特別損益が入る分だけ振れやすい）。"
               "<b>IFRS・米国基準の会社</b>は経常利益という区分が無いため税引前利益を使います"
               "（IFRSには特別損益の区分も無く、税引前利益が経常利益にいちばん近い数字です）。"
               "何期を経常利益で計算したかは銘柄詳細の「収益性の基準」で確認できます。"},
        {"項目": "安全性", "元にする数値": "自己資本比率（直近本決算）",
         "区分": hi(s_cuts, "%"),
         "注": "金融業だけは業法の健全性指標に差し替えます。"
               f"<b>銀行</b>はバーゼル規制の資本余裕度（規制最低水準を何%pt上回っているか）"
               f"＝{b[3]:,g}%pt以上が5、{b[0]:,g}%pt未満が1。"
               f"<b>証券</b>は自己資本規制比率＝{sc[3]:,g}%以上が5、{sc[0]:,g}%未満が1"
               f"（{SECURITIES_MIN_RATIO:,g}%未満で業務停止命令）。"
               f"<b>保険</b>はソルベンシー・マージン比率＝{ic[3]:,g}%以上が5、{ic[0]:,g}%未満が1"
               f"（{INSURANCE_MIN_SMR:,g}%未満で早期是正措置）。"
               f"<b>その他金融</b>は純有利子負債÷自己資本＝{o[0]:,g}未満（実質無借金）が5、"
               f"{o[0]:,g}〜{o[1]:,g}が4、{o[1]:,g}〜{o[2]:,g}が3、{o[2]:,g}〜{o[3]:,g}が2、"
               f"{o[3]:,g}倍以上が1。"
               "保険代理店やPE・資産運用会社のように規制指標を持たない会社も自己資本比率で評価します。"
               "どの物差しを使ったかは銘柄詳細の「安全性の基準」で確認できます。"},
        {"項目": "規模", "元にする数値": "時価総額（前営業日終値ベース）",
         "区分": ["1.5兆円以上", "5,000億〜1.5兆円", "2,000〜5,000億円",
                "500〜2,000億円", "500億円未満"],
         "注": "自己株式を含む発行済株式総数で計算しています（Yahoo!ファイナンス・JPXと同じ）。"},
        {"項目": "割安度", "元にする数値": "会社予想PER（時価総額÷今期予想純利益）",
         "区分": [f"{p[0]:,g}倍未満", f"{p[0]:,g}〜{p[1]:,g}倍", f"{p[1]:,g}〜{p[2]:,g}倍",
                f"{p[2]:,g}〜{p[3]:,g}倍", f"{p[3]:,g}倍以上"],
         "注": "四季報と同じく今期の会社予想PERで測ります。予想は決算短信（J-Quants と TDnet）の"
               "最新の通期予想で、株式分割でズレないよう1株あたりではなく純利益で割っています。"
               "予想を出していない会社は実績PERを使います。"
               f"<b>赤字（予想赤字を含む）などでPERが使えない銘柄はPBRに切り替えます</b>"
               f"（{pb[0]:,g}倍未満=5／{pb[0]:,g}〜{pb[1]:,g}=4／{pb[1]:,g}〜{pb[2]:,g}=3／"
               f"{pb[2]:,g}〜{pb[3]:,g}=2／{pb[3]:,g}倍以上=1。{pb[1]:,g}倍が解散価値）。"
               "債務超過の銘柄はPBRも意味を持たないため評価しません。"
               "どちらで測ったかは銘柄詳細の「割安度の基準」で確認できます。"},
        {"項目": "値上がり", "元にする数値": "250営業日前と比べた株価の騰落率",
         "区分": ["上位20%", "上位20〜40%", "中位40〜60%", "下位40〜60%", "下位20%"],
         "注": "この項目だけは絶対値ではなく全銘柄の中の順位で5等分します。"
               "相場全体が上げ下げすると水準が丸ごと動くためです。"},
    ]


def shikiho_scores(d: pd.DataFrame, drop_financial_safety: bool = False) -> pd.DataFrame:
    """6項目を1〜5で評価し、その平均から総合評価を出す。

    drop_financial_safety=True のときは、金融4業種（銀行業・保険業・
    証券、商品先物取引業・その他金融業）の安全性と収益性を一律で評価不能にする。
    収益性を外すのは、金融業の「売上高」が経常収益（受取利息・保険料・
    受入手数料の合計）で、事業会社の売上高とは中身がまるで違うためで、
    売上高税引前利益率を同じ基準で比べても意味を持たない
    （銀行の中央値は35%前後で、事業会社の基準では全行が5になる）。
    東洋経済の60業種分類でいう「大手銀行」「地方銀行」「証券・先物」
    「リース・消費者金融」「損害保険」「生命保険」にあたる銘柄で、
    これらはJPXの33業種分類のこの4業種にそのまま対応する。
    健全性の指標が業態ごとに違い、事業会社と同じ土俵では比べられないという
    立場を徹底したい場合に使う。残り5項目で総合評価を出す。"""
    out = pd.DataFrame(index=d.index)

    for item, (col, cuts) in SHIKIHO_BANDS.items():
        src = d[col] if col in d.columns else pd.Series(np.nan, index=d.index)
        out[item] = grade_high(src, cuts, lowest_exclusive=(item == "成長性"))

    # 安全性: 業態ごとに物差しを替える。
    # 会計上の自己資本比率は、預金・保険契約準備金・顧客預り金が負債に積み上がる
    # 業態では数%にしかならず、そのまま80%/60%/40%/20%に当てると全社が1になる。
    # 銀行・保険・証券はそれぞれの業法が定める健全性指標で採点し、
    # その他金融業（リース・クレジット等）は事業会社と同じ自己資本比率のままにする。
    # 使った物差しは「安全性の基準」列に残して、画面で確認できるようにする。
    basis = pd.Series("自己資本比率", index=d.index, dtype="object")
    code = d["コード"].astype(str)

    def apply_regulated(mask, col, cuts, name):
        """mask の銘柄を col の値で採点する。値が無いものは評価不能にする"""
        if col not in d.columns:
            out.loc[mask, "安全性"] = np.nan
            basis.loc[mask] = f"{name}（未取得）"
            return
        have = mask & d[col].notna()
        out.loc[mask, "安全性"] = np.nan
        out.loc[have, "安全性"] = grade_high(d.loc[have, col], cuts)
        basis.loc[have] = name
        basis.loc[mask & ~have] = f"{name}（未取得）"

    apply_regulated(d["業種"].eq("銀行業"), "資本余裕度(%pt)",
                    BANK_SAFETY_CUTS, "バーゼル資本余裕度")
    apply_regulated(d["業種"].eq("保険業") & code.isin(REGULATED_INSURERS),
                    "ソルベンシー・マージン比率(%)",
                    INSURANCE_SAFETY_CUTS, "ソルベンシー・マージン比率")
    # その他金融業（リース・クレジット・保証・取引所）はネットD/Eレシオ。
    # 有利子負債も現金も取れない銘柄だけ、会計上の自己資本比率のまま据え置く。
    oth = d["業種"].eq("その他金融業")
    de = "純有利子負債/自己資本"
    if de in d.columns:
        have = oth & d[de].notna()
        out.loc[have, "安全性"] = grade_low_signed(d.loc[have, de], OTHER_FIN_DE_CUTS)
        basis.loc[have] = "純有利子負債/自己資本"
        # 債務超過だと比率が意味を持たない（自己資本がマイナスで符号が反転する）ので、
        # 計算に乗せず最低評価にする
        insolvent = oth & (d["自己資本"] <= 0)
        out.loc[insolvent, "安全性"] = 1.0
        basis.loc[insolvent] = "債務超過"

    # 証券会社は自己資本規制比率。一覧に載らない会社（FX専業・商品先物・PE・運用会社）は
    # 規制指標を持たないので、会計上の自己資本比率のまま据え置く。
    sec = d["業種"].eq("証券、商品先物取引業") & d.get(
        "自己資本規制比率(%)", pd.Series(np.nan, index=d.index)).notna()
    if sec.any():
        out.loc[sec, "安全性"] = grade_high(d.loc[sec, "自己資本規制比率(%)"],
                                            SECURITIES_SAFETY_CUTS)
        basis.loc[sec] = "自己資本規制比率"
    if drop_financial_safety:
        fin_all = d["業種"].isin(FINANCIAL_SECTORS)
        out.loc[fin_all, "安全性"] = np.nan
        out.loc[fin_all, "収益性"] = np.nan
        basis.loc[fin_all] = "金融業のため評価しない"
    d["安全性の基準"] = basis

    # 割安度は四季報と同じく会社予想PER。予想が無い銘柄は実績PER、
    # 赤字（今期予想が赤字の場合を含む）や報告EPSの桁ズレでPERが使えない銘柄はPBRに切り替える。
    # 予想赤字の会社に実績PERを当てると「もう稼げない利益」で割安に見えてしまうため、
    # 予想が出ていて赤字なら実績PERには戻らない。どれで測ったかは「割安度の基準」列に残す。
    nan_s = pd.Series(np.nan, index=d.index)
    fc_grade = grade_low(d.get("予想PER", nan_s), SHIKIHO_PER_CUTS)
    fc_np = pd.to_numeric(d.get("今期予想純利益(億円)", nan_s), errors="coerce")
    fc_loss = fc_np.notna() & (fc_np <= 0)
    act_grade = grade_low(d.get("PER(分析用)", nan_s), SHIKIHO_PER_CUTS).mask(fc_loss)
    per_grade = fc_grade.where(fc_grade.notna(), act_grade)
    pbr_grade = grade_low(d.get("PBR", nan_s), SHIKIHO_PBR_CUTS)
    out["割安度"] = per_grade.where(per_grade.notna(), pbr_grade)
    vbasis = pd.Series("予想PER", index=d.index, dtype="object")
    vbasis = vbasis.mask(fc_grade.isna() & act_grade.notna(), "実績PER")
    vbasis = vbasis.mask(per_grade.isna() & pbr_grade.notna() & fc_loss, "PBR（予想赤字）")
    vbasis = vbasis.mask(per_grade.isna() & pbr_grade.notna() & ~fc_loss, "PBR")
    # 債務超過だと純資産がマイナスでPBRも意味を持たないので、ここだけ評価不能が残る
    vbasis = vbasis.mask(per_grade.isna() & pbr_grade.isna(), "評価不能")
    d["割安度の基準"] = vbasis
    out["値上がり"] = grade_quintile(d.get("250日騰落率(%)",
                                          pd.Series(np.nan, index=d.index)))
    return out[SHIKIHO_ITEMS]


def add_shikiho(d: pd.DataFrame, drop_financial_safety: bool = False) -> pd.DataFrame:
    d = d.copy()
    g = shikiho_scores(d, drop_financial_safety)
    for item in SHIKIHO_ITEMS:
        d[f"{item}評価"] = g[item]

    n = g.notna().sum(axis=1)
    avg = g.mean(axis=1, skipna=True).where(n >= SHIKIHO_MIN_ITEMS)
    d["有効項目数"] = n
    d["評価平均"] = avg.round(2)
    d["総合評価"] = grade_high(avg, SHIKIHO_TOTAL_CUTS)

    # 順位は1〜5に丸める前の平均で付ける。丸めたあとだと同点が数百銘柄になってしまう。
    d["総合順位"] = d["評価平均"].rank(ascending=False, method="min")
    d["業種内順位"] = d.groupby("業種", observed=True)["評価平均"].rank(
        ascending=False, method="min"
    )
    d["業種内銘柄数"] = d["業種"].map(d["業種"].value_counts())

    # 業種内偏差値。同じ業種の中で平均から何標準偏差ぶん離れているかを50±10で表す。
    # 1〜5の総合評価だと同点が数百銘柄になって差が見えないので、丸める前の
    # 評価平均を使う。母集団はその業種の全銘柄なので標準偏差は ddof=0。
    grp = d.groupby("業種", observed=True)["評価平均"]
    mean = grp.transform("mean")
    sd = grp.transform(lambda x: x.std(ddof=0))
    n = grp.transform("count")
    dev = 50 + 10 * (d["評価平均"] - mean) / sd.where(sd > 1e-9)
    d["業種内偏差値"] = dev.where(n >= MIN_SECTOR_FOR_DEVIATION).round(1)
    return d


# ---------------------------------------------------------------- スクリーニング

def build_screens(d: pd.DataFrame) -> dict:
    """条件別の候補銘柄。5つの条件はダッシュボードのプリセットと同じものです。

    共通の前提は置いていません（各条件の中で必要な足切りを完結させています）。
    流動比率は画面では%で持っているので、1倍=100%、1.5倍=150%に読み替えます。"""
    screens = {}

    screens["割安株"] = {
        "説明": "PER10倍以下・PBR0.6倍以下・流動比率2倍以上・負債資本比率0.5倍以下。"
                "利益と純資産に対して安く、短期の支払いと借入にも無理がない銘柄。",
        "条件": (d["PER(分析用)"] > 0) & (d["PER(分析用)"] <= 10)
        & (d["PBR"] > 0) & (d["PBR"] <= 0.6)
        & (d["流動比率(%)"] >= 200)
        & (d["負債資本比率"] <= 0.5),
        "並び": "PER(分析用)",
    }

    screens["成長株"] = {
        "説明": "増収率20%以上・ROE20%以上・純利益率10%以上。"
                "売上が伸びていて、しかもきちんと利益と資本効率に結びついている銘柄。",
        "条件": (d["売上高成長率(%)"] >= 20)
        & (d["ROE(%)"] >= 20)
        & (d["純利益率(%)"] >= 10),
        "並び": "売上高成長率(%)",
    }

    screens["高配当株"] = {
        "説明": "配当利回り4%以上・配当性向30〜60%・1株当たりフリーCFがプラス・自己資本比率50%以上。"
                "利回りが高く、無理のない配当性向で、実際のキャッシュで賄えている銘柄。",
        "条件": (d["配当利回り(%)"] >= 4)
        & (d["配当性向(%)"] >= 30) & (d["配当性向(%)"] <= 60)
        & (d["1株当たりフリーCF"] > 0)
        & (d["自己資本比率(%)"] >= 50),
        "並び": "配当利回り(%)",
    }

    screens["安定優良株"] = {
        "説明": "ROE20%以上・流動比率2倍以上・負債資本比率0.3倍以下・ベータ(1年)0.8以下。"
                "稼ぐ力があり、財務に余裕があり、値動きが市場より穏やかな銘柄。",
        "条件": (d["ROE(%)"] >= 20)
        & (d["流動比率(%)"] >= 200)
        & (d["負債資本比率"] <= 0.3)
        & (d["ベータ(1年)"] <= 0.8),
        "並び": "ROE(%)",
    }

    screens["高収益企業"] = {
        "説明": "ROE25%以上・ROTC20%以上・EBITDAマージン20%以上・純利益率10%以上。"
                "自己資本でも投下資本でも高い利益率を出していて、本業の稼ぐ力が厚い銘柄。",
        "条件": (d["ROE(%)"] >= 25)
        & (d["ROTC(%)"] >= 20)
        & (d["EBITDAマージン(%)"] >= 20)
        & (d["純利益率(%)"] >= 10),
        "並び": "ROE(%)",
    }

    screens["なごちょう式"] = {
        "説明": "ネットキャッシュ倍率1倍未満・売上高CAGR10%以上・自己資本比率50%以上・"
                "流動比率200%以上・営業利益率10%以上・配当利回り3%以上・PER10倍以下・PBR1倍以下。"
                "時価総額より換金しやすい資産のほうが多く、その上で伸びていて、儲かっていて、"
                "配当も出ている銘柄。8条件すべてを満たすのは全上場企業で数銘柄しかありません。",
        "条件": (d["ネットキャッシュ倍率"] < 1)
        & (d["売上高CAGR(%)"] >= 10)
        & (d["自己資本比率(%)"] >= 50)
        & (d["流動比率(%)"] >= 200)
        & (d["営業利益率(%)"] >= 10)
        & (d["配当利回り(%)"] >= 3)
        & (d["PER(分析用)"] > 0) & (d["PER(分析用)"] <= 10)
        & (d["PBR"] > 0) & (d["PBR"] <= 1),
        "並び": "ネットキャッシュ倍率",
    }

    screens["DOE安定配当株"] = {
        "説明": "DOE5%以上・直近3期の平均DOE5%以上・手元の期間（最大4期）で減配なし・"
                "DOEの前期比が−1〜+3%pt（急な上げ下げが無い）・自己資本比率60%以上・配当性向70%以下。"
                "自己資本を基準に配当を決めていて利益の上下で配当がぶれにくく、"
                "財務と利益の裏付けもある銘柄。自己資本の小さい会社でDOEが極端に高く出るのを"
                "自己資本比率の足切りで除いている。",
        "条件": (d["DOE(%)"] >= 5)
        & (d["平均DOE(%)"] >= 5)
        & (d["減配回数"] == 0)
        & (d["DOE変化(%pt)"] >= -1) & (d["DOE変化(%pt)"] <= 3)
        & (d["自己資本比率(%)"] >= 60)
        & (d["配当性向(%)"] > 0) & (d["配当性向(%)"] <= 70),
        "並び": "DOE(%)",
    }

    screens["連続増配株"] = {
        "説明": "手元の期間（最大4期）で毎期増配（連続増配期数3以上）・配当CAGR15〜50%"
                "（無配・復配からの見かけの急増を除くため上限を置く）・"
                "配当性向40%以下・FCF配当性向60%以下・ROE12%以上・自己資本比率50%以上。"
                "配当を毎年引き上げていて、しかも利益とキャッシュにまだ余力がある銘柄。",
        "条件": (d["連続増配期数"] >= 3)
        & (d["配当CAGR(%)"] >= 15) & (d["配当CAGR(%)"] <= 50)
        & (d["配当性向(%)"] > 0) & (d["配当性向(%)"] <= 40)
        & (d["FCF配当性向(%)"] <= 60)
        & (d["ROE(%)"] >= 12)
        & (d["自己資本比率(%)"] >= 50),
        "並び": "配当CAGR(%)",
    }

    screens["PEG割安成長株"] = {
        "説明": "PEG0.6倍以下・EPS成長率(年率)15〜50%・営業利益CAGR15%以上・平均ROE15%以上・"
                "純有利子負債/EBITDA2倍以下。EPS成長率は始点の利益が小さいと見かけ上跳ね上がるので"
                "50%で上限を置き、一時要因の疑いがある銘柄と決算が古い銘柄は除く。"
                "利益の伸びに対してPERが低く、成長が営業利益でも裏付けられ、借金に頼っていない銘柄。",
        "条件": (d["PEG"] > 0) & (d["PEG"] <= 0.6)
        & (d["EPS_CAGR(%)"] >= 15) & (d["EPS_CAGR(%)"] <= 50)
        & (d["営業利益CAGR(%)"] >= 15)
        & ~d["一時要因の疑い"] & ~d["決算が古い"]
        & (d["平均ROE(%)"] >= 15)
        & (d["純有利子負債/EBITDA"] <= 2),
        "並び": "PEG",
    }

    screens["新高値ブレイク株"] = {
        "説明": "5営業日以内に52週新高値を更新・増収率10%以上・営業増益率10%以上・黒字・決算が新しい。"
                "業績の伸びを伴って高値を抜けてきた銘柄（新高値投資法の考え方）。"
                "並び順は出来高倍率（直近5日÷50日）の高い順で、商いを伴ったブレイクほど上に来る。",
        "条件": (d["新高値からの日数"] <= 4)
        & (d["売上高成長率(%)"] >= 10)
        & (d["営業利益成長率(%)"] >= 10)
        & ~d["赤字"] & ~d["決算が古い"],
        "並び": "出来高倍率(5日/50日)",
    }

    screens["成長ブレイク株"] = {
        "説明": "今期（会社予想）を含む3期の営業増益率が平均30%以上・自己資本比率50%以上・"
                "直近2期の営業CFがともに黒字・株価が5日/25日/75日/200日の移動平均線すべてより上。"
                "今期予想が無い銘柄は実績の直近3期で判定。"
                "並び順は、横ばい（直近5日を除く前60営業日の値幅20%以内）から上放れた銘柄を先頭に、"
                "その中で営業増益率3期平均の高い順。「横ばい上放れ」が1の銘柄が最も良い形。",
        "条件": (d["営業増益率3期平均(%)"] >= 30)
        & (d["自己資本比率(%)"] >= 50)
        & (d["営業CF2期黒字"] == 1)
        & (d["移動平均線の上の本数"] == 4),
        "並び": ["横ばい上放れ", "営業増益率3期平均(%)"],
    }

    screens["上場来高値更新株"] = {
        "説明": "5営業日以内に上場来高値を更新・黒字・増収率5%以上・営業増益率5%以上。上に売りたい人（含み損の株主）がいない状態で、"
                "新高値の中でも特に強い形。株価データは2016年8月以降なので、それより前に上場した銘柄は"
                "「約10年来の高値」の意味。並び順は出来高倍率の高い順。",
        "条件": (d["上場来高値からの日数"] <= 4)
        & ~d["赤字"]
        & (d["売上高成長率(%)"] >= 5)
        & (d["営業利益成長率(%)"] >= 5),
        "並び": "出来高倍率(5日/50日)",
    }

    if "予想Fスコア" in d.columns:
        screens["復活Fスコア"] = {
            "説明": "PBR0.8倍未満・予想Fスコア9点・時価総額1,000億円以上（金融4業種は対象外）。"
                    "割安に放置された銘柄の中から、今期の会社予想と前期実績で9項目すべてに"
                    "改善の兆しがある銘柄（マネックス証券「復活Fスコア戦略」のスクリーニング条件）。"
                    "F1〜F3・F7は今期の会社予想（決算短信。J-Quants と TDnet）、残りは前期実績で判定。"
                    "戦略の基本形は8点以上なので、候補を広げたいときはダッシュボードで8に下げて使う。",
            "条件": (d["PBR"] > 0) & (d["PBR"] < 0.8)
            & (d["予想Fスコア"] >= 9)
            & (d["時価総額(億円)"] >= 1000)
            & ~d["業種"].isin(FINANCIAL_SECTORS),
            "並び": "PBR",
        }

    if "マルチバガー基本条件" in d.columns:
        screens["マルチバガー候補"] = {
            "説明": "論文「The Alchemy of Multibagger Stocks」(Yartseva 2025) の実証結果に基づく条件。"
                    "時価総額は業種別レンジ内（情報通信500〜3000億・サービス300〜2000億・"
                    "小売200〜1500億・製造業500〜5000億・その他100〜5000億）、"
                    "ROE15%以上・営業利益率10%以上・フリーCFプラス・"
                    "FCF利回りが業種基準以上（情報通信4%・サービス5%・小売6%・製造業5%）・"
                    "増収率とCAGRがともに5%以上。金融4業種と決算が古い銘柄は対象外。"
                    "並び順は適合度スコア（評価値40＋エントリー30＋品質20＋金利調整）。"
                    "「エントリー判定」がOKなら、スコア70以上かつ52週レンジ位置30%以下・"
                    "6か月騰落率+5%以下で、買い場の条件も満たしている。",
            "条件": d["マルチバガー基本条件"],
            "並び": "マルチバガースコア",
        }

    if "論文条件" in d.columns:
        screens["マルチバガー論文準拠"] = {
            "説明": "論文「The Alchemy of Multibagger Stocks」(Yartseva 2025) が有意とした変数だけを使った条件。"
                    "時価総額20〜3,000億円・PBR2.5倍以下（B/M0.40以上）・営業黒字・FCF利回りプラス・"
                    "直近期の総資産の伸びがEBITDAの伸び以下（論文のInvダミー=0）・過去の期の半分以上でFCF黒字。"
                    "増収率・ROE・PERは論文で予測力が無いとされたので使わない。金融4業種と決算が古い銘柄は対象外。"
                    "条件を満たす銘柄が数百あるので、論文スコア72点以上に絞っている。"
                    "並び順は論文スコア（FCF利回り30・B/M25・小型15・52週安値圏15・6か月下落10・ROA5の100点）。"
                    "「論文エントリー」が安値圏なら52週レンジ位置30%以下かつ6か月騰落率0%以下。"
                    "「論文注意」に印がある銘柄は一時要因を決算書で確認すること。",
            "条件": d["論文条件"] & (d["論文スコア"] >= 72),
            "並び": "論文スコア",
        }

    if "需給スコア" in d.columns and d["需給スコア"].notna().any():
        screens["好需給株"] = {
            "説明": "需給分析（JPXの日々の銘柄別信用残・日証金・大口空売り・価格帯別出来高）で需給スコア65以上か踏み上げ候補。"
                    "上値が軽い（買残が少ない・上の価格帯の出来高が少ない）、売残が厚く買い戻しが入りやすい、買残の整理が進んでいる銘柄。"
                    "売買代金25日平均1億円以上。需給スコアは経験則による目安（需給分析ダッシュボード参照）。",
            "条件": d["需給判定"].isin(["好需給", "踏み上げ候補"]) & (d["売買代金25日平均(百万円)"] >= 100),
            "並び": "需給スコア",
        }
        screens["信用買残が重い株"] = {
            "説明": "信用倍率8倍以上かつ信用買残が25日平均出来高の7日分以上、または買い方の評価損益率−20%以下で買残5日分以上。"
                    "上がると戻り売り（やれやれ売り）が出やすく、下げると追証の投げが出やすい。保有株の点検用。",
            "条件": d["需給判定"].isin(["買残重い", "投げ警戒"]),
            "並び": "買残回転日数(日)",
        }

    if "日経225入替スコア" in d.columns:
        screens["日経225採用候補"] = {
            "説明": "日経平均の構成銘柄選定基準（過去5年の売買代金と売買代金当たりの価格変動率で上位450＝高流動性、"
                    "未採用の75位以内は採用、セクターごとの採用妥当数）を株価CSVで再現し、次回の定期見直し"
                    "（4月・10月の第1営業日。基準日は1月末・7月末）で採用されそうな銘柄。"
                    "日経225入替スコアは採用予想の確度 高90・中70・低50、流動性100位以内や不足セクターの上位は30。"
                    "採用銘柄は基準日から実施日の前日にかけて上がりやすく、実施後は反落しやすい（日経225ダッシュボード参照）。",
            "条件": (d["日経225入替スコア"] >= 30) & (d["日経225採用"] == 0),
            "並び": ["日経225入替スコア"],
        }

    out = {}
    for name, spec in screens.items():
        sub = d[spec["条件"].fillna(False)].copy()
        by = spec["並び"]
        if isinstance(by, list):   # 複数キーは左から順にすべて大きい順
            sub = sub.sort_values(by, ascending=[False] * len(by), na_position="last")
        else:
            asc = by in ("PER(分析用)", "PBR", "PSR", "ネットキャッシュ倍率", "PEG")
            sub = sub.sort_values(by, ascending=asc, na_position="last")
        out[name] = {"説明": spec["説明"], "銘柄": sub}
    return out


# ---------------------------------------------------------------- 集計

AGG_METRICS = [
    "PER", "PBR", "PSR", "ROE(%)", "ROA(%)", "営業利益率(%)", "純利益率(%)",
    "自己資本比率(%)", "流動比率(%)", "配当利回り(%)", "配当性向(%)", "DOE(%)",
    "売上高成長率(%)", "営業利益成長率(%)",
]


def aggregate(d: pd.DataFrame, key: str) -> pd.DataFrame:
    # 中央値なので外れ値の影響を受けない。PER/PBRは正の値だけを対象にする。
    w = d.copy()
    for c in ("PER", "PBR", "PSR"):
        w[c] = w[c].where(w[c] > 0)
    g = w.groupby(key, observed=True)
    res = g[AGG_METRICS].median().round(2)
    res.insert(0, "銘柄数", g.size())
    res.insert(1, "時価総額合計(兆円)", (g["時価総額"].sum() / 1e12).round(2))
    res.insert(2, "赤字銘柄数", g["赤字"].sum())
    res["総合評価中央値"] = g["評価平均"].median().round(2)
    return res.sort_values("時価総額合計(兆円)", ascending=False)


# ---------------------------------------------------------------- 出力

DISPLAY_COLS = [
    "コード", "銘柄名", "市場", "業種", "株価", "決算期", "事業概要", "会社URL",
    "時価総額(億円)", "売上高(億円)", "営業利益(億円)", "当期純利益(億円)",
    "自己資本(億円)", "EPS", "BPS",
    "PER", "PER(時価総額ベース)", "PBR", "PSR", "配当利回り(%)", "配当性向(%)",
    "DOE(%)", "平均DOE(%)", "DOE変化(%pt)", "減配回数", "連続増配期数", "配当CAGR(%)", "FCF配当性向(%)",
    "PEG", "益回り(%)", "EPS_CAGR(%)", "営業利益CAGR(%)", "平均ROE(%)",
    "ネットキャッシュ比率(%)", "純有利子負債/EBITDA",
    "ROE(%)", "ROA(%)", "営業利益率(%)", "純利益率(%)",
    "自己資本比率(%)", "流動比率(%)", "営業CFマージン(%)", "FCF利回り(%)",
    "EV/EBITDA", "ROTC(%)", "EBITDAマージン(%)", "インタレストカバレッジ", "ベータ", "ベータ(1年)",
    "年率ボラティリティ(%)", "EV(億円)", "ネットキャッシュ(億円)", "換金性資産(億円)",
    "ネットキャッシュ倍率", "負債資本比率", "1株当たりフリーCF",
    "適用基準", "バーゼル自己資本比率(%)", "規制最低水準(%)", "資本余裕度(%pt)", "不良債権比率(%)",
    "自己資本規制比率(%)", "ソルベンシー・マージン比率(%)", "純有利子負債/自己資本", "安全性の基準",
    "割安度の基準",
    "売上高成長率(%)", "営業利益成長率(%)", "当期純利益成長率(%)", "総資本増加率(%)",
    "売上高CAGR(%)", "平均税引前利益率(%)", *KEIJO_COLS, *YOSOU_COLS, "250日騰落率(%)", "125日騰落率(%)",
    "52週高値", "52週安値", "52週レンジ位置(%)",
    "新高値からの日数", "新高値回数(20日)", "52週高値乖離(%)", "上場来高値からの日数", "上場来高値乖離(%)", "出来高倍率(5日/50日)", "5日線乖離(%)", "25日線乖離(%)", "75日線乖離(%)", "200日線乖離(%)", "移動平均線の上の本数", "ボックス幅(%)", "ボックス上抜け(%)", "横ばい上放れ", "営業増益率3期平均(%)", "営業増益率3期最低(%)", "営業増益率の基準", "営業CF2期黒字",
        *SBI_BASIC_COLS, *TECH_COLS, *FC_EXTRA_COLS,
    "マルチバガースコア", "エントリー判定", "評価値スコア", "エントリースコア", "品質スコア",
    "適合業種区分", "FCF利回り基準(%)", "適合時価総額レンジ", "P/FCF",
    "FCF黒字比率(%)", "総資産CAGR(%)", "EBITDA_CAGR(%)", "成長ギャップ(%pt)",
    "設備投資/売上(%)", "FCF/設備投資", "マルチバガー基本条件",
    "論文スコア", "論文エントリー", "論文注意", "論文条件", "B/M",
    "総資産成長率(%)", "EBITDA成長率(%)", "Invダミー",
    "Fスコア", *F_COLS, "Fデータ品質", F_SUBST_COL,
        *YF_ALL,
    "日経225採用", "日経225ウエート(%)", "日経225流動性順位", "日経225セクター",
    "日経225入替予想", "日経225入替スコア",
        *JUKYU_COLS,
    "成長性評価", "収益性評価", "安全性評価", "規模評価", "割安度評価", "値上がり評価",
    "評価平均", "総合評価", "総合順位", "業種内順位", "業種内銘柄数", "業種内偏差値",
    "有効項目数", "CAGR期数", "株価遅延日数", "決算が古い", "赤字", "一時要因の疑い",
    "EPS乖離", "金融",
]


def write_excel(path: Path, d: pd.DataFrame, screens: dict,
                by_sector: pd.DataFrame, by_market: pd.DataFrame) -> None:
    cols = [c for c in DISPLAY_COLS if c in d.columns]
    ranked = d.sort_values("評価平均", ascending=False)[cols]
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        ranked.to_excel(xw, sheet_name="総合ランキング", index=False)
        for name, spec in screens.items():
            sheet = name[:28]
            spec["銘柄"][cols].to_excel(xw, sheet_name=sheet, index=False)
        by_sector.to_excel(xw, sheet_name="業種別")
        by_market.to_excel(xw, sheet_name="市場別")
        # 各シートの1行目を固定
        for ws in xw.book.worksheets:
            ws.freeze_panes = "A2"


def clean(v):
    if v is None:
        return None
    try:
        if pd.isna(v):   # NaN / NaT / pd.NA をまとめて null にする
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        return None if not np.isfinite(v) else round(float(v), 4)
    return v


def dashboard_payload(d: pd.DataFrame, screens: dict, by_sector: pd.DataFrame,
                      by_market: pd.DataFrame, src_date: str,
                      drop_financial_safety: bool = False) -> dict:
    fields = [
        "コード", "銘柄名", "市場", "業種", "株価", "決算期", "事業概要", "会社URL",
        "時価総額(億円)", "売上高(億円)", "営業利益(億円)", "当期純利益(億円)",
        "自己資本(億円)", "EPS", "BPS",
        "PER", "PER(時価総額ベース)", "PBR", "PSR", "配当利回り(%)", "配当性向(%)",
        "DOE(%)", "平均DOE(%)", "DOE変化(%pt)", "減配回数", "連続増配期数", "配当CAGR(%)", "FCF配当性向(%)",
        "PEG", "益回り(%)", "EPS_CAGR(%)", "営業利益CAGR(%)", "平均ROE(%)",
        "ネットキャッシュ比率(%)", "純有利子負債/EBITDA",
        "ROE(%)", "ROA(%)", "営業利益率(%)", "純利益率(%)",
        "自己資本比率(%)", "流動比率(%)", "営業CFマージン(%)", "FCF利回り(%)",
        "EV/EBITDA", "ROTC(%)", "EBITDAマージン(%)", "インタレストカバレッジ", "ベータ", "ベータ(1年)",
        "年率ボラティリティ(%)", "EV(億円)", "ネットキャッシュ(億円)", "換金性資産(億円)",
    "ネットキャッシュ倍率", "負債資本比率", "1株当たりフリーCF",
        "適用基準", "バーゼル自己資本比率(%)", "資本余裕度(%pt)", "不良債権比率(%)",
        "自己資本規制比率(%)", "ソルベンシー・マージン比率(%)", "純有利子負債/自己資本", "安全性の基準",
        "割安度の基準",
        "売上高成長率(%)", "営業利益成長率(%)", "当期純利益成長率(%)",
        "売上高CAGR(%)", "平均税引前利益率(%)", *KEIJO_COLS, *YOSOU_COLS, "250日騰落率(%)", "125日騰落率(%)",
        "52週レンジ位置(%)",
        "新高値からの日数", "新高値回数(20日)", "52週高値乖離(%)", "上場来高値からの日数", "上場来高値乖離(%)", "出来高倍率(5日/50日)", "5日線乖離(%)", "25日線乖離(%)", "75日線乖離(%)", "200日線乖離(%)", "移動平均線の上の本数", "ボックス幅(%)", "ボックス上抜け(%)", "横ばい上放れ", "営業増益率3期平均(%)", "営業増益率3期最低(%)", "営業増益率の基準", "営業CF2期黒字",
        *SBI_BASIC_COLS, *TECH_COLS, *FC_EXTRA_COLS,
        "マルチバガースコア", "エントリー判定", "評価値スコア", "エントリースコア", "品質スコア",
        "適合業種区分", "FCF利回り基準(%)", "P/FCF",
        "FCF黒字比率(%)", "総資産CAGR(%)", "EBITDA_CAGR(%)", "成長ギャップ(%pt)",
        "設備投資/売上(%)", "FCF/設備投資",
        "論文スコア", "論文エントリー", "論文注意", "B/M",
        "総資産成長率(%)", "EBITDA成長率(%)", "Invダミー",
        "Fスコア", *F_COLS, "Fデータ品質", F_SUBST_COL,
        *YF_ALL,
        *[c for c in JUKYU_COLS if c not in ("需給メモ", "信用残の申込日")],
        "成長性評価", "収益性評価", "安全性評価", "規模評価", "割安度評価", "値上がり評価",
        "評価平均", "総合評価", "総合順位", "業種内順位", "業種内銘柄数", "業種内偏差値",
        "有効項目数", "CAGR期数", "決算が古い", "赤字", "一時要因の疑い", "EPS乖離",
    ]
    ranked = d.sort_values("評価平均", ascending=False, na_position="last")
    rows = [[clean(v) for v in rec] for rec in ranked[fields].itertuples(index=False, name=None)]
    code_index = {c: i for i, c in enumerate(ranked["コード"].astype(str))}

    screen_out = {}
    for name, spec in screens.items():
        codes = [str(c) for c in spec["銘柄"]["コード"]]
        screen_out[name] = {
            "説明": spec["説明"],
            "件数": len(codes),
            "行": [code_index[c] for c in codes if c in code_index],
        }

    def table(df):
        return {
            "index": [str(i) for i in df.index],
            "columns": list(df.columns),
            "rows": [[clean(v) for v in r] for r in df.itertuples(index=False, name=None)],
        }

    pos = d[d["PER"] > 0]
    summary = {
        "銘柄数": int(len(d)),
        "時価総額合計(兆円)": clean(d["時価総額"].sum() / 1e12),
        "PER中央値": clean(pos["PER"].median()),
        "PBR中央値": clean(d.loc[d["PBR"] > 0, "PBR"].median()),
        "ROE中央値(%)": clean(d["ROE(%)"].median()),
        "配当利回り中央値(%)": clean(d["配当利回り(%)"].median()),
        "自己資本比率中央値(%)": clean(d["自己資本比率(%)"].median()),
        "売上高成長率中央値(%)": clean(d["売上高成長率(%)"].median()),
        "赤字銘柄数": int(d["赤字"].sum()),
        "決算が古い銘柄数": int(d["決算が古い"].fillna(False).sum()),
        "一時要因の疑い": int(d["一時要因の疑い"].sum()),
        "EPS乖離": int(d["EPS乖離"].sum()),
        "総合評価中央値": clean(d["評価平均"].median()),
        "総合評価あり": int(d["総合評価"].notna().sum()),
    }

    # レーダーチャートに重ねる業種内中央値。絞り込みでは動かさず、
    # 常に「その業種の全銘柄の真ん中」を指すようにする。
    med = d.groupby("業種", observed=True)[[f"{i}評価" for i in SHIKIHO_ITEMS]].median()
    sector_median = {str(k): [clean(v) for v in row]
                     for k, row in zip(med.index, med.to_numpy())}

    return {
        "生成日": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "株価日付": src_date,
        "fields": fields,
        "stocks": rows,
        "screens": screen_out,
        "sector": table(by_sector.reset_index()),
        "market": table(by_market.reset_index()),
        "summary": summary,
        "版": ("金融の安全性・収益性を評価しない版" if drop_financial_safety else "標準版"),
        "金融の安全性を評価しない": bool(drop_financial_safety),
        "項目": SHIKIHO_ITEMS,
        "評価基準": grading_reference(),
        "業種中央値": sector_median,
    }


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description="東証全銘柄のファンダメンタル分析")
    ap.add_argument("--src", default=str(SRC), help="入力CSV")
    ap.add_argument("--out", default=str(OUT), help="出力先ディレクトリ")
    ap.add_argument("--min-cap", type=float, default=0.0,
                    help="この時価総額(億円)未満の銘柄を分析対象から外す")
    ap.add_argument("--bank-capital", default=str(BANK_CAPITAL),
                    help="銀行のバーゼル自己資本比率CSV")
    ap.add_argument("--beta", default=str(BETA), help="ベータ値のCSV")
    ap.add_argument("--new-high", default=str(NEW_HIGH), help="新高値の状況のCSV")
    ap.add_argument("--technical", default=str(TECHNICAL), help="テクニカル指標のCSV")
    ap.add_argument("--jq-summary", default=str(JQ_SUMMARY),
                    help="J-Quants fins summary のJSONを置いたフォルダ（予想Fスコア用）")
    ap.add_argument("--by-year", default=str(BY_YEAR),
                    help="年次決算の推移CSV（成長性・収益性の計算に使う）")
    ap.add_argument("--sec-capital", default=str(SEC_CAPITAL),
                    help="証券会社の自己資本規制比率CSV")
    ap.add_argument("--ins-solvency", default=str(INS_SOLVENCY),
                    help="保険会社のソルベンシー・マージン比率CSV")
    ap.add_argument("--profile", default=str(COMPANY_PROFILE),
                    help="事業概要と会社URLのCSV")
    ap.add_argument("--sectors", default=str(SECTORS),
                    help="JPXの銘柄一覧（上場中かどうかの判定に使う）")
    ap.add_argument("--keep-delisted", action="store_true",
                    help="上場廃止とみられる銘柄も分析に含める")
    ap.add_argument("--no-financial-safety", action="store_true",
                    help="金融4業種（銀行・保険・証券・その他金融）の安全性を評価しない版を作る")
    ap.add_argument("--rate-env", choices=list(MB_RATE_ENV), default="中立",
                    help="マルチバガー判定の金利環境（利上げ局面=逆風は−10点）")
    ap.add_argument("--no-excel", action="store_true", help="Excelを作らない")
    args = ap.parse_args()

    src = Path(args.src)
    out = Path(args.out)
    if not src.exists():
        print(f"入力が見つかりません: {src}", file=sys.stderr)
        return 1
    out.mkdir(parents=True, exist_ok=True)

    d = pd.read_csv(src, encoding="utf-8-sig")
    d["コード"] = d["コード"].astype(str)
    src_date = str(d["株価日付"].dropna().max())
    print(f"読み込み: {len(d):,}銘柄 (株価日付 {src_date})")

    d = add_derived(d, date.today())
    d = mark_delisted(d, Path(args.sectors))
    gone = d[d["上場廃止"]]
    if len(gone):
        names = "、".join(f"{r.コード} {r.銘柄名}" for r in gone.itertuples())
        if args.keep_delisted:
            print(f"上場廃止とみられる{len(gone)}銘柄を残します: {names}")
        else:
            print(f"上場廃止とみられる{len(gone)}銘柄を除外: {names}")
            d = d[~d["上場廃止"]].copy()
    d = attach_beta(d, Path(args.beta))
    d = attach_new_high(d, Path(args.new_high))
    d = attach_nikkei225(d, NIKKEI225)
    d = attach_jukyu(d, JUKYU)
    d = attach_technical(d, Path(args.technical))
    d = attach_sbi_basic(d, Path(args.sectors))
    d = attach_bank_capital(d, Path(args.bank_capital))
    d = attach_regulated_ratio(d, Path(args.sec_capital), "自己資本規制比率(%)",
                               "自己資本規制比率(%)", "証券の自己資本規制比率")
    d = attach_regulated_ratio(d, Path(args.ins_solvency), "ソルベンシー・マージン比率(%)",
                               "ソルベンシー・マージン比率(%)", "保険のソルベンシー・マージン比率")
    d = attach_yearly(d, Path(args.by_year))
    d = attach_multibagger_yearly(d, Path(args.by_year))
    d = attach_dividend_quality(d, Path(args.by_year))
    d = attach_fscore(d, Path(args.by_year))
    d = attach_forecast_fscore(d, Path(args.by_year), Path(args.jq_summary), FINANCIAL_SECTORS)
    d = attach_keijo_yosou(d, Path(args.by_year), Path(args.jq_summary), YEARS_FOR_TREND)
    d = attach_forecast_extra(d, Path(args.jq_summary))
    d = add_op_growth_3y(d, Path(args.by_year))
    d = attach_profile(d, Path(args.profile))
    if args.min_cap > 0:
        before = len(d)
        d = d[d["時価総額(億円)"] >= args.min_cap]
        print(f"時価総額{args.min_cap:,.0f}億円以上に限定: {before:,} → {len(d):,}銘柄")

    d = add_shikiho(d, args.no_financial_safety)
    d = add_multibagger(d, args.rate_env)
    d = add_multibagger_paper(d, Path(args.by_year))
    screens = build_screens(d)
    by_sector = aggregate(d, "業種")
    by_market = aggregate(d, "市場")

    cols = [c for c in DISPLAY_COLS if c in d.columns]
    ranked = d.sort_values("評価平均", ascending=False, na_position="last")
    ranked[cols].to_csv(out / "スコア一覧.csv", index=False, encoding="utf-8-sig")
    by_sector.to_csv(out / "業種別集計.csv", encoding="utf-8-sig")
    by_market.to_csv(out / "市場別集計.csv", encoding="utf-8-sig")
    for name, spec in screens.items():
        spec["銘柄"][cols].to_csv(out / f"screen_{name}.csv", index=False, encoding="utf-8-sig")

    payload = dashboard_payload(d, screens, by_sector, by_market, src_date,
                                args.no_financial_safety)
    (out / "dashboard_data.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )

    if not args.no_excel:
        try:
            write_excel(out / "ファンダメンタル分析.xlsx", d, screens, by_sector, by_market)
        except Exception as e:  # openpyxl が無い等
            print(f"Excelの出力に失敗しました（CSVは出ています）: {e}", file=sys.stderr)

    dist = d["総合評価"].value_counts().sort_index()
    print("\n総合評価の分布")
    for k, n in dist.items():
        print(f"  評価{int(k)}  {n:>5,}銘柄")
    nan_n = int(d["総合評価"].isna().sum())
    if nan_n:
        print(f"  評価不能 {nan_n:>4,}銘柄（有効項目が{SHIKIHO_MIN_ITEMS}つ未満）")
    dv = d["業種内偏差値"].dropna()
    print(f"\n業種内偏差値: {len(dv):,}/{len(d):,}銘柄"
          f"（{MIN_SECTOR_FOR_DEVIATION}社未満の業種は算出せず）"
          f"／範囲 {dv.min():.1f}〜{dv.max():.1f}")

    vb = d["割安度の基準"].value_counts()
    print(f"\n割安度の基準: 予想PER {int(vb.get('予想PER', 0)):,}銘柄／"
          f"実績PER（会社予想なし） {int(vb.get('実績PER', 0)):,}銘柄／"
          f"PBR（PERが使えない赤字等） {int(vb.get('PBR', 0) + vb.get('PBR（予想赤字）', 0)):,}銘柄／"
          f"評価不能 {int(vb.get('評価不能', 0)):,}銘柄")

    print("\n項目別のカバー率")
    for item in SHIKIHO_ITEMS:
        got = int(d[f"{item}評価"].notna().sum())
        print(f"  {item:<6} {got:>5,}/{len(d):,} ({got / len(d) * 100:4.1f}%)")

    fs = d["Fスコア"].dropna()
    if len(fs):
        print(f"\nFスコアの分布（{len(fs):,}銘柄）")
        for k, n in fs.value_counts().sort_index(ascending=False).items():
            print(f"  {int(k)}点 {n:>5,}銘柄")
        skipped = d.loc[d["Fスコア"].isna() & (d["Fデータ品質"] != ""), "Fデータ品質"]
        top = skipped[skipped != "金融4業種のため対象外"].str.split("; ").str[0].value_counts().head(5)
        if len(top):
            print("  見送りの主な理由")
            for reason, n in top.items():
                print(f"    {reason[:34]:<34} {n:>5,}銘柄")

    yfs = d["予想Fスコア"].dropna()
    if len(yfs):
        print(f"\n予想Fスコアの分布（{len(yfs):,}銘柄）")
        for k, n in yfs.value_counts().sort_index(ascending=False).items():
            print(f"  {int(k)}点 {n:>5,}銘柄")

    print("\nスクリーニング結果")
    for name, spec in screens.items():
        print(f"  {name:<16} {len(spec['銘柄']):>5,}銘柄")
    print(f"\n出力先: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
