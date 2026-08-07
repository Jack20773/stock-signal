"""
還原 backup_db.py 產生的 JSON 備份到指定的 PostgreSQL。
用法：python restore_db.py <backup_file.json> [--target-env-var DATABASE_URL] [--dry-run]

⚠️ 已知缺陷（2026-08-08 實測確認，尚未修）——災難還原前務必先讀：

1. **不重設 sequence**。本腳本帶著明確 id 值 INSERT，但沒有 setval。
   signals / subscribers / signal_review 三張表的 id 走 nextval，
   還原完 sequence 仍停在還原前的值 → 系統下一次正常寫入直接 UniqueViolation
   （duplicate key value violates unique constraint）。
   還原後必須手動補跑，每張表一次：
       SELECT setval('signals_id_seq',       (SELECT COALESCE(MAX(id),1) FROM signals));
       SELECT setval('subscribers_id_seq',   (SELECT COALESCE(MAX(id),1) FROM subscribers));
       SELECT setval('signal_review_id_seq', (SELECT COALESCE(MAX(id),1) FROM signal_review));

2. **ON CONFLICT DO NOTHING 沒指定衝突目標**。還原到「非空」資料庫時會靜默跳過，
   畫面照樣印「已還原 N 筆」但實際一筆都沒進。只有還原到空庫時輸出才可信。

3. 每張表重開一次連線（見 restore() 內迴圈），大表會慢。

補充：本備份只含「資料」不含 schema。建表 DDL 在 database.py（5 張表）與
crosscheck.py（signal_review），兩者都在版控中，Neon 整個消失仍可重建。
"""
import os
import sys
import json
import argparse
from dotenv import load_dotenv
load_dotenv(override=True)
import psycopg2

def restore(backup_file, target_env_var, dry_run=False):
    with open(backup_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    target_url = os.environ.get(target_env_var)
    if not target_url and not dry_run:
        print(f"[錯誤] 環境變數 {target_env_var} 未設定")
        sys.exit(1)

    if dry_run:
        print(f"[Dry-run] 目標：{target_env_var}（未實際連線）")

    for table, rows in data.items():
        if not rows:
            print(f"  {table}: 0 筆，跳過")
            continue
        cols = list(rows[0].keys())
        placeholders = ", ".join(["%s"] * len(cols))
        col_names = ", ".join(cols)
        sql = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"

        if dry_run:
            print(f"  {table}: 會插入 {len(rows)} 筆")
            print(f"    範例 SQL: {sql}")
            continue

        conn = psycopg2.connect(target_url)
        cur = conn.cursor()
        values = [[r.get(c) for c in cols] for r in rows]
        cur.executemany(sql, values)
        conn.commit()
        print(f"  {table}: 已還原 {len(rows)} 筆")
        conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("backup_file")
    parser.add_argument("--target-env-var", default="DATABASE_URL")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    restore(args.backup_file, args.target_env_var, args.dry_run)
