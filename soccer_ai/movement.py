"""板塊二：盤口走勢拉取 + 八錨點軌跡分類（架構 A，schema v2）。

不搶時間窗、不靠排程準時：對每場、每個 bookmaker 拉 historical 完整序列
（假設不計額度），交 trajectory.build 切八錨點 + segment + summary。
CROWN 雙記：MOVEMENT_BOOKMAKERS（pinnacle + singbet）各記一套，存於 trajectory[book]。
缺場/未開盤的 book 該場 trajectory 缺，不影響其他 book（部分失敗分流）。
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Optional

from . import config, odds_parser, oddspapi_client, storage, trajectory

logger = logging.getLogger(__name__)

# placeholder 隊名（隊伍未定 → 莊家未開盤）：組位 1A/2B、第三名組合 3A/3B/...、
# 勝者 W73、亞軍 RU101、敗者 L101。真實全大寫隊名（如 USA）不含數字/斜線，不誤判。
_PLACEHOLDER_RE = re.compile(r"^(W\d+|RU\d+|L\d+|\d+[A-Z]+|[A-Z]{1,3}\d+)$")


def _is_placeholder_name(name: str) -> bool:
    name = (name or "").strip()
    return not name or "/" in name or bool(_PLACEHOLDER_RE.match(name))


def _teams_determined(fixture: dict) -> bool:
    return not (
        _is_placeholder_name(str(fixture.get("participant1Name", "")))
        or _is_placeholder_name(str(fixture.get("participant2Name", "")))
    )


def _anchor(record: Optional[dict], book: str, market: str, anchor: str):
    """安全取 trajectory[book][market].anchors[anchor]，缺則 None。"""
    if not isinstance(record, dict):
        return None
    m = record.get("trajectory", {}).get(book, {}).get(market, {})
    if not isinstance(m, dict):
        return None
    return m.get("anchors", {}).get(anchor)


def _initial_captured(record: Optional[dict]) -> bool:
    """任一 book 的讓分已存 initial → 視為遠期初盤已抓。"""
    return any(_anchor(record, b, "handicap", config.ANCHOR_INITIAL) for b in config.MOVEMENT_BOOKMAKERS)


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


def _build_book_trajectory(fid: str, book: str, market_map: dict, kickoff: datetime) -> "tuple[Optional[dict], Optional[str]]":
    """拉某 book 的 historical → 兩市場軌跡。回 (trajectory_dict, fail_reason)。"""
    try:
        hist = oddspapi_client.get_historical_odds(fid, book)
    except oddspapi_client.RateLimited:
        return (None, "rate_limited")
    if hist is None:
        return (None, "no_data")  # 404 未開盤
    markets = hist.get("bookmakers", {}).get(book, {}).get("markets") if isinstance(hist.get("bookmakers"), dict) else None
    if not isinstance(markets, dict):
        return (None, "no_markets")
    return ({
        "handicap": trajectory.build(markets, market_map, kickoff, "handicap"),
        "over_under": trajectory.build(markets, market_map, kickoff, "over_under"),
    }, None)


def process_fixture(fixture: dict, market_map: dict, now: datetime) -> dict:
    """逐 book 拉 historical → 軌跡 → 入庫。回處理摘要（不拋例外，部分失敗分流）。"""
    summary = {"fixtureId": None, "captured": False, "skipped": None, "closing_settled": False, "failed": False}
    meta = _fixture_meta(fixture)
    if meta is None:
        summary["skipped"] = "缺主鍵或開賽時間"
        return summary
    fid = meta["fixtureId"]
    summary["fixtureId"] = fid

    if not _teams_determined(fixture):  # placeholder → 未開盤，直接跳過不打 API
        summary["skipped"] = "隊伍未定（未開盤）"
        return summary

    existing = storage.load_fixture_movement(fid)
    if existing and existing.get("closing_settled"):
        summary["skipped"] = "已定版收盤"
        return summary

    try:
        kickoff = config.to_utc(config.parse_iso(meta["startTime"]))
    except ValueError:
        summary["skipped"] = "開賽時間無法解析"
        return summary

    ttk = kickoff - now
    if ttk > config.MOVEMENT_WINDOW:
        if _initial_captured(existing):
            summary["skipped"] = "遠期·初盤已存"
            return summary
    elif ttk < -config.SETTLE_GRACE:
        summary["skipped"] = "賽事已過（視窗外）"
        return summary

    # 逐 book 建軌跡
    traj: dict[str, dict] = {}
    fails = []
    for book in config.MOVEMENT_BOOKMAKERS:
        tj, reason = _build_book_trajectory(fid, book, market_map, kickoff)
        if tj is not None:
            traj[book] = tj
        elif reason == "rate_limited":
            fails.append(book)
    if not traj:
        summary["failed"] = bool(fails)
        summary["skipped"] = "抓取失敗（429）" if fails else "尚未開盤（historical 無資料）"
        return summary

    # 收盤定版：賽後且主 book 讓分已抓到 closing → 往後不再抓
    primary = config.MOVEMENT_BOOKMAKERS[0]
    closing_book = primary if primary in traj else next(iter(traj))
    closing_present = bool(traj[closing_book]["handicap"]["anchors"].get(config.ANCHOR_CLOSING))
    closing_settled = now >= kickoff and closing_present

    record = {
        "schema_version": config.SCHEMA_VERSION,
        "fixtureId": fid,
        "tournamentId": config.WORLD_CUP_TOURNAMENT_ID,
        "sportId": config.SPORT_ID_SOCCER,
        "home": meta["home"],
        "away": meta["away"],
        "kickoff_utc": kickoff.isoformat(),
        "kickoff_local": config.to_local(kickoff).isoformat(),
        "books": list(traj.keys()),
        "trajectory": traj,
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
def scan() -> dict:
    now = config.now_local()
    market_map = ensure_market_map()
    if not market_map:
        logger.error("市場對照表為空，無法解析盤口，本次中止")
        return {"fixtures": 0, "captured": 0, "settled": 0, "error": "no_market_map"}

    fixtures = oddspapi_client.get_world_cup_fixtures()
    logger.info("走勢掃描開始：賽程 %d 場（books=%s, now=%s）",
                len(fixtures), config.MOVEMENT_BOOKMAKERS, now.isoformat())

    stats = {"fixtures": len(fixtures), "captured": 0, "settled": 0, "skipped": 0, "failed": 0}
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            continue
        s = process_fixture(fixture, market_map, now)
        if s["captured"]:
            stats["captured"] += 1
        if s["closing_settled"]:
            stats["settled"] += 1
        if s.get("failed"):
            stats["failed"] += 1
        elif s["skipped"]:
            stats["skipped"] += 1

    acct = oddspapi_client.get_account()
    logger.info(
        "走勢掃描結束：擷取 %d / 定版收盤 %d / 略過 %d / 抓取失敗 %d（額度 %s）",
        stats["captured"], stats["settled"], stats["skipped"], stats["failed"],
        f"{acct['request_count']}/{acct['request_limit']}" if acct else "未知",
    )
    return stats
