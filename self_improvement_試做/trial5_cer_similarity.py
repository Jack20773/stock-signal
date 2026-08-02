"""自我精進 Part B 第二輪、延伸試做 5：實作 DeepSeek 建議的 CER（字元編輯距離）
相似度指標，取代/對照現有 compare_paragraphs() 用的 SequenceMatcher.ratio()。

背景：上一輪試做2發現 SequenceMatcher.ratio()（87.39%）跟字元n-gram覆蓋率
（27-40%）數字差很多，跟DeepSeek討論後，DeepSeek建議正式方案改用「段落最佳
配對 + 字元編輯距離相似度(1-CER)，按段落字數加權平均」，理由是它同時處理
替代/插入/刪除，是語音辨識評估的標準做法，比SequenceMatcher更誠實（不會被
「允許跳過大段」誤導），比n-gram更不受單一錯字過度放大影響。

這輪延伸試做：真的實作這個指標，在同一份 EP680 真實資料上算出來，跟前兩輪
的兩個指標三方對照。

**這是試做，不是正式功能**——不修改 sync_independent_transcripts.py 正式的
compare_paragraphs()，這裡是獨立函式，用既有 EP680 資料做唯讀驗證。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from independent_transcribe import srt_to_md
from sync_independent_transcripts import compare_paragraphs  # 對照組


def levenshtein(a: str, b: str) -> int:
    """標準字元編輯距離（動態規劃）。這份資料量（2萬字）用 O(n*m) DP 會太慢
    （2萬*2萬=4億格），所以下面按段落分別算，每段只有幾百字，這樣可行。"""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[-1]


def cer_similarity(a: str, b: str) -> float:
    """1 - CER，CER = 編輯距離 / 較長字串長度。"""
    if not a and not b:
        return 1.0
    dist = levenshtein(a, b)
    return 1 - dist / max(len(a), len(b))


def paras(text: str) -> list[str]:
    return [p.strip() for p in text.split("\n\n") if p.strip() and not p.strip().startswith("#")]


def best_match_align(remote_paras: list[str], indep_paras: list[str]) -> list[tuple[str, str, float]]:
    """簡化版「段落最佳配對」：對每個 whatmkreallysaid.com 版段落，在獨立版裡找
    CER相似度最高的段落當配對對象（貪婪、不要求一對一，這是試做的簡化版，
    正式版如果要做應該用匈牙利演算法或動態規劃做真正的最佳一對一配對）。

    效能考量（試做階段的務實取捨，時間有限）：完全窮舉 89*40 對、每對都做
    O(len^2) 的字元級 Levenshtein DP，在純 Python 下會太慢。兩邊文字都是同一集
    節目、依時間順序排列，所以用「位置比例視窗」縮小搜尋範圍——只比對獨立版裡
    位置比例接近的段落（±20%視窗），而不是每個 remote 段落都跟全部 40 個獨立版
    段落做完整 DP。這是效能取捨不是演算法本身的限制，正式版如果要做，這步應該
    用真正的動態規劃全域最佳配對（DeepSeek 提過的 Vecalign/SentAlign 那類方法）。
    """
    n_remote, n_indep = len(remote_paras), len(indep_paras)
    window_ratio = 0.2
    pairs = []
    for i, rp in enumerate(remote_paras):
        center = (i / max(n_remote - 1, 1)) * (n_indep - 1)
        window = max(3, int(n_indep * window_ratio))
        lo = max(0, int(center - window))
        hi = min(n_indep, int(center + window) + 1)
        best_sim, best_ip = -1.0, ""
        for ip in indep_paras[lo:hi]:
            if abs(len(rp) - len(ip)) > max(len(rp), len(ip)) * 0.8:
                continue
            sim = cer_similarity(rp, ip)
            if sim > best_sim:
                best_sim, best_ip = sim, ip
        pairs.append((rp, best_ip, best_sim if best_sim >= 0 else 0.0))
    return pairs


def main():
    real_srt = Path(r"D:\All claude\300_Projects\video-transcribe\media\EP680_v2\source.srt")
    remote_md = (Path(__file__).parent.parent / "transcripts" / "EP680_筷子信仰與台積電心碎記.md").read_text(encoding="utf-8")
    indep_md = srt_to_md(real_srt, "EP680", "筷子信仰與台積電心碎記")

    print("=== 對照組1：SequenceMatcher.ratio()（正式版現用）===", flush=True)
    para_result = compare_paragraphs(remote_md, indep_md)
    print(f"相似度: {para_result['similarity_ratio']:.2%}", flush=True)

    print("\n=== 對照組2：字元n-gram覆蓋率（上一輪試做2b）===", flush=True)
    print("n=6: 39.90%（見 trial2b_demo_output.txt，這裡不重算節省時間）", flush=True)

    print("\n=== 試做版：CER-based段落配對相似度 ===", flush=True)
    remote_paras, indep_paras = paras(remote_md), paras(indep_md)
    print(f"whatmkreallysaid.com版 {len(remote_paras)} 段，獨立版 {len(indep_paras)} 段，開始配對...", flush=True)
    pairs = best_match_align(remote_paras, indep_paras)
    weighted_sum = sum(sim * len(rp) for rp, ip, sim in pairs)
    total_len = sum(len(rp) for rp, ip, sim in pairs)
    weighted_cer_sim = weighted_sum / total_len if total_len else 0.0
    simple_avg = sum(sim for _, _, sim in pairs) / len(pairs) if pairs else 0.0

    print(f"CER相似度（字數加權平均）: {weighted_cer_sim:.2%}", flush=True)
    print(f"CER相似度（簡單平均，不加權）: {simple_avg:.2%}", flush=True)

    lines = [
        "=== 三種相似度指標對照（同一份EP680真實資料）===",
        f"1. SequenceMatcher.ratio()（正式版現用）: {para_result['similarity_ratio']:.2%}",
        f"2. 字元n-gram覆蓋率(n=6)（上一輪試做2b）: 39.90%",
        f"3. CER-based段落配對相似度（本輪試做5，字數加權）: {weighted_cer_sim:.2%}",
        f"   CER-based段落配對相似度（簡單平均，未加權）: {simple_avg:.2%}",
        "",
        f"段落配對數: {len(pairs)}（whatmkreallysaid.com版{len(remote_paras)}段 vs 獨立版{len(indep_paras)}段）",
        "",
        "=== 各段落CER相似度分布（前10筆）===",
    ]
    for rp, ip, sim in pairs[:10]:
        lines.append(f"相似度 {sim:.1%} | whatmkreallysaid.com版片段: {rp[:40]}...")

    out_path = Path(__file__).parent / "trial5_demo_output.txt"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n已存檔：{out_path}")


if __name__ == "__main__":
    main()
