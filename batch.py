"""
批次分析腳本：依集數順序跑所有逐字稿，已分析過的自動跳過。

用法：
  python batch.py                   # 全部 672 集
  python batch.py --last 50         # 只跑最新 50 集（EP623–EP672）
  python batch.py --from EP100      # 從 EP100 開始
  python batch.py --dry-run         # 只列出待跑清單，不實際呼叫 API
"""
import sys
import re
import time
import argparse
import logging
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from database import init_db, save_result, _conn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("batch.log", encoding="utf-8"),
    ],
)

TRANSCRIPTS_DIR = Path(__file__).parent / "transcripts"
SLEEP_BETWEEN  = 3   # 每集之間暫停秒數，避免 API rate limit
MAX_RETRIES    = 3   # 單集最多重試次數


def _analyze_with_retry(transcript: str) -> dict:
    from analyzer import analyze  # lazy import，dry-run 時不需要 google.genai
    for attempt in range(MAX_RETRIES):
        try:
            return analyze(transcript)
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                wait = 5 * (2 ** attempt)  # 5 → 10 → 20 秒
                logging.warning(f"分析失敗（第 {attempt+1}/{MAX_RETRIES} 次），{wait}s 後重試：{e}")
                time.sleep(wait)
            else:
                raise


def ep_number(path: Path) -> int:
    m = re.match(r"EP(\d+)", path.stem, re.IGNORECASE)
    return int(m.group(1)) if m else 0


def load_transcripts(from_ep: int = 0, last_n: int = 0) -> list[Path]:
    files = sorted(TRANSCRIPTS_DIR.glob("EP*.md"), key=ep_number)
    if from_ep:
        files = [f for f in files if ep_number(f) >= from_ep]
    if last_n:
        files = files[-last_n:]
    return files


def load_analyzed_set() -> set[str]:
    """一次載入所有已分析的 episode_id，避免每集開一次 DB。"""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT episode_id FROM signals")
            return {r["episode_id"] for r in cur.fetchall()}


def run_batch(files: list[Path], dry_run: bool = False):
    total = len(files)
    skipped = done = failed = dry = 0
    analyzed = load_analyzed_set()

    for i, path in enumerate(files, 1):
        ep_num = ep_number(path)
        ep_id  = f"EP{ep_num}" if ep_num else path.stem
        prefix = f"[{i}/{total}] {ep_id}"

        if ep_id in analyzed:
            logging.info(f"{prefix} — 已分析，跳過")
            skipped += 1
            continue

        if dry_run:
            logging.info(f"{prefix} — 待跑（dry-run）")
            dry += 1
            continue

        try:
            transcript = path.read_text(encoding="utf-8")
            logging.info(f"{prefix} — 分析中（{len(transcript):,} chars）...")
            result = _analyze_with_retry(transcript)
            result["episode_id"] = ep_id  # 用檔名 ep_id 覆蓋 Gemini 的萃取結果，避免誤讀集號
            count = save_result(result)
            logging.info(f"{prefix} — 完成，存入 {count} 個訊號")
            done += 1
        except Exception as e:
            logging.error(f"{prefix} — 失敗：{e}")
            failed += 1

        if i < total:
            time.sleep(SLEEP_BETWEEN)

    if dry_run:
        logging.info(f"\ndry-run｜共 {total} 集｜待跑 {dry}｜已跳過 {skipped}")
    else:
        logging.info(f"\n完成｜共 {total} 集｜分析 {done}｜跳過 {skipped}｜失敗 {failed}")
    return done, skipped, failed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--last", type=int, default=0, help="只跑最新 N 集")
    parser.add_argument("--from", dest="from_ep", type=str, default="", help="從 EP{n} 開始，例如 --from EP100")
    parser.add_argument("--dry-run", action="store_true", help="只列清單，不呼叫 API")
    args = parser.parse_args()

    from_ep_num = 0
    if args.from_ep:
        m = re.search(r"\d+", args.from_ep)
        if m:
            from_ep_num = int(m.group())

    init_db()
    files = load_transcripts(from_ep=from_ep_num, last_n=args.last)

    if not files:
        print("找不到符合條件的逐字稿。")
        return

    print(f"待處理：{len(files)} 集（{ep_number(files[0])}–{ep_number(files[-1])}）")
    if args.dry_run:
        print("dry-run 模式，不呼叫 API\n")

    run_batch(files, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
