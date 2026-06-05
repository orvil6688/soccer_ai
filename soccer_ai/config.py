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


def local_date(dt) -> str:
    """任意 datetime / ISO 字串 → UTC+8 日曆日 'YYYY-MM-DD'。

    推薦記錄「存（select）/撈（backtest）」共用此函式，杜絕一邊 UTC 一邊 UTC+8 的跨日漏撈。
    例：KO '2026-06-12T03:00+08:00'（UTC 06-11T19:00Z）→ '2026-06-12'。
    """
    if isinstance(dt, str):
        dt = parse_iso(dt)
    return to_local(dt).strftime("%Y-%m-%d")


# =========================================================================
# 二、金鑰（雙軌）
# =========================================================================
ODDSPAPI_API_KEY = os.getenv("ODDSPAPI_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# Discord 四把 webhook（值僅由總司令自填 .env/Secret；程式只 os.getenv 讀、不經手不印）
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")              # 📋-推薦單（正式）
DISCORD_TEST_WEBHOOK_URL = os.getenv("DISCORD_TEST_WEBHOOK_URL", "")    # 🧪-測試（TEST_MODE）
DISCORD_BACKTEST_WEBHOOK_URL = os.getenv("DISCORD_BACKTEST_WEBHOOK_URL", "")  # 📊-回測戰報（推播後續）
DISCORD_ALERT_WEBHOOK_URL = os.getenv("DISCORD_ALERT_WEBHOOK_URL", "")        # ⚠️-系統告警（推播後續）


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
# 但 5.7MB 大回應在 GitHub Actions 共用 IP 上被限更嚴：本機 3s 零 429，雲端 3s 每場
# 先撞一次（靠重試成功、約 6s/場）。故拉長基礎間隔至 8s，讓雲端多數呼叫第一次就過）。
MIN_REQUEST_INTERVAL_SEC = 8.0            # 每次請求間「基礎間隔」（不只 429 後才等）
BACKOFF_SCHEDULE = [3.0, 6.0, 12.0]       # 429 指數退避（秒），長度＝最大重試次數
MAX_RETRY_ON_429 = len(BACKOFF_SCHEDULE)  # 超過即標該場抓取失敗、跳過（部分失敗分流）

# 按距開賽時間篩選（避免對數十天後賽事每次都打 historical）
MOVEMENT_WINDOW = timedelta(hours=80)  # 只對 80h 內開賽者拉取（涵蓋 t72h 決策錨點）
SETTLE_GRACE = timedelta(hours=3)      # 賽後 3h 內允許一次「收盤定版」拉取

# =========================================================================
# 五、八錨點 + 盤口軌跡（schema v2；不存原始/降採樣序列）
# =========================================================================
SCHEMA_VERSION = 2

# initial / closing 由序列位置定義；以下六個為「開賽前 Nh」目標時刻錨點。
ANCHOR_INITIAL = "initial"
ANCHOR_CLOSING = "closing"
ANCHOR_OFFSETS = {  # 錨點名 → kickoff 前的時長（目標時刻 = kickoff - offset）
    "t72h": timedelta(hours=72),
    "t24h": timedelta(hours=24),
    "t12h": timedelta(hours=12),
    "t6h": timedelta(hours=6),
    "t1h": timedelta(hours=1),
    "t30m": timedelta(minutes=30),
}
ANCHOR_DECISION = ["t72h", "t24h", "t12h", "t6h", "t1h", "t30m"]  # 決策核心（選注/推論主依據）
ANCHOR_BACKTEST = [ANCHOR_INITIAL, ANCHOR_CLOSING]                # 回測輔助（initial 噪音、closing CLV）
ANCHOR_ORDER = [ANCHOR_INITIAL, *ANCHOR_DECISION, ANCHOR_CLOSING]
ANCHOR_ROLE = {a: ("decision" if a in ANCHOR_DECISION else "backtest") for a in ANCHOR_ORDER}

# 多家盤口（CROWN 雙記）：movement 對每家各記一套軌跡。bookmaker 為 schema 頂層 key，
# 加新家＝加 key、零 schema 遷移。singbet＝皇冠(Crown) skin（覆蓋較少場，缺場該家標 null）。
MOVEMENT_BOOKMAKERS = ["pinnacle", "singbet"]

# 軌跡判定門檻（全「待回測校準」）
LINE_STEP = 0.25                 # 一級＝0.25 球
ODDS_FLAT_EPS = 0.02             # 裸賠率變化 <= 此值視為 flat（tag 用）
PROB_FLAT_EPS = 0.01             # 去水位後公允機率位移 <= 此值視為 flat（訊號用，濾水位假動作）
FAV_EPS = 0.02                   # 兩邊賠率差 <= 此值視為無明顯低水方(even)
SHAPE_SPIKE_EXCURSION_STEPS = 2  # spike_revert：最大偏離 >= 此級數且頭尾回歸
SHAPE_MONO_NET_STEPS = 2         # monotonic：同向且淨移動 >= 此級數
SHAPE_LATE_SWING_STEPS = 2       # late_swing：末段(1h→30m)位移 >= 此級數

# =========================================================================
# 六、選注與 AI 契約（沿用）
# =========================================================================
EDGE_THRESHOLD = 0.25  # 線差主閘（球）

# --- 選注引擎參數（Phase 3；多為「待回測校準」預設）---
# edge 哲學：Pinnacle 去水位求公允 vs 1xBet 偏差 + 線移動。AI 不參與選注。
EDGE_PCT_THRESHOLD = 0.02          # 價差次閘（同線時的 EV%），待校準
SELECT_WINDOW_HOURS = 24           # 只對開賽前 <= 此時數的場次選注，待校準
TRAP_EDGE_GOALS_MAX = 1.0          # 盤太甜上限（球）：超過視為陷阱/過期，待校準
TRAP_EDGE_PCT_MAX = 0.12           # 盤太甜上限（EV%），待校準
KEY_NUMBERS_TOTAL = [2.5, 3.0]     # 大小球關鍵數字
KEY_NUMBERS_HANDICAP = [0.0, 0.5, 1.0]  # 讓分關鍵數字
STAKE2_EDGE_GOALS = 0.5            # 2 單位門檻（球）：須再加同向線移動確認，待校準
# 動機層 v1 不做（空鉤子，延後；理由見 docs/phase3_proposal.md §0.2）
DEATH_GROUP_TEAMS: list[str] = []  # 死亡之組隊名清單（命中降權），預設空＝停用

WORD_BUDGET = {
    "confidence_reasoning": 50,
    "injury_news_inference": 100,   # 由盤口反推的傷病/陣容消息推測（無傷停源、不宣稱已證實）
    "market_reading": 150,
}
AI_TAG = "🤖 AI 推論"
# Gemini 模型（新 SDK google-genai 實查，2026-06-06）。此金鑰實測：2.0-flash 免費配額為 0、
# 2.5-flash 有配額 → 用 2.5-flash 並關 thinking(thinking_budget=0，免 thinking 吃 output token)。
# 2.5-flash 偶 503 高負載 → 由 analyze 部分失敗處理(非致命，下次重試)。
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_THINKING_BUDGET = 0  # 關閉 thinking（結構化短輸出不需要，且免吃 output 額度）

# =========================================================================
# 七、路徑與 TEST_MODE 隔離（沿用）
# =========================================================================
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
# 防呆：DATA_DIR 環境變數「設了但空字串」（.env 常見 `DATA_DIR=`）應回退預設，
# 否則 Path("") = 當前目錄 → 資料誤寫到 repo 根的 ./test、./prod。
_DATA_DIR_ENV = os.getenv("DATA_DIR", "").strip()
DATA_DIR = Path(_DATA_DIR_ENV) if _DATA_DIR_ENV else (_PROJECT_ROOT / "data")

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
