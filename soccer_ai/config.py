"""板塊共用：路徑 / 金鑰 / 常數 / league id / 盤口契約的唯一真實來源。

規格書 v2.0 §3.3「環境、時區與 API 缺口鎖定」逐字落地。
⚠️ 絕對不動清單：本檔金鑰讀取邏輯。修改需規格書明文解禁。

雙軌金鑰：
  - 本機：讀取 .env（python-dotenv）
  - CI（GitHub Actions）：讀 GitHub Secrets 注入的環境變數（不存在 .env）
金鑰命名以 API_FOOTBALL_KEY 為準（本機 .env 與 CI Secrets 同名）。
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

# --- .env 載入（CI 無 .env 檔時靜默略過，改讀真實環境變數）---
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # 具名攔截，禁止裸 except
    # 部署環境未裝 python-dotenv 時不致命，環境變數仍可由 CI 注入
    pass


# =========================================================================
# 一、時區（§3.3 時區轉換陷阱：GH Cron 為 UTC，程式邏輯一律 UTC+8）
# =========================================================================
TZ_UTC = timezone.utc
TZ_LOCAL = timezone(timedelta(hours=8))  # UTC+8 唯一時區基準


def now_local() -> datetime:
    """系統當下時間，一律以 UTC+8 表示（排程比對、壓碼皆用此）。"""
    return datetime.now(TZ_LOCAL)


def to_local(dt: datetime) -> datetime:
    """將任意 datetime 轉為 UTC+8。naive 視為 UTC（API 回傳多為 UTC ISO）。"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_UTC)
    return dt.astimezone(TZ_LOCAL)


def to_utc(dt: datetime) -> datetime:
    """將任意 datetime 轉為 UTC。naive 視為 UTC+8（本系統內部基準）。"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_LOCAL)
    return dt.astimezone(TZ_UTC)


# =========================================================================
# 二、金鑰（雙軌，§3.3）
# =========================================================================
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "")
BALLDONTLIE_API_KEY = os.getenv("BALLDONTLIE_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
# 測試模式專用推播頻道（§3.4 推播分流，可空 → 測試模式略過推播）
DISCORD_TEST_WEBHOOK_URL = os.getenv("DISCORD_TEST_WEBHOOK_URL", "")


def require_key(name: str) -> str:
    """致命前置檢查：金鑰缺失即拋錯中斷（§失敗分流：致命）。"""
    value = os.getenv(name, "")
    if not value:
        raise RuntimeError(f"致命：環境變數 {name} 未設定（本機檢查 .env / CI 檢查 Secrets）")
    return value


# =========================================================================
# 三、API-Football 契約（§3.3）
# =========================================================================
API_FOOTBALL_BASE = "https://v3.football.api-sports.io"
API_FOOTBALL_HOST = "v3.football.api-sports.io"

WORLD_CUP_LEAGUE_ID = 1  # 世界盃 League ID（API-Football）
WORLD_CUP_SEASON = 2026  # 2026 世界盃

# 盤口 Bet ID
BET_ID_ASIAN_HANDICAP = 4  # 亞洲讓分盤
BET_ID_OVER_UNDER = 5      # 大小球

# Bookmaker 優先序：Pinnacle, Bet365, 1xBet
BOOKMAKER_PRIORITY = [4, 8, 41]
BOOKMAKER_PINNACLE = 4
BOOKMAKER_1XBET = 41

# 結算口徑：嚴格 90 分鐘（含補時），不含延長賽/PK
SETTLEMENT_MINUTES = 90

# =========================================================================
# 四、Rate Limit 與 API 生存法則（§3.2 / §3.3）
# =========================================================================
API_DAILY_LIMIT = 100          # API-Football 免費層上限 100 次/日
API_ALERT_THRESHOLD = 95       # 達 95 次：Discord 告警並中止當次執行
API_SURVIVAL_THRESHOLD = 15    # 剩餘 <= 15 次：生存模式，僅允許收盤窗抓取

# =========================================================================
# 五、三大快照時間窗口（§3.2，以「開賽前剩餘時間」界定）
# =========================================================================
# 初盤 (initial)：首次發現賽事擁有盤口即抓，無時間窗（由 storage 狀態判定是否已抓）
WINDOW_INITIAL = "initial"
WINDOW_MID = "mid"
WINDOW_CLOSING = "closing"

# 中段 (mid)：開賽前 T-13h ~ T-11h
MID_WINDOW_OPEN = timedelta(hours=13)
MID_WINDOW_CLOSE = timedelta(hours=11)

# 收盤 (closing)：開賽前 T-90m ~ T-45m
CLOSING_WINDOW_OPEN = timedelta(minutes=90)
CLOSING_WINDOW_CLOSE = timedelta(minutes=45)

# 初盤掃描地平線（實作層額度防呆，非規格書業務契約；可調）：
# 僅對「開賽前 <= 此時長」的賽事嘗試抓初盤，避免每跑都掃數週外賽事爆額度。
INITIAL_SCAN_HORIZON = timedelta(days=14)

# =========================================================================
# 六、選注與 AI 契約（§3.5）
# =========================================================================
EDGE_THRESHOLD = 0.25  # Edge 出手門檻（球）

# Gemini 文字字數預算（各自獨立截斷，超出以 ... 替換，§3.5）
WORD_BUDGET = {
    "confidence_reasoning": 50,
    "injury_impact": 100,
    "market_reading": 150,
}

AI_TAG = "🤖 AI 推論"  # 強制壓上於所有 Gemini 產出

# =========================================================================
# 七、路徑與 TEST_MODE 隔離（§3.4）
# =========================================================================
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(_PROJECT_ROOT / "data")))

PROD_SUBDIR = "prod"
TEST_SUBDIR = "test"
TEST_TAG = "🧪"  # 測試產出視覺標記

# TEST_MODE 由 .env 決定預設值，可由 main.py 的 --test 旗標於執行期覆寫
_test_mode = os.getenv("TEST_MODE", "true").strip().lower() in ("1", "true", "yes")


def set_test_mode(enabled: bool) -> None:
    """執行期覆寫測試模式（main.py 解析 --test 旗標後呼叫）。"""
    global _test_mode
    _test_mode = bool(enabled)


def is_test_mode() -> bool:
    return _test_mode


def data_dir() -> Path:
    """依當前 TEST_MODE 回傳資料根目錄。

    test → data/test/（完全 Git 忽略）
    prod → data/prod/（git commit 追蹤）
    每次呼叫即時反映 set_test_mode，故讀寫一律經此函式取得路徑。
    """
    sub = TEST_SUBDIR if _test_mode else PROD_SUBDIR
    path = DATA_DIR / sub
    path.mkdir(parents=True, exist_ok=True)
    return path
