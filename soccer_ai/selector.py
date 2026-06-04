"""板塊三：選注引擎（Phase 3，架構 A）。

哲學（總司令裁示）：純盤口、零主觀預測。
  Pinnacle 去水位求公允 → 對比 1xBet 找 edge → 誘盤過濾(#2) → 線移動輔助訊號(#2)。
  AI 不參與選注，只在 analyzer 產敘述。

#1（本檔目前範圍）：de-vig、edge 計算、可下注窗候選偵測，輸出候選 pick（不含過濾/注碼）。
#2 將加：誘盤過濾、線移動訊號、注碼。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from . import config, movement, odds_parser, oddspapi_client, storage

logger = logging.getLogger(__name__)


# =========================================================================
# 去水位（de-vig）
# =========================================================================
def de_vig(odd1: float, odd2: float) -> "tuple[Optional[float], Optional[float]]":
    """兩邊賠率 → 去水位後的公允機率 (fair1, fair2)。無效回 (None, None)。"""
    if not (isinstance(odd1, (int, float)) and isinstance(odd2, (int, float))) or odd1 <= 1 or odd2 <= 1:
        return (None, None)
    p1, p2 = 1.0 / odd1, 1.0 / odd2
    s = p1 + p2
    if s <= 0:
        return (None, None)
    return (p1 / s, p2 / s)


# =========================================================================
# edge 計算（單一市場）
# =========================================================================
def _cand(market, side, line, odds, fair_prob, pin_line, xb_line, edge_goals, edge_pct, source):
    return {
        "market": market, "side": side, "line": float(line), "odds": float(odds),
        "fair_prob": round(fair_prob, 4) if fair_prob is not None else None,
        "pinnacle_line": float(pin_line), "xbet_line": float(xb_line),
        "edge_goals": round(edge_goals, 3), "edge_pct": round(edge_pct, 4) if edge_pct is not None else None,
        "edge_source": source,
    }


def edge_handicap(pin: dict, xb: dict) -> list[dict]:
    """讓分 edge（home 視角線；負=主隊讓）。回候選清單（未過核心閘）。"""
    fph, fpa = de_vig(pin["home_odd"], pin["away_odd"])
    if fph is None:
        return []
    out: list[dict] = []
    dline = xb["line"] - pin["line"]
    if abs(dline) >= 1e-9:
        # 線不同：1xBet 給某邊更甜的線
        if dline > 0:  # 1xBet 主隊讓得少（線較高）→ 背主
            out.append(_cand("handicap", "home", xb["line"], xb["home_odd"], fph, pin["line"], xb["line"], dline, None, "line"))
        else:          # 1xBet 客隊受讓更多 → 背客
            out.append(_cand("handicap", "away", xb["line"], xb["away_odd"], fpa, pin["line"], xb["line"], -dline, None, "line"))
    else:
        # 同線：比價（EV%）
        for side, odd, fp in (("home", xb["home_odd"], fph), ("away", xb["away_odd"], fpa)):
            ev = odd * fp - 1.0
            if ev > 0:
                out.append(_cand("handicap", side, xb["line"], odd, fp, pin["line"], xb["line"], 0.0, ev, "price"))
    return out


def edge_total(pin: dict, xb: dict) -> list[dict]:
    """大小球 edge。回候選清單（未過核心閘）。"""
    fpo, fpu = de_vig(pin["over_odd"], pin["under_odd"])
    if fpo is None:
        return []
    out: list[dict] = []
    dline = xb["line"] - pin["line"]
    if abs(dline) >= 1e-9:
        if dline < 0:  # 1xBet 總分較低 → Over 更甜
            out.append(_cand("over_under", "over", xb["line"], xb["over_odd"], fpo, pin["line"], xb["line"], -dline, None, "line"))
        else:          # 較高 → Under 更甜
            out.append(_cand("over_under", "under", xb["line"], xb["under_odd"], fpu, pin["line"], xb["line"], dline, None, "line"))
    else:
        for side, odd, fp in (("over", xb["over_odd"], fpo), ("under", xb["under_odd"], fpu)):
            ev = odd * fp - 1.0
            if ev > 0:
                out.append(_cand("over_under", side, xb["line"], odd, fp, pin["line"], xb["line"], 0.0, ev, "price"))
    return out


def _passes_core_gate(c: dict) -> bool:
    """核心閘：線差 >= 0.25 球，或（同線）EV% >= 門檻。"""
    if c["edge_source"] == "line":
        return c["edge_goals"] >= config.EDGE_THRESHOLD
    return c["edge_pct"] is not None and c["edge_pct"] >= config.EDGE_PCT_THRESHOLD


# =========================================================================
# 候選偵測
# =========================================================================
def _book_point(item: dict, bookmaker: str, market_map: dict) -> Optional[dict]:
    bo = item.get("bookmakerOdds")
    if not isinstance(bo, dict):
        return None
    book = bo.get(bookmaker)
    if not isinstance(book, dict):
        return None
    markets = book.get("markets")
    if not isinstance(markets, dict):
        return None
    return odds_parser.parse_point(markets, market_map, odds_parser.current_price_fn)


def _index_by_fixture(items: list) -> dict:
    out = {}
    for f in items:
        if isinstance(f, dict) and isinstance(f.get("fixtureId"), str):
            out[f["fixtureId"]] = f
    return out


def find_candidates(now: Optional[datetime] = None) -> list[dict]:
    """抓 Pinnacle + 1xBet 當前盤，對可下注窗賽事算 edge，回通過核心閘的候選 pick。"""
    now = now or config.now_local()
    market_map = movement.ensure_market_map()
    if not market_map:
        logger.error("選注：市場對照表為空，中止")
        return []

    pin = _index_by_fixture(oddspapi_client.get_odds_by_tournament(config.BOOKMAKER_PRIMARY))
    xb = _index_by_fixture(oddspapi_client.get_odds_by_tournament(config.BOOKMAKER_SECONDARY))
    logger.info("選注：Pinnacle %d 場 / 1xBet %d 場", len(pin), len(xb))

    candidates: list[dict] = []
    for fid, pin_f in pin.items():
        xb_f = xb.get(fid)
        if xb_f is None:
            continue
        start = pin_f.get("startTime")
        if not isinstance(start, str):
            continue
        try:
            kickoff = config.to_utc(config.parse_iso(start))
        except ValueError:
            continue
        ttk = kickoff - now
        if not (timedelta(0) < ttk <= timedelta(hours=config.SELECT_WINDOW_HOURS)):
            continue

        pin_pt = _book_point(pin_f, config.BOOKMAKER_PRIMARY, market_map)
        xb_pt = _book_point(xb_f, config.BOOKMAKER_SECONDARY, market_map)
        if not pin_pt or not xb_pt:
            continue

        rec = storage.load_fixture_movement(fid)
        meta = {
            "fixtureId": fid,
            "home": rec.get("home") if rec else "",
            "away": rec.get("away") if rec else "",
            "kickoff_utc": kickoff.isoformat(),
            "kickoff_local": config.to_local(kickoff).isoformat(),
        }
        for market, fn in (("handicap", edge_handicap), ("over_under", edge_total)):
            pin_m, xb_m = pin_pt.get(market), xb_pt.get(market)
            if not pin_m or not xb_m:
                continue
            for c in fn(pin_m, xb_m):
                if _passes_core_gate(c):
                    candidates.append({**meta, **c})

    logger.info("選注：通過核心閘候選 %d 筆", len(candidates))
    return candidates
