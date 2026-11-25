#!/usr/bin/env python3
"""日経225 入れ替え予想・ウエート分析のダッシュボード（HTML）。report.write_html から呼ばれる。

ページの構成（上から、知りたい順）
  1. 次回の定期見直しまでのタイムライン（今日・基準日・発表・実施）
  2. 入れ替え予想（採用 ⇄ 除外のペアのカード。確度・順位・需給インパクト）
  3. ボーダーライン（採用に近い未採用 / 除外に近い採用銘柄。順位の位置を棒で）
  4. セクターの過不足（採用数と採用妥当数、指数ウエート）
  5. ウエート・寄与度（セクター構成、上位15と10%キャップ、期間切替の寄与度、推移）
  6. 過去の検証（的中率、採用・除外銘柄の値動き、売買ルール、回ごとの再現テスト）
"""
from __future__ import annotations

import html
import re
import json
import math

import numpy as np
import pandas as pd

from selection import ABS_ADD, HIGH_LIQ

SECTOR_COLORS = {"技術": "--c1", "情報通信": "--c2", "消費": "--c3", "素材": "--c4",
                 "資本財・その他": "--c5", "金融": "--c6", "運輸・公共": "--c7"}
CONF_N = {"高": 3, "中": 2, "低": 1}
RANK_MAX = 500   # 順位バーの右端


def _e(s):
    return html.escape("" if s is None or (isinstance(s, float) and math.isnan(s)) else str(s))


def _ok(v):
    try:
        return v is not None and not (isinstance(v, (float, np.floating)) and (math.isnan(v) or math.isinf(v)))
    except TypeError:
        return False


def _f(v, nd=1, sign=False, unit=""):
    if not _ok(v):
        return "－"
    x = float(v)
    s = f"{x:+,.{nd}f}" if sign else f"{x:,.{nd}f}"
    return s.replace("-", "−") + unit


def _dots(c):
    n = CONF_N.get(c, 0)
    i = "".join('<i class="on"></i>' if k < n else "<i></i>" for k in range(3))
    return f'<span class="conf" title="確度 {_e(c)}">{i}<b>{_e(c)}</b></span>'


def _trend(now, before):
    """順位の変化（小さいほど上位）。上がった＝採用に近づいた"""
    if not (_ok(now) and _ok(before)):
        return '<span class="meta">－</span>'
    d = float(before) - float(now)
    if abs(d) < 0.5:
        return '<span class="meta">→</span>'
    return (f'<span class="rk-up" title="3か月前 {before:.0f}位">▲{d:.0f}</span>' if d > 0
            else f'<span class="rk-dn" title="3か月前 {before:.0f}位">▼{-d:.0f}</span>')


def _rankbar(rank, mode):
    """1〜RANK_MAX位の物差しの上に順位の位置を打つ。mode=add は75位、del は450位の線を強調"""
    if not _ok(rank):
        return ""
    x = min(float(rank), RANK_MAX) / RANK_MAX * 100
    z75 = ABS_ADD / RANK_MAX * 100
    z450 = HIGH_LIQ / RANK_MAX * 100
    return (f'<div class="rbar" title="{rank:.0f}位"><span class="z-add" style="width:{z75:.1f}%"></span>'
            f'<span class="z-del" style="left:{z450:.1f}%;width:{100 - z450:.1f}%"></span>'
            f'<span class="ln{" hl" if mode == "add" else ""}" style="left:{z75:.1f}%"></span>'
            f'<span class="ln{" hl" if mode == "del" else ""}" style="left:{z450:.1f}%"></span>'
            f'<span class="pt {mode}" style="left:{x:.1f}%"></span></div>')


# ---------------------------------------------------------------- CSS
CSS = """
@import url("https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap");
:root{color-scheme:light;--page:#f6f6f3;--surface:#ffffff;--ink:#111;--ink2:#4d4c48;--muted:#8a8882;
 --grid:#e6e5df;--border:rgba(17,17,17,.09);--add:#c93a3a;--add-w:rgba(201,58,58,.09);--del:#2b7d6a;--del-w:rgba(43,125,106,.10);
 --accent:#2a78d6;--accent-w:rgba(42,120,214,.09);--warn:#b87700;--warn-w:rgba(237,161,0,.13);--good:#0c8f3a;--bad:#d03b3b;
 --c1:#2a78d6;--c2:#7a5cd6;--c3:#eb6834;--c4:#1baf7a;--c5:#eda100;--c6:#d6488a;--c7:#7d8a99;
 --up:#c93a3a;--dn:#2b7d6a;--shadow:0 1px 2px rgba(0,0,0,.04),0 4px 14px rgba(0,0,0,.04)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--page:#0e0e0d;--surface:#191918;--ink:#f4f4f2;
 --ink2:#c3c2b7;--muted:#8d8b84;--grid:#2c2c2a;--border:rgba(255,255,255,.09);--add:#ec6b6b;--add-w:rgba(236,107,107,.13);
 --del:#48b497;--del-w:rgba(72,180,151,.13);--accent:#4a93ea;--accent-w:rgba(74,147,234,.15);--warn:#e0a426;--warn-w:rgba(224,164,38,.15);
 --good:#3ec26b;--bad:#ec6b6b;--c1:#4a93ea;--c2:#9b82ea;--c3:#ef7d4e;--c4:#2fc08c;--c5:#e0a426;--c6:#e46aa2;--c7:#93a0ae;
 --up:#ec6b6b;--dn:#48b497;--shadow:none}}
:root[data-theme="dark"]{color-scheme:dark;--page:#0e0e0d;--surface:#191918;--ink:#f4f4f2;--ink2:#c3c2b7;--muted:#8d8b84;--grid:#2c2c2a;
 --border:rgba(255,255,255,.09);--add:#ec6b6b;--add-w:rgba(236,107,107,.13);--del:#48b497;--del-w:rgba(72,180,151,.13);--accent:#4a93ea;
 --accent-w:rgba(74,147,234,.15);--warn:#e0a426;--warn-w:rgba(224,164,38,.15);--good:#3ec26b;--bad:#ec6b6b;--c1:#4a93ea;--c2:#9b82ea;
 --c3:#ef7d4e;--c4:#2fc08c;--c5:#e0a426;--c6:#e46aa2;--c7:#93a0ae;--up:#ec6b6b;--dn:#48b497;--shadow:none}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:64px}
body{margin:0;background:var(--page);color:var(--ink);font:14px/1.6 system-ui,-apple-system,"Hiragino Sans","Hiragino Kaku Gothic ProN","Segoe UI",sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:0 16px 56px}
.top{position:sticky;top:0;z-index:5;background:color-mix(in srgb,var(--page) 88%,transparent);backdrop-filter:blur(8px);border-bottom:1px solid var(--border)}
.top .in{max-width:1180px;margin:0 auto;padding:10px 16px;display:flex;align-items:center;gap:14px;flex-wrap:wrap}
.top h1{font-size:16px;margin:0;white-space:nowrap}.top h1 a{color:inherit;text-decoration:none;margin-right:6px;color:var(--muted)}
.top nav{display:flex;gap:4px;overflow-x:auto;flex:1;scrollbar-width:none}.top nav::-webkit-scrollbar{display:none}
.top nav a{white-space:nowrap;color:var(--ink2);text-decoration:none;font-size:13px;padding:4px 10px;border-radius:999px}
.top nav a:hover{background:var(--accent-w);color:var(--accent)}
.meta{color:var(--muted);font-size:12px}
section{margin-top:28px}
.sh{display:flex;align-items:baseline;justify-content:space-between;gap:8px;flex-wrap:wrap;margin-bottom:10px}
h2{font-size:18px;margin:0;letter-spacing:.01em}h3{font-size:14px;margin:0 0 8px;color:var(--ink2)}
.card{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:16px;box-shadow:var(--shadow)}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
.grid4{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
@media (max-width:900px){.grid3,.grid4{grid-template-columns:1fr 1fr}}
@media (max-width:700px){.grid2,.grid3{grid-template-columns:1fr}}
@media (max-width:460px){.grid4{grid-template-columns:1fr}}
.grid2>*,.grid3>*,.grid4>*,.pair>*{min-width:0}
.tip{color:var(--muted);font-size:12px;margin:8px 0 0}
/* ヒーロー */
.hero{margin-top:18px;padding:20px}
.hero .ttl{display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap;align-items:flex-end}
.hero .big{font-size:26px;font-weight:750;line-height:1.25}.hero .big small{font-size:14px;font-weight:500;color:var(--ink2);margin-left:6px}
.cd{text-align:right}@media (max-width:520px){.hero .big small{display:block;margin:4px 0 0}.top nav{flex-basis:100%;margin:0 -6px}}.cd .n{font-size:30px;font-weight:750;font-variant-numeric:tabular-nums;line-height:1}.cd .l{font-size:12px;color:var(--muted)}
.tl{position:relative;height:64px;margin:22px 6px 14px}
.tl .track{position:absolute;left:0;right:0;top:22px;height:6px;border-radius:99px;background:var(--grid)}
.tl .done{position:absolute;left:0;top:22px;height:6px;border-radius:99px;background:var(--accent)}
.tl .mk{position:absolute;top:0;transform:translateX(-50%);text-align:center;font-size:11px;color:var(--ink2);white-space:nowrap}
.tl .mk .d{display:block;width:14px;height:14px;border-radius:50%;background:var(--surface);border:3px solid var(--muted);margin:18px auto 4px}
.tl .mk.key .d{border-color:var(--accent)}.tl .mk b{display:block;font-size:12px;color:var(--ink)}
.tl .mk.first{transform:none;text-align:left}.tl .mk.first .d{margin-left:0}.tl .mk.last{transform:translateX(-100%);text-align:right}.tl .mk.last .d{margin-right:0}
@media (max-width:520px){.tl .xs{display:none}.cd{text-align:left}}
.tl .now{position:absolute;top:8px;width:2px;height:34px;background:var(--accent);transform:translateX(-1px)}
.tl .now span{position:absolute;top:-16px;left:50%;transform:translateX(-50%);font-size:11px;font-weight:700;color:var(--accent);white-space:nowrap}
.kpis{margin-top:14px}
.kpi{padding:12px 14px}.kpi .k{font-size:12px;color:var(--ink2)}.kpi .v{font-size:20px;font-weight:700;margin-top:2px;font-variant-numeric:tabular-nums}
.kpi .s{font-size:12px;color:var(--muted);overflow:hidden;text-overflow:ellipsis}
.kpi.alert{border-color:color-mix(in srgb,var(--warn) 45%,transparent);background:linear-gradient(0deg,var(--warn-w),var(--warn-w)),var(--surface)}
.good{color:var(--good)}.bad{color:var(--bad)}.warn{color:var(--warn)}
/* 予想ペア */
.pairs{display:grid;gap:14px}
.pair{display:grid;grid-template-columns:1fr 44px 1fr;align-items:stretch;padding:0;overflow:hidden}
.pair .rule{grid-column:1/-1;padding:10px 16px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;align-items:center}
.pair .rule b{font-size:13px}.pair .rule .meta{font-size:12px}
.side{padding:14px 16px}.side.add{background:var(--add-w)}.side.del{background:var(--del-w)}
.side .tag{display:inline-block;font-size:11px;font-weight:700;padding:1px 8px;border-radius:999px;color:#fff}
.side.add .tag{background:var(--add)}.side.del .tag{background:var(--del)}
.side .nm{font-size:19px;font-weight:750;margin:6px 0 0;line-height:1.3}.side .cd2{font-size:12px;color:var(--muted)}
.side dl{display:grid;grid-template-columns:auto 1fr;gap:3px 12px;margin:10px 0 0;font-size:13px}
.side dt{color:var(--ink2)}.side dd{margin:0;text-align:right;font-variant-numeric:tabular-nums}
.arrow{display:flex;align-items:center;justify-content:center;font-size:20px;color:var(--muted)}
@media (max-width:640px){.pair{grid-template-columns:1fr}.arrow{height:26px;transform:rotate(90deg)}}
.conf{display:inline-flex;align-items:center;gap:3px;font-size:12px}.conf i{width:8px;height:8px;border-radius:50%;background:var(--grid)}
.conf i.on{background:var(--accent)}.conf b{margin-left:4px;font-weight:600;color:var(--ink2)}
.none{padding:22px;text-align:center;color:var(--ink2)}
/* 表 */
.tbl{width:100%;border-collapse:collapse;font-size:13px}
.tbl th{text-align:left;color:var(--muted);font-weight:600;font-size:12px;border-bottom:1px solid var(--grid);padding:6px 6px;white-space:nowrap}
.tbl td{border-bottom:1px solid var(--grid);padding:7px 6px;vertical-align:middle}.tbl tr:last-child td{border-bottom:0}
.tbl td.n,.tbl th.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.tbl td.nm{white-space:nowrap;max-width:13em;overflow:hidden;text-overflow:ellipsis;font-weight:600}
.tbl .c{font-size:11px;color:var(--muted);font-weight:400;font-variant-numeric:tabular-nums}
.tbl tr.hl td{background:var(--accent-w)}
.scroll{overflow-x:auto}
.chips{display:flex;flex-wrap:wrap;gap:4px;margin-top:3px;white-space:normal}.chips:empty{display:none}.tbl .rb{width:34%}
@media (max-width:520px){.tbl .mh,.tbl .dt{display:none}.tbl .rb{width:auto}.rbar{min-width:50px}.tbl td.nm{max-width:8.5em}.tbl th,.tbl td{padding-left:4px;padding-right:4px}}
.chip{display:inline-block;font-size:11px;padding:1px 7px;border-radius:999px;white-space:nowrap;border:1px solid var(--border);color:var(--ink2)}
.chip.add{background:var(--add);border-color:transparent;color:#fff}.chip.del{background:var(--del);border-color:transparent;color:#fff}
.chip.warn{background:var(--warn-w);color:var(--warn);border-color:transparent}.chip.mute{background:var(--grid)}
.rk-up{color:var(--add);font-size:12px;font-variant-numeric:tabular-nums}.rk-dn{color:var(--del);font-size:12px;font-variant-numeric:tabular-nums}
.rbar{position:relative;height:10px;min-width:130px;border-radius:99px;background:var(--grid)}
.rbar .z-add{position:absolute;left:0;top:0;bottom:0;border-radius:99px 0 0 99px;background:color-mix(in srgb,var(--add) 22%,transparent)}
.rbar .z-del{position:absolute;top:0;bottom:0;border-radius:0 99px 99px 0;background:color-mix(in srgb,var(--del) 22%,transparent)}
.rbar .ln{position:absolute;top:-2px;bottom:-2px;width:1px;background:var(--muted);opacity:.5}.rbar .ln.hl{opacity:1;width:2px}
.rbar .pt{position:absolute;top:50%;width:10px;height:10px;border-radius:50%;transform:translate(-50%,-50%);border:2px solid var(--surface)}
.rbar .pt.add{background:var(--add)}.rbar .pt.del{background:var(--del)}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:var(--ink2);margin-top:8px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px;vertical-align:-1px}
/* セクター */
.sec{display:grid;grid-template-columns:minmax(84px,120px) 74px minmax(0,1fr) 96px minmax(80px,150px);gap:8px 12px;align-items:center;font-size:13px}
.sec .h{font-size:12px;color:var(--muted)}.sec .n{text-align:right;font-variant-numeric:tabular-nums}
.dv{position:relative;height:16px}.dv .m{position:absolute;left:50%;top:-3px;bottom:-3px;width:1px;background:var(--muted)}
.dv .b{position:absolute;top:2px;height:12px;border-radius:3px}.dv .g{position:absolute;top:2px;height:12px;border-radius:3px;border:1.5px dashed var(--muted);background:transparent}
.wbar{height:10px;border-radius:0 3px 3px 0}
.sec .mob{display:none}@media (max-width:640px){.sec .dt2{display:none}}
@media (max-width:640px){.sec{grid-template-columns:104px minmax(0,1fr) 82px;gap:10px 8px}.sec .wcol,.sec .cnt{display:none!important}.sec .mob{display:block;font-size:11px}.sec .h:nth-child(3){font-size:10px;line-height:1.3}}
.sw{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px}
/* ウエート */
.stack{display:flex;height:30px;border-radius:8px;overflow:hidden;margin:4px 0 8px}
.stack span{display:flex;align-items:center;justify-content:center;color:#fff;font-size:11px;font-weight:600;white-space:nowrap;overflow:hidden}
.wl{display:grid;grid-template-columns:minmax(80px,150px) minmax(0,1fr) 58px;gap:5px 10px;align-items:center;font-size:13px}
.wl .tr{position:relative;height:14px}.wl .tr .b{height:14px;border-radius:0 4px 4px 0}
.wl .tr .cap{position:absolute;top:-4px;bottom:-4px;width:0;border-left:2px dashed var(--bad)}
.wl .n{text-align:right;font-variant-numeric:tabular-nums}
.wl .nm{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.seg{display:inline-flex;background:var(--grid);border-radius:999px;padding:2px}
.seg button{border:0;background:transparent;color:var(--ink2);font:inherit;font-size:12px;padding:3px 11px;border-radius:999px;cursor:pointer}
.seg button.on{background:var(--surface);color:var(--ink);font-weight:600;box-shadow:0 1px 2px rgba(0,0,0,.12)}
.cb{display:grid;grid-template-columns:1fr 1fr;gap:6px 18px;margin-top:10px}@media (max-width:520px){.cb{grid-template-columns:1fr}}
.cl h4{font-size:12px;margin:0 0 4px;font-weight:600}.cl .rw{display:grid;grid-template-columns:minmax(0,1fr) 70px;gap:2px 8px;align-items:center;font-size:13px;margin:5px 0}
.cl .nm{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.cl .v{text-align:right;font-variant-numeric:tabular-nums}
.cl .tr{grid-column:1/-1;height:6px;border-radius:99px;background:var(--grid);overflow:hidden}.cl .tr span{display:block;height:100%;border-radius:99px}
.alertbox{display:flex;gap:12px;align-items:flex-start;padding:12px 14px;border-radius:12px;background:var(--warn-w);margin-top:12px;font-size:13px}
.alertbox .ic{font-size:18px;line-height:1.2;color:var(--warn)}
.chartbox{position:relative;height:260px}
/* 検証 */
.how{border-left:3px solid var(--accent);background:var(--accent-w);padding:12px 14px;border-radius:0 12px 12px 0;font-size:13px}
.how ul{margin:6px 0 0;padding-left:18px}.how li{margin:2px 0}
.big2{font-size:24px;font-weight:750;font-variant-numeric:tabular-nums}
.meter{height:6px;border-radius:99px;background:var(--grid);overflow:hidden;margin-top:8px}.meter span{display:block;height:100%;background:var(--accent)}
details{margin-top:12px}summary{cursor:pointer;color:var(--ink2);font-size:13px}
.hit{font-weight:700}.hit.full{color:var(--good)}.hit.part{color:var(--warn)}.hit.zero{color:var(--bad)}
footer{margin-top:32px;color:var(--muted);font-size:12px;line-height:1.7}
a{color:var(--accent)}
/* ===== 2026-11 デザイン刷新（トップ画面と共通）：黒／白地、枠線なしのカード、数字は Inter の極太 ===== */
:root{--page:#f3f4f6;--surface:#fff;--ink:#0c0d10;--ink2:#3d4148;--muted:#5b6068;--grid:#dfe2e7;--border:rgba(12,13,16,.13);--add:#b91c24;--add-w:rgba(185,28,36,.09);--del:#08705a;--del-w:rgba(8,112,90,.10);--up:#b91c24;--dn:#08705a;--bad:#b91c24;--shadow:none}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--page:#050608;--surface:#101216;--ink:#f2f4f8;--ink2:#c6cbd6;--muted:#8f96a3;--grid:#23262d;--border:rgba(255,255,255,.13);--add:#ff7378;--add-w:rgba(255,115,120,.13);--del:#3fd0a4;--del-w:rgba(63,208,164,.12);--up:#ff7378;--dn:#3fd0a4;--bad:#ff7378;--shadow:none}}
:root[data-theme="dark"]{--page:#050608;--surface:#101216;--ink:#f2f4f8;--ink2:#c6cbd6;--muted:#8f96a3;--grid:#23262d;--border:rgba(255,255,255,.13);--add:#ff7378;--add-w:rgba(255,115,120,.13);--del:#3fd0a4;--del-w:rgba(63,208,164,.12);--up:#ff7378;--dn:#3fd0a4;--bad:#ff7378;--shadow:none}
body{font-family:Inter,"Hiragino Sans","Hiragino Kaku Gothic ProN","Noto Sans JP",system-ui,-apple-system,"Segoe UI",sans-serif;font-variant-numeric:tabular-nums;-webkit-font-smoothing:antialiased}
.top h1{font-weight:800}
h2{font-weight:800}
.card{border:0}
.cd .n{font-weight:800;letter-spacing:-.03em}
/* ---- 入れ替えボード／日程と値動き／順位の物差し（2026-11） ---- */
.nb{padding:22px 24px}
.nb-top{display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:space-between;gap:8px 24px}
.nb-k{font-size:12px;font-weight:800;letter-spacing:.1em}
.nb-date{font-size:clamp(30px,4.6vw,52px);font-weight:800;letter-spacing:-.03em;line-height:1.05;margin-top:4px}
.nb-date small{font-size:14px;font-weight:600;letter-spacing:0;color:var(--muted);margin-left:10px}
.nb-cd{text-align:right}.nb-cd b{font-size:clamp(34px,5vw,56px);font-weight:800;letter-spacing:-.04em;line-height:1}
.nb-cd span{display:block;font-size:12px;color:var(--muted)}
.nb-rows{display:flex;flex-direction:column;gap:10px;margin-top:18px}
.nb-row{display:grid;grid-template-columns:86px minmax(0,1fr) 34px minmax(0,1fr);gap:10px;align-items:stretch}
.nb-conf{display:flex;flex-direction:column;justify-content:center;gap:4px;font-size:11.5px;color:var(--muted)}
.nb-conf b{font-size:20px;font-weight:800;color:var(--ink);line-height:1}
.nb-dots{display:flex;gap:4px}.nb-dots i{width:9px;height:9px;border-radius:50%;background:var(--grid)}.nb-dots i.on{background:var(--ink)}
.nb-side{border-radius:12px;padding:12px 16px;display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:6px 16px;min-width:0}
.nb-in{background:var(--add-w)}.nb-out{background:var(--del-w)}
.nb-tag{display:inline-block;font-size:11px;font-weight:800;color:#fff;border-radius:999px;padding:1px 9px;margin-bottom:3px}
.nb-in .nb-tag{background:#c8323a}.nb-out .nb-tag{background:#0f7f63}
.nb-nm{font-size:24px;font-weight:800;line-height:1.2}
.nb-sub{font-size:11.5px;color:var(--muted)}
.nb-imp{min-width:150px;flex:0 1 190px}
.nb-imp .v{font-size:19px;font-weight:800;letter-spacing:-.02em}.nb-imp .v small{font-size:11.5px;font-weight:600;color:var(--muted);margin-left:4px}
.nb-in .nb-imp .v{color:var(--add)}.nb-out .nb-imp .v{color:var(--del)}
.nb-bar{height:6px;background:var(--grid);margin-top:5px}.nb-bar i{display:block;height:6px}
.nb-in .nb-bar i{background:#c8323a}.nb-out .nb-bar i{background:#0f7f63}
.nb-imp .d{font-size:11.5px;color:var(--ink2);margin-top:3px}
.nb-arrow{display:flex;align-items:center;justify-content:center;font-size:20px;color:var(--muted)}
.nb-why{grid-column:2/-1;font-size:11.5px;color:var(--muted);margin-top:-4px}
.nb-foot{display:flex;flex-wrap:wrap;gap:6px 28px;margin-top:16px;padding-top:14px;border-top:1px solid var(--grid);font-size:12.5px;color:var(--ink2)}
.nb-foot b{font-size:18px;font-weight:800;color:var(--ink);letter-spacing:-.02em}
/* 日程と値動き */
.ph{display:grid;grid-template-columns:1.5fr 1fr 1fr 1fr 1fr;gap:0;margin-top:6px}
.ph-c{padding:0 14px 0 0;min-width:0}
.ph-line{position:relative;height:22px;margin:8px 0 10px}
.ph-line::before{content:"";position:absolute;left:0;right:0;top:10px;height:3px;background:var(--grid)}
.ph-c.past .ph-line::before{background:var(--ink)}
.ph-c.cur .ph-line::before{background:linear-gradient(90deg,var(--ink) 0 var(--p),var(--grid) var(--p) 100%)}
.ph-line i{position:absolute;left:0;top:5px;width:13px;height:13px;border-radius:50%;background:var(--surface);border:3px solid var(--ink);box-sizing:border-box}
.ph-now{position:absolute;left:var(--p);top:-9px;transform:translateX(-50%);font-size:10.5px;font-weight:800;background:var(--ink);color:var(--surface);border-radius:4px;padding:1px 6px;white-space:nowrap}
.ph-d{font-size:20px;font-weight:800;letter-spacing:-.02em;line-height:1.1}
.ph-n{font-size:12px;font-weight:800}
.ph-t{font-size:11.5px;color:var(--muted);line-height:1.5}
.ph-r{display:flex;align-items:baseline;justify-content:space-between;gap:6px;font-size:12px;color:var(--ink2);padding:3px 0;border-top:1px solid var(--grid)}
.ph-r b{font-size:17px;font-weight:800;letter-spacing:-.02em}
.ph-r b.u{color:var(--up)}.ph-r b.d{color:var(--dn)}
.ph-r small{font-size:10.5px;color:var(--muted);margin-left:4px}
.ph-nowm{display:none;font-size:10.5px;font-weight:800;background:var(--ink);color:var(--surface);border-radius:4px;padding:1px 6px;margin-left:8px;vertical-align:4px;letter-spacing:0}
.ph-note{font-size:11.5px;color:var(--muted);margin:12px 0 0}
.ph-tip{margin-top:12px;padding:12px 14px;border-radius:12px;background:var(--page);font-size:13px;line-height:1.6}
.ph-tip b{font-weight:800}
/* 順位の物差し */
.rk-2{display:grid;grid-template-columns:1fr 1fr;gap:16px 36px}
.rk{position:relative;height:96px;margin:6px 6px 0}
.rk-ax{position:absolute;left:0;right:0;top:50px;height:12px;background:var(--grid)}
.rk-z{position:absolute;top:50px;height:12px}.rk-za{background:#c8323a}.rk-zd{background:#0f7f63}
.rk-zl{position:absolute;top:30px;font-size:11px;font-weight:800}
.rk-t{position:absolute;top:66px;font-size:10.5px;color:var(--muted);transform:translateX(-50%);white-space:nowrap}
.rk-p{position:absolute;top:49px;width:10px;height:10px;border-radius:50%;transform:translate(-50%,0);border:2px solid var(--surface);box-sizing:content-box}
.rk-p.a{background:var(--add)}.rk-p.o{background:var(--del)}
.rk-p.key{top:46px;width:16px;height:16px;border-color:var(--ink);z-index:1}
.rk-l{position:absolute;top:0;font-size:12.5px;font-weight:800;white-space:nowrap;transform:translateX(-50%);line-height:1.2;text-align:center}
.rk-l small{display:block;font-size:10.5px;font-weight:600;color:var(--muted)}
.rk-l::after{content:"";position:absolute;left:50%;top:100%;width:1px;height:14px;background:var(--ink)}
.rk-cs{display:flex;flex-wrap:wrap;gap:5px 6px;margin-top:6px}
.rk-c{font-size:11.5px;padding:2px 9px 2px 3px;border-radius:999px;background:var(--page);white-space:nowrap;display:inline-flex;align-items:center;gap:6px}
.rk-c b{font-size:11px;font-weight:800;background:var(--surface);border-radius:999px;padding:1px 7px;min-width:34px;text-align:center}
.rk-c small{font-size:10px;color:var(--muted)}
.rk-c.key{outline:2px solid var(--ink)}
details.old{margin-top:12px}details.old>summary{cursor:pointer;font-size:13px;font-weight:700;padding:10px 0}
@media (max-width:760px){.nb{padding:16px 14px}.nb-row{grid-template-columns:1fr}.nb-arrow{transform:rotate(90deg);height:18px}.nb-why{grid-column:1}.nb-conf{flex-direction:row;align-items:center;gap:8px}
 .nb-nm{font-size:20px}.ph{grid-template-columns:1fr;gap:12px}.ph-line{display:none}.ph-c{padding:10px 0 0;border-top:3px solid var(--grid)}.ph-c.past,.ph-c.cur{border-top-color:var(--ink)}.ph-nowm{display:inline-block}
 .rk-2{grid-template-columns:1fr}}
.nb-none{margin-top:16px;font-size:15px;color:var(--ink2)}
.rk-tbl{display:grid;grid-template-columns:1fr 1fr;gap:14px 28px;margin-top:10px}@media (max-width:700px){.rk-tbl{grid-template-columns:1fr}}
"""


# ---------------------------------------------------------------- 部品
def _timeline(ctx):
    nxt = ctx["nxt"]
    today = pd.Timestamp(ctx["today"])
    eff, base, ann = nxt["effective"], nxt["base"], nxt["announce_est"]
    prev = eff - pd.DateOffset(months=6)
    span = max(1, (eff - prev).days)

    def pos(d):
        return max(0.0, min(100.0, (d - prev).days / span * 100))

    marks = [(prev, "前回実施", "first", ""), (base, "基準日", "", "key"), (ann, "発表<span class=\"xs\">（予想）</span>", "", "key"), (eff, "実施", "last", "key")]
    mk = "".join(f'<div class="mk {cls} {key}" style="left:{pos(d):.1f}%"><span class="d"></span><b>{d:%-m/%-d}</b>{lab}</div>'
                 for d, lab, cls, key in marks)
    now = pos(today)
    days_base = (base - today).days
    if days_base > 0:
        cd = f'<div class="n">{days_base}<small style="font-size:14px">日</small></div><div class="l">基準日（{base:%-m/%-d}）まで</div>'
    elif (ann - today).days > 0:
        cd = f'<div class="n">{(ann - today).days}<small style="font-size:14px">日</small></div><div class="l">発表（{ann:%-m/%-d}ごろ）まで</div>'
    else:
        cd = f'<div class="n">{max(0, (eff - today).days)}<small style="font-size:14px">日</small></div><div class="l">実施（{eff:%-m/%-d}）まで</div>'
    return f"""
<div class="card hero">
 <div class="ttl"><div><div class="meta">次回の定期見直し</div>
  <div class="big">{eff:%Y年%-m月%-d日} 実施<small>基準日 {base:%-m/%-d}・発表 {ann:%-m/%-d}ごろ</small></div></div>
  <div class="cd">{cd}</div></div>
 <div class="tl"><div class="track"></div><div class="done" style="width:{now:.1f}%"></div>{mk}
  <div class="now" style="left:{now:.1f}%"><span>今日</span></div></div>
 <p class="tip">順位は基準日までの5年間の売買代金などで決まります。いまの予想は「{ctx['asof']:%Y/%-m/%-d}までの株価のまま基準日を迎えたら」の暫定版で、基準日に近づくほど確かになります。</p>
</div>"""


def _countdown(ctx):
    nxt = ctx["nxt"]
    today = pd.Timestamp(ctx["today"])
    eff, base, ann = nxt["effective"], nxt["base"], nxt["announce_est"]
    if (base - today).days > 0:
        return (base - today).days, f"基準日（{base:%-m/%-d}）まで"
    if (ann - today).days > 0:
        return (ann - today).days, f"発表（{ann:%-m/%-d}ごろ）まで"
    return max(0, (eff - today).days), f"実施（{eff:%-m/%-d}）まで"


def _board(ctx, adds, dels):
    """最上部の「入れ替えボード」：実施日・残り日数と、採用⇄除外の予想を1枚にまとめる。
    右側は連動資金の売買額と、それが売買代金の何日分か（棒の長さ＝日数）"""
    nxt, names, aum = ctx["nxt"], ctx["names"], float(ctx["aum"])
    eff, base, ann = nxt["effective"], nxt["base"], nxt["announce_est"]
    imp = ctx["impact"].set_index("コード") if len(ctx["impact"]) else pd.DataFrame()
    n, lab = _countdown(ctx)
    head = (f'<div class="nb-top"><div><div class="nb-k">次回の定期見直し — 入れ替え予想</div>'
            f'<div class="nb-date">{eff:%Y年%-m月%-d日} 実施<small>基準日 {base:%-m/%-d}・発表 {ann:%-m/%-d}ごろ</small></div></div>'
            f'<div class="nb-cd"><b>{n}<span style="display:inline;font-size:16px;color:var(--ink);font-weight:800">日</span></b><span>{lab}</span></div></div>')

    def key(d):
        return d.rule.split("（")[0]
    pairs, used = [], set()
    for a in adds:
        m = next((d for d in dels if key(d) == key(a) and d.code not in used), None)
        if m is not None:
            used.add(m.code)
        pairs.append([a, m])
    rest = [d for d in dels if d.code not in used]
    for p in pairs:
        if p[1] is None and rest:
            p[1] = rest.pop(0)
    pairs += [[None, d] for d in rest]

    def flow(d):
        if d is None or d.code not in imp.index:
            return None
        i = imp.loc[d.code]
        w, tv = float(i["想定ウエート(%)"]), float(i["売買代金20日平均(億円)"])
        f = aum * 1e4 * abs(w) / 100   # 億円
        return f, (f / tv if _ok(tv) and tv > 0 else None)
    flows = {d.code: flow(d) for p in pairs for d in p if d is not None}
    mx = max([v[1] for v in flows.values() if v and v[1]] + [1e-9])

    def side(d, kind):
        tag, cls = ("採用", "nb-in") if kind == "add" else ("除外", "nb-out")
        if d is None:
            return f'<div class="nb-side {cls}"><div><span class="nb-tag">{tag}</span><div class="nb-sub">対になる銘柄の予想なし</div></div></div>'
        rank = f"・流動性 {d.liq_rank:.0f}位" if _ok(d.liq_rank) and d.liq_rank < 10_000 else ""
        impact, fl = "", flows.get(d.code)
        if fl:
            f, days = fl
            bar = (f'<div class="nb-bar"><i style="width:{min(100.0, days / mx * 100):.0f}%"></i></div><div class="d">売買代金の <b>{days:.1f}日分</b></div>'
                   if days else "")
            impact = f'<div class="nb-imp"><div class="v">約{f:,.0f}億円<small>の{"買い" if kind == "add" else "売り"}</small></div>{bar}</div>'
        return (f'<div class="nb-side {cls}"><div><span class="nb-tag">{tag}</span><div class="nb-nm">{_e(names.get(d.code, d.code))}</div>'
                f'<div class="nb-sub">{_e(d.code)}・{_e(d.sector)}{rank}</div></div>{impact}</div>')

    if not pairs:
        rows = '<div class="nb-none">いまの株価では、次回の入れ替えは予想されていません。</div>'
    else:
        rows = ""
        for a, d in pairs:
            ref = a or d
            notes = " ／ ".join(_e(x.note) for x in (a, d) if x is not None and x.note)
            conf = min((x.confidence for x in (a, d) if x is not None), key=lambda c: CONF_N.get(c, 0))
            dots = "".join(f'<i class="{"on" if i < CONF_N.get(conf, 0) else ""}"></i>' for i in range(3))
            rows += (f'<div class="nb-row"><div class="nb-conf"><span>確度</span><b>{_e(conf)}</b><div class="nb-dots">{dots}</div></div>'
                     f'{side(a, "add")}<div class="nb-arrow" aria-hidden="true">⇄</div>{side(d, "del")}'
                     f'<div class="nb-why">{_e(key(ref))}{"：" + notes if notes else ""}</div></div>')
        rows = f'<div class="nb-rows">{rows}</div>'
    foot = ""
    bt = ctx["bt"]
    if bt:
        try:
            h = bt["hit"]
            foot = ("<span>この予想の実績（再現テスト）</span>"
                    + "".join(f'<span>{k} <b>{h[k][0]}</b> / {h[k][1]} 銘柄</span>' for k in ("採用", "除外")))
        except Exception:  # noqa: BLE001
            foot = ""
    foot += (f'<span style="color:var(--muted)">いまの予想は {ctx["asof"]:%-m/%-d} までの株価による暫定版。基準日に近づくほど確かになります。'
             f'確度：高＝ルール上ほぼ確実 ／ 中 ／ 低＝閾値が非公表で不確か</span>')
    return f'<div class="card nb">{head}{rows}<div class="nb-foot">{foot}</div></div>'


def _phases(ctx):
    """日程を5つの時期に分け、それぞれの時期に採用・除外銘柄がどう動きやすかったか（対TOPIX・中央値）を並べる"""
    nxt = ctx["nxt"]
    today = pd.Timestamp(ctx["today"])
    eff, base, ann = nxt["effective"], nxt["base"], nxt["announce_est"]
    bt = ctx["bt"]
    es = bt["event_summary"] if bt else None

    def rows(col):
        if es is None or not col or col not in es.columns:
            return ""
        out = ""
        for k in ("採用", "除外"):
            try:
                v = float(es.loc[("中央値(%)", k), col])
                w = es.loc[("プラスの割合(%)", k), col]
            except (KeyError, TypeError, ValueError):
                continue
            if not _ok(v):
                continue
            win = f'<small>勝率 {float(w):.0f}%</small>' if _ok(w) else ""
            out += (f'<div class="ph-r"><span>{k}</span><span><b class="{"u" if v > 0 else "d" if v < 0 else ""}">{v:+.1f}%</b>{win}</span></div>')
        return out
    prev = eff - pd.DateOffset(months=6)
    eve = eff - pd.offsets.BDay(1)
    day = pd.Timedelta(days=1)
    steps = [(f"〜{base:%-m/%-d}", "基準日まで", "順位が動く期間。いまの予想は暫定で、ここで入れ替わることがあります", "", prev, base),
             (f"{base:%-m/%-d} → {ann:%-m/%-d}", "基準日 → 発表", "予想が固まり、先回りの売買が入り始める", "基準日→発表日", base, ann),
             (f"{ann:%-m/%-d}ごろ", "発表の翌日", "発表は大引け後。翌日が発表への反応", "発表翌日（発表日→翌営業日）", ann, ann + day),
             (f"→ {eve:%-m/%-d}", "発表後 → 実施前日", "連動ファンドは実施前日の大引けで売買", "発表翌日→実施前日", ann + day, eff),
             (f"{eff:%-m/%-d} 〜", "実施後 20日", "買いが一巡し、採用銘柄は反落しやすい", "実施前日→実施後20日", eff, eff + pd.Timedelta(days=30))]
    cur = next((i for i, st in enumerate(steps) if today < st[5]), len(steps) - 1)
    cells = ""
    for i, (d, n, t, col, a, b) in enumerate(steps):
        cls, now, nowm, sty = "", "", "", ""
        if i < cur:
            cls = "past"
        elif i == cur:
            cls = "cur"
            p = max(6.0, min(94.0, (today - a).days / max(1, (b - a).days) * 100))
            sty = f' style="--p:{p:.0f}%"'
            now = f'<span class="ph-now">今日 {today:%-m/%-d}</span>'
            nowm = '<span class="ph-nowm">いまここ</span>'
        cells += (f'<div class="ph-c {cls}"{sty}><div class="ph-d">{d}{nowm}</div><div class="ph-line"><i></i>{now}</div>'
                  f'<div class="ph-n">{n}</div><div class="ph-t">{t}</div>{rows(col)}</div>')
    tip = ""
    if bt:
        try:
            st_ = bt["strategy"]
            buy = st_[st_["売買"].str.startswith("買い")]["実施前日まで(%)"].dropna() if len(st_) else pd.Series(dtype=float)
            sell = st_[st_["売買"].str.startswith("売り")]["実施前日まで(%)"].dropna() if len(st_) else pd.Series(dtype=float)
            parts = []
            if len(buy):
                parts.append(f'予想採用を基準日の翌営業日に買い、当たれば実施前日・外れたら発表翌日に手じまうと、平均 <b>{_f(buy.mean(), 1, sign=True, unit="%")}</b>'
                             f'（{len(buy)}件・勝率{(buy > 0).mean() * 100:.0f}%）。')
            try:
                after = float(es.loc[("中央値(%)", "採用"), "実施前日→実施後20日"])
            except Exception:  # noqa: BLE001
                after = np.nan
            if _ok(after) and after < 0:
                parts.append(f'採用銘柄は実施後に反落しやすい（20日で中央値 {after:+.1f}%）。')
            if len(sell):
                parts.append(f'予想除外の空売りは平均 {_f(sell.mean(), 1, sign=True, unit="%")}'
                             + ("で、有効ではありませんでした。" if sell.mean() < 0 else "。"))
            if parts:
                tip = f'<div class="ph-tip"><b>過去の傾向から言えること：</b>{"".join(parts)}</div>'
        except Exception:  # noqa: BLE001
            tip = ""
    meta = "対TOPIXの超過リターン（中央値）・2023年4月以降の定期見直し" if es is not None else ""
    return (f'<section id="phase"><div class="sh"><h2>日程と、その時期に起きやすい値動き</h2><span class="meta">{meta}</span></div>'
            f'<div class="card"><div class="ph">{cells}</div>{tip}</div></section>')


def _kpis(ctx, adds, dels):
    wt, val, capw = ctx["wt"], ctx["val"], ctx["capw"]
    bt = ctx["bt"]
    k = []
    k.append(("", "ウエート1位", f"{_e(wt.iloc[0]['銘柄名'])} {wt.iloc[0]['ウエート(%)']:.1f}%",
              f"上位5銘柄で {wt['ウエート(%)'].iloc[:5].sum():.1f}%"))
    down = capw[capw.iloc[:, 3].astype(str).str.contains("引き下げ")] if len(capw) else capw
    if len(down):
        r = down.iloc[0]
        k.append(("alert", "キャップ監視", f'<span class="warn">{len(down)}銘柄が10%超</span>',
                  f"{_e(ctx['names'].get(r['コード'], r['コード']))} {r['ウエート(%)']:.1f}% → 基準日に係数引き下げ"))
    else:
        k.append(("", "キャップ監視", '<span class="good">10%超なし</span>', "ウエート10%を超える銘柄はありません"))
    ok = val["ok"]
    k.append(("" if ok is not False else "alert", "係数表の検証",
              '<span class="good">✓ 日経平均と一致</span>' if ok else ('<span class="bad">ずれあり</span>' if ok is False else "－"),
              _e(val["message"])))
    return '<div class="grid3 kpis" style="margin-bottom:14px">' + "".join(
        f'<div class="card kpi {c}"><div class="k">{a}</div><div class="v">{b}</div><div class="s">{s}</div></div>' for c, a, b, s in k) + "</div>"


def _pairs(ctx, adds, dels):
    names, aum = ctx["names"], float(ctx["aum"])
    imp = ctx["impact"].set_index("コード") if len(ctx["impact"]) else pd.DataFrame()
    rk = ctx["ranks"].set_index("code")
    if not adds and not dels:
        return '<div class="card none">いまの株価では、次回の入れ替えは予想されていません。</div>'

    def key(d):
        return d.rule.split("（")[0]
    pairs, used = [], set()
    for a in adds:
        m = next((d for d in dels if key(d) == key(a) and d.code not in used), None)
        if m is not None:
            used.add(m.code)
        pairs.append([a, m])
    rest = [d for d in dels if d.code not in used]
    for p in pairs:
        if p[1] is None and rest:
            p[1] = rest.pop(0)
    pairs += [[None, d] for d in rest]

    def side(d, kind):
        if d is None:
            return f'<div class="side {kind}"><span class="tag">{"採用" if kind == "add" else "除外"}</span><div class="nm meta" style="font-size:14px;font-weight:400">対になる銘柄の予想なし</div></div>'
        i = imp.loc[d.code] if d.code in imp.index else None
        rows = [("流動性順位", f"{d.liq_rank:.0f}位 " + _trend(d.liq_rank, rk["順位(3か月前)"].get(d.code, np.nan)) if _ok(d.liq_rank) and d.liq_rank < 10_000 else "－"),
                ("セクター", _e(d.sector))]
        if i is not None:
            w, tv, px = float(i["想定ウエート(%)"]), float(i["売買代金20日平均(億円)"]), float(i["株価"])
            flow = aum * 1e4 * abs(w) / 100   # 億円
            rows.append(("株価", f"{px:,.0f}円"))
            rows.append(("採用時の想定ウエート" if kind == "add" else "いまのウエート", f"{abs(w):.2f}%"))
            if _ok(tv) and tv > 0:
                rows.append((f"連動資金の{'買い' if kind == 'add' else '売り'}",
                             f"約{flow:,.0f}億円<br><span class='meta'>売買代金の{flow / tv:.1f}日分</span>"))
        dl = "".join(f"<dt>{a}</dt><dd>{b}</dd>" for a, b in rows)
        return (f'<div class="side {kind}"><span class="tag">{"採用" if kind == "add" else "除外"}</span>'
                f'<div class="nm">{_e(names.get(d.code, d.code))}</div><div class="cd2">{_e(d.code)}</div><dl>{dl}</dl></div>')

    out = ""
    for a, d in pairs:
        ref = a or d
        notes = " / ".join(_e(x.note) for x in (a, d) if x is not None and x.note)
        conf = min((x.confidence for x in (a, d) if x is not None), key=lambda c: CONF_N.get(c, 0))
        out += (f'<div class="card pair"><div class="rule"><div><b>{_e(key(ref))}</b> <span class="meta">{notes}</span></div>{_dots(conf)}</div>'
                f'{side(a, "add")}<div class="arrow">⇄</div>{side(d, "del")}</div>')
    return f'<div class="pairs">{out}</div>'


def _border(ctx):
    sim, rk, names = ctx["sim"], ctx["ranks"], ctx["names"]
    pred = {d.code for d in sim.decisions}
    excl = set(ctx["excl"]) if not isinstance(ctx["excl"], dict) else set(ctx["excl"].keys())
    passed = set(ctx["passed"])
    wt = ctx["wt"]
    # 採用に近い未採用
    nm = rk[~rk["member"] & rk["liq_rank"].notna()].copy()
    under = set(sim.add_candidates["code"]) if sim.add_candidates is not None else set()
    r3 = rk.set_index("code")["順位(3か月前)"]
    nm = nm[(nm["liq_rank"] <= 130) | nm["code"].isin(under)].sort_values("liq_rank").head(15)
    rows, up_items, dn_items = "", [], []
    for x in nm.itertuples():
        c = x.code
        chips = []
        if c in pred:
            chips.append('<span class="chip add">採用予想</span>')
        if c in excl:
            chips.append('<span class="chip mute">対象外</span>')
        if c in passed:
            chips.append('<span class="chip warn">前回見送り</span>')
        if x.liq_rank <= ABS_ADD and c not in excl and c not in passed and c not in pred:
            chips.append('<span class="chip warn">75位以内</span>')
        up_items.append((float(x.liq_rank), names.get(c, c), [re.sub(r"<[^>]+>", "", t) for t in chips], c in pred))
        rows += (f'<tr class="{"hl" if c in pred else ""}"><td class="nm">{_e(names.get(c, ""))}<div class="c">{_e(c)}・{_e(x.sector)}</div><div class="chips">{"".join(chips)}</div></td>'
                 f'<td class="n"><b>{x.liq_rank:.0f}</b></td><td class="rb">{_rankbar(x.liq_rank, "add")}</td>'
                 f'<td class="n">{_trend(x.liq_rank, r3.get(c, np.nan))}</td></tr>')
    t_add = (f'<div class="scroll"><table class="tbl"><tr><th>銘柄</th><th class="n">順位</th><th class="rb">位置<span class="dt">（1〜{RANK_MAX}位）</span></th>'
             f'<th class="n">3か月</th></tr>{rows}</table></div>')
    # 除外に近い採用銘柄
    dc = sim.del_candidates if sim.del_candidates is not None else pd.DataFrame()
    dc = dc.sort_values("liq_rank", ascending=False).head(12) if len(dc) else dc
    rows = ""
    for x in dc.itertuples():
        c = x.code
        chips = []
        if c in pred:
            chips.append('<span class="chip del">除外予想</span>')
        if x.liq_rank > HIGH_LIQ:
            chips.append('<span class="chip warn">451位以下</span>')
        try:
            low = int(dc.loc[c, "セクター内順位(下から)"])
        except Exception:  # noqa: BLE001
            low = None
        if low is not None and low <= 2:
            chips.append(f'<span class="chip" title="同じセクターの採用銘柄の中で、流動性が下から{low}番目">セクター下位{low}</span>')
        w = wt["ウエート(%)"].get(c, np.nan)
        dn_items.append((float(x.liq_rank), names.get(c, c), [re.sub(r"<[^>]+>", "", t) for t in chips], c in pred))
        rows += (f'<tr class="{"hl" if c in pred else ""}"><td class="nm">{_e(names.get(c, ""))}<div class="c">{_e(c)}・{_e(x.sector)}</div><div class="chips">{"".join(chips)}</div></td>'
                 f'<td class="n"><b>{x.liq_rank:.0f}</b></td><td class="rb">{_rankbar(x.liq_rank, "del")}</td>'
                 f'<td class="n">{_trend(x.liq_rank, r3.get(c, np.nan))}</td><td class="n mh">{_f(w, 2, unit="%")}</td></tr>')
    t_del = (f'<div class="scroll"><table class="tbl"><tr><th>銘柄</th><th class="n">順位</th><th class="rb">位置<span class="dt">（1〜{RANK_MAX}位）</span></th>'
             f'<th class="n">3か月</th><th class="n mh">ウエート</th></tr>{rows}</table></div>')
    legend = (f'<div class="legend"><span><i style="background:color-mix(in srgb,var(--add) 30%,transparent)"></i>1〜{ABS_ADD}位：未採用なら採用（絶対採用）</span>'
              f'<span><i style="background:color-mix(in srgb,var(--del) 30%,transparent)"></i>{HIGH_LIQ + 1}位〜：採用銘柄なら除外（絶対除外）</span>'
              f'<span>▲＝3か月で順位が上がった　▼＝下がった</span></div>')
    # 順位の物差し：左＝未採用の候補（1位〜）、右＝採用銘柄の下位（〜500位）。色の帯が絶対採用圏・絶対除外圏
    def half(title, note, items, lo, hi, z0, z1, kind, zl, zside):
        span = max(1, hi - lo)

        def X(r):
            return max(0.0, min(100.0, (r - lo) / span * 100))
        h = (f'<div class="rk-z rk-z{"a" if kind == "a" else "d"}" style="left:{X(z0):.2f}%;width:{X(z1) - X(z0):.2f}%"></div>'
             f'<span class="rk-zl" style="{zside}:0">{zl}</span>')
        for r, n, tags, key in items:
            h += f'<i class="rk-p {kind}{" key" if key else ""}" style="left:{X(r):.2f}%"></i>'
            if key:
                h += (f'<div class="rk-l" style="left:{X(r):.2f}%">{_e(n)} {r:.0f}位'
                      f'<small>{"採用予想" if kind == "a" else "除外予想"}</small></div>')
        ticks = sorted({lo, hi, z1 if kind == "a" else z0, int(round((lo + (z1 if kind == "a" else z0)) / 2, -1)),
                        int(round(((z1 if kind == "a" else z0) + hi) / 2, -1))})
        ticks = [t for t in ticks if lo <= t <= hi]
        h += "".join(f'<span class="rk-t" style="left:{X(t):.2f}%">{t}位</span>' for t in ticks)
        cs = "".join(f'<span class="rk-c{" key" if key else ""}"><b>{r:.0f}</b>{_e(n)}'
                     f'{"<small>" + _e("・".join(tags)) + "</small>" if tags else ""}</span>' for r, n, tags, key in items)
        return (f'<div class="rk-h"><div class="ph-n">{title}</div><div class="ph-t">{note}</div>'
                f'<div class="rk"><div class="rk-ax"></div>{h}</div><div class="rk-cs">{cs}</div></div>')
    ruler = ""
    if up_items or dn_items:
        hi_l = max(160, int(-(-max([r for r, *_ in up_items] + [1]) // 10) * 10))
        lo_r = min(320, int(min([r for r, *_ in dn_items] + [RANK_MAX]) // 10 * 10))
        hi_r = max(RANK_MAX, int(-(-max([r for r, *_ in dn_items] + [1]) // 10) * 10))
        ruler = ('<div class="card"><h3 style="margin:0 0 10px;color:var(--ink);font-weight:800">流動性順位の物差し '
                 '<span class="meta" style="font-weight:400">色の帯に近いほど、次回以降に入れ替わりやすい銘柄です</span></h3><div class="rk-2">'
                 + half("採用に近い未採用銘柄", f"{ABS_ADD}位以内に入ると「絶対採用」の対象", up_items, 1, hi_l, 1, ABS_ADD, "a", f"絶対採用圏（〜{ABS_ADD}位）", "left")
                 + half("除外に近い採用銘柄", f"{HIGH_LIQ + 1}位以下に落ちると「絶対除外」の対象", sorted(dn_items), lo_r, hi_r, HIGH_LIQ + 1, hi_r, "o",
                        f"絶対除外圏（{HIGH_LIQ + 1}位〜）", "right")
                 + '</div></div>')
    return f"""{ruler}
<details class="card" style="margin-top:12px"><summary>一覧表で見る（順位の位置・3か月の変化・ウエート）</summary>
<div class="rk-tbl">
 <div><h3>採用に近い未採用銘柄</h3>{t_add}</div>
 <div><h3>除外に近い採用銘柄</h3>{t_del}</div>
</div>{legend}
<p class="tip">「前回見送り」＝前回の見直しでこの近似では{ABS_ADD}位以内だったのに採用されなかった銘柄。日経の実際の順位では届いていないとみなし、絶対採用の扱いにしていません。
「対象外」＝特別注意銘柄など（日経225/data/exclude.csv）。</p></details>"""


def _sectors(ctx):
    st, secw = ctx["sim"].sector_table, ctx["secw"]
    mx = max(1.0, float(st[["過不足(見直し前)", "過不足(予想後)"]].abs().max().max()))
    wmax = float(secw["ウエート(%)"].max()) if len(secw) else 1
    rows = ('<div class="h">セクター</div><div class="h n cnt">採用 / 妥当数</div><div class="h" style="text-align:center"><span class="dt2">← 不足（採用が出やすい）　過剰（除外が出やすい）→</span><span class="mob">← 不足　｜　過剰 →</span></div>'
            '<div class="h n">過不足</div><div class="h wcol">指数ウエート</div>')
    for s, r in st.iterrows():
        v0, v1 = float(r["過不足(見直し前)"]), float(r["過不足(予想後)"])
        w0 = abs(v0) / mx * 50
        left = 50 if v0 >= 0 else 50 - w0
        col = "var(--add)" if v0 < 0 else "var(--del)"
        ghost = ""
        if abs(v1 - v0) > 1e-9:
            w1 = abs(v1) / mx * 50
            l1 = 50 if v1 >= 0 else 50 - w1
            ghost = f'<span class="g" style="left:{l1:.1f}%;width:{w1:.1f}%" title="予想後 {v1:+.1f}"></span>'
        w = float(secw["ウエート(%)"].get(s, np.nan)) if s in secw.index else np.nan
        sc = SECTOR_COLORS.get(s, "--c7")
        chg = f' <span class="meta" title="予想どおり入れ替えた後">→ {v1:+.1f}</span>' if abs(v1 - v0) > 1e-9 else ""
        rows += (f'<div><span class="sw" style="background:var({sc})"></span>{_e(s)}<div class="mob meta">採用 {r["見直し前"]:.0f} / 妥当 {r["採用妥当数"]:.1f}</div></div>'
                 f'<div class="n cnt">{r["見直し前"]:.0f} / {r["採用妥当数"]:.1f}</div>'
                 f'<div class="dv" title="{_e(s)}：高流動性 {r["高流動性銘柄数"]:.0f}銘柄 → 採用妥当数 {r["採用妥当数"]:.1f}"><span class="m"></span>'
                 f'<span class="b" style="left:{left:.1f}%;width:{w0:.1f}%;background:{col}"></span>{ghost}</div>'
                 f'<div class="n"><b>{v0:+.1f}</b>{chg}</div>'
                 f'<div class="wcol" style="display:flex;align-items:center;gap:6px"><div class="wbar" style="width:{(w / wmax * 100) if _ok(w) else 0:.0f}%;background:var({sc})"></div>'
                 f'<span class="meta">{_f(w, 1, unit="%")}</span></div>')
    return f"""<div class="card"><div class="sec">{rows}</div>
<p class="tip">採用妥当数＝流動性上位{HIGH_LIQ}銘柄のうち、そのセクターの銘柄数の半分。採用数がこれより多い（右・緑）セクターからは除外、少ない（左・赤）セクターには採用が出やすくなります。点線の枠は予想どおり入れ替えた後。</p></div>"""


def _weights(ctx):
    wt, secw, capw, names = ctx["wt"], ctx["secw"], ctx["capw"], ctx["names"]
    # セクター構成の100%積み上げ
    sw = secw.sort_values("ウエート(%)", ascending=False)
    stack = "".join(f'<span style="width:{r["ウエート(%)"]:.2f}%;background:var({SECTOR_COLORS.get(s, "--c7")})" '
                    f'title="{_e(s)} {r["ウエート(%)"]:.1f}%（{r["銘柄数"]:.0f}銘柄）">{_e(s) if r["ウエート(%)"] > 7 else ""}</span>'
                    for s, r in sw.iterrows())
    leg = "".join(f'<span><i style="background:var({SECTOR_COLORS.get(s, "--c7")})"></i>{_e(s)} {r["ウエート(%)"]:.1f}%</span>'
                  for s, r in sw.iterrows())
    # 上位15
    top = wt.head(15)
    scale = max(13.0, float(top["ウエート(%)"].max()) * 1.05)
    capx = 10 / scale * 100
    wl = ""
    for c, r in top.iterrows():
        w = float(r["ウエート(%)"])
        col = "var(--bad)" if w > 10 else f'var({SECTOR_COLORS.get(r["セクター"], "--c7")})'
        wl += (f'<div class="nm" title="{_e(c)} {_e(r["業種"])}">{_e(r["銘柄名"])}</div><div class="tr"><div class="b" style="width:{w / scale * 100:.1f}%;background:{col}"></div>'
               f'<span class="cap" style="left:{capx:.1f}%"></span></div><div class="n">{w:.2f}%</div>')
    # キャップ
    cap_h = ""
    for _, r in capw.iterrows():
        act = str(r.iloc[3])
        nm = names.get(r["コード"], r["コード"])
        if "引き下げ" in act:
            cap_h += (f'<div class="alertbox"><div class="ic">⚠</div><div><b>{_e(nm)}　ウエート {r["ウエート(%)"]:.2f}%（10%超）</b><br>'
                      f'次の基準日（{ctx["nxt"]["base"]:%Y/%-m/%-d}）にこの水準のままなら、キャップ調整比率が {r.iloc[2]:.1f} → {_e(act.split("→")[-1].strip())} に下がり、'
                      f'指数連動の売りが出ます。</div></div>')
        else:
            cap_h += (f'<p class="tip">{_e(nm)}：ウエート {r["ウエート(%)"]:.2f}%・キャップ調整比率 {r.iloc[2]:.1f}（10%まで {r.iloc[4]:.1f}pt）→ {_e(act)}</p>')
    # 寄与度データ（JS）
    cols = {"1日": "寄与度1日(円)", "5日": "寄与度5日(円)", "20日": "寄与度20日(円)", "年初来": "寄与度年初来(円)"}
    cdata = [{"n": str(r["銘柄名"]), **{k: (round(float(r[v]), 1) if _ok(r[v]) else 0) for k, v in cols.items()}}
             for _, r in wt.iterrows()]
    return f"""
<div class="card"><h3>セクター別のウエート（指数の何%を占めるか）</h3><div class="stack">{stack}</div><div class="legend">{leg}</div></div>
<div class="grid2" style="margin-top:14px">
 <div class="card"><h3>ウエート上位15銘柄 <span class="meta">赤の点線＝10%（キャップ）</span></h3><div class="wl">{wl}</div>{cap_h}</div>
 <div class="card"><div class="sh" style="margin-bottom:0"><h3 style="margin:0">日経平均への寄与度</h3>
  <div class="seg" id="cseg">{''.join(f'<button data-k="{k}"{" class=on" if k == "1日" else ""}>{k}</button>' for k in cols)}</div></div>
  <div class="meta" id="csum" style="margin-top:6px"></div><div class="cb" id="cb"></div>
  <p class="tip">寄与度＝株価換算係数×株価の変化÷除数（円）。</p></div>
</div>
<div class="card" style="margin-top:14px"><h3>上位5銘柄のウエート推移（1年）</h3><div class="chartbox"><canvas id="wh" role="img" aria-label="上位5銘柄のウエート推移"></canvas></div></div>
""", cdata


def _backtest(ctx):
    bt, names = ctx["bt"], ctx["names"]
    if not bt:
        return "", None
    h = bt["hit"]
    es = bt["event_summary"]
    phases = [c for c in es.columns if c != "基準日→実施前日"]
    short = {"基準日→発表日": "基準日→発表", "発表翌日（発表日→翌営業日）": "発表翌日", "発表翌日→実施前日": "発表後→実施前日",
             "実施前日→実施後20日": "実施後20日"}

    def cell(stat, kind, col):
        try:
            v = es.loc[(stat, kind), col]
            return None if not _ok(v) else round(float(v), 2)
        except KeyError:
            return None
    short2 = {"基準日→発表日": ["基準日", "→発表"], "発表翌日（発表日→翌営業日）": ["発表", "翌日"],
              "発表翌日→実施前日": ["発表後", "→実施前日"], "実施前日→実施後20日": ["実施後", "20日"]}
    edata = {"labels": [short2.get(c, c) for c in phases],
             "mean": {k: [cell("平均(%)", k, c) for c in phases] for k in ("採用", "除外")},
             "median": {k: [cell("中央値(%)", k, c) for c in phases] for k in ("採用", "除外")},
             "pos": {k: [cell("プラスの割合(%)", k, c) for c in phases] for k in ("採用", "除外")}}
    # 売買ルール
    st_ = bt["strategy"]
    strat_cards = ""
    if len(st_):
        for side, g in sorted(st_.groupby("売買"), key=lambda t: 0 if str(t[0]).startswith("買い") else 1):
            v = g["実施前日まで(%)"].dropna()
            win = (v > 0).mean() * 100 if len(v) else np.nan
            good = v.mean() > 0
            col = "--up" if good else "--dn"
            strat_cards += (f'<div class="card kpi"><div class="k">{_e(side)}</div><div class="big2" style="color:var({col})">{_f(v.mean(), 1, sign=True, unit="%")}</div>'
                            f'<div class="s">平均（中央値 {_f(v.median(), 1, sign=True, unit="%")}・勝率 {_f(win, 0, unit="%")}・{len(v)}件）</div>'
                            f'<div class="meter"><span style="width:{win if _ok(win) else 0:.0f}%;"></span></div></div>')
    hit_cards = ""
    for k in ("採用", "除外"):
        a, n, p = h[k]
        hit_cards += (f'<div class="card kpi"><div class="k">{k}の的中（再現テスト）</div><div class="big2">{a}<span class="meta" style="font-size:14px"> / {n}</span></div>'
                      f'<div class="s">実際の{k}{n}銘柄のうち、予想していた数（予想は{p}銘柄）</div><div class="meter"><span style="width:{a / max(n, 1) * 100:.0f}%"></span></div></div>')
    # 使い方（数字はデータから）
    a_bp = cell("平均(%)", "採用", "基準日→実施前日")
    a_after = cell("中央値(%)", "採用", "実施前日→実施後20日")
    d_mid = cell("平均(%)", "除外", "発表翌日→実施前日")
    buy = st_[st_["売買"].str.startswith("買い")]["実施前日まで(%)"] if len(st_) else pd.Series(dtype=float)
    sell = st_[st_["売買"].str.startswith("売り")]["実施前日まで(%)"] if len(st_) else pd.Series(dtype=float)
    how = f"""<div class="how"><b>過去の検証から言えること（対TOPIXの超過リターン）</b><ul>
<li>採用銘柄は<b>基準日→実施前日</b>に平均 {_f(a_bp, 1, sign=True, unit="%")}。ただし<b>実施後20日</b>は中央値 {_f(a_after, 1, sign=True, unit="%")} と反落しやすい。</li>
<li>予想採用を基準日の翌営業日に買い、当たれば実施前日・外れたら発表翌日に手じまう → 平均 {_f(buy.mean(), 1, sign=True, unit="%")}（{len(buy)}件）。</li>
<li>予想除外の空売りは平均 {_f(sell.mean() if len(sell) else np.nan, 1, sign=True, unit="%")}（{len(sell)}件）{"で、有効ではありませんでした" if len(sell) and sell.mean() < 0 else ""}。除外銘柄も発表後〜実施前日は平均 {_f(d_mid, 1, sign=True, unit="%")} とむしろ上がりやすい。</li>
</ul></div>"""
    # 回ごとの再現テスト
    rep = bt["replay"]

    def hit(s):
        try:
            a, n = str(s).split("/")
            cls = "full" if a == n else ("zero" if a == "0" else "part")
        except ValueError:
            cls = ""
        return f'<span class="hit {cls}">{_e(s)}</span>'

    def lst(s):
        return "<br>".join(_e(x.strip()) for x in str(s).split("、") if x.strip()) or "－"
    rr = "".join(f'<tr><td class="n">{_e(r["実施日"])}</td><td>{lst(r["実際の採用"])}</td><td>{lst(r["予想の採用"])}</td><td class="n">{hit(r["採用の的中"])}</td>'
                 f'<td>{lst(r["実際の除外"])}</td><td>{lst(r["予想の除外"])}</td><td class="n">{hit(r["除外の的中"])}</td></tr>'
                 for _, r in rep.iloc[::-1].iterrows())
    html_ = f"""
<div class="grid4">{hit_cards}{strat_cards}</div>
<div class="grid2" style="margin-top:14px">
 <div class="card"><div class="sh" style="margin-bottom:6px"><h3 style="margin:0">採用・除外銘柄の値動き（局面ごと・対TOPIX）</h3>
  <div class="seg" id="eseg"><button data-k="median" class="on">中央値</button><button data-k="mean">平均</button></div></div>
  <div class="chartbox"><canvas id="ev" role="img" aria-label="局面ごとの超過リターン"></canvas></div>
  <p class="tip">発表は大引け後なので「発表翌日」が発表への反応。指数連動ファンドは実施日の前営業日の大引けで売買します。</p></div>
 <div class="card">{how}</div>
</div>
<details class="card" style="margin-top:14px"><summary>回ごとの再現テスト（基準日までの株価だけで予想した場合）</summary>
<div class="scroll" style="margin-top:10px"><table class="tbl"><tr><th class="n">実施日</th><th>実際の採用</th><th>予想の採用</th><th class="n">的中</th><th>実際の除外</th><th>予想の除外</th><th class="n">的中</th></tr>{rr}</table></div></details>"""
    return html_, edata


JS = r"""
(function(){
const cs=getComputedStyle(document.documentElement),V=n=>cs.getPropertyValue(n).trim();
const fmt=v=>(v>0?'+':v<0?'−':'')+Math.abs(Math.round(v)).toLocaleString()+'円';
/* 寄与度 */
const C=__CDATA__;
function drawC(k){
  const arr=C.slice().sort((a,b)=>b[k]-a[k]);
  const up=arr.filter(x=>x[k]>0).slice(0,8), dn=arr.filter(x=>x[k]<0).reverse().slice(0,8);
  const mx=Math.max(1,...up.map(x=>x[k]),...dn.map(x=>-x[k]));
  const tot=C.reduce((s,x)=>s+x[k],0);
  document.getElementById('csum').textContent='全225銘柄の合計 '+fmt(tot)+'（'+k+'）';
  const blk=(t,xs,col)=>'<div class="cl"><h4 style="color:var('+col+')">'+t+'</h4>'+(xs.length?xs.map(x=>'<div class="rw"><span class="nm">'+x.n+'</span><span class="v" style="color:var('+col+')">'+fmt(x[k])+'</span><div class="tr"><span style="width:'+(Math.abs(x[k])/mx*100).toFixed(1)+'%;background:var('+col+')"></span></div></div>').join(''):'<div class="meta">なし</div>')+'</div>';
  const h=blk('押し上げ 上位8',up,'--up')+blk('押し下げ 上位8',dn,'--dn');
  document.getElementById('cb').innerHTML=h;
}
function seg(id,fn){const el=document.getElementById(id);if(!el)return;el.addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;
  el.querySelectorAll('button').forEach(x=>x.classList.toggle('on',x===b));fn(b.dataset.k);});}
drawC('1日');seg('cseg',drawC);
if(!window.Chart)return;
Chart.defaults.font.family=getComputedStyle(document.body).fontFamily;Chart.defaults.color=V('--muted');
/* ウエート推移 */
const W=__WDATA__;const pal=['--c1','--c3','--c4','--c2','--c5'].map(V);
const ds=W.series.map((s,i)=>({label:s.label,data:s.data,borderColor:pal[i],backgroundColor:pal[i],borderWidth:2,pointRadius:0,tension:.2}));
ds.push({label:'キャップ 10%',data:W.labels.map(()=>10),borderColor:V('--bad'),borderDash:[5,4],borderWidth:1.5,pointRadius:0,fill:false});
new Chart(document.getElementById('wh'),{type:'line',data:{labels:W.labels,datasets:ds},
 options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},
 plugins:{legend:{position:'bottom',labels:{boxWidth:10,boxHeight:10,color:V('--ink2')}},tooltip:{callbacks:{label:c=>c.dataset.label+' '+(c.parsed.y==null?'-':c.parsed.y.toFixed(2))+'%'}}},
 scales:{x:{ticks:{maxTicksLimit:innerWidth<520?4:7,maxRotation:0},grid:{display:false}},y:{ticks:{callback:v=>v+'%'},grid:{color:V('--grid')}}}}});
/* イベント */
const E=__EDATA__;if(!E)return;
const ec=new Chart(document.getElementById('ev'),{type:'bar',data:{labels:E.labels,datasets:[
 {label:'採用',data:E.median['採用'],backgroundColor:V('--add'),borderRadius:4},
 {label:'除外',data:E.median['除外'],backgroundColor:V('--del'),borderRadius:4}]},
 options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'bottom',labels:{boxWidth:10,boxHeight:10,color:V('--ink2')}},
  tooltip:{callbacks:{label:c=>c.dataset.label+' '+(c.parsed.y>0?'+':'')+c.parsed.y.toFixed(1)+'%（プラスの割合 '+(E.pos[c.dataset.label][c.dataIndex]??'-')+'%）'}}},
  scales:{x:{grid:{display:false},ticks:{maxRotation:0,autoSkip:false}},y:{ticks:{callback:v=>v+'%'},grid:{color:c=>c.tick.value===0?V('--muted'):V('--grid')}}}}});
seg('eseg',k=>{ec.data.datasets[0].data=E[k]['採用'];ec.data.datasets[1].data=E[k]['除外'];ec.update();});
})();
"""


# ---------------------------------------------------------------- 本体
def write_html(path, ctx) -> None:
    sim, nxt, names = ctx["sim"], ctx["nxt"], ctx["names"]
    adds = [d for d in sim.decisions if d.action == "採用"]
    dels = [d for d in sim.decisions if d.action == "除外"]

    weights_h, cdata = _weights(ctx)
    bt_h, edata = _backtest(ctx)
    wh = ctx["whist"]
    wdata = {"labels": [d.strftime("%Y-%m-%d") for d in wh.index],
             "series": [{"label": names.get(c, c), "data": [None if not _ok(v) else round(float(v), 3) for v in wh[c]]}
                        for c in wh.columns[:5]]}
    js = (JS.replace("__CDATA__", json.dumps(cdata, ensure_ascii=False))
            .replace("__WDATA__", json.dumps(wdata, ensure_ascii=False))
            .replace("__EDATA__", json.dumps(edata, ensure_ascii=False)))
    nav = [("pred", "入れ替え予想"), ("phase", "日程と値動き"), ("border", "ボーダーライン"), ("sector", "セクター"), ("weight", "ウエート・寄与度")]
    if bt_h:
        nav.append(("bt", "過去の検証"))
    nav_h = "".join(f'<a href="#{a}">{b}</a>' for a, b in nav)
    rules = (f"① 東証プライムを「過去5年の売買代金」と「売買代金当たりの価格変動率」で順位付けし、上位{HIGH_LIQ}を高流動性銘柄群とする。"
             f"② 採用銘柄で{HIGH_LIQ + 1}位以下は除外、未採用で{ABS_ADD}位以内は採用。③ 7セクターごとに高流動性銘柄の半数を採用妥当数とし、過不足を調整。"
             f"④ 同じセクター内で既採用の最下位と未採用の最上位の順位差が大きければ入れ替え。⑤ 1回3銘柄まで。"
             f"日経は2指標の合成方法を公表していないため、順位は「終値×出来高の1日平均」と「(高値÷安値−1)の平均÷売買代金」の順位の和で近似しています。")
    page = f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>日経225 入れ替え予想</title><style>{CSS}</style></head><body>
<div class="top"><div class="in"><h1><a href="./index.html" title="トップへ">‹</a>日経225 入れ替え予想・ウエート分析</h1><nav>{nav_h}</nav></div></div>
<div class="wrap">
<section id="pred" style="margin-top:14px">
{_board(ctx, adds, dels)}
<details class="card" style="margin-top:12px"><summary>日経の選定ルールと、このページの計算のしかた</summary><p class="tip" style="font-size:13px;color:var(--ink2)">{rules}</p></details>
</section>
{_phases(ctx)}
<section id="border"><div class="sh"><h2>ボーダーライン</h2><span class="meta">流動性順位（{ctx['asof']:%Y/%-m/%-d}時点）</span></div>{_border(ctx)}</section>
<section id="sector"><div class="sh"><h2>セクターの過不足</h2><span class="meta">採用数 − 採用妥当数</span></div>{_sectors(ctx)}</section>
<section id="weight"><div class="sh"><h2>ウエートと寄与度</h2><span class="meta">{ctx['last_day']:%Y/%-m/%-d} 終値</span></div>{_kpis(ctx, adds, dels)}{weights_h}</section>
{f'<section id="bt"><div class="sh"><h2>過去の検証</h2><span class="meta">2023年4月以降の定期見直し</span></div>{bt_h}</section>' if bt_h else ''}
<footer>株価 {ctx['last_day']:%Y-%m-%d} まで・作成 {ctx['today']}・データ：日経平均プロフィル（構成銘柄・お知らせ・除数）、株価CSV。
日経平均 ＝ Σ（株価×株価換算係数）÷ 除数（{ctx['D']:.6f}）。連動資金は日経平均連動の運用資産を{float(ctx['aum']):.0f}兆円と仮定（Excelの「需給インパクト」で変更可）。<br>
投資判断はご自身で。日経の公表ルールからの推定で、日経の公式予想ではありません。詳細は Excel（日経225/output）。</footer>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<script>{js}</script>
</body></html>"""
    path.write_text(page, encoding="utf-8")
