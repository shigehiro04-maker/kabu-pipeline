#!/usr/bin/env python3
"""売り側（上の窓を売る）の画面 data/charts/gap_short.html（通信なし・数秒）。
レイアウトは gap_page.py の画面をそのまま使い、文言と数字だけを売り側に置き換える"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

from gap_common import CAND, DAILY_S, OUT, REC_S, SITE, next_business_day
from gap_page import TMPL, series, stats


def _as_buy_cols(d: pd.DataFrame) -> pd.DataFrame:
    """stats/series は「買った数」を数えるので、売った数を同じ名前で渡す"""
    return d.rename(columns={"売った数": "買った数", "決算除く_売った数": "決算除く_買った数"})


def main():
    files = sorted(CAND.glob("*.csv"))
    f = files[-1]
    c = pd.read_csv(f, dtype={"コード": str})
    if "売り候補_k1" not in c:
        print("売り側の列がある候補ファイルがまだありません"); return 0
    for k in ("売り候補_k1", "売り候補_k0.5", "決算翌日"):
        c[k] = c[k].astype(str).str.lower().isin(["true", "1"])
    asof = pd.Timestamp(f.stem); nb = next_business_day(asof)
    c = c[c["売り候補_k0.5"]].copy()
    c["必要な上昇_k1"] = (c["売り下限_k1"] / c["終値"] - 1) * 100
    c["必要な上昇_k05"] = (c["売り下限_k0.5"] / c["終値"] - 1) * 100
    c = c.sort_values("必要な上昇_k05")
    cand = []
    for _, r in c.iterrows():
        # gap_page と同じ並び: [コード, 名前, 業種, 終値, 前日高値, 20日線, 下限k1, 下限k0.5, σ90, 必要k1, 必要k0.5, 決算]
        cand.append([r["コード"], r["銘柄名"], r["業種"], float(r["終値"]), float(r["前日高値"]), float(r["20日線"]),
                     float(r["売り下限_k1"]) if r["売り候補_k1"] else None, float(r["売り下限_k0.5"]), float(r["σ90_pct"]),
                     round(float(r["必要な上昇_k1"]), 2) if r["売り候補_k1"] else None, round(float(r["必要な上昇_k05"]), 2), bool(r["決算翌日"])])
    d = _as_buy_cols(pd.read_csv(DAILY_S)) if DAILY_S.exists() else pd.DataFrame(columns=["日付", "k", "買った数", "損益_pct"])
    t = pd.read_csv(REC_S, dtype={"コード": str}) if REC_S.exists() else pd.DataFrame(columns=["日付", "k", "損益_pct"])
    rp = OUT / "replay_short_daily.csv"
    rpd = _as_buy_cols(pd.read_csv(rp)) if rp.exists() else pd.DataFrame(columns=["日付", "k", "買った数", "損益_pct"])
    rpt = OUT / "replay_short_trades.csv"
    rptt = pd.read_csv(rpt, dtype={"コード": str}) if rpt.exists() else pd.DataFrame(columns=["日付", "k", "損益_pct"])
    recent = t.sort_values(["日付", "k", "順位"], ascending=[False, True, True]).head(60) if len(t) else t
    n1 = int(c["売り候補_k1"].sum())
    data = dict(asof=str(asof.date()), target=str(nb.date()), n1=n1, n05=len(c), cand=cand,
                live={str(k): dict(s=stats(d, t, k), eq=series(d, k)) for k in (1.0, 0.5)},
                replay={str(k): dict(s=stats(rpd, rptt, k), eq=series(rpd, k)) for k in (1.0, 0.5)},
                recent=[[str(r["日付"]), float(r["k"]), int(r["順位"]), r["コード"], r["銘柄名"], float(r["始値"]), float(r["終値"]),
                         float(r["ギャップ_pct"]), float(r["損益_pct"]), str(r.get("決算翌日", "")).lower() in ("true", "1")] for _, r in recent.iterrows()])
    html = TMPL
    R = [
        ('<title>寄り前ギャップ</title>', '<title>寄り前ギャップ 売り側</title>'),
        ('<h1><a href="./index.html" title="トップへ">‹</a>寄り前ギャップ<small>Buy-on-Gap・お金を入れない試験運用</small></h1>',
         '<h1><a href="./index.html" title="トップへ">‹</a>寄り前ギャップ 売り側<small>上の窓を売る・紙の記録</small></h1>'),
        ('<a href="./gap_short.html">売り側（上の窓を売る・紙の記録）→</a>', '<a href="./gap.html">← 買い側（下の窓を買う）</a>'),
        ('<li>候補の<b>寄り前の気配</b>を見る。気配が<b>「下限（20日線）より上、上限より下」</b>なら条件成立。</li>',
         '<li>候補の<b>寄り前の気配</b>を見る。気配が<b>「下限より上、上限（20日線）より下」</b>なら条件成立（＝前日高値より大きく上に寄り、まだ20日線の下）。</li>'),
        # 最上部（あすの朝の候補）の手順と、条件に入りやすい5銘柄の図
        ('<li><b>下限 ＜ 気配 ＜ 上限</b>この間なら条件成立。寄らず・ストップ安は買わない</li>',
         '<li><b>下限 ＜ 気配 ＜ 上限</b>この間なら条件成立。寄らず・寄りからストップ高は売らない</li>'),
        ('<li><b>寄りで買い、大引けで売る</b>同額ずつ・最大10銘柄・持ち越さない</li>',
         '<li><b>寄りで売り、大引けで買い戻す</b>同額ずつ・最大10銘柄・持ち越さない</li>'),
        ('<span class="meta">前日終値から上限までの下げが小さい順（k=1）</span>', '<span class="meta">前日終値から下限までの上げが小さい順（k=1）</span>'),
        ('買いゾーン（下限＝20日線 〜 上限）', '売りゾーン（下限 〜 上限＝20日線）'),
        ('点線＝寄付きまでに必要な下げ', '点線＝寄付きまでに必要な上げ'),
        ('.sort((a,b)=>b[9]-a[9]).slice(0,5);', '.sort((a,b)=>a[9]-b[9]).slice(0,5);'),
        ('const lo=x[5],up=x[6],cl=x[3],span=Math.max(cl-lo,1e-9),a=lo-span*.12,b=cl+span*.06',
         'const lo=x[6],up=x[5],cl=x[3],span=Math.max(up-cl,1e-9),a=cl-span*.06,b=up+span*.12'),
        ('<div class="ar" style="left:${P(up).toFixed(2)}%;width:${(P(cl)-P(up)).toFixed(2)}%"></div>',
         '<div class="ar" style="left:${P(cl).toFixed(2)}%;width:${(P(lo)-P(cl)).toFixed(2)}%"></div>'),
        ('aria-label="買いゾーン', 'aria-label="売りゾーン'),
        ('<span>買いゾーン <b>', '<span>売りゾーン <b>'),
        ('<span>買った日 <b>${a.買った日}</b></span>', '<span>売った日 <b>${a.買った日}</b></span>'),
        ('<li>成立した銘柄を寄付きの成行で同額ずつ買い、<b>大引けの成行で売る</b>（持ち越さない）。10銘柄を超えたら、気配÷前日安値が小さい順に10銘柄。</li>',
         '<li>成立した銘柄を寄付きの成行で同額ずつ<b>売り</b>、<b>大引けの成行で買い戻す</b>（持ち越さない）。10銘柄を超えたら、気配÷前日高値が大きい順に10銘柄。</li>'),
        ('<li>寄らず（特別気配のまま）・ストップ安は買わない。</li>', '<li>寄らず（特別気配のまま）・寄りからストップ高は売らない。空売りできる銘柄（制度信用の貸借銘柄や一般信用）かは確認していません。</li>'),
        ('<p class="note">主は k=1（本書の既定）。k=0.5 は条件がゆるく、候補・取引が増える（検証では成績も良かったが、多くの設定から選んだ結果なので参考）。',
         '<p class="note">第7章の検証（日中モメンタム_第7章_20261012）で、上に窓を開けた銘柄は日中に戻る傾向が強かった（k=1・始値&lt;20日線で 2016-12〜 1日 −49bp、t=−5.9）。条件は2026-10-12に固定し、10/13から記録。主は k=1、k=0.5 は参考。'),
        ('いまは<b>お金を入れない試験運用</b>：毎日の処理が翌営業日の実際の始値・終値で答え合わせし、記録します。コストは引いていません（検証の損益分岐は片道約18bp）。',
         'お金を入れない<b>紙の記録</b>：毎日の処理が翌営業日の実際の始値・終値で答え合わせします。損益は売りの向き（株価が下がればプラス）。コスト・貸株料は引いていません。'),
        ('並び順＝上限までの下げ幅が小さい順（＝条件に入りやすい順）。「上限まで」＝前日終値から上限までの下落率。', '並び順＝下限までの上げ幅が小さい順（＝条件に入りやすい順）。「下限まで」＝前日終値から下限までの上昇率。'),
        ('<th>下限（20日線）</th><th>上限 k=1</th><th>上限まで k=1</th><th>上限 k=0.5</th><th>上限まで k=0.5</th><th>終値</th><th>前日安値</th>',
         '<th>上限（20日線）</th><th>下限 k=1</th><th>下限まで k=1</th><th>下限 k=0.5</th><th>下限まで k=0.5</th><th>終値</th><th>前日高値</th>'),
        ('<h2>参考：同じスクリプトで過去1年を再現した成績</h2>', '<h2>参考：同じスクリプトで過去1年を再現した成績（売り側）</h2>'),
        ('2016-12〜2026-10 の検証では k=1 で年率26%・R/R 0.95・最大DD約37%、負けた年（2018・2021・2025）あり。\n詳細は 株分析/平均回帰_株とETF_第4章_20261010/README_株とETFの平均回帰.md。',
         '全期間（2016-12〜）の再現は README を参照。詳細は 株分析/日中モメンタム_第7章_20261012/README_日中モメンタム_第7章.md。'),
        ("sortAsc=false;", "sortAsc=true;"),
        ("買った日 ${s.買った日}", "売った日 ${s.買った日}"),
        ("<h2>候補の一覧", "<h2>売り候補の一覧"),
        ('<div class="k">次の寄付きの候補</div>', '<div class="k">次の寄付きの売り候補</div>'),
        ("第7章の検証では、決算翌日の窓は戻りにくく続きやすい（2024/9〜、件数が少なく未確定）。買う条件は変えず、",
         "決算翌日の上の窓は戻りにくく続きやすい（2024/9〜、件数が少なく未確定）。売る条件は変えず、"),
    ]
    miss = []
    for a, b in R:
        if a not in html:          # gap_page.py の文言が変わったとき。画面は作り、終了コード1で知らせる
            miss.append(a[:60])
            continue
        html = html.replace(a, b)
    for m in miss:
        print(f"置き換え先が見つかりません（gap_page.py の文言が変わった可能性）: {m}")
    html = html.replace("__DATA__", json.dumps(data, ensure_ascii=False, allow_nan=False, default=lambda o: None))
    SITE.mkdir(parents=True, exist_ok=True)
    (SITE / "gap_short.html").write_text(html, encoding="utf-8")
    sl = data["live"]["1.0"]["s"]
    print(f"gap_short.html: 対象日 {nb.date()} 売り候補 k=1 {n1} / k=0.5 {len(c)}、記録 {sl.get('日数', 0)}日")
    return 1 if miss else 0


if __name__ == "__main__":
    sys.exit(main())
