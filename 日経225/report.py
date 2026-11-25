#!/usr/bin/env python3
"""日経225ツールの出力（Excel・HTML・トップ画面用の要約）"""
from __future__ import annotations

import html
import json
import math

import numpy as np
import pandas as pd

from selection import ABS_ADD, HIGH_LIQ


def _f(v, nd=2, pct=False, sign=False):
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "－"
    try:
        x = float(v)
    except (TypeError, ValueError):
        return html.escape(str(v))
    s = f"{x:+,.{nd}f}" if sign else f"{x:,.{nd}f}"
    return s + ("%" if pct else "")


def _e(s):
    return html.escape("" if s is None or (isinstance(s, float) and math.isnan(s)) else str(s))


# ====================================================================== 要約
def summary(ctx) -> dict:
    sim, nxt = ctx["sim"], ctx["nxt"]
    adds = [d for d in sim.decisions if d.action == "採用"]
    dels = [d for d in sim.decisions if d.action == "除外"]
    wt = ctx["wt"]
    return {
        "asof": f"{ctx['last_day']:%Y-%m-%d}",
        "next_effective": f"{nxt['effective']:%Y-%m-%d}", "next_base": f"{nxt['base']:%Y-%m-%d}",
        "adds": [[d.code, ctx["names"].get(d.code, ""), d.confidence] for d in adds],
        "dels": [[d.code, ctx["names"].get(d.code, ""), d.confidence] for d in dels],
        "valid": ctx["val"]["ok"], "valid_msg": ctx["val"]["message"],
        "top": [[c, wt.loc[c, "銘柄名"], round(float(wt.loc[c, "ウエート(%)"]), 2)] for c in wt.index[:3]],
    }


# ====================================================================== Excel
def write_excel(path, ctx) -> None:
    from openpyxl import Workbook
    from openpyxl.formatting.rule import ColorScaleRule
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter as L

    wb = Workbook()
    HEAD = PatternFill("solid", fgColor="1F3A5F")
    HF = Font(bold=True, color="FFFFFF")
    INPUT = PatternFill("solid", fgColor="FFF4CC")
    BOLD = Font(bold=True)

    def sheet(title, df, widths=None, number_formats=None, index=False, note=None, freeze=True):
        ws = wb.create_sheet(title)
        r0 = 1
        if note:
            for line in note if isinstance(note, list) else [note]:
                ws.cell(r0, 1, line).font = Font(italic=True, color="555555")
                r0 += 1
            r0 += 1
        d = df.reset_index() if index else df
        for j, c in enumerate(d.columns, 1):
            x = ws.cell(r0, j, str(c))
            x.fill, x.font = HEAD, HF
            x.alignment = Alignment(wrap_text=True, vertical="center")
        for i, row in enumerate(d.itertuples(index=False), r0 + 1):
            for j, v in enumerate(row, 1):
                if isinstance(v, (float, np.floating)) and (np.isnan(v) or np.isinf(v)):
                    v = None
                elif isinstance(v, (np.integer,)):
                    v = int(v)
                elif isinstance(v, (np.floating,)):
                    v = float(v)
                elif isinstance(v, pd.Timestamp):
                    v = v.strftime("%Y-%m-%d")
                elif isinstance(v, (np.bool_,)):
                    v = bool(v)
                ws.cell(i, j, v)
        for j, c in enumerate(d.columns, 1):
            w = (widths or {}).get(c, max(8, min(40, len(str(c)) * 2 + 2)))
            ws.column_dimensions[L(j)].width = w
            fmt = (number_formats or {}).get(c)
            if fmt:
                for i in range(r0 + 1, r0 + 1 + len(d)):
                    ws.cell(i, j).number_format = fmt
        if freeze:
            ws.freeze_panes = ws.cell(r0 + 1, 2)
        ws.auto_filter.ref = f"A{r0}:{L(len(d.columns))}{r0 + len(d)}"
        return ws, r0

    sim, nxt, val = ctx["sim"], ctx["nxt"], ctx["val"]
    names = ctx["names"]

    # --- 概要
    ws = wb.active
    ws.title = "概要"
    lines = [
        ("日経225 入れ替え予想・ウエート分析", None),
        ("作成日", ctx["today"]), ("株価の最終日", f"{ctx['last_day']:%Y-%m-%d}"),
        ("次回の定期見直し（実施日）", f"{nxt['effective']:%Y-%m-%d}"),
        ("基準日", f"{nxt['base']:%Y-%m-%d}（この日までの5年間の流動性で判定）"),
        ("発表の目安", f"{nxt['announce_est']:%Y-%m-%d}ごろ（例年、実施日の約1か月前）"),
        ("予想の前提", f"{ctx['asof']:%Y-%m-%d}までの株価で基準日を迎えたと仮定した暫定の予想"),
        ("係数表の検証", val["message"]),
        ("除数（公表値）", f"{ctx['D']:.8f}（{ctx['d_date']} 公表）"),
    ]
    for i, (k, v) in enumerate(lines, 1):
        ws.cell(i, 1, k).font = BOLD if v is not None else Font(bold=True, size=14)
        if v is not None:
            ws.cell(i, 2, v)
    r = len(lines) + 2
    ws.cell(r, 1, "予想される入れ替え").font = Font(bold=True, size=12)
    r += 1
    dec = ctx["dec"]
    for j, c in enumerate(dec.columns, 1):
        x = ws.cell(r, j, c)
        x.fill, x.font = HEAD, HF
    for i, row in enumerate(dec.itertuples(index=False), r + 1):
        for j, v in enumerate(row, 1):
            ws.cell(i, j, None if isinstance(v, float) and np.isnan(v) else v)
    r += len(dec) + 2
    notes = [
        "■ 読み方",
        "・絶対採用（流動性75位以内）と絶対除外（451位以下）は確度が高い。セクター調整は日経の判断が入るので確度は中〜低。",
        "・流動性順位は日経の公式の数値ではなく、株価CSV（終値×出来高・高値÷安値）から再現した近似。75位・450位の境界付近は外れることがある。",
        "・2023〜2026年の8回の定期見直しで再現テスト済み（「再現テスト」シート）。",
        "・特別注意銘柄など、採用されない銘柄は 日経225/data/exclude.csv に書くと候補から外れる。",
        "■ 投資への使い方（「イベント分析」「売買ルール検証」シートの結果）",
        "・採用銘柄は基準日から実施日の前日にかけて対TOPIXで上昇しやすく、実施日以降は反落しやすい（指数買いの後の反動）。",
        "・除外銘柄の空売りは、この期間の実績では有効ではなかった（除外前に下げ切っていることが多い）。",
        "・確度の高い予想採用銘柄を基準日前後に買い、実施日の前日（指数連動ファンドの買いが入る日）に手じまうのが基本形。",
        "■ 注意：投資判断はご自身で。この表は日経の公表ルールからの推定で、日経の公式予想ではありません。",
    ]
    for line in notes:
        ws.cell(r, 1, line).font = BOLD if line.startswith("■") else Font()
        r += 1
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 20
    for c in "CDEFGH":
        ws.column_dimensions[c].width = 18

    # --- 入替予想（候補）
    add = sim.add_candidates.copy()
    add["銘柄名"] = add["code"].map(names)
    add["売買代金(億円/日)"] = add["tv_mean"] / 1e8
    add["除外リスト"] = add["code"].map(lambda c: ctx["excl"].get(c, ""))
    add["前回見送り"] = add["code"].map(lambda c: "○" if c in ctx["passed"] else "")
    r1 = ctx["ranks"].set_index("code")
    add["順位(1か月前)"] = add["code"].map(r1["順位(1か月前)"])
    add["順位(3か月前)"] = add["code"].map(r1["順位(3か月前)"])
    a = add[["code", "銘柄名", "industry", "sector", "liq_rank", "順位(1か月前)", "順位(3か月前)", "rank_tv",
             "rank_impact", "売買代金(億円/日)", "セクター過不足", "セクター内順位", "予想", "前回見送り", "除外リスト"]]
    a = a.rename(columns={"code": "コード", "industry": "日経業種", "sector": "セクター", "liq_rank": "流動性順位",
                          "rank_tv": "売買代金順位", "rank_impact": "価格変動率順位"}).sort_values("流動性順位")
    sheet("採用候補", a, number_formats={"売買代金(億円/日)": "#,##0.0", "セクター過不足": "+0.0;-0.0;0"},
          note=[f"未採用銘柄のうち流動性150位以内、または各セクターで流動性上位3位以内（{ctx['asof']:%Y-%m-%d}時点）。",
                "セクター過不足＝見直し前の採用数−採用妥当数（マイナス＝不足。不足セクターの上位ほど採用されやすい）。",
                "前回見送り＝前回の見直しでこの近似では75位以内だったが採用されなかった銘柄（日経の指標では基準外の可能性）。"])
    dl = sim.del_candidates.copy()
    dl["銘柄名"] = dl["code"].map(names)
    dl["売買代金(億円/日)"] = dl["tv_mean"] / 1e8
    dl["流動性順位"] = dl["liq_rank"].where(dl["liq_rank"] < 10_000)
    dl["ウエート(%)"] = dl["code"].map(ctx["wt"]["ウエート(%)"])
    d2 = dl[["code", "銘柄名", "industry", "sector", "流動性順位", "rank_tv", "rank_impact", "売買代金(億円/日)",
             "ウエート(%)", "セクター過不足", "セクター内順位(下から)", "予想"]]
    d2 = d2.rename(columns={"code": "コード", "industry": "日経業種", "sector": "セクター",
                            "rank_tv": "売買代金順位", "rank_impact": "価格変動率順位"})
    sheet("除外候補", d2, number_formats={"売買代金(億円/日)": "#,##0.0", "ウエート(%)": "0.000"},
          note="採用銘柄のうち流動性350位より下、または各セクターで流動性が下から2位以内。451位以下は絶対除外の対象。")

    # --- セクター
    st = sim.sector_table.copy()
    st.index.name = "セクター"
    sheet("セクター過不足", st, index=True, number_formats={"採用妥当数": "0.0", "過不足(見直し前)": "+0.0;-0.0;0",
                                                       "過不足(予想後)": "+0.0;-0.0;0"},
          note="採用妥当数＝高流動性銘柄群（上位450）のうちそのセクターに属する銘柄数の半分。")

    # --- 流動性順位（全銘柄）
    rk = ctx["ranks"].copy()
    rk = rk[rk["liq_rank"].notna()].sort_values("liq_rank")
    rk2 = rk[["code", "銘柄名", "member", "industry", "sector", "liq_rank", "順位(1か月前)", "順位(3か月前)",
              "rank_tv", "rank_impact", "売買代金(億円/日)", "days", "first"]].rename(columns={
        "code": "コード", "member": "採用中", "industry": "日経業種", "sector": "セクター", "liq_rank": "流動性順位",
        "rank_tv": "売買代金順位", "rank_impact": "価格変動率順位", "days": "計測日数", "first": "計測開始日"})
    rk2["採用中"] = rk2["採用中"].map({True: "○", False: ""})
    sheet("流動性順位", rk2, number_formats={"売買代金(億円/日)": "#,##0.0"},
          note=f"東証プライム（上場1年以上）の流動性順位。{HIGH_LIQ}位以内が高流動性銘柄群、{ABS_ADD}位以内の未採用銘柄は絶対採用の対象。")

    # --- ウエート・寄与度
    wt = ctx["wt"].copy()
    ws_w, r0 = sheet("ウエート・寄与度", wt, index=True,
                     number_formats={"株価": "#,##0.0", "前日比(%)": "+0.00;-0.00", "採用株価": "#,##0.0",
                                     "ウエート(%)": "0.000", "寄与度1日(円)": "+#,##0.0;-#,##0.0",
                                     "寄与度5日(円)": "+#,##0.0;-#,##0.0", "寄与度20日(円)": "+#,##0.0;-#,##0.0",
                                     "寄与度年初来(円)": "+#,##0.0;-#,##0.0"},
                     note="寄与度は「いまの係数×分割調整済み株価の変化÷除数」。年初来は途中の入れ替え・キャップ変更を反映しない近似。")
    col = list(wt.reset_index().columns).index("ウエート(%)") + 1
    ws_w.conditional_formatting.add(f"{L(col)}{r0 + 1}:{L(col)}{r0 + len(wt)}",
                                    ColorScaleRule(start_type="min", start_color="FFFFFF", end_type="max", end_color="5B8DEF"))
    secw = ctx["secw"].copy()
    secw.index.name = "セクター"
    sheet("セクター寄与度", secw, index=True, number_formats={c: "+#,##0.0;-#,##0.0" for c in secw.columns if "寄与" in c} | {"ウエート(%)": "0.00"})
    if len(ctx["capw"]):
        sheet("キャップ監視", ctx["capw"], number_formats={"ウエート(%)": "0.00", "10%までの余裕(%pt)": "+0.00;-0.00"},
              note=["ウエートが基準日（1月末・7月末）に10%を超えるとキャップ調整比率が0.1下がり、5%を下回ると0.1上がる。",
                    "下がった銘柄は指数連動ファンドの売りが出やすい（実施日は4月・10月の第1営業日）。"])

    # --- 需給インパクト（Excelの式で計算。連動資産額を変えると再計算）
    imp = ctx["impact"]
    ws_i = wb.create_sheet("需給インパクト")
    ws_i["A1"] = "日経平均連動の運用資産（兆円）"
    ws_i["A1"].font = BOLD
    ws_i["B1"] = ctx["aum"]
    ws_i["B1"].fill = INPUT
    ws_i["C1"] = "← 黄色のセルを変えると下の表が再計算されます。初期値は仮置き（ETF・投信・年金などの合計の推計で置き換えてください）"
    hdr = ["コード", "銘柄名", "確度", "株価", "想定係数", "想定ウエート(%)", "売買代金20日平均(億円)",
           "指数連動の売買(億円)", "売買代金の何日分"]
    for j, h in enumerate(hdr, 1):
        x = ws_i.cell(3, j, h)
        x.fill, x.font = HEAD, HF
    for i, row in enumerate(imp.itertuples(index=False), 4):
        vals = list(row)
        for j, v in enumerate(vals, 1):
            ws_i.cell(i, j, None if isinstance(v, float) and np.isnan(v) else v)
        ws_i.cell(i, 8, f"=$B$1*10000*F{i}/100")
        ws_i.cell(i, 9, f'=IF(G{i}>0,ABS(H{i})/G{i},"")')
        for j, fmt in ((4, "#,##0"), (5, "0.0"), (6, "+0.000;-0.000"), (7, "#,##0.0"), (8, "+#,##0;-#,##0"), (9, "0.0")):
            ws_i.cell(i, j).number_format = fmt
    for j, w in enumerate([8, 22, 6, 10, 9, 13, 18, 16, 14], 1):
        ws_i.column_dimensions[L(j)].width = w
    ws_i.cell(5 + len(imp), 1, "採用はプラス（買い）、除外はマイナス（売り）。採用時の係数は原則1、ウエートが1%を超える値がさ株は0.1〜0.9に下げられる（日経の規定）。")

    # --- 検証
    if val["rows"]:
        sheet("係数表の検証", pd.DataFrame(val["rows"]),
              number_formats={"日経平均(公表)": "#,##0.00", "計算値": "#,##0.00", "誤差(%)": "+0.0000;-0.0000",
                              "除数(公表)": "0.00000000", "逆算した除数": "0.00000000"},
              note="株価換算係数×終値の合計÷除数 が日経平均の終値と一致するか（誤差0.05%以内なら一致）。")
    if val.get("diagnosis"):
        sheet("ずれの推定原因", pd.DataFrame(val["diagnosis"]))
    fac = ctx["factors"].copy()
    fac["銘柄名"] = fac["code"].map(names)
    sheet("株価換算係数", fac[["code", "銘柄名", "factor", "cap_ratio", "source"]].rename(columns={
        "code": "コード", "factor": "株価換算係数", "cap_ratio": "キャップ調整比率", "source": "出所"}),
        widths={"出所": 70})

    # --- 過去の検証
    bt = ctx["bt"]
    if bt:
        sheet("再現テスト", bt["replay"], widths={"実際の採用": 45, "予想の採用": 45, "実際の除外": 45, "予想の除外": 45},
              note=["過去の定期見直しを、基準日までの株価だけで予想した結果。",
                    f"採用 {bt['hit']['採用'][0]}/{bt['hit']['採用'][1]} 的中（予想 {bt['hit']['採用'][2]}銘柄）・"
                    f"除外 {bt['hit']['除外'][0]}/{bt['hit']['除外'][1]} 的中（予想 {bt['hit']['除外'][2]}銘柄）"])
        es = bt["events"]
        sheet("イベント分析", es, number_formats={c: "+0.00;-0.00" for c in es.columns if "→" in c or "実施後" in c or "翌" in c},
              note="対TOPIXの超過リターン（%）。発表は大引け後なので「発表翌日」が発表への反応。実施前日の大引けで指数連動ファンドの売買が出る。")
        s = bt["event_summary"].copy()
        s.index = [" / ".join(map(str, i)) for i in s.index]
        s.index.name = "統計 / 区分"
        sheet("イベント分析(集計)", s, index=True)
        sheet("売買ルール検証", bt["strategy"], number_formats={"発表前日まで(%)": "+0.00;-0.00", "実施前日まで(%)": "+0.00;-0.00"},
              note=["予想に従って基準日の翌営業日の終値で売買した場合の対TOPIX超過リターン（売りは符号を反転）。",
                    "「実施前日まで」は予想が当たった銘柄は実施前日まで、外れた銘柄は発表翌日に手じまい。"])

    ev = ctx["events"].copy()
    sheet("入れ替えの履歴", ev.sort_values(["effective", "type"], ascending=[False, True]).rename(columns={
        "effective": "実施日", "announced": "発表日", "type": "種類", "code": "コード", "name": "銘柄名",
        "old": "旧", "new": "新", "reason": "理由"}), widths={"理由": 34},
        note="add=採用 del=除外 factor=株価換算係数の変更 cap=キャップ調整比率。2021年10月以降（日経平均プロフィルのお知らせから）。")
    wb.save(path)


# ====================================================================== HTML
CSS = """
:root{color-scheme:light;--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
 --grid:#e1e0d9;--border:rgba(11,11,11,.10);--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;
 --good:#0ca30c;--warning:#fab219;--critical:#d03b3b;--up:#c93a3a;--dn:#2E7D6B;--wash:rgba(42,120,214,.08)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;
 --ink:#fff;--ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--border:rgba(255,255,255,.10);--s1:#3987e5;--s2:#d95926;
 --s3:#199e70;--s4:#c98500;--critical:#e66767;--up:#e66767;--dn:#3FA58C;--wash:rgba(57,135,229,.14)}}
:root[data-theme="dark"]{color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--muted:#898781;
 --grid:#2c2c2a;--border:rgba(255,255,255,.10);--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--critical:#e66767;
 --up:#e66767;--dn:#3FA58C;--wash:rgba(57,135,229,.14)}
*{box-sizing:border-box}body{margin:0;background:var(--page);color:var(--ink);
 font:14px/1.55 system-ui,-apple-system,"Hiragino Sans","Segoe UI",sans-serif}
.wrap{max-width:1200px;margin:0 auto;padding:20px 16px 48px}
header{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;gap:8px;margin-bottom:16px}
h1{font-size:21px;margin:0}h2{font-size:16px;margin:0 0 10px}h3{font-size:14px;margin:14px 0 6px;color:var(--ink2)}
.meta{color:var(--muted);font-size:12px}
.panel{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:16px;margin-bottom:16px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:16px}
.tile{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:12px 14px}
.tile .k{color:var(--ink2);font-size:12px}.tile .v{font-size:22px;font-weight:700;margin-top:2px}
.tile .s{color:var(--muted);font-size:12px}
.tbl{width:100%;border-collapse:collapse;font-size:13px}
.tbl th{text-align:left;color:var(--ink2);font-weight:600;border-bottom:1px solid var(--grid);padding:6px 6px;white-space:nowrap}
.tbl td{border-bottom:1px solid var(--grid);padding:6px 6px;vertical-align:top}
.tbl td.nm{white-space:nowrap;max-width:16em;overflow:hidden;text-overflow:ellipsis}
.tbl td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.scroll{overflow-x:auto}
.badge{display:inline-block;border-radius:999px;padding:1px 8px;font-size:12px;border:1px solid var(--border);white-space:nowrap}
.b-high{background:rgba(201,58,58,.12);color:var(--up)}.b-mid{background:rgba(237,161,0,.15)}.b-low{background:var(--wash)}
.add{color:var(--up);font-weight:600}.del{color:var(--dn);font-weight:600}
.up{color:var(--up)}.dn{color:var(--dn)}
.ok{color:var(--good)}.ng{color:var(--critical)}
.bars{display:grid;grid-template-columns:minmax(90px,170px) 1fr 60px;max-width:760px;gap:4px 8px;align-items:center;font-size:13px}
.bar{height:12px;border-radius:0 4px 4px 0;background:var(--s1)}
.dv{position:relative;height:14px}.dv span{position:absolute;top:0;height:14px}
.dv .m{left:50%;width:1px;height:14px;background:var(--muted)}
.tip{color:var(--muted);font-size:12px;margin-top:6px}
details{margin-top:8px}summary{cursor:pointer;color:var(--ink2)}
.two{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media (max-width:820px){.two{grid-template-columns:1fr}}
.chartbox{position:relative;height:280px}
a{color:var(--s1)}
"""


def _conf(c):
    cls = {"高": "b-high", "中": "b-mid", "低": "b-low"}.get(c, "")
    return f'<span class="badge {cls}">確度 {c}</span>'


def write_html(path, ctx) -> None:
    """ダッシュボード。見やすく作り直した dashboard.py を使い、失敗したら従来版で出す"""
    try:
        import dashboard
        return dashboard.write_html(path, ctx)
    except Exception as e:  # noqa: BLE001
        print(f"※ 新しいダッシュボードの作成に失敗したため従来版で出力: {e}", flush=True)
        return write_html_legacy(path, ctx)


def write_html_legacy(path, ctx) -> None:
    sim, nxt, val, wt = ctx["sim"], ctx["nxt"], ctx["val"], ctx["wt"]
    names = ctx["names"]
    bt = ctx["bt"]
    adds = [d for d in sim.decisions if d.action == "採用"]
    dels = [d for d in sim.decisions if d.action == "除外"]

    # タイル
    tiles = [
        ("次回の定期見直し", f"{nxt['effective']:%Y/%m/%d}", f"基準日 {nxt['base']:%m/%d}・発表 {nxt['announce_est']:%m/%d}ごろ"),
        ("予想 採用 / 除外", f"{len(adds)} / {len(dels)}銘柄",
         "・".join(names.get(d.code, d.code) for d in adds[:3]) or "－"),
        ("ウエート1位", f"{_e(wt.iloc[0]['銘柄名'])} {wt.iloc[0]['ウエート(%)']:.1f}%",
         f"上位5銘柄で {wt['ウエート(%)'].iloc[:5].sum():.1f}%"),
        ("係数表の検証", '<span class="ok">一致</span>' if val["ok"] else
         ('<span class="ng">ずれあり</span>' if val["ok"] is False else "－"), _e(val["message"])),
    ]
    tiles_h = "".join(f'<div class="tile"><div class="k">{k}</div><div class="v">{v}</div><div class="s">{s}</div></div>'
                      for k, v, s in tiles)

    # 予想表
    def dec_rows(ds, cls):
        out = ""
        for d in ds:
            rk = "－" if d.liq_rank != d.liq_rank or d.liq_rank >= 10_000 else f"{d.liq_rank:.0f}位"
            out += (f'<tr><td style="white-space:nowrap"><span class="{cls}">{d.action}</span></td><td>{_e(d.code)}</td><td class="nm">{_e(names.get(d.code, ""))}</td>'
                    f'<td>{_e(d.sector)}</td><td class="n">{rk}</td><td>{_e(d.rule)}</td><td>{_conf(d.confidence)}</td>'
                    f'<td class="meta">{_e(d.note)}</td></tr>')
        return out
    dec_h = (f'<div class="scroll"><table class="tbl"><tr><th></th><th>コード</th><th>銘柄</th><th>セクター</th><th>流動性順位</th>'
             f'<th>根拠</th><th>確度</th><th>補足</th></tr>{dec_rows(adds, "add")}{dec_rows(dels, "del")}</table></div>')

    # 採用候補（上位20）
    ac = sim.add_candidates.sort_values("liq_rank").head(20)
    rk = ctx["ranks"].set_index("code")
    rows = ""
    for x in ac.itertuples():
        r1 = rk["順位(1か月前)"].get(x.code, np.nan)
        r3 = rk["順位(3か月前)"].get(x.code, np.nan)
        mv = "" if not (r3 == r3) else (f'<span class="up">↑{r3 - x.liq_rank:.0f}</span>' if r3 > x.liq_rank
                                        else (f'<span class="dn">↓{x.liq_rank - r3:.0f}</span>' if r3 < x.liq_rank else "→"))
        flag = "予想" if x.予想 else ("前回見送り" if x.code in ctx["passed"] else "")
        rows += (f'<tr><td>{_e(x.code)}</td><td class="nm">{_e(names.get(x.code, ""))}</td><td>{_e(x.sector)}</td>'
                 f'<td class="n">{x.liq_rank:.0f}</td><td class="n">{_f(r1, 0)}</td><td class="n">{mv}</td>'
                 f'<td class="n">{_f(x.セクター過不足, 1, sign=True)}</td><td class="n">{x.tv_mean / 1e8:,.0f}</td><td>{flag}</td></tr>')
    cand_h = (f'<div class="scroll"><table class="tbl"><tr><th>コード</th><th>銘柄</th><th>セクター</th><th>流動性順位</th>'
              f'<th>1か月前</th><th>3か月前比</th><th>セクター過不足</th><th>売買代金(億円/日)</th><th></th></tr>{rows}</table></div>')

    # セクター過不足（中央ゼロの横棒）
    st = sim.sector_table
    mx = max(1.0, float(st["過不足(見直し前)"].abs().max()))
    sb = ""
    for s, r in st.iterrows():
        v = float(r["過不足(見直し前)"])
        w = abs(v) / mx * 50
        left = 50 if v >= 0 else 50 - w
        color = "var(--s2)" if v > 0 else "var(--s1)"
        sb += (f'<div>{_e(s)}</div><div class="dv" title="{_e(s)}：採用妥当数 {r["採用妥当数"]:.1f}・採用 {r["見直し前"]:.0f}">'
               f'<span class="m"></span><span style="left:{left:.1f}%;width:{w:.1f}%;background:{color};border-radius:4px"></span></div>'
               f'<div class="n" style="text-align:right">{v:+.1f}</div>')
    sec_h = (f'<div class="bars">{sb}</div><p class="tip">右（オレンジ）＝採用が多すぎるセクター → 除外が出やすい。'
             f'左（青）＝不足 → 採用が出やすい。採用妥当数＝上位{HIGH_LIQ}銘柄のうちそのセクターの数の半分。</p>')

    # ウエート上位・寄与度
    top = wt.head(15)
    mxw = float(top["ウエート(%)"].max())
    wb_ = "".join(f'<div>{_e(r["銘柄名"])}</div><div><div class="bar" style="width:{r["ウエート(%)"] / mxw * 100:.1f}%" '
                  f'title="{_e(r["銘柄名"])} {r["ウエート(%)"]:.2f}%"></div></div><div class="n" style="text-align:right">{r["ウエート(%)"]:.2f}%</div>'
                  for _, r in top.iterrows())
    c1 = wt.sort_values("寄与度1日(円)")
    def crow(df):
        return "".join(f'<tr><td>{_e(r["銘柄名"])}</td><td class="n {"up" if r["寄与度1日(円)"] > 0 else "dn"}">'
                       f'{r["寄与度1日(円)"]:+,.0f}円</td><td class="n">{_f(r["前日比(%)"], 2, sign=True)}%</td></tr>'
                       for _, r in df.iterrows())
    contrib_h = (f'<div class="two"><div><h3>上げ寄与 上位5</h3><table class="tbl">{crow(c1.tail(5).iloc[::-1])}</table></div>'
                 f'<div><h3>下げ寄与 上位5</h3><table class="tbl">{crow(c1.head(5))}</table></div></div>')
    cap_h = ""
    if len(ctx["capw"]):
        cap_h = "<h3>キャップ監視（ウエート10%超で次の基準日にキャップ調整比率が0.1下がる）</h3>" + _table(ctx["capw"], names)

    # ウエート推移（Chart.js 折れ線）
    wh = ctx["whist"]
    series = [{"label": names.get(c, c), "data": [None if np.isnan(v) else round(float(v), 3) for v in wh[c]]} for c in wh.columns[:5]]
    chart_js = json.dumps({"labels": [d.strftime("%Y-%m-%d") for d in wh.index], "series": series}, ensure_ascii=False)

    # 過去の検証
    bt_h = ""
    if bt:
        h = bt["hit"]
        es = bt["event_summary"]
        def cell(stat, kind, col):
            try:
                return es.loc[(stat, kind), col]
            except KeyError:
                return np.nan
        cols = [c for c in es.columns]
        er = "".join(f'<tr><td>{k}</td>' + "".join(f'<td class="n">{_f(cell("平均(%)", k, c), 1, sign=True)}%<br>'
                                                    f'<span class="meta">中央 {_f(cell("中央値(%)", k, c), 1, sign=True)}</span></td>' for c in cols) + "</tr>"
                     for k in ("採用", "除外"))
        st_ = bt["strategy"]
        g = st_.groupby("売買")[["発表前日まで(%)", "実施前日まで(%)"]].agg(["mean", "median", "count"]) if len(st_) else None
        strat = ""
        if g is not None:
            for side, r in g.iterrows():
                strat += (f'<tr><td>{_e(side)}</td><td class="n">{r[("発表前日まで(%)", "mean")]:+.1f}%（中央 {r[("発表前日まで(%)", "median")]:+.1f}）</td>'
                          f'<td class="n">{r[("実施前日まで(%)", "mean")]:+.1f}%（中央 {r[("実施前日まで(%)", "median")]:+.1f}）</td>'
                          f'<td class="n">{int(r[("実施前日まで(%)", "count")])}</td></tr>')
        rep = bt["replay"]
        rr = "".join(f'<tr><td>{_e(r["実施日"])}</td><td>{_e(r["実際の採用"])}</td><td>{_e(r["予想の採用"])}</td>'
                     f'<td class="n">{_e(r["採用の的中"])}</td><td>{_e(r["実際の除外"])}</td><td>{_e(r["予想の除外"])}</td>'
                     f'<td class="n">{_e(r["除外の的中"])}</td></tr>' for _, r in rep.iterrows())
        bt_h = f"""
<section class="panel"><h2>過去の検証（2023年4月〜）</h2>
<div class="tiles">
<div class="tile"><div class="k">採用の的中（再現テスト）</div><div class="v">{h['採用'][0]}/{h['採用'][1]}</div><div class="s">予想した{h['採用'][2]}銘柄のうち</div></div>
<div class="tile"><div class="k">除外の的中</div><div class="v">{h['除外'][0]}/{h['除外'][1]}</div><div class="s">予想した{h['除外'][2]}銘柄のうち</div></div>
</div>
<h3>実際の採用・除外銘柄の値動き（対TOPIXの超過リターン、平均・中央値）</h3>
<div class="scroll"><table class="tbl"><tr><th></th>{''.join(f'<th>{_e(c)}</th>' for c in cols)}</tr>{er}</table></div>
<p class="tip">発表は大引け後なので「発表翌日」が発表への反応。指数連動ファンドは実施日の前営業日の大引けで売買する。</p>
<h3>予想どおりに売買した場合（基準日の翌営業日に入る・対TOPIX）</h3>
<table class="tbl"><tr><th></th><th>発表前日まで</th><th>実施前日まで</th><th>件数</th></tr>{strat}</table>
<p class="tip">「実施前日まで」は当たった銘柄を実施前日まで持ち、外れた銘柄は発表翌日に手じまった場合。売りは符号を反転。</p>
<details><summary>回ごとの再現テスト</summary><div class="scroll"><table class="tbl"><tr><th>実施日</th><th>実際の採用</th><th>予想の採用</th><th>的中</th><th>実際の除外</th><th>予想の除外</th><th>的中</th></tr>{rr}</table></div></details>
</section>"""

    page = f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>日経225 入れ替え予想</title><style>{CSS}</style></head><body><div class="wrap">
<header><h1><a href="./index.html" title="トップへ" style="text-decoration:none;color:inherit;margin-right:8px">‹</a>日経225 入れ替え予想・ウエート分析</h1>
<div class="meta">株価 {ctx['last_day']:%Y-%m-%d} まで・作成 {ctx['today']}・データ：日経平均プロフィル（構成銘柄・お知らせ・除数）、株価CSV</div></header>
<div class="tiles">{tiles_h}</div>
<section class="panel"><h2>次回（{nxt['effective']:%Y年%m月%d日}実施）の入れ替え予想</h2>
<p class="meta">{ctx['asof']:%Y-%m-%d}までの株価で基準日（{nxt['base']:%Y-%m-%d}）を迎えたと仮定した暫定の予想。基準日までの値動きで変わります。</p>
{dec_h}
<details><summary>選定ルールと、このページの計算のしかた</summary><p class="tip">
① 東証プライムを過去5年の売買代金と「売買代金当たりの価格変動率」で順位付けし、上位{HIGH_LIQ}を高流動性銘柄群とする。
② 採用銘柄で{HIGH_LIQ + 1}位以下は除外、未採用で{ABS_ADD}位以内は採用。③ セクターごとに高流動性銘柄の半数を採用妥当数とし、過不足を調整。
④ 入れ替えは1回3銘柄まで。日経は2指標の合成方法を公表していないため、このページの順位は「終値×出来高の1日平均」と
「(高値÷安値−1)の平均÷売買代金」の順位の和で近似（2023〜2026年の8回の見直しで再現を確認）。</p></details>
</section>
<section class="panel"><h2>セクターの過不足（採用数 − 採用妥当数）</h2>{sec_h}</section>
<section class="panel"><h2>採用候補（未採用の流動性上位・不足セクターの上位）</h2>{cand_h}</section>
<section class="panel"><h2>ウエートと寄与度</h2>
<div class="two"><div><h3>ウエート上位15</h3><div class="bars">{wb_}</div></div>
<div><h3>上位5銘柄のウエート推移（%・1年）</h3><div class="chartbox"><canvas id="wh" role="img" aria-label="上位5銘柄のウエート推移"></canvas></div></div></div>
{contrib_h}{cap_h}
<p class="tip">日経平均 ＝ Σ（株価×株価換算係数）÷ 除数（{ctx['D']:.8f}）。寄与度＝係数×株価の変化÷除数。{_e(val['message'])}</p>
</section>
{bt_h}
<p class="meta">投資判断はご自身で。日経の公表ルールからの推定で、日経の公式予想ではありません。詳細は Excel（日経225/output）。</p>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<script>(function(){{const D={chart_js};if(!window.Chart)return;const cs=getComputedStyle(document.documentElement);
const pal=['--s1','--s2','--s3','--s4','--muted'].map(v=>cs.getPropertyValue(v).trim());
new Chart(document.getElementById('wh'),{{type:'line',data:{{labels:D.labels,datasets:D.series.map((s,i)=>({{label:s.label,data:s.data,borderColor:pal[i],backgroundColor:pal[i],borderWidth:2,pointRadius:0,tension:.2}}))}},
options:{{responsive:true,maintainAspectRatio:false,interaction:{{mode:'index',intersect:false}},
plugins:{{legend:{{position:'bottom',labels:{{boxWidth:10,color:cs.getPropertyValue('--ink2')}}}},tooltip:{{callbacks:{{label:c=>c.dataset.label+' '+(c.parsed.y==null?'-':c.parsed.y.toFixed(2))+'%'}}}}}},
scales:{{x:{{ticks:{{maxTicksLimit:6,color:cs.getPropertyValue('--muted')}},grid:{{display:false}}}},y:{{ticks:{{color:cs.getPropertyValue('--muted'),callback:v=>v+'%'}},grid:{{color:cs.getPropertyValue('--grid')}}}}}}}}}});}})();</script>
</body></html>"""
    path.write_text(page, encoding="utf-8")


def _table(df, names):
    h = "".join(f"<th>{_e(c)}</th>" for c in df.columns)
    rows = ""
    for _, r in df.iterrows():
        tds = ""
        for c, v in r.items():
            if c == "コード":
                tds += f"<td>{_e(v)} {_e(names.get(v, ''))}</td>"
            elif isinstance(v, (float, np.floating)):
                tds += f'<td class="n">{_f(v, 2)}</td>'
            else:
                tds += f"<td>{_e(v)}</td>"
        rows += f"<tr>{tds}</tr>"
    return f'<div class="scroll"><table class="tbl"><tr>{h}</tr>{rows}</table></div>'
