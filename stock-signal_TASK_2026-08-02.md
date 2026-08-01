# stock-signal 索羅門任務檔 — 2026-08-02

> **本輪（2026-08-01 19:47 派工，2 小時窗口）版本錨點 commit：`55a463e`**——判斷是否偏離已定案技術設計時拿這個當客觀對照。
> 讀完本檔前，先讀通用章程 `D:\All claude\000_Agent\006_institution\pm_agent_solomon.md`。
> 本輪背景：上一輪（2026-08-01，commit `bc1b63a`）Codex 審查抓到 21 項，A 類 9 項已修完，B 類 1 項已唯讀驗證乾淨，**C 類 14 項這次要正式排入實作**（完整原文列在 `SOLOMON_HANDOFF.md` 舊版——已被本檔覆寫前的內容，git log 可查 `bc1b63a` 當時版本）。

## 0. 這次跟上一輪不同的地方（紅線放寬，使用者 2026-08-02 明確裁決）

上一輪任務檔明講「C 類全部只寫建議不動手」。**這次使用者已裁決全部放寬**，包含：
- 允許 DB 寫入路徑重構（含 live 測試）
- 允許 schema 變更（ALTER / CREATE INDEX / CREATE TABLE）
- 允許碰觸與 Gemini API 呼叫相鄰的程式碼（設定載入、重試邏輯等）

**但兩條全域安全規則不因這次放寬而失效，這是主控 session CLAUDE.md 的硬性規定，索羅門章程也管不到：**
1. **絕不呼叫真正會花錢的 Gemini API**（含為了驗證修法而測試呼叫）。第 9 項的程式碼可以改，但驗證只能用 mock/假資料跑過邏輯分支，不能真的打 API。如果不 mock 就無法驗證，寫進報告标记「需要你確認要不要花一次 Gemini API 費用來驗證」，不要自己決定呼叫。
2. **正式資料庫的破壞性 schema 變更（ALTER/CREATE INDEX 等）先 dry-run**：把要跑的 DDL 語法、以及唯讀查詢確認過的「執行後預期影響（例如目前資料是否已符合新約束）」寫進 `SOLOMON_HANDOFF.md`，**不要自己執行 ALTER**。這條是既有全域規則（正式 DB 破壞性寫入需先給使用者看 dry-run 才能執行），沒有被這次「放寬 C 類紅線」的裁決取代——放寬的是「可以設計方案」，不是「可以繞過使用者看一眼 DDL 就下手」。第 6 項因此分兩階段見下方。

## 1. 任務清單（技術設計已定案的部分；沒定案的會標注「AI 暫定，需你核對」）

### 效能類
1. **`prices.py` 批次查價退化成逐筆呼叫**：改成收集所有 cache miss 的 (ticker, ref_date) 清單後一次呼叫 yfinance 批次下載，收集完再一次 `execute_batch` bulk upsert 進 `price_cache`，不逐筆重跑 `init_db()`。驗證：用現有 `--dry-run` 或小樣本跑一次，比對新舊版本輸出的價格數值完全一致 + 記錄呼叫次數/耗時前後對比。
2. **`update.py`/`notifier.py` Step3/Step4 重複算 `calc_performance()`**：`run_batch()` 算完的 `results`/`stats` 明確傳給 `run_report()`（新增可選參數，預設 `None` 時保留原本自己重算的行為，維持 `notifier.py` 獨立被呼叫時的相容性）。驗證：跑一次 `update.py --last 5`，比對傳入版與獨立重算版算出的 stats 數字一致。
3. **`performance.py`/`database.py::save_perf_results()` 全量 UPDATE**：寫入前先讀出該筆訊號現有的 `stock_return_pct`/`beat_benchmark`/`days_held`，跟新算出的值比較，只有真的不同才放進這次 `execute_batch` 的 updates 清單。驗證：跑一次全量 `performance.py`，記錄「送出的 UPDATE 筆數」在修法前後的差異，並抽查幾筆確認值沒有算錯。
4. **`report_html.py` 前端 JS 篩選/排序 O(集數×列數)**：建立 `episode → rows` 的 Map 索引，排序完用 `DocumentFragment` 一次掛回 DOM。**驗證方式待定**——先查專案或 `video-transcribe` 是否已裝 Playwright 可重用；如果找不到瀏覽器自動化工具，這項改完只能人工描述邏輯正確性，不能宣稱「已驗證互動行為」，完工報告要如實標注「前端邏輯改了但沒有自動化瀏覽器驗證」。

### 正確性類
5+6. **（合併設計）episode 完成紀錄 + 同集重複寫入的並發保護**：新增 `episode_analysis` 表：
   ```sql
   CREATE TABLE IF NOT EXISTS episode_analysis (
       episode_id  TEXT PRIMARY KEY,
       signal_count INTEGER NOT NULL,
       analyzed_at TIMESTAMPTZ DEFAULT NOW()
   )
   ```
   `save_result()` 改成：先 `INSERT INTO episode_analysis (episode_id, signal_count) VALUES (%s, 0) ON CONFLICT (episode_id) DO NOTHING RETURNING episode_id`——沒有 RETURNING 任何列代表這集已經被處理過（不管當初萃取到 0 個還是多個訊號），直接跳過；有 RETURNING 才繼續原本的訊號迴圈寫入 `signals` 表，最後 `UPDATE episode_analysis SET signal_count=%s WHERE episode_id=%s`。`batch.py` 判斷「已分析」改成查 `episode_analysis` 而不是 `signals` 表是否有資料。**這個設計同時解決第5項（0訊號集數不再每次重跑）跟第6項（PRIMARY KEY 天生防併發重複插入，比原本的 SELECT COUNT 再 INSERT 更安全）**。
   **AI 暫定，需你核對**：這張表的 CREATE TABLE 屬於本輪已放寬的 schema 變更範圍，但仍照上面「0. 」的規則——索羅門只把 DDL 語法+唯讀確認過的現況（例如目前 `signals` 表裡各 `episode_id` 分佈、有沒有已知 0 訊號集數）寫進 `SOLOMON_HANDOFF.md`，不自己執行 `CREATE TABLE`；同理 `save_result()`/`batch.py` 的程式碼可以先寫好並用測試資料庫或 mock 驗證邏輯，但正式庫的表要等你看過 dry-run 報告才建。
7. **`prices.py` 歷史價格只回溯 10 個日曆日**：改用固定的台股/美股休市日曆（可以先用 `pandas_market_calendars` 套件，若專案依賴裡沒有要先確認能不能加新套件屬於低風險），或退而求其次把回溯天數從 10 天加大到 20 天（涵蓋農曆年連假）當作先求有再求精的版本。驗證：用已知的歷史長假期日期（例如今年農曆年期間的日期）跑一次回溯邏輯，確認能抓到假期前最後一個交易日的價格。
8. **價格快取永久有效、無 TTL**：**排除本輪範圍，不實作**——這是程式碼裡已有註解說明理由的既有設計哲學決定（除權息/分割回溯修正取捨），紅線放寬只涵蓋「技術風險」，不涵蓋「要不要推翻既有產品設計」這種本質是使用者決定的事。列在這裡是完整交代 14 項的去向，不是要索羅門動手。
9. **Gemini 輸出無結構化驗證、重試不分錯誤類型**：程式碼可以改（區分「格式錯誤」vs「逾時/429/5xx」分開處理重試邏輯），但**驗證只能用 mock Gemini 回應（模擬格式錯的 JSON、模擬 429 錯誤）跑過分支，不能真的呼叫付費 API**。如果 mock 測不出信心，如實寫進報告，不要為了驗證去真的呼叫。
10. **`report_html.py` 前端 innerHTML 未 escape（XSS 風險）**：三處渲染函式（`renderDetailTab`/`renderStockTab`/`toggleSD`）加一個 escape 函式包住內插資料。同第4項，**驗證方式待定**——沒有瀏覽器自動化工具的話，只能人工檢查邏輯（例如寫一個帶 `<script>` 字元的假資料跑過 escape 函式確認輸出被正確轉義），不能宣稱互動行為全部驗證過。
11. **篩選時統計母體仍是全集不是子集**：**排除本輪範圍**——程式碼已有註解明講這是刻意設計（避免 email/詳細版數字對不上），Codex 認為可能讓使用者誤判但這是 UX 判斷不是 bug，同第8項性質，需要你另外決定要不要改，不排入這輪索羅門任務。

### 可簡化類
12. **`.env` 重複載入 + `config.py` 定義的 `GEMINI_API_KEY` 沒被 `analyzer.py` 使用**：統一設定來源，`analyzer.py` 改讀 `config.py` 而不是自己重新 `os.getenv()`。驗證：跑一次 `analyzer.py`（用既有測試逐字稿或 mock，不呼叫真實 Gemini）確認能正確讀到 API key 變數（不印出值，只確認非空/長度合理）。
13. **`prices.py` 單筆/批次查價重複「查快取→取未命中→寫回」流程**：抽出共用內部函式。這跟第1項是同一個檔案，**建議跟第1項一起做**，避免抽函式跟批次重構互相打架要改兩次。驗證：跟第1項共用同一組驗證（新舊版本輸出價格數值一致）。
14. **`performance.py` 台股 `.TW`/`.TWO` 尾綴轉換邏輯分散兩處**：抽成單一函式。驗證：對已知需要 fallback 的股票代號（`stock_dict.py` 記錄過的踩雷案例，例如原本上櫃股）跑一次補價流程，確認結果跟修法前一致。

## 2. 明確排除本輪範圍（不是紅線問題，是產品設計決定，需要你之後另外拍板）
- 第8項：價格快取要不要加 TTL
- 第11項：篩選時統計母體要不要跟著子集變動

## 3. 建議施工順序（AI 暫定，你可以調整）
1. 5+6（episode_analysis 表，先寫 DDL + 程式碼，最後才是否 CREATE TABLE 交你決定）——影響範圍最大，最先做完才有餘裕測試
2. 1+13（prices.py 批次查價重構，一起做）
3. 2（update.py/notifier.py 傳遞 stats，避免重複計算）
4. 3（performance.py 只更新有變動的列）
5. 14（.TW/.TWO 抽函式）
6. 12（.env 統一來源）
7. 9（Gemini 重試分類，mock 驗證）
8. 7（歷史價格回溯窗口）
9. 4、10（前端兩項，視有無瀏覽器工具決定要不要做/怎麼驗證）

## 4. 範圍限定
只能動 `D:\All claude\300_Projects\stock-signal\` 目錄底下的檔案；例外只有依通用章程要追加的記憶檔。

## 5. 截止時間
**2026-08-01 19:47 派工，截止 2026-08-01 21:47（僅 2 小時，不是隔夜整晚）**。使用者當下在線、預期這 2 小時內會回來查看 → **監督模式：有人監督**。

**這次跟隔夜模式不同的地方**：使用者已裁決這 2 小時照原本「衝擊最大項優先」邏輯派工，即使可能整段時間卡在單一項目、後面小項完全沒空做也接受這個風險。順序：
1. 先攻第 5+6 項（`episode_analysis` 表設計＋程式碼，只寫 DDL 草稿與程式邏輯，**不執行 `CREATE TABLE`**——這條全域規則不因 2 小時或有人監督而放寬，見上方第 0 節）。
2. 如果 21:47 前這項做完（含驗證），剩餘時間依「建議施工順序」清單往下挑（2 → 1+13 → 3 → 14 → 12 → 9 → 7 → 4/10），做多少算多少，不用每項都做完。
3. **21:47 到期時，不管做到哪都要停手收尾**：commit 目前進度、寫好 `SOLOMON_HANDOFF.md`（`status` 依「監督模式」一節的定義填，`next_step` 清楚寫下一棒接手時該從哪個子項目、哪一步繼續），不要為了趕完一項而拖過截止時間。
4. 有人監督模式代表：真的命中「絕對紅線」或「重大自主決策」缺 Codex 覆核時，可以嘗試用 SendMessage 問主控 session；但因為只有 2 小時、使用者不一定秒回，**沒把握使用者會即時回覆就直接套用無人監督的隔離做法**（標記這個子任務 blocked，繼續做不依賴它的其他項目），不要在原地空等到截止時間。

## 6. 完成的定義
1. 施工順序清單裡的每一項，能做的都做完（受限於「不能真的花錢/不能自己下 ALTER」的兩項例外，那兩項改成「程式碼寫好+設計文件+DDL草稿」也算完成）。
2. 排除範圍（第8、11項）維持不動，不擅自實作。
3. `episode_analysis` 表的 `CREATE TABLE` 語法與影響分析寫進 `SOLOMON_HANDOFF.md`，等你看過才建。
4. 每個子項目都有實際驗證證據（跑過的指令+輸出），不是「應該沒問題」。
5. 完工報告清楚標注：真的完成 vs 因為兩條全域安全規則卡住只能做到「設計完成待你拍板」的項目。
