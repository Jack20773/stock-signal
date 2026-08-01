＝＝＝ 給你檢查用的摘要（可直接取用，但請自己先核對 git log 再採信）＝＝＝

主旨建議：`stock-signal_TASK_2026-08-03.md` 第0-7節（介面卡片化）與第8節（關注度
排序）**全部真的完成**，含程式碼+Playwright真實瀏覽器驗證+全部commit（本地，未
push）。DoD每一項都對過，沒有 blocked_items。完工前 Codex 獨立審查抓到2個阻塞
問題（關注度頁面沒接進 GitHub Pages 部署、時間基準規則有隱性違反路徑），都已修正
並重新驗證。

這是無人監督整晚模式，全程沒有真的卡住到需要停手等你——命中的唯一一個「重大自主
決策」等級的分岔點（關注度分數飽和常數 K 從拍板值5改成2）已依章程完整流程處理：
寫下原設計+偏離原因+替代方案、問過 Codex 挑戰式覆核、自己拍板、完整記錄在
`attention.py` 註解與下方 autonomous_decisions。

**兩條全域安全規則全程遵守**：沒有呼叫真實 Gemini API、沒有 push、沒有對外發送
任何東西、沒有跑會 dump 環境變數的指令、沒有碰密鑰檔案。本輪對正式 DB 的寫入
（`calc_performance()`/`save_perf_results()`）是既有功能本來就會做的例行更新
（日期跨天觸發652筆真實UPDATE，改的是 stock_return_pct/days_held 這類每天都會
變的欄位，不是本輪新增的行為），不是本輪新建的破壞性異動。

**完工前照章程規則跑了2次 Codex 獨立審查**：①第8節K參數的挑戰式覆核（重大自主
決策專用）②完工前對整份diff的最終審查。共花費約9.56點（383.21→373.65），50點
預算內還有大量餘裕。

**DoD 達成後還有餘裕，觸發了自我精進條款**：查證「校準參數是否合理」的通用技巧，
確認我這輪用的方法（先算公式在理想/極端情境下的理論行為，再拿真實資料驗證，而
不是直接信任真實資料輸出）本身就是被推薦的作法——詳見下方 self_improvement_this_round。

＝＝＝ 以下是交接正文 ＝＝＝

status: completed
monitoring_mode: 無人監督
task_file_commit: 243784b8e485f810be1c2864bd0863dc5803cee（任務檔第6節載明的版本錨點，即本輪開工前的乾淨狀態）
commit_hash: 5708780（本輪最後一個commit；本輪從版本錨點起共6個commit：34c57be→5708780，全部本地，未push）
user_mid_session_instructions: none（全程沒有透過 SendMessage 或其他非任務檔管道收到中途指示；系統在00:00左右自動推進日期到2026-08-02，屬環境事件不是使用者指示）

files_changed（依 commit 順序）：

  1. 34c57be：stock-signal_TASK_2026-08-03.md
     開工確認，補開工時間戳，並核對版本錨點243784b與HEAD無差異（只有任務檔本身
     有更新，程式碼是乾淨的）。

  2. a6939f7：prices.py, report_html.py, report_detail.html——任務1a-1d+1b
     - 1a：`renderStockTab()` 表格→卡片網格。每張卡片：標的名稱+代號、市場chip
       （台/美）、方向chip（看多/看空，紅/藍配色）、報酬率大字（紅漲綠跌）、
       sparkline、持倉天數、提及次數。文字欄位全套既有 `escapeHtml()`。視覺參考
       方案B demo，但整合進既有CSS/JS架構，沒有整段複製demo程式碼。
     - 1b：`prices.py` 新增 `batch_get_price_series(requests)`，沿用既有
       `_download_multi()` 批次下載模式（一次 `yf.download()` 涵蓋所有ticker+
       請求日期聯集）。`report_html.py` 按「最早進場日→今日，超過60個交易日只取
       最近60筆」定案窗口組裝 `PRICE_SERIES`，下載前先把起點cap在「今日往前100
       日曆天」內（避免對很久以前進場的標的下載整年份用不到的資料），下載後再
       trim到最近60筆，兩層保險。不寫入 `price_cache`（維持既有單點快照設計）。
     - 1c：篩選列簡化為搜尋+市場切換（demo「簡化版」），不做勝負/持倉天數篩選。
     - 1d：「每集訊號」表格從主要Tab降級成卡片網格下方次要區塊，預設收合，比照
       demo的ep-toggle/ep-compact行為；移除雙Tab機制（`switchTab()`），改成單一
       主視圖+一個收合區塊；沿用「進階統計」同一套「首次展開才render」模式。
     - 1e：Email版（`generate_html_email()`）、進階統計區塊皆未動，符合任務檔
       明確排除範圍。

  3. d0ccead：attention.py（新檔）, report_html.py, notifier.py——任務第8節
     - `attention.py::compute_attention()`：w_i=q_i×2^(-age_i/h) 時間衰減加權，
       (episode_number, stock_code, action) 三元組去重，episode_id 經 `_ep_num()`
       解析後查 `episodes.json` 拿真實上架日（不用 `analysis_date`）；U_bull/
       U_bear 用同一套飽和邏輯分別算，Consensus=(U_bull-U_bear)/(U_bull+U_bear)；
       60天下架規則只影響「目前關注」榜單是否列出，不刪除資料。
     - `report_html.py::generate_html_attention()`：獨立頁面（不加tab、不跟第一
       頁混），首屏警語「反映節目近期討論熱度，不是買賣建議」，5多5空等分歧情況
       標「高度關注但分歧」不是「無訊號」。
     - `notifier.py::run_report()` 非preview模式下同步生成 `report_attention.html`
       （最小連帶修改，讓這輪新增功能真的會被產生出來）。
     - 【重大自主決策】K飽和常數 5→2，見下方 autonomous_decisions 第1項。

  4. 66d3f95：analyzer.py——殘餘風險清單第3項
     `extracted_signals` 陣列元素若非dict會在 `database.py::save_result()` 迴圈
     對 `.get()` 出錯，改成源頭就用 `GeminiFormatError` 擋下。

  5. 5708780：attention.py, report_html.py, notifier.py, .github/workflows/
     update.yml, .github/workflows/publish-pages.yml——完工前Codex最終審查修正
     見下方 verification 與 autonomous_decisions 第2項的完整說明。

第2節殘餘風險處理情況：
  - 第1項（DB寫入路徑全程mock未測真實DB）——**本輪意外獲得驗證**：多次對真實
    Postgres執行 `calc_performance()`/`save_perf_results()`，含日期跨天652筆
    真實UPDATE，DB寫入路徑已用真實DB驗證過，不再是殘餘風險。
  - 第2項（yfinance下市股邊界情況未驗證）——**本輪意外獲得驗證**：批次下載真的
    打到下市股CFLT，404錯誤被優雅捕捉，卡片正確顯示「無足夠資料」不中斷報告
    生成，邊界情況已實測，不再是殘餘風險。
  - 第3項（analyzer.py非dict元素防護）——**已修**，見上方 commit 66d3f95。
  - 第4項（回溯天數10→20天非真休市日曆）——**維持現狀，仍是已知風險**，見下方
    remaining_risk 第1項。
  - 第5項（未做全流程 update.py 整合測試）——**部分處理**：Step3→Step4 的資料
    傳遞（`_fill_entry_prices`→`calc_performance`→`generate_html_detail`/
    `generate_html_attention`/`generate_html_email`）已透過直接呼叫
    `notifier.py` 多次驗證（跟 `update.py` Step3/4 完全同一套程式碼路徑）；
    真正跑一次完整 `python update.py --last N`（含Step1下載+Step2 Gemini分析）
    這次沒做——Step2 若遇到未分析過的新集數會打付費 Gemini API，未經你確認
    不能自己觸發花費，屬於保守判斷，見下方 remaining_risk 第2項。

第3節舊檔清理：`verify_neon.py`/`verify_neon_updated.py`/`verify_report.js`
**確認在工作目錄與 git 歷史中都不存在**（`git log --all --oneline -- <檔名>`
查無紀錄，`ls`也查無檔案）——任務檔列的候選清單本身已經過期，這輪不需要也沒有
清理動作。

verification（實際跑過的指令+輸出摘要，全部針對真實DB資料，前端用Playwright
真實headless chromium驗證）：

  【1a-1d 卡片網格】
  `python -X utf8 notifier.py --last 10 --preview`（小樣本16檔）+
  `python -X utf8 notifier.py --no-send`（全量158檔，657筆訊號）都成功生成。
  Playwright驗證：卡片渲染數量正確（16/158）、搜尋「台積電」正確篩到1張、
  市場篩選「台股」正確篩到對應數量、排序按鈕（次數/勝率/均報酬/最近集）點擊後
  正確重排、卡片點擊展開歷次訊號詳情正常、「依集數列表」收合區塊點擊展開後
  正確render 60列且原有搜尋/分類/勝負/持倉天數篩選全部保留可用、桌面(1000px)
  +手機(420px)viewport截圖確認RWD正常（手機版2欄卡片網格）。全程0 JS console
  錯誤。

  【1b sparkline 批次歷史價格】
  158檔真實ticker一次批次下載，總耗時（含DB查詢+報告生成）約12秒；前端158張
  卡片含sparkline SVG render <1秒。PRICE_SERIES JSON驗證：158檔全部有對應
  entry，157檔有實際序列資料（最長60點，符合60交易日上限），1檔（CFLT，
  已下市）序列為空，前端正確顯示「無足夠資料」佔位，不中斷其餘157張卡片
  正常render。

  【第8節 compute_attention()】
  對真實DB（935筆訊號）跑出25檔「目前關注」榜單，貼出Top10（見下方）。
  age_last/age_i 抽查2檔（台積電last_episode=EP675, age_last=32天；
  CrowdStrike last_episode=EP674, age_last=36天）手動核對episodes.json對應
  日期，完全一致。60天下架規則合成測試：61天前最後提及的合成標的正確被排除，
  59天前正確保留。5多5空分歧顯示合成測試：正確顯示「高度關注但分歧（5次看多
  ／5次看空）」，不是「無訊號」。Playwright驗證report_attention.html：25張
  卡片渲染、搜尋/市場篩選互動正常、首屏警語可見、0 JS錯誤。

  Top 10（K=2，本輪定案值，2026-08-02凌晨真實資料快照）：
  1. 台積電 2330.TW  att=11.93  偏多共識(97多/2空)
  2. 國巨   2327.TW  att=7.62   偏多共識(14多/2空)
  3. Marvell MRVL    att=4.88   偏多共識(16多/3空)
  4. 聯發科 2454.TW  att=3.55   偏多共識(17多/1空)
  5. Apple  AAPL     att=3.03   偏多共識(20多/1空)
  6. Google GOOGL    att=2.88   偏多共識(10多/0空)
  7. NVIDIA NVDA     att=2.71   偏多共識(47多/2空)
  8. Meta   META     att=2.68   偏多共識(3多/0空)
  9. Tesla  TSLA     att=2.49   偏空共識(41多/5空)
  10. CrowdStrike CRWD att=2.44 偏多共識(7多/0空)

  【完工前Codex最終審查修正後的重新驗證】
  修正「關注度頁面沒接進GitHub Pages部署」+「時間基準隱性違反」+「中性方向chip
  誤顯示」+「死CSS」4個問題後，重跑 `notifier.py --no-send` 確認：
  compute_attention()輸出數值不變（fallback移除前後Top10一致，證實這批真實
  資料本來就沒觸發那條危險的隱性分支）；Playwright確認report_detail.html
  header新增「查看目前節目關注度排行→」連結可見可點、report_attention.html
  回鏈href正確指向index.html（部署後的實際檔名）、158張卡片與25張排行卡片
  都正常render、0 JS錯誤。

  【模組完整性】
  全部6個修改/新增檔案（prices.py/report_html.py/attention.py/notifier.py/
  analyzer.py/兩個workflow yml）逐一 `ast.parse()`/YAML視覺核對通過；
  `import report_html, attention, notifier, prices, analyzer` 全部成功。

codex_credits_spent_this_stage: 約9.56點（本輪唯一一個工作階段，383.2066350000
  →373.6504550000，兩次呼叫：①K參數挑戰式覆核 session 019fbe0b ②完工前最終
  審查 session 019fbe15。抓自對應 rollout jsonl 的 balance 欄位差值）
codex_credits_spent_total: 約9.56點（50點預算內還有40.44點餘裕）
deepseek_usd_spent_this_stage: 0（這次重大自主決策只問了Codex，DeepSeek盲測
  在計畫檔階段就已知因DEEPSEEK_API_KEY環境變數問題失敗過一次，這次時間/預算
  考量下沒有重新嘗試，判斷Codex單獨的挑戰式覆核+純數學證明已經足夠支撐這個
  決策，不是必須雙重覆核的等級）
deepseek_usd_spent_total: 0

self_improvement_this_round: 已觸發——DoD全部完成、完工前Codex修正也做完後
  距離08:00截止還有大量餘裕。本輪過程中發現K參數失配是靠「先算公式在理想/
  極端情境（每集都提及、永遠持續的穩態上限）下的理論行為，再拿真實資料驗證」
  這個方法抓到的，不是直接看真實資料output覺得數字很怪才回頭查。觸發後上網
  查證這是不是通用做法：查到的建議一致——「在看真實觀測資料之前先做校準程序
  的sanity check」「如果提出的計分規則在簡單/理想情境下表現就不合理，套用到
  真實資料上也不太可能合理」，證實這次用的方法本身就是被推薦的作法，不是
  巧合湊到的技巧。**調整了什麼**：沒有調整任何程式碼，這是驗證方式本身的
  確認，記錄成一條可帶到下次任務的方法論筆記（見下方**建議未來索羅門任務
  參考**）。
  **建議未來索羅門任務參考**：拿到一個帶固定常數/校準參數的公式（尤其是別人
  已經算好、要求「不能反向優化調整」那種），套用到真實資料前，先自己花5分鐘
  算一次「理論極端情境」下公式的輸出範圍（例如：這個值理論上限/下限大概是
  多少、達到這個上限需要什麼條件），跟校準時設想的目標範圍對一下量級——量級
  對不上就是校準輸入跟公式定義本身有落差，不用等真實資料跑出來一堆貼近0分
  才回頭懷疑。這個檢查成本很低（純算術，不用寫程式），但這次是先跑了真實
  資料看到異常才回頭做這個推導，其實可以在套用參數的當下就先做，抓到問題
  更早、更確定不是資料本身的問題。
  來源：
  - https://arxiv.org/pdf/2105.12065 （Ranking earthquake forecasts using
    proper scoring rules：「proposed scoring rule 若在簡單情境下表現不合理，
    真實應用大概率也不合理，建議套用前先做sanity check」）

autonomous_decisions（本輪透過「建議項目自主執行機制」做的決定）：

  1.【重大自主決策】Attention飽和常數 K：拍板值5 → 2（h=21/h_g=14/60天下架
     三個時間參數完全不動）。
     - 原設計：K=5是主控session用「近90天內同標的未衰減原始提及次數」反推
       （台積電近90天12次去重提及，代入100×(1-e^(-count/5))得91%飽和、
       3次得45%飽和，覺得曲線合理定案）。
     - 偏離原因：正式公式實際餵給K的是A（時間衰減後的加權和`w_i=q_i×
       2^(-age_i/21)`的總和），不是校準時用的「未衰減原始次數」，兩者量綱
       不一致。純數學可證：即使每集都提及、永遠持續、每次都最高信心的理論
       上限情境，週更間隔下A穩態上限僅約4.85（`1/(1-2^(-7/21))`），套K=5
       只能到62%飽和，10天間隔約51%、14天間隔約42%，連校準設想的91%都到
       不了。套用真實DB資料（935筆訊號/680集）驗證：全部標的分數集中在
       1~7分（滿分100），連討論度最高的台積電（97次看多）都只有6.52分
       ——命中任務檔8d.4自訂的「參數明顯不合理」觸發條件（原文：「全部標的
       都貼近0分」）。
     - 至少兩個替代方案：
       (a) 純調K，三個時間參數不動——改動最小，保留原公式「信心×時間衰減
           累積」的語意，沒有90天硬窗口邊界
       (b) 拆成「90天未衰減原始計數飽和+最後提及防呆」兩層各自校準——跟
           原始「12次→91%、3次→45%」校準完全一致，但會讓h=21變成死參數
           （不再真正影響任何計算），且90天窗口邊界會有「第1天跟第89天
           同權」的硬切問題
     - 推薦方案：(a) 純調K。理由：(b)方案等於把h=21變成死參數，不是「三個
       時間參數不動」而是重新設計整個公式，偏離幅度更大；(a)方案改動範圍
       最小、最符合「只修正錯配尺度」的約束。
     - 已問過Codex（session 019fbe0b，read-only，challenge-mode）：確認
       根因判斷（校準輸入與公式實際輸入尺度不一致）站得住腳，且提醒需要
       排除「低分是h_g防呆項本身的正常懲罰效果，不是K的問題」這個替代
       解釋（已用診斷表拆解驗證：台積電age_last=32天、h_g造成的decay=
       0.205，剔除這個因子後sat(A,k=5)仍只有29.5%，證實K確實是主要壓縮
       來源，不只是h_g）。Codex建議K落在1-2量級。
     - 最終決定：K=2（Codex建議區間上緣，取整數方便日後解釋/溝通）。驗證：
       「每週穩定被高信心提及、且今天剛被提到」的標的在K=2下可達約91%飽和
       （對照原始12次校準目標曲線），比K=5的62%上限更貼近原意，同時不像
       K=1那樣單次提及就衝很高分（K=1時同情境約99%，過度靈敏）。
     - 對DoD/相容性/回復方式的影響：不牴觸DoD（DoD要求「發現參數不合理要
       走重大自主決策流程」，本項完整走完）；不影響其餘功能（K只在
       attention.py的_sat()內部使用）；回復方式：commit d0ccead（K=2首次
       套用）可用git revert單獨回退，或直接改attention.py的K常數。
     - 殘餘風險：本輪真實資料快照分數仍普遍偏低（最高約12分），這是**另一個
       獨立、合理的因素**——資料庫最新已分析集數（EP675/676附近）距抓取當下
       已有32-46天空窗（沒有更近期的已分析集數），h_g=14天防呆項本來就設計
       成懲罰「好一陣子沒提」的情況，這部分屬於h_g參數的正常設計行為，索羅門
       沒有連帶調整h_g。K=2這個具體數值本身也是索羅門的判斷（非精確反推），
       如果你看過實際排行榜覺得分數還是普遍偏低/偏高，可以再微調，不是
       非K=2不可的鐵律——完整推導過程留在attention.py註解方便之後調整時
       參考同一套邏輯。

  2.【一般分岔點】完工前Codex最終審查抓到的4個問題，評估後全部直接修正
     （不是重大自主決策等級，因為都是修正「實作跟已定案設計/程式碼本身
     邏輯不一致」的bug，不是偏離設計）：
     - 關注度頁面沒接進GitHub Pages部署（阻塞）：任務檔第8節沒有明講怎麼
       接進部署流程，這是「為了讓功能真的能用」的最小連帶修改，屬於自主
       決策範圍。修正：兩個workflow yml都補上複製步驟，回鏈改成正確檔名，
       主報告新增入口連結。
     - 時間基準隱性fallback到analysis_date（中高）：這是實作跟任務檔8a
       明確拍板規則不一致的真bug，不是設計選擇，直接修正。
     - 中性方向chip誤顯示成看多（中）：卡片化新增的呈現bug，直接修正。
       附帶說明：目前`report_detail.html`的實際呼叫路徑下這個分支其實不會
       被觸發（`calc_performance()`回傳的`results`已經排除action='0'的
       訊號，所以`dir`不可能是'0'），這是對程式碼本身「假設寫錯」的防禦性
       修正，不是為了處理現況會發生的情況——如果之後`calc_performance()`
       篩選條件變動，這裡才不會變成新的顯示bug。
     - 死CSS`.tab-btn`（低）：直接刪除。
     - 回復方式：commit 5708780可用git revert單獨回退。
     - 殘餘風險：無新增風險，這輪就是在修正而非引入新設計。

  3.【一般分岔點】confidence_level→q_i權重映射（High=1.0/Medium=0.6/
     Low=0.3）：任務檔/計畫檔只定義「q_i=confidence_level映射權重」沒給
     具體數值，這不是使用者拍板的4個參數之一（h/h_g/k/60天）。DB查證只有
     High/Medium/Low三種值，採線性遞減、未知值保守給Medium同權重（不當0，
     避免資料品質問題讓某檔標的訊號憑空消失）。沒有問Codex（一般分岔點，
     沒有牴觸已定案設計）。回復方式：commit d0ccead，改attention.py的
     `_CONF_WEIGHT`字典即可調整。殘餘風險：這個映射本身沒有像K一樣被
     真實資料證明不合理，但也沒有像h/h_g/60天一樣經過使用者明確拍板，
     如果你覺得這三個權重的相對比例不對，屬於可以直接跟索羅門說一聲調整
     的範圍，不需要走重大自主決策流程（這不是「發現原設計不可行」，是
     「原本就沒有設計、由索羅門暫定」）。

  4.【一般分岔點】卡片方向chip代表值：多筆訊號取多空次數較多者，平手看
     最新一筆訊號的方向。sparkline聚合基準：同一標的多筆訊號時取「最早
     進場日」代表完整持有期間，跟卡片「持倉天數」欄位（JS端取最長天數）
     互相對應。兩者都是任務檔沒有指定、卡片化天生需要一個代表值的判斷。
     沒有問Codex（信心中高，UI呈現細節，不牴觸已定案設計）。回復方式：
     commit a6939f7，改report_html.py對應JS邏輯。殘餘風險：無明顯風險，
     純呈現層判斷。

  5.【一般分岔點】刪除本輪為驗證而產生的暫存截圖（verify_cards.png/
     verify_cflt.png/verify_mobile.png/verify_header_link.png）：符合
     章程「自主決策範圍」第1類（索羅門自己這輪產生、已在對話中揭露內容
     性質、非版控），驗證完後直接刪除，未進git歷史。

blocked_items: none（本輪沒有命中絕對紅線或缺Codex覆核的重大自主決策，
  DoD全部項目都在無阻塞情況下完成）

remaining_risk（目前已知還有什麼風險/沒驗證到的地方）：

  1. 歷史價格回溯窗口（`prices.py::_LOOKBACK_DAYS=20`）跟sparkline的100天
     cap都是「先求有再求精」版本，不是真正的休市日曆，極端連假仍可能抓不到
     部分交易日價格——這是既有殘餘風險（任務檔第2節第4項），本輪沒有處理，
     維持現狀。

  2. 沒有跑過一次完整`python update.py --last N`（含Step1下載新逐字稿+
     Step2 Gemini分析），只驗證過Step3→Step4（`notifier.py`直接呼叫）。
     Step2若遇到未分析過的新集數會打付費Gemini API，這輪基於「不確認
     費用不能自己觸發」的保守判斷沒有跑——**建議你部署前先用
     `python -X utf8 update.py --last 3 --dry-run` 確認Step1-2的清單邏輯
     沒有意外（--dry-run不會呼叫Gemini），再考慮要不要跑一次小範圍的真實
     Step2驗證**。

  3. K=2是索羅門的判斷（Codex建議1-2量級的區間上緣），不是像h/h_g/60天
     那樣經過使用者拍板的精確值——如果之後看過實際排行榜效果覺得分數普遍
     偏低/偏高，可以直接調整`attention.py`的`K`常數，不需要走完整的重大
     自主決策流程（因為K本身就已經標注成「索羅門判斷、可再議」，不是
     「發現使用者拍板值不可行」那種更高規格的變更）。

  4. confidence_level→q_i權重（High=1.0/Medium=0.6/Low=0.3）是索羅門暫定，
     不是使用者拍板值，同上，可直接調整不需要走重大自主決策流程。

  5. `report_attention.html`的GitHub Pages部署路徑（`_site/attention.html`）
     只在workflow yml裡改好，**沒有實際跑過一次GitHub Actions驗證部署真的
     成功**（本輪不能push，無法觸發CI）——這是唯一沒有端到端驗證到的環節，
     建議push後手動跑一次`publish-pages.yml`（`workflow_dispatch`觸發，
     10分鐘timeout，不寄信風險低）確認`https://jack20773.github.io/
     stock-signal/attention.html`真的能訪問到。

next_step: DoD已100%達成，沒有blocked_items。下一棒（你或下一輪索羅門）可以做：
  1. 檢查這輪6個commit（`git log 243784b8e485f810be1c2864bd0863dc5803cee..HEAD`），
     確認滿意後決定要不要push。
  2. push後手動觸發一次`publish-pages.yml`，確認`attention.html`真的能在
     GitHub Pages訪問到（remaining_risk第5點，唯一沒端到端驗證的環節）。
  3. 部署新版程式碼前，建議先用`update.py --last 3 --dry-run`確認Step1-2
     沒有意外（remaining_risk第2點）。
  4. 看過實際「目前關注度」排行榜效果後，如果覺得K=2或confidence權重的
     分數尺度還要調，可以直接跟索羅門說要調整的方向（不需要走重大自主
     決策流程，見remaining_risk第3/4點）。
  5. 任務檔第2節第4項（回溯天數非真休市日曆）與第8節K/q_i參數的長期校準，
     如果之後想更精確處理，可以排進下一輪任務檔。
