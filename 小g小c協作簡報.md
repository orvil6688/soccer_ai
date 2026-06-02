# 小 g / 小 c 協作簡報 — 世界盃足球盤口分析系統（專案專屬版 v2.0-phase1）

> ✅ **規格書 v2.0 終極定案，Phase 1 已由小cc 完工**：原「🔜 待規格書回填」項已落地（見下）。
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

```
板塊一：核心抓取   api_client.py（API-Football 主）/ bdl_client.py（BALLDONTLIE 備）
板塊二：資料處理   odds_parser.py / snapshot.py（三錨點·核心）/ storage.py
板塊三：分析輸出   selector.py（選注引擎）/ analyzer.py（Gemini）/ notifier.py（DC 推播）/ web_builder.py（靜態網頁）
板塊四：流程編排   backtest.py（賽果回填）/ main.py
排程/部署          .github/workflows/（Actions）/ docs/（GitHub Pages）
後期實驗          scrapers/titan007.py
```

失敗分流：致命（金鑰缺/額度盡）→發警報→中斷；部分（單場錯/BDL 對不上/推播失敗）→發警報→不阻斷。

- **GitHub**：🔜 待建 repo 後填
- **部署**：GitHub Actions（排程）+ GitHub Pages（靜態網頁查看）+ Discord（推播）

---

## 六、核心資料契約

### 選注引擎邏輯（參數化，待回測校準）
```
估公允盤(基本面/動機) → 比莊家盤找 edge → 誘盤過濾(反向線移動/關鍵數字/盤太甜)
→ 世界盃動機檢查(死亡之組降權/淘汰賽偏小) → 固定注碼(價值高2/一般1) → 回測調參
edge_threshold = 0.25 球（起點，待回測）
凱利：取消
```

### 資料品質標記
✅ 真實（完整 API）/ 🟡 半真實（API+AI）/ 🤖 AI 推論。Gemini 輸出強制壓 🤖，存於推薦 JSON，由 analyzer 計算，下游讀不重判。

### 結算口徑（絕對紀律）
所有讓分/大小球一律 90 分鐘（含傷停）結算，延長賽與 PK 不計。

### 其他契約（v2.0 定案）
- 主鍵：✅ 數字 `fixture_id`（API-Football 原生，禁用隊名縮寫）
- League ID=1 / Season=2026；Bet ID 讓分=4 大小球=5；Bookmaker 優先序 [4,8,41]
- Rate Limit 100/日（達 95 告警中止）；生存法則：剩餘 ≤15 僅抓收盤
- 三窗口：初盤(首見即抓)／中段 T-13h~11h／收盤 T-90m~45m
- 字數預算：confidence_reasoning 50／injury_impact 100／market_reading 150（各自獨立截斷）
- 防呆：讀 API 陣列前 isinstance；賠率欄位回傳固定 (str, float)

---

## 七、環境變數

本機 `.env`（gitignored）／CI 用 GitHub Secrets，雙軌：
`API_FOOTBALL_KEY`、`BALLDONTLIE_API_KEY`、`GEMINI_API_KEY`、`DISCORD_WEBHOOK_URL`、`DATA_DIR`、`TEST_MODE`。

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
3. **GitHub Actions 排程不可信賴**：延遲/跳過/無告警 → 天真排精確時間點抓收盤會報廢。教訓：高頻檢查 + 窗口容錯，不依賴準時。

---

## 十、目前狀態

- **最新版本**：v2.0-phase1（2026-06-02，Phase 1 完工 + 契約回填）
- **核心架構**：API-Football 主 + BALLDONTLIE 備，三窗口快照 → 選注 → 回測，Actions + Pages + DC
- **Phase 1 完成**：git init / config / api_client / odds_parser / snapshot / storage / main / main_pipeline.yml，離線煙霧測試全綠
- **下一步**：Phase 2 — backtest 賽果回填 + CLV 防呆 + 命中率
- **待總司令**：建 GitHub remote 推送、repo Secrets 設 API_FOOTBALL_KEY（舊金鑰作廢）

---

## 十一、絕對不動清單（除非規格書明文解禁）

`config.py` 金鑰讀取、`storage.py` 歷史檔寫入格式、已上線快照排程錨點邏輯、`.env`、`.gitattributes`。

---

**本檔版本**：v2.0-phase1｜由通用範本 v1.0 轉本專案專屬｜建立 2026-06-02｜Phase 1 完工同步
