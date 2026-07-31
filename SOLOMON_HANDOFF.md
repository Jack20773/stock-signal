＝＝＝ 給早上檢查用的摘要（可直接取用，但請自己先核對 git log 再採信）＝＝＝

主旨建議：stock-signal 診斷完工，9 項 A 類已修完+驗證+commit，14 項 B/C 類只寫建議未動手

這是這個專案第一次被索羅門碰，紅線全部遵守：**沒有 push、沒有碰 .github/workflows/、沒有讀任何 .env* 檔案內容、沒有呼叫 Gemini API、沒有寄過任何一封信（連測試信都沒有）、沒有執行過任何 UPDATE/DELETE/DROP/ALTER**（連 `init_db()` 裡的 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 都刻意避開，唯讀 DB 檢查全部繞過 `init_db()` 直接用 psycopg2 連線+`SELECT COUNT(*)`）。

需要你知道的重要發現（不阻塞，但你應該知道）：
- **Railway DB 目前是連得上的**：935 筆 `signals`、1155 筆 `price_cache`。2026-07-27 記憶紀錄寫的「帳號停權/DB離線」現況已經改變，我已經更新記憶檔，你可以放心繼續用。
- **`stock_dict.py` 里有一項行為調整需要你知道**：公司名稱查代號現在會容忍前後空白，Codex 二輪審查抓到這個修法本身對「非字串輸入」（理論上 Gemini 不該吐出這種東西，但沒有 schema 強制保證）會不會更容易出錯，我已經補上防護，細節見下方 verification。
- **`performance.py` 有一項行為取捨我自己接受了，沒有停下來問你**：episodes.json 載入失敗後，同一次執行只試一次不再每筆訊號都重試。Codex 指出這代表「暫時網路故障、行程跑到一半自己恢復」這種情境不會再自動抓到——我評估這個 tradeoff 可以接受（原本每筆訊號都要等 15 秒逾時的代價更高，且找不到日期本來就有 fallback 機制，不影響資料正確性），標成 AI 暫定選擇讓你事後核對，理由寫在程式碼註解與下方 commit message 裡。

Codex 積分：三次呼叫共約 32.46 點（50 點標準預算內），其中第二次呼叫因為我自己把審查對象檔案路徑寫錯（打算貼一份不存在的檔案給它讀）浪費了約 14.53 點沒有產出實質審查結果——這是我的操作失誤，如實記錄，第三次修正路徑後才順利跑完。

＝＝＝ 以下是交接正文 ＝＝＝

status: completed
commit_hash: bc1b63a（本次 A 類程式碼改動唯一一個 commit，起點是昨晚 33f9756，只 commit 本地未 push）
user_mid_session_instructions: 主控 session 在等待背景任務時傳來一則中途指示，內容是要求
  「先把 video-transcribe 那段真的做完+驗證+commit 才回頭處理 stock-signal，遇到長時間指令
  要用阻塞呼叫或同一 turn 內輪詢，不要用等通知的方式結束 turn」。收到時 stock-signal 這邊
  report_html.py 已經先做了一項診斷性修改（O(n²)→O(n) 趨勢圖計算，當時是在等 video-transcribe
  的背景下載/stock-signal 的 Codex 審查時先動手的）。指示到達後：(1) 先完成 video-transcribe
  段的驗證+commit+SOLOMON_HANDOFF.md，(2) 才回頭處理 stock-signal，把那項先做的診斷性修改
  一併納入這裡完整的驗證流程與 commit（沒有留半成品，那項修改已包含在下方完整測試清單裡）。

files_changed:
  report_html.py —— import statistics；新增 _json_for_script()；趨勢圖累計勝率改先分組；
    中位數改用 statistics.median；signals_json/trend_labels_json/trend_values_json 改用
    _json_for_script()；JS daysDisp 改用 != null 判斷。
  performance.py —— 新增 _episodes_load_attempted 旗標；_fill_entry_prices() 的
    requests/retry_requests 送進批次查價前先去重。
  batch.py —— main() 新增 --last 負數驗證。
  notifier.py —— main() 新增 --last 負數驗證。
  update.py —— main() 新增 --last/--from-ep/--report-last 負數驗證；run() 讀取
    run_batch() 回傳的失敗筆數並在非零時警告。
  stock_dict.py —— 新增 _lookup()（前後空白正規化 + 非字串輸入防護）；resolve()/
    resolve_code() 改呼叫 _lookup()。

verification（實際跑過的指令 + 輸出摘要，全部用假資料/mock，沒有真實寫入 DB）：

  【report_html.py 趨勢圖 O(n) 化】
    合成 300 集 × 4 筆訊號（含隨機 None/True/False），比對修法前後兩版邏輯輸出
    → assert 完全相等，含 edge case（episode_id 為 None、無已決訊號）也一致。
    另外實際呼叫 generate_html_detail() 本身（50 集合成資料），成功產出 79137 字元
    HTML，含 SIGNALS_DATA 區塊，無例外拋出。

  【中位數修正】
    4 筆合成報酬 [10,20,30,40]（偶數筆）→ 產出 HTML 含 "+25.0"（正確：(20+30)/2），
    不是舊寫法會給的 30.0。

  【_json_for_script() 防注入】
    合成一筆 raw_reason 內容為 "</script><script>alert(1)</script>" 的訊號，產出的
    HTML 裡確認：(a) 危險字串沒有原樣出現 (b) 出現正確跳脫後的 "</script>"。
    另外直接單測 _json_for_script({'x': '</script>evil'}) → 輸出
    '{"x": "</script>evil"}'，跳脫正確。

  【JS days=0 truthiness bug】
    合成 1 筆 days_held=0 的訊號，從產出的 HTML 抓出真實 SIGNALS_DATA JSON，用 Node.js
    （v24.16.0）實際執行舊版三元運算子 vs 新版：
      days value: 0
      old (buggy) logic result: N/A
      new (fixed) logic result: 0天
    → 用真實資料 + 真的執行 JS（不是只看程式碼推理）證實修法生效。

  【performance.py 查價去重】
    完全 mock _conn/init_db/_load_episodes/batch_get_close_on_or_before/execute_batch
    （沒有碰真實 DB），合成 5 筆訊號（3 筆同一檔股票同一進場日、2 筆另一組同key）：
      第一次批次查價的 requests： [('2330.TW', '2026-01-01'), ('NVDA', '2026-01-02')]
      TEST2 PASS: 5 筆訊號（3+2 重複 key）去重後只送出 2 個獨立查價請求
      回傳補價筆數： 5（確認去重不影響每一筆訊號都有拿到結果，只是少送重複請求）

  【performance.py episodes.json 失敗快取】
    mock Path.exists()=False + urllib.request.urlopen 一律拋例外，連續呼叫 _load_episodes()
    三次：
      TEST1 PASS: episodes.json 載入失敗後只重試一次, urlopen 呼叫次數 = 1
      對照（模擬修法前行為）：3 次呼叫會發動 3 次網路請求
    → 用同一支腳本同時證明「修法前會重試 3 次」「修法後只試 1 次」。

  【batch.py / notifier.py / update.py 負數驗證】
    實際跑指令：
      python batch.py --last -1 --dry-run → argparse error，exit code 2（--last 不可為負數）
      python notifier.py --last -1 --preview → 同樣被 parser.error 擋下
      python update.py --last -1 --dry-run → 同樣被擋
      python update.py --report-last -1 --dry-run → 同樣被擋
      python batch.py --last 5 --dry-run → 正常執行，正確列出 5 集（675–680），
        確認正數輸入沒有被誤擋（回歸測試）

  【stock_dict.py 正規化 + 非字串防護】
    python -c 測試（含回歸）：
      既有查詢（台積電/輝達/查無資料）行為完全不變
      前後空白（'台積電 ' / ' 台積電' / ' 輝達 '）現在查得到
      空字串、None、純空白字串安全回傳 fallback 不拋例外
      非字串輸入（int 123）安全回傳 fallback（Codex 二輪審查抓到的邊界案例，
        補 isinstance 防護後才通過，補之前會 AttributeError）
    → 全部 assert 通過。

  【update.py 失敗筆數警告】
    純程式碼修改，讀取 run_batch() 既有回傳值（done, skipped, failed 三元組，
    原本已存在只是沒被讀），沒有新增邊界風險；沒有另外寫獨立測試腳本，
    因為改動本身就是「原本忽略的回傳值現在被讀取」，run_batch() 本身簽章
    在 batch.py 裡完全沒變。Codex 提醒「diff 本身無法證實 run_batch() 在所有
    路徑都固定回傳三元組」——已核對 batch.py 原始碼確認 run_batch() 唯一的
    return 語句就在函式最後、固定回傳 (done, skipped, failed)，沒有其他提前
    return 路徑，這個契約成立。

  【一次唯讀 DB 連線測試，繞過 init_db() 避免碰到 ALTER TABLE】
    直接用 psycopg2.connect(DATABASE_URL) + SELECT COUNT(*) FROM signals（不是
    SELECT *，沒有列出任何欄位內容，符合章程對含敏感欄位資料表的限制）：
      DB 連線成功，signals 表共 935 筆
    另一次唯讀聚合查詢（GROUP BY + HAVING，同樣不列欄位內容），驗證 B 類
    findings 第一項（database.py 同代號同方向重複未被攔截）是否已在真實資料
    顯現：
      同集數+同代號+同方向 出現超過1次的組合：0 組
      price_cache 筆數： 1155
    → 這是本輪唯一連過真實 DB 的兩次操作，全程唯讀，沒有寫入任何一筆資料。

  【Codex 完工前獨立審查，共兩次成功呼叫（另一次因我自己路徑寫錯浪費掉，見上方摘要）】
    review1（首輪唯讀診斷）：找出效能5項、正確性13項、可簡化3項，完整清單見下方
    B/C 類列表。
    review2（第三次呼叫，針對這次 A 類 diff 的完工前審查）：
      結論「沒有看到會破壞正常成功路徑的重大新錯誤」，指出兩項需處理：
      (1) episodes.json 永不重試的行為取捨 → 已在上方「需要你知道」段落說明並接受
      (2) stock_dict.py 對非字串輸入的 AttributeError 風險 → 已修正並補測試（見上方）
      _json_for_script() 的跳脫法（只跳脫 <）被確認「安全且足夠」，不需要額外跳脫
      >／&／引號（raw-text script 解析下不構成跳脫風險，唯一關鍵是 <）。

codex_credits_spent_this_stage: 約 32.46 點（三次呼叫：診斷審查 12.55 點 + 路徑寫錯浪費
  14.53 點 + 完工前審查 5.38 點，全部用 grep balance 方法反推）
codex_credits_spent_total: 約 32.46 點（上限 50 點，用掉約 65%，其中 14.53 點是我自己
  操作失誤浪費掉的，如實記錄不隱瞞）

── A 類（純本地、已修完並驗證，已 commit bc1b63a）──
見上方 files_changed + verification，共 9 項。

── B 類（需要唯讀連線驗證才能確認問題是否存在——已驗證，只寫結論，未動手改邏輯）──
1. `database.py:167-207` 的 `seen` 只攔截同代號相反方向的訊號，同代號同方向重複理論上
   會重複插入 → 唯讀聚合查詢確認：目前 935 筆真實資料裡，「同集數+同代號+同方向」重複
   的組合是 **0 組**。這代表目前資料乾淨，但不代表問題不存在——`save_result()` 目前
   確實沒有攔這種情況，只是實務上還沒踩到。要不要因此加防護是你的判斷（低急迫性）。

── C 類（需要你決定——會花錢/對外發送/改變資料/架構取捨，一律只寫建議未動手）──
效能類：
1. `prices.py:104-166` 批次查價未命中時退化成逐筆呼叫，重做 init_db/查詢/寫入，未命中
   N 筆就是 N 次 DB 往返；建議：批次函式直接一次抓完未命中價格再 bulk upsert。
2. `update.py:53-70` + `notifier.py:147` Step 3 已呼叫 calc_performance()，Step 4 的
   run_report() 又呼叫一次，重複價格查詢+全筆運算+DB 更新；建議：把 Step 3 算好的
   results/stats 傳給 Step 4，或讓 run_report() 變成唯一計算入口——這會改變兩個模組
   的呼叫介面，且 update.py 是 GitHub Actions 排程實際會跑的進入點，我判斷這是需要你
   對齊架構的變更，沒有動手。
3. `performance.py:219` + `database.py:213-240` 每次計算都對所有訊號寫回績效，即使
   價格沒變化也造成大量無效 UPDATE；建議：只更新真的變動的列，或用行情快取日期判斷
   是否需要重算——這需要「寫入前先讀出舊值比對」的新邏輯，且是 DB 寫入路徑，需要
   live 測試才能確認不會引入資料不一致，沒有動手。
4. `report_html.py` 前端 JS 篩選/排序時對每個集數重掃整個 DOM（O(集數×列數)）；
   建議：先在 JS 建 episode→rows 索引，排序用 DocumentFragment 一次掛回 DOM——這是
   純前端邏輯，但我沒有瀏覽器自動化工具可以實際驗證改動後互動行為不會壞（不像
   video-transcribe 專案已經裝好 Playwright），貿然改動有風險，只寫建議。

正確性類：
5. `batch.py:63-98` + `database.py:152-210`「已分析」用 signals 表有沒有資料判斷，
   一集分析成功但萃取到 0 個訊號時沒有完成紀錄，之後每次都會重新呼叫 Gemini API；
   建議：新增獨立的 episode 完成紀錄表。這需要 schema 變更（新表），且這個問題的
   後果是「重複呼叫付費 API」，這次任務完全不能碰任何真的會花錢的路徑，只寫建議。
6. `database.py:158-207` SELECT COUNT 再 INSERT 沒有資料庫唯一約束，兩個並發的程序
   可能都讀到 0 後各自寫入，造成同集重複訊號；建議：加唯一索引 + INSERT ON CONFLICT。
   需要 schema 變更（ALTER/CREATE UNIQUE INDEX），這次任務明確禁止任何 ALTER，只寫建議。
7. `prices.py:43-51` 歷史價格只往前找 10 個日曆日，遇到農曆年這類較長連假可能抓不到
   實際可用的前一交易日；建議：擴大回溯窗口或改用真實交易日曆。需要真實市場資料才能
   驗證抓到的日期是否正確，這次沒有做這種驗證，只寫建議。
8. `prices.py:53-64` 歷史價格快取永久有效，但除權息/股票分割/資料供應商回溯修正會讓
   舊快取失真；建議：加版本化或 TTL 重算機制。這是既有的、程式碼裡已有註解說明理由
   的架構取捨（「查無資料的股票會學不會」是刻意設計），屬於要不要改變既有設計哲學的
   決定，不是單純 bug，留給你判斷。
9. `analyzer.py:24-36` + `batch.py:35-46` 模型輸出沒有要求結構化 JSON/schema 驗證，
   而重試邏輯對「確定性錯誤」（格式錯）跟「暫時性錯誤」（逾時/429/5xx）一視同仁都重試
   3 次；建議：改用結構化輸出+分類重試。這直接碰觸會呼叫 Gemini API 的程式碼路徑，
   這次任務明確禁止任何會花錢的呼叫，連驗證修法本身都不能做，只寫建議。
10. `report_html.py` 前端 innerHTML 直接內插 raw_reason/quote/tag 等資料庫欄位（renderDetailTab/
    renderStockTab/toggleSD 三處），沒有做 HTML escape，範圍比這次已修的 `</script>`
    JSON 注入問題更廣（那個修的是「JSON 資料本身不會提前結束 script 標籤」，這個是
    「JS 組出來的 HTML 字串本身沒有對內容做 escape，直接塞進 innerHTML」）；建議：
    加一個 JS escape 函式（例如用 textContent 或 HTML entity 編碼）包住所有內插資料。
    這是更大範圍的前端改動，橫跨三個渲染函式，需要瀏覽器實際測試互動行為（篩選/排序/
    展開）沒有壞掉才能有信心，這次沒有瀏覽器自動化工具，只寫建議，不動手。
11. `notifier.py:147-162` + `report_html.py` 用 --last/--ep 篩選時，畫面標題下的
    總訊號/勝負/勝率統計仍是全集算出來的，不是篩選後的子集——**這其實不是 bug，是
    程式碼裡已經寫清楚理由的刻意設計**（"勝率永遠用全集計算,email/詳細版才不會對不上"
    這行註解就在 notifier.py:148）。Codex 認為這可能讓讀者誤判母體，是合理的 UX
    提醒，但改不改是產品判斷，不是我能自主決定的範圍，列出來給你看。

可簡化類：
12. `config.py:1-8` + `analyzer.py:12-18` + `notifier.py:26-30` .env 被載入兩次，
    且 config.py 定義的 GEMINI_API_KEY 沒有被 analyzer.py 使用（它自己重新讀
    os.getenv）；建議：統一設定來源。這個改動雖然本身很小，但緊貼著會呼叫 Gemini
    API 的程式碼路徑，這次任務對這類程式碼採取最保守處理（連小改動都不做），只寫建議。
13. `prices.py:29-101,104-166` 單筆/批次查價各自重複「查快取→取未命中→寫回」的流程；
    建議：抽出共用內部函式。這會改動 DB 讀寫路徑本身，需要 live 測試才能確認行為
    等價，只寫建議。
14. `performance.py:55-61,91-106` 台股 .TW/.TWO 尾綴轉換邏輯在補進場價的重試流程裡
    分散在兩段迴圈；建議：抽成單一函式。這段程式碼是 entry_price/stock_code 的 DB
    UPDATE 路徑的一部分，這次為求保守沒有動手（跟已修的「查價去重」不同——去重只是
    減少送出的請求數量，不改變任何 UPDATE 邏輯本身；這項是要重構寫入邏輯，風險層級
    不同），只寫建議。

remaining_risk:
  1. episodes.json 「本次執行只試一次」的行為取捨，已在上面清楚說明，AI 暫定接受，
     需要你事後核對是否認同。
  2. B 類第 1 項（同代號同方向重複）目前真實資料是乾淨的，但防護本身沒有加，理論
     風險仍在，之後累積更多資料或有並發執行時可能真的踩到。
  3. C 類 14 項全部只是建議，沒有優先序判斷——這次任務範圍要求「不需要重新設計
     任何架構」，優先序留給你白天跟主控 session 對齊時決定。
  4. `_json_for_script()` 目前只跳脫 `<`，Codex 確認這對現行瀏覽器已足夠安全，但
     沒有跳脫 U+2028/U+2029（極舊 JS 引擎的邊界案例），記錄在案不影響目前使用情境。
  5. 目錄裡大量一次性除錯腳本（check_*.py/test_*.py/verify_*.py 等）跟舊 SQLite
     備份檔完全沒有動，也沒有列入這次診斷範圍（任務檔明講不在「自主決定刪除」
     例外清單裡），如實回報現況不變。

self_improvement_this_round: 未觸發——理由跟 video-transcribe 那段一致：兩段任務都
  做完後,雖然離 10:00 還有餘裕,但今晚已經有一次因為結束 turn 等背景通知被主控 session
  糾正、以及一次 Codex 呼叫因為自己路徑寫錯浪費積分的操作失誤,這輪判斷應該把餘裕
  留給覆核前面的產出品質,不再額外觸發自我精進條款去研究新方法論。

next_step: 已完工（任務檔列的 5 項「完成的定義」全部達成：Codex 審查跑完且完整列出
  A/B/C三類、A 類全部修完並附驗證證據、B/C 類附理由明確標示未動手需你決定、只 commit
  本地未 push、完工報告已寫進本檔+待寫進 project_stocksignal.md 記憶檔+daily log）。
  建議你回來後做的事（不阻塞，AI 判斷優先序）：
    (1) 核對 episodes.json「永不重試」的行為取捨是否認同
    (2) 從 C 類 14 項裡挑你在意的，安排進之後的任務檔（這次任務範圍不含重新設計架構）
    (3) 決定要不要清理目錄裡大量的一次性除錯腳本跟舊 SQLite 備份檔（沒有列入這次
        範圍，如果你想清，下次任務檔明講即可）
