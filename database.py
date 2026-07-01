import json
import logging
import re
import sqlite3
from pathlib import Path

from stock_dict import resolve_code

DB_PATH = Path(__file__).parent / "signals.db"
_initialized = False

# 合法 ticker 格式：台股 xxxx.TW / .TWO，美股 1-5 大寫字母（含數字後綴如 BRK.B）
_TW_PAT = re.compile(r"^\d{4,5}\.(TW|TWO)$")
_US_PAT = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")

_KNOWN_PRIVATE = {"SPACEX", "BYTEDANCE", "STRIPE", "SHEIN"}  # 已知未上市


def _valid_ticker(code: str) -> bool:
    if code in _KNOWN_PRIVATE:
        return False
    return bool(_TW_PAT.match(code) or _US_PAT.match(code))


def init_db():
    global _initialized
    if _initialized:
        return
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
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
                created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        for col, typedef in [
            ("entry_date",           "TEXT"),
            ("entry_price",          "REAL"),
            ("benchmark_ticker",     "TEXT"),
            ("stock_return_pct",     "REAL"),
            ("benchmark_return_pct", "REAL"),
            ("beat_benchmark",       "INTEGER"),
            ("days_held",            "INTEGER"),
            ("perf_updated_at",      "TEXT"),
        ]:
            try:
                conn.execute(f"ALTER TABLE signals ADD COLUMN {col} {typedef}")
            except sqlite3.OperationalError:
                pass  # column already exists
    _initialized = True


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
            name   = s.get("stock_name", "")
            code   = s.get("stock_code") or "Unknown"
            action = s.get("action", "0")

            # 嘗試用名稱補齊 Unknown 代號
            code = resolve_code(name, code)

            # Unknown 代號不寫入（無法回測）
            if code == "Unknown":
                logging.debug(f"[跳過] {episode_id} {name!r}：無法解析代號")
                continue

            # 無效 ticker 格式（未上市、公司名稱誤當代號等）
            if not _valid_ticker(code):
                logging.warning(f"[無效代號] {episode_id} {name!r}：{code!r} 不符合 ticker 格式，略過")
                continue

            # 同集同股衝突攔截
            if code in seen and seen[code] != action and action != "0" and seen[code] != "0":
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


def save_perf_results(results: list[dict]) -> int:
    """將 calc_performance() 的結果（勝負、報酬、天數）寫回 signals 表，供離線讀取。"""
    from datetime import date as _date
    today = _date.today().isoformat()
    updates = []
    for r in results:
        sig_id = r.get("id")
        if not sig_id:
            continue
        beat = r.get("beat_benchmark")
        updates.append((
            r.get("stock_return_pct"),
            r.get("benchmark_return_pct"),
            (1 if beat is True else (0 if beat is False else None)),
            r.get("days_held"),
            today,
            sig_id,
        ))
    if not updates:
        return 0
    with sqlite3.connect(DB_PATH) as conn:
        conn.executemany("""
            UPDATE signals
            SET stock_return_pct=?, benchmark_return_pct=?,
                beat_benchmark=?, days_held=?, perf_updated_at=?
            WHERE id=?
        """, updates)
    return len(updates)


def list_signals(episode_id: str = None) -> list[dict]:
    query  = "SELECT * FROM signals"
    params = ()
    if episode_id:
        query  += " WHERE episode_id=?"
        params  = (episode_id,)
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query + " ORDER BY created_at DESC", params).fetchall()
    return [dict(r) for r in rows]
