# 架構 A 修訂提案 — 改用 OddsPapi 主源 + historical 走勢

> 狀態：**待施工**（總司令 2026-06-04 選定 A，並追加六錨點與三條規則）。本檔為動工前的完整範圍提案，經總司令過目核准後才改程式與規格書。
> 關聯存證：[oddspapi_findings.md](./oddspapi_findings.md)

---

## 0. 前提聲明（推翻兩條 🔒 決策，已由總司令解禁）
- **🔒#5**「API-Football 免費層為主源」→ 改為 **OddsPapi v4 免費層為主源**（API-Football 免費層拿不到 2026 賽季，已實證）。
- **🔒#6**「BALLDONTLIE 備援交叉驗證」→ **作廢**（BDL 無世界盃）。交叉驗證改為 **OddsPapi 內 Pinnacle vs 1xBet** 對盤。
- 解禁時點：總司令 2026-06-04。CLAUDE.md 決策表須標注此修訂。

---

## 1. 模組層級變更

| 模組 | 處置 | 說明 |
|---|---|---|
| `api_client.py`（API-Football）| **封存** `git mv` → `soccer_ai/_legacy/api_football_client.py` | 保留歷史可退回，不進主流程 |
| `snapshot.py`（三窗口）| **封存** `git mv` → `soccer_ai/_legacy/snapshot_threewindow.py` | 安全處置，一行不刪 |
| `odds_parser.py`（API-Football 盤口）| **封存** → `_legacy/odds_parser_apifootball.py`，另寫新版 | OddsPapi 盤口結構不同 |
| `bdl_client.py` | **停用/封存** | BDL 無世界盃 |
| `oddspapi_client.py` | **新增** | v4 抓取：fixtures / historical-odds / odds-by-tournaments / account / settlement，含 429 退避重試 + isinstance |
| `odds_parser.py` | **改寫** | 解析 historical 序列與 odds-by-tournaments，對照 `/markets` 切 Asian Handicap / Over-Under，型別固定 |
| `movement.py` | **新增（取代 snapshot 角色）** | 抓 historical 序列 → 推導六錨點 |
| `config.py` | **改常數、留機制** | 金鑰讀取/UTC+8/TEST_MODE 機制不動；換 league/market/bookmaker/rate 常數 |
| `storage.py` | **改 schema、留機制** | 原子寫入不動；快照記錄改六錨點結構 |
| `main.py` | **小改** | 失敗分流/`--test` 不動；改呼叫 movement，移除生存法則分支 |
| `main_pipeline.yml` | **改排程** | `*/15` → 低頻；移除生存法則 env；commit&push 機制保留 |
| `backtest.py`（Phase 2 未建）| **依新源設計** | settlement 取賽果 + historical 收盤算 CLV |

> `_legacy/` 不被 main 匯入、不進排程，純存證。封存一律 `git mv`（保 blame 與歷史），不 `rm`。

---

## 2. `snapshot.py` 拆解方案

**舊核心** `process_fixture()`：算 ttk → 判 mid/closing 時間窗 → 生存法則鉤子 → 收盤缺失標記 → 每 15 分搶抓。

**拆法**：整檔 `git mv` 到 `_legacy/snapshot_threewindow.py`（可退回）。職責改置：

| 舊職責 | 新去處 |
|---|---|
| 三時間窗判定（mid/closing ttk）| **移除** —— 不再搶窗 |
| 生存法則（剩餘≤15 只抓收盤）| **移除** —— historical 不計數、額度非瓶頸 |
| 收盤缺失標記 | **改義** → `movement` 判定「序列最後點是否在開賽前」 |
| 「窗口內未抓才補抓」狀態機 | **改義** → `movement` 判定「fixture 是否已開盤(非404)、是否已落地最終序列」 |
| 抓盤動作 | → `oddspapi_client.get_historical_odds()` |

**新 `movement.py` 職責**：
1. `pull_movement(fixtureId, bookmaker)` → 抓 historical 序列（不計額度）。
2. `derive_anchors(series, kickoff)` → 從序列切出六錨點（規則見 §3.2）。
3. `scan()` → 對「已開盤、未落地最終序列」的 fixture 拉取、推導、入庫；已開賽者補抓定版收盤。

---

## 3. 資料結構 / 儲存 — 六錨點（不存降採樣完整序列）

- **主鍵**：整數 `fixture_id` → **字串 `fixtureId`**（如 `id1000001666456904`）。
- **每場只存六個錨點**（總司令 2026-06-04 定）：**初盤、賽前24h、賽前12h、賽前6h、賽前1h、收盤**。
  - **不存原始逐筆序列、不存降採樣序列**。原始序列（≈5MB/場）需要時即時重抓（免費）。
- **快照記錄新 schema（草案）**：
  ```json
  {"fixtureId":"id...", "tournamentId":16, "sportId":10,
   "home":"Mexico","away":"South Africa",
   "kickoff_utc":"...","kickoff_local":"...",
   "bookmaker":"pinnacle",
   "anchors":{
     "initial": {"captured_ts":"ISO", "handicap":{...}|null, "over_under":{...}|null},
     "t24h":    {"target_ts":"ISO","captured_ts":"ISO","offset_sec":int,"handicap":...,"over_under":...} | null,
     "t12h":    { ... } | null,
     "t6h":     { ... } | null,
     "t1h":     { ... } | null,
     "closing": {"captured_ts":"ISO","handicap":{...}|null,"over_under":{...}|null}
   },
   "closing_settled":bool, "pulled_at_local":"ISO"}
  ```
  - `initial` 與 `closing` 由位置定義，不需 `target_ts`；`t24h/t12h/t6h/t1h` 為目標時刻錨點，須存 `target_ts`+`captured_ts`+`offset_sec`。
- **可改 schema 的依據**：`data/prod/` 目前只有 `.gitkeep`，無真實資料，故現在改 schema **不違反絕對不動清單**（該清單保護「已上線」格式）。

---

## 3.2 規格書 §3.2 寫死的錨點規則（取代舊「三窗口 + 生存法則」整段）

**六錨點**：初盤(initial)、賽前24h(t24h)、賽前12h(t12h)、賽前6h(t6h)、賽前1h(t1h)、收盤(closing)。
四個「賽前 Nh」錨點的目標時刻 = `kickoff − Nh`。

**規則 1（最接近 + 存實際時間戳）**：每個錨點取「序列中**時間戳最接近目標時刻**的那一筆」，**不是**找正好整點的值。每個錨點連同**它的實際時間戳**（及與目標的 `offset_sec`）一起存，回測算 CLV 時看得到誤差。

**規則 2（收盤 ≠ 賽前1h）**：收盤 = **開賽前序列的最後一筆**（沿用 §3.6 定義），與「賽前1h」是**不同的點**，不得混為一談。兩者各自獨立存。

**規則 3（缺失標 null，不硬塞）**：某錨點在序列裡不存在時，該錨點標 **null/缺失**，**不得**硬塞最接近的點假裝有。
> 判定「不存在」＝目標時刻落在序列觀測區間 `[最早, 最新]` **之外**：
> ①早於序列首筆（盤開得晚，無此時段資料）；②晚於序列最新筆（時間還沒到，未來尚未發生）。
> 目標時刻落在區間**內** → 必有最近點 → 取之（規則 1）。

**初盤定義**：序列**第一筆** = 莊家首次開盤價（沿用）。

---

## 3.2b 抓取範圍與節流（2026-06-04 fix；併入規格書 §3.2）

實機跑 movement 對 104 場連打 historical（5.7MB）撞 429 卡死，追加三條：

**節流退避（fix1；2026-06-04 雲端調校）**：
- 每次請求間「基礎間隔」`MIN_REQUEST_INTERVAL_SEC = 8.0s`（不只 429 後才等）。
- 429 指數退避 `BACKOFF_SCHEDULE = [3.0, 6.0, 12.0]`，取 `max(排程, Retry-After)`；超過即 `raise RateLimited` → 該場標「抓取失敗」跳過，**不中斷整批**（部分失敗分流）。
- OddsPapi 文件 rate limit：odds 端點 10 req/s；其他端點（含 historical）200 req/分。**但 5.7MB 大回應在 GitHub Actions 共用 IP 被限更嚴**：本機 3s 零 429；雲端 3s 每場先撞一次（靠重試成功、約 6s/場、不卡死）。故基礎間隔拉長至 **8s** 讓雲端多數呼叫第一次就過。
- 實機驗證紀錄：commit 24d18ab 的 run 在 3s 下穩定前進（~24 場/2.5 分、零失敗），被手動取消而非失敗；取消發生在 scan 完成前，故 commit&push 未執行、runner 本地檔銷毀。→ 結論「會跑完只是慢」→ 拉長間隔。

**按距開賽時間篩選（fix2）**：
- 初盤：每場開盤後抓一次存起來，之後不重抓（遠期 `ttk > 48h` 且初盤已存 → 跳過）。
- 其餘五錨點（24h/12h/6h/1h/收盤）：只對 `ttk ≤ FORWARD_WINDOW(48h)` 的場次抓。
- 賽後 `SETTLE_GRACE(3h)` 內允許一次「收盤定版」拉取（取真實收盤＝開賽前最後一筆），之後 `closing_settled=true` 不再抓；超過 grace 仍未抓到 → 視窗外不再抓。

**用隊名 placeholder 判斷已開盤（fix3，修正案）**：
- ⚠️ 實測 **`hasOdds` 對 104 場全為 true（含 placeholder），不可用**。改用**隊名**判斷：
  placeholder＝`W\d+`/`RU\d+`/`L\d+`/組位 `1A`/第三名組合含 `/`；真實全大寫隊名（如 `USA`）不含數字/斜線，不誤判。
- placeholder（隊伍未定）→ 直接跳過，**連 historical 都不打**（省掉 ~32 場的 404）。
- 隨小組賽打完、淘汰賽對戰確定，隊名變真實 → 下次跑自動納入。
- **效果**：常態只有 72 場小組賽抓初盤（且各一次）；淘汰賽 32 場晉級確定後陸續加入；真正密集抓的只有臨近 48h 的 2–4 場 → 429 自然解決。

---

## 4. 排程 / CI 變更

- **Cron**：`*/15 * * * *` → 提案 **每小時** `0 * * * *`（賽前驅動推薦 + 賽後補收盤皆夠；historical 免費故可頻繁）。最終頻率待總司令定。
- **移除**：生存法則相關 env、收盤窗搶抓邏輯。
- **保留不動**：跑完 `git commit & push` 回 repo、`permissions: contents:write`、concurrency。
- **額度監控**：改用 `/v4/account` 的 `request_count`（不計數、可免費輪詢），取代 API-Football 回應標頭。

---

## 5. 規格書 v2.0 逐章修訂清單

| 章節 | 動作 |
|---|---|
| §1.1 目錄結構 | 加 `oddspapi_client.py`/`movement.py`/`_legacy/`；標封存 |
| §1.2 防線 | 刪「生存法則」「收盤窗搶抓」；加 OddsPapi 429 退避、六錨點、不存原始序列 |
| §2 Mermaid | **重畫**：移除 15分窗口掃描+生存分支；改 historical 拉取 → 推導六錨點 → settlement 回測 |
| §3.1 主鍵 | `fixture_id`(int) → `fixtureId`(str) |
| **§3.2 快照** | **整段重寫**為上方「六錨點 + 三條規則」 |
| §3.3 API 契約 | **整塊換掉**：base `api.oddspapi.io/v4`、`?apiKey=`、sportId 10、tournamentId 16、市場名 `Asian Handicap`/`Over Under Full Time`、bookmaker slug `pinnacle`/`1xbet`、250/月、request_count 監控 |
| §3.5 選注/AI | edge 0.25、字數預算 **不動**；盤口輸入結構描述改 |
| §3.6 CLV | **自算（v4 無 /clv，總司令 2026-06-04 定）**：CLV =（收盤錨點的線）對比（推薦產出時記錄的線）；收盤錨點沿用六錨點的「收盤」（序列開賽前最後一筆）；時序防呆：推薦產出時間 ≥ 收盤抓取時間 → 該筆標「無 CLV」 |
| §4 Phase 計畫 | 重排（見 §9）；Phase 4 BDL → 改「Pinnacle vs 1xBet 對盤」 |

---

## 6. CLAUDE.md 修訂
- §二 決策表 #5/#6 標「v2.0 修訂、總司令 2026-06-04 解禁」。
- §五（API 契約）**重新回填** OddsPapi 契約 + 六錨點規則。
- §八 事件學習庫 **新增一筆**（見 §8-B）。
- §十 絕對不動清單：加註「快照 schema 在 prod 上線前可改」。
- 同步 `小g小c協作簡報.md`。

---

## 7. 保留不動清單（這次不碰）
- `config.py` 金鑰讀取機制、UTC+8 helper、TEST_MODE 隔離
- `storage.py` 原子寫入（tmp→replace）
- `main.py` 失敗分流雙軌、`--test`
- `.gitignore` / `.gitattributes` / `data/{prod,test}` 隔離
- Actions 的 commit&push-back 機制
- 行尾鐵律、每 Phase 獨立 commit

---

## 8. 施工特別指令（總司令 2026-06-04）

**A. `/clv` 與 `/settlement` 的 v4 路徑驗證（施工第一步）—— 已完成（2026-06-04 實打）**：
- **`/v4/settlements?fixtureId=…` ✅ 存在**（HTTP 200，回 `{fixtureId, markets:{<marketId>:{outcomes:{<outcomeId>:{players:{0:{result}}}}}}}`；未開打場次 result=`UNDECIDED`）。Phase 2 賽果回填照用。
- **`/clv` ❌ v4 無此端點**（7 候選路徑全回 404 `The requested endpoint does not exist`）。
- 裁示：**CLV 自算**（見 §3.6 / §5），不用原生端點。settlement 用 `/v4/settlements` 按 market/outcome 取 result。

**B. CLAUDE.md 事件庫須記一筆**：
```
事件：依賴 OddsPapi historical-odds「不計入 250/月額度」之觀察
性質：此為實測觀察，未經 OddsPapi 官方確認，可能是免費層設計／隱藏限制／計費 bug。
影響：架構 A 將 historical-odds 當主力抓取手段並假設其不耗額度。
退場條件：若此假設失效（historical 開始計數或被限制），須退回以
         odds-by-tournaments（批量現況盤，會計數）為主，並重排額度模型。
教訓：把未確認的有利觀察當架構支柱時，務必明列假設與退場路徑，勿寫成不可動鐵律。
```

---

## 9. 建議施工順序（核准後，每步獨立 commit）
1. **封存舊模組（`git mv`）+ 實打驗證 `/clv`、`/settlement` v4 路徑**（無此端點則停工回報，指令 A）
2. `config.py` 換常數 + `oddspapi_client.py` 新增
3. `odds_parser.py` 改寫 + `movement.py` 新增（六錨點 + 三規則）
4. `storage.py` 新 schema + `main.py`/`yml` 接線、移除生存法則
5. 回填 CLAUDE.md（含事件庫 B）/規格書 §3.2 等/協作簡報

---

## 10. 風險 / 待確認
1. **historical 不計數** — 未經官方確認；見指令 B 的退場條件。建議總司令寄信 OddsPapi 確認。
2. **`/clv`、`/settlement` v4 路徑** — 見指令 A，施工第一步驗。
3. **429 節流** — heavy 端點需間隔+重試。
