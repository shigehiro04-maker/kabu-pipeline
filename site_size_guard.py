#!/usr/bin/env python3
"""公開フォルダ（data/charts）の容量を確かめ、GitHub Pages の上限（1GB）を超えないようにする。

deploy_github.sh の最初に毎回呼ばれる。終了コード 0=公開してよい、1=公開を中止。
  ・WARN_MB を超えたら注意を logs/run_daily.log に1行残す
  ・SHRINK_MB を超えたら5分足のファイル（data/charts/intra/*.js）を古い日から削って
    12日分 → 7日分 → 6日分まで減らす（チャートの5日・1日はそのまま見られる。10日は短くなる）
  ・それでも LIMIT_MB を超えたら公開を中止して記録する
手動で容量だけ見る:  python3 site_size_guard.py --report
"""
import glob
import json
import os
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(BASE, "data", "charts")
LOG = os.path.join(BASE, "logs", "run_daily.log")
WARN_MB, SHRINK_MB, LIMIT_MB = 850, 950, 1000
STEPS = [7, 6]            # 5分足を減らすときの日数（5日表示＋助走）


def site_mb():
    t = 0
    for d, ds, fs in os.walk(SITE):
        ds[:] = [x for x in ds if x != ".git"]
        for f in fs:
            if ".pre_" in f or f == ".DS_Store":       # .gitignore で公開しないもの
                continue
            try:
                t += os.path.getsize(os.path.join(d, f))
            except OSError:
                pass
    return t / 1e6


def intra_mb():
    return sum(os.path.getsize(p) for p in glob.glob(os.path.join(SITE, "intra", "*.js"))) / 1e6


def note(msg):
    line = f"[{time.strftime('%F %T')}] 公開容量: {msg}"
    print(line)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def trim_intra(days):
    n = 0
    for p in glob.glob(os.path.join(SITE, "intra", "*.js")):
        try:
            s = open(p, encoding="utf-8").read()
            d = json.loads(s[s.index("=") + 1:].rstrip().rstrip(";"))
        except Exception:
            continue
        if len(d["d"]) <= days:
            continue
        cut = len(d["d"]) - days
        d["d"] = d["d"][cut:]
        d["r"] = [[r[0] - cut] + r[1:] for r in d["r"] if r[0] >= cut]
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("var INTRA=" + json.dumps(d, ensure_ascii=False, separators=(",", ":")) + ";\n")
        n += 1
    return n


def main():
    mb = site_mb()
    print(f"公開サイズ {mb:.0f}MB（うち5分足 {intra_mb():.0f}MB）／上限 {LIMIT_MB}MB")
    if "--report" in sys.argv:
        return 0
    if mb > SHRINK_MB:
        for days in STEPS:
            n = trim_intra(days)
            mb = site_mb()
            note(f"{SHRINK_MB}MBを超えたため5分足を{days}日分に減らしました（{n}銘柄、現在{mb:.0f}MB）")
            if mb <= SHRINK_MB:
                break
    if mb > LIMIT_MB:
        note(f"{mb:.0f}MB で上限{LIMIT_MB}MBを超えるため、GitHub Pages への公開を中止しました")
        return 1
    if mb > WARN_MB:
        note(f"{mb:.0f}MB（注意の目安{WARN_MB}MB超え。上限は{LIMIT_MB}MB）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
