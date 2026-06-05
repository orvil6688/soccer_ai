# web_builder + GitHub Pages 提案

> 狀態：**設計提案，待 8 點審 + 總司令過目核准才寫程式**。
> 定位：把 `data/` 已存的推薦/走勢/回測轉**靜態網頁**，補 Discord summary 看不到的完整明細。
> **純讀 + 產 HTML，不碰 selector/analyzer/storage/movement/backtest/trajectory 邏輯。**
> 關聯：[notifier_proposal.md](./notifier_proposal.md)、[select_pipeline_proposal.md](./select_pipeline_proposal.md)

---

## 0. 為何要（與 Discord 分工）
- Discord＝**即時精簡**（推薦摘要 + 🤖 三欄）。
- 網頁＝**完整明細**：每場**八錨點**（決策6 `t72h/24h/12h/6h/1h/30m` + 回測2 `initial/closing`）讓分+大小球**逐點線/賠率 + 走勢圖**，+ 回測戰報（命中率/ROI/CLV/by_trajectory）。
- ⚠️ 用詞校正：總司令說「6 錨點」，現行系統是**八錨點**；網頁會列**全八點**（標決策/回測 role），決策 6 點為主視覺、initial/closing 標註輔助。請確認。

## 1. 靜態檔產出流程
```
web_builder.build(out_dir):
  讀 config.data_dir()/recommendations/*.json   （推薦 + ai{} + 回測回填欄）
  讀 config.data_dir()/movements/*.json          （八錨點 trajectory：anchors/segments/summary）
  → 生：
     index.html         推薦列表（依日期/kickoff，含 pick/單位/edge/🤖摘要/結算結果）
     fixtures/{fixtureId}.html  單場明細（雙 book × 讓分+大小球：八錨點逐點線/賠率表 + 走勢圖 + segment/summary + 完整 ai{} + 結算/CLV）
     backtest.html      回測戰報（命中率/單位/ROI/平均CLV/擊敗收盤率 + by_trajectory 各 shape 過盤率）
```
- **走勢圖**：提案用 **web_builder 產生的內嵌 SVG**（線值 + 賠率隨八錨點/時間），**自包含、無外部 CDN 依賴**（GH Pages 純靜態、離線可看、不依賴第三方）。（替代：Chart.js CDN，較花俏但有外部依賴——不建議。）
- 模板：標準函式庫 `string.Template`/手組 HTML（**不引第三方模板套件**，避免相依膨脹）；shape/signal 沿用 notifier 的英譯中對照（顯示層，內部 key 不動）。

## 2. GH Pages 部署方式
- 用 **GitHub Actions Pages 官方流程**（`actions/upload-pages-artifact` + `actions/deploy-pages`），**不需 gh-pages 分支**。
- ⚠️ 網站輸出目錄**不可用 `/docs`**（已放提案 md）；輸出到專用 `site/`（build 時生成、git 忽略；CI 直接打包 artifact 部署，不 commit 進 repo）。
- 新增 `.github/workflows/gh_pages.yml`：
  - 觸發：`workflow_run`（main_pipeline 完成後）+ `workflow_dispatch`（手動）。→ 每次資料更新後自動重建部署。
  - 步驟：checkout（含最新 committed `data/prod/`）→ `pip install`（僅標準庫，可能零額外依賴）→ `python -m soccer_ai.web_builder`（讀 data/prod 生 site/）→ upload-pages-artifact(site/) → deploy-pages。
  - `permissions: pages: write, id-token: write`。

## 3. 資料更新時機
- 推薦每小時變（select）、回測 D+1 填賽果 → **網頁跟著 main_pipeline 走**：`gh_pages.yml` 由 `workflow_run`（main_pipeline 成功後）觸發重建，網頁總是反映最新 committed 資料。
- 即：**每小時** movement/select commit 後 → 自動重建；D+1 backtest commit 後 → 自動重建回測戰報。不需獨立排程。

## 4. 測試模式行為
- `web_builder.build` 讀 `config.data_dir()`（TEST→`data/test`、prod→`data/prod`）。
- **本機預覽**：`--test` 從 data/test 生 site/ 本地開（標 🧪），不部署。
- **CI Pages 部署一律用 prod 資料**（TEST_MODE off）；測試模式**不觸發 Pages 部署**（Pages 是正式公開站）。

## 5. 不碰哪些（界線）
- **不碰** selector/analyzer/storage/movement/backtest/trajectory 任何邏輯；web_builder **只讀 `data/` + 產 HTML**。
- 不改推薦/走勢 schema（純消費）。
- shape/signal 英譯中沿用既有對照（顯示層）。

---

## 8 點自審對照
1. 環境變數：無新增（純讀檔）；GH Pages 用 Actions 權限 ✅
2. 鍵值：讀既有 fixtureId/推薦複合鍵，無新鍵 ✅
3. 字數/截斷：網頁不截（明細全展）；ai 三欄已截 ✅
4. 測試模式：data/test 本地預覽標🧪、不部署；CI 用 prod ✅
5. 失敗分流：單場 HTML 生成失敗→log 跳過該場、不中斷整站 build ✅
6. 禁止觸碰：只讀 data/+產 HTML，不碰任何分析邏輯；輸出避開 /docs ✅
7. 閾值：無 ✅
8. 行尾：`web_builder.py`=LF、`gh_pages.yml` 標準 ✅

---

## 待確認（請總司令/小c 裁）
1. 走勢圖用**內嵌 SVG（自包含無 CDN）** vs Chart.js CDN？（提案：SVG 自包含）
2. 「6 錨點」→ 網頁列**全八錨點**（決策6+回測2，標 role）—— 認可？
3. 部署觸發：`workflow_run`（main_pipeline 後自動重建）—— 認可？還是獨立排程/僅手動？
4. 是否**先做唯讀本機預覽**（生 site/ 本地開）給總司令看版面，確認後再加 gh_pages.yml 部署？（建議：先本機版面、再上線）
