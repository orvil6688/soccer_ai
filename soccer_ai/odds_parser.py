"""板塊二：盤口解析。

職責：把 API-Football /odds 原始 JSON 解析成「型別固定」的乾淨結構。
契約 D（isinstance 防禦）：讀任何外部 API 陣列前一律 isinstance 檢查。
回傳型固定：盤口線與賠率一律 float，名稱一律 str；無法取得回 None。

API-Football /odds 結構（節錄）：
  response[].bookmakers[].bets[].values[] = {"value": "Home -0.5", "odd": "1.90"}
"""
from __future__ import annotations

from typing import Optional

from . import config


def _to_float(raw: object) -> Optional[float]:
    """安全轉 float；支援亞洲盤分盤線 '-0.25/-0.5'（取平均）。失敗回 None。"""
    if isinstance(raw, (int, float)):
        return float(raw)
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s:
        return None
    if "/" in s:  # 分盤線（split line）
        parts = s.split("/")
        nums = []
        for p in parts:
            try:
                nums.append(float(p.strip()))
            except ValueError:
                return None
        return sum(nums) / len(nums) if nums else None
    try:
        return float(s)
    except ValueError:
        return None


def _select_bookmaker(bookmakers: object, priority: list[int]) -> Optional[dict]:
    """依優先序挑第一個存在的 bookmaker。"""
    if not isinstance(bookmakers, list):
        return None
    by_id: dict[int, dict] = {}
    for bm in bookmakers:
        if isinstance(bm, dict) and isinstance(bm.get("id"), int):
            by_id[bm["id"]] = bm
    for pref in priority:
        if pref in by_id:
            return by_id[pref]
    return None


def _find_bet(bookmaker: dict, bet_id: int) -> Optional[dict]:
    bets = bookmaker.get("bets")
    if not isinstance(bets, list):
        return None
    for bet in bets:
        if isinstance(bet, dict) and bet.get("id") == bet_id:
            return bet
    return None


def _iter_values(bet: dict):
    values = bet.get("values")
    if not isinstance(values, list):
        return
    for v in values:
        if isinstance(v, dict):
            yield v


def parse_handicap(bookmaker: dict) -> Optional[dict]:
    """解析亞洲讓分盤（bet id 4）→ 主盤線（home/away 賠率最接近者）。

    回傳 {"line": float, "home_odd": float, "away_odd": float} 或 None。
    line 以 Home 視角（負值=主隊讓盤）。
    """
    bet = _find_bet(bookmaker, config.BET_ID_ASIAN_HANDICAP)
    if bet is None:
        return None

    # line(以 Home 視角) → {"home": odd, "away": odd}
    lines: dict[float, dict] = {}
    for v in _iter_values(bet):
        value_str = v.get("value")
        odd = _to_float(v.get("odd"))
        if not isinstance(value_str, str) or odd is None:
            continue
        tokens = value_str.split()
        if len(tokens) < 2:
            continue
        side = tokens[0].lower()
        line_val = _to_float(tokens[-1])
        if line_val is None:
            continue
        # 統一成 Home 視角的盤口線
        home_line = line_val if side.startswith("home") else -line_val
        slot = lines.setdefault(home_line, {})
        slot["home" if side.startswith("home") else "away"] = odd

    candidates = [
        (ln, d["home"], d["away"])
        for ln, d in lines.items()
        if "home" in d and "away" in d
    ]
    if not candidates:
        return None
    # 主盤線：home/away 賠率最接近（莊家主推線）
    line, home_odd, away_odd = min(candidates, key=lambda c: abs(c[1] - c[2]))
    return {"line": float(line), "home_odd": float(home_odd), "away_odd": float(away_odd)}


def parse_over_under(bookmaker: dict) -> Optional[dict]:
    """解析大小球（bet id 5）→ 主盤線（over/under 賠率最接近者）。

    回傳 {"line": float, "over_odd": float, "under_odd": float} 或 None。
    """
    bet = _find_bet(bookmaker, config.BET_ID_OVER_UNDER)
    if bet is None:
        return None

    lines: dict[float, dict] = {}
    for v in _iter_values(bet):
        value_str = v.get("value")
        odd = _to_float(v.get("odd"))
        if not isinstance(value_str, str) or odd is None:
            continue
        tokens = value_str.split()
        if len(tokens) < 2:
            continue
        side = tokens[0].lower()
        line_val = _to_float(tokens[-1])
        if line_val is None:
            continue
        slot = lines.setdefault(line_val, {})
        if side.startswith("over"):
            slot["over"] = odd
        elif side.startswith("under"):
            slot["under"] = odd

    candidates = [
        (ln, d["over"], d["under"])
        for ln, d in lines.items()
        if "over" in d and "under" in d
    ]
    if not candidates:
        return None
    line, over_odd, under_odd = min(candidates, key=lambda c: abs(c[1] - c[2]))
    return {"line": float(line), "over_odd": float(over_odd), "under_odd": float(under_odd)}


def parse_odds_snapshot(odds_response: object, captured_at_local: str) -> Optional[dict]:
    """把單場 /odds 回應解析為一筆窗口快照 payload。

    odds_response：API-Football /odds 的 response 陣列（單場通常 1 元素）。
    回傳：
      {"captured_at_local": str, "source_bookmaker": int,
       "source_bookmaker_name": str, "handicap": {...}|None, "over_under": {...}|None}
    若連 bookmaker 都取不到，回 None（視為本窗無有效盤口）。
    """
    if not isinstance(odds_response, list) or not odds_response:
        return None
    first = odds_response[0]
    if not isinstance(first, dict):
        return None

    bookmaker = _select_bookmaker(first.get("bookmakers"), config.BOOKMAKER_PRIORITY)
    if bookmaker is None:
        return None

    name = bookmaker.get("name")
    return {
        "captured_at_local": captured_at_local,
        "source_bookmaker": int(bookmaker.get("id")),
        "source_bookmaker_name": str(name) if isinstance(name, str) else "",
        "handicap": parse_handicap(bookmaker),
        "over_under": parse_over_under(bookmaker),
    }
