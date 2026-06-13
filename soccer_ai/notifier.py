"""板塊三：Discord 推播（notifier #4，架構 A）。

純呈現 storage 已存的推薦，**不選注、不改推薦**。推播失敗不阻斷 pipeline。
TEST_MODE → 推 test 頻道或略過（不污染正式）。去重免每小時洗頻（§4）。
#4 只實作 📋-推薦單 + 🧪-測試 兩把；📊-回測 / ⚠️-告警 env 在位、推播後續。
"""
from __future__ import annotations

import hashlib
import logging

import requests

from . import config, storage

logger = logging.getLogger(__name__)

_MAX_EMBEDS = 10   # Discord 單則訊息 embed 上限
_TIMEOUT = 10

_MARKET_ZH = {"handicap": "讓分", "over_under": "大小球"}
_SIDE_ZH = {"home": "主", "away": "客", "over": "大", "under": "小"}
# ⚠️ 純顯示層翻譯：英文 shape/signal key → 中文標籤。**絕不改 trajectory/selector/backtest
# 的內部 shape key**（那是 by_trajectory 統計/回測對應鍵，動了會錯、踩 §10）。
_SHAPE_SIGNAL_ZH = {
    # ⚠️ fav_swap=賠率反轉（低水方/被看好方中途換邊，非讓分換受讓）
    "fav_swap": "賠率反轉", "flat": "盤口持平", "monotonic": "單向走盤", "gradual": "緩步推移",
    "spike_revert": "急拉回吐", "late_swing": "臨場變盤", "choppy": "上下震盪", "odds_drift": "賠率單向飄",
    "mixed": "混合", "confirm": "順勢確認", "reverse": "逆勢背離", "insufficient": "資料不足",
}


def _zh(key) -> str:
    return _SHAPE_SIGNAL_ZH.get(key, key) if key else "—"


def _odds(v) -> str:
    """賠率顯示小數點後 2 位（儲存原始值/回測全精度不動）。"""
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return str(v)


# =========================================================================
# 去重（裁示：line/odds/stake 變 OR ai.available 由 false→true → 重推）
# =========================================================================
def _notify_hash(rec: dict) -> str:
    key = "|".join(str(rec.get(k)) for k in ("fixtureId", "market", "side", "line", "odds", "stake_units"))
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def should_notify(rec: dict) -> bool:
    """首次出單 / 下注關鍵欄變 / ai 由無轉有 → 推；AI 文字變或 ai 轉無 → 不推。"""
    if rec.get("notified_hash") != _notify_hash(rec):
        return True  # 首次（無 notified_hash）或 line/odds/stake 變
    now_avail = bool(rec.get("ai", {}).get("available"))
    return rec.get("notified_ai_available") is False and now_avail is True


# =========================================================================
# embed 組版
# =========================================================================
def _format_embed(rec: dict) -> dict:
    tag = "🧪 " if config.is_test_mode() else ""
    market = _MARKET_ZH.get(rec.get("market"), rec.get("market"))
    side = _SIDE_ZH.get(rec.get("side"), rec.get("side"))
    edge = f"{rec.get('edge_goals')}球" + (f"/{rec['edge_pct']:.1%}" if rec.get("edge_pct") else "")
    sig = rec.get("signals", {})
    fields = [
        {"name": "選注（系統數學）",
         "value": f"{market} **{side}** 線 {rec.get('line')} @ {_odds(rec.get('odds'))}　**{rec.get('stake_units')} 單位**　edge {edge}",
         "inline": False},
        {"name": "盤口軌跡（系統客觀）",
         "value": f"形狀 **{_zh(sig.get('shape'))}**　{sig.get('tag') or '—'}　訊號 **{_zh(sig.get('signal'))}**",
         "inline": False},
    ]
    if rec.get("settled"):
        sc = rec.get("score")
        rv = rec.get("result")
        val = (f"{rec.get('home','主')} **{sc['home']} : {sc['away']}** {rec.get('away','客')}（{rv}）"
               if isinstance(sc, dict) else f"（{rv}）")
        fields.append({"name": "🏁 賽果", "value": val, "inline": False})
    ai = rec.get("ai", {})
    if ai.get("available"):
        # Gemini 解讀已不限字數；但 Discord embed field value 硬上限 1024 字元，
        # 超出會被 API 退件。故此處截到 ~1000 + 指向網頁看完整（analyzer/網頁存完整不受影響）。
        def _dc(v):
            v = (v or "—").strip() or "—"
            return v if len(v) <= 1000 else v[:1000].rstrip() + "…（完整解讀見網頁）"
        fields += [
            {"name": "🤖 信心理由", "value": _dc(ai.get("confidence_reasoning")), "inline": False},
            {"name": "🤖 消息面推測（盤口反推）", "value": _dc(ai.get("injury_news_inference")), "inline": False},
            {"name": "🤖 盤口解讀", "value": _dc(ai.get("market_reading")), "inline": False},
        ]
    else:
        fields.append({"name": "🤖 AI 推論", "value": f"暫無（{ai.get('reason')}）", "inline": False})
    return {
        "title": f"{tag}{rec.get('home','?')} vs {rec.get('away','?')}",
        "description": f"🕐 {str(rec.get('kickoff_local',''))[:16]}",
        "color": 0x2ECC71 if rec.get("stake_units") == 2 else 0x3498DB,
        "fields": fields,
        "footer": {"text": "✅ 系統客觀數據　|　🤖 AI 推論（不參與選注）"},
    }


# =========================================================================
# 推播
# =========================================================================
def _webhook_url() -> "str | None":
    """依 TEST_MODE 選頻道。正式缺 url → None；測試缺 test url → None（略過不推）。"""
    if config.is_test_mode():
        return config.DISCORD_TEST_WEBHOOK_URL or None
    return config.DISCORD_WEBHOOK_URL or None


def _mark_notified(rec: dict) -> None:
    rec["notified_hash"] = _notify_hash(rec)
    rec["notified_at"] = config.now_local().isoformat()
    rec["notified_ai_available"] = bool(rec.get("ai", {}).get("available"))


def notify_batch(recs: list[dict]) -> dict:
    """整批彙總一則多 embed 推送（>10 分多則）。成功者回寫 notified_* 並重存。

    失敗不阻斷、告警記一次/輪。回 {sent, skipped, failed}。
    """
    stats = {"sent": 0, "skipped": 0, "failed": 0}
    if not recs:
        return stats
    url = _webhook_url()
    if not url:
        logger.info("無對應 webhook（%s），略過推播 %d 筆", "test" if config.is_test_mode() else "prod", len(recs))
        stats["skipped"] = len(recs)
        return stats

    err_once = None
    for i in range(0, len(recs), _MAX_EMBEDS):
        chunk = recs[i:i + _MAX_EMBEDS]
        payload = {"embeds": [_format_embed(r) for r in chunk]}
        try:
            resp = requests.post(url, json=payload, timeout=_TIMEOUT)
            if resp.status_code == 429:  # 尊重 retry_after 一次
                import time
                try:
                    time.sleep(min(float(resp.json().get("retry_after", 1)), 5))
                except (ValueError, AttributeError):
                    time.sleep(1)
                resp = requests.post(url, json=payload, timeout=_TIMEOUT)
            if resp.status_code >= 400:
                err_once = err_once or f"HTTP {resp.status_code}"
                stats["failed"] += len(chunk)
                continue
        except requests.RequestException as e:
            err_once = err_once or type(e).__name__
            stats["failed"] += len(chunk)
            continue
        for r in chunk:  # 成功 → 回寫 notified_* 並重存（失敗者不回寫 → 下輪重試）
            _mark_notified(r)
            try:
                storage.append_recommendation(r, date_local=config.local_date(r["kickoff_utc"]))
            except (KeyError, ValueError, OSError) as e:
                logger.warning("notified 回寫失敗 fixture=%s：%s", r.get("fixtureId"), e)
            stats["sent"] += 1

    if err_once:  # 告警只記一次/輪
        logger.warning("Discord 推播部分失敗（%d 筆，首錯 %s）", stats["failed"], err_once)
    return stats
