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


def _current_rule_version() -> str | None:
    """2026-08-15（ai-trader ④組規格 7.6.5）：寫入訊號時標記產生它的規則版本。

    刻意做成「取不到就回 None、不擋寫入」——版本追蹤是**稽核用的附加資訊**，
    不該因為它壞掉就讓整條分析管線寫不進訊號。這是本專案的主線功能，
    ④組只是它的下游消費者，下游的需求不該有能力弄停上游。
    """
    try:
        from prompt import rule_version  # noqa: PLC0415 -- 延遲 import，避免循環相依

        return rule_version()
    except Exception:  # noqa: BLE001 -- 見 docstring：取不到就留 NULL，不擋寫入
        logging.warning("[rule_version] 取不到規則版本，本次訊號的 rule_version 留空")
        return None


def _clean_claim_type(value, episode_id: str = "", code: str = "") -> str | None:
    """把模型回傳的 claim_type 收斂成 prompt.CLAIM_TYPES 之一，否則回 None（留 NULL）。

    跟 _current_rule_version() 同一個設計原則：這是**稽核用的附加欄位**，
    值不合法就留空並記一行日誌，不擋寫入、不猜一個值填進去——
    猜值等於製造假資料，而這一欄存在的理由正是「不要讓假的方向混進勝率分母」。
    """
    if value is None:
        return None
    v = str(value).strip().lower()
    try:
        from prompt import CLAIM_TYPES  # noqa: PLC0415 -- 延遲 import，避免循環相依
    except Exception:  # noqa: BLE001
        return None
    if v in CLAIM_TYPES:
        return v
    logging.warning(
        f"[claim_type] {episode_id} {code}：非法值 {value!r}（合法值 {CLAIM_TYPES}），本筆留空"
    )
    return None


# 台股：形狀取自本專案自己的官方白名單 `tw_listing_map.json`（證交所＋櫃買中心
# open API，2026-08-24 產生）。該檔 2326 筆代號的形狀只有兩種：
#   * 純數字 4~6 碼——一般股 `2330`、ETF `0050` / `00878`（5 碼）/ `006208`（6 碼）
#   * 5 碼數字＋1 個大寫字母——債券 ETF，例 `00679B`、`00687C`
# 舊版寫死 `\d{4,5}`，6 碼 ETF（DB 實測有 `006208.TW`）會被判無效整筆丟掉。
_TW_PAT = re.compile(r"^(?:\d{4,6}|\d{5}[A-Z])\.(?:TW|TWO)$")

# 美股：純大寫字母 1~5 碼，可帶一個單字母級別後綴（`BRK.B`）。維持原樣。
_US_PAT = re.compile(r"^[A-Z]{1,5}(?:\.[A-Z])?$")

# 外國掛牌：**只放行語料裡實際出現過的市場**（2026-08-24 唯讀查 signals 表得到）：
#   * `.T`  日本東證，4 碼數字——`6324.T`、`6787.T`、`6857.T`、`6981.T`
#   * `.KS` 韓國 KOSPI，6 碼數字——`005930.KS`、`000660.KS`、`009150.KS`
# 刻意不順手開放 `.KQ`/`.HK`/`.L` 等沒出現過的後綴：這個函式存在的目的就是擋掉
# Gemini 憑空拼出來的假代號（實例 `6elf.TW`），放寬過頭等於把守門員撤掉。
_JP_PAT = re.compile(r"^\d{4}\.T$")
_KR_PAT = re.compile(r"^\d{6}\.KS$")

_KNOWN_PRIVATE = {"BYTEDANCE", "STRIPE", "SHEIN"}  # SpaceX 已於 2026-06-12 IPO（SPCX），移出名單


def _valid_ticker(code: str) -> bool:
    """代號格式守門員：不符合任一已知市場形狀就不寫進 DB（見 save_result()）。"""
    if not isinstance(code, str):
        return False
    if code in _KNOWN_PRIVATE:
        return False
    return bool(
        _TW_PAT.match(code)
        or _US_PAT.match(code)
        or _JP_PAT.match(code)
        or _KR_PAT.match(code)
    )


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
            # 2026-08-15 新增（來源：ai-trader ④組規格 7.6.5，丹尼爾裁決「要補」）：
            # 記錄「這筆訊號是哪一版分析規則產生的」。純新增、可為 NULL、不回填——
            # 既有 973 筆訊號的版本資訊已無法回溯取得，強行填值等於製造假資料。
            # NULL 的語意是「此列產生時尚未有版本追蹤」，這個分界會寫進 ④組已知限制。
            # 值的來源是 prompt.rule_version()（SYSTEM_PROMPT 內容雜湊前 12 碼）。
            cur.execute("""
                ALTER TABLE signals
                ADD COLUMN IF NOT EXISTS rule_version TEXT
            """)
            # 2026-09-02 新增（來源：serenity-clone/remodel266_model_bakeoff_2026-08-27.md
            # 第 7 節第 1 件）：記錄「這句話到底是不是在猜未來」。
            # 值域見 prompt.CLAIM_TYPES（forward / notfwd / unclear）。
            # 純新增、可為 NULL、不回填——既有訊號沒有這個判定，強行填值等於製造假資料；
            # NULL 的語意是「此列產生時 schema 還沒有這一欄」。
            # 🔴 這一欄只記錄、不過濾：action 的填法、寄信與回測的母體都沒有因此改變
            #    （要不要拿它當過濾條件是丹尼爾的決定，不是這次改的範圍）。
            cur.execute("""
                ALTER TABLE signals
                ADD COLUMN IF NOT EXISTS claim_type TEXT
            """)
            # 2026-09-02 補建（schema 漂移修補，非新功能）：
            # 這兩欄 2026-08-29 就已經直接加在正式庫上（見 backups/ 當日之後的備份），
            # 但一直沒寫進 init_db()。正式庫因此看不出問題，全新建立的資料庫卻會炸——
            # list_signals()、performance._fill_entry_prices()、performance.calc_performance()
            # 都以 `invalid_reason IS NULL` 當「這筆訊號還算數」的判準，欄位不存在時
            # 直接 UndefinedColumn。restore_db.py 從備份 JSON 還原時也會帶著這兩個欄名
            # INSERT，缺欄一樣還原失敗。
            # 語意：invalid_reason NULL = 有效；非 NULL = 作廢原因（例：業配被誤判成訊號）。
            #       invalidated_at 是作廢時間，跟著 invalid_reason 一起填。
            # 純附加、可為 NULL、不回填；IF NOT EXISTS 對已有這兩欄的正式庫是 no-op。
            cur.execute("""
                ALTER TABLE signals
                ADD COLUMN IF NOT EXISTS invalid_reason TEXT
            """)
            cur.execute("""
                ALTER TABLE signals
                ADD COLUMN IF NOT EXISTS invalidated_at TIMESTAMPTZ
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

                raw_code = code
                code = resolve_code(name, code)
                if raw_code != code:
                    # 2026-08-24 新增：代號被校正過就留一行紀錄。校正本身是靜默的
                    # （見 stock_dict.resolve_code），沒有這行日誌就無從得知
                    # 「Gemini 這一版到底把幾個代號標錯」，也就無從判斷 prompt 改得有沒有效。
                    logging.info(
                        f"[代號校正] {episode_id} {name!r}：{raw_code!r} -> {code!r}"
                    )

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
                         primary_tag, secondary_tags, rule_version, claim_type)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (
                    episode_id, analysis_date,
                    s.get("stock_name"), code, action,
                    s.get("confidence_level"), s.get("reasoning"),
                    s.get("exact_quote"), s.get("raw_reason"),
                    s.get("primary_tag"),
                    json.dumps(s.get("secondary_tags", []), ensure_ascii=False),
                    _current_rule_version(),
                    _clean_claim_type(s.get("claim_type"), episode_id, code),
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
                    "SELECT * FROM signals WHERE episode_id=%s AND invalid_reason IS NULL ORDER BY created_at DESC",
                    (episode_id,)
                )
            else:
                cur.execute("SELECT * FROM signals WHERE invalid_reason IS NULL ORDER BY created_at DESC")
            return [dict(r) for r in cur.fetchall()]
