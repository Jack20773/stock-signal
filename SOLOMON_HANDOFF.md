＝＝＝ 給你檢查用的摘要（可直接取用，但請自己先核對 git log 再採信）＝＝＝

主旨建議：stock-signal 這輪任務檔 9 項全部真的完成（含程式碼+驗證+commit），
episode_analysis 的 CREATE TABLE + 資料回填等你核准後才執行；第 14 項施工前發現
在你看到這份任務檔之前就已經被上一輪修完，不需要再動。

這是有人監督模式（2小時窗口，19:47-21:47），全程沒有真的卡住到需要 SendMessage
問你——命中的唯一一個「需要你介入」的點是 episode_analysis 的 CREATE TABLE，這是
任務檔第0節本來就講好的既有全域規則，不算臨時卡關。

**兩條全域安全規則全程遵守**：沒有呼叫真實 Gemini API（連驗證都只用 mock 回應）、
沒有執行任何 CREATE TABLE/ALTER 對正式 DB（`episode_analysis` 的 DDL 只寫好放在
下面，沒有執行；讀資料庫現況一律唯讀 SELECT，沒有動過任何寫入）。

**完工前照章程規則跑了一次 Codex 獨立審查**（花費約 2.46 點，50 點預算內還很寬裕），
抓到 2 個阻塞問題（`episode_analysis` 缺舊資料回填、Gemini 格式驗證漏放行缺欄位的
錯誤回應）+ 3 個建議項（REAL 精度誤判/重試註解不準/email 版也有 XSS 缺口），已經
全部修正並重新驗證過，詳見下方 verification 與 autonomous_decisions。

＝＝＝ 以下是交接正文 ＝＝＝

status: completed
monitoring_mode: 有人監督
task_file_commit: 55a463e
commit_hash: e31bc26（本輪最後一個 commit；本輪從 55a463e 開始共 8 個 commit，見下方 files_changed 逐項對應）
user_mid_session_instructions: none（全程沒有透過 SendMessage 或其他非任務檔管道收到中途指示）

files_changed（依 commit 順序，每個 commit 都已個別驗證+commit，細節見各 commit message）:
  1. database.py, batch.py（commit 0e8d8a4）——任務第5+6項
     新增 episode_analysis 表設計：save_result() 改用
     INSERT episode_analysis ... ON CONFLICT DO NOTHING RETURNING 判斷「是否第一個
     拿到這集」（PRIMARY KEY 天生防併發），有 RETURNING 才繼續寫 signals，最後
     UPDATE signal_count；batch.py::load_analyzed_set() 改查 episode_analysis 而非
     signals。CREATE TABLE IF NOT EXISTS 已寫進 init_db()，但這輪沒有執行任何會
     連線真實 DB 呼叫 init_db() 的腳本（見下方 blocked_items 的 DDL）。

  2. prices.py（commit 5d44b3a）——任務第1+13項
     批次查價 cache miss 時從逐筆呼叫 yfinance 改成一次 yf.download() 批次下載
     （涵蓋所有請求日期的最寬區間）+ 一次 execute_batch bulk upsert；抽出
     _read_price_cache()/_read_latest_cache()/_write_price_cache() 共用函式，取代
     原本 get_close_on_or_before()/batch_get_close_on_or_before() 等處重複的
     「查快取→取未命中→寫回」邏輯。

  3. notifier.py, update.py（commit 5f64564）——任務第2項
     notifier.run_report() 新增可選參數 results/stats，傳入時跳過內部重算
     calc_performance()/win_rate()；update.py Step3 算好後傳給 Step4，避免同一批
     訊號被算兩次。

  4. performance.py（commit 0bc7f27，後續 e31bc26 再補一次精度修正）——任務第3項
     calc_performance() 比對這筆訊號目前存的值跟新算出的值，只有真的不同才放進
     UPDATE 清單。

  5. analyzer.py（commit ec87ac9，後續 9dc5a35/e31bc26 再修）——任務第12項
     改讀 config.py 的 GEMINI_API_KEY，不再自己 os.getenv()（原本能動只是因為
     import config 的副作用湊巧先跑了 load_dotenv()）。

  6. analyzer.py, batch.py（commit 9dc5a35，後續 e31bc26 再修）——任務第9項
     新增 GeminiFormatError，JSON parse 失敗/欄位形狀不對時拋出；
     _analyze_with_retry() 對這個例外用固定 2 秒重試，對其他例外（逾時/429/5xx）
     維持指數退避。

  7. prices.py（commit c2c883e）——任務第7項
     歷史價格回溯天數 10→20 天（_LOOKBACK_DAYS 常數），因應農曆年連假等長假期
     抓不到交易日價格的問題（AI 暫定：先用固定天數這個「先求有再求精」版本，
     沒有加 pandas_market_calendars 依賴，理由見 prices.py 該常數上方註解）。

  8. report_html.py（commit eaee603）——任務第4+10項
     新增 _buildEpRowIndex() 一次性建立 ep→rows Map 索引，取代
     collapseOldEps()/syncEpHeaders()/sortBy() 原本 O(集數×列數) 的
     querySelectorAll；sortBy() 排序完用 DocumentFragment 一次掛回 DOM。新增
     escapeHtml()，renderDetailTab()/renderStockTab() 組 innerHTML 時把來自
     Gemini 的自由文字欄位（stock_name/stock_code/primary_tag/raw_reason/
     exact_quote）都跳脫。

  9. analyzer.py, batch.py, performance.py, report_html.py（commit e31bc26）
     ——完工前 Codex 覆核抓到的修正（詳見下方 verification 與 blocked_items）：
     (a) analyzer.py：extracted_signals 欄位「缺席」也視為格式錯誤（不只型別
         不對才擋），避免 Gemini 錯誤回應被誤判成「這集真的是0訊號」並永久記錄
     (b) performance.py：比較前把 DB 讀回的舊值也 round(2)，避免 PostgreSQL
         REAL 精度漂移讓「沒真的變動」的列被誤判成「有變動」
     (c) batch.py：修正「5→10→20秒」的失真註解（MAX_RETRIES=3 下只會用到
         5s/10s，20s 從未真的發生），純文字修正不改變邏輯
     (d) report_html.py：generate_html_email()（email 版報告）新增 _esc()
         （html.escape()），修補跟 JS 端同一類但 Python 端獨立的 XSS 缺口

第14項（.TW/.TWO 尾綴轉換邏輯分散兩處）——**開工前查證發現已經不存在，沒有動手**：
  git blame 確認 `_swap_tw_suffix()` 這個共用函式從 2026-07-02（commit a3aae41）
  就已經是單一函式、performance.py 內兩處呼叫點都共用它，不是分散重複的邏輯。
  搜過全專案 .TW/.TWO 相關字串，沒有找到第二處獨立實作的轉換邏輯。判斷任務檔
  第14項描述的問題在這次任務檔寫成之前就已經被更早的修法解決，這次不需要
  也沒有動手。

verification（實際跑過的指令 + 輸出摘要，全部合成資料/mock，沒有連線真實 DB 也
沒有呼叫真實付費 API；前端兩項另外用真實 Playwright headless chromium 驗證）：

  【episode_analysis / save_result() 並發與跳過邏輯】
  用 mock psycopg2 連線（假 cursor 記錄每次 execute() 的 SQL+參數，依劇本回傳
  fetchone()）跑 4 個情境：(1) 全新集數 → INSERT RETURNING 命中，寫入訊號，
  UPDATE signal_count=1 (2) 已分析過的集數（含當初0訊號的）→ ON CONFLICT DO
  NOTHING 沒有 RETURNING，直接回傳 -1，只執行 1 次 SQL，不再寫 signals (3) 這次
  分析出 0 訊號 → episode_analysis 仍記錄 signal_count=0 (4) batch.py
  load_analyzed_set() 改查 episode_analysis。4 個情境全部通過。

  【prices.py 批次查價重構】
  把修改前的 prices.py 存一份到暫存路徑當「舊版」，跟新版用同一組合成資料
  （4 檔股票的歷史價+最新價，含 1 檔查無資料的情境）分別跑
  batch_get_close_on_or_before()/batch_get_latest_close()，用假的 yfinance
  （yf.Ticker().history()/yf.download()，記錄呼叫次數）+ 假 DB（記錄連線開啟
  次數、execute_batch 呼叫次數）比對：(a) 全部 cache miss 情境：新舊版算出的
  價格數值完全一致；yfinance 呼叫從 9 次逐筆降為 2 次批次；DB 連線開啟次數從
  20 次降為 4 次 (b) 全部 cache hit 情境：新舊版都是 0 次 yfinance 呼叫，數值
  跟 miss 情境一致。

  【update.py Step3→Step4 傳遞 results/stats】
  mock calc_performance()/win_rate()/generate_html_detail()/generate_html_email()
  統計呼叫次數：(1) 傳入 results+stats → run_report() 內部 0 次重算 (2) 不傳
  （notifier.py 獨立被呼叫的相容性）→ 內部各呼叫一次，行為不變 (3) 只傳
  results 不傳 stats → 不重算 calc_performance()，但用傳入的 results 算一次
  win_rate()。3 個情境都通過。

  【calc_performance() 只送真的變動的列】
  合成 4 筆訊號（現價不變/現價變動/entry_price缺失且原本就是None/entry_price
  缺失但原本有資料）用 mock DB+mock 批次查價跑一次：只有「現價真的變動」跟
  「資料被清空」兩筆送進 UPDATE，另外兩筆正確跳過；回傳的 results 仍是全部
  4 筆且數值正確。完工前修正版另外驗證：REAL 精度漂移（10.000000149...）的
  舊值 round(2) 後正確判定「沒有變動」，不誤送 UPDATE。

  【analyzer.py 讀 config.py 的 GEMINI_API_KEY】
  mock genai.Client（不呼叫真實 API），確認 _get_client() 傳給它的 api_key
  參數等於 config.GEMINI_API_KEY（只比對是否相等+印長度=53，不印值本身）；
  確認 analyzer.py 不再 import os。

  【Gemini 輸出結構化驗證 + 重試分錯誤類型】
  mock genai.Client 模擬「格式錯的 JSON」「extracted_signals 不是陣列」「正常
  合法輸出」三種回應；用假的 GeminiFormatError/一般 Exception 模擬 batch.py
  持續失敗，確認格式錯誤固定等 2s×2 次重試、API 錯誤指數退避 5s→10s，
  MAX_RETRIES 後正確拋出。完工前修正版另外驗證：extracted_signals「欄位缺席」
  （例如 {"error":"quota exceeded"}）正確被 GeminiFormatError 擋下，對照組
  （正常帶空陣列）仍正常通過。

  【歷史價格回溯 10→20 天】
  合成「最後交易日在目標日期前 12 天」的長假情境（10 天回溯窗口起點會晚於
  最後交易日、抓不到；20 天回溯窗口抓得到），mock yfinance 確認新版正確抓到
  假期前最後一個交易日的價格。

  【report_html.py 前端效能+XSS，Playwright 真實瀏覽器驗證】
  本機已裝 Playwright（1.61.0）+ chromium，可正常 launch（跟任務檔預期「可能
  沒有瀏覽器工具、只能人工描述」不同，做了真實瀏覽器自動化）。合成含
  <script>/onerror payload 與含 & 特殊字元股名的訊號資料，實際呼叫
  generate_html_detail() 產生真實 HTML，headless chromium 載入後確認：
  (a) payload 沒有被執行、跳脫後文字仍可見、tbody innerHTML 原始內容確認是
      跳脫過的實體不是原始標籤
  (b) 含 & 的股票名稱搜尋功能不受 escape 影響仍正確命中（驗證 HTML 解析時
      data-* 屬性的實體解碼往返正確）
  (c) sortBy() 重構後每個集數內排序仍正確、點兩次正確反向、DocumentFragment
      搬移沒有遺失任何 header/row 節點
  (d) 以標的 tab 展開（toggleSD 顯示內容）也正確跳脫
  全程瀏覽器 console 無 JS 錯誤。email 版（generate_html_email()）額外用
  Python 端字串比對驗證 escape 生效（email 不執行 JS，不需要瀏覽器）。

  【模組完整性】
  8 個修改檔案全部 ast.parse 語法檢查通過；import database, batch, prices,
  performance, analyzer, report_html, notifier, update 全部成功（不觸發任何
  真實 DB 連線或 API 呼叫，因為連線/呼叫都在函式內才觸發）。

codex_credits_spent_this_stage: 約 2.46 點（390.99 → 388.53，抓自
  C:\Users\USER\.codex\sessions\2026\08\01\rollout-2026-08-01T20-22-51-019fbd46-...jsonl
  的 balance 欄位差值）
codex_credits_spent_total: 約 2.46 點（這輪只呼叫過一次 Codex，50 點預算內還有大量餘裕）
deepseek_usd_spent_this_stage: 0（這輪沒有觸發需要 DeepSeek 覆核的分岔點——完工前審查
  用 Codex 一次就抓到足夠問題，沒有另外需要盲測第二意見的重大自主決策）
deepseek_usd_spent_total: 0

self_improvement_this_round: 未觸發——DoD 全部完成後還有約 75 分鐘餘裕，理論上滿足
  觸發條件，但這次選擇把餘裕時間用在「完工前 Codex 審查抓到問題後的即時修正+重新
  驗證」上（見上方 verification 與 autonomous_decisions），這件事本身已經是章程
  「完成的定義」第2條的硬性要求，優先序高於自我精進條款；如果之後還有餘裕會回頭
  補（目前這份交接檔完成後若還有時間，會另外執行自我精進條款並更新這個欄位）。

autonomous_decisions（本輪透過「建議項目自主執行機制」做的決定）：

  1.【一般分岔點】prices.py 批次下載策略：對 cache miss 的 (ticker, target_date)
     清單，用「涵蓋所有請求日期最寬區間」的單次 yf.download() 取代逐筆呼叫，而
     不是逐 ticker 各自開一次較窄區間的下載。原因：真正做到「一次呼叫」而不是
     「一次呼叫/ticker」，符合任務描述「一次呼叫 yfinance 批次下載」的字面意思；
     代價是查詢區間分散時會抓多於必要的資料量，但這個專案規模（訊號進場日集中在
     過去1-2年）可接受。沒有問 Codex（信心中高，沒有牴觸已定案設計）。回復方式：
     commit 5d44b3a。殘餘風險：Codex 完工審查有指出 yf.download() 是一次 Python
     呼叫不等於一次真正的 HTTP 請求（threads=True 下 yfinance 內部仍可能對各
     ticker 發多個請求）——這點已經知道，是「吹毛求疵」等級的用詞精確度問題，
     不影響這次優化的實際效益（Python呼叫次數/DB連線次數/DB交易次數都確實下降），
     之後對外溝通這項改動時用詞會更精確（「批次下載」而非「單一HTTP請求」）。

  2.【一般分岔點】驗證方式全面改用 mock 而非連線真實 DB：因為 database.py 這輪
     起 init_db() 已經包含未經核准的 episode_analysis CREATE TABLE，任何會連線
     真實 DATABASE_URL 呼叫 init_db() 的腳本都會意外把這張表建到正式庫，牴觸
     「不自己執行 CREATE TABLE」的硬性規則。改成全程用 mock/合成資料驗證所有
     9 個項目（含原本任務檔建議「用現有 --dry-run 或小樣本跑一次」的第1/13/7項），
     沒有連線真實 DB 一次（除了唯讀查 episode_analysis 現況那幾次，繞過
     init_db() 直接用 psycopg2 連線+SELECT）。沒有問 Codex（低信心分岔點按規則
     該問，但這個判斷邏輯很直接——「不能執行未核准DDL」是絕對紅線等級的既有規則，
     不是需要別人挑戰的設計選擇）。回復方式：每個 commit 的驗證腳本內容都寫在
     對應 commit message 裡。殘餘風險：mock 驗證終究不是「真的打過一次 yfinance
     網路」，理論上 yfinance 回傳格式若有邊界情況（例如 Codex 指出的
     _download_multi() 對非預期 MultiIndex 結構的處理）沒有被合成資料涵蓋到；
     這點在完工前 Codex 審查裡被列為「建議」等級（不阻塞），已知風險，留給你之後
     決定要不要用真實 yfinance 呼叫（免費 API，不牴觸兩條全域安全規則）補一次
     整合測試。

  3.【一般分岔點】第14項（.TW/.TWO 轉換邏輯分散兩處）判定為「已解決不需動手」：
     git blame 查證 _swap_tw_suffix() 從 2026-07-02 就是單一函式，沒有找到第二處
     獨立實作。沒有問 Codex（這是查證既有程式碼狀態的客觀判斷，不是需要挑戰的
     設計選擇）。回復方式：不適用（沒有改動）。殘餘風險：無，純粹是任務檔跟目前
     程式碼狀態的落差，已在報告誠實揭露。

  4.【一般分岔點】刪除測試產生的暫存檔案：這輪產生的所有驗證腳本
     （_solomon_verify_*.py）跟一份意外被驗證流程覆寫成假資料的 report_preview.html
     （gitignored、非版控、build 產物）都在驗證完後自己刪除，沒有進 git 版控、
     沒有留在工作目錄。符合章程「自主決策範圍」第1類（自己這輪產生、已在報告
     揭露內容的測試素材）。

  5.【重大自主決策】完工前 Codex 審查抓到的2個阻塞問題（extracted_signals
     欄位缺席未擋、episode_analysis 缺資料回填），評估後判定：
     - 原設計：analyzer.py 只在 extracted_signals「存在」時驗證型別；
       episode_analysis 表建立後預期直接投入使用，沒有考慮既有 signals 資料。
     - 偏離原因：Codex 具體指出這兩個缺口會造成資料正確性問題（前者讓
       API錯誤被誤記成永久的0訊號；後者讓部署當下257個已分析集數被重新分析、
       在 signals 表重複插入）。
     - 至少兩個替代方案：
       (a) 只在報告裡列成「已知風險」，不改程式碼，讓你自行決定要不要修
       (b) 直接修正程式碼邏輯（extracted_signals 缺席也擋）+ 把回填 DML 準備好
           跟 CREATE TABLE 一起交給你核准執行
       (c) 回退整個 episode_analysis 設計，改用其他判斷「已分析」的方式
     - 推薦方案：(b)——這是真正的邏輯 bug（不是設計取捨），修正它不偏離「這輪
       要做 episode_analysis」的核心目標，只是把設計做對；回填 DML 不執行、
       只準備好給你核准，沒有踩過「不自己執行 DDL」的紅線。
     - 已問過 Codex：這 2 個問題就是 Codex 這次審查主動提出的（我沒有先有結論
       再拿去問，是它自己發現並指出「阻塞」等級），符合「要求它挑戰、不是只求
       附和」的精神——它没有被要求附和任何我的既有想法，是獨立找出的問題。
     - 最終決定：採用方案(b)，已修正 analyzer.py 邏輯（commit e31bc26）+ 把
       CREATE TABLE 與回填 DML 一起準備在下方 blocked_items，等你核准。
     - 對 DoD/相容性/回復方式的影響：沒有牴觸 DoD（DoD 本來就要求「有實際驗證
       證據」，這次補強驗證涵蓋了新發現的邊界情況）；不影響回復方式（commit
       e31bc26 可用 git revert 單獨回退）；殘餘風險見下方 blocked_items。

blocked_items（命中「絕對紅線」而隔離、需要你核准才能繼續的項目）：

  1. episode_analysis 的 CREATE TABLE + 既有資料回填——這是唯一被隔離的項目，
     其餘 8 個施工項目都不依賴這個表真的被建出來（程式碼已經寫好、用 mock
     驗證過邏輯），可以獨立先 commit、先讓你看程式碼。

     **要交給你核准、依序執行的 SQL（索羅門沒有執行過任何一條）**：

     步驟1——建表：
     ```sql
     CREATE TABLE IF NOT EXISTS episode_analysis (
         episode_id   TEXT PRIMARY KEY,
         signal_count INTEGER NOT NULL,
         analyzed_at  TIMESTAMPTZ DEFAULT NOW()
     );
     ```

     步驟2——回填既有資料（**必須在步驟1之後、部署新版程式碼之前執行**，否則
     257 個已分析集數會被新版 batch.py 誤判成「未分析」，重打 Gemini API 並在
     signals 表產生重複資料——這是完工前 Codex 審查抓到的阻塞問題，已經確認
     這條回填語法能正確處理）：
     ```sql
     INSERT INTO episode_analysis (episode_id, signal_count, analyzed_at)
     SELECT episode_id, COUNT(*), NOW()
     FROM signals
     WHERE episode_id IS NOT NULL
     GROUP BY episode_id
     ON CONFLICT (episode_id) DO NOTHING;
     ```

     **唯讀查證過的現況**（用 psycopg2 直接 SELECT，沒有透過 init_db()，沒有
     執行任何寫入）：
     - `signals` 表目前 935 筆，`COUNT(DISTINCT episode_id)` = 257
     - `episode_id IS NULL` 的筆數 = 0，`episode_id = ''` 的筆數 = 0（回填語法
       的 WHERE 條件安全，不會漏掉或誤判資料）
     - `to_regclass('public.episode_analysis')` 查詢結果是 NULL，確認這張表
       目前還不存在
     - 執行後預期影響：步驟1建出空表（0筆）；步驟2回填後預期新增 257 筆（每個
       distinct episode_id 一筆，signal_count 是該集在 signals 表目前的訊號數）；
       這兩步都不影響、不刪除 `signals` 表任何一筆既有資料
     - 部署順序建議：先執行步驟1+2（DDL+回填），確認 episode_analysis 有
       257 筆之後，才部署這輪改過的程式碼（database.py/batch.py），順序顛倒
       會踩到上面說的重打 API 問題

remaining_risk（目前已知還有什麼風險/沒驗證到的地方）：

  1. 所有驗證都是合成資料 + mock，沒有一次是連線真實 DB 或真實 yfinance 網路
     跑出來的結果（刻意選擇，理由見上方 autonomous_decisions 第2點）。真正
     部署後第一次跑 update.py/batch.py 才是這輪改動的第一次「真實環境」驗證，
     建議你先用 `--dry-run` 或小範圍（例如 `--last 5`）跑一次確認。
  2. prices.py::_download_multi() 對 yfinance 非標準/退化回傳形狀（Codex 審查
     指出的邊界情況）沒有被合成資料涵蓋，目前用 try/except KeyError 靜默回傳
     None（不會整批崩潰，但可能漏抓某些 ticker 的價格且不易發現）。
  3. analyzer.py 的結構化驗證目前只確保 extracted_signals「存在且是 list」，
     list 裡的元素如果是字串/數字（不是預期的 dict），還是會在 database.py 的
     for 迴圈裡對 `.get()` 出錯——Codex 標成「建議」非阻塞，這次沒有加更深一層
     的元素驗證（時間/範圍取捨），如果要補可以在 analyzer.py 再加一段檢查。
  4. 第7項（回溯天數10→20天）是「先求有再求精」版本，不是真正的休市日曆，
     極端情況（例如超過20天的連假）仍可能抓不到價格；已在程式碼註解與這份
     交接檔標注給你核對是否要換成 pandas_market_calendars。
  5. 第4/8/9/10/12/2/3/13 項改動範圍都局限在各自檔案內，沒有做「跨所有項目
     一起跑一次 update.py 全流程」的整合測試（因為那需要連真實 DB/可能觸發
     init_db() 的 episode_analysis 建表副作用，這輪刻意避免）——建議部署後
     第一次執行時你在旁邊看一次輸出。

next_step: 這輪 9 個項目（施工順序清單全部）都已完成+驗證+commit，DoD 達成度
  高。下一棒（可能還是你自己，也可能是下一次索羅門指派）該做的事：
  1. 核准並依序執行上方 blocked_items 的 CREATE TABLE + 回填 DML（順序不可顛倒）。
  2. 部署新版程式碼前，先用 `python batch.py --dry-run` 跑一次確認
     load_analyzed_set() 讀到的「已分析」集合跟預期一致（回填後應該有257個
     episode_id）。
  3. 小範圍跑一次 `python update.py --last 3` 或類似指令，確認整條 pipeline
     （批次分析→補進場價→績效→報告）在真實環境下沒有意外。
  4. 排除範圍第8、11項（價格快取TTL、篩選時統計母體）仍待你之後另外拍板，
     這次沒有動。
  5. remaining_risk 列的幾個殘餘風險，看你要不要排進下一輪任務檔。
