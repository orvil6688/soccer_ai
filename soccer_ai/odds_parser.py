"""板塊二：OddsPapi 盤口解析（架構 A）。

職責：
  1. 把 /markets 原始清單壓成精簡對照表（marketId → 名稱/讓分線/型別/outcome 對映），
     僅留 Asian Handicap 與 Over Under Full Time 的 fulltime 市場。
  2. 把「單一時間點」的盤口（current 或 historical 切片）解析成型別固定的主盤線結構。

契約 D：讀外部陣列/字典前一律 isinstance。回傳型固定：線值與賠率 float、無則 None。
盤口模型：AH(spreads) outcome "1"=主 "2"=客；OU(totals) outcome Over/Under。
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional

from . import config

# 單一 outcome → (price, timestamp_iso)。current 與 historical 各自提供不同實作。
PriceFn = Callable[[dict], "tuple[Optional[float], Optional[str]]"]


# =========================================================================
# 市場對照表
# =========================================================================
def build_market_map(raw_markets: list) -> dict:
    """raw /markets → {marketId(int): {name,handicap,type,period,outcomes:{outcomeId:name}}}。

    僅保留 Asian Handicap / Over Under Full Time 的 fulltime 市場。
    """
    out: dict[int, dict] = {}
    if not isinstance(raw_markets, list):
        return out
    keep = {config.MARKET_ASIAN_HANDICAP, config.MARKET_OVER_UNDER}
    for m in raw_markets:
        if not isinstance(m, dict):
            continue
        name = m.get("marketName")
        if name not in keep or m.get("period") != config.MARKET_PERIOD:
            continue
        mid = m.get("marketId")
        handicap = m.get("handicap")
        if not isinstance(mid, int) or not isinstance(handicap, (int, float)):
            continue
        outcomes = {}
        for o in m.get("outcomes", []) if isinstance(m.get("outcomes"), list) else []:
            if isinstance(o, dict) and isinstance(o.get("outcomeId"), int):
                # outcome 鍵一律存字串：JSON 往返後鍵必為字串，統一避免 int/str 查找不一致
                outcomes[str(o["outcomeId"])] = str(o.get("outcomeName", ""))
        out[mid] = {
            "name": name,
            "handicap": float(handicap),
            "type": m.get("marketType"),  # "spreads" | "totals"
            "period": m.get("period"),
            "outcomes": outcomes,
        }
    return out


# =========================================================================
# PriceFn 實作
# =========================================================================
def current_price_fn(outcome: dict) -> "tuple[Optional[float], Optional[str]]":
    """odds-by-tournaments：單一現值。"""
    p = outcome.get("players", {}).get("0") if isinstance(outcome.get("players"), dict) else None
    if not isinstance(p, dict):
        return (None, None)
    price = p.get("price")
    ts = p.get("changedAt") or p.get("bookmakerChangedAt")
    return (float(price) if isinstance(price, (int, float)) else None, ts)


def make_historical_price_fn(target: datetime) -> PriceFn:
    """historical：在 outcome 的時間序列中取「最接近 target」的一筆（§3.2 規則 1）。"""

    def fn(outcome: dict) -> "tuple[Optional[float], Optional[str]]":
        series = outcome.get("players", {}).get("0") if isinstance(outcome.get("players"), dict) else None
        if not isinstance(series, list):
            return (None, None)
        best: Optional[tuple[float, str]] = None
        best_diff: Optional[float] = None
        for pt in series:
            if not isinstance(pt, dict):
                continue
            price, cts = pt.get("price"), pt.get("createdAt")
            if not isinstance(price, (int, float)) or not isinstance(cts, str):
                continue
            try:
                diff = abs((config.parse_iso(cts) - target).total_seconds())
            except ValueError:
                continue
            if best_diff is None or diff < best_diff:
                best_diff, best = diff, (float(price), cts)
        return best if best else (None, None)

    return fn


# =========================================================================
# 時間跨度（供 movement 判定 initial/closing/null）
# =========================================================================
def collect_timestamps(markets: dict, market_map: dict) -> list[datetime]:
    """蒐集 AH/OU fulltime outcome 的所有 historical 時間點（排序）。"""
    out: list[datetime] = []
    if not isinstance(markets, dict):
        return out
    for mid_str, mobj in markets.items():
        meta = market_map.get(_to_int(mid_str))
        if not meta or not isinstance(mobj, dict):
            continue
        outcomes = mobj.get("outcomes")
        if not isinstance(outcomes, dict):
            continue
        for oobj in outcomes.values():
            series = oobj.get("players", {}).get("0") if isinstance(oobj, dict) and isinstance(oobj.get("players"), dict) else None
            if not isinstance(series, list):
                continue
            for pt in series:
                if isinstance(pt, dict) and isinstance(pt.get("createdAt"), str):
                    try:
                        out.append(config.parse_iso(pt["createdAt"]))
                    except ValueError:
                        pass
    out.sort()
    return out


# =========================================================================
# 解析單一時間點 → 主盤線
# =========================================================================
def parse_point(markets: dict, market_map: dict, price_fn: PriceFn) -> dict:
    """回 {'handicap':{line,home_odd,away_odd,captured_ts}|None, 'over_under':{line,over_odd,under_odd,captured_ts}|None}。

    主盤線 = home/away（或 over/under）賠率最接近者（莊家主推線）。
    """
    ah: dict[float, dict] = {}
    ou: dict[float, dict] = {}
    if not isinstance(markets, dict):
        return {"handicap": None, "over_under": None}

    for mid_str, mobj in markets.items():
        meta = market_map.get(_to_int(mid_str))
        if not meta or not isinstance(mobj, dict):
            continue
        outcomes = mobj.get("outcomes")
        if not isinstance(outcomes, dict):
            continue
        for oid_str, oobj in outcomes.items():
            if not isinstance(oobj, dict):
                continue
            side = meta["outcomes"].get(str(oid_str))  # outcomes 鍵為字串
            if side is None:
                continue
            price, ts = price_fn(oobj)
            if price is None:
                continue
            line = meta["handicap"]
            if meta["type"] == "spreads":
                slot = ah.setdefault(line, {})
                if side == "1":
                    slot["home"] = (price, ts)
                elif side == "2":
                    slot["away"] = (price, ts)
            elif meta["type"] == "totals":
                slot = ou.setdefault(line, {})
                if side.lower() == "over":
                    slot["over"] = (price, ts)
                elif side.lower() == "under":
                    slot["under"] = (price, ts)

    return {
        "handicap": _select_balanced(ah, "home", "away", "home_odd", "away_odd"),
        "over_under": _select_balanced(ou, "over", "under", "over_odd", "under_odd"),
    }


def _select_balanced(lines: dict, k1: str, k2: str, out1: str, out2: str) -> Optional[dict]:
    cands = [
        (ln, d[k1], d[k2]) for ln, d in lines.items() if k1 in d and k2 in d
    ]
    if not cands:
        return None
    line, a, b = min(cands, key=lambda c: abs(c[1][0] - c[2][0]))  # 賠率最接近
    ts = max(t for t in (a[1], b[1]) if t) if (a[1] or b[1]) else None
    return {"line": float(line), out1: float(a[0]), out2: float(b[0]), "captured_ts": ts}


def _to_int(x) -> Optional[int]:
    try:
        return int(x)
    except (TypeError, ValueError):
        return None
