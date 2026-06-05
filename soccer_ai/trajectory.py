"""板塊二：盤口軌跡分類（schema v2 核心智慧）。

系統＝事實層：客觀記錄八錨點 + segment 四維變化 + summary 形狀/結構化標籤。
**不解讀意圖**（洗盤/誘散戶/消息走漏等動機留給 GEMINI 標 🤖）。
形狀名一律中性、描述性（spike_revert 非「洗盤」）；原始特徵全存，回測可任意分桶。

客觀以固定視角記錄：讓分＝home/away、大小＝over/under。「我方/對方」由下游依 pick 邊重定向。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from . import config, odds_parser

_MARKET_NAME = {"handicap": config.MARKET_ASIAN_HANDICAP, "over_under": config.MARKET_OVER_UNDER}
_SIDES = {"handicap": ("home", "away"), "over_under": ("over", "under")}
_ODD_KEY = {"home": "home_odd", "away": "away_odd", "over": "over_odd", "under": "under_odd"}


# =========================================================================
# 序列時間跨度（單一 market）
# =========================================================================
def _market_timestamps(markets: dict, market_map: dict, market_type: str) -> list[datetime]:
    name = _MARKET_NAME[market_type]
    out: list[datetime] = []
    if not isinstance(markets, dict):
        return out
    for mid_str, mobj in markets.items():
        try:
            meta = market_map.get(int(mid_str))
        except (TypeError, ValueError):
            continue
        if not meta or meta.get("name") != name or not isinstance(mobj, dict):
            continue
        oc = mobj.get("outcomes")
        if not isinstance(oc, dict):
            continue
        for o in oc.values():
            s = o.get("players", {}).get("0") if isinstance(o, dict) and isinstance(o.get("players"), dict) else None
            if isinstance(s, list):
                for pt in s:
                    if isinstance(pt, dict) and isinstance(pt.get("createdAt"), str):
                        try:
                            out.append(config.parse_iso(pt["createdAt"]))
                        except ValueError:
                            pass
    out.sort()
    return out


def _anchor_value(markets: dict, market_map: dict, target: datetime, market_type: str) -> Optional[dict]:
    """該 market 在 target 時刻的主盤線（最接近一筆）：{line, *_odd, captured_ts} 或 None。"""
    pt = odds_parser.parse_point(markets, market_map, odds_parser.make_historical_price_fn(target))
    return pt.get(market_type)


# =========================================================================
# 八錨點（單一 market）
# =========================================================================
def build_anchors(markets: dict, market_map: dict, kickoff: datetime, market_type: str) -> dict:
    anchors: dict[str, Optional[dict]] = {a: None for a in config.ANCHOR_ORDER}
    ts = _market_timestamps(markets, market_map, market_type)
    if not ts:
        return anchors
    earliest, latest = ts[0], ts[-1]

    v = _anchor_value(markets, market_map, earliest, market_type)
    if v:
        anchors[config.ANCHOR_INITIAL] = {"target_ts": None, "offset_sec": None, **v}

    pre = [t for t in ts if t < kickoff]
    if pre:
        v = _anchor_value(markets, market_map, pre[-1], market_type)
        if v:
            anchors[config.ANCHOR_CLOSING] = {"target_ts": None, "offset_sec": None, **v}

    for name, off in config.ANCHOR_OFFSETS.items():
        target = kickoff - off
        if target < earliest or target > latest:  # 目標落在序列觀測區間外 → null（不硬塞）
            continue
        v = _anchor_value(markets, market_map, target, market_type)
        if not v:
            continue
        offset = None
        if v.get("captured_ts"):
            try:
                offset = int((config.parse_iso(v["captured_ts"]) - target).total_seconds())
            except ValueError:
                pass
        anchors[name] = {"target_ts": target.isoformat(), "offset_sec": offset, **v}
    return anchors


# =========================================================================
# segment（相鄰決策錨點之間的四維變化）
# =========================================================================
def _favorite(anchor: dict, market_type: str) -> str:
    s1, s2 = _SIDES[market_type]
    a, b = anchor[_ODD_KEY[s1]], anchor[_ODD_KEY[s2]]
    if abs(a - b) <= config.FAV_EPS:
        return "even"
    return s1 if a < b else s2  # 低水方（賠率較低）＝低水/被看好那邊


def _dir(delta: float) -> str:
    if abs(delta) <= config.ODDS_FLAT_EPS:
        return "flat"
    return "up" if delta > 0 else "down"


def _devig_p1(odd1: float, odd2: float) -> float:
    """side1 去水位後公允機率。"""
    if odd1 <= 1 or odd2 <= 1:
        return 0.5
    p1, p2 = 1.0 / odd1, 1.0 / odd2
    return p1 / (p1 + p2)


def _prob_dir(shift: float) -> str:
    """公允機率位移方向：up=機率升(往該邊)、down=機率降、flat。"""
    if abs(shift) <= config.PROB_FLAT_EPS:
        return "flat"
    return "up" if shift > 0 else "down"


def build_segments(anchors: dict, market_type: str) -> list[dict]:
    s1, s2 = _SIDES[market_type]
    k1, k2 = _ODD_KEY[s1], _ODD_KEY[s2]
    dec = config.ANCHOR_DECISION
    segs: list[dict] = []
    for i in range(len(dec) - 1):
        a, b = anchors[dec[i]], anchors[dec[i + 1]]
        if not a or not b:
            segs.append({"from": dec[i], "to": dec[i + 1], "present": False})
            continue
        d1, d2 = b[k1] - a[k1], b[k2] - a[k2]
        fa, fb = _favorite(a, market_type), _favorite(b, market_type)
        segs.append({
            "from": dec[i], "to": dec[i + 1], "present": True,
            "line_steps": round((b["line"] - a["line"]) / config.LINE_STEP),
            "side1": s1, "side1_odd_delta": round(d1, 3), "side1_dir": _dir(d1),
            "side2": s2, "side2_odd_delta": round(d2, 3), "side2_dir": _dir(d2),
            "fav_from": fa, "fav_to": fb,
            "fav_swap": fa != fb and "even" not in (fa, fb),
        })
    return segs


# =========================================================================
# summary（跨決策窗的特徵 + 中性形狀 + 客觀結構化標籤）
# =========================================================================
def _direction_changes(seg_steps: list[int]) -> int:
    nz = [s for s in seg_steps if s != 0]
    return sum(1 for x, y in zip(nz, nz[1:]) if (x > 0) != (y > 0))


def _classify(net: int, abs_path: int, excur: int, reverted: bool, dir_changes: int,
              late: bool, fav_swaps: int, odds_active: bool) -> str:
    """中性形狀（無動機解讀）。線不動時仍以賠率/水互換維度分類，不誤判為 flat。"""
    if net == 0 and abs_path <= 1:
        # 線（幾乎）不動 → 看賠率維度，避免漏掉「線不動但賠率大幅移動」訊號
        if fav_swaps > 0:
            return "fav_swap"        # 低水方換邊（水互換）
        if odds_active:
            return "odds_drift"      # 線不動、賠率明顯移動
        return "flat"
    if reverted:
        return "spike_revert"
    if late and dir_changes <= 1:
        return "late_swing"
    if dir_changes == 0:
        return "monotonic" if abs(net) >= config.SHAPE_MONO_NET_STEPS else "gradual"
    if dir_changes >= 2 and abs(net) <= 1:
        return "choppy"
    return "mixed"


_DMAP = {"up": "升", "down": "降", "flat": "平"}


def _build_tag(market_type: str, net: int, fav_swaps: int, s1_net: str, s2_net: str) -> str:
    lvl = f"{'升' if net > 0 else '降' if net < 0 else '平'}{abs(net)}級"
    swap = "·水互換" if fav_swaps > 0 else ""
    if market_type == "handicap":
        odds = f"·主{_DMAP[s1_net]}客{_DMAP[s2_net]}"
    else:
        odds = f"·大{_DMAP[s1_net]}小{_DMAP[s2_net]}"
    return lvl + swap + odds


def build_summary(anchors: dict, segments: list[dict], market_type: str) -> dict:
    s1, s2 = _SIDES[market_type]
    k1, k2 = _ODD_KEY[s1], _ODD_KEY[s2]
    present = [anchors[n] for n in config.ANCHOR_DECISION if anchors[n]]
    if len(present) < 2:
        return {"present_anchors": len(present), "shape": "insufficient", "tag": None}

    step = config.LINE_STEP
    lines = [a["line"] for a in present]
    net = round((lines[-1] - lines[0]) / step)
    seg_steps = [s["line_steps"] for s in segments if s.get("present")]
    abs_path = sum(abs(x) for x in seg_steps)
    excur = max((round((ln - lines[0]) / step) for ln in lines), key=abs, default=0)
    reverted = abs(excur) >= config.SHAPE_SPIKE_EXCURSION_STEPS and abs(net) <= 1
    dir_changes = _direction_changes(seg_steps)
    last_seg = next((s for s in reversed(segments) if s.get("present")), None)
    late = bool(last_seg) and abs(last_seg["line_steps"]) >= config.SHAPE_LATE_SWING_STEPS
    fav_swaps = sum(1 for s in segments if s.get("fav_swap"))
    s1_net, s2_net = _dir(present[-1][k1] - present[0][k1]), _dir(present[-1][k2] - present[0][k2])
    odds_active = any(
        s.get("present") and (s["side1_dir"] != "flat" or s["side2_dir"] != "flat") for s in segments
    )
    # 去水位後 side1 公允機率位移（首→末決策錨點）：濾掉「兩邊一起調水位」的假動作。
    p1_shift = _devig_p1(present[-1][k1], present[-1][k2]) - _devig_p1(present[0][k1], present[0][k2])
    s1_prob_net = _prob_dir(p1_shift)
    s2_prob_net = _prob_dir(-p1_shift)

    shape = _classify(net, abs_path, excur, reverted, dir_changes, late, fav_swaps, odds_active)
    return {
        "present_anchors": len(present),
        "net_line_steps": net,
        "abs_path_steps": abs_path,
        "max_excursion_steps": excur,
        "reverted": reverted,
        "direction_changes": dir_changes,
        "late_swing": late,
        "fav_swap_count": fav_swaps,
        "fav_final": _favorite(present[-1], market_type),
        "side1": s1, "side1_odd_net": s1_net, "side1_prob_net": s1_prob_net,
        "side2": s2, "side2_odd_net": s2_net, "side2_prob_net": s2_prob_net,
        "shape": shape,
        "tag": _build_tag(market_type, net, fav_swaps, s1_net, s2_net),
    }


def build(markets: dict, market_map: dict, kickoff: datetime, market_type: str) -> dict:
    """單一 market 的完整軌跡：{anchors, segments, summary}。"""
    anchors = build_anchors(markets, market_map, kickoff, market_type)
    segments = build_segments(anchors, market_type)
    summary = build_summary(anchors, segments, market_type)
    return {"anchors": anchors, "segments": segments, "summary": summary}
