"""2026-10-20：修正式庫 signals 裡 93 筆 entry_date／entry_price 錯（根因見
gooaye-site/db_fix_dryrun_2026-10-17/說明.md）。丹尼爾 2026-10-20 01:00 授權（先備份）。

只動 CSV 列出的 93 個 signal_id：entry_date 改成 episodes.json 上架日、entry_price 用
跟 _fill_entry_prices 同一套 batch_get_close_on_or_before 重抓。
預設 dry-run（只印、不寫）；加 --commit 才寫，且 UPDATE 影響筆數 != 93 會 rollback。
寫之前把這 93 筆的舊值存到 old_values.json（逐筆還原用）。
在 stock-signal 目錄跑：python -X utf8 ops/fix_entry_date_2026-10-20/fix93.py [--commit]
"""
import csv, json, os, sys
from pathlib import Path
HERE = Path(__file__).parent
PROJ = HERE.parent.parent
sys.path.insert(0, str(PROJ)); os.chdir(PROJ)
import psycopg2.extras
from database import _conn
from prices import batch_get_close_on_or_before

CSV = PROJ.parent / "gooaye-site/db_fix_dryrun_2026-10-17/entry_date_mismatch.csv"
want = {int(r["signal_id"]): r["entry_date_should_be"]
        for r in csv.DictReader(open(CSV, encoding="utf-8-sig"))}
ids = sorted(want)
assert len(ids) == 93, len(ids)
air = {f"EP{e['number']}": e["date"] for e in json.loads((PROJ / "episodes.json").read_text(encoding="utf-8"))
       if e.get("number") and e.get("date")}

with _conn() as c:
    cur = c.cursor()
    cur.execute("SELECT id, episode_id, stock_code, entry_date, entry_price FROM signals WHERE id = ANY(%s)", (ids,))
    rows = [dict(r) for r in cur.fetchall()]
assert len(rows) == 93, f"DB 只找到 {len(rows)} 筆"

plan, bad = [], []
for r in rows:
    d = air.get(r["episode_id"])
    if d != want[r["id"]]:
        bad.append((r["id"], "episodes.json 日期與 CSV 不符", d, want[r["id"]]))
        continue
    plan.append({"id": r["id"], "code": r["stock_code"], "date": d,
                 "old_date": str(r["entry_date"]), "old_price": float(r["entry_price"]) if r["entry_price"] is not None else None})
prices = batch_get_close_on_or_before(list(dict.fromkeys((p["code"], p["date"]) for p in plan)))
for p in plan:
    p["price"] = prices.get((p["code"], p["date"]))
    if not p["price"] and p["old_price"] is not None:   # 原本就沒價（如已下市的 CFLT）只修日期
        bad.append((p["id"], "抓不到價", p["code"], p["date"]))
    print(f"  id={p['id']} {p['code']} {p['old_date']} @{p['old_price']} -> {p['date']} @{p['price']}")
if bad:
    print("有問題，停止：", bad); sys.exit(1)
print(f"計畫更新 {len(plan)} 筆")

if "--commit" not in sys.argv:
    print("dry-run，沒寫"); sys.exit(0)

(HERE / "old_values.json").write_text(json.dumps(
    [{"id": p["id"], "entry_date": p["old_date"], "entry_price": p["old_price"]} for p in plan],
    ensure_ascii=False, indent=1), encoding="utf-8")
id_list = ",".join(map(str, ids))   # 全是 int，來自 CSV
with _conn() as conn:   # 例外 -> _conn 自動 rollback；正常結束才 commit
    cur = conn.cursor()
    psycopg2.extras.execute_values(cur, f"""
        UPDATE signals AS s SET entry_date = v.d, entry_price = v.p
        FROM (VALUES %s) AS v(id, d, p)
        WHERE s.id = v.id AND s.id IN ({id_list})""",
        [(p["id"], p["date"], p["price"]) for p in plan],
        template="(%s::bigint, %s::text, %s::real)", page_size=1000)
    n = cur.rowcount
    print("UPDATE 影響筆數：", n)
    if n != 93:
        raise RuntimeError(f"影響 {n} 筆 != 93，rollback")
print("已 commit")
