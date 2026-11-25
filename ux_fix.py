#!/usr/bin/env python3
"""公開フォルダ（data/charts）の操作感の補正（2026-11-14）。東証版・米国版で同じファイル。

1. チャート一覧：列幅を固定し、長い銘柄名は「…」で省略する。画面幅に合わせて列を間引き、
   並べ替えても表が画面からはみ出さないようにする。見出しの貼りつく位置を検索欄の高さに合わせる
2. 売買シグナル・チャート形状検索・需給分析：列幅を固定し、並べ替えで列が動かないようにする
3. スマホ：入力欄・選択欄の文字を16pxにする（16px未満だとiPhoneがタップ時に画面を拡大して戻らない）
4. スマホ：小さなチェックボックスやボタンを押しやすい大きさにする（見た目の並びはそのまま）

・各ページの <head> に <style id="ux-fix"> を入れる（銘柄ごとのページは共通CSSファイルの末尾に足す）
・何度実行しても同じ結果（目印のコメントで前回分を置き換える）
deploy_github.sh から毎回自動で呼ばれる。手動なら:  python3 ~/株分析/ux_fix.py（米国版は ~/米国株分析/ux_fix.py）
"""
import os, re, sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "charts")
VER = "v1"
TOUCH = "(pointer:coarse)"
PHONE_OR_TOUCH = "(max-width:760px),(pointer:coarse)"

# ---------------------------------------------------------------- 全ページ共通
COMMON = f"""
/* 3. 入力欄・選択欄は16px（iPhoneの自動拡大を防ぐ） */
@media {PHONE_OR_TOUCH}{{
input:not([type=checkbox]):not([type=radio]):not([type=range]):not([type=button]):not([type=submit]):not([type=color]),select,textarea{{font-size:16px!important}}
}}
/* 4. チェックボックスを押しやすく */
@media {TOUCH}{{input[type=checkbox],input[type=radio]{{width:20px;height:20px;vertical-align:-5px}}}}
"""

# 説明の開閉（details）の見出しを押しやすく
SUMMARY = f"@media {TOUCH}{{details>summary{{padding-top:7px;padding-bottom:7px}}}}"

# ---------------------------------------------------------------- 1. チャート一覧
# 列：1★ 2コード 3銘柄名 4市場 5終値 6前日比 7 25日線乖離 8 RSI 9 RCI(9) 10 RCI(26) 11出来高
def _w(widths, scope="table"):
    return "".join(f"{scope} th:nth-child({i}),{scope} td:nth-child({i}){{width:{w}px}}" for i, w in widths.items())

def _hide(cols, scope="table"):
    return ",".join(f"{scope} th:nth-child({i}),{scope} td:nth-child({i})" for i in cols) + "{display:none}"

CHARTS = (
    # お気に入りが0件のときなどの案内文は折り返す（折り返さないとスマホで画面の外まで伸びる）
    "table td[colspan]{white-space:normal}"
    # 広い画面（1280px〜）：全列
    "@media (min-width:701px){"
    "table{table-layout:fixed}"
    "table td:nth-child(3){overflow:hidden;text-overflow:ellipsis}"
    "table th{top:var(--ux-tools,56px)}"
    "}"
    "@media (min-width:1280px){"
    + _w({1: 38, 2: 96, 4: 132, 5: 100, 6: 92, 7: 130, 8: 108, 9: 92, 10: 100, 11: 104}) +
    "}"
    # 701〜1279px：余白を詰め、市場の列を外す（市場は上の切り替えで絞れる）
    "@media (min-width:701px) and (max-width:1279px){"
    "table th,table td{padding-left:6px;padding-right:6px}"
    + _w({1: 34, 2: 88, 5: 92, 6: 84, 7: 120, 8: 100, 9: 84, 10: 92, 11: 96}) + _hide([4]) +
    "}"
    # 701〜1099px：25日線乖離も外す
    "@media (min-width:701px) and (max-width:1099px){" + _hide([7]) + "}"
    # 701〜859px：スマホと同じ列だけにする
    "@media (min-width:701px) and (max-width:859px){" + _hide([10, 11]) + "}"
    # 4. ★を押しやすく
    f"@media {TOUCH}{{.star-btn{{min-width:34px;min-height:38px}}}}"
)
# 見出しを検索欄のすぐ下に貼りつける（検索欄が2段になる幅でも見出しが隠れない）
CHARTS_JS = ("<script>(function(){function f(){var t=document.querySelector('.tools');"
             "if(t)document.documentElement.style.setProperty('--ux-tools',t.offsetHeight+'px')}"
             "addEventListener('resize',f);document.addEventListener('DOMContentLoaded',f);addEventListener('load',f)})();</script>")

# ---------------------------------------------------------------- 2. 売買シグナル
# 列：1コード 2銘柄名 3業種 4株価 5テクニカル 6トレンド 7オシレーター 8ファンダ 9総合 10イベント
SIGNALS = (
    # スマホ（〜760px）：1〜3列目はページ側で固定済み。残りの列の幅を固定する（イベントは最後なので可変のまま）
    "@media (max-width:760px){"
    "table.sig th,table.sig td{box-sizing:border-box}"
    + _w({4: 62, 5: 90, 6: 78, 7: 136, 8: 90, 9: 70}, "table.sig") +
    "}"
    # 761px〜：列幅を固定。銘柄名と業種は「…」で省略、入りきらない幅では枠の中で横にスクロール
    "@media (min-width:761px){"
    ".sigwrap{overflow-x:auto}"
    "table.sig{table-layout:fixed;width:max(100%,1240px)}"
    "table.sig td:nth-child(2),table.sig td:nth-child(3){overflow:hidden;text-overflow:ellipsis;white-space:nowrap}"
    + _w({1: 76, 3: 140, 4: 76, 5: 100, 6: 88, 7: 152, 8: 100, 9: 80, 10: 260}, "table.sig") +
    "}"
    "@media (min-width:761px) and (max-width:1239px){"
    "table.sig{width:max(100%,980px)}" + _hide([3], "table.sig") + _w({10: 220}, "table.sig") +
    "}"
    + SUMMARY
)

# ---------------------------------------------------------------- 2. チャート形状検索
# 列：1コード 2銘柄名 3市場 4業種 5終値 6前日比 7 1か月 8 3か月 9 25日線乖離（3・4・9はスマホで非表示）
PATTERNS = (
    ".tw table{table-layout:fixed}"
    ".tw td.n{max-width:none}"
    ".tw td:nth-child(4){overflow:hidden;text-overflow:ellipsis}"
    "@media (max-width:760px){"
    ".tw table{width:max(100%,476px)}"
    + _w({1: 66, 2: 118, 5: 70, 6: 78, 7: 72, 8: 72}, ".tw table") +
    "}"
    "@media (min-width:761px){"
    ".tw table{width:max(100%,1220px)}"
    + _w({1: 96, 3: 132, 4: 170, 5: 112, 6: 124, 7: 118, 8: 118, 9: 152}, ".tw table") +
    "}"
    "@media (min-width:761px) and (max-width:1219px){"
    ".tw table{width:max(100%,920px)}" + _hide([3, 4], ".tw table") +
    "}"
    + SUMMARY
)

# ---------------------------------------------------------------- 2. 需給分析（ランキングの表）
# 701px〜で表になる（〜700pxはカード表示なので触らない）。列幅は割合で固定し、狭い幅では見出しを2行に折り返す
def _pct(pcts):
    return "".join(f"table.rk th:nth-child({i}),table.rk td:nth-child({i}){{width:{p}%}}" for i, p in enumerate(pcts, 1))

def jukyu_css(text):
    us = "信用倍率" not in text   # 米国版は信用取引のデータが無い
    # 東証：銘柄 判定 スコア 信用倍率 株価・20日 買残の重さ 買い方の損益 大口空売り
    # 米国：銘柄 判定 スコア 空売り比率 増減 空売り日数 機関保有 25日線 時価総額
    pcts = [30, 10, 7, 9, 9, 9, 9, 8, 9] if us else [27, 12, 9, 9, 12, 10, 11, 10]
    return (
        "@media (min-width:701px){"
        "table.rk{table-layout:fixed;width:100%}"
        "table.rk th{white-space:normal;vertical-align:bottom}"
        "table.rk td{overflow:hidden;text-overflow:ellipsis}"
        + _pct(pcts) +
        "}"
        # 市場の切り替え（全て／プライム…）を押しやすく
        f"@media {TOUCH}{{#mkt.chips button,.chips.sm button{{min-height:34px}}}}"
    )

# ---------------------------------------------------------------- 4. その他のページ
PAGE_CSS = {
    "charts.html": CHARTS,
    "signals.html": SIGNALS,
    "patterns.html": PATTERNS,
    "fundamentals.html": f"@media {TOUCH}{{#rkopenall,#rkcloseall{{min-height:34px}}}}",
    "sector_mom.html": SUMMARY,
    "gap.html": SUMMARY,
    "gap_short.html": SUMMARY,
    "nikkei225.html": SUMMARY + f"@media {TOUCH}{{#cseg button,#eseg button{{min-height:32px}}}}",
}
PAGE_JS = {"charts.html": CHARTS_JS}

# 銘柄ごとのページは共通CSSファイルに足す（数千ファイルを書き換えずに済む）
ASSET_CSS = {
    # 個別チャート：★、出来高／代金の切り替え、「指標の計算方法」
    os.path.join("assets", "chart.css"):
        f"@media {TOUCH}{{#star.star-btn{{min-width:34px;min-height:34px}}"
        ".vmode button,.vmode.nw button{padding-top:7px;padding-bottom:7px}"
        "details.nt summary{padding-top:7px;padding-bottom:7px}}",
    # 株式分析ダッシュボード：監視に追加、内訳・推移、期間、指標を選ぶ、計上額／構成比
    os.path.join("one", "assets", "one.css"):
        f"@media {TOUCH}{{.tbtn,.tgl,.seg button,.kbseg button{{min-height:32px}}}}",
    # 業績ページ：表、計上額／構成比
    os.path.join("gyoseki", "assets", "style.css"):
        f"@media {TOUCH}{{.tbtn,.kbseg button{{min-height:32px;min-width:32px}}}}",
}

RE_HTML = re.compile(r"<!--ux-fix:[^>]*-->.*?<!--/ux-fix-->", re.S)
RE_CSS = re.compile(r"/\*ux-fix:[^*]*\*/.*?/\*/ux-fix\*/", re.S)


def html_block(name, text):
    css = COMMON
    if name == "jukyu.html":
        css += jukyu_css(text)
    css += PAGE_CSS.get(name, "")
    return f'<!--ux-fix:{VER}--><style id="ux-fix">{css}</style>{PAGE_JS.get(name, "")}<!--/ux-fix-->'


def fix_html(name, text):
    t = RE_HTML.sub("", text)
    i = t.lower().rfind("</head>")
    if i < 0:
        return None
    return t[:i] + html_block(name, t) + t[i:]


def fix_css(rel, text):
    t = RE_CSS.sub("", text).rstrip()
    return t + f"\n/*ux-fix:{VER}*/{COMMON}{ASSET_CSS[rel]}/*/ux-fix*/\n"


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else ROOT
    changed = 0
    # 各ページ（名前が小文字で始まるもの。銘柄コードのページ・フォルダ内の銘柄ページは除く）
    for d in [root, os.path.join(root, "one")]:
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if not f.endswith(".html") or not f[:1].islower():
                continue
            if d != root and f != "index.html":
                continue
            p = os.path.join(d, f)
            try:
                with open(p, encoding="utf-8") as fh:
                    s = fh.read()
            except (UnicodeDecodeError, OSError):
                continue
            t = fix_html(f if d == root else "one/" + f, s)
            if t is not None and t != s:
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write(t)
                changed += 1
    for rel in ASSET_CSS:
        p = os.path.join(root, rel)
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as fh:
            s = fh.read()
        t = fix_css(rel, s)
        if t != s:
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(t)
            changed += 1
    print(f"ux-fix: {changed}件を更新")


if __name__ == "__main__":
    main()
