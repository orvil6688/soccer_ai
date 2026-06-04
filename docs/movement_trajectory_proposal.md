# movement 升級提案 — 完整盤口軌跡分類（八錨點）

> 狀態：**設計提案，待總司令過目核准後才寫程式**。這是系統核心智慧。
> 取代關係：**完整取代並升級**先前的「movement 線+賠率雙軌」修正。`selector.line_movement_signal`
> （selector.py:209-216「線不動就 flat、沒看賠率」那段）將被本設計的軌跡分類整段取代，
> 不是修那兩行——新設計天然涵蓋賠率維度，原 bug 在新設計下不存在。
> 關聯：[arch_A_proposal.md](./arch_A_proposal.md)、[phase3_proposal.md](./phase3_proposal.md)

---

## 0. 前提與驗證
- **T-72h 可得性已實打驗證**：完賽場序列涵蓋開賽前 168h、73k 點；T-72h 目標 ±3h 內 1844 點、最近點距目標 0.06h；T-30m 精準命中。世界盃賽前數月開盤，覆蓋更深 → 八錨點皆可填，非一片 null（未開到的時段仍依規則標 null）。
- **定位三層**（貫穿全設計）：
  - **系統＝事實層**：客觀記錄並結構化描述完整盤口軌跡，確定性、可回測，**不解讀意圖**。
  - **GEMINI＝推論層**：拿軌跡描述+原始數據，以開盤手+玩家心理推論**意圖**，強制標 🤖。
  - **總司令＝拍板層**：看系統數據 + GEMINI 推論 + 自身判斷最後決定。

---

## 1. 八錨點（六錨點 → 八錨點）

| 錨點 | 目標時刻 | 類別 | 用途 |
|---|---|---|---|
| initial | 序列第一筆 | **回測輔助** | 莊家試水溫價、雜訊多，**不當決策訊號**，僅回測對照 |
| **t72h** | KO−72h | **決策（核心）** | 新增：捕捉賽前 2–5 天「真正反映現實」區間 |
| t24h | KO−24h | 決策（核心） | |
| t12h | KO−12h | 決策（核心） | |
| t6h | KO−6h | 決策（核心） | |
| t1h | KO−1h | 決策（核心） | |
| **t30m** | KO−30m | **決策（核心）** | 新增：開賽前最後突變 |
| closing | 開賽前最後一筆 | **回測輔助** | 來不及投注，僅 CLV / 回測對照 |

- **核心 6 個（72h–30m）**＝選注與推論主依據；**輔助 2 個（initial/closing）**＝回測用，schema 標 `role:"decision"|"backtest"`，GEMINI 也據此知道孰輕孰重。
- 沿用三規則：取最接近目標時刻那筆、各錨點存 `target_ts`+`captured_ts`(+`offset_sec`)、不存在標 null 不硬塞（目標落在序列 [最早,最新] 外 → null）。

---

## 2.（Q1）軌跡描述資料結構

`trajectory` 掛進 movement 記錄頂層，**bookmaker → market → {anchors, segments, summary}** 三層：

```jsonc
"schema_version": 2,
"trajectory": {
  "pinnacle": {                          // 多家並存（CROWN 雙記，見 §7）
    "handicap": {                        // 客觀以 home 視角記錄（線=home 視角）
      "anchors": {
        "initial": {"target_ts":null,"captured_ts":ISO,"offset_sec":null,
                    "line":-0.5,"home_odd":1.95,"away_odd":1.90} ,
        "t72h": {"target_ts":ISO,"captured_ts":ISO,"offset_sec":int,
                 "line":-0.5,"home_odd":1.98,"away_odd":1.88} ,
        "t24h":..., "t12h":..., "t6h":..., "t1h":..., "t30m":..., "closing":...   // 每個 obj 或 null
      },
      "segments": [                      // 相鄰「決策」錨點之間（72h→24h→…→30m，共 5 段）
        {"from":"t72h","to":"t24h","present":true,
         "line_steps": +2,                              // (new−old)/0.25，帶號
         "home_odd_delta": -0.10,"home_odd_dir":"down",
         "away_odd_delta": +0.08,"away_odd_dir":"up",
         "fav_from":"home","fav_to":"home","fav_swap":false} ,
        ...
      ],
      "summary": {                       // 跨整個決策窗 72h→30m
        "net_line_steps": +3,
        "abs_path_steps": 5,             // 沿途總移動量（含來回）
        "max_excursion_steps": +4,       // 距起點最大偏離
        "reverted": true,                // 頭尾回歸（暴走後收回）
        "direction_changes": 2,          // 線方向改變次數
        "late_swing": false,             // 末段(1h→30m)是否大幅突變
        "fav_swap_count": 1,"fav_final":"home",
        "home_odd_net":"down","away_odd_net":"up",
        "shape": "spike_revert",         // 中性形狀枚舉（系統，非動機）
        "tag": "升三盤·水互換·主賠降客賠升"   // 客觀結構化中文標籤（系統生成）
      }
    },
    "over_under": { ...同結構，over/under 取代 home/away... }
  },
  "singbet": { ...同結構... }
}
```
> 客觀記錄一律 **home/away（讓分）、over/under（大小）固定視角**；「我方/對方」由 selector/GEMINI 依 pick 邊**重新定向**（fact 層保持中立）。`closing` 不進 segments/summary 的決策統計，僅供另算「30m→closing 末段變化」與 CLV。

---

## 3.（Q2）各維度客觀判定

### 升降幾級 line_steps
`steps = round((new_line − old_line) / 0.25)`，帶號。例：讓分 0→0.5＝+2 級；大小 3.0→2.25＝−3 級。客觀、確定性。

### 賠率方向 odds_dir
`delta = new_odd − old_odd`；`|delta| ≤ ODDS_FLAT_EPS（待校準, 預設 0.02）` → `flat`，否則 up/down。我方/對方兩邊各記。

### 水互換 fav_swap
每錨點 `favorite = 低水方`（賠率較低那邊；差距 ≤ `FAV_EPS` 預設 0.02 視為無明顯偏好 `even`）。某段 `fav_swap = (fav_to ≠ fav_from 且兩者皆非 even)`。**只看低水方換邊，與線升降無關**（符合總司令定義）。

### 軌跡形狀 shape（不寫死、特徵驅動、可擴充）
先算**客觀特徵**（net_line_steps / abs_path_steps / max_excursion / reverted / direction_changes / late_swing / fav_swap_count），再用規則派生中性形狀名：
| shape | 規則（門檻待校準）|
|---|---|
| `flat` | net≈0 且 abs_path≈0 |
| `monotonic` | 所有段同向、direction_changes=0、net 顯著 |
| `gradual` | 同向但每段小幅 |
| `spike_revert` | max_excursion 大但 reverted=true（頭尾回歸） |
| `late_swing` | 末段(1h→30m)位移佔比高 |
| `choppy` | direction_changes≥2 且 net 小 |
> **形狀名中性、描述性**（不叫「洗盤」）。動機解讀（洗盤/誘散戶/消息走漏）留給 GEMINI。**原始特徵一律存**，回測可自訂任意條件分桶，不受這幾個命名限制。

---

## 4.（Q3）進 backtest — 軌跡 → 真實過盤率

- **選注時凍結**：selector 產生 pick 時，把「該 book × 該 market × 依 pick 邊重定向後的決策窗 trajectory summary（含 shape/tag/特徵）」附到推薦記錄。
- backtest 既有 `result/pnl/clv` 之外，`compute_metrics` 新增 **by_trajectory 分組**：
  ```
  by_shape: { spike_revert:{n, hit_rate, roi, avg_clv}, monotonic:{...}, ... }
  by_feature: { "net_steps>=+3":{...}, "fav_swap":{...}, "late_swing":{...}, "升三盤水互換":{...} }
  ```
- 因原始特徵都存，可離線跑「任意軌跡條件 → 命中率/ROI/CLV」統計，回答「某種軌跡→真實過盤率」。
- **跨 book 比較**（CROWN 目標）：同一 fixture 兩家 trajectory 都存，回測可比「pinnacle 訊號 vs singbet 訊號 哪個命中率高 / 哪個 sharp」。

---

## 5.（Q4）系統客觀 vs GEMINI 推論 界線

| 層 | 產出 | 性質 |
|---|---|---|
| **系統（事實）** | 八錨點數值、各段四維 delta、fav_swap、形狀特徵、中性 shape 名、結構化 tag（「升三盤·水互換·主賠降客賠升」）| 數學算出、確定性、可回測、**無意圖解讀** |
| **GEMINI（推論 🤖）** | 讀上述 + 原始數據，推論**意圖/心理**（「spike_revert+水互換 疑似莊家洗盤誘散戶」「30m 突變疑似消息走漏/後場 sharp 錢」）、信心敘述 | 主觀、標 🤖、**不參與選注決策** |
| **總司令** | 系統數據 + GEMINI 推論 + 自身判斷 | 最後拍板 |

界線原則：**「盤口怎麼動」＝系統；「為何動/代表什麼」＝GEMINI**。shape 名保持中性（`spike_revert`），動機詞（洗盤）只在 GEMINI。

---

## 6.（Q5）schema 改動範圍 / 重抓 / 頻率

- **改動**：movement 記錄由「扁平 6 錨點」→「`schema_version:2` + 八錨點 + `trajectory{book{market{...}}}`」。`selector.line_movement_signal` 整段移除，改讀 trajectory summary（confirm/reverse/flat 由「我方邊重定向後的 net 方向 + 賠率位移」綜合得出，天然含賠率維度）。
- **重抓**：**需要**。historical 免費 → 重跑一次 scan 重生全部記錄（prod 現有 72 場）。加 `schema_version` 偵測舊檔。
- **抓取頻率/節流**：
  - 錨點/軌跡皆由**單次 historical 全序列**離線切出 → 多 2 個錨點**不增加呼叫**。
  - **雙 book（pinnacle+singbet）= 每場 2 次 historical 拉取** → 呼叫量 ×2；維持 8s 節流，首輪 ~72×2≈19 分（可接受，初盤抓一次後穩態僅近窗少數）。
  - **關鍵洞察**：賽後一次 settle 拉取＝拿到完整序列 → **八錨點（含 t30m/closing）可精準重建**。故 cron 頻率只影響「賽前決策的即時新鮮度」（t30m 決策值在 T-30m 後有拉取才精準），**不影響回測準確度**（settle 拉取後全部精準）。
  - 建議：維持每小時；近開賽可選擇性加密以提升 t30m 決策新鮮度（待定，非必要）。

---

## 7. CROWN 雙記 schema（多家盤口）—— 一開始就設計，免日後遷移

- `trajectory` **第一層即 bookmaker key**（`pinnacle`/`singbet`/未來可加）。**加新 book = 加 key，零 schema 遷移。**
- movement.scan 對每場拉 **pinnacle + singbet 各一次** historical，各自建 trajectory；singbet 缺場（目前 47/72）→ 該 book 該場 trajectory 標缺/部分 null，不影響 pinnacle。
- selector 用哪家當公允錨＝config 可選（CROWN 切換 = 改 config，不改 schema）。
- backtest 跨 book 比命中率 → 決定誰 sharp。
- **結論：是，現在就設計成多家**。成本：雙拉取（免費）+ 首輪時間翻倍；效益：避免日後 schema 大改 + 直接支援 CROWN 比較。

---

## 8. 待校準門檻清單（全標「待回測校準」）
`ODDS_FLAT_EPS(0.02)`、`FAV_EPS(0.02)`、shape 各規則門檻（spike_revert 的 excursion 大小、late_swing 末段佔比、choppy 的 direction_changes 與 net 界線）、賠率位移計 confirm/reverse 的最小機率位移。

---

## 9. 取代與相依
- **取代**：`selector.line_movement_signal`（線-only、線不動即 flat）→ 由 trajectory summary 取代（含賠率/水互換維度）。selector 的 `_filter_and_stake` 改讀新 summary 取 confirm/reverse。
- **不動**：edge 計算（de-vig vs 1xBet）、誘盤過濾其餘項、注碼框架；只換「訊號」來源。

---

## 10. 先記著、這份不做、之後依序
1. **titan007 Spike**（軌跡分類做完後）：0.5–1 天爬 1 場 2022 WC 驗證 go/no-go。
2. **analyzer #3**（Gemini 開盤手人設）：排最後，等軌跡分類定稿才知餵什麼給 Gemini。
3. **上半場盤口**：未來擴充。

---

## 提案自檢對照（你要的 5 問 + CROWN）
1. 資料結構：§2（schema/枚舉/掛法）✅ 2. 客觀判定：§3（級/水互換/形狀）✅
3. 進 backtest：§4（by_trajectory + 跨 book）✅ 4. 系統/AI 界線：§5 ✅
5. schema 範圍/重抓/頻率：§6 ✅ CROWN 雙記：§7（現在就多家、免遷移）✅
