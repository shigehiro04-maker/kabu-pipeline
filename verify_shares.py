#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
発行済株式数の照合（株探の銘柄ページの発行済株式数と比べる）  2026-11-02 作成

時価総額・PER・PBR・EPS はすべて株数に依存するので、株数がずれると全部ずれる。
対象（1件 3 秒の間隔で取りに行く。無料・登録不要）:
  ・分割台帳 data/splits.csv で、直近の決算期末より後に分割・併合した銘柄（分割の反映漏れが起きやすい）
  ・それ以外から無作為に --sample 件（既定 100）
差が 3% を超えたものを fundamentals/verify/shares_YYYYMMDD.csv に出す。

  ./.venv/bin/python verify_shares.py              # 分割銘柄＋無作為100件
  ./.venv/bin/python verify_shares.py --all        # 全銘柄（約3時間）
"""
import argparse, re, time, random
from datetime import date
from pathlib import Path

import pandas as pd
import requests

BASE = Path(__file__).resolve().parent
OUT = BASE / "fundamentals" / "verify"
OUT.mkdir(parents=True, exist_ok=True)


class Blocked(Exception):
    pass


def kabutan(code):
    r = requests.get(f"https://kabutan.jp/stock/?code={code}",
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    if r.status_code in (403, 429):
        raise Blocked(r.status_code)
    if r.status_code != 200:
        return None
    t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.text)).replace("&nbsp;", " ")
    m = re.search(r"発行済株式数 ([\d,]+) ?株", t)
    return float(m.group(1).replace(",", "")) if m else None


def save_external(fetched):
    """取れた株数を fundamentals/shares_external.csv に追記（同じ銘柄は新しい方を残す）。
    reconcile_edinet.py がこれを使って株数・時価総額を直す。"""
    p = BASE / "fundamentals" / "shares_external.csv"
    new = pd.DataFrame(fetched)
    if p.exists():
        new = pd.concat([pd.read_csv(p, dtype={"コード": str}, encoding="utf-8-sig"), new])
    new.drop_duplicates("コード", keep="last").to_csv(p, index=False, encoding="utf-8-sig")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=100)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--codes-file", help="この一覧（1行1コード）の銘柄だけ照合する（shares_crosscheck.py が出す疑わしい銘柄）")
    a = ap.parse_args()
    fu = pd.read_csv(BASE / "fundamentals/fundamentals_latest.csv", dtype={"コード": str}, encoding="utf-8-sig")
    sp = pd.read_csv(BASE / "data/splits.csv", dtype={"code": str})
    fy = dict(zip(fu["コード"], fu["決算期"]))
    split_codes = sorted({r.code for r in sp.itertuples()
                          if r.code in fy and isinstance(fy[r.code], str) and str(r.ex_date)[:10] > fy[r.code]})
    rest = [c for c in fu["コード"] if c not in split_codes]
    random.seed(int(date.today().strftime("%Y%m%d")))
    targets = split_codes + (rest if a.all else random.sample(rest, min(a.sample, len(rest))))
    if a.codes_file:
        want = [l.strip() for l in open(a.codes_file, encoding="utf-8") if l.strip()]
        targets = [c for c in want if c in set(fu["コード"])]
        split_codes = [c for c in split_codes if c in targets]
    F = fu.set_index("コード")
    rows, n_ok, fetched = [], 0, []
    for i, c in enumerate(targets):
        try:
            q = kabutan(c)
        except Blocked as e:
            print(f"アクセスを断られたので中断します（{e}）", flush=True)
            break
        except Exception:  # noqa
            q = None
        time.sleep(3)
        if not q:
            continue
        n_ok += 1
        fetched.append(dict(コード=c, 外部株数=q, 出所="株探", 取得日=date.today().isoformat()))
        if len(fetched) % 10 == 0:
            save_external(fetched)
        ours = F.at[c, "発行済株式総数"]
        diff = (ours - q) / q if pd.notna(ours) else None
        if diff is None or abs(diff) > 0.03:
            rows.append(dict(コード=c, 銘柄名=F.at[c, "銘柄名"], 自前株数=ours, 外部株数=q,
                             比率=None if diff is None else round(ours / q, 3),
                             決算期=F.at[c, "決算期"], 分割台帳=("あり" if c in split_codes else ""),
                             自前時価総額=F.at[c, "時価総額"]))
        if rows:
            pd.DataFrame(rows).to_csv(OUT / f"shares_{date.today():%Y%m%d}.csv", index=False, encoding="utf-8-sig")
        if (i + 1) % 25 == 0:
            print(f"{i+1}/{len(targets)} 件  不一致 {len(rows)}", flush=True)
    save_external(fetched)
    df = pd.DataFrame(rows)
    p = OUT / f"shares_{date.today():%Y%m%d}.csv"
    df.to_csv(p, index=False, encoding="utf-8-sig")
    print(f"照合 {n_ok} 件（うち分割台帳 {len(split_codes)}）  株数の不一致 {len(df)} 件 → {p}")
    print("DONE")


if __name__ == "__main__":
    main()
