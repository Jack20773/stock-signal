# -*- coding: utf-8 -*-
"""逐字稿 → 結構化投資訊號 JSON 的單一入口。

2026-09-03（丹尼爾裁決「改用 Claude，而且是訂閱制」）之前，這支檔案只會打
Gemini。現在改成**可切換的兩條路**，由 config.LLM_PROVIDER 決定：

    LLM_PROVIDER=claude （預設）→ _analyze_claude()：本機 `claude -p` 子行程，
                                   走已登入的訂閱制 OAuth 憑證。
    LLM_PROVIDER=gemini          → _analyze_gemini()：原本那條路，邏輯一行沒改，
                                   保留成可回退路徑（額度回來就能切回去）。

🔴 訂閱制紅線（改這支檔案的人請先讀完再動）：
    `claude -p` 子行程的環境會先被 _build_clean_env() 拔掉
    ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN / CLAUDE_CODE_USE_BEDROCK /
    CLAUDE_CODE_USE_VERTEX。理由是**只要環境裡有 API key，CLI 就會改用按次計費
    的 API 認證**，那是丹尼爾沒同意的花費。拔掉之後 CLI 只剩下自己存的訂閱
    憑證可用，跑得起來就代表用的是訂閱額度。**不要為了「比較好 debug」把這段
    拿掉。** 同款做法沿用自 300_Projects/ai-trader/ops/tw_daily_report.py::
    build_clean_env（2026-08-26 已在該專案實證過）。

兩條路共用同一套輸出驗證（_validate_parsed），所以下游 database.save_result()
吃到的結構完全一樣，換供應商不需要動下游。
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import date

from config import (
    CLAUDE_CLI_BINARY,
    CLAUDE_MAX_BUDGET_USD,
    CLAUDE_MODEL,
    CLAUDE_SAFE_MODE,
    CLAUDE_TIMEOUT_S,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    LLM_PROVIDER,
)
from prompt import SYSTEM_PROMPT

_client = None


class GeminiFormatError(Exception):
    """模型回傳內容不是合法 JSON、或缺少必要欄位（結構化輸出失敗）。

    2026-08-02 索羅門新增（任務第9項）：跟逾時/429/5xx 這種 API/網路錯誤是不同
    性質的問題——後者等待重試有意義（給伺服器時間恢復），前者純粹是模型這次輸出
    不合格式，重試意義不大（頂多給模型一次「換句話說」的機會），呼叫端
    （batch.py::_analyze_with_retry）要能分開處理，不能用同一套指數退避。

    2026-09-03：改用 Claude 後這個類別名稱已經名不副實（它現在也代表 Claude 的
    格式錯誤），但 batch.py 與既有程式都 import 這個名字，**故意不改名**以免製造
    無謂的破壞性變更；新程式碼請用底下的別名 LLMFormatError。
    """
    pass


# 語意正確的新名字；GeminiFormatError 保留給既有 import 相容。
LLMFormatError = GeminiFormatError


class ClaudeCLIError(RuntimeError):
    """`claude -p` 子行程層級的失敗（非零 exit、逾時、信封不合法）。

    刻意**不**繼承 GeminiFormatError：batch.py 對格式錯誤用短固定等待，對這種
    傳輸/執行層錯誤用指數退避，兩者要分開處理。
    """
    pass


# ---------------------------------------------------------------------------
# 共用：輸出驗證（兩條供應商路徑都必須通過這一關）
# ---------------------------------------------------------------------------
def _strip_fences(raw: str) -> str:
    raw = (raw or "").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()


def _validate_parsed(parsed, provider: str) -> dict:
    """最小結構化驗證：至少要是 dict，且 extracted_signals 一定要存在且是 list
    （SYSTEM_PROMPT 本身就規定這是必填欄位，即使 0 個訊號也要回傳空陣列，
    見 prompt.py）。2026-08-02 完工前 Codex 覆核抓到：原本只在這個欄位「存在
    時」驗證型別，如果模型回傳缺少這個欄位的錯誤格式（例如 {"error":"..."}），
    會被當成合法輸出放行，save_result() 再用 result.get("extracted_signals", [])
    補一個空陣列預設值，等於把「這次根本沒分析成功」誤判成「這集真的是 0 訊號」
    ——搭配 episode_analysis 的「永久記錄」語意，這集會被永遠跳過、再也不會重跑，
    比舊版影響更嚴重，所以欄位缺席也要當格式錯誤處理，不只是型別不對才擋。
    """
    if not isinstance(parsed, dict):
        raise GeminiFormatError(
            f"{provider} 回傳的 JSON 最外層不是物件（dict），而是 {type(parsed).__name__}")
    if not isinstance(parsed.get("extracted_signals"), list):
        raise GeminiFormatError(
            f"{provider} 回傳缺少 extracted_signals 欄位，或型別不是陣列"
            f"（實際回傳的最外層欄位：{sorted(parsed.keys())}）"
        )
    # 2026-08-02 索羅門補強（殘餘風險清單第3項）：只驗證 extracted_signals 本身是
    # list 還不夠——database.py::save_result() 的迴圈對每個元素直接呼叫 s.get(...)，
    # 陣列裡混入非 dict 元素會在 save_result() 內部丟出未預期的 AttributeError，
    # 等於同一個「格式錯誤」問題只是延後到更難追查的下游位置才爆炸。
    for i, s in enumerate(parsed["extracted_signals"]):
        if not isinstance(s, dict):
            raise GeminiFormatError(
                f"{provider} 回傳的 extracted_signals[{i}] 不是物件（dict），"
                f"而是 {type(s).__name__}"
            )
    return parsed


def _extract_first_json_object(text: str):
    """從一段可能夾雜前後說明文字的輸出裡，抓出第一個成對的 {...} 區塊。

    2026-09-03 實測必要性：Claude 有時會在 ```json 圍欄**後面**再補一句說明
    （EP691 第一次實跑就是這樣），`_strip_fences` 的尾端規則因此對不上，
    json.loads 會在圍欄那一行報 "Extra data"。這個 fallback 用大括號配對
    （會跳過字串內的括號與跳脫字元）把物件本體挖出來。

    🔴 這只是「把正文從閒聊裡挑出來」，不是放寬驗證——挖出來的東西照樣要過
    _validate_parsed，結構不對一樣會被擋。
    """
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _parse_model_text(raw_text: str, provider: str) -> dict:
    raw = _strip_fences(raw_text)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        candidate = _extract_first_json_object(raw)
        if candidate is None:
            raise GeminiFormatError(f"{provider} 回傳內容不是合法 JSON：{e}") from e
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            raise GeminiFormatError(f"{provider} 回傳內容不是合法 JSON：{e}") from e
        # 用了 fallback 就要留痕，不能靜默——否則「模型每次都亂加話」這件事
        # 會被這段程式碼永遠蓋住，沒人知道。
        print(f"[warn] {provider} 輸出的 JSON 前後夾雜了說明文字，已用大括號配對挖出物件"
              f"（原始長度 {len(raw)}，取出 {len(candidate)}）", file=sys.stderr)
    return _validate_parsed(parsed, provider)


def _build_user_content(transcript: str) -> str:
    today = date.today().isoformat()
    return f"今天日期：{today}\n\n以下是今天的逐字稿：\n\n{transcript}"


# ---------------------------------------------------------------------------
# 路徑 A：Gemini（保留成可回退路徑，邏輯與 2026-08-02 版一致）
# ---------------------------------------------------------------------------
def _get_client():
    # 2026-08-02 索羅門修正（任務第12項）：改讀 config.py 統一管理的 GEMINI_API_KEY，
    # 不再自己重新 os.getenv()。原本能運作是因為 import config 這個動作本身會觸發
    # config.py 的 load_dotenv(override=True) 當副作用，那是隱性依賴。
    global _client
    if _client is None:
        from google import genai  # lazy import：走 Claude 路徑時不需要裝這包
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


def _analyze_gemini(transcript: str) -> dict:
    from google.genai import types  # lazy import
    response = _get_client().models.generate_content(
        model=GEMINI_MODEL,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            max_output_tokens=8192,
        ),
        contents=_build_user_content(transcript),
    )
    return _parse_model_text(response.text, "Gemini")


# ---------------------------------------------------------------------------
# 路徑 B：Claude CLI（訂閱制，預設）
# ---------------------------------------------------------------------------
# 呼叫 `claude -p` 前要從子行程環境拔掉的變數。前四個是「會把認證從 OAuth 訂閱
# 換成按次計費」的開關（丹尼爾明確不允許）；CLAUDECODE 是 Claude Code 用來擋
# 「在互動 session 裡再開一個 session」的旗標，程式化 subprocess 呼叫要拔掉才
# 能巢狀執行（同款做法見官方 skill-creator 外掛的 run_eval.py / improve_description.py）。
CLI_ENV_BLOCKLIST = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDECODE",
)

# 子行程的工作目錄：用系統暫存目錄，讓 CLI 讀不到本專案任何檔案。逐字稿完全走
# stdin 進去，不需要檔案系統存取。（同款理由見 ai-trader 的 D8 覆核。）
ISOLATED_CWD = os.path.join(tempfile.gettempdir(), "stock_signal_llm_workdir")


def _build_clean_env() -> dict:
    env = {k: v for k, v in os.environ.items() if k not in CLI_ENV_BLOCKLIST}
    removed = [k for k in CLI_ENV_BLOCKLIST if k in os.environ]
    if removed:
        # 只印名稱不印值（NEVER 清單：不得把密鑰印進日誌／對話）
        print(f"[env] 呼叫 claude -p 前已從子行程環境移除：{', '.join(removed)}"
              "（保住 OAuth 訂閱認證，避免變成按次計費）", file=sys.stderr)
    return env


def build_claude_args(model: str = None, cli_binary: str = None,
                      safe_mode: bool = None, max_budget_usd: float = None) -> list:
    """組 `claude -p` 的參數。獨立成函式是為了讓測試不用真的開子行程也驗得到。

    --safe-mode / --max-budget-usd 一定要放在 --tools 之前：--tools 是可變長度
    參數，後面接旗標會被它吃掉（ai-trader 的 build_cli_args 已踩過這個雷）。
    --tools 傳空字串＝一個工具都不給，這支只要模型讀 stdin 吐 JSON，不需要讀檔
    或上網，關掉也順便縮小 prompt-injection 面。
    --safe-mode 不加的後果：子行程會繼承本機 CLAUDE.md / SessionStart hook，
    MEMORY.md 會被整份注入，模型改去扮演記憶交接角色（ai-trader 2026-08-26
    實證的 156 bytes 事故）。
    """
    model = CLAUDE_MODEL if model is None else model
    cli_binary = CLAUDE_CLI_BINARY if cli_binary is None else cli_binary
    safe_mode = CLAUDE_SAFE_MODE if safe_mode is None else safe_mode
    max_budget_usd = CLAUDE_MAX_BUDGET_USD if max_budget_usd is None else max_budget_usd

    args = [cli_binary, "-p", "--model", model, "--output-format", "json"]
    if safe_mode:
        args.append("--safe-mode")
    if max_budget_usd:
        args += ["--max-budget-usd", str(max_budget_usd)]
    args += ["--tools", ""]
    return args


def parse_claude_envelope(stdout_text: str) -> dict:
    """解析 `claude -p --output-format json` 的頂層信封，取出模型輸出文字。

    嚴格只信任 `result`：官方文件對 --output-format json 的公開契約只承諾這一個
    鍵，用 response/text 之類的 fallback「救」內容，會把診斷訊息或未來 schema
    變動誤當成正文（silent false pass）。找不到就大聲失敗，不猜測。
    （結論沿用 ai-trader 2026-08-26 的 D8 二重確認審核。）
    """
    stripped = (stdout_text or "").strip()
    if not stripped:
        raise ClaudeCLIError("claude -p stdout 為空，無法解析")
    try:
        envelope = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ClaudeCLIError(
            f"claude -p stdout 不是合法 JSON 信封：{exc}\n前 500 字元：{stripped[:500]}"
        ) from exc
    if not isinstance(envelope, dict):
        raise ClaudeCLIError(f"JSON 信封應為物件，實際為 {type(envelope).__name__}")

    etype = envelope.get("type")
    if etype is not None and etype != "result":
        raise ClaudeCLIError(f"JSON 信封 type={etype!r}，預期 'result' 或缺省，拒收")
    subtype = envelope.get("subtype")
    if subtype is not None and subtype != "success":
        raise ClaudeCLIError(f"JSON 信封 subtype={subtype!r}，預期 'success' 或缺省，拒收")
    if envelope.get("is_error"):
        raise ClaudeCLIError(
            f"信封 is_error=true（terminal_reason={envelope.get('terminal_reason')}）")

    value = envelope.get("result")
    if not (isinstance(value, str) and value.strip()):
        raise ClaudeCLIError(
            f"JSON 信封找不到非空的 result 欄位，實際鍵：{sorted(envelope.keys())}")
    return {"text": value, "envelope": envelope}


# 最近一次 Claude 呼叫的用量信封摘要（給呼叫端／除錯用，不進 DB）。
# 🔴 total_cost_usd 是 CLI 以「列表價」估算的用量，不是帳單——訂閱制沒有按次收費。
LAST_CLAUDE_USAGE = {}

_USAGE_FIELDS = ("total_cost_usd", "duration_ms", "num_turns", "subtype",
                 "terminal_reason", "session_id")


def _analyze_claude(transcript: str) -> dict:
    global LAST_CLAUDE_USAGE

    # --safe-mode 會關掉 CLAUDE.md / hooks / skills，所以分析規則必須整份走
    # stdin 進去，不能倚賴任何本機設定。
    prompt_text = SYSTEM_PROMPT + "\n\n---\n\n" + _build_user_content(transcript)

    args = build_claude_args()
    env = _build_clean_env()
    os.makedirs(ISOLATED_CWD, exist_ok=True)

    try:
        proc = subprocess.run(
            args,
            input=prompt_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=ISOLATED_CWD,
            env=env,
            timeout=CLAUDE_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as exc:
        raise ClaudeCLIError(f"claude -p 逾時（timeout={CLAUDE_TIMEOUT_S}s）") from exc

    if proc.returncode != 0:
        raise ClaudeCLIError(
            f"claude -p exit={proc.returncode}\nstderr 尾段：\n{(proc.stderr or '')[-2000:]}")

    parsed_env = parse_claude_envelope(proc.stdout)
    env_obj = parsed_env["envelope"]
    LAST_CLAUDE_USAGE = {k: env_obj.get(k, "unavailable") for k in _USAGE_FIELDS}
    return _parse_model_text(parsed_env["text"], "Claude")


# ---------------------------------------------------------------------------
# 對外入口
# ---------------------------------------------------------------------------
_PROVIDERS = {
    "claude": _analyze_claude,
    "gemini": _analyze_gemini,
}


def analyze(transcript: str, provider: str = None) -> dict:
    """把逐字稿丟給 LLM，回傳通過最小結構驗證的 dict。

    provider 不給時看 config.LLM_PROVIDER（預設 claude／訂閱制）。
    """
    name = (provider or LLM_PROVIDER or "claude").strip().lower()
    fn = _PROVIDERS.get(name)
    if fn is None:
        raise ValueError(f"未知的 LLM_PROVIDER={name!r}，合法值：{sorted(_PROVIDERS)}")
    return fn(transcript)
