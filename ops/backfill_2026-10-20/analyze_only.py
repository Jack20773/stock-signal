"""2026-10-20 補 EP697~699：只跑真的 analyzer.analyze()（claude -p 訂閱制），
結果存成 JSON，不寫資料庫。寫 DB 要等丹尼爾看過 dry-run 再說。"""
import json, sys, time
from pathlib import Path
HERE = Path(__file__).parent
PROJ = HERE.parent.parent
sys.path.insert(0, str(PROJ))
import os; os.chdir(PROJ)
from batch import load_transcripts, ep_number, _analyze_with_retry
files = [f for f in load_transcripts() if ep_number(f) in (697, 698, 699)]
print("files:", [f.name for f in files], flush=True)
for f in files:
    out = HERE / f"EP{ep_number(f)}_result.json"
    if out.exists():
        print("skip (already have)", out.name, flush=True); continue
    t0 = time.time()
    r = _analyze_with_retry(f.read_text(encoding="utf-8"))
    r["episode_id"] = f"EP{ep_number(f)}"   # 同 batch.run_batch：用檔名覆蓋
    out.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"done {out.name} {time.time()-t0:.0f}s signals={len(r.get('extracted_signals', []))}", flush=True)
