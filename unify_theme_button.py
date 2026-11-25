#!/usr/bin/env python3
"""公開フォルダ（data/charts）の全HTMLで、明暗（ライト／ダーク）切り替えボタンの見た目と動きを統一する。

・ボタンはスマホのスイッチのようなスライド式（つまみが左＝ライト・太陽、右＝ダーク・月）にそろえる
・設定は全ページ共通で localStorage の 'fdb-theme' に保存（どのページで切り替えても他のページに引き継ぐ）
・ボタンが無かったページ（チャート一覧・需給分析・日経225・銘柄一覧・個別チャート・業績ページ・チャート形状検索・理論株価）には追加する
・ドル円ページの「自動／ライト／ダーク」も「明暗」ボタン1つに置き換える
・他のページの iframe の中に埋め込まれたチャートでは、追加したボタンは表示しない（親ページ側で切り替える）
・何度実行しても同じ結果（目印のコメントで前回分を置き換える）
run_daily.sh と deploy_github.sh から毎回自動で呼ばれる。手動なら:  python3 ~/株分析/unify_theme_button.py（米国版は ~/米国株分析/unify_theme_button.py）
"""
import os, re, sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "charts")
VER = "v3"
# ボタンの中身：スマホのスイッチのように、つまみが左（ライト・太陽）⇔右（ダーク・月）へスライドする
_SUN = ('<svg class="kb-sun" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.4" '
        'stroke-linecap="round"><circle cx="12" cy="12" r="4.3"/><path d="M12 2.2v2.3M12 19.5v2.3M2.2 12h2.3M19.5 12h2.3'
        'M5.1 5.1l1.6 1.6M17.3 17.3l1.6 1.6M5.1 18.9l1.6-1.6M17.3 6.7l1.6-1.6"/></svg>')
_MOON = ('<svg class="kb-moon" viewBox="0 0 24 24" aria-hidden="true" fill="currentColor">'
         '<path d="M20.2 14.6A8.4 8.4 0 0 1 9.4 3.8a.6.6 0 0 0-.8-.7A9.2 9.2 0 1 0 20.9 15.4a.6.6 0 0 0-.7-.8z"/></svg>')
LABEL = (f'<span class="kb-trk kb-l">{_SUN}</span><span class="kb-trk kb-r">{_MOON}</span>'
         f'<span class="kb-knob">{_SUN}{_MOON}</span>')
ARIA = "明暗を切り替え（ライト／ダーク）"

# ---- 全ページ共通：<head> の先頭に入れる（保存済みの明暗を描画前に反映＋ボタンの見た目） ----
HEAD = f"""<!--kb-theme:{VER}--><script>(function(){{var d=document.documentElement,
m=/[?&#]theme=(dark|light)/.exec(location.search+location.hash),t=m&&m[1];
if(!t){{try{{t=localStorage.getItem('fdb-theme')}}catch(e){{}}}}
if(t==='dark'||t==='light')d.setAttribute('data-theme',t);
try{{if(window.top!==window.self)d.classList.add('kb-embed')}}catch(e){{d.classList.add('kb-embed')}}}})();</script>
<style id="kb-theme">
:root{{--kb-fg:#1f1f1e;--kb-line:#d6d5ce;--kb-hover:rgba(0,0,0,.05)}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--kb-fg:#ecebe6;--kb-line:#3b3b38;--kb-hover:rgba(255,255,255,.08)}}}}
:root[data-theme="dark"]{{--kb-fg:#ecebe6;--kb-line:#3b3b38;--kb-hover:rgba(255,255,255,.08)}}
/* スイッチ本体（トラック） */
:root{{--kb-trk:#e8e7e1;--kb-knob:#fff;--kb-ico:#d08a00;--kb-dim:#a9a79f}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--kb-trk:#2b2b29;--kb-knob:#45453f;--kb-ico:#f3d36a;--kb-dim:#6f6e68}}}}
:root[data-theme="dark"]{{--kb-trk:#2b2b29;--kb-knob:#45453f;--kb-ico:#f3d36a;--kb-dim:#6f6e68}}
:root button.kb-theme.kb-theme{{-webkit-appearance:none;appearance:none;position:relative;display:inline-block;box-sizing:border-box;
width:54px;height:30px;min-width:54px;min-height:0;padding:0;border:1px solid var(--kb-line);border-radius:15px;background:var(--kb-trk);
color:var(--kb-fg);font-size:0;line-height:0;cursor:pointer;box-shadow:inset 0 1px 2px rgba(0,0,0,.08);vertical-align:middle;flex-shrink:0;
overflow:hidden;-webkit-tap-highlight-color:transparent;transition:background .3s,border-color .3s}}
:root button.kb-theme.kb-theme:focus-visible{{outline:2px solid #2a78d6;outline-offset:2px}}
:root button.kb-theme.kb-theme svg{{display:block;width:100%;height:100%}}
/* 両端の小さなアイコン（つまみが無い側だけ見える） */
:root button.kb-theme.kb-theme .kb-trk{{position:absolute;top:50%;width:13px;height:13px;margin-top:-6.5px;color:var(--kb-dim);transition:opacity .3s}}
:root button.kb-theme.kb-theme .kb-l{{left:7px;opacity:0}}
:root button.kb-theme.kb-theme .kb-r{{right:7px;opacity:1}}
/* つまみ */
:root button.kb-theme.kb-theme .kb-knob{{position:absolute;top:2px;left:2px;width:24px;height:24px;border-radius:50%;background:var(--kb-knob);
color:var(--kb-ico);box-shadow:0 1px 3px rgba(0,0,0,.25),0 0 0 .5px rgba(0,0,0,.06);transform:translateX(0);
transition:transform .32s cubic-bezier(.3,1.35,.5,1),background .3s,color .3s}}
:root button.kb-theme.kb-theme:active .kb-knob{{width:28px}}
:root button.kb-theme.kb-theme .kb-knob svg{{position:absolute;inset:0;margin:auto;width:15px;height:15px;transition:opacity .25s,transform .35s}}
:root button.kb-theme.kb-theme .kb-knob .kb-sun{{opacity:1;transform:none}}
:root button.kb-theme.kb-theme .kb-knob .kb-moon{{opacity:0;transform:rotate(-90deg) scale(.4)}}
/* ダーク表示中：つまみを右へ */
@media (prefers-color-scheme:dark){{
:root:not([data-theme="light"]) button.kb-theme.kb-theme .kb-knob{{transform:translateX(24px)}}
:root:not([data-theme="light"]) button.kb-theme.kb-theme:active .kb-knob{{transform:translateX(20px)}}
:root:not([data-theme="light"]) button.kb-theme.kb-theme .kb-knob .kb-sun{{opacity:0;transform:rotate(90deg) scale(.4)}}
:root:not([data-theme="light"]) button.kb-theme.kb-theme .kb-knob .kb-moon{{opacity:1;transform:none}}
:root:not([data-theme="light"]) button.kb-theme.kb-theme .kb-l{{opacity:1}}
:root:not([data-theme="light"]) button.kb-theme.kb-theme .kb-r{{opacity:0}}}}
:root[data-theme="dark"] button.kb-theme.kb-theme .kb-knob{{transform:translateX(24px)}}
:root[data-theme="dark"] button.kb-theme.kb-theme:active .kb-knob{{transform:translateX(20px)}}
:root[data-theme="dark"] button.kb-theme.kb-theme .kb-knob .kb-sun{{opacity:0;transform:rotate(90deg) scale(.4)}}
:root[data-theme="dark"] button.kb-theme.kb-theme .kb-knob .kb-moon{{opacity:1;transform:none}}
:root[data-theme="dark"] button.kb-theme.kb-theme .kb-l{{opacity:1}}
:root[data-theme="dark"] button.kb-theme.kb-theme .kb-r{{opacity:0}}
@media (prefers-reduced-motion:reduce){{:root button.kb-theme.kb-theme *{{transition:none!important}}}}
/* 全ページ共通の置き場所：ページ右上の角 */
:root button.kb-theme.kb-theme.kb-corner{{position:absolute;top:12px;right:16px;z-index:60;margin:0;float:none}}
@media (max-width:700px){{:root button.kb-theme.kb-theme.kb-corner{{top:10px;right:12px}}}}
/* 右上のスイッチの下に見えない「よけ」を置き、見出しの文字やボタンがスイッチと重ならないようにする */
.kb-spacer{{float:right;width:84px;height:46px;pointer-events:none}}
@media (max-width:700px){{.kb-spacer{{width:76px;height:44px}}}}
html.kb-embed .kb-spacer{{display:none}}
html.kb-embed button.kb-theme[data-kb]{{display:none}}
__KB_RESERVE__
</style><!--/kb-theme-->"""

# ---- 追加したボタン用の切り替え処理（</body> の直前） ----
TAIL = """<!--kb-theme-js--><script>(function(){var bs=document.querySelectorAll('button.kb-theme[data-kb]');
for(var i=0;i<bs.length;i++)bs[i].addEventListener('click',function(){var b=this,d=document.documentElement,
cur=d.getAttribute('data-theme')||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'),n=cur==='dark'?'light':'dark';
d.setAttribute('data-theme',n);try{localStorage.setItem('fdb-theme',n)}catch(e){}
var f=document.querySelectorAll('iframe');for(var j=0;j<f.length;j++){try{f[j].contentWindow.postMessage({chartTheme:n},'*')}catch(e){}}
var k=b.getAttribute('data-kb');
if(k==='reload')location.reload();
else if(k==='msg')window.postMessage({chartTheme:n},'*');
else if(k==='fn'&&typeof window.__kbRedraw==='function')window.__kbRedraw();});})();</script><!--/kb-theme-js-->"""

RE_HEAD = re.compile(r"<!--kb-theme:[^>]*-->.*?<!--/kb-theme-->", re.S)
RE_TAIL = re.compile(r"<!--kb-theme-js-->.*?<!--/kb-theme-js-->", re.S)
RE_BTN = re.compile(r"<!--kb-btn--><button[^>]*\bdata-kb=.*?<!--/kb-btn-->", re.S)  # 追加したボタンだけ（既存ボタンは残す）


def new_btn(kind, style=""):
    st = f' style="{style}"' if style else ""
    return (f'<!--kb-btn--><button class="kb-theme" id="kbTheme" type="button" data-kb="{kind}" '
            f'aria-label="{ARIA}" title="{ARIA}"{st}>{LABEL}</button><!--/kb-btn-->')


# 既存の明暗ボタン（各ページ固有の処理はそのまま使い、見た目と表記だけそろえる）
RE_OLD = re.compile(r'<button\b([^>]*\bid="(?:theme|themeBtn|thm|dtheme)"[^>]*)>(.*?)</button>', re.S)


def restyle_old(m):
    attrs = m.group(1)
    cm = re.search(r'\bclass="([^"]*)"', attrs)
    if cm:
        cls = cm.group(1).split()
        if "kb-theme" not in cls:
            cls.append("kb-theme")
        attrs = attrs[:cm.start()] + f'class="{" ".join(cls)}"' + attrs[cm.end():]
    else:
        attrs = ' class="kb-theme"' + attrs
    attrs = re.sub(r'\s(aria-label|title)="[^"]*"', "", attrs)
    if "type=" not in attrs:
        attrs += ' type="button"'
    attrs += f' aria-label="{ARIA}" title="{ARIA}"'
    return f"<button{attrs}>{LABEL}</button>"


def insert_after(t, pat, html, flags=0):
    m = re.search(pat, t, flags)
    if not m:
        return t, False
    return t[:m.end()] + html + t[m.end():], True


def insert_before(t, pat, html, flags=0):
    m = re.search(pat, t, flags)
    if not m:
        return t, False
    return t[:m.start()] + html + t[m.start():], True


def page_specific(rel, t):
    """ボタンが無いページへの追加と、ページ固有の手直し"""
    name = rel.replace(os.sep, "/")
    base = os.path.basename(name)

    if name == "charts.html":
        # 明暗の指定（data-theme）に従うよう、OS連動だけだったダークの配色を書き換える
        m = re.search(r"@media\(prefers-color-scheme:dark\)\{\s*:root\{([^}]*)\}\s*\}", t)
        if m:
            v = m.group(1)
            t = (t[:m.start()] + '@media(prefers-color-scheme:dark){:root:not([data-theme="light"]){' + v + "}}"
                 + ':root[data-theme="dark"]{' + v + "}" + t[m.end():])
        t, _ = insert_before(t, r"</h1>", new_btn("plain", "float:right;margin-top:2px"))
        return t

    if name in ("jukyu.html", "analyst.html"):
        m = re.search(r"<header>\s*<h1>.*?</h1>", t, re.S)
        if m:
            i = m.end() - len("</h1>")
            t = t[:i] + new_btn("reload", "float:right;margin-top:3px") + t[i:]
        return t

    if name == "nikkei225.html":
        m = re.search(r'<div class="top"><div class="in">.*?</nav>', t, re.S)
        if m:
            t = t[:m.end()] + new_btn("reload") + t[m.end():]
        return t

    if name == "one/index.html":
        m = re.search(r"<header>.*?</header>", t, re.S)
        if m:
            i = m.end() - len("</header>")
            t = t[:i] + new_btn("plain", "margin-left:auto;align-self:center") + t[i:]
        return t

    if name == "usdjpy.html":
        # 「自動／ライト／ダーク」の3択を「明暗」ボタン1つに置き換え、保存先も共通の 'fdb-theme' に
        t = re.sub(r'<div class="seg" id="theme"[^>]*>.*?</div>\s*', "", t, count=1, flags=re.S)
        t, _ = insert_after(t, r'<div class="tools">\s*', new_btn("fn"))
        t = t.replace("localStorage.getItem('usdjpy-theme')", "localStorage.getItem('fdb-theme')")
        if "window.__kbRedraw" not in t:
            t = t.replace("function drawAll", "window.__kbRedraw=drawAll;function drawAll", 1)
        return t

    if name.startswith("gyoseki/") and base.endswith(".html"):
        m = re.search(r'<div class="eyebrow">', t)
        if m:
            t = t[:m.end()] + new_btn("reload", "float:right;margin-top:-4px") + t[m.end():]
        return t

    # チャート形状検索・理論株価にはボタンが無かったので追加する（2026-11-14）。置き場所は右上の角（move_to_corner）
    if name in ("patterns.html", "valuation.html", "daytrade.html"):
        t, _ = insert_after(t, r"<body[^>]*>", new_btn("plain"), re.I)
        return t

    # 個別チャート（data/charts/XXXX.html）: 「ダッシュボード ›」の右に置く
    if "/" not in name:
        m = re.search(r'<a class="dash"[^>]*>[^<]*</a>', t)
        if m:
            t = t[:m.end()] + new_btn("msg", "align-self:center") + t[m.end():]
        return t
    return t


RE_ANY_BTN = re.compile(r'(?:<!--kb-btn-->)?<button\b(?=[^>]*\bkb-theme\b)(?![^>]*\bid="dtheme")[^>]*>.*?</button>(?:<div class="kb-spacer"[^>]*></div>)?(?:<!--/kb-btn-->)?', re.S)


def reserve_css(rel):
    """右上のスイッチと重ならないよう、ページごとに見出し行の右側をあける"""
    name = rel.replace(os.sep, "/")
    return RESERVE.get(name, RESERVE.get("*/" + name.split("/")[0] if "/" in name else "", ""))


RESERVE = {}


def move_to_corner(t):
    """明暗スイッチを本文の先頭へ移し、ページ右上の角に固定配置する（詳細画面内のスイッチは除く）"""
    m = RE_ANY_BTN.search(t)
    if not m:
        return t
    btn = m.group(0)
    t = t[:m.start()] + t[m.end():]
    btn = re.sub(r'\sstyle="[^"]*"', "", btn, count=1)
    btn = re.sub(r'class="([^"]*)"', lambda c: 'class="' + (c.group(1) if "kb-corner" in c.group(1) else c.group(1) + " kb-corner") + '"', btn, count=1)
    btn = re.sub(r'^<!--kb-btn-->|<div class="kb-spacer"[^>]*></div>|<!--/kb-btn-->$', "", btn)
    btn = "<!--kb-btn-->" + btn + '<div class="kb-spacer" aria-hidden="true"></div><!--/kb-btn-->'
    b = re.search(r"<body[^>]*>", t, re.I)
    if not b:
        return t
    return t[:b.end()] + btn + t[b.end():]


def fix(rel, text):
    low = text.lower()
    if "<html" not in low[:3000] and "<body" not in low:
        return None
    t = RE_HEAD.sub("", text)
    t = RE_TAIL.sub("", t)
    t = RE_BTN.sub("", t)
    t = RE_OLD.sub(restyle_old, t)
    t = page_specific(rel, t)
    t = move_to_corner(t)
    # <head> の直後（charset の後）に入れて、CSSより先に明暗を確定させる
    m = re.search(r"<meta[^>]*charset[^>]*>", t, re.I) or re.search(r"<head[^>]*>", t, re.I)
    if not m:
        return None
    t = t[:m.end()] + HEAD.replace('__KB_RESERVE__', reserve_css(rel)) + t[m.end():]
    if "data-kb=" in RE_HEAD.sub("", t):
        j = t.lower().rfind("</body>")
        t = (t[:j] + TAIL + t[j:]) if j >= 0 else (t + TAIL)
    return t


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else ROOT
    changed = seen = 0
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x != ".git"]
        for f in files:
            if not f.endswith(".html"):
                continue
            p = os.path.join(d, f)
            rel = os.path.relpath(p, root)
            seen += 1
            try:
                with open(p, encoding="utf-8") as fh:
                    s = fh.read()
            except UnicodeDecodeError:
                continue
            t = fix(rel, s)
            if t is not None and t != s:
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write(t)
                changed += 1
    print(f"theme-button: {seen}ファイル中 {changed}件を更新")


if __name__ == "__main__":
    main()
