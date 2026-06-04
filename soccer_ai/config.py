"""板塊共用：路徑 / 金鑰 / 常數 / OddsPapi 契約的唯一真實來源。

架構 A（規格書 v2.0 修訂，總司令 2026-06-04）：主資料源 = OddsPapi v4。
⚠️ 絕對不動清單：本檔金鑰讀取邏輯。修改需規格書明文解禁。

雙軌金鑰：本機讀 .env；CI 讀 GitHub Secrets（同名環境變數）。
主金鑰命名以 ODDSPAPI_API_KEY 為準。
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # 具名攔截，禁止裸 except；CI 無 dotenv 時改讀真實環境變數
    pass


# =========================================================================
# 一、時區（GH Cron 為 UTC，程式邏輯一律 UTC+8）
# =========================================================================
TZ_UTC = timezone.utc
TZ_LOCAL = timezone(timedelta(hours=8))  # UTC+8 唯一時區基準


def now_local() -> datetime:
    return datetime.now(TZ_LOCAL)


def to_local(dt: datetime) -> datetime:
    """轉 UTC+8。naive 視為 UTC（OddsPapi 回傳多為 UTC ISO）。"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_UTC)
    return dt.astimezone(TZ_LOCAL)


def to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_LOCAL)
    return dt.astimezone(TZ_UTC)


def parse_iso(s: str) -> datetime:
    """解析 ISO 字串（含 Z 結尾）為帶時區 datetime。"""
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


# =========================================================================
# 二、金鑰（雙軌）
# =========================================================================
ODDSPAPI_API_KEY = os.getenv("ODDSPAPI_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
DISCORD_TEST_WEBHOOK_URL = os.getenv("DISCORD_TEST_WEBHOOK_URL", "")


def require_key(name: str) -> str:
    """致命前置檢查：金鑰缺失即拋錯中斷。"""
    value = os.getenv(name, "")
    if not value:
        raise RuntimeError(f"致命：環境變數 {name} 未設定（本機檢查 .env / CI 檢查 Secrets）")
    return value


# =========================================================================
# 三、OddsPapi v4 契約（實打驗證，見 docs/oddspapi_findings.md）
# =========================================================================
ODDSPAPI_BASE = "https://api.oddspapi.io/v4"
ODDSPAPI_LANG = "en"

SPORT_ID_SOCCER = 10
WORLD_CUP_TOURNAMENT_ID = 16  # 2026 世界盃正盤（非資格賽/虛擬/青年盃）

# 市場名稱（對照 /markets 分類；period 取 fulltime）
MARKET_ASIAN_HANDICAP = "Asian Handicap"   # marketType=spreads，outcome "1"=主 "2"=客
MARKET_OVER_UNDER = "Over Under Full Time"  # marketType=totals，outcome Over/Under
MARKET_PERIOD = "fulltime"

# Bookmaker slug（主 + 交叉驗證）
BOOKMAKER_PRIMARY = "pinnacle"
BOOKMAKER_SECONDARY = "1xbet"
BOOKMAKERS = [BOOKMAKER_PRIMARY, BOOKMAKER_SECONDARY]

# 結算口徑：嚴格 90 分鐘（fulltime），不含延長/PK
SETTLEMENT_MINUTES = 90

# =========================================================================
# 四、額度（OddsPapi 免費層；以 /v4/account 的 request_count 監控）
# =========================================================================
# ⚠️ 假設：historical-odds 不計入此額度（實測觀察，未經官方確認）。
#    退場條件見 CLAUDE.md 事件庫；若失效須退回 odds-by-tournaments。
MONTHLY_REQUEST_LIMIT = 250
REQUEST_ALERT_REMAINING = 25  # 剩餘 <= 此值 → Discord 告警

# heavy 端點節流（OddsPapi 文件：historical 屬「其他端點 200/分」桶；
# 但 5.7MB 大回應實測 sub-1/s 即 429，故保守設基礎間隔，遠低於 200/分）。
MIN_REQUEST_INTERVAL_SEC = 3.0            # 每次請求間「基礎間隔」（不只 429 後才等）
BACKOFF_SCHEDULE = [1.5, 3.0, 6.0]        # 429 指數退避（秒），長度＝最大重試次數
MAX_RETRY_ON_429 = len(BACKOFF_SCHEDULE)  # 超過即標該場抓取失敗、跳過（部分失敗分流）

# 按距開賽時間篩選（避免對 45 天後賽事每次都打 historical）
FORWARD_WINDOW = timedelta(hours=48)  # 只對 48h 內開賽者抓「五錨點」
SETTLE_GRACE = timedelta(hours=3)     # 賽後 3h 內允許一次「收盤定版」拉取

# =========================================================================
# 五、六錨點（規格書 §3.2 寫死；不存原始/降採樣序列）
# =========================================================================
# initial / closing 由序列位置定義；以下四個為「開賽前 Nh」目標時刻錨點。
ANCHOR_INITIAL = "initial"
ANCHOR_CLOSING = "closing"
ANCHOR_OFFSETS = {  # 錨點名 → kickoff 前的時長（目標時刻 = kickoff - offset）
    "t24h": timedelta(hours=24),
    "t12h": timedelta(hours=12),
    "t6h": timedelta(hours=6),
    "t1h": timedelta(hours=1),
}
# 錨點輸出順序（含位置型）
ANCHOR_ORDER = [ANCHOR_INITIAL, "t24h", "t12h", "t6h", "t1h", ANCHOR_CLOSING]

# =========================================================================
# 六、選注與 AI 契約（沿用）
# =========================================================================
EDGE_THRESHOLD = 0.25

WORD_BUDGET = {
    "confidence_reasoning": 50,
    "injury_impact": 100,
    "market_reading": 150,
}
AI_TAG = "🤖 AI 推論"

# =========================================================================
# 七、路徑與 TEST_MODE 隔離（沿用）
# =========================================================================
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(_PROJECT_ROOT / "data")))

PROD_SUBDIR = "prod"
TEST_SUBDIR = "test"
TEST_TAG = "🧪"

_test_mode = os.getenv("TEST_MODE", "true").strip().lower() in ("1", "true", "yes")


def set_test_mode(enabled: bool) -> None:
    global _test_mode
    _test_mode = bool(enabled)


def is_test_mode() -> bool:
    return _test_mode


def data_dir() -> Path:
    """依當前 TEST_MODE 回傳資料根目錄（test→data/test、prod→data/prod）。"""
    sub = TEST_SUBDIR if _test_mode else PROD_SUBDIR
    path = DATA_DIR / sub
    path.mkdir(parents=True, exist_ok=True)
    return path
