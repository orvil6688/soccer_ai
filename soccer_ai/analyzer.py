"""板塊三：Gemini 開盤手推論層（analyzer #3，架構 A）。

定位：系統＝事實層（客觀軌跡）；本檔＝推論層（讀事實推意圖，強制 🤖、不改數據、不選注）。
產出三欄敘述包進 pick 的 `ai{}` 區塊，與系統客觀層（signals/trajectory）結構性隔離。
金鑰 config.GEMINI_API_KEY（env，不硬編）；SDK＝google-genai（新版）。

失敗分流：逐 pick 隔離、不阻斷 pipeline；金鑰缺/insufficient/API 錯 → ai.available=False。
TEST_MODE：一律 mock，不真打、不燒額度。
快取：summary_hash 未變 → 沿用 prior_ai，不重打 Gemini。
"""
from __future__ import annotations

import hashlib
import json
import logging

from . import config

logger = logging.getLogger(__name__)

AI_FIELDS = list(config.WORD_BUDGET)  # confidence_reasoning / injury_news_inference / market_reading

PERSONA = (
    "你是世界盃資深開盤手，深諳莊家如何用盤口操控散戶心理，也懂玩家心理。\n"
    "以下是系統「客觀記錄」的盤口軌跡事實（八錨點、賠率、軌跡形狀皆為中性描述）。\n"
    "你的任務：以開盤手視角推論莊家意圖與市場心理。只解讀，不得修改任何數據、不得重命名軌跡形狀、不參與選注決策。\n"
    "所有判斷皆為推論；務必講具體、避免空話套話。\n"
    "嚴格只輸出 JSON 物件，三個鍵：\n"
    "- confidence_reasoning：對此注的信心理由（基於盤口軌跡與 edge）。\n"
    "- injury_news_inference：由盤口異動反推的傷病/陣容消息推測；僅盤口反推，不得宣稱已證實傷情。\n"
    "- market_reading：莊家意圖與市場心理推論（如疑似洗盤/誘盤/消息走漏/後場 sharp 錢）。\n"
    "**不限字數**：把推論講完整、具體、有層次（盤口怎麼動→可能意圖→對散戶心理的作用）；"
    "但只講盤口能支撐的推論，避免空話套話與無資訊的湊字。\n"
    "一律繁體中文。不要輸出 JSON 以外的任何文字。"
)

_client = None


def _get_client():
    global _client
    if _client is None:
        from google import genai
        from google.genai import types
        _client = genai.Client(
            api_key=config.require_key("GEMINI_API_KEY"),
            http_options=types.HttpOptions(timeout=20000),
        )
    return _client


# =========================================================================
# 輔助
# =========================================================================
def _truncate(text: str, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _summary_hash(pick: dict) -> str:
    """(fixtureId, market, side, 凍結軌跡摘要 + shape) 的 sha1，作快取/覆寫判定鍵。"""
    payload = {
        "fixtureId": pick.get("fixtureId"),
        "market": pick.get("market"),
        "side": pick.get("side"),
        "trajectory": pick.get("trajectory"),
        "shape": pick.get("signals", {}).get("shape"),
    }
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def _is_insufficient(pick: dict) -> bool:
    """決策窗未填（shape=insufficient/None）→ 不打 Gemini。"""
    return pick.get("signals", {}).get("shape") in (None, "insufficient")


def _render_trajectory(record: dict, book: str, market: str) -> str:
    tj = record.get("trajectory", {}).get(book, {}).get(market) if isinstance(record, dict) else None
    if not isinstance(tj, dict):
        return ""
    anchors, segs, su = tj.get("anchors", {}), tj.get("segments", []), tj.get("summary", {})
    ap = []
    for a in config.ANCHOR_ORDER:
        v = anchors.get(a)
        if not v:
            continue
        o1, o2 = v.get("home_odd", v.get("over_odd")), v.get("away_odd", v.get("under_odd"))
        ap.append(f"{a}:線{v['line']:+g} 賠{o1}/{o2}")
    sp = []
    for s in segs:
        if not s.get("present"):
            continue
        sp.append(f"{s['from']}→{s['to']}:線{s['line_steps']:+}級 {s['side1']}{s['side1_dir']}/{s['side2']}{s['side2_dir']}"
                  + ("·水互換" if s.get("fav_swap") else ""))
    summary = f"形狀={su.get('shape')} 標籤={su.get('tag')} 淨{su.get('net_line_steps')}級 水互換{su.get('fav_swap_count')}次"
    return "錨點：" + "; ".join(ap) + "\n變化：" + "; ".join(sp) + "\n總結：" + summary


def _build_user(pick: dict, record: dict) -> str:
    market, side = pick.get("market"), pick.get("side")
    edge = f"{pick.get('edge_goals')}球" + (f"/{pick.get('edge_pct')}" if pick.get("edge_pct") else "")
    lines = [
        f"對戰：{pick.get('home','?')} vs {pick.get('away','?')}（開賽 {str(pick.get('kickoff_local',''))[:16]}）",
        f"選注：{market} {side} 線{pick.get('line')} @ {pick.get('odds')}；edge {edge}",
    ]
    for book in config.MOVEMENT_BOOKMAKERS:
        txt = _render_trajectory(record, book, market)
        if txt:
            lines.append(f"【{book} 軌跡】\n{txt}")
    return "\n".join(lines)


def _gemini_call(user: str) -> dict:
    from google.genai import types
    resp = _get_client().models.generate_content(
        model=config.GEMINI_MODEL,
        contents=user,
        config=types.GenerateContentConfig(
            system_instruction=PERSONA,
            response_mime_type="application/json",
            temperature=0.7,
            # 解讀已不限字數（8c6ed78）→ 提高 output 上限，否則長回答會在 1024 token 被截成無效 JSON→parse_error。
            max_output_tokens=4096,
            # 關 thinking：2.5-flash 預設 thinking 會佔光 output token 把回答截成無效 JSON
            thinking_config=types.ThinkingConfig(thinking_budget=config.GEMINI_THINKING_BUDGET),
        ),
    )
    return json.loads(resp.text)


def _mock_ai(base: dict) -> dict:
    fields = {f: _truncate(f"🧪 mock {f}（測試模式不真打 Gemini）", config.WORD_BUDGET[f]) for f in AI_FIELDS}
    return {"available": True, "reason": None, "tag": config.AI_TAG, "is_inference": True,
            "model": "mock", **base, **fields}


# =========================================================================
# 主入口
# =========================================================================
def analyze(pick: dict, record: dict, prior_ai: "dict | None" = None) -> dict:
    """回 ai{} 區塊（成功/失敗兩式，見 docs/analyzer_proposal.md §3）。不拋例外。"""
    h = _summary_hash(pick)
    # C：軌跡摘要未變且**上次成功** → 沿用，不重打 Gemini。
    # 只快取成功：失敗(available=False)不沿用 → 下輪一定重試，避免 transient api_error/parse_error
    # 被快取進 summary_hash 永遠卡在公開頁不自癒。
    if isinstance(prior_ai, dict) and prior_ai.get("summary_hash") == h and prior_ai.get("available"):
        return prior_ai
    base = {"produced_at": config.now_local().isoformat(), "summary_hash": h}

    if config.is_test_mode():                       # TEST_MODE：一律 mock
        return _mock_ai(base)
    if _is_insufficient(pick):                      # 🔴B：決策窗未填 → 不打 API
        return {"available": False, "reason": "insufficient_window", **base}
    if not config.GEMINI_API_KEY:
        return {"available": False, "reason": "missing_key", **base}

    try:
        data = _gemini_call(_build_user(pick, record))
    except json.JSONDecodeError:
        return {"available": False, "reason": "parse_error", **base}
    except Exception as e:  # 具名攔截：API/逾時/網路 → 部分失敗不阻斷
        nm = type(e).__name__.lower()
        reason = "timeout" if ("timeout" in nm or "deadline" in nm) else "api_error"
        logger.warning("Gemini 失敗 fixture=%s reason=%s：%s", pick.get("fixtureId"), reason, e)
        return {"available": False, "reason": reason, **base}

    if not isinstance(data, dict):
        return {"available": False, "reason": "parse_error", **base}
    fields = {f: str(data.get(f, "")).strip() for f in AI_FIELDS}  # 不截斷：存完整解讀（顯示層負責可展開）
    if not any(fields.values()):
        return {"available": False, "reason": "parse_error", **base}
    return {"available": True, "reason": None, "tag": config.AI_TAG, "is_inference": True,
            "model": config.GEMINI_MODEL, **base, **fields}


# =========================================================================
# 觀察場 AI 解讀（唯讀加法；**不改 analyze()**）。無 pick → 只出盤口解讀兩欄，不評信心。
# =========================================================================
OBS_FIELDS = ["injury_news_inference", "market_reading"]  # 無 pick 故不出 confidence_reasoning


def _obs_hash(record: dict) -> str:
    payload = {"fixtureId": record.get("fixtureId"), "trajectory": record.get("trajectory")}
    return hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _obs_insufficient(record: dict) -> bool:
    """所有 book/market 決策窗 shape 皆 insufficient/None → 不打 Gemini。"""
    tj = record.get("trajectory", {}) if isinstance(record, dict) else {}
    for bt in tj.values() if isinstance(tj, dict) else []:
        if not isinstance(bt, dict):
            continue
        for mt in ("handicap", "over_under"):
            su = (bt.get(mt) or {}).get("summary", {}) if isinstance(bt.get(mt), dict) else {}
            if su.get("shape") not in (None, "insufficient"):
                return False
    return True


def _build_observation_user(record: dict) -> str:
    lines = [
        f"對戰：{record.get('home','?')} vs {record.get('away','?')}（開賽 {str(record.get('kickoff_local',''))[:16]}）",
        "性質：**觀察場**（無 edge 對手盤、系統不下注）。請只解讀盤口為何這樣動，**不要建議下注、不要給選邊**。",
    ]
    for book in config.MOVEMENT_BOOKMAKERS:
        for market in ("handicap", "over_under"):
            txt = _render_trajectory(record, book, market)
            if txt:
                lines.append(f"【{book} {market} 軌跡】\n{txt}")
    return "\n".join(lines)


def analyze_observation(record: dict, prior_ai: "dict | None" = None) -> dict:
    """觀察場解讀：回 ai{}（含 observation:True），只出 injury_news_inference + market_reading。不拋例外。"""
    h = _obs_hash(record)
    if isinstance(prior_ai, dict) and prior_ai.get("summary_hash") == h and prior_ai.get("available"):
        return prior_ai  # 軌跡未變且上次成功 → 沿用；失敗不沿用 → 下輪重試（不讓 error 卡死公開頁）
    base = {"produced_at": config.now_local().isoformat(), "summary_hash": h, "observation": True}

    if config.is_test_mode():
        fields = {f: _truncate(f"🧪 mock {f}（觀察場·測試模式）", config.WORD_BUDGET[f]) for f in OBS_FIELDS}
        return {"available": True, "reason": None, "tag": config.AI_TAG, "is_inference": True,
                "model": "mock", **base, **fields}
    if _obs_insufficient(record):
        return {"available": False, "reason": "insufficient_window", **base}
    if not config.GEMINI_API_KEY:
        return {"available": False, "reason": "missing_key", **base}

    try:
        data = _gemini_call(_build_observation_user(record))
    except json.JSONDecodeError:
        return {"available": False, "reason": "parse_error", **base}
    except Exception as e:
        nm = type(e).__name__.lower()
        reason = "timeout" if ("timeout" in nm or "deadline" in nm) else "api_error"
        logger.warning("Gemini 觀察場失敗 fixture=%s reason=%s：%s", record.get("fixtureId"), reason, e)
        return {"available": False, "reason": reason, **base}

    if not isinstance(data, dict):
        return {"available": False, "reason": "parse_error", **base}
    fields = {f: str(data.get(f, "")).strip() for f in OBS_FIELDS}  # 不截斷：存完整解讀
    if not any(fields.values()):
        return {"available": False, "reason": "parse_error", **base}
    return {"available": True, "reason": None, "tag": config.AI_TAG, "is_inference": True,
            "model": config.GEMINI_MODEL, **base, **fields}
