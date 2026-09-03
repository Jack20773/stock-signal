import os
from dotenv import load_dotenv

load_dotenv(override=True)

# ---------------------------------------------------------------------------
# LLM 供應商切換（2026-09-03 丹尼爾裁決：改用 Claude，而且走「訂閱制」）
# ---------------------------------------------------------------------------
# 背景：Gemini 免費額度用完、連三次被拒，2026-08-30 commit 10b91dd 把 GitHub
# Actions 的每日排程註解掉了。今天改成 Claude。
#
# 🔴 這裡的 "claude" 指的是**本機已登入的 Claude Code CLI（訂閱制 OAuth）**，
#    不是 Anthropic API（按次計費）。analyzer.py 呼叫 `claude -p` 子行程前會
#    把 ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN 從子行程環境**移除**，
#    確保認證只可能來自 CLI 存的訂閱憑證，不會悄悄變成按次計費的 API key。
#    見 analyzer.py::_build_clean_env()（同款做法沿用自
#    300_Projects/ai-trader/ops/tw_daily_report.py::build_clean_env）。
#
# Gemini 那條路**沒有砍掉**，設 LLM_PROVIDER=gemini 就回退。
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "claude").strip().lower()

# --- Gemini（保留成可回退路徑）---------------------------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL   = "gemini-flash-lite-latest"

# --- Claude CLI（訂閱制，預設路徑）------------------------------------------
# 模型：預設 sonnet。**這個預設值是量出來的，不是猜的**，2026-09-03 拿同一集
# EP690 對照三方（母體：同一份 21,824 字逐字稿，各跑 1 次）：
#   Gemini（DB 既有基準）：3 筆 — Marvell +1 / Broadcom 0 / 美光 -1
#   claude-haiku-4-5     ：5 筆 — **五筆 action 全部是 0**，耗時 221.7s
#   sonnet               ：5 筆 — Marvell +1 / Broadcom -1 / 聯發科 +1 /
#                          AMD +1 / Alphabet +1，耗時 129.1s
# haiku 找得到標的卻不敢判方向，全押 0。這不是省錢問題是壞掉：下游 performance.py
# 的勝率分母、寄出去的信、ai-trader 的 ④股癌訊號組全都吃 action，全 0 等於這條
# 管線停止產出可用訊號。所以預設用 sonnet。
# ⚠️ 誠實限制：上面是 **n=1、單一集數**的觀察，不是統計顯著的模型評測；
#    2026-08-27 的五模型對分（serenity-clone/remodel266_model_bakeoff）反而說
#    「換模型全對率 55.0%–60.0% 全部重疊、量不出差別」。兩者不衝突——那份量的是
#    「標得準不準」，這裡看到的是「敢不敢標」。要換模型改環境變數 CLAUDE_MODEL 即可。
CLAUDE_MODEL       = os.getenv("CLAUDE_MODEL", "sonnet")
CLAUDE_CLI_BINARY  = os.getenv("CLAUDE_CLI_BINARY", "claude")
# --safe-mode：不加會被本機 SessionStart hook 把 MEMORY.md 整份注入子行程，
# 模型會誤以為自己在做記憶交接（ai-trader 2026-08-26 實證的 156B 事故）。
CLAUDE_SAFE_MODE   = os.getenv("CLAUDE_SAFE_MODE", "1") not in ("0", "false", "False")
# 訂閱制下這不是帳單，是「跑歪迴圈」的保險絲（CLI 用列表價估算 usage）。
CLAUDE_MAX_BUDGET_USD = float(os.getenv("CLAUDE_MAX_BUDGET_USD", "2.0"))
CLAUDE_TIMEOUT_S   = float(os.getenv("CLAUDE_TIMEOUT_S", "600"))

DATABASE_URL   = os.getenv("DATABASE_URL", "")

# ---------------------------------------------------------------------------
# 業配關卡（2026-09-03 新增，第二道防線）
# ---------------------------------------------------------------------------
# 為什麼有這一段（2026-08-28 實際事故）：EP689 的保險套業配裡有一句
# 「誠心推薦特斯拉，濕，大大的濕」，被判成 TSLA 看多訊號並**自動寄給 8 個人**，
# 事後才發現。當天的修法是 prompt.py 的 Rule 1-B——**那道關卡是「叫模型自己
# 注意」，原理跟出事的那一步是同一個**：同一顆模型、同一次推論、同一種失敗
# 模式。模型看漏一次，整條線就再破一次。
#
# 所以這裡加的是**第二道、原理不同的關卡**：不問模型，用確定性的關鍵字比對，
# 攔在「訊號已經產出」之後、「信寄出去」之前（notifier.run_report()）。
# 兩道關卡是 AND，不是二選一：Rule 1-B 負責「一開始就不要產生」，這一道負責
# 「就算產生了也寄不出去」。
#
# 🔴 被擋下的訊號**不會被刪掉**：signals 資料表一個字都不動，另外落一份
#    JSONL 稽核檔（AD_GUARD_BLOCKED_LOG），並在執行輸出印出擋了幾筆、命中
#    哪個關鍵字。悄悄消失比寄錯還糟。

AD_GUARD_ENABLED = os.getenv("AD_GUARD_ENABLED", "1") not in ("0", "false", "False")

# 關鍵字清單放這裡（不是寫死在邏輯中間），之後要加字直接改這一行。
# 前 11 個是丹尼爾 2026-09-03 指定的最小涵蓋範圍，其餘是同一次事故的語料裡
# 實際出現、原理相同的詞。比對是**大小寫不敏感的子字串比對**，不是語意判斷——
# 這是刻意的：它的價值就在於「跟模型的判斷無關」。
AD_KEYWORDS = [
    # --- 丹尼爾指定的必含清單 ---
    "業配", "贊助", "合作", "優惠碼", "折扣碼", "團購", "開箱", "廣告", "置入",
    "sponsor", "promo",
    # --- 同一類，來自 prompt.py Rule 1-B 已經列出的辨識線索 ---
    "折扣", "專屬連結", "輸入代碼", "限時優惠", "誠心推薦", "送禮首選",
    "本集節目由", "支持本節目",
]
# 🔴 全部都是**純子字串**，沒有一個是 regex。刻意的：這份清單以後會有人加字，
#    混進 regex 的那天，加字的人不會知道自己寫的 `.` 會match到任何字元。

# 逐字稿裡「一段」的定義：exact_quote 前後各 N 字，外加所在段落的 Markdown
# 標題行（`## 贊助` 這種）。
# 300 是量出來的，不是猜的（2026-09-03，母體 = signals 表 988 筆有效訊號）：
#   整個標題段落 擋 310/988=31.4%｜窗800 擋 93=9.4%｜窗500 擋 65=6.6%
#   窗300 擋 46=4.7%（現值）｜窗150 擋 29=2.9%｜只比對訊號欄位 擋 23=2.3%
# EP689 那句「誠心推薦特斯拉」在以上每一種窗寬下都照樣被擋，所以縮到 300
# 不會放過這次要防的東西。誤擋大宗是「合作」（正常的產業合作討論）。
# 改之前先跑 `python -X utf8 test_ad_guard.py --survey` 看誤擋率會變多少。
AD_GUARD_WINDOW_CHARS = int(os.getenv("AD_GUARD_WINDOW_CHARS", "300"))

# 被擋訊號的稽核檔（append-only，永遠不覆寫、不刪除）。
AD_GUARD_BLOCKED_LOG = os.getenv(
    "AD_GUARD_BLOCKED_LOG",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "ops", "ad_blocked_signals.jsonl"),
)
