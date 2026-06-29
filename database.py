import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "signals.db"


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                episode_id       TEXT,
                analysis_date    TEXT,
                stock_name       TEXT,
                stock_code       TEXT,
                action           TEXT,
                confidence_level TEXT,
                reasoning        TEXT,
                exact_quote      TEXT,
                raw_reason       TEXT,
                primary_tag      TEXT,
                secondary_tags   TEXT,
                entry_date       TEXT,
                entry_price      REAL,
                benchmark_ticker TEXT,
                created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # migrate existing DB
        for col, typedef in [
            ("entry_date",       "TEXT"),
            ("entry_price",      "REAL"),
            ("benchmark_ticker", "TEXT"),
        ]:
            try:
                conn.execute(f"ALTER TABLE signals ADD COLUMN {col} {typedef}")
            except Exception:
                pass


def save_result(result: dict) -> int:
    """儲存分析結果；若該集數已有訊號則跳過並回傳 -1。
    同集同股衝突（一看好一看空）會自動攔截並記錄警告。
    """
    episode_id    = result.get("episode_id", "Unknown")
    analysis_date = result.get("analysis_date", "")
    signals       = result.get("extracted_signals", [])

    with sqlite3.connect(DB_PATH) as conn:
        existing = conn.execute(
            "SELECT COUNT(*) FROM signals WHERE episode_id=?", (episode_id,)
        ).fetchone()[0]
        if existing > 0:
            return -1

        saved = 0
        seen: dict[str, str] = {}  # stock_code → action，攔截同集同股衝突

        for s in signals:
            code   = s.get("stock_code") or "Unknown"
            action = s.get("action", "0")

            # Unknown 代號不寫入（無法回測）
            if code == "Unknown":
                continue

            # 同集同股衝突攔截
            if code in seen and seen[code] != action and action != "0" and seen[code] != "0":
                import logging
                logging.warning(
                    f"[衝突攔截] {episode_id} {code}：已有 {seen[code]}，新訊號 {action} 被丟棄"
                )
                continue

            seen[code] = action

            conn.execute("""
                INSERT INTO signals
                    (episode_id, analysis_date, stock_name, stock_code, action,
                     confidence_level, reasoning, exact_quote, raw_reason,
                     primary_tag, secondary_tags)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                episode_id, analysis_date,
                s.get("stock_name"), code,
                action, s.get("confidence_level"),
                s.get("reasoning"),
                s.get("exact_quote"), s.get("raw_reason"),
                s.get("primary_tag"),
                json.dumps(s.get("secondary_tags", []), ensure_ascii=False),
            ))
            saved += 1

    return saved


def list_signals(episode_id: str = None) -> list[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        if episode_id:
            rows = conn.execute(
                "SELECT * FROM signals WHERE episode_id=? ORDER BY created_at DESC",
                (episode_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM signals ORDER BY created_at DESC"
            ).fetchall()
    return [dict(r) for r in rows]
