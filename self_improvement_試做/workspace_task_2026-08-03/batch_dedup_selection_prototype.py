"""
索羅門工作區任務（2026-08-03）Track 1收尾：batch.py根因修正的具體demo。

背景：Track 1（dedup_prototype.py/v2）用「掃描transcripts/目錄+移動獨立版檔案」解決
重複集數問題，DeepSeek審查指出這只是清症狀，真正根因在
`batch.py::load_transcripts()`——`sorted(glob(...), key=ep_number)` 對「同一EP編號
兩個檔案」這種情況，用 Python `sorted()` 的穩定排序特性保留 `glob()` 原始順序，而
`glob()` 順序是作業系統檔案系統目錄項順序，不是設計出來的邏輯，等於「誰先被讀到用誰」
是隨機的，不是選了品質更好的官方版。

這個demo展示一個**不用刪檔案、不用移動檔案**的替代/互補做法：在「挑選哪個檔案送進
分析」這一步，就優先選非獨立轉錄來源（官方版）的檔案，讓行為變成「有官方版就一定用
官方版」，不是碰運氣。這是**建議附試做佐證**，不修改 batch.py 本身。

**這輪索羅門判斷**：這個做法可以跟Track 1的quarantine方案**互補**而不是二選一——
quarantine解決「transcripts/目錄裡不要留兩份檔案」（清爽度/儲存空間），這個demo解決
「即使因為某種原因兩份檔案還沒被quarantine，分析結果也不會碰運氣選錯版本」（正確性
的最後一道防線）。兩個都做，互相補強；只做這個demo不做quarantine，目錄還是會亂；
只做quarantine不做這個，quarantine執行前的空窗期（例如排程還沒跑到那一次）分析結果
仍然可能碰運氣選到獨立版。
"""
import json
import re
from pathlib import Path

EP_RE = re.compile(r"EP(\d+)", re.IGNORECASE)


def ep_number(path: Path) -> int:
    m = EP_RE.match(path.stem)
    return int(m.group(1)) if m else 0


def load_manifest_filenames(manifest_path: Path) -> set[str]:
    if not manifest_path.exists():
        return set()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {Path(r["path"]).name for r in data.get("records", []) if r.get("path")}


def load_transcripts_dedup_aware(
    transcripts_dir: Path, manifest_path: Path, from_ep: int = 0, last_n: int = 0
) -> list[Path]:
    """對照 batch.py::load_transcripts()，這是加了「同EP多檔案時優先選非獨立轉錄版」
    邏輯的版本。原版：
        files = sorted(TRANSCRIPTS_DIR.glob("EP*.md"), key=ep_number)
    這個版本多一步：同EP編號如果有多個檔案，且其中至少一個不在manifest記錄裡（=推定為
    官方版），就只保留非manifest的那個/那些，manifest記錄的（獨立轉錄版）從清單裡濾掉，
    不送進分析——不改動檔案系統，只改「這次批次要分析誰」的挑選邏輯。
    """
    manifest_names = load_manifest_filenames(manifest_path)
    all_files = sorted(transcripts_dir.glob("EP*.md"), key=ep_number)

    by_ep: dict[int, list[Path]] = {}
    for f in all_files:
        by_ep.setdefault(ep_number(f), []).append(f)

    selected: list[Path] = []
    for ep, files in by_ep.items():
        if len(files) == 1:
            selected.append(files[0])
            continue
        official = [f for f in files if f.name not in manifest_names]
        independent = [f for f in files if f.name in manifest_names]
        if official:
            # 有官方版，一律優先選官方版，獨立版全部濾掉不送分析
            selected.extend(official)
        else:
            # 全部都是獨立版（沒有官方版可選），維持原行為全部保留
            selected.extend(independent if independent else files)

    selected.sort(key=ep_number)

    if from_ep:
        selected = [f for f in selected if ep_number(f) >= from_ep]
    if last_n:
        selected = selected[-last_n:]
    return selected


if __name__ == "__main__":
    import sys
    print("這是demo/建議檔案，不接受直接對正式 transcripts/ 執行分析。")
    print("驗證見同目錄 batch_dedup_selection_test.py。")
    sys.exit(0)
