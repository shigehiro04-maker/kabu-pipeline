#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_usdjpy.py の解析部分を、実際のサイトと同じ形のダミー応答で検証する。
通信はしない。 python3 test_update_usdjpy.py で実行。
"""
import io, json, re, sys, tempfile, zipfile, shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
# 作業ファイルは一時フォルダに作る（利用者のフォルダに何も残さない）
TMP = Path(tempfile.mkdtemp(prefix="usdjpy_test_"))
import update_usdjpy as U
import fetch_data as fd

OK, NG = [], []
def check(name, cond, detail=""):
    (OK if cond else NG).append(name)
    print(("  OK   " if cond else "  NG   ") + name + (f"  {detail}" if detail else ""))

# ---------------------------------------------------------------- Yahoo
print("[Yahoo 1時間足 → 日次四本値]")
base = int(datetime(2026, 9, 14, 0, tzinfo=timezone.utc).timestamp())
ts, op, hi, lo, cl = [], [], [], [], []
def day(d, n, o, h, l, c):
    st = int(datetime(2026, 9, d, 0, tzinfo=timezone.utc).timestamp())
    for k in range(n):
        ts.append(st + k * 3600)
        op.append(o if k == 0 else (o + h) / 2); hi.append(h if k == 1 else o)
        lo.append(l if k == 2 else o); cl.append(c if k == n - 1 else o)
day(11, 21, 154.465, 154.607, 153.234, 153.554)   # 金曜
day(12,  8, 153.6, 153.7, 153.5, 153.6)           # 土曜 → 除外されるべき
day(13,  1, 153.675, 153.736, 153.392, 153.411)   # 日曜 → 除外
day(14, 23, 153.418, 155.000, 153.368, 154.422)   # 月曜
day(15,  2, 154.414, 154.534, 154.397, 154.524)   # 火曜・途中 → 本数不足で除外
fake = {"chart": {"result": [{"timestamp": ts,
        "indicators": {"quote": [{"open": op, "high": hi, "low": lo, "close": cl}]},
        "meta": {"regularMarketPrice": 154.524,
                 "regularMarketTime": int(datetime(2026, 9, 15, 0, 16, tzinfo=timezone.utc).timestamp())}}]}}
U.fd.http_get = lambda *a, **k: json.dumps(fake).encode()
df, spot, asof = U.fetch_yahoo()
check("平日だけ・本数の足りる日だけ残る", list(df["date"]) == ["2026-09-11", "2026-09-14"], list(df["date"]))
check("始値・終値が正しい", (df.iloc[1]["open"], df.iloc[1]["close"]) == (153.418, 154.422))
check("高値・安値が正しい", (df.iloc[1]["high"], df.iloc[1]["low"]) == (155.0, 153.368))
check("スポットと時刻をJSTで返す", spot == 154.524 and asof == "2026-09-15 09:16 JST", asof)

# ---------------------------------------------------------------- 財務省
print("[財務省 国債金利情報]")
HEAD = "国債金利情報,,,,,,,,,,,,,,,(単位 : %)\n基準日,1年,2年,3年,4年,5年,6年,7年,8年,9年,10年,15年,20年,25年,30年,40年\n"
ALL = HEAD + "R8.8.28,1.483,1.719,1.872,2.062,2.212,2.345,2.492,2.656,2.79,2.91,3.4,3.7,4.0,4.0,4.0\n" \
           + "R8.8.31,1.502,1.743,1.894,2.084,2.233,2.358,2.507,2.67,2.801,2.943,3.4,3.7,4.0,4.0,4.0\n"
CUR = "国債金利情報 (令和8年9月),,,,,,,,,,,,,,,(単位 : %)\n" + HEAD.splitlines()[1] + "\n" \
    + "R8.8.31,1.502,1.743,1.894,2.084,2.233,2.358,2.507,2.67,2.801,2.943,3.4,3.7,4.0,4.0,4.0\n" \
    + "R8.9.14,1.553,1.841,1.989,2.17,2.302,2.42,2.547,2.711,2.849,2.988,3.5,3.8,4.0,4.0,4.0\n" \
    + "R8.9.15,1.57,1.861,2.005,2.197,2.338,2.46,2.584,2.753,2.888,3.028,3.5,3.8,4.0,4.0,4.0\n" \
    + ",,,,,,,,,,,,,,,\n※最新のcsvデータが…,,,,,,,,,\n"
def fake_get(url, *a, **k):
    return (CUR if url == U.MOF_CURRENT_URL else ALL).encode("cp932")
U.fd.http_get = fake_get
merged = U.fetch_jgb_bytes().decode("cp932")
check("当月ぶんが足される", "R8.9.15" in merged and "R8.9.14" in merged)
check("重複する日は足さない", merged.count("R8.8.31") == 1, f"{merged.count('R8.8.31')}回")
check("注記行は混ざらない", "※" not in merged)
got = U.jgb_last(merged.encode("cp932"))
check("最新日の1年・2年を読む", got == ("2026-09-15", {"y1": 1.57, "y2": 1.861}), str(got))
p = TMP / "jgb.csv"; p.write_bytes(merged.encode("cp932"))
j = fd.fetch_jgb(local_file=str(p))
check("fetch_data.py 側でも読める", str(j["date"].max().date()) == "2026-09-15", str(j["date"].max()))
p.unlink()

# ---------------------------------------------------------------- 日銀 xlsx
print("[日銀 コールO/N物レート xlsx]")
shared = ('<?xml version="1.0"?><x:sst xmlns:x="u">'
          + "".join(f"<x:si><x:t>{s}</x:t></x:si>" for s in
                    ["Financial Markets Department", "日本銀行金融市場局", "Bank of Japan",
                     "Uncollateralized Overnight Call Rate for September 15",
                     "（％）", "平均\nAverage", "最高\nMaximum", "最低\nMinimum"])
          + "</x:sst>")
# 実物の日銀ファイルと同じ形：見出しはB列、値はC列、s= 属性が間に入り、
# 空セルは自己終了タグ
sheet = ('<?xml version="1.0"?><x:worksheet xmlns:x="u"><x:sheetData>'
         '<x:row r="2"><x:c r="A2" s="1" t="s"><x:v>0</x:v></x:c></x:row>'
         '<x:row r="10" spans="1:12"><x:c r="A10" s="13" />'
         '<x:c r="B10" s="14" t="s"><x:v>5</x:v></x:c>'
         '<x:c r="C10" s="15"><x:v>0.981</x:v></x:c></x:row>'
         '<x:row r="11"><x:c r="A11" s="13" />'
         '<x:c r="B11" s="14" t="s"><x:v>6</x:v></x:c>'
         '<x:c r="C11" s="15"><x:v>1.03</x:v></x:c></x:row>'
         '</x:sheetData></x:worksheet>')
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as z:
    z.writestr("xl/sharedStrings.xml", shared)
    z.writestr("xl/worksheets/sheet1.xml", sheet)
XLSX = buf.getvalue()
BOJ_HTML = ('<html><a href="/statistics/market/short/mutan/d_release/mp/mp20260916.xlsx">速報</a>'
            '<a href="/statistics/market/short/mutan/d_release/md/2026/md20260915.xlsx">確報</a>'
            '<a href="/statistics/market/short/mutan/d_release/md/2026/md20260914.xlsx">確報</a></html>')
U.fd.http_get = lambda url, *a, **k: (XLSX if url.endswith(".xlsx") else BOJ_HTML.encode())
got = U.boj_call_rate()
check("最新の確報から平均レートを読む", got == ("2026-09-15", 0.981), str(got))
_, cells = U._xlsx_cells(XLSX)
check("x: 接頭辞つき・s= 付きのセルを読める", cells.get("C11") == "1.03", str(cells.get("C11")))
# 共有文字列が読めない形式に変わっても、平均（最初の金利らしい数値）は拾える
buf2 = io.BytesIO()
with zipfile.ZipFile(buf2, "w") as z:
    z.writestr("xl/worksheets/sheet1.xml", sheet)      # sharedStrings を入れない
U.fd.http_get = lambda url, *a, **k: (buf2.getvalue() if url.endswith(".xlsx") else BOJ_HTML.encode())
check("見出しが読めなくても平均を拾う", U.boj_call_rate() == ("2026-09-15", 0.981), str(U.boj_call_rate()))

# ---------------------------------------------------------------- 月次マクロ
print("[米CPI・雇用統計の計算と、市場予想の保護]")
months = pd.date_range("2024-06-01", "2026-08-01", freq="MS")
def series(sid, col, *a):
    n = len(months)
    v = {"CPIAUCNS": [300 + i for i in range(n)], "CPILFENS": [310 + i for i in range(n)],
         "CPIAUCSL": [320 + i for i in range(n)], "CPILFESL": [330 + i for i in range(n)],
         "PAYEMS": [158000 + 100 * i for i in range(n)], "UNRATE": [4.0] * n,
         "CES0500000003": [36 + 0.1 * i for i in range(n)]}[sid]
    return pd.DataFrame({"date": months, col: v})
U.fd._fetch_one_series = series
work = TMP / "macro"; work.mkdir()
old = pd.DataFrame({"date": ["2026-07-01", "2026-08-01", "2026-09-01"],
                    "cpi_yoy": [3.36, None, None], "cpi_yoy_f": [3.4, 3.4, None],
                    "cpi_release": ["2026-08-12", "2026-09-11", "2026-10-14"]})
old.to_csv(work / "us_macro.csv", index=False)
real_here = U.HERE; U.HERE = work
U.update_macro()
U.HERE = real_here
res = pd.read_csv(work / "us_macro.csv")
r8 = res[res["date"] == "2026-08-01"].iloc[0]
check("新しい月の実績が入る", abs(r8["cpi_yoy"] - (326 / 314 - 1) * 100) < 0.01, f'{r8["cpi_yoy"]}')
check("市場予想(_f)は上書きされない", r8["cpi_yoy_f"] == 3.4)
check("発表日も残る", r8["cpi_release"] == "2026-09-11")
check("予想だけの先の月も残る", "2026-09-01" in list(res["date"]))
check("前月差が計算される", res[res["date"] == "2026-08-01"].iloc[0]["payrolls_chg"] == 100)
check("既存より古い月へは遡らない", res["date"].min() == "2026-07-01", res["date"].min())
shutil.rmtree(work)

# ---------------------------------------------------------------- 保存の安全装置
print("[書き込みの安全装置]")
work = TMP / "save"; work.mkdir()
old = pd.DataFrame({"date": ["2026-09-01", "2026-09-02", "2026-09-03"], "v": [1, 2, 3]})
f = work / "x.csv"; old.to_csv(f, index=False)
short = pd.DataFrame({"date": ["2026-09-01"], "v": [1]})
check("行が減る更新は捨てる", U.save_frame(f, short, old, "x") is False)
back = pd.DataFrame({"date": ["2026-09-01", "2026-09-02", "2026-09-03"], "v": [9, 9, 9]})
back.loc[2, "date"] = "2026-08-31"
check("最終日が戻る更新は捨てる", U.save_frame(f, back, old, "x") is False)
good = pd.concat([old, pd.DataFrame({"date": ["2026-09-04"], "v": [4]})], ignore_index=True)
check("正常な更新は通る", U.save_frame(f, good, old, "x") is True)
check("直前の版が .bak に残る", (work / "x.csv.bak").exists())
check("一時ファイルは残らない", not (work / "x.csv.tmp").exists())
shutil.rmtree(work)

# ---------------------------------------------------------------- 通信方法の順番
print("[curl_cffi が本当に最初に使われるか]")
import types
called = []
fake_mod = types.ModuleType("curl_cffi")
fake_req = types.ModuleType("curl_cffi.requests")
class _Resp:
    content = b"CFFI"
    def raise_for_status(self): pass
def _fake_get(url, impersonate=None, timeout=None):
    called.append(("curl_cffi", url, impersonate)); return _Resp()
fake_req.get = _fake_get
fake_mod.requests = fake_req
sys.modules["curl_cffi"] = fake_mod
sys.modules["curl_cffi.requests"] = fake_req

# fetch_data 側の旧来の方法は、呼ばれたら分かるようにしておく
for nm in list(fd.TRANSPORTS):
    fd.TRANSPORTS[nm] = (lambda n: (lambda url, timeout: called.append((n, url, None))
                                    or (_ for _ in ()).throw(RuntimeError("旧来の方法"))))(nm)

import importlib
importlib.reload(U)
U.tighten_fetch_data()
got = U.fd.http_get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS2")
check("curl_cffi が最初に呼ばれる", called and called[0][0] == "curl_cffi", str(called[:1]))
check("curl_cffi の結果がそのまま返る", got == b"CFFI", str(got))
check("chrome になりすます", called[0][2] == "chrome", str(called[0][2]))
check("旧来の方法は呼ばれない", len(called) == 1, str([c[0] for c in called]))
check("curl_cffi あり と記録される", getattr(U.fd.http_get, "uses_cffi", False) is True)

# curl_cffi が無いときは、ちゃんと警告して旧来の方法に落ちる
del sys.modules["curl_cffi"]; del sys.modules["curl_cffi.requests"]
importlib.reload(U)
U.tighten_fetch_data()
check("curl_cffi が無ければ警告する",
      any("curl_cffi" in w for w in U.WARNINGS), str(U.WARNINGS[:1]))
check("curl_cffi なし と記録される", getattr(U.fd.http_get, "uses_cffi", True) is False)


# ---------------------------------------------------------------- FREDの遅れを埋める
print("[FREDのドル円が遅れている日をYahooで埋める]")
work = TMP / "gap"; work.mkdir()
base = pd.DataFrame({"date": ["2026-09-11","2026-09-14","2026-09-15","2026-09-16"],
                     "usdjpy":[153.71,153.71,153.71,153.71],   # ← 前日値の繰り越し
                     "us2y":[4.63,4.64,4.66,4.67],"jp2y":[1.84,1.84,1.85,1.85],
                     "us10y":[4.96,4.97,4.98,4.99],"jp10y":[2.99,2.99,3.0,3.0],
                     "vix":[15.8,17.1,17.0,16.9]})
ohlc = pd.DataFrame({"date":["2026-09-11","2026-09-14","2026-09-15","2026-09-16"],
                     "open":[0,0,0,0],"high":[0,0,0,0],"low":[0,0,0,0],
                     "close":[153.554,154.422,155.012,155.61]})
U.fd.build = lambda *a, **k: base.copy()
U.fd._fetch_one_series = lambda *a, **k: pd.DataFrame(
    {"date": pd.to_datetime(["2026-09-10","2026-09-11"]), "usdjpy":[154.06,153.71]})
real_here = U.HERE; U.HERE = work
U.update_data_csv(None, ohlc)
U.HERE = real_here
res = pd.read_csv(work/"data.csv").set_index("date")["usdjpy"].to_dict()
check("FREDに実測がある日はそのまま", res["2026-09-11"] == 153.71, str(res["2026-09-11"]))
check("遅れている日はYahooの終値で埋まる",
      (res["2026-09-14"], res["2026-09-16"]) == (154.42, 155.61), str(res))
check("前日値の平坦な並びが解消する", len(set(res.values())) == 4, str(res))
shutil.rmtree(work)

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n合計 {len(OK)+len(NG)}件 / 成功 {len(OK)} / 失敗 {len(NG)}")
if NG:
    print("失敗:", NG)
sys.exit(1 if NG else 0)
