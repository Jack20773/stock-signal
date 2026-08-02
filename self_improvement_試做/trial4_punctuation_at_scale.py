"""自我精進 Part B 第二輪、延伸試做 4：把試做1的「標點復原+逐字驗證」擴大到整集規模。

背景：使用者要求「不是單次流程」，針對上一輪延伸方向選項 (b)（加值功能：
LLM加標點 + 逐字比對驗證，不通過就丟棄，改保留無標點原文）做更深入的試做——
上一輪只測了1段~550字樣本，這輪跑一整集(EP681，40個段落)的真實成功率，
把「同音異字漂移常見嗎」這個問題從單一樣本的觀察，變成有統計意義的數字。

**這是試做，不是正式功能**——不修改 independent_transcribe.py 正式邏輯，
只是獨立示範「as a gated post-processing step」這個延伸方向選項的可行性。
唯讀讀取本輪任務已下載的 EP681 逐字稿，不寫回任何正式檔案。
"""
import json
import re
import sys
import time
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


def strip_punct(t: str) -> str:
    return re.sub(r"[，。！？、：；,.!?;:\s《》「」\-—]", "", t)


def gated_restore(paragraph: str) -> dict:
    """試做的「加值功能」版本：加標點，逐字比對通過才採用，不通過就退回原文
    （這就是上一輪延伸方向選項(b)描述的閘門機制，這裡真的實作出來測試）。"""
    t0 = time.time()
    try:
        restored = restore_punctuation(paragraph)
    except Exception as e:  # noqa: BLE001 - 試做腳本，任何失敗都算這筆不通過
        return {"accepted": False, "reason": f"呼叫失敗: {type(e).__name__}: {e}",
                "seconds": round(time.time() - t0, 1)}
    orig_stripped, restored_stripped = strip_punct(paragraph), strip_punct(restored)
    if orig_stripped == restored_stripped:
        return {"accepted": True, "restored": restored, "seconds": round(time.time() - t0, 1)}
    # 找第一個差異位置方便人工複核
    diff_pos = next((i for i in range(min(len(orig_stripped), len(restored_stripped)))
                      if orig_stripped[i] != restored_stripped[i]), min(len(orig_stripped), len(restored_stripped)))
    return {"accepted": False,
            "reason": f"逐字比對不通過(原文去標點{len(orig_stripped)}字 vs 復原去標點{len(restored_stripped)}字，"
                      f"第{diff_pos}字起不同)",
            "diff_excerpt_orig": orig_stripped[max(0, diff_pos - 10):diff_pos + 10],
            "diff_excerpt_restored": restored_stripped[max(0, diff_pos - 10):diff_pos + 10],
            "seconds": round(time.time() - t0, 1)}


def main():
    srt_path = Path(__file__).parent.parent / "transcripts_data" / "independent_media" / "EP681" / "source.srt"
    cues = parse_srt(srt_path)
    paragraphs = cues_to_paragraphs(cues)
    print(f"EP681 共 {len(paragraphs)} 段，開始逐段測試「標點復原+逐字驗證閘門」...", flush=True)

    results = []
    for i, para in enumerate(paragraphs, 1):
        r = gated_restore(para)
        r["para_index"] = i
        r["para_len"] = len(para)
        results.append(r)
        status = "ACCEPT" if r["accepted"] else "REJECT"
        print(f"[{i}/{len(paragraphs)}] {status} ({r['seconds']}s)"
              + ("" if r["accepted"] else f"  {r['reason']}"), flush=True)

    accepted = sum(1 for r in results if r["accepted"])
    rejected = len(results) - accepted
    total_seconds = sum(r["seconds"] for r in results)

    lines = [
        f"=== EP681 全集規模測試：標點復原+逐字驗證閘門（共 {len(paragraphs)} 段）===",
        f"通過(採用復原版): {accepted}/{len(paragraphs)} ({accepted/len(paragraphs):.1%})",
        f"未通過(退回原文): {rejected}/{len(paragraphs)} ({rejected/len(paragraphs):.1%})",
        f"總耗時: {total_seconds:.0f}s，平均每段: {total_seconds/len(paragraphs):.1f}s",
        "",
        "=== 未通過的段落詳情（供人工複核，驗證閘門有沒有正確攔截真的竄改）===",
    ]
    for r in results:
        if not r["accepted"]:
            lines.append(f"段落 {r['para_index']}（{r['para_len']}字）: {r['reason']}")
            if "diff_excerpt_orig" in r:
                lines.append(f"  原文附近: ...{r['diff_excerpt_orig']}...")
                lines.append(f"  復原附近: ...{r['diff_excerpt_restored']}...")

    out_path = Path(__file__).parent / "trial4_demo_output.txt"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n已存檔：{out_path}")
    print(f"通過率: {accepted}/{len(paragraphs)} ({accepted/len(paragraphs):.1%})")


if __name__ == "__main__":
    main()
