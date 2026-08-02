"""自我精進 Part B 試做 2b：延續試做2的負面結果，驗證 DeepSeek 建議的替代方案。

DeepSeek 對試做2負面結果的診斷：「標點不能當切分訊號」不等於「細粒度對齊沒用」，
建議改用「兩邊都存在的訊號」當比對單位——詞級 tokenization 或字元 n-gram shingle。

**注意（誠實記錄 DeepSeek 建議的一個問題）**：DeepSeek 建議「兩邊都用空白切詞
（whisper 一定有空格）」——這對英文成立，但這個專案是**中文**逐字稿，中文書寫
不用空白分詞，whisper 的中文輸出也沒有詞邊界空格（可用 trial1/trial2 的
demo_output.txt 檔案內容直接驗證：完全沒有空格）。所以「詞級 tokenization」
這條路對中文不能直接套用（需要額外的中文斷詞工具，例如 jieba，這輪環境沒裝，
也算新增依賴，不符合「快速試做、不新增正式依賴」的精神）。

改採 DeepSeek 建議的第二條路：**字元 n-gram shingle**——不需要任何斷詞，語言
無關，直接可用。用「兩邊共同出現的 n 字元子字串比例」估算內容覆蓋率，驗證
DeepSeek 的核心論點：「巨型 replace 是分段/格式造成的幻象，不是內容真的不同」。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from independent_transcribe import srt_to_md


def char_ngrams(text: str, n: int = 8) -> set[str]:
    """把文字切成長度 n 的字元 n-gram 集合（不需要斷詞，中英文皆可用）。"""
    clean = "".join(ch for ch in text if not ch.isspace())
    return {clean[i:i + n] for i in range(len(clean) - n + 1)}


def ngram_coverage(remote_text: str, independent_text: str, n: int = 8) -> dict:
    """估算兩份文字的字元 n-gram 重疊率，語言無關、不需要斷詞/embedding。"""
    remote_grams = char_ngrams(remote_text, n)
    indep_grams = char_ngrams(independent_text, n)
    if not remote_grams or not indep_grams:
        return {"coverage_remote_in_indep": 0.0, "jaccard": 0.0}
    overlap = remote_grams & indep_grams
    return {
        "remote_ngram_count": len(remote_grams),
        "indep_ngram_count": len(indep_grams),
        "overlap_count": len(overlap),
        # 第三方版有多少比例的 n-gram 也出現在獨立版裡——這是「內容覆蓋率」的代理指標，
        # 不受兩邊分段方式不同影響（n-gram 本來就是滑動窗，不看段落邊界）。
        "coverage_remote_in_indep": round(len(overlap) / len(remote_grams), 4),
        "jaccard": round(len(overlap) / len(remote_grams | indep_grams), 4),
    }


def main():
    real_srt = Path(r"D:\All claude\300_Projects\video-transcribe\media\EP680_v2\source.srt")
    remote_md = (Path(__file__).parent.parent / "transcripts" / "EP680_筷子信仰與台積電心碎記.md").read_text(encoding="utf-8")
    indep_md = srt_to_md(real_srt, "EP680", "筷子信仰與台積電心碎記")

    lines = ["=== 字元 n-gram 覆蓋率估算（語言無關，不需要斷詞/embedding）==="]
    for n in (6, 8, 12):
        result = ngram_coverage(remote_md, indep_md, n=n)
        lines.append(f"\nn={n}:")
        lines.append(f"  whatmkreallysaid.com版 {n}-gram 數: {result['remote_ngram_count']}")
        lines.append(f"  獨立版 {n}-gram 數: {result['indep_ngram_count']}")
        lines.append(f"  重疊數: {result['overlap_count']}")
        lines.append(f"  覆蓋率(whatmkreallysaid.com版有多少比例的{n}-gram也出現在獨立版): "
                     f"{result['coverage_remote_in_indep']:.2%}")
        lines.append(f"  Jaccard相似度: {result['jaccard']:.2%}")

    lines.append("\n=== 對照：正式版/試做版既有結果 ===")
    lines.append("段落粒度(正式版compare_paragraphs): 相似度87.39%, diff_count=1")
    lines.append("短句粒度(試做2,失敗): 獨立版只有8個chunk, diff_count=1(無意義)")

    out_path = Path(__file__).parent / "trial2b_demo_output.txt"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"\n已存檔：{out_path}")


if __name__ == "__main__":
    main()
