"""新訂閱者加入流程：把 email 加進 extra_recipients.txt + 寄一封歡迎信。

背景：週報收件人有三個來源——`REPORT_TO`（GitHub Secret，寫入後讀不回）、
訂閱者資料庫、以及 `extra_recipients.txt`（進版控、AI 可直接維護）。
新增人員一律走 `extra_recipients.txt`，不要去動 `REPORT_TO`
（決策見 001_memory/project_stocksignal.md「Railway 帳號停權」段）。

用法：
    python -X utf8 welcome_email.py someone@example.com --dry-run   # 只產預覽，不寫檔不寄信
    python -X utf8 welcome_email.py someone@example.com             # 加入名單 + 寄歡迎信
    python -X utf8 welcome_email.py someone@example.com --no-add    # 只寄信不加名單
    python -X utf8 welcome_email.py someone@example.com --no-send   # 只加名單不寄信
"""
import argparse
import datetime
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from notifier import send_email, EXTRA_RECIPIENTS_FILE, _extra_recipients

DETAIL_URL = "https://jack20773.github.io/stock-signal/"
PREVIEW_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "welcome_email_preview.html")

# 寬鬆但夠用的 email 格式檢查——擋掉打錯的明顯情況，不追求 RFC 5322 完整性
_EMAIL_RE = re.compile(r"^[^@\s,]+@[^@\s,.]+(\.[^@\s,.]+)+$")


def valid_email(addr: str) -> bool:
    return bool(_EMAIL_RE.match(addr))


def already_listed(addr: str) -> bool:
    return addr.lower() in {e.lower() for e in _extra_recipients()}


def add_to_list(addr: str, note: str = "") -> None:
    """append 到 extra_recipients.txt，附日期註解方便日後追蹤誰何時被加進來。"""
    today = datetime.date.today().isoformat()
    comment = f"# {today} 新訂閱者{('，' + note) if note else ''}"
    with open(EXTRA_RECIPIENTS_FILE, "a", encoding="utf-8") as f:
        f.write(f"{comment}\n{addr}\n")


def build_welcome_html(addr: str) -> str:
    """歡迎信 HTML——沿用週報的視覺（深藍 header + 紅色 CTA + 免責 footer）。"""
    today = datetime.date.today().strftime("%Y-%m-%d")
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f6f9;font-family:Arial,Helvetica,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" border="0">
  <tr>
    <td align="center" style="padding:24px 10px;">
      <table width="100%" cellpadding="0" cellspacing="0" border="0"
             style="max-width:620px;background:#fff;border-radius:10px;overflow:hidden;
                    box-shadow:0 2px 12px rgba(0,0,0,.1);">

        <!-- Header -->
        <tr>
          <td style="background:#1a252f;padding:28px 24px;text-align:center;">
            <div style="font-size:26px;font-weight:bold;color:#fff;letter-spacing:0.5px;">股癌訊號勝率追蹤</div>
            <div style="color:#b3c1cd;font-size:15px;margin-top:6px;">訂閱確認 · {today}</div>
          </td>
        </tr>

        <!-- 歡迎詞 -->
        <tr>
          <td style="padding:28px 24px 8px;">
            <div style="font-size:20px;font-weight:bold;color:#333;">歡迎加入 🎉</div>
            <div style="font-size:15px;color:#555;line-height:1.8;margin-top:14px;">
              你的信箱 <span style="color:#1a252f;font-weight:bold;">{addr}</span>
              已加入每週報告的寄送名單。收到這封信就代表訂閱成功，不用再做任何事。
            </div>
          </td>
        </tr>

        <!-- 你會收到什麼 -->
        <tr>
          <td style="padding:8px 24px 4px;">
            <div style="background:#f8f9fb;border-radius:8px;padding:18px 20px;">
              <div style="font-size:15px;font-weight:bold;color:#333;margin-bottom:12px;">你每週會收到</div>
              <div style="font-size:14px;color:#555;line-height:1.9;">
                📊 <b>績效儀表板</b>——歷史訊號的整體勝率與平均報酬<br>
                🔥 <b>本週最新訊號</b>——最新一集提到的標的、方向與節目原文引用<br>
                🔗 <b>完整報告連結</b>——逐集訊號、個股排行、關注度排序、逐字稿全文
              </div>
            </div>
          </td>
        </tr>

        <!-- 寄送時間 -->
        <tr>
          <td style="padding:18px 24px 4px;">
            <div style="font-size:14px;color:#555;line-height:1.8;">
              <b>寄送時間</b>：每週二早上（台灣時間），節目更新後自動分析並寄出。
            </div>
          </td>
        </tr>

        <!-- CTA -->
        <tr>
          <td style="padding:22px 24px 26px;text-align:center;">
            <a href="{DETAIL_URL}"
               style="display:inline-block;padding:16px 40px;background:#d9534f;
                      color:#fff;text-decoration:none;border-radius:6px;
                      font-size:17px;font-weight:bold;">先看看完整報告 →</a>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="padding:16px;text-align:center;font-size:13px;color:#bbb;
              border-top:1px solid #f0f0f0;line-height:1.7;">
            台股基準 0050.TW · 美股基準 SPY · 僅供參考，非投資建議<br>
            不想再收到的話，直接回信告訴我就會把你移除。
          </td>
        </tr>

      </table>
    </td>
  </tr>
</table>
</body>
</html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description="加入週報名單並寄歡迎信")
    parser.add_argument("email", help="要加入的 email 地址")
    parser.add_argument("--note", default="", help="寫進名單註解的備註（例如來源／關係）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只產生預覽 HTML，不寫入名單也不寄信")
    parser.add_argument("--no-add", action="store_true", help="不寫入 extra_recipients.txt")
    parser.add_argument("--no-send", action="store_true", help="不寄信")
    args = parser.parse_args()

    addr = args.email.strip()
    if not valid_email(addr):
        print(f"❌ email 格式看起來不對：{addr}")
        return 1

    html = build_welcome_html(addr)

    if args.dry_run:
        with open(PREVIEW_FILE, "w", encoding="utf-8") as f:
            f.write(html)
        listed = "已在名單中" if already_listed(addr) else "尚未在名單中"
        print(f"[dry-run] 收件人：{addr}（{listed}）")
        print(f"[dry-run] 預覽已寫入：{PREVIEW_FILE}")
        print("[dry-run] 未寫入名單、未寄信")
        return 0

    if not args.no_add:
        if already_listed(addr):
            print(f"⚠ {addr} 已在 extra_recipients.txt，跳過新增（不重複寫入）")
        else:
            add_to_list(addr, args.note)
            print(f"✅ 已加入 extra_recipients.txt：{addr}")

    if not args.no_send:
        ok = send_email("歡迎訂閱｜股癌訊號勝率追蹤週報", html, override_to=addr)
        if not ok:
            print("❌ 歡迎信寄送失敗（見上方 log）")
            return 1
        print(f"✅ 歡迎信已寄出 → {addr}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
