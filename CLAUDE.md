# CLAUDE.md — 世界盃足球盤口分析系統 · AI 協作記憶中樞

> ✅ **本檔為 v2.0-titan（架構 A：OddsPapi 主源 + 八錨點軌跡 + 選注/AI/推播/回測閉環 + 公開網頁，Phase 3 全完成；titan007 全量 64 場 2022 離線校準素材完成、0 跳過/0 旗標）**：第五節契約自包含、
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
板塊一：核心抓取    oddspapi_client.py（OddsPapi v4 主）｜_legacy/（API-Football/BDL 封存）
板塊二：資料處理    odds_parser.py（market_map+主盤線）/ trajectory.py（八錨點軌跡分類·核心）/ movement.py（雙book編排）/ storage.py
板塊三：分析輸出    selector.py（選注·純數學）/ analyzer.py（Gemini🤖）/ notifier.py（Discord）/ web_builder.py（靜態網頁）
板塊四：流程編排    backtest.py（settlements 回填+CLV+derive_score）/ main.py（--mode movement|select|backtest）
排程/部署          .github/workflows/main_pipeline.yml（每小時）/ gh_pages.yml（Pages 部署）
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
- **結算**：`/v4/settlements?fixtureId=` 按 market/outcome 取 result；嚴格 90 分鐘（fulltime）。result 列舉（實測）：`WIN/LOSE/HALFWIN/HALFLOSS/PUSH/UNDECIDED`。
- **比分反推**：OddsPapi **無直接比分**（REST settlements/fixtures 皆無、比分僅 WS `scores` 而免費 `websocket_access:0`）。→ **`backtest.derive_score` 由 O/U+讓分多盤口階梯反推確切比分**（O/U 邊界定總進球、讓分邊界定淨差 → 主=(總+差)/2），零新資料源；存 `rec["score"]`，Discord/網頁顯真比分。已驗 MLS 多場（1:0/2:0/2:1）。
- **額度**：免費層 250/月，以 `/v4/account` 的 `request_count` 監控（不計額度）；剩餘 ≤25 告警。
- ⚠️ **`/clv` v4 不存在**（已實打），CLV 自算（見 5.5）。

### 5.2 選注引擎參數
- **Edge 門檻** `edge_threshold = 0.25` 球：Pinnacle 去水位求公允 vs 1xBet 偏差（線差為主閘、同線價差 EV% 為次閘）。AI 不參與選注。
- **訊號改 trajectory**（見 5.6）：`selector.line_movement_signal`（線-only）已**移除**，改 `trajectory_signal` 讀軌跡 summary —— 線動以線方向為主、**線不動看 de-vig 公允機率位移**（能抓「線黏住但賠率動」、濾掉兩邊一起調水位的假動作）→ confirm/reverse/flat。
- 反向線移動只記「加權訊號」供回測，**不**單獨觸發 2 單位。動機層(D) v1 不做（空鉤子）。
- 🔒 **釐清（選注依據唯一性）**：**選注唯一依據＝edge（找定價歧見）**；八錨點軌跡/trajectory 訊號＝**加權確認 + Gemini 解讀材料**，**不單獨選注**；xG/實際數據面＝**Phase 5 才接**（現只有盤口）。
- **edge 對手盤＝1xBet**（公允錨＝Pinnacle）：總司令實際下注皇冠/平博；待 2026 小組賽真實資料看「皇冠 vs 1xBet 實際出 edge」情況再評估是否改對手盤，**暫不動 selector**。
- **pick.odds 取 1xBet（下注軟盤）**、movement 錨點取 pinnacle（sharp 參考）→ 兩者**不同莊故賠率不一致＝設計非 bug**（CLV 現用 pinnacle 收盤＝跨莊，同上待評估）。

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
- 函式實際呼叫點：
  - `--mode movement` → `movement.scan()` →（逐場、逐 book）`process_fixture()` → `oddspapi_client.get_historical_odds()` → `trajectory.build()` → `storage.save_fixture_movement()`。
  - `--mode select` → `selector.select()` →（逐 pick）載軌跡記錄 + `storage.find_recommendation`(prior) → 蓋 `produced_at_local`(首見凍) → `analyzer.analyze(pick,record,prior_ai)` → `storage.append_recommendation`(date=`config.local_date(kickoff_utc)`) → 收集 `notifier.should_notify` 為真者 → 整輪 `notifier.notify_batch()`（Discord 推播）。逐 pick 隔離、部分失敗不阻斷。
  - `--mode backtest` → `backtest.run_backfill()`。
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
- **歷史推薦檔**：`data/{prod|test}/recommendations/{YYYY-MM-DD}.json`，**檔名日期＝`config.local_date(kickoff_utc)`（kickoff 的 UTC+8 日曆日，存撈共用，杜絕跨日漏撈）**；list，以 **`(fixtureId, market, side)` 複合鍵** upsert（一場可同時讓分+大小球兩注、不互蓋）。
  推薦 schema（selector 數學產出 + analyzer 加 `ai{}`、backtest 消費）：
  `{fixtureId, market, side, line, odds, stake_units, kickoff_utc, kickoff_local, home, away, edge_*, signals{signal,shape,tag,...}, trajectory{book:{shape,tag,...}}, produced_at_local, ai{}}`；backtest 回填 `result/pnl_units/settled/clv/score{home,away,total,margin}`。
  - `odds`＝1xBet 下注價（非 pinnacle 錨點），故與 movement 錨點賠率不一致屬正常（不同莊）。
  - **兩個 produced_at 各管各**：`produced_at_local`（頂層，CLV 基準，**首見凍結**）／`ai.produced_at`（在 `ai{}` 內，標推論對應哪個軌跡快照，**隨 summary_hash 變更新**）。`ai{}` 格式見 §5.4 / docs/analyzer_proposal.md。
  - **notifier 去重欄**（推播後回寫，list[dict] 格式不變、僅加欄）：`notified_hash`(=sha1(fixtureId,market,side,line,odds,stake_units))、`notified_at`、`notified_ai_available`。重推＝下注關鍵變 OR ai.available false→true。
- **Discord 推播（notifier #4）**：四把 webhook env（📋推薦單 `DISCORD_WEBHOOK_URL` / 🧪測試 `DISCORD_TEST_WEBHOOK_URL` / 📊回測 `DISCORD_BACKTEST_WEBHOOK_URL` / ⚠️告警 `DISCORD_ALERT_WEBHOOK_URL`，值僅總司令自填）；#4 已實作前兩把推播（📊/⚠️ env 在位、推播後續）。TEST_MODE→test 頻道或略過、壓 🧪；整輪彙總一則多 embed（>10 分多則）；shape/signal 顯示層英譯中（內部 key 不動）；失敗逐筆跳過、告警記一次/輪。
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

### 5.7 靜態網頁 + GitHub Pages（web_builder + gh_pages）
- `web_builder.py`：**純讀 `data/` 產自包含 HTML**（無 CDN、內嵌 SVG）：`index`（推薦列表+賽果欄顯真比分）/`fixtures/{id}`（單場八錨點逐點線+賠率+SVG 走勢圖，雙 book×讓分/大小球）/`backtest`（命中率/ROI/CLV/by_trajectory）。公開頁衛生：**不讀 .env、不輸出 webhook/key/內部 hash、白名單欄位、shape 顯示層英譯中、缺/壞場跳過**。
- `gh_pages.yml`：`workflow_run`（main_pipeline 完成且成功後）+ `workflow_dispatch` 觸發 → **`checkout ref=main`（取 main_pipeline 剛 commit 的 data/prod、不慢一輪，鐵律3）** → `TEST_MODE=false` 讀 data/prod → web_builder 產 `site/` → `upload-pages-artifact@v5`+`deploy-pages@v5`（全 **node24**：configure-pages@v6/deploy-pages@v5/checkout@v6/setup-python@v6）。`site/` gitignored、CI 打包不進 repo。
- **公開網址**：`https://orvil6688.github.io/soccer_ai/`（Settings→Pages→Source=GitHub Actions 啟用）。
- **顯示層調整（D/E/F）**：shape/signal 英譯中（fav_swap=賠率反轉…，內部 key 不動）；tag 級→盤/平盤（net 計算不動）；賠率顯示 `{:.2f}`（儲存/回測全精度不動）。

---

## 六、Phase 計畫（對應 🔒 #11 施工序）

> 鐵律：6/11 前 Phase 1+2 必須能跑，否則回測永遠生不出勝率。

> 註：架構 A 後實際路徑＝OddsPapi（見 §5）；下列 Phase 名沿用，內容以架構 A 為準。
- **✅ Phase 1（完成）**：config + oddspapi_client + movement/trajectory（八錨點軌跡）+ storage（架構 A 取代原三錨點）。
- **✅ Phase 2（完成）**：backtest `/v4/settlements` 賽果回填 + CLV 自算 + 命中率/by_trajectory + derive_score 比分反推。
- **✅ Phase 3（完成）**：selector（純數學選注）+ analyzer（Gemini🤖 推論評論員）+ notifier（Discord）+ web_builder/gh_pages（公開網頁）。閉環+公開網頁全線。
- **Phase 4**：交叉驗證/edge 對手盤調校（待小組賽真實資料；原 bdl_client 作廢→改 Pinnacle vs 1xBet/singbet 比較）。
- **Phase 5（後期）**：xG/實際數據面接入 analyzer、scrapers/titan007 實驗、上半場盤口。

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
```
事件：OddsPapi 無直接比分、推薦 odds 對不上錨點（疑似 bug，查證後皆非 bug）
查證：①settlement/fixtures REST 無 score、比分僅 WS 而免費 websocket_access=0（實打證實）
     →以 O/U+讓分多盤口階梯反推確切比分(derive_score)，零新資料源，MLS 多場驗對(1:0/2:0/2:1)
     ②pick.odds 取 1xBet(下注軟盤)、movement 錨點取 pinnacle(sharp 參考)，不同莊故不一致＝設計
     （demo 的 1.95 是手寫 mock 加劇誤會）；edge 仍餵真值給 Gemini、未掰
教訓：報 bug 前先實打/讀碼分清「mock 殘留 vs 真錯 vs 設計」；缺的能力（比分）常可由既有富資料反推
```
```
事件：titan007 端點 OverDown.aspx 是空錯頁、overunder.aspx 才有料
查證：抓 changeDetail/OverDown.aspx 回 875b/912b 空殼（無 odds2 表），憑「OverDown=大小」拼的端點是錯的；
     實打試 overunder.aspx 才回 60KB 含完整大小球時間序列；讓分正解＝handicap.aspx；companyID 47=平博/3=皇冠。
教訓：再次驗證憑記憶/語意拼第三方端點會錯——端點要實打試出來、用回應大小/結構驗證有沒有真資料，別只看名字像
```
```
事件：titan007 `_parse_ts` 單位數日期 bug（全量採集偽裝成「無盤口」）
根因：時間戳正則寫死 `(\d{2})-(\d{2})` 要求 2 位數，但 titan007 日期不補零（如 `12-9 22:54`）
後果：**所有日 1-9 的盤口列被整列靜默丟棄** → 早段淘汰賽(12/3-9)、末輪組賽(12/1-2) 整批變空/稀疏，
     全量首跑誤報 7 跳過「四組盤口全空」+11 旗標；spike 因 id=2185072 在 11-20（兩位數日）僥倖沒踩到
抓出：手動低速重抓「跳過」場證實有盤口 → 再 debug `_series` 發現 raw rows 有、`_parse_ts` 回 None
教訓：報「跳過/缺資料」前先查解析 bug，別當真缺；跳過聚集若按「日期/格式」分群而非隨機，多半是解析雷不是來源缺
```
```
事件：titan007 比分欄=90 分鐘賽果（ET/PK 另寫，避免結算抓錯分）
查證：c75.js（賽程 feed）每場 `[mid,...,'90分比分'(index6),'半場比分'(index7),...]`；ET/PK 在備註不在同欄
     決賽 2302891 比分欄=2-2（備註 120分3-3 / PK4-2）、克巴 QF 2302885=0-0（ET 1-1）→ 抓 index6 不誤抓 ET/PK
     2022 無「進 ET 但沒 PK」場（5 場 ET 全進 PK），故改驗 90分≠ET 的場（更強）
教訓：嚴格 90 分鐘結算口徑，score 必須取「比分欄/腰盤」而非全場終分；ET/PK 場用「90分≠ET」的場驗才證得了沒誤抓
```
```
事件：OddsPapi 免費層 1xbet 覆蓋不全（查證為覆蓋限制、非 bug）
查證（2026 WC 賽前 5 天實打）：揭幕戰 MEX-RSA 1xbet 有盤；但 KOR-CZE 經 historical-odds + odds-by-tournaments
     + 所有 slug 變體（1xbet/1xBet/onexbet…）全回 None，而 pinnacle/singbet 有盤；`/bookmakers` 權威清單
     確認正解 slug＝`1xbet`（解析/slug 都對）。1xBet 官網有盤 ≠ OddsPapi 免費層 feed 有抓到。
事實：1xbet 即時覆蓋約 **43/104**（pinnacle 72、singbet 70），會隨臨近開賽增加但**不保證補滿**；
     **付費層救不了**（OddsPapi 免費/付費的莊家清單相同，差別在額度/即時推送非覆蓋）。
影響：edge＝pinnacle vs 1xbet，沒 1xbet 的 ~61 場算不出 edge → 不出下注 pick（但 movement/八錨點靠 pinnacle/singbet、照常有走勢）。
教訓：報「抓不到某 book」前先讀回傳+試 slug 變體+查 /bookmakers 權威清單分清「覆蓋缺口 vs slug/解析 bug」；覆蓋是資料源天花板、改 code 救不了
```

---

## 九、目前狀態

- **最新版本**：v2.0-titan（2026-06-07，**Phase 3 全完成**：閉環 + 公開網頁全線上線；**titan007 全量 64 場 2022 離線校準素材完成**，0 跳過/0 旗標、commit 5524c46）
- **公開網址**：`https://orvil6688.github.io/soccer_ai/`（GH Pages，gh_pages.yml 部署）。
- **核心架構**：OddsPapi v4 主源；`historical-odds` 賽前即時走勢 → **八錨點 + 軌跡分類(§5.6)** → `selector` 選注(de-vig vs 1xBet + trajectory 訊號) → `analyzer` 🤖 推論(Gemini 2.5-flash) → 存推薦 → `backtest` settlement 回測(含 by_trajectory)；CROWN 雙記 Pinnacle + singbet。
- **Phase 1A 已完成**：封存 API-Football 舊模組；config/oddspapi_client/odds_parser/storage/main/yml（每小時 8s 節流、placeholder 篩選）。
- **Phase 2 已完成**：`backtest.py` `/v4/settlements` 賽果回填 + CLV 自算 + 命中率/ROI/CLV 彙總 + by_trajectory；真實 MLS 完賽場驗證。
- **軌跡分類已完成**（schema v2）：六錨點→**八錨點**(+t72h/+t30m，決策6/回測2/role)；`trajectory.py`(八錨點+segment 四維+summary 中性 shape+中文 tag，CROWN 雙記)；`movement.py` 重寫雙 book schema v2；`selector` line_movement_signal→`trajectory_signal`(線+de-vig 機率位移，抓「線黏住賠率動」、濾水位假動作)；`backtest` 加 by_trajectory。MLS 真實場驗證：水位假動作正確判 flat、線動 confirm/reverse 正確。CI 每小時自動遷移 v1→v2。
- **analyzer #3 已完成**：`analyzer.py`（Gemini 2.5-flash 開盤手推論評論員，**只解釋不選注**；三欄獨立截斷、`ai{}` 區塊🤖、summary_hash 快取、insufficient 前置攔截、TEST_MODE mock、失敗分流）。GEMINI_MODEL 鎖 2.5-flash（見 §5.4）。真打驗證敘述品質達標。
- **#5 編排已完成**：`--mode select`（selector→analyzer→存推薦→notifier）+ `config.local_date` UTC+8 歸檔 + storage `(fixtureId,market,side)` 複合鍵 + 兩個 produced_at 各管各。
- **#4 notifier 已完成**：Discord 推播（四 webhook、實作 📋推薦單+🧪測試；彙總多 embed、去重 `notified_*`、英譯中、失敗不阻斷）。🧪 真打 204 通過。
- **web_builder + gh_pages 已完成**：`web_builder.py`（純讀 data/ 產自包含 HTML：推薦列表+賽果真比分、單場八錨點+SVG 走勢圖、回測戰報）；`gh_pages.yml`（workflow_run 後 deploy-pages，全 node24，checkout ref=main 取最新 data）；**公開網頁線上**（首頁框架正常、賽前推薦空屬正常、fixtures/* 72 場走勢有料）；derive_score 比分反推已上（賽果顯 `主N:M客`）。
- **Phase 3 全完成**：selector→analyzer→notifier→web_builder 全線；閉環 + 公開網頁全到位。
- **titan007 全量 64 場完成 ✅**：OddsPapi 歷史僅 3–6 個月拿不到 2022，改用 titan007 凍結歷史補 2022 世界盃 64 場做離線回測校準。
  - scrapling 輕量裝（`requirements-titan007.txt`，不進主 requirements、不上 CI 🔒#7）；端點釘死：讓分 `changeDetail/handicap.aspx`、大小 `changeDetail/overunder.aspx`（**OverDown.aspx 是空錯頁已棄用**，見 §八），`companyID 47=平博→pinnacle / 3=皇冠→singbet`，表 id="odds2"、gb2312。
  - 賽程/比分權威源：`https://zq.titan007.com/jsData/matchResult/2022/c75.js`（賽程頁 `cn/CupMatch/2022/75.html` 的 JS feed）→ 解析 64 場 mid/隊名/開賽/**90 分鐘比分=比分欄 index 6**（ET/PK 另寫備註、不誤抓；已驗決賽 2302891=2-2、克巴 QF 2302885=0-0）。
  - `scrapers/titan007_spike.py`（單場 build_fixture/八錨點邏輯）+ `scrapers/titan007_full.py`（c75.js 解析 + 逐場 build + 3.5s 節流 + 429/5xx 退避[3,6,12] + 抓不到/覆蓋不足標記跳過彙總、不靜默丟；`--rerun mid,... --interval N` 可慢速重抓）。
  - **全量結果：64 寫出 / 0 跳過 / 0 旗標**（commit **5524c46**）。八錨點：濾 ts<kickoff 排滾球、§3.2 取最近目標時刻/區間外→null；reuse `trajectory.build_segments/build_summary`；CROWN 雙記 pinnacle+singbet。
  - 本機回測頁 `web_builder --mode titan007_local` → `site_titan007/`（by_trajectory：shape→過盤率，過盤基準=**收盤低水方**零門檻、PUSH 不計分母；逐場八錨點+SVG）。`data/titan007_2022/`(64 檔)、`site_titan007/` 皆 gitignored（第三方爬料/本機頁，不上 repo）。
  - 2022 校準素材：緩步推移 75 筆 46%、賠率單向飄 50 筆 57%、賠率反轉 47 筆 51%、混合 43 筆 41%、上下震盪 6 筆 18%、急拉回吐 4 筆 25%（純校準、不參與線上選注）。
- **下一步（Phase 3 後）尚未做清單**：上半場盤口(Phase 5)／edge 對手盤調校(待小組賽真實資料)／xG/數據面接 analyzer(Phase 5)／📊回測+⚠️告警 Discord 推播(env 在位、推播後續)／比分顯示樣式微調(可選)。
- **待總司令動作**：repo Secrets `ODDSPAPI_API_KEY`+`GEMINI_API_KEY`+四把 `DISCORD_*_WEBHOOK_URL`（已備）；GH Pages Settings→Source=GitHub Actions（已啟用）。
- **暫停/排隊中**：上半場盤口（未來擴充）、6/11 校準（小組賽開打後以 **2022 的 64 場**（已備齊）+ 真實小組賽當樣本校準 shape/門檻/edge 對手盤）。

---

## 十、絕對不動清單（除非規格書明文解禁）

- `config.py` 金鑰讀取邏輯
- `storage.py` 寫入格式（**prod 上線後**即契約；目前 prod 未上線，schema 仍可改）
- 已上線的走勢/錨點推導邏輯
- `.env`（機密）

---

**本檔版本**：v2.0-titan｜格式來源：總司令通用範本 v1.0｜建立 2026-06-02｜Phase 3 全完成(閉環+公開網頁)回填 2026-06-06｜titan007 全量 64 場完成同步 2026-06-07
