# analyzer #3 提案 — Gemini 開盤手推論層

> 狀態：**設計提案，待總司令過目核准後寫程式**。
> 定位鐵律：**系統＝事實層（客觀軌跡，不解讀意圖）；Gemini＝推論層（讀事實推意圖，強制 🤖，不改數據、不選注）；總司令＝拍板**。
> 關聯：[movement_trajectory_proposal.md](./movement_trajectory_proposal.md)、[phase3_proposal.md](./phase3_proposal.md)

---

## 0. Gemini 角色定位
- **輸入**：selector 已選出的 pick（含 edge、signals.shape/tag、雙 book 軌跡摘要）+ 該場 movement v2 軌跡記錄（八錨點/segment/summary）+ 對戰/開賽資訊。
- **任務**：以資深開盤手 + 玩家心理視角，**推論莊家意圖與市場心理**（疑似洗盤/誘盤/消息走漏/sharp 後場錢…），產出三段敘述。
- **明令不可**：不改任何系統數據、不重命名 shape、不參與選注決策（edge/注碼已由 selector 數學定）。
- **產出**：三欄敘述，**全部標 🤖**，寫進推薦記錄的獨立 `ai{}` 區塊（與系統客觀層分離）。

---

## 1. prompt 怎麼組（八錨點軌跡 → Gemini 輸入）

**(a) System/人設 prompt**（固定）：
> 你是世界盃資深開盤手，深諳莊家如何用盤口操控散戶心理。以下是系統「客觀記錄」的盤口軌跡事實。
> 你的任務：推論莊家意圖與市場心理。**只解讀、不改數據、不選注**。所有判斷皆為推論。
> 嚴格輸出 JSON：`{confidence_reasoning, injury_impact, market_reading}`，各欄分別 ≤50/≤100/≤150 字、繁中。

**(b) User content**：系統事實 →「結構化 JSON + 人類可讀渲染」雙附（讓模型既精確又好讀）：
- 對戰/盤：`Mexico vs South Africa, KO 6/12 03:00；pick=讓分 home -0.5 @1.95；edge 0.25球(line)`
- **逐 book 軌跡渲染**（pinnacle 主、singbet 皇冠系）：把八錨點+segment+summary 翻成事實句，例：
  > 「Pinnacle 讓分：初盤 −0.5(1.87/1.94)→ t24h −0.5(1.93/1.95)→ 收盤 −0.5(2.01/1.90)；**線全程不動**，低水方 home→away→home（**水互換 1 次**），shape=`fav_swap`，tag=`平0級·水互換·主升客升`，de-vig 機率位移≈0」
- 附原始 summary JSON（精確值）。
- **餵的是系統中性 shape + 客觀 tag + 數值**，**不預先標動機**（動機由 Gemini 推）。

**(c) 呼叫**：`google-generativeai`，`GenerationConfig(response_mime_type="application/json")` 強制 JSON 輸出；逾時/解析失敗 → 走失敗分流(§6)。

---

## 2. 三欄字數預算「各自獨立截斷」
- 欄位與上限：`confidence_reasoning`≤50、`injury_impact`≤100、`market_reading`≤150（字＝字元數）。
- **prompt 先要求**模型自律在限內；**程式再強制**逐欄獨立截斷（不信任模型）：
  ```
  def _truncate(text, n): return text if len(text)<=n else text[:n-1].rstrip()+"…"
  ```
- **逐欄各自截**（禁止合併後截，避免某欄爆掉吃掉別欄/JSON 膨脹）。
- ⚠️ `injury_impact`：**我們無傷停資料源**。此欄定義為「**從盤口異動推論的消息面/陣容疑慮**」（純推論、非真實傷停），故必為 🤖。提案於 prompt 明示此欄是「盤口反推的消息面推測」，不得宣稱真實傷情。

---

## 3. 🤖 標記怎麼強制（下游不重判）
- **不靠模型自己加** 🤖。程式拿到三欄、截斷後，**結構性包進 `ai{}` 區塊**：
  ```json
  "ai": {"tag":"🤖 AI 推論", "is_inference": true, "model":"gemini-…", "generated_at":ISO,
         "confidence_reasoning":"…", "injury_impact":"…", "market_reading":"…"}
  ```
- 整個 `ai{}` 帶 `tag`+`is_inference:true` → 下游（notifier/web）一律以 🤖 呈現，**讀 `ai{}` 即知是推論、不重判**。
- 🤖 標記放**區塊層**（`ai.tag`），不佔三欄的 50/100/150 字額度（純內容）；UI 呈現時前綴 🤖。

---

## 4. 動機推論界線（防 Gemini 主觀污染系統客觀層）
- **結構性隔離**：analyzer **只新增 `rec["ai"]`，絕不改** `rec["signals"]`/`rec["trajectory"]`/movement 記錄/shape 名。
- 系統 shape 永遠中性（`fav_swap` 等）；Gemini 的動機詞（「疑似洗盤」「消息走漏」）**只**出現在 `ai.market_reading`/`ai.confidence_reasoning`，且整塊 🤖。
- prompt 明令：可推論動機，但**不得修改或重命名系統 shape**；動機是你的推論不是事實。
- 結果：客觀層（可回測）與推論層（🤖）並存但不混；回測 `by_trajectory` 用的是系統中性 shape，不受 Gemini 影響。

---

## 5. 金鑰 env 讀 + 寫推薦記錄接 backtest 閉環
- **金鑰**：`config.GEMINI_API_KEY`（`os.getenv`，env/.env/CI Secrets）。**絕不硬編**。缺金鑰 → 不致命，跳過 AI（見 §6）。
- **模型**：`config.GEMINI_MODEL`（預設 flash 類，如 `gemini-2.0-flash`，可改）。
- **寫入閉環**：analyzer 把 `ai{}` 併入 pick → 成為完整**推薦記錄**，經 `storage.append_recommendation` 寫入 `recommendations/{date}.json`。
  - 推薦記錄 = 系統欄位（fixtureId/market/side/line/odds/stake_units/signals/trajectory）+ `ai{}`。
  - **backtest 既有閉環直接吃**：`settle_recommendation`/`compute_clv`/`by_trajectory` 只讀系統欄位，`ai{}` 是附加、不影響回測；命中率/CLV/by_trajectory 照算。閉環接上。
- **呼叫點**：屬 `--mode select` 流程（selector→analyzer→store→notify）。本提案聚焦 analyzer.py；`--mode select` 編排與 notifier 為相鄰下一塊（#5/#4）。

---

## 6. 失敗分流（Gemini 掛了不阻斷整條 pipeline）
- **部分失敗、逐 pick 隔離**：某 pick 的 Gemini 失敗，不影響其他 pick、不中斷 select/movement/backtest。
- 失敗情境具名攔截：金鑰缺、API 錯誤/逾時、額度、回應非 JSON/解析失敗。
- 失敗時：**仍寫推薦記錄**，但 `ai = {"available": false, "reason": "<具名>"}`（或省略 `ai`）。系統客觀數據完整 → **該推薦仍可回測**（只是沒 AI 敘述）。
- 不致命、不 raise 中斷；log 警告。可選輕量重試（1 次），逾時上限短（如 15s）。

---

## 模組與切分
- `analyzer.py`：`build_prompt(pick, record)` / `_render_trajectory(record)` / `_truncate` / `analyze(pick, record) -> ai_dict|unavailable`（含 Gemini 呼叫、JSON 解析、截斷、包 `ai{}`）。
- 不在本塊：`--mode select` 編排（#5）、notifier Discord（#4）、web/pages（後置）。
- **獨立 commit**：analyzer.py + config(GEMINI_MODEL) 一塊；測試用真實軌跡（MLS/WC）+ 模擬 Gemini 回應驗截斷/🤖/失敗分流（真打 Gemini 一次驗 JSON 格式）。

## 待校準/待確認
- shape→prompt 用語、三欄字數上限、模型選型，皆可後續調。
- `injury_impact` 無真實傷停源（純盤口反推）——是否保留此欄名、或改名「消息面推測」，請總司令定。

---

## 提案自檢（你要審的）
1. prompt 組法：§1（雙附 JSON+渲染、餵中性 shape）✅
2. 字數獨立截斷：§2（逐欄、程式強制、injury 無源警示）✅
3. 🤖 強制：§3（區塊層 tag+is_inference，不靠模型、不佔額度）✅
4. 動機界線：§4（只加 ai{}、不改 shape、結構隔離）✅
5. env 金鑰 + 閉環：§5（os.getenv、寫推薦、backtest 照吃）✅
6. 失敗分流：§6（逐 pick 隔離、仍寫記錄可回測、不中斷）✅
