"""一次性歷史採集 spike：titan007 2022 世界盃 → 八錨點 schema_v2。

🔒#7：獨立 script、**不接 main.py、不上 CI、可失敗**。低頻禮貌爬；HTML 當不可信資料、只抽數字。
依賴：requirements-titan007.txt（scrapling 輕量；本檔用 requests 抓 + 正則抽 odds2 表）。
用法：python -m scrapers.titan007_spike

端點（實打確認）：
  讓分 https://vip.titan007.com/changeDetail/handicap.aspx?id=<mid>&companyID=<47|3>
  大小 https://vip.titan007.com/changeDetail/overunder.aspx?id=<mid>&companyID=<47|3>
  companyID 47=平博→pinnacle、3=皇冠→singbet；表 id="odds2"，gb2312。
防呆：只取 ts<kickoff（濾滾球「即」）；§3.2 規則① 取最接近目標時刻、區間外 null 不硬塞。
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone

import requests

from soccer_ai import config, trajectory

_BASE = "https://vip.titan007.com/changeDetail"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
_TZ_CN = timezone(timedelta(hours=8))   # titan007 北京時間
_COMPANY = {"pinnacle": 47, "singbet": 3}  # 平博 / 皇冠
_POLITE_SEC = 3.5                          # 低頻禮貌間隔（3-5s 區間）
_BACKOFF = [3, 6, 12]                       # 429/錯誤指數退避（耗盡 → 拋出，由上層標該場跳過）

# 中文讓盤 → 數值（主隊視角）。受让X=主受讓(+)；無受让=主讓(-)。
_HCAP = {
    "平手": 0.0, "平手/半球": 0.25, "半球": 0.5, "半球/一球": 0.75, "一球": 1.0,
    "一球/球半": 1.25, "球半": 1.5, "球半/两球": 1.75, "两球": 2.0,
    "两球/两球半": 2.25, "两球半": 2.5, "两球半/三球": 2.75, "三球": 3.0,
}


def _f(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _hcap_to_num(s: str):
    s = (s or "").strip()
    recv = s.startswith("受让")
    base = _HCAP.get(s[2:] if recv else s)
    if base is None:
        return None
    return base if recv else -base   # 受让=主受讓(+)；主讓(-)


def _total_to_num(s: str):
    s = (s or "").strip()
    if "/" in s:
        ps = [_f(x) for x in s.split("/")]
        return sum(ps) / len(ps) if all(p is not None for p in ps) else None
    return _f(s)


def _parse_ts(s: str, year: int = 2022):
    # titan007 月/日/時不補零（如 '12-9 9:05'），故 1-2 位數都要吃，否則單位數日期(1-9)全被丟
    m = re.match(r"(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})", (s or "").strip())
    if not m:
        return None
    mo, d, h, mi = map(int, m.groups())
    return datetime(year, mo, d, h, mi, tzinfo=_TZ_CN)


def _fetch_odds2_rows(page: str, mid: int, company_id: int) -> list[list[str]]:
    url = f"{_BASE}/{page}?id={mid}&companyID={company_id}"
    t = None
    for attempt, wait in enumerate([0, *_BACKOFF]):
        if wait:
            time.sleep(wait)
        try:
            r = requests.get(url, headers={"User-Agent": _UA, "Referer": "https://www.titan007.com/"}, timeout=20)
            if r.status_code == 429 or r.status_code >= 500:
                continue  # 退避重試
            r.raise_for_status()
            r.encoding = "gb2312"
            t = r.text
            break
        except requests.RequestException:
            if attempt == len(_BACKOFF):
                raise  # 退避耗盡 → 拋出，上層標該場跳過
    i = t.find('id="odds2"')
    if i < 0:
        time.sleep(_POLITE_SEC)
        return []
    seg = t[i:t.find("</TABLE>", i) + 8]
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", seg, re.S | re.I):
        tds = [re.sub(r"<[^>]+>", "", c).replace("\xa0", " ").strip()
               for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S | re.I)]
        rows.append([c for c in tds if c != ""])
    time.sleep(_POLITE_SEC)
    return rows


def _series(market: str, mid: int, company_id: int, kickoff: datetime) -> list[dict]:
    """回賽前（ts<kickoff）時間序列；handicap→{ts,line,home_odd,away_odd}、over_under→{ts,line,over_odd,under_odd}。"""
    page = "handicap.aspx" if market == "handicap" else "overunder.aspx"
    out = []
    for cells in _fetch_odds2_rows(page, mid, company_id):
        if len(cells) < 4:
            continue
        o1, ln_raw, o2, ts_raw = cells[0], cells[1], cells[2], cells[3]
        ts = _parse_ts(ts_raw)
        a, b = _f(o1), _f(o2)
        line = _hcap_to_num(ln_raw) if market == "handicap" else _total_to_num(ln_raw)
        if ts is None or a is None or b is None or line is None:
            continue
        if ts >= kickoff:        # 防呆：濾滾球，只留賽前
            continue
        rec = {"ts": ts, "line": line}
        if market == "handicap":
            rec["home_odd"], rec["away_odd"] = a, b
        else:
            rec["over_odd"], rec["under_odd"] = a, b
        out.append(rec)
    out.sort(key=lambda x: x["ts"])
    return out


def _anchor(row: dict, market: str, target, positional: bool) -> dict:
    o1, o2 = ("home_odd", "away_odd") if market == "handicap" else ("over_odd", "under_odd")
    cts = row["ts"]
    a = {
        "target_ts": None if positional else target.astimezone(timezone.utc).isoformat(),
        "captured_ts": cts.astimezone(timezone.utc).isoformat(),
        "offset_sec": None if positional else int((cts - target).total_seconds()),
        "line": row["line"], o1: row[o1], o2: row[o2],
    }
    return a


def _anchors_from_series(series: list[dict], kickoff: datetime, market: str) -> dict:
    """§3.2：initial=序列首筆、closing=賽前末筆；t*=最接近目標、區間外 null 不硬塞。"""
    anchors = {a: None for a in config.ANCHOR_ORDER}
    if not series:
        return anchors
    earliest, latest = series[0]["ts"], series[-1]["ts"]
    anchors[config.ANCHOR_INITIAL] = _anchor(series[0], market, None, positional=True)
    anchors[config.ANCHOR_CLOSING] = _anchor(series[-1], market, None, positional=True)
    for name, off in config.ANCHOR_OFFSETS.items():
        target = kickoff - off
        if target < earliest or target > latest:
            continue  # 區間外 → null
        nearest = min(series, key=lambda r: abs((r["ts"] - target).total_seconds()))
        anchors[name] = _anchor(nearest, market, target, positional=False)
    return anchors


def build_fixture(mid: int, home: str, away: str, kickoff_utc: str, score: dict) -> dict:
    kickoff = config.parse_iso(kickoff_utc).astimezone(_TZ_CN)
    traj = {}
    for book, cid in _COMPANY.items():
        book_t = {}
        for market in ("handicap", "over_under"):
            series = _series(market, mid, cid, kickoff)
            anchors = _anchors_from_series(series, kickoff, market)
            segments = trajectory.build_segments(anchors, market)
            book_t[market] = {
                "anchors": anchors,
                "segments": segments,
                "summary": trajectory.build_summary(anchors, segments, market),
            }
        traj[book] = book_t
    return {
        "schema_version": config.SCHEMA_VERSION,
        "source": "titan007",
        "fixtureId": f"titan007_{mid}",
        "tournamentId": config.WORLD_CUP_TOURNAMENT_ID,
        "sportId": config.SPORT_ID_SOCCER,
        "home": home, "away": away,
        "kickoff_utc": config.parse_iso(kickoff_utc).astimezone(timezone.utc).isoformat(),
        "kickoff_local": config.to_local(config.parse_iso(kickoff_utc)).isoformat(),
        "books": list(traj),
        "trajectory": traj,
        "score": score,
        "closing_settled": True,
        "pulled_at_local": config.now_local().isoformat(),
    }


# 卡塔爾 0-2 厄瓜多爾（2022 開幕戰）。KO 2022-11-20 19:00 Doha(UTC+3)=16:00Z。
# 比分先以已知值帶入（全量採集時改抓 titan007 結果頁）。
_SPIKE = dict(mid=2185072, home="卡塔爾", away="厄瓜多爾",
              kickoff_utc="2022-11-20T16:00:00Z", score={"home": 0, "away": 2})


def main():
    rec = build_fixture(**_SPIKE)
    out_dir = config._PROJECT_ROOT / "data" / "titan007_2022"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{_SPIKE['mid']}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)
    print("寫出:", path)


if __name__ == "__main__":
    main()
