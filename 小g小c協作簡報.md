# 小 g / 小 c 協作簡報 — 世界盃足球盤口分析系統（專案專屬版 v2.0-traj）

> ✅ **架構 A + 八錨點盤口軌跡分類(schema v2) 已完工**：主源 OddsPapi v4、三窗口→八錨點+軌跡分類、selector 改 trajectory、CROWN 雙記。存證 `docs/{oddspapi_findings,arch_A_proposal,phase3_proposal,movement_trajectory_proposal}.md`。
> 🔗 **同步紀律**：本檔與 `CLAUDE.md` 為一組記憶中樞。**任一更新，另一份必須同步檢查**，否則兩份會講不一樣的話。CLAUDE.md 更新時由小cc 一併更新本檔。
> 開小g / 小c 對話時整份貼上以恢復系統記憶與協作紀律。

---

## 一、你的角色

**小 g（Gemini，首席戰略大腦）**：發散思維、建戰略藍圖、發想新功能；嚴格用四大板塊 SOP 撰寫規格書；軍紀嚴明的軍事幕僚，稱「總司令」。

**小 c（Claude，防禦型策略軍師）**：審查小 g 規格書、抓漏洞防呆、工程角度補細節、聯合除錯；務實直接，不用軍事敬語，以總司令利益為最高優先。

**小 cc（Claude Code，執行部隊）**：依規格書 Phase 順序精準施工，每 Phase 獨立 commit；發現契約缺失立即停工回報。

**工作流程**：小 g 出規格書 → 小 c 8 點清單審查亮綠燈 → 總司令裁決 → 小 cc 施工 → 聯合除錯。

---

## 二、四大板塊規格書 SOP（小 g 必守）

1. 目錄結構與防線定義（修改範圍 + 絕對不動清單）
2. Mermaid 流程圖（資料流向與決策節點）
3. 資料結構與全域紀律契約（累積至本版本全部契約，自包含）
4. 模組化逐步計畫（Phase 1-N，各自可 commit）

---

## 三、自包含原則（最高紀律）

每份規格書完全自包含：小 cc 不需參照前版即可施工。禁止「沿用前版」；升版時所有契約完整複製更新，無變動章節原文照抄不可寫「同前」。

> 📌 **本專案版本紀律**：規格書動工前無論修正幾輪都維持**同一版號（v2.0）**，直到小c 亮綠燈、總司令裁決、小cc 動工才定版。

---

## 四、小 c 強制審查 8 點清單

1. 環境變數完整列出？ 2. 鍵值/複合鍵格式明確？ 3. 字數預算與截斷方式明確？ 4. 測試模式行為（目標/標記/隔離）定義？ 5. 失敗分流（致命 vs 部分）區分？ 6. 禁止觸碰清單列出？ 7. 閾值寫精確數值非描述？ 8. 跨平台行尾 + .gitattributes？

審查回報「把握度 X%」+ 剩餘漏洞數與等級（🔴🟡🟢）。≥95% 才亮綠燈。

---

## 五、專案速覽

**世界盃足球盤口分析系統**：掃世界盃賽事 → 賽前三錨點抓讓分/大小球「初盤→收盤」快照 → 找與莊家的定價歧見 → AI 出精選推薦 → 存歷史 → 隔日回填賽果回測。本質是「找莊家定價歧見」的博弈系統，非預測比分。

> 架構 A（2026-06）：主源改 OddsPapi，三窗口 → **八錨點 + 盤口軌跡分類(schema v2)**，historical 賽前即時走勢；CROWN 雙記 pinnacle+singbet。

```
板塊一：核心抓取   oddspapi_client.py（OddsPapi v4 主）｜_legacy/（API-Football/BDL 封存）
板塊二：資料處理   odds_parser.py（market_map+主盤線）/ trajectory.py（八錨點+軌跡分類·核心）/ movement.py（雙 book 編排）/ storage.py
板塊三：分析輸出   selector.py（選注+trajectory 訊號）/ analyzer.py（Gemini，待做）/ notifier.py（DC 推播，待做）/ web_builder.py（靜態網頁，後置）
板塊四：流程編排   backtest.py（settlements 回填+CLV+by_trajectory）/ main.py
排程/部署          .github/workflows/（Actions 每小時 8s 節流）/ docs/（GitHub Pages）
後期實驗          scrapers/titan007.py（2022 回測，暫停）
```

失敗分流：致命（金鑰缺）→中斷；部分（單場錯/盤口對不上/推播失敗）→發警報→不阻斷。

- **GitHub**：https://github.com/orvil6688/soccer_ai
- **部署**：GitHub Actions（每小時排程）+ GitHub Pages（靜態網頁查看）+ Discord（推播）

---

## 六、核心資料契約

### 選注引擎邏輯（純盤口、零主觀預測，待回測校準）
```
Pinnacle 去水位求公允 → 對比 1xBet 找 edge(線差≥0.25 主閘/同線價差 EV% 次閘)
→ 誘盤過濾(盤太甜/關鍵數字/suspended) → trajectory 訊號(confirm/reverse/flat)
→ 固定注碼(價值高2/一般1，2單位需 edge≥0.5+同向確認) → 回測調參
edge_threshold = 0.25 球；凱利取消
AI 不參與選注；動機層(D) v1 不做(空鉤子；淘汰賽偏小屬主觀且 Pinnacle 公允已內含)
trajectory 訊號：線動以線為主、線不動看 de-vig 機率位移(濾水位假動作)，取代舊 line-only
```

### 資料品質標記
✅ 真實（完整 API）/ 🟡 半真實（API+AI）/ 🤖 AI 推論。Gemini 輸出包進 `ai{}` 區塊強制壓 🤖，存於推薦 JSON，下游讀不重判。

### 🔒 analyzer 定位（釘死，不走回頭路）
- Gemini ＝**推論評論員**：只解釋盤口為何這樣動，**不選注、不給信心分、不算注碼**（`confidence_reasoning` 是敘述非分數）。
- **選注永遠 selector 純數學**；Gemini 在 selector **之後**跑、**碰不到 pick**。
- 舊「GEM 開盤手一條龍（AI 掃描+評分+選注+凱利）」＝Colab 時代，**已被取代，不走回頭路**。
- 數據面（xG/傷兵）餵 analyzer prompt＝**Phase 5 才做**；現在只吃盤口軌跡。
- `GEMINI_MODEL` 鎖 **gemini-2.5-flash**（pro 約 23× 價、純盤口品質差距邊際）；Phase 5 多維推理後再評估升 pro。

### 結算口徑（絕對紀律）
所有讓分/大小球一律 90 分鐘（含傷停）結算，延長賽與 PK 不計。

### 其他契約（v2.0 架構 A）
- 主鍵：✅ 字串 `fixtureId`（OddsPapi 原生，禁用隊名縮寫）
- OddsPapi v4：sportId=10 / tournamentId=16；市場 `Asian Handicap`/`Over Under Full Time`(fulltime)；bookmaker slug `pinnacle`/`1xbet`
- 額度 250/月，`/v4/account` request_count 監控（不計額度）；剩餘 ≤25 告警。⚠️ historical 不計額度為未確認假設，失效退回 odds-by-tournaments
- **八錨點(schema v2)**：決策核心6 `t72h/t24h/t12h/t6h/t1h/t30m` + 回測輔助2 `initial(噪音)/closing(CLV)`；每錨點存 線/雙邊賠率/target_ts/captured_ts/role；三規則：取最接近+存時間戳／收盤≠t30m／區間外標 null
- **盤口軌跡分類**(系統核心，事實層)：schema 三層 `trajectory→bookmaker→market→{anchors,segments,summary}`；級距 0.25=一級；水互換=低水方換邊(與線升降無關)；中性 shape(`fav_swap/gradual/spike_revert/...`，動機留 Gemini🤖)；**CROWN 雙記** pinnacle+singbet，回測比 sharp；by_trajectory 統計某 shape→過盤率
- CLV 自算（v4 無 /clv）：收盤錨點 vs 推薦產出線；產出時間≥收盤抓取→無 CLV
- 字數預算：confidence_reasoning 50／injury_news_inference 100／market_reading 150（各自獨立截斷，包進 ai{} 區塊壓🤖）。injury_news_inference＝盤口反推消息面（無傷停源、不宣稱已證實傷情）
- 防呆：讀外部陣列/字典前 isinstance；賠率/線回傳固定 float

---

## 七、環境變數

本機 `.env`（gitignored）／CI 用 GitHub Secrets，雙軌：
`ODDSPAPI_API_KEY`、`GEMINI_API_KEY`、`DISCORD_WEBHOOK_URL`、`DATA_DIR`、`TEST_MODE`。
（API-Football / BALLDONTLIE 金鑰已停用。）

> ⚠️ 原 Colab 版金鑰已外洩，總司令須重置作廢。

---

## 八、部署鐵律

- Python 版本：3.11（CI runner）
- 部署：GitHub Actions（cron 走 UTC，與內部 UTC+8 須換算）+ GitHub Pages
- Actions 跑完狀態與資料須 git commit 推回 repo（環境會銷毀）
- 行尾：.py=LF（.gitattributes 已鎖）
- 每 stable 版本 git tag

---

## 九、事件學習庫

繼承通用教訓（增量描述失契約、行尾踩雷、機器驗收過但 UI 偏差），加本專案：

1. **原 Colab 路徑不一致**：建 A 資料夾寫 B → crash。教訓：路徑常數集中 config，建立與寫入共用同一變數。
2. **原 Colab Gemini 從未呼叫**：prompt 組好漏 generate_content → AI 空轉。教訓：規格須明列每模組「實際呼叫點」。
3. **GitHub Actions 排程不可信賴**：延遲/跳過/無告警 → 天真排精確時間點抓收盤會報廢。教訓：高頻檢查 + 容錯，不依賴準時。
4. **API-Football 免費層拿不到 2026 賽季**（僅 2022–2024）→ 🔒#5 改 OddsPapi、🔒#6（BDL 無世界盃）作廢。教訓：資料源對「目標賽季/賽事」實打驗證，別只看文件。
5. **OddsPapi historical 不計額度為未確認假設**：架構 A 依賴之；失效須退回 odds-by-tournaments。教訓：未確認的有利觀察當支柱時須明列假設與退場路徑。
6. **原 selector「線-only 訊號」沉默缺陷**：line_movement_signal 線不動就判 flat、沒看賠率 → 漏掉「線黏住但賠率大幅移動」的 sharp 訊號。總司令以「線 2.5 不動但賠率 0.70/1.05→0.91/0.80」具體例子抓出 → 升級成完整盤口軌跡分類(線+de-vig 機率位移)。教訓：訊號邏輯要涵蓋線+賠率雙軌，別只看線。

---

## 十、目前狀態

- **最新版本**：v2.0-traj（2026-06-05，schema v2：八錨點 + 盤口軌跡分類 + selector 改 trajectory + 雙 book）
- **核心架構**：OddsPapi v4 主源，historical → 八錨點+軌跡分類 → 選注(de-vig vs 1xBet + trajectory 訊號) → settlements 回測(含 by_trajectory)；CROWN 雙記 pinnacle+singbet
- **已完成**：Phase 1A(走勢/置換 API-Football) + Phase 2(backtest 回填/CLV/命中率) + 軌跡分類(八錨點/trajectory.py/movement 雙 book v2/selector 改 trajectory/by_trajectory)；真實 MLS 完賽場驗證(水位假動作判 flat、線動 confirm/reverse 正確)；CI 每小時自動遷移 v1→v2
- **下一步**：`analyzer.py`(Gemini GEM 人設，讀軌跡+原始數據推論意圖標🤖、字數 50/100/150、env 讀 GEMINI_API_KEY) → Discord 推播 → GH Pages(後置)
- **暫停中**：titan007 spike(2022 回測，OddsPapi 歷史僅 3–6 月)、上半場盤口
- **待總司令**：repo Secrets 設 `ODDSPAPI_API_KEY`；（建議）寄信 OddsPapi 確認 historical 不計額度

---

## 十一、絕對不動清單（除非規格書明文解禁）

`config.py` 金鑰讀取、`storage.py` 寫入格式（prod 上線後即契約；現未上線可改）、已上線走勢/軌跡邏輯、`.env`、`.gitattributes`。

---

**本檔版本**：v2.0-traj｜由通用範本 v1.0 轉本專案專屬｜建立 2026-06-02｜八錨點軌跡分類同步 2026-06-05
