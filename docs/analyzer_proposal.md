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
> 嚴格輸出 JSON：`{confidence_reasoning, injury_news_inference, market_reading}`，各欄分別 ≤50/≤100/≤150 字、繁中。
> （`injury_news_inference`＝由盤口異動反推的傷病/陣容消息推測；**僅盤口反推、不得宣稱已證實傷情**。）

**(b) User content**：系統事實 →「結構化 JSON + 人類可讀渲染」雙附（讓模型既精確又好讀）：
- 對戰/盤：`Mexico vs South Africa, KO 6/12 03:00；pick=讓分 home -0.5 @1.95；edge 0.25球(line)`
- **逐 book 軌跡渲染**（pinnacle 主、singbet 皇冠系）：把八錨點+segment+summary 翻成事實句，例：
  > 「Pinnacle 讓分：初盤 −0.5(1.87/1.94)→ t24h −0.5(1.93/1.95)→ 收盤 −0.5(2.01/1.90)；**線全程不動**，低水方 home→away→home（**水互換 1 次**），shape=`fav_swap`，tag=`平0級·水互換·主升客升`，de-vig 機率位移≈0」
- 附原始 summary JSON（精確值）。
- **餵的是系統中性 shape + 客觀 tag + 數值**，**不預先標動機**（動機由 Gemini 推）。

**(c) 呼叫**：`google-generativeai`，`GenerationConfig(response_mime_type="application/json")` 強制 JSON 輸出；逾時/解析失敗 → 走失敗分流(§6)。

---

## 2. 三欄字數預算「各自獨立截斷」
- 欄位與上限：`confidence_reasoning`≤50、`injury_news_inference`≤100、`market_reading`≤150（字＝字元數）。
- **prompt 先要求**模型自律在限內；**程式再強制**逐欄獨立截斷（不信任模型）：
  ```
  def _truncate(text, n): return text if len(text)<=n else text[:n-1].rstrip()+"…"
  ```
- **逐欄各自截**（禁止合併後截，避免某欄爆掉吃掉別欄/JSON 膨脹）。
- 🔧 **`injury_impact` → 改名 `injury_news_inference`**（總司令裁示 (b)，更誠實）。**我們無傷停資料源**：此欄為「**從盤口異動反推的傷病/陣容消息推測**」。
  - prompt **仍以傷病/陣容消息為主要推測對象**（不丟焦點），但**明示「僅盤口反推、不得宣稱已證實傷情」**，整欄 🤖。
  - 同步改兩份記憶中樞 §5.4 欄名 + `config.WORD_BUDGET` key（建置時）。

---

## 3. 🤖 標記強制 + `ai{}` 完整 schema（key 列死）
- **不靠模型自己加** 🤖。程式拿到三欄、截斷後**結構性包進 `ai{}`**；整塊帶 `tag`+`is_inference` → 下游一律 🤖 呈現、**不重判**。🤖 放**區塊層**不佔字數額度。
- **`ai{}` 確切 key 清單**（成功 vs 失敗/略過）：

  成功（available=true）：
  ```json
  "ai": {
    "available": true,
    "reason": null,
    "tag": "🤖 AI 推論",
    "is_inference": true,
    "model": "gemini-2.0-flash",     // 或 mock（TEST_MODE）
    "produced_at": "ISO(UTC+8)",      // 對應「哪個軌跡快照」的戳記
    "summary_hash": "sha1(...)",      // 快取/覆寫判定鍵（見 §8/§9）
    "confidence_reasoning": "…",      // ≤50
    "injury_news_inference": "…",     // ≤100
    "market_reading": "…"             // ≤150
  }
  ```
  失敗/略過（available=false）：
  ```json
  "ai": {"available": false, "reason": "insufficient_window|missing_key|api_error|timeout|parse_error",
         "produced_at": "ISO(UTC+8)", "summary_hash": "sha1(...)"}
  ```
  - 失敗時**省略三欄 + tag/is_inference/model**；仍存 `produced_at`+`summary_hash`（供快取判定、避免反覆重打）。
  - 下游判定：`ai.available && ai.is_inference` → 以 🤖 呈現三欄；否則只顯示系統數據。

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

## 7.（🔴 B 最急）打 Gemini 前先攔 insufficient
- **在組 prompt / 呼叫 API 之前**先檢查：`signals.shape == "insufficient"` **或** 決策窗（t72h–t30m）無任一錨點 → **直接** `ai = {"available": false, "reason": "insufficient_window", produced_at, summary_hash}`，**不打 API、不燒額度**。
- 動機：離開賽 6 天全 pick insufficient（決策窗空），這條讓賽前不會空燒 Gemini。沿用 §3 失敗 `ai{}` 格式。
- 決策窗一旦填上（shape ≠ insufficient）→ summary_hash 改變 → 下次 select 自動重打（見 §8/§9）。

## 8.（🟡 C）`ai{}` 快取：summary 沒變不重打 Gemini
- `summary_hash = sha1(fixtureId + market + side + 該 book 的 trajectory summary 正規化 JSON)`。
- caller（#5 編排）查該 pick 既有推薦的 `ai`：若 `ai.summary_hash == 新 hash`（軌跡摘要沒變）→ **直接沿用舊 `ai{}`，不呼叫 Gemini**（含沿用 available=false 的 insufficient，避免反覆重打）。
- `analyze(pick, record, prior_ai=None)`：prior_ai 命中且 hash 相同 → 回 prior_ai（cache hit）；否則重算。analyzer 保持純函式，查既有由編排層做。

## 9.（🟡 F）覆寫策略 + `produced_at` 戳記
- 推薦記錄以 **(fixtureId, market, side)** 為鍵 upsert（#5 storage 確定；目前 append_recommendation 僅以 fixtureId upsert，#5 改複合鍵以支援一場多注）。
- 重跑 select：同一 pick **summary_hash 未變 → 不覆寫、不重算 `ai{}`**（沿用，含其 `produced_at`）；**hash 變（軌跡移動）→ 重算並覆寫 `ai{}`、`produced_at` 更新**為新戳記。
- `produced_at` + `summary_hash` 明確標「此 AI 推論對應哪個軌跡快照」，回測與稽核可追溯。

## 10.（🟡 TEST_MODE）旗標行為釘死
- `config.is_test_mode()` 為真 → analyzer **一律 mock、絕不真打 Gemini、不燒額度**。
- mock 產出：`ai{ available:true, model:"mock", 三欄=確定性佔位文字(壓 🧪), is_inference:true, tag, produced_at, summary_hash }` → 讓 `--mode select --test` 能離線跑完整管線、推薦可進回測測試。
- 正式（TEST_MODE off）才真打 Gemini。

## 11.（🟢）行尾
- `analyzer.py` = **LF**（`.gitattributes` 已鎖 `*.py text eol=lf`）。

---

## 模組與切分
- `analyzer.py`：`build_prompt(pick, record)` / `_render_trajectory(record)` / `_truncate` / `analyze(pick, record) -> ai_dict|unavailable`（含 Gemini 呼叫、JSON 解析、截斷、包 `ai{}`）。
- 不在本塊：`--mode select` 編排（#5）、notifier Discord（#4）、web/pages（後置）。
- **獨立 commit**：analyzer.py + config(GEMINI_MODEL) 一塊；測試用真實軌跡（MLS/WC）+ 模擬 Gemini 回應驗截斷/🤖/失敗分流（真打 Gemini 一次驗 JSON 格式）。

## 待校準
- shape→prompt 用語、三欄字數上限、模型選型、summary_hash 正規化細節，皆可後續調（標待校準）。
- ✅ `injury_impact` → `injury_news_inference`（總司令裁示 (b)，已定案）。

---

## 提案自檢（8 點審對照）
1. prompt 組法：§1（雙附 JSON+渲染、餵中性 shape）✅
2. 字數獨立截斷：§2（逐欄程式強制；injury 改名 injury_news_inference、焦點仍傷病但僅盤口反推）✅
3. 🤖 強制 + ai{} schema：§3（區塊層 tag+is_inference、不佔額度、key 列死成功/失敗兩式）✅
4. 動機界線：§4（只加 ai{}、不改 shape、結構隔離）✅
5. env 金鑰 + 閉環：§5（os.getenv 不硬編、寫推薦、backtest 照吃）✅
6. 失敗分流：§6（逐 pick 隔離、仍寫記錄可回測、不中斷）✅
7. 🔴 B insufficient 前置攔截：§7（打 API 前攔、ai available:false reason:insufficient_window、不燒額度）✅
8. 🟡 C 快取 / 🟡 F 覆寫+produced_at / 🟡 TEST_MODE mock / 🟢 LF：§8/§9/§10/§11 ✅
