#!/usr/bin/env python3
"""公開フォルダ（data/charts）の全HTMLに、スマホ（特にiPhoneのホーム画面から開いたとき）で
ページの最下部まで見られるようにする補正を入れる。

iPhoneでホーム画面に追加したページ（Webアプリ表示）は、画面下のホームバー付近の高さが
正しく計算されず、ページの最後の部分が画面外に残ってスクロールで届かないことがある。
対策として、トップレベルで開いたスマホ表示のときだけ、ページ末尾に余白を足す。
・PCや、他のページの iframe の中で開いたチャートには何も起きない（表示は変わらない）
・何度実行しても同じ結果（目印のコメントで前回分を置き換える）
deploy_github.sh から毎回自動で呼ばれる。手動なら:  python3 ~/株分析/add_mobile_fix.py
"""
import os, re, sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "charts")
VER = "v1"
HEAD = f"""<!--mobile-fix:{VER}--><style id="mobile-fix">
.mf-spacer{{display:none}}
html.mf-sa .mf-spacer{{display:block;height:calc(env(safe-area-inset-bottom,0px) + 110px)}}
html.mf-sa .detail .inner{{padding-bottom:calc(env(safe-area-inset-bottom,0px) + 140px)}}
</style><script>(function(){{try{{if(window.top!==window.self)return;
var sa=navigator.standalone===true||matchMedia('(display-mode: standalone)').matches;
var touch=matchMedia('(pointer: coarse)').matches;
if(sa||touch)document.documentElement.classList.add('mf-sa');}}catch(e){{}}}})();</script><!--/mobile-fix-->"""
TAIL = '<!--mobile-fix-spacer--><div class="mf-spacer" aria-hidden="true"></div><!--/mobile-fix-spacer-->'

RE_HEAD = re.compile(r"<!--mobile-fix:[^>]*-->.*?<!--/mobile-fix-->", re.S)
RE_TAIL = re.compile(r"<!--mobile-fix-spacer-->.*?<!--/mobile-fix-spacer-->", re.S)

def fix(text):
    if "<html" not in text.lower()[:3000] and "<body" not in text.lower():
        return None  # HTMLの断片やリダイレクトだけのファイルは触らない
    t = RE_HEAD.sub("", text)
    t = RE_TAIL.sub("", t)
    i = t.lower().find("</head>")
    if i >= 0:
        t = t[:i] + HEAD + t[i:]
    else:
        m = re.search(r"<body[^>]*>", t, re.I)
        if not m:
            return None
        t = t[:m.start()] + HEAD + t[m.start():]
    j = t.lower().rfind("</body>")
    t = (t[:j] + TAIL + t[j:]) if j >= 0 else (t + TAIL)
    return t

def main():
    changed = seen = 0
    for d, dirs, files in os.walk(ROOT):
        dirs[:] = [x for x in dirs if x != ".git"]
        for f in files:
            if not f.endswith(".html"):
                continue
            p = os.path.join(d, f)
            seen += 1
            try:
                with open(p, encoding="utf-8") as fh:
                    s = fh.read()
            except UnicodeDecodeError:
                continue
            t = fix(s)
            if t is not None and t != s:
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write(t)
                changed += 1
    print(f"mobile-fix: {seen}件中 {changed}件を更新")

if __name__ == "__main__":
    main()
