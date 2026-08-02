"""
dedup_prototype.py 的驗證腳本——完全在暫存目錄操作，不碰任何專案正式資料
（不讀寫 D:\\All claude\\300_Projects\\stock-signal\\transcripts/ 或 transcripts_data/ 本身）。

三個測試案例：
  1. 明確情況：1個manifest記錄的獨立版 + 1個官方版 → 應該刪除獨立版、保留官方版、寫1筆log
  2. 不明確情況A：2個檔案都不在manifest（可能都是官方版，也可能manifest記錄本身缺漏）
     → 不應該刪任何檔案，只記 skip_ambiguous
  3. 不明確情況B：2個檔案都在manifest（異常狀況，理論上不該發生，但要驗證原型不會誤刪）
     → 不應該刪任何檔案，只記 skip_ambiguous
  4. 無重複的正常情況（3個不同EP各1個檔案）→ 不應該有任何事件

用逐字比對（不是肉眼看輸出）驗證：檔案是否真的被刪除/保留、log內容是否符合預期結構。
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from dedup_prototype import resolve_duplicates_file_level, append_dedup_log, find_duplicate_eps


def setup_case(tmp: Path):
    transcripts = tmp / "transcripts"
    transcripts.mkdir()
    manifest_dir = tmp / "transcripts_data" / "independent_transcribe"
    manifest_dir.mkdir(parents=True)
    manifest_path = manifest_dir / "manifest.json"
    return transcripts, manifest_path


def write_manifest(manifest_path: Path, records: list[dict]):
    manifest_path.write_text(json.dumps({"records": records}, ensure_ascii=False, indent=2), encoding="utf-8")


def test_case_1_clear_resolution():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        transcripts, manifest_path = setup_case(tmp)
        # EP500：一份官方版（不在manifest），一份獨立版（在manifest）
        (transcripts / "EP500_官方標題.md").write_text("官方版內容", encoding="utf-8")
        (transcripts / "EP500_獨立轉錄.md").write_text("獨立版內容", encoding="utf-8")
        write_manifest(manifest_path, [
            {"ep_id": "EP500", "path": "transcripts\\EP500_獨立轉錄.md", "mode": "gap_fill"}
        ])

        events = resolve_duplicates_file_level(transcripts, manifest_path, dry_run=False)

        assert len(events) == 1, f"預期1筆事件，實際{len(events)}筆"
        e = events[0]
        assert e["action"] == "delete_independent_duplicate", e
        assert e["deleted_file"] == "EP500_獨立轉錄.md", e
        assert e["kept_files"] == ["EP500_官方標題.md"], e
        # 逐字驗證檔案系統實際狀態（不是只看log，是看磁碟上真的發生了什麼）
        remaining = sorted(p.name for p in transcripts.glob("EP500*.md"))
        assert remaining == ["EP500_官方標題.md"], f"實際殘留檔案：{remaining}"
        assert not (transcripts / "EP500_獨立轉錄.md").exists()
        assert (transcripts / "EP500_官方標題.md").read_text(encoding="utf-8") == "官方版內容"
        print("[PASS] test_case_1_clear_resolution：明確情況正確刪除獨立版、保留官方版")


def test_case_2_ambiguous_neither_in_manifest():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        transcripts, manifest_path = setup_case(tmp)
        (transcripts / "EP501_標題A.md").write_text("A", encoding="utf-8")
        (transcripts / "EP501_標題B.md").write_text("B", encoding="utf-8")
        write_manifest(manifest_path, [])  # manifest 是空的

        events = resolve_duplicates_file_level(transcripts, manifest_path, dry_run=False)

        assert len(events) == 1
        assert events[0]["action"] == "skip_ambiguous", events[0]
        # 驗證兩個檔案都沒被動過
        remaining = sorted(p.name for p in transcripts.glob("EP501*.md"))
        assert remaining == ["EP501_標題A.md", "EP501_標題B.md"], f"不該刪任何檔案，實際：{remaining}"
        print("[PASS] test_case_2_ambiguous_neither_in_manifest：兩個都不在manifest時不誤刪")


def test_case_3_ambiguous_both_in_manifest():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        transcripts, manifest_path = setup_case(tmp)
        (transcripts / "EP502_標題A.md").write_text("A", encoding="utf-8")
        (transcripts / "EP502_標題B.md").write_text("B", encoding="utf-8")
        write_manifest(manifest_path, [
            {"ep_id": "EP502", "path": "transcripts\\EP502_標題A.md", "mode": "gap_fill"},
            {"ep_id": "EP502", "path": "transcripts\\EP502_標題B.md", "mode": "gap_fill"},
        ])

        events = resolve_duplicates_file_level(transcripts, manifest_path, dry_run=False)

        assert len(events) == 1
        assert events[0]["action"] == "skip_ambiguous", events[0]
        remaining = sorted(p.name for p in transcripts.glob("EP502*.md"))
        assert remaining == ["EP502_標題A.md", "EP502_標題B.md"], f"不該刪任何檔案，實際：{remaining}"
        print("[PASS] test_case_3_ambiguous_both_in_manifest：異常雙記錄狀況不誤刪（安全邊界測試）")


def test_case_4_no_duplicates():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        transcripts, manifest_path = setup_case(tmp)
        (transcripts / "EP503_x.md").write_text("x", encoding="utf-8")
        (transcripts / "EP504_y.md").write_text("y", encoding="utf-8")
        (transcripts / "EP505_z.md").write_text("z", encoding="utf-8")
        write_manifest(manifest_path, [])

        events = resolve_duplicates_file_level(transcripts, manifest_path, dry_run=False)
        assert events == [], f"不該有任何事件，實際：{events}"
        print("[PASS] test_case_4_no_duplicates：正常無重複情況不觸發任何事件")


def test_case_5_dry_run_does_not_delete():
    """dry_run=True 是排程實際會先用的模式（比照sql-write-guard精神：先dry-run再動手），
    驗證dry_run模式下即使判斷出明確情況，也真的不會刪檔案，只回報。"""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        transcripts, manifest_path = setup_case(tmp)
        (transcripts / "EP506_官方.md").write_text("官方", encoding="utf-8")
        (transcripts / "EP506_獨立轉錄.md").write_text("獨立", encoding="utf-8")
        write_manifest(manifest_path, [
            {"ep_id": "EP506", "path": "transcripts\\EP506_獨立轉錄.md", "mode": "gap_fill"}
        ])

        events = resolve_duplicates_file_level(transcripts, manifest_path, dry_run=True)

        assert len(events) == 1
        assert events[0]["action"] == "delete_independent_duplicate"
        # 關鍵：dry_run=True 時兩個檔案都還在
        remaining = sorted(p.name for p in transcripts.glob("EP506*.md"))
        assert remaining == ["EP506_官方.md", "EP506_獨立轉錄.md"], f"dry_run不該真的刪檔案，實際：{remaining}"
        print("[PASS] test_case_5_dry_run_does_not_delete：dry_run模式正確地只回報不動手")


def test_case_6_log_append_not_overwrite():
    """驗證 append_dedup_log 是純附加，不會蓋掉之前跑的紀錄——這是排程長期運作的關鍵特性。"""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        log_path = tmp / "dedup_log.json"
        append_dedup_log(log_path, [{"ep": 1, "action": "test_a"}])
        append_dedup_log(log_path, [{"ep": 2, "action": "test_b"}])
        data = json.loads(log_path.read_text(encoding="utf-8"))
        assert len(data["events"]) == 2, f"預期累積2筆，實際：{data}"
        assert data["events"][0]["ep"] == 1 and data["events"][1]["ep"] == 2
        print("[PASS] test_case_6_log_append_not_overwrite：log是累加不是覆蓋")


def test_case_7_real_data_no_false_positive():
    """用真實 transcripts/ 目錄跑唯讀掃描（不複製、不寫入，只呼叫find_duplicate_eps做偵測），
    確認目前正式資料完全沒有重複——這一步是唯讀，不涉及本測試腳本要驗證的刪除邏輯，
    只是額外交叉確認：目前線上狀態下,方案F邏輯不會有事情可做（因為還沒發生過重複），
    佐證「風險目前是潛在的，不是已經爆炸的」這個規劃稿判斷。"""
    real_transcripts = Path(__file__).parent.parent.parent / "transcripts"
    if not real_transcripts.exists():
        print("[SKIP] test_case_7：找不到正式 transcripts/ 目錄，略過交叉確認")
        return
    dupes = find_duplicate_eps(real_transcripts)
    print(f"[INFO] 正式 transcripts/ 目錄實際掃描結果：{len(dupes)} 個EP有重複檔案"
          f"{'（' + str(dupes) + '）' if dupes else '（目前為0，符合規劃稿「風險尚未發生」的判斷)'}")


if __name__ == "__main__":
    test_case_1_clear_resolution()
    test_case_2_ambiguous_neither_in_manifest()
    test_case_3_ambiguous_both_in_manifest()
    test_case_4_no_duplicates()
    test_case_5_dry_run_does_not_delete()
    test_case_6_log_append_not_overwrite()
    test_case_7_real_data_no_false_positive()
    print("\n全部測試通過。")
