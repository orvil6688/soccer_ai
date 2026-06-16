# 小 g / 小 c 協作簡報 — 世界盃足球盤口分析系統（專案專屬版 v2.0-titan）

> ✅ **Phase 3 全完成：閉環 + 公開網頁全線**：OddsPapi v4、selector(純數學)→analyzer(🤖)→notifier(Discord)→web_builder(公開網頁 orvil6688.github.io/soccer_ai/) ／ backtest(含 derive_score 比分)、CROWN 雙記。存證 `docs/*_proposal.md` + oddspapi_findings/movement_trajectory/web_builder。
> 🔬 **titan007 全量 64 場完成**：OddsPapi 歷史拿不到 2022 → 改 titan007 凍結歷史補 2022 世界盃 64 場離線校準。全量 0 跳過/0 旗標（commit 5524c46）；`data/titan007_2022/` 64 檔、`site_titan007/` 本機頁（皆 gitignored）；by_trajectory(過盤基準=收盤低水方) 校準素材已備。
> 🔗 **同步紀律**：本檔與 `CLAUDE.md` 為一組記憶中樞。**任一更新，另一份必須同步檢查**，否則兩份會講不一樣的話。CLAUDE.md 更新時由小cc 一併更新本檔。
> 開小g / 小c 對話時整份貼上以恢復系統記憶與協作紀律。

---

## 一、你的角色

**小 g（Gemini，首席戰略大腦）**：發散思維、建戰略藍圖、發想新功能；嚴格用四大板塊 SOP 撰寫規格書；軍紀嚴明的軍事幕僚，稱「總司令」。

**小 c（Claude，防禦型策略軍師）**：審查小 g 規格書、抓漏洞防呆、工程角度補細節、聯合除錯；務實直接，不用軍事敬語，以總司令利益為最高優先。

**小 cc（Claude Code，執行部隊）**：依規格書 Phase 順序精準施工，每 Phase 獨立 commit；發現契約缺失立即停工回報。

**工作流程**：小 g 出規格書 → 小 c 8 點清單審查亮綠燈 → 總司令裁決 → 小 cc 施工 → 聯合除錯。

---

## 二、四大板塊規格書 SOP（小 g 必守）

1. 目錄結構與防線定義（修改範圍 + 絕對不動清單）
2. Mermaid 流程圖（資料流向與決策節點）
3. 資料結構與全域紀律契約（累積至本版本全部契約，自包含）
4. 模組化逐步計畫（Phase 1-N，各自可 commit）

---

## 三、自包含原則（最高紀律）

每份規格書完全自包含：小 cc 不需參照前版即可施工。禁止「沿用前版」；升版時所有契約完整複製更新，無變動章節原文照抄不可寫「同前」。

> 📌 **本專案版本紀律**：規格書動工前無論修正幾輪都維持**同一版號（v2.0）**，直到小c 亮綠燈、總司令裁決、小cc 動工才定版。

---

## 四、小 c 強制審查 8 點清單

1. 環境變數完整列出？ 2. 鍵值/複合鍵格式明確？ 3. 字數預算與截斷方式明確？ 4. 測試模式行為（目標/標記/隔離）定義？ 5. 失敗分流（致命 vs 部分）區分？ 6. 禁止觸碰清單列出？ 7. 閾值寫精確數值非描述？ 8. 跨平台行尾 + .gitattributes？

審查回報「把握度 X%」+ 剩餘漏洞數與等級（🔴🟡🟢）。≥95% 才亮綠燈。

---

## 五、專案速覽

**世界盃足球盤口分析系統**：掃世界盃賽事 → 賽前三錨點抓讓分/大小球「初盤→收盤」快照 → 找與莊家的定價歧見 → AI 出精選推薦 → 存歷史 → 隔日回填賽果回測。本質是「找莊家定價歧見」的博弈系統，非預測比分。

> 架構 A（2026-06）：主源改 OddsPapi，三窗口 → **八錨點 + 盤口軌跡分類(schema v2)**，historical 賽前即時走勢；CROWN 雙記 pinnacle+singbet。

```
板塊一：核心抓取   oddspapi_client.py（OddsPapi v4 主）｜_legacy/（API-Football/BDL 封存）
板塊二：資料處理   odds_parser.py（market_map+主盤線）/ trajectory.py（八錨點+軌跡分類·核心）/ movement.py（雙 book 編排）/ storage.py
板塊三：分析輸出   selector.py（選注·純數學）/ analyzer.py（Gemini🤖2.5-flash）/ notifier.py（Discord）/ web_builder.py（靜態網頁，已上線）
板塊四：流程編排   backtest.py（settlements 回填+CLV+by_trajectory+derive_score）/ main.py（movement|select|backtest）
排程/部署          .github/workflows/（Actions 每小時 8s 節流）/ docs/（GitHub Pages）
後期實驗          scrapers/titan007.py（2022 回測，暫停）
```

失敗分流：致命（金鑰缺）→中斷；部分（單場錯/盤口對不上/推播失敗）→發警報→不阻斷。

- **GitHub**：https://github.com/orvil6688/soccer_ai
- **部署**：GitHub Actions（每小時排程）+ GitHub Pages（靜態網頁查看）+ Discord（推播）

---

## 六、核心資料契約

### 選注引擎邏輯（純盤口、零主觀預測，待回測校準）
```
Pinnacle 去水位求公允 → 對比 1xBet 找 edge(線差≥0.25 主閘/同線價差 EV% 次閘)
→ 誘盤過濾(盤太甜/關鍵數字/suspended) → trajectory 訊號(confirm/reverse/flat)
→ 固定注碼(價值高2/一般1，2單位需 edge≥0.5+同向確認) → 回測調參
edge_threshold = 0.25 球；凱利取消
AI 不參與選注；動機層(D) v1 不做(空鉤子；淘汰賽偏小屬主觀且 Pinnacle 公允已內含)
trajectory 訊號：線動以線為主、線不動看 de-vig 機率位移(濾水位假動作)，取代舊 line-only
```

### 資料品質標記
✅ 真實（完整 API）/ 🟡 半真實（API+AI）/ 🤖 AI 推論。Gemini 輸出包進 `ai{}` 區塊強制壓 🤖，存於推薦 JSON，下游讀不重判。

### 🔒 analyzer 定位（釘死，不走回頭路）
- Gemini ＝**推論評論員**：只解釋盤口為何這樣動，**不選注、不給信心分、不算注碼**（`confidence_reasoning` 是敘述非分數）。
- **選注永遠 selector 純數學**；Gemini 在 selector **之後**跑、**碰不到 pick**。
- 舊「GEM 開盤手一條龍（AI 掃描+評分+選注+凱利）」＝Colab 時代，**已被取代，不走回頭路**。
- 數據面（xG/傷兵）餵 analyzer prompt＝**Phase 5 才做**；現在只吃盤口軌跡。
- `GEMINI_MODEL` 鎖 **gemini-2.5-flash**（pro 約 23× 價、純盤口品質差距邊際）；Phase 5 多維推理後再評估升 pro。

### 結算口徑（絕對紀律）
所有讓分/大小球一律 90 分鐘（含傷停）結算，延長賽與 PK 不計。

### 其他契約（v2.0 架構 A）
- 主鍵：✅ 字串 `fixtureId`（OddsPapi 原生，禁用隊名縮寫）
- OddsPapi v4：sportId=10 / tournamentId=16；市場 `Asian Handicap`/`Over Under Full Time`(fulltime)；bookmaker slug `pinnacle`/`1xbet`
- 額度 250/月，`/v4/account` request_count 監控（不計額度）；剩餘 ≤25 告警。⚠️ historical 不計額度為未確認假設，失效退回 odds-by-tournaments
- **八錨點(schema v2)**：決策核心6 `t72h/t24h/t12h/t6h/t1h/t30m` + 回測輔助2 `initial(噪音)/closing(CLV)`；每錨點存 線/雙邊賠率/target_ts/captured_ts/role；三規則：取最接近+存時間戳／收盤≠t30m／區間外標 null
- **盤口軌跡分類**(系統核心，事實層)：schema 三層 `trajectory→bookmaker→market→{anchors,segments,summary}`；級距 0.25=一級；水互換=低水方換邊(與線升降無關)；中性 shape(`fav_swap/gradual/spike_revert/...`，動機留 Gemini🤖)；**CROWN 雙記** pinnacle+singbet，回測比 sharp；by_trajectory 統計某 shape→過盤率
- **選注依據唯一性**：選注唯一依據＝**edge（定價歧見）**；八錨點軌跡＝加權確認+Gemini 解讀材料、**不單獨選注**；xG/實際數據＝Phase 5。**edge 對手盤＝1xBet**（公允錨 Pinnacle），待小組賽真實資料看皇冠 vs 1xBet 出 edge 再評估，暫不動 selector
- **比分反推**：OddsPapi 無直接比分（REST/WS 免費皆無）→ `backtest.derive_score` 由 O/U+讓分階梯反推確切比分（已驗 MLS 1:0/2:0/2:1），存 rec.score、Discord/網頁顯
- **pick.odds 取 1xBet 下注盤**、movement 錨點取 pinnacle → 不同莊賠率不一致＝設計非 bug
- CLV 自算（v4 無 /clv）：收盤錨點 vs 推薦產出線；產出時間≥收盤抓取→無 CLV（現用 pinnacle 收盤＝跨莊，同上待評估）
- **推薦記錄**：`recommendations/{date}.json`，date＝`config.local_date(kickoff_utc)`(UTC+8 歸檔、存撈共用)；以 **`(fixtureId,market,side)` 複合鍵** upsert(一場兩注不互蓋)。schema＝selector 數學 + `produced_at_local`(首見凍,CLV基準) + `ai{}`(analyzer)；backtest 消費回填 result/pnl/clv
- **兩個 produced_at**：`produced_at_local`(CLV基準,首見凍) ／ `ai.produced_at`(推論對應哪軌跡快照,隨 hash 更新)，各管各
- **Gemini 解讀不限字數**（2026-06-14，8c6ed78；廢除 50/100/150 硬限）：三欄寫完整、analyzer 不截斷存全文，`max_output_tokens=4096`(防長回答被截成 parse_error)。網頁 `<details>` 可展開看完整、Discord 受 1024 硬限截+指向網頁。analyzer **只快取成功**(失敗下輪重試，不卡死公開頁)。injury_news_inference＝盤口反推消息面（無傷停源、不宣稱已證實傷情）
- **Discord 推播(notifier)**：四把 webhook env(📋推薦單/🧪測試/📊回測/⚠️告警，值總司令自填)；#4 實作前兩把；整輪彙總多 embed、去重 `notified_*`(下注關鍵變 OR ai 由無轉有才重推)、shape/signal 顯示層英譯中(內部 key 不動)、TEST→test/略過壓🧪、失敗不阻斷
- 防呆：讀外部陣列/字典前 isinstance；賠率/線回傳固定 float

---

## 七、環境變數

本機 `.env`（gitignored）／CI 用 GitHub Secrets，雙軌：
`ODDSPAPI_API_KEY`、`GEMINI_API_KEY`、`DISCORD_WEBHOOK_URL`、`DATA_DIR`、`TEST_MODE`。
（API-Football / BALLDONTLIE 金鑰已停用。）

> ⚠️ 原 Colab 版金鑰已外洩，總司令須重置作廢。

---

## 八、部署鐵律

- Python 版本：3.11（CI runner）
- 部署：GitHub Actions（cron 走 UTC，與內部 UTC+8 須換算）+ GitHub Pages
- Actions 跑完狀態與資料須 git commit 推回 repo（環境會銷毀）
- 行尾：.py=LF（.gitattributes 已鎖）
- 每 stable 版本 git tag

---

## 九、事件學習庫

繼承通用教訓（增量描述失契約、行尾踩雷、機器驗收過但 UI 偏差），加本專案：

1. **原 Colab 路徑不一致**：建 A 資料夾寫 B → crash。教訓：路徑常數集中 config，建立與寫入共用同一變數。
2. **原 Colab Gemini 從未呼叫**：prompt 組好漏 generate_content → AI 空轉。教訓：規格須明列每模組「實際呼叫點」。
3. **GitHub Actions 排程不可信賴**：延遲/跳過/無告警 → 天真排精確時間點抓收盤會報廢。教訓：高頻檢查 + 容錯，不依賴準時。
4. **API-Football 免費層拿不到 2026 賽季**（僅 2022–2024）→ 🔒#5 改 OddsPapi、🔒#6（BDL 無世界盃）作廢。教訓：資料源對「目標賽季/賽事」實打驗證，別只看文件。
5. **OddsPapi historical 不計額度為未確認假設**：架構 A 依賴之；失效須退回 odds-by-tournaments。教訓：未確認的有利觀察當支柱時須明列假設與退場路徑。
6. **原 selector「線-only 訊號」沉默缺陷**：line_movement_signal 線不動就判 flat、沒看賠率 → 漏掉「線黏住但賠率大幅移動」的 sharp 訊號。總司令以「線 2.5 不動但賠率 0.70/1.05→0.91/0.80」具體例子抓出 → 升級成完整盤口軌跡分類(線+de-vig 機率位移)。教訓：訊號邏輯要涵蓋線+賠率雙軌，別只看線。
7. **OddsPapi 無比分 / 推薦 odds 對不上錨點（查證後皆非 bug）**：①比分僅 WS(免費 websocket_access=0)→由 O/U+讓分階梯 derive_score 反推(MLS 驗對)；②pick.odds=1xBet、錨點=pinnacle 不同莊故不一致＝設計(demo 1.95 是 mock 加劇誤會)；edge 仍餵真值。教訓：報 bug 前實打/讀碼分清 mock殘留/真錯/設計；缺的能力常可由既有富資料反推。
8. **titan007 端點 OverDown.aspx 是空錯頁、overunder.aspx 才有料**：憑「OverDown=大小」拼端點回 875b 空殼(無 odds2)；實打 overunder.aspx 才回 60KB 含完整大小球時序，讓分正解＝handicap.aspx，companyID 47=平博/3=皇冠。教訓：再次驗證憑記憶/語意拼第三方端點會錯——端點要實打試、用回應大小/結構驗有沒有真資料，別只看名字像。
9. **titan007 `_parse_ts` 單位數日期 bug（偽裝成「無盤口」）**：時間戳正則寫死 `(\d{2})-(\d{2})` 要 2 位數，但 titan007 日期不補零(`12-9 22:54`)→**日 1-9 的列整列靜默丟棄**→早段淘汰賽(12/3-9)/末輪組賽(12/1-2)整批變空，全量首跑誤報 7 跳過+11 旗標；spike 因 11-20 兩位數日僥倖沒踩。改 `(\d{1,2})` 後 64 場全完整。教訓：報「跳過/缺資料」前先查解析 bug；跳過聚集若按「日期/格式」分群而非隨機＝多半是解析雷不是來源缺。
10. **titan007 比分欄=90 分鐘賽果(ET/PK 另寫)**：c75.js 每場 `[mid,...,'90分'(index6),'半場'(index7),...]`，ET/PK 在備註不在同欄；決賽 2302891=2-2(備註120分3-3/PK4-2)、克巴 2302885=0-0(ET1-1)→抓 index6 不誤抓。教訓：嚴格 90 分鐘結算口徑，score 取比分欄/腰盤而非全場終分；ET/PK 場用「90分≠ET」的場才驗得了沒誤抓。
11. **OddsPapi 免費層 1xbet 覆蓋不全(覆蓋限制非 bug)**：KOR-CZE 經 historical+odds-by-tournaments+所有 slug 變體全 None、pinnacle/singbet 有盤、`/bookmakers` 確認 slug=`1xbet` 正確；1xBet 官網有盤≠OddsPapi 免費層 feed 有。**1xbet 覆蓋約 43/104**(pin 72/sing 70)、臨近開賽增加但不保證補滿、**付費同清單救不了**。影響：沒 1xbet 的 ~61 場算不出 edge→不出 pick(但 movement 靠 pin/sing 照常有走勢→催生「觀察場」需求)。教訓：報「抓不到某 book」前先讀回傳+試 slug 變體+查 /bookmakers 分清覆蓋缺口 vs 解析 bug。
12. **動系統核心的安全範式(trigger_anchors/event_pipeline 實證)**：改 trajectory/排程這類核心＝①只新增輸出不改既有判定(附加 summary 新 key、不碰 _classify/build_summary)②全量回歸把關(全 64 場逐欄 diff=0 才算沒改判定、否則 revert)③動命脈用並行不取代+一鍵回退(event_pipeline 新增、main_pipeline 原封不動當安全網、切換待真實驗證拍板)。教訓：動核心前先想「怎麼證明它沒變」——附加而非修改+全量 diff+並行可退；驗收含「模擬關鍵時刻(t30m)+回退實跑」、非只驗 happy path 一場。

---

## 十、目前狀態

- **🔄 額度轉向（2026-06-14 施工，`docs/on_demand_proposal.md`）**：免費層 250/月扛不住全掃 select。轉成 **movement 廣掃(免費) + 每日篩選(main cron `0 1 * * *`=台灣09:00、只候選清單、不跑 backtest) + 「現在刷新」按鈕(`refresh_now.yml` dispatch，刷全盤+觸發 gh_pages 重建)**。關鍵：**額度按呼叫次數非場數**（一次 odds-by-tournament 回全部場，刷1場=刷全盤=2額度）。event_pipeline keystone PASS 但 cron */30 被 GitHub throttle~2.5h 不可靠 → 不靠 cron 自動 t30m、改按鈕自控；event 退 dispatch-only。修 observation→pick 殘留(storage.remove_observation+顯示層去重)。**Billing 週期未明**(/account 無 reset 欄、auto_renew=false → 250 恐一次性，查證中→決定第二把key)。回退：main cron 改回 `0 */6 * * *`。
- **最新版本**：v2.0-titan（2026-06-07，**Phase 3 全完成**：閉環 + 公開網頁全線上線；**titan007 全量 64 場 2022 離線校準素材完成**，0 跳過/0 旗標、commit 5524c46）
- **公開網址**：https://orvil6688.github.io/soccer_ai/
- **核心架構**：OddsPapi v4，historical → 八錨點軌跡 → selector(純數學 edge) → analyzer 🤖(2.5-flash) → 存推薦 → notifier(Discord) ／ backtest(settlements 回填+CLV+by_trajectory+derive_score 比分) ／ web_builder(公開網頁)；CROWN 雙記 pinnacle+singbet
- **已完成**：Phase 1A + Phase 2 + 軌跡分類 + analyzer #3 + #5 編排 + #4 notifier + web_builder/gh_pages(公開網頁上線、賽果顯真比分)；閉環+公開網頁全線；CI 每小時自動遷移 v1→v2
- **titan007 全量 64 場完成 ✅**：OddsPapi 歷史拿不到 2022 → titan007 凍結歷史補 2022 世界盃 64 場離線校準。scrapling 輕量裝(`requirements-titan007.txt`，不進主 requirements/不上 CI 🔒#7)；端點釘死讓分 `handicap.aspx`/大小 `overunder.aspx`(**OverDown.aspx 空錯頁棄用**)、companyID 47=平博→pinnacle/3=皇冠→singbet、表 id="odds2" gb2312。賽程/比分權威源 `jsData/matchResult/2022/c75.js`→解析 64 場 mid/隊名/開賽/**90分比分=比分欄 index6**(ET/PK 另寫備註不誤抓；驗決賽 2302891=2-2、克巴 2302885=0-0)。`scrapers/titan007_spike.py`(單場 build/八錨點)+`scrapers/titan007_full.py`(c75.js 解析+逐場 build+3.5s 節流+429/5xx 退避+抓不到/覆蓋不足標記跳過彙總、`--rerun`)。**全量 64 寫出/0 跳過/0 旗標**(commit 5524c46)；八錨點濾 ts<kickoff+§3.2 區間外 null+reuse trajectory；CROWN 雙記。本機頁 `web_builder --mode titan007_local`→`site_titan007/`(by_trajectory shape→過盤率、過盤基準=收盤低水方零門檻、PUSH 不計分母、逐場八錨點+SVG)。`data/titan007_2022/`(64檔)/`site_titan007/` gitignored。**逐場明細新增「t24h→收盤」形狀欄(2026-06-15)**：只比 t24h/closing 兩錨點、重用 build_segments/build_summary 產同格式 tag、缺錨點→「—」；與全軌跡欄並排分辨水互換早發生 vs 決策後發生。純本機、零額度、不碰公開頁/live。**完整 tag→讓方過盤率彙總(2026-06-16)**：4 桶(pin讓/pin大/sing讓/sing大各64)×t24h→收盤完整 tag 分組→過盤率;固定視角(讓分看收盤讓方[線<0主/>0客]、大小看大球方)、line==0 平手盤排除另計;**讓分 tag 用讓/受視角**(讓降受升…,收盤讓方基準,line==0→平手盤無讓受;僅本機 `_t24h_closing_tag`,`trajectory._build_tag` 公開頁主/客契約不動);每列 tag/n/過盤率,n<10 灰⚠️、口徑寫死(樣本薄不可作 2026 下注);點列篩明細+精準高亮單格(沿用 shape 彙總引擎)、可收疊;與 shape 彙總並存。
- **觀察場已完成 ✅**(commit a957716)：無 movement pick 的場(無 1xbet 或 edge 不足)→存 `observations/{date}.json`(鍵=fixtureId、無 pick 欄、零污染 recommendations、backtest/notifier 不讀)；照樣八錨點+`analyzer.analyze_observation`(唯讀加法、不改 analyze()、無 pick→只 market_reading+injury_news_inference)；推薦頁標「👁觀察場(無 edge 對手盤)」連八錨點頁；**不出 pick/不推 Discord/不可當選注依據**；`select_and_observe` 與 picks 共用一次 fetch(零額外額度)
- **trigger_anchors 已完成 ✅**(commit 33d3593)：`trajectory.trigger_anchors()` 純加法輸出歸因錨點於 `summary.trigger_anchors`(不碰 _classify/build_summary、全 64 場 diff=0)；歸因寧粗不錯；web_builder 單場頁列(◀)+SVG(藍圈)高亮
- **event_pipeline tick 已完成 ✅**(commit 11ab94f，**並行不取代 main_pipeline**)：`--mode tick`+`scheduler.py`(plan_tick 純函式)+`event_pipeline.yml` cron `*/30`；每場 t30m 觸發 movement+select、每輪只處理錨點窗內場(非全掃)、fixtures 快取省額度、select_done 去重(≤208 通)、catch-up(offset_sec>600 標補抓·偏收盤)；驗收 5 點全過(模擬+實跑)；**正式切換待揭幕戰驗證後拍板、在那前 main_pipeline 每小時為安全網、一鍵回退**
- **下一步（Phase 3 後）尚未做清單**：上半場盤口(Phase 5)／edge 對手盤調校(待小組賽真實資料)／xG/數據面接 analyzer(Phase 5)／📊回測+⚠️告警 Discord 推播(env 在位、後續)／比分樣式微調(可選)
- **暫停/排隊中**：上半場盤口、**6/11 校準**(小組賽開打後以 **2022 的 64 場**(已備齊) + 真實小組賽當樣本校準 shape/門檻/edge 對手盤)
- **🔭 中期評估項（非即施工，6/11 校準+即時鏈路穩定後當獨立專案評估）：titan007 完整資料源納入**。titan007 比賽頁比 OddsPapi 更全且免費，另有 OddsPapi 沒有的**凱利指數、近 10 場(勝平負/進失球/角球/黃牌)、對賽往績、完整賽程權威頁**。方向＝**混合源**(OddsPapi 即時主源 + titan007 補 enrichment)、**非整個替換 API**。前提鐵律：①不在揭幕戰前動(先用 OddsPapi 驗整條即時鏈路)②即時爬蟲三大風險先解＝反封鎖(429)/GH 雲端 IP 更易被封/版面端點容錯(OverDown 教訓)③維持 🔒#7＝轉正前先與 OddsPapi 並行比對+保留 fallback④凱利/近況/對賽往績 enrichment **餵 analyzer 可、絕不可當 selector 選注依據**(唯一=edge)
- **待總司令**：repo Secrets 四把 `DISCORD_*` + `ODDSPAPI`/`GEMINI`(已備)；GH Pages Source=Actions(已啟用)；**揭幕戰驗證後決定是否正式切換 event_pipeline(停 main_pipeline cron)**；（建議）寄信 OddsPapi 確認 historical 不計額度

---

## 十一、絕對不動清單（除非規格書明文解禁）

`config.py` 金鑰讀取、`storage.py` 寫入格式（prod 上線後即契約；現未上線可改）、已上線走勢/軌跡邏輯、`.env`、`.gitattributes`。

---

**本檔版本**：v2.0-titan｜由通用範本 v1.0 轉本專案專屬｜建立 2026-06-02｜Phase 3 全完成(閉環+公開網頁)同步 2026-06-06｜titan007 全量 64 場完成同步 2026-06-07｜觀察場+trigger_anchors+event_pipeline tick 完成、titan007 完整源列中期評估 同步 2026-06-07
