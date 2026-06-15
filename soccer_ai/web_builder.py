"""板塊三：靜態網頁產生器（web_builder，架構 A）。

純讀 `data/`（推薦 + 走勢）→ 產自包含 HTML（無外部 CDN、內嵌 SVG 走勢圖）。
補 Discord summary 看不到的明細：每場八錨點（決策6 + 回測2）逐點線/賠率 + 走勢圖。

⚠️ 公開頁衛生（必守）：
  - 絕不讀 .env、絕不輸出任何 webhook URL / API key。
  - data/ 內部欄位（summary_hash/notified_hash 等）**不原樣 dump**，只挑白名單欄位產 HTML。
不碰 selector/analyzer/storage/movement/backtest/trajectory 邏輯；只讀檔 + 產 HTML。
"""
from __future__ import annotations

import glob
import html
import json
import logging
import os
from pathlib import Path

from . import backtest, config, storage, trajectory
from .notifier import _MARKET_ZH, _SIDE_ZH, _odds, _zh  # 顯示層對照（內部 key 不動）

logger = logging.getLogger(__name__)

_CSS = """
body{font-family:-apple-system,'Segoe UI',sans-serif;max-width:980px;margin:0 auto;padding:16px;background:#0f1115;color:#e6e6e6}
a{color:#5ab0ff}h1,h2,h3{color:#fff}table{border-collapse:collapse;width:100%;margin:8px 0}
th,td{border:1px solid #2a2f3a;padding:6px 8px;text-align:center;font-size:14px}th{background:#1a1f29}
.card{background:#161a22;border:1px solid #2a2f3a;border-radius:8px;padding:12px 16px;margin:12px 0}
.u2{color:#2ecc71;font-weight:700}.u1{color:#5ab0ff}.ai{background:#13202b;border-left:3px solid #5ab0ff;padding:8px 12px;margin:6px 0;border-radius:4px}
.muted{color:#8b95a5;font-size:12px}.tag{font-family:monospace;color:#ffd479}
tr.trig td{background:#16283a;border-color:#2f5170}
"""


def _esc(x) -> str:
    return html.escape(str(x if x is not None else "—"))


# =========================================================================
# 內嵌 SVG 走勢圖（自包含、無 CDN）
# =========================================================================
def _svg_multiline(labels: list, series: dict, width: int = 560, height: int = 160,
                   highlight: "set | None" = None) -> str:
    """labels: x 軸錨點名；series: {名稱:(值list, 顏色)}。值為 None 的點跳過。

    highlight: 要強調的錨點名集合（trigger_anchors）→ 該 x 畫淡色直線 + 放大圈，標出觸發點。
    """
    highlight = highlight or set()
    pad_l, pad_b, pad_t, pad_r = 44, 22, 14, 90
    vals = [v for (arr, _) in series.values() for v in arr if v is not None]
    if not vals or len(labels) < 2:
        return '<div class="muted">（走勢點不足，無法繪圖）</div>'
    lo, hi = min(vals), max(vals)
    if hi == lo:
        hi += 0.1
    iw, ih = width - pad_l - pad_r, height - pad_b - pad_t
    n = len(labels)

    def x(i):
        return pad_l + (iw * i / (n - 1) if n > 1 else 0)

    def y(v):
        return pad_t + ih * (1 - (v - lo) / (hi - lo))

    parts = [f'<svg viewBox="0 0 {width} {height}" width="100%" style="background:#0c0f14;border:1px solid #2a2f3a;border-radius:6px">']
    # y 軸刻度
    for frac in (0, 0.5, 1):
        yy = pad_t + ih * frac
        val = hi - (hi - lo) * frac
        parts.append(f'<line x1="{pad_l}" y1="{yy:.0f}" x2="{width-pad_r}" y2="{yy:.0f}" stroke="#222831"/>')
        parts.append(f'<text x="6" y="{yy+4:.0f}" fill="#8b95a5" font-size="10">{val:.2f}</text>')
    # 觸發錨點：淡色直線標記（畫在序列底下）
    for i, lab in enumerate(labels):
        if lab in highlight:
            parts.append(f'<line x1="{x(i):.0f}" y1="{pad_t}" x2="{x(i):.0f}" y2="{height-pad_b}" stroke="#5ab0ff" stroke-width="1" stroke-dasharray="3 3" opacity="0.55"/>')
    # x 標籤（觸發點標藍）
    for i, lab in enumerate(labels):
        fill = "#5ab0ff" if lab in highlight else "#8b95a5"
        weight = ' font-weight="700"' if lab in highlight else ""
        parts.append(f'<text x="{x(i):.0f}" y="{height-6}" fill="{fill}"{weight} font-size="10" text-anchor="middle">{_esc(lab)}</text>')
    # 各序列
    cy = pad_t
    for name, (arr, color) in series.items():
        pts = [f"{x(i):.0f},{y(v):.1f}" for i, v in enumerate(arr) if v is not None]
        if len(pts) >= 2:
            parts.append(f'<polyline points="{" ".join(pts)}" fill="none" stroke="{color}" stroke-width="2"/>')
        for i, v in enumerate(arr):
            if v is not None:
                if labels[i] in highlight:  # 觸發點放大 + 藍色外圈
                    parts.append(f'<circle cx="{x(i):.0f}" cy="{y(v):.1f}" r="5" fill="none" stroke="#5ab0ff" stroke-width="2"/>')
                    parts.append(f'<circle cx="{x(i):.0f}" cy="{y(v):.1f}" r="3" fill="{color}"/>')
                else:
                    parts.append(f'<circle cx="{x(i):.0f}" cy="{y(v):.1f}" r="2.5" fill="{color}"/>')
        parts.append(f'<text x="{width-pad_r+6}" y="{cy+10:.0f}" fill="{color}" font-size="11">{_esc(name)}</text>')
        cy += 16
    parts.append("</svg>")
    return "".join(parts)


def _page(title: str, body: str) -> str:
    return (f"<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{_esc(title)}</title><style>{_CSS}</style></head><body>{body}"
            f"<footer class='muted'><hr>世界盃盤口分析系統 · 系統客觀數據 + 🤖 AI 推論（不參與選注）· 僅供研究</footer>"
            f"</body></html>")


# =========================================================================
# 單場明細（八錨點逐點 + 走勢圖）
# =========================================================================
def _market_block(traj_market: dict, market: str) -> str:
    if not isinstance(traj_market, dict):
        return ""
    anchors = traj_market.get("anchors", {})
    su = traj_market.get("summary", {})
    triggers = set(su.get("trigger_anchors") or [])  # 造成此 shape 的錨點 → 高亮
    o1, o2 = ("home_odd", "away_odd") if market == "handicap" else ("over_odd", "under_odd")
    s1, s2 = ("home", "away") if market == "handicap" else ("over", "under")
    rows, labels, line_s, a_s, b_s = [], [], [], [], []
    for name in config.ANCHOR_ORDER:
        a = anchors.get(name)
        role = config.ANCHOR_ROLE.get(name, "")
        trig = name in triggers
        cls = " class='trig'" if trig else ""
        mark = " ◀" if trig else ""
        if not a:
            rows.append(f"<tr><td>{name}</td><td class='muted'>{role}</td><td colspan='3' class='muted'>—（缺/未到）</td></tr>")
            continue
        off = a.get("offset_sec")  # catch-up：captured 距 target 過遠 → 標補抓·偏收盤（#3，顯示層判讀）
        late = (f"<span class='muted' title='captured 距 target {off}s'> 補抓·偏收盤</span>"
                if isinstance(off, (int, float)) and off > config.OFFSET_LATE_SEC else "")
        rows.append(f"<tr{cls}><td>{name}{mark}{late}</td><td class='muted'>{role}</td><td>{_esc(a.get('line'))}</td>"
                    f"<td>{_esc(_odds(a.get(o1)))}</td><td>{_esc(_odds(a.get(o2)))}</td></tr>")
        labels.append(name)
        line_s.append(a.get("line"))
        a_s.append(a.get(o1))
        b_s.append(a.get(o2))
    chart = _svg_multiline(labels, {f"{_SIDE_ZH[s1]}賠": (a_s, "#2ecc71"), f"{_SIDE_ZH[s2]}賠": (b_s, "#ff7675")}, highlight=triggers)
    line_chart = _svg_multiline(labels, {"線": (line_s, "#ffd479")}, highlight=triggers)
    trig_note = (f"　<span style='color:#5ab0ff'>● 藍圈/◀＝觸發此形狀的錨點：{_esc('、'.join(su.get('trigger_anchors')))}</span>"
                 if triggers else "")
    return (f"<h3>{_MARKET_ZH.get(market, market)}　<span class='tag'>{_esc(su.get('tag'))}</span>"
            f"　形狀 {_esc(_zh(su.get('shape')))}{trig_note}</h3>"
            f"<table><tr><th>錨點</th><th>role</th><th>線</th><th>{_SIDE_ZH[s1]}賠</th><th>{_SIDE_ZH[s2]}賠</th></tr>{''.join(rows)}</table>"
            f"<div class='muted'>賠率走勢</div>{chart}<div class='muted'>讓分/大小 線走勢</div>{line_chart}")


def render_fixture(mv: dict) -> str:
    fid = mv.get("fixtureId")
    title = f"{mv.get('home','?')} vs {mv.get('away','?')}"
    body = [f"<h1>{_esc(title)}</h1>",
            f"<div class='muted'>開賽 {_esc(str(mv.get('kickoff_local',''))[:16])}　fixtureId {_esc(fid)}　books {_esc('/'.join(mv.get('books', [])))}</div>"]
    for book in mv.get("books", []):
        body.append(f"<div class='card'><h2>{_esc(book)}</h2>")
        bt = mv.get("trajectory", {}).get(book, {})
        for market in ("handicap", "over_under"):
            body.append(_market_block(bt.get(market, {}), market))
        body.append("</div>")
    return _page(title, "".join(body))


# =========================================================================
# 推薦列表 + 回測戰報
# =========================================================================
def _all_recommendations() -> list[dict]:
    out = []
    for p in sorted(glob.glob(str(config.data_dir() / "recommendations" / "*.json"))):
        data = storage._read_json(Path(p))
        if isinstance(data, list):
            out.extend(x for x in data if isinstance(x, dict))
    return out


def _all_observations() -> list[dict]:
    out = []
    for p in sorted(glob.glob(str(config.data_dir() / "observations" / "*.json"))):
        data = storage._read_json(Path(p))
        if isinstance(data, list):
            out.extend(x for x in data if isinstance(x, dict))
    return out


_OBS_REASON_ZH = {"no_1xbet": "無 1xBet 盤（無 edge 對手盤）", "edge_below_threshold": "edge 未達門檻"}

_AI_LABELS = {
    "confidence_reasoning": "信心理由",
    "injury_news_inference": "消息面推測（盤口反推）",
    "market_reading": "盤口解讀",
}


def _ai_cell(ai: dict, primary: str, preview: int = 90) -> str:
    """🤖 AI 解讀格：不限字數。短的直接顯示；長的（或多欄）以 <details> 摘要+可展開完整解讀。

    summary 顯示 primary 欄前 preview 字當預覽；展開後列出所有可用欄位（完整、不截斷）。
    回傳已含 HTML，呼叫端勿再 _esc。
    """
    if not isinstance(ai, dict) or not ai.get("available"):
        r = ai.get("reason") if isinstance(ai, dict) else None
        return f"🤖 暫無（{_esc(r)}）" if r else "🤖 暫無"
    full = "<br>".join(f"<b>{lab}</b>：{_esc((ai.get(k) or '').strip())}"
                       for k, lab in _AI_LABELS.items() if (ai.get(k) or "").strip())
    if not full:
        return "🤖 暫無"
    prim = (ai.get(primary) or "").strip()
    n_fields = sum(1 for k in _AI_LABELS if (ai.get(k) or "").strip())
    if n_fields == 1 and len(prim) <= preview:        # 短且單欄 → 直接顯示，免展開
        return _esc(prim)
    head = _esc(prim[:preview].rstrip()) or "🤖 解讀"
    return (f"<details><summary style='cursor:pointer;color:#9fd0ff'>{head}… "
            f"<span class='muted'>(展開完整解讀)</span></summary>"
            f"<div style='margin-top:6px;white-space:pre-wrap;line-height:1.55'>{full}</div></details>")


def _render_observations(obs: list[dict], have_fixture: set) -> str:
    """觀察場區塊：有走勢但無 pick（無下注結論）。只顯示走勢入口 + 🤖 盤口解讀。"""
    if not obs:
        return ""
    rows = []
    for r in sorted(obs, key=lambda x: str(x.get("kickoff_utc", "")), reverse=True):
        ai = r.get("ai", {})
        match = f"{r.get('home','?')} vs {r.get('away','?')}"
        fid = r.get("fixtureId")
        match_html = f"<a href='fixtures/{_esc(fid)}.html'>{_esc(match)}</a>" if fid in have_fixture else _esc(match)
        rows.append(
            f"<tr><td>{_esc(str(r.get('kickoff_local',''))[:16])}</td><td>{match_html}</td>"
            f"<td>{_esc(_OBS_REASON_ZH.get(r.get('reason'), r.get('reason')))}</td>"
            f"<td style='text-align:left'>{_ai_cell(ai, 'market_reading')}</td></tr>")
    return (f"<h2>👁 觀察場（無 edge 對手盤·系統不下注）</h2>"
            f"<div class='muted'>有 Pinnacle/皇冠走勢可看、Gemini 解讀盤口為何這樣動，但缺 1xBet 對手盤或 edge 未達門檻 → "
            f"<b>不產生下注推薦</b>。點對戰看八錨點走勢。</div>"
            f"<table><tr><th>開賽</th><th>對戰</th><th>原因</th><th>🤖 盤口解讀</th></tr>{''.join(rows)}</table>")


def render_index(recs: list[dict], have_fixture: set, observations: "list[dict] | None" = None) -> str:
    rows = []
    for r in sorted(recs, key=lambda x: str(x.get("kickoff_utc", "")), reverse=True):
        ai = r.get("ai", {})
        ucls = "u2" if r.get("stake_units") == 2 else "u1"
        match = f"{r.get('home','?')} vs {r.get('away','?')}"
        fid = r.get("fixtureId")
        match_html = f"<a href='fixtures/{_esc(fid)}.html'>{_esc(match)}</a>" if fid in have_fixture else _esc(match)
        if r.get("settled"):
            sc = r.get("score")
            result = (f"{sc['home']}:{sc['away']}（{_esc(r.get('result'))}）"
                      if isinstance(sc, dict) else _esc(r.get("result")))
        else:
            result = "<span class='muted'>未結算</span>"
        rows.append(
            f"<tr><td>{_esc(str(r.get('kickoff_local',''))[:16])}</td><td>{match_html}</td>"
            f"<td>{_MARKET_ZH.get(r.get('market'),r.get('market'))} {_SIDE_ZH.get(r.get('side'),r.get('side'))} {_esc(r.get('line'))}</td>"
            f"<td>{_esc(_odds(r.get('odds')))}</td><td class='{ucls}'>{_esc(r.get('stake_units'))}</td>"
            f"<td>{_esc(_zh(r.get('signals',{}).get('shape')))}</td><td>{result}</td>"
            f"<td style='text-align:left'>{_ai_cell(ai, 'confidence_reasoning')}</td></tr>")
    table = (f"<table><tr><th>開賽</th><th>對戰</th><th>選注</th><th>賠率</th><th>單位</th><th>形狀</th><th>賽果</th><th>🤖 信心理由</th></tr>"
             f"{''.join(rows) or '<tr><td colspan=8 class=muted>目前無推薦（賽前無場在選注窗內屬正常）</td></tr>'}</table>")
    # observation→pick 去重（顯示層）：已是 pick 的場不再列觀察場（含清掉舊殘留條目）
    rec_fids = {r.get("fixtureId") for r in recs}
    obs_filtered = [o for o in (observations or []) if o.get("fixtureId") not in rec_fids]
    obs_section = _render_observations(obs_filtered, have_fixture)
    return _page("推薦單", f"<h1>📋 推薦單</h1><div class='muted'><a href='backtest.html'>📊 回測戰報</a></div>{table}{obs_section}")


def render_backtest(recs: list[dict]) -> str:
    m = backtest.compute_metrics(recs)
    bt = "".join(f"<tr><td>{_esc(_zh(k))}</td><td>{_esc(v['n'])}</td><td>{_esc(v['hit_rate'])}</td><td>{_esc(v['units'])}</td></tr>"
                 for k, v in (m.get("by_trajectory") or {}).items())
    body = (f"<h1>📊 回測戰報</h1><div class='muted'><a href='index.html'>← 推薦單</a></div>"
            f"<div class='card'>已結算 {m['decided']}/{m['total']}　命中率 {_esc(m['hit_rate'])}　單位 {_esc(m['units'])}　"
            f"ROI {_esc(m['roi'])}　平均CLV {_esc(m['avg_clv_pct'])}　擊敗收盤率 {_esc(m['beat_close_rate'])}</div>"
            f"<h3>各軌跡形狀 → 過盤率</h3><table><tr><th>形狀</th><th>筆數</th><th>命中率</th><th>單位</th></tr>"
            f"{bt or '<tr><td colspan=4 class=muted>尚無已結算資料</td></tr>'}</table>")
    return _page("回測戰報", body)


# =========================================================================
# titan007 2022 本機離線回測頁（local-only；不上 GitHub Pages、不進 git）
# -------------------------------------------------------------------------
# 口徑（總司令 2026-06-07 裁決）：
#   2022 titan007 只有 pinnacle+singbet、無 1xBet → 無 edge 對手盤 → 不是 selector 命中率，
#   是 by_trajectory：shape → 實際過盤率。過盤基準＝**收盤低水方（盤面最終看好邊）**。
#   過盤判定一律 90 分鐘比分（嚴格 fulltime），延長賽/PK 不計（score 由全量結果頁只取 90 分鐘）。
# 沿用 backtest 計分口徑：PUSH 不計分母、半贏半輸計 0.5。
# =========================================================================
_T007_DIR = config._PROJECT_ROOT / "data" / "titan007_2022"
_WIN_W = {"WIN": 1.0, "HALFWIN": 0.5}
_LOSE_W = {"LOSE": 1.0, "HALFLOSS": 0.5}


def _cover_result(score: dict, market: str, line, side: str):
    """以 90 分鐘比分判某邊是否過盤 → WIN/HALFWIN/PUSH/HALFLOSS/LOSE 或 None（資料不足）。

    讓分：line＝主隊視角（正=主受讓）；adj = (主-客) + line，主用 adj、客用 -adj。
    大小：base = 總進球 - 線；大用 base、小用 -base。亞洲盤 1/4 線 → 半贏半輸。
    """
    if not isinstance(score, dict) or line is None or side is None:
        return None
    h, a = score.get("home"), score.get("away")
    if not isinstance(h, (int, float)) or not isinstance(a, (int, float)):
        return None
    if market == "handicap":
        adj = (h - a) + float(line)
        x = adj if side == "home" else -adj
    else:
        base = (h + a) - float(line)
        x = base if side == "over" else -base
    if x >= 0.5 - 1e-9:
        return "WIN"
    if abs(x - 0.25) < 1e-9:
        return "HALFWIN"
    if abs(x) < 1e-9:
        return "PUSH"
    if abs(x + 0.25) < 1e-9:
        return "HALFLOSS"
    return "LOSE"


def _closing_favored_side(traj_market: dict, market: str):
    """收盤低水方（賠率較低那邊）。收盤缺則退而取最接近開賽的非空錨點。

    口徑（總司令 2026-06-07）：**零門檻**——od1<od2 取 s1、od1>od2 取 s2、**完全相等(diff==0)才不計**。
    不套任何容差（FAV_EPS 只管 shape 分類，禁跨用途）；門檻是校準產物、非前提，先攤原始事實。
    """
    if not isinstance(traj_market, dict):
        return None
    anchors = traj_market.get("anchors", {})
    a = None
    for name in reversed(config.ANCHOR_ORDER):  # closing, t30m, t1h, ... 取最接近開賽
        if anchors.get(name):
            a = anchors[name]
            break
    if not a:
        return None
    o1, o2 = ("home_odd", "away_odd") if market == "handicap" else ("over_odd", "under_odd")
    s1, s2 = ("home", "away") if market == "handicap" else ("over", "under")
    od1, od2 = a.get(o1), a.get(o2)
    if not isinstance(od1, (int, float)) or not isinstance(od2, (int, float)):
        return None
    if od1 == od2:
        return None  # 完全平水 → 無看好邊 → 不計（僅此一種，零容差）
    return s1 if od1 < od2 else s2


def _t24h_closing_tag(anchors: dict, market_type: str) -> str:
    """只比 [t24h, closing] 兩錨點 → 重用 trajectory.build_segments/build_summary 產**同格式**中文 tag。

    手法：把 t24h/closing 塞進兩個相鄰 ANCHOR_DECISION 槽當單一 segment 餵進既有邏輯（不手刻新算法、
    與頁上其他形狀 tag 同一套 4 維：①線升降級 ②我方賠率向 ③對方賠率向 ④低水方水互換）。
    任一錨點缺（null/場開太晚/區間外）→ '—'，不 crash。純本機 titan007 頁用、零額度、不碰 live。
    """
    if not isinstance(anchors, dict):
        return "—"
    a24, acl = anchors.get("t24h"), anchors.get("closing")
    if not a24 or not acl:
        return "—"
    dec = config.ANCHOR_DECISION
    synth = {n: None for n in dec}
    synth[dec[0]], synth[dec[1]] = a24, acl   # 兩相鄰 decision 槽 → 視為單一 [t24h→closing] segment
    try:
        segs = trajectory.build_segments(synth, market_type)
        summ = trajectory.build_summary(synth, segs, market_type)
        return summ.get("tag") or "—"
    except Exception:
        return "—"


def _titan_records(mv: dict) -> list[dict]:
    """單場 → 每 (market, book) 一筆：shape + 收盤低水方 + 過盤 result。"""
    out = []
    score = mv.get("score")
    for book in mv.get("books", []):
        bt = mv.get("trajectory", {}).get(book, {})
        for market in ("handicap", "over_under"):
            tm = bt.get(market, {})
            if not isinstance(tm, dict) or not tm.get("anchors"):
                continue
            su = tm.get("summary", {})
            fav = _closing_favored_side(tm, market)
            line = (tm.get("anchors", {}).get("closing") or {}).get("line")
            result = _cover_result(score, market, line, fav) if fav else None
            out.append({
                "fixtureId": mv.get("fixtureId"), "home": mv.get("home"), "away": mv.get("away"),
                "kickoff_local": mv.get("kickoff_local"), "market": market, "book": book,
                "shape": su.get("shape"), "tag": su.get("tag"),
                "tc_tag": _t24h_closing_tag(tm.get("anchors", {}), market),  # 另增：t24h→收盤 兩錨點形狀 tag
                "fav": fav, "line": line, "result": result, "score": score,
            })
    return out


def _titan_by_trajectory(records: list[dict]) -> dict:
    """shape → {n(有效判定筆數=扣走盤), push(走盤筆數,僅參考), hit_rate(過盤率), fixtures}。

    **PUSH(走盤) 完全排除在分母外**：n＝有效判定筆數(非 PUSH)，hit_rate＝過盤加權/(過盤+輸盤)。
    半過/半輸計 0.5（沿用 backtest 口徑）。走盤數另列僅供參考，不進分母。
    """
    groups: dict[str, list] = {}
    for r in records:
        if r["result"] in _WIN_W or r["result"] in _LOSE_W or r["result"] == "PUSH":
            groups.setdefault(r.get("shape") or "unknown", []).append(r)
    out = {}
    for shape, rs in groups.items():
        decided = [r for r in rs if r["result"] != "PUSH"]  # 扣掉走盤
        w = sum(_WIN_W.get(r["result"], 0.0) for r in decided)
        l = sum(_LOSE_W.get(r["result"], 0.0) for r in decided)
        out[shape] = {
            "n": len(decided),
            "push": len(rs) - len(decided),
            "hit_rate": round(w / (w + l), 4) if (w + l) > 0 else None,
            "fixtures": len({r["fixtureId"] for r in decided}),
        }
    return out


def _load_titan_movements() -> list[dict]:
    out = []
    for p in sorted(glob.glob(str(_T007_DIR / "*.json"))):
        data = storage._read_json(Path(p))
        if isinstance(data, dict) and data.get("fixtureId"):
            out.append(data)
    return out


_RESULT_ZH = {"WIN": "過盤", "HALFWIN": "半過", "PUSH": "走盤", "HALFLOSS": "半輸", "LOSE": "輸盤"}


def _titan_shape_legend(records: list[dict]) -> str:
    """形狀說明：條件文字由 trajectory._classify 的判定階梯 + config 門檻值生成（非照抄外部描述）。

    _classify 為**由上而下優先級聯**（先命中者勝）；insufficient 在 build_summary 前置判定。
    中文取 notifier._zh（顯示層唯一來源）；實測欄為本批 64 場 256 筆的實際偵測分佈。
    """
    s = config  # 門檻常數唯一真實來源
    # (內部 key, 觸發條件文字＝程式現況)；順序＝_classify 優先級聯（insufficient 最前置）
    cascade = [
        ("insufficient", f"決策錨點 < 2 筆，無足夠資料判形狀（build_summary 前置攔截）"),
        ("fav_swap", f"線幾乎不動（淨 0 級且路徑 ≤ 1 級）但<b>低水方中途換邊</b>（水互換 ≥ 1，FAV_EPS={s.FAV_EPS}）"),
        ("odds_drift", f"線幾乎不動（淨 0 級且路徑 ≤ 1 級）但<b>賠率明顯移動</b>（無水互換，ODDS_FLAT_EPS={s.ODDS_FLAT_EPS}）"),
        ("flat", f"線幾乎不動（淨 0 級且路徑 ≤ 1 級）且無水互換、賠率也幾乎不動"),
        ("spike_revert", f"最大偏離 ≥ {s.SHAPE_SPIKE_EXCURSION_STEPS} 級且頭尾回歸（淨 ≤ 1 級）＝沖高回吐"),
        ("late_swing", f"末段（t1h→t30m）位移 ≥ {s.SHAPE_LATE_SWING_STEPS} 級且方向轉變 ≤ 1 次＝臨場急動"),
        ("monotonic", f"方向 0 次轉變（單向）且淨移動 ≥ {s.SHAPE_MONO_NET_STEPS} 級"),
        ("gradual", f"方向 0 次轉變（單向）但淨移動 < {s.SHAPE_MONO_NET_STEPS} 級＝小幅單向推移"),
        ("choppy", f"方向轉變 ≥ 2 次且淨移動 ≤ 1 級＝來回震盪"),
        ("mixed", f"以上皆不命中（有移動但結構不純）的其餘情況"),
    ]
    n_rec = {}
    n_fix = {}
    for r in records:
        k = r.get("shape")
        n_rec[k] = n_rec.get(k, 0) + 1
        n_fix.setdefault(k, set()).add(r.get("fixtureId"))
    total = len(records)
    rows = "".join(
        f"<tr><td><code>{_esc(k)}</code></td><td>{_esc(_zh(k))}</td>"
        f"<td style='text-align:left'>{cond}</td>"
        f"<td>{n_rec.get(k, 0)} 筆 / {len(n_fix.get(k, set()))} 場</td></tr>"
        for k, cond in cascade
    )
    return (
        f"<details><summary style='cursor:pointer;color:#9fd0ff'>📖 形狀說明（內部 key｜中文｜觸發條件｜實測）— 條件由程式判定階梯生成</summary>"
        f"<div class='muted' style='margin:6px 0'>判定為<b>由上而下優先級聯</b>（先命中者勝）；中文為系統定調顯示層；"
        f"實測＝本批 {total} 筆（64 場×4）的實際偵測分佈。一級＝{s.LINE_STEP} 球；"
        f"另 <code>confirm/reverse</code> 屬 trajectory_signal（訊號層）非 shape，不列此表。</div>"
        f"<table><tr><th>內部 key</th><th>中文（系統定調）</th><th>觸發條件（程式現況）</th><th>實測（本批）</th></tr>{rows}</table>"
        f"</details>"
    )


# 純前端 inline 篩選（不依賴 CDN / localStorage）：點彙總表某 shape →
# 卡片層依 data-shapes 顯隱（任一列命中保留），列層依 data-shape 高亮（同場多列命中多列高亮）。
_TITAN_FILTER_JS = """<script>
(function(){
  var sel=null;
  var sumrows=[].slice.call(document.querySelectorAll('#sumtbl tr.shaperow'));
  var cards=[].slice.call(document.querySelectorAll('#cards .matchcard'));
  var fstatus=document.getElementById('fstatus');
  var shown=document.getElementById('shown');
  var clearbtn=document.getElementById('clearbtn');
  function apply(shape, zh){
    sel=shape; var n=0;
    cards.forEach(function(c){
      var set=(' '+(c.getAttribute('data-shapes')||'')+' ');
      var has=!shape || set.indexOf(' '+shape+' ')>=0;
      c.style.display=has?'':'none'; if(has) n++;
      [].slice.call(c.querySelectorAll('tr[data-shape]')).forEach(function(tr){
        if(shape && tr.getAttribute('data-shape')===shape) tr.classList.add('hl');
        else tr.classList.remove('hl');
      });
    });
    sumrows.forEach(function(r){ r.classList.toggle('selrow', !!shape && r.getAttribute('data-shape')===shape); });
    shown.textContent=n;
    if(shape){ fstatus.textContent='　篩選：'+zh+' · '+n+' 場'; clearbtn.style.display=''; }
    else { fstatus.textContent=''; clearbtn.style.display='none'; }
  }
  sumrows.forEach(function(r){
    r.addEventListener('click', function(){
      var s=r.getAttribute('data-shape');
      if(s===sel) apply(null,null); else apply(s, r.getAttribute('data-zh'));
    });
  });
  clearbtn.addEventListener('click', function(){ apply(null,null); });
})();
</script>"""

# 2022 歷史「主動查詢」工具（純前端、讀內嵌 JSON）。
# 🔒 鐵律：只查 2022 歷史供人工對比，**絕不接 2026 推薦/selector/公開頁**；
#          不做相似度標註、不回寫任何選注依據（選注唯一依據＝edge）。
_TITAN_QUERY_JS = """<script>
(function(){
  var data=JSON.parse(document.getElementById('qdata').textContent);
  var ZH=JSON.parse(document.getElementById('qzh').textContent);
  function v(id){ return document.getElementById(id).value; }
  function cat(rs){ if(rs==='WIN'||rs==='HALFWIN')return 'cover'; if(rs==='PUSH')return 'push';
    if(rs==='LOSE'||rs==='HALFLOSS')return 'lose'; return 'none'; }
  function run(){
    var sh=v('q_sh'),mk=v('q_mk'),bk=v('q_bk'),rs=v('q_rs');
    var hits=data.filter(function(d){
      return (!sh||d.sh===sh)&&(!mk||d.mk===mk)&&(!bk||d.bk===bk)&&(!rs||cat(d.rs)===rs); });
    var fixset={}; hits.forEach(function(h){ fixset[h.id]=1; });
    var out='<div class="muted" style="margin:6px 0">符合 '+hits.length+' 筆 · '+Object.keys(fixset).length+' 場</div>';
    if(!hits.length){ document.getElementById('q_result').innerHTML='<div class="muted">無符合條件</div>'; return; }
    out+='<table><tr><th>場次</th><th>盤口</th><th>莊</th><th>形狀</th><th>收盤線</th><th>過盤</th></tr>';
    hits.forEach(function(h){
      out+='<tr><td style="text-align:left"><a href="fixtures/'+h.id+'.html">'+h.m+'</a> <span class="muted">'+h.ko+'</span></td>'
        +'<td>'+(ZH.market[h.mk]||h.mk)+'</td><td>'+h.bk+'</td>'
        +'<td>'+(ZH.shape[h.sh]||h.sh)+'</td><td>'+(h.ln==null?'—':h.ln)+'</td>'
        +'<td>'+(h.rs?(ZH.result[h.rs]||h.rs):'平水·不計')+'</td></tr>';
    });
    out+='</table>';
    document.getElementById('q_result').innerHTML=out;
  }
  document.getElementById('q_run').addEventListener('click',run);
})();
</script>"""


def render_titan_index(records: list[dict], movements: list[dict]) -> str:
    by = _titan_by_trajectory(records)

    def _pct(hr):
        return "—" if hr is None else f"{hr:.0%}"

    # 彙總表：每列掛 data-shape(內部 key)/data-zh，供前端篩選；點擊以 key 比對（非中文）
    bt = "".join(
        f"<tr class='shaperow' data-shape='{_esc(k)}' data-zh='{_esc(_zh(k))}'>"
        f"<td>{_esc(_zh(k))}</td><td>{_esc(v['n'])}</td>"
        f"<td>{_pct(v['hit_rate'])}</td><td class='muted'>{_esc(v['push'])}</td>"
        f"<td>{_esc(v['fixtures'])}</td></tr>"
        for k, v in sorted(by.items(), key=lambda kv: -kv[1]["n"])
    )
    # 逐場明細：卡片掛 data-shapes(該場四列 shape 集合)；每列掛 data-shape
    det = []
    for mv in sorted(movements, key=lambda m: str(m.get("kickoff_local", ""))):
        fid = mv.get("fixtureId")
        sc = mv.get("score") or {}
        sc_txt = f"{sc.get('home','?')}:{sc.get('away','?')}" if isinstance(sc, dict) else "—"
        match = f"{mv.get('home','?')} vs {mv.get('away','?')}"
        link = f"<a href='fixtures/{_esc(storage._safe_name(fid))}.html'>{_esc(match)}</a>"
        recs = [r for r in records if r["fixtureId"] == fid]
        card_shapes = " ".join(sorted({str(r["shape"]) for r in recs if r.get("shape")}))
        sub = "".join(
            f"<tr data-shape='{_esc(r['shape'])}'><td>{_MARKET_ZH.get(r['market'], r['market'])}</td><td>{_esc(r['book'])}</td>"
            f"<td>{_esc(_zh(r['shape']))}　<span class='tag'>{_esc(r['tag'])}</span></td>"
            f"<td><span class='tag'>{_esc(r.get('tc_tag') or '—')}</span></td>"
            f"<td>{_SIDE_ZH.get(r['fav'], '平水·不計') if r['fav'] else '平水·不計'}</td>"
            f"<td>{_esc(r['line'])}</td>"
            f"<td>{_RESULT_ZH.get(r['result'], '—') if r['result'] else '—'}</td></tr>"
            for r in recs
        )
        det.append(
            f"<div class='card matchcard' data-shapes='{_esc(card_shapes)}'>"
            f"<h3>{link}　<span class='muted'>{_esc(str(mv.get('kickoff_local',''))[:16])}　🏁 {sc_txt}（90 分鐘）</span></h3>"
            f"<table><tr><th>盤口</th><th>莊</th><th>形狀（全軌跡）</th><th>t24h→收盤</th><th>收盤低水方</th><th>收盤線</th><th>過盤</th></tr>{sub}</table></div>"
        )
    # #4 2022 主動查詢工具：內嵌白名單 records JSON + zh 對照（純查歷史、不接 2026）
    qdata = [{
        "id": storage._safe_name(r["fixtureId"]), "m": f"{r.get('home','?')} vs {r.get('away','?')}",
        "mk": r["market"], "bk": r["book"], "sh": r["shape"], "rs": r["result"],
        "ln": r["line"], "ko": str(r.get("kickoff_local") or "")[:10],
    } for r in records]
    qzh = {"shape": {s: _zh(s) for s in {r["shape"] for r in records if r.get("shape")}},
           "market": _MARKET_ZH, "result": _RESULT_ZH}
    shape_opts = "".join(
        f"<option value='{_esc(s)}'>{_esc(_zh(s))}</option>"
        for s in sorted({r["shape"] for r in records if r.get("shape")})
    )
    query_panel = (
        "<div class='card' id='querytool'>"
        "<h3>🔎 2022 歷史主動查詢　<span class='muted' style='font-size:13px'>（僅供人工查 2022 對比 · 絕不接 2026 推薦/selector/公開頁）</span></h3>"
        "<div class='muted'>形狀 <select id='q_sh'><option value=''>全部</option>" + shape_opts + "</select>　"
        "盤口 <select id='q_mk'><option value=''>全部</option><option value='handicap'>讓分</option><option value='over_under'>大小球</option></select>　"
        "莊 <select id='q_bk'><option value=''>全部</option><option value='pinnacle'>pinnacle</option><option value='singbet'>singbet</option></select>　"
        "過盤 <select id='q_rs'><option value=''>全部</option><option value='cover'>過盤(含半過)</option><option value='push'>走盤</option><option value='lose'>輸盤(含半輸)</option><option value='none'>平水不計</option></select>　"
        "<button id='q_run'>查詢</button></div>"
        "<div id='q_result'>（選條件後按查詢；結果可點場次連到單場頁對比）</div>"
        f"<script type='application/json' id='qdata'>{json.dumps(qdata, ensure_ascii=False)}</script>"
        f"<script type='application/json' id='qzh'>{json.dumps(qzh, ensure_ascii=False)}</script>"
        "</div>"
    )
    body = (
        f"<style>.shaperow{{cursor:pointer}}.shaperow:hover td{{background:#222b38}}"
        f".shaperow.selrow td{{background:#2d3f55;color:#fff}}tr.hl td{{background:#2d3f55}}"
        f"#querytool select{{background:#0c0f14;color:#e6e6e6;border:1px solid #3a4252;border-radius:4px;padding:2px 4px}}"
        f"#clearbtn,#q_run{{background:#222b38;color:#9fd0ff;border:1px solid #3a4252;border-radius:4px;padding:3px 10px;cursor:pointer;margin-left:8px}}</style>"
        f"<h1>🔬 titan007 2022 世界盃 · 本機離線回測</h1>"
        f"<div class='muted'>口徑：by_trajectory（shape → 過盤率），過盤基準＝<b>收盤低水方</b>；無 1xBet/無 edge，非 selector 命中率。</div>"
        f"<h3>各軌跡形狀 → 過盤率（走盤 PUSH 完全不計分母、半過/半輸計 0.5）　<span class='muted'>（點某列篩選場次）</span></h3>"
        f"<table id='sumtbl'><tr><th>形狀</th><th>有效判定筆數</th><th>過盤率</th><th>走盤(不計)</th><th>樣本場次</th></tr>"
        f"{bt or '<tr><td colspan=5 class=muted>尚無可判定資料</td></tr>'}</table>"
        f"{query_panel}"
        f"<h2>逐場明細（<span id='shown'>{len(movements)}</span>/{len(movements)} 場）"
        f"<span id='fstatus' class='muted' style='font-size:14px'></span>"
        f"<button id='clearbtn' style='display:none'>清除篩選</button></h2>"
        f"<div id='cards'>{''.join(det)}</div>"
        f"<hr>{_titan_shape_legend(records)}"
        f"<p class='muted'>本機離線回測 · titan007 2022 · 僅供校準</p>"
        f"{_TITAN_FILTER_JS}{_TITAN_QUERY_JS}"
    )
    return _page("titan007 2022 本機回測", body)


def build_titan007_local(out_dir: str = "site_titan007") -> dict:
    """local-only：讀 data/titan007_2022/ → 產 site_titan007/（不上 Pages、不進 git）。"""
    out = Path(out_dir)
    (out / "fixtures").mkdir(parents=True, exist_ok=True)
    stats = {"fixtures": 0, "records": 0, "failed": 0}
    movements, records = [], []
    for mv in _load_titan_movements():
        fid = mv.get("fixtureId")
        try:
            (out / "fixtures" / f"{storage._safe_name(fid)}.html").write_text(render_fixture(mv), encoding="utf-8")
            records.extend(_titan_records(mv))
            movements.append(mv)
            stats["fixtures"] += 1
        except Exception as e:  # 單場壞 → 跳過不阻斷
            logger.warning("titan007 本機回測單場失敗 fixture=%s：%s", fid, e)
            stats["failed"] += 1
    stats["records"] = len(records)
    (out / "index.html").write_text(render_titan_index(records, movements), encoding="utf-8")
    logger.info("titan007 本機回測完成：場次 %d / 記錄 %d / 失敗 %d → %s",
                stats["fixtures"], stats["records"], stats["failed"], out.resolve())
    return stats


# =========================================================================
# build
# =========================================================================
def build(out_dir: str = "site") -> dict:
    out = Path(out_dir)
    (out / "fixtures").mkdir(parents=True, exist_ok=True)
    stats = {"recommendations": 0, "fixtures": 0, "failed": 0}

    have_fixture = set()
    for mv in storage.list_movements():
        fid = mv.get("fixtureId")
        if not fid:
            continue
        try:
            (out / "fixtures" / f"{storage._safe_name(fid)}.html").write_text(render_fixture(mv), encoding="utf-8")
            have_fixture.add(fid)
            stats["fixtures"] += 1
        except Exception as e:  # 單場壞 → 跳過不阻斷整站
            logger.warning("web_builder 單場失敗 fixture=%s：%s", fid, e)
            stats["failed"] += 1

    recs = _all_recommendations()
    obs = _all_observations()
    stats["recommendations"] = len(recs)
    stats["observations"] = len(obs)
    (out / "index.html").write_text(render_index(recs, have_fixture, obs), encoding="utf-8")
    (out / "backtest.html").write_text(render_backtest(recs), encoding="utf-8")
    logger.info("web_builder 完成：推薦 %d / 觀察場 %d / 單場頁 %d / 失敗 %d → %s",
                stats["recommendations"], stats["observations"], stats["fixtures"], stats["failed"], out.resolve())
    return stats


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description="web_builder：公開站(預設) 或 titan007 本機離線回測頁")
    ap.add_argument("--mode", choices=["public", "titan007_local"], default="public",
                    help="public=讀 data/ 產公開站(gh_pages 用)；titan007_local=讀 data/titan007_2022/ 產本機回測頁(不上 Pages)")
    ap.add_argument("--out", default=None, help="輸出目錄（預設 public→site / titan007_local→site_titan007）")
    args = ap.parse_args()
    if args.mode == "titan007_local":
        build_titan007_local(args.out or "site_titan007")
    else:
        build(args.out or os.getenv("SITE_OUT", "site"))
