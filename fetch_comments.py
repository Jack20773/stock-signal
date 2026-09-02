"""股癌 YouTube 留言抓取（全新獨立工具，2026-09-03）。

這支是什麼
----------
把股癌 YouTube 頻道（https://www.youtube.com/@Gooaye/videos）每一集影片下方的留言
抓下來，存成結構化 JSON，放在 comments_data/，之後拿去做留言分析。跟既有的
sync_independent_transcripts.py／download_transcripts.py 完全獨立、互不呼叫、
互不影響——本檔案只讀 episodes.json/transcripts/ 做集數比對，不寫這兩處。

怎麼跑
------
  # 先看打算抓哪幾支，不會真的呼叫 yt-dlp 抓留言（唯讀，安全）
  python fetch_comments.py --dry-run --from-channel --limit 3

  # 抓頻道最新 1 支，留言上限 50 則（測試用，跑得快）
  python fetch_comments.py --from-channel --limit 1 --max-comments 50

  # 指定某一集（會先查頻道清單解析出 video_id）
  python fetch_comments.py --ep 693 --max-comments 200

  # 指定單支影片網址
  python fetch_comments.py --url "https://www.youtube.com/watch?v=XXXXXXXXXXX"

  # 已經抓過的預設會跳過（見 comments_data/manifest.json），--force 才重抓
  python fetch_comments.py --from-channel --limit 5 --force

限制
----
- 只走 yt-dlp（免費、本地工具），沒有 YouTube Data API key，也不打算申請——
  全部留言資料都是 yt-dlp 從網頁擷取到的公開留言，不是官方 API 回應，欄位隨
  YouTube 網頁改版可能跟著變動。
- 留言數量、排序（預設 top）、能不能抓到，都受 YouTube 當下的行為與 yt-dlp
  版本影響，本檔案不保證每次都抓得到、也不保證抓到「全部」留言——
  --max-comments 是「最多抓幾則」的上限，不是承諾一定抓滿。
- 隱私：只留留言的公開顯示名稱（YouTube 現在顯示的是 @handle 這類公開暱稱），
  **不存 author_id、author_url、author_thumbnail 這些能反查到留言者頻道的欄位**——
  這是刻意的取捨，寧可資訊少一點也不留可反查個人的鉤子。
- **不設任何自動排程**（不建 Windows Task Scheduler、不寫 cron、不接 GitHub
  Actions）。要不要定期跑，跑完這輪之後由使用者自己決定。
- 對 YouTube 這種第三方網站沒有 SLA，抓不到／被擋（403、需要登入、留言關閉）
  一律照實印錯誤、不產生假資料頂替。

輸出
----
  comments_data/EP<集號>_<video_id>.json   單支影片的留言（集號查不到就用 unknown）
  comments_data/manifest.json              抓取紀錄（video_id -> 集號/時間/則數/檔案路徑）
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

HERE = Path(__file__).parent
CHANNEL_URL = "https://www.youtube.com/@Gooaye/videos"
EPISODES_LOCAL = HERE / "episodes.json"
TRANSCRIPTS_DIR = HERE / "transcripts"
COMMENTS_DIR = HERE / "comments_data"
MANIFEST_PATH = COMMENTS_DIR / "manifest.json"

EP_TITLE_RE = re.compile(r"^EP\s*0*(\d+)\b")
VIDEO_ID_RE = re.compile(r"(?:v=|youtu\.be/|/shorts/)([A-Za-z0-9_-]{11})")

PRIVACY_NOTE = (
    "隱私取捨：只保留留言的公開顯示名稱（author，通常是 @handle 這類公開暱稱），"
    "刻意不存 author_id / author_url / author_thumbnail 等可反查留言者頻道的欄位。"
)


# ---------------------------------------------------------------- 小工具

def extract_video_id_from_url(url: str) -> str | None:
    m = VIDEO_ID_RE.search(url)
    return m.group(1) if m else None


def load_local_episode_map() -> dict[int, dict]:
    """讀本地 episodes.json（跟 sync_independent_transcripts.py 一樣，只讀不寫）。"""
    if not EPISODES_LOCAL.exists():
        return {}
    data = json.loads(EPISODES_LOCAL.read_text(encoding="utf-8"))
    return {e["number"]: e for e in data if isinstance(e.get("number"), int)}


def load_local_transcript_episode_numbers() -> set[int]:
    nums = set()
    if not TRANSCRIPTS_DIR.exists():
        return nums
    for f in TRANSCRIPTS_DIR.glob("EP*.md"):
        m = re.match(r"EP(\d+)", f.stem, re.IGNORECASE)
        if m:
            nums.add(int(m.group(1)))
    return nums


def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        try:
            return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"videos": {}}


def save_manifest(manifest: dict) -> None:
    COMMENTS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = MANIFEST_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(MANIFEST_PATH)


def atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------- 頻道清單（唯讀）

def fetch_channel_episode_map(channel_url: str = CHANNEL_URL, timeout: int = 120) -> dict[int, dict]:
    """用 yt-dlp --flat-playlist 抓頻道完整影片清單，回傳 {EP編號: {video_id, title, url}}。

    跟 sync_independent_transcripts.py::fetch_youtube_episodes 邏輯相同但獨立實作
    （本檔案刻意不 import 那支腳本，維持零耦合、不影響既有行為）。純讀取，不寫檔。
    """
    cmd = ["yt-dlp", "--flat-playlist", "-J", channel_url]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"yt-dlp 取得頻道清單失敗 (exit {proc.returncode}): {proc.stderr[-2000:]}")
    data = json.loads(proc.stdout)
    entries = data.get("entries", [])
    result: dict[int, dict] = {}
    for e in entries:
        title = (e.get("title") or "").strip()
        m = EP_TITLE_RE.match(title)
        if not m:
            continue
        num = int(m.group(1))
        result[num] = {
            "video_id": e.get("id"),
            "title": title,
            "url": f"https://www.youtube.com/watch?v={e.get('id')}",
        }
    return result


# ---------------------------------------------------------------- 目標解析

def build_targets_dry_run(args: argparse.Namespace) -> list[dict]:
    """dry-run 專用：完全不呼叫 yt-dlp、不連網，只用本地既有資訊組出「打算做什麼」。"""
    targets: list[dict] = []
    if args.url:
        for url in args.url:
            vid = extract_video_id_from_url(url)
            targets.append({
                "ep": None, "video_id": vid or "?", "title": "(dry-run 不查標題)", "url": url,
                "note": "video_id 由網址直接解析，未連網" if vid else "無法從網址解析出 video_id",
            })
    if args.from_channel:
        targets.append({
            "ep": "?", "video_id": "?", "title": "(dry-run 不連網，無法列出實際影片)",
            "url": args.channel_url,
            "note": f"將從頻道抓最新 {args.limit} 支影片；實際 video_id/標題要呼叫 yt-dlp 才能得知",
        })
    if args.ep:
        for ep in args.ep:
            targets.append({
                "ep": ep, "video_id": "?", "title": "(dry-run 不查頻道清單)", "url": "?",
                "note": f"EP{ep} 的 video_id 要查頻道清單（yt-dlp --flat-playlist）才能解析，dry-run 不查",
            })
    return targets


def build_targets_real(args: argparse.Namespace) -> list[dict]:
    """實際跑：可能呼叫一次 fetch_channel_episode_map（唯讀、輕量，只是列表，不抓留言）。"""
    targets: list[dict] = []
    seen_video_ids: set[str] = set()

    channel_map: dict[int, dict] | None = None

    def get_channel_map() -> dict[int, dict]:
        nonlocal channel_map
        if channel_map is None:
            print(f"[頻道清單] 查詢 {args.channel_url} ...")
            channel_map = fetch_channel_episode_map(args.channel_url)
            print(f"[頻道清單] 共 {len(channel_map)} 集")
        return channel_map

    if args.url:
        for url in args.url:
            vid = extract_video_id_from_url(url)
            if not vid:
                print(f"[警告] 無法從網址解析出 video_id，略過：{url}")
                continue
            if vid in seen_video_ids:
                continue
            seen_video_ids.add(vid)
            targets.append({"ep": None, "video_id": vid, "title": None, "url": url})

    if args.from_channel:
        cmap = get_channel_map()
        latest_eps = sorted(cmap.keys(), reverse=True)[: args.limit]
        for ep in latest_eps:
            info = cmap[ep]
            vid = info["video_id"]
            if vid in seen_video_ids:
                continue
            seen_video_ids.add(vid)
            targets.append({"ep": ep, "video_id": vid, "title": info["title"], "url": info["url"]})

    if args.ep:
        cmap = get_channel_map()
        for ep in args.ep:
            info = cmap.get(ep)
            if not info:
                print(f"[警告] EP{ep} 不在 YouTube 頻道清單裡（可能下架/非公開），略過")
                continue
            vid = info["video_id"]
            if vid in seen_video_ids:
                continue
            seen_video_ids.add(vid)
            targets.append({"ep": ep, "video_id": vid, "title": info["title"], "url": info["url"]})

    return targets


# ---------------------------------------------------------------- 抓留言（yt-dlp）

def run_ytdlp_fetch_comments(
    video_id: str, url: str, max_comments: int, sleep_requests: float, retries: int, tmp_dir: Path,
) -> dict:
    """呼叫 yt-dlp --write-comments --skip-download，回傳解析後的 info.json 內容（dict）。

    失敗（yt-dlp 非 0 exit、逾時、輸出檔缺失）會照 retries 重試，重試間隔線性遞增。
    全部失敗後丟出 RuntimeError，由呼叫端照實回報，不產生假資料。
    """
    tmp_dir.mkdir(parents=True, exist_ok=True)
    out_template = str(tmp_dir / f"ytc_{video_id}.%(ext)s")
    info_path = tmp_dir / f"ytc_{video_id}.info.json"

    extractor_args = f"youtube:max_comments={max_comments};comment_sort=top"
    cmd = [
        "yt-dlp",
        "--write-comments",
        "--skip-download",
        "--sleep-requests", str(sleep_requests),
        "--extractor-args", extractor_args,
        "-o", out_template,
        url,
    ]

    last_err = None
    for attempt in range(1, retries + 1):
        if info_path.exists():
            info_path.unlink()
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8", timeout=300,
            )
        except subprocess.TimeoutExpired as e:
            last_err = f"逾時（第 {attempt}/{retries} 次）：{e}"
            print(f"  [重試 {attempt}/{retries}] {last_err}")
            time.sleep(attempt * 3)
            continue

        if proc.returncode != 0 or not info_path.exists():
            last_err = (
                f"yt-dlp exit {proc.returncode}（第 {attempt}/{retries} 次）。"
                f"stderr 末段：{proc.stderr[-1500:]}"
            )
            print(f"  [重試 {attempt}/{retries}] {last_err}")
            time.sleep(attempt * 3)
            continue

        try:
            data = json.loads(info_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            last_err = f"info.json 讀取/解析失敗（第 {attempt}/{retries} 次）：{e}"
            print(f"  [重試 {attempt}/{retries}] {last_err}")
            time.sleep(attempt * 3)
            continue
        finally:
            if info_path.exists():
                info_path.unlink()

        return data

    raise RuntimeError(f"video_id={video_id} 抓留言失敗，已重試 {retries} 次。最後錯誤：{last_err}")


def sanitize_comments(raw_comments: list[dict]) -> list[dict]:
    """只留不會反查到個人頻道的欄位，見模組 docstring 的隱私段落。"""
    out = []
    for c in raw_comments:
        parent = c.get("parent")
        out.append({
            "id": c.get("id"),
            "author_display_name": c.get("author"),
            "text": c.get("text"),
            "like_count": c.get("like_count"),
            "timestamp": c.get("timestamp"),
            "is_author_reply": bool(c.get("author_is_uploader", False)),
            "parent_id": None if parent in (None, "root") else parent,
        })
    return out


# ---------------------------------------------------------------- 主流程

def process_one(target: dict, args: argparse.Namespace, manifest: dict) -> str:
    video_id = target["video_id"]
    ep = target.get("ep")
    ep_label = str(ep) if ep is not None else "unknown"
    title = target.get("title") or ""

    existing = manifest["videos"].get(video_id)
    if existing and not args.force:
        print(f"[跳過] EP{ep_label} ({video_id}) 已抓過（{existing.get('fetched_at')}，"
              f"{existing.get('comment_count')} 則），--force 才重抓")
        return "SKIP"

    print(f"[抓取] EP{ep_label} ({video_id}) {title} ...")
    tmp_dir = COMMENTS_DIR / "_tmp"
    try:
        info = run_ytdlp_fetch_comments(
            video_id=video_id, url=target["url"] or f"https://www.youtube.com/watch?v={video_id}",
            max_comments=args.max_comments, sleep_requests=args.sleep_requests,
            retries=args.retries, tmp_dir=tmp_dir,
        )
    except RuntimeError as e:
        print(f"[失敗] EP{ep_label} ({video_id})：{e}")
        return "FAIL"

    raw_comments = info.get("comments") or []
    comments = sanitize_comments(raw_comments)
    fetched_at = datetime.now(timezone.utc).isoformat()

    out_path = COMMENTS_DIR / f"EP{ep_label}_{video_id}.json"
    output = {
        "_privacy_note": PRIVACY_NOTE,
        "video_id": video_id,
        "ep": ep,
        "video_title": info.get("title") or title,
        "fetched_at": fetched_at,
        "max_comments_requested": args.max_comments,
        "comment_count": len(comments),
        "yt_reported_comment_count": info.get("comment_count"),
        "comments": comments,
    }
    atomic_write_json(out_path, output)

    manifest["videos"][video_id] = {
        "ep": ep, "fetched_at": fetched_at, "comment_count": len(comments),
        "file": str(out_path.relative_to(HERE)),
    }
    save_manifest(manifest)

    print(f"[完成] EP{ep_label} ({video_id}) -> {out_path.name}（{len(comments)} 則留言）")
    return "OK"


def main() -> int:
    parser = argparse.ArgumentParser(description="股癌 YouTube 留言抓取（yt-dlp，唯讀來源，不設排程）")
    parser.add_argument("--url", action="append", help="指定單支影片網址，可重複給多個")
    parser.add_argument("--from-channel", action="store_true", help="從頻道抓最新 N 支（配合 --limit）")
    parser.add_argument("--limit", type=int, default=5, help="--from-channel 時抓最新幾支（預設 5）")
    parser.add_argument("--ep", action="append", type=int, help="指定集號，可重複給多個（查頻道清單解析 video_id）")
    parser.add_argument("--max-comments", type=int, default=500, help="每支影片最多抓幾則留言（預設 500）")
    parser.add_argument("--sleep-requests", type=float, default=2.0, help="yt-dlp 請求間隔秒數（禮貌間隔，預設 2）")
    parser.add_argument("--retries", type=int, default=3, help="單支影片抓取失敗重試上限（預設 3）")
    parser.add_argument("--channel-url", default=CHANNEL_URL, help="頻道網址（預設股癌）")
    parser.add_argument("--force", action="store_true", help="已抓過的也重抓（預設跳過）")
    parser.add_argument("--dry-run", action="store_true", help="只印打算抓哪幾支、輸出到哪，不呼叫 yt-dlp")
    args = parser.parse_args()

    if not (args.url or args.from_channel or args.ep):
        parser.error("要指定 --url 或 --from-channel 或 --ep 其中至少一個")

    if args.dry_run:
        targets = build_targets_dry_run(args)
        print("=== --dry-run：以下是打算抓的目標，不會呼叫 yt-dlp ===")
        for t in targets:
            out_name = f"EP{t['ep']}_{t['video_id']}.json" if t["ep"] not in (None, "?") else "(視實際 video_id 而定)"
            print(f"  EP{t['ep']} video_id={t['video_id']} url={t['url']}")
            print(f"    -> 輸出：comments_data/{out_name}")
            print(f"    -> 備註：{t['note']}")
        print(f"\n每支上限 {args.max_comments} 則留言，請求間隔 {args.sleep_requests} 秒，失敗重試 {args.retries} 次。")
        print(f"輸出目錄：{COMMENTS_DIR}")
        return 0

    manifest = load_manifest()
    targets = build_targets_real(args)
    if not targets:
        print("沒有解析出任何目標，結束。")
        return 1

    print(f"\n=== 共 {len(targets)} 支目標，開始抓取 ===")
    ok = skip = fail = 0
    for t in targets:
        status = process_one(t, args, manifest)
        if status == "OK":
            ok += 1
        elif status == "SKIP":
            skip += 1
        else:
            fail += 1

    print(f"\n=== 完成：成功 {ok}、跳過 {skip}、失敗 {fail} ===")
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
