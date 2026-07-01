"""
SQLite → PostgreSQL 資料遷移腳本

用法（先確認 .env 有 DATABASE_URL）：
  python -X utf8 migrate.py                # 完整遷移
  python -X utf8 migrate.py --dry-run      # 只計算筆數，不寫入
  python -X utf8 migrate.py --skip-prices  # 不遷移 price_cache（會重新抓）
"""
import sys
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

SQLITE_PATH = Path(__file__).parent / "signals.db"


def migrate(dry_run: bool = False, skip_prices: bool = False):
    if not SQLITE_PATH.exists():
        print(f"[ERROR] 找不到 SQLite 資料庫：{SQLITE_PATH}")
        sys.exit(1)

    # 連 SQLite
    src = sqlite3.connect(SQLITE_PATH)
    src.row_factory = sqlite3.Row

    # 連 PostgreSQL（從 database.py 取 pool）
    from database import init_db, _conn
    init_db()

    # ── 遷移 signals ──────────────────────────────────────────────
    print("\n[1/2] 遷移 signals 表...")
    src_rows = src.execute("SELECT * FROM signals ORDER BY id ASC").fetchall()
    print(f"  SQLite 共 {len(src_rows)} 筆訊號")

    if not dry_run and src_rows:
        import psycopg2.extras
        cols = [
            "episode_id", "analysis_date", "stock_name", "stock_code",
            "action", "confidence_level", "reasoning", "exact_quote",
            "raw_reason", "primary_tag", "secondary_tags",
            "entry_date", "entry_price", "benchmark_ticker",
            "stock_return_pct", "benchmark_return_pct",
            "beat_benchmark", "days_held", "perf_updated_at",
        ]
        rows_to_insert = []
        for r in src_rows:
            row_dict = dict(r)
            rows_to_insert.append(tuple(row_dict.get(c) for c in cols))

        col_str   = ", ".join(cols)
        place_str = ", ".join(["%s"] * len(cols))

        with _conn() as conn:
            with conn.cursor() as cur:
                # 跳過已存在的 episode_id，避免重複
                cur.execute("SELECT DISTINCT episode_id FROM signals")
                existing_eps = {r["episode_id"] for r in cur.fetchall()}

                new_rows = [
                    r for r in rows_to_insert
                    if r[0] not in existing_eps  # r[0] = episode_id
                ]

                if new_rows:
                    psycopg2.extras.execute_values(
                        cur,
                        f"INSERT INTO signals ({col_str}) VALUES %s",
                        new_rows,
                        page_size=200,
                    )
                    print(f"  已寫入 {len(new_rows)} 筆（跳過 {len(rows_to_insert)-len(new_rows)} 筆重複）")
                else:
                    print("  所有集數已存在，跳過")

    # ── 遷移 price_cache ──────────────────────────────────────────
    if not skip_prices:
        print("\n[2/2] 遷移 price_cache 表...")
        try:
            cache_rows = src.execute("SELECT * FROM price_cache").fetchall()
        except sqlite3.OperationalError:
            cache_rows = []
        print(f"  SQLite 共 {len(cache_rows)} 筆快取")

        if not dry_run and cache_rows:
            import psycopg2.extras
            data = [(r["ticker"], r["ref_date"], r["price"], r["cache_date"]) for r in cache_rows]
            with _conn() as conn:
                with conn.cursor() as cur:
                    psycopg2.extras.execute_values(
                        cur,
                        """INSERT INTO price_cache (ticker, ref_date, price, cache_date)
                           VALUES %s
                           ON CONFLICT (ticker, ref_date) DO UPDATE
                               SET price=EXCLUDED.price, cache_date=EXCLUDED.cache_date""",
                        data,
                        page_size=500,
                    )
            print(f"  已 upsert {len(data)} 筆價格快取")
    else:
        print("\n[2/2] 跳過 price_cache（--skip-prices）")

    src.close()

    # ── 驗證 ──────────────────────────────────────────────────────
    print("\n[驗證] PostgreSQL 目前資料量：")
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM signals")
            sig_count = cur.fetchone()["count"]
            cur.execute("SELECT COUNT(*) FROM price_cache")
            price_count = cur.fetchone()["count"]
    print(f"  signals:     {sig_count} 筆")
    print(f"  price_cache: {price_count} 筆")

    if dry_run:
        print("\n[dry-run] 以上為預覽，實際未寫入任何資料。")
    else:
        print("\n✅ 遷移完成！")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run",      action="store_true", help="預覽模式，不寫入")
    parser.add_argument("--skip-prices",  action="store_true", help="跳過 price_cache 遷移")
    args = parser.parse_args()
    migrate(dry_run=args.dry_run, skip_prices=args.skip_prices)
