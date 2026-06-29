import sys
import json
import re
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
from analyzer import analyze
from database import init_db, save_result


def srt_to_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    # 移除 SRT 序號與時間戳，只保留字幕文字
    text = re.sub(r"\d+\n\d{2}:\d{2}:\d{2},\d+ --> \d{2}:\d{2}:\d{2},\d+\n", "", text)
    return text.strip()


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python main.py <transcript.txt>    # 純文字逐字稿")
        print("  python main.py <transcript.srt>    # 直接吃 yt-transcript 輸出的 SRT")
        print("  python main.py -                   # 從 stdin 讀入")
        sys.exit(1)

    init_db()

    src = sys.argv[1]
    if src == "-":
        transcript = sys.stdin.read()
    else:
        p = Path(src)
        if not p.exists():
            print(f"File not found: {src}")
            sys.exit(1)
        transcript = srt_to_text(p) if p.suffix == ".srt" else p.read_text(encoding="utf-8")

    print(f"Analyzing... ({len(transcript):,} chars)\n")

    try:
        result = analyze(transcript)
    except json.JSONDecodeError as e:
        print(f"JSON parse error: {e}")
        sys.exit(1)

    count = save_result(result)

    print(f"Episode : {result.get('episode_id')}")
    print(f"Date    : {result.get('analysis_date')}")
    if count == -1:
        print("Signals : already in DB (skipped). Use --force to overwrite.\n")
    else:
        print(f"Signals : {count} extracted\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
