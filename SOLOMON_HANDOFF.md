status: completed
monitoring_mode: 無人監督（使用者 2026-08-11 00:33 派工後離線，截止 07:30）
task_file_commit: da0ae5a（`stock-signal_TASK_2026-08-11.md`，本輪技術設計版本錨點）
commit_hash: dceed7b（本階段最後一個 commit；本輪範圍 da0ae5a..dceed7b，**已全部 push 到 origin/master**）
user_mid_session_instructions: none（派工時一次問完四題後離線，執行期間沒有再收到任何訊息）

files_changed:
- `report_html.py`（第一頁補 title/h1；第二頁 _card 重寫＋onboarding／黃框文案；第三頁 _item a11y、搜尋兩段式、錯誤分類、深連結、_footer_counts）
- `attention.py`（consensus_label 去掉括號次數與綠色；compute_attention 新增 entry_date 第二來源與丟棄警告）
- `report_detail.html` / `report_attention.html` / `report_transcripts.html`（產出物，隨版控慣例一起 commit）
- `stock-signal_TASK_2026-08-11.md`（+ .html）任務檔
- `_verify_2026-08-11/`（T1 報告、T2/T3 報告、雙審素材包與兩份原文、before/after 截圖、final_diff.patch）

verification:
- `python -X utf8 notifier.py --no-fill --no-send` 對正式 Neon 庫實跑 6 次（含改動後重產）。
  首次：689 筆訊號、684 筆送 UPDATE；第二次起「0 筆變動」＝冪等。
  執行前後逐列比對 973 筆：**不增不減**，無 DELETE/DROP/TRUNCATE。
- 第一頁定樁（國巨 EP674，看空、beat=true）：頁面顯示「✓ 跑贏大盤」、class `led-st win`、
  `個股 -46.80%｜同期 0050.TW +1.12%`。舊版同一筆會誤塗成綠色「輸」。
- 第三頁深連結端到端（用正式站檔名）：attention.html 93 個 EP 連結 →
  `transcripts.html?ep=685` → 自動展開 21,109 字、aria-expanded=true、捲動到位。
- 兩段式搜尋：標題搜尋「台積電」17/685（只下載 1 檔）；全文搜尋 446/685（含內文 429），
  進度 110→230→350→600 可見，取消鈕出現。
- 錯誤分類對照組：真 404 → `missing`；`fetch` 強制 reject → `network`；兩段訊息實測不同。
- footer 計數對照組：`_footer_counts` 全有／有缺兩種輸出實測會變。
- attention 救援三組對照：A 正常 33 檔 EP685／B 陳舊 json+救援 33 檔 EP685／
  **C 陳舊 json 無救援 28 檔 EP680（＝改動前行為，精準重現今晚踩到的狀況）**。
- console 0 errors（唯一一筆是我自己請求 EP99999 測 404 造成的）。
- `ast.parse()` 對兩支 .py 全部通過。

codex_credits_spent_this_stage: 約 2.01 點（278.6595 → 276.6502，grep balance 法）＋完工前最終審查一次（未計入，執行中）
codex_credits_spent_total: 同上，遠低於 50 點上限
deepseek_usd_spent_this_stage: 約 US$0.02（134,913 tokens，依 2026-08-01 查到的費率估算，**費率未重新查證**）
deepseek_usd_spent_total: 同上，遠低於 US$5 上限

self_improvement_this_round: 已完成一輪，正本 `self_improvement_試做/ROUND_2026-08-11.md`（+ .html）
  Part A：①查到的研究與我們的踩坑同向——LLM4FPM 靠「完整精確上下文」把誤報降 85%+；對照 8/10 因刪掉
    `escapeHtml()` 造出假 critical、今晚素材完整所以三項全中。已採用的作法：素材包一律腳本原檔切片＋行號、
    附完整檔案清單、附真實渲染文字。下一輪要補：切片每行加 `檔名:行號|` 前綴（兩位審查者引用的都是素材包行號）。
    ②成本盤點：這輪 Codex 2.01 點、DeepSeek ~US$0.02。通用省錢手法（prompt caching 30–90%）**對我們幫助有限**
    ——一次性長 prompt 沒有可重用前綴；真正的成本是「重跑」，所以省錢正解是一次問對，不是壓 token。
    已採用：第二三頁合併成一份素材問一次，省掉一次背景重述。
  Part B（3 個試做，全部隔離、未接進正式流程）：
    - trial7/7b 靜態搜尋索引可行性：把我原本「工程量不小」的空話換成數字。兩個非直覺發現——
      ①壓縮索引最有效的一刀剛好砍死最熱門查詢（台積電/NVIDIA/AI 召回 0%）②整詞索引跟現行 substring
      語意不等價會靜默漏搜；改 ASCII 2-gram 才 12/12 全 100% 召回，gzip 6.16 MB（原始 35.9 MB 的 17.2%）。
    - trial8 驗證前資料忠實度 pre-flight：把「先確認比對目標本身對不對」這條沒有機制的記憶規則變成
      跑得動的唯讀檢查（離開碼 0/1）。鑑別度測試能重現今晚的 EP681-685 缺口；今晚實際抓到 4 集重複逐字稿。
  要不要延伸成正式功能：三個選項表在 ROUND 檔末，我的傾向是索引維持現狀／pre-flight 接進 notifier.py 開頭
  ／行號前綴下次直接改，但**都等使用者決定**。

final_review: 完工前 Codex 挑戰式審查結論原文「**不建議直接合併**」，抓到 5 項，逐條回原始碼複查**全部屬實**，
  已全部修正並各自用打到失敗路徑的方式重測（commit `3850815`）。其中 2 項**推翻我自己在 commit message
  裡的宣稱**：①`entry_date` 第二來源可能偷渡 `analysis_date`（`performance.py:89` 的 fallback 就是它）
  ②「網路失敗可再點一次重試」是假的（快取寫成 null 讓重試不發請求）。第 3 項是我今晚自己加出來的顯示錯誤
  （「歷史累計 128 次（102 多／2 空）」加起來不等於 128，33 檔裡 27 檔對不起來）。詳見 T2/T3 報告第 4b 節。

autonomous_decisions:
1. 【一般】本機 episodes.json 陳舊 → 直接跑 `download_transcripts.py` 補齊（Downloaded 5／Skipped 680／Failed 0），
   而不是拿失真資料驗證。風險：造成 4 集重複檔案（見 remaining_risk）。可回復：刪掉多的那份即可。
2. 【一般】第一頁補 `<title>`／`<h1>`。原本不在任務清單，是 T1 驗證時發現的缺陷（站台首頁沒有頁名）。
   視覺零變化。回復：`git revert 8c952fa` 的該段。
3. 【一般】雙審採 blinded 而非上次的非 blinded，兩邊素材完全相同、都不含我的診斷。
4. 【重大】**下修雙審對「方向標籤 vs 括號次數」的定性**：兩邊都說是正確性 bug／必然發生，
   我用真實資料逐檔驗算得到「方向相反 0 檔、原話錯位 0 檔」，因此改判為**敘述錯配**，
   照「拆時間窗、標清楚」去改，**沒有動演算法**。若你認為應該連演算法一起改（例如括號改成近30天計數），
   回復方式：改 `report_html.py::_card` 的 `cum_txt` 與 `attention.py` 的 `bull_n/bear_n` 統計窗。
5. 【一般】兩位審查者對「onboarding 該不該常駐」意見相反，我兩邊都採：不動可關閉性，
   但把量尺說明搬進常駐黃框。
6. 【一般】`attention.py` 的第二來源選 `signals.entry_date` 而非 `analysis_date`——後者是任務檔明文禁止的
   時間基準，這次**沒有放寬**。entry_date 本質是同一個時間基準（真實上架日）的 DB 快照。
7. 【一般】push 了 4 次。**這是使用者本輪明確授權、覆蓋章程「絕不 push」的一次性例外**，
   理由是週四 08:00 排程會自動部署，不能留沒驗過的版本在 master。

blocked_items: none

remaining_risk:
1. **本機 `transcripts/` 出現 4 集重複檔案**（EP681–684 各有「獨立轉錄版」與「官方站下載版」）。
   是我補下載造成的，觸發 2026-08-02 就記錄過的已知風險。`export_transcripts_data()` 會讓後複製的覆蓋前一個
   （順序取決於 `os.listdir`）。**只影響本機，`transcripts/` 未進版控，線上不受影響。**
   依規則不自行刪使用者原始資料，清單列在 T1 報告 4b 節。
2. **正式站尚未實際跑過新版**。所有驗證都在本機（真實 DB + 真實 yfinance + 真實瀏覽器），
   但 GitHub Actions 的 `_site` 組裝與 Pages 部署這一段沒有端到端跑過。
   週四 08:00 排程會自然驗證；若要提前，手動觸發 `publish-pages.yml`。
3. **Neon 連線偶發 `SSL connection has been closed unexpectedly`**（01:00 那次）。重試即過。
   看起來是 Neon 閒置回收連線、連線池拿到死連線，`database.py::_conn()` 沒有重試機制。未修。
4. 第二頁仍沒有「點標的看歷史勝率」的直接入口（需第一頁支援 deep link，跨兩頁，沒自作主張）。
5. 手機第一屏只小勝 15px（605 → 590），說明區塊仍佔掉大半。
6. 完工前 Codex 最終審查**執行中**，結果尚未納入本檔（若有發現會另行修正並更新）。

next_step:
- 主任務（T1/T2/T3）已完工並 push；接下來是自我精進 Part A+B（隔離在 `self_improvement_試做/`）。
- 使用者早上要裁決的：①原話預設展開或收合 ②要不要投入靜態搜尋索引 ③本機 4 集重複逐字稿怎麼處理
  ④要不要提前手動觸發 `publish-pages.yml` 驗證部署。
