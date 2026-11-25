"""需給分析：JPX・日証金のファイルを読み取る関数（通信なし）。

  parse_margin_pdf      銘柄別信用取引残高（JPX、日々・全銘柄・PDF）→ 1銘柄1行
  parse_daily_flags     日々公表銘柄等信用取引残高（JPX、Excel）→ 規制・日々公表などの印
  parse_taisyaku        日証金 貸借取引残高 zandaka.csv → 融資・貸株残高と回転日数
  parse_shina           日証金 品貸料率 shina.csv → 逆日歩
  parse_short_positions 空売り残高に関する情報（JPX、残高割合0.5%以上の報告、xls）
  parse_short_sector    空売り集計（JPX、業種別・日次PDF）→ 業種別の空売り比率
  parse_investor_new / parse_investor_old  投資部門別 株式売買状況（JPX、週次）
"""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd


def _num(s):
    """'1,234' '▲ 1,234' '-' '' → 数値（▲は負）"""
    if s is None:
        return np.nan
    if isinstance(s, (int, float, np.integer, np.floating)):
        return float(s)
    t = str(s).replace(",", "").replace("\n", "").strip()
    if t in ("", "-", "*", "－", "*****"):
        return np.nan
    neg = t.startswith("▲") or t.startswith("△")
    t = t.lstrip("▲△ ").strip()
    if t.endswith("%"):
        try:
            v = float(t[:-1]) / 100
        except ValueError:
            return np.nan
    else:
        try:
            v = float(t)
        except ValueError:
            return np.nan
    return -v if neg else v


def _code(c) -> str:
    """JPXの5桁コード（13010・137A0）→ 4桁（1301・137A）"""
    c = str(c).strip()
    if len(c) == 5 and c.endswith("0"):
        c = c[:4]
    return c


# ------------------------------------------------------------ 銘柄別信用取引残高（PDF）

MARGIN_COLS = ["売残", "売残前日比", "売残上場比", "買残", "買残前日比", "買残上場比",
               "売残一般", "売残一般前日比", "売残制度", "売残制度前日比",
               "買残一般", "買残一般前日比", "買残制度", "買残制度前日比"]
KIND = {"貸": "貸借", "制": "制度信用", "他": "その他"}


def _ascii(s) -> str:
    return re.sub(r"[^0-9A-Z]", "", str(s or ""))


def parse_margin_pdf(path: Path) -> tuple[pd.DataFrame, pd.DataFrame, date]:
    """銘柄別信用取引残高のPDFを読む。

    銘柄名が長い行（ETFなど）は文字が隣の列に食い込むので、コードは「コード列のASCII英数字」で取る。銘柄名・市場は株価CSVの銘柄一覧で付け直す。

    戻り値: (銘柄別, 小計, 申込日)
      銘柄別  コード・区分（貸借/制度信用/その他）・株数14列・売残金額・買残金額（約定金額）
      小計    区分（貸借銘柄／プライム小計…／総合計）ごとの売残・買残（株数・金額）"""
    import pdfplumber
    rows, subs, asof = [], [], None
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            if asof is None:
                m = re.search(r"(\d{4})/(\d{1,2})/(\d{1,2})申込み現在", page.extract_text() or "")
                if m:
                    asof = date(int(m[1]), int(m[2]), int(m[3]))
            for tb in page.extract_tables():
                for r in tb:
                    if not r or len(r) < 20:
                        continue
                    unit = (r[5] or "").replace("\n", "")
                    kind = "株数" if "株数" in unit else ("金額" if "金額" in unit else None)
                    if kind is None:
                        continue
                    head = (r[0] or "").replace("\n", " ").strip()
                    if r[1] is None and r[3] is None and ("銘柄" in head or "total" in head.lower()
                                                          or "sub-total" in head.lower()):
                        subs.append((kind, head, r))
                        continue
                    code = _ascii(r[3])
                    if not re.fullmatch(r"[0-9A-Z]{4}0", code):
                        code = None   # 読めない行は捨てる（ログに件数を出す）
                    if code:
                        rows.append((kind, code, r))
    recs = {}
    for kind, code, r in rows:
        c = _code(code)
        rec = recs.setdefault(c, {"コード": c})
        if kind == "株数":
            k = next((KIND[ch] for ch in (r[2] or "") if ch in KIND), "")
            rec["区分"] = k
            rec.update(dict(zip(MARGIN_COLS, [_num(x) for x in r[6:20]])))
        else:
            rec["売残金額"] = _num(r[6])
            rec["買残金額"] = _num(r[9])
    return pd.DataFrame(recs.values()), _subtotals(subs), asof


def _subtotals(subs) -> pd.DataFrame:
    """小計行。株数行のラベル（「貸借銘柄 2671 銘柄」「プライム 小計 1475 銘柄」）に、
    直前の大区分（貸借銘柄・制度信用銘柄・その他銘柄）を前につけて区別する。"""
    out, top, cur = [], "", None
    for kind, head, r in subs:
        if kind == "株数":
            m = re.match(r"(.+?)\s*(\d+)\s*銘柄", head)
            if not m:
                cur = None
                continue
            lab = m[1].replace(" ", "")
            if "小計" not in lab:
                top = lab
                name = lab
            else:
                name = f"{top}/{lab.replace('小計', '')}"
            cur = {"区分": name, "銘柄数": int(m[2]), "売残": _num(r[6]), "売残前日比": _num(r[7]),
                   "買残": _num(r[9]), "買残前日比": _num(r[10])}
            out.append(cur)
        elif cur is not None:
            cur["売残金額"] = _num(r[6])
            cur["買残金額"] = _num(r[9])
    return pd.DataFrame(out)


# ------------------------------------------------------------ 日々公表銘柄等（規制・注意の印）

def parse_daily_flags(path: Path) -> pd.DataFrame:
    """日々公表銘柄等信用取引残高（Excel）から、銘柄ごとの印（規・日・監・株・喚・○）だけを取る。
    印は銘柄名の前に付いている。コード列は5桁。"""
    x = pd.read_excel(path, header=None, dtype=str)
    out = []
    for r in x.itertuples(index=False):
        vals = [v for v in r if isinstance(v, str)]
        code = next((v for v in vals if re.fullmatch(r"[0-9A-Z]{4}0", v.strip())), None)
        if not code:
            continue
        txt = " ".join(vals)
        marks = "".join(ch for ch in "規日監株喚○" if ch in txt.split(code)[0])
        out.append({"コード": _code(code), "規制等": marks})
    d = pd.DataFrame(out, columns=["コード", "規制等"])
    return d.drop_duplicates("コード")


# ------------------------------------------------------------ 日証金

def _read_csv_jp(path: Path, **kw) -> pd.DataFrame:
    for enc in ("cp932", "utf-8-sig"):
        try:
            return pd.read_csv(path, encoding=enc, **kw)
        except UnicodeDecodeError:
            continue
    return pd.read_csv(path, encoding="cp932", encoding_errors="replace", **kw)


def parse_taisyaku(path: Path) -> pd.DataFrame:
    """日証金 zandaka.csv（貸借取引残高、前営業日申込分）→ 東証分の1銘柄1行"""
    z = _read_csv_jp(path, dtype=str)
    z = z[z["取引所区分名"].astype(str).str.contains("東証")]
    keep = {"申込日": "申込日", "銘柄コード": "コード", "速報／確報": "速報確報",
            "融資新規株数": "融資新規", "融資返済株数": "融資返済", "融資残高株数": "融資残",
            "貸株新規株数": "貸株新規", "貸株返済株数": "貸株返済", "貸株残高株数": "貸株残",
            "差引残高株数": "差引残", "貸株・残高回転日数": "貸株回転日数", "融資・残高回転日数": "融資回転日数"}
    z = z[list(keep)].rename(columns=keep)
    for c in z.columns:
        if c not in ("申込日", "コード", "速報確報"):
            z[c] = pd.to_numeric(z[c], errors="coerce")
    z["コード"] = z["コード"].str.strip()
    z["申込日"] = pd.to_datetime(z["申込日"]).dt.date
    return z.drop_duplicates("コード", keep="last")


def parse_shina(path: Path) -> pd.DataFrame:
    """日証金 shina.csv（品貸料率＝逆日歩）→ 東証分。当日品貸料率は1株あたり円（日数を掛けた値）"""
    s = _read_csv_jp(path, header=None, dtype=str, skiprows=4)
    s = s.iloc[:, :16]
    s.columns = ["申込日", "決済日", "コード", "銘柄名", "取引所", "決算事由", "決算等", "貸借値段",
                 "貸株超過株数", "最高料率", "逆日歩", "品貸日数", "前日逆日歩", "備考", "制限", "応札倍率ランク"]
    s = s[s["取引所"].astype(str).str.contains("東証")]
    for c in ("貸借値段", "貸株超過株数", "最高料率", "逆日歩", "品貸日数", "前日逆日歩"):
        s[c] = pd.to_numeric(s[c], errors="coerce")
    s["逆日歩(%)"] = s["逆日歩"] / s["品貸日数"].where(s["品貸日数"] > 0) / s["貸借値段"] * 100
    return s[["コード", "貸借値段", "貸株超過株数", "逆日歩", "品貸日数", "逆日歩(%)", "制限"]] \
        .drop_duplicates("コード", keep="last")


# ------------------------------------------------------------ 空売り残高（0.5%以上の報告）

SP_COLS = ["計算日", "コード", "銘柄名", "銘柄名英", "報告者", "報告者住所", "委託者", "委託者住所",
           "ファンド", "残高割合", "残高数量", "売買単位数", "前回計算日", "前回残高割合", "備考"]


def parse_short_positions(path: Path) -> pd.DataFrame:
    x = pd.read_excel(path, header=None)
    # 見出し「計算年月日」の行を探し、その2行下からがデータ
    hdr = next(i for i in range(min(30, len(x)))
               if any(isinstance(v, str) and "計算年月日" in v for v in x.iloc[i].tolist()))
    c0 = next(j for j, v in enumerate(x.iloc[hdr].tolist()) if isinstance(v, str) and "計算年月日" in v)
    d = x.iloc[hdr + 2:, c0:c0 + len(SP_COLS)].copy()
    d.columns = SP_COLS[:d.shape[1]]
    d = d[d["コード"].notna()]
    d["コード"] = d["コード"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    d = d[d["コード"].str.fullmatch(r"[0-9A-Z]{4}")]
    for c in ("計算日", "前回計算日"):
        d[c] = pd.to_datetime(d[c], errors="coerce")
    for c in ("残高割合", "残高数量", "前回残高割合"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d["報告者"] = d["報告者"].astype(str).str.strip()
    d["ファンド"] = d["ファンド"].fillna("").astype(str).str.strip()
    d["委託者"] = d["委託者"].fillna("").astype(str).str.strip()
    return d[["計算日", "コード", "報告者", "委託者", "ファンド", "残高割合", "残高数量",
              "前回計算日", "前回残高割合"]]


# ------------------------------------------------------------ 空売り集計（日次・業種別PDF）

_SS = re.compile(r"^(\S+?)\s+([\d,]+)\s+([\d.]+)%\s+([\d,]+)\s+([\d.]+)%\s+([\d,]+)\s+([\d.]+)%\s+([\d,]+)\s*$")


def parse_short_sector(path: Path) -> tuple[date | None, pd.DataFrame]:
    """業種別の空売り集計PDF → (売買日, 業種・実注文・空売り(規制あり)・空売り(規制なし)・合計[百万円]・空売り比率)"""
    import pdfplumber
    with pdfplumber.open(str(path)) as pdf:
        text = "\n".join(p.extract_text() or "" for p in pdf.pages)
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text)
    day = date(int(m[1]), int(m[2]), int(m[3])) if m else None
    out = []
    for line in text.splitlines():
        line = line.strip()
        mm = _SS.match(line)
        if mm and not re.match(r"\d{4}年", mm[1]):
            a, b, c, dd = (_num(mm[i]) for i in (2, 4, 6, 8))
            out.append({"業種": mm[1], "実注文": a, "空売り規制あり": b, "空売り規制なし": c, "合計": dd,
                        "空売り比率(%)": (b + c) / dd * 100 if dd else np.nan})
    return day, pd.DataFrame(out)


def parse_short_market(path: Path) -> tuple[date | None, dict]:
    """空売り集計（日次）の本体PDF → 市場全体の空売り比率"""
    import pdfplumber
    with pdfplumber.open(str(path)) as pdf:
        text = "\n".join(p.extract_text() or "" for p in pdf.pages)
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日\s+([\d,]+)\s+([\d.]+)%\s+([\d,]+)\s+([\d.]+)%\s+([\d,]+)\s+([\d.]+)%\s+([\d,]+)", text)
    if not m:
        return None, {}
    a, b, c, d = _num(m[4]), _num(m[6]), _num(m[8]), _num(m[10])
    return date(int(m[1]), int(m[2]), int(m[3])), {
        "実注文": a, "空売り規制あり": b, "空売り規制なし": c, "合計": d,
        "空売り比率(%)": (b + c) / d * 100, "規制なし比率(%)": c / d * 100}


# ------------------------------------------------------------ 投資部門別（週次）

INV_KEYS = ["自己", "個人", "個人現金", "個人信用", "海外投資家", "証券会社", "投資信託", "事業法人",
            "その他法人等", "生保・損保", "都銀・地銀等", "信託銀行", "その他金融機関"]
MARKET_SHEETS = {"プライム": ("Prime", "プライム"), "スタンダード": ("Standard", "スタンダード"),
                 "グロース": ("Growth", "グロース"), "東名二市場": ("Nagoya", "二市場")}


def parse_investor_new(path: Path, week_end: date) -> pd.DataFrame:
    """2026年9月からの新様式（stock_1_w_YYYYMMDD_YYYYMMDD.xlsx）。金額の差引（買い−売り、千円）を取る。
    列は4本ずつ（売・買・差引・合計）。"""
    x = pd.read_excel(path, header=None)
    blk = {"自己現金": 3, "自己信用": 7, "個人現金": 11, "個人信用": 15, "海外法人": 19, "海外個人": 23,
           "証券会社": 27, "投資信託": 31, "事業法人": 35, "その他法人等": 39, "生保・損保": 43,
           "都銀・地銀等": 47, "信託銀行": 51, "その他金融機関": 55}
    # 見出しが想定どおりか確かめる（様式が変わったら止める）
    h = " ".join(str(v) for v in x.iloc[2:6].to_numpy().ravel() if isinstance(v, str))
    for w in ("個人", "海外投資家", "投資信託", "信託銀行"):
        if w not in h:
            raise ValueError(f"投資部門別の新様式の見出しが想定とちがいます（{w} が無い）: {path.name}")
    out, mk = [], None
    for i in range(6, len(x)):
        r = x.iloc[i].tolist()
        if isinstance(r[1], str) and r[1].strip():
            mk = r[1]
        if not (isinstance(r[2], str) and "金額" in r[2]):
            continue
        name = next((k for k, (en, ja) in MARKET_SHEETS.items() if ja in str(mk)), None)
        if name is None:
            continue
        g = lambda k, o: _num(r[blk[k] + o])     # o: 0売 1買 2差引 3合計
        rec = {"週末": week_end, "市場": name}
        rec["自己"] = g("自己現金", 2) + g("自己信用", 2)
        rec["個人現金"], rec["個人信用"] = g("個人現金", 2), g("個人信用", 2)
        rec["個人"] = rec["個人現金"] + rec["個人信用"]
        rec["海外投資家"] = g("海外法人", 2) + g("海外個人", 2)
        for k in ("証券会社", "投資信託", "事業法人", "その他法人等", "生保・損保", "都銀・地銀等",
                  "信託銀行", "その他金融機関"):
            rec[k] = g(k, 2)
        rec["個人売"] = g("個人現金", 0) + g("個人信用", 0)
        rec["個人買"] = g("個人現金", 1) + g("個人信用", 1)
        rec["海外売"] = g("海外法人", 0) + g("海外個人", 0)
        rec["海外買"] = g("海外法人", 1) + g("海外個人", 1)
        out.append(rec)
    return pd.DataFrame(out)


def parse_investor_old(path: Path) -> pd.DataFrame:
    """旧様式（stock_val_1_YYMMNN.xls、市場ごとのシート、千円）。当週の列（8・9・10列目）を使う。"""
    book = pd.read_excel(path, header=None, sheet_name=None)
    label = {"自己計": "自己", "個　人": "個人", "個人": "個人", "海外投資家": "海外投資家",
             "証券会社": "証券会社", "投資信託": "投資信託", "事業法人": "事業法人",
             "その他法人等": "その他法人等", "生保・損保": "生保・損保", "都銀・地銀等": "都銀・地銀等",
             "信託銀行": "信託銀行", "その他金融機関": "その他金融機関"}
    out = []
    for sheet, x in book.items():
        name = next((k for k, (en, ja) in MARKET_SHEETS.items() if en in sheet), None)
        if name is None:
            continue
        title = " ".join(str(v) for v in x.iloc[0:5, 0].tolist() if isinstance(v, str))
        m = re.search(r"(\d{4})年(\d{1,2})月第\d週.*?-\s*(\d{1,2})/(\d{1,2})", title)
        if not m:
            continue
        y, mo, em, ed = int(m[1]), int(m[2]), int(m[3]), int(m[4])
        if em < mo - 6:          # 12月第5週が1月にかかる場合
            y += 1
        rec = {"週末": date(y, em, ed), "市場": name}
        cur = None
        sell = {}
        for i in range(len(x)):
            a, b = x.iat[i, 0], x.iat[i, 1]
            if isinstance(a, str) and a.strip() in label:
                cur = label[a.strip()]
            if cur and isinstance(b, str):
                v = _num(x.iat[i, 8])
                if b.strip() == "売り":
                    sell[cur] = v
                elif b.strip() == "買い":
                    rec[cur] = v - sell.get(cur, np.nan)
                    if cur == "個人":
                        rec["個人売"], rec["個人買"] = sell.get(cur), v
                    if cur == "海外投資家":
                        rec["海外売"], rec["海外買"] = sell.get(cur), v
                    cur = None
            if isinstance(a, str) and a.startswith("個人現金"):
                rec["個人現金"] = _num(x.iat[i, 4]) - _num(x.iat[i, 2])
            if isinstance(a, str) and a.startswith("個人信用"):
                rec["個人信用"] = _num(x.iat[i, 4]) - _num(x.iat[i, 2])
        out.append(rec)
    return pd.DataFrame(out)
