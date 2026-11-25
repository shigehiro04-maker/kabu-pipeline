#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ファンダメンタル分析ダッシュボードのHTMLを生成する

analyze_fundamentals.py が出力した dashboard_data.json を読み、
外部ライブラリに依存しない1枚のHTMLを作る。

    ./.venv/bin/python make_fundamental_dashboard.py

出力: data/charts/fundamentals.html
（既存の銘柄チャート <コード>.html と同じ場所なので、行のコードから個別チャートへ飛べる）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
SRC = BASE / "fundamentals" / "analysis" / "dashboard_data.json"
DST = BASE / "data" / "charts" / "fundamentals.html"

TEMPLATE = r"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
@import url("https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap");
:root{
  color-scheme: light;
  --surface-1:#fcfcfb; --page:#f9f9f7;
  --text-primary:#0b0b0b; --text-secondary:#52514e; --muted:#898781;
  --grid:#e1e0d9; --axis:#c3c2b7; --border:rgba(11,11,11,0.10);
  --series-1:#2a78d6; --series-2:#eb6834; --series-3:#1baf7a;
  --good:#0ca30c; --critical:#d03b3b;
  --tint:rgba(42,120,214,0.13); --hover:rgba(11,11,11,0.04);
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    color-scheme: dark;
    --surface-1:#1a1a19; --page:#0d0d0d;
    --text-primary:#ffffff; --text-secondary:#c3c2b7; --muted:#898781;
    --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,0.10);
    --series-1:#3987e5; --series-2:#d95926; --series-3:#199e70;
    --good:#0ca30c; --critical:#d03b3b;
    --tint:rgba(57,135,229,0.20); --hover:rgba(255,255,255,0.05);
  }
}
:root[data-theme="dark"]{
  color-scheme: dark;
  --surface-1:#1a1a19; --page:#0d0d0d;
  --text-primary:#ffffff; --text-secondary:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,0.10);
  --series-1:#3987e5; --series-2:#d95926; --series-3:#199e70;
  --tint:rgba(57,135,229,0.20); --hover:rgba(255,255,255,0.05);
}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--text-primary);
  font:14px/1.6 system-ui,-apple-system,"Hiragino Sans","Noto Sans JP",sans-serif;}
a{color:var(--series-1)}
.wrap{max-width:1500px;margin:0 auto;padding:20px 18px 60px}
header{display:flex;flex-wrap:wrap;align-items:baseline;gap:12px;margin-bottom:4px}
h1{font-size:20px;margin:0;font-weight:650;letter-spacing:.01em}
.back{text-decoration:none;color:var(--muted);font-size:24px;line-height:1;
  padding:2px 8px 6px 0;margin-right:-4px}
.back:hover{color:var(--text-primary)}
.sub{color:var(--muted);font-size:12.5px}
.theme-btn{margin-left:auto;background:none;border:1px solid var(--border);color:var(--text-secondary);
  border-radius:8px;padding:5px 11px;cursor:pointer;font:inherit;font-size:12.5px}
.theme-btn:hover{background:var(--hover)}

/* --- フィルタ行（すべてのタブに効く） --- */
.filters{background:var(--surface-1);border:1px solid var(--border);border-radius:12px;
  padding:12px 14px;margin:14px 0 16px;display:flex;flex-wrap:wrap;gap:10px 16px;align-items:center}
.filters label{font-size:12.5px;color:var(--text-secondary);display:flex;align-items:center;gap:6px}
select,input[type=search]{font:inherit;font-size:13px;background:var(--surface-1);color:var(--text-primary);
  border:1px solid var(--border);border-radius:8px;padding:5px 8px;min-height:30px}
input[type=search]{min-width:190px}
.chips{display:flex;gap:6px}
.chip{border:1px solid var(--border);border-radius:999px;padding:4px 12px;font-size:12.5px;cursor:pointer;
  background:var(--surface-1);color:var(--text-secondary);user-select:none;min-height:28px}
.chip[aria-pressed="true"]{background:var(--tint);border-color:transparent;color:var(--text-primary);font-weight:600}
.count{margin-left:auto;font-size:12.5px;color:var(--muted);font-variant-numeric:tabular-nums}
.reset{background:none;border:none;color:var(--series-1);cursor:pointer;font:inherit;font-size:12.5px;padding:4px}

/* --- タブ --- */
.tabs{display:flex;gap:2px;border-bottom:1px solid var(--border);margin-bottom:18px;overflow-x:auto}
.tab{background:none;border:none;border-bottom:2px solid transparent;color:var(--text-secondary);
  font:inherit;font-size:14px;padding:9px 16px;cursor:pointer;white-space:nowrap;min-height:40px}
.tab:hover{color:var(--text-primary)}
.tab[aria-selected="true"]{color:var(--text-primary);border-bottom-color:var(--series-1);font-weight:600}
.panel[hidden]{display:none}

/* --- カード / タイル --- */
.card{background:var(--surface-1);border:1px solid var(--border);border-radius:12px;padding:16px 18px;margin-bottom:16px}
.card h2{font-size:14px;margin:0 0 2px;font-weight:600}
.card .note{color:var(--muted);font-size:12.5px;margin:0 0 14px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:16px}
.tile{background:var(--surface-1);border:1px solid var(--border);border-radius:12px;padding:14px 16px}
.tile .k{font-size:12px;color:var(--muted);margin-bottom:6px}
.tile .v{font-size:26px;line-height:1.1;font-weight:600;white-space:nowrap}
.tile .u{font-size:13px;color:var(--text-secondary);margin-left:3px;font-weight:400}
.tile .d{font-size:11.5px;color:var(--muted);margin-top:5px}

/* --- テーブル --- */
.tablebox{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}
th,td{padding:7px 9px;text-align:right;white-space:nowrap;border-bottom:1px solid var(--grid)}
th{position:sticky;top:0;background:var(--surface-1);color:var(--text-secondary);font-weight:600;
  font-size:12px;cursor:pointer;user-select:none;z-index:2;border-bottom:1px solid var(--axis)}
th:hover{color:var(--text-primary)}
th.sorted::after{content:" ▾";color:var(--series-1)}
th.sorted.asc::after{content:" ▴"}
td.l,th.l{text-align:left}
tbody tr{cursor:pointer}
tbody tr:hover{background:var(--hover)}
.name{max-width:230px;overflow:hidden;text-overflow:ellipsis;display:inline-block;vertical-align:bottom}
.neg{color:var(--critical)}
.pos{color:var(--good)}
.scorecell{position:relative;padding-right:12px}
.scorecell .bar{position:absolute;left:2px;top:50%;transform:translateY(-50%);height:16px;border-radius:3px;
  background:var(--tint);z-index:0}
.scorecell span{position:relative;z-index:1}
.rkgroups{margin:0 0 10px;border-top:1px solid var(--grid)}
.rkd .rkcur{font-size:12px;color:var(--series-1);font-weight:600;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.rkg{display:flex;flex-wrap:wrap;gap:6px;align-items:center;padding:2px 2px 10px}
.rkall{display:flex;gap:6px;justify-content:flex-end;margin:0 0 4px}
.rkall button{font-size:11.5px;color:var(--muted);background:none;border:1px solid var(--border);border-radius:6px;padding:2px 8px;cursor:pointer}
.rkg .chip[aria-pressed="true"]{background:var(--series-1);color:#fff;border-color:transparent}
.rkopt{display:flex;flex-wrap:wrap;gap:6px 16px;align-items:center;font-size:12.5px;color:var(--muted);margin:2px 0 10px}
.rkna{font-size:11.5px;color:var(--muted);margin:8px 0 0}
td.rkv,th.rkv{background:var(--tint);font-weight:600}
th.rkv{background:linear-gradient(var(--tint),var(--tint)),var(--surface-1)}
td.rkno,th.rkno{color:var(--muted);text-align:right;width:2.6em}
.cvals{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0 2px}
.cvals .chip{font-size:12px;padding:3px 10px}
.cvals .chip small{color:var(--muted);margin-left:4px}
@media (max-width:640px){.rkg{gap:5px}.rkd summary{padding:11px 2px}}
.flag{font-size:10.5px;color:var(--muted);border:1px solid var(--border);border-radius:4px;padding:0 4px;margin-left:5px}
.more{display:block;margin:14px auto 0;background:var(--surface-1);border:1px solid var(--border);
  color:var(--text-secondary);border-radius:8px;padding:8px 20px;cursor:pointer;font:inherit;font-size:13px;min-height:36px}
.more:hover{background:var(--hover)}
.empty{color:var(--muted);padding:30px 0;text-align:center}

/* --- チャート --- */
.chartwrap{position:relative}
canvas{display:block;width:100%;touch-action:none}
.legend{display:flex;flex-wrap:wrap;gap:14px;margin:2px 0 10px;font-size:12.5px;color:var(--text-secondary)}
.legend i{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:6px;vertical-align:baseline}
.tip{position:absolute;pointer-events:none;background:var(--surface-1);border:1px solid var(--border);
  border-radius:8px;padding:7px 10px;font-size:12.5px;box-shadow:0 4px 14px rgba(0,0,0,.14);
  white-space:nowrap;z-index:10;opacity:0;transition:opacity .08s}
.tip b{font-weight:600}
.tip .r{color:var(--text-secondary)}
.axcap{font-size:12px;color:var(--muted);margin-top:6px}

/* --- 条件ビルダー --- */
.cond{padding:10px 0 8px;border-bottom:1px solid var(--grid)}
.cond .ctop{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.cond .cname{font-weight:600;font-size:13.5px;flex:1 1 220px;min-width:0}
.cond .cin{display:flex;gap:6px;align-items:center}
/* 範囲スライダー（分布つき・つまみ2つ） */
.rs{position:relative;height:46px;margin:6px 11px 0;touch-action:none;cursor:pointer;user-select:none;-webkit-user-select:none}
.rs .hist{position:absolute;left:0;right:0;top:0;height:30px;display:flex;align-items:flex-end;gap:1px;pointer-events:none}
.rs .hist i{flex:1;background:var(--grid);border-radius:2px 2px 0 0}
.rs .hist i.in{background:var(--series-1);opacity:.5}
.rs .trk{position:absolute;left:0;right:0;top:34px;height:4px;border-radius:2px;background:var(--grid);pointer-events:none}
.rs .fill{position:absolute;top:0;height:4px;border-radius:2px;background:var(--series-1)}
.rs .h{position:absolute;top:27px;width:18px;height:18px;margin-left:-9px;border-radius:50%;padding:0;
  background:var(--surface-1);border:2px solid var(--series-1);cursor:grab;touch-action:none;z-index:1}
.rs .h.off{border-color:var(--axis)}
.rs .h:active{cursor:grabbing}
.rs .h:focus-visible{outline:2px solid var(--series-1);outline-offset:2px}
.rsax{display:flex;justify-content:space-between;gap:8px;font-size:11.5px;color:var(--muted);margin:1px 2px 0;
  font-variant-numeric:tabular-nums}
.rsax .cnt{color:var(--text-secondary)}
@media (pointer:coarse){.rs{height:52px}.rs .h{width:26px;height:26px;margin-left:-13px;top:23px}}
@media (max-width:640px){.cond .cname{flex-basis:100%}}
/* 「条件を追加」の項目一覧。まとまりごとに▼で開く */
.addcond .tri{display:inline-block;font-size:10px;margin-left:4px;transition:transform .15s}
.addcond[aria-expanded="true"] .tri{transform:rotate(180deg)}
.picker{border:1px solid var(--border);border-radius:10px;padding:10px 12px;margin-top:10px;background:var(--page)}
.picker input[type=search]{width:100%;font:inherit;font-size:13px;background:var(--surface-1);color:var(--text-primary);
  border:1px solid var(--border);border-radius:8px;padding:6px 10px;min-height:34px;margin-bottom:6px}
.pg{border-bottom:1px solid var(--grid)}
.pg:last-child{border-bottom:none}
.pg summary{list-style:none;display:flex;align-items:center;gap:8px;padding:9px 2px;cursor:pointer;font-size:13.5px}
.pg summary::-webkit-details-marker{display:none}
.pg summary .pgc{font-size:11.5px;color:var(--muted)}
.pg summary .tri{margin-left:auto;font-size:11px;color:var(--muted);transition:transform .15s}
.pg[open] summary .tri{transform:rotate(180deg)}
.pitems{display:flex;flex-wrap:wrap;gap:6px;padding:0 0 10px}
.pi{border:1px solid var(--border);border-radius:999px;padding:4px 11px;font:inherit;font-size:12.5px;cursor:pointer;
  background:var(--surface-1);color:var(--text-secondary);text-align:left}
.pi:hover{background:var(--tint);color:var(--text-primary)}
.pi.used{opacity:.5;cursor:default}
.cond input[type=number]{width:96px;font:inherit;font-size:13px;background:var(--surface-1);
  color:var(--text-primary);border:1px solid var(--border);border-radius:8px;padding:5px 8px;min-height:32px}
.cond .tilde{color:var(--muted)}
.cond .unit{color:var(--muted);font-size:12.5px;min-width:34px}
.cond .del{background:none;border:none;color:var(--muted);cursor:pointer;font-size:17px;
  padding:2px 8px;margin-left:auto;line-height:1}
.cond .del:hover{color:var(--critical)}
.condfoot{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-top:14px}
.addcond{background:var(--surface-1);border:1px solid var(--border);color:var(--text-secondary);
  border-radius:8px;padding:7px 14px;cursor:pointer;font:inherit;font-size:13px;min-height:36px}
.addcond:hover{background:var(--hover);color:var(--text-primary)}
.hit{margin-left:auto;font-size:13px;color:var(--text-secondary);font-variant-numeric:tabular-nums}
.hit b{font-size:16px;color:var(--text-primary)}

/* --- スクリーン説明 --- */
.screenbar{display:flex;flex-wrap:wrap;gap:7px;margin-bottom:12px}
.desc{background:var(--surface-1);border:1px solid var(--border);border-left:3px solid var(--series-1);
  border-radius:8px;padding:10px 14px;font-size:13px;color:var(--text-secondary);margin-bottom:14px}

/* --- 銘柄詳細 --- */
/* 銘柄をタップしたときの画面。チャートが主役なので全画面で開く */
.detail{position:fixed;inset:0;background:var(--page);overflow:auto;z-index:30;
  -webkit-overflow-scrolling:touch}
.detail[hidden]{display:none}
.detail .inner{max-width:1500px;margin:0 auto;padding:0 18px 60px;position:relative}
.dhead{position:sticky;top:0;background:var(--page);padding:14px 0 11px;z-index:2;
  border-bottom:1px solid var(--border)}
.detail h3{margin:0 0 2px;font-size:17px;padding-right:88px}
.detail .close{position:absolute;top:8px;right:0;background:var(--surface-1);
  border:1px solid var(--border);border-radius:8px;font-size:19px;width:36px;height:36px;
  color:var(--text-secondary);cursor:pointer;line-height:1;padding:0}
.detail .close:hover{background:var(--hover);color:var(--text-primary)}
/* チャートHTMLの中身は約1113px（PC）／965px（スマホ）。
   その分の高さを与えて、iframeの中でスクロールが起きないようにする */
.chartframe{position:relative;margin:14px 0 4px;border:1px solid var(--border);
  border-radius:12px;overflow:hidden;background:var(--surface-1)}
.chartframe iframe{display:block;width:100%;height:1140px;border:0}
.chartframe .load{position:absolute;inset:0;display:grid;place-items:center;
  color:var(--muted);font-size:13px;background:var(--surface-1)}
.chartframe[hidden]{display:none}
@media (max-width:1000px){.chartframe iframe{height:1030px}}
.radarbox{max-width:520px;margin:16px auto 18px}
.radarbox .axcap{text-align:center;margin-top:2px}
.dtot{display:flex;flex-wrap:wrap;gap:6px 16px;align-items:baseline;margin-top:4px}
.dtot b{font-size:19px;color:var(--text-primary)}
.kv{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:4px 22px;font-size:12.5px}
.kv div{display:flex;justify-content:space-between;gap:10px;border-bottom:1px solid var(--grid);padding:3px 0}
.kv span:first-child{color:var(--text-secondary)}
.kv span:last-child{font-variant-numeric:tabular-nums}
.kv .grp{grid-column:1/-1;border:none;font-weight:600;color:var(--text-primary);
  padding:12px 0 2px;font-size:12.5px}
.kv .grp:first-child{padding-top:0}
/* --- 指標の説明（スマホでも縦に伸びすぎないよう、表ではなくカードで組む） --- */
.dbiz{margin:8px 0 0;font-size:13.5px;line-height:1.7;color:var(--text-secondary);
  padding-right:80px}
.dbiz a{white-space:nowrap}
@media(max-width:640px){.dbiz{padding-right:0;font-size:13px}}
.bands{display:grid;gap:10px;margin-top:14px}
.band{border:1px solid var(--border);border-radius:10px;padding:12px 14px;background:var(--surface-1)}
.band h3{margin:0 0 9px;font-size:14px;display:flex;flex-wrap:wrap;gap:2px 9px;align-items:baseline}
.band h3 em{font-style:normal;font-weight:400;font-size:12.5px;color:var(--text-secondary)}
.scale{list-style:none;margin:0;padding:0;display:grid;gap:2px}
.scale li{display:grid;grid-template-columns:24px 1fr;gap:10px;align-items:center;
  font-size:12.5px;padding:4px 0;border-bottom:1px solid var(--grid)}
.scale li:last-child{border-bottom:none}
.scale b{text-align:center;border-radius:5px;font-size:11.5px;padding:2px 0;
  background:var(--grid);color:var(--text-primary);font-variant-numeric:tabular-nums}
.scale li:first-child b{background:var(--series-1);color:#fff}
.band details,.qa{font-size:12.5px}
.band details{margin-top:10px}
.band summary,.qa summary{cursor:pointer;list-style:none}
.band summary::-webkit-details-marker,.qa summary::-webkit-details-marker{display:none}
.band summary{color:var(--series-1)}
.band summary::before{content:'▸ '}
.band details[open] summary::before{content:'▾ '}
.band details p{margin:8px 0 0;color:var(--text-secondary);line-height:1.85}
.notes{margin-top:10px}
.qa{border-bottom:1px solid var(--grid)}
.qa:last-child{border-bottom:none}
.qa summary{padding:12px 28px 12px 0;font-weight:600;font-size:13px;
  color:var(--text-primary);position:relative;line-height:1.55}
.qa summary:hover{color:var(--series-1)}
.qa summary::after{content:'＋';position:absolute;right:2px;top:12px;
  color:var(--muted);font-weight:400}
.qa[open] summary::after{content:'−'}
.qa>div{padding:0 0 14px;font-size:13px;color:var(--text-secondary);line-height:1.9}
/* 横幅があるときは5段階を横一列に並べて、一目で幅を掴めるようにする */
@media (min-width:780px){
  .scale{grid-template-columns:repeat(5,1fr);gap:8px}
  .scale li{grid-template-columns:1fr;justify-items:center;text-align:center;gap:5px;
    border-bottom:none;background:var(--page);border-radius:8px;padding:9px 5px}
  .scale b{width:24px}
}
/* 版のバッジと、もう一方の版への行き来 */
.vbadge{display:inline-block;background:var(--surface-1);border:1px solid var(--border);
  border-radius:999px;padding:3px 11px;font-size:11.5px;color:var(--text-secondary);
  white-space:nowrap;line-height:1.5}
.vlink{font-size:12.5px;color:var(--series-1);text-decoration:none;white-space:nowrap}
.vlink:hover{text-decoration:underline}
#t-sector tbody tr{cursor:pointer}
#t-sector tbody tr:hover td{background:var(--hover)}
footer{color:var(--muted);font-size:12px;margin-top:26px;line-height:1.8}
@media (max-width:640px){
  .wrap{padding:14px 12px 60px}
  .tile .v{font-size:22px}
  .filters{gap:8px 12px;padding:10px}
  .detail .inner{padding:0 12px 40px}
}

/* ======================================================================
   見やすさの改善（2026-09-23）
   ・評価1〜5は色つきバッジ（5=濃い青 … 3=灰 … 1=橙）で、一目で強弱がわかるように
   ・銘柄名の列は左に固定。列は「表示」ボタンでグループごとに切り替える
   ・絞り込み欄は上に貼りつけ、スマホでは折りたたむ
   ・スマホの一覧は表ではなくカード
   ====================================================================== */
:root{
  --r5:#1f6fd1; --r5t:#fff; --r4:#a9cbf2; --r4t:#0b2a52; --r3:#e7e6df; --r3t:#3a3935;
  --r2:#f7cdb4; --r2t:#5a2408; --r1:#e0662f; --r1t:#fff;
  --shadow:0 1px 2px rgba(0,0,0,.04),0 2px 10px rgba(0,0,0,.04);
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --r5:#3987e5; --r5t:#fff; --r4:#27507f; --r4t:#e3efff; --r3:#3a3a37; --r3t:#dddcd4;
    --r2:#6b3a22; --r2t:#ffdcc8; --r1:#d95926; --r1t:#fff; --shadow:none;
  }
}
:root[data-theme="dark"]{
  --r5:#3987e5; --r5t:#fff; --r4:#27507f; --r4t:#e3efff; --r3:#3a3a37; --r3t:#dddcd4;
  --r2:#6b3a22; --r2t:#ffdcc8; --r1:#d95926; --r1t:#fff; --shadow:none;
}
.rb{display:inline-grid;place-items:center;width:24px;height:24px;border-radius:6px;
  font-size:12.5px;font-weight:600;font-variant-numeric:tabular-nums;line-height:1}
.rb.big{width:32px;height:32px;font-size:16px;border-radius:8px}
.rb.xl{width:52px;height:52px;font-size:26px;border-radius:12px}
.rb.na{background:transparent;color:var(--muted);border:1px dashed var(--axis);font-weight:400}
.rb.v5{background:var(--r5);color:var(--r5t)} .rb.v4{background:var(--r4);color:var(--r4t)}
.rb.v3{background:var(--r3);color:var(--r3t)} .rb.v2{background:var(--r2);color:var(--r2t)}
.rb.v1{background:var(--r1);color:var(--r1t)}
.rbs{display:inline-flex;gap:3px;vertical-align:middle}

/* --- ヘッダーと絞り込み欄（上に貼りつく） --- */
header{align-items:center}
.sticky{position:sticky;top:0;z-index:20;background:var(--page);margin:0 -18px;padding:10px 18px 0}
.filters{margin:0 0 0;box-shadow:var(--shadow);padding:10px 14px;gap:8px 14px}
.filters .grow{flex:1 1 200px;display:flex}
.filters .grow input{flex:1;min-width:0}
input[type=search]{min-height:34px;padding:6px 10px}
.seg{display:inline-flex;border:1px solid var(--border);border-radius:9px;overflow:hidden;background:var(--surface-1)}
.seg .chip{border:none;border-radius:0;min-height:32px;padding:5px 13px;border-left:1px solid var(--border)}
.seg .chip:first-child{border-left:none}
.seg .chip[aria-pressed="true"]{background:var(--series-1);color:#fff}
.ftoggle{display:none;font:inherit;font-size:13px;min-height:34px;padding:5px 12px;border-radius:8px;
  border:1px solid var(--border);background:var(--surface-1);color:var(--text-primary);cursor:pointer;white-space:nowrap}
.ftoggle .nb{display:inline-grid;place-items:center;min-width:18px;height:18px;border-radius:9px;
  background:var(--series-1);color:#fff;font-size:11px;margin-left:5px;padding:0 5px}
.fmore{display:contents}
.filters .cm{display:none}
.tabs .count{align-self:center;padding:0 4px 0 12px;white-space:nowrap}
.tabs{margin:8px 0 0;border-bottom:1px solid var(--border)}
.panel{padding-top:16px}

/* --- 一覧の上の操作列（表示の切替・並べ替え） --- */
.tbar{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center;margin:0 0 12px}
.tbar .lab{font-size:12px;color:var(--muted)}
.views{display:flex;gap:6px;flex-wrap:wrap}
.views .chip[aria-pressed="true"]{background:var(--text-primary);color:var(--page);border-color:transparent}
.sortbox{display:flex;gap:6px;align-items:center;margin-left:auto}
.sortbox select{max-width:220px}
.dirbtn{font:inherit;font-size:13px;min-height:30px;min-width:34px;border-radius:8px;border:1px solid var(--border);
  background:var(--surface-1);color:var(--text-primary);cursor:pointer}

/* --- 表 --- */
.tablebox{max-height:calc(100vh - 150px);overflow:auto;border:1px solid var(--grid);border-radius:10px}
table{font-size:13px}
th,td{padding:8px 10px}
th{top:0}
tbody tr:nth-child(even){background:color-mix(in srgb,var(--page) 55%,transparent)}
tbody tr:hover{background:var(--tint)}
td.stk,th.stk{position:sticky;left:0;z-index:1;background:var(--surface-1);text-align:left;
  min-width:210px;max-width:260px;white-space:normal;box-shadow:1px 0 0 var(--grid)}
th.stk{z-index:3}
tbody tr:nth-child(even) td.stk{background:color-mix(in srgb,var(--page) 55%,var(--surface-1))}
tbody tr:hover td.stk{background:color-mix(in srgb,var(--series-1) 10%,var(--surface-1))}
td.rk,th.rk{position:sticky;left:0;z-index:1;background:inherit}
.stk .nm{display:block;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:240px}
.stk .mt{display:block;font-size:11.5px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:240px}
.stk .cd{color:var(--series-1);font-weight:500;margin-right:6px}
td.sc{text-align:center;padding:6px 3px}
th.sc{text-align:center;padding-left:3px;padding-right:3px}
th.gs{border-left:1px solid var(--grid)} td.gs{border-left:1px solid var(--grid)}
.num-muted{color:var(--muted)}

/* --- スマホのカード一覧 --- */
.cards{display:none}
.scard{display:grid;grid-template-columns:1fr auto;gap:6px 10px;padding:12px 2px;border-bottom:1px solid var(--grid);cursor:pointer}
.scard:active{background:var(--hover)}
.scard .t{min-width:0}
.scard .nm{font-weight:600;font-size:14.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.scard .rkn{color:var(--muted);font-size:12px;margin-right:6px;font-variant-numeric:tabular-nums}
.scard .mt{font-size:11.5px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.scard .items{grid-column:1/-1;display:grid;grid-template-columns:repeat(6,1fr);gap:4px}
.scard .it{display:flex;flex-direction:column;align-items:center;gap:2px;font-size:10.5px;color:var(--muted)}
.scard .it .rb{width:100%;max-width:44px;height:22px;font-size:12px}
.scard .ms{grid-column:1/-1;display:grid;grid-template-columns:repeat(4,1fr);gap:4px;
  background:var(--page);border-radius:8px;padding:6px 8px}
.scard .ms div{display:flex;flex-direction:column;min-width:0}
.scard .ms span{font-size:10.5px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.scard .ms b{font-size:13.5px;font-weight:600;font-variant-numeric:tabular-nums;white-space:nowrap}
.scard .ms{row-gap:8px}
/* スマホだけに出す「カード／表」の切替 */
.lay{display:none;gap:6px;align-items:center}
.lay .chip[aria-pressed="true"]{background:var(--text-primary);color:var(--page);border-color:transparent}
@media (max-width:720px){
  .lay{display:flex}
  /* 表モード：銘柄名の列を細くして、残りの列を横スクロールで見る */
  .mtable .stk .nm,.mtable .stk .mt{max-width:118px}
  .mtable .tablebox{max-height:calc(100vh - 110px)}
  .mtable table{font-size:12.5px}
}

/* --- 銘柄詳細 --- */
.dhead{padding:12px 0 10px}
.dhead h3{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 10px;font-size:18px}
.dhead h3 .cd{color:var(--muted);font-weight:500;font-size:14px}
.dhead h3 a{font-size:12.5px;font-weight:400}
.dmeta{color:var(--muted);font-size:12.5px;margin-top:2px}
.dscore{display:grid;grid-template-columns:auto 1fr;gap:14px 20px;align-items:center;
  background:var(--surface-1);border:1px solid var(--border);border-radius:14px;padding:14px 16px;margin:14px 0 0;box-shadow:var(--shadow)}
.dscore .tot{display:flex;align-items:center;gap:12px}
.dscore .tot .k{font-size:12px;color:var(--muted)}
.dscore .tot .s{font-size:12.5px;color:var(--text-secondary);line-height:1.5}
.dscore .tot .s b{font-size:15px;color:var(--text-primary)}
.ditems{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:8px}
.ditem{display:flex;flex-direction:column;align-items:center;gap:4px;font-size:11.5px;color:var(--text-secondary)}
.ditem .rb{width:100%;max-width:64px;height:30px;font-size:15px}
.dbiz{padding-right:0;margin:12px 0 0}
.dgrid{display:grid;grid-template-columns:minmax(280px,420px) 1fr;gap:16px;margin:16px 0}
.dgrid .radarbox{margin:0;background:var(--surface-1);border:1px solid var(--border);border-radius:14px;padding:10px 12px 12px;max-width:none}
.keys{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;align-content:start}
.key{background:var(--surface-1);border:1px solid var(--border);border-radius:12px;padding:11px 13px}
.key .k{font-size:11.5px;color:var(--muted)}
.key .v{font-size:21px;font-weight:600;line-height:1.25;font-variant-numeric:tabular-nums;white-space:nowrap}
.key .v small{font-size:12px;font-weight:400;color:var(--text-secondary);margin-left:2px}
.key .c{font-size:11px;color:var(--muted);margin-top:2px}
.kv{display:block;columns:320px 4;column-gap:12px;font-size:13px}
.kv .gcard{break-inside:avoid;margin:0 0 12px;background:var(--surface-1);border:1px solid var(--border);border-radius:12px;padding:12px 14px}
.kv .gcard h4{margin:0 0 6px;font-size:13px;font-weight:650}
.kv .row{display:flex;justify-content:space-between;gap:12px;border-bottom:1px solid var(--grid);padding:5px 0}
.kv .row:last-child{border-bottom:none}
.kv .row span:first-child{color:var(--text-secondary)}
.kv .row span:last-child{font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
.kv .row small{color:var(--muted);margin-left:2px;font-size:11px}
.fdots{display:flex;gap:4px;margin:4px 0 8px}
.fdots i{flex:1;height:8px;border-radius:4px;background:var(--grid)}
.fdots i.on{background:var(--good)}
.chartframe{margin:16px 0 4px}

@media (max-width:900px){
  .dgrid{grid-template-columns:1fr}
}
@media (max-width:720px){
  .sticky{margin:0 -12px;padding:8px 12px 0}
  .filters{padding:8px 10px}
  .ftoggle{display:inline-block}
  .fmore{display:none}
  .filters.open .fmore{display:flex;flex-wrap:wrap;gap:10px 12px;width:100%;align-items:center}
  .filters .cm{display:block;margin-left:0;width:100%;text-align:right;font-size:11.5px}
  .tabs .count{display:none}
    .card{padding:12px 12px}
  .sortbox{margin-left:0;width:100%}
  .sortbox select{flex:1;max-width:none}
  header h1{font-size:18px}
  .dscore{grid-template-columns:1fr;padding:12px}
  .ditems{gap:5px}
  .ditem{font-size:10.5px}
  .kv{columns:1}
  .keys{grid-template-columns:repeat(2,1fr)}
  .key .v{font-size:18px}
}
/* ======================================================================
   スマホのスクリーニング（2026-09-24）
   ・プリセットは1行の横スクロール
   ・条件は「名前／×」「下限〜上限」「スライダー」の3段。入力欄は16pxでiOSの拡大を防ぐ
   ・画面下に該当数と「結果を見る／条件に戻る」を固定
   ・結果のカードは、条件に使った数値（青い見出し）を先頭に出して短くする
   ====================================================================== */
.sponly{display:none}
.sbar{display:none}
.scard .ms div.cv span{color:var(--series-1)}
@media (max-width:720px){
  .pconly{display:none}
  .sponly{display:inline}
  #p-screen>.card:first-child{padding:14px 14px 12px}
  .screenbar{flex-wrap:nowrap;overflow-x:auto;scroll-snap-type:x proximity;-webkit-overflow-scrolling:touch;
    margin:0 -14px 8px;padding:2px 14px 8px;scrollbar-width:none;
    -webkit-mask-image:linear-gradient(90deg,transparent 0,#000 12px,#000 calc(100% - 32px),transparent 100%);
    mask-image:linear-gradient(90deg,transparent 0,#000 12px,#000 calc(100% - 32px),transparent 100%)}
  .screenbar::-webkit-scrollbar{display:none}
  .screenbar .chip{flex:none;scroll-snap-align:start;padding:6px 13px;font-size:13px}
  .cond{padding:10px 0 6px}
  .cond .ctop{gap:6px 8px}
  .cond .cname{flex:1 1 calc(100% - 44px);font-size:13.5px;line-height:1.45}
  .cond .del{margin-left:auto;padding:4px 8px}
  .cond .cin{order:3;flex:1 1 100%;min-width:0}
  .cond .cin input[type=number]{flex:1 1 0;width:0;min-width:0;font-size:16px;min-height:38px}
  .cond .unit{min-width:26px}
  .rs{margin:4px 13px 0}
  .condfoot{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:12px}
  .condfoot .addcond{padding:8px 4px;font-size:12.5px;min-height:40px}
  .condfoot .hit{display:none}
  .picker{margin:10px -6px 0;padding:8px 10px}
  .picker input[type=search]{font-size:16px}
  .pitems{display:grid;grid-template-columns:1fr;gap:5px}
  .pi{font-size:13.5px;padding:9px 12px;border-radius:8px}
  .pg summary .pgc{white-space:nowrap}
  body.on-screen .wrap{padding-bottom:92px}
  body.on-screen .sbar{display:flex}
  .sbar{position:fixed;left:0;right:0;bottom:0;z-index:25;align-items:center;gap:12px;
    padding:10px 16px calc(10px + env(safe-area-inset-bottom));background:var(--surface-1);
    border-top:1px solid var(--border);box-shadow:0 -4px 18px rgba(0,0,0,.10)}
  .sbar .sh{font-size:13px;color:var(--text-secondary);white-space:nowrap}
  .sbar .sh b{font-size:19px;color:var(--text-primary);margin:0 2px}
  .sbar button{margin-left:auto;background:var(--series-1);color:#fff;border:none;border-radius:999px;
    padding:10px 18px;font:inherit;font-size:13.5px;font-weight:600;white-space:nowrap}
  #screenres,#p-screen>.card:first-child{scroll-margin-top:96px}
}
/* 設定中の条件の折りたたみ（2026-09-24）。畳んでいる間は1〜2行の要約だけ出す */
.condtoggle{display:flex;flex-wrap:wrap;align-items:center;gap:4px 10px;width:100%;text-align:left;cursor:pointer;
  background:var(--page);border:1px solid var(--border);border-radius:10px;padding:9px 12px;margin:2px 0 4px;
  font:inherit;color:var(--text-primary)}
.condtoggle:hover{background:var(--hover)}
.condtoggle .ct-h{font-size:13px;font-weight:600;white-space:nowrap}
.condtoggle .ct-h b{display:inline-block;min-width:20px;text-align:center;background:var(--series-1);color:#fff;
  border-radius:999px;font-size:11.5px;padding:0 6px;margin-left:2px}
.condtoggle .csum{flex:1 1 200px;min-width:0;font-size:12.5px;color:var(--text-secondary);
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.condtoggle .ct-a{margin-left:auto;display:flex;align-items:center;gap:5px;font-size:12px;color:var(--series-1);white-space:nowrap}
.condtoggle .tri{display:inline-block;font-size:11px;transition:transform .15s}
.condtoggle[aria-expanded="true"] .tri{transform:rotate(180deg)}
.condtoggle[aria-expanded="true"] .csum{display:none}
@media (max-width:720px){.condtoggle{padding:10px 12px}.condtoggle .csum{flex-basis:100%;order:3}}
/* スクリーニングの結果は表だけ。スマホの縦画面でも指標の列が読めるよう、銘柄の列を細くする（2026-09-24） */
.sorthint{margin:0 0 8px;font-size:12px;color:var(--muted)}
.more[hidden]{display:none}
#t-screen td.stk,#t-screen th.stk{min-width:0;max-width:15em}
#t-screen .stk .nm,#t-screen .stk .mt{max-width:15em}
#t-screen .stk .mi{margin-right:4px}
#t-screen th{cursor:pointer}
#t-screen th.sorted{color:var(--text-primary)}
@media (max-width:720px){
  #screenres{padding:12px 10px}
  #screenres .tablebox{max-height:calc(100vh - 170px)}
  #t-screen{font-size:13px}
  #t-screen th,#t-screen td{padding:7px 6px}
  #t-screen th{white-space:normal;min-width:3.6em;max-width:5.6em;font-size:11px;line-height:1.3;vertical-align:bottom}
  #t-screen td.stk,#t-screen th.stk{width:7.6em;min-width:7.6em;max-width:7.6em;padding-left:8px}
  #t-screen .stk .nm{max-width:7.4em;font-size:12.5px;white-space:normal;display:-webkit-box;
    -webkit-line-clamp:2;-webkit-box-orient:vertical;line-height:1.3}
  #t-screen .stk .mt{max-width:7.4em;font-size:11px}
  #t-screen .stk .mi,#t-screen .stk .flag{display:none}
  #t-screen .rb.big{width:26px;height:26px;font-size:14px;border-radius:7px}
  #t-screen td.sc,#t-screen th.sc{padding-left:2px;padding-right:2px}
  .condfoot{grid-template-columns:repeat(2,minmax(0,1fr))}
  #csvout{grid-column:1/-1}   /* スマホでもCSVを保存できるよう、下の段に全幅で出す（2026-09-29） */
}
/* ランキングの表もスマホ縦画面で読めるよう、銘柄の列を細くする（2026-09-24） */
@media (max-width:720px){
  #p-rank>.card{padding:12px 10px}
  #p-rank .tablebox{max-height:calc(100vh - 170px)}
  #t-rank{font-size:13px}
  #t-rank th,#t-rank td{padding:7px 6px}
  #t-rank th{white-space:normal;min-width:2.6em;max-width:5.6em;font-size:11px;line-height:1.3;vertical-align:bottom}
  #t-rank td.l:first-child,#t-rank th.l:first-child{display:none}
  #t-rank td.rkno,#t-rank th.rkno{width:2.2em;padding-left:2px;padding-right:2px}
  #t-rank td.stk,#t-rank th.stk{width:7.6em;min-width:7.6em;max-width:7.6em;padding-left:8px}
  #t-rank .stk .nm{max-width:7.4em;font-size:12.5px;white-space:normal;display:-webkit-box;
    -webkit-line-clamp:2;-webkit-box-orient:vertical;line-height:1.3}
  #t-rank .stk .mt{max-width:7.4em;font-size:11px}
  #t-rank .stk .mi,#t-rank .stk .flag{display:none}
  #t-rank .rb{width:22px;height:22px;font-size:12px}
  #t-rank .rb.big{width:26px;height:26px;font-size:14px;border-radius:7px}
  #t-rank td.sc,#t-rank th.sc{padding-left:2px;padding-right:2px}
  #t-rank th.gs,#t-rank td.gs{border-left:none}
}
/* 指標の説明（2026-09-24） */
#p-about .bands{grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
@media (max-width:760px){#p-about .bands{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}#p-about .band{padding:9px 10px}#p-about .band h3{font-size:13.5px}#p-about .scale li{font-size:12px}}
#p-about .band{padding:11px 13px}
#p-about .scale{grid-template-columns:1fr;gap:0}
#p-about .scale li{grid-template-columns:22px 1fr;justify-items:stretch;text-align:left;gap:8px;
  background:none;border-radius:0;padding:3px 0;border-bottom:1px solid var(--grid)}
#p-about .scale li:last-child{border-bottom:none}
#p-about .scale b{width:auto}
.gl{border-bottom:1px solid var(--grid)}
.gl:last-child{border-bottom:none}
.gl summary{list-style:none;display:flex;align-items:center;gap:8px;padding:11px 2px;cursor:pointer;font-size:14px;font-weight:600}
.gl summary::-webkit-details-marker{display:none}
.gl summary .gc{font-size:11.5px;color:var(--muted);font-weight:400}
.gl summary .tri{margin-left:auto;font-size:11px;color:var(--muted);transition:transform .15s}
.gl[open] summary .tri{transform:rotate(180deg)}
.gl dl{display:grid;grid-template-columns:minmax(9em,13em) 1fr;gap:0;margin:0 0 12px;font-size:13px}
.gl dt,.gl dd{margin:0;padding:6px 0;border-top:1px solid var(--grid)}
.gl dt{font-weight:600;padding-right:14px}
.gl dd{color:var(--text-secondary);line-height:1.6}
.pts{list-style:none;margin:0;padding:0;display:grid;gap:0}
.pts li{display:grid;grid-template-columns:minmax(9em,13em) 1fr;gap:4px 14px;padding:8px 0;border-bottom:1px solid var(--grid);font-size:13px}
.pts li:last-child{border-bottom:none}
.pts li span{color:var(--text-secondary);line-height:1.6}
.pts .flag{margin:0 3px 0 0}
@media (max-width:640px){
  .gl dl{grid-template-columns:1fr}
  .gl dt{padding-bottom:0}
  .gl dd{border-top:none;padding-top:2px}
  .pts li{grid-template-columns:1fr;gap:2px}
}

/* ======================================================================
   銘柄詳細の作り直し（2026-10-05）
   ・上にリンクのボタン（株式分析ダッシュボードを一番目立たせる）
   ・概要／チャート／全指標のタブ。見出しと一緒に上に貼りつく
   ====================================================================== */
.dhead{padding:12px 0 0}
.dlinks{display:flex;flex-wrap:wrap;gap:6px;margin:9px 0 0}
.dlinks a{display:inline-flex;align-items:center;gap:5px;font-size:12.5px;line-height:1;
  padding:8px 12px;border-radius:999px;border:1px solid var(--border);background:var(--surface-1);
  color:var(--text-primary);text-decoration:none;white-space:nowrap}
.dlinks a:hover{background:var(--hover)}
.dlinks a.pri{background:var(--series-1);border-color:var(--series-1);color:#fff;font-weight:600}
.dlinks a.pri:hover{filter:brightness(1.08);background:var(--series-1)}
.dlinks svg{width:14px;height:14px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.dtabs{display:flex;gap:2px;margin:10px 0 0}
.dtabs button{flex:0 0 auto;background:none;border:0;border-bottom:2.5px solid transparent;
  padding:9px 16px 8px;font:inherit;font-size:14px;color:var(--text-secondary);cursor:pointer}
.dtabs button:hover{color:var(--text-primary)}
.dtabs button.on{color:var(--series-1);border-bottom-color:var(--series-1);font-weight:600}
.dtabs button small{font-size:11px;color:var(--muted);margin-left:3px;font-weight:400}
.dpane[hidden]{display:none}
.dpane{padding-top:2px}
.dmore{display:block;margin:4px auto 0;background:var(--surface-1);border:1px solid var(--border);
  border-radius:999px;padding:10px 20px;font:inherit;font-size:13px;color:var(--series-1);cursor:pointer}
.dmore:hover{background:var(--hover)}
.dnone{color:var(--muted);font-size:13px;padding:40px 0;text-align:center}
.dtools{display:flex;flex-wrap:wrap;gap:8px 12px;align-items:center;margin:14px 0 12px}
.dfind{position:relative;flex:1 1 260px;max-width:420px}
.dfind input{width:100%;box-sizing:border-box;font:inherit;font-size:14px;padding:9px 56px 9px 34px;
  border:1px solid var(--border);border-radius:10px;background:var(--surface-1);color:var(--text-primary)}
.dfind svg{position:absolute;left:11px;top:50%;transform:translateY(-50%);width:15px;height:15px;
  fill:none;stroke:var(--muted);stroke-width:2}
.dfind .n{position:absolute;right:11px;top:50%;transform:translateY(-50%);font-size:11.5px;color:var(--muted)}
.djump{display:flex;gap:6px;overflow-x:auto;padding:0 0 12px;scrollbar-width:thin}
.djump button{flex:0 0 auto;font:inherit;font-size:12px;padding:6px 11px;border-radius:999px;
  border:1px solid var(--border);background:var(--surface-1);color:var(--text-secondary);cursor:pointer;white-space:nowrap}
.djump button:hover{background:var(--hover);color:var(--text-primary)}
.kv .gcard[hidden],.kv .row[hidden]{display:none}
.kv .gcard{scroll-margin-top:var(--dhead-h,150px)}
.kv .gcard h4{display:flex;justify-content:space-between;align-items:baseline;padding-bottom:6px;
  border-bottom:1px solid var(--border);margin-bottom:2px;font-size:13.5px}
.kv .row span:first-child{min-width:0}
.kv mark{background:var(--tint);color:inherit;border-radius:3px;padding:0 1px}
@media (max-width:640px){
  .dlinks{flex-wrap:nowrap;overflow-x:auto;margin-right:-12px;padding-right:12px;scrollbar-width:none}
  .dlinks::-webkit-scrollbar{display:none}
  .dtabs{margin-right:-12px}
  .dtabs button{flex:1 1 0;padding:10px 6px 9px;font-size:14px}
  .dfind{max-width:none}
  .dgrid .keys{order:-1}   /* スマホは数字のタイルを先に、レーダーは後に */
  .dfind input{font-size:16px}
}
/* ===== 2026-11 デザイン刷新（トップ画面と共通）：黒／白地、枠線なしのカード、数字は Inter ===== */
:root{--surface-1:#fff;--page:#f3f4f6;--text-primary:#0c0d10;--text-secondary:#3d4148;--muted:#5b6068;--grid:#dfe2e7;--axis:#c0c4cc;--border:rgba(12,13,16,.13);--hover:rgba(12,13,16,.05)}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--surface-1:#101216;--page:#050608;--text-primary:#f2f4f8;--text-secondary:#c6cbd6;--muted:#8f96a3;--grid:#23262d;--axis:#30343d;--border:rgba(255,255,255,.13);--hover:rgba(255,255,255,.06)}}
:root[data-theme="dark"]{--surface-1:#101216;--page:#050608;--text-primary:#f2f4f8;--text-secondary:#c6cbd6;--muted:#8f96a3;--grid:#23262d;--axis:#30343d;--border:rgba(255,255,255,.13);--hover:rgba(255,255,255,.06)}
body{font-family:Inter,"Hiragino Sans","Hiragino Kaku Gothic ProN","Noto Sans JP",system-ui,-apple-system,sans-serif;font-variant-numeric:tabular-nums;-webkit-font-smoothing:antialiased}
h1{font-weight:800;letter-spacing:.02em}
@media (min-width:701px){h1{font-size:24px}}
.card,.filters{border:0;border-radius:14px}
.card h2{font-weight:800}
.tab{font-weight:600}
.tab[aria-selected="true"]{font-weight:800;border-bottom-width:3px;border-bottom-color:var(--text-primary)}
/* 株価の騰落は他のページと同じ 赤＝上昇／緑＝下落。業績などの「良い／悪い」（.pos／.neg）は従来どおり 緑＝良い */
:root{--up:#b91c24;--dn:#08705a}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--up:#ff7378;--dn:#3fd0a4}}
:root[data-theme="dark"]{--up:#ff7378;--dn:#3fd0a4}
.up{color:var(--up)}.dn{color:var(--dn)}
/* アナリスト予想タブ */
.anmin{display:inline-flex;gap:6px;flex-wrap:wrap}
.anmin .chip[aria-pressed="true"]{background:var(--series-1);color:#fff;border-color:transparent}
#t-analyst td.key,#t-analyst th.key{background:var(--tint);font-weight:600}
#t-analyst th.key{background:linear-gradient(var(--tint),var(--tint)),var(--surface-1)}
#t-analyst td{vertical-align:middle}
#t-analyst small.chg{display:block;font-size:11px}
.dn3{display:inline-flex;align-items:center;gap:7px;text-align:left}
.dn3 svg{width:36px;height:36px;flex:none}.dn3 .c{font-size:11px;line-height:1.35;color:var(--text-secondary);white-space:nowrap}
.dn3 .c i{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:4px}
.anrec{display:inline-block;font-size:12px;font-weight:700;padding:1px 8px;border-radius:999px;white-space:nowrap}
.anrec.b{color:var(--up);background:color-mix(in srgb,var(--up) 13%,transparent)}
.anrec.n{color:var(--muted);background:color-mix(in srgb,var(--muted) 15%,transparent)}
.anrec.s{color:var(--dn);background:color-mix(in srgb,var(--dn) 15%,transparent)}
@media (max-width:640px){#t-analyst .hsp{display:none}#t-analyst td.stk,#t-analyst th.stk{width:7.6em;min-width:7.6em;max-width:7.6em}
 #t-analyst .stk .nm{max-width:7.4em;white-space:normal;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
 #t-analyst .stk .mi,#t-analyst .stk .flag{display:none}#t-analyst th{white-space:normal;font-size:11px}}
</style>
</head>
<body>
<div class="wrap">
<header>
  <a class="back" href="./index.html" title="トップへ">‹</a>
  <h1>東証スクリーニング</h1>
  __VARIANT__
  <span class="sub" id="sub"></span>
  <button class="theme-btn" id="theme">表示切替</button>
</header>

<div class="sticky">
<div class="filters" id="filters">
  <div class="grow"><input type="search" id="q" placeholder="コード・銘柄名で検索"></div>
  <button class="ftoggle" id="ftoggle" aria-expanded="false">絞り込み</button>
  <div class="fmore">
    <div class="seg chips" id="mkt"></div>
    <label>業種 <select id="sector"></select></label>
    <label>時価総額
      <select id="cap">
        <option value="0">すべて</option>
        <option value="50">50億円以上</option>
        <option value="100">100億円以上</option>
        <option value="500">500億円以上</option>
        <option value="1000">1000億円以上</option>
        <option value="10000">1兆円以上</option>
      </select>
    </label>
    <label>規模
      <select id="size">
        <option value="">すべて</option>
        <option value="大型">大型（Core30・Large70）</option>
        <option value="中型">中型（Mid400）</option>
        <option value="小型">小型（Small）</option>
        <option value="Core30">TOPIX Core30</option>
        <option value="Large70">TOPIX Large70</option>
        <option value="その他">指数外（新規上場など）</option>
      </select>
    </label>
    <label>投資金額
      <select id="inv">
        <option value="0">すべて</option>
        <option value="5">5万円以下</option>
        <option value="10">10万円以下</option>
        <option value="30">30万円以下</option>
        <option value="50">50万円以下</option>
        <option value="100">100万円以下</option>
      </select>
    </label>
    <label><input type="checkbox" id="exStale" checked> 決算が古い銘柄を除く</label>
    <label><input type="checkbox" id="exLoss"> 赤字を除く</label>
    <label title="PERと時価総額÷純利益の食い違い、売上高の桁ずれ、EDINET DB（有報）とのずれが見つかった銘柄"><input type="checkbox" id="exBad" checked> データ不整合を除く</label>
    <button class="reset" id="reset">リセット</button>
  </div>
  <span class="count cm" id="count-m"></span>
</div>

<div class="tabs" role="tablist">
  <button class="tab" role="tab" data-p="rank" aria-selected="true">ランキング</button>
  <button class="tab" role="tab" data-p="analyst" aria-selected="false" id="tab-analyst">アナリスト予想</button>
  <button class="tab" role="tab" data-p="screen" aria-selected="false">スクリーニング</button>
  <button class="tab" role="tab" data-p="sector" aria-selected="false">業種別</button>
  <button class="tab" role="tab" data-p="about" aria-selected="false">指標の説明</button>
  <span class="count" id="count"></span>
</div>
</div>

<section class="panel" id="p-rank">
  <div class="card">
    <h2 id="rktitle">ランキング</h2>
    <p class="note">MarketSpeed II のランキング種類と独自ランキングを、スクリーニング定義表（ranking_definitions.csv）のとおりに並べています。銘柄をタップすると概要と全指標が開きます。チャートは上のボタンから別画面で開けます。上の絞り込み（市場・業種など）も効きます。</p>
    <div class="rkall"><button type="button" id="rkopenall">すべて開く</button><button type="button" id="rkcloseall">すべて閉じる</button></div>
    <div class="rkgroups" id="rkgroups"></div>
    <div class="rkopt"><label><input type="checkbox" id="rkPrice" checked> 株価100円未満を除く</label><span id="rkinfo"></span></div>
    <div class="tablebox"><table id="t-rank"><thead></thead><tbody></tbody></table></div>
    <div class="empty" id="rank-empty" hidden>条件に合う銘柄がありません。</div>
    <button class="more" id="rank-more" hidden>さらに表示</button>
    <p class="rkna" id="rkna"></p>
  </div>
</section>

<section class="panel" id="p-analyst" hidden>
  <div class="card">
    <h2 id="antitle">アナリスト予想</h2>
    <div class="rkg" id="anrk"></div>
    <div class="rkopt"><span>アナリスト</span><span class="anmin" id="anmin"></span><span id="aninfo"></span></div>
    <div class="tablebox"><table id="t-analyst"><thead></thead><tbody></tbody></table></div>
    <div class="empty" id="an-empty" hidden>条件に合う銘柄がありません。</div>
    <button class="more" id="an-more" hidden>さらに表示</button>
  </div>
</section>

<section class="panel" id="p-screen" hidden>
  <div class="card">
    <h2>条件で絞り込む</h2>
    <p class="note"><span class="pconly">よく使う条件をボタンで呼び出して、そこから範囲を変えられます。つまみをドラッグするか、スライダーの上でマウスホイールを回すと動きます（Shiftを押しながらだと細かく）。端まで寄せると制限なし。グラフは上の絞り込み（市場・業種など）を通った銘柄の分布で、青い部分が範囲内です。条件はすべて満たす銘柄が残ります。</span><span class="sponly">上のボタンは横にスクロールできます。つまみを指で動かすと範囲が変わり、端まで寄せると制限なし。青い棒が範囲内の銘柄です。</span></p>
    <div class="screenbar" id="screenbar"></div>
    <button type="button" class="condtoggle" id="condtoggle" aria-expanded="false" aria-controls="condlist">
      <span class="ct-h">設定中の条件 <b id="condn">0</b></span><span class="csum" id="condsum"></span>
      <span class="ct-a"><span class="ct-t" id="condtt">開く</span><span class="tri" aria-hidden="true">▼</span></span>
    </button>
    <div id="condlist"></div>
    <div class="condfoot">
      <button class="addcond" id="addcond" aria-expanded="false" aria-controls="picker">＋ 条件を追加<span class="tri" aria-hidden="true">▼</span></button>
      <button class="addcond" id="clearcond">すべて消す</button>
      <button class="addcond" id="csvout">CSVで保存</button>
      <span class="hit" id="screenhit"></span>
    </div>
    <div class="picker" id="picker" hidden>
      <input type="search" id="pickq" placeholder="項目名で探す（例: RSI・配当・修正・クロス）" aria-label="項目名で探す">
      <div id="pickgroups"></div>
    </div>
  </div>
  <div class="card" id="screenres">
    <p class="sorthint" id="sorthint"></p>
    <div class="tablebox"><table id="t-screen"><thead></thead><tbody></tbody></table></div>
    <div class="empty" id="screen-empty" hidden>条件に合う銘柄がありません。数値を緩めてみてください。</div>
    <button class="more" id="screen-more" hidden>さらに表示</button>
  </div>
</section>

<section class="panel" id="p-sector" hidden>
  <div class="card">
    <h2>業種別の中央値</h2>
    <p class="note">絞り込んだ範囲で業種ごとに集計した中央値。PER・PBRは正の値の銘柄だけを対象にしています。<b>業種名をタップすると、その業種だけのランキングが開きます。</b>列見出しで並べ替えできます。</p>
    <div class="tablebox"><table id="t-sector"><thead></thead><tbody></tbody></table></div>
  </div>
</section>

<section class="panel" id="p-about" hidden>
  <div class="card">
    <h2>総合評価の作り方</h2>
    <p class="note">6項目をそれぞれ決まった基準で1〜5に区分し、その平均をもう一度1〜5にします。順位ではないので、時期が違っても評価を見比べられます。</p>
    <div class="bands" id="bands"></div>
    <p class="axcap" id="totalband"></p>
  </div>
  <div class="card">
    <h2>指標の意味</h2>
    <p class="note">まとまりを押すと開きます。</p>
    <div id="gloss"></div>
  </div>
  <div class="card">
    <h2>読むときの注意</h2>
    <ul class="pts" id="notes"></ul>
  </div>
</section>

<footer id="foot"></footer>
</div>

<!-- スマホでスクリーニングを開いている間だけ出す、該当数と結果への移動ボタン -->
<div class="sbar" id="sbar"><span class="sh" id="sbarhit"></span><button type="button" id="sbarbtn">結果を見る ↓</button></div>
<div class="detail" id="detail" hidden>
  <div class="inner">
    <div class="dhead" id="dhead">
      <button class="close" id="dclose" aria-label="閉じる">×</button>
      <button class="close" id="dtheme" style="right:44px" aria-label="表示切替" title="明るさを切り替える">◐</button>
      <h3 id="dtitle"></h3>
      <div class="dmeta" id="dsub"></div>
      <nav class="dlinks" id="dlinks" aria-label="関連ページ"></nav>
      <div class="dtabs" role="tablist">
        <button type="button" role="tab" data-t="ov" class="on">概要</button>
        <button type="button" role="tab" data-t="all">全指標<small id="dcount"></small></button>
      </div>
    </div>
    <section class="dpane" data-p="ov">
      <div class="dscore" id="dscore"></div>
      <p class="dbiz" id="dbiz" hidden></p>
      <div class="dgrid">
        <div class="radarbox">
          <div class="chartwrap"><canvas id="dradar" height="300"></canvas></div>
          <p class="axcap" id="dradarcap"></p>
        </div>
        <div class="keys" id="dkeys"></div>
      </div>
      <button type="button" class="dmore" data-go="all">すべての指標を見る →</button>
    </section>
    <section class="dpane" data-p="all" hidden>
      <div class="dtools">
        <label class="dfind"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/></svg>
          <input id="dq" type="text" inputmode="search" placeholder="指標名で探す（例：PER、信用倍率、RSI）" autocomplete="off"><span class="n" id="dqn"></span></label>
      </div>
      <div class="djump" id="djump"></div>
      <div class="kv" id="dkv"></div>
    </section>
  </div>
</div>

<script>
const DATA = __DATA__;
const F = DATA.fields, S = DATA.stocks;
// 個別チャートHTMLが実際に存在する銘柄。無い銘柄にリンクを出さないため
const HAS_CHART = new Set(DATA.charts || []);
const HAS_GYO = new Set(DATA.gyoseki || []);
// 株式分析ダッシュボード（one/<コード>.html）がある銘柄。一覧が無い古いデータでは全銘柄にリンクを出す
const HAS_ONE = DATA.one ? new Set(DATA.one) : null;
var DCUR=null;   // いま詳細を開いている銘柄の行   // 通期の業績ダッシュボードがある銘柄
const ix = {}; F.forEach((f,i)=>ix[f]=i);
const $ = s=>document.querySelector(s);
const css = v=>getComputedStyle(document.documentElement).getPropertyValue(v).trim();

/* ---------- 数値の書式 ---------- */
const nf=(v,d=2)=>v==null||!isFinite(v)?'—':v.toLocaleString('ja-JP',{minimumFractionDigits:d,maximumFractionDigits:d});
const ni=v=>v==null||!isFinite(v)?'—':Math.round(v).toLocaleString('ja-JP');
function cap(v){ // 億円 → 読みやすい単位
  if(v==null||!isFinite(v))return '—';
  if(v>=10000) return (v/10000).toFixed(2)+'兆';
  return Math.round(v).toLocaleString('ja-JP')+'億';
}
function median(a){const x=a.filter(v=>v!=null&&isFinite(v)).sort((p,q)=>p-q);
  if(!x.length)return null;const m=x.length>>1;return x.length%2?x[m]:(x[m-1]+x[m])/2;}
function quantile(a,q){const x=a.filter(v=>v!=null&&isFinite(v)).sort((p,q2)=>p-q2);
  if(!x.length)return null;const i=(x.length-1)*q,lo=Math.floor(i),hi=Math.ceil(i);
  return x[lo]+(x[hi]-x[lo])*(i-lo);}

/* ---------- テーマ ---------- */
const root=document.documentElement;
// いま実際に表示している側。埋め込んだチャートにも同じものを渡す
const theme=()=>root.getAttribute('data-theme')
  ||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');
function toggleTheme(){
  root.setAttribute('data-theme',theme()==='dark'?'light':'dark');
  try{localStorage.setItem('fdb-theme',root.getAttribute('data-theme'))}catch(e){}
  drawAll();
  if(DCUR&&!$('#detail').hidden&&!document.querySelector('.dpane[data-p="ov"]').hidden)drawRadar(DCUR);
}
// チャートを開いている間は上のボタンが隠れるので、詳細画面側にも同じものを置く
$('#theme').onclick=toggleTheme;
$('#dtheme').onclick=toggleTheme;
try{const t=localStorage.getItem('fdb-theme'); if(t)root.setAttribute('data-theme',t);}catch(e){}

/* ---------- フィルタ ---------- */
const MARKETS=['プライム','スタンダード','グロース'];
// 規模はJPXの規模区分（sectors.csv の size 列）。SBIの「大型・中型・小型」に合わせてまとめる
const SIZE_SETS={'大型':['Core30','Large70'],'中型':['Mid400'],'小型':['Small 1','Small 2'],
  'Core30':['Core30'],'Large70':['Large70'],'その他':['その他']};
const state={mkt:new Set(MARKETS),sector:'',cap:0,size:'',inv:0,exStale:true,exLoss:false,exBad:true,q:'',
  screen:Object.keys(DATA.screens)[0]};

$('#mkt').innerHTML=MARKETS.map(m=>`<button class="chip" data-m="${m}" aria-pressed="true">${m}</button>`).join('');
$('#mkt').onclick=e=>{const b=e.target.closest('.chip');if(!b)return;
  const m=b.dataset.m;
  if(state.mkt.has(m)&&state.mkt.size>1)state.mkt.delete(m);else state.mkt.add(m);
  b.setAttribute('aria-pressed',state.mkt.has(m));refresh();};

// 上場廃止などでJPXの一覧から消えた銘柄は業種が空になる。
// 1件でも null が混じると並べ替えで落ちて画面全体が出なくなるため、ここで埋める。
S.forEach(r=>{ if(r[ix['業種']]==null) r[ix['業種']]='未分類';
               if(r[ix['市場']]==null) r[ix['市場']]='その他'; });
const sectors=[...new Set(S.map(r=>r[ix['業種']]))]
  .filter(Boolean).sort((a,b)=>String(a).localeCompare(String(b),'ja'));
$('#sector').innerHTML='<option value="">すべての業種</option>'+sectors.map(s=>`<option>${s}</option>`).join('');

$('#sector').onchange=e=>{state.sector=e.target.value;refresh()};
$('#cap').onchange=e=>{state.cap=+e.target.value;refresh()};
$('#size').onchange=e=>{state.size=e.target.value;refresh()};
$('#inv').onchange=e=>{state.inv=+e.target.value;refresh()};
// 規模の列がまだ無いデータ（sectors.csv に size 列が入る前）では選べないようにする
if(ix['規模']==null||!S.some(r=>r[ix['規模']]&&r[ix['規模']]!=='その他')){
  $('#size').disabled=true; $('#size').title='JPXの規模区分がまだ取り込まれていません（翌営業日の更新で入ります）';}
$('#exStale').onchange=e=>{state.exStale=e.target.checked;refresh()};
$('#exLoss').onchange=e=>{state.exLoss=e.target.checked;refresh()};
$('#exBad').onchange=e=>{state.exBad=e.target.checked;refresh()};
if(ix['データ不整合']==null){$('#exBad').disabled=true;state.exBad=false;$('#exBad').checked=false;}
let qt;$('#q').oninput=e=>{clearTimeout(qt);qt=setTimeout(()=>{state.q=e.target.value.trim();refresh()},180)};
$('#reset').onclick=()=>{
  state.mkt=new Set(MARKETS);state.sector='';state.cap=0;state.size='';state.inv=0;state.exStale=true;state.exLoss=false;state.exBad=ix['データ不整合']!=null;state.q='';
  $('#size').value='';$('#inv').value='0';
  document.querySelectorAll('#mkt .chip').forEach(c=>c.setAttribute('aria-pressed','true'));
  $('#sector').value='';$('#cap').value='0';$('#exStale').checked=true;$('#exLoss').checked=false;$('#exBad').checked=state.exBad;$('#q').value='';
  refresh();
};

let rows=[];
function applyFilter(){
  const q=state.q.toLowerCase();
  rows=S.filter(r=>{
    if(!state.mkt.has(r[ix['市場']]))return false;
    if(state.sector&&r[ix['業種']]!==state.sector)return false;
    if(state.cap&&!(r[ix['時価総額(億円)']]>=state.cap))return false;
    if(state.size&&!SIZE_SETS[state.size].includes(r[ix['規模']]))return false;
    if(state.inv&&!(r[ix['最低投資金額(万円)']]<=state.inv))return false;
    if(state.exStale&&r[ix['決算が古い']])return false;
    if(state.exLoss&&r[ix['赤字']])return false;
    if(state.exBad&&r[ix['データ不整合']])return false;
    if(q&&!(String(r[ix['コード']]).toLowerCase().includes(q)||r[ix['銘柄名']].toLowerCase().includes(q)))return false;
    return true;
  });
  $('#count').textContent=$('#count-m').textContent=
    rows.length.toLocaleString('ja-JP')+' / '+S.length.toLocaleString('ja-JP')+' 銘柄';
  // スマホで折りたたんだとき、既定から変えている条件の数をボタンに出す
  const n=(state.mkt.size<MARKETS.length)+!!state.sector+!!state.cap+!!state.size+!!state.inv+(!state.exStale)+state.exLoss+(ix['データ不整合']!=null&&!state.exBad);
  $('#ftoggle').innerHTML='絞り込み'+(n?`<span class="nb">${n}</span>`:'');
}
$('#ftoggle').onclick=()=>{
  const f=$('#filters'); f.classList.toggle('open');
  $('#ftoggle').setAttribute('aria-expanded',f.classList.contains('open'));
};

/* ---------- タブ ---------- */
function goTab(name){
  document.querySelectorAll('.tab').forEach(x=>x.setAttribute('aria-selected',x.dataset.p===name));
  document.querySelectorAll('.panel').forEach(p=>p.hidden=p.id!=='p-'+name);
  refresh();
}
document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>goTab(t.dataset.p));
const activeTab=()=>document.querySelector('.tab[aria-selected="true"]').dataset.p;

/* ---------- canvas 共通 ---------- */
function prep(cv,cssH){
  // cv.height は描画のたびに書き換わるので、意図した高さは data-h に持たせる
  const dpr=Math.min(devicePixelRatio||1,2);
  if(cssH)cv.dataset.h=cssH;
  const h=+(cv.dataset.h||cv.getAttribute('height')||240);
  const w=cv.clientWidth;
  cv.width=w*dpr; cv.height=h*dpr; cv.style.height=h+'px';
  const c=cv.getContext('2d'); c.setTransform(dpr,0,0,dpr,0,0); c.clearRect(0,0,w,h);
  return {c,w,h};
}
function showTip(el,x,y,html,box){
  el.innerHTML=html; el.style.opacity=1;
  const bw=el.offsetWidth, bh=el.offsetHeight;
  el.style.left=Math.max(4,Math.min(x+12,box.clientWidth-bw-4))+'px';
  el.style.top=Math.max(4,y-bh-10)+'px';
}
const hideTip=el=>el.style.opacity=0;

/* ---------- 業種別の集計 ---------- */
function sectorStats(){
  const by={};
  rows.forEach(r=>{const s=r[ix['業種']];(by[s]=by[s]||[]).push(r)});
  return Object.entries(by).map(([s,rs])=>{
    const g=c=>rs.map(r=>r[ix[c]]);
    return {業種:s,銘柄数:rs.length,
      '時価総額(兆円)':g('時価総額(億円)').reduce((a,b)=>a+(b||0),0)/10000,
      'PER':median(g('PER').filter(v=>v>0)),'PBR':median(g('PBR').filter(v=>v>0)),
      'ROE(%)':median(g('ROE(%)')),'営業利益率(%)':median(g('営業利益率(%)')),
      '自己資本比率(%)':median(g('自己資本比率(%)')),'配当利回り(%)':median(g('配当利回り(%)')),
      '売上高成長率(%)':median(g('売上高成長率(%)')),
      '評価平均':median(g('評価平均')),
      '赤字数':rs.filter(r=>r[ix['赤字']]).length};
  });
}
/* ---------- 表 ---------- */
// t: 表示形式。rt=1〜5評価 / n0,n1,n2=小数桁 / cap=時価総額 / s=文字列 / code / stock=銘柄名（左に固定）
const COLS=[
  {k:'銘柄名',l:'銘柄',t:'stock'},
  {k:'コード',l:'コード',t:'code',w:'l'},
  {k:'市場',l:'市場',t:'s',w:'l'},
  {k:'業種',l:'業種',t:'s',w:'l'},
  {k:'総合評価',l:'総合',t:'rt',big:1},
  {k:'成長性評価',l:'成長',t:'rt'},
  {k:'収益性評価',l:'収益',t:'rt'},
  {k:'安全性評価',l:'安全',t:'rt'},
  {k:'規模評価',l:'規模',t:'rt'},
  {k:'割安度評価',l:'割安',t:'rt'},
  {k:'値上がり評価',l:'値上り',t:'rt'},
  {k:'評価平均',l:'平均',t:'n2'},
  {k:'業種内偏差値',l:'業種偏差値',t:'n1'},
  {k:'株価',l:'株価',t:'n0'},
  {k:'時価総額(億円)',l:'時価総額',t:'cap'},   // 自己株式を含む発行済株式総数ベース
  {k:'従業員数(人)',l:'従業員数',t:'n0'},
  {k:'平均年収(万円)',l:'平均年収(万)',t:'n0'},
  {k:'PER',l:'PER',t:'n1'},
  {k:'予想PER',l:'予想PER',t:'n1'},
  {k:'PBR',l:'PBR',t:'n2'},
  {k:'EV/EBITDA',l:'EV/EBITDA',t:'n1'},
  {k:'配当利回り(%)',l:'配当利回り%',t:'n2'},
  {k:'ROE(%)',l:'ROE%',t:'n1'},
  {k:'ROTC(%)',l:'ROTC%',t:'n1'},
  {k:'ベータ',l:'ベータ',t:'n2'},
  {k:'営業利益率(%)',l:'営業利益率%',t:'n1'},
  {k:'自己資本比率(%)',l:'自己資本比率%',t:'n1'},
  {k:'売上高成長率(%)',l:'増収率%',t:'n1',sign:1},
  {k:'営業利益成長率(%)',l:'営業増益率%',t:'n1',sign:1},
  {k:'売上高CAGR(%)',l:'売上CAGR%',t:'n1',sign:1},
  {k:'平均経常利益率(%)',l:'経常利益率%',t:'n1',sign:1},
  {k:'平均税引前利益率(%)',l:'税引前利益率%',t:'n1',sign:1},
  {k:'250日騰落率(%)',l:'250日騰落率%',t:'n1',sign:1},
  {k:'125日騰落率(%)',l:'6か月騰落率%',t:'n1',sign:1},
  {k:'52週レンジ位置(%)',l:'52週位置%',t:'n1'},
  {k:'マルチバガースコア',l:'マルチバガー点',t:'n1'},
  {k:'論文スコア',l:'論文MB点',t:'n1'},
  {k:'Fスコア',l:'Fスコア',t:'n0'},
  {k:'予想Fスコア',l:'予想Fスコア',t:'n0'},
  {k:'配当性向(%)',l:'配当性向%',t:'n0'},
  {k:'DOE(%)',l:'DOE%',t:'n2'},
  {k:'平均DOE(%)',l:'平均DOE%',t:'n2'},
  {k:'連続増配期数',l:'連続増配',t:'n0'},
  {k:'配当CAGR(%)',l:'増配率%',t:'n1',sign:1},
  {k:'PEG',l:'PEG',t:'n2'},
  {k:'EPS_CAGR(%)',l:'EPS成長%',t:'n1',sign:1},
  {k:'営業増益率3期平均(%)',l:'営業増益3期%',t:'n1',sign:1},
  {k:'移動平均線の上の本数',l:'MA上/4本',t:'n0'},
  {k:'横ばい上放れ',l:'上放れ',t:'n0'},
  {k:'200日線乖離(%)',l:'200日線%',t:'n1',sign:1},
  {k:'新高値からの日数',l:'新高値から日',t:'n0'},
  {k:'52週高値乖離(%)',l:'高値から%',t:'n1',sign:1},
  {k:'出来高倍率(5日/50日)',l:'出来高倍率',t:'n2'},
  {k:'規模',l:'規模',t:'s',w:'l'},
  {k:'最低投資金額(万円)',l:'投資金額万円',t:'n1'},
  {k:'PCFR',l:'PCFR',t:'n1'},
  {k:'前日比(%)',l:'前日比%',t:'n2',sign:1},
  {k:'20日騰落率(%)',l:'20日騰落%',t:'n1',sign:1},
  {k:'対市場超過(20日)(%pt)',l:'対市場20日',t:'n1',sign:1},
  {k:'売買代金(百万円)',l:'売買代金百万',t:'n0'},
  {k:'出来高倍率(6日/25日)',l:'出来高6/25',t:'n2'},
  {k:'RSI(14)(%)',l:'RSI',t:'n1'},
  {k:'ボリンジャー位置(σ)',l:'BBσ',t:'n2'},
  {k:'MACDヒストグラム(%)',l:'MACD%',t:'n2',sign:1},
  {k:'GC(5×25)からの日数',l:'GC5×25日',t:'n0'},
  {k:'一目 雲の位置',l:'雲',t:'n0'},
  {k:'新値3本足',l:'3本足',t:'n0'},
  {k:'予想配当利回り(%)',l:'予想利回り%',t:'n2'},
  {k:'予想売上高成長率(%)',l:'予想増収%',t:'n1',sign:1},
  {k:'予想営業増益率(%)',l:'予想営業増益%',t:'n1',sign:1},
  {k:'業績予想修正率(%)',l:'予想修正%',t:'n1',sign:1},
  {k:'期初予想比(%)',l:'期初予想比%',t:'n1',sign:1},
  {k:'決算サプライズ(%)',l:'サプライズ%',t:'n1',sign:1},
  {k:'最新決算日',l:'決算発表日',t:'s',w:'l'},
  {k:'決算期間',l:'決算の期',t:'s',w:'l'},
  {k:'累計増収率(%)',l:'増収率%(累計)',t:'n1',sign:1},
  {k:'累計営業増益率(%)',l:'営業増益%(累計)',t:'n1',sign:1},
  {k:'累計純益増益率(%)',l:'純益増益%(累計)',t:'n1',sign:1},
  {k:'営業益進捗率(%)',l:'営業益進捗%',t:'n1'},
  {k:'決算発表からの日数',l:'発表から日',t:'n0'},
  {k:'需給判定',l:'需給判定',t:'s',w:'l'},
  {k:'需給スコア',l:'需給点',t:'n0'},
  {k:'信用倍率(倍)',l:'信用倍率',t:'n2'},
  {k:'買残回転日数(日)',l:'買残日数',t:'n1'},
  {k:'買残5日変化(%)',l:'買残5日%',t:'n1',sign:1},
  {k:'信用買い評価損益率(%)',l:'買い評価損益%',t:'n1',sign:1},
  {k:'貸借倍率(倍)',l:'貸借倍率',t:'n2'},
  {k:'逆日歩(円)',l:'逆日歩',t:'n2'},
  {k:'大口空売り比率(%)',l:'大口空売%',t:'n2'},
  {k:'上値出来高比率(%)',l:'上値出来高%',t:'n0'},
];
// 条件に使った項目は、COLSに無くてもスクリーニング結果の列に足す
function colOf(k){
  if(COL[k])return COL[k];
  const m=METRIC[k]; if(!m)return null;
  const l=k.replace(/\((%|%pt)\)$/,'%').replace(/\((億円|百万円|万円|円|σ)\)$/,'');
  return COL[k]={k,l,t:typeof S[0][ix[k]]==='string'?'s':('n'+Math.min(2,m[3]))};
}
const COL=Object.fromEntries(COLS.map(c=>[c.k,c]));
const SCORE_KEYS=['総合評価','成長性評価','収益性評価','安全性評価','規模評価','割安度評価','値上がり評価'];
// 「表示」ボタンで切り替える列のまとまり。銘柄名と総合評価はどの表示でも出す。
// cards: スマホのカードに出す4つの数値
const VIEWS={
  basic:{l:'基本',cols:[...SCORE_KEYS,'業種内偏差値','時価総額(億円)','PER','PBR','配当利回り(%)','ROE(%)'],
         cards:['PER','PBR','配当利回り(%)','ROE(%)']},
  value:{l:'割安さ',cols:['総合評価','割安度評価','株価','時価総額(億円)','予想PER','PER','PBR','EV/EBITDA','配当利回り(%)','Fスコア','予想Fスコア'],
         cards:['PER','PBR','EV/EBITDA','配当利回り(%)']},
  quality:{l:'収益・財務',cols:['総合評価','収益性評価','安全性評価','ROE(%)','ROTC(%)','営業利益率(%)','平均経常利益率(%)','自己資本比率(%)','ベータ'],
         cards:['ROE(%)','ROTC(%)','営業利益率(%)','自己資本比率(%)']},
  growth:{l:'成長・値動き',cols:['総合評価','成長性評価','値上がり評価','売上高成長率(%)','営業利益成長率(%)','売上高CAGR(%)','250日騰落率(%)','125日騰落率(%)','52週レンジ位置(%)','マルチバガースコア','論文スコア'],
         cards:['売上高成長率(%)','売上高CAGR(%)','250日騰落率(%)','52週レンジ位置(%)']},
  dividend:{l:'配当',cols:['総合評価','株価','配当利回り(%)','配当性向(%)','DOE(%)','平均DOE(%)','連続増配期数','配当CAGR(%)','自己資本比率(%)'],
         cards:['配当利回り(%)','DOE(%)','連続増配期数','配当CAGR(%)']},
  breakout:{l:'ブレイク',cols:['総合評価','株価','営業増益率3期平均(%)','PEG','移動平均線の上の本数','横ばい上放れ','200日線乖離(%)','新高値からの日数','52週高値乖離(%)','出来高倍率(5日/50日)'],
         cards:['営業増益率3期平均(%)','横ばい上放れ','新高値からの日数','出来高倍率(5日/50日)']},
  tech:{l:'テクニカル',cols:['総合評価','株価','前日比(%)','20日騰落率(%)','対市場超過(20日)(%pt)','RSI(14)(%)','ボリンジャー位置(σ)',
         'MACDヒストグラム(%)','GC(5×25)からの日数','一目 雲の位置','出来高倍率(6日/25日)','売買代金(百万円)'],
         cards:['RSI(14)(%)','ボリンジャー位置(σ)','GC(5×25)からの日数','出来高倍率(6日/25日)']},
  jukyu:{l:'需給',cols:['総合評価','株価','需給判定','需給スコア','信用倍率(倍)','買残回転日数(日)','買残5日変化(%)',
         '信用買い評価損益率(%)','貸借倍率(倍)','逆日歩(円)','大口空売り比率(%)','上値出来高比率(%)'],
         cards:['需給スコア','信用倍率(倍)','買残回転日数(日)','信用買い評価損益率(%)']},
  forecast:{l:'会社予想',cols:['総合評価','株価','予想PER','予想配当利回り(%)','予想売上高成長率(%)','予想営業増益率(%)',
         '業績予想修正率(%)','期初予想比(%)','決算サプライズ(%)'],
         cards:['予想配当利回り(%)','予想営業増益率(%)','業績予想修正率(%)','決算サプライズ(%)']},
  kessan:{l:'最新決算',cols:['総合評価','株価','最新決算日','決算期間','累計増収率(%)','累計営業増益率(%)','累計純益増益率(%)',
         '営業益進捗率(%)','予想営業増益率(%)','業績予想修正率(%)'],
         cards:['累計増収率(%)','累計営業増益率(%)','累計純益増益率(%)','営業益進捗率(%)']},
  all:{l:'すべて',cols:COLS.filter(c=>c.t!=='stock').map(c=>c.k),
         cards:['PER','PBR','配当利回り(%)','ROE(%)']},
};
let view='basic';
try{const v=localStorage.getItem('fdb-view'); if(v&&VIEWS[v])view=v;}catch(e){}
const isMobile=()=>matchMedia('(max-width:720px)').matches;
// スマホの一覧の出し方：card=カード / table=PCと同じ表（横スクロール）
let mlay='card';
try{const v=localStorage.getItem('fdb-mlay'); if(v==='card'||v==='table')mlay=v;}catch(e){}

const rbadge=(v,cls='')=>v==null||!isFinite(v)
  ?`<span class="rb na ${cls}">–</span>`
  :`<span class="rb v${Math.max(1,Math.min(5,Math.round(v)))} ${cls}">${v}</span>`;
function flags(r){
  let f='';
  if(r[ix['決算が古い']])f+='<span class="flag" title="決算期から400日以上">古</span>';
  if(r[ix['赤字']])f+='<span class="flag" title="当期純利益がマイナス">赤</span>';
  if(r[ix['一時要因の疑い']])f+='<span class="flag" title="PERが2倍未満、ROEが60%超、または純利益が4倍超。資産売却益などの一時要因で指標が歪んでいる可能性">特</span>';
  if(ix['データ不整合']!=null&&r[ix['データ不整合']])f+='<span class="flag" title="元データの整合性チェックに当たりました（PERと時価総額÷純利益の食い違い、売上高の桁ずれ、EDINET DBとのずれ）。PER・ROE・売上系・利益率系は空欄にしています">D</span>';
  if(r[ix['EPS乖離']])f+='<span class="flag" title="報告EPSと 当期純利益÷株式数 が2倍以上ずれています（株式分割の未反映など）。このPERはスコアとスクリーニングから外しています">E</span>';
  return f;
}
// 株価の動きを表す項目（騰落率・前日比・乖離など）。プラスを赤、マイナスを緑で出す
const PRICE_RE=/騰落|前日比|寄付|乖離|対市場|MACD|値上|値下/;
function fmtVal(col,v){
  switch(col.t){
    case 's':return v??'—';
    case 'code':return `<span style="color:var(--series-1)">${v}</span>`;
    case 'n0':return ni(v);
    case 'cap':return cap(v);
    case 'n1':case 'n2':{
      const s=nf(v,col.t==='n1'?1:2);
      const pm=PRICE_RE.test(col.k||'');
      return col.sign&&v!=null&&isFinite(v)?`<span class="${v<0?(pm?'dn':'neg'):(v>0?(pm?'up':'pos'):'')}">${v>0?'+':''}${s}</span>`:s;}
  }
  return v??'—';
}
function cellHTML(r,col){
  const v=r[ix[col.k]];
  if(col.t==='stock'){
    const name=he(v);
    return `<span class="nm" title="${name}">${name}</span>`+
      `<span class="mt"><span class="cd">${r[ix['コード']]}</span><span class="mi">${r[ix['市場']]}・${r[ix['業種']]}</span>${flags(r)}</span>`;
  }
  if(col.t==='rt')return rbadge(v,col.big?'big':'');
  return fmtVal(col,v);
}
function cardHTML(r,i,extra=[]){
  const items=DATA.項目.map(it=>`<div class="it">${rbadge(r[ix[it+'評価']])}<span>${it.replace('値上がり','値上り')}</span></div>`).join('');
  // 選んでいる「表示」の数値の列をすべて出す（評価1〜5は上の6つのバッジで出している）
  const base=extra.length?VIEWS[view].cards:VIEWS[view].cols;
  const mk=extra.concat(base.filter(k=>!extra.includes(k)))
    .filter(k=>colOf(k)&&COL[k].t!=='rt'&&COL[k].t!=='stock');
  const ms=(mk.length?mk:VIEWS[view].cards).map(k=>{const c=COL[k];
    return `<div${extra.includes(k)?' class="cv"':''}><span>${c.l.replace(/%$/,'')}</span><b>${fmtVal(c,r[ix[k]])}${/%$/.test(c.l)&&r[ix[k]]!=null?'<small style="font-weight:400">%</small>':''}</b></div>`;}).join('');
  return `<div class="scard" data-c="${r[ix['コード']]}">`+
    `<div class="t"><div class="nm"><span class="rkn">${i+1}</span>${he(r[ix['銘柄名']])}</div>`+
    `<div class="mt"><span style="color:var(--series-1)">${r[ix['コード']]}</span>　${r[ix['市場']]}・${r[ix['業種']]}・${cap(r[ix['時価総額(億円)']])}${flags(r)}</div></div>`+
    `<div>${rbadge(r[ix['総合評価']],'big')}</div>`+
    `<div class="items">${items}</div><div class="ms">${ms}</div></div>`;
}
function renderScreenTable(list){
  const t=$('#t-screen'), n=Math.min(list.length,screenLim.n);
  const ck=conds.map(c=>c.k).filter(k=>colOf(k)&&!['総合評価','株価','時価総額(億円)'].includes(k));
  const cols=[COL['銘柄名'],COL['総合評価'],...ck.map(colOf),COL['株価'],COL['時価総額(億円)']];
  const cls=c=>(c.t==='stock'?'stk':'')+(c.t==='rt'?' sc':'');
  t.querySelector('thead').innerHTML='<tr>'+cols.map(c=>
    `<th class="${cls(c)}${c.k===sortKey?' sorted'+(sortAsc?' asc':''):''}" data-k="${c.k}">${c.l}</th>`).join('')+'</tr>';
  let html='';
  for(let i=0;i<n;i++){const r=list[i];
    html+=`<tr data-c="${r[ix['コード']]}">`+cols.map(c=>`<td class="${cls(c)}">${cellHTML(r,c)}</td>`).join('')+'</tr>';}
  t.querySelector('tbody').innerHTML=html;
  t.querySelectorAll('th[data-k]').forEach(th=>th.onclick=()=>{
    if(sortKey===th.dataset.k)sortAsc=!sortAsc;
    else{sortKey=th.dataset.k;sortAsc=['PER','PBR','PSR','コード','銘柄名','EV/EBITDA','RSI(14)(%)'].includes(sortKey);}
    refresh();});
  const sl=sortKey==='評価平均'?'総合評価':(COL[sortKey]?COL[sortKey].l:(METRIC[sortKey]||[0,sortKey])[1]);
  $('#sorthint').textContent=`並び順：${sl}の${sortAsc?'小さい':'大きい'}順（列の見出しを押すと並べ替え）`;
  $('#screen-empty').hidden=list.length>0;
  const mb=$('#screen-more'); mb.hidden=list.length<=n;
  mb.textContent=`さらに表示（残り ${ni(list.length-n)} 銘柄）`;
}
function renderTable(tid,list,limitRef,moreBtn,emptyEl){
  if(tid==='t-screen')return renderScreenTable(list);
  const t=$('#'+tid), cards=$('#'+tid+'-cards'), box=t.closest('.tablebox');
  const mob=false;   // 一覧は表だけ（カード表示は 2026-09-24 に廃止）
  const n=Math.min(list.length,limitRef.n);
  // スクリーニングでは、条件に使った項目も列（カードの数値）に出す
  const extra=tid==='t-screen'?conds.map(c=>c.k).filter(k=>colOf(k)):[];
  if(mob){
    let html='';
    for(let i=0;i<n;i++)html+=cardHTML(list[i],i,extra);
    cards.innerHTML=html; t.querySelector('tbody').innerHTML='';
  } else {
    const vk=VIEWS[view].cols;
    const cols=[COL['銘柄名'],...vk.map(k=>COL[k]),...extra.filter(k=>!vk.includes(k)).map(k=>colOf(k))];
    // 評価の列と数値の列の境目に区切り線を入れる
    const firstNum=cols.findIndex(c=>c.t!=='rt'&&c.t!=='stock');
    const cls=(c,j)=>(c.t==='stock'?'stk':'')+(c.t==='rt'?' sc':'')+(c.w==='l'?' l':'')+(j===firstNum&&j>1?' gs':'');
    t.querySelector('thead').innerHTML='<tr><th class="l">#</th>'+
      cols.map((c,j)=>`<th class="${cls(c,j)}" data-k="${c.k}">${c.l}</th>`).join('')+'</tr>';
    let html='';
    for(let i=0;i<n;i++){
      const r=list[i];
      html+=`<tr data-c="${r[ix['コード']]}"><td class="l num-muted">${i+1}</td>`+
        cols.map((c,j)=>`<td class="${cls(c,j)}">${cellHTML(r,c)}</td>`).join('')+'</tr>';
    }
    t.querySelector('tbody').innerHTML=html;
    t.querySelectorAll('th[data-k]').forEach(th=>{
      th.classList.toggle('sorted',th.dataset.k===sortKey);
      th.classList.toggle('asc',th.dataset.k===sortKey&&sortAsc);
      th.onclick=()=>{
        if(sortKey===th.dataset.k)sortAsc=!sortAsc;
        else{sortKey=th.dataset.k;sortAsc=['PER','PBR','PSR','コード','銘柄名','EV/EBITDA'].includes(sortKey);}
        refresh();
      };
    });
  }
  box.style.display='';
  emptyEl.hidden=list.length>0;
  moreBtn.hidden=list.length<=n;
  moreBtn.textContent=`さらに表示（残り ${ni(list.length-n)} 銘柄）`;
  syncToolbars();
}
let sortKey='評価平均', sortAsc=false;
function sorted(list){
  const i=ix[sortKey]; const sgn=sortAsc?1:-1;
  return list.slice().sort((a,b)=>{
    let x=a[i],y=b[i];
    if(typeof x==='string'||typeof y==='string')return sgn*String(x).localeCompare(String(y),'ja');
    const xa=(x==null||!isFinite(x)), ya=(y==null||!isFinite(y));
    if(xa&&ya)return 0; if(xa)return 1; if(ya)return -1;   // 欠損は常に末尾
    return sgn*(x-y);
  });
}
const rankLim={n:100}, screenLim={n:100};
$('#rank-more').onclick=()=>{rankLim.n+=200;refresh()};
$('#screen-more').onclick=()=>{screenLim.n+=200;refresh()};

/* ---------- ランキング（スクリーニング定義表の ranking_definitions.csv） ---------- */
const RANKS=(DATA.定義表||{}).ranks||[];
const RGROUPS=[...new Set(RANKS.map(r=>r.g))];
// ランキングごとに並べる、参考の列（並べる値の列は先頭に別に出す）
const RCTX={
  '値動き':['株価','前日比(円)','前日比(%)','寄付比騰落率(%)','出来高(株)','売買代金(百万円)','時価総額(億円)'],
  '出来高・売買代金':['株価','前日比(%)','出来高(株)','出来高倍率(当日/25日)','売買代金(百万円)','売買代金増加率(%)','時価総額(億円)'],
  '株価指標':['株価','PER','予想PER','PBR','配当利回り(%)','ROE(%)','時価総額(億円)'],
  '信用残':['株価','前日比(%)','信用倍率(倍)','信用買残(株)','信用売残(株)','買残前日比(株)','売残前日比(株)','買残回転日数(日)'],
  'X01':['株価','ROE(%)','平均ROE(%)','ROIC税前(%)','営業利益率(%)','自己資本比率(%)','PER','時価総額(億円)'],
  'X02':['株価','理論株価乖離率・ファンダのみ(%)','理論株価の信頼度','PER','PBR','時価総額(億円)'],
  'X03':['株価','需給判定','信用倍率(倍)','買残回転日数(日)','信用買い評価損益率(%)','貸借倍率(倍)'],
  'X04':['株価','PER','PBR','EBITDAマージン(%)','ネットキャッシュ比率(%)','時価総額(億円)'],
  'X05':['株価','配当利回り(%)','連続増配期数','DOE(%)','配当性向(%)','時価総額(億円)'],
  'X06':['株価','総合評価','成長性評価','収益性評価','安全性評価','規模評価','割安度評価','値上がり評価','業種内偏差値'],
  'X07':['株価','業種内順位','総合評価','評価平均','時価総額(億円)','時価総額(百万ドル)'],
};
let rkId=(RANKS.find(r=>r.ok)||{}).id;
try{const v=localStorage.getItem('fdb-rank'); if(v&&RANKS.some(r=>r.id===v&&r.ok))rkId=v;}catch(e){}
// 開いているまとまり。初めては選んでいるランキングのまとまりだけ開く
let rkOpen=null;
try{const v=JSON.parse(localStorage.getItem('fdb-rkopen')||'null'); if(Array.isArray(v))rkOpen=new Set(v);}catch(e){}
if(!rkOpen)rkOpen=new Set([(RANKS.find(r=>r.id===rkId)||{}).g]);
const saveRkOpen=()=>{try{localStorage.setItem('fdb-rkopen',JSON.stringify([...rkOpen]))}catch(e){}};
$('#rkgroups').innerHTML=RANKS.length?RGROUPS.map(g=>{
  const rs=RANKS.filter(r=>r.g===g&&r.ok); if(!rs.length)return '';
  return `<details class="pg rkd" data-g="${g}"${rkOpen.has(g)?' open':''}><summary><span>${g}</span><span class="pgc">${rs.length}種</span>`+
    `<span class="rkcur"></span><span class="tri" aria-hidden="true">▼</span></summary><div class="rkg">`+rs.map(r=>
    `<button type="button" class="chip" data-r="${r.id}" title="${String(r.note||'').replace(/"/g,'&quot;')}">${r.name.replace(/上位$/,'')}</button>`).join('')+'</div></details>';
}).join(''):'<p class="note">スクリーニング定義表を読み込めませんでした（screening_config を確認してください）。</p>';
const naR=RANKS.filter(r=>!r.ok);
$('#rkna').textContent=naR.length?`作れないランキング：${naR.map(r=>r.name).join('、')}（板の気配値・ティック・注文の訂正取消は無料のデータでは取れないため）`:'';
$('#rkgroups').onclick=e=>{const b=e.target.closest('.chip'); if(!b)return;
  rkId=b.dataset.r; try{localStorage.setItem('fdb-rank',rkId)}catch(_){}; refresh();};
$('#rkPrice').onchange=()=>refresh();
$('#rkgroups').addEventListener('toggle',e=>{const d=e.target; if(!d.dataset||!d.dataset.g)return;
  d.open?rkOpen.add(d.dataset.g):rkOpen.delete(d.dataset.g); saveRkOpen();},true);
const rkAll=open=>{document.querySelectorAll('#rkgroups details').forEach(d=>{d.open=open;});
  rkOpen=new Set(open?RGROUPS:[]); saveRkOpen();};
$('#rkopenall').onclick=()=>rkAll(true);
$('#rkcloseall').onclick=()=>rkAll(false);
function ruleOk(r,x){
  const v=r[ix[x.k]];
  if(x.c==='FLT_PRICE_MIN'&&!$('#rkPrice').checked)return true;
  if(x.op==='range')return typeof v==='number'&&(x.lo==null||v>=x.lo)&&(x.hi==null||v<=x.hi);
  if(x.op==='=')return String(v)===String(x.v);
  if(typeof v!=='number'||!isFinite(v))return false;
  return x.op==='>'?v>x.v:x.op==='>='?v>=x.v:x.op==='<'?v<x.v:v<=x.v;
}
function renderRank(){
  const R=RANKS.find(r=>r.id===rkId);
  document.querySelectorAll('#rkgroups .chip').forEach(b=>b.setAttribute('aria-pressed',b.dataset.r===rkId));
  document.querySelectorAll('#rkgroups details').forEach(d=>{
    d.querySelector('.rkcur').textContent=R&&R.g===d.dataset.g?'● '+R.name:'';});
  const t=$('#t-rank');
  if(!R||ix[R.key]==null){t.querySelector('thead').innerHTML='';t.querySelector('tbody').innerHTML='';
    $('#rank-empty').hidden=false;$('#rank-more').hidden=true;return;}
  const j=ix[R.key], sg=R.asc?1:-1;
  const list=rows.filter(r=>{const v=r[j]; return typeof v==='number'&&isFinite(v)&&R.rules.every(x=>ruleOk(r,x));})
    .sort((a,b)=>sg*(a[j]-b[j]));
  const n=Math.min(list.length,R.n);
  const ctx=(RCTX[R.id]||RCTX[R.g]||['株価','時価総額(億円)']).filter(k=>k!==R.key&&ix[k]!=null);
  const vcol=colOf(R.key)||{k:R.key,l:R.key,t:'n2'};
  const cols=[COL['銘柄名'],Object.assign({},vcol,{rk:1}),...ctx.map(k=>colOf(k)).filter(Boolean)];
  const cls=c=>(c.t==='stock'?'stk':'')+(c.rk?' rkv':'');
  t.querySelector('thead').innerHTML='<tr><th class="rkno">順位</th>'+cols.map(c=>`<th class="${cls(c)}">${c.rk?`<span title="${(TNAME[c.k]||c.l).replace(/"/g,'&quot;')}">${(TNAME[c.k]||c.l).split('（')[0]}</span>`:c.l}</th>`).join('')+'</tr>';
  let html='';
  for(let i=0;i<n;i++){const r=list[i];
    html+=`<tr data-c="${r[ix['コード']]}"><td class="rkno">${i+1}</td>`+cols.map(c=>`<td class="${cls(c)}">${cellHTML(r,c)}</td>`).join('')+'</tr>';}
  t.querySelector('tbody').innerHTML=html;
  $('#rktitle').textContent=`ランキング：${R.name}`;
  const rl=R.rules.filter(x=>x.c!=='FLT_PRICE_MIN').map(x=>x.op==='='?`${TNAME[x.k]||x.k}が「${x.v}」`:`${TNAME[x.k]||x.k}${x.op}${x.v}`);
  $('#rkinfo').textContent=`${R.asc?'小さい':'大きい'}順に上位${R.n}件`+(rl.length?`・対象：${rl.join('、')}`:'')+
    (R.note?`・${R.note}`:'')+`（該当 ${ni(list.length)} 銘柄）`;
  $('#rank-empty').hidden=list.length>0;
  $('#rank-empty').textContent=list.length?'':`この順位に使う値（${TNAME[R.key]||R.key}）がまだありません。データがそろうと表示されます。`;
  $('#rank-more').hidden=true;
}

/* ---------- 一覧の上の操作列（表示の切替・並べ替え） ---------- */
// 並べ替えの候補。表の見出しが無いスマホでもここから選べる
const SORTS=[['評価平均','評価平均（総合評価の順）'],['業種内偏差値','業種内偏差値'],
  ...COLS.filter(c=>!['銘柄名','市場','業種','総合評価','評価平均','業種内偏差値'].includes(c.k))
    .map(c=>[c.k,c.t==='rt'?c.l+'の評価':c.l.replace(/%$/,'')]),['銘柄名','銘柄名']];
document.querySelectorAll('.tbar').forEach(el=>{
  el.innerHTML=`<span class="lab">表示</span><div class="views">`+
    Object.entries(VIEWS).map(([k,v])=>`<button class="chip" data-v="${k}">${v.l}</button>`).join('')+
    `</div><div class="sortbox"><span class="lab">並べ替え</span><select class="sortsel">`+
    SORTS.map(([k,l])=>`<option value="${k}">${l}</option>`).join('')+
    `</select><button class="dirbtn" title="昇順／降順">↓</button></div>`+
    ``;
  el.addEventListener('click',e=>{
    const b=e.target.closest('.views .chip');
    if(b){view=b.dataset.v; try{localStorage.setItem('fdb-view',view)}catch(_){}; refresh(); return;}
    const lb=e.target.closest('.lay .chip');
    if(lb){mlay=lb.dataset.l; try{localStorage.setItem('fdb-mlay',mlay)}catch(_){}; refresh(); return;}
    if(e.target.closest('.dirbtn')){sortAsc=!sortAsc; refresh();}
  });
  el.querySelector('.sortsel').onchange=e=>{
    sortKey=e.target.value;
    sortAsc=['PER','PBR','PSR','コード','銘柄名','EV/EBITDA'].includes(sortKey);
    refresh();
  };
});
function syncToolbars(){
  document.querySelectorAll('.tbar').forEach(el=>{
    el.querySelectorAll('.views .chip').forEach(c=>c.setAttribute('aria-pressed',c.dataset.v===view));
    el.querySelectorAll('.lay .chip').forEach(c=>c.setAttribute('aria-pressed',c.dataset.l===mlay));
    // スマホのカードは列を持たないので「表示」はカードの数値4つの切替として働く
    const s=el.querySelector('.sortsel');
    if(![...s.options].some(o=>o.value===sortKey))s.insertAdjacentHTML('beforeend',`<option value="${sortKey}">${sortKey}</option>`);
    s.value=sortKey;
    el.querySelector('.dirbtn').textContent=sortAsc?'↑ 小さい順':'↓ 大きい順';
  });
}

/* ---------- スクリーニング（条件ビルダー） ---------- */
// 絞り込みに使える指標。[列名, 表示名, 単位, 小数桁]
const METRICS=[
  ['予想PER','PER（会社予想）','倍',1],
  ['PER','PER（実績）','倍',1],
  ['PBR','PBR','倍',2],
  ['PSR','PSR','倍',2],
  ['EV/EBITDA','EV/EBITDA','倍',1],
  ['配当利回り(%)','配当利回り','%',2],
  ['配当性向(%)','配当性向','%',0],
  ['DOE(%)','DOE（配当総額÷平均自己資本）','%',2],
  ['平均DOE(%)','平均DOE（直近3期）','%',2],
  ['DOE変化(%pt)','DOEの前期比','%pt',2],
  ['減配回数','減配回数（最大4期）','回',0],
  ['連続増配期数','連続増配期数（最大3）','期',0],
  ['配当CAGR(%)','1株配当の年平均成長率','%',1],
  ['FCF配当性向(%)','FCF配当性向（配当総額÷フリーCF）','%',0],
  ['PEG','PEG（PER÷EPS成長率）','倍',2],
  ['益回り(%)','益回り（1÷PER）','%',2],
  ['EPS_CAGR(%)','EPSの年平均成長率','%',1],
  ['営業利益CAGR(%)','営業利益の年平均成長率','%',1],
  ['平均ROE(%)','平均ROE（最大4期）','%',1],
  ['ネットキャッシュ比率(%)','ネットキャッシュ÷時価総額','%',1],
  ['純有利子負債/EBITDA','純有利子負債÷EBITDA','倍',2],
  ['ROE(%)','ROE','%',1],
  ['ROA(%)','ROA','%',1],
  ['ROTC(%)','ROTC（投下資本利益率）','%',1],
  ['営業利益率(%)','営業利益率','%',1],
  ['純利益率(%)','純利益率','%',1],
  ['自己資本比率(%)','自己資本比率','%',1],
  ['流動比率(%)','流動比率','%',0],
  ['インタレストカバレッジ','インタレストカバレッジ','倍',1],
  ['営業CFマージン(%)','営業CFマージン','%',1],
  ['FCF利回り(%)','フリーCF利回り','%',1],
  ['売上高成長率(%)','増収率','%',1],
  ['営業利益成長率(%)','営業増益率','%',1],
  ['当期純利益成長率(%)','純利益成長率','%',1],
  ['時価総額(億円)','時価総額','億円',0],
  ['従業員数(人)','従業員数（連結。無ければ単体・有価証券報告書）','人',0],
  ['平均年収(万円)','平均年収（提出会社＝単体の平均年間給与・有価証券報告書）','万円',0],
  ['ベータ','ベータ（3年・市場感応度）','',2],
  ['ベータ(1年)','ベータ（1年）','',2],
  ['負債資本比率','負債資本比率（有利子負債÷自己資本）','倍',2],
  ['EBITDAマージン(%)','EBITDAマージン','%',1],
  ['1株当たりフリーCF','1株当たりフリーCF','円',1],
  ['年率ボラティリティ(%)','年率ボラティリティ','%',1],
  ['売上高CAGR(%)','売上高CAGR（4期）','%',1],
  ['平均経常利益率(%)','平均経常利益率（4期）','%',1],
  ['予想経常増益率(%)','今期予想の経常増益率','%',1],
  ['平均税引前利益率(%)','平均税引前利益率（4期）','%',1],
  ['250日騰落率(%)','250日騰落率','%',1],
  ['125日騰落率(%)','6か月騰落率','%',1],
  ['52週レンジ位置(%)','52週レンジ位置（0=安値・100=高値）','%',1],
  ['新高値からの日数','52週新高値からの営業日数（0=最新日に更新）','日',0],
  ['新高値回数(20日)','直近20営業日の52週新高値の回数','回',0],
  ['52週高値乖離(%)','52週高値からの下落率（0=高値）','%',1],
  ['上場来高値からの日数','上場来高値からの営業日数（0=最新日に更新）','日',0],
  ['上場来高値乖離(%)','上場来高値からの下落率（0=高値）','%',1],
  ['出来高倍率(5日/50日)','出来高倍率（直近5日÷50日）','倍',2],
  ['移動平均線の上の本数','株価が上にある移動平均線の本数（5/25/75/200日）','本',0],
  ['5日線乖離(%)','5日移動平均線からの乖離','%',1],
  ['25日線乖離(%)','25日移動平均線からの乖離','%',1],
  ['75日線乖離(%)','75日移動平均線からの乖離','%',1],
  ['200日線乖離(%)','200日移動平均線からの乖離','%',1],
  ['横ばい上放れ','横ばいからの上放れ（1=該当）','',0],
  ['ボックス幅(%)','横ばい期間（前60営業日）の値幅','%',1],
  ['ボックス上抜け(%)','横ばい期間の最高値からの上抜け率','%',1],
  ['営業増益率3期平均(%)','営業増益率の3期平均（今期予想込み）','%',1],
  ['営業増益率3期最低(%)','営業増益率の3期のうち最低','%',1],
  ['営業CF2期黒字','直近2期の営業CFがともに黒字（1=該当）','',0],
  ['マルチバガースコア','マルチバガー適合度スコア','点',1],
  ['論文スコア','マルチバガー論文スコア（100点）','点',1],
  ['B/M','簿価/時価（B/M＝1÷PBR）','',2],
  ['総資産成長率(%)','総資産成長率（直近期の前期比）','%',1],
  ['EBITDA成長率(%)','EBITDA成長率（直近期の前期比）','%',1],
  ['Invダミー','Invダミー（1=資産の伸び＞EBITDAの伸び）','',0],
  ['評価値スコア','　内訳: 評価値（FCF利回り・安定性）','点',1],
  ['エントリースコア','　内訳: エントリー（52週位置・6か月）','点',1],
  ['品質スコア','　内訳: 品質（資産vsEBITDA・投資効率）','点',1],
  ['P/FCF','P/FCF（時価総額÷フリーCF）','倍',1],
  ['FCF黒字比率(%)','フリーCFが黒字だった期の割合','%',0],
  ['成長ギャップ(%pt)','成長ギャップ（総資産CAGR−EBITDA CAGR）','%pt',1],
  ['設備投資/売上(%)','設備投資÷売上高','%',1],
  ['FCF/設備投資','フリーCF÷設備投資','倍',1],
  ['純有利子負債/自己資本','純有利子負債÷自己資本（ネットD/E）','倍',2],
  ['ネットキャッシュ倍率','ネットキャッシュ倍率（時価総額÷換金性資産）','倍',2],
  ['換金性資産(億円)','換金性資産（流動資産−負債合計）','億円',0],
  ['成長性評価','成長性の評価','1〜5',0],
  ['収益性評価','収益性の評価','1〜5',0],
  ['安全性評価','安全性の評価','1〜5',0],
  ['規模評価','規模の評価','1〜5',0],
  ['割安度評価','割安度の評価','1〜5',0],
  ['値上がり評価','値上がりの評価','1〜5',0],
  ['評価平均','評価平均（6項目）','',2],
  ['業種内偏差値','業種内偏差値（同業の中での位置）','',1],
  ['総合評価','総合評価','1〜5',0],
  ['Fスコア','Fスコア（改善の兆し・0〜9点）','点',0],
  ['予想Fスコア','予想Fスコア（会社予想ベース・0〜9点）','点',0],
  // ---- ここから SBI証券スクリーナーの項目に合わせて追加（2026-09-24） ----
  ['株価','株価','円',0],
  ['最低投資金額(万円)','最低投資金額（株価×100株）','万円',1],
  ['決算月','決算月','月',0],
  ['売上高(億円)','売上高','億円',0],
  ['営業利益(億円)','営業利益','億円',0],
  ['当期純利益(億円)','当期純利益','億円',0],
  ['自己資本(億円)','自己資本','億円',0],
  ['EV(億円)','EV（企業価値）','億円',0],
  ['PCFR','PCFR（時価総額÷営業CF）','倍',1],
  ['EPS','EPS（1株当たり利益・実績）','円',1],
  ['BPS','BPS（1株当たり純資産）','円',0],
  ['直近経常利益率(%)','売上高経常利益率（直近期）','%',1],
  ['総資産CAGR(%)','総資産CAGR','%',1],
  ['EBITDA_CAGR(%)','EBITDA CAGR','%',1],
  ['予想EPS(円)','予想EPS（会社予想）','円',1],
  ['予想1株配当(円)','予想1株配当（会社予想）','円',1],
  ['予想配当利回り(%)','予想配当利回り（会社予想）','%',2],
  ['予想売上高成長率(%)','予想増収率（今期予想÷前期実績）','%',1],
  ['予想営業増益率(%)','予想営業増益率（今期予想÷前期実績）','%',1],
  ['予想純利益率(%)','予想純利益率','%',1],
  ['今期予想売上高(億円)','今期予想 売上高','億円',0],
  ['今期予想営業利益(億円)','今期予想 営業利益','億円',0],
  ['今期予想経常利益(億円)','今期予想 経常利益','億円',0],
  ['今期予想純利益(億円)','今期予想 純利益','億円',0],
  ['今期予想営業利益率(%)','今期予想 営業利益率','%',1],
  ['業績予想修正率(%)','業績予想修正率（最後の修正。＋上方／−下方）','%',1],
  ['決算発表からの日数','最新の決算短信の発表からの日数（TDnet）','日',0],
  ['累計増収率(%)','最新決算の増収率（四半期は累計の前年同期比・TDnet）','%',1],
  ['累計営業増益率(%)','最新決算の営業増益率（累計の前年同期比。営業利益の無い会社は経常利益）','%',1],
  ['累計純益増益率(%)','最新決算の純利益の増益率（累計の前年同期比）','%',1],
  ['営業益進捗率(%)','通期の会社予想に対する営業利益の進捗率（第1〜3四半期）','%',1],
  ['期初予想比(%)','期初予想からの修正の累計','%',1],
  ['予想修正からの日数','業績予想を修正してからの日数（暦日）','日',0],
  ['配当予想修正率(%)','配当予想修正率（＋増配／−減配）','%',1],
  ['決算サプライズ(%)','決算サプライズ（実績÷発表直前の会社予想−1）','%',1],
  ['前日比(円)','前日比（円）','円',1],
  ['前日比(%)','前日比（値上がり率・値下がり率）','%',2],
  ['5日騰落率(%)','5日騰落率（1週間）','%',1],
  ['20日騰落率(%)','20日騰落率（4週間）','%',1],
  ['対市場超過(1日)(%pt)','市場との差（1日。＋なら市場より強い）','%pt',2],
  ['対市場超過(20日)(%pt)','市場との差（20日）','%pt',1],
  ['売買代金(百万円)','売買代金（最新日）','百万円',0],
  ['平均売買代金(百万円)','平均売買代金（25日）','百万円',0],
  ['売買代金増加率(%)','売買代金増加率（最新日÷25日平均−1）','%',0],
  ['出来高増加率(%)','出来高増加率（前日比）','%',0],
  ['出来高倍率(6日/25日)','出来高倍率（6日平均÷25日平均）','倍',2],
  ['60日ボラティリティ(%)','60日ボラティリティ（年率）','%',1],
  ['52週安値からの上昇率(%)','52週安値からの上昇率','%',1],
  ['年初来高値からの日数','年初来高値からの営業日数（0=最新日に更新）','日',0],
  ['年初来安値からの日数','年初来安値からの営業日数（0=最新日に更新）','日',0],
  ['年初来高値乖離(%)','年初来高値からの下落率（0=高値）','%',1],
  ['年初来安値からの上昇率(%)','年初来安値からの上昇率','%',1],
  ['GC(5×25)からの日数','ゴールデンクロス①（5日×25日）からの日数','日',0],
  ['GC(25×75)からの日数','ゴールデンクロス②（25日×75日）からの日数','日',0],
  ['GC(75×200)からの日数','ゴールデンクロス③（75日×200日）からの日数','日',0],
  ['DC(5×25)からの日数','デッドクロス①（5日×25日）からの日数','日',0],
  ['DC(25×75)からの日数','デッドクロス②（25日×75日）からの日数','日',0],
  ['DC(75×200)からの日数','デッドクロス③（75日×200日）からの日数','日',0],
  ['一目 雲の位置','一目均衡表 雲の位置（1=上・0=中・−1=下）','',0],
  ['雲上抜けからの日数','一目 雲抜け上からの日数','日',0],
  ['雲下抜けからの日数','一目 雲抜け下からの日数','日',0],
  ['ボリンジャー位置(σ)','ボリンジャーバンド（25日）の位置','σ',2],
  ['RSI(14)(%)','RSI（14日）','%',1],
  ['RCI(9)(%)','RCI（9日）','%',1],
  ['RCI(26)(%)','RCI（26日）','%',1],
  ['ストキャス%K(9)','ストキャスティクス %K（9日）','%',1],
  ['ストキャス%D','ストキャスティクス %D','%',1],
  ['スローストキャス%D','スローストキャスティクス %D（SD）','%',1],
  ['+DI(14)','DMI ＋DI（14日）','',1],
  ['−DI(14)','DMI −DI（14日）','',1],
  ['ADX(14)','DMI ADX（トレンドの強さ）','',1],
  ['サイコロジカル(12)(%)','サイコロジカルライン（12日）','%',1],
  ['MACDヒストグラム(%)','MACD−シグナル（株価比。＋なら好転）','%',2],
  ['MACD GCからの日数','MACDがシグナルを上抜けてからの日数','日',0],
  ['新値3本足','新値3本足（1=陽線・−1=陰線）','',0],
  ['新値3本足の転換からの日数','新値3本足の転換からの日数','日',0],
  ['ベータ(対業種)(1年)','ベータ（対東証業種・1年）','',2],
  ['ドル円感応度(2年)','ドル円感応度（＋なら円安で上がりやすい）','',2],
  ['需給スコア','需給スコア（0〜100、50が中立）','点',0],
  ['信用買残(株)','信用買残','株',0],
  ['信用売残(株)','信用売残','株',0],
  ['信用倍率(倍)','信用倍率（買残÷売残）','倍',2],
  ['買残前日比(株)','信用買残の前日比','株',0],
  ['売残前日比(株)','信用売残の前日比','株',0],
  ['買残5日変化(%)','信用買残の5営業日変化','%',1],
  ['買残20日変化(%)','信用買残の20営業日変化','%',1],
  ['売残5日変化(%)','信用売残の5営業日変化','%',1],
  ['売残20日変化(%)','信用売残の20営業日変化','%',1],
  ['買残上場比(%)','信用買残の上場株数比','%',2],
  ['売残上場比(%)','信用売残の上場株数比','%',2],
  ['買残回転日数(日)','買残回転日数（買残÷25日平均出来高）','日',1],
  ['売残回転日数(日)','売残回転日数（売残÷25日平均出来高）','日',2],
  ['一般信用買残比率(%)','買残のうち一般信用の割合','%',0],
  ['信用買い評価損益率(%)','信用買い方の評価損益率','%',1],
  ['信用売り評価損益率(%)','信用売り方の評価損益率','%',1],
  ['貸借倍率(倍)','日証金の貸借倍率（融資÷貸株）','倍',2],
  ['日証金差引(株)','日証金の差引残（融資−貸株）','株',0],
  ['逆日歩(円)','逆日歩（1株・円）','円',2],
  ['逆日歩(年率%)','逆日歩の年率換算','%',1],
  ['大口空売り比率(%)','大口空売り残高割合の合計（0.5%以上の報告）','%',2],
  ['大口空売り報告数','大口空売りの報告件数','件',0],
  ['大口空売り30日変化(%pt)','大口空売り比率の30日変化','%pt',2],
  ['出来高倍率(当日/25日)','出来高倍率（当日÷25日平均）','倍',2],
  ['売買代金25日平均(百万円)','売買代金25日平均','百万円',0],
  ['最多価格帯からの乖離(%)','価格帯別出来高の最多価格帯からの乖離（60日）','%',1],
  ['上値出来高比率(%)','現在値より上の価格帯の出来高割合（60日）','%',0],
];
// 「条件を追加」の選択肢をSBI証券のスクリーナーに近いまとまりで並べる（無い項目は最後の「その他」へ）
let MGROUPS=[
  ['基本・規模',['株価','最低投資金額(万円)','時価総額(億円)','決算月','売上高(億円)','営業利益(億円)',
    '当期純利益(億円)','自己資本(億円)','EV(億円)','従業員数(人)','平均年収(万円)']],
  ['財務：割安度',['予想PER','PER','PBR','PSR','PCFR','EV/EBITDA','PEG','益回り(%)','FCF利回り(%)','P/FCF','B/M',
    'EPS','BPS','ネットキャッシュ比率(%)','ネットキャッシュ倍率','換金性資産(億円)']],
  ['財務：配当',['配当利回り(%)','配当性向(%)','DOE(%)','平均DOE(%)','DOE変化(%pt)','減配回数','連続増配期数',
    '配当CAGR(%)','FCF配当性向(%)','1株当たりフリーCF']],
  ['財務：収益性',['ROE(%)','平均ROE(%)','ROA(%)','ROTC(%)','営業利益率(%)','直近経常利益率(%)','平均経常利益率(%)',
    '平均税引前利益率(%)','純利益率(%)','EBITDAマージン(%)','営業CFマージン(%)']],
  ['財務：安全性',['自己資本比率(%)','流動比率(%)','負債資本比率','純有利子負債/自己資本','純有利子負債/EBITDA',
    'インタレストカバレッジ','設備投資/売上(%)','FCF/設備投資','FCF黒字比率(%)','営業CF2期黒字']],
  ['財務：成長性',['売上高成長率(%)','営業利益成長率(%)','当期純利益成長率(%)','売上高CAGR(%)','営業利益CAGR(%)',
    'EPS_CAGR(%)','営業増益率3期平均(%)','営業増益率3期最低(%)','総資産CAGR(%)','EBITDA_CAGR(%)',
    '総資産成長率(%)','EBITDA成長率(%)','成長ギャップ(%pt)','Invダミー']],
  ['会社予想（SBIのコンセンサス欄の代わり）',['予想EPS(円)','予想1株配当(円)','予想配当利回り(%)',
    '予想売上高成長率(%)','予想営業増益率(%)','予想経常増益率(%)','予想純利益率(%)','今期予想売上高(億円)',
    '今期予想営業利益(億円)','今期予想経常利益(億円)','今期予想純利益(億円)','今期予想営業利益率(%)',
    '業績予想修正率(%)','期初予想比(%)','予想修正からの日数','配当予想修正率(%)','決算サプライズ(%)',
    '決算発表からの日数','累計増収率(%)','累計営業増益率(%)','累計純益増益率(%)','営業益進捗率(%)']],
  ['株価パフォーマンス',['前日比(円)','前日比(%)','5日騰落率(%)','20日騰落率(%)','125日騰落率(%)','250日騰落率(%)',
    '対市場超過(1日)(%pt)','対市場超過(20日)(%pt)','売買代金(百万円)','平均売買代金(百万円)','売買代金増加率(%)',
    '出来高増加率(%)','出来高倍率(6日/25日)','出来高倍率(5日/50日)','60日ボラティリティ(%)','年率ボラティリティ(%)',
    '52週レンジ位置(%)','52週高値乖離(%)','52週安値からの上昇率(%)','新高値からの日数','新高値回数(20日)',
    '年初来高値からの日数','年初来安値からの日数','年初来高値乖離(%)','年初来安値からの上昇率(%)',
    '上場来高値からの日数','上場来高値乖離(%)']],
  ['テクニカル',['5日線乖離(%)','25日線乖離(%)','75日線乖離(%)','200日線乖離(%)','移動平均線の上の本数',
    'GC(5×25)からの日数','GC(25×75)からの日数','GC(75×200)からの日数',
    'DC(5×25)からの日数','DC(25×75)からの日数','DC(75×200)からの日数',
    '一目 雲の位置','雲上抜けからの日数','雲下抜けからの日数','ボリンジャー位置(σ)','RSI(14)(%)','RCI(9)(%)','RCI(26)(%)',
    'ストキャス%K(9)','ストキャス%D','スローストキャス%D','+DI(14)','−DI(14)','ADX(14)','サイコロジカル(12)(%)',
    'MACDヒストグラム(%)','MACD GCからの日数','新値3本足','新値3本足の転換からの日数',
    '横ばい上放れ','ボックス幅(%)','ボックス上抜け(%)',
    'ベータ','ベータ(1年)','ベータ(対業種)(1年)','ドル円感応度(2年)']],
  ['需給（信用残・空売り・出来高）',['需給スコア','信用倍率(倍)','信用買残(株)','信用売残(株)','買残前日比(株)','売残前日比(株)',
    '買残5日変化(%)','買残20日変化(%)','売残5日変化(%)','売残20日変化(%)','買残上場比(%)','売残上場比(%)',
    '買残回転日数(日)','売残回転日数(日)','一般信用買残比率(%)','信用買い評価損益率(%)','信用売り評価損益率(%)',
    '貸借倍率(倍)','日証金差引(株)','逆日歩(円)','逆日歩(年率%)','大口空売り比率(%)','大口空売り報告数',
    '大口空売り30日変化(%pt)','出来高倍率(当日/25日)','売買代金25日平均(百万円)','最多価格帯からの乖離(%)','上値出来高比率(%)']],
  ['スコア・評価',['総合評価','成長性評価','収益性評価','安全性評価','規模評価','割安度評価','値上がり評価',
    '評価平均','業種内偏差値','Fスコア','予想Fスコア','マルチバガースコア','論文スコア',
    '評価値スコア','エントリースコア','品質スコア']],
];
// ---- スクリーニング定義表（screening_config）の条件。ページに無かった列は dashboard_bridge.py が足している
const TEIGI=DATA.定義表||{conds:[],ranks:[],added:[]};
const DIGITS={'%':1,'倍':2,'円':0,'株':0,'日':0,'回':1,'年':0,'億円':0,'百万円':0,'万円':1,'点':0,'本':0,'σ':2,'':1};
const CAT=new Set(TEIGI.conds.filter(c=>c.kind==='cat').map(c=>c.key));
const CATORDER=Object.fromEntries(TEIGI.conds.filter(c=>c.kind==='cat').map(c=>[c.key,c.order]));
(function(){
  const have=new Set(METRICS.map(m=>m[0]));
  TEIGI.conds.forEach(c=>{
    if(have.has(c.key)||ix[c.key]==null)return;
    METRICS.push([c.key,c.name,c.kind==='cat'?'':c.unit,DIGITS[c.unit]??1]); have.add(c.key);
  });
  // 定義表の区分ごとのまとまりを先頭に。上の絞り込み欄で選べるもの（市場・業種など）は出さない
  const defg=[], seen=new Set();
  TEIGI.conds.forEach(c=>{
    if(c.bar||ix[c.key]==null||seen.has(c.key))return; seen.add(c.key);
    let g=defg.find(x=>x[0]===c.g); if(!g){g=[c.g,[]];defg.push(g);} g[1].push(c.key);
  });
  // 定義表に無い指標（Fスコア・DOE・各種スコアなど）はもとのまとまりのまま後ろに残す
  const rest=MGROUPS.map(([g,ks])=>['定義表外：'+g.replace(/（.*$/,''),ks.filter(k=>!seen.has(k))]).filter(x=>x[1].length);
  MGROUPS.splice(0,MGROUPS.length,...defg,...rest);
})();
const TNAME=Object.fromEntries(TEIGI.conds.map(c=>[c.key,c.name]));
const METRIC=Object.fromEntries(METRICS.map(m=>[m[0],m]));

// よく使う条件。押すと下の条件欄に入り、そこから数値を変えられる。
// 流動比率は%で持っているので、1倍=100、1.5倍=150に読み替えている。
const PRESETS={
  '割安株':      [['PER',0,10],['PBR',null,0.6],['流動比率(%)',200,null],['負債資本比率',null,0.5]],
  '成長株':      [['売上高成長率(%)',20,null],['ROE(%)',20,null],['純利益率(%)',10,null]],
  '高配当株':    [['配当利回り(%)',4,null],['配当性向(%)',30,60],['1株当たりフリーCF',0.01,null],['自己資本比率(%)',50,null]],
  'DOE安定配当株':[['DOE(%)',5,null],['平均DOE(%)',5,null],['減配回数',null,0],['DOE変化(%pt)',-1,3],
                 ['自己資本比率(%)',60,null],['配当性向(%)',0,70]],
  '連続増配株':  [['連続増配期数',3,null],['配当CAGR(%)',15,50],['配当性向(%)',0,40],['FCF配当性向(%)',null,60],
                 ['ROE(%)',12,null],['自己資本比率(%)',50,null]],
  'PEG割安成長株':[['PEG',0,0.6],['EPS_CAGR(%)',15,50],['営業利益CAGR(%)',15,null],['平均ROE(%)',15,null],
                 ['純有利子負債/EBITDA',null,2]],
  '新高値ブレイク株':[['新高値からの日数',null,4],['売上高成長率(%)',10,null],['営業利益成長率(%)',10,null]],
  '成長ブレイク株':[['営業増益率3期平均(%)',30,null],['自己資本比率(%)',50,null],['営業CF2期黒字',1,null],
                 ['移動平均線の上の本数',4,null]],
  '上場来高値更新株':[['上場来高値からの日数',null,4],['売上高成長率(%)',5,null],['営業利益成長率(%)',5,null]],
  '安定優良株':  [['ROE(%)',20,null],['流動比率(%)',200,null],['負債資本比率',null,0.3],['ベータ(1年)',null,0.8]],
  '高収益企業':  [['ROE(%)',25,null],['ROTC(%)',20,null],['EBITDAマージン(%)',20,null],['純利益率(%)',10,null]],
  'マルチバガー候補':[['マルチバガースコア',70,null],['52週レンジ位置(%)',null,30],
                 ['125日騰落率(%)',null,5],['ROE(%)',15,null],['営業利益率(%)',10,null],
                 ['時価総額(億円)',100,5000],['売上高成長率(%)',5,null]],
  'マルチバガー論文準拠':[['論文スコア',72,null]],
  '論文準拠・安値圏':[['論文スコア',60,null],['52週レンジ位置(%)',null,30],['125日騰落率(%)',null,0]],
  '復活Fスコア':[['PBR',0,0.8],['予想Fスコア',9,null],['時価総額(億円)',1000,null]],
  // ---- SBI証券のスクリーナーの項目を使った条件（2026-09-24 追加。どれも100銘柄未満） ----
  'GC＋出来高増':[['GC(5×25)からの日数',null,4],['出来高倍率(6日/25日)',1.3,null],['売上高成長率(%)',5,null],
                 ['自己資本比率(%)',40,null]],
  '雲上抜け＋MACD好転':[['雲上抜けからの日数',null,5],['MACD GCからの日数',null,5],['ADX(14)',20,null],
                 ['売上高成長率(%)',5,null]],
  '売られすぎ優良株':[['RSI(14)(%)',null,35],['自己資本比率(%)',50,null],['ROE(%)',8,null]],
  '年初来高値＋商い増':[['年初来高値からの日数',null,0],['売買代金増加率(%)',100,null],['平均売買代金(百万円)',100,null]],
  '市場より強い割安株':[['対市場超過(20日)(%pt)',10,null],['新値3本足',1,null],['PER',null,15],['ROE(%)',10,null]],
  '上方修正銘柄':[['業績予想修正率(%)',10,null],['予想営業増益率(%)',10,null]],
  '決算サプライズ':[['決算サプライズ(%)',15,null],['予想営業増益率(%)',15,null],['自己資本比率(%)',40,null]],
  '直近の好決算':[['決算発表からの日数',null,14],['累計増収率(%)',10,null],['累計営業増益率(%)',20,null]],
  '増配予想':[['配当予想修正率(%)',0.01,null],['予想配当利回り(%)',3.5,null],['自己資本比率(%)',50,null]],
  '低PCFR株':[['PCFR',0,4],['PBR',null,0.8],['自己資本比率(%)',50,null]],
  'なごちょう式':[['ネットキャッシュ倍率',null,1],['売上高CAGR(%)',10,null],['自己資本比率(%)',50,null],
                 ['流動比率(%)',200,null],['営業利益率(%)',10,null],['配当利回り(%)',3,null],
                 ['PER',null,10],['PBR',null,1]],
};

let conds=[];   // {k, min, max}
$('#screenbar').innerHTML=Object.keys(PRESETS).map(n=>
  `<button class="chip" data-s="${n}">${n}</button>`).join('');
$('#screenbar').onclick=e=>{const b=e.target.closest('.chip');if(!b)return;
  conds=PRESETS[b.dataset.s].map(([k,mn,mx])=>({k,min:mn,max:mx}));
  if(b.dataset.s.includes('論文')){sortKey='論文スコア';sortAsc=false;}
  if(b.dataset.s==='成長ブレイク株'){sortKey='横ばい上放れ';sortAsc=false;}
  if(b.dataset.s==='上方修正銘柄'){sortKey='業績予想修正率(%)';sortAsc=false;}
  if(b.dataset.s==='決算サプライズ'){sortKey='決算サプライズ(%)';sortAsc=false;}
  if(b.dataset.s==='直近の好決算'){sortKey='累計営業増益率(%)';sortAsc=false;}
  if(b.dataset.s==='売られすぎ優良株'){sortKey='RSI(14)(%)';sortAsc=true;}
  if(b.dataset.s==='市場より強い割安株'){sortKey='対市場超過(20日)(%pt)';sortAsc=false;}
  document.querySelectorAll('#screenbar .chip').forEach(c=>c.setAttribute('aria-pressed',c===b));
  if(isMobile()){const sb=$('#screenbar'); sb.scrollTo({left:b.offsetLeft-sb.offsetLeft-14,behavior:'smooth'});}
  screenLim.n=100; drawConds(); refresh();};

/* ---------- 条件の範囲スライダー ---------- */
// 目盛りは全銘柄の2〜98%点の範囲（外れ値でつまみが片寄らないように）。整数で幅が24以下の項目は1刻み。
const niceStep=x=>{if(!(x>0))return 1;const e=Math.pow(10,Math.floor(Math.log10(x)));const f=x/e;
  return (f<1.5?1:f<3?2:f<7?5:10)*e;};
const decOf=st=>Math.max(0,-Math.floor(Math.log10(st)+1e-9));
const fmtN=(v,d)=>Number(v).toLocaleString('ja-JP',{maximumFractionDigits:d});
const MSTAT={};
function rsGeom(k){
  if(k in MSTAT)return MSTAT[k];
  const col=ix[k];
  const v=col==null?[]:S.map(r=>r[col]).filter(x=>typeof x==='number'&&isFinite(x)).sort((a,b)=>a-b);
  if(v.length<2)return MSTAT[k]=null;
  const q=p=>v[Math.round(p*(v.length-1))];
  const allInt=v.every(x=>Number.isInteger(x));
  let lo,hi,step,disc=false;
  if(allInt&&v[v.length-1]-v[0]<=24){lo=v[0];hi=v[v.length-1];step=1;disc=true;}
  else{
    lo=q(0.02);hi=q(0.98); if(!(hi>lo)){lo=v[0];hi=v[v.length-1];}
    step=niceStep((hi-lo)/200); if(allInt)step=Math.max(1,Math.round(step));
    lo=Math.floor(lo/step)*step; hi=Math.ceil(hi/step)*step;
  }
  const dec=disc?0:decOf(step);
  return MSTAT[k]={lo:+lo.toFixed(dec),hi:+hi.toFixed(dec),step,disc,dec,
    nb:disc?hi-lo+1:40, a:disc?lo-0.5:lo, b:disc?hi+0.5:hi};
}
const fr=(g,v)=>Math.max(0,Math.min(1,(v-g.a)/(g.b-g.a)));
function valAt(g,f){let v=g.a+f*(g.b-g.a); v=Math.round(v/g.step)*g.step;
  return +Math.max(g.lo,Math.min(g.hi,v)).toFixed(g.dec);}

function catValues(k){
  const cnt=new Map(); const j=ix[k];
  rows.forEach(r=>{const v=r[j]; if(v!=null&&v!=='')cnt.set(String(v),(cnt.get(String(v))||0)+1);});
  const all=new Set(S.map(r=>r[j]).filter(v=>v!=null&&v!=='').map(String));
  const ord=(CATORDER[k]||[]).filter(v=>all.has(v));
  return ord.concat([...all].filter(v=>!ord.includes(v)).sort()).map(v=>[v,cnt.get(v)||0]);
}
function condRowHTML(c,i){
  const m=METRIC[c.k]||[c.k,c.k,'',2], g=rsGeom(c.k);
  if(c.vals)return `<div class="cond" data-i="${i}">
    <div class="ctop"><span class="cname">${TNAME[c.k]||m[1]}</span>
      <span class="cin"><span class="unit">${c.vals.length?'選んだものに当てはまる銘柄':'どれも選んでいない＝制限なし'}</span></span>
      <button class="del" aria-label="この条件を消す">×</button></div>
    <div class="cvals">${catValues(c.k).map(([v,n])=>`<button type="button" class="chip" data-v="${he(v)}" aria-pressed="${c.vals.includes(v)}">${he(v)}<small>${ni(n)}</small></button>`).join('')}</div>
  </div>`;
  return `<div class="cond" data-i="${i}">
    <div class="ctop"><span class="cname">${m[1]}</span>
      <span class="cin"><input type="number" class="cmin" step="any" placeholder="下限なし" value="${c.min??''}" aria-label="${m[1]}の下限">
      <span class="tilde">〜</span>
      <input type="number" class="cmax" step="any" placeholder="上限なし" value="${c.max??''}" aria-label="${m[1]}の上限">
      <span class="unit">${m[2]}</span></span>
      <button class="del" aria-label="この条件を消す">×</button></div>
    ${g?`<div class="rs"><div class="hist">${'<i></i>'.repeat(g.nb)}</div><div class="trk"><div class="fill"></div></div>
      <button class="h h0" role="slider" aria-label="${m[1]}の下限"></button>
      <button class="h h1" role="slider" aria-label="${m[1]}の上限"></button></div>
      <div class="rsax"><span>${g.disc?'':'〜'}${fmtN(g.lo,g.dec)}${m[2]}</span><span class="cnt"></span><span>${fmtN(g.hi,g.dec)}${m[2]}${g.disc?'':'〜'}</span></div>`:''}
  </div>`;
}
// 条件欄はスマホでは普段畳んでおく（PCは開いておく）
let condOpen=!matchMedia('(max-width:720px)').matches;
function setCondOpen(v){
  condOpen=v; $('#condlist').hidden=!v;
  $('#condtoggle').setAttribute('aria-expanded',String(v));
  $('#condtt').textContent=v?'閉じる':'開く';
}
$('#condtoggle').onclick=()=>setCondOpen(!condOpen);
// 畳んでいる間の要約。「PER 0〜10倍・PBR 0.6倍以下…」
function condText(c){
  if(c.vals)return `${(TNAME[c.k]||c.k).split('（')[0]} ${c.vals.length?c.vals.join('・'):'制限なし'}`;
  const m=METRIC[c.k]||[c.k,c.k,'',2], u=m[2]==='1〜5'?'':m[2];
  const name=m[1].split('（')[0];
  const f=v=>fmtN(v,Math.max(0,m[3]));
  const r=c.min!=null&&c.max!=null?`${f(c.min)}〜${f(c.max)}${u}`
    :c.min!=null?`${f(c.min)}${u}以上`:c.max!=null?`${f(c.max)}${u}以下`:'制限なし';
  return `${name} ${r}`;
}
function drawSum(){
  $('#condn').textContent=conds.length;
  $('#condsum').textContent=conds.length?conds.map(condText).join('・'):'条件なし（上のボタンか「条件を追加」から）';
}
function drawConds(){
  $('#condlist').innerHTML=conds.length?conds.map(condRowHTML).join('')
    : '<p class="note" style="margin:6px 0 0">条件がありません。上のボタンを押すか「条件を追加」から選んでください。</p>';
  document.querySelectorAll('#condlist .cond').forEach(el=>{syncRow(el);histRow(el);});
  if(!$('#picker').hidden)drawPicker();
  drawSum(); setCondOpen(condOpen);
}
// つまみ・帯の位置
function syncRow(el){
  const c=conds[+el.dataset.i]; if(c.vals)return;
  const g=rsGeom(c.k), rs=el.querySelector('.rs'); if(!g||!rs)return;
  const f0=c.min==null?0:fr(g,c.min), f1=c.max==null?1:fr(g,c.max);
  const h0=rs.querySelector('.h0'), h1=rs.querySelector('.h1'), fill=rs.querySelector('.fill');
  h0.style.left=f0*100+'%'; h1.style.left=f1*100+'%';
  fill.style.left=f0*100+'%'; fill.style.width=Math.max(0,f1-f0)*100+'%';
  h0.classList.toggle('off',c.min==null); h1.classList.toggle('off',c.max==null);
  h0.setAttribute('aria-valuetext',c.min==null?'下限なし':fmtN(c.min,g.dec));
  h1.setAttribute('aria-valuetext',c.max==null?'上限なし':fmtN(c.max,g.dec));
  // 同じ位置に重なったら、動かせる向きのつまみを上にする
  h0.style.zIndex=f0>=0.999?2:1;
}
// 分布（上の絞り込みを通った銘柄）と、この条件だけで残る数
function histRow(el){
  const c=conds[+el.dataset.i];
  if(c.vals){el.querySelectorAll('.cvals .chip').forEach(b=>{const n=catValues(c.k).find(x=>x[0]===b.dataset.v);
    b.querySelector('small').textContent=ni(n?n[1]:0);}); return;}
  const g=rsGeom(c.k), bars=el.querySelectorAll('.hist i'); if(!g||!bars.length)return;
  const cnt=new Array(g.nb).fill(0), col=ix[c.k], w=(g.b-g.a)/g.nb; let inr=0;
  for(const r of rows){const v=r[col]; if(typeof v!=='number'||!isFinite(v))continue;
    let b=Math.floor((v-g.a)/w); cnt[b<0?0:b>=g.nb?g.nb-1:b]++;
    if((c.min==null||v>=c.min)&&(c.max==null||v<=c.max))inr++;}
  const mx=Math.max(1,...cnt);
  bars.forEach((e,j)=>{
    e.style.height=cnt[j]?Math.max(5,Math.sqrt(cnt[j]/mx)*100)+'%':'0';
    const l=g.a+j*w, h=l+w;
    e.classList.toggle('in',(c.min==null||h>c.min)&&(c.max==null||l<c.max));
  });
  el.querySelector('.cnt').textContent=`この条件だけで ${ni(inr)} 銘柄`;
}
function syncInputs(el,c){el.querySelector('.cmin').value=c.min??''; el.querySelector('.cmax').value=c.max??'';}
let rsRaf=0;
const schedule=()=>{if(rsRaf)return; rsRaf=requestAnimationFrame(()=>{rsRaf=0; screenLim.n=100; refresh();});};
const posFrac=(rs,x)=>{const b=rs.getBoundingClientRect(); return Math.max(0,Math.min(1,(x-b.left)/b.width));};
function nearest(c,g,f){
  const f0=c.min==null?0:fr(g,c.min), f1=c.max==null?1:fr(g,c.max);
  const d0=Math.abs(f-f0), d1=Math.abs(f-f1);
  return d0<d1?0:d0>d1?1:(f<f0?0:1);
}
// つまみを位置 f に。端まで寄せたら制限なし
function setFrac(el,which,f){
  const c=conds[+el.dataset.i], g=rsGeom(c.k);
  if(which===0){let v=f<=0.002?null:valAt(g,f); if(g.disc&&v===g.lo)v=null;
    if(v!=null&&c.max!=null&&v>c.max)v=c.max; c.min=v;}
  else{let v=f>=0.998?null:valAt(g,f); if(g.disc&&v===g.hi)v=null;
    if(v!=null&&c.min!=null&&v<c.min)v=c.min; c.max=v;}
  syncInputs(el,c); syncRow(el); histRow(el); schedule();
}
// ホイール・キーで n 目盛り動かす
function nudge(el,which,n){
  const c=conds[+el.dataset.i], g=rsGeom(c.k);
  const cur=which===0?(c.min??g.lo):(c.max??g.hi);
  let v=+(Math.round((cur+n*g.step)/g.step)*g.step).toFixed(g.dec);
  if(which===0){ if(n<0&&v<=g.lo-(g.disc?0:g.step*0.5)||g.disc&&v<=g.lo)v=null;
    else if(c.max!=null&&v>c.max)v=c.max; c.min=v;}
  else{ if(n>0&&v>=g.hi+(g.disc?0:g.step*0.5)||g.disc&&v>=g.hi)v=null;
    else if(c.min!=null&&v<c.min)v=c.min; c.max=v;}
  syncInputs(el,c); syncRow(el); histRow(el); schedule();
}
let drag=null;
$('#condlist').addEventListener('pointerdown',e=>{
  const rs=e.target.closest('.rs'); if(!rs||e.button>0)return;
  const el=rs.closest('.cond'), c=conds[+el.dataset.i], g=rsGeom(c.k), f=posFrac(rs,e.clientX);
  const which=e.target.classList.contains('h0')?0:e.target.classList.contains('h1')?1:nearest(c,g,f);
  drag={rs,el,which}; rs.setPointerCapture(e.pointerId); e.preventDefault();
  rs.querySelector(which?'.h1':'.h0').focus({preventScroll:true});
  if(!e.target.classList.contains('h'))setFrac(el,which,f);
});
$('#condlist').addEventListener('pointermove',e=>{if(drag)setFrac(drag.el,drag.which,posFrac(drag.rs,e.clientX));});
const endDrag=()=>{drag=null;};
$('#condlist').addEventListener('pointerup',endDrag);
$('#condlist').addEventListener('pointercancel',endDrag);
let wacc=0;
$('#condlist').addEventListener('wheel',e=>{
  const rs=e.target.closest('.rs'); if(!rs)return;
  e.preventDefault();
  wacc+=Math.abs(e.deltaY)>=Math.abs(e.deltaX)?e.deltaY:-e.deltaX;
  if(Math.abs(wacc)<(e.deltaMode?1:40))return;
  const dir=wacc<0?1:-1; wacc=0;                    // 上に回すと値が大きくなる
  const el=rs.closest('.cond'), c=conds[+el.dataset.i], g=rsGeom(c.k);
  const t=e.target.classList;
  const which=t.contains('h0')?0:t.contains('h1')?1:nearest(c,g,posFrac(rs,e.clientX));
  nudge(el,which,dir*(e.shiftKey||g.disc?1:4));
},{passive:false});
$('#condlist').addEventListener('keydown',e=>{
  const h=e.target.closest('.h'); if(!h)return;
  const el=h.closest('.cond'), which=h.classList.contains('h0')?0:1, c=conds[+el.dataset.i];
  const K={ArrowRight:1,ArrowUp:1,ArrowLeft:-1,ArrowDown:-1,PageUp:10,PageDown:-10};
  if(K[e.key]){e.preventDefault(); nudge(el,which,K[e.key]); return;}
  if(e.key==='Home'||e.key==='End'){e.preventDefault();
    if(which===0)c.min=null; else c.max=null; syncInputs(el,c); syncRow(el); histRow(el); schedule();}
});
$('#condlist').addEventListener('change',e=>{
  const row=e.target.closest('.cond'); if(!row)return;
  const c=conds[+row.dataset.i];
  if(e.target.classList.contains('cmin'))c.min=e.target.value===''?null:+e.target.value;
  if(e.target.classList.contains('cmax'))c.max=e.target.value===''?null:+e.target.value;
  syncRow(row); histRow(row); screenLim.n=100; refresh();
});
$('#condlist').addEventListener('click',e=>{
  const vb=e.target.closest('.cvals .chip');
  if(vb){const c=conds[+vb.closest('.cond').dataset.i], v=vb.dataset.v;
    c.vals=c.vals.includes(v)?c.vals.filter(x=>x!==v):c.vals.concat([v]);
    vb.setAttribute('aria-pressed',c.vals.includes(v));
    vb.closest('.cond').querySelector('.cin .unit').textContent=c.vals.length?'選んだものに当てはまる銘柄':'どれも選んでいない＝制限なし';
    screenLim.n=100; refresh(); return;}
  if(!e.target.classList.contains('del'))return;
  conds.splice(+e.target.closest('.cond').dataset.i,1);
  drawConds(); refresh();
});

/* ---------- 「条件を追加」：まとまりごとに▼で開く一覧 ---------- */
const pickOpen=new Set();
function drawPicker(){
  const used=new Set(conds.map(c=>c.k)), q=$('#pickq').value.trim().toLowerCase();
  const has=kk=>METRIC[kk]&&ix[kk]!=null;      // 古いデータで列が無い項目は出さない
  const grouped=new Set(MGROUPS.flatMap(g=>g[1]));
  const rest=METRICS.map(m=>m[0]).filter(kk=>!grouped.has(kk)&&has(kk));
  $('#pickgroups').innerHTML=MGROUPS.concat(rest.length?[['その他',rest]]:[]).map(([g,ks])=>{
    const items=ks.filter(has).filter(k=>!q||METRIC[k][1].toLowerCase().includes(q)||k.toLowerCase().includes(q)||(TNAME[k]||'').toLowerCase().includes(q));
    if(!items.length)return '';
    return `<details class="pg" data-g="${g}"${q||pickOpen.has(g)?' open':''}><summary><span>${g}</span>`+
      `<span class="pgc">${items.length}項目</span><span class="tri" aria-hidden="true">▼</span></summary><div class="pitems">`+
      items.map(k=>`<button class="pi${used.has(k)?' used':''}" data-k="${k}"${used.has(k)?' disabled':''}>`+
        `${used.has(k)?'✓ ':''}${TNAME[k]||METRIC[k][1]}</button>`).join('')+`</div></details>`;
  }).join('')||'<p class="note" style="margin:6px 0">見つかりません。</p>';
}
$('#pickgroups').addEventListener('toggle',e=>{const d=e.target;
  if(d.dataset&&d.dataset.g&&!$('#pickq').value.trim())(d.open?pickOpen.add(d.dataset.g):pickOpen.delete(d.dataset.g));},true);
$('#pickq').oninput=drawPicker;
function closePicker(){$('#picker').hidden=true; $('#addcond').setAttribute('aria-expanded','false');}
$('#pickgroups').addEventListener('click',e=>{
  const b=e.target.closest('.pi'); if(!b||b.disabled)return;
  conds.push(CAT.has(b.dataset.k)?{k:b.dataset.k,vals:[]}:{k:b.dataset.k,min:null,max:null}); closePicker();
  drawConds(); refresh();
  const last=[...document.querySelectorAll('#condlist .cond')].pop();
  setCondOpen(true);
  if(last){last.scrollIntoView({block:'nearest',behavior:'smooth'}); const h=last.querySelector('.h0'); h&&h.focus({preventScroll:true});}
});
$('#addcond').onclick=()=>{
  const p=$('#picker'); p.hidden=!p.hidden;
  $('#addcond').setAttribute('aria-expanded',String(!p.hidden));
  if(!p.hidden){$('#pickq').value=''; drawPicker(); }
};
$('#clearcond').onclick=()=>{conds=[];
  document.querySelectorAll('#screenbar .chip').forEach(c=>c.removeAttribute('aria-pressed'));
  drawConds(); refresh();};

function screenMatch(r){
  for(const c of conds){
    const v=r[ix[c.k]];
    if(c.vals){ if(c.vals.length&&(v==null||!c.vals.includes(String(v))))return false; continue; }
    if(v==null||!isFinite(v))return false;      // 値が無い銘柄は条件を満たさない扱い
    if(c.min!=null&&v<c.min)return false;
    if(c.max!=null&&v>c.max)return false;
  }
  return true;
}

// 表示中の絞り込み結果をCSVに落とす（上の絞り込み＋条件＋いまの並び順のまま、全件）
function screenCsv(){
  const list=sorted(rows.filter(screenMatch));
  const cols=['コード','銘柄名','市場','業種','株価','時価総額(億円)','PER','PBR','EV/EBITDA',
    '配当利回り(%)','ROE(%)','ROTC(%)','営業利益率(%)','自己資本比率(%)','売上高成長率(%)',
    'ベータ','ベータ(1年)','負債資本比率','EBITDAマージン(%)','1株当たりフリーCF',
    '成長性評価','収益性評価','安全性評価','規模評価','割安度評価','値上がり評価',
    '評価平均','総合評価','業種内偏差値','規模','最低投資金額(万円)'];
  conds.forEach(c=>{if(!cols.includes(c.k)&&ix[c.k]!=null)cols.push(c.k)});   // 条件に使った項目も列に足す
  const esc=v=>v==null?'':(/[",\r\n]/.test(String(v))?'"'+String(v).replace(/"/g,'""')+'"':v);
  const body=[cols.map(esc).join(',')].concat(list.map(r=>cols.map(c=>esc(r[ix[c]])).join(','))).join('\r\n');
  return {n:list.length, text:'﻿'+body};   // BOM付き：Excelで開いても文字化けしない
}
function csvFlash(t){const b=$('#csvout');b.textContent=t;clearTimeout(b._t);b._t=setTimeout(()=>{b.textContent='CSVで保存'},2600);}
$('#csvout').onclick=()=>{
  const {n,text}=screenCsv();
  if(!n){csvFlash('該当0件');return;}
  const url=URL.createObjectURL(new Blob([text],{type:'text/csv;charset=utf-8'}));
  const a=document.createElement('a');
  a.href=url; a.download=`screener_${DATA.株価日付}_${n}件.csv`;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(()=>URL.revokeObjectURL(url),4000);
  csvFlash(`${n}件を保存しました`);
};

/* ---------- 業種別テーブル ---------- */
const SECCOLS=[['業種','業種','l'],['銘柄数','銘柄数','n0'],['時価総額(兆円)','時価総額(兆円)','n2'],
  ['赤字数','赤字','n0'],['PER','PER','n1'],['PBR','PBR','n2'],['ROE(%)','ROE%','n1'],
  ['営業利益率(%)','営業利益率%','n1'],['自己資本比率(%)','自己資本比率%','n1'],
  ['配当利回り(%)','配当利回り%','n2'],['売上高成長率(%)','増収率%','n1'],['評価平均','評価平均','n2']];
let secSort='評価平均', secAsc=false;
function drawSectorTable(){
  const t=$('#t-sector');
  const data=sectorStats().sort((a,b)=>{
    let x=a[secSort],y=b[secSort],s=secAsc?1:-1;
    if(typeof x==='string')return s*String(x).localeCompare(String(y),'ja');
    if(x==null)return 1; if(y==null)return -1; return s*(x-y);
  });
  t.querySelector('thead').innerHTML='<tr>'+SECCOLS.map(([k,l,f])=>
    `<th class="${f==='l'?'l':''}${k===secSort?' sorted'+(secAsc?' asc':''):''}" data-k="${k}">${l}</th>`).join('')+'</tr>';
  t.querySelector('tbody').innerHTML=data.map(d=>`<tr data-sec="${d.業種}">`+SECCOLS.map(([k,l,f])=>{
    const v=d[k];
    const s=f==='l'?`<span style="color:var(--series-1)">${v}</span>`:(f==='n0'?ni(v):nf(v,f==='n2'?2:1));
    return `<td class="${f==='l'?'l':''}">${s}</td>`;
  }).join('')+'</tr>').join('');
  // 業種名をタップしたら、その業種だけに絞り込んだランキングを開く
  t.querySelectorAll('tbody tr[data-sec]').forEach(tr=>tr.onclick=()=>{
    state.sector=tr.dataset.sec;
    $('#sector').value=tr.dataset.sec;
    sortKey='評価平均'; sortAsc=false; rankLim.n=100;
    goTab('rank');
    window.scrollTo({top:0});
  });
  t.querySelectorAll('th').forEach(th=>th.onclick=()=>{
    if(secSort===th.dataset.k)secAsc=!secAsc;else{secSort=th.dataset.k;secAsc=th.dataset.k==='業種';}
    drawSectorTable();
  });
}

/* ---------- レーダーチャート ---------- */
// 6項目の評価を1枚で見る図。点線はその銘柄が属する業種の中央値で、
// 「同業と比べてどこが強いか」を形の違いとして読ませる。
function drawRadar(r){
  const cv=$('#dradar'); if(!cv||!cv.clientWidth)return;
  const {c,w,h}=prep(cv,300);
  const items=DATA.項目||[];
  if(items.length<3)return;
  const cx=w/2, cy=h/2+2, R=Math.min(w/2-58,h/2-42);
  const ang=i=>-Math.PI/2+i*2*Math.PI/items.length;
  const pt=(i,v)=>[cx+Math.cos(ang(i))*R*(v-1)/4, cy+Math.sin(ang(i))*R*(v-1)/4];

  // 目盛の輪（1が中心、5が外周）
  c.strokeStyle=css('--grid'); c.lineWidth=1;
  for(let k=2;k<=5;k++){
    c.beginPath();
    items.forEach((_,i)=>{const [x,y]=pt(i,k); i?c.lineTo(x,y):c.moveTo(x,y)});
    c.closePath(); c.stroke();
  }
  items.forEach((_,i)=>{const [x,y]=pt(i,5);
    c.beginPath(); c.moveTo(cx,cy); c.lineTo(x,y); c.stroke()});

  const vals=items.map(it=>r[ix[it+'評価']]);
  const med=(DATA.業種中央値||{})[r[ix['業種']]]||[];
  const poly=(arr,dash,stroke,fill,lw)=>{
    const ok=arr.map((v,i)=>[v,i]).filter(([v])=>v!=null&&isFinite(v));
    if(ok.length<3)return null;
    c.save(); c.setLineDash(dash);
    c.beginPath();
    ok.forEach(([v,i],k)=>{const [x,y]=pt(i,v); k?c.lineTo(x,y):c.moveTo(x,y)});
    c.closePath();
    if(fill){c.globalAlpha=.15; c.fillStyle=fill; c.fill(); c.globalAlpha=1}
    c.strokeStyle=stroke; c.lineWidth=lw; c.stroke();
    c.restore();
    return ok;
  };
  const ok=poly(vals,[],css('--series-1'),css('--series-1'),2);
  if(ok)ok.forEach(([v,i])=>{const [x,y]=pt(i,v);
    c.beginPath(); c.arc(x,y,3.6,0,6.284);
    c.fillStyle=css('--series-1'); c.fill();
    c.lineWidth=1.8; c.strokeStyle=css('--surface-1'); c.stroke()});
  // 業種の中央値は最後に重ねる。先に描くと銘柄側の面に隠れて読めなくなる
  poly(med,[5,4],css('--text-secondary'),null,1.5);

  // ラベル
  c.textBaseline='middle';
  items.forEach((it,i)=>{
    const a=ang(i), x=cx+Math.cos(a)*(R+26), y=cy+Math.sin(a)*(R+26);
    c.textAlign=Math.abs(Math.cos(a))<0.25?'center':(Math.cos(a)>0?'left':'right');
    c.font='11.5px system-ui,-apple-system,sans-serif';
    c.fillStyle=css('--text-secondary'); c.fillText(it,x,y-8);
    const v=vals[i];
    c.font='600 13px system-ui,-apple-system,sans-serif';
    c.fillStyle=v==null?css('--muted'):css('--text-primary');
    c.fillText(v==null?'評価不能':String(v),x,y+8);
  });
}

/* ---------- 銘柄詳細 ---------- */
// 事業概要やURLをそのまま埋め込むと壊れるので、HTMLの特殊文字を逃がす
const he=v=>String(v==null?'':v).replace(/[&<>"']/g,c=>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const FITEM=new Set(['F1純利益','F2営業CF','F3ROA変化','F4収益の質','F5長期借入金',
  'F6流動比率','F7株式発行','F8売上総利益率','F9資産回転率',
  '予想F1営業利益','予想F2ROA変化','予想F3営業利益率','予想F4営業CF','予想F5流動比率',
  '予想F6有利子負債','予想F7資産回転率','予想F8アクルーアル','予想F9株式発行']);
const DETAIL_GROUPS=[
  ['規模',['株価','時価総額(億円)','規模','最低投資金額(万円)','決算月','売上高(億円)','営業利益(億円)','当期純利益(億円)','従業員数(人)','平均年収(万円)']],
  ['バリュエーション',['予想PER','今期予想純利益(億円)','予想PERの対象期','予想PERの開示日','PER','PER(時価総額ベース)','PBR','PSR','EV/EBITDA','配当利回り(%)','配当性向(%)','PEG','益回り(%)','PCFR','EPS','BPS','割安度の基準']],
  ['配当の質',['DOE(%)','平均DOE(%)','DOE変化(%pt)','減配回数','連続増配期数','配当CAGR(%)','FCF配当性向(%)']],
  ['収益性',['ROE(%)','ROA(%)','ROTC(%)','営業利益率(%)','純利益率(%)','EBITDAマージン(%)']],
  ['財務・CF',['自己資本比率(%)','流動比率(%)','営業CFマージン(%)','FCF利回り(%)',
    'インタレストカバレッジ','負債資本比率','ネットキャッシュ(億円)','換金性資産(億円)','ネットキャッシュ倍率','ネットキャッシュ比率(%)','純有利子負債/EBITDA']],
  ['株価の動き',['ベータ','ベータ(1年)','年率ボラティリティ(%)']],
  ['移動平均線・ブレイク',['移動平均線の上の本数','5日線乖離(%)','25日線乖離(%)','75日線乖離(%)','200日線乖離(%)',
    '横ばい上放れ','ボックス幅(%)','ボックス上抜け(%)']],
  ['最新の決算（TDnet 決算短信）',['最新決算日','決算期間','決算発表からの日数','累計増収率(%)','累計営業増益率(%)',
    '累計純益増益率(%)','営業益進捗率(%)']],
  ['会社予想（修正・サプライズ）',['予想EPS(円)','予想1株配当(円)','予想配当利回り(%)','予想売上高成長率(%)',
    '予想営業増益率(%)','予想純利益率(%)','業績予想修正率(%)','期初予想比(%)','予想修正の開示日','予想修正からの日数',
    '配当予想修正率(%)','決算サプライズ(%)']],
  ['株価パフォーマンス',['前日比(円)','前日比(%)','5日騰落率(%)','20日騰落率(%)','対市場超過(1日)(%pt)','対市場超過(20日)(%pt)',
    '売買代金(百万円)','平均売買代金(百万円)','売買代金増加率(%)','出来高増加率(%)','出来高倍率(6日/25日)',
    '60日ボラティリティ(%)','52週安値からの上昇率(%)','年初来高値からの日数','年初来安値からの日数',
    '年初来高値乖離(%)','年初来安値からの上昇率(%)']],
  ['テクニカル',['GC(5×25)からの日数','GC(25×75)からの日数','GC(75×200)からの日数','DC(5×25)からの日数',
    'DC(25×75)からの日数','DC(75×200)からの日数','一目 雲の位置','雲上抜けからの日数','雲下抜けからの日数',
    'ボリンジャー位置(σ)','RSI(14)(%)','RCI(9)(%)','RCI(26)(%)','ストキャス%K(9)','ストキャス%D','スローストキャス%D',
    '+DI(14)','−DI(14)','ADX(14)','サイコロジカル(12)(%)','MACDヒストグラム(%)','MACD GCからの日数',
    '新値3本足','新値3本足の転換からの日数','ベータ(対業種)(1年)','ドル円感応度(2年)']],
  ['需給（信用残・空売り）',['需給判定','需給スコア','信用倍率(倍)','信用買残(株)','信用売残(株)','買残前日比(株)','売残前日比(株)',
    '買残5日変化(%)','買残回転日数(日)','売残回転日数(日)','買残上場比(%)','一般信用買残比率(%)','信用買い評価損益率(%)',
    '信用売り評価損益率(%)','貸借倍率(倍)','逆日歩(円)','大口空売り比率(%)','大口空売り報告数','出来高倍率(当日/25日)',
    '最多価格帯からの乖離(%)','上値出来高比率(%)','信用区分','規制等']],
  ['営業増益の持続',['営業増益率3期平均(%)','営業増益率3期最低(%)','営業増益率の基準','営業CF2期黒字']],
  ['新高値',['新高値からの日数','新高値回数(20日)','52週高値乖離(%)','上場来高値からの日数','上場来高値乖離(%)','出来高倍率(5日/50日)']],
  ['成長性',['売上高成長率(%)','営業利益成長率(%)','当期純利益成長率(%)','EPS_CAGR(%)','営業利益CAGR(%)','平均ROE(%)']],
  ['総合評価の元になる数値',['売上高CAGR(%)','平均経常利益率(%)','収益性の基準','直近経常利益率(%)','今期予想経常利益(億円)','予想経常増益率(%)','平均税引前利益率(%)','250日騰落率(%)','評価平均']],
  ['Fスコア（改善の兆し）',['Fスコア','F1純利益','F2営業CF','F3ROA変化','F4収益の質',
    'F5長期借入金','F6流動比率','F7株式発行','F8売上総利益率','F9資産回転率','F代用','Fデータ品質']],
  ['予想Fスコア（会社予想ベース）',['予想Fスコア','予想F1営業利益','予想F2ROA変化','予想F3営業利益率','予想F4営業CF',
    '予想F5流動比率','予想F6有利子負債','予想F7資産回転率','予想F8アクルーアル','予想F9株式発行',
    '今期予想売上高(億円)','今期予想営業利益(億円)','今期予想営業利益率(%)','予想の対象期','予想の開示日','予想Fデータ品質']],
  ['マルチバガー判定',['マルチバガースコア','エントリー判定','評価値スコア','エントリースコア','品質スコア',
    '適合業種区分','FCF利回り基準(%)','P/FCF','FCF黒字比率(%)','成長ギャップ(%pt)',
    '設備投資/売上(%)','FCF/設備投資','52週レンジ位置(%)','125日騰落率(%)']],
  ['マルチバガー判定（論文準拠）',['論文スコア','論文エントリー','論文注意','FCF利回り(%)','B/M',
    '時価総額(億円)','ROA(%)','総資産成長率(%)','EBITDA成長率(%)','Invダミー','FCF黒字比率(%)',
    '52週レンジ位置(%)','125日騰落率(%)']],
];
if(TEIGI.added&&TEIGI.added.length)DETAIL_GROUPS.push(['定義表で追加した指標',TEIGI.added.filter(k=>ix[k]!=null)]);
// 銀行は会計上の自己資本比率では健全性を測れないので、バーゼル比率を主にして見せる
const BANK_DETAIL_GROUPS=DETAIL_GROUPS.map(g=>g[0]!=='財務・CF'?g:
  ['財務（バーゼル規制ベース）',['バーゼル自己資本比率(%)','資本余裕度(%pt)','不良債権比率(%)','自己資本比率(%)']]);
// 証券・保険も、会計上の自己資本比率ではなく業法の健全性指標を主にして見せる
const SEC_DETAIL_GROUPS=DETAIL_GROUPS.map(g=>g[0]!=='財務・CF'?g:
  ['財務（金融商品取引法ベース）',['自己資本規制比率(%)','自己資本比率(%)','営業CFマージン(%)','FCF利回り(%)']]);
const INS_DETAIL_GROUPS=DETAIL_GROUPS.map(g=>g[0]!=='財務・CF'?g:
  ['財務（保険業法ベース）',['ソルベンシー・マージン比率(%)','自己資本比率(%)','営業CFマージン(%)','FCF利回り(%)']]);
// その他金融業は、預かり資産で膨らむ自己資本比率よりネットD/Eレシオを先に見せる
const OTHFIN_DETAIL_GROUPS=DETAIL_GROUPS.map(g=>g[0]!=='財務・CF'?g:
  ['財務（レバレッジベース）',['純有利子負債/自己資本','自己資本比率(%)','インタレストカバレッジ',
    '営業CFマージン(%)','ネットキャッシュ(億円)']]);
const DETAIL_BY_SECTOR={'銀行業':BANK_DETAIL_GROUPS,'証券、商品先物取引業':SEC_DETAIL_GROUPS,
  '保険業':INS_DETAIL_GROUPS,'その他金融業':OTHFIN_DETAIL_GROUPS};
// 値の単位と小数桁。ラベルから (%) などを外し、値の側に単位を付けて読みやすくする
const BAI=new Set(['予想PER','PER','PER(時価総額ベース)','PBR','PSR','EV/EBITDA','インタレストカバレッジ','負債資本比率',
  'P/FCF','FCF/設備投資','ネットキャッシュ倍率','純有利子負債/自己資本','PCFR','出来高倍率(6日/25日)']);
const YEN=new Set(['株価','EPS','BPS','1株当たりフリーCF']);
const D2=new Set(['PBR','PSR','負債資本比率','ネットキャッシュ倍率','純有利子負債/自己資本','配当利回り(%)',
  'ベータ','ベータ(1年)','評価平均','資本余裕度(%pt)','ベータ(対業種)(1年)','ドル円感応度(2年)','ボリンジャー位置(σ)',
  '出来高倍率(6日/25日)','MACDヒストグラム(%)','前日比(%)','予想配当利回り(%)','対市場超過(1日)(%pt)']);
function unitOf(k){
  if(k.endsWith('(%pt)'))return '%pt';
  if(k.endsWith('(%)'))return '%';
  if(k.endsWith('(億円)'))return '億円';
  if(k.endsWith('(百万円)'))return '百万円';
  if(k.endsWith('(万円)'))return '万円';
  if(k.endsWith('(円)'))return '円';
  if(k.endsWith('(σ)'))return 'σ';
  if(k.endsWith('日数'))return '日';
  if(k==='決算月')return '月';
  if(BAI.has(k))return '倍';
  if(YEN.has(k))return '円';
  if(/スコア$/.test(k))return '点';
  return '';
}
const ENUMV={'一目 雲の位置':{'1':'雲の上','0':'雲の中','-1':'雲の下'},
  '新値3本足':{'1':'陽線（上昇基調）','-1':'陰線（下落基調）'}};
function fmtDetail(k,v){
  if(v==null||(typeof v==='number'&&!isFinite(v)))return '—';
  if(typeof v==='string')return v===''?'—':he(v);
  if(ENUMV[k])return ENUMV[k][v]??nf(v,0);
  if(k.endsWith('日数')||k==='決算月')return ni(v)+`<small>${unitOf(k)}</small>`;
  // 株数・回数・本数などの数えるものは整数で出す（19,916,700.0 → 19,916,700株）
  if(/\(株\)$/.test(k))return ni(v)+'<small>株</small>';
  if(/(回数|期数|報告数|本数|ダミー|横ばい上放れ)(\(.*\))?$/.test(k)&&Number.isInteger(v))return ni(v);
  if(k==='時価総額(億円)')return cap(v)+'<small>円</small>';
  const u=unitOf(k);
  let s;
  if(k==='株価')s=ni(v);
  else if(u==='億円')s=Math.abs(v)>=1000?ni(v):nf(v,1);
  else if(u==='百万円')s=Math.abs(v)>=100?ni(v):nf(v,1);
  else s=nf(v,D2.has(k)?2:1);
  return s+(u?`<small>${u}</small>`:'');
}
const DLABEL={'PER':'PER（実績）','PER(時価総額ベース)':'PER（時価総額÷純利益）',
  '時価総額(億円)':'時価総額（自己株式込み）','売上高CAGR(%)':'売上高CAGR（4期・年率）',
  '平均税引前利益率(%)':'売上高税引前利益率（4期平均・参考）',
  '平均経常利益率(%)':'売上高経常利益率（4期平均）','直近経常利益率(%)':'売上高経常利益率（直近期）',
  '収益性の基準':'収益性を測った利益','予想PER':'PER（会社予想）',
  '今期予想純利益(億円)':'今期の会社予想 純利益','今期予想経常利益(億円)':'今期の会社予想 経常利益',
  '予想経常増益率(%)':'今期予想の経常増益率','予想PERの対象期':'予想PERの対象期（期末）','予想PERの開示日':'予想PERの元の開示日',
  '250日騰落率(%)':'250営業日前比','評価平均':'6項目の平均',
  '125日騰落率(%)':'125営業日前比（約6か月）',
  '52週レンジ位置(%)':'52週レンジ位置（0=安値・100=高値）',
  'Fスコア':'Fスコア（9項目の合計）',
  'F1純利益':'F1 純利益がプラス','F2営業CF':'F2 営業CFがプラス',
  'F3ROA変化':'F3 ROAが前期を上回る','F4収益の質':'F4 営業CFが特別損益前の純利益を上回る',
  'F5長期借入金':'F5 長期借入金の比率が前期より低い','F6流動比率':'F6 流動比率が前期を上回る',
  'F7株式発行':'F7 新株発行が無い','F8売上総利益率':'F8 売上総利益率が前期を上回る',
  'F9資産回転率':'F9 総資産回転率が前期を上回る','F代用':'代用データで判定した項目',
  'Fデータ品質':'Fスコアを出せない理由',
  '予想Fスコア':'予想Fスコア（9項目の合計）',
  '予想F1営業利益':'F1 今期予想営業利益がプラス','予想F2ROA変化':'F2 予想ROAが前期を上回る',
  '予想F3営業利益率':'F3 予想営業利益率が前期を上回る','予想F4営業CF':'F4 前期の営業CFがプラス',
  '予想F5流動比率':'F5 流動比率が前年を上回る','予想F6有利子負債':'F6 有利子負債依存度が前年を下回る',
  '予想F7資産回転率':'F7 予想資産回転率が前期を上回る','予想F8アクルーアル':'F8 純利益が営業CFを下回る',
  '予想F9株式発行':'F9 発行済株式数が増えていない','予想Fデータ品質':'予想Fスコアを出せない理由',
  '今期予想売上高(億円)':'今期の会社予想 売上高','今期予想営業利益(億円)':'今期の会社予想 営業利益',
  '今期予想営業利益率(%)':'今期の会社予想 営業利益率','予想の対象期':'予想の対象期（期末）',
  '予想の開示日':'予想を開示した日',
  'マルチバガースコア':'マルチバガー適合度（最大95点）','論文スコア':'論文準拠スコア（100点・条件外は空欄）','論文エントリー':'論文準拠のタイミング','論文注意':'論文準拠で確認したい点','FCF利回り基準(%)':'この業種に求めるFCF利回り',
  '成長ギャップ(%pt)':'総資産CAGR − EBITDA CAGR','FCF/設備投資':'フリーCF ÷ 設備投資',
  'EPS':'1株当たり当期純利益','BPS':'1株当たり純資産','ベータ':'ベータ（3年）',
  '負債資本比率':'負債資本比率（有利子負債÷自己資本）','割安度の基準':'割安度を測った指標',
  '自己資本規制比率(%)':'自己資本規制比率（最低120%）',
  'ソルベンシー・マージン比率(%)':'ソルベンシー・マージン比率（基準200%）',
  '純有利子負債/自己資本':'純有利子負債÷自己資本（ネットD/E）'};
Object.assign(DLABEL,{'最低投資金額(万円)':'最低投資金額（100株）','PCFR':'PCFR（時価総額÷営業CF）',
  '規模':'規模（TOPIX規模区分）','予想修正の開示日':'最後に予想を修正した日',
  '業績予想修正率(%)':'業績予想修正率（最後の修正）','期初予想比(%)':'期初予想からの修正累計',
  '決算サプライズ(%)':'決算サプライズ（実績÷直前予想−1）','対市場超過(1日)(%pt)':'市場との差（1日）',
  '対市場超過(20日)(%pt)':'市場との差（20日）','GC(5×25)からの日数':'GC① 5日×25日から',
  'GC(25×75)からの日数':'GC② 25日×75日から','GC(75×200)からの日数':'GC③ 75日×200日から',
  'DC(5×25)からの日数':'DC① 5日×25日から','DC(25×75)からの日数':'DC② 25日×75日から',
  'DC(75×200)からの日数':'DC③ 75日×200日から','一目 雲の位置':'一目均衡表 雲の位置',
  'ドル円感応度(2年)':'ドル円感応度（＋は円安で上昇）','出来高倍率(6日/25日)':'出来高倍率（6日÷25日）','ベータ(対業種)(1年)':'ベータ（対業種・1年）'});
const dlabel=k=>DLABEL[k]||k.replace(/\((%|%pt|億円|百万円|万円|円|σ|株)\)$/,'');

// 同じ業種の中央値（主要指標のタイルに添える）。業種ごとに一度だけ計算する
const secMedCache={};
function secMed(sec,k){
  const key=sec+'|'+k;
  if(!(key in secMedCache)){
    const vals=S.filter(r=>r[ix['業種']]===sec).map(r=>r[ix[k]]);
    secMedCache[key]=median(['PER','PBR'].includes(k)?vals.filter(v=>v>0):vals);
  }
  return secMedCache[key];
}
// 業種ごとの「安全性」を表す主要指標
const SAFETY_KEY={'銀行業':'資本余裕度(%pt)','証券、商品先物取引業':'自己資本規制比率(%)',
  '保険業':'ソルベンシー・マージン比率(%)','その他金融業':'純有利子負債/自己資本'};

function openDetail(code){
  const r=S.find(x=>String(x[ix['コード']])===code); if(!r)return;
  const has=HAS_CHART.has(code);
  const sec=r[ix['業種']];
  $('#dtitle').innerHTML=`<span>${he(r[ix['銘柄名']])}</span><span class="cd">${code}</span>`;
  // 関連ページへのボタン。株式分析ダッシュボード（one/<コード>.html）を先頭に目立たせる
  const IC={one:'<svg viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/></svg>',
    gyo:'<svg viewBox="0 0 24 24"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></svg>',
    juk:'<svg viewBox="0 0 24 24"><path d="M4 7h13l-3-3M20 17H7l3 3"/></svg>',
    ch:'<svg viewBox="0 0 24 24"><path d="M3 17l5-6 4 3 6-8 3 3"/></svg>'};
  const L=[];
  if(!HAS_ONE||HAS_ONE.has(code))L.push(`<a class="pri" href="one/${code}.html" target="_blank" rel="noopener">${IC.one}株式分析ダッシュボード ↗</a>`);
  if(has)L.push(`<a href="${code}.html" target="_blank" rel="noopener">${IC.ch}チャート ↗</a>`);
  $('#dlinks').innerHTML=L.join('');
  $('#dsub').innerHTML=`${r[ix['市場']]}・${sec}｜決算期 ${r[ix['決算期']]}`+
    `${r[ix['決算が古い']]?'<span class="flag">400日以上前</span>':''}${flags(r).replace(/<span class="flag" title="決算期から400日以上">古<\/span>/,'')}`+
    `${r[ix['適用基準']]?'｜'+r[ix['適用基準']]+(r[ix['適用基準']]==='国内基準'
        ?'（コア資本比率・最低4.0%）':'（CET1比率・最低4.5%＋バッファー2.5%＝7.0%）'):''}`;

  // 評価の見出し：総合評価を大きく、6項目を色つきで横に並べる
  const dev=r[ix['業種内偏差値']];
  $('#dscore').innerHTML=
    `<div class="tot">${rbadge(r[ix['総合評価']],'xl')}<div><div class="k">総合評価</div>`+
      `<div class="s">評価平均 <b>${nf(r[ix['評価平均']],2)}</b>　全${ni(S.length)}社中 <b>${ni(r[ix['総合順位']])}</b>位<br>`+
      `${he(sec)}内 ${ni(r[ix['業種内銘柄数']])}社中 <b>${ni(r[ix['業種内順位']])}</b>位`+
      `${dev!=null?`・偏差値 <b>${nf(dev,1)}</b>`:''}</div></div></div>`+
    `<div class="ditems">${DATA.項目.map(it=>
      `<div class="ditem">${rbadge(r[ix[it+'評価']])}<span>${it}</span></div>`).join('')}</div>`;

  // 事業概要と公式サイト。どちらも無い銘柄では行ごと隠す
  (()=>{
    const biz=r[ix['事業概要']]||'', url=r[ix['会社URL']]||'', el=$('#dbiz');
    if(!biz&&!url){el.hidden=true;el.innerHTML='';return;}
    const host=url?url.replace(/^https?:\/\//,'').replace(/\/$/,''):'';
    el.innerHTML=(biz?he(biz):'')+
      (url?`${biz?' ':''}<a href="${he(url)}" target="_blank" rel="noopener noreferrer">${he(host)} ↗</a>`:'');
    el.hidden=false;
  })();

  // 主要指標のタイル。下に同じ業種の中央値を添えて、高いか低いかを読めるようにする
  const safeK=(SAFETY_KEY[sec]&&r[ix[SAFETY_KEY[sec]]]!=null)?SAFETY_KEY[sec]:'自己資本比率(%)';
  const KEYS=[['時価総額(億円)','時価総額'],['PER','PER（実績）'],['PBR','PBR'],['配当利回り(%)','配当利回り'],
    ['ROE(%)','ROE'],['営業利益率(%)','営業利益率'],[safeK,dlabel(safeK).replace(/（.*）$/,'')],['売上高成長率(%)','増収率']];
  $('#dkeys').innerHTML=KEYS.map(([k,l])=>{
    const v=r[ix[k]];
    const m=k==='時価総額(億円)'?null:secMed(sec,k);
    const sign=(k==='売上高成長率(%)'&&v!=null)?(v<0?' class="neg"':(v>0?' class="pos"':'')):'';
    return `<div class="key"><div class="k">${l}</div><div class="v"${sign}>${fmtDetail(k,v)}</div>`+
      `<div class="c">${m!=null?'業種中央値 '+fmtDetail(k,m).replace(/<\/?small>/g,''):'&nbsp;'}</div></div>`;
  }).join('');

  const bs=r[ix['安全性の基準']];
  // 安全性については理由を別に書くので、欠損の並びからは外して重複を避ける
  const safetyNote=(()=>{
    if(!bs||bs==='自己資本比率')return '';
    if(bs==='金融業のため評価しない')
      return '　<b>この版では金融業（銀行・保険・証券・その他金融）の安全性と収益性を評価していません。</b>残り4項目で総合評価を出しています。';
    const m=bs.match(/^(.+)（未取得）$/);   // その物差しで測るべきだが数字がまだ無い
    if(m)return `　安全性は<b>${m[1]}</b>で測る業種ですが、数値がまだ取れていません。`;
    return `　安全性は<b>${bs}</b>で評価しています。`;
  })();
  const noFin=(bs==='金融業のため評価しない');
  const miss=DATA.項目.filter(it=>r[ix[it+'評価']]==null
    && !(safetyNote && (it==='安全性'||(noFin&&it==='収益性'))));
  $('#dradarcap').innerHTML=`実線がこの銘柄、点線が<b>${sec}</b>の中央値（${ni(r[ix['業種内銘柄数']])}社）。`+
    `外側ほど評価が高く、中心が1、いちばん外の輪が5です。`+
    (miss.length?`　${miss.join('・')}は評価できていません。`:'')+safetyNote+
    (String(r[ix['割安度の基準']]||'').startsWith('PBR')
      ? '　割安度は赤字（予想赤字を含む）などでPERが使えないため、<b>PBR</b>（純資産に対する株価）で測っています。'
      : r[ix['割安度の基準']]==='実績PER' ? '　会社予想が出ていないため、割安度は<b>実績PER</b>で測っています。':'');

  // 全指標。まとまりごとにカードにする
  const groups=DETAIL_BY_SECTOR[sec]||DETAIL_GROUPS;
  $('#dkv').innerHTML=groups.map(([g,ks],gi)=>{
    let pre='';
    if(g.startsWith('Fスコア')||g.startsWith('予想Fスコア')){
      const fs=ks.filter(k=>FITEM.has(k)).map(k=>r[ix[k]]);
      if(fs.some(v=>v!=null))pre=`<div class="fdots" title="○の数＝Fスコア">${fs.map(v=>`<i class="${v>=1?'on':''}"></i>`).join('')}</div>`;
    }
    const body=ks.map(k=>{const v=r[ix[k]], lab=dlabel(k);
      // Fスコアの9項目は0/1なので、数値として並べず○×で見せる
      if(FITEM.has(k))return `<div class="row"><span>${lab}</span><span>${
        v==null?'—':(v>=1?'<b class="pos">○</b>':'<b class="neg">×</b>')}</span></div>`;
      if(k==='Fデータ品質'||k==='予想Fデータ品質'||k==='F代用')return v?`<div class="row"><span>${lab}</span><span style="white-space:normal">${he(v)}</span></div>`:'';
      if(k==='Fスコア'||k==='予想Fスコア')return `<div class="row"><span>${lab}</span><span>${
        v==null?'—':`<b>${nf(v,0)}</b><small>/ 9点</small>`}</span></div>`;
      const pm=PRICE_RE.test(k), sign=/成長率|騰落率|CAGR/.test(k)&&typeof v==='number'?(v<0?(pm?'dn':'neg'):(v>0?(pm?'up':'pos'):'')):'';
      return `<div class="row"><span>${lab}</span><span class="${sign}">${fmtDetail(k,v)}</span></div>`;
    }).join('');
    return `<section class="gcard" id="dg${gi}"><h4>${g}</h4>${pre}${body}</section>`;
  }).join('');
  $('#djump').innerHTML=groups.map(([g],gi)=>`<button type="button" data-j="dg${gi}">${he(g)}</button>`).join('');
  $('#dcount').textContent=$('#dkv').querySelectorAll('.row').length;
  $('#dq').value=''; dfilter();
  $('#detail').hidden=false;
  $('#detail').scrollTop=0;
  DCUR=r;
  dtab(dtabSaved());  // レーダーは表示してからでないと canvas の幅が取れないので dtab の中で描く
  document.body.style.overflow='hidden';   // 裏の一覧が一緒に動かないように
}
function closeDetail(){
  $('#detail').hidden=true;
  document.body.style.overflow='';
}
$('#dclose').onclick=closeDetail;
// 概要／全指標のタブ。最後に選んだタブを覚えておき、次の銘柄もそのタブで開く
function dtabSaved(){try{const t=localStorage.getItem('fdb-dtab');if(['ov','all'].includes(t))return t}catch(e){}return 'ov'}
function dtab(t,save){
  document.querySelectorAll('.dtabs button').forEach(b=>{const on=b.dataset.t===t;
    b.classList.toggle('on',on);b.setAttribute('aria-selected',on?'true':'false')});
  document.querySelectorAll('.dpane').forEach(p=>p.hidden=p.dataset.p!==t);
  if(t==='ov'&&DCUR)drawRadar(DCUR);
  $('#detail').style.setProperty('--dhead-h',($('#dhead').offsetHeight+10)+'px');
  $('#detail').scrollTop=0;
  if(save)try{localStorage.setItem('fdb-dtab',t)}catch(e){}
}
document.querySelector('.dtabs').addEventListener('click',e=>{const b=e.target.closest('button[data-t]');if(b)dtab(b.dataset.t,true)});
document.querySelector('.dmore').addEventListener('click',()=>dtab('all',true));
$('#djump').addEventListener('click',e=>{const b=e.target.closest('button[data-j]');if(!b)return;
  const el=document.getElementById(b.dataset.j);if(el)el.scrollIntoView({behavior:'smooth',block:'start'})});
// 指標名で絞り込む。グループ名に当たったらそのグループは全部出す
const dnorm=s=>String(s).normalize('NFKC').toLowerCase().replace(/\s+/g,'');
function dfilter(){
  const q=dnorm($('#dq').value);let n=0;
  $('#dkv').querySelectorAll('.gcard').forEach(c=>{
    const gHit=q&&dnorm(c.querySelector('h4').textContent).includes(q);let any=false;
    c.querySelectorAll('.row').forEach(rw=>{const sp=rw.firstElementChild;
      if(sp.dataset.t==null)sp.dataset.t=sp.textContent;
      const t=sp.dataset.t, i=q?dnorm(t).indexOf(q):-1, show=!q||gHit||i>=0;
      rw.hidden=!show; if(show){any=true;n++;}
      sp.innerHTML=(q&&!gHit&&i>=0&&dnorm(t)===t.toLowerCase().replace(/\s+/g,''))
        ?he(t.slice(0,i))+'<mark>'+he(t.slice(i,i+q.length))+'</mark>'+he(t.slice(i+q.length)):he(t);
    });
    c.hidden=!any;
  });
  $('#dqn').textContent=q?n+'件':'';
  $('#djump').style.display=q?'none':'';
}
$('#dq').addEventListener('input',dfilter);
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeDetail()});
document.addEventListener('click',e=>{
  const tr=e.target.closest('tbody tr[data-c], .scard[data-c]');
  if(tr&&!e.target.closest('a'))openDetail(tr.dataset.c);
});

/* ---------- 指標の説明タブ（2026-09-24 に簡潔に作り直し） ---------- */
(function(){
  const noFin=!!DATA['金融の安全性を評価しない'];
  const REF=(DATA.評価基準||[]).map(r=>
    (noFin&&(r.項目==='安全性'||r.項目==='収益性'))
      ? Object.assign({},r,{注:'金融4業種（銀行・保険・証券・その他金融）は評価しません。'}) : r);
  $('#bands').innerHTML=REF.map(r=>
    `<article class="band"><h3>${r.項目}<em>${r['元にする数値']}</em></h3>`+
    `<ol class="scale">${r.区分.map((v,i)=>`<li><b>${5-i}</b><span>${v}</span></li>`).join('')}</ol>`+
    (r.注?`<details><summary>補足</summary><p>${r.注}</p></details>`:'')+`</article>`).join('');
  $('#totalband').textContent='総合評価＝6項目の平均が 4.5以上→5／3.5以上→4／2.5以上→3／1.5以上→2／1.5未満→1。'+
    '評価できた項目が3つ未満の銘柄は出しません。';

  // 指標の意味（1行ずつ）
  const G=[
    ['割安度',[
      ['PER（実績）','株価÷1株利益（直近の決算）。低いほど利益に対して割安。赤字だとマイナス'],
      ['予想PER','株価÷会社予想の1株利益。総合評価の割安度はこちらで測る'],
      ['PBR','株価÷1株純資産。1倍が解散価値の目安'],
      ['PSR / PCFR','時価総額÷売上高 / 時価総額÷営業キャッシュフロー'],
      ['EV/EBITDA','（時価総額＋借入−現金）÷償却前営業利益。借金の多い会社は高めに出る'],
      ['PEG','PER÷利益の成長率。1未満なら成長の割に安い'],
      ['FCF利回り','フリーキャッシュフロー÷時価総額'],
      ['ネットキャッシュ倍率','時価総額÷（流動資産−負債合計）。1倍未満なら資産の面で割安'],
    ]],
    ['収益性',[
      ['ROE','純利益÷自己資本。株主のお金でどれだけ稼いだか'],
      ['ROA','利益÷総資産'],
      ['ROTC','営業利益÷投下資本。借入も分母に入るので、借金で見かけを良くできない'],
      ['営業利益率 / 経常利益率','売上高に対する利益の割合。総合評価の収益性は経常利益率（4期平均）'],
    ]],
    ['安全性',[
      ['自己資本比率','自己資本÷総資産。高いほど借金に頼っていない'],
      ['流動比率','流動資産÷流動負債。200%以上が目安'],
      ['負債資本比率','有利子負債÷自己資本（倍）'],
      ['インタレストカバレッジ','営業利益÷支払利息。利払いの何倍稼いでいるか'],
    ]],
    ['配当',[
      ['配当利回り','1株配当÷株価'],
      ['配当性向','配当÷純利益。高すぎると減配の余地が小さい'],
      ['DOE','配当総額÷自己資本。利益の振れに左右されにくい配当の目安'],
      ['連続増配期数','続けて増配した期数（最大3）'],
    ]],
    ['成長性',[
      ['増収率・営業増益率','前期と比べた伸び'],
      ['CAGR','年平均成長率（最大4期）'],
      ['営業増益率3期平均','今期予想・前期・前々期の営業増益率の平均'],
    ]],
    ['会社予想（決算短信）',[
      ['業績予想修正率','最後に予想を修正したときの変化率。＋は上方修正、−は下方修正'],
      ['期初予想比','その期の最初の予想から、いまの予想までの修正の累計'],
      ['決算サプライズ','本決算の営業利益÷発表直前の会社予想−1'],
      ['予想配当利回り','会社予想の年間配当÷株価'],
    ]],
    ['株価・テクニカル',[
      ['52週レンジ位置','過去1年の値幅の中の位置。0＝安値、100＝高値'],
      ['移動平均線乖離','株価が5・25・75・200日の平均からどれだけ離れているか'],
      ['GC / DC','短期の移動平均線が長期線を上抜け（GC）／下抜け（DC）。「からの日数」0＝最新日'],
      ['RSI','上げ下げの勢い。70%以上は買われすぎ、30%以下は売られすぎの目安'],
      ['ボリンジャー位置','25日平均から標準偏差（σ）いくつ分離れているか。±2σ超は行き過ぎの目安'],
      ['MACD','ヒストグラムが＋なら上昇の勢いが強まっている'],
      ['一目 雲の位置','1＝株価が雲の上、0＝中、−1＝下'],
      ['新値3本足','1＝上昇基調（陽線）、−1＝下落基調（陰線）'],
      ['出来高倍率','直近の出来高÷ふだんの出来高。1.5倍以上なら商いが増えている'],
      ['ベータ','市場が1%動いたときの動き。1より大きいほど値動きが荒い'],
      ['ドル円感応度','＋なら円安で上がりやすく、−なら円高で上がりやすい'],
    ]],
    ['スコア',[
      ['業種内偏差値','同じ業種の中での位置。50が真ん中、60で上位16%あたり'],
      ['Fスコア','9項目で財務の改善を測る点数（0〜9）。予想Fスコアは会社予想を使った版'],
      ['マルチバガー／論文スコア','10倍株の研究（Yartseva 2025）にもとづく点数。FCF利回り・割安さ・小型・安値圏を重く見る'],
      ['なごちょう式','資産バリュー・成長・高配当を同時に満たす8条件'],
    ]],
  ];
  $('#gloss').innerHTML=G.map(([g,items])=>
    `<details class="gl"><summary><span>${g}</span><span class="gc">${items.length}</span><span class="tri" aria-hidden="true">▼</span></summary>`+
    `<dl>${items.map(([t,d])=>`<dt>${t}</dt><dd>${d}</dd>`).join('')}</dl></details>`).join('');

  // 読むときの注意（短く）
  const NOTES=[
    ...(noFin?[['金融4業種','銀行・保険・証券・その他金融は、安全性と収益性を評価せず、残り4項目の平均で総合評価を出しています。']]:[]),
    ['会社予想の出どころ','決算短信の数字です。発表当日に TDnet から取り込み、あとから J-Quants の値で答え合わせしています（3か月より前の開示は J-Quants の値）。'],
    ['赤字の会社の割安度','PERが使えないので、PBRで測っています。'],
    ['値上がりだけは相対評価','全銘柄の中の順位で5等分しています。相場全体が下げた年でも2割の銘柄が5になります。'],
    ['銘柄名の横の印','<span class="flag">古</span>決算が400日以上前　<span class="flag">赤</span>最終赤字　<span class="flag">特</span>一時的な利益の疑い（PER2倍未満など）　<span class="flag">E</span>1株利益の桁ずれ（PERを評価から除外）　<span class="flag">D</span>元データの不整合（PER・ROE・売上系・利益率系を空欄に）'],
    ['ランキングとスクリーニングの定義','ランキングの種類と「条件を追加」の項目は、screening_config のスクリーニング定義表（条件ID・計算式・データ源・NULLの扱い）から作っています。値が無い銘柄は順位・条件の対象外です。'],
    ['PERがYahoo!と違う','ここのPERは実績ベース、Yahoo!は会社予想ベースです。予想ベースは「予想PER」の列で見られます。'],
    ['評価の限界','過去の決算と株価から機械的に付けたものです。見通しや数字にならない材料は入っていないので、銘柄を絞る入口として使ってください。'],
  ];
  $('#notes').innerHTML=NOTES.map(([t,b])=>`<li><b>${t}</b><span>${b}</span></li>`).join('');
})();

/* ---------- 再描画 ---------- */
// 行 → 元配列での位置。スクリーニングの照合をO(1)にする
const rowIndex=new Map(); S.forEach((r,i)=>rowIndex.set(r,i));

/* ---------- アナリスト予想（アナリスト予想/analyst_page.py の build()。証券会社アナリストの予想の集計・Yahoo Finance） ---------- */
// 行: 0 コード,4 株価,5 目標株価,6 上昇余地,7 安値目標までの余地,8 人数,9 投資判断,11 判断の3か月変化,12 今期EPS修正30日,
//     14 来期EPS成長,15 来期売上成長,16 サプライズ4期平均,17 予想超え回数,18 格上げ90日,19 格下げ90日,26 EPS予想人数,
//     27 今期EPS予想,28 買い人数,29 中立人数,30 売り人数,31 前日比,32 直近の判断変更日
const AN=DATA.analyst;
if(!AN){const b=$('#tab-analyst');if(b)b.remove();const p=$('#p-analyst');if(p)p.remove();}
const AR=AN?AN.rows:[];
const anPx=v=>v==null?'—':nf(v,Math.abs(v)>=1000?0:1)+'円';
const anSg=(v,d=1,u='%')=>v==null||!isFinite(v)?'—':`<span class="${v>0?'up':v<0?'dn':''}">${v>0?'+':v<0?'−':''}${nf(Math.abs(v),d)}${u}</span>`;
const anNN=x=>Math.max(x[8]||0,x[26]||0);
const anRecN=v=>v==null?'—':v<=1.5?'強い買い':v<=2.5?'買い':v<=3.5?'中立':v<=4.5?'売り':'強い売り';
const anRec=v=>v==null?'—':`<span class="anrec ${v<=2.5?'b':v<=3.5?'n':'s'}">${anRecN(v)} ${nf(v,2)}</span>`;
function anDonut(x){const a=[x[28]||0,x[29]||0,x[30]||0],n=a[0]+a[1]+a[2];if(!n)return '—';const C=2*Math.PI*15,col=['var(--up)','var(--muted)','var(--dn)'];let o=0,s='';
 a.forEach((v,i)=>{if(!v)return;const l=v/n*C;s+=`<circle cx="20" cy="20" r="15" fill="none" stroke-width="5" style="stroke:${col[i]}" stroke-dasharray="${l.toFixed(2)} ${(C-l).toFixed(2)}" stroke-dashoffset="${(-o).toFixed(2)}" transform="rotate(-90 20 20)"/>`;o+=l;});
 return `<span class="dn3"><svg viewBox="0 0 40 40">${s}<text x="20" y="24" text-anchor="middle" font-size="12" font-weight="800" style="fill:var(--text-primary)">${n}</text></svg><span class="c"><i style="background:var(--up)"></i>${a[0]} 買い<br><i style="background:var(--muted)"></i>${a[1]} 中立<br><i style="background:var(--dn)"></i>${a[2]} 売り</span></span>`;}
const anE=x=>x[27]!=null&&x[27]>=10;
const AN_RK=[
 ['cnt','アナリスト注目度','担当するアナリストの人数が多い順。',x=>anNN(x),-1,'n'],
 ['up','上昇余地が大きい','目標株価の平均が、いまの株価より高い順。上昇余地が200%を超える銘柄は目標株価が古いとみて外しています。',x=>x[5]!=null&&x[6]<=200?x[6]:null,-1,6],
 ['dn','株価が目標を超えた','目標株価の平均より株価が高い順（かい離率がマイナス）。',x=>x[5]!=null&&x[6]<0?x[6]:null,1,6],
 ['lo','弱気な目標より安い','いちばん低い目標株価よりも、いまの株価が安い順。',x=>x[7]!=null&&x[7]>0&&x[6]<=200?x[7]:null,-1,7],
 ['rec','投資判断が強い','投資判断の平均点（1 強い買い〜5 強い売り）が小さい順。',x=>x[9],1,9],
 ['recw','投資判断が弱い','投資判断の平均点が大きい順。',x=>x[9],-1,9],
 ['reci','投資判断が改善','3か月前より投資判断の点数が下がった（強気に傾いた）順。',x=>x[11]!=null&&x[11]<0?x[11]:null,1,9],
 ['rvu','EPS 予想の上方修正','今期の EPS の平均予想が30日前から上がった順（今期 EPS 予想10円以上）。',x=>anE(x)&&x[12]>0?x[12]:null,-1,12],
 ['rvd','EPS 予想の下方修正','今期の EPS の平均予想が30日前から下がった順。',x=>x[12]!=null&&x[12]<0?x[12]:null,1,12],
 ['ge','来期の利益成長','来期の EPS 予想が今期の予想からどれだけ増えるか（今期 EPS 予想10円以上）。',x=>anE(x)?x[14]:null,-1,14],
 ['gs','来期の売上成長','来期の売上高予想が今期の予想からどれだけ増えるか。',x=>x[15],-1,15],
 ['sp','決算サプライズ','直近4四半期の EPS 実績が予想を上回った幅の平均（4回とも上回った銘柄）。',x=>x[17]==='4/4'&&anE(x)?x[16]:null,-1,16],
 ['ug','格上げが多い','直近90日の格上げの数が多い順（格下げを引いた数）。',x=>x[18]-x[19]>0?x[18]-x[19]:null,-1,18],
];
// 判断変更の履歴は米国株だけ（東証銘柄は Yahoo にほぼ無い）。少ないときは列・ランキングを出さない
const AN_HASDT=AR.filter(x=>x[32]).length>=AR.length*0.05;
if(!AN_HASDT)AN_RK.splice(AN_RK.findIndex(r=>r[0]==='ug'),1);
let anRk='cnt',anMin=3,anSk=null,anAsc=false,anLim=200;
try{const v=localStorage.getItem('fdb-anrk');if(AN_RK.some(r=>r[0]===v))anRk=v;const m=+localStorage.getItem('fdb-anmin');if([3,5,10,20].includes(m))anMin=m;}catch(_){}
if(AN){
 $('#anrk').innerHTML=AN_RK.map(r=>`<button type="button" class="chip" data-r="${r[0]}" title="${r[2]}">${r[1]}</button>`).join('');
 $('#anrk').onclick=e=>{const b=e.target.closest('.chip');if(!b)return;anRk=b.dataset.r;anSk=null;anLim=200;try{localStorage.setItem('fdb-anrk',anRk)}catch(_){};refresh();};
 $('#anmin').innerHTML=[3,5,10,20].map(m=>`<button type="button" class="chip" data-m="${m}">${m}人以上</button>`).join('');
 $('#anmin').onclick=e=>{const b=e.target.closest('.chip');if(!b)return;anMin=+b.dataset.m;anLim=200;try{localStorage.setItem('fdb-anmin',anMin)}catch(_){};refresh();};
 $('#an-more').onclick=()=>{anLim+=200;refresh();};
 $('#t-analyst').querySelector('thead').onclick=e=>{const th=e.target.closest('th[data-i]');if(!th)return;const i=+th.dataset.i;
  if(anSk===i)anAsc=!anAsc;else{anSk=i;anAsc=false;}refresh();};
}
const SBY={};S.forEach(r=>SBY[String(r[ix['コード']])]=r);
function renderAnalyst(){
 if(!AN)return;
 const R0=AN_RK.find(r=>r[0]===anRk)||AN_RK[0],key=R0[5];
 document.querySelectorAll('#anrk .chip').forEach(b=>b.setAttribute('aria-pressed',b.dataset.r===R0[0]));
 document.querySelectorAll('#anmin .chip').forEach(b=>b.setAttribute('aria-pressed',+b.dataset.m===anMin));
 const pass=new Set(rows.map(r=>String(r[ix['コード']])));
 let L=AR.filter(x=>pass.has(String(x[0]))&&anNN(x)>=anMin&&R0[3](x)!=null);
 if(anSk!=null){const i=anSk==='n'?null:anSk,g=x=>i==null?anNN(x):x[i];
  L.sort((a,b)=>{const p=g(a),q=g(b);return p==null?1:q==null?-1:(typeof p==='string'?p.localeCompare(q):(p-q))*(anAsc?1:-1);});}
 else L.sort((a,b)=>(R0[3](a)-R0[3](b))*R0[4]||anNN(b)-anNN(a));
 $('#antitle').textContent=`アナリスト予想：${R0[1]}`;
 $('#aninfo').textContent=`${R0[2]}（該当 ${ni(L.length)} 銘柄・予想は ${AN.asof} 取得）`;
 const lo=R0[0]==='lo';
 const C=[['順位',null,'rkno'],['銘柄',null,'stk'],['株価',4,'hsp'],['アナリスト予想','n',''],['投資判断',9,''],['目標株価の平均',5,''],
  [lo?'安値目標まで':'かい離率',lo?7:6,''],['EPS修正30日',12,'hsp'],['来期EPS成長',14,'hsp'],
  R0[0]==='gs'?['来期売上成長',15,'hsp']:R0[0]==='ug'?['格上げ／下げ',18,'hsp']:['サプライズ',16,'hsp']];
 if(AN_HASDT)C.push(['予想更新日',32,'hsp']);
 C.push(['時価総額',-1,'hsp']);
 const t=$('#t-analyst');
 t.querySelector('thead').innerHTML='<tr>'+C.map(([h,i,c])=>`<th class="${c}${i===key?' key':''}${anSk!=null&&anSk===i?' sorted'+(anAsc?' asc':''):''}"${i!=null&&i!==-1?` data-i="${i}"`:''}>${h}</th>`).join('')+'</tr>';
 const cell=(x,i,r)=>{switch(i){
  case 4:return anPx(x[4])+`<small class="chg">${anSg(x[31],2)}</small>`;
  case 'n':return anDonut(x);
  case 9:return anRec(x[9])+(R0[0]==='reci'?` ${anSg(x[11],2,'')}`:'');
  case 5:return anPx(x[5]);
  case 16:return anSg(x[16])+(x[17]?` <small style="color:var(--muted)">${x[17]}</small>`:'');
  case 18:return `<span class="up">↑${x[18]}</span> <span class="dn">↓${x[19]}</span>`;
  case 32:return x[32]?x[32].replace(/-/g,'/'):'—';
  case -1:return r?cap(r[ix['時価総額(億円)']]):'—';
  default:return anSg(x[i]);}};
 const n=Math.min(L.length,anLim);let h='';
 for(let k=0;k<n;k++){const x=L[k],r=SBY[String(x[0])];
  h+=`<tr data-c="${x[0]}">`+C.map(([hd,i,c])=>c==='rkno'?`<td class="rkno">${k+1}</td>`:c==='stk'?`<td class="stk">${r?cellHTML(r,COL['銘柄名']):x[0]}</td>`:`<td class="${c}${i===key?' key':''}">${cell(x,i,r)}</td>`).join('')+'</tr>';}
 t.querySelector('tbody').innerHTML=h;
 $('#an-empty').hidden=L.length>0;$('#an-more').hidden=L.length<=anLim;
}
// fundamentals.html#analyst で開いたときは「アナリスト予想」タブから
addEventListener('DOMContentLoaded',()=>{if(AN&&location.hash==='#analyst')goTab('analyst');});

function refresh(){
  applyFilter();
  const tab=activeTab();
  document.body.classList.toggle('on-screen',tab==='screen');
  syncSbar();
  if(tab==='rank'){renderRank();}
  else if(tab==='analyst'){renderAnalyst();}
  else if(tab==='screen'){
    const list=sorted(rows.filter(screenMatch));
    $('#screenhit').innerHTML=`該当 <b>${ni(list.length)}</b> 銘柄`;
    $('#sbarhit').innerHTML=`該当<b>${ni(list.length)}</b>銘柄`;
    drawSum();
    renderTable('t-screen',list,screenLim,$('#screen-more'),$('#screen-empty'));
    if(!drag)document.querySelectorAll('#condlist .cond').forEach(histRow);
  }
  else if(tab==='sector'){drawSectorTable();}
}
function drawAll(){refresh()}
// 画面下のバー：結果が見えていれば「条件に戻る」、条件を触っている間は「結果を見る」
function syncSbar(){
  const r=$('#screenres').getBoundingClientRect();
  const inRes=r.top<innerHeight*0.55;
  $('#sbarbtn').textContent=inRes?'条件に戻る ↑':'結果を見る ↓';
  $('#sbarbtn').dataset.to=inRes?'cond':'res';
}
let sbRaf=0;
addEventListener('scroll',()=>{if(sbRaf||!document.body.classList.contains('on-screen'))return;
  sbRaf=requestAnimationFrame(()=>{sbRaf=0;syncSbar();});},{passive:true});
$('#sbarbtn').onclick=()=>{
  const to=$('#sbarbtn').dataset.to==='cond'?document.querySelector('#p-screen>.card'):$('#screenres');
  to.scrollIntoView({behavior:'smooth',block:'start'});
};

conds=PRESETS['割安株'].map(([k,mn,mx])=>({k,min:mn,max:mx}));
document.querySelector('#screenbar .chip').setAttribute('aria-pressed','true');
drawConds();

$('#sub').textContent=`株価 ${DATA.株価日付} 時点・${ni(DATA.summary.銘柄数)}銘柄／生成 ${DATA.生成日}`;
$('#foot').innerHTML=`データ元は Yahoo Finance の標準化財務諸表。時価総額・PER・PBR・PSR は保存済み終値と決算実績から自前で計算しています。`+
  `<br>総合評価は過去の決算数値と株価から機械的に付けたもので、投資判断そのものではありません。銘柄を絞り込む入口として使ってください。`+
  `<br>赤字 ${ni(DATA.summary.赤字銘柄数)}銘柄、決算期が400日以上前 ${ni(DATA.summary['決算が古い銘柄数'])}銘柄、一時要因の疑い ${ni(DATA.summary['一時要因の疑い'])}銘柄、報告EPSの桁が合わない ${ni(DATA.summary['EPS乖離'])}銘柄。`;

let rt;addEventListener('resize',()=>{clearTimeout(rt);rt=setTimeout(refresh,150)});
matchMedia('(prefers-color-scheme: dark)').addEventListener('change',()=>{syncChartTheme();refresh()});
refresh();
</script>
</body>
</html>
"""


KS_FIELDS = ["最新決算日", "決算期間", "累計増収率(%)", "累計営業増益率(%)", "累計純益増益率(%)", "営業益進捗率(%)",
             "決算発表からの日数"]


def add_kessan(payload):
    """kessan_latest.csv の値を payload の fields / stocks に足す。
    第1〜3四半期は累計の前年比、進捗率＝累計の営業利益÷通期の会社予想（本決算は空）。"""
    import csv as _csv
    f = BASE / "fundamentals" / "kessan_latest.csv"
    if not f.exists():
        return
    with f.open(encoding="utf-8-sig", newline="") as fo:
        ks = {r["コード"]: r for r in _csv.DictReader(fo)}

    def n(v):
        try:
            return float(v) if v not in ("", None) else None
        except ValueError:
            return None
    flds = payload["fields"]
    ci = flds.index("コード")
    for k in KS_FIELDS:
        if k not in flds:
            flds.append(k)
    pos = [flds.index(k) for k in KS_FIELDS]
    hit = 0
    for r in payload["stocks"]:
        while len(r) < len(flds):
            r.append(None)
        k = ks.get(str(r[ci]))
        vals = [None] * len(KS_FIELDS)
        if k and k.get("期間末"):
            q = int(n(k.get("四半期")) or 4)
            fye = k.get("決算期末", "")
            per = (fye[2:4] + "/" + str(int(fye[5:7])) + "期 " if fye else "") + ("通期" if q == 4 else f"{q}Q累計")
            op, fop = n(k.get("営業利益")), n(k.get("予想_営業利益"))
            if op is None:   # 営業利益の無い会社（銀行・保険など）は経常利益で
                op, fop = n(k.get("経常利益")), n(k.get("予想_経常利益"))
            prog = round(op / fop * 100, 1) if (q < 4 and op is not None and fop and fop > 0 and op >= 0) else None
            def yy(c):
                v = n(k.get(c))
                return round(v, 1) if v is not None else None
            import datetime as _dt
            days = (_dt.date.today() - _dt.date.fromisoformat(k["開示日"])).days
            vals = [k["開示日"], per, yy("売上高_前年比(%)"),
                    yy("営業利益_前年比(%)") if k.get("営業利益") else yy("経常利益_前年比(%)"),
                    yy("純利益_前年比(%)"), prog, days]
            hit += 1
        for p_, v in zip(pos, vals):
            r[p_] = v
    print(f"最新の決算短信: {hit} 銘柄に列を追加")


def add_company(payload, jp=True):
    """会社情報（make_company_links.py → fundamentals/company_info.json）の従業員数・平均年収を列に足す（2026-11-18）。
    従業員数は連結（無ければ単体、米国は Yahoo）、平均年収は提出会社（単体）の平均年間給与を万円で。"""
    f = BASE / "fundamentals" / "company_info.json"
    if not f.exists():
        return
    co = json.loads(f.read_text(encoding="utf-8"))
    keys = ["従業員数(人)", "平均年収(万円)"] if jp else ["従業員数(人)"]
    flds = payload["fields"]
    ci = flds.index("コード")
    for k in keys:
        if k not in flds:
            flds.append(k)
    pos = [flds.index(k) for k in keys]
    hit = 0
    for r in payload["stocks"]:
        while len(r) < len(flds):
            r.append(None)
        e = (co.get(str(r[ci])) or {}).get("emp") or {}
        emp = e.get("emp")
        vals = [int(emp) if emp else None]
        if jp:
            s = e.get("salary")
            vals.append(round(s / 1e4) if s else None)
        hit += bool(emp)
        for p_, v in zip(pos, vals):
            r[p_] = v
    print(f"会社情報: 従業員数 {hit} 銘柄に列を追加")


def main() -> int:
    ap = argparse.ArgumentParser(description="ファンダメンタル分析ダッシュボードを生成")
    ap.add_argument("--src", default=str(SRC))
    ap.add_argument("--out", default=str(DST))
    ap.add_argument("--title", default="東証スクリーニング",
                    help="ブラウザのタブに出すタイトル")
    ap.add_argument("--badge", default="", help="見出しの横に出す版の名前")
    ap.add_argument("--other-url", default="", help="もう一方の版のファイル名")
    ap.add_argument("--other-label", default="", help="もう一方の版へのリンクの文言")
    args = ap.parse_args()

    src, dst = Path(args.src), Path(args.out)
    if not src.exists():
        print(f"{src} がありません。先に analyze_fundamentals.py を実行してください。", file=sys.stderr)
        return 1

    payload = json.loads(src.read_text(encoding="utf-8"))

    # スクリーニング定義表（screening_config）。ランキングの種類・条件の一覧・整合性チェックを入れる。
    # 失敗してもページは出す（ランキングの欄に読み込めなかった旨を出す）
    try:
        sys.path.insert(0, str(BASE / "screening_config"))
        from dashboard_bridge import augment
        info = augment(payload)
        print(f"定義表: 条件{info['conds']}件（列を{info['added']}個追加）・ランキング{info['ranks']}種・"
              f"データ不整合{info['bad']}銘柄（{info['nulled']}個の値を空欄に）")
    except Exception as e:  # noqa: BLE001
        print(f"※ スクリーニング定義表を読み込めませんでした: {e}", file=sys.stderr)
        payload["定義表"] = {"conds": [], "ranks": [], "added": []}

    # 会社情報（従業員数・平均年収。make_company_links.py の出力）を列に足す（2026-11-18）
    try:
        add_company(payload, jp=True)
    except Exception as e:  # noqa: BLE001
        print("会社情報を読み込めません:", e, file=sys.stderr)

    # 最新の決算短信（fetch_tdnet.py → fundamentals/kessan_latest.csv。TDnet・発表当日の値）を列に足す（2026-11-16）
    try:
        add_kessan(payload)
    except Exception as e:  # noqa: BLE001  無くてもスクリーニングは作る（列が空になるだけ）
        print("最新の決算短信を読み込めません:", e, file=sys.stderr)

    # 同じフォルダにある個別チャート（<コード>.html）を数える。
    # チャートが無い銘柄で空のiframeを開かないよう、存在するものだけ渡す。
    dst.parent.mkdir(parents=True, exist_ok=True)
    ci = payload["fields"].index("コード")
    codes = {str(r[ci]) for r in payload["stocks"]}
    charts = sorted(p.stem for p in dst.parent.glob("*.html")
                    if p.stem in codes and p.name != dst.name)
    payload["charts"] = charts
    # 通期の業績ダッシュボード（make_company_dashboards.py → dashboards/<コード>.html）。
    # make_home.py が data/charts/gyoseki/ に複製して公開する。
    payload["gyoseki"] = sorted(p.stem for p in (BASE / "dashboards").glob("*.html")
                                if p.stem in codes)
    # 株式分析ダッシュボード（make_one_screen.py → dashboards/one/<コード>.html）。
    # make_home.py が data/charts/one/ に複製して公開する。詳細画面の先頭からリンクする
    one = {p.stem for d in (BASE / "dashboards" / "one", dst.parent / "one")
           for p in d.glob("*.html") if p.stem in codes}
    payload["one"] = sorted(one)
    # アナリスト予想（アナリスト予想/analyst_page.py の build()）。「アナリスト予想」タブで使う
    payload["analyst"] = None
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("analyst_page", BASE / "アナリスト予想" / "analyst_page.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        arows, aasof = mod.build()
        arows = [r for r in arows if str(r[0]) in codes]
        if arows:
            payload["analyst"] = {"asof": aasof, "rows": arows}
    except Exception as e:  # 無くてもスクリーニングは作る（タブが出ないだけ）
        print("アナリスト予想を読み込めません:", e, file=sys.stderr)

    # 書き出す前に中身を検査する。
    # 2026-09-15に、業種が空の7銘柄のせいで画面側の並べ替えが落ち、
    # ダッシュボード全体が真っ白になったことがある。データの穴は静かに広がるので、
    # 出力の直前で止めて気づけるようにしておく。
    problems = []
    for key in ("業種", "市場", "コード", "銘柄名"):
        if key in payload["fields"]:
            i = payload["fields"].index(key)
            n = sum(1 for r in payload["stocks"] if r[i] is None or r[i] == "")
            if n:
                problems.append(f"{key} が空の銘柄が {n} 件")
    si = payload["fields"].index("総合評価")
    scored = sum(1 for r in payload["stocks"] if r[si] is not None)
    if scored < len(payload["stocks"]) * 0.95:
        problems.append(f"総合評価が {scored}/{len(payload['stocks'])} 銘柄にしかない")
    for key in ("項目", "評価基準", "業種中央値"):
        if not payload.get(key):
            problems.append(f"{key} が空（analyze_fundamentals.py が古い可能性）")
    if problems:
        print("ダッシュボードを書き出せません:\n  - " + "\n  - ".join(problems)
              + "\n  analyze_fundamentals.py の出力を確認してください。", file=sys.stderr)
        return 1

    variant = ""
    if args.badge:
        variant += f'<span class="vbadge">{args.badge}</span>'
    if args.other_url and args.other_label:
        variant += f'<a class="vlink" href="{args.other_url}">{args.other_label}</a>'

    html = (TEMPLATE
            .replace("__TITLE__", args.title)
            .replace("__VARIANT__", variant)
            .replace("__DATA__", json.dumps(payload, ensure_ascii=False, separators=(",", ":"))))
    dst.write_text(html, encoding="utf-8")
    print(f"出力: {dst}  ({dst.stat().st_size/1024/1024:.1f} MB, "
          f"{payload['summary']['銘柄数']:,}銘柄／チャートあり {len(charts):,}銘柄)")
    if len(charts) < payload["summary"]["銘柄数"] * 0.9:
        print(f"※ チャートが {len(charts):,}銘柄分しかありません。"
              "make_all_charts.py を実行すると増えます。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
