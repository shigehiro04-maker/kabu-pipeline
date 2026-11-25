# -*- coding: utf-8 -*-
"""html_dashboard.py の CSS をデジタル庁ダッシュボードデザインテンプレート準拠に置き換える（1回だけ実行）。
元ファイルは html_dashboard.py.pre_da に保存。"""
import re, shutil
from pathlib import Path

P = Path(__file__).with_name("html_dashboard.py")
src = P.read_text(encoding="utf-8")
if "DA-THEME" in src:
    raise SystemExit("適用済みです")
shutil.copy2(P, P.with_name("html_dashboard.py.pre_da"))

LIGHT = ("--bg:#ffffff;--card:#f8f8fb;--ink:#000000;--ink2:#626264;--ink3:#767676;\n"
         "  --rule:#e6e6e6;--grid:#e6e6e6;--up:#ce0000;--dn:#0017c1;--up-bg:rgba(254,57,57,.10);--dn-bg:rgba(52,96,251,.10);\n"
         "  --fair:#259d63;--band:rgba(81,184,131,.16);--band2:rgba(81,184,131,.07);\n"
         "  --s2:#006f83;--s10:#ac3e00;--price:#000000;--warn:#ac3e00;--ok:#197a4b;\n"
         "  --hl:#0017c1;--ctl:#f1f1f4;--shadow:none;")
DARK = ("--bg:#111113;--card:#1c1c20;--ink:#f8f8fb;--ink2:#c4c4c8;--ink3:#9a9aa0;\n"
        "    --rule:#2e2e33;--grid:#2a2a2f;--up:#ff7171;--dn:#7096f8;--up-bg:rgba(255,113,113,.14);--dn-bg:rgba(112,150,248,.14);\n"
        "    --fair:#51b883;--band:rgba(81,184,131,.18);--band2:rgba(81,184,131,.08);\n"
        "    --s2:#2bc8e4;--s10:#ff8d44;--price:#f8f8fb;--warn:#ff8d44;--ok:#51b883;\n"
        "    --hl:#0017c1;--ctl:#26262b;--shadow:none;")

css_start = src.index('CSS = r"""')
css_end = src.index('"""', css_start + 10)
css = src[css_start:css_end]

# 1) ライトの :root
css = re.sub(r"(:root\{\n)(.*?)(\n  color-scheme:light;)", lambda m: m.group(1) + "  /* DA-THEME: デジタル庁デザインテンプレート準拠 */\n  " + LIGHT + m.group(3), css, count=1, flags=re.S)
# 2) ダークの2ブロック
css = re.sub(r"(:root:not\(\[data-theme=\"light\"\]\)\{\n    )(.*?)(\n    color-scheme:dark;)", lambda m: m.group(1) + DARK + m.group(3), css, count=1, flags=re.S)
css = re.sub(r"(:root\[data-theme=\"dark\"\]\{\n  )(.*?)(\n  color-scheme:dark;)", lambda m: m.group(1) + DARK.replace("\n    ", "\n  ") + m.group(3), css, count=1, flags=re.S)

rep = [
    # カード：影なし・角丸8・Standard背景（テンプレートのパネル）
    (".kpi{background:var(--card);border-radius:10px;", ".kpi{background:var(--card);border-radius:8px;"),
    (".card{background:var(--card);border-radius:12px;box-shadow:var(--shadow);padding:14px 16px 14px;",
     ".card{background:var(--card);border-radius:8px;box-shadow:var(--shadow);padding:14px 16px 14px;"),
    # 強調KPIは Highlight 背景（Blue 900）に白文字
    (".kpi.hero{background:var(--ink);color:var(--card)}", ".kpi.hero{background:var(--hl);color:#ffffff}"),
    (".kpi.hero .kl,.kpi.hero .ks{color:inherit;opacity:.72}", ".kpi.hero .kl,.kpi.hero .ks{color:inherit;opacity:.9}"),
    (".kpi.hero .dl.up{color:#ff9b9a}.kpi.hero .dl.dn{color:#8cbcff}", ".kpi.hero .dl.up,.kpi.hero .dl.dn{color:#ffffff}"),
    # 数値を目立たせる（テンプレートの数値カード36pt相当。7枚並ぶので28px）
    (".kv{font-size:24px;font-weight:700;", ".kv{font-size:28px;font-weight:700;"),
    (".kl{font-size:11.5px;color:var(--ink2);white-space:nowrap}", ".kl{font-size:12px;font-weight:700;color:var(--ink);white-space:nowrap}"),
    (".ks{font-size:11px;color:var(--ink3);", ".ks{font-size:11.5px;color:var(--ink2);"),
    # グラフタイトル 14 bold → Web 15px
    (".ch h2{font-size:14.5px;margin:0}", ".ch h2{font-size:15px;font-weight:700;margin:0}"),
    # 軸ラベルは補助テキスト色、最小11px
    (".tick{font-size:10.5px;fill:var(--ink3)}", ".tick{font-size:11px;fill:var(--ink2)}"),
    # 操作部品は Control 背景、選択中は Blue 900
    (".seg{display:inline-flex;background:var(--card);border-radius:8px;box-shadow:var(--shadow);padding:2px}",
     ".seg{display:inline-flex;background:var(--ctl);border-radius:8px;padding:2px}"),
    (".seg button[aria-pressed=\"true\"]{background:var(--ink);color:var(--card)}",
     ".seg button[aria-pressed=\"true\"]{background:var(--hl);color:#ffffff}"),
    (".ev .cd.soon{background:var(--ink);color:var(--card)}", ".ev .cd.soon{background:var(--hl);color:#ffffff}"),
    ("input[type=range]{width:100%;accent-color:var(--ink);", "input[type=range]{width:100%;accent-color:var(--hl);"),
    (".bars2 i{display:block;height:12px;border-radius:0 4px 4px 0;background:var(--ink)}",
     ".bars2 i{display:block;height:12px;border-radius:0;background:var(--hl)}"),
    # 表ヘッダは Control 背景
    ("thead th{border-top:0;font-size:11px;color:var(--ink3);font-weight:500}",
     "thead th{border-top:0;font-size:11.5px;color:var(--ink);font-weight:700;background:var(--ctl)}"),
]
miss = []
for a, b in rep:
    if a in css:
        css = css.replace(a, b)
    else:
        miss.append(a[:60])
css += ("\n/* DA-THEME: 追加分 */\n"
        "button:focus-visible,select:focus-visible,input:focus-visible{outline:2px solid var(--hl);outline-offset:2px}\n"
        ".da-src{margin-top:4px}\n")
src = src[:css_start] + css + src[css_end:]
P.write_text(src, encoding="utf-8")
print("OK", "未適用:", miss)
