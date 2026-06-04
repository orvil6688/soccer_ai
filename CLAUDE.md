# CLAUDE.md — 世界盃足球盤口分析系統 · AI 協作記憶中樞

> ✅ **本檔為 v2.0-phase1A（架構 A：OddsPapi 主源）**：第五節契約已換為 OddsPapi v4，本檔自包含、
> 可讓任何 AI 憑此恢復上下文。實測存證見 `docs/oddspapi_findings.md`、修訂範圍見 `docs/arch_A_proposal.md`。
> `HANDOFF_TO_GEMINI.md`（API-Football 時期）降為歷史參考。
>
> 🔗 **同步紀律**：本檔與 `小g小c協作簡報.md`（協作簡報）為一組記憶中樞。**任一更新，另一份必須同步檢查**。本檔更新時由小cc 一併更新協作簡報。

---

## 🛡️ 團隊分工與溝通約定

**總司令**：最終決策者。溝通高效簡潔。

**小 g（Gemini，首席戰略大腦）**：用四大板塊 SOP 撰寫規格書；軍紀嚴明的軍事幕僚，稱「總司令」。

**小 c（Claude，防禦型策略軍師）**：審查小 g 規格書、抓漏洞防呆、聯合除錯；務實直接，不用軍事敬語。

**小 cc（Claude Code，執行部隊）**：依規格書 Phase 順序精準施工，每 Phase 獨立 commit；發現契約缺失立即停工回報。

**工作流程**：小 g 出規格書 → 小 c 8 點清單審查亮綠燈 → 總司令裁決 → 小 cc 施工 → 聯合除錯。

---

## 一、專案定位

**世界盃足球盤口分析系統**

掃描世界盃賽事 → 賽前不同時間點對讓分盤與大小球抓「初盤→收盤」快照 → 結合基本面與盤口心理找出與莊家的定價歧見 → 出精選推薦 → 存歷史推薦 → 隔日回填賽果做回測，迭代篩選規則。

**本質**：不是「預測比分」，是「找出莊家定價歧見」的博弈系統。AI 信心度非真實勝率，全程標 🤖 AI 推論。

---

## 二、🔒 已拍板決策（12 條，不得更動）

| # | 決策項 | 結果 |
|---|---|---|
| 1 | 範圍 | 完整版：快照存檔 + AI 分析 + 回測閉環 |
| 2 | 首要賽事 | 2026 世界盃（6/11 開幕） |
| 3 | 盤口 | 亞洲讓分盤 + 大小球 |
| 4 | 資金管理 | 凱利取消，固定注碼（價值高 2 單位、一般 1 單位） |
| 5 | 主資料源 | ~~API-Football 免費層~~ → **OddsPapi v4 免費層**（v2.0 修訂解禁，總司令 2026-06-04；API-Football 免費層拿不到 2026 賽季，已實證）|
| 6 | 備援 | ~~BALLDONTLIE~~ **作廢**（無世界盃）→ 交叉驗證改 OddsPapi 內 **Pinnacle vs 1xBet** 對盤 |
| 7 | 爬蟲 | 球探007/Scrapling 為後期實驗，可失敗、不進主流程 |
| 8 | 快照 | ~~三窗口排程~~ → **OddsPapi historical 賽前即時走勢 + 六錨點推導**（v2.0 修訂，見 §5.3）|
| 9 | 回測 | 隔日回填前一日賽果，算命中率調規則 |
| 10 | AI 角色 | 沿用 GEM 開盤手人設，數據掃描改用 API |
| 11 | 施工序 | 6/11 前先上線快照存檔+賽果回填 |
| 12 | 環境 | 脫離 Colab，正式專案結構 |

---

## 三、系統架構

### 板塊組成

```
板塊一：核心抓取    api_client.py（API-Football）/ bdl_client.py（BALLDONTLIE）
板塊二：資料處理    odds_parser.py / snapshot.py（三錨點快照·核心）/ storage.py
板塊三：分析輸出    selector.py（選注引擎）/ analyzer.py（Gemini）
板塊四：流程編排    backtest.py（賽果回填）/ main.py
後期實驗：          scrapers/titan007.py
```

### 資料流向（概念，精確節點 🔜 待規格書 Mermaid 定稿）

```
排程器（錨定各場開賽時間）
  → 三錨點抓盤口快照 → storage 入庫（初盤靠自己存，API 不提供歷史）
  → selector 選注引擎（找歧見 + 誘盤過濾 + 動機檢查）
  → analyzer（Gemini，GEM 人設）→ 出推薦（標 🤖 AI 推論）
  → 隔日 backtest 回填賽果 → 算命中率 → 回頭調 selector 參數
```

失敗分流：致命失敗（金鑰缺/額度盡）→ 中斷；部分失敗（單場錯/BDL 對不上）→ log 不阻斷。

---

## 四、環境變數

`.env`（gitignored，已建 `.env.example`）：
- `ODDSPAPI_API_KEY` — 主資料源（OddsPapi v4）
- `GEMINI_API_KEY` — AI 分析
- `DISCORD_WEBHOOK_URL` / `DISCORD_TEST_WEBHOOK_URL` — 推播
- `DATA_DIR` — 資料輸出目錄
- `TEST_MODE` — 測試隔離開關

> ⚠️ 原 Colab 版金鑰已外洩，總司令須至各後台重置作廢。
> 架構 A：`API_FOOTBALL_KEY` / `BALLDONTLIE_API_KEY` 已停用（舊實作見 `soccer_ai/_legacy/`）。
> CI Secret 名稱須與此一致＝`ODDSPAPI_API_KEY`。

---

## 五、API 與系統契約（v2.0 架構 A 修訂 · 唯一真實來源＝`config.py`）

> 架構 A（總司令 2026-06-04）：主源改 **OddsPapi v4**。實測存證見 `docs/oddspapi_findings.md`、
> 修訂範圍見 `docs/arch_A_proposal.md`。本節為人類可讀摘要，程式以 `config.py` 常數為準。
> 金鑰命名以 **`ODDSPAPI_API_KEY`** 為準（本機 .env 與 CI Secrets 同名）。

### 5.1 API 契約（OddsPapi v4）
- Base `https://api.oddspapi.io/v4`，認證 query `?apiKey=`。
- **sportId = 10**（Soccer）；**tournamentId = 16**（2026 世界盃正盤，104 場）。
- 市場名：**`Asian Handicap`**（spreads，outcome "1"=主/"2"=客）、**`Over Under Full Time`**（totals，Over/Under）；period 取 `fulltime`。
- Bookmaker slug：主 `pinnacle`、交叉驗證 `1xbet`。
- **結算**：`/v4/settlements?fixtureId=` 按 market/outcome 取 result；嚴格 90 分鐘（fulltime）。
- **額度**：免費層 250/月，以 `/v4/account` 的 `request_count` 監控（不計額度）；剩餘 ≤25 告警。
- ⚠️ **`/clv` v4 不存在**（已實打），CLV 自算（見 5.5）。

### 5.2 選注引擎參數
- **Edge 門檻** `edge_threshold = 0.25` 球。
- Pinnacle vs 1xBet 反向線移動 → 列「加權訊號」記錄供回測，**不**直接觸發 2 單位警報。

### 5.3 走勢與六錨點（取代三窗口排程）
- OddsPapi `historical-odds` = **賽前即時走勢**（已實證），不搶時間窗、不需生存法則。
- 對每場拉完整序列（假設不計額度，**未經官方確認**，退場條件見 §8），切六錨點。
- **六錨點**：`initial`（序列首筆=莊家首次開盤）、`t24h`/`t12h`/`t6h`/`t1h`、`closing`。
- **§3.2 寫死三規則**：①取最接近目標時刻一筆 + 存實際時間戳/`offset_sec`；②收盤=序列開賽前最後一筆（≠t1h，§5.5）；③目標時刻落在序列觀測區間 `[最早,最新]` 外（盤開太晚 或 時間未到）→ 該錨點 `null`，不硬塞。
- **不存原始/降採樣序列**，需要時即時重抓（免費）。
- 排程：GitHub Actions Cron `0 * * * *`（每小時），內部 UTC、邏輯轉 **UTC+8**。

### 5.4 各板塊細部
- **Gemini 字數預算（各自獨立截斷，超出以 `...` 替換）**：`confidence_reasoning` 50 / `injury_impact` 100 / `market_reading` 150 字。所有產出強制壓 `🤖 AI 推論`。
- 函式實際呼叫點：`main.py` → `movement.scan()` →（逐場）`process_fixture()` → `oddspapi_client.get_historical_odds()` → `movement.derive_anchors()`（內呼 `odds_parser.parse_point` + `make_historical_price_fn`）→ `storage.save_fixture_movement()`。
- 市場對照表 `/markets`（≈9MB）抓一次後快取 `data/{}/market_map_soccer.json` 重用。

### 5.5 資料結構
- **主鍵**：字串 `fixtureId`（OddsPapi 原生，如 `id1000001666456904`）。隊名僅輔助，嚴禁當 ID。
- **走勢檔**（prod 上線前 schema 仍可改）：`data/{prod|test}/movements/{fixtureId}.json`
  ```json
  {"fixtureId": str, "tournamentId": 16, "sportId": 10, "home": str, "away": str,
   "kickoff_utc": ISO, "kickoff_local": ISO, "bookmaker": str,
   "anchors": {"initial":A, "t24h":A|null, "t12h":A|null, "t6h":A|null, "t1h":A|null, "closing":A},
   "closing_settled": bool, "pulled_at_local": ISO}
  ```
  錨點 A：`{"target_ts": ISO, "handicap": H|null, "over_under": O|null}`；
  `H = {line, home_odd, away_odd, captured_ts, [offset_sec]}`、`O = {line, over_odd, under_odd, captured_ts, [offset_sec]}`。
- **歷史推薦檔**：`data/{prod|test}/recommendations/{YYYY-MM-DD}.json`（list，以 `fixtureId` upsert）。
- **CLV 自算**（v4 無 /clv）：CLV =（收盤錨點的線）對比（推薦產出時記錄的線）；收盤=六錨點的 `closing`；時序防呆：推薦產出時間 ≥ 收盤抓取時間 → 該筆標「無 CLV」。
- **原子寫入**：tmp → `os.replace`；`.gitignore` 已排除 `data/prod/*.tmp`。

---

## 六、Phase 計畫（對應 🔒 #11 施工序）

> 鐵律：6/11 前 Phase 1+2 必須能跑，否則回測永遠生不出勝率。

- **Phase 1（6/11 前必須）**：config + api_client + snapshot + storage（三錨點抓盤存庫）
- **Phase 2（6/11 前必須）**：backtest 賽果回填 + 命中率（閉環最後一塊）
- **Phase 3**：selector 選注引擎 + analyzer（GEM 人設）
- **Phase 4**：bdl_client 交叉驗證 + edge 門檻調校
- **Phase 5（後期）**：xG 接入、scrapers 爬蟲實驗、俱樂部賽季漏斗

---

## 七、開發紀律（繼承通用範本）

- **自包含原則**：規格書/本檔升版時所有契約完整複製，禁止「沿用前版」。
- **AI 推論透明化（契約 I）**：Gemini 輸出強制標 🤖 AI 推論；真實 API ✅；API+AI 補位 🟡。
- **isinstance 防禦（契約 D）**：讀外部 API 陣列前一律 isinstance 檢查。
- **失敗分流雙軌**：致命中斷、部分不阻斷。
- **自動 commit**：每 Phase 獨立 commit，格式 `{type}(version) Phase N - desc`。
- **行尾鐵律**：已建 `.gitattributes`，.py=LF。

---

## 八、事件學習庫

繼承通用教訓（增量描述失契約、行尾踩雷、機器驗收過但 UI 偏差），加本專案實戰：

```
事件：原 Colab 版路徑不一致
根因：建立 Soccer_AI_Apisport 資料夾卻寫入 Soccer_AI_Data
後果：每場寫檔 crash
教訓：路徑常數集中 config.py，建立與寫入共用同一變數
```
```
事件：原 Colab 版 Gemini 從未被呼叫
根因：prompt 組好卻漏 generate_content
後果：核心 AI 功能空轉無輸出
教訓：規格書須明列每模組的「實際呼叫點」，非只定義函式
```
```
事件：API-Football 免費層拿不到 2026 賽季
根因：免費層僅開放 2022–2024 賽季，season=2026 直接被擋（CI log 實證）
後果：原 🔒#5 主資料源對「世界盃」根本不可行
教訓：選資料源必須對「目標賽季/賽事」實打驗證，別只看方案文件；連帶發現 BDL 無世界盃（🔒#6 作廢）
```
```
事件：依賴 OddsPapi historical-odds「不計入 250/月額度」之觀察（指令 B）
性質：實測觀察，未經 OddsPapi 官方確認，可能是免費層設計／隱藏限制／計費 bug
影響：架構 A 以 historical-odds 為主力抓取手段並假設其不耗額度
退場條件：若假設失效（historical 開始計數或被限制）→ 退回 odds-by-tournaments（批量現況盤，會計數）為主，重排額度模型
教訓：把未確認的有利觀察當架構支柱時，務必明列假設與退場路徑，勿寫成不可動鐵律
```

---

## 九、目前狀態

- **最新版本**：v2.0-phase1A（2026-06-04，架構 A：OddsPapi 主源 + 六錨點，Phase 1 重作完工）
- **核心架構**：OddsPapi v4 主源；`historical-odds` 賽前即時走勢 → 推導六錨點 → 選注 → settlement 回測；交叉驗證 Pinnacle vs 1xBet
- **Phase 1A 已完成**（5 commit）：封存 API-Football 舊模組(`_legacy/`)；`config.py`(OddsPapi 契約)；`oddspapi_client.py`(429 退避+額度)；`odds_parser.py`(market_map+主盤線)；`movement.py`(六錨點+三規則)；`storage.py`(字串主鍵+市場表快取)；`main.py`/`main_pipeline.yml`(每小時+移除生存法則)。離線+真打 E2E 測試全綠（真抓 104 場、初盤→收盤走勢正確）。
- **下一步**：Phase 2 — `backtest.py` `/v4/settlements` 賽果回填 + CLV 自算 + 命中率。
- **待總司令動作**：①於 repo Secrets 設 `ODDSPAPI_API_KEY`；②（建議）寄信 OddsPapi 確認 historical 不計額度（見 §8 退場條件）。

---

## 十、絕對不動清單（除非規格書明文解禁）

- `config.py` 金鑰讀取邏輯
- `storage.py` 寫入格式（**prod 上線後**即契約；目前 prod 未上線，schema 仍可改）
- 已上線的走勢/錨點推導邏輯
- `.env`（機密）

---

**本檔版本**：v2.0-phase1A｜格式來源：總司令通用範本 v1.0｜建立 2026-06-02｜架構 A 改版回填 2026-06-04
