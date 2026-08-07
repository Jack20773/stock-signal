import os
import json
import decimal
import datetime
from dotenv import load_dotenv
load_dotenv(override=True)
import psycopg2
import psycopg2.extras

def json_default(obj):
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()
    if isinstance(obj, decimal.Decimal):
        return float(obj)
    raise TypeError(f"Cannot serialize {type(obj)}")

conn = psycopg2.connect(os.environ['DATABASE_URL'], cursor_factory=psycopg2.extras.RealDictCursor)
cur = conn.cursor()

cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name")
tables = [r['table_name'] for r in cur.fetchall()]

backup = {}
for t in tables:
    cur.execute(f"SELECT * FROM {t}")
    rows = [dict(r) for r in cur.fetchall()]
    backup[t] = rows
    print(f"  {t}: {len(rows)} rows dumped")

conn.close()

ts = datetime.date.today().isoformat()
out_path = f"backups/backup_stocksignal_db_{ts}.json"
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(backup, f, default=json_default, ensure_ascii=False, indent=2)

print(f"\nSaved to {out_path}")
import os as _os
print(f"File size: {_os.path.getsize(out_path)} bytes")
