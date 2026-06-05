# #5 提案 — `--mode select` 編排 + storage 複合鍵

> 狀態：**設計提案，待 8 點審 + 總司令過目核准才寫程式**。
> ⚠️ 觸碰 §10 絕對不動清單之 `storage.py` 寫入格式（prod 未上線、schema 可改，但須提案+過目）。
> 關聯：[phase3_proposal.md](./phase3_proposal.md)、[analyzer_proposal.md](./analyzer_proposal.md)

---

## 0. 目標
把已完成的零件接成閉環：**selector（純數學選注）→ analyzer（🤖 推論評論）→ 存推薦記錄 → backtest 隔日回填**。
本塊只到「存推薦」；Discord 推播＝下一塊 #4（沒帶 `ai{}` 的推薦先產出，推播才有料）。

---

## 1. `--mode select` 編排流程
```
main --mode select [--test]:
  1) 致命前置：require ODDSPAPI_API_KEY（缺→exit1）。GEMINI 缺不致命（analyzer 自行降級）。
  2) picks = selector.select()         # 候選偵測→誘盤過濾→注碼；已含 signals/trajectory(凍結)
  3) for pick in picks:
       rec   = storage.load_fixture_movement(pick.fixtureId)     # 取完整軌跡供 analyzer 渲染
       date  = config.local_date(pick.kickoff_utc)               # kickoff 轉 UTC+8 的日曆日（共用函式）
       prior = storage.find_recommendation(date, fixtureId, market, side)  # 取既有(供快取+保留 produced_at_local)
       pick.produced_at_local = prior.produced_at_local if prior else config.now_local().isoformat()  # 首見凍結(CLV 基準)
       pick.ai = analyzer.analyze(pick, rec, prior_ai = prior.ai if prior else None)  # 內含 C 快取 + ai.produced_at 隨 hash 更新
       storage.append_recommendation(pick, date_local=date)      # 以 (fixtureId,market,side) upsert
  4) log：本次 picks 數 / ai available 數 / 各 reason 計數 / 額度
  （5) notify → #4，本塊不做）
```
- **逐 pick 隔離**：任一 pick 的 analyzer/儲存失敗 → log 後跳過，不中斷其餘（部分失敗分流）。
- **TEST_MODE**：寫 `data/test/`、analyzer 走 mock（不真打 Gemini）、推薦壓 🧪。

---

## 2. storage 複合鍵改動範圍（精準、最小）
**現況**：`append_recommendation` 以 **fixtureId** upsert → 一場同時有讓分+大小球兩注時，後者覆蓋前者（漏注）。
**改為**：以 **(fixtureId, market, side)** 複合鍵 upsert，支援一場多注。

| 函式 | 改動 | 寫入「格式」是否變 |
|---|---|---|
| `append_recommendation(record, date_local)` | dedup 條件 `it.fixture_id!=fid` → `(it.fixtureId,it.market,it.side) != (…)` | **否**（仍是 list[dict]，每筆仍含 fixtureId/market/side）|
| `find_recommendation(date_local, fixtureId, market, side)` | **新增** getter，回符合複合鍵的那筆或 None（供 #1 取 prior_ai / produced_at）| 新增讀取函式，不動格式 |
| `load_recommendations` / `save_recommendations` | **不變** | 否 |
| `_recommendations_path` | **不變**（仍 `recommendations/{date}.json`）| 否 |

- **檔案格式不變**（list of dict）；變的只是 **upsert 去重鍵**（fixtureId → 複合鍵）。原子寫入、路徑、隔離全不動。
- **儲存日期**：以**該場 kickoff 的 UTC+8 日期**為檔名（非產出日）→ backtest `run_backfill(該日)` D+1 直接撈到當日所有推薦結算。
- prod `recommendations/` 目前**空**（未上線），故此改動不破壞既有資料。

### 🔴 跨日歸檔：存/撈共用同一個 UTC+8 日期函式
- 世界盃台灣半夜開賽（如 KO `2026-06-12T03:00+08:00`，其 UTC 為 `06-11T19:00Z`）。**歸檔日期＝kickoff 轉 UTC+8 後的日曆日**＝`06-12`（不是 UTC 的 `06-11`）。
- **新增共用函式 `config.local_date(dt_or_iso) -> "YYYY-MM-DD"`**（內部 `to_local()` 轉 UTC+8 再取日期）。
  - select 編排：`date = config.local_date(pick["kickoff_utc"])` 決定存檔日。
  - backtest：`run_backfill` 預設日 `config.local_date(now_local - 1天)`；指定日也走同函式。
- **存與撈一律經此函式**，杜絕「一邊 UTC 一邊 UTC+8 → 存 6/12 撈 6/11」漏撈。

---

## 3. 推薦記錄最終形狀（backtest 直接吃）
selector pick + `produced_at_local` + `ai{}`：
```jsonc
{ "fixtureId","market","side","line","odds","stake_units",      // selector 數學(backtest 用)
  "kickoff_utc","kickoff_local","home","away",
  "edge_goals","edge_pct","edge_source","fair_prob","pinnacle_line","xbet_line",
  "signals":{"signal","reverse_against","key_number_cross","shape","tag"},  // 系統客觀
  "trajectory":{"pinnacle":{shape,tag,...},"singbet":{...}},                // 凍結軌跡
  "produced_at_local":ISO,                                       // 首見凍結(CLV 時序防呆用)
  "ai":{...} }                                                   // 🤖 推論層(analyzer)；backtest 不讀
```
- backtest 既有 `settle_recommendation/compute_clv/by_trajectory` 只讀系統欄位（market/side/line/odds/stake_units/kickoff_utc/produced_at_local/signals.shape）→ **閉環自動接上**，`ai{}` 純附加不影響。

### 🔴 兩個 produced_at 是不同欄位，各管各（勿混為一談）
| 欄位 | 層 | 語意 | 重跑行為 |
|---|---|---|---|
| **`produced_at_local`**（推薦頂層）| 推薦/CLV 層 | **下注時點**＝CLV 時序防呆基準 | **首見凍結、重跑不更新**（否則 CLV 基準漂移）|
| **`ai.produced_at`**（在 `ai{}` 內）| analyzer 推論層 | 標「這版 Gemini 推論對應**哪個軌跡快照**」 | **隨軌跡 hash 變而更新**（analyzer §F；否則回測分不清哪版推論對應哪個 shape，by_trajectory 會錯）|
- 由不同模組管：`ai.produced_at` 由 `analyzer.analyze` 寫（hash 變即更新）；`produced_at_local` 由 select 編排寫（首見凍結）。兩者**不得用一句「produced_at 凍結」一起凍**。

---

## 4. 快取/覆寫（併 analyzer C/F）
- 重跑 select：`analyzer.analyze(pick, rec, prior_ai)` 內部以 `summary_hash` 判定——軌跡摘要沒變→沿用 prior `ai{}`（不重打 Gemini，`ai.produced_at` 不變）；變了→重算覆寫、**`ai.produced_at` 更新**（標新快照）。
- 系統欄位（line/odds/edge/signals/trajectory）每次以最新 upsert 覆蓋；**`produced_at_local` 保留首見值**（CLV 基準不漂移）。
- 注意：analyzer 現版 `ai{}` 已含 `produced_at`（=快照戳記）；本塊不改 analyzer，只在編排層額外蓋一個**頂層** `produced_at_local`（CLV 基準）。兩戳記並存、語意不同。

---

## 5. main 改動
- `--mode` 選項加 `select`；`--test` 沿用。
- 致命：ODDSPAPI_API_KEY；GEMINI 缺→analyzer 回 `ai.available=false reason=missing_key`，不致命。
- 不改 movement/backtest 模式。

---

## 6. 不在本塊（明確界線）
- **#4 notifier Discord 推播**（下一塊）。
- web/pages、titan007、上半場（暫停/後置）。
- selector/analyzer/trajectory 邏輯**不動**（只編排 + storage 去重鍵）。

---

## 7. 失敗分流
- ODDSPAPI 缺→致命 exit1。
- 逐 pick：analyzer 失敗→`ai.available=false`仍存；單筆儲存例外→log 跳過不中斷。
- GEMINI 額度/503→analyzer api_error，該注無 ai、仍可回測。

---

## 8 點自審對照
1. 環境變數：ODDSPAPI 致命、GEMINI 非致命，皆 env ✅
2. 鍵值/複合鍵：推薦 upsert 改 (fixtureId,market,side)，明確 ✅
3. 字數預算/截斷：analyzer 既有，本塊不動 ✅
4. 測試模式：data/test + analyzer mock + 🧪 ✅
5. 失敗分流：致命(ODDSPAPI) vs 部分(逐 pick/GEMINI) ✅
6. 禁止觸碰：僅動 storage upsert 鍵(格式不變)+ main 編排；selector/analyzer 邏輯不碰 ✅
7. 閾值精確：無新閾值（沿用 selector/analyzer）✅
8. 行尾：改動檔 `*.py=LF` ✅

---

## 待確認（請總司令/小c 裁）
- storage upsert 改複合鍵 (fixtureId,market,side)：認可？（格式不變、僅去重鍵 + 新增 getter）✅ 小c 已認可
- 推薦儲存日期＝kickoff UTC+8 日期、存撈共用 `config.local_date`：認可？
- **兩個 produced_at 各管各**（`produced_at_local` 首見凍結／`ai.produced_at` 隨軌跡 hash 更新）：認可？

## 🟡 補釘（複審回應）
- **🟡1 produced_at 兩義性**：已拆清為兩欄各管各（§3「兩個 produced_at」表 + §4）。`produced_at_local`(CLV 基準)首見凍；`ai.produced_at`(快照戳記)隨 hash 更新——不再用一句話一起凍。
- **🟡2 跨日歸檔**：新增共用 `config.local_date()`，存(select)與撈(backtest)一律經此 UTC+8 轉換，杜絕跨日漏撈（§2 跨日歸檔）。
