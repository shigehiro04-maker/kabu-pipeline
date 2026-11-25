#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""銀行のバーゼル自己資本比率を集めて bank_capital.csv を作る

会計上の自己資本比率（純資産÷総資産）は、銀行では5%前後にしかならず、
事業会社（中央値55%）と同じ物差しで測ると財務健全性が不当に低く出ます。
銀行の健全性はバーゼル規制上の自己資本比率で見るべきなので、その値をここで集めます。

出どころ:
  1. 全国銀行協会「銀行別諸比率表」   都銀・信託・地銀・第二地銀 111行の自己資本比率
       国際統一基準行 → 普通株式等Tier1比率
       国内基準行     → コア資本比率
       連結・単体の両方が載っており、連結財務諸表を作っていない14行は連結が「－」
  2. 金融庁「中小・地域金融機関情報一覧」  地域銀行の不良債権比率
  3. MANUAL（下記）                     1に載らないゆうちょ・楽天・セブンを手入力

年に一度しか更新されないデータなので、run_fundamentals.sh から月1回だけ
`--download` が呼ばれます。URLは年度が変わると数字が変わりますが、
索引ページから最新年度のリンクを自分で探すので、手作業は要りません。

使い方:
    ./.venv/bin/python fetch_bank_capital.py --download   # 最新年度を探して取得し、CSVを作る
    ./.venv/bin/python fetch_bank_capital.py              # 手元のファイルから作り直すだけ
    ./.venv/bin/python fetch_bank_capital.py --inspect    # 元ファイルの構造を確認する

出力: fundamentals/bank_capital.csv
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen

BASE = Path(__file__).resolve().parent
DL = BASE / "fundamentals" / "basel"
OUT = BASE / "fundamentals" / "bank_capital.csv"

# 索引ページ。ここから最新年度のExcelを自分で探す。
ZEN_INDEX = "https://www.zenginkyo.or.jp/stats/year2-02/"
FSA_INDEX = "https://www.fsa.go.jp/policy/chusho/shihyou.html"

# 索引の作りが変わって見つけられなかったときの保険。
# ここが使われたらログに警告が出るので、そのときはURLを更新してください。
FALLBACK = {
    "zenginkyo_hiritsu.xlsx": (
        "https://www.zenginkyo.or.jp/fileadmin/res/abstract/stats/year2_02/"
        "account2025_terminal/hiritsu37.xlsx", 2025),
    "fsa_chiiki.xlsx": (
        "https://www.fsa.go.jp/policy/chusho/shihyou/zenkoku/2025-1.xlsx", 2025),
}

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")

ZEN_SHEET = "諸比率表（決算期）"
# 見つけた年度から基準日を決める。
#   全国銀行協会 account2025-terminal → 2025年度決算 → 2026-03-31
#   金融庁       zenkoku/2025-1.xlsx  → 令和7年3月末  → 2025-03-31
BASIS = DL / "_basis.txt"        # 取得した年度を覚えておく

# 上場コード → 全国銀行協会の表に載っている銀行名。
# 上場しているのは持株会社なのに、表は銀行単体の名前なので突き合わせが要る。
# 持株会社が複数の銀行を抱える場合は、貸出金がいちばん大きい銀行を代表として使う
# （FG連結の比率とは多少ずれるため、出所列にどの銀行を使ったか残している）。
BANK_MAP = {
    "8306": "三菱ＵＦＪ", "8316": "三井住友", "8411": "みずほ",
    "8308": "りそな", "8309": "三井住友信託",
    "7186": "横浜", "8331": "千葉", "5831": "静岡", "7167": "常陽",
    "8354": "福岡", "5844": "京都", "8303": "ＳＢＩ新生", "8359": "八十二長野",
    "5830": "伊予", "8334": "群馬", "8377": "北陸", "8341": "七十七",
    "7337": "広島", "7189": "西日本シティ", "7327": "第四北越", "7180": "肥後",
    "8418": "山口", "8366": "滋賀", "5832": "中国", "8368": "百五",
    "8358": "スルガ", "8524": "北洋", "7389": "あいち", "8304": "あおぞら",
    "7380": "十六", "7173": "きらぼし", "8381": "山陰合同", "8388": "阿波",
    "8386": "百十四", "8522": "名古屋", "8544": "京葉", "8361": "大垣共立",
    "8370": "紀陽", "8367": "南都", "8714": "池田泉州", "7381": "北國",
    "8336": "武蔵野", "8346": "東邦", "7322": "三十三", "8360": "山梨中央",
    "8392": "大分", "8600": "徳島大正", "8393": "宮崎", "7184": "富山第一",
    "8345": "岩手", "7350": "沖縄", "8362": "福井", "8337": "千葉興業",
    "8343": "秋田", "8387": "四国", "8344": "山形", "8399": "琉球",
    "7384": "青森みちのく", "8541": "愛媛", "8550": "栃木", "8395": "佐賀",
    "8551": "北日本", "8338": "筑波", "8558": "東和", "8713": "荘内",
    "8364": "清水", "8537": "大光", "8542": "トマト", "8383": "鳥取",
    "8349": "東北", "7161": "仙台", "8563": "大東", "8562": "福島",
    "8365": "富山", "8416": "高知", "7150": "島根",
}

# 複数の銀行を持つ持株会社。出所にその旨を残すためのメモ
MULTI_BANK = {
    "7167": "常陽銀行と足利銀行", "8354": "福岡・十八親和・熊本銀行など",
    "8377": "北陸銀行と北海道銀行", "7180": "肥後銀行と鹿児島銀行",
    "8418": "山口・もみじ・北九州銀行", "7189": "西日本シティ銀行と長崎銀行",
    "8600": "徳島大正銀行と香川銀行", "8713": "荘内銀行と北都銀行",
    "7161": "仙台銀行ときらやか銀行", "8308": "りそな銀行と埼玉りそな銀行など",
}

# 全国銀行協会の表に載らない銀行。各社の開示から手入力。
# 年に一度、決算発表後に更新してください（リンクは出所の欄）。
MANUAL = [
    # コード, 銘柄名, 適用基準, 自己資本比率(%), 連結/単体, 基準日, 出所
    ("7182", "ゆうちょ銀行", "国内基準", 14.93, "連結", "2026-03-31",
     "自己資本の構成に関する開示事項 https://www.jp-bank.japanpost.jp/ir/financial/ir_fnc_jikoshihon.html"),
    ("5838", "楽天銀行", "国内基準", 10.70, "連結", "2026-03-31",
     "2026年3月期IRプレゼンテーション https://www.rakuten-bank.co.jp/corp/investors/financial/data.html"),
    ("8410", "セブン銀行", "国内基準", 29.91, "連結", "2026-03-31",
     "統合報告書2026 資料編 https://www.sevenbank.co.jp/ir/library/disclosure/"),
]


# ---------------------------------------------------------------- 取得

def get(url: str, timeout: int = 90) -> bytes:
    with urlopen(Request(url, headers={"User-Agent": UA}), timeout=timeout) as r:
        return r.read()


def discover_zenginkyo() -> tuple:
    """全国銀行協会の索引から、最新年度の「銀行別諸比率表」を探す。

    索引 /stats/year2-02/ に account2025-terminal のような年度ページが並ぶので、
    いちばん新しい年を選び、その中から hiritsu*.xlsx を拾う。
    ファイル名の数字（hiritsu37）は毎年増えるため、名前を決め打ちしない。"""
    html = get(ZEN_INDEX, 40).decode("utf-8", "replace")
    years = {int(y): m for m, y in re.findall(
        r'href="([^"]*?account(\d{4})-terminal/?)"', html)}
    if not years:
        raise LookupError("年度ページのリンクが索引に見つかりません")
    year = max(years)
    page = get(urljoin(ZEN_INDEX, years[year]), 40).decode("utf-8", "replace")
    m = re.search(r'href="([^"]*?hiritsu[^"]*\.xlsx)"', page)
    if not m:
        raise LookupError(f"{year}年度のページに銀行別諸比率表が見つかりません")
    return urljoin(ZEN_INDEX, m.group(1)), year


def discover_fsa() -> tuple:
    """金融庁の索引から、最新年の地域銀行ファイル（zenkoku/YYYY-1.xlsx）を探す"""
    html = get(FSA_INDEX, 40).decode("utf-8", "replace")
    years = {int(y): m for m, y in re.findall(
        r'href="([^"]*?/zenkoku/(\d{4})-1\.xlsx)"', html)}
    if not years:
        raise LookupError("地域銀行のExcelリンクが索引に見つかりません")
    year = max(years)
    return urljoin(FSA_INDEX, years[year]), year


def download() -> int:
    """最新年度を探してダウンロードする。年度は _basis.txt に控える。"""
    DL.mkdir(parents=True, exist_ok=True)
    plan = [("zenginkyo_hiritsu.xlsx", discover_zenginkyo),
            ("fsa_chiiki.xlsx", discover_fsa)]
    basis, ng = {}, 0
    for name, finder in plan:
        try:
            url, year = finder()
            print(f"  最新年度を発見: {name} → {year}年")
        except Exception as e:
            url, year = FALLBACK[name]
            print(f"  ※ {name} の索引を読めませんでした（{e}）。"
                  f"控えのURLを使います。索引の作りが変わった可能性があります。", file=sys.stderr)
        try:
            body = get(url)
            if len(body) < 10_000 or body[:2] != b"PK":
                raise ValueError(f"Excelではない応答（{len(body):,}バイト）")
            (DL / name).write_bytes(body)
            basis[name] = year
            print(f"  OK   {name}  {len(body):,}バイト")
        except Exception as e:
            ng += 1
            print(f"  NG   {name}  {e}\n       {url}", file=sys.stderr)

    if basis:
        old = read_basis()
        old.update(basis)
        BASIS.write_text("\n".join(f"{k}\t{v}" for k, v in sorted(old.items())),
                         encoding="utf-8")
    if ng:
        print("\n取得できなかったファイルは、上のURLをブラウザで開いて "
              f"{DL} に手で置いてください。手元に前回のファイルが残っていれば"
              "そのまま使われるので、日次の処理は止まりません。", file=sys.stderr)
    return ng


def read_basis() -> dict:
    """前回どの年度のファイルを取ったかを読む"""
    if not BASIS.exists():
        return {}
    out = {}
    for line in BASIS.read_text(encoding="utf-8").splitlines():
        k, _, v = line.partition("\t")
        if v.strip().isdigit():
            out[k] = int(v)
    return out


def inspect() -> int:
    """元Excelの構造を書き出す。年度が変わって列がずれたときの調査用。"""
    import openpyxl
    files = sorted(DL.glob("*.xlsx"))
    if not files:
        print(f"{DL} にExcelがありません。先に --download を。", file=sys.stderr)
        return 1
    for f in files:
        print("=" * 70)
        print(f"FILE: {f.name}  ({f.stat().st_size:,}バイト)")
        wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
        for sn in wb.sheetnames:
            ws = wb[sn]
            print("-" * 70)
            print(f"[{sn}]  {ws.max_row} 行 x {ws.max_column} 列")
            for i, row in enumerate(ws.iter_rows(max_row=12, values_only=True), 1):
                cells = ["" if c is None else str(c).replace("\n", " ")[:22] for c in row[:20]]
                print(f"  {i:>2}| " + " | ".join(cells).rstrip(" |"))
        wb.close()
    return 0


# ---------------------------------------------------------------- 読み取り

def num(v):
    """'－' や '-' や空欄を None にして float にする"""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("△", "-")
    if s in ("", "-", "－", "―", "ー"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def read_zenginkyo(path: Path) -> dict:
    """銀行名 → {適用基準, 連結, 単体}

    列の位置は「銀行別諸比率表」の見出しから:
      B=銀行名  M=適用基準(国際/国内)  P=連結  R=単体
    """
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[ZEN_SHEET] if ZEN_SHEET in wb.sheetnames else wb[wb.sheetnames[0]]
    out = {}
    for row in ws.iter_rows(min_row=7, values_only=True):
        name, std = row[1], row[12]
        if not name or std not in ("国際", "国内"):
            continue          # 業態平均の行や注記の行を飛ばす
        out[str(name).strip()] = {
            "適用基準": "国際統一基準" if std == "国際" else "国内基準",
            "連結": num(row[15]),
            "単体": num(row[17]),
        }
    wb.close()
    return out


def read_fsa(path: Path) -> dict:
    """銀行名（「銀行」を落としたもの）→ 不良債権比率(%)"""
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    out = {}
    for row in ws.iter_rows(min_row=3, values_only=True):
        name = row[4]
        if not name:
            continue
        key = str(name).strip().replace("株式会社", "").replace("銀行", "")
        v = num(row[13])
        if v is not None:
            out[key] = v
    wb.close()
    return out


# ---------------------------------------------------------------- 組み立て

def build() -> int:
    zen_path, fsa_path = DL / "zenginkyo_hiritsu.xlsx", DL / "fsa_chiiki.xlsx"
    if not zen_path.exists():
        print(f"{zen_path} がありません。先に --download を実行してください。", file=sys.stderr)
        return 1

    basis = read_basis()
    zen_year = basis.get("zenginkyo_hiritsu.xlsx", FALLBACK["zenginkyo_hiritsu.xlsx"][1])
    fsa_year = basis.get("fsa_chiiki.xlsx", FALLBACK["fsa_chiiki.xlsx"][1])
    zen_date = f"{zen_year + 1}-03-31"   # 2025年度決算 → 2026年3月末
    fsa_date = f"{fsa_year}-03-31"       # 令和7年3月末 → 2025年3月末

    zen = read_zenginkyo(zen_path)
    print(f"銀行別諸比率表({zen_date}時点): {len(zen)}行")
    npl = read_fsa(fsa_path) if fsa_path.exists() else {}
    print(f"金融庁の不良債権比率({fsa_date}時点): {len(npl)}行")

    rows, missing = [], []
    for code, bank in sorted(BANK_MAP.items()):
        z = zen.get(bank)
        if not z:
            missing.append(f"{code}（{bank}）")
            continue
        # 連結が基本。連結財務諸表を作っていない14行は単体で代用する。
        ratio, scope = (z["連結"], "連結") if z["連結"] is not None else (z["単体"], "単体")
        if ratio is None:
            missing.append(f"{code}（{bank}）")
            continue
        src = f"全国銀行協会 銀行別諸比率表／{bank}銀行（{scope}）"
        if code in MULTI_BANK:
            src += f"　※持株会社は{MULTI_BANK[code]}を傘下に持つため代表行の値"
        rows.append({
            "コード": code, "適用基準": z["適用基準"], "自己資本比率(%)": ratio,
            "連結単体": scope, "不良債権比率(%)": npl.get(bank), "基準日": zen_date,
            "不良債権比率基準日": fsa_date if npl.get(bank) is not None else "",
            "出所": src,
        })

    have = {r["コード"] for r in rows}
    for code, name, std, ratio, scope, day, src in MANUAL:
        if code in have:
            continue
        rows.append({
            "コード": code, "適用基準": std, "自己資本比率(%)": ratio, "連結単体": scope,
            "不良債権比率(%)": None, "基準日": day, "不良債権比率基準日": "", "出所": src,
        })
        missing = [m for m in missing if not m.startswith(code)]

    rows.sort(key=lambda r: r["コード"])
    cols = ["コード", "適用基準", "自己資本比率(%)", "連結単体",
            "不良債権比率(%)", "基準日", "不良債権比率基準日", "出所"]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: ("" if r[c] is None else r[c]) for c in cols})

    n_npl = sum(1 for r in rows if r["不良債権比率(%)"] is not None)
    print(f"\n{len(rows)}行を書き出しました → {OUT}")
    print(f"  うち不良債権比率あり: {n_npl}行")
    print(f"  国際統一基準（普通株式等Tier1比率）: "
          f"{sum(1 for r in rows if r['適用基準'] == '国際統一基準')}行")
    print(f"  国内基準（コア資本比率）: "
          f"{sum(1 for r in rows if r['適用基準'] == '国内基準')}行")
    if missing:
        print(f"\n対応先が見つからなかった銘柄: {'、'.join(missing)}\n"
              "  BANK_MAP か MANUAL に追記してください。", file=sys.stderr)

    # 手入力の3行だけは自動更新できない。他行より古くなったら知らせる。
    stale = [(n, d) for _, n, _, _, _, d, _ in MANUAL if d < zen_date]
    if stale:
        print(f"\n※ 手入力の {'、'.join(f'{n}({d})' for n, d in stale)} が、"
              f"他行の基準日 {zen_date} より古いままです。\n"
              "  各社の開示（bank_capital.csv の出所列にURL）を見て、"
              "  fetch_bank_capital.py の MANUAL を更新してください。", file=sys.stderr)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="銀行のバーゼル自己資本比率を集める")
    ap.add_argument("--download", action="store_true",
                    help="最新年度を索引から探してダウンロードする")
    ap.add_argument("--inspect", action="store_true", help="元ファイルの構造を書き出す")
    args = ap.parse_args()

    if args.inspect:
        return inspect()
    if args.download:
        download()   # 取得に失敗しても、手元に残っているファイルからCSVは作り直す
    return build()


if __name__ == "__main__":
    raise SystemExit(main())
