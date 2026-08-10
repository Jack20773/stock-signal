# stock-signal 索羅門任務檔 2026-08-11

> 通用章程：`D:\All claude\000_Agent\006_institution\pm_agent_solomon.md`（開工前必讀）
> 版本錨點 commit：**`da0ae5a`**（本檔第一次 commit）
> 開工時 repo HEAD：`fef73ea`（= `origin/master`，工作區乾淨，僅兩個使用者裁決保留的 untracked 檔案）

---

## 0. 基本參數

| 項目 | 內容 |
|---|---|
| 派工時間 | 2026-08-11 00:33（機器時鐘，週二凌晨） |
| **截止時間** | **2026-08-11 07:30**（使用者起床檢查）；07:00 前收尾＋寄 Email |
| **監督模式** | **無人監督**（使用者問完問題後離線） |
| 範圍目錄 | `D:\All claude\300_Projects\stock-signal\`；例外＝可寫記憶正本 `000_Agent\001_memory\` 與 daily log |
| **明確排除** | 新手包／`100_Todo\projects\youqian_deploy\` **全程不碰**（另一個 AI session 正在跑，避免撞檔） |
| **不要再提** | 前視偏差（使用者裁決「不重要，結案」）／手機第一屏（裁決「下次再說」＝待釐清，不主動催） |

## 1. 使用者當場給的授權（覆蓋章程預設，逐條記錄）

1. **正式 DB 寫入**：授權跑 `notifier.py --no-fill --no-send`，先唯讀 dry-run 再執行。
   （靜態分析確認寫入僅 `signals` 的 5 個績效欄位 + `price_cache` upsert，無 DELETE/DROP/TRUNCATE、無付費 API——證據見第 3 節）
2. **push 授權**：🔴 **覆蓋章程「絕不 push」**。可 push 修正，也可在驗證失敗時 revert 並 push。每次 push 都要寫進報告。
   理由：`update.yml` 排程 **週四 08:00（2026-08-13）** 會 checkout 新版並自動部署，不能留一個沒驗過的版本在 master。
3. **第二/三頁尺度**：**直接改，早上給成果驗收**（不是只出報告）。不滿意就 revert。
4. **剩餘時間優先序**：① stock-signal 再往下做 ② 自我精進條款 Part A+B。（「舊帳小項」使用者未選＝不做）
5. 預算：照章程標準授權 Codex 50 點、DeepSeek US$5（Part B 另計獨立 US$15）。

## 2. 任務清單（優先序由高到低）

### T1（最高，有時限）：真實 DB 端到端產出 + 三頁回歸驗證
- 1a. 唯讀 dry-run：列出 `signals` 表將被 UPDATE 的欄位現況（筆數、樣本值），存成證據。
- 1b. 跑 `python -X utf8 notifier.py --no-fill --no-send`，貼出完整 stdout。
- 1c. 驗第一頁 `report_detail.html`：勝負讀 `beat`（用國巨 EP674 看空案例當定樁）、主區「最近訊號」與收合次區「個股排行」都在、console 0 errors。
- 1d. **回歸驗證** `report_attention.html`、`report_transcripts.html`：實際產出、瀏覽器開啟、console 0 errors、關鍵元素（nav tabs／卡片／逐字稿 lazy-load）存在。
  ⚠️ 這是上次只做「靜態把關」（diff 全在 366–1319 行、三個產生器在其後）沒實跑的缺口，**靜態把關 ≠ 回歸測試**。
- 1e. 若 1c/1d 抓到 bug：修 → 重驗 → commit → push；修不好就 revert `fef73ea` 並 push，寫進報告。

### T2：第二頁 `attention.html`（關注度排序）比照第一頁方法論改造
- 2a. 先用真實產出的頁面做診斷（不是憑程式碼想像）：這頁在回答什麼問題、陌生訪客看不看得懂、有沒有跟第一頁同類的「主指標選錯」問題。
- 2b. 雙審（Codex + DeepSeek，各自獨立、**blinded**——不先把我的診斷餵給對方，避免又變成非獨立意見）。
- 2c. 依歸納結果改造 → Playwright 實測截圖 → commit。
- 2d. 改造原則沿用第一頁裁決：**讀者含陌生訪客，說明文字要更詳細不是更精簡**；台股慣例紅漲綠跌；不刪任何既有資訊，只調主次。

### T3：第三頁 `transcripts.html`（逐字稿）同上
- 同 T2 流程。注意這頁有兩層 lazy-load（中繼資料內嵌、全文 fetch `transcripts_data/EP<n>.txt`），改動別破壞這個機制。

### T4：自我精進條款 Part A + Part B
- 只有 T1–T3 的 DoD 全數達成、且距 07:30 仍有餘裕才能開始。
- 隔離在 `self_improvement_試做/` 子資料夾，不得動 T1–T3 涉及的正式檔案。

## 3. 開工前已完成的技術查證（不要重查）

`python notifier.py --no-fill --no-send` 靜態分析（subagent 讀碼，行號已附）：

- **DB 寫入**：`signals.stock_return_pct/benchmark_return_pct/beat_benchmark/days_held/perf_updated_at`（`database.py:262-267`，只更新有變動的列：`performance.py:254-256`）；`price_cache` upsert（`prices.py:89-94`）。`init_db()` 的 DDL 全是 `IF NOT EXISTS`。**無 DELETE/DROP/TRUNCATE**。
- **`--no-fill`** 關掉 `_fill_entry_prices()`（`performance.py:132-136` 的 entry_price/stock_code UPDATE 不會跑）；**`--no-send`** 關掉 SMTP 與 `latest_report` upsert（`notifier.py:231`）。
- **付費 API：零**。Gemini 只在 `analyzer.py`、DeepSeek 只在 `crosscheck.py`／`build_idiom_glossary.py`，都不在此 import 鏈。yfinance 與 episodes.json 抓取是免費網路呼叫（且本地已有 episodes.json 會優先讀本地）。
- **產出**：`report_detail.html`(`notifier.py:195-198`)、`report_attention.html`(`209-212`)、`report_transcripts.html`(`223-226`)、`transcripts_data/EP<n>.txt`(`report_html.py:1733-1742`)。三頁都是 `"w"` 整檔覆蓋。
- **原始資料**：`transcripts/`、`episodes.json` 全程只讀，無 `os.remove`/`rmtree`。

## 4. 完成的定義（逐條可驗證）

1. `notifier.py --no-fill --no-send` 用真實 DB 實跑成功，stdout 貼進報告，dry-run 前後對照存證。
2. 三頁各自在真實瀏覽器開過，**console 0 errors**，截圖存檔，路徑寫進報告。
3. 第一頁的 `beat` 勝負修正在真實資料上定樁驗證（國巨 EP674：看空、個股 -50.54% vs 0050 -0.24%、`beat=true` → 必須顯示「跑贏大盤／win」）。
4. T2/T3 的改動有 before/after 截圖對照，且「兩區都在、內容一項未刪」可被逐項核對。
5. 每階段先 commit 再往下；`SOLOMON_HANDOFF.md` 照章程格式填滿（含 `autonomous_decisions`、`blocked_items`）。
6. 記憶回寫 `000_Agent/001_memory/project_stocksignal.md`（電報體，舊項壓縮成一行）＋ daily log。
7. 07:00 前寄 Email 到 mt870908yt@gmail.com（跑 `000_Agent/005_scripts/notify_email.py`）。

## 5. 紅線（本輪維持章程原文，只有 push 一條被使用者放寬）

- 不碰密鑰、不 dump 環境變數、不對 `signals` 做 DELETE/DROP/TRUNCATE。
- 不刪使用者原始資料（`transcripts/`、`episodes.json`、`transcripts_data/`）。
- 不寄週報給訂閱者（`--no-send` 必帶；`notify_email.py` 只寄給使用者自己）。
- 不碰 `youqian_deploy/`。
- 預算上限到就停手寫報告。
