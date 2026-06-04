# Phase 3 提案 — 選注引擎 + AI 敘述 + 推播（已核准）

> 狀態：**已核准（總司令 2026-06-04）**，依此施工。Pages（web_builder + gh_pages）後置最後做。
> 關聯：[arch_A_proposal.md](./arch_A_proposal.md)、[oddspapi_findings.md](./oddspapi_findings.md)

---

## 0. 核心前提與哲學裁示

無獨立基本面/xG 公允值模型（Phase 5）。Phase 3 edge **不預測比分**，純從**市場歧見**取得，呼應系統本質「找莊家定價歧見」。

**總司令裁示**：
1. **edge 哲學**：Pinnacle 去水位求公允 vs 1xBet 偏差 + 線移動。**選注交給數學，Gemini 只產敘述、不參與選注決策**（不讓 AI 估公允）。
2. **動機層（D 段）v1 整塊不做**，理由：
   - 「淘汰賽偏小」是**主觀預測比賽風格**，違反「不預測、只找盤口歧見」本質；且 **Pinnacle 公允線本身已反映淘汰賽因素**，再降權＝重複計算、扭曲 edge。
   - 死亡之組、dead rubber **本就無資料源**。
   - → D 段全留 **config 空鉤子**延後。selector v1 **零主觀預測**。
3. **誘盤過濾門檻**：用預設值，標「**待回測校準**」，現不調。
4. 切分順序照下表；**#1+#2 完成後停下驗證候選 pick，再做 analyzer**。

---

## 1. 資料取得設計
- selector 需 **Pinnacle + 1xBet 當前盤**：用 `odds-by-tournaments` 各抓一次（2 次/run，批量涵蓋全賽事，計額度）取最新可下注盤。
- 線移動訊號讀已存 movement 六錨點（Pinnacle）。
- 只對**可下注窗**（開賽前 `0 < ttk ≤ SELECT_WINDOW_HOURS`，預設 24h，待校準）的賽事跑選注。

---

## 2. selector 選注邏輯（純盤口、確定性、可回測）

### A. 去水位（de-vig）求 Pinnacle 公允
兩邊市場價 `O₁,O₂` → 隱含 `p=1/O`，水位 `overround=p₁+p₂`，**公允機率 `fair=p/overround`**。

### B. edge 計算
同一市場比較 Pinnacle（公允錨）vs 1xBet（實際開盤）：
- **線差 edge（球，主閘）**：兩莊主線差。讓分以 home 視角線；1xBet 給某邊更甜的線 → 背那邊，`edge_goals = |線差|`。大小球：1xBet 總分較低→Over 更甜；較高→Under 更甜。**主閘 `edge_goals ≥ 0.25`**（規格 edge_threshold）。
- **價差 edge（EV%，次閘）**：**僅當兩莊同線**時，`edge_pct = 1xBet價 × Pinnacle公允機率 − 1`，背 EV>0 那邊，門檻 `≥ EDGE_PCT_THRESHOLD（預設 0.02）`。
- 線不同 → 走線差；線相同 → 走價差。互斥。

### C. 誘盤過濾（#2；預設值「待回測校準」）
1. **盤太甜**：`edge_goals > 1.0` 或 `edge_pct > 0.12` → 視為過期/錯盤/陷阱，剔除。
2. **反向線移動逆我**：Pinnacle 初盤→當前線往我方反向移動 → 剔除/降權；同向＝確認訊號（讀 movement 六錨點 initial vs 最新）。
3. **關鍵數字**：大小球 2.5/3.0、讓分 0/0.5/1；edge 靠跨越關鍵數字才成立 → 要求更大邊際。
4. **盤口失效**：1xBet `active=false`/`suspended` 或盤口過舊 → 剔除。

### D. 動機檢查 —— **v1 整塊不做（空鉤子）**
規格的「死亡之組降權／淘汰賽偏小」全延後。理由見 §0.2。`config` 預留空鉤子（`DEATH_GROUP_TEAMS=[]` 等），未來有資料源再啟用。

### E. 注碼（規格：價值高2、一般1）
- **2 單位**：`edge_goals ≥ 0.5` **且** 線移動同向確認 **且** 未命中任何誘盤旗標。
- **1 單位**：其餘通過者。
- 鐵律：**反向線移動僅記為「加權訊號」存檔供回測，不單獨觸發 2 單位**。

### F. selector 輸出（候選 pick）
`{fixtureId, home, away, kickoff_utc, kickoff_local, market, side, line(1xBet), odds(1xBet該邊價), fair_prob(Pinnacle), pinnacle_line, xbet_line, edge_goals, edge_pct, edge_source}`；#2 再加 `stake_units / signals / filters`。通過者交 analyzer 補敘述 → 落地**推薦記錄**（backtest 消費 schema，閉環接上）。

---

## 3. 切分（每塊獨立 commit，依賴順序）

| # | 區塊 | 做什麼 | 依賴 |
|---|---|---|---|
| 1 | **selector 核心** | config 選注參數；de-vig；edge_goals/edge_pct；可下注窗候選偵測；輸出候選 pick（**不含過濾**）| movement / oddspapi_client |
| 2 | **selector 過濾+注碼** | 誘盤過濾(C)、注碼(E)；動機(D)留空鉤子 → 最終 picks | #1 |
| — | **（停）** | **#1+#2 完成停下，總司令驗證候選 pick** | |
| 3 | **analyzer (Gemini)** | GEM 開盤手人設；字數 50/100/150 獨立截斷；強制 🤖；`GEMINI_API_KEY` 從 `config`(env) 讀**不硬編**；產敘述並寫推薦記錄 | #2 |
| 4 | **notifier (Discord)** | 推播 picks；測試模式發 test webhook 或略過、壓 🧪 | #3 |
| 5 | **main 接線** | `--mode select`：抓盤→selector→analyzer→存推薦→notify | #1–4 |
| 6 | **(後置) web_builder + gh_pages** | 靜態 HTML + Pages | 最後 |

**金鑰**：analyzer 用 `config.GEMINI_API_KEY`（`os.getenv` 讀 env/.env/CI Secrets），**絕不硬編值**。

---

## 4. 待校準（回測後調）
SELECT_WINDOW_HOURS(24)、EDGE_PCT_THRESHOLD(0.02)、盤太甜上限(1.0球/0.12)、關鍵數字邊際、注碼門檻(edge_goals≥0.5)。全標「待回測校準」。
