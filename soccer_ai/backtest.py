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
from datetime import timedelta
from typing import Optional

from . import config, movement, oddspapi_client, storage

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


# =========================================================================
# 命中率 / 單位損益 / CLV 彙總
# =========================================================================
_DECIDED = ("WIN", "HALFWIN", "PUSH", "HALFLOSS", "LOSE")
_WIN_WEIGHT = {"WIN": 1.0, "HALFWIN": 0.5}
_LOSE_WEIGHT = {"LOSE": 1.0, "HALFLOSS": 0.5}


def compute_metrics(recs: list) -> dict:
    """彙總命中率、單位損益、ROI、CLV 統計。命中率 PUSH 不計入分母，半贏半輸計 0.5。"""
    decided = [r for r in recs if r.get("settled") and r.get("result") in _DECIDED]
    w = sum(_WIN_WEIGHT.get(r["result"], 0.0) for r in decided)
    l = sum(_LOSE_WEIGHT.get(r["result"], 0.0) for r in decided)
    staked = sum(float(r.get("stake_units", 1)) for r in decided)
    units = sum(float(r.get("pnl_units", 0.0)) for r in decided)
    clvs = [
        r["clv"]["clv_pct"] for r in recs
        if isinstance(r.get("clv"), dict) and r["clv"].get("clv_pct") is not None
    ]
    return {
        "total": len(recs),
        "decided": len(decided),
        "hit_rate": round(w / (w + l), 4) if (w + l) > 0 else None,
        "units": round(units, 4),
        "roi": round(units / staked, 4) if staked > 0 else None,
        "avg_clv_pct": round(sum(clvs) / len(clvs), 4) if clvs else None,
        "beat_close_rate": round(sum(1 for c in clvs if c > 0) / len(clvs), 4) if clvs else None,
        "breakdown": {res: sum(1 for r in decided if r["result"] == res) for res in _DECIDED},
        "by_trajectory": _by_trajectory(decided),
    }


def _by_trajectory(decided: list) -> dict:
    """依凍結的軌跡 shape 分組 → 各形狀的命中率/單位/筆數（回答「某種軌跡→真實過盤率」）。"""
    groups: dict[str, list] = {}
    for r in decided:
        shape = (r.get("signals") or {}).get("shape") or "unknown"
        groups.setdefault(shape, []).append(r)
    out = {}
    for shape, rs in groups.items():
        w = sum(_WIN_WEIGHT.get(r["result"], 0.0) for r in rs)
        l = sum(_LOSE_WEIGHT.get(r["result"], 0.0) for r in rs)
        out[shape] = {
            "n": len(rs),
            "hit_rate": round(w / (w + l), 4) if (w + l) > 0 else None,
            "units": round(sum(float(r.get("pnl_units", 0.0)) for r in rs), 4),
        }
    return out


def run_backfill(date_local: Optional[str] = None, bookmaker: str = config.BOOKMAKER_PRIMARY) -> dict:
    """回填某日推薦的賽果 + CLV，存回並回彙總。預設前一日（UTC+8，§回測隔日回填）。"""
    if date_local is None:
        date_local = (config.now_local() - timedelta(days=1)).strftime("%Y-%m-%d")
    recs = storage.load_recommendations(date_local)
    if not recs:
        logger.info("回測：%s 無推薦記錄", date_local)
        return {"date": date_local, "total": 0}

    market_map = movement.ensure_market_map()
    if not market_map:
        logger.error("回測：市場對照表為空，無法結算")
        return {"date": date_local, "total": len(recs), "error": "no_market_map"}

    for r in recs:
        settle_recommendation(r, market_map)
        clv = compute_clv(r, market_map, bookmaker)
        r["clv"] = clv if clv is not None else "無 CLV（資料不足）"
    storage.save_recommendations(recs, date_local)

    m = compute_metrics(recs)
    m["date"] = date_local
    logger.info(
        "回測 %s：命中率 %s / 單位 %s / ROI %s / 平均CLV %s / 擊敗收盤率 %s（已結算 %d/%d）",
        date_local, m["hit_rate"], m["units"], m["roi"], m["avg_clv_pct"],
        m["beat_close_rate"], m["decided"], m["total"],
    )
    return m


def _to_int(x) -> Optional[int]:
    try:
        return int(x)
    except (TypeError, ValueError):
        return None
