"""板塊四：賽果回填 + CLV 自算 + 命中率/單位損益（Phase 2，架構 A）。

資料源：OddsPapi `/v4/settlements`（賽果，已驗證）。
結算 result 列舉（實測 MLS 完賽場）：WIN / LOSE / HALFWIN / HALFLOSS / PUSH / UNDECIDED。
結構：settlements.markets[<marketId>].outcomes[<outcomeId>].players["0"].result。
以市場對照表（odds_parser.build_market_map）把 (market 類型, 線, 邊) 對映到 marketId/outcomeId。

推薦記錄 schema（Phase 3 selector/analyzer 產出，本檔消費；存於 recommendations/{date}.json）：
  {"fixtureId": str, "produced_at_local": ISO, "kickoff_utc": ISO,
   "market": "handicap"|"over_under", "side": "home"|"away"|"over"|"under",
   "line": float, "odds": float, "stake_units": 1|2, ...}
  本檔回填：result / pnl_units / settled（+ Phase 2 後續加 clv）。
"""
from __future__ import annotations

import logging
from typing import Optional

from . import config, oddspapi_client

logger = logging.getLogger(__name__)

# 推薦的 side → 結算 outcomeName 對映
_SIDE_TO_OUTCOME = {"home": "1", "away": "2", "over": "Over", "under": "Under"}


def _market_name_for(market_type: str) -> Optional[str]:
    if market_type == "handicap":
        return config.MARKET_ASIAN_HANDICAP
    if market_type == "over_under":
        return config.MARKET_OVER_UNDER
    return None


def find_settlement_result(
    settlements: dict, market_map: dict, market_type: str, line: float, side: str
) -> Optional[str]:
    """在結算回應中找 (market 類型, 線, 邊) 對應的 result 字串；找不到回 None。"""
    target_name = _market_name_for(market_type)
    side_label = _SIDE_TO_OUTCOME.get(side)
    if target_name is None or side_label is None:
        return None
    markets = settlements.get("markets")
    if not isinstance(markets, dict):
        return None
    for mid, mobj in markets.items():
        meta = market_map.get(_to_int(mid))
        if not meta or meta["name"] != target_name:
            continue
        if abs(float(meta["handicap"]) - float(line)) > 1e-9:
            continue
        outcomes = mobj.get("outcomes") if isinstance(mobj, dict) else None
        if not isinstance(outcomes, dict):
            continue
        for oid, oobj in outcomes.items():
            if meta["outcomes"].get(str(oid)) != side_label:
                continue
            player = oobj.get("players", {}).get("0") if isinstance(oobj, dict) else None
            if isinstance(player, dict):
                return player.get("result")
    return None


def pnl_from_result(result: Optional[str], odds: float, stake: float) -> Optional[float]:
    """結算 result → 單位損益（以注碼為單位）。UNDECIDED/未知回 None（未結算）。"""
    if result == "WIN":
        return stake * (odds - 1.0)
    if result == "HALFWIN":
        return stake * (odds - 1.0) / 2.0
    if result == "PUSH":
        return 0.0
    if result == "HALFLOSS":
        return -stake / 2.0
    if result == "LOSE":
        return -stake
    if result and result != "UNDECIDED":
        logger.warning("未知結算 result：%s（視為未結算）", result)
    return None


def settle_recommendation(rec: dict, market_map: dict) -> dict:
    """對單筆推薦回填賽果（result / pnl_units / settled）。回傳更新後的 rec（原地）。"""
    fid = rec.get("fixtureId")
    settlements = oddspapi_client.get_settlements(fid) if isinstance(fid, str) else None
    if settlements is None:
        rec["settled"] = False
        return rec
    result = find_settlement_result(
        settlements, market_map, rec.get("market"), rec.get("line"), rec.get("side")
    )
    pnl = pnl_from_result(result, float(rec.get("odds", 0.0)), float(rec.get("stake_units", 1)))
    rec["result"] = result
    rec["pnl_units"] = pnl
    rec["settled"] = pnl is not None
    return rec


# =========================================================================
# CLV 自算（§3.6）：v4 無 /clv，自行以收盤盤口 vs 推薦產出時的線計算。
#   收盤 = historical 序列「該注確切線/邊」在開賽前的最後一筆（與六錨點 closing 同義）。
#   時序防呆：推薦產出時間 ≥ 收盤抓取時間 → 該筆標「無 CLV」。
# =========================================================================
def _historical_series_for(
    hist_markets: dict, market_map: dict, market_type: str, line: float, side: str
) -> Optional[list]:
    """從 historical markets 取 (market 類型, 線, 邊) 那條 outcome 的時間序列。"""
    target_name = _market_name_for(market_type)
    side_label = _SIDE_TO_OUTCOME.get(side)
    if target_name is None or side_label is None or not isinstance(hist_markets, dict):
        return None
    for mid, mobj in hist_markets.items():
        meta = market_map.get(_to_int(mid))
        if not meta or meta["name"] != target_name or abs(float(meta["handicap"]) - float(line)) > 1e-9:
            continue
        if not isinstance(mobj, dict):
            continue
        for oid, oobj in mobj.get("outcomes", {}).items():
            if meta["outcomes"].get(str(oid)) != side_label:
                continue
            series = oobj.get("players", {}).get("0") if isinstance(oobj, dict) else None
            return series if isinstance(series, list) else None
    return None


def closing_odds_for(
    hist_markets: dict, market_map: dict, kickoff, market_type: str, line: float, side: str
) -> "tuple[Optional[float], Optional[str]]":
    """該注確切線/邊在開賽前的最後一筆賠率（收盤）。回 (odds, ts_iso) 或 (None, None)。"""
    series = _historical_series_for(hist_markets, market_map, market_type, line, side)
    if not series:
        return (None, None)
    best = None
    for pt in series:
        if not isinstance(pt, dict):
            continue
        price, cts = pt.get("price"), pt.get("createdAt")
        if not isinstance(price, (int, float)) or not isinstance(cts, str):
            continue
        try:
            t = config.parse_iso(cts)
        except ValueError:
            continue
        if t < kickoff and (best is None or t > best[1]):
            best = (float(price), t)
    return (best[0], best[1].isoformat()) if best else (None, None)


def compute_clv(rec: dict, market_map: dict, bookmaker: str = config.BOOKMAKER_PRIMARY) -> Optional[dict]:
    """CLV =（推薦產出賠率 / 收盤賠率 − 1）。重抓 historical 取確切線收盤價。

    回 {closing_odds, closing_ts, production_odds, clv_pct, no_clv} 或 None（無法計算）。
    """
    fid = rec.get("fixtureId")
    try:
        kickoff = config.to_utc(config.parse_iso(rec["kickoff_utc"]))
        produced = config.parse_iso(rec["produced_at_local"])
    except (KeyError, ValueError):
        return None
    try:
        hist = oddspapi_client.get_historical_odds(fid, bookmaker) if isinstance(fid, str) else None
    except oddspapi_client.RateLimited:
        return None
    bm = hist.get("bookmakers", {}) if isinstance(hist, dict) else {}
    markets = bm.get(bookmaker, {}).get("markets") if isinstance(bm, dict) else None
    if not isinstance(markets, dict):
        return None
    close_odds, close_ts = closing_odds_for(
        markets, market_map, kickoff, rec.get("market"), rec.get("line"), rec.get("side")
    )
    if close_odds is None or close_ts is None:
        return None
    prod_odds = float(rec.get("odds", 0.0))
    # §3.6 時序防呆：推薦產出時間 >= 收盤抓取時間 → 無 CLV
    no_clv = produced >= config.parse_iso(close_ts)
    return {
        "closing_odds": close_odds,
        "closing_ts": close_ts,
        "production_odds": prod_odds,
        "clv_pct": None if no_clv else round(prod_odds / close_odds - 1.0, 4),
        "no_clv": no_clv,
    }


def _to_int(x) -> Optional[int]:
    try:
        return int(x)
    except (TypeError, ValueError):
        return None
