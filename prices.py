import math
import sys
from datetime import date, timedelta

import yfinance as yf

sys.stdout.reconfigure(encoding="utf-8")

BENCHMARK_TW = "0050.TW"
BENCHMARK_US = "SPY"


def benchmark_for(stock_code: str) -> str:
    return BENCHMARK_TW if (stock_code.endswith(".TW") or stock_code.endswith(".TWO")) else BENCHMARK_US


def _safe_float(val) -> float | None:
    try:
        v = float(val)
        return None if math.isnan(v) else round(v, 4)
    except (TypeError, ValueError):
        return None


def _fetch_history(ticker: str, start: str, end: str):
    return yf.Ticker(ticker).history(start=start, end=end, auto_adjust=True)


def get_close_on_or_before(ticker: str, target_date: str) -> float | None:
    """歷史收盤價：target_date 當天或之前最近交易日，結果永久 cache 於 PostgreSQL。"""
    from database import _conn, init_db
    init_db()
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT price FROM price_cache WHERE ticker=%s AND ref_date=%s",
                (ticker, target_date)
            )
            row = cur.fetchone()
    if row is not None:
        return row["price"]

    d     = date.fromisoformat(target_date)
    start = str(d - timedelta(days=10))
    end   = str(d + timedelta(days=1))
    hist  = _fetch_history(ticker, start, end)
    price = None
    if not hist.empty:
        hist = hist[hist.index.date <= d].dropna(subset=["Close"])
        if not hist.empty:
            price = _safe_float(hist["Close"].iloc[-1])

    if price is not None:
        from database import _conn as _c2
        with _c2() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO price_cache (ticker, ref_date, price, cache_date)
                       VALUES (%s,%s,%s,%s)
                       ON CONFLICT (ticker, ref_date) DO UPDATE SET price=EXCLUDED.price""",
                    (ticker, target_date, price, date.today().isoformat())
                )
    return price


def get_latest_close(ticker: str) -> float | None:
    """當日最新收盤價：以今日為 TTL key，同一天只抓一次 yfinance。"""
    from database import _conn, init_db
    init_db()
    today = date.today().isoformat()
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT price FROM price_cache WHERE ticker=%s AND ref_date='LATEST' AND cache_date=%s",
                (ticker, today)
            )
            row = cur.fetchone()
    if row is not None:
        return row["price"]

    hist  = yf.Ticker(ticker).history(period="5d", auto_adjust=True)
    price = None
    if not hist.empty:
        hist = hist.dropna(subset=["Close"])
        if not hist.empty:
            price = _safe_float(hist["Close"].iloc[-1])

    if price is not None:
        from database import _conn as _c2
        with _c2() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO price_cache (ticker, ref_date, price, cache_date)
                       VALUES (%s,'LATEST',%s,%s)
                       ON CONFLICT (ticker, ref_date) DO UPDATE
                           SET price=EXCLUDED.price, cache_date=EXCLUDED.cache_date""",
                    (ticker, price, today)
                )
    return price


def batch_get_close_on_or_before(
    requests: list[tuple[str, str]]
) -> dict[tuple[str, str], float | None]:
    """批次查詢多個 (ticker, target_date) 歷史收盤價；命中 cache 時單一 SQL 搞定。"""
    if not requests:
        return {}

    from database import _conn, init_db
    init_db()

    result: dict[tuple[str, str], float | None] = {}
    uncached: list[tuple[str, str]] = []

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT ticker, ref_date, price FROM price_cache WHERE (ticker, ref_date) IN %s",
                (tuple(requests),)
            )
            cached = {(r["ticker"], r["ref_date"]): r["price"] for r in cur.fetchall()}

    for key in requests:
        if key in cached:
            result[key] = cached[key]
        else:
            uncached.append(key)

    for ticker, target_date in uncached:
        result[(ticker, target_date)] = get_close_on_or_before(ticker, target_date)

    return result


def batch_get_latest_close(tickers: list[str]) -> dict[str, float | None]:
    """批次查詢多個 ticker 的最新收盤價；命中 cache 時單一 SQL 搞定。"""
    if not tickers:
        return {}

    from database import _conn, init_db
    init_db()
    today = date.today().isoformat()

    result: dict[str, float | None] = {}
    uncached: list[str] = []

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT ticker, price FROM price_cache
                   WHERE ticker IN %s AND ref_date='LATEST' AND cache_date=%s""",
                (tuple(tickers), today)
            )
            cached = {r["ticker"]: r["price"] for r in cur.fetchall()}

    for ticker in tickers:
        if ticker in cached:
            result[ticker] = cached[ticker]
        else:
            uncached.append(ticker)

    for ticker in uncached:
        result[ticker] = get_latest_close(ticker)

    return result
