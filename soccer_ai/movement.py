"""板塊二：盤口走勢拉取 + 六錨點推導（架構 A，取代舊三窗口 snapshot）。

不搶時間窗、不靠排程準時：對每場拉 historical 完整序列（假設不計額度），
再從序列「切」出六錨點。規則寫死於 derive_anchors（規格書 §3.2）：
  錨點：initial / t24h / t12h / t6h / t1h / closing
  規則1 取最接近目標時刻的一筆 + 存實際時間戳/offset
  規則2 收盤=序列開賽前最後一筆，與 t1h 不同點
  規則3 目標時刻早於序列首筆 → 該錨點 null（不硬塞）
  initial=序列第一筆（莊家首次開盤價）
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from . import config, odds_parser, oddspapi_client, storage

logger = logging.getLogger(__name__)


# =========================================================================
# 市場對照表：快取優先，缺則抓一次（9MB，計入額度）後存檔重用
# =========================================================================
def ensure_market_map() -> dict:
    cached = storage.load_market_map()
    if cached:
        return {int(k): v for k, v in cached.items()}
    logger.info("市場對照表缺，抓 /markets 一次並快取")
    raw = oddspapi_client.get_markets_raw()
    market_map = odds_parser.build_market_map(raw)
    if market_map:
        storage.save_market_map(market_map)
    return market_map


# =========================================================================
# 六錨點推導
# =========================================================================
def _build_anchor(markets: dict, market_map: dict, target: datetime, timed: bool) -> dict:
    point = odds_parser.parse_point(markets, market_map, odds_parser.make_historical_price_fn(target))
    if timed:
        for key in ("handicap", "over_under"):
            sub = point.get(key)
            if sub and sub.get("captured_ts"):
                try:
                    sub["offset_sec"] = int((config.parse_iso(sub["captured_ts"]) - target).total_seconds())
                except ValueError:
                    sub["offset_sec"] = None
    return {"target_ts": target.isoformat(), **point}


def derive_anchors(markets: dict, market_map: dict, kickoff: datetime) -> dict:
    """從 historical 序列切六錨點。回 {anchor_name: {...}|None}。"""
    anchors: dict[str, Optional[dict]] = {name: None for name in config.ANCHOR_ORDER}
    times = odds_parser.collect_timestamps(markets, market_map)
    if not times:
        return anchors  # 全 null（尚未開盤）
    earliest, latest = times[0], times[-1]

    # initial = 序列第一筆
    anchors[config.ANCHOR_INITIAL] = _build_anchor(markets, market_map, earliest, timed=False)

    # closing = 開賽前最後一筆（規則2，§3.6）
    pre_kick = [t for t in times if t < kickoff]
    if pre_kick:
        anchors[config.ANCHOR_CLOSING] = _build_anchor(markets, market_map, pre_kick[-1], timed=False)

    # 四個 T-Nh：目標時刻落在序列觀測區間 [earliest, latest] 外 → null（規則3）
    #   target < earliest：盤開得晚，無此時段資料
    #   target > latest  ：時間還沒到（未來尚未發生），資料尚未存在
    # 兩者皆不得硬塞最接近的假裝有。
    for name, offset in config.ANCHOR_OFFSETS.items():
        target = kickoff - offset
        if target < earliest or target > latest:
            anchors[name] = None
        else:
            anchors[name] = _build_anchor(markets, market_map, target, timed=True)
    return anchors


# =========================================================================
# 單場處理
# =========================================================================
def _fixture_meta(fixture: dict) -> Optional[dict]:
    fid = fixture.get("fixtureId")
    start = fixture.get("startTime")
    if not isinstance(fid, str) or not isinstance(start, str):
        return None
    return {
        "fixtureId": fid,
        "home": str(fixture.get("participant1Name", "")),
        "away": str(fixture.get("participant2Name", "")),
        "startTime": start,
        "statusName": fixture.get("statusName", ""),
    }


def process_fixture(fixture: dict, market_map: dict, now: datetime, bookmaker: str) -> dict:
    """拉 historical → 推導六錨點 → 入庫。回處理摘要（不拋例外）。"""
    summary = {"fixtureId": None, "captured": False, "skipped": None, "closing_settled": False}
    meta = _fixture_meta(fixture)
    if meta is None:
        summary["skipped"] = "缺主鍵或開賽時間"
        return summary
    fid = meta["fixtureId"]
    summary["fixtureId"] = fid

    existing = storage.load_fixture_movement(fid)
    if existing and existing.get("closing_settled"):
        summary["skipped"] = "已定版收盤"
        return summary

    try:
        kickoff = config.to_utc(config.parse_iso(meta["startTime"]))
    except ValueError:
        summary["skipped"] = "開賽時間無法解析"
        return summary

    hist = oddspapi_client.get_historical_odds(fid, bookmaker)
    if hist is None:
        summary["skipped"] = "尚未開盤（historical 無資料）"
        return summary
    bm = hist.get("bookmakers", {})
    markets = bm.get(bookmaker, {}).get("markets") if isinstance(bm, dict) else None
    if not isinstance(markets, dict):
        summary["skipped"] = "無盤口市場"
        return summary

    anchors = derive_anchors(markets, market_map, kickoff)
    # 賽事已開賽且抓到收盤 → 定版，往後不再重抓
    closing_settled = now >= kickoff and anchors.get(config.ANCHOR_CLOSING) is not None

    record = {
        "fixtureId": fid,
        "tournamentId": config.WORLD_CUP_TOURNAMENT_ID,
        "sportId": config.SPORT_ID_SOCCER,
        "home": meta["home"],
        "away": meta["away"],
        "kickoff_utc": kickoff.isoformat(),
        "kickoff_local": config.to_local(kickoff).isoformat(),
        "bookmaker": bookmaker,
        "anchors": anchors,
        "closing_settled": closing_settled,
        "pulled_at_local": config.to_local(now).isoformat(),
    }
    storage.save_fixture_movement(record)
    summary["captured"] = True
    summary["closing_settled"] = closing_settled
    return summary


# =========================================================================
# 主入口
# =========================================================================
def scan(bookmaker: str = config.BOOKMAKER_PRIMARY) -> dict:
    now = config.now_local()
    market_map = ensure_market_map()
    if not market_map:
        logger.error("市場對照表為空，無法解析盤口，本次中止")
        return {"fixtures": 0, "captured": 0, "settled": 0, "error": "no_market_map"}

    fixtures = oddspapi_client.get_world_cup_fixtures()
    logger.info("走勢掃描開始：賽程 %d 場（bookmaker=%s, now=%s）", len(fixtures), bookmaker, now.isoformat())

    stats = {"fixtures": len(fixtures), "captured": 0, "settled": 0, "skipped": 0}
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            continue
        s = process_fixture(fixture, market_map, now, bookmaker)
        if s["captured"]:
            stats["captured"] += 1
        if s["closing_settled"]:
            stats["settled"] += 1
        if s["skipped"]:
            stats["skipped"] += 1

    acct = oddspapi_client.get_account()
    logger.info(
        "走勢掃描結束：擷取 %d / 定版收盤 %d / 略過 %d（額度 %s）",
        stats["captured"], stats["settled"], stats["skipped"],
        f"{acct['request_count']}/{acct['request_limit']}" if acct else "未知",
    )
    return stats
