"""
Gmail HTML 報告寄送模組。

用法：
  python notifier.py --ep EP672           # 單集報告
  python notifier.py --last 50            # 最新 50 集匯總
  python notifier.py --preview            # 存 HTML 預覽，不寄信
  python notifier.py --detail-url URL     # email 附完整報告連結
"""
import json
import os
import re
import sys
import smtplib
import argparse
import logging
from collections import defaultdict
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import date

sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
from performance import _fill_entry_prices, calc_performance, win_rate
from prices import benchmark_for

load_dotenv(override=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])

from report_html import generate_html_detail, generate_html_email, _ep_num

# ── 寄信 ────────────────────────────────────────────────────────────────────

def send_email(subject: str, html_content: str) -> bool:
    user     = os.getenv("GMAIL_USER")
    password = os.getenv("GMAIL_APP_PASSWORD")
    # REPORT_TO 支援多個收件人，用逗號分隔，例如 a@gmail.com,b@gmail.com
    to_raw   = os.getenv("REPORT_TO") or user or ""
    to_list  = [a.strip() for a in to_raw.split(",") if a.strip()]

    if not user or not password or not to_list:
        logging.error("未設定 GMAIL_USER / GMAIL_APP_PASSWORD / REPORT_TO，跳過寄信")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = user
    msg["To"]      = ", ".join(to_list)
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as server:
            server.login(user, password)
            server.sendmail(user, to_list, msg.as_string())
        logging.info(f"報告已寄出 → {', '.join(to_list)}")
        return True
    except Exception as e:
        logging.error(f"寄信失敗：{e}")
        return False


# ── 主流程 ──────────────────────────────────────────────────────────────────

def run_report(ep_filter: str = None, last_n: int = 0, fill: bool = True,
               preview: bool = False, detail_url: str = "", no_send: bool = False):
    if fill:
        logging.info("補抓進場價中...")
        n = _fill_entry_prices()
        logging.info(f"已更新 {n} 筆進場價")

    results = calc_performance()

    if ep_filter:
        results = [r for r in results if r.get("episode_id") == ep_filter]
        title = f"集數 {ep_filter}"
    elif last_n:
        eps  = sorted({r["episode_id"] for r in results if r.get("episode_id")}, key=_ep_num)
        keep = set(eps[-last_n:])
        results = [r for r in results if r.get("episode_id") in keep]
        title = f"最新 {last_n} 集匯總"
    else:
        title = "全集匯總"

    results.sort(key=lambda r: (r.get("entry_date") or "", r.get("episode_id") or ""))

    if not results:
        logging.warning("無符合條件的訊號資料")
        return

    stats   = win_rate(results)
    subject = f"【股癌訊號追蹤】{title}  勝率 {stats['win_rate']}%  Win {stats['wins']}/{stats['decided']}"

    if preview:
        html = generate_html_detail(results, title, stats)
        try:
            with open("report_preview.html", "w", encoding="utf-8") as f:
                f.write(html)
            logging.info("預覽已存至 report_preview.html（未寄送）")
        except OSError as e:
            logging.error(f"寫入 report_preview.html 失敗：{e}")
    else:
        # 儲存詳細版（供 workflow push 到 GitHub Pages）
        html_detail = generate_html_detail(results, title, stats)
        try:
            with open("report_detail.html", "w", encoding="utf-8") as f:
                f.write(html_detail)
        except OSError as e:
            logging.error(f"寫入 report_detail.html 失敗：{e}")
        if not no_send:
            # 寄送簡要版 email
            html_email = generate_html_email(results, title, stats, detail_url)
            send_email(subject, html_email)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ep",         default="",  help="單集，如 --ep EP672")
    parser.add_argument("--last",       type=int, default=0, help="最新 N 集")
    parser.add_argument("--no-fill",    action="store_true", help="跳過補抓進場價")
    parser.add_argument("--preview",    action="store_true", help="只存 HTML 預覽，不寄信")
    parser.add_argument("--no-send",    action="store_true", help="只存 report_detail.html，不寄信")
    parser.add_argument("--detail-url", default="",  help="詳細版 URL（加在 email 按鈕）")
    args = parser.parse_args()

    run_report(
        ep_filter  = args.ep or None,
        last_n     = args.last,
        fill       = not args.no_fill,
        preview    = args.preview,
        no_send    = args.no_send,
        detail_url = args.detail_url,
    )


if __name__ == "__main__":
    main()
