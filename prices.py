import math
import sys
from datetime import date, timedelta
from functools import lru_cache
import yfinance as yf

sys.stdout.reconfigure(encoding="utf-8")

BENCHMARK_TW = "0050.TW"
BENCHMARK_US = "SPY"


def benchmark_for(stock_code: str) -> str:
    return BENCHMARK_TW if stock_code.endswith(".TW") else BENCHMARK_US


def _fetch_history(ticker: str, start: str, end: str):
    return yf.Ticker(ticker).history(start=start, end=end, auto_adjust=True)


def _safe_float(val) -> float | None:
    try:
        v = float(val)
        return None if math.isnan(v) else round(v, 4)
    except (TypeError, ValueError):
        return None


@lru_cache(maxsize=512)
def get_close_on_or_before(ticker: str, target_date: str) -> float | None:
    """回傳 target_date 當天或之前最近一個有效交易日的收盤價。"""
    d     = date.fromisoformat(target_date)
    start = str(d - timedelta(days=10))
    end   = str(d + timedelta(days=1))
    hist  = _fetch_history(ticker, start, end)
    if hist.empty:
        return None
    hist = hist[hist.index.date <= d].dropna(subset=["Close"])
    if hist.empty:
        return None
    return _safe_float(hist["Close"].iloc[-1])


@lru_cache(maxsize=256)
def get_latest_close(ticker: str) -> float | None:
    """回傳最新一個有效交易日的收盤價。"""
    hist = yf.Ticker(ticker).history(period="5d", auto_adjust=True)
    if hist.empty:
        return None
    hist = hist.dropna(subset=["Close"])
    if hist.empty:
        return None
    return _safe_float(hist["Close"].iloc[-1])
