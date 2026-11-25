# -*- coding: utf-8 -*-
"""
html_dashboard.py — ドル円 金利差モデルの結果を「1画面で見渡せるダッシュボード」にする

usdjpy_model.py から呼ばれます（--html を付けたとき。--layout classic で従来ページ）。

  ・外部への通信ゼロ（フォント・ライブラリも読みに行かない）。1ファイルで完結
  ・グラフはページ内のJavaScriptでSVGを描く。ホバー／タップで数値が出る
  ・方向性スコアとイベント・シナリオは、ページ上のスライダーで動かせる
    （usdjpy_model.py と同じ式をJavaScriptで再現。初期値は main() の設定値）
  ・スマホ対応・ダークモード対応（端末設定に追従＋手動切替）

色の約束は従来ページと同じ: 赤＝円安方向、青＝円高方向。
"""
from __future__ import annotations

import html
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import html_report as _hr   # 読み込み関数（policy.json / us_macro.csv / usdjpy_ohlc.csv）を共用

JST = timezone(timedelta(hours=9))
DAYS_KEEP = 520            # 埋め込む履歴（営業日）。≒2年
MACRO_KEEP = 24            # CPI・雇用統計の月数
CANDLE_YEARS = 2           # 01 のローソク足の期間（年）。期間ボタンに関係なく固定


def _now() -> datetime:
    return datetime.now(JST)


def _r(x, nd=3):
    """JSONに入れる数値。NaN・None は null にする。"""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, nd) if math.isfinite(v) else None


def _passthrough(grid: pd.DataFrame, default=0.70) -> float:
    """scenario_grid の結果から『2年債への伝わり方』を逆算する（定数の二重管理を避ける）。"""
    try:
        for _, r in grid.iterrows():
            s = r["米サプライズ(pt)"] - r["日サプライズ(pt)"]
            if abs(s) > 1e-6:
                return round(float(r["金利差の変化(pt)"]) / s, 4)
    except Exception:
        pass
    return default


def _events(policy, macro, today: str) -> list[dict]:
    """これから来るイベント（会合・CPI・雇用統計）を日付順に並べる。"""
    ev = []
    if policy:
        for m in policy.get("meetings", []):
            if m.get("end", m["date"]) >= today:
                ev.append({"date": m["date"], "end": m.get("end", m["date"]),
                           "kind": "fomc" if m["who"] == "FOMC" else "boj",
                           "label": m["who"] if m["who"] == "FOMC" else "日銀会合",
                           "note": m.get("note") or ""})
    if macro is not None:
        for _, r in macro.iterrows():
            ref = f"{r['date']:%-m}月分"
            for col, kind, lab in (("cpi_release", "cpi", "米CPI"),
                                   ("jobs_release", "jobs", "米雇用統計")):
                d = r.get(col)
                if pd.notna(d) and f"{d:%Y-%m-%d}" >= today:
                    ev.append({"date": f"{d:%Y-%m-%d}", "end": f"{d:%Y-%m-%d}",
                               "kind": kind, "label": lab, "note": ref})
    ev.sort(key=lambda e: e["date"])
    return ev[:8]


def _payload(df, sens, bt, grid, score, args, score_items):
    ohlc = _hr.load_ohlc(getattr(args, "csv", None))
    macro = _hr.load_macro(getattr(args, "csv", None))
    policy = _hr.load_policy(getattr(args, "csv", None))

    d = df.tail(DAYS_KEEP).copy()
    ser = {
        "date": [f"{t:%Y-%m-%d}" for t in d["date"]],
        "close": [_r(v) for v in d["usdjpy"]],
        "fair": [_r(v) for v in d["fair"]],
        "sd": [_r(v) for v in d["resid_sd"]],
        "z": [_r(v) for v in d["z"]],
        "s2": [_r(v) for v in d["spread2"]],
        "s10": [_r(v) for v in d["spread10"]] if "spread10" in d else [],
        "vix": [_r(v, 2) for v in d["vix"]] if "vix" in d else [],
    }

    # ローソク足: 四本値の日付を軸にし、フェアバリューは直近の値を3日まで繰り越す
    # （data.csv は FRED の都合で1〜2営業日遅れるため）
    px = None
    if ohlc is not None and len(ohlc):
        start = ohlc["date"].iloc[-1] - pd.DateOffset(years=CANDLE_YEARS)
        o = ohlc[ohlc["date"] > start].copy()
        cols = ["date", "fair", "resid_sd", "spread2"] + (["spread10"] if "spread10" in df else [])
        fv = df[cols].set_index("date")
        o = o.set_index("date").join(fv, how="left")
        o[cols[1:]] = o[cols[1:]].ffill(limit=3)
        o = o.reset_index()
        px = {
            "date": [f"{t:%Y-%m-%d}" for t in o["date"]],
            "o": [_r(v) for v in o["open"]], "h": [_r(v) for v in o["high"]],
            "l": [_r(v) for v in o["low"]], "c": [_r(v) for v in o["close"]],
            "fair": [_r(v) for v in o["fair"]], "sd": [_r(v) for v in o["resid_sd"]],
            "s2": [_r(v) for v in o["spread2"]],
            "s10": [_r(v) for v in o["spread10"]] if "spread10" in o else [],
        }

    mac = None
    if macro is not None and len(macro):
        m = macro.dropna(subset=["cpi_yoy", "payrolls_chg"], how="all").tail(MACRO_KEEP)
        mac = {
            "date": [f"{t:%Y-%m}" for t in m["date"]],
            "cpi": [_r(v, 2) for v in m["cpi_yoy"]],
            "core": [_r(v, 2) for v in m["core_cpi_yoy"]],
            "pay": [_r(v, 0) for v in m["payrolls_chg"]],
            "unemp": [_r(v, 1) for v in m["unemp"]],
        }

    spot = float(args.spot) if getattr(args, "spot", None) else float(sens["spot"])
    ols = sens["ols"]
    btd = None
    if bt.get("ok"):
        btd = {"h": bt["horizon"], "n": bt["n"], "hit": _r(bt["hit_rate"], 4),
               "beta": _r(bt["full"].beta, 4), "r2": _r(bt["full"].r2, 4),
               "rm": _r(bt["rmse_model"], 4), "rw": _r(bt["rmse_rw"], 4),
               "ratio": _r(bt["ratio"], 4), "nt": bt["n_test"]}

    return {
        "ser": ser, "px": px, "mac": mac, "policy": policy, "bt": btd,
        "spot": spot, "beta": _r(sens["pct_per_pt"], 5), "r2": _r(ols.r2, 4),
        "pass": _passthrough(grid), "step": float((policy or {}).get("step", 0.25)),
        "pF": float(getattr(args, "p_fomc_hike", 0.55)),
        "pB": float(getattr(args, "p_boj_hike", 0.60)),
        "items": [{"name": n, "w": w, "note": note,
                   "v": float(args.score_inputs.get(n, 0))} for n, w, note in score_items],
        "exc": float(score.get("exception_factor", 1.0)),
        "today": f"{_now():%Y-%m-%d}",
    }, ohlc, macro, policy


# ------------------------------------------------------------------------------
# サーバー側で組み立てる部分（数字が確定しているもの）
# ------------------------------------------------------------------------------

def _kpis(df, sens, args, spot, px) -> str:
    d = df.dropna(subset=["fair"])
    last = d.iloc[-1]
    s2 = df["spread2"]
    ds2 = float(s2.iloc[-1] - s2.iloc[-21]) if len(s2) > 21 else float("nan")

    if getattr(args, "spot", None):
        asof = getattr(args, "spot_asof", None) or f"{_now():%Y-%m-%d %H:%M} JST"
        spot_sub = f"{asof} 時点"
    else:
        spot_sub = f"{df['date'].iloc[-1]:%Y-%m-%d} 終値"
    chg = ""
    if px and len(px["c"]) >= 2 and px["c"][-2]:
        dd = spot - px["c"][-2]
        chg = (f'<span class="dl {"up" if dd > 0 else "dn" if dd < 0 else ""}">'
               f'{"▲" if dd > 0 else "▼" if dd < 0 else "—"} {abs(dd):.2f}</span>')

    z = float(last["z"])
    zcls = "up" if z >= 1 else "dn" if z <= -1 else ""
    vix = float(df["vix"].dropna().iloc[-1]) if "vix" in df and df["vix"].notna().any() else None

    def tile(label, val, sub, cls="", extra="", tid=""):
        idattr = f' id="{tid}"' if tid else ""
        return (f'<div class="kpi {cls}"{idattr}><div class="kl">{label}</div>'
                f'<div class="kv">{val}{extra}</div><div class="ks">{sub}</div></div>')

    # 2026-11 デザイン刷新：最上部に「実勢（特大）」と「いまの結論（水準・方向・次のイベント）」、その下に補助の数字
    t = [
        tile("フェアバリュー", f"{last['fair']:.2f}",
             f"{last['date']:%-m/%-d} 時点・金利差から見た妥当水準"),
        tile("日米2年金利差", f"{s2.iloc[-1]:.2f}<small>pt</small>",
             f"20営業日で {ds2:+.2f}pt" if math.isfinite(ds2) else "米2年 − 日2年"),
        tile("金利感応度", f"{sens['pct_per_pt']:+.2f}<small>%/pt</small>",
             f"10bp ≒ {sens['yen_per_10bp']:+.2f}円・R² {sens['ols'].r2:.2f}"),
    ]
    if vix is not None:
        vcls = "warnc" if vix >= 25 else ""
        t.append(tile("VIX（恐怖指数）", f"{vix:.1f}",
                      "25超はリスクオフ警戒" if vix < 25 else "リスクオフ警戒圏", vcls))
    az = abs(z)
    lvl = "金利差どおり（ほぼ妥当）" if az < 1 else ("やや" if az < 2 else "") + ("円安" if z > 0 else "円高") + "に行き過ぎ"
    lc = "" if az < 1 else ("up" if z > 0 else "dn")
    resid = float(last["resid"])
    return (f'<div class="hero"><div class="hcard"><div class="hk">ドル円<span>実勢</span></div>'
            f'<div class="hbig">{spot:.2f}{chg}</div><div class="hsub">{html.escape(spot_sub)}</div></div>'
            f'<div class="hcard"><div class="hk">いまの結論</div><div class="con">'
            f'<div><span class="cl">水準</span><b class="{lc}">{lvl}</b>'
            f'<small>金利差から見た妥当水準 <b>{last["fair"]:.2f}</b> より <b>{resid:+.2f}円</b>（{z:+.2f}σ・{"円安" if z > 0 else "円高"}側）</small></div>'
            f'<div id="kpiScore"><span class="cl">方向</span><b id="kVerdict">—</b>'
            f'<small>方向性スコア <b id="kScore">—</b>（−100 円高 〜 +100 円安）</small></div>'
            f'<div><span class="cl">次のイベント</span><b id="kNext">—</b><small id="kNextS"></small></div>'
            f'</div></div></div><div class="ktiles">{"".join(t)}</div>')


def _zcard(df) -> str:
    d = df.dropna(subset=["z"])
    z = float(d["z"].iloc[-1])
    z20 = float(d["z"].iloc[-21]) if len(d) > 21 else None
    sgn = np.sign(d["z"].values)
    run = 1
    for i in range(len(sgn) - 2, -1, -1):
        if sgn[i] == sgn[-1]:
            run += 1
        else:
            break

    if abs(z) >= 2:
        msg = ("金利差では説明できないほど<strong>行き過ぎ</strong>ています。"
               "ただし何か月も張り付くなら『金利差以外の力（介入・構造的な円売り）』のサインです。")
    elif abs(z) >= 1:
        msg = "やや乖離していますが、統計的には<strong>ふつうの範囲</strong>です。"
    else:
        msg = "実勢は<strong>金利差でおおむね説明できる水準</strong>にあります。"
    side = "割高（円安）" if z > 0 else "割安（円高）"
    return f"""
      <div class="zbox" data-z="{z:.3f}" data-z20="{'' if z20 is None else f'{z20:.3f}'}">
        <div class="zbig"><span class="{ 'up' if z > 0 else 'dn' }">{z:+.2f}</span><small>σ</small></div>
        <div class="zmeter" id="zmeter"></div>
        <p class="zmsg">{msg}</p>
        <ul class="facts">
          <li><span>乖離の向き</span><b>{side}側に {run}営業日</b></li>
          <li><span>20営業日前</span><b>{'—' if z20 is None else f'{z20:+.2f}σ'}</b></li>
        </ul>
      </div>"""


def _policy_card(pol, sens, spot) -> str:
    if not pol:
        return '<p class="muted">policy.json がないため表示できません。</p>'
    step = float(pol.get("step", 0.25))
    us, jp = pol["us"], pol["jp"]

    def imp(c, k):
        chg = float(c[k]) - float(c["policy_rate"])
        return chg, chg / step
    u1, u1n = imp(us, "y1"); j1, j1n = imp(jp, "y1")
    u2, u2n = imp(us, "y2"); j2, j2n = imp(jp, "y2")
    pct = sens["pct_per_pt"]
    y1 = spot * pct * (u1 - j1) / 100
    y2 = spot * pct * (u2 - j2) / 100
    mx = max(abs(u1n), abs(j1n), abs(u2n), abs(j2n), 1.0)

    def bar(n):
        w = min(abs(n) / mx * 50, 50)
        side = "r" if n >= 0 else "l"
        return (f'<div class="pbar"><i class="{side}" style="width:{w:.1f}%"></i>'
                f'<em></em></div>')

    def row(c, p, n, p2, n2):
        rng = f'（誘導 {c["target_range"]}）' if c.get("target_range") else ""
        return f"""<tr><th scope="row">{c['name']}<small>{c['policy_rate']:.2f}%{rng}</small></th>
          <td>{bar(n)}<span class="num">{n:+.1f}回<small>{p:+.2f}pt</small></span></td>
          <td>{bar(n2)}<span class="num">{n2:+.1f}回<small>{p2:+.2f}pt</small></span></td></tr>"""

    return f"""
      <table class="ptab">
        <thead><tr><th></th><th>今後1年の織り込み</th><th>今後2年の織り込み</th></tr></thead>
        <tbody>
          {row(us, u1, u1n, u2, u2n)}
          {row(jp, j1, j1n, j2, j2n)}
          <tr class="sum"><th scope="row">ドル円への含意</th>
            <td><span class="num {'up' if y1 > 0 else 'dn'}">{y1:+.2f}円</span></td>
            <td><span class="num {'up' if y2 > 0 else 'dn'}">{y2:+.2f}円</span></td></tr>
        </tbody>
      </table>
      <p class="cap">「回」＝0.25%の利上げ何回ぶんか（1年債・2年債 − 今の翌日物金利 で推計）。
      含意は「織り込みどおりに進んだとき金利差だけで説明できる変化幅」。
      会合ごとの確率ではなく期間全体の平均です。</p>"""


def _macro_card(macro) -> str:
    if macro is None or not len(macro):
        return '<p class="muted">us_macro.csv がないため表示できません。</p>'
    out = []

    def diff_cell(a, f, fmt, inv=False):
        if pd.isna(a) or pd.isna(f):
            return '<td class="muted">—</td>'
        nd = 0 if "0f" in fmt else (2 if ".2f" in fmt else 1)
        dv = round(float(a), nd) - float(f)
        good = dv > 0 if not inv else dv < 0
        cls = "" if abs(dv) < 1e-6 else ("up" if good else "dn")
        if abs(dv) < 1e-6:
            dv = 0.0
        return f'<td class="{cls}">{fmt.format(dv)}</td>'

    c = macro.dropna(subset=["cpi_yoy"])
    j = macro.dropna(subset=["payrolls_chg"])
    rows = []
    if len(c):
        r = c.iloc[-1]
        lab = f"{r['date']:%-m}月分"
        for name, a, f, fmt, dfmt in (("CPI 総合 前年比", "cpi_yoy", "cpi_yoy_f", "{:.1f}%", "{:+.1f}"),
                                      ("CPI コア 前年比", "core_cpi_yoy", "core_cpi_yoy_f", "{:.1f}%", "{:+.1f}"),
                                      ("CPI 総合 前月比", "cpi_mom", "cpi_mom_f", "{:+.1f}%", "{:+.1f}")):
            fv = r.get(f)
            rows.append(f'<tr><th scope="row">{name}<small>{lab}</small></th>'
                        f'<td>{fmt.format(r[a])}</td>'
                        f'<td class="muted">{"—" if pd.isna(fv) else fmt.format(fv)}</td>'
                        f'{diff_cell(r[a], fv, dfmt)}</tr>')
    if len(j):
        r = j.iloc[-1]
        lab = f"{r['date']:%-m}月分"
        fv = r.get("payrolls_chg_f")
        rows.append(f'<tr><th scope="row">雇用者数 前月差<small>{lab}・千人</small></th>'
                    f'<td>{r["payrolls_chg"]:+,.0f}</td>'
                    f'<td class="muted">{"—" if pd.isna(fv) else f"{fv:+,.0f}"}</td>'
                    f'{diff_cell(r["payrolls_chg"], fv, "{:+,.0f}")}</tr>')
        fv = r.get("unemp_f")
        rows.append(f'<tr><th scope="row">失業率<small>{lab}</small></th>'
                    f'<td>{r["unemp"]:.1f}%</td>'
                    f'<td class="muted">{"—" if pd.isna(fv) else f"{fv:.1f}%"}</td>'
                    f'{diff_cell(r["unemp"], fv, "{:+.1f}", inv=True)}</tr>')
    out.append(f"""<table class="mtab"><thead><tr><th>最新の結果</th><th>実績</th>
      <th>予想</th><th>差</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
      <p class="cap">差の色は <span class="up">赤＝ドル高・円安方向の上振れ</span>／
      <span class="dn">緑＝円高方向</span>。失業率は低いほうが強いので色が逆になります。</p>""")
    return "".join(out)


def _bt_card(bt) -> str:
    if not bt.get("ok"):
        return f'<p class="muted">バックテストは実施できませんでした（{html.escape(bt.get("reason", ""))}）。</p>'
    ratio = bt["ratio"]
    if ratio < 0.98:
        chip, judge = "ok", "ランダムウォークをわずかに上回った"
    elif ratio < 1.02:
        chip, judge = "mid", "ほぼ互角（実質的に勝てていない）"
    else:
        chip, judge = "ng", "ランダムウォークに負けた"
    mx = max(bt["rmse_model"], bt["rmse_rw"]) * 1.1
    hit = bt["hit_rate"] * 100
    return f"""
      <div class="btv"><span class="chip {chip}">{judge}</span>
        <span class="muted">検証期間 {bt['n_test']}日（学習に使っていない直近30%）</span></div>
      <div class="bars2">
        <div><span>モデルの予測誤差</span><i style="width:{bt['rmse_model']/mx*100:.1f}%"></i><b>{bt['rmse_model']:.2f}%</b></div>
        <div><span>「動かない」と予想</span><i class="rw" style="width:{bt['rmse_rw']/mx*100:.1f}%"></i><b>{bt['rmse_rw']:.2f}%</b></div>
      </div>
      <ul class="facts">
        <li><span>誤差の比率（1未満で勝ち）</span><b>{ratio:.3f}</b></li>
        <li><span>向きの的中率（コイン投げ＝50%）</span><b>{hit:.1f}%</b></li>
        <li><span>乖離z → {bt['horizon']}日後リターンの傾き</span><b>{bt['full'].beta:+.2f}（R² {bt['full'].r2:.3f}）</b></li>
      </ul>
      <p class="cap">傾きがマイナス＝乖離は縮む方向に戻りやすい、という関係自体はあります。
      それでも点予測ではランダムウォークに勝てない — これがこのモデルの実力です。
      「明日いくらか」ではなく「今の水準は説明できる範囲か」を測る道具として使ってください。</p>"""


# ------------------------------------------------------------------------------
# ページ全体
# ------------------------------------------------------------------------------

def write_dashboard(df, sens, bt, grid, score, args, outdir, score_items) -> Path:
    data, ohlc, macro, policy = _payload(df, sens, bt, grid, score, args, score_items)
    spot = data["spot"]
    demo = bool(getattr(args, "demo", False))
    events = _events(policy, macro, data["today"])
    data["events"] = events

    demo_banner = ('<div class="demo">DEMO — このページは合成デモデータで作られています。'
                   '実際の相場ではありません。</div>') if demo else ""

    page = (TEMPLATE
            .replace("__CSS__", CSS)
            .replace("__JS__", JS)
            .replace("__DATA__", json.dumps(data, ensure_ascii=False, separators=(",", ":"))
                     .replace("</", "<\\/"))
            .replace("__UPDATED__", f"{_now():%Y-%m-%d %H:%M} JST")
            .replace("__RANGE__", f"{df['date'].iloc[0]:%Y-%m-%d} 〜 {df['date'].iloc[-1]:%Y-%m-%d}（{len(df)}営業日）")
            .replace("__SRC__", "合成デモデータ" if demo else "実データ")
            .replace("__DEMO__", demo_banner)
            .replace("__KPIS__", _kpis(df, sens, args, spot, data["px"]))
            .replace("__ZCARD__", _zcard(df))
            .replace("__POLICY__", _policy_card(policy, sens, spot))
            .replace("__MACRO__", _macro_card(macro))
            .replace("__HASMAC__", "" if data["mac"] else "hide"))

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / "index.html"
    path.write_text(page, encoding="utf-8")
    return path


CSS = r"""
@import url("https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap");
:root{
  /* DA-THEME: デジタル庁デザインテンプレート準拠 */
  --bg:#f3f4f6;--card:#ffffff;--ink:#0c0d10;--ink2:#3d4148;--ink3:#5b6068;
  --rule:#dfe2e7;--grid:#e6e8ec;--up:#b91c24;--dn:#08705a;--up-bg:rgba(200,50,58,.10);--dn-bg:rgba(15,127,99,.10);
  --fair:#5b6068;--band:rgba(91,96,104,.16);--band2:rgba(91,96,104,.07);
  --s2:#2a78d6;--s10:#eb6834;--price:#0c0d10;--warn:#b91c24;--ok:#08705a;
  --hl:#0c0d10;--ctl:#e9ebef;--shadow:none;
  color-scheme:light;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --bg:#050608;--card:#101216;--ink:#f2f4f8;--ink2:#c6cbd6;--ink3:#8f96a3;
    --rule:#23262d;--grid:#1b1e24;--up:#ff7378;--dn:#3fd0a4;--up-bg:rgba(255,115,120,.14);--dn-bg:rgba(63,208,164,.14);
    --fair:#8f96a3;--band:rgba(143,150,163,.18);--band2:rgba(143,150,163,.08);
    --s2:#4a93ea;--s10:#ef7d4e;--price:#f2f4f8;--warn:#ff7378;--ok:#3fd0a4;
    --hl:#f2f4f8;--ctl:#1b1e24;--shadow:none;
    color-scheme:dark;
  }
}
:root[data-theme="dark"]{
  --bg:#050608;--card:#101216;--ink:#f2f4f8;--ink2:#c6cbd6;--ink3:#8f96a3;
  --rule:#23262d;--grid:#1b1e24;--up:#ff7378;--dn:#3fd0a4;--up-bg:rgba(255,115,120,.14);--dn-bg:rgba(63,208,164,.14);
  --fair:#8f96a3;--band:rgba(143,150,163,.18);--band2:rgba(143,150,163,.08);
  --s2:#4a93ea;--s10:#ef7d4e;--price:#f2f4f8;--warn:#ff7378;--ok:#3fd0a4;
  --hl:#f2f4f8;--ctl:#1b1e24;--shadow:none;
  color-scheme:dark;
}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--ink)}
body{font-family:"Hiragino Sans","Hiragino Kaku Gothic ProN","Yu Gothic Medium","Meiryo",system-ui,sans-serif;
  font-size:14px;line-height:1.6;-webkit-text-size-adjust:100%}
.num,.kv,.zbig,td,.tick{font-variant-numeric:tabular-nums}
.wrap{max-width:1360px;margin:0 auto;padding:18px 16px 40px}
header.top{display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:space-between;gap:10px 20px;margin-bottom:14px}
.top h1{font-size:22px;margin:0;letter-spacing:.02em}
.top .kick{font-size:11px;letter-spacing:.14em;color:var(--ink3);margin:0 0 2px;text-transform:uppercase}
.meta{display:flex;flex-wrap:wrap;gap:4px 14px;color:var(--ink2);font-size:12px}
.tools{display:flex;gap:8px;align-items:center}
.seg{display:inline-flex;background:var(--ctl);border-radius:8px;padding:2px}
.seg button{border:0;background:none;color:var(--ink2);font:inherit;font-size:12px;padding:5px 11px;border-radius:6px;cursor:pointer;min-height:30px}
.seg button[aria-pressed="true"]{background:var(--hl);color:#ffffff}
.demo{background:var(--up-bg);border-radius:8px;padding:10px 14px;margin-bottom:14px;font-weight:600}

.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:14px}
.kpi{background:var(--card);border-radius:8px;box-shadow:var(--shadow);padding:11px 14px 10px;min-width:0}
.kpi.hero{background:var(--hl);color:#ffffff}
.kpi.hero .kl,.kpi.hero .ks{color:inherit;opacity:.9}
.kl{font-size:12px;font-weight:700;color:var(--ink);white-space:nowrap}
.kv{font-size:28px;font-weight:700;line-height:1.3;letter-spacing:-.01em;white-space:nowrap}
.kv small{font-size:12px;font-weight:500;margin-left:2px;color:inherit;opacity:.7}
.ks{font-size:11.5px;color:var(--ink2);overflow:hidden;text-overflow:ellipsis}
.dl{font-size:12px;font-weight:600;margin-left:8px}
.kpi.hero .dl.up,.kpi.hero .dl.dn{color:#ffffff}
.up{color:var(--up)}.dn{color:var(--dn)}.muted{color:var(--ink3)}
.kpi.warnc .kv{color:var(--warn)}

.grid{display:grid;grid-template-columns:repeat(12,minmax(0,1fr));gap:14px}
.card{background:var(--card);border-radius:8px;box-shadow:var(--shadow);padding:14px 16px 14px;min-width:0;display:flex;flex-direction:column}
.c3{grid-column:span 3}.c4{grid-column:span 4}.c5{grid-column:span 5}.c6{grid-column:span 6}.c7{grid-column:span 7}.c8{grid-column:span 8}.c12{grid-column:span 12}
@media (max-width:1080px){.c3,.c4,.c5{grid-column:span 6}.c7,.c8{grid-column:span 12}}
@media (max-width:760px){.sl{grid-template-columns:minmax(0,1fr) 118px 40px}.c3,.c4,.c5,.c6,.c7,.c8{grid-column:span 12}.kv{font-size:21px}.wrap{padding:14px 12px 30px}}
.hide{display:none!important}
.ch{display:flex;align-items:baseline;justify-content:space-between;gap:8px;margin-bottom:6px;flex-wrap:wrap}
.ch h2{font-size:15px;font-weight:700;margin:0}
.ch .tag{font-size:10.5px;letter-spacing:.12em;color:var(--ink3);text-transform:uppercase}
.legend{display:flex;flex-wrap:wrap;gap:4px 12px;font-size:11.5px;color:var(--ink2);margin:0 0 4px}
.legend i{display:inline-block;width:14px;height:3px;border-radius:2px;vertical-align:middle;margin-right:5px}
.legend i.box{height:10px;width:10px;border-radius:2px}
.legend.tg button{font:inherit;font-size:11.5px;color:var(--ink2);background:none;border:1px solid var(--rule);border-radius:20px;padding:2px 10px;cursor:pointer;min-height:28px}
.legend.tg button[aria-pressed="false"]{opacity:.45;text-decoration:line-through}
.legend.tg span{padding:2px 0;align-self:center}
.hscroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
.hscroll .chart{touch-action:pan-x pan-y}
.scrollhint{display:none;font-size:11px;color:var(--ink3);margin:4px 0 0}
@media (max-width:760px){.scrollhint{display:block}}
.cap{font-size:11.5px;color:var(--ink2);margin:8px 0 0;line-height:1.65}
.chart{position:relative;width:100%;touch-action:pan-y}
.chart svg{display:block;width:100%;overflow:visible}
.tick{font-size:11px;fill:var(--ink2)}
.gl{stroke:var(--grid);stroke-width:1}
.zl{stroke:var(--ink3);stroke-width:1}
.tip{position:absolute;pointer-events:none;background:var(--card);color:var(--ink);box-shadow:0 4px 16px rgba(0,0,0,.14),0 0 0 1px var(--rule);
  border-radius:8px;padding:7px 10px;font-size:11.5px;line-height:1.5;white-space:nowrap;z-index:5;opacity:0;transition:opacity .08s}
.tip b{font-weight:600}.tip .d{color:var(--ink3);font-size:10.5px}
.tip .r{display:flex;justify-content:space-between;gap:14px}
.tip .sw{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:5px}

/* z メーター */
.zbox{display:flex;flex-direction:column;gap:8px}
.zbig{font-size:40px;font-weight:700;line-height:1}
.zbig small{font-size:16px;color:var(--ink3);margin-left:3px}
.zmsg{margin:2px 0 0;font-size:12.5px;color:var(--ink2)}
.facts{list-style:none;padding:0;margin:6px 0 0;font-size:12.5px}
.facts li{display:flex;justify-content:space-between;gap:10px;padding:5px 0;border-top:1px solid var(--rule)}
.facts li span{color:var(--ink2)}
.ev{list-style:none;margin:0;padding:0}
.ev li{display:grid;grid-template-columns:58px 1fr auto;gap:10px;align-items:center;padding:7px 0;border-top:1px solid var(--rule)}
.ev li:first-child{border-top:0}
.ev .dt{font-size:12px;font-weight:600}
.ev .dt small{display:block;font-weight:400;color:var(--ink3);font-size:10.5px}
.ev .nm{font-size:12.5px;min-width:0}
.ev .nm small{color:var(--ink3);margin-left:6px}
.ev .cd{font-size:11px;color:var(--ink2);background:var(--grid);border-radius:20px;padding:1px 8px;white-space:nowrap}
.ev .cd.soon{background:var(--hl);color:#ffffff}
.b{display:inline-block;font-size:10px;font-weight:700;border-radius:4px;padding:0 5px;margin-right:6px;letter-spacing:.04em;border:1px solid currentColor}
.b.fomc{color:var(--up)}.b.boj{color:var(--dn)}.b.cpi,.b.jobs{color:var(--ink2)}

/* スコア */
.gauge{display:flex;flex-direction:column;align-items:center;margin:-4px 0 4px}
.gauge svg{width:min(260px,100%)}
.gv{font-size:30px;font-weight:700;margin-top:2px;line-height:1}
.gverd{font-size:13px;font-weight:600;margin-top:4px}
.sl{display:grid;grid-template-columns:minmax(0,1fr) 150px 40px;gap:4px 10px;align-items:center;padding:6px 0;border-top:1px solid var(--rule)}
.sl label{font-size:12.5px;min-width:0}
.sl label small{display:block;font-size:10.5px;color:var(--ink3);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sl output{font-size:12.5px;font-weight:600;text-align:right;font-variant-numeric:tabular-nums}
input[type=range]{width:100%;accent-color:var(--hl);min-height:28px}
.rowbtn{display:flex;gap:8px;align-items:center;justify-content:space-between;margin-top:8px;flex-wrap:wrap;font-size:12px;color:var(--ink2)}
.rowbtn select,.rowbtn button{font:inherit;font-size:12px;color:var(--ink);background:var(--card);border:1px solid var(--rule);border-radius:6px;padding:4px 8px;min-height:30px}

/* シナリオ */
.mx{display:grid;grid-template-columns:auto 1fr 1fr;gap:6px;margin-top:6px}
.mx .h{font-size:11.5px;color:var(--ink2);text-align:center;align-self:end}
.mx .rh{font-size:11.5px;color:var(--ink2);writing-mode:horizontal-tb;align-self:center;text-align:right;padding-right:4px}
.cell{border-radius:8px;padding:10px 8px;text-align:center;min-height:74px;display:flex;flex-direction:column;justify-content:center;box-shadow:inset 0 0 0 1px var(--rule)}
.cell .lv{font-size:20px;font-weight:700;font-variant-numeric:tabular-nums}
.cell .dv{font-size:12px;font-weight:600}
.cell .sp{font-size:10.5px;color:var(--ink3)}
.hint{font-size:11.5px;color:var(--ink2);background:var(--grid);border-radius:6px;padding:6px 9px;margin-top:8px}

/* テーブル */
table{border-collapse:collapse;width:100%;font-size:12.5px}
th,td{text-align:right;padding:6px 4px;border-top:1px solid var(--rule);vertical-align:middle}
thead th{border-top:0;font-size:11.5px;color:var(--ink);font-weight:700;background:var(--ctl)}
th[scope=row],thead th:first-child{text-align:left;font-weight:500}
th small,td small{display:block;font-size:10.5px;color:var(--ink3);font-weight:400}
.ptab td{width:38%}
.ptab .num{display:inline-block;min-width:64px}
.pbar{position:relative;height:8px;background:var(--grid);border-radius:4px;margin:2px 0 3px}
.pbar i{position:absolute;top:0;bottom:0;border-radius:4px}
.pbar i.r{left:50%;background:var(--up)}.pbar i.l{right:50%;background:var(--dn)}
.pbar em{position:absolute;left:50%;top:-2px;bottom:-2px;width:1px;background:var(--ink3)}
.ptab tr.sum th,.ptab tr.sum td{font-weight:700}
.mtab td,.mtab th{padding:5px 4px}

/* バックテスト */
.btv{display:flex;flex-wrap:wrap;gap:6px 10px;align-items:center;font-size:12px}
.chip{display:inline-block;font-size:12px;font-weight:700;border-radius:20px;padding:2px 10px}
.chip.ok{background:rgba(12,163,12,.14);color:var(--ok)}
.chip.mid{background:rgba(250,178,25,.18);color:var(--warn)}
.chip.ng{background:var(--up-bg);color:var(--up)}
.bars2{margin:10px 0 2px;display:flex;flex-direction:column;gap:6px}
.bars2 div{display:grid;grid-template-columns:110px 1fr 52px;align-items:center;gap:8px;font-size:12px}
.bars2 span{color:var(--ink2)}
.bars2 i{display:block;height:12px;border-radius:0;background:var(--hl)}
.bars2 i.rw{background:var(--ink3)}
.bars2 b{text-align:right;font-variant-numeric:tabular-nums}
.check{list-style:none;padding:0;margin:0;font-size:12.5px}
.check li{padding:7px 0 7px 26px;border-top:1px solid var(--rule);position:relative}
.check li:first-child{border-top:0}
.check li::before{content:"";position:absolute;left:2px;top:10px;width:13px;height:13px;border:1.5px solid var(--ink3);border-radius:3px}
.check b{font-weight:600}
footer{margin-top:22px;font-size:11px;color:var(--ink3);line-height:1.7}

/* DA-THEME: 追加分 */
button:focus-visible,select:focus-visible,input:focus-visible{outline:2px solid var(--hl);outline-offset:2px}
.da-src{margin-top:4px}

/* ===== 2026-11 デザイン刷新（トップ画面と共通）：黒／白地、枠線なしのカード、数字は Inter の極太、赤＝円安（上昇）／緑＝円高（下落）。開いた瞬間に「いまの水準・結論・次のイベント」が分かる並び ===== */
body{font-family:Inter,"Hiragino Sans","Hiragino Kaku Gothic ProN","Noto Sans JP",system-ui,-apple-system,sans-serif;font-variant-numeric:tabular-nums;-webkit-font-smoothing:antialiased}
.wrap{max-width:1360px;padding:24px 16px 56px}
.top h1{font-size:24px;font-weight:800}
.card,.kpi{border-radius:14px}.card{padding:20px 22px}
.ch h2{font-size:14px;font-weight:800;letter-spacing:.08em}
.seg button[aria-pressed="true"],.ev .cd.soon{background:var(--ink);color:var(--bg);font-weight:800}
.b.fomc,.b.boj{color:var(--ink)}
.kpis{display:block}
.hero{display:grid;grid-template-columns:minmax(0,5fr) minmax(0,7fr);gap:14px;margin-bottom:14px}
.hcard{background:var(--card);border-radius:14px;padding:22px 24px;min-width:0}
.hk{font-size:12px;font-weight:800;letter-spacing:.1em}.hk span{font-weight:400;letter-spacing:0;color:var(--ink3);margin-left:8px}
.hbig{font-size:clamp(64px,8.6vw,116px);font-weight:800;letter-spacing:-.045em;line-height:1;margin-top:8px;white-space:nowrap}
.hbig small{font-size:22px;letter-spacing:0;margin-left:4px}
.hbig .dl{font-size:20px;font-weight:800;letter-spacing:0;margin-left:14px}
.hsub{font-size:12.5px;color:var(--ink3);margin-top:8px}
.con{display:flex;flex-direction:column;margin-top:6px}
.con>div{display:grid;grid-template-columns:104px minmax(0,1fr);gap:2px 14px;align-items:baseline;padding:11px 0;border-top:1px solid var(--rule)}
.con>div:first-child{border-top:0}
.con .cl{font-size:12px;font-weight:800;color:var(--ink3);letter-spacing:.06em}
.con b{font-size:26px;font-weight:800;letter-spacing:-.01em;line-height:1.25}
.con small{grid-column:2;font-size:12.5px;color:var(--ink2)}
.con small b{font-size:inherit;letter-spacing:0}
.ktiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px;margin-bottom:14px}
.kpi{padding:14px 18px}.kl{font-weight:800;letter-spacing:.06em}.kv{font-size:30px;font-weight:800;letter-spacing:-.03em}
.zbig{font-size:56px;font-weight:800;letter-spacing:-.04em}
.gauge{align-items:stretch;margin:0 0 6px}.gauge svg{width:100%;order:3}
.gv{font-size:56px;font-weight:800;letter-spacing:-.04em;order:1}.gverd{font-size:15px;font-weight:800;order:2;margin:4px 0 8px}
.cell .lv{font-size:24px;font-weight:800;letter-spacing:-.02em}.cell{border-radius:10px}
.sl output,.facts b,td b{font-weight:800}
thead th{background:transparent;border-bottom:2px solid var(--ink);font-weight:800}
.hint{border-radius:8px}
@media (max-width:900px){.hero{grid-template-columns:1fr}}
@media (max-width:760px){.wrap{padding:16px 12px 40px}.card,.hcard{padding:16px 14px}.top h1{font-size:19px}.con b{font-size:21px}.con>div{grid-template-columns:76px minmax(0,1fr)}.kv{font-size:24px}.ktiles{grid-template-columns:1fr 1fr;gap:10px}}
"""


TEMPLATE = r"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>ドル円 ダッシュボード</title>
<style>__CSS__</style>
</head>
<body>
<div class="wrap">

<header class="top">
  <div>
    <p class="kick">USD / JPY — Rate Differential Model</p>
    <h1>ドル円 ダッシュボード</h1>
    <div class="meta"><span>更新 __UPDATED__</span><span>データ __RANGE__</span><span>__SRC__</span></div>
  </div>
  <div class="tools">
    <div class="seg" id="theme" role="group" aria-label="表示モード">
      <button data-t="auto" aria-pressed="true">自動</button><button data-t="light">ライト</button><button data-t="dark">ダーク</button>
    </div>
  </div>
</header>

__DEMO__

<section class="kpis">__KPIS__</section>

<div class="grid">

  <article class="card c8">
    <div class="ch"><h2>ドル円と日米金利差（直近2年）</h2><span class="tag">01 Price &amp; Spread</span></div>
    <div class="legend tg" id="pxLegend">
      <span><i class="box" style="background:var(--up)"></i><i class="box" style="background:var(--dn);margin-left:-3px"></i>ドル円 日足（左軸・円）</span>
      <button type="button" data-k="s2" aria-pressed="true"><i style="background:var(--s2)"></i>2年金利差（右軸・pt）</button>
      <button type="button" data-k="s10" aria-pressed="true"><i style="background:var(--s10)"></i>10年金利差（右軸・pt）</button>
      <button type="button" data-k="fair" aria-pressed="false"><i style="background:var(--fair)"></i>フェアバリュー</button>
    </div>
    <div class="hscroll" id="pxScroll"><div class="chart" id="cPrice"></div></div>
    <p class="scrollhint">← 横にスワイプすると2年分をさかのぼれます</p>
    <p class="cap">ローソクは赤＝その日円安、緑＝円高（左の目盛り・円）。重ねた2本の線は日米の金利差（右の目盛り・pt）で、
    <strong>青が2年、オレンジが10年</strong>。<strong>金利差の向きとローソクの向きがそろっているか</strong>を見る図です。
    そろっていない期間は、金利差以外の要因が相場を動かしています。
    凡例のボタンで線の表示／非表示を切り替えられ、「フェアバリュー」を押すと妥当水準の線と±2σの帯が出ます。
</p>
  </article>

  <article class="card c4">
    <div class="ch"><h2>乖離メーター</h2><span class="tag">02 Deviation</span></div>
    __ZCARD__
    <div class="ch" style="margin-top:14px"><h2>これからのイベント</h2><span class="tag">Calendar</span></div>
    <ul class="ev" id="events"></ul>
  </article>

  <article class="card c6">
    <div class="ch"><h2>方向性スコア</h2><span class="tag">03 Scoring</span></div>
    <div class="gauge"><svg viewBox="0 0 320 50" id="gauge" aria-hidden="true"></svg>
      <div class="gv" id="gVal">0</div><div class="gverd" id="gVerd">—</div></div>
    <div id="sliders"></div>
    <div class="rowbtn">
      <label>例外フィルター
        <select id="exc">
          <option value="1">×1.0 なし</option><option value="0.5">×0.5 介入警戒・リスクオフ</option>
          <option value="0.2">×0.2 判断保留</option></select></label>
      <button id="reset" type="button">初期値に戻す</button>
    </div>
    <p class="cap">各材料を −2（強い円高）〜 +2（強い円安）で採点。|スコア| &lt; 20 の「方向感なし」も正しい結論です。
    ここで動かした値は保存されません。毎回の初期値は usdjpy_model.py の <code>score_inputs</code> です。</p>
  </article>

  <article class="card c6">
    <div class="ch"><h2>イベント・シナリオ</h2><span class="tag">04 FOMC × BOJ</span></div>
    <div class="sl"><label>FOMC 利上げの織り込み確率<small>市場がどこまで価格に入れているか</small></label>
      <input type="range" id="pF" min="0" max="1" step="0.05"><output id="oF"></output></div>
    <div class="sl"><label>日銀 利上げの織り込み確率<small>同上</small></label>
      <input type="range" id="pB" min="0" max="1" step="0.05"><output id="oB"></output></div>
    <div class="mx" id="mx"></div>
    <div class="hint" id="shint"></div>
    <p class="cap">効くのは「決定」ではなく「織り込みとのズレ」。
    サプライズ × 2年債への伝わり方 × 金利感応度 で着地水準を計算しています（usdjpy_model.py と同じ式）。</p>
  </article>

  <article class="card c6">
    <div class="ch"><h2>金融政策の織り込み</h2><span class="tag">05 Policy</span></div>
    __POLICY__
  </article>

  <article class="card c6 __HASMAC__">
    <div class="ch"><h2>米国の経済指標</h2><span class="tag">06 CPI / Jobs</span></div>
    <div class="legend"><span><i style="background:var(--up)"></i>CPI 総合（前年比）</span>
      <span><i style="background:var(--s10)"></i>CPI コア（前年比）</span></div>
    <div class="chart" id="cCpi"></div>
    <div class="legend" style="margin-top:6px"><span><i class="box" style="background:var(--ink3)"></i>非農業部門雇用者数（前月差・千人）</span></div>
    <div class="chart" id="cJobs"></div>
    __MACRO__
  </article>

</div>

<footer>
  本ページは教育・分析目的で自動生成されたものであり、投資助言ではありません。
  生成: usdjpy_model.py → html_dashboard.py ／ データ出典: Yahoo Finance（四本値・VIX）、FRED、
  財務省 国債金利情報、BLS（CPI・雇用統計）、日本銀行、FRB。
</footer>
</div>
<script id="payload" type="application/json">__DATA__</script>
<script>__JS__</script>
</body>
</html>"""


JS = r"""
(function(){
'use strict';
const D = JSON.parse(document.getElementById('payload').textContent);
const $ = s => document.querySelector(s);
const NS = 'http://www.w3.org/2000/svg';
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const fmt = (v, d=2) => v==null||!isFinite(v) ? '—' : Number(v).toFixed(d);
const sgn = (v, d=2) => v==null||!isFinite(v) ? '—' : (v>0?'+':'')+Number(v).toFixed(d);

/* ---------- テーマ ---------- */
function setTheme(t){
  const r=document.documentElement;
  if(t==='auto') r.removeAttribute('data-theme'); else r.setAttribute('data-theme',t);
  document.querySelectorAll('#theme button').forEach(b=>b.setAttribute('aria-pressed',b.dataset.t===t));
  try{localStorage.setItem('usdjpy-theme',t)}catch(e){}
  drawAll();
}
document.querySelectorAll('#theme button').forEach(b=>b.onclick=()=>setTheme(b.dataset.t));
try{const t=localStorage.getItem('usdjpy-theme'); if(t&&t!=='auto'){document.documentElement.setAttribute('data-theme',t);
  document.querySelectorAll('#theme button').forEach(b=>b.setAttribute('aria-pressed',b.dataset.t===t));}}catch(e){}
/* ---------- 小さなチャートエンジン ---------- */
function niceTicks(lo, hi, n){
  const span = hi-lo || 1, raw = span/n, p = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1,2,2.5,5,10].map(m=>m*p).find(s=>s>=raw) || p*10;
  const t=[]; for(let v=Math.ceil(lo/step)*step; v<=hi+1e-9; v+=step) t.push(+v.toFixed(10));
  return {t, step};
}
function el(tag, attrs, parent){ const e=document.createElementNS(NS,tag);
  for(const k in attrs) e.setAttribute(k, attrs[k]); if(parent) parent.appendChild(e); return e; }

/*
 cfg = { dates:[], h, layers:[...], refs:[{y,dash}], yfmt, tip:(i)=>html, pad, yMin, yMax, xfmt }
 layer: {type:'line', v:[], color, w} | {type:'band', lo:[], hi:[], fill} |
        {type:'candle', o,h,l,c} | {type:'bar', v:[], color:(v,i)=>css}
*/
function chart(host, cfg){
  host.innerHTML='';
  const W = Math.max(host.clientWidth, 260), H = cfg.h || 240;
  const dual = cfg.layers.some(L=>L.axis==='r');
  const P = {l:dual?40:8, r:46, t:8, b:22};
  const n = cfg.dates.length; if(!n) return;
  let lo=Infinity, hi=-Infinity, lo2=Infinity, hi2=-Infinity;
  const acc = v => { if(v!=null && isFinite(v)){ if(v<lo) lo=v; if(v>hi) hi=v; } };
  const acc2 = v => { if(v!=null && isFinite(v)){ if(v<lo2) lo2=v; if(v>hi2) hi2=v; } };
  cfg.layers.filter(L=>L.axis==='r').forEach(L=>L.v.forEach(acc2));
  cfg.layers.filter(L=>L.axis!=='r').forEach(L=>{
    if(L.type==='line'||L.type==='bar') L.v.forEach(acc);
    if(L.type==='band'){ L.lo.forEach(acc); L.hi.forEach(acc); }
    if(L.type==='candle'){ L.h.forEach(acc); L.l.forEach(acc); }
  });
  (cfg.refs||[]).forEach(r=>acc(r.y));
  if(cfg.yMin!=null) lo=Math.min(lo,cfg.yMin); if(cfg.yMax!=null) hi=Math.max(hi,cfg.yMax);
  if(cfg.zero){ lo=Math.min(lo,0); hi=Math.max(hi,0); }
  const padv=(hi-lo)*0.06||1; lo-=padv; hi+=padv;
  const {t:ticks} = niceTicks(lo, hi, H<180?3:5);
  const iw=W-P.l-P.r, ih=H-P.t-P.b, bw=iw/n;
  const X = i => P.l + bw*(i+0.5), Y1 = v => P.t + ih*(1-(v-lo)/(hi-lo));
  let Y2 = Y1, t2 = [];
  if(dual && isFinite(lo2)){ const pv=(hi2-lo2)*0.08||0.2; lo2-=pv; hi2+=pv;
    t2 = niceTicks(lo2,hi2,H<180?3:5).t; Y2 = v => P.t + ih*(1-(v-lo2)/(hi2-lo2)); }
  const Y = Y1, YA = L => L.axis==='r'?Y2:Y1;
  const svg = el('svg',{viewBox:`0 0 ${W} ${H}`, height:H, role:'img'}, host);
  if(cfg.label) svg.setAttribute('aria-label', cfg.label);
  // グリッドと目盛
  ticks.forEach(v=>{ el('line',{x1:P.l,x2:W-P.r,y1:Y(v),y2:Y(v),class:'gl'},svg);
    const t=el('text',dual?{x:P.l-6,y:Y(v)+3.5,class:'tick','text-anchor':'end'}:{x:W-P.r+6,y:Y(v)+3.5,class:'tick'},svg);
    t.textContent=(cfg.yfmt||(x=>x))(v);
    if(dual && cfg.leftAtRight){ // スクロールで左端が隠れても円の目盛りが読めるよう、右端の内側にも出す
      const u=el('text',{x:W-P.r-4,y:Y(v)-3,class:'tick','text-anchor':'end',style:'paint-order:stroke;stroke:var(--card);stroke-width:3px'},svg);
      u.textContent=(cfg.yfmt||(x=>x))(v)+'円'; } });
  t2.forEach(v=>{ const t=el('text',{x:W-P.r+6,y:Y2(v)+3.5,class:'tick'},svg); t.textContent=(cfg.y2fmt||(x=>x))(v); });
  // 月の目盛（60px以上あける）
  let lastX=-1e9, lastM='';
  cfg.dates.forEach((d,i)=>{ const m=d.slice(0,7); if(m!==lastM){ lastM=m; const x=X(i);
    if(x-lastX>=(cfg.xgap||58) && x < W-P.r-16){ lastX=x;
      const t=el('text',{x:x,y:H-6,class:'tick','text-anchor':'middle'},svg);
      t.textContent = (m.slice(5)==='01'||i<3 ? m.slice(2,4)+'/' : '') + (+m.slice(5))+'月'; } } });
  (cfg.refs||[]).forEach(r=>el('line',{x1:P.l,x2:W-P.r,y1:Y(r.y),y2:Y(r.y),class:'zl','stroke-dasharray':r.dash||'0',opacity:r.op||1},svg));
  const path = (arr, Yf=Y) => { let s='', on=false; arr.forEach((v,i)=>{ if(v==null||!isFinite(v)){on=false;return;}
    s += (on?'L':'M')+X(i).toFixed(1)+' '+Yf(v).toFixed(1); on=true; }); return s; };
  cfg.layers.forEach(L=>{
    if(L.type==='band'){
      let s='', seg=[];
      const flush=()=>{ if(seg.length>1){ s+='M'+seg.map(i=>X(i).toFixed(1)+' '+Y(L.hi[i]).toFixed(1)).join('L')
        +'L'+seg.slice().reverse().map(i=>X(i).toFixed(1)+' '+Y(L.lo[i]).toFixed(1)).join('L')+'Z'; } seg=[]; };
      L.lo.forEach((v,i)=>{ if(v==null||L.hi[i]==null) flush(); else seg.push(i); }); flush();
      el('path',{d:s,fill:L.fill,stroke:'none'},svg);
    }
    if(L.type==='line') el('path',{d:path(L.v,YA(L)),fill:'none',stroke:L.color,'stroke-width':L.w||2,'stroke-linejoin':'round','stroke-linecap':'round',opacity:L.op||1},svg);
    if(L.type==='bar'){ const y0=Y(Math.max(lo,Math.min(hi,0))), w=Math.max(1, Math.min(bw-(bw>4?1.5:0.4), 26));
      L.v.forEach((v,i)=>{ if(v==null) return; const y=Y(v), top=Math.min(y,y0), h=Math.max(Math.abs(y-y0),1);
        el('rect',{x:X(i)-w/2,y:top,width:w,height:h,fill:L.color(v,i),rx:Math.min(2,w/2)},svg); }); }
    if(L.type==='candle'){ const up=css('--up'), dn=css('--dn'), w=Math.max(1, bw*0.62);
      L.c.forEach((c,i)=>{ const o=L.o[i]; if(c==null||o==null) return; const col = c>=o?up:dn;
        el('line',{x1:X(i),x2:X(i),y1:Y(L.h[i]),y2:Y(L.l[i]),stroke:col,'stroke-width':1},svg);
        const t=Y(Math.max(o,c)), b=Y(Math.min(o,c));
        el('rect',{x:X(i)-w/2,y:t,width:w,height:Math.max(b-t,1),fill:col},svg); }); }
  });
  // 最終値ラベル
  const LL=(cfg.lastLabels||[]).map(o=>{ const arr=o.v; let i=arr.length-1; while(i>=0&&arr[i]==null) i--;
    return i<0?null:{...o,val:arr[i],y:(o.axis==='r'?Y2:Y1)(arr[i])}; }).filter(Boolean).sort((a,b)=>a.y-b.y);
  for(let k=1;k<LL.length;k++) if(LL[k].y-LL[k-1].y<17) LL[k].y=LL[k-1].y+17;
  LL.forEach(o=>{ const y=o.y, arr=[o.val], i=0; el('rect',{x:W-P.r+2,y:y-8,width:P.r-2,height:16,rx:3,fill:o.color},svg);
    const t=el('text',{x:W-P.r+5,y:y+3.8,class:'tick',style:'fill:'+ (o.ink||'#fff') +';font-weight:600'},svg); t.textContent=o.fmt(arr[i]); });
  // ホバー
  if(!cfg.tip) return;
  const tip=document.createElement('div'); tip.className='tip'; host.appendChild(tip);
  const cross=el('line',{y1:P.t,y2:H-P.b,stroke:css('--ink3'),'stroke-width':1,'stroke-dasharray':'3 3',opacity:0},svg);
  const dots=(cfg.dots||[]).map(o=>({o, c:el('circle',{r:4,fill:o.color,stroke:css('--card'),'stroke-width':2,opacity:0},svg)}));
  const hit=el('rect',{x:P.l,y:0,width:iw,height:H,fill:'transparent'},svg);
  const move=(cx)=>{ const r=svg.getBoundingClientRect(); const sx=(cx-r.left)*(W/r.width);
    const i=Math.max(0,Math.min(n-1,Math.floor((sx-P.l)/bw))); const x=X(i);
    cross.setAttribute('x1',x); cross.setAttribute('x2',x); cross.setAttribute('opacity',1);
    dots.forEach(d=>{ const v=d.o.v[i]; if(v==null){d.c.setAttribute('opacity',0);return;}
      d.c.setAttribute('cx',x); d.c.setAttribute('cy',(d.o.axis==='r'?Y2:Y1)(v)); d.c.setAttribute('opacity',1); });
    tip.innerHTML='<div class="d">'+cfg.dates[i]+'</div>'+cfg.tip(i); tip.style.opacity=1;
    const px=x*(r.width/W), tw=tip.offsetWidth;
    tip.style.left=Math.max(0, Math.min(r.width-tw, px+(px>r.width/2?-tw-12:12)))+'px'; tip.style.top='6px'; };
  const leave=()=>{ tip.style.opacity=0; cross.setAttribute('opacity',0); dots.forEach(d=>d.c.setAttribute('opacity',0)); };
  hit.addEventListener('mousemove',e=>move(e.clientX)); hit.addEventListener('mouseleave',leave);
  hit.addEventListener('touchstart',e=>move(e.touches[0].clientX),{passive:true});
  hit.addEventListener('touchmove',e=>move(e.touches[0].clientX),{passive:true});
  hit.addEventListener('touchend',()=>setTimeout(leave,1600));
}
const row=(color,label,val)=>`<div class="r"><span><span class="sw" style="background:${color}"></span>${label}</span><b>${val}</b></div>`;
const tail=(a,k)=>a.slice(Math.max(0,a.length-k));

/* ---------- 01 価格＋金利差（直近2年固定） ---------- */
const SHOW = {s2:true, s10:true, fair:false};
document.querySelectorAll('#pxLegend button').forEach(b=>b.onclick=()=>{
  SHOW[b.dataset.k]=!SHOW[b.dataset.k]; b.setAttribute('aria-pressed',SHOW[b.dataset.k]); drawPrice(); });
function drawPrice(){
  const host=$('#cPrice'), sc=$('#pxScroll'), S=D.px, T=D.ser;
  const narrow = innerWidth<760, H = narrow?300:400;
  const cUp=css('--up'), cDn=css('--dn'), cFair=css('--fair'), c2=css('--s2'), c10=css('--s10'), cPrice=css('--price');
  let dates,o,h,l,c,fair,sd,s2,s10;
  if(S){ ({date:dates,o,h,l,c,fair,sd,s2,s10}=S); }
  else { const k=Math.min(T.date.length,500); dates=tail(T.date,k); c=tail(T.close,k); fair=tail(T.fair,k); sd=tail(T.sd,k); s2=tail(T.s2,k); s10=tail(T.s10,k); }
  // スマホでは1本が2.4px以上になるよう横に広げてスクロールさせる
  host.style.width = narrow ? Math.max(sc.clientWidth, dates.length*2.4+86)+'px' : '100%';
  const layers=[];
  if(SHOW.fair){ const lo=fair.map((f,i)=>f==null||sd[i]==null?null:f-2*sd[i]), hi=fair.map((f,i)=>f==null||sd[i]==null?null:f+2*sd[i]);
    layers.push({type:'band',lo,hi,fill:css('--band')},{type:'line',v:fair,color:cFair,w:1.6}); }
  if(S) layers.push({type:'candle',o,h,l,c}); else layers.push({type:'line',v:c,color:cPrice,w:1.6});
  if(SHOW.s2) layers.push({type:'line',v:s2,color:c2,w:1.8,axis:'r'});
  if(SHOW.s10 && s10 && s10.length) layers.push({type:'line',v:s10,color:c10,w:1.8,axis:'r'});
  const LL=[{v:c,color:cPrice,ink:css('--card'),fmt:v=>v.toFixed(2)}];
  const dots=[{v:c,color:cPrice}];
  if(SHOW.s2){ dots.push({v:s2,color:c2,axis:'r'}); }
  if(SHOW.s10 && s10 && s10.length){ dots.push({v:s10,color:c10,axis:'r'}); }
  chart(host,{dates,h:H,layers,yfmt:v=>v.toFixed(0),y2fmt:v=>v.toFixed(1),label:'ドル円のローソク足と日米金利差（直近2年）',
    lastLabels:LL, dots, xgap:52, leftAtRight:narrow,
    tip:i=>{ let s='';
      if(S&&o[i]!=null) s+=row(c[i]>=o[i]?cUp:cDn,'始 → 終',fmt(o[i])+' → '+fmt(c[i]))+row('transparent','高 / 安',fmt(h[i])+' / '+fmt(l[i]));
      else s+=row(cPrice,'ドル円',fmt(c[i]));
      if(SHOW.s2) s+=row(c2,'2年金利差',fmt(s2[i])+'pt');
      if(SHOW.s10&&s10&&s10.length) s+=row(c10,'10年金利差',fmt(s10[i])+'pt');
      if(SHOW.fair){ s+=row(cFair,'フェアバリュー',fmt(fair[i]));
        if(fair[i]!=null&&sd[i]) s+=row('transparent','乖離',sgn(c[i]-fair[i])+'円（'+sgn((c[i]-fair[i])/sd[i])+'σ）'); }
      return s; }});
  if(narrow) sc.scrollLeft = sc.scrollWidth;
}
/* ---------- 08 マクロ ---------- */
function drawMacro(){
  const M=D.mac; if(!M) return;
  const up=css('--up'), cc=css('--s10');
  chart($('#cCpi'),{dates:M.date.map(d=>d+'-01'),h:150,xgap:52,layers:[{type:'line',v:M.cpi,color:up,w:2},{type:'line',v:M.core,color:cc,w:2}],
    refs:[{y:2,dash:'4 4',op:.7}],yfmt:v=>v.toFixed(1)+'%',label:'米CPIの推移',
    dots:[{v:M.cpi,color:up},{v:M.core,color:cc}],
    tip:i=>row(up,'総合',fmt(M.cpi[i],1)+'%')+row(cc,'コア',fmt(M.core[i],1)+'%')});
  chart($('#cJobs'),{dates:M.date.map(d=>d+'-01'),h:120,xgap:52,zero:true,yfmt:v=>v.toFixed(0),label:'米雇用者数の推移',
    layers:[{type:'bar',v:M.pay,color:v=>v>=0?css('--ink3'):css('--dn')}],
    tip:i=>row(css('--ink3'),'雇用者数',sgn(M.pay[i],0)+'千人')+row('transparent','失業率',fmt(M.unemp[i],1)+'%')});
}
/* ---------- 乖離メーター ---------- */
function drawZMeter(){
  const box=document.querySelector('.zbox'), host=$('#zmeter'); if(!box) return;
  const z=+box.dataset.z, z20=box.dataset.z20===''?null:+box.dataset.z20;
  const W=Math.max(host.clientWidth,220), H=46, L=-3, R=3, X=v=>8+(W-16)*(Math.max(L,Math.min(R,v))-L)/(R-L);
  host.innerHTML=''; const s=el('svg',{viewBox:`0 0 ${W} ${H}`,height:H},host);
  const up=css('--up'), dn=css('--dn');
  el('rect',{x:X(-3),y:14,width:X(-2)-X(-3),height:10,fill:dn,opacity:.28,rx:3},s);
  el('rect',{x:X(-2),y:14,width:X(-1)-X(-2),height:10,fill:dn,opacity:.12},s);
  el('rect',{x:X(-1),y:14,width:X(1)-X(-1),height:10,fill:css('--grid')},s);
  el('rect',{x:X(1),y:14,width:X(2)-X(1),height:10,fill:up,opacity:.12},s);
  el('rect',{x:X(2),y:14,width:X(3)-X(2),height:10,fill:up,opacity:.28,rx:3},s);
  [-2,-1,0,1,2].forEach(v=>{ const t=el('text',{x:X(v),y:40,class:'tick','text-anchor':'middle'},s); t.textContent=v>0?'+'+v:v; });
  if(z20!=null) el('circle',{cx:X(z20),cy:19,r:5,fill:'none',stroke:css('--ink3'),'stroke-width':1.5},s);
  el('path',{d:`M${X(z)-7} 4 L${X(z)+7} 4 L${X(z)} 13 Z`,fill:z>=0?up:dn},s);
  el('rect',{x:X(z)-1.5,y:12,width:3,height:14,fill:css('--ink'),rx:1},s);
}
/* ---------- イベント ---------- */
function kNext(){ const b=$('#kNext'); if(!b) return; const e=(D.events||[])[0]; if(!e){ b.textContent='予定なし'; return; }
  const today=new Date(D.today+'T00:00:00+09:00'), d=new Date(e.date+'T00:00:00+09:00'), days=Math.round((d-today)/864e5);
  b.textContent=`${e.label}　${days<=0?'今日':days===1?'明日':'あと'+days+'日'}`;
  $('#kNextS').textContent=`${d.getMonth()+1}/${d.getDate()}（${'日月火水木金土'[d.getDay()]}）${e.note?'・'+e.note:''}`; }
function drawEvents(){
  const ul=$('#events'); kNext(); if(!D.events||!D.events.length){ ul.innerHTML='<li class="muted">予定が登録されていません（policy.json / us_macro.csv）</li>'; return; }
  const today=new Date(D.today+'T00:00:00+09:00'), wd='日月火水木金土';
  ul.innerHTML=D.events.slice(0,6).map(e=>{ const d=new Date(e.date+'T00:00:00+09:00'); const days=Math.round((d-today)/864e5);
    const cd=days<=0?'今日':days===1?'明日':'あと'+days+'日';
    return `<li><span class="dt">${d.getMonth()+1}/${d.getDate()}<small>(${wd[d.getDay()]})</small></span>
      <span class="nm"><span class="b ${e.kind}">${e.kind==='fomc'?'FOMC':e.kind==='boj'?'日銀':e.kind==='cpi'?'CPI':'雇用'}</span>${e.label}${e.note?'<small>'+e.note+'</small>':''}</span>
      <span class="cd ${days<=7?'soon':''}">${cd}</span></li>`; }).join('');
}

/* ---------- 05 スコア ---------- */
const items=D.items.map(x=>({...x}));
function verdict(v){ return v>=50?'強く円安寄り':v>=20?'円安寄り':v>-20?'方向感なし（無理に張らない）':v>-50?'円高寄り':'強く円高寄り'; }
function buildSliders(){
  $('#sliders').innerHTML=items.map((it,k)=>`<div class="sl"><label for="s${k}">${it.name}<small>重み${it.w}%・${it.note}</small></label>
    <input type="range" id="s${k}" min="-2" max="2" step="0.5" value="${it.v}"><output id="o${k}"></output></div>`).join('');
  items.forEach((it,k)=>{ $('#s'+k).oninput=e=>{ it.v=+e.target.value; updScore(); }; });
  $('#exc').value=String(D.exc); if($('#exc').value!==String(D.exc)){ const op=document.createElement('option'); op.value=D.exc; op.textContent='×'+D.exc; $('#exc').appendChild(op); $('#exc').value=String(D.exc); }
  $('#exc').onchange=updScore;
  $('#reset').onclick=()=>{ items.forEach((it,k)=>{ it.v=D.items[k].v; $('#s'+k).value=it.v; }); $('#exc').value=String(D.exc); updScore(); };
}
function updScore(){
  const tw=items.reduce((a,b)=>a+b.w,0), raw=items.reduce((a,b)=>a+b.w*b.v,0)/(tw*2)*100, f=raw*(+$('#exc').value);
  items.forEach((it,k)=>{ const o=$('#o'+k); o.textContent=(it.v>0?'+':'')+it.v.toFixed(1); o.className=it.v>0?'up':it.v<0?'dn':''; });
  const cls=f>=20?'up':f<=-20?'dn':'';
  $('#gVal').textContent=(f>0?'+':'')+f.toFixed(0); $('#gVal').className='gv '+cls;
  $('#gVerd').textContent=verdict(f);
  $('#kScore').textContent=(f>0?'+':'')+f.toFixed(0); $('#kScore').className=cls; $('#kVerdict').textContent=verdict(f);
  // 横メーター（−100 円高 〜 +100 円安）
  const g=$('#gauge'); g.innerHTML=''; const W=Math.max(g.clientWidth||320,240), H=50; g.setAttribute('viewBox',`0 0 ${W} ${H}`); g.setAttribute('height',H);
  const X=v=>(W)*(Math.max(-100,Math.min(100,v))+100)/200, up=css('--up'), dn=css('--dn');
  [[-100,-50,dn,.75],[-50,-20,dn,.3],[-20,20,css('--grid'),1],[20,50,up,.3],[50,100,up,.75]].forEach(([a,b,c,o])=>
    el('rect',{x:X(a)+1,y:16,width:X(b)-X(a)-2,height:10,fill:c,opacity:o},g));
  [[-100,'円高'],[-50,'−50'],[-20,'−20'],[20,'+20'],[50,'+50'],[100,'円安']].forEach(([v,t])=>{ const e=el('text',{x:X(v),y:44,class:'tick','text-anchor':v<=-100?'start':v>=100?'end':'middle'},g); e.textContent=t; });
  const nx=Math.max(4,Math.min(W-4,X(f)));
  el('path',{d:`M${nx-7} 2 L${nx+7} 2 L${nx} 12 Z`,fill:f>=20?up:f<=-20?dn:css('--ink')},g);
  el('rect',{x:nx-1.5,y:11,width:3,height:19,fill:css('--ink')},g);
}

/* ---------- 06 シナリオ ---------- */
function surprise(h,p){ p=Math.min(Math.max(p,0),1); return h? D.step*(1-p) : -D.step*p; }
function updScen(){
  const pF=+$('#pF').value, pB=+$('#pB').value;
  $('#oF').textContent=Math.round(pF*100)+'%'; $('#oB').textContent=Math.round(pB*100)+'%';
  const cells=[]; let mx=0;
  [true,false].forEach(us=>[true,false].forEach(jp=>{
    const ds=D.pass*(surprise(us,pF)-surprise(jp,pB)), dy=D.spot*D.beta*ds/100; mx=Math.max(mx,Math.abs(dy)); cells.push({us,jp,ds,dy}); }));
  const up=css('--up'), dn=css('--dn');
  const bg=(dy)=>{ const a=Math.min(Math.abs(dy)/Math.max(mx,0.5),1)*0.28; if(Math.abs(dy)<0.05) return 'transparent';
    return (dy>0?'rgba(200,50,58,':'rgba(15,127,99,')+a.toFixed(3)+')'; };
  let h='<div></div><div class="h">日銀 利上げ</div><div class="h">日銀 据え置き</div>';
  [true,false].forEach(us=>{ h+=`<div class="rh">FOMC<br>${us?'利上げ':'据え置き'}</div>`;
    cells.filter(c=>c.us===us).forEach(c=>{ h+=`<div class="cell" style="background:${bg(c.dy)}">
      <div class="lv">${(D.spot+c.dy).toFixed(2)}</div>
      <div class="dv ${c.dy>0.05?'up':c.dy<-0.05?'dn':''}">${c.dy>0.05?'▲ ':c.dy<-0.05?'▼ ':''}${sgn(c.dy)}円</div>
      <div class="sp">金利差 ${sgn(c.ds,3)}pt</div></div>`; }); });
  $('#mx').innerHTML=h;
  const hi=Math.max(...cells.map(c=>c.dy)), lo=Math.min(...cells.map(c=>c.dy));
  $('#shint').innerHTML=`基準 ${D.spot.toFixed(2)}円 ／ 値幅 <b>${(D.spot+lo).toFixed(2)} 〜 ${(D.spot+hi).toFixed(2)}</b>（感応度 ${sgn(D.beta)}%/pt・伝わり方 ${Math.round(D.pass*100)}%）`;
}
function buildScen(){ $('#pF').value=D.pF; $('#pB').value=D.pB; $('#pF').oninput=updScen; $('#pB').oninput=updScen; updScen(); }

function drawAll(){ drawPrice(); drawMacro(); drawZMeter(); updScore(); updScen(); }
buildSliders(); buildScen(); drawEvents(); drawAll();
let rt; addEventListener('resize',()=>{ clearTimeout(rt); rt=setTimeout(drawAll,120); });
if(window.matchMedia) matchMedia('(prefers-color-scheme: dark)').addEventListener('change',drawAll);
})();
"""
