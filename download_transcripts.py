import sys
import json
import time
import urllib.request
import urllib.parse
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BASE_URL   = "https://whatmkreallysaid.com"
EPISODES_URL = f"{BASE_URL}/episodes.json"
OUT_DIR    = Path(__file__).parent / "transcripts"
DELAY_SEC  = 0.5   # 每次請求間隔，避免打爆伺服器


def safe_filename(name: str) -> str:
    """Replace Windows-illegal filename characters."""
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


def main():
    OUT_DIR.mkdir(exist_ok=True)

    print("Fetching episode list...")
    episodes = json.loads(fetch(EPISODES_URL).decode("utf-8"))
    total = len(episodes)
    print(f"Found {total} episodes\n")

    skipped = downloaded = failed = 0

    for i, ep in enumerate(episodes, 1):
        filename  = ep["filename"]          # e.g. "EP1_EP1 _( _・ω・)╰—╯✄.md"
        number    = ep.get("number", "?")
        ep_date   = ep.get("date", "")
        out_path  = OUT_DIR / safe_filename(filename)

        if out_path.exists() and out_path.stat().st_size > 0:
            print(f"[{i:>3}/{total}] SKIP   EP{number}")
            skipped += 1
            continue

        url = f"{BASE_URL}/episodes/{urllib.parse.quote(filename)}"
        try:
            content = fetch(url)
            out_path.write_bytes(content)
            size_kb = len(content) / 1024
            print(f"[{i:>3}/{total}] OK     EP{number} ({ep_date})  {size_kb:.1f} KB")
            downloaded += 1
        except Exception as e:
            print(f"[{i:>3}/{total}] FAIL   EP{number}  {e}")
            failed += 1

        time.sleep(DELAY_SEC)

    print(f"\nDone.  Downloaded: {downloaded}  Skipped: {skipped}  Failed: {failed}")
    print(f"Saved to: {OUT_DIR}")


if __name__ == "__main__":
    main()
