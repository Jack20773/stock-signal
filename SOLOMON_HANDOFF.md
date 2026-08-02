status: completed
monitoring_mode: 無人監督
task_file_commit: 6be5125
commit_hash: a04060d
user_mid_session_instructions: |
  1. 主控 session 於執行中途（EP681 剛開始 transcribe 階段時）介入，指出我用
     Bash run_in_background + 等通知的方式跑 sync_independent_transcripts.py，
     違反通用章程「隔夜特別要注意的執行紀律」——背景 subagent 不會被自己啟動的
     OS 層級行程自動叫醒。收到後立即改成同一個 turn 內阻塞式輪詢等待，直到腳本
     真正跑完才繼續，之後全程比照辦理，沒有再用背景+等通知的模式跑長流程。
  2. 主控 session 另傳達使用者裁決：截止時間由 23:09 改為 23:00；自我精進條款
     Part A/B 有新版規則。當時因主線任務（1a-1e）雖已全數完成，但完工前 Codex
     審查又抓到需要處理的重大問題，時間全部用於處理這些問題，尚未進入自我精進
     環節。
  3. 主線 DoD 完工後，主控 session 傳達已完成獨立核對（git commit範圍/EP677
     URL/batch.py --dry-run/Codex花費/程式碼抽查/沒push沒碰DB 皆核對通過），
     並確認「有時間的話就執行閒置計畫」的條件成立（20:12，離23:00還有約2小時
     48分鐘），指示進入自我精進 Part A/B，且提醒不要再用背景+等通知模式跑長
     流程（同一提醒的第二次）。已依指示完整執行 Part A/B，見下方
     self_improvement_this_round 與 self_improvement_new_ideas。
files_changed: |
  新增：
  - independent_transcribe.py（1a 格式橋接模組：.srt→.md 轉換 + video-transcribe
    外部 CLI 呼叫包裝）
  - sync_independent_transcripts.py（1b-1e：三方比對缺口偵測 + 缺口補齊 +
    交叉驗證 + 可重複執行的整合腳本）
  - docs/independent_transcript_diffs.md（1d 交叉驗證差異紀錄，純附加，git 追蹤）
  - self_improvement_試做/（自我精進 Part B 試做，5個檔案，隔離不影響任何 DoD
    正式檔案，git 追蹤——內容不是 whatmkreallysaid.com 逐字稿也不是密鑰，屬於
    程式碼與研究筆記，進 git 沒有敏感性疑慮）
  修改（純文件/註解更正，不改邏輯，commit f43a64d）：
  - independent_transcribe.py（自我精進 Part B 試做2意外發現：精確計數後 EP680
    真實逐字稿只有2個內容逗號，先前文件誤把SRT時間碼本身的逗號算進去，更正說明）
  新增（transcripts_data/，gitignore 不進 git，比照既有慣例）：
  - transcripts_data/independent_transcribe/manifest.json（獨立轉錄留痕）
  - transcripts_data/independent_media/EP681~684/（下載的影片+.srt/.ass/.mkv，共547MB）
  新增（transcripts/，gitignore 不進 git，比照既有慣例）：
  - transcripts/EP681_再一次相信真愛存在的機會.md（20,808字）
  - transcripts/EP682_魂系 everywhere.md（19,263字）
  - transcripts/EP683_一個月前的自己對未來寄予厚望.md（20,365字）
  - transcripts/EP684_終於可以喘一下.md（19,282字）
  順便修復：transcripts/EP677_四代同堂槓桿論與研報獵巫記.md（用既有
  download_transcripts.py 從 whatmkreallysaid.com 正常下載補齊，非獨立轉錄，
  詳見下方「EP677 查證結論」）
verification: |
  === 1a 格式橋接 ===
  用既有 media/EP680_v2/source.srt（2小時真實 podcast，1917筆cue）轉換測試，
  確認 srt_to_md() 能正確產出符合 transcripts/*.md 既有格式（# 標題+段落）的
  純文字。轉換前 SRT 片段：
    1
    00:00:00,000 --> 00:00:01,520
    歡迎收聽古愛,我是聖木工
  轉換後 .md 片段（無時間軸、合併成段落）：
    # EP680 筷子信仰與台積電心碎記
    歡迎收聽古愛,我是聖木工本期節目由喬志勇國際有限公司贊助太熱了,夏天全民運動...
  batch.py --dry-run 對真實新增的 EP681-684 驗證：
    待處理：4 集（681–684）
    [1/4] EP681 — 待跑（dry-run）
    [2/4] EP682 — 待跑（dry-run）
    [3/4] EP683 — 待跑（dry-run）
    [4/4] EP684 — 待跑（dry-run）
    dry-run｜共 4 集｜待跑 4｜已跳過 0
  全集 dry-run（確認沒有破壞既有 684 集含新集數的判斷）：
    dry-run｜共 684 集｜待跑 423｜已跳過 261

  === 1b 缺口偵測 ===
  yt-dlp --flat-playlist 對 @Gooaye 頻道抓完整清單，共 683 部影片，EP 編號解析
  100% 成功（683/683，抽查遠超過任務檔要求的 10 筆）；唯一「找不到」的是
  EP232 整個不在 YouTube 清單裡（不是解析失敗，是 whatmkreallysaid.com 有但
  YouTube 頻道本身沒有這部影片，猜測後來被下架/設非公開，不影響本輪偵測結果）。
  標題格式實測是「EPxxx | <emoji>」，跟任務檔原本假設的「Gooaye 股癌- EP629」
  格式不同（已在程式註解與下方誠實記錄這個落差）。
  三方比對結果：
    YouTube 共 683 集（EP1–EP684）
    本地 transcripts/ 共 680 集，episodes.json（鏡像 whatmkreallysaid.com）共 680 集
    YouTube 有、但本地與 whatmkreallysaid.com 都沒有的集數（共 4 集）：[681, 682, 683, 684]
  EP677 查證結論（推翻任務檔原本的假設）：直接對 whatmkreallysaid.com 發 HTTP GET
  查證，得到 HTTP 200、54,965 bytes 的正常內容（不是 404）——**EP677 不是雙方都缺
  的真缺口，只是本地端之前沒下載到**（episodes.json 裡本來就有這筆資料）。已用
  既有 download_transcripts.py 正常下載補齊（一般缺口，不需要獨立轉錄）：
    [ 677] OK     EP677 (2026-07-08)  53.7 KB
    Done.  Downloaded: 1  Skipped: 679  Failed: 0
  真正的三方缺口只有 EP681-684（YouTube 上架時間比 whatmkreallysaid.com 更新頻率快
  的自然現象，不是對方停更或缺漏）。

  === 1c 缺口補齊 ===
  對 EP681/682/683/684 執行獨立轉錄（video-transcribe 本地 yt-dlp 下載 +
  faster-whisper large-v3-turbo 轉錄），全部成功寫入 transcripts/。
  過程中兩次 yt-dlp 下載遇到 HTTP 403（YouTube bot 檢測/缺 JS runtime 警告），
  重跑後成功，判斷為暫時性節流（同一批影片有的成功有的失敗，非系統性問題）。
  轉錄耗時：50分鐘節目約 2-3 分鐘（GPU RTX 5070 Ti），下載約 10-30 秒，遠快於
  預估。EP681 檔案內容片段：
    # EP681 再一次相信真愛存在的機會
    歡迎收聽古愛,我是孟公本期節目由尼古清贊助戒菸如同投資,需要放棄短線刺激與快感...
  batch.py --dry-run 驗證見上方 1a 區塊（4 集皆列「待跑」非「忽略」）。

  === 1d 交叉驗證（最新2集）===
  YouTube 最新 2 集為 EP683/EP684。查 episodes.json（whatmkreallysaid.com 鏡像）
  確認對方尚未收錄這兩集 → 依任務檔明文指示「如果這2集剛好whatmkreallysaid.com
  也還沒有，就自動併入1c的缺口補齊流程處理，不用勉強做比對」，兩集均已在上方
  1c 用獨立轉錄直接處理完成，**沒有可比對的 whatmkreallysaid.com 版本，因此沒有
  產生真正的交叉驗證紀錄**——這是誠實結論，不是漏做。
  另外用 EP680（雙方都已有的舊集數）做了一次端到端機制驗證，證明交叉驗證管線
  （_fetch_remote_md/compare_paragraphs/_append_diff_report，都是實際會在未來
  真實交叉驗證時用到的同一套函式，不是重寫的等價邏輯）真的能正常運作、正確寫入
  docs/independent_transcript_diffs.md：
    整體字元相似度：87.39%（誠實邊界：這是含標題/標點的粗略對齊比對，見下方限制）
    差異區塊數：1（因兩邊分段方式不同，整篇被判成一大塊 replace，見殘餘風險）
  此測試在報告裡明確標注「不是真正待審閱的差異，只是機制驗證」，不會誤導成
  EP680 有問題。

  === 1e 可重用觸發腳本 ===
  sync_independent_transcripts.py 完整跑過 3 次（首次全跑、修 bug 後重新產出、
  idempotency 驗證），log 範例（最後一次 idempotency 驗證）：
    === 步驟 1：抓 YouTube 頻道集數清單 ===
    YouTube 共 683 集（EP1–EP684）
    本地 transcripts/ 共 684 集，本地 episodes.json（鏡像遠端）共 680 集
    === 步驟 2：三方比對結果 ===
    沒有發現任何缺口
    YouTube 最新 2 集：[683, 684]
    === 步驟 3：處理 2 集 ===
    [ 684] SKIP   EP684（transcripts/ 已有檔案 EP684_終於可以喘一下.md）
    [ 683] SKIP   EP683（transcripts/ 已有檔案 EP683_一個月前的自己對未來寄予厚望.md）
    Done. OK=0 SKIP=2 FAIL=0
  **明確聲明：這支腳本目前需要手動執行，本輪未設定任何常駐/自動排程（Windows
  Task Scheduler 等）。之後如果要接自動排程，需要另外跟使用者確認執行頻率與方式**
  ——這是任務檔第1e節明文要求的聲明，不是本輪自己決定要不要做。
codex_credits_spent_this_stage: 8.13（344.8726750000 → 336.7425550000）
codex_credits_spent_total: 8.13
deepseek_usd_spent_this_stage: 約US$0.02（自我精進Part B試做用，56,490 tokens累加估算，
  遠低於Part B獨立US$15上限；DoD主線本身未呼叫DeepSeek）
deepseek_usd_spent_total: 約US$0.02
self_improvement_this_round: |
  觸發並完整執行（主控 session 20:12 確認條件成立、指示進入，DoD 6項此時已
  100% 完成並經主控 session 獨立核對通過）。

  === Part A（效率/成本研究，已小幅自調，記在 project_pm_agent_solomon.md
  不是章程本身）===
  WebSearch 查「LLM token優化」+「AI coding agent驗證/防幻覺」，找到兩個可
  自行採用的習慣：
  1. Codex 審查 prompt 避免整段貼 diff（Codex 自己有 shell 能重新讀檔驗證，
     這輪貼了 605 行 diff 進 prompt 是重複的 token 浪費）——以後改成只描述
     背景+具體要挑戰的設計決策，讓 Codex 自己 `git diff` 讀取。
  2. 驗證改用 hash/exact-match 而非純肉眼比對 diff 摘要——這輪 Part B 試做1
     直接示範了這個做法的價值。
  來源：[LLM Token Optimization 2026](https://redis.io/blog/llm-token-optimization-speed-up-apps/)、
  [Stop AI Agent Hallucinations](https://dev.to/aws/5-techniques-to-stop-ai-agent-hallucinations-in-production-oik)。

  === Part B（3個新想法+多次試做）=== 詳見下方 self_improvement_new_ideas。
self_improvement_new_ideas: |
  三個想法全部隔離在 stock-signal/self_improvement_試做/（git 追蹤，5個檔案，
  未修改任何 DoD 正式檔案——唯一對正式檔案的觸碰是試做2意外發現後的
  independent_transcribe.py 純註解更正，commit f43a64d，已在 files_changed
  說明）。三個想法各試做1輪（想法2實際做了3次迭代：短句切分→n-gram覆蓋率→
  跟DeepSeek討論CER指標），每次都跟 DeepSeek 討論（read-only 顧問角色），
  總計5次DeepSeek呼叫（含1次連線測試）約56,490 tokens，估算花費約
  US$0.02（遠低於 Part B 獨立 US$15 上限，估算方式：tokens累加乘
  deepseek-v4-flash混合費率，見「硬性預算與範圍界線」第1項）。

  === 想法1：本機LLM幫ASR逐字稿加標點（來源：ASR punctuation restoration
  研究領域，[arxiv 2606.05179](https://arxiv.org/abs/2606.05179) 等） ===
  背景動機：這輪主線任務實測 faster-whisper 中文輸出幾乎無標點（見殘餘風險
  第4點），讀起來生硬。
  可行性：技術上完全可行（本機 Ollama qwen2.5:14b-instruct 本來就在跑，
  video-transcribe 已用它做翻譯，不需新裝套件/新下載模型）。
  試做內容：`trial1_punctuation_restore.py`，取 EP681 一段~550字獨立轉錄，
  丟給 Ollama 加標點，看 `trial1_demo_output.txt`。
  **實測發現（重要）**：標點加得正確合理，但意外把「戒菸/電子煙/加熱煙/煙影」
  全部竄改成「戒菜/電子菜/加熱菜/菜影」（同音異字漂移，違反 prompt 明確要求的
  「不要改動文字內容」）。用 `trial1_verification_result.txt` 記錄的「去標點後
  逐字比對」驗證機制成功攔截這個錯誤（第223字元位置起偵測到差異）。
  DeepSeek討論摘要：確認這是「原地編輯型任務」LLM重寫本質的高發問題（模型是
  自迴歸重新生成不是原地插入，跟溫度/量化關係較小），逐字比對可以可靠**攔截**
  但不能**防止**；要真正保證不改字需要 constrained decoding（Ollama 本身
  不支援，需換 SGLang/vLLM）；正式功能建議改核心用「標點還原」專用模型
  （如 FunASR CT-Transformer，架構上就無法竄改文字），LLM 只當語意斷句
  fallback。
  **延伸方向選項（供使用者裁決，不是索羅門能自己拍板）**：
    (a) 不追加此功能，維持現狀（獨立轉錄結果保持無標點，忠實度優先）
    (b) 加值功能：用「LLM加標點 + 逐字比對驗證，不通過就丟棄該次結果、
        改保留無標點原文」的組合，作為獨立轉錄後處理的可選步驟（風險可控，
        因為有驗證閘門，即使失敗也不影響正確性，只是有時候拿不到標點加值）
    (c) 正式投入：換用專用標點還原模型（需要額外調查/安裝，成本較高，
        但架構上更可靠、不需要逐字比對這個安全網）

  === 想法2：改善 compare_paragraphs() 的差異對齊粒度（來源：文本對齊研究，
  [SentAlign/Vecalign](https://arxiv.org/pdf/2509.18360) 等embedding對齊文獻）===
  背景動機：完工前 Codex 審查指出正式版 compare_paragraphs() 在段落粒度比對，
  兩邊分段方式不同時容易整篇被判成一大塊「replace」，診斷價值低（見殘餘風險
  第2點）。
  可行性：文獻建議的 embedding+動態規劃做法這輪環境沒有現成中文 embedding
  服務，改試做兩個不需要額外模型的輕量替代方案。
  試做內容與結果（3次迭代，誠實記錄含負面結果）：
    1. `trial2_finer_diff_alignment.py`——短句切分後比對：**失敗**。獨立版因
       這輪修正（移除逗號竄改，見 autonomous_decisions）幾乎沒標點可切，只
       切出8個chunk（對方1653個），細粒度這個變數根本沒被測到。
    2. `trial2b_char_ngram_coverage.py`——改用字元n-gram重疊率（DeepSeek建議
       的替代方案，語言無關不需斷詞）：發現n-gram覆蓋率（27-40%，視n而定）
       遠低於現有 SequenceMatcher.ratio()（87.39%）。
    3. 再次跟DeepSeek討論這個落差：確認計算無誤，是兩種指標的數學本質不同
       （LCS式配對對散布錯字很寬容，n-gram要求連續完全相等，對雜訊過度嚴苛）
       ——這揭露一個對主線任務有意義的額外發現：whisper逐字稿本身散布大量
       同音異字辨識錯誤（股癌→古愛等），現有87.39%這個相似度數字可能沒有
       完全反映這一點。
  DeepSeek討論摘要：建議正式方案改用CER（字元編輯距離相似度，語音辨識標準
  評估指標）取代SequenceMatcher.ratio()，能同時處理替代/插入/刪除、比n-gram
  抗雜訊、比ratio()更貼近人眼判斷；短句切分本身的問題不是「切不細」而是
  「兩邊標點密度差太多，標點不能當兩邊都存在的切分訊號」。
  **延伸方向選項（供使用者裁決）**：
    (a) 不變更，維持現有 SequenceMatcher 段落粒度比對（正確性夠用，
        只是診斷粒度較粗）
    (b) 小幅升級：只換相似度指標（ratio()→CER加權平均），不動對齊演算法，
        改動範圍小、風險低
    (c) 較大升級：引入兩階段對齊（先用n-gram/滑動視窗粗對齊定位分歧區塊，
        再局部細比），診斷價值最高但工程量較大，且要重新測試

  === 想法3：Windows subprocess呼叫Python CLI工具的通用編碼防護模式（來源：
  這輪主線任務實際踩到的真bug + [CPython issue #105312](https://github.com/python/cpython/issues/105312)）===
  背景動機：這輪修正過 yt-dlp `--print` 純文字輸出在 cp950 主控台下的編碼問題
  （已改用 `-J` JSON 輸出解決，見 daf11a4）。這裡驗證一個更通用、不依賴目標
  工具剛好有JSON輸出選項的備用修法。
  可行性：查證確認這是已知的 CPython 生態系問題，`PYTHONIOENCODING=utf-8`
  是文獻常見建議修法。
  試做內容：`trial3_subprocess_encoding.py`，用真實 yt-dlp 呼叫做 A/B 對照。
  **實測發現**：不修法時 emoji 字元是**靜默丟失**（'EP684 | 🔦' 變成
  'EP684 |'），不是我原本以為的亂碼——這點本身就是重要發現，代表這類 bug
  可能連「肉眼看起來有點怪」的警訊都沒有，更難察覺。加上
  `env={**os.environ, "PYTHONIOENCODING": "utf-8"}`（per-call傳，不動全域
  os.environ）後逐字元比對完全正確。
  DeepSeek討論摘要：確認根因是 yt-dlp 自己的 `write_string()` 在非TTY輸出時
  用 `errors='ignore'` encode 成主控台編碼，encode不過的字元直接丟棄；
  `PYTHONIOENCODING` 修法只對 Python 寫的 CLI 有效（Rust/Go/Node工具不吃）、
  必須跟 parent 的 `encoding="utf-8"` 成對設定、要用 per-call env 不要動全域
  os.environ、Python 3.15（PEP 686）後這招會自然變多餘。
  **延伸方向選項（供使用者裁決）**：
    (a) 不需要正式導入：這輪唯一實際踩到的具體案例已經用 -J 方案解決，
        目前程式碼裡沒有其他已知會踩到類似問題的 subprocess 呼叫
    (b) 預防性導入：把 `env={**os.environ, "PYTHONIOENCODING": "utf-8"}`
        當成 independent_transcribe.py/sync_independent_transcripts.py 裡
        所有 subprocess.run() 呼叫的標準寫法，即使目前沒有已知問題，也降低
        未來遇到類似情境的風險（低成本、無明顯副作用的預防性強化）
    (c) 寫進索羅門的個人工作筆記（已完成，見 project_pm_agent_solomon.md），
        以後索羅門本人在任何專案遇到類似 subprocess 編碼情境時直接套用這個
        pattern，不需要每次重新踩坑才學到
autonomous_decisions: |
  === 重大自主決策：完工前 Codex 挑戰式審查抓到的問題，全部已修正 ===

  【原案】1a/1b/1c/1d/1e 初版實作（commit 95d288a + daf11a4）。
  【觸發原因】章程要求完工前必須用 Codex 額度做最後一次獨立審查，且要求 Codex
  「挑戰」而非附和。這次提問明確要求 Codex 對 5 個我自己判斷的設計決策提出質疑，
  Codex（gpt-5.6-terra, reasoning effort high）回應「不建議目前版本合併」，
  指出多項真實風險（完整意見見 git commit a04060d 的 commit message，此處摘要）。
  【是否問過 Codex 及意見摘要】已問，逐項意見：
    1. 段落分段搜尋逗號無上限，段落可能遠超550字設計上限
    2. cue間插入原文沒有的逗號，等於竄改逐字稿內容，可能影響 Gemini「一字不漏」判讀
    3. 「exit code非零但source.srt存在就當成功」的寬容處理不安全——Codex 實際重讀
       當前 video-transcribe/transcribe.py::verify() 確認我原本引用的已知 bug
       **現在已經修好了**，這個寬容處理反而會把真正的失敗（下載/GPU/舊工作目錄
       殘留）誤判成成功
    4. errors="replace" 靜默替換壞位元組，JSON 仍可能解析成功但資料已被污染
    5. _fetch_remote_md() 把所有例外（含連線層錯誤）都當「對方沒有」，會把暫時性
       網路故障誤判成真缺口
    6. compare_paragraphs() 的差異分類是字串對齊層級，不是語意判斷，容易誤導；
       whatmkreallysaid.com 被稱為「官方」在背景定義上不正確
    7.（我沒問到但 Codex 主動指出，最重要的一項）交叉驗證分支在「本地已有檔案」
       時會先 SKIP——正常情況下 whatmkreallysaid.com 已有逐字稿時本地也該已有檔，
       這代表**真正該交叉驗證的情境反而不會執行**；且獨立版寫入後，
       whatmkreallysaid.com 日後補上同集會造成同一 EP 兩個檔案並存，
       batch.py 只會分析先出現的那份，另一份被永久跳過——分析結果來源不可預測，
       且無法在對方版本到位後重新驗證/更新
    8. cross-validation 成功後不寫 transcripts/，導致「可重複執行」不成立（每次
       重跑都重新下載+轉錄+重複寫入差異報告）
    9. --limit 用 sorted() 由小到大截斷，`--limit 2` 會先處理 681/682，不是任務
       指定優先要處理的最新2集 683/684
  【最終選擇】全部採納，逐項修正（commit a04060d，詳見 commit message）：
    1. 加搜尋視窗上限（550+150字），確保段落長度真的有界
    2. 移除逗號插入，cue間直接串接，不再竄改原文
    3. 移除寬容處理，改嚴格要求 exit code 0
    4. 兩處改嚴格 UTF-8 解碼（不帶 errors=），失敗就報錯不污染資料
    5. 新增 RemoteFetchTransportError 區分「確認404」跟「連線層失敗」，後者不
       再假設「對方沒有」
    6. 新增 detect_duplicate_episode_files()，main() 執行時主動掃描並警告——
       這是唯一沒有「完全解決」的一項，因為完整解法需要動 batch.py 的
       episode_id 去重邏輯（判斷哪份該分析、哪份該重新分析），這已經跨出任務檔
       明確排除的範圍（「不修改 analyzer.py/batch.py/update.py/database.py
       既有分析 pipeline 核心邏輯」），只能做偵測+警告，完整解法留給使用者裁決
    7. 交叉驗證分支新增 SKIP 判準（cross_validated_raw 檔案存在），恢復可重複執行
    8. 寫入 transcripts/ 前重新檢查一次 existing（縮小競態視窗）+ 改用原子寫入
    9. --limit 改成最新2集優先排在前面
  【對DoD/相容性/回復方式的影響】全部修正都在任務檔範圍內（stock-signal 目錄底下，
  不動 video-transcribe、不動 batch.py/analyzer.py 核心邏輯），DoD 沒有降級——
  EP681-684 已用修正後的程式碼重新產生（移除逗號竄改後內容略短，結構不變），
  重新跑過 batch.py --dry-run 與 idempotency 測試皆通過。回復方式：commit
  daf11a4（修正前）與 a04060d（修正後）都在，需要回滾直接 git revert 即可。
  【殘餘風險】detect_duplicate_episode_files() 只做偵測+警告，不自動解決同集雙檔
  問題——這是本輪機制無法在不擴大任務範圍的前提下完全解決的結構性缺口，見下方
  remaining_risk 詳細說明。

  === 一般分岔點（精簡列）===
  - EP681-684 全部走「缺口補齊」（不只283/684走）：任務原文「1c對1b找出的缺口
    集數(預期數量很小)...直接採用」+「1d的最新兩集若whatmkreallysaid.com也還沒
    有，就自動併入1c」——四集全部符合這個條件（remote都沒有），解讀合理，Codex
    審查也確認「任務文字本身允許這樣做」。
  - 段落分段/交叉驗證診斷用詞等格式細節：見上方重大自主決策段落，已整合修正。
  - 獨立轉錄的展示標題來源改用 YouTube 影片描述第一行（因為影片標題本身只有
    「EPxxx | emoji」無描述文字，跟任務檔原本假設不同）：低風險裝飾性資訊，
    抓不到就退回「獨立轉錄」，不影響資料正確性。
blocked_items: none
remaining_risk: |
  1.【最重要，未完全解決】同一 EP 編號在 transcripts/ 有多檔案的長期風險：
     若之後 whatmkreallysaid.com 補上 EP681-684 任一集，download_transcripts.py
     會依「完整檔名」判斷是否已下載（不依 EP 號），通常會另外寫一份對方版本，
     造成同集兩檔並存。batch.py 用 glob 讀全部 EP*.md，兩份都映射成同一
     episode_id，哪份先被分析、寫進 episode_analysis 表，另一份就會被永久跳過
     ——分析結果可能停留在較低品質的獨立轉錄版本，不會自動升級成
     whatmkreallysaid.com 版本。本輪已加 detect_duplicate_episode_files()
     在每次執行 sync_independent_transcripts.py 時主動掃描警告，但**沒有自動
     解決**（完整解法需要改 batch.py 的判斷邏輯或加一道「偵測到官方版本出現時
     刪除獨立版+重置該集分析紀錄」的遷移步驟，這兩者都跨出本輪任務檔明確排除的
     範圍，且後者涉及 DELETE episode_analysis/signals 資料，不在自主決策範圍
     內）。**建議**：使用者看到這份報告後，之後每次跑
     sync_independent_transcripts.py 前先看有沒有「[警告] 發現N個EP編號有多個
     檔案」，出現時手動決定要保留哪份、要不要連帶重跑該集分析。
  2. compare_paragraphs() 的差異分類是字串對齊層級的候選，不是語意判斷（見
     autonomous_decisions 第6項），whatmkreallysaid.com 版與獨立版分段方式不同
     時容易被判成大塊差異，實際上可能只是分段不同——EP680 機制驗證測試就出現
     這個現象（1個差異區塊涵蓋大半篇幅）。之後若要更精確，需要句子/滑動視窗
     層級的比對，這輪沒有做。
  3. 獨立轉錄品質沒有客觀門檻：目前只要求 source.srt 非空即算成功，沒有最低
     cue數/時長/重複迴圈偵測/語言不符等品質檢查（video-transcribe 本身有
     repetition detection 但只寫進它自己的 manifest.json，本模組沒有讀取這個
     資訊來做二次把關）。manifest.json 也沒記錄轉錄器版本/模型參數這些可稽核性
     欄位。
  4. 段落分段（cues_to_paragraphs）改成不插入任何原文外字元後，可讀性略微下降
     （兩個分句之間偶爾少一個停頓標點）——這是刻意的忠實度優先權衡，不是 bug。
  5. transcripts_data/independent_media/ 目前佔用 547MB（4集下載的原始影片+
     srt/ass/mkv），已在 stock-signal 目錄底下、gitignore 排除，不影響版控，
     磁碟還有約1TB剩餘空間，這輪沒有清理，供使用者決定要不要之後清掉。
  6. run_independent_transcription() 移除寬容處理後，如果 video-transcribe 未來
     又出現任何新的封裝驗證問題，會直接讓整個獨立轉錄失敗（而不是像舊版那樣
     矇混過去）——這是刻意的取捨（正確性優先於可用性），但代表 video-transcribe
     那邊如果出新 bug，本模組的成功率會直接受影響，需要去那邊修，不能在這邊繞過。
next_step: |
  已完工，DoD 6 項全數達成，無 blocked_items，且已完成自我精進 Part A/B。
  下一棒（下次索羅門指派或使用者自己接手）建議優先順序：
  1. 看過本報告 remaining_risk 第1項後，決定要不要授權設計「偵測到
     whatmkreallysaid.com 補上獨立轉錄過的集數時如何處理」的遷移機制（會需要
     討論是否允許刪除獨立版+重置分析紀錄，涉及 DB DELETE，需要另外拍板）
  2. 決定要不要把 sync_independent_transcripts.py 接上自動排程（本輪任務檔
     明確排除，任務檔原文要求另外確認執行頻率與方式）
  3. 如果满意這輪的獨立轉錄品質，可以考慮之後真的遇到 whatmkreallysaid.com
     停更時，把 sync_independent_transcripts.py 當唯一逐字稿來源持續使用
  4. 看過 self_improvement_new_ideas 三個延伸方向選項，決定要不要挑選任何一項
     正式投入（想法1標點復原/想法2相似度指標CER化/想法3編碼防護預防性導入）
     ——三者都只是研究筆記+試做，沒有一項已經是正式功能，索羅門沒有自行拍板
  5. 本輪 8 個 commit 全部本地（95d288a..HEAD），尚未 push，跟其他輪一樣
     由使用者/主控 session 決定要不要 push
