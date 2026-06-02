# CLAUDE.md — 世界盃足球盤口分析系統 · AI 協作記憶中樞

> ✅ **本檔為 v2.0-phase1**：規格書 v2.0 終極定案契約已回填第五節，本檔已自包含、
> 可讓任何 AI 憑此恢復上下文。`HANDOFF_TO_GEMINI.md` 降為歷史交接參考。
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
| 5 | 主資料源 | API-Football 免費層 |
| 6 | 備援 | BALLDONTLIE 免費層（交叉驗證） |
| 7 | 爬蟲 | 球探007/Scrapling 為後期實驗，可失敗、不進主流程 |
| 8 | 快照 | 錨定開賽時間，抓 初盤/中段(T-12h)/收盤(T-1~2h) |
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
- `API_FOOTBALL_KEY` — 主資料源
- `BALLDONTLIE_API_KEY` — 備援交叉驗證
- `GEMINI_API_KEY` — AI 分析
- `DATA_DIR` — 資料輸出目錄
- `TEST_MODE` — 測試隔離開關

> ⚠️ 原 Colab 版金鑰已外洩，總司令須至各後台重置作廢。

---

## 五、API 與系統契約（規格書 v2.0 回填 · 唯一真實來源＝`config.py`）

> 來源：規格書 v2.0 終極定案版。本節為人類可讀摘要，程式以 `config.py` 常數為準。
> 金鑰命名以 **`API_FOOTBALL_KEY`** 為準（本機 .env 與 CI Secrets 同名，總司令 2026-06-02 裁定）。

### 5.1 API 契約（API-Football）
- 世界盃 **League ID = 1**；**Season = 2026**。
- 盤口 **Bet ID**：亞洲讓分盤 `4`、大小球 `5`。
- **Bookmaker 優先序**：`[4, 8, 41]`（Pinnacle / Bet365 / 1xBet）。
- **結算口徑**：嚴格 90 分鐘（含補時），不含延長/PK。
- **Rate Limit**：100 次/日；已用達 95（剩餘 ≤5）→ Discord 告警並中止當次執行。
- BALLDONTLIE `game_id` 對齊邏輯延至 Phase 4 定義，現不得含糊實作。

### 5.2 選注引擎參數
- **Edge 門檻** `edge_threshold = 0.25` 球。
- Pinnacle vs 1xBet 反向線移動 → 列「加權訊號」記錄供回測，**不**直接觸發 2 單位警報。

### 5.3 快照排程（三窗口容錯，不依賴精確時間點）
- **初盤 initial**：首見盤口即抓，抓完標記完成（實作層額外加 14 天掃描地平線防爆額度）。
- **中段 mid**：開賽前 T-13h ~ T-11h。
- **收盤 closing**：開賽前 T-90m ~ T-45m。
- **收盤缺失**：過收盤窗下緣仍未抓 → 標 `closing_missing`，回測排除/降權。
- **API 生存法則**：剩餘 ≤15 次 → 拒絕 initial/mid，全額度死守收盤窗。
- 排程：GitHub Actions Cron `*/15`，內部 UTC、邏輯一律轉 **UTC+8**。

### 5.4 各板塊細部
- **Gemini 字數預算（各自獨立截斷，超出以 `...` 替換）**：`confidence_reasoning` 50 / `injury_impact` 100 / `market_reading` 150 字。所有產出強制壓 `🤖 AI 推論`。
- 函式實際呼叫點：`main.py` → `snapshot.run_snapshot_scan()` →（逐場）`process_fixture()` → `api_client.get_fixture_odds()` → `odds_parser.parse_odds_snapshot()` → `storage.save_window()`。

### 5.5 資料結構
- **主鍵**：`fixture_id`（整數，API-Football 原生）。隊名僅輔助，嚴禁當 ID。
- **快照檔**（上線即契約）：`data/{prod|test}/snapshots/{fixture_id}.json`
  ```json
  {"fixture_id": int, "league_id": 1, "season": 2026, "home": str, "away": str,
   "kickoff_utc": ISO, "kickoff_local": ISO,
   "snapshots": {"initial": payload|null, "mid": payload|null, "closing": payload|null},
   "closing_missing": bool}
  ```
  window payload：`{"captured_at_local": ISO, "source_bookmaker": int, "source_bookmaker_name": str, "handicap": {"line","home_odd","away_odd"}|null, "over_under": {"line","over_odd","under_odd"}|null}`
- **歷史推薦檔**：`data/{prod|test}/recommendations/{YYYY-MM-DD}.json`（list，以 `fixture_id` upsert，UTC+8 日期分檔）。
- **CLV 時序防呆**：推薦產出時間 ≥ 收盤抓取時間 → 該筆 `CLV = "無 CLV"`，只有收盤前產出者計入期望值回測。
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

---

## 九、目前狀態

- **最新版本**：v2.0-phase1（2026-06-02，規格書 v2.0 終極定案 + Phase 1 完工）
- **核心架構**：API-Football 主 + BALLDONTLIE 備，三窗口容錯快照 → 選注 → 回測閉環
- **Phase 1 已完成**：git init；`config.py`（全契約常數 + UTC+8 + 雙軌金鑰 + TEST_MODE 隔離）；`api_client.py`（額度控管 + 收盤優先生存鉤子 + isinstance）；`odds_parser.py`（型別固定解析）；`snapshot.py`（三窗口容錯掃描）；`storage.py`（原子寫入 + 隔離）；`main.py`（失敗分流 + `--test`）；`main_pipeline.yml`（Cron `*/15` + 跑完 commit&push）。離線煙霧測試全綠。
- **下一步**：Phase 2 — `backtest.py` D+1 賽果回填 + CLV 時序防呆 + 命中率。
- **待總司令動作**：①建 GitHub remote 並推送；②於 repo Secrets 設 `API_FOOTBALL_KEY`（外洩舊金鑰須作廢重置）。

---

## 十、絕對不動清單（除非規格書明文解禁）

- `config.py` 金鑰讀取邏輯
- `storage.py` 歷史檔寫入格式（上線後即契約）
- 已上線的快照排程錨點邏輯
- `.env`（機密）

---

**本檔版本**：v2.0-phase1｜格式來源：總司令通用範本 v1.0｜建立 2026-06-02｜Phase 1 完工回填
