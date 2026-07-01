import sys
import json
import time
import argparse
import urllib.request
import urllib.parse
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BASE_URL     = "https://whatmkreallysaid.com"
EPISODES_URL = f"{BASE_URL}/episodes.json"
OUT_DIR      = Path(__file__).parent / "transcripts"
EPISODES_LOCAL = Path(__file__).parent / "episodes.json"
DELAY_SEC    = 0.5


def safe_filename(name: str) -> str:
    for ch in r'\/:*?"<>|':
        name = name.replace(ch, "_")
    return name


def fetch(url: str, retries: int = 3) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.read()
        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)


def main(last_n: int = 0):
    OUT_DIR.mkdir(exist_ok=True)

    print("Fetching episode list...")
    raw = fetch(EPISODES_URL)
    episodes = json.loads(raw.decode("utf-8"))

    # C: 存成本地檔案，讓 performance.py 直接讀，不用再抓一次
    EPISODES_LOCAL.write_bytes(raw)

    total = len(episodes)
    if last_n > 0:
        episodes = episodes[-last_n:]
        print(f"Found {total} episodes (only downloading last {last_n})\n")
    else:
        print(f"Found {total} episodes\n")

    skipped = downloaded = failed = 0
    for i, ep in enumerate(episodes, 1):
        filename = ep["filename"]
        number   = ep.get("number", "?")
        ep_date  = ep.get("date", "")
        out_path = OUT_DIR / safe_filename(filename)

        if out_path.exists() and out_path.stat().st_size > 0:
            print(f"[{number:>4}] SKIP   EP{number}")
            skipped += 1
            continue

        url = f"{BASE_URL}/episodes/{urllib.parse.quote(filename)}"
        try:
            content = fetch(url)
            out_path.write_bytes(content)
            size_kb = len(content) / 1024
            print(f"[{number:>4}] OK     EP{number} ({ep_date})  {size_kb:.1f} KB")
            downloaded += 1
        except Exception as e:
            print(f"[{number:>4}] FAIL   EP{number}  {e}")
            failed += 1

        time.sleep(DELAY_SEC)

    print(f"\nDone.  Downloaded: {downloaded}  Skipped: {skipped}  Failed: {failed}")
    print(f"Saved to: {OUT_DIR}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--last", type=int, default=0,
                        help="只下載最新 N 集（0 = 全下載）")
    args = parser.parse_args()
    main(last_n=args.last)
