"""
索羅門工作區任務（2026-08-03）Track 1 試做：重複集數檔案「檔案層級去重」原型（方案F）。

背景：`100_Todo/projects/2026-08-02_stock-signal獨立轉錄長期自動化設計.md` 規劃稿裡，
方案F 被評為「不碰DB、不命中絕對紅線，排程可以自主執行」，但規劃稿本身沒有寫程式碼，
只有文字設計。這個檔案是把方案F 的文字設計變成可執行、可驗證的原型。

**這是試做/demo檔案，不是正式程式碼**——不會被 sync_independent_transcripts.py import，
不改動任何專案既有正式檔案。真正要採用時，建議把 resolve_duplicates_file_level() 的邏輯
搬進 sync_independent_transcripts.py，取代目前 detect_duplicate_episode_files() 純警告的行為。

判斷邏輯（對照規劃稿方案F）：
  1. 找出 transcripts/ 裡同一 EP 編號有 2+ 檔案的情況（沿用既有 detect_duplicate_episode_files() 邏輯）。
  2. 用 transcripts_data/independent_transcribe/manifest.json 的 records[].path 判斷
     哪個檔案是「純獨立轉錄來源」（manifest 有記錄 = 獨立轉錄版；manifest 沒記錄 = 假定為
     whatmkreallysaid.com 官方版，因為官方版是 download_transcripts.py 寫的，不會進這份 manifest）。
  3. 明確情況（剛好 1 個獨立版 + 1+ 個官方版）→ 自動刪除獨立版檔案，保留官方版，寫 log 事件。
  4. 不明確情況（0 個或 2+ 個匹配 manifest，例如兩份都被誤判、或 manifest 記錄本身有問題）
     → 不動手，只記一筆 skip_ambiguous 事件，留給人工判斷——這是規劃稿裡「DB層級升級留給
     人工」精神的延伸：連檔案層級都判斷不出來時，一樣不猜、不動手。
"""
import json
import re
from pathlib import Path
from datetime import datetime, timezone

EP_RE = re.compile(r"EP(\d+)", re.IGNORECASE)


def find_duplicate_eps(transcripts_dir: Path) -> dict[int, list[str]]:
    """沿用 sync_independent_transcripts.py::detect_duplicate_episode_files() 的邏輯，
    獨立重寫一份（不 import 正式檔案，維持這個原型完全自我包含、可攜帶審查）。"""
    by_ep: dict[int, list[str]] = {}
    for f in transcripts_dir.glob("EP*.md"):
        m = EP_RE.match(f.stem)
        if m:
            by_ep.setdefault(int(m.group(1)), []).append(f.name)
    return {ep: names for ep, names in by_ep.items() if len(names) > 1}


def load_manifest_filenames(manifest_path: Path) -> set[str]:
    """回傳 manifest.json 裡記錄過的獨立轉錄檔案「檔名」集合（不含目錄路徑，
    因為 manifest 裡存的是 Windows 相對路徑 transcripts\\EPxxx_xxx.md，
    跨平台/跨呼叫端最穩的比對基準是檔名本身）。"""
    if not manifest_path.exists():
        return set()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    names = set()
    for r in data.get("records", []):
        p = r.get("path", "")
        if p:
            names.add(Path(p).name)
    return names


def resolve_duplicates_file_level(
    transcripts_dir: Path, manifest_path: Path, dry_run: bool = True
) -> list[dict]:
    """回傳這次會/已經做的事件清單，每筆事件是一個 dict。dry_run=True 時只回報不刪檔。"""
    dupes = find_duplicate_eps(transcripts_dir)
    manifest_names = load_manifest_filenames(manifest_path)
    events = []
    for ep, filenames in sorted(dupes.items()):
        independent_files = [f for f in filenames if f in manifest_names]
        official_files = [f for f in filenames if f not in manifest_names]
        now = datetime.now(timezone.utc).isoformat()
        if len(independent_files) == 1 and len(official_files) >= 1:
            target = independent_files[0]
            event = {
                "ep": ep,
                "action": "delete_independent_duplicate",
                "deleted_file": target,
                "kept_files": official_files,
                "timestamp": now,
            }
            if not dry_run:
                (transcripts_dir / target).unlink()
            events.append(event)
        else:
            events.append({
                "ep": ep,
                "action": "skip_ambiguous",
                "all_files": filenames,
                "matched_independent": independent_files,
                "matched_official": official_files,
                "reason": (
                    "0個或2個以上檔案命中manifest，無法唯一判斷哪個是獨立版，"
                    "不猜、留給人工"
                ),
                "timestamp": now,
            })
    return events


def append_dedup_log(log_path: Path, events: list[dict]):
    """純附加寫入去重事件 log（不覆蓋既有內容），比照 manifest.json 的
    load->append->save 模式，讓使用者之後可以批次審視。"""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if log_path.exists():
        data = json.loads(log_path.read_text(encoding="utf-8"))
    else:
        data = {"events": []}
    data["events"].extend(events)
    log_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    import sys
    print("這是原型/demo檔案，不接受直接對正式 transcripts/ 執行。")
    print("驗證方式見同目錄 dedup_prototype_test.py（在隔離的暫存目錄跑測試案例）。")
    sys.exit(0)
