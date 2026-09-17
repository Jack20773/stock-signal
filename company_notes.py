"""
「按公司病歷卡」資料組裝（2026-09-17 新增，任務檔 STOCKSIGNAL_TASK_2026-09-17_attention_company_notes.md）。

丹尼爾 2026-09-17 21:05 裁決：「我覺得按照公司是對的 會比較有脈絡，我想要將這個加在熱度那一頁」。
demo：100_Todo/drafts/daniel-demos/gooaye_v2_by_company.html（版型 B）。

這支只做三件事，**全部唯讀**（不寫 signals、不寫任何檔）：
  1. 對上榜的每一檔標的，從 signals 表撈最近 N 集的提及（欄位點名，不 SELECT *）。
  2. 補上那一集的真實上架日、集名（episodes.json → 逐字稿檔名 → signals.entry_date 依序 fallback）。
  3. 用 prices 的**批次**函式抓「提到當天收盤」與「最新收盤」（走 price_cache，不逐筆打 yfinance）。

summary / oneliner / context / substantive / quote_long 這幾欄的**內容**是由
  (a) 2026-09-17 一次性回填（Claude 子分身讀逐字稿寫的，notes_source='claude-backfill'）
  (b) 之後每集分析時 LLM 順便一起吐（prompt.py Rule 9，notes_source=config.LLM_PROVIDER）
寫進去的；這支只負責讀出來。欄位是 NULL 就是 NULL，頁面端（report_html）顯示
「這集只有一句原話」，**不在這裡編一句頂上去**。

股價語意（跟 demo B 不一樣，刻意的）：
  demo B 用「當天未開盤就取之後第一個交易日」；本專案既有的 price_cache 與主報告
  進場價都是 `on_or_before` 語意（當天或之前最近一個交易日），沿用同一套才不會
  同一檔股票在兩頁出現兩種「當天價」。假日／週末時在 px_note 註明。
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date
from pathlib import Path

import attention

_HERE = Path(__file__).parent
_TRANSCRIPTS_DIR = _HERE / "transcripts"
_EPISODES_PATH = _HERE / "episodes.json"

HISTORY_PER_CODE = 6

_WEEKDAY_ZH = "一二三四五六日"


def _weekday_zh(iso: str) -> str:
    try:
        return _WEEKDAY_ZH[date.fromisoformat(iso).weekday()]
    except (TypeError, ValueError):
        return ""


# ── 集名／上架日 ────────────────────────────────────────────────────────────
_title_cache: dict[int, str] | None = None


def _episode_titles() -> dict[int, str]:
    """集號 → 集名。先讀 episodes.json（正式來源），沒有的集再用逐字稿檔名
    `EP695_原來印這麼快.md` 補（本機 episodes.json 常比 transcripts/ 慢幾集）。"""
    global _title_cache
    if _title_cache is not None:
        return _title_cache
    titles: dict[int, str] = {}
    if _TRANSCRIPTS_DIR.is_dir():
        for p in _TRANSCRIPTS_DIR.glob("EP*.md"):
            m = re.match(r"EP(\d+)_(.+)\.md$", p.name)
            if m:
                titles.setdefault(int(m.group(1)), m.group(2).strip())
    try:
        data = json.loads(_EPISODES_PATH.read_text(encoding="utf-8"))
        for e in data:
            if e.get("number") and e.get("title"):
                titles[int(e["number"])] = str(e["title"]).strip()
    except (OSError, ValueError) as ex:
        logging.warning(f"[company_notes] episodes.json 讀不到集名，改用逐字稿檔名：{ex}")
    _title_cache = titles
    return titles


_rss_dates_cache: dict[int, str] | None = None


def _rss_dates() -> dict[int, str]:
    """第二來源：官方 RSS 的 pubDate（download_transcripts.load_rss_dates 已經在做同一件事，
    這裡只是重用）。為什麼需要：episodes.json 是上游站的複本，常落後 2～3 集
    （2026-09-17 實查：episodes.json 停在 EP693，DB 已有 EP694–696 的 14 筆，
    entry_date 又全是 analysis_date 頂替的），沒有這一層，時間軸最新那幾集就會沒日期、沒股價。
    RSS 取不到就回空 dict，呼叫端照樣往下走。"""
    global _rss_dates_cache
    if _rss_dates_cache is not None:
        return _rss_dates_cache
    _rss_dates_cache = {}
    try:
        from download_transcripts import load_rss_dates  # noqa: PLC0415
        _rss_dates_cache = {int(n): d.isoformat() for n, d in load_rss_dates(max_age_hours=24).items()}
    except Exception as ex:  # noqa: BLE001
        logging.warning(f"[company_notes] RSS 上架日取不到（不影響其他來源）：{ex}")
    return _rss_dates_cache


def _episode_date_for(sig: dict) -> str | None:
    """順序：episodes.json 真實上架日 → 官方 RSS pubDate → signals.entry_date
    （最後這個只在 entry_date != analysis_date 時信，理由見 attention.py 2026-08-11 那段註解：
    entry_date 可能是 analysis_date 頂替來的）。三個都沒有就回 None，頁面顯示「日期不明」。"""
    ep_id = sig.get("episode_id") or ""
    d = attention._episode_date(ep_id)
    if d:
        return d
    d = _rss_dates().get(attention._ep_num(ep_id))
    if d:
        return d
    ed, ad = sig.get("entry_date"), sig.get("analysis_date")
    if ed and (ad is None or str(ed) != str(ad)):
        return str(ed)
    return None


# ── DB（唯讀）───────────────────────────────────────────────────────────────
_HISTORY_COLS = (
    "id", "episode_id", "stock_code", "stock_name", "action", "exact_quote",
    "entry_date", "analysis_date",
    "summary", "oneliner", "context", "substantive", "quote_long", "notes_source",
)


def fetch_raw_history(codes: list[str], per_code: int = HISTORY_PER_CODE) -> dict[str, list[dict]]:
    """每檔標的最近 per_code 集的提及列（同集同標的多筆時取 id 最小那筆——
    跟回填時的存放位置一致，見任務檔 A 段）。回傳 {code: [row, ...]}，
    row 依集號由新到舊。純唯讀。"""
    if not codes:
        return {}
    from database import _conn, init_db
    init_db()
    cols = ", ".join(_HISTORY_COLS)
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {cols}
                FROM signals
                WHERE stock_code IN %s AND invalid_reason IS NULL
                ORDER BY stock_code, episode_id, id
                """,
                (tuple(codes),),
            )
            rows = [dict(r) for r in cur.fetchall()]

    # 同集同標的只留 id 最小那筆
    first: dict[tuple[str, str], dict] = {}
    for r in rows:
        key = (r["stock_code"], r["episode_id"])
        if key not in first or r["id"] < first[key]["id"]:
            first[key] = r

    by_code: dict[str, list[dict]] = {}
    for (code, _ep), r in first.items():
        by_code.setdefault(code, []).append(r)
    for code, lst in by_code.items():
        lst.sort(key=lambda r: attention._ep_num(r["episode_id"]), reverse=True)
        by_code[code] = lst[:per_code]
    return by_code


# ── 股價 ────────────────────────────────────────────────────────────────────
def _fetch_prices(items: list[dict]) -> tuple[dict, dict, str | None]:
    """批次拿 (ticker, ep_date) 收盤與 ticker 最新收盤。任何失敗都回空 dict＋錯誤字串，
    不讓整頁掛掉（比照 notifier 對 attention 的容錯）。"""
    import prices  # 延遲 import：只讀 DB 的呼叫端（例如回填腳本）不必載 yfinance

    on_keys = sorted({(it["code"], it["date"]) for it in items if it.get("date")})
    tickers = sorted({it["code"] for it in items})
    px_on: dict = {}
    px_now: dict = {}
    err = None
    try:
        px_on = prices.batch_get_close_on_or_before(on_keys)
    except Exception as ex:  # noqa: BLE001
        err = f"歷史收盤批次失敗：{ex}"
        logging.warning(f"[company_notes] {err}")
    try:
        px_now = prices.batch_get_latest_close(tickers)
    except Exception as ex:  # noqa: BLE001
        err = (err + "；" if err else "") + f"最新收盤批次失敗：{ex}"
        logging.warning(f"[company_notes] {err}")
    return px_on, px_now, err


def _fmt_px(v, mkt: str) -> str:
    unit = "元" if mkt == "tw" else "美元"
    if v is None:
        return ""
    v = float(v)
    s = f"{v:,.2f}" if v < 1000 else f"{v:,.1f}"
    return f"{s} {unit}"


# ── 對外入口 ────────────────────────────────────────────────────────────────
def attach_history(rows: list[dict], per_code: int = HISTORY_PER_CODE,
                   with_prices: bool = True) -> dict:
    """就地把 `history`（list[dict]）與 `weekline`（str）掛到 attention rows 上。
    rows 是 attention.compute_attention() 的回傳值。

    回傳統計 dict（給呼叫端印數字用）：
      codes / timeline_items / summary_filled / notes_missing / px_on_ok / px_now_ok / price_error
    任何一步失敗都只記警告：rows 沒有 history 時 report_html 退回原本的卡片。"""
    stats = {"codes": len(rows), "timeline_items": 0, "summary_filled": 0,
             "notes_missing": 0, "px_on_ok": 0, "px_now_ok": 0, "price_error": None}
    if not rows:
        return stats

    codes = [r["code"] for r in rows]
    raw = fetch_raw_history(codes, per_code=per_code)
    titles = _episode_titles()

    items: list[dict] = []
    for r in rows:
        hist = []
        for s in raw.get(r["code"], []):
            ep_id = s["episode_id"]
            ep_date = _episode_date_for(s)
            has_summary = bool((s.get("summary") or "").strip())
            it = {
                "ep": ep_id,
                "ep_num": attention._ep_num(ep_id),
                "date": ep_date,
                "weekday": _weekday_zh(ep_date) if ep_date else "",
                "title": titles.get(attention._ep_num(ep_id), ""),
                "summary": (s.get("summary") or "").strip(),
                "oneliner": (s.get("oneliner") or "").strip(),
                "context": (s.get("context") or "").strip(),
                "substantive": s.get("substantive"),
                "quote_long": (s.get("quote_long") or "").strip(),
                "quote": (s.get("exact_quote") or "").strip(),
                "notes_source": s.get("notes_source"),
                "code": r["code"],
                "mkt": r["mkt"],
                "px_on": None, "px_now": None, "px_note": "", "chg_pct": None,
                "px_on_txt": "", "px_now_txt": "",
            }
            hist.append(it)
            items.append(it)
            stats["timeline_items"] += 1
            if has_summary:
                stats["summary_filled"] += 1
            else:
                stats["notes_missing"] += 1
        r["history"] = hist
        # 本週他怎麼講：最近一集的 oneliner，沒有就 summary 第一句
        week = ""
        if hist:
            h0 = hist[0]
            week = h0["oneliner"] or _first_sentence(h0["summary"])
        r["weekline"] = week

    if with_prices and items:
        px_on, px_now, err = _fetch_prices(items)
        stats["price_error"] = err
        for it in items:
            on = px_on.get((it["code"], it["date"])) if it["date"] else None
            now = px_now.get(it["code"])
            it["px_on"] = on
            it["px_now"] = now
            it["px_on_txt"] = _fmt_px(on, it["mkt"])
            it["px_now_txt"] = _fmt_px(now, it["mkt"])
            if on is not None:
                stats["px_on_ok"] += 1
            if now is not None:
                stats["px_now_ok"] += 1
            if on and now:
                try:
                    it["chg_pct"] = round((float(now) - float(on)) / float(on) * 100, 1)
                except ZeroDivisionError:
                    it["chg_pct"] = None
            if on is not None and it["date"]:
                wd = date.fromisoformat(it["date"]).weekday()
                if wd >= 5:
                    it["px_note"] = f"（{it['date']} 是週{_WEEKDAY_ZH[wd]}未開盤，取前一個交易日收盤）"
    return stats


def _first_sentence(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    m = re.split(r"(?<=[。！？!?])", text, maxsplit=1)
    return m[0].strip() if m and m[0].strip() else text
