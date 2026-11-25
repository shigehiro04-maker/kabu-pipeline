"""定義表CSV（正本）を検証し、screening_config.sqlite を作り直す。

使い方（~/株分析 で実行）:
  .venv/bin/python screening_config/build_config.py

検証する内容
  1. 条件ID・ランキングIDの重複
  2. 状態・NULLの扱い・データ源・良い向き・並び順が決められた値か
  3. 代替条件ID／ランキングが参照する条件IDが存在するか
  4. 状態=active の「既存ファイル:既存列」と、derived/approx の「入力項目」が
     実際のCSVのヘッダーに存在するか（列名の打ち間違い・既存スクリプトの列名変更の検知）
  5. 状態=derived/approx の条件が screening_engine.py に実装されているか
エラーがあると SQLite を書き換えずに終了コード1で終わる。
"""
from __future__ import annotations

import csv
import datetime as dt
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

CONF_DIR = Path(__file__).resolve().parent
BASE = CONF_DIR.parent
DB_PATH = CONF_DIR / "screening_config.sqlite"

TABLES = {
    "conditions": "screening_conditions.csv",
    "rankings": "ranking_definitions.csv",
    "data_sources": "data_sources.csv",
    "null_policies": "null_policies.csv",
    "statuses": "statuses.csv",
}
DIRECTIONS = {"高いほど良い", "低いほど良い", "中立"}
ORDERS = {"asc", "desc"}


def read(name):
    with open(CONF_DIR / name, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def header_of(rel: str, cache: dict):
    if rel not in cache:
        p = BASE / rel
        if not p.exists():
            cache[rel] = None
        else:
            with open(p, encoding="utf-8-sig", newline="") as f:
                cache[rel] = set(next(csv.reader(f), []))
    return cache[rel]


def validate(data: dict) -> tuple[list[str], list[str]]:
    errors, warns = [], []
    conds, ranks = data["conditions"], data["rankings"]
    statuses = {r["状態"] for r in data["statuses"]}
    policies = {r["NULLの扱い"] for r in data["null_policies"]}
    sources = {r["データ源ID"] for r in data["data_sources"]}

    ids = [r["条件ID"] for r in conds]
    for i in sorted({x for x in ids if ids.count(x) > 1}):
        errors.append(f"条件IDが重複: {i}")
    rids = [r["ランキングID"] for r in ranks]
    for i in sorted({x for x in rids if rids.count(x) > 1}):
        errors.append(f"ランキングIDが重複: {i}")
    idset = set(ids)

    try:
        sys.path.insert(0, str(CONF_DIR))
        import screening_engine as eng
        derived_impl = set(eng.DERIVED)
    except Exception as e:  # pandas が無い環境など
        derived_impl = None
        warns.append(f"screening_engine.py を読み込めず、計算式の実装確認を省略: {e}")

    cache: dict = {}
    for r in conds:
        cid = r["条件ID"]
        if r["状態"] not in statuses:
            errors.append(f"{cid}: 状態「{r['状態']}」は statuses.csv に無い")
        if r["NULLの扱い"] not in policies:
            errors.append(f"{cid}: NULLの扱い「{r['NULLの扱い']}」は null_policies.csv に無い")
        if r["データ源"] not in sources:
            errors.append(f"{cid}: データ源「{r['データ源']}」は data_sources.csv に無い")
        if r["良い向き"] not in DIRECTIONS:
            errors.append(f"{cid}: 良い向き「{r['良い向き']}」が不正")
        if r["NULLの扱い"] == "fallback" and r["代替条件ID"] not in idset:
            errors.append(f"{cid}: 代替条件ID「{r['代替条件ID']}」が存在しない")
        for k in ("既定の下限", "既定の上限"):
            if r[k]:
                try:
                    float(r[k])
                except ValueError:
                    errors.append(f"{cid}: {k}「{r[k]}」が数値でない")

        st = r["状態"]
        refs = []
        if st == "active":
            if not (r["既存ファイル"] and r["既存列"]):
                errors.append(f"{cid}: 状態=active なのに既存ファイル・既存列が空")
            else:
                refs.append((r["既存ファイル"], r["既存列"]))
        if st in ("derived", "approx"):
            if derived_impl is not None and cid not in derived_impl and not r["既存列"]:
                errors.append(f"{cid}: 状態={st} だが screening_engine.DERIVED に計算式が無い")
            for item in filter(None, r["入力項目"].split(";")):
                if ":" in item and item.split(":", 1)[0].endswith(".csv"):
                    refs.append(tuple(item.split(":", 1)))
            if r["既存ファイル"] and r["既存列"]:
                refs.append((r["既存ファイル"], r["既存列"]))
        for rel, col in refs:
            h = header_of(rel, cache)
            if h is None:
                warns.append(f"{cid}: {rel} が見つからない（列名の照合を省略）")
            elif col not in h:
                errors.append(f"{cid}: {rel} に列「{col}」が無い")

    for r in ranks:
        rid = r["ランキングID"]
        if r["並べる条件ID"] not in idset:
            errors.append(f"{rid}: 並べる条件ID「{r['並べる条件ID']}」が存在しない")
        if r["並び順"] not in ORDERS:
            errors.append(f"{rid}: 並び順「{r['並び順']}」は asc / desc のどちらか")
        if r["状態"] not in statuses:
            errors.append(f"{rid}: 状態「{r['状態']}」が不正")
        for part in filter(None, (r["既定で除外"] + "|" + r["対象の絞り込み"]).split("|")):
            head = part.split(">")[0].split("<")[0].split("=")[0].split(":")[0]
            if head not in idset:
                errors.append(f"{rid}: 絞り込み「{part}」の条件ID「{head}」が存在しない")
    return errors, warns


def write_sqlite(data: dict, warns: list[str]) -> None:
    # 一時フォルダで組み立ててから上書きコピーする（同期フォルダや共有マウント上の
    # SQLite ロック不具合を避け、途中で失敗しても既存の SQLite を壊さないため）
    tmpdir = Path(tempfile.mkdtemp(prefix="screening_config_"))
    tmp = tmpdir / DB_PATH.name
    con = sqlite3.connect(tmp)
    try:
        for table, rows in data.items():
            cols = list(rows[0].keys())
            con.execute(f'CREATE TABLE {table} ({", ".join(f"[{c}] TEXT" for c in cols)})')
            con.executemany(f'INSERT INTO {table} VALUES ({", ".join("?" * len(cols))})',
                            [tuple(r[c] for c in cols) for r in rows])
        con.execute("CREATE TABLE meta (key TEXT, value TEXT)")
        con.executemany("INSERT INTO meta VALUES (?, ?)", [
            ("built_at", dt.datetime.now().isoformat(timespec="seconds")),
            ("warnings", "\n".join(warns)),
        ])
        con.execute("CREATE UNIQUE INDEX ix_conditions_id ON conditions([条件ID])")
        con.execute("CREATE UNIQUE INDEX ix_rankings_id ON rankings([ランキングID])")
        con.commit()
    finally:
        con.close()
    shutil.copyfile(tmp, DB_PATH)
    shutil.rmtree(tmpdir, ignore_errors=True)


def main() -> int:
    data = {t: read(f) for t, f in TABLES.items()}
    errors, warns = validate(data)
    for w in warns:
        print("[警告]", w)
    if errors:
        for e in errors:
            print("[エラー]", e)
        print(f"エラー {len(errors)} 件。SQLiteは更新していません。")
        return 1
    write_sqlite(data, warns)
    from collections import Counter
    cnt = Counter(r["状態"] for r in data["conditions"])
    print(f"OK: 条件 {len(data['conditions'])} 件 {dict(cnt)}／ランキング {len(data['rankings'])} 件")
    print(f"書き出し: {DB_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
