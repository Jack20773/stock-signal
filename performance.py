"""
計算每筆訊號的即時績效，並與大盤比較勝率。
"""
import sys
import json
import sqlite3
import urllib.request
from datetime import date
from prices import get_close_on_or_before, get_latest_close, benchmark_for
from database import DB_PATH, init_db

sys.stdout.reconfigure(encoding="utf-8")

_EPISODES_URL  = "https://whatmkreallysaid.com/episodes.json"
_episodes_cache: dict[str, str] = {}   # ep_number_str → date (YYYY-MM-DD)


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
    """用集數 ID（如 EP672）查播出日，抓不到就回傳 fallback。"""
    return _load_episodes().get(episode_id, fallback)


def _fill_entry_prices():
    """對 entry_price 為 NULL 的訊號補抓進場價（用集數播出日，非分析日）。"""
    init_db()
    _load_episodes()  # pre-warm cache
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, episode_id, stock_code, analysis_date FROM signals "
            "WHERE action != '0' AND (entry_price IS NULL OR entry_price = 0)"
        ).fetchall()

    updates = []
    for r in rows:
        code  = r["stock_code"]
        ep_id = r["episode_id"] or ""
        # 優先用播出日，退而求其次用分析日
        entry_d = _episode_date(ep_id, r["analysis_date"])
        if not code or code == "Unknown" or not entry_d:
            continue
        price = get_close_on_or_before(code, entry_d)
        bm    = benchmark_for(code)
        if price:
            updates.append((price, bm, entry_d, r["id"]))
            print(f"  {code} @ {entry_d} = {price}")

    if updates:
        with sqlite3.connect(DB_PATH) as conn:
            conn.executemany(
                "UPDATE signals SET entry_price=?, benchmark_ticker=?, entry_date=? WHERE id=?",
                updates
            )
    return len(updates)


def calc_performance() -> list[dict]:
    """
    回傳所有 action != 0 的訊號，附上即時績效欄位：
      stock_return_pct, benchmark_return_pct, beat_benchmark, current_price, days_held
    """
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM signals WHERE action != '0' ORDER BY entry_date ASC"
        ).fetchall()

    results = []

    for r in rows:
        row = dict(r)
        code     = row.get("stock_code", "")
        action   = row.get("action", "0")
        entry_p  = row.get("entry_price")
        entry_d  = row.get("entry_date") or row.get("analysis_date")
        bm       = row.get("benchmark_ticker") or benchmark_for(code)

        if not entry_p or not entry_d or not code or code == "Unknown":
            row["stock_return_pct"]     = None
            row["benchmark_return_pct"] = None
            row["beat_benchmark"]       = None
            row["current_price"]        = None
            row["days_held"]            = None
            results.append(row)
            continue

        # 個股報酬：重抓 entry 價確保與 current 在同一 auto_adjust 基礎上
        # 統一用買進視角：不論原始訊號多空，都比較「買進後是否贏大盤」
        live_entry = get_close_on_or_before(code, entry_d) or entry_p
        current_p = get_latest_close(code)
        if current_p and live_entry:
            raw_pct = (current_p - live_entry) / live_entry * 100
            stock_pct = round(raw_pct, 2)
        else:
            stock_pct = current_p = None

        # 大盤報酬（同期，方向固定為多）
        bm_entry = get_close_on_or_before(bm, entry_d)
        bm_now   = get_latest_close(bm)
        if bm_entry and bm_now and bm_entry != 0:
            bm_pct = round((bm_now - bm_entry) / bm_entry * 100, 2)
        else:
            bm_pct = None

        # 勝負
        if stock_pct is not None and bm_pct is not None:
            beat = stock_pct > bm_pct
        else:
            beat = None

        # 持倉天數
        try:
            d0 = date.fromisoformat(entry_d)
            days = (date.today() - d0).days
        except Exception:
            days = None

        row["stock_return_pct"]     = stock_pct
        row["benchmark_return_pct"] = bm_pct
        row["beat_benchmark"]       = beat
        row["current_price"]        = current_p
        row["days_held"]            = days
        row["live_entry_price"]     = live_entry  # 計算用的調整後進場價（顯示用）
        results.append(row)

    return results


def win_rate(results: list[dict]) -> dict:
    decided = [r for r in results if r["beat_benchmark"] is not None]
    wins    = [r for r in decided if r["beat_benchmark"]]
    return {
        "total":    len(results),
        "decided":  len(decided),
        "wins":     len(wins),
        "losses":   len(decided) - len(wins),
        "win_rate": round(len(wins) / len(decided) * 100, 1) if decided else 0.0,
    }
