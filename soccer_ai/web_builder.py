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
import logging
import os
from pathlib import Path

from . import backtest, config, storage
from .notifier import _MARKET_ZH, _SIDE_ZH, _odds, _zh  # 顯示層對照（內部 key 不動）

logger = logging.getLogger(__name__)

_CSS = """
body{font-family:-apple-system,'Segoe UI',sans-serif;max-width:980px;margin:0 auto;padding:16px;background:#0f1115;color:#e6e6e6}
a{color:#5ab0ff}h1,h2,h3{color:#fff}table{border-collapse:collapse;width:100%;margin:8px 0}
th,td{border:1px solid #2a2f3a;padding:6px 8px;text-align:center;font-size:14px}th{background:#1a1f29}
.card{background:#161a22;border:1px solid #2a2f3a;border-radius:8px;padding:12px 16px;margin:12px 0}
.u2{color:#2ecc71;font-weight:700}.u1{color:#5ab0ff}.ai{background:#13202b;border-left:3px solid #5ab0ff;padding:8px 12px;margin:6px 0;border-radius:4px}
.muted{color:#8b95a5;font-size:12px}.tag{font-family:monospace;color:#ffd479}
"""


def _esc(x) -> str:
    return html.escape(str(x if x is not None else "—"))


# =========================================================================
# 內嵌 SVG 走勢圖（自包含、無 CDN）
# =========================================================================
def _svg_multiline(labels: list, series: dict, width: int = 560, height: int = 160) -> str:
    """labels: x 軸錨點名；series: {名稱:(值list, 顏色)}。值為 None 的點跳過。"""
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
    # x 標籤
    for i, lab in enumerate(labels):
        parts.append(f'<text x="{x(i):.0f}" y="{height-6}" fill="#8b95a5" font-size="10" text-anchor="middle">{_esc(lab)}</text>')
    # 各序列
    cy = pad_t
    for name, (arr, color) in series.items():
        pts = [f"{x(i):.0f},{y(v):.1f}" for i, v in enumerate(arr) if v is not None]
        if len(pts) >= 2:
            parts.append(f'<polyline points="{" ".join(pts)}" fill="none" stroke="{color}" stroke-width="2"/>')
        for i, v in enumerate(arr):
            if v is not None:
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
    o1, o2 = ("home_odd", "away_odd") if market == "handicap" else ("over_odd", "under_odd")
    s1, s2 = ("home", "away") if market == "handicap" else ("over", "under")
    rows, labels, line_s, a_s, b_s = [], [], [], [], []
    for name in config.ANCHOR_ORDER:
        a = anchors.get(name)
        role = config.ANCHOR_ROLE.get(name, "")
        if not a:
            rows.append(f"<tr><td>{name}</td><td class='muted'>{role}</td><td colspan='3' class='muted'>—（缺/未到）</td></tr>")
            continue
        rows.append(f"<tr><td>{name}</td><td class='muted'>{role}</td><td>{_esc(a.get('line'))}</td>"
                    f"<td>{_esc(_odds(a.get(o1)))}</td><td>{_esc(_odds(a.get(o2)))}</td></tr>")
        labels.append(name)
        line_s.append(a.get("line"))
        a_s.append(a.get(o1))
        b_s.append(a.get(o2))
    chart = _svg_multiline(labels, {f"{_SIDE_ZH[s1]}賠": (a_s, "#2ecc71"), f"{_SIDE_ZH[s2]}賠": (b_s, "#ff7675")})
    line_chart = _svg_multiline(labels, {"線": (line_s, "#ffd479")})
    return (f"<h3>{_MARKET_ZH.get(market, market)}　<span class='tag'>{_esc(su.get('tag'))}</span>"
            f"　形狀 {_esc(_zh(su.get('shape')))}</h3>"
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


def render_index(recs: list[dict], have_fixture: set) -> str:
    rows = []
    for r in sorted(recs, key=lambda x: str(x.get("kickoff_utc", "")), reverse=True):
        ai = r.get("ai", {})
        why = ai.get("confidence_reasoning") if ai.get("available") else f"🤖 暫無"
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
            f"<td style='text-align:left'>{_esc(why)}</td></tr>")
    table = (f"<table><tr><th>開賽</th><th>對戰</th><th>選注</th><th>賠率</th><th>單位</th><th>形狀</th><th>賽果</th><th>🤖 信心理由</th></tr>"
             f"{''.join(rows) or '<tr><td colspan=8 class=muted>目前無推薦（賽前無場在選注窗內屬正常）</td></tr>'}</table>")
    return _page("推薦單", f"<h1>📋 推薦單</h1><div class='muted'><a href='backtest.html'>📊 回測戰報</a></div>{table}")


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
    """收盤低水方（賠率較低那邊）。收盤缺則退而取最接近開賽的非空錨點；平水回 None。"""
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
    if abs(od1 - od2) <= config.FAV_EPS:
        return None  # 平水 → 無看好邊 → 不計
    return s1 if od1 < od2 else s2


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
                "fav": fav, "line": line, "result": result, "score": score,
            })
    return out


def _titan_by_trajectory(records: list[dict]) -> dict:
    """shape → {n(已判定筆數), hit_rate(過盤率), fixtures(樣本場次)}。PUSH 不計分母、半贏半輸 0.5。"""
    groups: dict[str, list] = {}
    for r in records:
        if r["result"] in _WIN_W or r["result"] in _LOSE_W or r["result"] == "PUSH":
            groups.setdefault(r.get("shape") or "unknown", []).append(r)
    out = {}
    for shape, rs in groups.items():
        w = sum(_WIN_W.get(r["result"], 0.0) for r in rs)
        l = sum(_LOSE_W.get(r["result"], 0.0) for r in rs)
        out[shape] = {
            "n": len(rs),
            "hit_rate": round(w / (w + l), 4) if (w + l) > 0 else None,
            "fixtures": len({r["fixtureId"] for r in rs}),
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


def render_titan_index(records: list[dict], movements: list[dict]) -> str:
    by = _titan_by_trajectory(records)

    def _pct(hr):
        return "—" if hr is None else f"{hr:.0%}"

    bt = "".join(
        f"<tr><td>{_esc(_zh(k))}</td><td>{_esc(v['n'])}</td>"
        f"<td>{_pct(v['hit_rate'])}</td><td>{_esc(v['fixtures'])}</td></tr>"
        for k, v in sorted(by.items(), key=lambda kv: -kv[1]["n"])
    )
    # 逐場明細
    det = []
    for mv in sorted(movements, key=lambda m: str(m.get("kickoff_local", ""))):
        fid = mv.get("fixtureId")
        sc = mv.get("score") or {}
        sc_txt = f"{sc.get('home','?')}:{sc.get('away','?')}" if isinstance(sc, dict) else "—"
        match = f"{mv.get('home','?')} vs {mv.get('away','?')}"
        link = f"<a href='fixtures/{_esc(storage._safe_name(fid))}.html'>{_esc(match)}</a>"
        recs = [r for r in records if r["fixtureId"] == fid]
        sub = "".join(
            f"<tr><td>{_MARKET_ZH.get(r['market'], r['market'])}</td><td>{_esc(r['book'])}</td>"
            f"<td>{_esc(_zh(r['shape']))}　<span class='tag'>{_esc(r['tag'])}</span></td>"
            f"<td>{_SIDE_ZH.get(r['fav'], '平水·不計') if r['fav'] else '平水·不計'}</td>"
            f"<td>{_esc(r['line'])}</td>"
            f"<td>{_RESULT_ZH.get(r['result'], '—') if r['result'] else '—'}</td></tr>"
            for r in recs
        )
        det.append(
            f"<div class='card'><h3>{link}　<span class='muted'>{_esc(str(mv.get('kickoff_local',''))[:16])}　🏁 {sc_txt}（90 分鐘）</span></h3>"
            f"<table><tr><th>盤口</th><th>莊</th><th>形狀</th><th>收盤低水方</th><th>收盤線</th><th>過盤</th></tr>{sub}</table></div>"
        )
    body = (
        f"<h1>🔬 titan007 2022 世界盃 · 本機離線回測</h1>"
        f"<div class='muted'>口徑：by_trajectory（shape → 過盤率），過盤基準＝<b>收盤低水方</b>；無 1xBet/無 edge，非 selector 命中率。</div>"
        f"<h3>各軌跡形狀 → 過盤率（PUSH 不計分母、半過/半輸計 0.5）</h3>"
        f"<table><tr><th>形狀</th><th>已判定筆數</th><th>過盤率</th><th>樣本場次</th></tr>"
        f"{bt or '<tr><td colspan=4 class=muted>尚無可判定資料</td></tr>'}</table>"
        f"<h2>逐場明細（{len(movements)} 場）</h2>{''.join(det)}"
        f"<p class='muted'>本機離線回測 · titan007 2022 · 僅供校準</p>"
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
    stats["recommendations"] = len(recs)
    (out / "index.html").write_text(render_index(recs, have_fixture), encoding="utf-8")
    (out / "backtest.html").write_text(render_backtest(recs), encoding="utf-8")
    logger.info("web_builder 完成：推薦 %d / 單場頁 %d / 失敗 %d → %s",
                stats["recommendations"], stats["fixtures"], stats["failed"], out.resolve())
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
