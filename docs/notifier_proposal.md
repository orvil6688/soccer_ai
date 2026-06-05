# #4 提案 — notifier（Discord 推播帶 ai{} 的推薦）

> 狀態：**設計提案，待 8 點審 + 總司令過目核准才寫程式**。
> 關聯：[select_pipeline_proposal.md](./select_pipeline_proposal.md)、[analyzer_proposal.md](./analyzer_proposal.md)

---

## 0. 目標與界線
- 把 `--mode select` 產出、**帶 `ai{}` 的推薦**推到 Discord，給總司令看單。
- **不選注、不改推薦**：notifier 只「呈現」storage 已存的推薦；selector/analyzer 不碰。
- 推播失敗**不阻斷** pipeline（推薦已存、回測照跑）。

---

## 1. 觸發點與流程
- 接在 `--mode select` 編排尾端：每筆 `append_recommendation` 後（或整批收集後）呼叫 `notifier.notify(rec)`。
- 建議**整批收集、逐筆送**（逐筆 embed），順序依 kickoff。
```
for pick in picks:
    ... 存推薦 ...
    notifier.notify(rec)     # rec = 剛存的完整推薦(含 signals/ai{})
```

## 2. 推什麼（內容 + 🤖 界線）
單筆推薦 → 一則 Discord embed：
- **標題**：`{home} vs {away}　{kickoff_local}`
- **選注（系統數學）**：`{market} {side} 線{line} @ {odds}　{stake_units}單位　edge {edge_goals}球`
- **盤口軌跡（系統客觀）**：`shape={signals.shape}　{signals.tag}　訊號={signals.signal}`（中性，無動機）
- **🤖 AI 推論**（`ai.available` 時）：三欄 `confidence_reasoning / injury_news_inference / market_reading`，整段冠 `🤖 AI 推論`；`ai.available=false` → 顯示「🤖 暫無（reason）」不顯三欄。
- **資料品質標記**：系統層 ✅ 客觀 / AI 層 🤖；明確分區，下游/總司令一眼分清「事實 vs 推論」。

## 3. 環境變數 / 測試模式
- **正式**：`config.DISCORD_WEBHOOK_URL`（env，不硬編）。缺 → log 警告、略過推播（非致命）。
- **測試（`is_test_mode()`）**：
  - 有 `config.DISCORD_TEST_WEBHOOK_URL` → 推到 test 頻道；否則**略過不推**（不污染正式頻道）。
  - 內容壓 `🧪`（標題前綴），與正式區隔。

## 4. 防重複推播（不每小時洗頻）
- `--mode select` 每小時跑、同一注會重複出現 → 必須去重，否則洗版。
- **notify_hash** = `sha1(fixtureId,market,side,line,odds,stake_units,signals.signal,ai.summary_hash)`。
- 推播前比對推薦記錄既有 `notified_hash`：**相同 → 跳過不推**；不同（首次／線/注/訊號/AI 有變）→ 推，並把 `notified_hash`+`notified_at` 寫回該推薦記錄。
- 效果：首次出單推一次；之後只在「實質變化」時再推（例：line 變、stake 升、AI 從無到有）。
- ⚠️ 這會在推薦記錄多兩個欄位 `notified_hash`/`notified_at`（list[dict] 格式不變、非 §10 寫入格式契約變更，僅加欄）。

## 5. 失敗分流
- 逐筆 try/except 具名攔截：webhook 缺/4xx/5xx/逾時/網路 → log 警告、**該筆跳過、不中斷其餘、不中斷 pipeline**。
- 不重試或輕量 1 次重試（Discord 偶發 429 帶 retry_after，可選尊重；逾時上限短）。
- 推播失敗不影響推薦已存與回測。

## 6. 模組與切分
- `notifier.py`：`_format_embed(rec)` / `_notify_hash(rec)` / `send(webhook, payload)` / `notify(rec)`（含去重+測試分流+失敗攔截，回 sent/skipped/failed）。
- `main._run_select`：存推薦後呼叫 `notifier.notify(rec)`；彙總 sent/skipped/failed 數入 log。
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

## 待確認（請總司令/小c 裁）
- 去重：notify_hash 含 `ai.summary_hash`（AI 內容變也重推）—— 認可？還是只看下注關鍵欄(line/odds/stake)變才重推、AI 變不重推？
- 推播時機：每筆即推 vs 整批彙總一則訊息？（提案：逐筆 embed）
- `ai.available=false`（如 insufficient/503）的推薦：仍推（標🤖暫無）還是不推？（提案：仍推，因下注決策來自 selector 數學、AI 只是評論）
