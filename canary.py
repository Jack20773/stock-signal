"""部署後的正式站健康檢查（canary）。

**這支存在的理由**：每週四／週日 08:00 的 `update.yml` 排程如果失敗，
目前沒有任何人會知道——網站停在舊資料，沒有告警，第一次失靈是無聲的。
這個專案已經被同一型態的靜默失敗咬過三次（`signals_id_seq` 撞號、
`attention.py` 的 `ep_date is None` 整批丟棄、CI 綠燈但單集分析全被 try/except 吞掉），
所以這裡刻意**不只看 exit code**，而是回頭 curl 正式站，比對它上面印的資料日期。

檢查三層（任何一層不過就算失敗）：
  1. **上游任務狀態**：`--upstream-status failure` 時直接告警（job 根本沒跑到部署）。
  2. **抓得到頁面**：HTTP 200、body 不小於 `min_bytes`（防「部署了一個空殼」）。
  3. **內容是新的**：頁面自己印出來的資料日期，距今不得超過 `--max-age-days` 天。
     這一層才是真正擋「CI 綠燈但網站停在舊資料」的那一層。
  另外附帶記錄各頁 sha256，寫進 `--state-file`，下一次跑可以看出「內容有沒有變過」
  （GitHub Actions runner 每次都是全新機器、state 不會留存，所以這欄只是輔助資訊，
  不拿來當判定條件——不要讓一個在 CI 上永遠拿不到的東西決定成敗）。

用法：
  # 正式站檢查（CI 用；預設會寄信）
  python -X utf8 canary.py --upstream-status success
  # 只看結果不寄信（本機驗證用）
  python -X utf8 canary.py --dry-run
  # 用本機檔案當假資料跑邏輯（驗證告警文案，完全不碰網路）
  python -X utf8 canary.py --base-url "file:///D:/tmp/fake/" --dry-run

exit code：0＝全部通過；1＝有檢查失敗（已告警或已列印告警內容）。

🔴 寄信只在「有失敗」時發生，而且要同時給 `--notify`（或不給 `--dry-run`）
   與可用的 GMAIL_USER / GMAIL_APP_PASSWORD。成功時一律不寄信，避免每週兩封噪音
   把真正的告警訓練成被忽略的東西。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# 節目與排程都以台灣時間為準；GitHub Actions runner 是 UTC，直接用 date.today()
# 會在台灣清晨時段算出前一天，讓「今天的頁面」被誤判成過期。
TW_TZ = timezone(timedelta(hours=8))

DEFAULT_BASE_URL = "https://jack20773.github.io/stock-signal/"
DEFAULT_STATE_FILE = "canary_state.json"

# 每一頁怎麼判定「這頁是新的」。
#   date_re：頁面上那個由 report_html.py 印出來的資料日期（不是隨便抓一個日期——
#            第一頁內嵌 SIGNALS_DATA 有幾千個日期，抓錯就等於沒檢查）。
#            date_re 為 None＝這一頁目前沒有可靠的日期標記，只驗 200＋大小。
#   min_bytes：低於這個大小視同壞掉（空殼、錯誤頁、被截斷的部署）。
PAGES: list[dict] = [
    {
        "path": "index.html",
        "name": "主報告",
        # report_html.py:451 常駐導讀「以及截至 {today} 收盤相對大盤的結果」
        "date_re": r"截至\s*(\d{4}-\d{2}-\d{2})\s*收盤",
        "min_bytes": 200_000,
    },
    {
        "path": "attention.html",
        "name": "關注度",
        # report_html.py:1687 標題列下方那行日期
        "date_re": r'margin-top:4px;">(\d{4}-\d{2}-\d{2})<',
        "min_bytes": 20_000,
    },
    {
        "path": "transcripts.html",
        "name": "逐字稿",
        "date_re": None,  # 這頁沒有印資料日期，只能驗存在與大小
        "min_bytes": 50_000,
    },
]


def _today_tw() -> date:
    return datetime.now(TW_TZ).date()


def _fetch(url: str, timeout: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "stock-signal-canary/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (固定網域)
        # 真正的 HTTP 非 200 會由 urllib 丟 HTTPError，這裡是保險；
        # file:// 走同一條路但沒有 status（None），視同 200 才能拿本機假資料驗邏輯。
        status = getattr(resp, "status", None) or 200
        if status != 200:
            raise RuntimeError(f"HTTP {status}")
        return resp.read()


def check_page(base_url: str, page: dict, today: date, max_age_days: int,
               timeout: int, retries: int, retry_wait: int) -> dict:
    """回傳 {'ok', 'name', 'path', 'problems'[], 'bytes', 'sha256', 'page_date'}。
    失敗原因用人話寫，而且要指出是哪一層失敗——半夜收到告警信的人需要的是
    「哪一步壞了」，不是一個 traceback。"""
    url = base_url.rstrip("/") + "/" + page["path"]
    result = {"name": page["name"], "path": page["path"], "url": url,
              "problems": [], "bytes": 0, "sha256": "", "page_date": None}

    body = None
    last_err = ""
    for attempt in range(1, retries + 1):
        try:
            body = _fetch(url, timeout)
            break
        except Exception as e:  # 網路錯誤、404、逾時都在這裡
            last_err = f"{type(e).__name__}: {e}"
            if attempt < retries:
                logging.warning("抓 %s 失敗（第 %d/%d 次）：%s，%d 秒後重試",
                                url, attempt, retries, last_err, retry_wait)
                time.sleep(retry_wait)

    if body is None:
        result["problems"].append(f"抓不到頁面（重試 {retries} 次都失敗）：{last_err}")
        result["ok"] = False
        return result

    result["bytes"] = len(body)
    result["sha256"] = hashlib.sha256(body).hexdigest()

    if len(body) < page["min_bytes"]:
        result["problems"].append(
            f"頁面只有 {len(body):,} bytes，低於門檻 {page['min_bytes']:,}——"
            f"多半是部署了一個空殼或錯誤頁")

    if page["date_re"]:
        text = body.decode("utf-8", errors="replace")
        m = re.search(page["date_re"], text)
        if not m:
            result["problems"].append(
                "找不到資料日期標記——頁面結構可能改了（改版時記得同步更新 canary.py 的 date_re），"
                "或部署到了一個非預期的頁面")
        else:
            result["page_date"] = m.group(1)
            try:
                page_date = date.fromisoformat(m.group(1))
            except ValueError:
                result["problems"].append(f"資料日期格式怪異：{m.group(1)}")
            else:
                age = (today - page_date).days
                if age > max_age_days:
                    result["problems"].append(
                        f"網站上的資料日期是 {page_date}，距今 {age} 天（上限 {max_age_days} 天）"
                        f"——排程可能失敗了，或部署沒把新產出的檔案帶上去，網站停在舊資料")
                elif age < 0:
                    result["problems"].append(f"資料日期 {page_date} 在未來，時區或系統時間有問題")

    result["ok"] = not result["problems"]
    return result


def build_report(results: list[dict], upstream_status: str, today: date,
                 base_url: str) -> tuple[bool, str, str]:
    """回傳 (all_ok, 純文字摘要, 告警用 HTML)。"""
    upstream_bad = upstream_status not in ("", "success", "skipped")
    all_ok = (not upstream_bad) and all(r["ok"] for r in results)

    lines = [f"stock-signal 部署 canary — {today}（台灣時間）", f"檢查對象：{base_url}", ""]
    if upstream_status:
        lines.append(f"[{'FAIL' if upstream_bad else ' OK '}] 上游排程任務狀態：{upstream_status}")
    for r in results:
        tag = " OK " if r["ok"] else "FAIL"
        extra = f"{r['bytes']:,} bytes"
        if r["page_date"]:
            extra += f"，資料日期 {r['page_date']}"
        lines.append(f"[{tag}] {r['name']}（{r['path']}）：{extra}")
        for p in r["problems"]:
            lines.append(f"       ↳ {p}")
    lines.append("")
    lines.append("結論：全部通過" if all_ok else "結論：有檢查未通過，網站可能停在舊資料或根本沒更新")
    text = "\n".join(lines)

    rows = []
    if upstream_status:
        rows.append((not upstream_bad, "上游排程任務", f"狀態：{upstream_status}", []))
    for r in results:
        detail = f"{r['bytes']:,} bytes"
        if r["page_date"]:
            detail += f"｜資料日期 {r['page_date']}"
        rows.append((r["ok"], f"{r['name']}（{r['path']}）", detail, r["problems"]))

    tr = ""
    for ok, name, detail, problems in rows:
        color = "#2b8a3e" if ok else "#d9534f"
        badge = "通過" if ok else "失敗"
        prob = ""
        if problems:
            items = "".join(f"<li>{p}</li>" for p in problems)
            prob = f'<ul style="margin:6px 0 0;padding-left:18px;color:#d9534f;font-size:13px;">{items}</ul>'
        tr += (f'<tr><td style="padding:10px;border-bottom:1px solid #eee;">'
               f'<b style="color:{color};">{badge}</b></td>'
               f'<td style="padding:10px;border-bottom:1px solid #eee;">{name}'
               f'<div style="color:#888;font-size:12px;">{detail}</div>{prob}</td></tr>')

    headline = ("正式站看起來是新的" if all_ok
                else "正式站沒有如期更新，請人工確認 GitHub Actions")
    html = f"""<html><body style="font-family:Arial,Helvetica,sans-serif;background:#f4f6f9;padding:16px;">
<div style="max-width:640px;margin:0 auto;background:#fff;border-radius:8px;overflow:hidden;">
  <div style="background:{'#1a252f' if all_ok else '#d9534f'};color:#fff;padding:16px 20px;">
    <div style="font-size:18px;font-weight:bold;">stock-signal 部署檢查</div>
    <div style="font-size:13px;color:#e6ecf2;margin-top:4px;">{today}（台灣時間）｜{headline}</div>
  </div>
  <table style="width:100%;border-collapse:collapse;font-size:14px;">{tr}</table>
  <div style="padding:14px 20px;font-size:12px;color:#888;">
    檢查對象：<a href="{base_url}">{base_url}</a><br>
    下一步：到 GitHub Actions 看最近一次 <code>update.yml</code> 的 log；
    綠燈不代表成功（單集失敗會被 try/except 吞掉），要看 log 裡「分析 N 失敗 M」那行。
  </div>
</div></body></html>"""
    return all_ok, text, html


def main() -> int:
    ap = argparse.ArgumentParser(description="部署後的正式站健康檢查（canary）")
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL,
                    help="要檢查的站台根路徑；可以給 file:/// 路徑用本機假資料跑邏輯")
    ap.add_argument("--max-age-days", type=int, default=1,
                    help="網站上的資料日期最多可以落後幾天（預設 1）")
    ap.add_argument("--upstream-status", default="",
                    help="上游 job 的 result（success/failure/cancelled）；非 success 直接算失敗")
    ap.add_argument("--timeout", type=int, default=20)
    ap.add_argument("--retries", type=int, default=3,
                    help="Pages CDN 有傳播延遲，抓不到時重試次數")
    ap.add_argument("--retry-wait", type=int, default=30, help="重試間隔秒數")
    ap.add_argument("--state-file", default=DEFAULT_STATE_FILE)
    ap.add_argument("--alert-to", default="", help="告警收件人；留空＝用 notifier 的預設名單")
    ap.add_argument("--dry-run", action="store_true",
                    help="不寄信，只把告警內容印出來（本機驗證一律用這個）")
    ap.add_argument("--today", default="", help="覆寫「今天」（YYYY-MM-DD），測試用")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.max_age_days < 0:
        print("--max-age-days 不可為負數", file=sys.stderr)
        return 2

    today = date.fromisoformat(args.today) if args.today else _today_tw()

    results = [check_page(args.base_url, p, today, args.max_age_days,
                          args.timeout, args.retries, args.retry_wait)
               for p in PAGES]
    all_ok, text, html = build_report(results, args.upstream_status, today, args.base_url)
    print(text)

    # sha256 留痕（輔助資訊，不參與判定；CI 上不會留存）
    try:
        state_path = Path(args.state_file)
        prev = {}
        if state_path.exists():
            prev = json.loads(state_path.read_text(encoding="utf-8"))
        for r in results:
            old = (prev.get("pages") or {}).get(r["path"], {}).get("sha256")
            if old and r["sha256"] and old == r["sha256"]:
                print(f"（提醒）{r['path']} 的內容 sha256 跟上次完全相同：{old[:12]}…")
        state_path.write_text(json.dumps(
            {"checked_at": datetime.now(TW_TZ).isoformat(),
             "base_url": args.base_url,
             "pages": {r["path"]: {"sha256": r["sha256"], "bytes": r["bytes"],
                                   "page_date": r["page_date"]} for r in results}},
            ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logging.warning("state file 讀寫失敗（不影響判定）：%s", e)

    if all_ok:
        print("canary 通過，不寄信（成功不打擾）。")
        return 0

    subject = f"[stock-signal] ⚠ 部署檢查未通過（{today}）"
    if args.dry_run:
        print("\n=== DRY-RUN：以下是原本會寄出的告警信 ===")
        print(f"Subject: {subject}")
        print(html)
        return 1

    try:
        from notifier import send_email  # 延後 import：dry-run 不該被寄信模組的相依拖累
        sent = send_email(subject, html, override_to=args.alert_to)
    except Exception as e:
        logging.error("寄告警信失敗：%s", e)
        sent = False
    if not sent:
        print("⚠ 告警信沒寄出去（缺 GMAIL_USER / GMAIL_APP_PASSWORD 或 SMTP 失敗）——"
              "告警管道本身也壞了，請直接看 Actions log。", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
