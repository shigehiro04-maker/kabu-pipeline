#!/usr/bin/env python3
"""公開フォルダ（data/charts）の全HTMLで、PCの広い画面では本文の横幅を広げる（2026-11-13）。

各ページは .wrap か main の max-width（1100〜1500px）で横幅を決めている。
画面幅が 1280px 以上のときだけ、その上限を WIDE（px）まで広げる。スマホ・タブレットの表示は変わらない。
・何度実行しても同じ結果（目印のコメントで前回分を置き換える）
deploy_github.sh から毎回自動で呼ばれる。手動なら:  python3 ~/株分析/pc_wide.py
"""
import os, re

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "charts")
WIDE = 1680
VER = "v1"
BLOCK = (f'<!--pc-wide:{VER}--><style id="pc-wide">@media (min-width:1280px){{'
         f'body>.wrap,body>main,body>div.wrap{{max-width:{WIDE}px!important}}}}</style><!--/pc-wide-->')
RE = re.compile(r"<!--pc-wide:[^>]*-->.*?<!--/pc-wide-->", re.S)


def fix(text):
    if RE.search(text):
        new = RE.sub(BLOCK, text, count=1)
    else:
        i = text.lower().find("</head>")
        if i < 0:
            return text
        new = text[:i] + BLOCK + text[i:]
    return new


def main():
    n = 0
    for d, _, fs in os.walk(ROOT):
        if "/.git" in d:
            continue
        for f in fs:
            if not f.endswith(".html"):
                continue
            p = os.path.join(d, f)
            try:
                t = open(p, encoding="utf-8").read()
            except Exception:
                continue
            u = fix(t)
            if u != t:
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write(u)
                n += 1
    print(f"pc-wide: {n} ファイルを更新（上限 {WIDE}px）")


if __name__ == "__main__":
    main()
