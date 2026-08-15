"""
把 stock-signal 的資料庫從 Railway 搬到 Neon：
1. 讀 .env.neon 拿 NEON_DATABASE_URL
2. 直接對 Neon 執行建表 SQL（複製自 database.py 的 init_db，不 import 該模組以避免 config.py 的 load_dotenv(override=True) 蓋掉連線目標）
3. 從 backups/backup_stocksignal_db_2026-07-06.json 還原資料
不印出任何連線字串或密鑰。
"""
import re
import sys
import json
import psycopg2

def load_neon_url():
    with open(".env.neon", "r", encoding="utf-8") as f:
        content = f.read()
    match = re.search(r"^NEON_DATABASE_URL=(.+)$", content, re.MULTILINE)
    if not match:
        print("[錯誤] .env.neon 裡沒有 NEON_DATABASE_URL")
        sys.exit(1)
    return match.group(1).strip()

neon_url = load_neon_url()
conn = psycopg2.connect(neon_url)
cur = conn.cursor()

cur.execute("""
    CREATE TABLE IF NOT EXISTS signals (
        id                   BIGSERIAL PRIMARY KEY,
        episode_id           TEXT,
        analysis_date        TEXT,
        stock_name           TEXT,
        stock_code           TEXT,
        action               TEXT,
        confidence_level     TEXT,
        reasoning            TEXT,
        exact_quote          TEXT,
        raw_reason           TEXT,
        primary_tag          TEXT,
        secondary_tags       TEXT,
        entry_date           TEXT,
        entry_price          REAL,
        benchmark_ticker     TEXT,
        stock_return_pct     REAL,
        benchmark_return_pct REAL,
        beat_benchmark       INTEGER,
        days_held            INTEGER,
        perf_updated_at      TEXT,
        created_at           TIMESTAMPTZ DEFAULT NOW()
    )
""")
cur.execute("""
    CREATE TABLE IF NOT EXISTS price_cache (
        ticker     TEXT NOT NULL,
        ref_date   TEXT NOT NULL,
        price      REAL,
        cache_date TEXT NOT NULL,
        PRIMARY KEY (ticker, ref_date)
    )
""")
cur.execute("CREATE INDEX IF NOT EXISTS idx_signals_episode ON signals(episode_id)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_signals_stock_code ON signals(stock_code)")
cur.execute("""
    CREATE TABLE IF NOT EXISTS subscribers (
        id                  BIGSERIAL PRIMARY KEY,
        email               TEXT UNIQUE NOT NULL,
        token               TEXT UNIQUE NOT NULL,
        status              TEXT NOT NULL DEFAULT 'active',
        created_at          TIMESTAMPTZ DEFAULT NOW(),
        last_subscribed_at  TIMESTAMPTZ DEFAULT NOW()
    )
""")
cur.execute("""
    CREATE TABLE IF NOT EXISTS latest_report (
        id         INTEGER PRIMARY KEY DEFAULT 1,
        subject    TEXT,
        html       TEXT,
        updated_at TIMESTAMPTZ DEFAULT NOW(),
        CHECK (id = 1)
    )
""")
conn.commit()
print("Neon schema 建立完成（signals / price_cache / subscribers / latest_report）")


def restore_table(rows, table):
    if not rows:
        print(f"  {table}: 0 筆，跳過")
        return
    cols = list(rows[0].keys())
    placeholders = ", ".join(["%s"] * len(cols))
    col_names = ", ".join(cols)
    sql = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"
    values = [[r.get(c) for c in cols] for r in rows]
    cur.executemany(sql, values)
    conn.commit()
    print(f"  {table}: 已還原 {len(rows)} 筆")


backup_file = "backups/backup_stocksignal_db_2026-07-06.json"
with open(backup_file, "r", encoding="utf-8") as f:
    data = json.load(f)

for table, rows in data.items():
    restore_table(rows, table)

conn.close()
print("\n還原完成")
