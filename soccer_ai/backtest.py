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


def _to_int(x) -> Optional[int]:
    try:
        return int(x)
    except (TypeError, ValueError):
        return None
