import json
import re
from datetime import date
from google import genai
from google.genai import types
from config import GEMINI_API_KEY, GEMINI_MODEL
from prompt import SYSTEM_PROMPT

_client = None

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

    return json.loads(raw)
