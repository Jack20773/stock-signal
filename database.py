import json
import logging
import re
from contextlib import contextmanager
from datetime import date

import psycopg2
import psycopg2.extras
import psycopg2.pool

from config import DATABASE_URL
from stock_dict import resolve_code

_pool: psycopg2.pool.ThreadedConnectionPool | None = None
_initialized = False

_TW_PAT = re.compile(r"^\d{4,5}\.(TW|TWO)$")
_US_PAT = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")
_KNOWN_PRIVATE = {"BYTEDANCE", "STRIPE", "SHEIN"}  # SpaceX 已於 2026-06-12 IPO（SPCX），移出名單


def _valid_ticker(code: str) -> bool:
    if code in _KNOWN_PRIVATE:
        return False
    return bool(_TW_PAT.match(code) or _US_PAT.match(code))


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise RuntimeError(
                "DATABASE_URL 未設定。請在 .env 加入 DATABASE_URL=postgresql://..."
            )
        _pool = psycopg2.pool.ThreadedConnectionPool(
            1, 5, DATABASE_URL,
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
    return _pool


@contextmanager
def _conn():
    """取得連線，commit/rollback 後自動歸還 pool。"""
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def init_db():
    global _initialized
    if _initialized:
        return
    with _conn() as conn:
        with conn.cursor() as cur:
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
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_signals_episode
                ON signals(episode_id)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_signals_stock_code
                ON signals(stock_code)
            """)
    _initialized = True


def save_result(result: dict) -> int:
    """儲存分析結果；若該集數已有訊號則跳過並回傳 -1。"""
    episode_id    = result.get("episode_id", "Unknown")
    analysis_date = result.get("analysis_date", "")
    signals       = result.get("extracted_signals", [])

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM signals WHERE episode_id=%s", (episode_id,)
            )
            if cur.fetchone()["count"] > 0:
                return -1

            saved = 0
            seen: dict[str, str] = {}

            for s in signals:
                name   = s.get("stock_name", "")
                code   = s.get("stock_code") or "Unknown"
                action = s.get("action", "0")

                code = resolve_code(name, code)

                if code == "Unknown":
                    logging.debug(f"[跳過] {episode_id} {name!r}：無法解析代號")
                    continue

                if not _valid_ticker(code):
                    logging.warning(
                        f"[無效代號] {episode_id} {name!r}：{code!r} 不符合 ticker 格式，略過"
                    )
                    continue

                if code in seen and seen[code] != action and action != "0" and seen[code] != "0":
                    logging.warning(
                        f"[衝突攔截] {episode_id} {code}：已有 {seen[code]}，新訊號 {action} 被丟棄"
                    )
                    continue

                seen[code] = action

                cur.execute("""
                    INSERT INTO signals
                        (episode_id, analysis_date, stock_name, stock_code, action,
                         confidence_level, reasoning, exact_quote, raw_reason,
                         primary_tag, secondary_tags)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (
                    episode_id, analysis_date,
                    s.get("stock_name"), code, action,
                    s.get("confidence_level"), s.get("reasoning"),
                    s.get("exact_quote"), s.get("raw_reason"),
                    s.get("primary_tag"),
                    json.dumps(s.get("secondary_tags", []), ensure_ascii=False),
                ))
                saved += 1

    return saved


def save_perf_results(results: list[dict]) -> int:
    """將 calc_performance() 結果寫回 signals 表供離線讀取。"""
    today = date.today().isoformat()
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
    with _conn() as conn:
        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(cur, """
                UPDATE signals
                SET stock_return_pct=%s, benchmark_return_pct=%s,
                    beat_benchmark=%s, days_held=%s, perf_updated_at=%s
                WHERE id=%s
            """, updates)
    return len(updates)


def list_signals(episode_id: str = None) -> list[dict]:
    init_db()
    with _conn() as conn:
        with conn.cursor() as cur:
            if episode_id:
                cur.execute(
                    "SELECT * FROM signals WHERE episode_id=%s ORDER BY created_at DESC",
                    (episode_id,)
                )
            else:
                cur.execute("SELECT * FROM signals ORDER BY created_at DESC")
            return [dict(r) for r in cur.fetchall()]
