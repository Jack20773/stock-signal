# 任務：把「按公司病歷卡」（demo B）接進正式站的熱度頁 attention.html

派工：2026-09-17 21:15，主 session 遠端棒。丹尼爾 21:05 裁決（訊息 `1550130683412746366`）：「我覺得按照公司是對的 會比較有脈絡，我想要將這個加在熱度那一頁」。

## 目標（做完的樣子）
正式站 https://jack20773.github.io/stock-signal/attention.html （由 `notifier.py` 產 `report_attention.html` → `publish-pages.yml` 發布）每一張 `.att-card` 底下多兩塊：
1. **本週他怎麼講**（`weekline`）：一句話，取該標的**最近一次提到那集**的 `oneliner`／`summary` 第一句。
2. **病歷時間軸**（`<details>` 收合，預設收起）：該標的最近 6 集（依集數由新到舊），每集：
   - `EPxxx・日期（星期）`＋集名＋`順帶提到` 標籤（`substantive=false` 時）
   - 2～3 句人話 `summary`
   - 「提到當天 X 元 → 今天 Y 元 (+Z%)」（用 `prices.get_close_on_or_before(ticker, ep_date)`＋`prices.get_latest_close`；當天沒開盤就取之後第一個交易日並小字註明，跟 demo 一樣）
   - `原話備查` 再收合一層（`quote`）
   - EP 號要能點到 `transcripts.html?ep=N`（沿用現有 `_ep_link`）
   - 卡片原本的內容（分數、方向、近30天、那一句原話）**一項不刪**。
3. 手機（375px）版面不爆、深色模式不用管（正式站本來就沒有）。

demo B 的樣子（**視覺與資訊密度以它為準**）：`D:\All claude\100_Todo\drafts\daniel-demos\gooaye_v2_by_company.html`（線上 https://jack20773.github.io/daniel-demos/gooaye_v2_by_company.html ）。要求正本：`D:\All claude\100_Todo\drafts\2026-09-17_股癌週報v2_prompt規格.md`。

## 資料從哪裡來（三段）
### A. 儲存：`signals` 表加欄位（純附加，允許）
在 `database.py` 的 schema 初始化區塊比照既有 `ALTER TABLE signals ADD COLUMN IF NOT EXISTS ...` 的寫法，加：
`summary TEXT`、`oneliner TEXT`、`context TEXT`、`substantive BOOLEAN`、`quote_long TEXT`、`notes_source TEXT`（'claude-backfill' / 'gemini'）、`notes_at TIMESTAMPTZ`。
全部 nullable、不動任何既有值。執行時指令開頭要加 `CONFIRM_DB=1`（hook 會攔 ALTER；本任務屬 N9 例外①純附加，主 session 已核對條件成立）。**先用唯讀查詢確認欄位不存在再加。**
如果你查到 signals 表的主鍵／唯一鍵不是 (episode_id, stock_code) 而是一集同公司多筆，就以「該集該公司第一筆（id 最小）」當存放位置，其他筆留空；在報告寫明。

### B. 補寫舊資料（免費，用 Claude 分身）
1. 用 `attention.compute_attention(signals)`（看 `notifier.py` L200 附近怎麼餵 signals）拿到目前上榜的標的清單（約 30 幾檔）。
2. 每檔取最近 6 集（DB 依 episode 排序），列出 (stock_code, episode_id, 原句 quote, 逐字稿路徑 `transcripts/EPxxx*.md`)。母體數要印出來。
3. 這批 (code, ep) 對子依 prompt 規格寫 JSON。**你自己不要親手讀 200 筆逐字稿**：把對子切成每批 ~15 筆、每批派一個 `general-purpose` 子分身（同時最多 4 個），prompt 就是那份規格檔全文＋該批的清單＋輸出 JSON 路徑（scratchpad）。子分身**只讀 transcripts、只寫 JSON**。
4. 收回 JSON → 用 python 逐筆 `UPDATE signals SET summary=..., ... WHERE id=...`（只填新欄位、只填 NULL 的列；指令開頭 `CONFIRM_DB=1`；先 dry-run 印「將更新 N 筆／母體 M 筆」）。
5. 對照組（驗證必做）：隨機抽 5 筆，把 JSON 的 summary 跟逐字稿那段對一眼，確認不是編的；`found=false` 的筆數印出來，這些 summary 留 NULL、頁面顯示「這集只有一句原話」而不是空白。

### C. 以後每週自動寫（Gemini 順便）
`prompt.py` 的抽取 prompt 已經每集叫 Gemini 讀整份逐字稿抽 signals。在同一個輸出 schema 裡，每個 signal 多要四個欄位：`summary`（2～3 句、每句≤40字、只寫他講的、不下看好看壞）、`oneliner`（≤25字）、`context`（≤20字）、`substantive`（bool）。規格文字直接從 prompt 規格檔搬（保留「不編造」「不替他下結論」兩條）。`database.py` 存 signals 時把這四欄一起寫進去，`notes_source='gemini'`。
- 改完用一集**既有逐字稿**跑一次 dry-run（不寫 DB、不寄信）看 Gemini 回得出這四欄；貼一筆輸出當證據。
- 這一步會讓每週那通 Gemini 多吐一些 token，主 session 已跟他講過「帳單幾乎不變」，你**不要**另外跑大量 Gemini 呼叫做回填（回填走 B）。

## 渲染
改 `report_html.py::generate_html_attention` 的 `_card`：
- `rows` 每筆要多帶 `history`（list of dict：ep, date, title, summary, oneliner, context, substantive, quote_long, quote, px_on, px_now, px_note, chg_pct）。資料組裝放在 `attention.py` 或新 `company_notes.py`（唯讀 DB＋prices），不要把 SQL 塞進 report_html。
- 股價：batch 拿（`prices.batch_get_close_on_or_before`），有快取表就用，避免每次 build 打 200 次 yfinance。抓不到就顯示「股價暫無」，不能讓整頁掛掉（try/except，比照 notifier 對 attention 的容錯）。
- 樣式沿用 demo B 的 `.hist`／`.weekline`／`details.q`，顏色改成正式站現有配色（#2b6cb0 藍、#1a252f 深）。

## 驗證（全綠才推）
1. `python -X utf8 notifier.py` 的產生 attention 那條路徑（找一個不寄信、不推 DB 的入口；沒有就寫 `ops/build_attention_only.py`，唯讀）→ 產出 `report_attention.html`。
2. `node --check` 不適用（純 HTML）；用 Playwright 開本機檔案截 375px 與 1280px 各一張，放 scratchpad，報告附路徑。
3. 對照組：把 `history` 故意清空跑一次，頁面要退回原本卡片、不報錯；再把某檔 summary 設 NULL 跑一次，要看到「這集只有一句原話」。
4. `python -X utf8 check_site_payload.py`（既有的站台 payload 檢查）通過。
5. 數字：報告寫「上榜 N 檔／時間軸 M 條／summary 有值 K 條／股價抓到 P/M」，每個數字附產生它的指令。

## 上線
- git：`stock-signal` repo commit（訊息中文、一行說明＋Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>）＋ push；然後 `gh workflow run publish-pages.yml --repo Jack20773/stock-signal`，等 ~9 分鐘（**一次等 600 秒再查，不要密集輪詢**），`gh run list --workflow=publish-pages.yml --limit 1` 成功後 `curl -s https://jack20773.github.io/stock-signal/attention.html | grep -c "hist"` 要 > 0。
- **不要**碰 `ops/backtest_hold.flag`、不要動 `report_html.py` 的其他頁、不要改寄信內容。
- 已知資料錯（不要在本任務修，寫進報告就好）：EP567「兆利」被記成 `3376.TW`（新日興）、EP591 代號混淆。

## 禁止
- 不跑會印環境變數的指令；DB 連線只透過 `database.py` 既有函式或既有的 env 讀法。
- 不對 signals 跑 `SELECT *`——點名欄位。
- 不 DELETE／DROP／覆蓋既有值。
- 不另開 Gemini 批次回填。

## 回報格式（給主 session，精確優先）
1. 三行結論：上線了沒／網址／哪裡跟 demo B 不一樣。
2. 數字＋指令（見驗證 5）。
3. 改了哪些檔（路徑＋一句）。
4. 沒做到的、殘留物、發現的坑。
