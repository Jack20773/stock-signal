"""自我精進 Part B 試做 3：Windows 上呼叫外部 Python CLI 工具的通用編碼防護模式。

背景：這輪 r3 任務實際踩過的真 bug——用 subprocess.run(text=True, encoding="utf-8")
讀 yt-dlp（本身是 Python 程式）的 `--print` 純文字輸出，在這台 Windows 機器上
（主控台編碼 cp950）解出亂碼，寫壞了 4 個檔名（已在正式程式碼修正為改用 `-J`
JSON dump，因為 JSON 輸出定義明確是 UTF-8）。

查證（WebSearch，來源見自我精進報告）：這是已知的 CPython 議題
（github.com/python/cpython/issues/105312：subprocess.run() 在 Windows 上對
文字編碼的預設行為容易出錯）。業界建議的通用修法之一：呼叫子行程時明確在
子行程的環境變數裡加 `PYTHONIOENCODING=utf-8`，強制**子行程自己**（如果也是
Python 程式）用 UTF-8 輸出，不受 Windows 主控台編碼影響——這跟正式程式碼裡
已採用的「優先用 -J JSON 輸出」是兩種互補的修法：JSON 輸出對「有結構化輸出
選項」的工具最穩健；PYTHONIOENCODING 環境變數對「只能用純文字輸出、且目標
工具本身是 Python 寫的」的情況更通用。

**這是試做，不是正式功能**——不修改 independent_transcribe.py/
sync_independent_transcripts.py 正式程式碼（那兩個檔案已經用 -J 方案解決了
這次的具體 bug），這裡只是驗證「PYTHONIOENCODING 環境變數覆蓋」這個更通用的
修法本身是否有效，作為以後遇到「沒有 JSON 輸出選項」的類似情境時的備用方案。
"""
import os
import subprocess
import sys
from pathlib import Path

VIDEO_ID = "AmYcb52jMTU"  # EP684，這輪任務已經用過的真實影片，唯讀查詢不影響任何東西
URL = f"https://www.youtube.com/watch?v={VIDEO_ID}"


def try_without_fix() -> tuple[bool, str]:
    """重現原始 bug：不覆蓋子行程環境變數，直接用 text=True + encoding="utf-8" 讀
    yt-dlp --print 純文字輸出。"""
    proc = subprocess.run(
        ["yt-dlp", "--skip-download", "--print", "%(title)s", URL],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    output = proc.stdout.strip()
    # 亂碼的特徵：出現 U+FFFD replacement character（errors="replace" 的產物）
    has_replacement_char = "�" in output
    return has_replacement_char, output


def try_with_pythonioencoding_fix() -> tuple[bool, str]:
    """修法：明確覆蓋子行程的 PYTHONIOENCODING=utf-8 環境變數，強制 yt-dlp
    （本身是 Python 程式）用 UTF-8 輸出，不受 Windows 主控台編碼影響。"""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.run(
        ["yt-dlp", "--skip-download", "--print", "%(title)s", URL],
        capture_output=True, text=True, encoding="utf-8", errors="strict", timeout=30,
        env=env)
    output = proc.stdout.strip()
    return False, output  # errors="strict" 不會產生 replacement char，解碼失敗會直接拋例外


def main():
    # 全程不對 console print() 原始內容（emoji/中文在這台機器的 cp950 主控台會再炸一次
    # UnicodeEncodeError，那是「顯示層」的問題，跟這次真正要測的「subprocess 解碼層」
    # 是兩回事，混在一起會誤導測試結果）——一律直接寫檔，用 repr() 避免任何顯示問題。
    known_true_title = "EP684 | 🔦"  # 已知這部影片的真實標題（本輪任務前面用 -J 查過）

    has_garble, output1 = try_without_fix()
    test1_correct = output1 == known_true_title

    try:
        _, output2 = try_with_pythonioencoding_fix()
        test2_error = None
        test2_correct = output2 == known_true_title
    except UnicodeDecodeError as e:
        output2 = None
        test2_error = str(e)
        test2_correct = False

    result_lines = [
        "=== 測試1：原始寫法（重現 bug，text=True + encoding='utf-8'，未覆蓋子行程env）===",
        f"輸出 repr: {output1!r}",
        f"偵測到 U+FFFD 亂碼字元: {has_garble}",
        f"跟已知真實標題「{known_true_title}」完全一致: {test1_correct}",
        "",
        "=== 測試2：PYTHONIOENCODING=utf-8 修法（覆蓋子行程環境變數）===",
    ]
    if test2_error:
        result_lines.append(f"解碼失敗（UnicodeDecodeError）: {test2_error}")
    else:
        result_lines.append(f"輸出 repr: {output2!r}")
        result_lines.append(f"跟已知真實標題「{known_true_title}」完全一致: {test2_correct}")

    result_lines.append("")
    result_lines.append("=== 結論 ===")
    if test1_correct:
        result_lines.append("這次測試1（未修法）意外沒有重現 mojibake——跟本輪任務實際踩到的")
        result_lines.append("bug（用 --print 讀 description 這種多行長文字時出現亂碼）不是同一個")
        result_lines.append("觸發條件，說明這個 bug 不是每次都會發生，跟輸出內容的長度/字元組成")
        result_lines.append("有關，不穩定重現——這件事本身就是個重要發現：不能因為「這次測試沒有")
        result_lines.append("亂碼」就認定某個 subprocess 呼叫是安全的。")
    else:
        result_lines.append("這次測試1（未修法）成功重現了原始 bug，測試2（加 PYTHONIOENCODING=utf-8）")
        result_lines.append(f"修正了它: {test2_correct}")

    out_path = Path(__file__).parent / "trial3_demo_output.txt"
    out_path.write_text("\n".join(result_lines), encoding="utf-8")
    print("saved")


if __name__ == "__main__":
    main()
