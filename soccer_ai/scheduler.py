"""板塊四：逐場事件驅動排程（tick）。與 main_pipeline（每小時全掃）**並行、可回退**。

設計（總司令 2026-06-07 拍板）：
- cron `*/30`（event_pipeline.yml），每輪**只處理「落在自己錨點窗內」的場**，非全掃 104 場（省額度、#4）。
- 每場在自己 t30m（開賽前 30 分）那輪觸發 movement 抓取 + select；其餘決策錨點(t72h..t1h)經過時亦補抓走勢。
- **catch-up**：historical 回整條序列、trajectory 取最近 target 的點，故 t30m 那輪若延遲/跳過，
  下一輪（甚至賽後 settle 輪）仍會把 t30m 從完整序列補上；「補抓·偏收盤」由既有 `offset_sec` 在顯示層判（不動 trajectory/storage）。
- **額度**：fixtures 改快取（每日 1 次）+ historical 免費 + select 每場去重一次（≤104×2≤208 通）；request_count 接近 250 告警。

絕不動：trajectory 判定 / selector edge / storage 既有格式 / analyzer。只加「何時觸發抓哪場」的編排 + 2 新檔。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from . import config, movement, oddspapi_client, storage

logger = logging.getLogger(__name__)

_FIXTURES_CACHE = "fixtures_cache.json"
_TICK_STATE = "tick_state.json"


def _path(name: str):
    return config.data_dir() / name


# =========================================================================
# fixtures 快取（準靜態：104 場 + kickoff 固定 → 每日刷，免每輪計額度）
# =========================================================================
def load_fixtures_cached(now: datetime) -> "tuple[list, bool]":
    """回 (fixtures, refetched)。快取未過期 → 用快取（0 額度）；否則打 API（計 1）並寫快取。"""
    data = storage._read_json(_path(_FIXTURES_CACHE))
    if isinstance(data, dict) and isinstance(data.get("fixtures"), list) and data.get("fetched_utc"):
        try:
            if now - config.parse_iso(data["fetched_utc"]) < timedelta(hours=config.FIXTURES_CACHE_TTL_H):
                return data["fixtures"], False
        except ValueError:
            pass
    fixtures = oddspapi_client.get_world_cup_fixtures()
    if fixtures:
        storage._atomic_write_json(_path(_FIXTURES_CACHE),
                                   {"fetched_utc": now.astimezone(timezone.utc).isoformat(), "fixtures": fixtures})
    return fixtures, True


# =========================================================================
# 錨點目標時刻 + tick 規劃（**純函式**：無 I/O、無副作用，便於模擬驗證）
# =========================================================================
def anchor_targets(kickoff: datetime) -> dict:
    """決策錨點 target = kickoff - offset；closing target = kickoff。"""
    t = {a: kickoff - off for a, off in config.ANCHOR_OFFSETS.items()}
    t[config.ANCHOR_CLOSING] = kickoff
    return t


def plan_tick(fixtures: list, state: dict, now: datetime) -> dict:
    """純函式：回 {active, scan, select, select_fids}。

    - active：在「t72h ~ kickoff+settle_grace」窗內的場（只處理這些，#4 不全掃）。
    - scan：有「已過 target 但未捕捉」的錨點 → 需抓 movement（免費）。
    - select_fids：t30m 已過、未 select、仍賽前 → 該場觸發 select（去重防重複爆額度）。
    """
    active, scan, select_fids = [], [], []
    for f in fixtures:
        fid, start = f.get("fixtureId"), f.get("startTime")
        if not isinstance(fid, str) or not isinstance(start, str):
            continue
        try:
            kickoff = config.to_utc(config.parse_iso(start))
        except ValueError:
            continue
        targets = anchor_targets(kickoff)
        t72h = targets[config.ANCHOR_DECISION[0]]
        if not (t72h <= now <= kickoff + config.SETTLE_GRACE):  # 活躍窗外 → 略過（不掃）
            continue
        active.append(fid)
        st = state.get(fid) or {}
        captured = set(st.get("captured", []))
        if any(tt <= now and a not in captured for a, tt in targets.items()):
            scan.append(fid)
        if now >= targets[config.ANCHOR_DECISION[-1]] and now < kickoff and not st.get("select_done"):
            select_fids.append(fid)  # t30m 已過、仍賽前、未做 → select due
    return {"active": active, "scan": scan, "select": bool(select_fids), "select_fids": select_fids}


# =========================================================================
# tick 主入口（執行：掃 due 場 + 視情況跑 select；持久化狀態）
# =========================================================================
def _alert_quota():
    acct = oddspapi_client.get_account()
    if acct and acct.get("remaining", 999) <= config.REQUEST_ALERT_REMAINING:
        logger.warning("⚠️ OddsPapi 額度剩 %s（≤%s）—— 接近 %s 月限",
                       acct["remaining"], config.REQUEST_ALERT_REMAINING, config.MONTHLY_REQUEST_LIMIT)
    return acct


def run_tick(select_fn, now: "datetime | None" = None) -> dict:
    """select_fn：注入的「跑 select→存推薦/觀察場」流程（由 main 提供，避免循環匯入）。"""
    now = now or config.to_utc(config.now_local())
    market_map = movement.ensure_market_map()
    if not market_map:
        logger.error("tick：市場對照表為空，中止")
        return {"error": "no_market_map"}

    fixtures, refetched = load_fixtures_cached(now)
    state = storage._read_json(_path(_TICK_STATE))
    state = state if isinstance(state, dict) else {}
    plan = plan_tick(fixtures, state, now)
    logger.info("tick now=%s：active %d / 掃描 %d / select_due %d（fixtures 快取刷新=%s）",
                now.isoformat(), len(plan["active"]), len(plan["scan"]), len(plan["select_fids"]), refetched)

    fx = {f.get("fixtureId"): f for f in fixtures}
    scanned = 0
    for fid in plan["scan"]:
        s = movement.process_fixture(fx[fid], market_map, config.now_local())  # historical（免費）
        st = state.setdefault(fid, {"captured": [], "select_done": False})
        if s.get("captured"):
            kickoff = config.to_utc(config.parse_iso(fx[fid]["startTime"]))
            targets = anchor_targets(kickoff)
            st["captured"] = sorted({*st.get("captured", []), *[a for a, tt in targets.items() if tt <= now]})
            st["last_scan_utc"] = now.astimezone(timezone.utc).isoformat()
            scanned += 1

    if plan["select"]:                          # 有場 t30m due → 跑一次（tournament-wide 覆蓋全部窗內場）
        select_fn()
        for fid in plan["select_fids"]:
            state.setdefault(fid, {"captured": [], "select_done": False})["select_done"] = True

    storage._atomic_write_json(_path(_TICK_STATE), state)
    acct = _alert_quota()
    return {"active": len(plan["active"]), "scanned": scanned, "selected": plan["select"],
            "fixtures_refetched": refetched, "request_count": acct.get("request_count") if acct else None}
