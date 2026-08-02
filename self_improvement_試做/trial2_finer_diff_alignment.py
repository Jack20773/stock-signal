"""自我精進 Part B 試做 2：更細粒度的差異對齊，改善 compare_paragraphs() 的已知限制。

背景：完工前 Codex 審查指出 sync_independent_transcripts.py::compare_paragraphs()
在段落（paragraph）粒度上比對，whatmkreallysaid.com 版是人工主題分節、獨立版是
純字數切段，兩者分段方式不同時，即使文字幾乎相同也可能整篇被判成一大塊
「replace」，診斷價值不高（已記錄在 SOLOMON_HANDOFF.md remaining_risk 第2點）。

查證：業界作法（Vecalign/SentAlign 等文獻）是用 embedding + 動態規劃做語義對齊，
但這需要額外的 embedding 模型（這輪環境沒有現成的中文 embedding 服務可用）。
這裡試做一個更輕量、不需要額外模型的替代方案：**把兩邊文字都重新切成統一的細粒度
單位（逗號/短句），再讓 SequenceMatcher 在這個細粒度上比對**——不改變比對演算法
本身，只改變「切多細」，用來驗證「細粒度切法」本身能不能顯著改善診斷粒度。

**這是試做，不是正式功能**——不修改 sync_independent_transcripts.py 正式邏輯，
只是獨立示範可行性，用既有的 EP680 資料（whatmkreallysaid.com 版 + 獨立轉錄版）
唯讀比對。
"""
import difflib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from independent_transcribe import srt_to_md
from sync_independent_transcripts import compare_paragraphs  # 正式版（段落粒度），當對照組


def split_clauses(text: str) -> list[str]:
    """把文字切成細粒度的「短句」單位：任何逗號/句號/分號/問號/驚嘆號都當切點。
    比 compare_paragraphs() 現在的「整段落」單位細得多，理論上能讓 SequenceMatcher
    的錨點更密集，減少「因分段方式不同被判成大塊replace」的問題。
    """
    text = re.sub(r"[#\n]+", " ", text)  # 去掉標題符號跟換行，避免格式字元干擾切句
    clauses = re.split(r"([，,。.！!？?；;])", text)
    # re.split 保留分隔符，這裡把分隔符黏回前一個片段，並過濾空白
    merged = []
    for i in range(0, len(clauses) - 1, 2):
        piece = (clauses[i] + (clauses[i + 1] if i + 1 < len(clauses) else "")).strip()
        if piece:
            merged.append(piece)
    if len(clauses) % 2 == 1 and clauses[-1].strip():
        merged.append(clauses[-1].strip())
    return merged


def compare_clauses(remote_text: str, independent_text: str) -> dict:
    """試做版：細粒度（短句）對齊，跟正式版 compare_paragraphs() 的段落粒度對照。"""
    remote_clauses = split_clauses(remote_text)
    indep_clauses = split_clauses(independent_text)
    sm = difflib.SequenceMatcher(None, remote_clauses, indep_clauses, autojunk=False)
    diffs = [op for op in sm.get_opcodes() if op[0] != "equal"]
    equal_ratio = sum((i2 - i1) for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag == "equal") / max(len(remote_clauses), 1)
    return {
        "remote_clause_count": len(remote_clauses),
        "indep_clause_count": len(indep_clauses),
        "diff_block_count": len(diffs),
        "matched_clause_ratio": round(equal_ratio, 4),
        "sample_diffs": diffs[:5],
    }


def main():
    srt_path = Path(__file__).parent.parent / "transcripts_data" / "independent_media" / "EP680_v2_missing"
    # EP680 的獨立轉錄 srt 實際放在 video-transcribe 專案（唯讀，這輪任務原本就用它做過測試）
    real_srt = Path(r"D:\All claude\300_Projects\video-transcribe\media\EP680_v2\source.srt")
    remote_md = (Path(__file__).parent.parent / "transcripts" / "EP680_筷子信仰與台積電心碎記.md").read_text(encoding="utf-8")
    indep_md = srt_to_md(real_srt, "EP680", "筷子信仰與台積電心碎記")

    print("=== 對照組：正式版 compare_paragraphs()（段落粒度）===")
    para_result = compare_paragraphs(remote_md, indep_md)
    print(f"相似度: {para_result['similarity_ratio']:.2%}  差異區塊數: {para_result['diff_count']}")

    print("\n=== 試做版：compare_clauses()（短句粒度）===")
    clause_result = compare_clauses(remote_md, indep_md)
    print(f"whatmkreallysaid.com版短句數: {clause_result['remote_clause_count']}  "
          f"獨立版短句數: {clause_result['indep_clause_count']}")
    print(f"對齊上的短句比例: {clause_result['matched_clause_ratio']:.2%}  "
          f"差異區塊數: {clause_result['diff_block_count']}")

    out_path = Path(__file__).parent / "trial2_demo_output.txt"
    lines = [
        "=== 對照組：正式版 compare_paragraphs()（段落粒度）===",
        f"相似度: {para_result['similarity_ratio']:.2%}  差異區塊數: {para_result['diff_count']}",
        "",
        "=== 試做版：compare_clauses()（短句粒度）===",
        f"whatmkreallysaid.com版短句數: {clause_result['remote_clause_count']}  "
        f"獨立版短句數: {clause_result['indep_clause_count']}",
        f"對齊上的短句比例: {clause_result['matched_clause_ratio']:.2%}  "
        f"差異區塊數: {clause_result['diff_block_count']}",
        "",
        "=== 前 5 個差異區塊樣本（短句粒度）===",
    ]
    remote_clauses = split_clauses(remote_md)
    indep_clauses = split_clauses(indep_md)
    for tag, i1, i2, j1, j2 in clause_result["sample_diffs"]:
        # 差異區塊可能橫跨幾百個短句(見trial2實測發現)，只截斷顯示前3+後3個，避免輸出爆量
        def _preview(seq):
            if len(seq) <= 6:
                return seq
            return seq[:3] + [f"...(略過中間 {len(seq)-6} 筆)..."] + seq[-3:]
        lines.append(f"[{tag}] 涵蓋 whatmkreallysaid.com版第{i1}-{i2}筆(共{i2-i1}筆)/"
                     f"獨立版第{j1}-{j2}筆(共{j2-j1}筆)")
        lines.append(f"  whatmkreallysaid.com版預覽: {_preview(remote_clauses[i1:i2])}")
        lines.append(f"  獨立版預覽: {_preview(indep_clauses[j1:j2])}")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n已存檔：{out_path}")


if __name__ == "__main__":
    main()
