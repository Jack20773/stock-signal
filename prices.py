import math
import sys
import sqlite3
from datetime import date, timedelta
import yfinance as yf
from database import DB_PATH, init_db

sys.stdout.reconfigure(encoding="utf-8")

BENCHMARK_TW = "0050.TW"
BENCHMARK_US = "SPY"

_cache_ready = False


def benchmark_for(stock_code: str) -> str:
    return BENCHMARK_TW if (stock_code.endswith(".TW") or stock_code.endswith(".TWO")) else BENCHMARK_US


def _safe_float(val) -> float | None:
    try:
        v = float(val)
        return None if math.isnan(v) else round(v, 4)
    except (TypeError, ValueError):
        return None


def _ensure_cache_table():
    global _cache_ready
    if _cache_ready:
        return
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS price_cache (
                ticker     TEXT NOT NULL,
                ref_date   TEXT NOT NULL,
                price      REAL,
                cache_date TEXT NOT NULL,
                PRIMARY KEY (ticker, ref_date)
            )
        """)
    _cache_ready = True


def _fetch_history(ticker: str, start: str, end: str):
    return yf.Ticker(ticker).history(start=start, end=end, auto_adjust=True)


def get_close_on_or_before(ticker: str, target_date: str) -> float | None:
    """歷史收盤價：target_date 當天或之前最近交易日，結果永久 cache 於 SQLite。"""
    _ensure_cache_table()
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT price FROM price_cache WHERE ticker=? AND ref_date=?",
            (ticker, target_date)
        ).fetchone()
    if row is not None:
        return row[0]

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
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO price_cache (ticker, ref_date, price, cache_date) VALUES (?,?,?,?)",
                (ticker, target_date, price, date.today().isoformat())
            )
    return price


def get_latest_close(ticker: str) -> float | None:
    """當日最新收盤價：以今日為 key，同一天只抓一次 yfinance。"""
    _ensure_cache_table()
    today = date.today().isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT price FROM price_cache WHERE ticker=? AND ref_date='LATEST' AND cache_date=?",
            (ticker, today)
        ).fetchone()
    if row is not None:
        return row[0]

    hist  = yf.Ticker(ticker).history(period="5d", auto_adjust=True)
    price = None
    if not hist.empty:
        hist = hist.dropna(subset=["Close"])
        if not hist.empty:
            price = _safe_float(hist["Close"].iloc[-1])

    if price is not None:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO price_cache (ticker, ref_date, price, cache_date) VALUES (?,'LATEST',?,?)",
                (ticker, price, today)
            )
    return price
