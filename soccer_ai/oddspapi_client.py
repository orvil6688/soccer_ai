"""板塊一：OddsPapi v4 抓取（節流 / 429 退避 / 額度監控 / isinstance）。

主資料源（架構 A）。base=https://api.oddspapi.io/v4，認證 query ?apiKey=。
失敗分流：金鑰缺 → 致命（require_key 拋錯）；單次請求錯 → 具名攔截回 None 不阻斷。

端點（已實打驗證，見 docs/oddspapi_findings.md）：
  /sports /tournaments /fixtures /markets （計入額度）
  /odds-by-tournaments （計入額度）
  /historical-odds （不計額度——未經官方確認的假設）
  /settlements /account （account 不計額度）
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import requests

from . import config

logger = logging.getLogger(__name__)

_last_request_ts = 0.0
_TIMEOUT = 30


def _throttle() -> None:
    global _last_request_ts
    gap = time.monotonic() - _last_request_ts
    if gap < config.MIN_REQUEST_INTERVAL_SEC:
        time.sleep(config.MIN_REQUEST_INTERVAL_SEC - gap)
    _last_request_ts = time.monotonic()


def _request(path: str, params: Optional[dict] = None) -> Optional[dict]:
    """單次 GET（自動帶 apiKey、語言前綴非必需）。

    回傳解析後 JSON（dict 或 list 包成 {'_list':...}？不——直接回原物件）。
    429 依 Retry-After 退避重試；其他錯誤具名攔截回 None。
    """
    params = dict(params or {})
    params["apiKey"] = config.require_key("ODDSPAPI_API_KEY")
    url = f"{config.ODDSPAPI_BASE}/{path.lstrip('/')}"

    for attempt in range(config.MAX_RETRY_ON_429 + 1):
        _throttle()
        try:
            resp = requests.get(url, params=params, timeout=_TIMEOUT)
        except requests.RequestException as e:
            logger.warning("OddsPapi 請求失敗 %s — %s", path, e)
            return None

        if resp.status_code == 429:
            wait = _retry_after_sec(resp)
            if attempt < config.MAX_RETRY_ON_429:
                logger.info("429 節流 %s，等 %.1fs 重試（第 %d 次）", path, wait, attempt + 1)
                time.sleep(wait)
                continue
            logger.warning("429 節流 %s 重試耗盡", path)
            return None

        if resp.status_code != 200:
            # 404 可能是「無資料」或「端點不存在」，交由呼叫端判讀
            logger.debug("OddsPapi 非 200：%s → %s | %s", path, resp.status_code, resp.text[:160])
            return None

        try:
            return resp.json()
        except ValueError as e:
            logger.warning("OddsPapi 回應非 JSON：%s — %s", path, e)
            return None
    return None


def _retry_after_sec(resp: requests.Response) -> float:
    raw = resp.headers.get("Retry-After")
    if raw:
        try:
            return min(float(raw), 5.0)
        except ValueError:
            pass
    return 1.5


def _as_list(payload) -> list:
    """契約 D：保證回 list。"""
    return payload if isinstance(payload, list) else []


# =========================================================================
# 額度監控（/account 不計額度）
# =========================================================================
def get_account() -> Optional[dict]:
    """回 {'request_count':int,'request_limit':int,'plan':str,'remaining':int} 或 None。"""
    payload = _request("account")
    if not isinstance(payload, dict):
        return None
    subs = payload.get("subscriptions")
    if not isinstance(subs, list) or not subs or not isinstance(subs[0], dict):
        return None
    s = subs[0]
    used = s.get("request_count")
    limit = s.get("request_limit")
    if not isinstance(used, int) or not isinstance(limit, int):
        return None
    return {
        "request_count": used,
        "request_limit": limit,
        "plan": s.get("plan", ""),
        "remaining": max(limit - used, 0),
    }


# =========================================================================
# 賽事 / 市場
# =========================================================================
def get_world_cup_fixtures() -> list[dict]:
    """世界盃所有場次（計入額度）。"""
    payload = _request("fixtures", {"tournamentId": config.WORLD_CUP_TOURNAMENT_ID})
    return [f for f in _as_list(payload) if isinstance(f, dict)]


def get_markets_raw(sport_id: int = config.SPORT_ID_SOCCER) -> list[dict]:
    """市場分類原始清單（≈9MB、計入額度；應由 movement 快取後重用）。"""
    payload = _request("markets", {"sportId": sport_id})
    return [m for m in _as_list(payload) if isinstance(m, dict)]


# =========================================================================
# 盤口
# =========================================================================
def get_historical_odds(fixture_id: str, bookmaker: str) -> Optional[dict]:
    """單場某 bookmaker 的完整賽前走勢序列（假設不計額度）。

    回 {'fixtureId':..,'bookmakers':{<slug>:{'markets':{..}}}}；無資料(404)回 None。
    """
    payload = _request("historical-odds", {"fixtureId": fixture_id, "bookmaker": bookmaker})
    return payload if isinstance(payload, dict) and "bookmakers" in payload else None


def get_odds_by_tournament(bookmaker: str) -> list[dict]:
    """整賽事批量現況盤（計入額度；退場/即時用途）。"""
    payload = _request(
        "odds-by-tournaments",
        {"bookmaker": bookmaker, "tournamentIds": config.WORLD_CUP_TOURNAMENT_ID},
    )
    return [f for f in _as_list(payload) if isinstance(f, dict)]


def get_settlements(fixture_id: str) -> Optional[dict]:
    """單場結算（賽果）。回 {'fixtureId':..,'markets':{<mid>:{'outcomes':{<oid>:{'players':{'0':{'result':..}}}}}}}。"""
    payload = _request("settlements", {"fixtureId": fixture_id})
    return payload if isinstance(payload, dict) and "markets" in payload else None
