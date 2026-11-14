"""橋接：把 gooaye-latest / asr-lab 本機已轉好的新集數逐字稿（asr-lab/out_best/EPnnn.srt）
補進 stock-signal，讓「誰說得對」記分板不必等第三方站（whatmkreallysaid.com）。

為什麼有這支（2026-11-14 根因）：EP712（11/07）、EP713（11/11）早在 11/08 20:31、11/11 16:00
就由 GooayeLatest_NewEp 在本機轉好 out_best/*.srt，但 stock-signal 只認第三方站的 episodes.json
（停在 EP711），所以每天 04:13 都「跳過 3 集」，直到 11/12 有人手動補。
本橋接在 update.py Step 1 之後自動跑：RSS 有、episodes.json 沒有、out_best 有 SRT → 轉成 md 寫進
transcripts/、併進 episodes.json（merge_local_only 會保留）、記進 manifest（同集日後第三方站上架時，
batch 既有的去重邏輯照舊處理）。純附加，不覆蓋任何既有檔案；不花錢（只用本機檔）。
任何失敗只印警告、回傳 []，不擋後面的流程。
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ASRLAB_OUT_BEST = HERE.parent / "asr-lab" / "out_best"
EPISODES_LOCAL = HERE / "episodes.json"
TRANSCRIPTS = HERE / "transcripts"


def _clean_title(raw: str, n: int) -> str:
    """RSS 標題常是「EP713 | 🌲」這種只有表情符號的；去掉集號、符號、表情後沒字就用「EPn」當名。"""
    t = re.sub(r"^\s*EP\s*\d+", "", raw or "")
    t = re.sub(r"[^\w一-鿿 ]+", " ", t).strip()
    t = re.sub(r"\s+", "_", t)
    return t or f"EP{n}"


def bridge(rss: dict | None = None, *, srt_dir: Path = ASRLAB_OUT_BEST,
           episodes_path: Path = EPISODES_LOCAL, transcripts_dir: Path = TRANSCRIPTS,
           manifest: bool = True) -> list[int]:
    """回傳這次補進來的集號清單。rss 可傳 {集號: {title, pub_dt}}（測試用），None 就抓 RSS。"""
    try:
        import gooaye_rss
        from download_transcripts import derive_date_fields, _dump_bytes
        from independent_transcribe import srt_to_md, safe_filename, atomic_write_text
        if rss is None:
            rss = gooaye_rss.parse_episodes(gooaye_rss.fetch_rss(HERE / "_cache" / "rss.xml", max_age_hours=6.0))
        raw = episodes_path.read_bytes()
        eps = json.loads(raw.decode("utf-8"))
        have = {e.get("number") for e in eps if isinstance(e, dict)}
        have_files = {int(m.group(1)) for p in transcripts_dir.glob("EP*.md")
                      if (m := re.match(r"EP(\d+)", p.name))}
        added, new_entries = [], []
        for n in sorted(rss):
            if n in have or n in have_files:
                continue
            srt = srt_dir / f"EP{n}.srt"
            if not srt.exists() or srt.stat().st_size == 0:
                continue
            title = _clean_title(rss[n]["title"], n)
            md = srt_to_md(srt, f"EP{n}", title, restore_punctuation=False)  # out_best 已校正過，不再叫 ollama 補標點（慢且吃 GPU）
            fname = safe_filename(f"EP{n}_{title}.md")
            atomic_write_text(transcripts_dir / fname, md)
            d = rss[n]["pub_dt"].astimezone(timezone.utc).date()
            ent = {"number": n, "title": title, "filename": fname, "description": "", "date": d.isoformat(),
                   "year": d.year, "month": d.month, "day": d.day, "display_title": title, "summary": "",
                   "source": "asrlab_bridge"}
            ent.update({k: v for k, v in derive_date_fields(d).items() if k not in ent})
            new_entries.append(ent)
            if manifest:
                from sync_independent_transcripts import _append_manifest_record
                _append_manifest_record({
                    "ep_id": f"EP{n}", "video_id": None,
                    "processed_at": datetime.now(timezone.utc).isoformat(), "mode": "gap_fill",
                    "written_to_transcripts": True, "path": str(transcripts_dir / fname),
                    "note": "本機 asr-lab 轉錄（bridge_asrlab），沒有第二方（whatmkreallysaid.com）交叉驗證"})
            added.append(n)
            print(f"[bridge_asrlab] EP{n} 由 asr-lab/out_best 補進 transcripts 與 episodes.json", flush=True)
        if new_entries:
            merged = sorted(eps + new_entries, key=lambda e: e.get("number", 0))
            episodes_path.write_bytes(_dump_bytes(merged, raw))
        return added
    except Exception as e:  # 橋接失敗不擋主流程，但要看得到
        print(f"[bridge_asrlab] ⚠ 橋接失敗（不影響後續）：{type(e).__name__}: {e}", file=sys.stderr, flush=True)
        return []


if __name__ == "__main__":
    print(bridge())
