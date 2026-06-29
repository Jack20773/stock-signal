"""
Gmail HTML 報告寄送模組。

用法：
  python notifier.py --ep EP672          # 單集報告
  python notifier.py --last 50           # 最新 50 集匯總
  python notifier.py                     # 全部訊號匯總

環境變數（.env）：
  GMAIL_USER          Gmail 帳號，例如 xxx@gmail.com
  GMAIL_APP_PASSWORD  Gmail 應用程式密碼（非登入密碼）
  REPORT_TO           收件人，預設同 GMAIL_USER
"""
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

load_dotenv(override=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])


# ── HTML 產生 ──────────────────────────────────────────────────────────────

def _pct_color(v) -> str:
    if v is None:
        return "#888888"
    return "#d9534f" if v >= 0 else "#2b8a3e"


def _fmt_pct(v) -> str:
    if v is None:
        return "N/A"
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.2f}%"


def _beat_label(beat) -> str:
    if beat is True:
        return "<span style='color:#d9534f;font-weight:bold;'>獲勝</span>"
    if beat is False:
        return "<span style='color:#2b8a3e;font-weight:bold;'>落後</span>"
    return "<span style='color:#888;'>待定</span>"


def _action_label(action: str, confidence: str) -> str:
    if action == "+1":
        return "超級看好" if confidence == "High" else "看好"
    if action == "-1":
        return "看壞"
    return "中立"


def _ep_num(ep: str) -> int:
    m = re.search(r"\d+", ep)
    return int(m.group()) if m else 0


def generate_html(results: list[dict], title: str, stats: dict) -> str:
    # 收集所有 primary_tag
    all_tags = sorted({r.get("primary_tag", "") for r in results if r.get("primary_tag")})

    # 準備每筆資料的 JS data-* 屬性
    rows_by_ep = defaultdict(list)
    for r in results:
        ep = r.get("episode_id", "")
        rows_by_ep[ep].append(r)

    table_rows = ""
    for ep in sorted(rows_by_ep, key=_ep_num):
        ep_signals = rows_by_ep[ep]
        ep_date    = ep_signals[0].get("entry_date", "") or ""
        ep_num_val = _ep_num(ep)  # 每個 episode 算一次
        # 集數 header row
        table_rows += f"""
        <tr class="ep-header" data-ep="{ep}"
            style="background:#e8ecf0;cursor:pointer;"
            onclick="toggleEp('{ep}')">
          <td colspan="7" style="padding:8px 12px;font-weight:bold;color:#1a252f;font-size:13px;">
            ▾ {ep}
            <span style="font-weight:normal;color:#7f8c8d;font-size:12px;margin-left:8px;">{ep_date} · {len(ep_signals)} 筆</span>
          </td>
        </tr>"""

        for r in ep_signals:
            action = r.get("action", "0")
            # 顯示 P&L 視角：performance.py 對 -1 已反轉，+10% = 空頭賺 10%
            s_pct  = r.get("stock_return_pct")
            b_pct  = r.get("benchmark_return_pct")
            beat   = r.get("beat_benchmark")
            name   = r.get("stock_name", "")
            code   = r.get("stock_code", "")
            tag    = r.get("primary_tag", "")
            bm     = r.get("benchmark_ticker") or ("0050.TW" if str(code).endswith(".TW") else "SPY")
            action_lbl = _action_label(action, r.get("confidence_level", ""))
            # -1 空頭標記
            short_badge = ('<span style="font-size:10px;background:#e8f4fd;color:#1a6b9a;'
                           'border-radius:3px;padding:1px 4px;margin-left:4px;">空</span>'
                           if action == "-1" else "")
            _ep     = r.get("live_entry_price") or r.get("entry_price")
            entry_p = f"{_ep:.2f}" if _ep else "N/A"
            curr_p  = f"{r['current_price']:.2f}" if r.get("current_price") else "N/A"
            days    = r.get("days_held") or "N/A"
            s_pct_val = s_pct if s_pct is not None else -9999
            b_pct_val = b_pct if b_pct is not None else -9999
            beat_val  = 1 if beat is True else (0 if beat is False else -1)
            mkt = "tw" if str(code).endswith(".TW") else "us"
            # ep_num_val 已在 episode 迴圈外計算

            raw_reason  = (r.get("raw_reason")   or "").strip()
            exact_quote = (r.get("exact_quote")  or "").strip()
            quote_html  = (f'<div style="margin-top:5px;padding-left:10px;border-left:3px solid #ccc;'
                           f'color:#888;font-style:italic;font-size:11px;">「{exact_quote}」</div>'
                           if exact_quote else "")
            reason_html = (f'<tr class="ep-row ep-{ep} reason-row" data-ep="{ep}" data-epnum="{ep_num_val}"'
                           f' data-tag="{tag}" data-mkt="{mkt}" data-spct="{s_pct_val}"'
                           f' data-bpct="{b_pct_val}" data-beat="{beat_val}"'
                           f' style="background:#f8f9fa;">'
                           f'<td colspan="8" style="padding:7px 12px 10px 32px;border-bottom:1px solid #eee;">'
                           f'<span style="font-size:11px;font-weight:bold;color:#3b6ea5;">主委觀點</span>'
                           f'<span style="font-size:11px;color:#555;margin-left:6px;">{raw_reason}</span>'
                           f'{quote_html}</td></tr>'
                           if raw_reason or exact_quote else "")

            table_rows += f"""
        <tr class="ep-row ep-{ep}"
            data-ep="{ep}" data-epnum="{ep_num_val}" data-tag="{tag}" data-mkt="{mkt}"
            data-spct="{s_pct_val}" data-bpct="{b_pct_val}"
            data-beat="{beat_val}" data-days="{days}"
            style="border-bottom:none;">
          <td style="padding:9px 12px 4px;font-weight:bold;color:#1a252f;white-space:nowrap;padding-left:24px;">{ep}</td>
          <td style="padding:9px 12px 4px;color:#888;font-size:12px;">{tag}</td>
          <td style="padding:9px 12px 4px;font-weight:bold;">{name}<br>
            <span style="color:#aaa;font-size:11px;">{code}</span></td>
          <td style="padding:9px 12px 4px;color:#666;font-size:12px;">{action_lbl}{short_badge}</td>
          <td style="padding:9px 12px 4px;">{r.get('entry_date','N/A')}<br>
            <span style="color:#aaa;font-size:11px;">{entry_p} → {curr_p}</span></td>
          <td style="padding:9px 12px 4px;font-weight:bold;color:{_pct_color(s_pct)};">{_fmt_pct(s_pct)}</td>
          <td style="padding:9px 12px 4px;color:#666;">{_fmt_pct(b_pct)}<br>
            <span style="color:#bbb;font-size:10px;">{bm}</span></td>
          <td style="padding:9px 12px 4px;">{_beat_label(beat)}</td>
        </tr>{reason_html}"""

    win_pct   = stats.get("win_rate", 0)
    win_color = "#d9534f" if win_pct >= 50 else "#2b8a3e"
    today     = date.today().isoformat()

    tag_btns = "".join(
        f'<button onclick="filterTag(\'{t}\')" style="margin:2px 4px;padding:4px 10px;border:1px solid #ddd;border-radius:12px;background:#fff;cursor:pointer;font-size:12px;">{t}</button>'
        for t in all_tags
    )

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  body{{margin:0;padding:0;background:#f4f6f9;font-family:Arial,Helvetica,sans-serif;color:#333;}}
  .wrap{{max-width:780px;margin:20px auto;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 4px 12px rgba(0,0,0,.07);}}
  th{{cursor:pointer;user-select:none;}}
  th:hover{{background:#e2e6ea;}}
  .btn-active{{background:#1a252f!important;color:#fff!important;border-color:#1a252f!important;}}
  tr.ep-row.hidden{{display:none;}}
</style>
</head>
<body>
<div class="wrap">

  <!-- Header -->
  <div style="background:#1a252f;padding:22px 20px;text-align:center;color:#fff;">
    <div style="font-size:20px;font-weight:bold;">股癌訊號勝率追蹤</div>
    <div style="color:#b3c1cd;font-size:12px;margin-top:4px;">{title} · {today}</div>
  </div>

  <!-- Stats -->
  <div style="display:flex;text-align:center;border-bottom:1px solid #eee;">
    <div style="flex:1;padding:16px 0;">
      <div style="font-size:11px;color:#999;">總訊號</div>
      <div style="font-size:26px;font-weight:bold;color:#2c3e50;">{stats['total']}</div>
    </div>
    <div style="flex:1;padding:16px 0;border-left:1px solid #eee;border-right:1px solid #eee;">
      <div style="font-size:11px;color:#999;">對標大盤勝率</div>
      <div style="font-size:26px;font-weight:bold;color:{win_color};">{win_pct}%</div>
    </div>
    <div style="flex:1;padding:16px 0;border-right:1px solid #eee;">
      <div style="font-size:11px;color:#999;">Win / Lose</div>
      <div style="font-size:24px;font-weight:bold;">
        <span style="color:#d9534f;">{stats['wins']}</span>
        <span style="color:#ccc;"> / </span>
        <span style="color:#2b8a3e;">{stats['losses']}</span>
      </div>
    </div>
    <div style="flex:1;padding:16px 0;">
      <div style="font-size:11px;color:#999;">待定</div>
      <div style="font-size:26px;font-weight:bold;color:#aaa;">{stats['total'] - stats['decided']}</div>
    </div>
  </div>

  <!-- Filters -->
  <div style="padding:10px 16px 6px;border-bottom:1px solid #eee;background:#fafafa;">
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
      <span style="font-size:12px;color:#888;white-space:nowrap;">搜集數：</span>
      <input id="ep-search" type="text" placeholder="輸入集數，如 630 或 EP630"
        oninput="filterEp(this.value)"
        style="flex:1;max-width:220px;padding:5px 10px;border:1px solid #ddd;border-radius:12px;
               font-size:12px;outline:none;">
      <button onclick="clearEpFilter()"
        style="padding:4px 10px;border:1px solid #ddd;border-radius:12px;background:#fff;
               cursor:pointer;font-size:12px;color:#888;">清除</button>
    </div>
    <div>
      <span style="font-size:12px;color:#888;margin-right:4px;">分類：</span>
      <button onclick="filterTag('all')" id="btn-all" class="btn-active"
        style="margin:2px 4px;padding:4px 10px;border:1px solid #ddd;border-radius:12px;background:#fff;cursor:pointer;font-size:12px;">全部</button>
      <button onclick="filterMkt('tw')"
        style="margin:2px 4px;padding:4px 10px;border:1px solid #ddd;border-radius:12px;background:#fff;cursor:pointer;font-size:12px;">台股</button>
      <button onclick="filterMkt('us')"
        style="margin:2px 4px;padding:4px 10px;border:1px solid #ddd;border-radius:12px;background:#fff;cursor:pointer;font-size:12px;">美股</button>
      {tag_btns}
    </div>
    <div style="font-size:10px;color:#bbb;margin-top:6px;">台股對比 0050.TW · 美股對比 SPY（同集台美混合時基準不同）</div>
  </div>

  <!-- Table -->
  <div style="padding:0 0 12px;">
    <table id="main-table" style="width:100%;border-collapse:collapse;font-size:13px;">
      <thead>
        <tr style="background:#f1f3f5;color:#495057;font-size:12px;">
          <th onclick="sortBy('epnum')" style="padding:10px 12px;text-align:left;">集數 ↕</th>
          <th onclick="sortBy('tag')"   style="padding:10px 12px;text-align:left;">分類 ↕</th>
          <th style="padding:10px 12px;text-align:left;">標的</th>
          <th style="padding:10px 12px;text-align:left;">動作</th>
          <th onclick="sortBy('date')"  style="padding:10px 12px;text-align:left;">進場日 ↕</th>
          <th onclick="sortBy('spct')"  style="padding:10px 12px;text-align:left;">個股報酬 ↕</th>
          <th onclick="sortBy('bpct')"  style="padding:10px 12px;text-align:left;">同期大盤 ↕</th>
          <th onclick="sortBy('beat')"  style="padding:10px 12px;text-align:left;">勝負 ↕</th>
        </tr>
      </thead>
      <tbody id="tbody">{table_rows}</tbody>
    </table>
  </div>

  <!-- Footer -->
  <div style="padding:10px;text-align:center;font-size:10px;color:#bbb;border-top:1px solid #f0f0f0;">
    台股基準 0050.TW · 美股基準 SPY · 僅供參考，非投資建議
  </div>
</div>

<script>
// ── 集數展開/收合 ───────────────────────────────────────
function toggleEp(ep) {{
  const rows = document.querySelectorAll('.ep-' + ep);
  const hdr  = document.querySelector('.ep-header[data-ep="' + ep + '"] td');
  const collapsed = rows[0] && rows[0].classList.contains('hidden');
  rows.forEach(r => r.classList.toggle('hidden', !collapsed));
  if (hdr) hdr.innerHTML = hdr.innerHTML.replace(/[▾▸]/, collapsed ? '▾' : '▸');
}}

// ── 集數搜尋 ────────────────────────────────────────────
let epFilter = '';
function filterEp(val) {{
  epFilter = val.replace(/^EP/i, '').trim();
  applyAllFilters();
}}
function clearEpFilter() {{
  epFilter = '';
  document.getElementById('ep-search').value = '';
  applyAllFilters();
}}

// ── 分類篩選 ────────────────────────────────────────────
let tagFilter = 'all';
let mktFilter = 'all';

function filterTag(tag) {{
  tagFilter = tag; mktFilter = 'all';
  document.querySelectorAll('button').forEach(b => b.classList.remove('btn-active'));
  event.target.classList.add('btn-active');
  applyAllFilters();
}}
function filterMkt(mkt) {{
  mktFilter = mkt; tagFilter = 'all';
  document.querySelectorAll('button').forEach(b => b.classList.remove('btn-active'));
  event.target.classList.add('btn-active');
  applyAllFilters();
}}

function applyAllFilters() {{
  document.querySelectorAll('.ep-row').forEach(r => {{
    const epNum = r.dataset.epnum;           // "630"
    const epId  = r.dataset.ep;              // "EP630"
    const epMatch = !epFilter ||
                    epNum === epFilter ||
                    epId.toLowerCase().includes(epFilter.toLowerCase());
    const tagMatch = tagFilter === 'all' || r.dataset.tag === tagFilter;
    const mktMatch = mktFilter === 'all' || r.dataset.mkt === mktFilter;
    r.classList.toggle('hidden', !(epMatch && tagMatch && mktMatch));
  }});
  syncEpHeaders();
}}
function syncEpHeaders() {{
  document.querySelectorAll('.ep-header').forEach(hdr => {{
    const ep = hdr.dataset.ep;
    const visible = document.querySelectorAll('.ep-' + ep + ':not(.hidden)').length;
    hdr.style.display = visible === 0 ? 'none' : '';
  }});
}}

// ── 欄位排序 ────────────────────────────────────────────
let sortDir = {{}};
function sortBy(col) {{
  const tbody = document.getElementById('tbody');
  const dir = (sortDir[col] === 1) ? -1 : 1;
  sortDir[col] = dir;

  const rowVal = r => {{
    if (col === 'epnum') return parseInt(r.dataset.epnum);
    if (col === 'spct')  return parseFloat(r.dataset.spct);
    if (col === 'bpct')  return parseFloat(r.dataset.bpct);
    if (col === 'beat')  return parseInt(r.dataset.beat);
    if (col === 'date')  return r.querySelector('td:nth-child(5)').innerText;
    if (col === 'tag')   return r.dataset.tag;
    return 0;
  }};

  if (col === 'epnum') {{
    // 集數排序：整組搬移（header + 屬於它的 rows）
    const headers = [...tbody.querySelectorAll('.ep-header')];
    const groups  = headers.map(h => {{
      const ep   = h.dataset.ep;
      const rows = [...tbody.querySelectorAll('.ep-' + CSS.escape(ep))];
      return {{ header: h, rows, epnum: parseInt(ep.replace(/[^0-9]/g,'')) }};
    }});
    groups.sort((a, b) => a.epnum > b.epnum ? dir : a.epnum < b.epnum ? -dir : 0);
    groups.forEach(g => {{
      tbody.appendChild(g.header);
      g.rows.forEach(r => tbody.appendChild(r));
    }});
  }} else {{
    // 其他欄：組內排序
    const headers = [...tbody.querySelectorAll('.ep-header')];
    const groups  = headers.map(h => {{
      const ep   = h.dataset.ep;
      const rows = [...tbody.querySelectorAll('.ep-' + CSS.escape(ep))];
      return {{ header: h, rows }};
    }});
    groups.forEach(g => {{
      g.rows.sort((a, b) => rowVal(a) > rowVal(b) ? dir : rowVal(a) < rowVal(b) ? -dir : 0);
      tbody.appendChild(g.header);
      g.rows.forEach(r => tbody.appendChild(r));
    }});
  }}
}}
</script>
</body>
</html>"""


# ── 寄信 ──────────────────────────────────────────────────────────────────

def send_email(subject: str, html_content: str) -> bool:
    user     = os.getenv("GMAIL_USER")
    password = os.getenv("GMAIL_APP_PASSWORD")
    to_addr  = os.getenv("REPORT_TO") or user

    if not user or not password:
        logging.error("未設定 GMAIL_USER / GMAIL_APP_PASSWORD，無法寄信")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = user
    msg["To"]      = to_addr
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as server:
            server.login(user, password)
            server.sendmail(user, to_addr, msg.as_string())
        logging.info(f"報告已寄出 → {to_addr}")
        return True
    except Exception as e:
        logging.error(f"寄信失敗：{e}")
        return False


# ── 主流程 ─────────────────────────────────────────────────────────────────

def run_report(ep_filter: str = None, last_n: int = 0, fill: bool = True, send: bool = True):
    if fill:
        logging.info("補抓進場價中...")
        n = _fill_entry_prices()
        logging.info(f"已更新 {n} 筆進場價")

    results = calc_performance()

    if ep_filter:
        results = [r for r in results if r.get("episode_id") == ep_filter]
        title = f"集數 {ep_filter}"
    elif last_n:
        # 取最新 N 個 episode 的訊號
        eps = sorted({r["episode_id"] for r in results if r.get("episode_id")},
                     key=lambda e: int(e.replace("EP", "") or 0))
        keep = set(eps[-last_n:])
        results = [r for r in results if r.get("episode_id") in keep]
        title = f"最新 {last_n} 集匯總"
    else:
        title = "全集匯總"

    results.sort(key=lambda r: (r.get("entry_date") or "", r.get("episode_id") or ""))

    if not results:
        logging.warning("無符合條件的訊號資料")
        return

    stats = win_rate(results)
    html  = generate_html(results, title, stats)

    subject = f"【股癌訊號追蹤】{title}  勝率 {stats['win_rate']}%  Win {stats['wins']}/{stats['decided']}"

    if send:
        send_email(subject, html)
    else:
        out = "report_preview.html"
        with open(out, "w", encoding="utf-8") as f:
            f.write(html)
        logging.info(f"預覽已存至 {out}（未寄送）")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ep",      default="",  help="單集，例如 --ep EP672")
    parser.add_argument("--last",    type=int, default=0, help="最新 N 集")
    parser.add_argument("--no-fill", action="store_true", help="跳過補抓進場價")
    parser.add_argument("--preview", action="store_true", help="只存 HTML，不寄信")
    args = parser.parse_args()

    run_report(
        ep_filter=args.ep or None,
        last_n=args.last,
        fill=not args.no_fill,
        send=not args.preview,
    )


if __name__ == "__main__":
    main()
