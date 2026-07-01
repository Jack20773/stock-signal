"""
計算每筆訊號的即時績效，並與大盤比較勝率。
批次查詢 price_cache 以減少 DB round-trips。
"""
import sys
import json
import urllib.request
from datetime import date
from prices import (
    get_close_on_or_before, get_latest_close,
    batch_get_close_on_or_before, batch_get_latest_close,
    benchmark_for,
)
from database import init_db, save_perf_results, _conn

sys.stdout.reconfigure(encoding="utf-8")

_EPISODES_URL  = "https://whatmkreallysaid.com/episodes.json"
_episodes_cache: dict[str, str] = {}


def _load_episodes() -> dict[str, str]:
    global _episodes_cache
    if _episodes_cache:
        return _episodes_cache
    try:
        req  = urllib.request.Request(_EPISODES_URL, headers={"User-Agent": "Mozilla/5.0"})
        data = json.loads(urllib.request.urlopen(req, timeout=15).read().decode("utf-8"))
        _episodes_cache = {
            f"EP{e['number']}": e["date"]
            for e in data
            if e.get("date") and e.get("number")
        }
    except Exception as ex:
        print(f"[warn] episodes.json 載入失敗：{ex}")
    return _episodes_cache


def _episode_date(episode_id: str, fallback: str) -> str:
    return _load_episodes().get(episode_id, fallback)


def _fill_entry_prices():
    """對 entry_price 為 NULL 的訊號補抓進場價（用集數播出日，非分析日）。"""
    import psycopg2.extras
    init_db()
    _load_episodes()

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, episode_id, stock_code, analysis_date FROM signals
                   WHERE action != '0' AND (entry_price IS NULL OR entry_price = 0)"""
            )
            rows = [dict(r) for r in cur.fetchall()]

    requests = []
    meta = []
    for r in rows:
        code    = r["stock_code"]
        ep_id   = r["episode_id"] or ""
        entry_d = _episode_date(ep_id, r["analysis_date"])
        if not code or code == "Unknown" or not entry_d:
            continue
        requests.append((code, entry_d))
        meta.append((r["id"], code, entry_d, benchmark_for(code)))

    prices = batch_get_close_on_or_before(requests)

    updates = []
    for sig_id, code, entry_d, bm in meta:
        price = prices.get((code, entry_d))
        if price:
            updates.append((price, bm, entry_d, sig_id))
            print(f"  {code} @ {entry_d} = {price}")

    if updates:
        with _conn() as conn:
            with conn.cursor() as cur:
                psycopg2.extras.execute_batch(cur, """
                    UPDATE signals
                    SET entry_price=%s, benchmark_ticker=%s, entry_date=%s
                    WHERE id=%s
                """, updates)
    return len(updates)


def calc_performance() -> list[dict]:
    """
    回傳所有 action != 0 的訊號，附上即時績效欄位：
      stock_return_pct, benchmark_return_pct, beat_benchmark, current_price, days_held
    """
    init_db()
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM signals WHERE action != '0' ORDER BY entry_date ASC"
            )
            rows = [dict(r) for r in cur.fetchall()]

    # 收集所有需要的價格 key，一次批次抓完
    hist_keys: set[tuple[str, str]] = set()
    live_tickers: set[str] = set()

    for r in rows:
        code    = r.get("stock_code", "")
        entry_p = r.get("entry_price")
        entry_d = r.get("entry_date") or r.get("analysis_date")
        if not code or code == "Unknown" or not entry_p or not entry_d:
            continue
        bm = r.get("benchmark_ticker") or benchmark_for(code)
        hist_keys.add((code, entry_d))
        hist_keys.add((bm, entry_d))
        live_tickers.add(code)
        live_tickers.add(bm)

    hist_cache   = batch_get_close_on_or_before(list(hist_keys))
    latest_cache = batch_get_latest_close(list(live_tickers))

    results = []

    for r in rows:
        code    = r.get("stock_code", "")
        entry_p = r.get("entry_price")
        entry_d = r.get("entry_date") or r.get("analysis_date")
        bm      = r.get("benchmark_ticker") or benchmark_for(code)

        if not entry_p or not entry_d or not code or code == "Unknown":
            r.update(dict.fromkeys(
                ["stock_return_pct", "benchmark_return_pct", "beat_benchmark", "current_price", "days_held"]
            ))
            results.append(r)
            continue

        live_entry = hist_cache.get((code, entry_d)) or entry_p
        current_p  = latest_cache.get(code)

        if current_p and live_entry:
            stock_pct = round((current_p - live_entry) / live_entry * 100, 2)
        else:
            stock_pct = current_p = None

        bm_entry = hist_cache.get((bm, entry_d))
        bm_now   = latest_cache.get(bm)
        if bm_entry and bm_now and bm_entry != 0:
            bm_pct = round((bm_now - bm_entry) / bm_entry * 100, 2)
        else:
            bm_pct = None

        beat = (stock_pct > bm_pct) if (stock_pct is not None and bm_pct is not None) else None

        try:
            days = (date.today() - date.fromisoformat(entry_d)).days
        except Exception:
            days = None

        r["stock_return_pct"]     = stock_pct
        r["benchmark_return_pct"] = bm_pct
        r["beat_benchmark"]       = beat
        r["current_price"]        = current_p
        r["days_held"]            = days
        r["live_entry_price"]     = live_entry
        results.append(r)

    save_perf_results(results)
    return results


def win_rate(results: list[dict]) -> dict:
    decided = [r for r in results if r["beat_benchmark"] is not None]
    wins    = sum(1 for r in decided if r["beat_benchmark"])
    return {
        "total":    len(results),
        "decided":  len(decided),
        "wins":     wins,
        "losses":   len(decided) - wins,
        "win_rate": round(wins / len(decided) * 100, 1) if decided else 0.0,
    }
