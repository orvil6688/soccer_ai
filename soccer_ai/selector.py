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


def _book_status(item: dict, bookmaker: str) -> dict:
    """取該 bookmaker 盤口狀態（供誘盤過濾判斷失效/暫停）。"""
    book = item.get("bookmakerOdds", {}).get(bookmaker, {}) if isinstance(item.get("bookmakerOdds"), dict) else {}
    return {
        "active": bool(book.get("bookmakerIsActive", True)) if isinstance(book, dict) else True,
        "suspended": bool(book.get("suspended", False)) if isinstance(book, dict) else False,
    }


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
        xb_status = _book_status(xb_f, config.BOOKMAKER_SECONDARY)
        meta = {
            "fixtureId": fid,
            "home": rec.get("home") if rec else "",
            "away": rec.get("away") if rec else "",
            "kickoff_utc": kickoff.isoformat(),
            "kickoff_local": config.to_local(kickoff).isoformat(),
            "xbet_active": xb_status["active"],
            "xbet_suspended": xb_status["suspended"],
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


# =========================================================================
# #2 線移動訊號（讀 movement 六錨點：initial vs 最新）
# =========================================================================
def _latest_anchor(anchors: dict) -> Optional[dict]:
    for name in ("closing", "t1h", "t6h", "t12h", "t24h"):
        a = anchors.get(name)
        if a:
            return a
    return None


def line_movement_signal(rec: Optional[dict], pick: dict) -> str:
    """Pinnacle 初盤→最新線相對「我方 pick」的方向：confirm / reverse / flat。"""
    if not rec or not isinstance(rec.get("anchors"), dict):
        return "flat"
    anchors = rec["anchors"]
    init, late = anchors.get(config.ANCHOR_INITIAL), _latest_anchor(anchors)
    if not init or not late:
        return "flat"
    mkt = pick["market"]
    a_i, a_l = init.get(mkt), late.get(mkt)
    if not a_i or not a_l:
        return "flat"
    d = a_l["line"] - a_i["line"]
    if abs(d) < 1e-9:
        return "flat"
    if mkt == "handicap":
        toward = "home" if d < 0 else "away"  # 線更負＝往主隊
    else:
        toward = "over" if d > 0 else "under"  # 總分上移＝往大
    return "confirm" if pick["side"] == toward else "reverse"


def _key_number_cross(c: dict) -> bool:
    """兩莊線之間是否跨越關鍵數字（edge 靠跨關鍵數字成立 → 較不可靠）。"""
    if c["market"] == "handicap":
        keys = config.KEY_NUMBERS_HANDICAP
        lo, hi = sorted([abs(c["pinnacle_line"]), abs(c["xbet_line"])])
    else:
        keys = config.KEY_NUMBERS_TOTAL
        lo, hi = sorted([c["pinnacle_line"], c["xbet_line"]])
    return any(lo < k < hi for k in keys)


# =========================================================================
# #2 誘盤過濾 + 注碼
# =========================================================================
def _filter_and_stake(c: dict, rec: Optional[dict]) -> dict:
    """回傳加上 signals/stake_units/filtered/filter_reason 的 pick。"""
    signal = line_movement_signal(rec, c)
    key_cross = _key_number_cross(c)
    c["signals"] = {"line_move": signal, "reverse_against": signal == "reverse", "key_number_cross": key_cross}

    reason = None
    # 盤太甜（過期/錯盤/陷阱）→ 剔除
    if c["edge_goals"] > config.TRAP_EDGE_GOALS_MAX:
        reason = f"盤太甜(線差>{config.TRAP_EDGE_GOALS_MAX})"
    elif c["edge_pct"] is not None and c["edge_pct"] > config.TRAP_EDGE_PCT_MAX:
        reason = f"盤太甜(EV>{config.TRAP_EDGE_PCT_MAX})"
    # 盤口失效/暫停 → 剔除
    elif not c.get("xbet_active", True) or c.get("xbet_suspended", False):
        reason = "1xBet 盤口失效/暫停"
    # 關鍵數字：edge 靠跨關鍵數字成立且邊際不足 → 剔除（門檻待校準＝2×主閘）
    elif key_cross and c["edge_source"] == "line" and c["edge_goals"] < config.EDGE_THRESHOLD * 2:
        reason = "關鍵數字邊際不足"

    c["filtered"] = reason is not None
    c["filter_reason"] = reason
    if reason:
        c["stake_units"] = 0
        return c

    # 注碼（E）：2 單位＝線差大 + 同向確認 + 無反向；反向→降權為 1
    strong = c["edge_goals"] >= config.STAKE2_EDGE_GOALS and signal == "confirm"
    c["stake_units"] = 2 if strong else 1
    return c


def select(now: Optional[datetime] = None) -> list[dict]:
    """主入口：候選偵測 → 誘盤過濾 + 注碼。回最終通過的 picks（已含 stake_units）。"""
    candidates = find_candidates(now=now)
    picks, filtered = [], []
    for c in candidates:
        rec = storage.load_fixture_movement(c["fixtureId"])
        c = _filter_and_stake(c, rec)
        (filtered if c["filtered"] else picks).append(c)
    logger.info(
        "選注完成：最終 picks %d（2單位 %d / 1單位 %d）/ 誘盤濾除 %d",
        len(picks), sum(1 for p in picks if p["stake_units"] == 2),
        sum(1 for p in picks if p["stake_units"] == 1), len(filtered),
    )
    return picks
