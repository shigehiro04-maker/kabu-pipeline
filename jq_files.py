"""決算短信サマリーのファイル一覧（J-Quants ＋ TDnet）。2026-11-16 追加。

J-Quants の無料版（fundamentals/jq_summary/）は12週間遅れ。その先の日付は、fetch_tdnet.py が TDnet の
決算短信 XBRL から同じ項目名で作ったファイル（fundamentals/jq_summary_tdnet/）で埋める。
J-Quants の最新の日付より後の TDnet の日だけを足すので、同じ開示が二重にはならない
（J-Quants が追いつけば、その日は自然に J-Quants に置き換わる）。

使い方: for f in jq_files.files(jq_dir): ...   （jq_dir が fundamentals/jq_summary 以外なら、そのフォルダだけ）
TDnet を混ぜたくないときは環境変数 KB_JQ_ONLY=1。
"""
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent
JQ = BASE / "fundamentals" / "jq_summary"
TD = BASE / "fundamentals" / "jq_summary_tdnet"


def files(jq_dir=None):
    jq_dir = Path(jq_dir) if jq_dir else JQ
    out = sorted(jq_dir.glob("*.json"))
    try:
        same = jq_dir.resolve() == JQ.resolve()
    except OSError:
        same = False
    if not same or os.environ.get("KB_JQ_ONLY") or not TD.exists():
        return out
    last = out[-1].stem if out else ""
    return out + [p for p in sorted(TD.glob("*.json")) if p.stem > last]
