import json
import re
from datetime import date
from google import genai
from google.genai import types
from config import GEMINI_API_KEY, GEMINI_MODEL
from prompt import SYSTEM_PROMPT

_client = None


class GeminiFormatError(Exception):
    """Gemini 回傳內容不是合法 JSON、或缺少必要欄位（結構化輸出失敗）。
    2026-08-02 索羅門新增（任務第9項）：跟逾時/429/5xx 這種 API/網路錯誤是不同
    性質的問題——後者等待重試有意義（給伺服器時間恢復），前者純粹是模型這次輸出
    不合格式，重試意義不大（頂多給模型一次「換句話說」的機會），呼叫端
    （batch.py::_analyze_with_retry）要能分開處理，不能用同一套指數退避。"""
    pass


def _get_client():
    # 2026-08-02 索羅門修正（任務第12項）：改讀 config.py 統一管理的 GEMINI_API_KEY，
    # 不再自己重新 os.getenv()。原本能運作是因為 import config 這個動作本身會觸發
    # config.py 的 load_dotenv(override=True) 當副作用，但那是隱性依賴——分析腳本
    # 本身完全沒呼叫 load_dotenv()，只是碰巧 config.GEMINI_MODEL 的 import 順序讓
    # .env 先被載入到 os.environ，才讓 os.getenv() 查得到值。
    global _client
    if _client is None:
        _client = genai.Client(
            api_key=GEMINI_API_KEY,
        )
    return _client

def analyze(transcript: str) -> dict:
    today = date.today().isoformat()
    user_content = f"今天日期：{today}\n\n以下是今天的逐字稿：\n\n{transcript}"

    response = _get_client().models.generate_content(
        model=GEMINI_MODEL,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            max_output_tokens=8192,
        ),
        contents=user_content,
    )

    raw = response.text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise GeminiFormatError(f"Gemini 回傳內容不是合法 JSON：{e}") from e

    # 最小結構化驗證：至少要是 dict，且 extracted_signals 一定要存在且是 list
    # （SYSTEM_PROMPT 本身就規定這是必填欄位，即使 0 個訊號也要回傳空陣列，
    # 見 prompt.py）。2026-08-02 完工前 Codex 覆核抓到：原本只在這個欄位「存在
    # 時」驗證型別，如果 Gemini 回傳缺少這個欄位的錯誤格式（例如 {"error":"..."}），
    # 會被當成合法輸出放行，save_result() 再用 result.get("extracted_signals", [])
    # 補一個空陣列預設值，等於把「Gemini 這次根本沒分析成功」誤判成「這集真的
    # 是 0 訊號」——搭配 episode_analysis 新增的「永久記錄」語意，這集會被永遠
    # 跳過、再也不會重跑，比舊版影響更嚴重，所以改成欄位缺席也要當格式錯誤處理，
    # 不只是型別不對才擋。
    if not isinstance(parsed, dict):
        raise GeminiFormatError(f"Gemini 回傳的 JSON 最外層不是物件（dict），而是 {type(parsed).__name__}")
    if not isinstance(parsed.get("extracted_signals"), list):
        raise GeminiFormatError(
            "Gemini 回傳缺少 extracted_signals 欄位，或型別不是陣列"
            f"（實際回傳的最外層欄位：{sorted(parsed.keys())}）"
        )

    return parsed
