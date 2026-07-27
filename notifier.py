"""
Gmail HTML 報告寄送模組。

用法：
  python notifier.py --ep EP672           # 單集報告
  python notifier.py --last 50            # 最新 50 集匯總
  python notifier.py --preview            # 存 HTML 預覽，不寄信
  python notifier.py --detail-url URL     # email 附完整報告連結
  python notifier.py --to a@x.com,b@x.com # 只寄給指定的人（略過 REPORT_TO 與訂閱者清單）
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
from urllib.parse import quote

sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
from performance import _fill_entry_prices, calc_performance, win_rate
from prices import benchmark_for

load_dotenv(override=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])

from report_html import generate_html_detail, generate_html_email, _ep_num
from database import list_active_subscribers, save_latest_report

# ── 寄信 ────────────────────────────────────────────────────────────────────

EXTRA_RECIPIENTS_FILE = os.path.join(os.path.dirname(__file__), "extra_recipients.txt")


def _extra_recipients() -> list[str]:
    """額外收件人清單，獨立於 REPORT_TO（GitHub Secret，寫入後讀不回）與訂閱者資料庫（Railway Postgres）。
    一行一個 email，`#` 開頭當註解；直接進版控，方便之後查誰、何時被加進來。"""
    if not os.path.exists(EXTRA_RECIPIENTS_FILE):
        return []
    with open(EXTRA_RECIPIENTS_FILE, encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]


def send_email(subject: str, html_content: str, override_to: str = "") -> bool:
    user     = os.getenv("GMAIL_USER")
    password = os.getenv("GMAIL_APP_PASSWORD")
    # override_to 有值時（手動指定收件人）優先於 REPORT_TO 與額外名單；都支援多個收件人，用逗號分隔
    if override_to:
        to_list = [a.strip() for a in override_to.split(",") if a.strip()]
    else:
        to_raw  = os.getenv("REPORT_TO") or user or ""
        to_list = [a.strip() for a in to_raw.split(",") if a.strip()]
        for email in _extra_recipients():
            if email not in to_list:
                to_list.append(email)

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


# ── rijian-studio 訂閱名單（stock-signal 自己的 Postgres，linebot /subscribe 寫入） ──

def send_subscriber_emails(subject: str, html_content: str) -> None:
    """把報告寄給 rijian-studio 訂閱名單，逐一寄送並附上各自的個人化退訂連結（token-based）"""
    try:
        subs = list_active_subscribers()
    except Exception as e:
        logging.error(f"讀取訂閱名單失敗：{e}")
        return
    if not subs:
        return

    user     = os.getenv("GMAIL_USER")
    password = os.getenv("GMAIL_APP_PASSWORD")
    unsub_base = os.getenv("UNSUBSCRIBE_BASE_URL")  # linebot 的 /unsubscribe 網址
    if not user or not password:
        logging.error("未設定 GMAIL_USER / GMAIL_APP_PASSWORD，跳過訂閱名單寄信")
        return

    try:
        server = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15)
        server.login(user, password)
    except Exception as e:
        logging.error(f"訂閱名單寄信失敗（登入 SMTP 失敗）：{e}")
        return

    sent = 0
    try:
        for sub in subs:
            email, token = sub["email"], sub["token"]
            try:
                footer = ""
                if unsub_base:
                    unsub_link = f"{unsub_base}?token={quote(token)}"
                    footer = (f'<p style="font-size:11px;color:#bbb;text-align:center;margin-top:16px;">'
                              f'不想再收到這份報告？<a href="{unsub_link}" style="color:#999;">點此退訂</a></p>')
                personalized = html_content.replace("</body>", footer + "</body>") if footer else html_content
                msg = MIMEMultipart("alternative")
                msg["Subject"] = subject
                msg["From"]    = user
                msg["To"]      = email
                msg.attach(MIMEText(personalized, "html", "utf-8"))
                server.sendmail(user, [email], msg.as_string())
                sent += 1
            except Exception as e:
                logging.error(f"訂閱者寄信失敗（{email}），跳過繼續下一位：{e}")
    finally:
        server.quit()
    logging.info(f"訂閱名單報告已寄出 → {sent}/{len(subs)} 位")


# ── 主流程 ──────────────────────────────────────────────────────────────────

def run_report(ep_filter: str = None, last_n: int = 0, fill: bool = True,
               preview: bool = False, detail_url: str = "", no_send: bool = False,
               override_to: str = ""):
    if fill:
        logging.info("補抓進場價中...")
        n = _fill_entry_prices()
        logging.info(f"已更新 {n} 筆進場價")

    all_results = calc_performance()
    stats = win_rate(all_results)  # 勝率永遠用全集計算，email/詳細版才不會對不上

    results = all_results
    if ep_filter:
        results = [r for r in all_results if r.get("episode_id") == ep_filter]
        title = f"集數 {ep_filter}"
    elif last_n:
        eps  = sorted({r["episode_id"] for r in all_results if r.get("episode_id")}, key=_ep_num)
        keep = set(eps[-last_n:])
        results = [r for r in all_results if r.get("episode_id") in keep]
        title = f"最新 {last_n} 集匯總"
    else:
        title = "全集匯總"

    results.sort(key=lambda r: (r.get("entry_date") or "", r.get("episode_id") or ""))

    if not results:
        logging.warning("無符合條件的訊號資料")
        return

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
            send_email(subject, html_email, override_to=override_to)
            if not override_to:
                # 手動指定收件人時視為一次性測試/單獨寄送，不連帶寄給全體訂閱者
                send_subscriber_emails(subject, html_email)
            try:
                save_latest_report(subject, html_email)
            except Exception as e:
                logging.error(f"存最新報告失敗（不影響本次寄信）：{e}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ep",         default="",  help="單集，如 --ep EP672")
    parser.add_argument("--last",       type=int, default=0, help="最新 N 集")
    parser.add_argument("--no-fill",    action="store_true", help="跳過補抓進場價")
    parser.add_argument("--preview",    action="store_true", help="只存 HTML 預覽，不寄信")
    parser.add_argument("--no-send",    action="store_true", help="只存 report_detail.html，不寄信")
    parser.add_argument("--detail-url", default="",  help="詳細版 URL（加在 email 按鈕）")
    parser.add_argument("--to",         default="",  help="手動指定收件人（逗號分隔），會取代 REPORT_TO 且不寄給訂閱者清單")
    args = parser.parse_args()

    run_report(
        ep_filter   = args.ep or None,
        last_n      = args.last,
        fill        = not args.no_fill,
        preview     = args.preview,
        no_send     = args.no_send,
        detail_url  = args.detail_url,
        override_to = args.to,
    )


if __name__ == "__main__":
    main()
