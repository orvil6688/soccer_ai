# CLAUDE.md — 世界盃足球盤口分析系統 · AI 協作記憶中樞

> ✅ **本檔為 v2.0-traj（架構 A：OddsPapi 主源 + 八錨點盤口軌跡分類 schema v2）**：第五節契約自包含、
> 可讓任何 AI 憑此恢復上下文。存證：`docs/oddspapi_findings.md`、`docs/arch_A_proposal.md`、
> `docs/phase3_proposal.md`、`docs/movement_trajectory_proposal.md`。`HANDOFF_TO_GEMINI.md`（API-Football 時期）降為歷史參考。
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
- **結算**：`/v4/settlements?fixtureId=` 按 market/outcome 取 result；嚴格 90 分鐘（fulltime）。result 列舉（實測）：`WIN/LOSE/HALFWIN/HALFLOSS/PUSH/UNDECIDED`（不提供比分，result 直接給）。
- **額度**：免費層 250/月，以 `/v4/account` 的 `request_count` 監控（不計額度）；剩餘 ≤25 告警。
- ⚠️ **`/clv` v4 不存在**（已實打），CLV 自算（見 5.5）。

### 5.2 選注引擎參數
- **Edge 門檻** `edge_threshold = 0.25` 球：Pinnacle 去水位求公允 vs 1xBet 偏差（線差為主閘、同線價差 EV% 為次閘）。AI 不參與選注。
- **訊號改 trajectory**（見 5.6）：`selector.line_movement_signal`（線-only）已**移除**，改 `trajectory_signal` 讀軌跡 summary —— 線動以線方向為主、**線不動看 de-vig 公允機率位移**（能抓「線黏住但賠率動」、濾掉兩邊一起調水位的假動作）→ confirm/reverse/flat。
- 反向線移動只記「加權訊號」供回測，**不**單獨觸發 2 單位。動機層(D) v1 不做（空鉤子）。

### 5.3 走勢與八錨點（schema v2，取代三窗口排程）
- OddsPapi `historical-odds` = **賽前即時走勢**（已實證），不搶時間窗、不需生存法則。對每場拉完整序列（假設不計額度，**未經官方確認**，退場條件見 §8）切八錨點。
- **八錨點**（每錨點存 `線/雙邊賠率/target_ts/captured_ts`(+`offset_sec`)+`role`）：
  - **決策核心 6**：`t72h`/`t24h`/`t12h`/`t6h`/`t1h`/`t30m`（選注/推論主依據）
  - **回測輔助 2**：`initial`（序列首筆=莊家試水溫，噪音，不當決策訊號）、`closing`（開賽前最後一筆，來不及投注，僅 CLV/回測對照）
- **§3.2 寫死三規則**：①取最接近目標時刻一筆 + 存時間戳/`offset_sec`；②收盤≠t30m，各自獨立；③目標落在序列觀測區間 `[最早,最新]` 外（盤開太晚 或 時間未到）→ `null`，不硬塞。
- **不存原始/降採樣序列**，需要時即時重抓（免費）。
- **抓取範圍與節流**：節流基礎間隔 **8s/次**、429 指數退避 `[3,6,12]`耗盡標該場失敗跳過；**拉取窗 80h**（涵蓋 t72h），遠期僅抓一次 initial、賽後 3h 內定版收盤後不再抓；**隊名 placeholder 判未開盤**（`hasOdds` 全 true 不可用）→ placeholder 跳過不打 API。
- 排程：GH Actions Cron `0 * * * *`（每小時，UTC→UTC+8）；回測準確度靠賽後 settle 拉取保證，頻率只影響賽前決策新鮮度。

### 5.4 各板塊細部
- **🔒 analyzer 定位（釘死，不走回頭路）**：
  - Gemini ＝**推論評論員**：只解釋盤口為何這樣動，**不選注、不給信心分、不算注碼**。`confidence_reasoning` 是「信心理由」**敘述**，非驅動決策的分數。
  - **選注永遠是 selector 純數學**；Gemini 在 selector **之後**跑、**碰不到 pick**（不能改 market/side/line/stake/edge）。
  - 舊「GEM 開盤手一條龍（AI 自己掃描+評分+選注+凱利）」＝Colab 時代玩法，**已被現架構取代，不走回頭路**。
  - 數據面（xG/傷兵）餵進 analyzer prompt＝**Phase 5 接 xG 後才做**；現在 analyzer 只吃盤口軌跡。
  - **`GEMINI_MODEL` 鎖 `gemini-2.5-flash`**（2026-06-06 拍板）：pro 為 flash 約 23× 價但純盤口反推品質差距邊際；Phase 5 多維推理後再評估升 pro。
- **Gemini 字數預算（各自獨立截斷，超出以 `...` 替換）**：`confidence_reasoning` 50 / `injury_news_inference` 100 / `market_reading` 150 字。所有產出包進 `ai{}` 區塊強制壓 `🤖 AI 推論`（區塊層 tag，不佔字數）。`injury_news_inference`＝由盤口反推的傷病/陣容消息推測（無真實傷停源，僅盤口反推、不宣稱已證實傷情）。
- 函式實際呼叫點：`main.py --mode movement` → `movement.scan()` →（逐場、逐 book）`process_fixture()` → `oddspapi_client.get_historical_odds()` → `trajectory.build()`（八錨點+segment+summary）→ `storage.save_fixture_movement()`。`--mode backtest` → `backtest.run_backfill()`。
- 市場對照表 `/markets`（≈9MB）抓一次後快取 `data/{}/market_map_soccer.json` 重用。

### 5.5 資料結構
- **主鍵**：字串 `fixtureId`（OddsPapi 原生）。隊名僅輔助，嚴禁當 ID。
- **走勢檔 v2**（`schema_version:2`；prod 上線前可改）：`data/{prod|test}/movements/{fixtureId}.json`
  ```json
  {"schema_version":2, "fixtureId":str, "tournamentId":16, "sportId":10, "home":str,"away":str,
   "kickoff_utc":ISO, "kickoff_local":ISO, "books":["pinnacle","singbet"],
   "trajectory": { "<book>": { "handicap":{anchors,segments,summary}, "over_under":{...} } },
   "closing_settled":bool, "pulled_at_local":ISO}
  ```
  錨點：`{target_ts,captured_ts,offset_sec,line, home_odd/away_odd 或 over_odd/under_odd}`（或 null）。
- **歷史推薦檔**：`data/{prod|test}/recommendations/{YYYY-MM-DD}.json`（list，以 `fixtureId` upsert）。
  推薦 schema（selector 產出、backtest 消費）：`{fixtureId, produced_at_local, kickoff_utc, market, side, line, odds, stake_units, signals{signal,shape,tag,...}, trajectory{book:{shape,tag,...}}}`；backtest 回填 `result/pnl_units/settled/clv`。
- **CLV 自算**（v4 無 /clv）：CLV% =（推薦產出賠率 / 收盤賠率 − 1），收盤＝重抓 historical 取「該確切線/邊」開賽前最後一筆；時序防呆：產出時間 ≥ 收盤抓取時間 → `no_clv`。
- **單位損益**：WIN→+stake×(odds−1)、HALFWIN→半、PUSH→0、HALFLOSS→−stake/2、LOSE→−stake。命中率 PUSH 不計分母、半贏半輸計 0.5。**`by_trajectory`**：依 shape 分組出命中率/單位（統計「某軌跡形狀 → 真實過盤率」）。
- **原子寫入**：tmp → `os.replace`；`.gitignore` 已排除 `data/prod/*.tmp`。

### 5.6 盤口軌跡分類（系統核心智慧；系統＝事實層、不解讀意圖）
- **schema 三層**：`trajectory → bookmaker → market → {anchors(8), segments(決策相鄰), summary}`。bookmaker 為頂層 key，**加家＝加 key、零遷移**。
- **CROWN 雙記**：`MOVEMENT_BOOKMAKERS = [pinnacle, singbet]`（singbet＝皇冠 Crown skin，免費層覆蓋較少場；mansion88 本尊免費層 403 受限）。兩家各記一套軌跡，回測比哪家 sharp。
- **segment 四維**：①線升降幾級（一級＝0.25，`級=(新線−舊線)/0.25`）②我方賠率方向 ③對方賠率方向 ④**水互換**（看低水方[賠率較低那邊]有沒有換邊，**與線升降無關**）。
- **summary**：net級數/abs路徑/max偏離/reverted/方向變數/late_swing/水互換次數 + de-vig 機率位移 + **中性 shape** + 客觀結構化中文 tag（如「平0級·水互換·主升客升」）。
- **shape 中性枚舉**：`flat/odds_drift/fav_swap/gradual/monotonic/spike_revert/late_swing/choppy/mixed`。系統只描述「怎麼動」；**動機（洗盤/誘散戶/消息走漏）留 Gemini 標 🤖**，shape 名不叫「洗盤」。線不動時改看賠率/水互換維度 → 不誤判 flat。
- 門檻全「待回測校準」（`LINE_STEP/ODDS_FLAT_EPS/PROB_FLAT_EPS/FAV_EPS/shape 規則`）；shape 第一版待小組賽真實資料對照看盤迭代。

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
```
事件：原 selector「線-only 訊號」沉默缺陷
根因：line_movement_signal 只比線移動，「線不動就判 flat」、完全沒看賠率
後果：亞洲盤線常黏住、移動在賠率（例：大小線 2.5 不動但賠率 0.70/1.05→0.91/0.80＝重大 sharp 訊號）會被漏成 flat
抓出：總司令以「線 2.5 不動但賠率大幅移動」具體例子點出，要求線+賠率雙軌
教訓：訊號邏輯要涵蓋「線 + 賠率」雙維，別只看線。最後升級成完整「盤口軌跡分類」(§5.6)——
     線不動改看 de-vig 公允機率位移、並濾掉兩邊一起調水位的假動作；舊 line-only bug 在新設計下不存在
```

---

## 九、目前狀態

- **最新版本**：v2.0-traj（2026-06-05，schema v2：八錨點 + 盤口軌跡分類 + selector 改 trajectory + 雙 book）
- **核心架構**：OddsPapi v4 主源；`historical-odds` 賽前即時走勢 → **八錨點 + 軌跡分類(§5.6)** → 選注(de-vig vs 1xBet + trajectory 訊號) → settlement 回測(含 by_trajectory)；CROWN 雙記 Pinnacle + singbet。
- **Phase 1A 已完成**：封存 API-Football 舊模組；config/oddspapi_client/odds_parser/storage/main/yml（每小時 8s 節流、placeholder 篩選）。
- **Phase 2 已完成**：`backtest.py` `/v4/settlements` 賽果回填 + CLV 自算 + 命中率/ROI/CLV 彙總 + by_trajectory；真實 MLS 完賽場驗證。
- **軌跡分類已完成**（schema v2）：六錨點→**八錨點**(+t72h/+t30m，決策6/回測2/role)；`trajectory.py`(八錨點+segment 四維+summary 中性 shape+中文 tag，CROWN 雙記)；`movement.py` 重寫雙 book schema v2；`selector` line_movement_signal→`trajectory_signal`(線+de-vig 機率位移，抓「線黏住賠率動」、濾水位假動作)；`backtest` 加 by_trajectory。MLS 真實場驗證：水位假動作正確判 flat、線動 confirm/reverse 正確。CI 每小時自動遷移 v1→v2。
- **下一步**：`analyzer.py`（Gemini GEM 開盤手人設，讀軌跡描述+原始數據推論意圖、標 🤖、字數 50/100/150、`GEMINI_API_KEY` 從 env 讀）→ Discord 推播 → GH Pages（後置）。shape 第一版待小組賽真實資料對照看盤迭代。
- **待總司令動作**：①repo Secrets 設 `ODDSPAPI_API_KEY`；②（建議）寄信 OddsPapi 確認 historical 不計額度。
- **暫停中**：titan007 spike（2022 回測，OddsPapi 歷史僅 3–6 個月拿不到）、上半場盤口（未來擴充）。

---

## 十、絕對不動清單（除非規格書明文解禁）

- `config.py` 金鑰讀取邏輯
- `storage.py` 寫入格式（**prod 上線後**即契約；目前 prod 未上線，schema 仍可改）
- 已上線的走勢/錨點推導邏輯
- `.env`（機密）

---

**本檔版本**：v2.0-traj｜格式來源：總司令通用範本 v1.0｜建立 2026-06-02｜八錨點軌跡分類回填 2026-06-05
