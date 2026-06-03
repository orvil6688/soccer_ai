"""板塊一：API-Football 抓取（節流 / 額度控管 / 收盤優先鉤子 / isinstance）。

§3.2 API 生存法則、§3.3 Rate Limit 在此落地。
失敗分流：金鑰缺 → 致命（require_key 拋錯）；單次請求錯 → 具名攔截、log、回 None 不阻斷。
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import requests

from . import config

logger = logging.getLogger(__name__)

# 節流：免費層約 10 次/分，保守設每次請求間隔
_MIN_INTERVAL_SEC = 1.2
_last_request_ts = 0.0

# 當日剩餘額度快取（由回應標頭 / get_status 更新；None=尚未知）
_remaining: Optional[int] = None
_TIMEOUT = 15


def _headers() -> dict:
    return {"x-apisports-key": config.require_key("API_FOOTBALL_KEY")}


def _throttle() -> None:
    global _last_request_ts
    gap = time.monotonic() - _last_request_ts
    if gap < _MIN_INTERVAL_SEC:
        time.sleep(_MIN_INTERVAL_SEC - gap)
    _last_request_ts = time.monotonic()


def _update_remaining_from_headers(resp: requests.Response) -> None:
    global _remaining
    raw = resp.headers.get("x-ratelimit-requests-remaining")
    if raw is not None:
        try:
            _remaining = int(raw)
        except ValueError:
            pass


def remaining() -> Optional[int]:
    """回傳當前已知的當日剩餘額度（None=尚未查詢）。"""
    return _remaining


def _request(path: str, params: dict) -> Optional[dict]:
    """單次 GET。回傳整個 JSON dict；網路/HTTP 錯誤具名攔截回 None（部分失敗）。"""
    _throttle()
    url = f"{config.API_FOOTBALL_BASE}/{path.lstrip('/')}"
    try:
        resp = requests.get(url, headers=_headers(), params=params, timeout=_TIMEOUT)
    except requests.RequestException as e:
        logger.warning("API 請求失敗 %s %s — %s", path, params, e)
        return None
    _update_remaining_from_headers(resp)
    if resp.status_code != 200:
        logger.warning("API 非 200：%s %s → %s", path, params, resp.status_code)
        return None
    try:
        payload = resp.json()
    except ValueError as e:
        logger.warning("API 回應非 JSON：%s — %s", path, e)
        return None
    if not isinstance(payload, dict):  # isinstance 防禦（契約 D）
        logger.warning("API 回應頂層非 dict：%s", path)
        return None
    errors = payload.get("errors")
    if errors:  # API-Football 把業務錯誤放 errors（dict 或 list）
        logger.warning("API errors：%s → %s", path, errors)
    return payload


def _response_array(payload: Optional[dict]) -> list:
    """安全取出 payload['response'] 並保證為 list（契約 D）。"""
    if not isinstance(payload, dict):
        return []
    arr = payload.get("response")
    return arr if isinstance(arr, list) else []


# =========================================================================
# 額度 / 生存法則
# =========================================================================
def get_status() -> Optional[dict]:
    """查當前訂閱與用量（/status 不計入每日額度）。

    回傳 {"limit": int, "used": int, "remaining": int} 或 None。
    """
    payload = _request("status", {})
    if not isinstance(payload, dict):
        return None
    resp = payload.get("response")
    if not isinstance(resp, dict):
        return None
    requests_info = resp.get("requests")
    if not isinstance(requests_info, dict):
        return None
    used = requests_info.get("current")
    limit = requests_info.get("limit_day")
    if not isinstance(used, int) or not isinstance(limit, int):
        return None
    global _remaining
    _remaining = max(limit - used, 0)
    return {"limit": limit, "used": used, "remaining": _remaining}


def window_allowed(window: str) -> bool:
    """API 生存法則（§3.2 收盤絕對優先）。

    剩餘 <= API_SURVIVAL_THRESHOLD 時，拒絕 initial/mid，只放行 closing。
    剩餘未知時放行（首跑會先 get_status 取得）。
    """
    if _remaining is None:
        return True
    if _remaining <= config.API_SURVIVAL_THRESHOLD:
        return window == config.WINDOW_CLOSING
    return True


def quota_exhausted() -> bool:
    """達告警門檻（已用 >= 95 → 剩餘 <= limit-95）→ 應中止當次執行（§3.3）。"""
    if _remaining is None:
        return False
    return _remaining <= (config.API_DAILY_LIMIT - config.API_ALERT_THRESHOLD)


# =========================================================================
# 賽事 / 盤口
# =========================================================================
def get_world_cup_fixtures(season: Optional[int] = None) -> list[dict]:
    """抓世界盃賽程。回傳 fixture 原始 dict 陣列（已 isinstance 過濾）。"""
    season = season or config.WORLD_CUP_SEASON
    payload = _request(
        "fixtures",
        {"league": config.WORLD_CUP_LEAGUE_ID, "season": season},
    )
    return [f for f in _response_array(payload) if isinstance(f, dict)]


def get_fixtures_by_date(date_str: str) -> list[dict]:
    """抓指定日期（YYYY-MM-DD）世界盃賽事，供 Phase 2 回測抓賽果用。"""
    payload = _request(
        "fixtures",
        {"league": config.WORLD_CUP_LEAGUE_ID, "season": config.WORLD_CUP_SEASON, "date": date_str},
    )
    return [f for f in _response_array(payload) if isinstance(f, dict)]


def get_fixture_odds(fixture_id: int) -> list:
    """抓單場盤口（讓分 bet4 + 大小球 bet5 同回應，選擇交給 odds_parser）。

    不傳 bet 參數，使單次請求即涵蓋兩種盤口（節省額度）。回傳 response 陣列。
    """
    payload = _request(
        "odds",
        {
            "league": config.WORLD_CUP_LEAGUE_ID,
            "season": config.WORLD_CUP_SEASON,
            "fixture": int(fixture_id),
        },
    )
    return _response_array(payload)
