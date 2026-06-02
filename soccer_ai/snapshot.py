"""板塊二：三窗口容錯快照（系統核心）。

§3.2 設計精神：不依賴精確時間點。每次排程只檢查「哪些賽事在指定窗口內、
且尚未抓取」，補抓並標記完成；超時未抓的收盤標記缺失。

額度紀律：
  - 每場每次最多一次 /odds 呼叫（同一回應可同時滿足初盤與當前時窗）。
  - 抓取前過 api_client.window_allowed()（收盤絕對優先生存法則）。
  - 全程偵測 quota_exhausted()，達告警門檻即停手。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from . import api_client, config, odds_parser, storage

logger = logging.getLogger(__name__)


def _parse_kickoff_utc(fixture: dict) -> Optional[datetime]:
    """從 fixture 取開賽時間（API 回 ISO 帶時區）。"""
    fx = fixture.get("fixture")
    if not isinstance(fx, dict):
        return None
    date_str = fx.get("date")
    if not isinstance(date_str, str):
        return None
    try:
        dt = datetime.fromisoformat(date_str)
    except ValueError:
        logger.warning("無法解析開賽時間：%s", date_str)
        return None
    return config.to_utc(dt)


def _extract_meta(fixture: dict) -> Optional[dict]:
    """取 fixture_id / 隊名。fixture_id 為主鍵，缺則跳過該場。"""
    fx = fixture.get("fixture")
    teams = fixture.get("teams")
    if not isinstance(fx, dict) or not isinstance(teams, dict):
        return None
    fid = fx.get("id")
    if not isinstance(fid, int):
        return None
    home = teams.get("home") if isinstance(teams.get("home"), dict) else {}
    away = teams.get("away") if isinstance(teams.get("away"), dict) else {}
    return {
        "fixture_id": fid,
        "home": str(home.get("name", "")),
        "away": str(away.get("name", "")),
    }


def _active_timed_window(ttk: timedelta) -> Optional[str]:
    """依開賽前剩餘時間 ttk 判定當前落在哪個『有時窗』的窗口（mid / closing）。"""
    if config.CLOSING_WINDOW_CLOSE <= ttk <= config.CLOSING_WINDOW_OPEN:
        return config.WINDOW_CLOSING
    if config.MID_WINDOW_CLOSE <= ttk <= config.MID_WINDOW_OPEN:
        return config.WINDOW_MID
    return None


def process_fixture(fixture: dict, now: datetime) -> dict:
    """處理單場：判定待抓窗口 → 必要時抓盤 → 寫庫。

    回傳本場處理摘要（供 main 彙總），不拋例外（部分失敗不阻斷）。
    """
    summary = {"fixture_id": None, "captured": [], "skipped": None, "closing_missing": False}
    meta = _extract_meta(fixture)
    kickoff = _parse_kickoff_utc(fixture)
    if meta is None or kickoff is None:
        summary["skipped"] = "缺主鍵或開賽時間"
        return summary

    fid = meta["fixture_id"]
    summary["fixture_id"] = fid
    ttk = kickoff - now  # 開賽前剩餘時間

    rec = storage.load_snapshot(fid)
    base = rec or storage.init_snapshot_record(
        fid, meta["home"], meta["away"],
        kickoff_utc=kickoff.isoformat(),
        kickoff_local=config.to_local(kickoff).isoformat(),
    )

    has_initial = bool(rec) and rec.get("snapshots", {}).get(config.WINDOW_INITIAL) is not None

    # 收盤缺失偵測：已過收盤窗下緣仍未抓收盤 → 標記缺失（不需再耗額度）
    closing_done = bool(rec) and rec.get("snapshots", {}).get(config.WINDOW_CLOSING) is not None
    if ttk < config.CLOSING_WINDOW_CLOSE and not closing_done:
        if rec and not rec.get("closing_missing"):
            storage.mark_closing_missing(fid)
            summary["closing_missing"] = True
            logger.warning("收盤缺失：fixture %s（%s vs %s）", fid, meta["home"], meta["away"])
        elif not rec:
            summary["closing_missing"] = True  # 從未抓過任何窗口的已過期賽事

    # 已開賽 → 不再抓任何窗口
    if ttk <= timedelta(0):
        summary["skipped"] = "已開賽"
        return summary

    # 判定本次待抓窗口
    active = _active_timed_window(ttk)
    need_active = active is not None and not (
        rec and rec.get("snapshots", {}).get(active) is not None
    )
    need_initial = (not has_initial) and ttk <= config.INITIAL_SCAN_HORIZON

    if not need_active and not need_initial:
        summary["skipped"] = "無待抓窗口"
        return summary

    # 生存法則 / 額度防線（以待抓的最高優先窗口判定放行）
    target_window = active if need_active else config.WINDOW_INITIAL
    if not api_client.window_allowed(target_window):
        summary["skipped"] = f"生存模式拒絕 {target_window}"
        return summary
    if api_client.quota_exhausted():
        summary["skipped"] = "額度告警門檻，停手"
        return summary

    # 抓盤（單次呼叫，供初盤與當前時窗共用）
    odds_response = api_client.get_fixture_odds(fid)
    captured_at = config.to_local(now).isoformat()
    payload = odds_parser.parse_odds_snapshot(odds_response, captured_at)
    if payload is None:
        summary["skipped"] = "尚無有效盤口"
        return summary

    # 寫入：當前時窗
    if need_active and api_client.window_allowed(active):
        storage.save_window(fid, active, base, payload)
        summary["captured"].append(active)
        base = storage.load_snapshot(fid) or base

    # 寫入：初盤（首見盤口即記）
    if need_initial and api_client.window_allowed(config.WINDOW_INITIAL):
        storage.save_window(fid, config.WINDOW_INITIAL, base, payload)
        summary["captured"].append(config.WINDOW_INITIAL)

    return summary


def run_snapshot_scan() -> dict:
    """主入口：抓世界盃賽程 → 逐場處理三窗口。回傳整體統計。"""
    now = config.now_local()
    fixtures = api_client.get_world_cup_fixtures()
    logger.info("快照掃描開始：賽程 %d 場（now=%s）", len(fixtures), now.isoformat())

    stats = {
        "fixtures": len(fixtures),
        "captured_initial": 0,
        "captured_mid": 0,
        "captured_closing": 0,
        "closing_missing": 0,
        "details": [],
    }
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            continue
        if api_client.quota_exhausted():
            logger.warning("達額度告警門檻，中止掃描剩餘賽事")
            break
        s = process_fixture(fixture, now)
        for w in s["captured"]:
            stats[f"captured_{w}"] += 1
        if s["closing_missing"]:
            stats["closing_missing"] += 1
        if s["captured"] or s["closing_missing"]:
            stats["details"].append(s)

    logger.info(
        "快照掃描結束：初盤 +%d / 中段 +%d / 收盤 +%d / 收盤缺失 %d（剩餘額度=%s）",
        stats["captured_initial"], stats["captured_mid"], stats["captured_closing"],
        stats["closing_missing"], api_client.remaining(),
    )
    return stats
