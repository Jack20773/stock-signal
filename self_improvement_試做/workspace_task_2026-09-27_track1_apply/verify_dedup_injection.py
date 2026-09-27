"""Track1 上線驗收腳本（2026-09-27）。

驗什麼：batch.py::load_transcripts() 接上 dedup-aware 選擇邏輯（commit f285894 demo
正式上線）之後，行為符合預期，而且量尺本身有鑑別度（不是恆真的綠燈）。

三組測試，全部直接呼叫 batch.py 的真正函式（不是重寫一份等價邏輯）：
  1. 迴歸：對正式 transcripts/ 目錄跑一次，跟「未去重」的 naive glob 結果比對，
     母體用真實檔案數。2026-09-27 現況（見 daily 查證）：4 組已知重複集數
     （EP681-684）已在 2026-09-03 被手動改名成 .bak-20260903-dedupe 後綴，
     不再命中 `EP*.md` glob，所以正式資料現在的重複母體＝0——這正是為什麼
     一定要做下面的注入測試，不能只驗正式資料。
  2. 注入組（塞一筆刻意重複）：EP900 兩個檔案，一個不在 manifest（推定官方版）、
     一個在 manifest（推定獨立版）→ 期望只留官方版，去重數字要動（從 2 變 1）。
  3. 對照組（塞一筆不重複）：EP901 只有一個檔案 → 期望不受影響，數字不准動。
     另外多測一組「兩個都是獨立版、都不是官方版」→ 期望維持原行為全部保留
     （不能因為都在 manifest 就一個都不留）。

跑法：python verify_dedup_injection.py
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import batch  # noqa: E402  (要在 sys.path 設好之後才 import)


def naive_glob_count(transcripts_dir: Path) -> int:
    return len(list(transcripts_dir.glob("EP*.md")))


def run_case(tmp_dir: Path, files: dict[str, str], manifest_names: list[str], label: str):
    """files: {filename: content}；manifest_names: 要寫進 manifest.json 的檔名清單。"""
    transcripts_dir = tmp_dir / "transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (transcripts_dir / name).write_text(content, encoding="utf-8")

    manifest_path = tmp_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps({"records": [{"path": n} for n in manifest_names]}, ensure_ascii=False),
        encoding="utf-8",
    )

    # monkeypatch batch.py 的模組層常數，不碰正式 transcripts/ 目錄
    orig_dir, orig_manifest = batch.TRANSCRIPTS_DIR, batch.MANIFEST_PATH
    batch.TRANSCRIPTS_DIR = transcripts_dir
    batch.MANIFEST_PATH = manifest_path
    try:
        naive = naive_glob_count(transcripts_dir)
        selected = batch.load_transcripts()
        selected_names = sorted(f.name for f in selected)
        print(f"[{label}] naive_glob={naive} dedup_aware={len(selected)} selected={selected_names}")
        return naive, len(selected), selected_names
    finally:
        batch.TRANSCRIPTS_DIR, batch.MANIFEST_PATH = orig_dir, orig_manifest


def main():
    results = {}

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)

        # 1) 迴歸：對正式 transcripts/ 目錄跑（不 monkeypatch，直接用真常數）
        real_naive = naive_glob_count(batch.TRANSCRIPTS_DIR)
        real_selected = batch.load_transcripts()
        print(f"[正式資料迴歸] naive_glob={real_naive} dedup_aware={len(real_selected)}")
        results["regression_naive"] = real_naive
        results["regression_selected"] = len(real_selected)

        # 2) 注入組：EP900 兩個檔案，一官方一獨立
        n, s, names = run_case(
            tmp / "inject_dup",
            {
                "EP900_official.md": "官方版內容",
                "EP900_independent.md": "獨立轉錄版內容",
            },
            manifest_names=["EP900_independent.md"],
            label="注入組-重複",
        )
        results["inject_dup_naive"] = n
        results["inject_dup_selected"] = s
        results["inject_dup_names"] = names

        # 3a) 對照組：EP901 只有一個檔案，不在 manifest
        n, s, names = run_case(
            tmp / "control_solo",
            {"EP901_solo.md": "單一版本內容"},
            manifest_names=[],
            label="對照組-不重複",
        )
        results["control_solo_naive"] = n
        results["control_solo_selected"] = s

        # 3b) 邊界對照：EP902 兩個檔案，但兩個都在 manifest（都是獨立版、沒有官方版）
        n, s, names = run_case(
            tmp / "control_both_independent",
            {
                "EP902_v1.md": "獨立版1",
                "EP902_v2.md": "獨立版2",
            },
            manifest_names=["EP902_v1.md", "EP902_v2.md"],
            label="邊界對照-兩者皆獨立版",
        )
        results["control_both_indep_naive"] = n
        results["control_both_indep_selected"] = s

    # ---- 斷言（鑑別度：注入要讓數字動，對照不准動）----
    assert results["inject_dup_naive"] == 2 and results["inject_dup_selected"] == 1, \
        f"注入組應該從2篩到1，實際：{results['inject_dup_naive']}->{results['inject_dup_selected']}"
    assert results["inject_dup_names"] == ["EP900_official.md"], \
        f"注入組應該只留官方版，實際留下：{results['inject_dup_names']}"
    assert results["control_solo_naive"] == results["control_solo_selected"] == 1, \
        "不重複的對照組數字不准變動"
    assert results["control_both_indep_naive"] == results["control_both_indep_selected"] == 2, \
        "兩者皆獨立版時應維持原行為全部保留，不准被誤刪成0或1"
    assert results["regression_naive"] == results["regression_selected"], (
        f"正式資料迴歸：naive={results['regression_naive']} "
        f"dedup_aware={results['regression_selected']}，兩者不相等代表現在正式"
        f"資料裡藏著尚未被人工處理的重複，需要人工確認才能判斷是否為預期。"
    )

    print("\n全部斷言通過。")
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
