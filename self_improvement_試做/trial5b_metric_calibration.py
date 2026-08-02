"""自我精進 Part B 第二輪、延伸試做 5b：DeepSeek 建議的「已知比例合成改寫」校準測試。

背景：試做5發現我的CER實作因為段落粒度不匹配（remote 246字 vs 獨立版 550字）
被系統性壓低到29%，跟DeepSeek討論後確認是「較長字串當分母」的粒度天花板效應
（246/550≈44.7%理論上限），不是CER這個指標本身不誠實。DeepSeek建議：拿同一
段文字做「已知比例」的合成改寫（例如真的改20%/40%/60%的字元），看哪個指標
（SequenceMatcher.ratio() vs CER）算出來的數字最貼近真實改寫比例，這樣完全
不需要處理段落對齊問題，是更嚴謹的指標校準法。

這裡實作這個校準測試：取一段真實段落，用固定亂數種子隨機替換 X% 的字元，
分別用兩種指標算「相似度」，看哪個比較接近「100% - X%」這個已知的真實答案。

**這是試做，不是正式功能**——純粹是指標校準實驗，不修改任何正式檔案。
"""
import difflib
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from independent_transcribe import srt_to_md
from trial5_cer_similarity import cer_similarity


def synthetic_rewrite(text: str, change_ratio: float, seed: int = 42) -> str:
    """用固定種子隨機替換 change_ratio 比例的字元（換成隨機中文字），
    模擬「已知比例的改寫」，當作衡量指標準確度的 ground truth。"""
    rng = random.Random(seed)
    chars = list(text)
    n_change = int(len(chars) * change_ratio)
    indices = rng.sample(range(len(chars)), min(n_change, len(chars)))
    # 用一批跟原文不會重複的字元池，確保「替換」是真的改變（不會巧合替換成同一個字）
    pool = "甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉戌亥金木水火土風雷電光影聲色空無有無"
    for i in indices:
        chars[i] = rng.choice(pool)
    return "".join(chars)


def seq_ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def main():
    real_srt = Path(r"D:\All claude\300_Projects\video-transcribe\media\EP680_v2\source.srt")
    indep_md = srt_to_md(real_srt, "EP680", "筷子信仰與台積電心碎記")
    # 取一段真實、長度適中的段落當基準文字
    sample = [p for p in indep_md.split("\n\n") if len(p) > 400][0][:400]

    lines = ["=== 指標校準測試：已知比例合成改寫 vs 兩種相似度指標 ===",
             f"基準文字長度: {len(sample)} 字\n",
             f"{'真實改寫比例':<12} {'真實相似度(1-改寫比例)':<20} {'SequenceMatcher.ratio()':<25} {'CER相似度':<12}"]

    for change_ratio in (0.0, 0.1, 0.2, 0.4, 0.6, 0.8):
        rewritten = synthetic_rewrite(sample, change_ratio)
        true_sim = 1 - change_ratio
        sm_sim = seq_ratio(sample, rewritten)
        cer_sim = cer_similarity(sample, rewritten)
        sm_error = abs(sm_sim - true_sim)
        cer_error = abs(cer_sim - true_sim)
        lines.append(f"{change_ratio:<12.0%} {true_sim:<20.0%} "
                     f"{sm_sim:<14.2%}(誤差{sm_error:.1%}) {cer_sim:<8.2%}(誤差{cer_error:.1%})")

    out_path = Path(__file__).parent / "trial5b_demo_output.txt"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"\n已存檔：{out_path}")


if __name__ == "__main__":
    main()
