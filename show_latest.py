import sys, json, urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

episodes = json.loads(
    urllib.request.urlopen(
        urllib.request.Request(
            "https://whatmkreallysaid.com/episodes.json",
            headers={"User-Agent": "Mozilla/5.0"}
        ), timeout=15
    ).read().decode("utf-8")
)

latest = max(episodes, key=lambda e: (e.get("date", ""), e.get("number", 0)))

print(f"EP     : {latest['number']}")
print(f"Title  : {latest.get('display_title', latest.get('title', ''))}")
print(f"Date   : {latest.get('date', '')}")
print(f"File   : {latest['filename']}")
print(f"Summary: {latest.get('summary', '')}")
print()

# Read local file
def safe_filename(name):
    for ch in '\\/:*?"<>|':
        name = name.replace(ch, "_")
    return name

local = Path("transcripts") / safe_filename(latest["filename"])
if local.exists():
    print("=== 逐字稿（前 3000 字）===")
    print(local.read_text(encoding="utf-8")[:3000])
else:
    print(f"本地未找到：{local}")
