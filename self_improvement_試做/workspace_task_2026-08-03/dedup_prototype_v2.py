"""
dedup_prototype.py 的第二輪迭代（v2）——依 DeepSeek 獨立審查意見修正（見同目錄
dedup_prototype_v2_deepseek_review.txt）。這輪只處理 DeepSeek 點出的「風險最高、
成本最低」兩項，其餘（batch.py根因、manifest superseded標記、ep_id而非檔名比對）
留在報告的「延伸方向」給使用者裁決，不在這輪展開——見下方檔案結尾的「這輪故意沒做」。

修正1（DeepSeek意見#2，最高優先）：不再直接 unlink() 刪除獨立版檔案，改成移進
quarantine/ 子目錄（純檔案系統move，可逆）。理由：即使這是「排程自主執行、不碰DB」
的方案F範圍，permanent delete 仍然不可逆，跟索羅門通用章程「刪檔案列清單請使用者
動手」的精神方向相反；quarantine 讓使用者事後可以肉眼查看/一鍵搬回，符合章程
「自主決策範圍」機制一貫要求的「強制留痕、可復原」精神。

修正2（DeepSeek意見#6）：log 寫入改成 atomic write（同目錄寫暫存檔+os.replace），
避免寫到一半程式崩潰造成 log 檔損毀，也避免「刪檔成功但log沒寫到」的紀錄遺失風險
（quarantine化之後這個風險的嚴重性已經降低很多，但仍值得用低成本方式補上）。
"""
import json
import os
import re
import shutil
from pathlib import Path
from datetime import datetime, timezone

EP_RE = re.compile(r"EP(\d+)", re.IGNORECASE)


def find_duplicate_eps(transcripts_dir: Path) -> dict[int, list[str]]:
    by_ep: dict[int, list[str]] = {}
    for f in transcripts_dir.glob("EP*.md"):
        m = EP_RE.match(f.stem)
        if m:
            by_ep.setdefault(int(m.group(1)), []).append(f.name)
    return {ep: names for ep, names in by_ep.items() if len(names) > 1}


def load_manifest_filenames(manifest_path: Path) -> set[str]:
    if not manifest_path.exists():
        return set()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {Path(r["path"]).name for r in data.get("records", []) if r.get("path")}


def _atomic_write_text(path: Path, text: str):
    """比照 independent_transcribe.py::atomic_write_text() 同款做法：
    同目錄寫暫存檔 -> os.replace -> 換目標檔，避免寫到一半中斷造成半份檔案。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def resolve_duplicates_file_level(
    transcripts_dir: Path, manifest_path: Path, quarantine_dir: Path, dry_run: bool = True
) -> list[dict]:
    """v2：明確情況改成「移進 quarantine_dir」而非刪除。"""
    dupes = find_duplicate_eps(transcripts_dir)
    manifest_names = load_manifest_filenames(manifest_path)
    events = []
    for ep, filenames in sorted(dupes.items()):
        independent_files = [f for f in filenames if f in manifest_names]
        official_files = [f for f in filenames if f not in manifest_names]
        now = datetime.now(timezone.utc).isoformat()
        if len(independent_files) == 1 and len(official_files) >= 1:
            target = independent_files[0]
            dest = quarantine_dir / target
            event = {
                "ep": ep,
                "action": "quarantine_independent_duplicate",
                "quarantined_file": target,
                "quarantined_to": str(dest),
                "kept_files": official_files,
                "timestamp": now,
            }
            if not dry_run:
                quarantine_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(transcripts_dir / target), str(dest))
            events.append(event)
        else:
            events.append({
                "ep": ep,
                "action": "skip_ambiguous",
                "all_files": filenames,
                "matched_independent": independent_files,
                "matched_official": official_files,
                "reason": "0個或2個以上檔案命中manifest，無法唯一判斷哪個是獨立版，不猜、留給人工",
                "timestamp": now,
            })
    return events


def append_dedup_log(log_path: Path, events: list[dict]):
    if log_path.exists():
        data = json.loads(log_path.read_text(encoding="utf-8"))
    else:
        data = {"events": []}
    data["events"].extend(events)
    _atomic_write_text(log_path, json.dumps(data, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# 這輪故意沒做（留給使用者裁決要不要排進下一份任務檔，不是索羅門自己拍板）：
#   - batch.py 根因修正（讓它固定優先讀官方版而非glob順序）——這是動正式檔案的範圍，
#     索羅門這輪不能碰，只能建議。
#   - manifest.json 標記 superseded——同樣需要動 sync_independent_transcripts.py
#     正式檔案才能真正落地，這裡只在報告裡註明「quarantine之後，若要避免下次
#     gap_fill重新轉錄同一集，需要額外加這個標記」。
#   - 用 ep_id 而非檔名做 manifest 比對key——目前的資料型態(manifest記錄的是完整
#     相對路徑)在原輪測試裡沒有發現這個弱點會實際造成誤判(路徑本身已含檔名全部
#     資訊，比對時Path(p).name本來就是取檔名字串完全比對，不是取子字串)，但
#     DeepSeek提醒的Windows大小寫議題是真實存在的邊界情況，值得寫進建議清單。
# ---------------------------------------------------------------------------
