"""自我精進 Part B 第三輪：實作 DeepSeek 最後建議的「SequenceMatcher粗對齊 + CER計分」
混合方案——把前兩輪的研究收斂成一個可用的參考實作，不是只停在概念討論。

背景：試做5發現直接對不等長段落算CER會被「粒度天花板」誤導出過低數字；
試做5b用同長度合成資料證明CER本身是準確的相似度計量器。DeepSeek在5b的討論
裡具體建議：**用SequenceMatcher.get_matching_blocks()先做全文字元級的粗對齊
（找出兩邊逐字相同的長區塊當錨點），只在「錨點之間的間隙」（也就是真正有
差異的地方）才用CER計分**——這樣完全跳過段落切分/配對的問題，因為
get_matching_blocks()本身就是在做全域最佳對齊（Ratcliff-Obershelp演算法），
不需要我們自己切段落。

方法：
1. 對「whatmkreallysaid.com版全文」vs「獨立版全文」跑
   difflib.SequenceMatcher.get_matching_blocks()——這是 compare_paragraphs()
   現有 overall_ratio 已經在用的同一個底層機制，只是這裡進一步利用它回傳的
   逐塊資訊，不是只拿最後的單一 ratio() 數字。
2. 相同區塊(matching block)直接算「完全相同」，不需要再算CER。
3. 兩個相同區塊之間的「間隙」（一邊有多的內容、或兩邊都有但不同的內容），
   才對這一小段間隙做CER計分——間隙通常很短（不像整段落那麼長），不會遇到
   trial5的粒度天花板問題。
4. 加總：整份文件的相似度 = 1 - (所有間隙的編輯距離總和) / 較長文本總長度。

**這是試做，不是正式功能**——不修改 sync_independent_transcripts.py 正式的
compare_paragraphs()，這裡是獨立函式，用既有 EP680 資料做唯讀驗證，證明這個
混合方案是否真的能給出更接近真實情況（DeepSeek原估83-88%）的數字。
"""
import difflib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from independent_transcribe import srt_to_md
from sync_independent_transcripts import compare_paragraphs  # 對照組


def levenshtein(a: str, b: str) -> int:
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


def hybrid_alignment_similarity(remote_text: str, indep_text: str) -> dict:
    """SequenceMatcher 粗對齊（找逐字相同的錨點區塊）+ 只在間隙做CER計分。

    2026-08-02 索羅門依 DeepSeek review 補上 edge case：兩邊都是空字串時
    max(len,len)=0 會除以零，這裡提前回傳 1.0（定義成完全相同）。
    """
    if not remote_text and not indep_text:
        return {"similarity": 1.0, "matched_chars": 0, "gap_count": 0,
                "max_gap_len": 0, "total_gap_cost": 0, "total_len": 0}
    sm = difflib.SequenceMatcher(None, remote_text, indep_text, autojunk=False)
    blocks = sm.get_matching_blocks()  # 最後一筆是 size=0 的哨兵，標記結尾

    total_gap_cost = 0
    total_matched_chars = 0
    gap_count = 0
    max_gap_len = 0
    prev_a_end, prev_b_end = 0, 0

    for block in blocks:
        a_start, b_start, size = block.a, block.b, block.size
        gap_a = remote_text[prev_a_end:a_start]
        gap_b = indep_text[prev_b_end:b_start]
        if gap_a or gap_b:
            gap_count += 1
            max_gap_len = max(max_gap_len, len(gap_a), len(gap_b))
            total_gap_cost += levenshtein(gap_a, gap_b)
        total_matched_chars += size
        prev_a_end, prev_b_end = a_start + size, b_start + size

    total_len = max(len(remote_text), len(indep_text))
    similarity = 1 - total_gap_cost / total_len if total_len else 1.0
    return {
        "similarity": round(similarity, 4),
        "matched_chars": total_matched_chars,
        "gap_count": gap_count,
        "max_gap_len": max_gap_len,
        "total_gap_cost": total_gap_cost,
        "total_len": total_len,
    }


def main():
    real_srt = Path(r"D:\All claude\300_Projects\video-transcribe\media\EP680_v2\source.srt")
    remote_md = (Path(__file__).parent.parent / "transcripts" / "EP680_筷子信仰與台積電心碎記.md").read_text(encoding="utf-8")
    indep_md = srt_to_md(real_srt, "EP680", "筷子信仰與台積電心碎記")

    print("開始計算混合方案相似度（get_matching_blocks粗對齊 + 間隙CER計分）...", flush=True)
    result = hybrid_alignment_similarity(remote_md, indep_md)

    para_result = compare_paragraphs(remote_md, indep_md)

    lines = [
        "=== 四種相似度指標總對照（同一份EP680真實資料，三輪試做累積）===",
        f"1. SequenceMatcher.ratio()（正式版現用）: {para_result['similarity_ratio']:.2%}",
        f"2. 字元n-gram覆蓋率(n=6)（第一輪試做2b）: 39.90%",
        f"3. CER-based段落配對相似度（第二輪試做5，有粒度天花板缺陷）: 29.41%",
        f"4. 混合方案：get_matching_blocks粗對齊+間隙CER計分（本輪試做6）: {result['similarity']:.2%}",
        "",
        "=== 混合方案細節 ===",
        f"逐字相同的錨點字元數: {result['matched_chars']} / {result['total_len']} "
        f"({result['matched_chars']/result['total_len']:.1%})",
        f"間隙(差異)區塊數: {result['gap_count']}",
        f"最長單一間隙: {result['max_gap_len']} 字",
        f"所有間隙的編輯距離總和: {result['total_gap_cost']}",
        "",
        "=== 結論 ===",
    ]
    if 0.80 <= result["similarity"] <= 0.92:
        lines.append(f"混合方案算出 {result['similarity']:.2%}，落在DeepSeek原本預期的83-88%附近，"
                     f"且方法論上解決了試做5的粒度天花板問題（不對不等長段落整段算CER，"
                     f"只在真正有差異的間隙才計分）——這是三輪試做裡最接近「可直接拿去用」"
                     f"的參考實作。")
    else:
        lines.append(f"混合方案算出 {result['similarity']:.2%}，跟DeepSeek預期的83-88%有落差，"
                     f"需要進一步討論原因。")

    out_path = Path(__file__).parent / "trial6_demo_output.txt"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"\n已存檔：{out_path}")


if __name__ == "__main__":
    main()
