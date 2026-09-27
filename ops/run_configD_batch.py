"""組態 D 批次轉錄（EP682 → EP683 → EP684 → EP687），一次起好、放手跑完。

背景：EP681 已經用同一組參數（model=large-v3, asr_guard=lite, hotwords_file=
asr/hotwords_gooaye.txt）轉完並產出 md（2026-09-27，人工單集操作）。這支腳本把剩下
4 集包成一支會自己跑到底的批次，不靠 agent session 盯著（agent 被回收，程序不該跟著死）。

用法：
  python ops/run_configD_batch.py

行為：
  - 序列處理 EP682/683/684/687（GPU 只有一張，不平行）。
  - 冪等：每集開始前先檢查 transcripts_data/independent_configD_2026-09-27/ 底下
    有沒有 EP{n}_*.md，有就跳過（可安全重跑本腳本）。
  - 每集的 stdout/stderr 全部導進 transcripts_data/independent_configD_2026-09-27/_run_EP{n}.log，
    不吞任何錯誤；某集失敗會記錄下來、繼續下一集，不會讓整支腳本停掉。
  - 每集做完（成功或失敗）都 append 一行進 _progress.log：集數、完成時間、md 字數
    （失敗則 0）、耗時秒數、狀態。
  - 每集轉完立刻刪掉該集的 source.mkv（工作目錄體積控制）。
  - 腳本一啟動就把自己的 pid 寫進 _progress.log 第一行。
"""
from __future__ import annotations

import contextlib
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from independent_transcribe import (  # noqa: E402
    run_independent_transcription, srt_to_md, safe_filename, atomic_write_text,
    IndependentTranscribeError, INDEPENDENT_MEDIA_ROOT,
)
from sync_independent_transcripts import _title_from_description  # noqa: E402

OUT_DIR = REPO / "transcripts_data" / "independent_configD_2026-09-27"
PROGRESS_LOG = OUT_DIR / "_progress.log"
HOTWORDS_FILE = REPO / "asr" / "hotwords_gooaye.txt"

EPISODES = [
    (682, "https://www.youtube.com/watch?v=5qjPyT428eM"),
    (683, "https://www.youtube.com/watch?v=xsyVbqn_4N8"),
    (684, "https://www.youtube.com/watch?v=AmYcb52jMTU"),
    (687, "https://www.youtube.com/watch?v=hasrdP2S7LA"),
]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _append_progress(line: str):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(PROGRESS_LOG, "a", encoding="utf-8") as f:
        f.write(line.rstrip("\n") + "\n")


def _already_done(ep_num: int) -> Path | None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cands = sorted(OUT_DIR.glob(f"EP{ep_num}_*.md"))
    return cands[0] if cands else None


def _job_dir(name: str) -> Path:
    # 跟 independent_transcribe.run_independent_transcription 一樣，容忍新舊兩種擺法。
    for cand in (INDEPENDENT_MEDIA_ROOT / "_工作檔" / name, INDEPENDENT_MEDIA_ROOT / name):
        if cand.exists():
            return cand
    return INDEPENDENT_MEDIA_ROOT / "_工作檔" / name


def process_one(ep_num: int, url: str):
    ep_id = f"EP{ep_num}"
    name = f"{ep_id}_configD"
    run_log_path = OUT_DIR / f"_run_{ep_id}.log"

    existing = _already_done(ep_num)
    if existing is not None:
        _append_progress(
            f"{ep_id}\tstatus=SKIP（已存在 {existing.name}）\tat={_now()}"
        )
        print(f"[batch] {ep_id} 已有產物 {existing.name}，跳過")
        return

    t0 = time.monotonic()
    started_at = _now()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(run_log_path, "w", encoding="utf-8") as logf:
        with contextlib.redirect_stdout(logf), contextlib.redirect_stderr(logf):
            print(f"[driver] 開始 {ep_id}，來源={url}，job name={name}，開始={started_at}",
                  flush=True)
            try:
                video_id = url.split("v=", 1)[1].split("&", 1)[0] if "v=" in url else None
                srt_path = run_independent_transcription(
                    url, name=name, model="large-v3", lang="zh",
                    asr_guard="lite", hotwords_file=str(HOTWORDS_FILE),
                )
                title = _title_from_description(video_id) if video_id else "獨立轉錄"
                md_text = srt_to_md(srt_path, ep_id, title)
                OUT_DIR.mkdir(parents=True, exist_ok=True)
                filename = safe_filename(f"{ep_id}_{title}.md")
                out_path = OUT_DIR / filename
                atomic_write_text(out_path, md_text)
                word_count = len(md_text)
                print(f"RESULT_OK {out_path} {word_count}", flush=True)
                ok = True
                err_summary = ""
            except (IndependentTranscribeError, ValueError, Exception) as e:  # noqa: BLE001
                ok = False
                word_count = 0
                out_path = None
                err_summary = f"{type(e).__name__}: {e}"
                print(f"RESULT_FAIL {err_summary}", flush=True)
                traceback.print_exc(file=logf)

    # 不管成功失敗，都刪掉這集的 source.mkv（工作目錄體積控制）。
    jd = _job_dir(name)
    mkv = jd / "source.mkv"
    try:
        if mkv.exists():
            mkv.unlink()
    except OSError:
        pass

    elapsed = time.monotonic() - t0
    if ok:
        _append_progress(
            f"{ep_id}\t狀態=OK\t完成時間={_now()}\t字數={word_count}\t耗時秒={elapsed:.0f}"
            f"\t檔案={out_path.name}\tlog={run_log_path.name}"
        )
        print(f"[batch] {ep_id} 完成，{word_count} 字，耗時 {elapsed:.0f}s → {out_path}")
    else:
        _append_progress(
            f"{ep_id}\t狀態=FAIL\t時間={_now()}\t耗時秒={elapsed:.0f}\t錯誤={err_summary}"
            f"\tlog={run_log_path.name}"
        )
        print(f"[batch] {ep_id} 失敗（{err_summary}），詳見 {run_log_path}，繼續下一集")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _append_progress(f"PID={os.getpid()}\t批次啟動={_now()}\t集數={[e for e,_ in EPISODES]}")
    results = []
    for ep_num, url in EPISODES:
        try:
            process_one(ep_num, url)
            results.append((ep_num, "processed（詳見上方逐行；SKIP/OK/FAIL 見 _progress.log）"))
        except Exception as e:  # noqa: BLE001 - 任何未預期例外都不准讓整支腳本掛掉
            _append_progress(f"EP{ep_num}\t狀態=FAIL（批次層級未預期例外）\t時間={_now()}\t錯誤={type(e).__name__}: {e}")
            print(f"[batch] EP{ep_num} 批次層級未預期例外：{e}", flush=True)
            results.append((ep_num, f"unexpected-exception: {e}"))

    success = []
    fail = []
    skip = []
    for ep_num, _ in EPISODES:
        p = _already_done(ep_num)
        if p is not None:
            success.append(ep_num)
        else:
            fail.append(ep_num)
    _append_progress(
        f"SUMMARY\t完成時間={_now()}\t有產物={success}\t沒有產物={fail}"
    )
    print(f"[batch] 全部完成。有產物: {success}；沒有產物: {fail}")


if __name__ == "__main__":
    main()
