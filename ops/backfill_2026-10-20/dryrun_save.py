"""2026-10-20 dry-run：用真的 database.save_result() 跑一遍，但把 DB 連線換成
只記錄不執行的假連線 -> 列出「會新增的列」。另外唯讀查一次正式庫確認 EP697~699
真的還沒有 episode_analysis 列（有的話真的 save_result 會回 -1、一筆都不寫）。
加 --commit 才會走真的 save_result 寫正式庫（要丹尼爾點頭後才跑）。"""
import json, sys, os
from contextlib import contextmanager
from pathlib import Path
HERE = Path(__file__).parent
PROJ = HERE.parent.parent
sys.path.insert(0, str(PROJ)); os.chdir(PROJ)
import database

EPS = ["EP697", "EP698", "EP699"]
results = [json.loads((HERE / f"{e}_result.json").read_text(encoding="utf-8")) for e in EPS]

with database._conn() as c:   # 唯讀
    cur = c.cursor()
    cur.execute("SELECT episode_id FROM episode_analysis WHERE episode_id = ANY(%s)", (EPS,))
    already = [r["episode_id"] for r in cur.fetchall()]
    cur.execute("SELECT count(*) AS n FROM signals WHERE episode_id = ANY(%s)", (EPS,))
    n_sig = cur.fetchone()["n"]
print(f"[唯讀] 正式庫 episode_analysis 已有：{already or '無'}；signals 已有 {n_sig} 筆")

if "--commit" in sys.argv:
    for r in results:
        print(r["episode_id"], "寫入", database.save_result(r), "筆")
    sys.exit(0)


class FakeCur:
    def __init__(s): s.log = []; s._ret = None
    def execute(s, sql, params=None):
        s.log.append((" ".join(sql.split()), params))
        s._ret = ("x",) if "RETURNING" in sql else None
    def fetchone(s): return s._ret
    def __enter__(s): return s
    def __exit__(s, *a): return False


class FakeConn:
    def __init__(s): s.cur = FakeCur()
    def cursor(s): return s.cur
    def commit(s): pass
    def rollback(s): pass


KEYS = ["episode_id", "analysis_date", "stock_name", "stock_code", "action",
        "confidence_level", "reasoning", "exact_quote", "raw_reason", "primary_tag",
        "secondary_tags", "rule_version", "claim_type", "summary", "oneliner",
        "context", "substantive", "notes_source", "notes_at_now"]
rows_out = []
for r in results:
    fc = FakeConn()

    @contextmanager
    def fake():
        yield fc
    orig = database._conn
    database._conn = fake
    try:
        n = database.save_result(r)
    finally:
        database._conn = orig
    print(f"\n===== {r['episode_id']}（analysis_date={r.get('analysis_date')}）會寫 {n} 筆 signals；"
          f"模型原始點名 {len(r.get('extracted_signals', []))} 個 =====")
    for sql, p in fc.cur.log:
        if sql.startswith("INSERT INTO signals"):
            d = dict(zip(KEYS, p))
            rows_out.append(d)
            print(f"  {d['stock_name']} {d['stock_code']} action={d['action']} conf={d['confidence_level']} "
                  f"claim={d['claim_type']} rule={d['rule_version']} src={d['notes_source']}")
            print(f"    原話：{(d['exact_quote'] or '')[:140]}")
        else:
            print("  SQL:", sql[:100], p)
(HERE / "dryrun_rows.json").write_text(json.dumps(rows_out, ensure_ascii=False, indent=2, default=str),
                                      encoding="utf-8")
