"""板塊二：歷史推薦 & 快照持久化（支援 TEST_MODE 隔離）。

⚠️ 絕對不動清單：本檔歷史/快照檔寫入格式，上線後即契約。
原子寫入：先寫 *.tmp（prod 下被 .gitignore 排除）再 os.replace，避免半截檔。

主鍵：fixture_id（整數，API-Football 原生）。隊名僅輔助說明，嚴禁當 ID（§3.1）。
所有路徑經 config.data_dir() 取得，自動依 TEST_MODE 重定向至 data/test|prod。
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from . import config


# =========================================================================
# 路徑
# =========================================================================
def _snapshots_dir() -> Path:
    path = config.data_dir() / "snapshots"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _recommendations_dir() -> Path:
    path = config.data_dir() / "recommendations"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _snapshot_path(fixture_id: int) -> Path:
    return _snapshots_dir() / f"{int(fixture_id)}.json"


# =========================================================================
# 原子寫入 / 讀取
# =========================================================================
def _atomic_write_json(path: Path, data: Any) -> None:
    """原子寫入 JSON：tmp → replace。tmp 副檔名與 .gitignore data/prod/*.tmp 對齊。"""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)  # Windows/POSIX 皆原子


def _read_json(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:  # 具名攔截，部分失敗不阻斷
        import logging

        logging.warning("讀取 JSON 失敗（視為缺檔）: %s — %s", path, e)
        return None


# =========================================================================
# 快照（snapshot）持久化 —— Phase 1 核心
# =========================================================================
def load_snapshot(fixture_id: int) -> Optional[dict]:
    """讀取單場快照檔，無則回 None。"""
    return _read_json(_snapshot_path(fixture_id))


def init_snapshot_record(
    fixture_id: int,
    home: str,
    away: str,
    kickoff_utc: str,
    kickoff_local: str,
) -> dict:
    """建立空白快照骨架（三窗口皆 None）。"""
    return {
        "fixture_id": int(fixture_id),
        "league_id": config.WORLD_CUP_LEAGUE_ID,
        "season": config.WORLD_CUP_SEASON,
        "home": home,
        "away": away,
        "kickoff_utc": kickoff_utc,
        "kickoff_local": kickoff_local,
        "snapshots": {
            config.WINDOW_INITIAL: None,
            config.WINDOW_MID: None,
            config.WINDOW_CLOSING: None,
        },
        "closing_missing": False,
    }


def has_window(fixture_id: int, window: str) -> bool:
    """該場該窗口是否已抓取（用於『窗口內尚未抓取』判定，§3.2）。"""
    rec = load_snapshot(fixture_id)
    if rec is None:
        return False
    snaps = rec.get("snapshots", {})
    if not isinstance(snaps, dict):  # isinstance 防禦（契約 D）
        return False
    return snaps.get(window) is not None


def save_window(fixture_id: int, window: str, base: dict, odds_payload: dict) -> dict:
    """寫入單一窗口快照。base 為 init_snapshot_record 結果（用於首次建檔）。

    odds_payload 形如：
      {"captured_at_local": ISO, "source_bookmaker": int,
       "handicap": {...} | None, "over_under": {...} | None}
    回傳更新後完整紀錄。
    """
    rec = load_snapshot(fixture_id) or base
    snaps = rec.setdefault("snapshots", {})
    if not isinstance(snaps, dict):
        snaps = {}
        rec["snapshots"] = snaps
    snaps[window] = odds_payload
    _atomic_write_json(_snapshot_path(fixture_id), rec)
    return rec


def mark_closing_missing(fixture_id: int) -> None:
    """收盤窗結束仍未抓到 → 標記缺失（回測時排除/降權，§3.2）。"""
    rec = load_snapshot(fixture_id)
    if rec is None:
        return
    rec["closing_missing"] = True
    _atomic_write_json(_snapshot_path(fixture_id), rec)


def list_snapshots() -> list[dict]:
    """列出所有快照紀錄。"""
    out: list[dict] = []
    for p in sorted(_snapshots_dir().glob("*.json")):
        rec = _read_json(p)
        if isinstance(rec, dict):
            out.append(rec)
    return out


# =========================================================================
# 歷史推薦持久化 —— Phase 3 寫入、Phase 2 回測回填
# =========================================================================
def _recommendations_path(date_local: Optional[str] = None) -> Path:
    """按 UTC+8 日期分檔，便於 D+1 回測掃描。"""
    if date_local is None:
        date_local = config.now_local().strftime("%Y-%m-%d")
    return _recommendations_dir() / f"{date_local}.json"


def append_recommendation(record: dict, date_local: Optional[str] = None) -> Path:
    """以 fixture_id 為複合鍵 upsert 一筆推薦至當日推薦檔。"""
    path = _recommendations_path(date_local)
    existing = _read_json(path)
    items: list[dict] = existing if isinstance(existing, list) else []
    fid = record.get("fixture_id")
    items = [it for it in items if it.get("fixture_id") != fid]  # upsert
    items.append(record)
    _atomic_write_json(path, items)
    return path


def load_recommendations(date_local: str) -> list[dict]:
    data = _read_json(_recommendations_path(date_local))
    return data if isinstance(data, list) else []


def save_recommendations(items: list[dict], date_local: str) -> Path:
    """整批覆寫當日推薦檔（回測回填賽果後使用）。"""
    path = _recommendations_path(date_local)
    _atomic_write_json(path, items)
    return path
