"""一次性歷史採集（全量 64 場）：titan007 2022 世界盃 → 八錨點 schema_v2。

🔒#7：獨立 script、不接 main.py、不上 CI、可失敗。低頻禮貌爬、HTML 當不可信資料只抽數字。
用法：python -m scrapers.titan007_full

賽程/比分權威源（總司令 2026-06-07 提供）：
  賽程頁 https://zq.titan007.com/cn/CupMatch/2022/75.html（JS 渲染）
  資料源 https://zq.titan007.com/jsData/matchResult/2022/c75.js
    var arrTeam=[[id,'隊名',...],...]
    jh["G..."]=[[mid,75,-1,'YYYY-MM-DD HH:MM'(北京),home_id,away_id,'90分比分','半場比分',...]]
  **score 取 index 6＝比分欄＝90 分鐘賽果**（ET/PK 不在此欄、不誤抓；已驗決賽 2302891=2-2、克巴 2302885=0-0）。

賠率走勢沿用 spike：handicap.aspx / overunder.aspx × companyID 47(pinnacle)/3(singbet)。
節流 3.5s/次 + 429 指數退避（_fetch_odds2_rows）；抓不到/null 過多 → 標記跳過、最後彙總、不靜默丟。
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone

import requests

from soccer_ai import config
from scrapers import titan007_spike as t007

_FEED = "https://zq.titan007.com/jsData/matchResult/2022/c75.js"
_SCHED_REF = "https://zq.titan007.com/cn/CupMatch/2022/75.html"
_TZ_CN = timezone(timedelta(hours=8))


def fetch_schedule() -> list[dict]:
    """解析 c75.js → 64 場 [{mid,home,away,kickoff_bj_iso,score{home,away}}]。"""
    r = requests.get(_FEED, headers={"User-Agent": t007._UA, "Referer": _SCHED_REF}, timeout=20)
    b = r.content.decode("utf-8-sig", "replace")
    teams = {int(i): n for i, n in re.findall(r"\[(\d+),'([^']*)'", re.search(r"var\s+arrTeam\s*=\s*(\[.*?\]\]);", b, re.S).group(1))}
    out = []
    for m in re.finditer(r'jh\["[^"]+"\]\s*=\s*(\[\[.*?\]\]);', b, re.S):
        for row in re.finditer(r"\[(\d{6,7}),(\d+),(-?\d+),'([^']+)',(\d+),(\d+),'([^']*)','([^']*)'", m.group(1)):
            mid, _cup, _x, dt, hid, aid, ft, _ht = row.groups()
            sc = re.match(r"\s*(\d+)\s*-\s*(\d+)\s*", ft)
            score = {"home": int(sc.group(1)), "away": int(sc.group(2))} if sc else None
            out.append({
                "mid": int(mid), "home": teams.get(int(hid), hid), "away": teams.get(int(aid), aid),
                "kickoff_bj_iso": dt.replace(" ", "T") + ":00+08:00", "score": score,
            })
    return out


def _coverage(rec: dict) -> tuple[int, int]:
    """回 (空的 book×market 組數, 總決策錨點命中數)。"""
    empty, present = 0, 0
    for book in rec.get("books", []):
        for market in ("handicap", "over_under"):
            anchors = rec["trajectory"][book][market]["anchors"]
            n = sum(1 for name in config.ANCHOR_DECISION if anchors.get(name))
            present += n
            if all(anchors.get(name) is None for name in config.ANCHOR_ORDER):
                empty += 1
    return empty, present


def _process(out_dir, mt) -> tuple[str, str]:
    """單場：build + 寫檔 + 評估覆蓋。回 (status, detail)；status∈{ok,flag,skip}。"""
    mid = mt["mid"]
    if mt["score"] is None:
        return "skip", "比分欄缺/壞"
    try:
        rec = t007.build_fixture(mid, mt["home"], mt["away"], mt["kickoff_bj_iso"], mt["score"])
    except Exception as e:  # 抓取退避耗盡 → 標記跳過、不靜默丟
        return "skip", f"抓取失敗：{e}"
    empty, present = _coverage(rec)
    if empty == 4:
        return "skip", "四組盤口全空"
    (out_dir / f"{mid}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    if empty or present < 12:  # 部分組空 或 決策錨點偏少（4組×6=24 滿）
        return "flag", f"空組={empty} 決策錨點={present}/24"
    return "ok", f"比分{mt['score']['home']}-{mt['score']['away']}"


def _summary(written, skipped, flagged):
    print("\n===== 彙總 =====", flush=True)
    print(f"寫出 {len(written)} / 跳過 {len(skipped)} / 旗標(已寫但留意) {len(flagged)}", flush=True)
    if skipped:
        print("-- 跳過場次 --")
        for mid, why in skipped:
            print(f"  {mid}: {why}")
    if flagged:
        print("-- 旗標場次（已寫，錨點偏少/部分組空）--")
        for mid, why in flagged:
            print(f"  {mid}: {why}")


def run(mids: "set[int] | None" = None, interval: float = 3.5):
    """mids=None 跑全量；否則只跑指定 mid（重抓用，建議放慢 interval 避軟封鎖）。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows 重導向預設 cp950，含簡體隊名會炸
    except Exception:
        pass
    t007._POLITE_SEC = interval
    out_dir = config._PROJECT_ROOT / "data" / "titan007_2022"
    out_dir.mkdir(parents=True, exist_ok=True)
    sched = fetch_schedule()
    if mids is not None:
        sched = [m for m in sched if m["mid"] in mids]
    print(f"賽程解析：{len(sched)} 場（interval={interval}s{'，重抓模式' if mids else ''}）", flush=True)

    written, skipped, flagged = [], [], []
    for k, mt in enumerate(sched, 1):
        st, detail = _process(out_dir, mt)
        tag = f"[{k}/{len(sched)}] {mt['mid']} {mt['home']} vs {mt['away']}"
        if st == "skip":
            skipped.append((mt["mid"], detail)); print(f"{tag} → SKIP {detail}", flush=True)
        elif st == "flag":
            written.append(mt["mid"]); flagged.append((mt["mid"], detail)); print(f"{tag} → OK ⚠️ {detail}", flush=True)
        else:
            written.append(mt["mid"]); print(f"{tag} → OK {detail}", flush=True)
    _summary(written, skipped, flagged)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--rerun", help="只重抓這些 mid（逗號分隔）")
    ap.add_argument("--interval", type=float, default=3.5, help="每次請求間隔秒（重抓建議放慢，如 6）")
    a = ap.parse_args()
    ids = {int(x) for x in a.rerun.split(",")} if a.rerun else None
    run(ids, a.interval)
