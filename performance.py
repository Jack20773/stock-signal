"""
計算每筆訊號的即時績效，並與大盤比較勝率。
批次查詢 price_cache 以減少 DB round-trips。
"""
import sys
import json
import logging
import urllib.request
from datetime import date
from pathlib import Path
from prices import (
    get_close_on_or_before, get_latest_close,
    batch_get_close_on_or_before, batch_get_latest_close,
    benchmark_for,
)
from database import init_db, save_perf_results, _conn

sys.stdout.reconfigure(encoding="utf-8")

_EPISODES_URL  = "https://whatmkreallysaid.com/episodes.json"
_episodes_cache: dict[str, str] = {}
# 「已經試過載入」跟「快取有內容」是兩件事——原本只用 _episodes_cache 是否為空
# dict 判斷「要不要載入」，本地檔跟網路都失敗時 _episodes_cache 會維持空 dict，
# 之後每呼叫一次 _episode_date()（在 _fill_entry_prices() 的迴圈裡對每一筆訊號都會
# 呼叫）就會重新試一次本地檔+網路，網路連不上時等於每筆訊號都多等一次 15 秒逾時。
# 2026-08-01 索羅門診斷 + Codex 審查一起發現，純本地邏輯修正，不改變成功時的行為。
_episodes_load_attempted = False


def _load_episodes() -> dict[str, str]:
    global _episodes_cache, _episodes_load_attempted
    if _episodes_cache or _episodes_load_attempted:
        return _episodes_cache
    _episodes_load_attempted = True

    def _parse(data):
        return {f"EP{e['number']}": e["date"] for e in data if e.get("date") and e.get("number")}

    # 優先讀本地快取（由 download_transcripts.py 在同一次執行中寫入）
    local = Path(__file__).parent / "episodes.json"
    if local.exists():
        try:
            _episodes_cache = _parse(json.loads(local.read_text(encoding="utf-8")))
            return _episodes_cache
        except Exception:
            pass

    # 本地沒有才走網路
    try:
        req  = urllib.request.Request(_EPISODES_URL, headers={"User-Agent": "Mozilla/5.0"})
        data = json.loads(urllib.request.urlopen(req, timeout=15).read().decode("utf-8"))
        _episodes_cache = _parse(data)
    except Exception as ex:
        print(f"[warn] episodes.json 載入失敗，本次執行不再重試：{ex}")
    return _episodes_cache


def _episode_date(episode_id: str, fallback: str | None = None) -> str | None:
    """集數上架日（episodes.json）。2026-10-20 起：episodes.json 還沒有這一集就回 None
    （fallback 參數保留只為相容舊呼叫，不再使用）——以前退回 analysis_date，
    EP694–696 因此被寫成補分析那天 09-15，之後又沒人回頭改。留空等下一輪補才對。"""
    return _load_episodes().get(episode_id)


# 已寫入的 entry_date 跟 episodes.json 不一致時，一輪最多自動重寫幾筆；超過就只報警不動，
# 防 episodes.json 本身又壞掉時把整張表改歪（2026-10-17 那次是 93 筆，那種量要人看過再修）。
_RESYNC_MAX = 20


def _swap_tw_suffix(code: str) -> str | None:
    """Gemini 常分不清台股上市(.TW)/上櫃(.TWO)，回傳另一種尾綴供重試。"""
    if code.endswith(".TWO"):
        return code[:-4] + ".TW"
    if code.endswith(".TW"):
        return code[:-3] + ".TWO"
    return None


def _plan_entry_fills(rows: list[dict], air: dict[str, str], resync_max: int = _RESYNC_MAX):
    """決定哪些訊號要（重）抓進場價。回傳 (meta, skipped_no_air, mismatched, alarm)。
    - 進場價空的：用 episodes.json 上架日補；episodes.json 沒這集 → 跳過（留空等下一輪）。
    - 進場價有、但 entry_date 跟上架日不一致：重寫（日期＋價格）；
      不一致超過 resync_max 筆 → 一筆都不重寫，alarm=True 交給人看。"""
    meta, skipped, mismatched = [], [], []
    for r in rows:
        code = r["stock_code"]
        if not code or code == "Unknown":
            continue
        d = air.get(r["episode_id"] or "")
        has_price = bool(r.get("entry_price"))
        if not d:
            if not has_price:
                skipped.append(r["id"])
            continue
        if not has_price:
            meta.append({"id": r["id"], "code": code, "date": d, "resync": False})
        elif str(r.get("entry_date") or "")[:10] != d:
            mismatched.append({"id": r["id"], "code": code, "date": d, "resync": True,
                               "old_date": r.get("entry_date")})
    alarm = len(mismatched) > resync_max
    if not alarm:
        meta.extend(mismatched)
    return meta, skipped, mismatched, alarm


def _fill_entry_prices():
    """補抓進場價（用集數播出日，非分析日）；並把 entry_date 跟 episodes.json 不一致的重寫。"""
    import psycopg2.extras
    init_db()
    air = _load_episodes()

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, episode_id, stock_code, analysis_date, entry_date, entry_price FROM signals
                   WHERE action != '0' AND invalid_reason IS NULL"""
            )
            rows = [dict(r) for r in cur.fetchall()]

    meta, skipped, mismatched, alarm = _plan_entry_fills(rows, air)
    if skipped:
        print(f"[info] {len(skipped)} 筆訊號的集數 episodes.json 還沒有上架日，先不補進場價（下一輪再補）：id={skipped[:20]}")
    if mismatched:
        ids = [m["id"] for m in mismatched]
        if alarm:
            print(f"[警報] {len(mismatched)} 筆 entry_date 跟 episodes.json 上架日不一致，超過自動重寫上限 "
                  f"{_RESYNC_MAX}，這次不動，請人工確認 episodes.json 是否正確：id={ids[:30]}")
        else:
            print(f"[修正] {len(mismatched)} 筆 entry_date 跟 episodes.json 上架日不一致，重寫日期與進場價：id={ids}")

    requests = [(m["code"], m["date"]) for m in meta]
    # meta 保留一筆對一筆（後面要用各自的 id 寫回），但送進批次查價的 requests
    # 去重——同一檔股票同一個進場日期，可能被好幾筆訊號同時引用（例如多次提到
    # 同一檔且剛好同一集），去重前會對同一個 key 重複查快取/重複打 yfinance。
    # 2026-08-01 索羅門診斷 + Codex 審查一起發現，純本地邏輯修正，dict.fromkeys
    # 保留原本出現順序，回傳值仍是 dict 查表，去不去重不影響最終結果正確性。
    requests = list(dict.fromkeys(requests))

    prices = batch_get_close_on_or_before(requests)

    # 查不到價格時，自動改用另一種台股上市/上櫃尾綴重試
    retry_requests = []
    for m in meta:
        if prices.get((m["code"], m["date"])) is None:
            alt = _swap_tw_suffix(m["code"])
            if alt:
                retry_requests.append((alt, m["date"]))
    retry_requests = list(dict.fromkeys(retry_requests))
    if retry_requests:
        alt_prices = batch_get_close_on_or_before(retry_requests)
        for m in meta:
            if prices.get((m["code"], m["date"])) is None:
                alt = _swap_tw_suffix(m["code"])
                if alt and alt_prices.get((alt, m["date"])):
                    m["code"] = alt  # 修正為實際有效代號
                    prices[(alt, m["date"])] = alt_prices[(alt, m["date"])]

    updates = []
    for m in meta:
        price = prices.get((m["code"], m["date"]))
        if not price and m.get("resync"):
            print(f"[警報] id={m['id']} {m['code']} 上架日 {m['date']} 抓不到價，entry_date 維持錯的 {m.get('old_date')}，請人工處理")
        if price:
            updates.append((price, benchmark_for(m["code"]), m["date"], m["code"], m["id"]))
            print(f"  {m['code']} @ {m['date']} = {price}")

    if updates:
        with _conn() as conn:
            with conn.cursor() as cur:
                psycopg2.extras.execute_batch(cur, """
                    UPDATE signals
                    SET entry_price=%s, benchmark_ticker=%s, entry_date=%s, stock_code=%s
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
                "SELECT * FROM signals WHERE action != '0' AND invalid_reason IS NULL ORDER BY entry_date ASC"
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
    changed = []  # 2026-08-02 索羅門新增（任務第3項）：只有真的變動的列才送進 UPDATE

    for r in rows:
        code    = r.get("stock_code", "")
        entry_p = r.get("entry_price")
        entry_d = r.get("entry_date") or r.get("analysis_date")
        bm      = r.get("benchmark_ticker") or benchmark_for(code)

        # 寫入前先記下這筆訊號目前存的值（SELECT * 已經帶出來了），跟這輪重新算出
        # 的值比較，只有真的不同才放進 save_perf_results() 的 UPDATE 清單——原本
        # 不論值變不變全部送進 execute_batch，等於每次全量跑一次 UPDATE 全部訊號。
        # beat_benchmark 存的是 INTEGER(1/0/NULL)，這裡先正規化成同一種型別再比較。
        # 2026-08-02 完工前 Codex 覆核指出：DB 裡 stock_return_pct/benchmark_return_pct
        # 是 PostgreSQL REAL（單精度 float4），讀回 Python 後可能是 5.170000076...
        # 這種精度漂移值，跟這輪新算出、用 round(x,2) 產生的雙精度 float 直接比較
        # 幾乎必然「看起來不同」，讓這次優化在浮點欄位上大打折扣（正確性不受影響，
        # 只是變動判斷過於保守）——比較前先把舊值也 round(2) 校正到跟新值同一個
        # 精度基準再比。
        old_snapshot = (
            round(r["stock_return_pct"], 2) if r.get("stock_return_pct") is not None else None,
            round(r["benchmark_return_pct"], 2) if r.get("benchmark_return_pct") is not None else None,
            r.get("beat_benchmark"), r.get("days_held"),
        )

        if not entry_p or not entry_d or not code or code == "Unknown":
            r.update(dict.fromkeys(
                ["stock_return_pct", "benchmark_return_pct", "beat_benchmark", "current_price", "days_held"]
            ))
            results.append(r)
            if old_snapshot != (None, None, None, None):
                changed.append(r)
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

        if stock_pct is not None and bm_pct is not None:
            action = r.get("action", "0")
            if action == "+1":
                beat = stock_pct > bm_pct
            elif action == "-1":
                beat = stock_pct < bm_pct
            else:
                beat = None
        else:
            beat = None

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

        # 保險絲：短持倉卻出現極端報酬，多半是分割/錯價等資料問題（2026-07-12 CRWD -73% 事件），
        # 只告警不改顯示，避免誤殺真的暴漲暴跌
        if stock_pct is not None and days is not None and days <= 45 and abs(stock_pct) >= 60:
            logging.warning(
                f"⚠ 報酬異常待驗證：{r.get('episode_id')} {code} 持倉 {days} 天報酬 {stock_pct}%"
                f"（進場 {live_entry} → 現價 {current_p}），請檢查是否分割/錯價"
            )
        results.append(r)

        beat_repr = 1 if beat is True else (0 if beat is False else None)
        new_snapshot = (stock_pct, bm_pct, beat_repr, days)
        if new_snapshot != old_snapshot:
            changed.append(r)

    save_perf_results(changed)
    logging.info(
        f"績效比對：{len(rows)} 筆訊號，{len(changed)} 筆數值有變動送出 UPDATE"
        f"（{len(rows) - len(changed)} 筆跟上次相同，跳過寫入）"
    )
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
