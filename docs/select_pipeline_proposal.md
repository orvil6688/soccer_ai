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
       date  = pick.kickoff 的 UTC+8 日期
       prior = storage.find_recommendation(date, fixtureId, market, side)  # 取既有(供快取+保留 produced_at)
       pick.produced_at_local = prior.produced_at_local if prior else now_local()   # 首見凍結，重跑不漂移
       pick.ai = analyzer.analyze(pick, rec, prior_ai = prior.ai if prior else None) # C 快取在內
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
- `produced_at_local`：**首見凍結、重跑不更新**（保 CLV 時序防呆的「下注時點」穩定）。

---

## 4. 快取/覆寫（併 analyzer C/F）
- 重跑 select：`analyzer.analyze(pick, rec, prior_ai)` 內部以 `summary_hash` 判定——軌跡摘要沒變→沿用 prior `ai{}`（不重打 Gemini）；變了→重算覆寫、`ai.produced_at` 更新。
- 系統欄位（line/odds/edge/signals/trajectory）每次以最新 upsert 覆蓋；`produced_at_local` 保留首見值。

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
- storage upsert 改複合鍵：認可？（格式不變、僅去重鍵 + 新增 getter）
- 推薦儲存日期＝kickoff UTC+8 日期：認可？
- `produced_at_local` 首見凍結（不隨重跑更新）：認可？
