import sys, json, urllib.request, urllib.parse, time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BASE_URL = "https://whatmkreallysaid.com"
OUT_DIR  = Path("transcripts")
OUT_DIR.mkdir(exist_ok=True)

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=15).read()

episodes = json.loads(fetch(f"{BASE_URL}/episodes.json").decode("utf-8"))
print(f"Total episodes: {len(episodes)}")

for ep in episodes[:3]:
    fn  = ep["filename"]
    url = f"{BASE_URL}/episodes/{urllib.parse.quote(fn)}"
    content = fetch(url)
    (OUT_DIR / fn).write_bytes(content)
    print(f"OK  EP{ep['number']}  {fn}  ({len(content)} bytes)")
    time.sleep(0.5)
