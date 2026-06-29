import sys, json, urllib.request
from pathlib import Path

def safe_filename(name: str) -> str:
    for ch in r'\/:*?"<>|':
        name = name.replace(ch, "_")
    return name

sys.stdout.reconfigure(encoding="utf-8")

BASE_URL  = "https://whatmkreallysaid.com"
OUT_DIR   = Path(__file__).parent / "transcripts"

episodes = json.loads(
    urllib.request.urlopen(
        urllib.request.Request(f"{BASE_URL}/episodes.json", headers={"User-Agent": "Mozilla/5.0"}),
        timeout=15
    ).read().decode("utf-8")
)

missing = []
for ep in episodes:
    fn = ep["filename"]
    if not (OUT_DIR / safe_filename(fn)).exists():
        missing.append(ep)

print(f"Total in episodes.json : {len(episodes)}")
print(f"Downloaded             : {len(list(OUT_DIR.glob('*.md')))}")
print(f"Missing                : {len(missing)}")
for ep in missing:
    print(f"  EP{ep['number']}  {ep['date']}  {ep['filename']}")
