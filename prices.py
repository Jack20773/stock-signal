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


# ---------------------------------------------------------------------------
# 2026-08-02 索羅門重構（任務清單第1+13項）：
# 原本 get_close_on_or_before()/get_latest_close() 各自重複「查快取→取未命中→
# 寫回」的邏輯，且 batch_get_* 遇到 cache miss 時是逐筆呼叫這兩個單筆版本，
# 等於批次查價「退化」成逐筆 yfinance 呼叫、逐筆開一次 DB 交易寫回。
# 現在抽出 _read_price_cache()/_write_price_cache() 共用函式，且 batch_get_*
# 對未命中的部分改成一次 yf.download() 抓完所有 ticker，最後一次
# execute_batch bulk upsert，不再逐筆呼叫。
# ---------------------------------------------------------------------------

def _read_price_cache(keys: list[tuple[str, str]]) -> dict[tuple[str, str], float | None]:
    """共用：一次查快取命中的部分。keys 是 (ticker, ref_date) tuple 清單（ref_date 可以是
    真實日期字串，也可以是代表「當日最新價」的特殊值 'LATEST'）。"""
    if not keys:
        return {}
    from database import _conn
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT ticker, ref_date, price FROM price_cache WHERE (ticker, ref_date) IN %s",
                (tuple(keys),)
            )
            return {(r["ticker"], r["ref_date"]): r["price"] for r in cur.fetchall()}


def _read_latest_cache(tickers: list[str], today: str) -> dict[str, float | None]:
    """LATEST 快取要求 cache_date=今天才算數（跟舊版行為一致，避免用到過期的 LATEST 值），
    這點跟歷史收盤價快取（一旦寫入永遠有效）不同，所以另外開一個函式而不是共用
    _read_price_cache（那個不篩 cache_date）。"""
    if not tickers:
        return {}
    from database import _conn
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT ticker, price FROM price_cache
                   WHERE ticker IN %s AND ref_date='LATEST' AND cache_date=%s""",
                (tuple(tickers), today)
            )
            return {r["ticker"]: r["price"] for r in cur.fetchall()}


def _write_price_cache(rows: list[tuple[str, str, float | None, str]]) -> None:
    """共用：一次 bulk upsert 進 price_cache。rows 是 (ticker, ref_date, price, cache_date) tuple 清單。"""
    if not rows:
        return
    import psycopg2.extras
    from database import _conn
    with _conn() as conn:
        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(cur, """
                INSERT INTO price_cache (ticker, ref_date, price, cache_date)
                VALUES (%s,%s,%s,%s)
                ON CONFLICT (ticker, ref_date) DO UPDATE
                    SET price=EXCLUDED.price, cache_date=EXCLUDED.cache_date
            """, rows)


def _download_multi(tickers: list[str], **kwargs):
    """一次呼叫 yfinance 批次下載多檔股票的價格（單一 HTTP 請求，取代逐檔呼叫）。
    回傳 {ticker: DataFrame}，遮蔽 yfinance 對單檔/多檔回傳形狀不一致的問題
    （單檔有時是單層欄位，多檔一定是 MultiIndex）。"""
    tickers = sorted(set(tickers))
    raw = yf.download(
        tickers=tickers, auto_adjust=True, group_by="ticker",
        progress=False, threads=True, **kwargs,
    )
    out = {}
    is_multi = hasattr(raw.columns, "nlevels") and raw.columns.nlevels > 1
    for t in tickers:
        if len(tickers) == 1 and not is_multi:
            out[t] = raw
        else:
            try:
                out[t] = raw[t]
            except KeyError:
                out[t] = None
    return out


def get_close_on_or_before(ticker: str, target_date: str) -> float | None:
    """歷史收盤價：target_date 當天或之前最近交易日，結果永久 cache 於 PostgreSQL。"""
    from database import init_db
    init_db()
    cached = _read_price_cache([(ticker, target_date)])
    if (ticker, target_date) in cached:
        return cached[(ticker, target_date)]

    d     = date.fromisoformat(target_date)
    start = str(d - timedelta(days=10))
    end   = str(d + timedelta(days=1))
    hist  = _fetch_history(ticker, start, end)
    price = None
    if not hist.empty:
        hist = hist[hist.index.date <= d].dropna(subset=["Close"])
        if not hist.empty:
            price = _safe_float(hist["Close"].iloc[-1])

    # 無論查到價格與否都寫入 cache（含「確認查無資料」的 NULL），
    # 否則下市/查無資料的股票會在每次執行時被重新打一次 yfinance，永遠學不會。
    # 如果之後這檔股票真的補上歷史資料，手動刪掉 price_cache 對應那筆即可強制重查。
    _write_price_cache([(ticker, target_date, price, date.today().isoformat())])
    return price


def get_latest_close(ticker: str) -> float | None:
    """當日最新收盤價：以今日為 TTL key，同一天只抓一次 yfinance。"""
    from database import init_db
    init_db()
    today = date.today().isoformat()
    cached = _read_latest_cache([ticker], today)
    if ticker in cached:
        return cached[ticker]

    hist  = yf.Ticker(ticker).history(period="5d", auto_adjust=True)
    price = None
    if not hist.empty:
        hist = hist.dropna(subset=["Close"])
        if not hist.empty:
            price = _safe_float(hist["Close"].iloc[-1])

    if price is not None:
        _write_price_cache([(ticker, "LATEST", price, today)])
    return price


def batch_get_close_on_or_before(
    requests: list[tuple[str, str]]
) -> dict[tuple[str, str], float | None]:
    """批次查詢多個 (ticker, target_date) 歷史收盤價；命中 cache 時單一 SQL 搞定，
    未命中的部分改成一次 yf.download() 抓完所有需要的 ticker（涵蓋所有請求日期
    的最寬區間），最後一次 execute_batch bulk upsert 回 price_cache——不再逐筆
    呼叫 yfinance、不再逐筆開 DB 交易。"""
    if not requests:
        return {}

    from database import init_db
    init_db()

    result = _read_price_cache(requests)
    uncached = [key for key in requests if key not in result]

    if not uncached:
        return result

    tickers   = [t for t, _ in uncached]
    all_dates = [date.fromisoformat(d) for _, d in uncached]
    start = str(min(all_dates) - timedelta(days=10))
    end   = str(max(all_dates) + timedelta(days=1))

    hist_by_ticker = _download_multi(tickers, start=start, end=end)

    today = date.today().isoformat()
    upsert_rows = []
    for ticker, target_date in uncached:
        d = date.fromisoformat(target_date)
        price = None
        sub = hist_by_ticker.get(ticker)
        if sub is not None and not sub.empty:
            sub2 = sub.dropna(subset=["Close"])
            sub2 = sub2[sub2.index.date <= d]
            if not sub2.empty:
                price = _safe_float(sub2["Close"].iloc[-1])
        result[(ticker, target_date)] = price
        upsert_rows.append((ticker, target_date, price, today))

    _write_price_cache(upsert_rows)
    return result


def batch_get_latest_close(tickers: list[str]) -> dict[str, float | None]:
    """批次查詢多個 ticker 的最新收盤價；命中 cache 時單一 SQL 搞定，未命中的部分
    改成一次 yf.download() 抓完，最後一次 execute_batch bulk upsert。"""
    if not tickers:
        return {}

    from database import init_db
    init_db()
    today = date.today().isoformat()

    cached = _read_latest_cache(tickers, today)
    result: dict[str, float | None] = dict(cached)
    uncached = [t for t in tickers if t not in cached]

    if not uncached:
        return result

    hist_by_ticker = _download_multi(uncached, period="5d")

    upsert_rows = []
    for ticker in uncached:
        price = None
        sub = hist_by_ticker.get(ticker)
        if sub is not None and not sub.empty:
            sub2 = sub.dropna(subset=["Close"])
            if not sub2.empty:
                price = _safe_float(sub2["Close"].iloc[-1])
        result[ticker] = price
        if price is not None:
            upsert_rows.append((ticker, "LATEST", price, today))

    _write_price_cache(upsert_rows)
    return result
