# OddsPapi 實測事實存證（2026-06-04）

> 全程以真實 API 呼叫驗證（非看文件），免費層帳號。撰寫者：小cc。
> ⚠️ 本檔僅為事實存證，**尚未**成為規格契約；架構方向（A/B/C）待總司令裁示後才動 `snapshot.py` 與規格書。
> 🔒 金鑰不入檔。本機測試用 key 僅暫存，正式接入時寫進 `.env` 的 `ODDSPAPI_API_KEY=`（gitignored）。

---

## 0. 連線基礎

| 項目 | 值 |
|---|---|
| Base URL | `https://api.oddspapi.io/v4` |
| 認證 | query param `?apiKey=<KEY>`（亦接受 `x-api-key` header） |
| 錯誤格式 | `{"error":<code>,"message":...,"code":...}` 或 `{"error":{"message":...,"code":...}}` |
| 文件 | docs.oddspapi.io（機器可讀：`/llms-full.txt`）。**注意**：docs 寫的 `v5.oddspapi.io/en/...` 與實際可用的 `api.oddspapi.io/v4` 不同，以 v4 為準 |

> 踩雷紀錄：最初照 docs 打 `v5.oddspapi.io/en/...` 一直回 `invalid apiKey`，誤判成 key 沒啟用。實際是 **base URL / 路徑錯**，正確為 `api.oddspapi.io/v4`。教訓：API base 以「實打 200」為準，不盲信 docs。

---

## 1. 帳號 / 方案（`/v4/account`）

```
plan: free | price: null | is_active: true | auto_renew: false
request_limit: 250 | request_count: <即時計數器>
websocket_access: 0
sport_ids: [10..68]（含 soccer=10 等 60+ 運動）
subscriptions[0].bookmakers: 388 家（含 pinnacle / 1xbet / bet365）
  但免費層每家 has_live_odds=false, has_player_props=false
```

- **免費層無 in-play（live）即時盤、無 player props、無 websocket**。
- 我們是**賽前**策略，要 pre-match 盤 + 歷史走勢，**不需要 live**，故此限制無傷。

---

## 2. 賽事覆蓋（`/v4/sports`, `/v4/tournaments`, `/v4/fixtures`）

| 項目 | 結果 |
|---|---|
| Soccer | `sportId=10`（slug `soccer`） |
| **2026 世界盃** | `tournamentId=16`，name `World Cup`，categorySlug `international` |
| 賽事數 | **104 場**（48 隊新制），`futureFixtures=104` |
| hasOdds | **104/104 = true** |
| 首戰 | `id1000001666456904` Mexico vs South Africa `2026-06-11T19:00:00Z` |
| 決賽 | `id1000001653452537` W101 vs W102 `2026-07-19T19:00:00Z`（隊伍未定，尚未開盤 → historical 回 404） |

> 注意：別誤抓其他 World Cup（資格賽 13/14/308…、Women 290、U17/U20、Virtual、SRL 模擬）。**正盤是 tournamentId 16**。
> fixture 主鍵為字串 `fixtureId`（如 `id1000001666456904`），非整數 —— 與 API-Football 的整數 fixture_id 不同，接入時資料結構要改。

fixture 重要欄位：`fixtureId, participant1Id/Name, participant2Id/Name, sportId, tournamentId, seasonId, statusId, statusName(Pre-Game), hasOdds, startTime(UTC ISO), trueStartTime/trueEndTime, externalProviders(含 pinnacleId)`。

---

## 3. 市場與盤口（`/v4/markets?sportId=10`, `/v4/odds-by-tournaments`）

- **市場類型確認存在**：
  - **`Asian Handicap`**（亞洲讓分）— marketId 1024 起，**每條讓分線一個 marketId**，帶 `handicap` 線值與 `period`。
  - **`Over Under Full Time`**（大小球）— marketId 106/108/1010 起，同樣每條線一個 id。
- soccer 市場總數 32,814（含各週期/各線，極細）。market 物件欄位：`marketId, marketName, handicap, period, marketType, playerProp, outcomes`。
- **批量現況盤**：`GET /v4/odds-by-tournaments?bookmaker=<slug>&tournamentIds=16`
  - 一次回傳**整賽事所有場次**某一家 bookmaker 的當下盤口（非逐場）。pinnacle ≈2.5MB、1xbet ≈2.9MB。
  - 結構：`[{fixtureId, ..., bookmakerOdds:{<slug>:{bookmakerIsActive, suspended, markets:{<marketId>:{outcomes:{<outcomeId>:{players:{0:{price, priceAmerican, priceFractional, limit, mainLine, active, changedAt, bookmakerOutcomeId}}}}}}}}}]`
- **真實報價樣本**（開幕戰 pinnacle）：Asian Handicap `-2.0/home price=3.83`(+283) / `-2.0/away price=1.291`；Over/Under handicap=1.75、3.5 等。
- Pinnacle ✅、1xBet ✅（1xbet 首戰恰標 active=false，但盤口結構齊全）。

---

## 4. 歷史走勢（`/v4/historical-odds?fixtureId=<id>&bookmaker=<slug>`）★ 核心發現

**性質：賽前即時型 —— 莊家一開盤就即時累積走勢，賽前可查到「開盤 → 此刻」完整序列。不是賽後才有。**

鐵證（開幕戰，測試時今天 6/3、8 天後才開賽、statusName=Pre-Game）：
- 走勢 `2026-03-05` → `2026-06-03T19:24Z`（**距打 API 僅 6 分鐘**），**56,936 個時間點 / 62 市場**。
- 結構：`{fixtureId, bookmakers:{<slug>:{markets:{<marketId>:{outcomes:{<outcomeId>:{players:{0:[{createdAt, price, limit, active, exchangeMeta}, ...時間序列...]}}}}}}}}`
- 每個 outcome 是一串「逐筆改盤」的時間序列 → **初盤=序列最早點、收盤=最新/賽前最後點，皆可事後切出**。
- 前提：該場**已被莊家開盤**才有資料（決賽未開盤 → 404 `No historical odds found`）。

---

## 5. 額度計數模型（`request_count` 唯讀實測）

| 端點 | 計數 | 信心 |
|---|---|---|
| `/sports` | **+1 / 次** | 高（5 次→+5） |
| `/odds-by-tournaments` | **+1 / 次** | 高（2 次→+2） |
| `/historical-odds` | **不計數（+0）** | 高（3 次成功、含 +15s 觀察皆不動） |
| `/account` | **不計數** | 高（讀十餘次不影響計數） |
| 4xx / 429 | **不計數** | 中高 |

- 計數**秒級即時**，無明顯延遲/快取。
- 推論：計的是「成功的 metadata / 批量 odds REST 呼叫」（sports、tournaments、fixtures、markets、odds-by-tournaments，各 +1）；**historical-odds 與 account 不吃額度**。
- **節流**：heavy 端點（historical、odds-by-tournaments）間隔 2 秒仍易撞 **429**（per-second/burst 限制），實作須加間隔+重試。429 不耗額度。

### ⚠️ 下注前的保留
`historical-odds` 不計數「好到該跟官方確認」：可能是 (a) 免費層刻意、(b) 有隱藏獨立限制、(c) 計費 bug 會被修。**程式可承擔風險地依賴，但別寫成不可動鐵律**；建議寄信問官方或觀察數日。

---

## 6. 對既有架構（Phase 1）的衝擊摘要

| 既有（API-Football 思路） | OddsPapi 可行新思路 |
|---|---|
| 每 15 分 cron 輪詢搶三時間窗、怕漏收盤 | 對每場打 `historical-odds` 取完整序列，事後切初盤/收盤，零遺漏 |
| 額度逼近上限、生存法則複雜 | historical 不計數；odds-by-tournaments 一天個位數次；250/月幾乎不是問題 |
| `snapshot.py` 三窗口容錯為核心 | 三窗口邏輯可大幅簡化甚至移除 |
| 主鍵整數 `fixture_id`、bet id 4/5、bookmaker [4,8,41] | 主鍵字串 `fixtureId`、市場名 `Asian Handicap`/`Over Under Full Time`、bookmaker slug `pinnacle`/`1xbet` |

**待總司令裁示方向後**，再決定改寫 `api_client`/`odds_parser`、是否簡化 `snapshot`、以及規格書如何更新。本檔在此之前僅供存證與接規格參考。

---

## 7. 端點速查（已實打驗證存在）

```
GET /v4/sports?apiKey=                                   # 運動清單（計數）
GET /v4/tournaments?apiKey=&sportId=10                   # 賽事清單（計數）
GET /v4/fixtures?apiKey=&tournamentId=16                 # 某賽事所有場次（計數）
GET /v4/markets?apiKey=&sportId=10                       # 市場分類（計數）
GET /v4/odds-by-tournaments?apiKey=&bookmaker=pinnacle&tournamentIds=16   # 批量現況盤（計數）
GET /v4/historical-odds?apiKey=&fixtureId=<id>&bookmaker=pinnacle         # 賽前即時走勢（不計數）
GET /v4/account?apiKey=                                  # 帳號/額度監控（不計數）
GET /v4/historical-odds（無 fixtureId）→ 400 Missing fixtureId
GET /v4/<不存在> → 404 NOT_FOUND
```
