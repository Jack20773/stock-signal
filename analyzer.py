import json
import re
from datetime import date
import anthropic
from config import MODEL
from prompt import SYSTEM_PROMPT

_client = None

def _get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client

def analyze(transcript: str) -> dict:
    today = date.today().isoformat()
    user_content = f"今天日期：{today}\n\n以下是今天的逐字稿：\n\n{transcript}"

    response = _get_client().messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}]
    )

    raw = response.content[0].text.strip()
    # 防護：Claude 有時仍會包 ```json ... ``` 標籤
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    return json.loads(raw)
