"""両版の make_home.py に「デイトレ チャートパターン」のカードを足す（何度実行しても同じ）"""
import os
import shutil

CARD = '''

def daytrade_card():
    """デイトレ チャートパターン（デイトレパターン/dtp_scan.py が作る daytrade/latest.json）へのカード"""
    f = SITE / "daytrade.html"
    if not f.exists():
        return ""
    big, rest, foot = None, "", f"更新 {mtime(f)}"
    try:
        D = json.load(open(SITE / "daytrade" / "latest.json", encoding="utf-8"))
        sig = D.get("sig", [])
        up = sum(1 for s in sig if D["patterns"].get(s[2], [0, 0, 0])[2] > 0)
        lab = "取引中のシグナル" if D.get("live") else f'{D["day"][5:].replace("-", "/")}のシグナル'
        big = (lab, f"{len(sig):,}件", "")
        rest = (f'<span class="u">買い <b>{up:,}</b></span><span class="d">売り <b>{len(sig) - up:,}</b></span>'
                f'<span>形成中 <b>{len(D.get("form", [])):,}</b></span>')
        foot = f'更新 {D.get("made", "")[5:].replace("-", "/")}'
    except Exception:
        pass
    return card("./daytrade.html", "デイトレ チャートパターン",
                "5分足でダブルボトム・三尊・フラッグなど22パターンを自動で検出。過去の勝率・値幅つき",
                big, rest, foot)
'''

for base in ("株分析", "米国株分析"):
    p = os.path.join(os.path.expanduser("~"), base, "make_home.py")
    t = open(p, encoding="utf-8").read()
    if "def daytrade_card" in t:
        print(p, "済み")
        continue
    shutil.copyfile(p, p + ".pre_daytrade")
    assert t.count("    out.append(pattern_card())\n") == 1, p
    t = t.replace("    out.append(pattern_card())\n", "    out.append(pattern_card())\n    out.append(daytrade_card())\n")
    i = t.index("\ndef pattern_card():")
    j = t.index("\n\n\n", i)
    t = t[:j] + CARD + t[j:]
    open(p, "w", encoding="utf-8").write(t)
    print(p, "追加")
