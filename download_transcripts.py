import sys
import json
import time
import argparse
import urllib.request
import urllib.parse
from datetime import datetime, timezone, date as _date
from pathlib import Path

import gooaye_rss  # 官方 RSS 抓取／解析（沿用既有實作，不另外發明一套）

sys.stdout.reconfigure(encoding="utf-8")

BASE_URL     = "https://whatmkreallysaid.com"
EPISODES_URL = f"{BASE_URL}/episodes.json"
OUT_DIR      = Path(__file__).parent / "transcripts"
EPISODES_LOCAL = Path(__file__).parent / "episodes.json"
RSS_CACHE    = Path(__file__).parent / "_cache" / "gooaye_rss.xml"
DELAY_SEC    = 0.5

# ---------------------------------------------------------------------------
# 日期校正關卡（2026-09-03 新增）
#
# 為什麼要有這一段：
#   episodes.json 是上游 whatmkreallysaid.com 的逐位元複本（見 main() 的
#   write_bytes）。上游把英文月份縮寫 Mar/May、Jun/Jul（前兩字母相同）解析錯，
#   2026-09-03 實測有 97 集日期是錯的。而本檔每次跑都會無條件覆寫 episodes.json，
#   所以手動修完會被下一次下載洗掉 → 必須在「寫檔之後」當場再修一遍。
#
# 比對母體用官方 RSS 的 pubDate（不是寫死那 97 筆的對照表）：
#   未來新集數有同樣錯誤會被接住；上游哪天自己修好了，比對結果就是 0 筆，
#   不會反而改壞。
#
# 只改日期與其衍生欄位（DATE_FIELDS），title/summary/description/filename 不動。
# ---------------------------------------------------------------------------

DATE_FIELDS = ("date", "year", "month", "day",
               "month_name", "date_display", "date_short")

# 硬寫月份名稱，不用 strftime("%B")——那個受 locale 影響，
# 換一台機器跑就可能寫出中文月份，把資料弄髒。
_MON_FULL = ("January", "February", "March", "April", "May", "June",
             "July", "August", "September", "October", "November", "December")
_MON_ABBR = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
             "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def derive_date_fields(d: _date) -> dict:
    """由 date 推出 episodes.json 裡的全部日期衍生欄位。

    格式取自現況檔案實測（2026-09-03，690 筆有日期的紀錄 0 筆不符）：
      date_display = "Mar 02, 2020"（日補零）
      date_short   = "Mar 2020"
      month_name   = "March"
    """
    return {
        "date": f"{d.year:04d}-{d.month:02d}-{d.day:02d}",
        "year": d.year,
        "month": d.month,
        "day": d.day,
        "month_name": _MON_FULL[d.month - 1],
        "date_display": f"{_MON_ABBR[d.month - 1]} {d.day:02d}, {d.year}",
        "date_short": f"{_MON_ABBR[d.month - 1]} {d.year}",
    }


def load_rss_dates(cache_path: Path = RSS_CACHE, max_age_hours: float = 6.0) -> dict:
    """回傳 {集號: datetime.date}（RSS pubDate 轉 UTC 日）。

    取不到就讓例外往上拋，由 fix_episode_dates() 轉成「本次未校正」的明確回報，
    絕不靜默放行。
    """
    raw = gooaye_rss.fetch_rss(cache_path, max_age_hours=max_age_hours)
    parsed = gooaye_rss.parse_episodes(raw)
    out = {}
    for n, rec in parsed.items():
        pub = rec.get("pub_dt")
        if pub is not None:
            out[int(n)] = pub.astimezone(timezone.utc).date()
    return out


def _dump_bytes(data, like: bytes) -> bytes:
    """序列化成跟原檔同樣的格式（indent=2、非 ASCII 不轉義、沿用原本換行字元）。"""
    s = json.dumps(data, ensure_ascii=False, indent=2)
    if b"\r\n" in like:
        s = s.replace("\n", "\r\n")
    return s.encode("utf-8")


def fix_episode_dates(path: Path = EPISODES_LOCAL, *,
                      cache_path: Path = RSS_CACHE,
                      max_age_hours: float = 6.0,
                      rss_dates: dict | None = None,
                      verbose: bool = True) -> dict:
    """拿官方 RSS 的 pubDate 校正 episodes.json 的日期欄位。

    回傳 dict：
      status      ok / rss_unavailable / rss_empty / read_failed / empty_population
      population  真正拿去比對的集數（RSS 與 episodes.json 都有、且本地有日期值）
      fixed       實際改掉幾筆
      changes     [(集號, 舊日期, 新日期), ...]
      no_date     本地缺日期而跳過的（缺值不是錯值，例如 EP162）
      not_in_rss  本地有、RSS 沒有，無從比對的
      message     人看的一句話

    設計重點：
      - 冪等：改完再跑一次，fixed 一定是 0。
      - 母體為 0 不算通過（status=empty_population），因為「沒比到任何東西」跟
        「比過而且都對」的輸出長得一樣，但意義完全不同。
      - RSS 拿不到時不改檔，明確印警告並回報「本次未校正」。
    """
    res = {"status": "ok", "population": 0, "fixed": 0, "changes": [],
           "no_date": 0, "not_in_rss": 0, "message": ""}

    def say(msg):
        if verbose:
            print(msg, flush=True)

    if rss_dates is None:
        try:
            rss_dates = load_rss_dates(cache_path, max_age_hours=max_age_hours)
        except Exception as e:
            res["status"] = "rss_unavailable"
            res["message"] = (f"無法取得官方 RSS（{type(e).__name__}: {e}）"
                              f"→ 本次未校正日期，episodes.json 保持上游原樣")
            say(f"[date-fix][警告] {res['message']}")
            return res

    if not rss_dates:
        res["status"] = "rss_empty"
        res["message"] = "官方 RSS 解析後 0 集可比對 → 本次未校正日期"
        say(f"[date-fix][警告] {res['message']}")
        return res

    try:
        raw = Path(path).read_bytes()
        episodes = json.loads(raw.decode("utf-8"))
    except Exception as e:
        res["status"] = "read_failed"
        res["message"] = f"讀不到／解析不了 {path}（{type(e).__name__}: {e}）→ 本次未校正日期"
        say(f"[date-fix][警告] {res['message']}")
        return res

    for ep in episodes:
        num = ep.get("number")
        if num is None:
            continue
        try:
            num = int(num)
        except (TypeError, ValueError):
            continue

        want = rss_dates.get(num)
        if want is None:
            res["not_in_rss"] += 1
            continue

        cur = ep.get("date")
        if not cur:                      # 缺值（None／""／欄位不存在）不是錯值，本關不補
            res["no_date"] += 1
            continue

        res["population"] += 1
        if cur == f"{want.year:04d}-{want.month:02d}-{want.day:02d}":
            # 日期本身對，順手確認衍生欄位也對（上游只錯月份時衍生欄位會一起錯）
            expect = derive_date_fields(want)
            if all(ep.get(k) == v for k, v in expect.items()):
                continue
        else:
            expect = derive_date_fields(want)

        ep.update(expect)
        res["fixed"] += 1
        res["changes"].append((num, cur, expect["date"]))

    if res["population"] == 0:
        res["status"] = "empty_population"
        res["message"] = ("比對母體 0 集（RSS 與 episodes.json 沒有任何一集對得上）"
                          "→ 不視為通過，本次未校正日期")
        say(f"[date-fix][失敗] {res['message']}")
        return res

    if res["fixed"]:
        Path(path).write_bytes(_dump_bytes(episodes, raw))

    res["message"] = (f"比對母體 {res['population']} 集"
                      f"（RSS {len(rss_dates)} 集 / 本地缺日期 {res['no_date']} 集 / "
                      f"RSS 查無 {res['not_in_rss']} 集），修正 {res['fixed']} 筆")
    say(f"[date-fix] {res['message']}")
    for num, old, new in res["changes"][:20]:
        say(f"[date-fix]   EP{num}: {old} → {new}")
    if len(res["changes"]) > 20:
        say(f"[date-fix]   …另外 {len(res['changes']) - 20} 筆略")
    return res


def safe_filename(name: str) -> str:
    for ch in r'\/:*?"<>|':
        name = name.replace(ch, "_")
    return name


def fetch(url: str, retries: int = 3) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.read()
        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)


def main(last_n: int = 0, rss_max_age_hours: float = 6.0):
    OUT_DIR.mkdir(exist_ok=True)

    print("Fetching episode list...")
    raw = fetch(EPISODES_URL)
    episodes = json.loads(raw.decode("utf-8"))

    # C: 存成本地檔案，讓 performance.py 直接讀，不用再抓一次
    EPISODES_LOCAL.write_bytes(raw)

    # 寫檔後當場用官方 RSS 校正日期（上游月份解析有 bug，見檔頭說明）
    fix = fix_episode_dates(EPISODES_LOCAL, max_age_hours=rss_max_age_hours)
    if fix["fixed"]:
        episodes = json.loads(EPISODES_LOCAL.read_text(encoding="utf-8"))

    total = len(episodes)
    if last_n > 0:
        episodes = episodes[-last_n:]
        print(f"Found {total} episodes (only downloading last {last_n})\n")
    else:
        print(f"Found {total} episodes\n")

    skipped = downloaded = failed = 0
    for i, ep in enumerate(episodes, 1):
        filename = ep["filename"]
        number   = ep.get("number", "?")
        ep_date  = ep.get("date", "")
        out_path = OUT_DIR / safe_filename(filename)

        if out_path.exists() and out_path.stat().st_size > 0:
            print(f"[{number:>4}] SKIP   EP{number}")
            skipped += 1
            continue

        url = f"{BASE_URL}/episodes/{urllib.parse.quote(filename)}"
        try:
            content = fetch(url)
            out_path.write_bytes(content)
            size_kb = len(content) / 1024
            print(f"[{number:>4}] OK     EP{number} ({ep_date})  {size_kb:.1f} KB")
            downloaded += 1
        except Exception as e:
            print(f"[{number:>4}] FAIL   EP{number}  {e}")
            failed += 1

        time.sleep(DELAY_SEC)

    print(f"\nDone.  Downloaded: {downloaded}  Skipped: {skipped}  Failed: {failed}")
    # 日期校正結果再印一次，免得被上面幾百行下載紀錄洗掉
    print(f"日期校正：{fix['status']} — {fix['message']}")
    print(f"Saved to: {OUT_DIR}")
    return fix


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--last", type=int, default=0,
                        help="只下載最新 N 集（0 = 全下載）")
    parser.add_argument("--fix-dates-only", action="store_true",
                        help="只跑日期校正關卡，不下載任何東西")
    parser.add_argument("--rss-max-age-hours", type=float, default=6.0,
                        help="RSS 快取多久內算新鮮（給離線／測試用；預設 6 小時）")
    args = parser.parse_args()
    if args.fix_dates_only:
        r = fix_episode_dates(EPISODES_LOCAL, max_age_hours=args.rss_max_age_hours)
        sys.exit(0 if r["status"] == "ok" else 1)
    main(last_n=args.last, rss_max_age_hours=args.rss_max_age_hours)
