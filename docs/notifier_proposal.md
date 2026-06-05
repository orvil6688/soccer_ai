# #4 提案 — notifier（Discord 推播帶 ai{} 的推薦）

> 狀態：**設計提案，待 8 點審 + 總司令過目核准才寫程式**。
> 關聯：[select_pipeline_proposal.md](./select_pipeline_proposal.md)、[analyzer_proposal.md](./analyzer_proposal.md)

---

## 0. 目標與界線
- 把 `--mode select` 產出、**帶 `ai{}` 的推薦**推到 Discord，給總司令看單。
- **不選注、不改推薦**：notifier 只「呈現」storage 已存的推薦；selector/analyzer 不碰。
- 推播失敗**不阻斷** pipeline（推薦已存、回測照跑）。

---

## 1. 觸發點與流程（裁示：整批彙總一則）
- `--mode select` 編排：先存完所有推薦，**整輪結束彙總成「一則訊息、內含多 embed」推一次**（某輪 1 筆＝一則一 embed）。
```
sent_recs = []
for pick in picks:
    ... 存推薦 ...
    if notifier.should_notify(rec): sent_recs.append(rec)   # 去重判定(§4)
notifier.notify_batch(sent_recs)   # 一則訊息多 embed；送出後回寫 notified_hash/notified_at
```
- Discord 單則訊息上限 **10 embeds** → 超過 10 筆自動分多則送。

## 2. 推什麼（內容 + 🤖 界線）
單筆推薦 → 一則 Discord embed：
- **標題**：`{home} vs {away}　{kickoff_local}`
- **選注（系統數學）**：`{market} {side} 線{line} @ {odds}　{stake_units}單位　edge {edge_goals}球`
- **盤口軌跡（系統客觀）**：`shape={signals.shape}　{signals.tag}　訊號={signals.signal}`（中性，無動機）
- **🤖 AI 推論**（`ai.available` 時）：三欄 `confidence_reasoning / injury_news_inference / market_reading`，整段冠 `🤖 AI 推論`；`ai.available=false` → 顯示「🤖 暫無（reason）」不顯三欄。
- **資料品質標記**：系統層 ✅ 客觀 / AI 層 🤖；明確分區，下游/總司令一眼分清「事實 vs 推論」。

## 3. 環境變數 / 頻道對應 / 測試模式
- **四把 webhook env 一次全定義在位**（config 全 `os.getenv` 讀、`.env.example` 列名值留空）。
  **小cc 絕不經手 URL 值、不印 log；總司令自填 .env + GitHub Secret + 自驗收**。
  | env 變數 | Discord 頻道 | #4 本次 |
  |---|---|---|
  | `DISCORD_WEBHOOK_URL` | 📋-推薦單（正式推薦）| **本次實作推播** |
  | `DISCORD_TEST_WEBHOOK_URL` | 🧪-測試（TEST_MODE 推這、與正式隔離）| **本次實作推播** |
  | `DISCORD_BACKTEST_WEBHOOK_URL` | 📊-回測戰報 | env 先接好、**推播留 backtest 推播後續** |
  | `DISCORD_ALERT_WEBHOOK_URL` | ⚠️-系統告警 | env 先接好、**推播留告警模組後續** |
  - 即：四把變數現在全定義好（免日後回頭補），但 #4 只實作前兩把的推播。
- **正式（TEST off）**：推 `DISCORD_WEBHOOK_URL`。缺 → log 警告一次、略過推播（非致命）。
- **測試（`is_test_mode()`）**：有 `DISCORD_TEST_WEBHOOK_URL` → 推 test 頻道；否則**略過不推**（不污染正式）。內容壓 `🧪`。

## 4. 防重複推播（裁示：下注關鍵 OR ai 由無轉有）
- `--mode select` 每小時跑、同一注重複出現 → 去重免洗版。
- **重推條件**（`should_notify`）：首次出單 **OR** 下注關鍵欄變（`line`/`odds`/`stake_units`）**OR** `ai.available` 由 **false→true**（AI 從無到有）。
  - **AI 文字措辭變（available 仍 true）→ 不重推**；ai true→false（如 503 暫失）→ **不重推**（已推過、不為失去 AI 洗頻）。
- 實作：`notify_hash = sha1(fixtureId,market,side,line,odds,stake_units)`；
  重推 = `notify_hash != rec.notified_hash`（下注關鍵變/首次）**或**（`prior.ai.available==False and 現 ai.available==True`）。
- 送出後把 `notified_hash` + `notified_at`（+ `notified_ai_available`）寫回推薦記錄。
- ⚠️ 推薦記錄多 `notified_hash`/`notified_at`/`notified_ai_available` 欄（list[dict] 格式不變、僅加欄，非 §10 契約變更）。

## 5. 失敗分流
- 具名攔截：webhook 缺/4xx/5xx/逾時/網路 → **不中斷 pipeline**（推薦已存、回測照跑）。
- **告警只記一次／輪**（跟 Gemini 503 同理）：本輪 webhook 錯誤彙總後 log 一次，**不逐筆刷**。
- 429 帶 retry_after 可輕量尊重 1 次；逾時上限短。

## 6. 模組與切分
- `config`：新增 4 把 webhook `os.getenv` 讀（值不經手）；`.env.example` 列 4 變數名值留空。
- `notifier.py`：`should_notify(rec)`（去重判定 §4）/ `_format_embed(rec)` / `_webhook_url()`（依 TEST_MODE 選 test/正式，缺則略過）/ `notify_batch(recs)`（一則多 embed、>10 分批、回寫 notified_*、告警記一次、回 sent/skipped/failed）。
- `main._run_select`：存推薦後收集 `should_notify` 為真者 → 整輪 `notify_batch` → 彙總數入 log。
- 不動 selector/analyzer/trajectory/backtest 邏輯。

## 7. 不在本塊
- web_builder / GH Pages（後置）；2 單位警報音/特殊樣式（可後續）；上半場（未來）。

---

## 8 點自審對照
1. 環境變數：`DISCORD_WEBHOOK_URL`/`DISCORD_TEST_WEBHOOK_URL` env、不硬編 ✅
2. 鍵值：去重 `notify_hash`(複合)明確 ✅
3. 字數/截斷：沿用 ai{} 已截斷三欄，notifier 不再截 ✅
4. 測試模式：test webhook 或略過、壓 🧪、不污染正式 ✅
5. 失敗分流：webhook 失敗逐筆跳過不阻斷（部分失敗）✅
6. 禁止觸碰：只讀推薦+加 notified_* 欄+送 webhook；selector/analyzer 不碰 ✅
7. 閾值：無新閾值 ✅
8. 行尾：`notifier.py`=LF ✅

---

## 裁示已定（總司令 2026-06-06）
- **去重**：line/odds/stake 變 **OR** ai.available 由 false→true → 重推；AI 文字措辭變 → 不重推（§4）。✅
- **推播時機**：整批彙總一則（內含多 embed），一輪 select 跑完彙總推（§1）。✅
- **ai.available=false 仍推**（標🤖暫無）——下注決策來自 selector 數學，AI 只評論，AI 掛不代表推薦不成立（§2）。✅
- **四把 webhook env 全定義**、#4 只實作 📋-推薦單 + 🧪-測試兩把推播，📊-回測/⚠️-告警 env 在位、推播後續（§3）。✅
- webhook 4xx/5xx **告警記一次／輪**、不逐筆刷（§5）。✅
- 🔒 webhook 值：小cc 不經手、不印 log；總司令自填 .env/Secret + 自驗收。
