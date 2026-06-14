# on_demand_proposal.md — 轉向「movement 廣掃 + 每日篩選 + 按需刷新」提案

> 狀態：**已拍板轉向（總司令 2026-06-14）**，待 Germany 16:30 UTC event 驗證 keystone 確認 + 六月第二把 key 決策後施工。
> 自包含原則：本檔複製所需契約，不依賴他檔。對應記憶中樞：`CLAUDE.md` §5、`小g小c協作簡報.md`。

---

## 0. 動機

總司令實際只玩 1–2 場/天。原 main_pipeline 每小時全掃 104 場 → select 每輪 2 計額度 × 24 = 48/天，
免費層 250/月扛不住（已實證約 6/15 撞牆，已先降每 3h→6h 止血）。要的形狀：
1. 每天固定一次全抓 → 候選清單（看哪些場有 edge）。
2. 挑中的場按需刷新到臨場新鮮盤（不每場都玩）。

## 1. 🔑 改寫問題的關鍵事實：額度按「呼叫次數」算，不是「場數」

- `odds-by-tournaments`（算 edge 的現價盤）**一次呼叫回全部 104 場** → 掃 1 場 vs 104 場**花一樣的 2 計額度**（pinnacle + 1xbet）。
- `historical-odds`（走勢/八錨點）**幾乎免費**（§8 假設，本 session 實證：event tick 掃 12 場 movement，request_count 只 +1 且那 +1 是 fixtures 快取）。
- ⇒ 燒額度的根因是 **select 一天被呼叫幾次**，不是掃幾場。
- ⇒ 「按需刷新某場」**不需要單場邏輯**：按一次「現在刷新」= 跑一次 select（2 額度）= 整盤含你那場都更新。**按鈕不必填 fixtureId**。

## 2. 提案形狀（三層分離，各用對的頻率）

| 層 | 角色 | 頻率 | 額度 |
|---|---|---|---|
| **movement 廣掃** | 全部活躍場走勢圖/八錨點（公開頁全局） | 可頻繁（免費）；**六月先省略、靠每日篩選那次的 movement** | ~0 |
| **每日篩選（1 次全 select）** | 候選清單（哪些場有 edge），**僅方向參考、會過時** | 每天 1 次 `cron 0 1 * * *`（UTC）= 台灣 09:00 | 2/天 |
| **按需刷新按鈕** | 選中場下注前臨場拿真數字 | workflow_dispatch 手動，玩才按 | 2/按 |

- **每日篩選只當候選清單**：實證 pinnacle 6h 內 4 場有 2 場跳整整 1 線級(0.25)+賠率漂 0.09–0.15；edge 門檻就是 0.25 → 早上的 edge 晚上會過時。**下注前一定按鈕臨場刷**。
- 第二期（想省心再加）：watchlist 檔列 1–2 場 + cron 在那些場 t30m 自動刷（重用 event_pipeline plumbing）。

## 3. 驗證取捨 → (a)：先確認機制、再改策略

新版重用 event_pipeline 同一套底層（tick_state / anchor_targets / plan_tick t30m 判定 / catch-up / P1 rebase），
只改「select 何時觸發」策略。先確認底層對、改完出 bug 才分得清是機制還是新策略。
- **keystone = Germany-Curaçao t30m（16:30 UTC）那輪**：確認 `select_due=1` / 該場 `select_done=True` / quota +2。
- **確認那輪即可轉，不跑滿驗證日**（省 ~12 額度）。catch-up 真實漏觸率「待全小組賽」（不為它多燒一天）。

## 4. 轉向/安全網/回退

| 元件 | 轉向後 | 做法 | 回退 |
|---|---|---|---|
| main_pipeline | **= 每日篩選** | cron `0 */6 * * *`→`0 1 * * *`；movement+select+backtest 步驟不動 | cron 改回 `0 */6 * * *` 一行 |
| event_pipeline | 退回 dispatch-only | 重新註解 `*/30` | 一行解開 |
| 「現在刷新」按鈕 | 新增 | 小 workflow（dispatch，movement+select）或重用 event 手動觸發 | 不掛 cron、零影響 |
| movement 廣掃 | 看需求 | 六月省略；要全局走勢新鮮再加 movement-only cron（免費） | — |

movement/selector/storage/trajectory 全程不動，純排程層切換。

## 5. 🔴 六月逐日額度實算（誠實版）

當前 6/14 = **187 用 / 剩 63**。**新形狀救不了六月**（187 已燒掉，大半是每小時全掃 + 查證/驗證），救的是七月起永續。

最省跑（六月austerity：砍 backtest、每日篩選 1 次、臨場才按；篩選2+fixtures1=3/不玩日，玩球日+按需）：

| 日期 | 情境 | 耗 | 剩 |
|---|---|---|---|
| 6/14 餘 | 驗證收尾+轉向 | ~7 | ~56 |
| 6/15 | 玩1場(刷2次=4) | 3+4=7 | 49 |
| 6/16 | 不玩 | 3 | 46 |
| 6/17 | 玩1場 | 7 | 39 |
| 6/18 | 不玩 | 3 | 36 |
| 6/19 | 玩1場 | 7 | 29 |
| 6/20 | 不玩 | 3 | 26 |
| 6/21 | 玩1場 | 7 | 19 |
| 6/22 | 不玩 | 3 | 16 |
| 6/23 | 玩1場 | 7 | 9 |
| 6/24 | 不玩 | 3 | 6 |
| 6/25 | 玩1場 | 7 | **斷糧** |

**結論**：最省跑 + 每隔天玩 1 場，約撐到 **6/24–25**。要真撐到月底（若 7/1 重置）需 <3.7/天，等於幾乎不按需（拿過時 edge 下注，不現實）。
**七月**：滿 250、~5/天玩 → 月用 ~150，單把 key 穩。

## 6. 🔴 Billing 週期 — API 查不到，且有警訊（總司令需自查）

實打 `/v4/account` 全欄位：有 `request_limit:250`、`request_count:187`、`plan:free`，**但無任何 reset/period/cycle 欄位** → 無法由 API 確認重置時點。
- `subscription.valid_from: 2026-06-03`、`valid_until: null`、`auto_renew: false`、`created_at: 2026-06-03`。
- ⚠️ **警訊**：`auto_renew=false` + `valid_until=null` → **不排除「免費 250 是一次性配額、不每月重置」**。若如此，則「等七月」前提不成立、63 是剩下的全部。
- **總司令自查**：登入 OddsPapi 官網 → Subscription/Billing/Usage 頁，找「resets on / renewal / billing period」；或問官方 support 確認「免費 250 是每月循環還是一次性、幾號重置」。**這決定七月幾號有額度、也決定要不要第二把 key。**

## 7. 第二把免費 key / 多帳號 — ToS 風險（總司令自查條款）

- 我未掌握 OddsPapi ToS 全文。**一般經驗**：多開免費帳號規避用量限制，是多數 API 商明文禁止的（「one account」「no circumventing limits」「fair use」），違者常**連坐封所有關聯帳號**（共用 email/IP/裝置指紋）。
- **總司令自查**：OddsPapi 官網 footer 的 Terms of Service，找 multiple accounts / circumvent / fair use 條款。
- 我**不協助**設第二帳號規避限制（屬規避行為）。較安全路徑：① 升付費；② 認賠六月斷幾天、只靠每日篩選清單；③ 問 support 能否臨時加額。

## 8. 待施工檔案清單（拍板施工時）

1. `main_pipeline.yml`：cron → `0 1 * * *`；（六月可選）暫移除 backtest step。
2. `event_pipeline.yml`：重新註解 `*/30`（退 dispatch-only）。
3. 新增 `refresh_now.yml`（或重用 event 手動）：workflow_dispatch，movement+select，不填參數、刷全盤。
   - 🔴 **必須連帶觸發 gh_pages 重建**，否則按鈕抓到新盤但公開頁仍舊數字＝白按。做法：把 refresh_now 加進 `gh_pages.yml` 的 `workflow_run.workflows` 清單（與 main_pipeline 並列），或 refresh_now 自己 build+deploy site。**每日篩選（main_pipeline）已會觸發 gh_pages，按鈕也要比照。**
4. （第二期）watchlist 檔 + scheduler 過濾。
5. 同步 `CLAUDE.md` §5/§9 + 協作簡報。

## 10. 驗證發現（2026-06-14 event 真實環境，Germany keystone）

- **機制 PASS**：run #5（16:58 UTC）`select_due=1` → select 跑、picks 3/觀察 2；tick_state Germany `select_done=True`、captured 含 t30m；movement t30m 錨點 pinnacle **offset_sec=-11s**（series 取點近乎正中 16:30 目標），singbet +316s。t30m 觸發 + select_done 去重 + catch-up 取點 全對。
- **Germany observation→pick**：早上篩選 edge 不足→觀察場；t30m 線移動（pinnacle 日內 -3.25→-3.75）edge 出現→**變 pick**。**證明「早上候選清單會變、下注前必須 t30m 再刷」是對的**（提案核心假設成立）。
- 🔴 **cron 不可靠（公開 repo、非額度問題）**：`*/30` 實際只在 07:53/10:51/13:01/15:26/16:58 跑（~每 2–2.5h，非 30 分）。**public repo Actions 分鐘無限**，throttle 是 GitHub schedule 觸發本質的 best-effort 延遲/丟棄。Germany select 落在 [16:30,17:00) **靠 #5 剛好 16:58（離 kickoff 僅 2 分）撞上**＝運氣。→ **靠 cron 命中 30 分 t30m 窗 來出 pick 不可靠**；走勢/錨點靠 historical catch-up 沒事（offset 證明），但 **pick（用即時盤、只在 [t30m,kickoff) 觸發）會漏**。**這強化轉向結論**：on-demand 按鈕（dispatch 立即觸發、你控制時點）才能保證打到你要那場的 t30m pick。
- 🐛 **observation→pick 殘留 bug**：fixture 由觀察場升為 pick 時，舊 observation 條目沒被移除 → Germany 同時在 `recommendations`(pick) 與 `observations`(舊 edge_below_threshold+api_error)。公開頁會重複顯示、且殘留舊 api_error。**轉向施工時要處理**：select 升 pick 時刪該場 observation 條目，或 web_builder 顯示層「在 recommendations 的場不再列 observation」。
- **閒輪 0 API ✓**：#5 `fixtures_refetched=False`（快取命中）；select_due=0 的輪只走 historical（免費）。
- **private repo 分鐘 ✓ 無慮**：repo 為 public，Actions 免費無限。

## 9. 待總司令決策（施工前）

- [ ] Germany 16:30 UTC keystone 驗證確認 → 當晚轉。
- [ ] Billing 週期自查結果（§6）。
- [ ] 第二把 key vs 認賠斷糧（§7，待 §6 結果）。
