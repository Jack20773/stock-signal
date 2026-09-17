# -*- coding: utf-8 -*-
"""把 Claude 子分身寫好的人話重點 JSON 回填進 signals 的新欄位（2026-09-17 一次性）。

  python -X utf8 ops/backfill_company_notes.py PAIRS.json batch*.json            # 唯讀 dry-run：印「將更新 N 筆／母體 M 筆」
  CONFIRM_DB=1 python -X utf8 ops/backfill_company_notes.py --apply PAIRS.json batch*.json

只做 UPDATE signals SET summary/oneliner/context/substantive/quote_long/notes_source/notes_at
WHERE id=%s AND summary IS NULL AND notes_source IS NULL——**只填新欄位、只填還是 NULL 的列**，
不動任何既有欄位；found=false 的筆 summary 留 NULL（頁面顯示「這集只有一句原話」）。
存放位置是 (stock_code, episode_id) 的 id 最小那筆（PAIRS.json 就是這樣算出來的）。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

SOURCE = "claude-backfill"


def load(pairs_path: str, batch_paths: list[str]):
    pairs = json.load(open(pairs_path, encoding="utf-8"))
    notes: dict[tuple[str, str], dict] = {}
    for bp in batch_paths:
        data = json.load(open(bp, encoding="utf-8"))
        for code, eps in data.items():
            for ep, rec in eps.items():
                notes[(code, ep)] = rec
    return pairs, notes


def plan(pairs, notes):
    """回傳 (updates, found_false, missing)。updates = [(summary, oneliner, context, substantive, quote_long, id)]"""
    updates, found_false, missing = [], [], []
    for p in pairs:
        rec = notes.get((p["code"], p["ep"]))
        if rec is None:
            missing.append((p["code"], p["ep"]))
            continue
        found = bool(rec.get("found", True))
        summary = (rec.get("summary") or "").strip() if found else ""
        oneliner = (rec.get("oneliner") or "").strip() if found else ""
        context = (rec.get("context") or "").strip() or None
        sub = rec.get("substantive")
        sub = sub if isinstance(sub, bool) else None
        quote_long = (rec.get("quote") or "").strip() or None
        if not found:
            found_false.append((p["code"], p["ep"]))
        updates.append((summary or None, oneliner or None, context, sub, quote_long, p["id"]))
    return updates, found_false, missing


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    apply = "--apply" in sys.argv
    pairs_path, batch_paths = args[0], args[1:]
    pairs, notes = load(pairs_path, batch_paths)
    updates, found_false, missing = plan(pairs, notes)

    from database import _conn, init_db
    init_db()
    ids = [u[-1] for u in updates]
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM signals")
            total = cur.fetchone()["n"]
            cur.execute(
                "SELECT COUNT(*) AS n FROM signals WHERE id IN %s AND summary IS NULL AND notes_source IS NULL",
                (tuple(ids) if ids else (-1,),),
            )
            eligible = cur.fetchone()["n"]

    print(f"母體 M（signals 全表）= {total}")
    print(f"對子數（PAIRS）= {len(pairs)}；JSON 有結果 = {len(updates)}；JSON 缺 = {len(missing)} {missing[:10]}")
    print(f"found=false F = {len(found_false)} {found_false}")
    print(f"目前仍為 NULL、可更新 = {eligible}（將更新 N 筆 = {eligible}）")
    print(f"summary 有值將寫入 K = {sum(1 for u in updates if u[0])}")

    if not apply:
        print("（dry-run，未寫入；要執行請加 --apply 且指令開頭 CONFIRM_DB=1）")
        return 0
    if os.environ.get("CONFIRM_DB") != "1":
        print("拒絕：--apply 需要 CONFIRM_DB=1")
        return 2

    import psycopg2.extras
    with _conn() as conn:
        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(cur, f"""
                UPDATE signals
                SET summary=%s, oneliner=%s, context=%s, substantive=%s, quote_long=%s,
                    notes_source='{SOURCE}', notes_at=NOW()
                WHERE id=%s AND summary IS NULL AND notes_source IS NULL
            """, updates)
            cur.execute(
                "SELECT COUNT(*) AS n, COUNT(summary) AS s FROM signals WHERE id IN %s AND notes_source=%s",
                (tuple(ids), SOURCE),
            )
            r = cur.fetchone()
    print(f"已寫入：notes_source='{SOURCE}' 的列 = {r['n']}，其中 summary 有值 = {r['s']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
