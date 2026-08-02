"""驗證 batch_dedup_selection_prototype.py::load_transcripts_dedup_aware()。
全部在暫存目錄操作，不碰正式 transcripts/。"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from batch_dedup_selection_prototype import load_transcripts_dedup_aware


def setup(tmp: Path):
    transcripts = tmp / "transcripts"
    transcripts.mkdir()
    manifest_dir = tmp / "transcripts_data" / "independent_transcribe"
    manifest_dir.mkdir(parents=True)
    manifest_path = manifest_dir / "manifest.json"
    return transcripts, manifest_path


def write_manifest(manifest_path: Path, records: list[dict]):
    manifest_path.write_text(json.dumps({"records": records}, ensure_ascii=False), encoding="utf-8")


def test_duplicate_prefers_official():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        transcripts, manifest_path = setup(tmp)
        (transcripts / "EP600_獨立轉錄.md").write_text("獨立版", encoding="utf-8")
        (transcripts / "EP600_官方標題.md").write_text("官方版", encoding="utf-8")
        write_manifest(manifest_path, [{"ep_id": "EP600", "path": "transcripts\\EP600_獨立轉錄.md"}])

        result = load_transcripts_dedup_aware(transcripts, manifest_path)
        names = [f.name for f in result]
        assert names == ["EP600_官方標題.md"], f"應該只選官方版，實際：{names}"
        print("[PASS] 重複時優先選官方版，獨立版被排除在分析清單外")


def test_no_official_falls_back_to_independent():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        transcripts, manifest_path = setup(tmp)
        (transcripts / "EP601_獨立轉錄.md").write_text("獨立版", encoding="utf-8")
        write_manifest(manifest_path, [{"ep_id": "EP601", "path": "transcripts\\EP601_獨立轉錄.md"}])

        result = load_transcripts_dedup_aware(transcripts, manifest_path)
        names = [f.name for f in result]
        assert names == ["EP601_獨立轉錄.md"], f"沒有官方版時應該退回獨立版，實際：{names}"
        print("[PASS] 沒有官方版可選時，正常保留獨立版（不會整集消失不分析）")


def test_no_duplicates_unaffected():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        transcripts, manifest_path = setup(tmp)
        (transcripts / "EP602_x.md").write_text("x", encoding="utf-8")
        (transcripts / "EP603_y.md").write_text("y", encoding="utf-8")
        write_manifest(manifest_path, [])

        result = load_transcripts_dedup_aware(transcripts, manifest_path)
        names = sorted(f.name for f in result)
        assert names == ["EP602_x.md", "EP603_y.md"], f"正常情況不該受影響，實際：{names}"
        print("[PASS] 無重複的正常情況完全不受影響")


def test_ordering_still_by_ep_number():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        transcripts, manifest_path = setup(tmp)
        (transcripts / "EP610_a.md").write_text("a", encoding="utf-8")
        (transcripts / "EP605_b.md").write_text("b", encoding="utf-8")
        (transcripts / "EP608_c.md").write_text("c", encoding="utf-8")
        write_manifest(manifest_path, [])

        result = load_transcripts_dedup_aware(transcripts, manifest_path)
        names = [f.name for f in result]
        assert names == ["EP605_b.md", "EP608_c.md", "EP610_a.md"], f"排序應該仍按EP編號，實際：{names}"
        print("[PASS] 排序邏輯（按EP編號）不受這輪修改影響")


def test_real_data_unaffected_count():
    """跟真實 transcripts/ 目錄比對：目前0重複，這個函式選出的檔案數量應該
    跟原版 batch.py::load_transcripts() 完全一樣（因為沒有重複可以濾）。"""
    real_transcripts = Path(__file__).parent.parent.parent / "transcripts"
    real_manifest = Path(__file__).parent.parent.parent / "transcripts_data" / "independent_transcribe" / "manifest.json"
    if not real_transcripts.exists():
        print("[SKIP] 找不到正式 transcripts/ 目錄")
        return
    result = load_transcripts_dedup_aware(real_transcripts, real_manifest)
    original_count = len(list(real_transcripts.glob("EP*.md")))
    print(f"[INFO] 正式資料：原始檔案數={original_count}，dedup-aware選出數={len(result)}"
          f"（應該相等，因為目前沒有重複可濾）：{'一致' if original_count == len(result) else '不一致，需查'}")
    assert original_count == len(result)


if __name__ == "__main__":
    test_duplicate_prefers_official()
    test_no_official_falls_back_to_independent()
    test_no_duplicates_unaffected()
    test_ordering_still_by_ep_number()
    test_real_data_unaffected_count()
    print("\n全部測試通過。")
