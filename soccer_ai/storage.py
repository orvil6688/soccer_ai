"""板塊二：走勢/錨點 & 推薦持久化（架構 A，支援 TEST_MODE 隔離）。

⚠️ 寫入格式上線後即契約（目前 prod 未上線，schema 仍可改）。
原子寫入：先寫 *.tmp（prod 下被 .gitignore 排除）再 os.replace。
主鍵：字串 fixtureId（OddsPapi 原生）。所有路徑經 config.data_dir() 取得。
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

from . import config

logger = logging.getLogger(__name__)


# =========================================================================
# 路徑
# =========================================================================
def _movements_dir() -> Path:
    p = config.data_dir() / "movements"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _recommendations_dir() -> Path:
    p = config.data_dir() / "recommendations"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _safe_name(fixture_id: str) -> str:
    """fixtureId 形如 'id1000001666456904'，僅留安全字元當檔名。"""
    return "".join(c for c in str(fixture_id) if c.isalnum() or c in ("-", "_"))


# =========================================================================
# 原子寫入 / 讀取
# =========================================================================
def _atomic_write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _read_json(path: Path) -> Optional[Any]:
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:  # 具名攔截，部分失敗不阻斷
        logger.warning("讀取 JSON 失敗（視為缺檔）: %s — %s", path, e)
        return None


# =========================================================================
# 走勢/錨點記錄（movement）—— 核心
# =========================================================================
def _movement_path(fixture_id: str) -> Path:
    return _movements_dir() / f"{_safe_name(fixture_id)}.json"


def save_fixture_movement(record: dict) -> Path:
    path = _movement_path(record["fixtureId"])
    _atomic_write_json(path, record)
    return path


def load_fixture_movement(fixture_id: str) -> Optional[dict]:
    rec = _read_json(_movement_path(fixture_id))
    return rec if isinstance(rec, dict) else None


def list_movements() -> list[dict]:
    out: list[dict] = []
    for p in sorted(_movements_dir().glob("*.json")):
        rec = _read_json(p)
        if isinstance(rec, dict):
            out.append(rec)
    return out


# =========================================================================
# 市場對照表快取（reference data；可進 prod 版控免重抓）
# =========================================================================
def _market_map_path() -> Path:
    return config.data_dir() / "market_map_soccer.json"


def save_market_map(market_map: dict) -> Path:
    path = _market_map_path()
    _atomic_write_json(path, market_map)
    return path


def load_market_map() -> Optional[dict]:
    data = _read_json(_market_map_path())
    return data if isinstance(data, dict) and data else None


# =========================================================================
# 歷史推薦持久化（Phase 3 寫入、Phase 2 回測回填）
# =========================================================================
def _recommendations_path(date_local: Optional[str] = None) -> Path:
    if date_local is None:
        date_local = config.now_local().strftime("%Y-%m-%d")
    return _recommendations_dir() / f"{date_local}.json"


def append_recommendation(record: dict, date_local: Optional[str] = None) -> Path:
    """以 fixtureId 為鍵 upsert 一筆推薦至當日推薦檔。"""
    path = _recommendations_path(date_local)
    existing = _read_json(path)
    items: list[dict] = existing if isinstance(existing, list) else []
    fid = record.get("fixtureId")
    items = [it for it in items if it.get("fixtureId") != fid]
    items.append(record)
    _atomic_write_json(path, items)
    return path


def load_recommendations(date_local: str) -> list[dict]:
    data = _read_json(_recommendations_path(date_local))
    return data if isinstance(data, list) else []


def save_recommendations(items: list[dict], date_local: str) -> Path:
    path = _recommendations_path(date_local)
    _atomic_write_json(path, items)
    return path
