# stock-signal 索羅門煙霧測試任務（2026-08-01）

> 目的：驗證索羅門背景執行 + 即時監看機制（`solomon_watch.sh`）真的能運作，不是空口報告。純測試，不是真實產品需求。
> 任務檔版本錨點 commit：`a704ba5a1bbc67e52fdc48d6358560550ee7c9fe`

## 1. 具體任務清單（技術設計已定案，不需要自己設計）

範圍完全隔離在 `stock-signal/.smoke_test/` 這個新建子目錄，不得修改此目錄以外的任何檔案。

**階段一**：
1. 建立目錄 `stock-signal/.smoke_test/`
2. 建立檔案 `stock-signal/.smoke_test/smoke_test_log.md`，內容包含：
   - 目前時間戳（跑 `date` 指令取得，不要自己編）
   - 實際執行 `python -X utf8 --version` 的真實輸出（貼指令+輸出）
   - 一句話：「索羅門煙霧測試階段一，確認可以讀寫檔案與跑指令」
3. `git add` 該檔案，commit，訊息：`test: 索羅門煙霧測試 階段一`

**階段二**（緊接著做，不要間隔太久）：
1. 實際執行 `ls stock-signal/` 列出專案根目錄檔案清單（真實指令輸出，不要自己編）
2. 把這份清單附加到 `smoke_test_log.md` 的新段落
3. `git add` 該檔案，commit，訊息：`test: 索羅門煙霧測試 階段二`

**階段三（收工）**：
1. 在 `stock-signal/.smoke_test/` 底下寫 `SOLOMON_HANDOFF.md`，格式照通用章程「每個階段交接的固定格式」，`status: completed`
2. 確認 `git status` 除了 `.smoke_test/` 底下的檔案，沒有動到任何其他檔案

## 2. 截止時間

20 分鐘內完成（使用者現場等待中，不是隔夜任務）。

## 3. 範圍限定

僅限 `stock-signal/.smoke_test/` 目錄。不得碰 `.env*`、不得呼叫任何付費 API（Gemini/寄信）、不得 push、不得對正式資料庫做任何讀寫、不得動這份任務檔以外的任何既有原始碼檔案。

## 4. 完成的定義

1. `.smoke_test/` 底下至少有 2 個獨立 commit（階段一、階段二各一次），每個 commit 都是真的跑過指令、貼真實輸出，不是編造內容。
2. `SOLOMON_HANDOFF.md` 存在且 `status: completed`。
3. `git status` 確認沒有動到 `.smoke_test/` 以外的任何檔案。
4. 不需要動用 Codex/DeepSeek 額度（任務太小、沒有需要覆核的設計決策）；如果過程中真的遇到不確定的分岔點，直接選最保守的做法繼續，不用停下來問。

## 5. 監督模式

**有人監督**——使用者現在就在螢幕前看著監看畫面，不會離開。卡住可以直接在完工報告裡寫清楚，不需要走無人監督的隔離流程。
