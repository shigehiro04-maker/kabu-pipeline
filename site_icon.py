#!/usr/bin/env python3
"""東証 株分析のアイコン（2026-11-13、11-14 左上に日の丸）を公開フォルダの全HTMLに入れる。

  icons/icon-black.svg      … ブラウザが明るい表示のときのタブのアイコン
  icons/icon-white.svg      … ブラウザが暗い表示のときのタブのアイコン
  icons/apple-touch-icon.png … iPhone のホーム画面に追加したときのアイコン（黒・180px）
を data/charts/ にコピーし、各ページの <head> にリンクを入れる。
・何度実行しても同じ結果（目印のコメントで前回分を置き換える）
deploy_github.sh から毎回自動で呼ばれる。手動なら:  python3 ~/株分析/site_icon.py
"""
import os, re, shutil

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(BASE, "data", "charts")
SRC = os.path.join(BASE, "icons")
FILES = ["icon-black.svg", "icon-white.svg", "apple-touch-icon.png", "icon-512.png"]
P = "/kabu-charts/"          # GitHub Pages の公開パス（どの階層のページからでも同じ場所を指す）
VER = "v3"
BLOCK = (f'<!--site-icon:{VER}-->'
         f'<link rel="icon" type="image/svg+xml" href="{P}icon-black.svg?v=3" media="(prefers-color-scheme: light)">'
         f'<link rel="icon" type="image/svg+xml" href="{P}icon-white.svg?v=3" media="(prefers-color-scheme: dark)">'
         f'<link rel="apple-touch-icon" href="{P}apple-touch-icon.png?v=3">'
         f'<!--/site-icon-->')
RE = re.compile(r"<!--site-icon:[^>]*-->.*?<!--/site-icon-->", re.S)


def fix(text):
    if RE.search(text):
        return RE.sub(BLOCK, text, count=1)
    i = text.lower().find("</head>")
    return text if i < 0 else text[:i] + BLOCK + text[i:]


def main():
    for f in FILES:
        s = os.path.join(SRC, f)
        if os.path.exists(s):
            shutil.copy2(s, os.path.join(ROOT, f))
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
    print(f"site-icon: {n} ファイルを更新")


if __name__ == "__main__":
    main()
