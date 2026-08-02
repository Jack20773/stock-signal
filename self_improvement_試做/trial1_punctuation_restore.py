"""自我精進 Part B 試做 1：用本機 Ollama 幫獨立轉錄的逐字稿補標點。

背景：這輪 r3 任務實際踩到的問題——faster-whisper 對中文口語幾乎只產生逗號，
不產生句號/問號，獨立轉錄出來的段落讀起來比 whatmkreallysaid.com 版本生硬
（見 SOLOMON_HANDOFF.md remaining_risk 第4點）。查證 ASR 標點復原是有名的
研究領域，這裡用「已經在跑的本機 Ollama qwen2.5:14b-instruct」（video-transcribe
專案本來就用它做翻譯，不需要新裝套件/新下載模型）試做一版輕量標點復原。

**這是試做，不是正式功能**——不改動任何 independent_transcribe.py 的正式邏輯，
只是獨立示範可行性。輸入直接讀取本輪已下載的 EP681 srt 檔案（唯讀），
不寫回任何 transcripts/ 底下的正式檔案。
"""
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from independent_transcribe import parse_srt, cues_to_paragraphs

OLLAMA_HOST = "http://localhost:11434"
MODEL = "qwen2.5:14b-instruct"

PROMPT_TEMPLATE = """以下是語音辨識(ASR)產出的中文逐字稿片段，幾乎沒有句號，只有零星逗號。
請幫這段文字加上恰當的標點符號（句號、逗號、問號等），**不要改動任何文字內容、
不要增刪字詞、不要意譯**，只加標點與適當分段。直接輸出結果，不要加任何說明。

原文：
{text}"""


def restore_punctuation(text: str, timeout: int = 120) -> str:
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": PROMPT_TEMPLATE.format(text=text)}],
        "stream": False,
        "options": {"temperature": 0.1},
    }
    req = urllib.request.Request(
        f"{OLLAMA_HOST}/api/chat",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["message"]["content"].strip()


def main():
    srt_path = Path(__file__).parent.parent / "transcripts_data" / "independent_media" / "EP681" / "source.srt"
    cues = parse_srt(srt_path)
    paragraphs = cues_to_paragraphs(cues)
    sample = paragraphs[0]  # 第一段當示範樣本

    print("=== 原始（獨立轉錄，僅逗號無句號）===")
    print(sample)
    print()
    print("=== 標點復原後（本機 Ollama qwen2.5:14b-instruct）===")
    restored = restore_punctuation(sample)
    print(restored)

    out_path = Path(__file__).parent / "trial1_demo_output.txt"
    out_path.write_text(
        "=== 原始 ===\n" + sample + "\n\n=== 標點復原後 ===\n" + restored + "\n",
        encoding="utf-8",
    )
    print(f"\n已存檔：{out_path}")


if __name__ == "__main__":
    main()
