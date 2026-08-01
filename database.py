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
                ALTER TABLE subscribers
                ADD COLUMN IF NOT EXISTS last_subscribed_at TIMESTAMPTZ DEFAULT NOW()
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
            # 2026-08-02 索羅門新增：取代原本用 signals 表判斷「已分析」的邏輯。
            # PRIMARY KEY 天生防併發重複插入（見 save_result() 的 INSERT ON CONFLICT
            # DO NOTHING RETURNING 用法），且 0 訊號的集數也會有一筆紀錄，不會被
            # batch.py 誤判成「還沒跑過」而每次重跑。
            cur.execute("""
                CREATE TABLE IF NOT EXISTS episode_analysis (
                    episode_id   TEXT PRIMARY KEY,
                    signal_count INTEGER NOT NULL,
                    analyzed_at  TIMESTAMPTZ DEFAULT NOW()
                )
            """)
    _initialized = True


def save_latest_report(subject: str, html: str) -> None:
    """存一份最新的 mail 版報告，供 linebot 在新訂閱者確認訂閱時直接撈來寄送（單行表，只存最新一份）"""
    init_db()
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO latest_report (id, subject, html, updated_at)
                VALUES (1, %s, %s, NOW())
                ON CONFLICT (id) DO UPDATE SET subject=EXCLUDED.subject, html=EXCLUDED.html, updated_at=NOW()
            """, (subject, html))


def list_active_subscribers() -> list[dict]:
    """回傳 rijian-studio 訂閱名單中狀態為 active 的 email + 個人化退訂 token"""
    init_db()
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT email, token FROM subscribers WHERE status='active'")
            return [dict(r) for r in cur.fetchall()]


def save_result(result: dict) -> int:
    """儲存分析結果；若該集數已分析過（不論當初萃取到 0 個還是多個訊號）則跳過並回傳 -1。

    用 episode_analysis 的 INSERT ... ON CONFLICT DO NOTHING RETURNING 判斷是否
    「第一個拿到這集」——PRIMARY KEY 讓這個判斷本身具備並發安全性（兩個進程同時
    處理同一集時，只有一個會拿到 RETURNING 的列，另一個直接跳過），不像舊版
    「SELECT COUNT 再 INSERT」中間有 race window。
    """
    episode_id    = result.get("episode_id", "Unknown")
    analysis_date = result.get("analysis_date", "")
    signals       = result.get("extracted_signals", [])

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO episode_analysis (episode_id, signal_count)
                VALUES (%s, 0)
                ON CONFLICT (episode_id) DO NOTHING
                RETURNING episode_id
                """,
                (episode_id,),
            )
            if cur.fetchone() is None:
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

            cur.execute(
                "UPDATE episode_analysis SET signal_count=%s WHERE episode_id=%s",
                (saved, episode_id),
            )

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
