"""
Gmail HTML 報告寄送模組。

用法：
  python notifier.py --ep EP672           # 單集報告
  python notifier.py --last 50            # 最新 50 集匯總
  python notifier.py --preview            # 存 HTML 預覽，不寄信
  python notifier.py --detail-url URL     # email 附完整報告連結
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


# ── 小工具 ──────────────────────────────────────────────────────────────────

def _pct_color(v) -> str:
    if v is None: return "#888888"
    return "#d9534f" if v >= 0 else "#2b8a3e"

def _fmt_pct(v) -> str:
    if v is None: return "N/A"
    return f"{'+'if v>=0 else ''}{v:.2f}%"

def _beat_label(beat) -> str:
    if beat is True:  return "<span style='color:#d9534f;font-weight:bold;'>獲勝</span>"
    if beat is False: return "<span style='color:#2b8a3e;font-weight:bold;'>落後</span>"
    return "<span style='color:#888;'>待定</span>"

def _action_label(action: str, confidence: str) -> str:
    if action == "+1": return "超級看好" if confidence == "High" else "看好"
    if action == "-1": return "看壞"
    return "中立"

def _ep_num(ep: str) -> int:
    m = re.search(r"\d+", ep)
    return int(m.group()) if m else 0


# ── 標的彙整 ────────────────────────────────────────────────────────────────

def _build_stock_groups(results: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for r in results:
        code = r.get("stock_code", "")
        if code:
            groups[code].append(r)

    out = []
    for code, sigs in groups.items():
        decided = [s for s in sigs if s.get("beat_benchmark") is not None]
        wins = sum(1 for s in decided if s.get("beat_benchmark"))
        rets = [s["stock_return_pct"] for s in sigs if s.get("stock_return_pct") is not None]
        is_tw = str(code).endswith(".TW") or str(code).endswith(".TWO")
        out.append({
            "code": code,
            "name": sigs[0].get("stock_name", ""),
            "tag": sigs[0].get("primary_tag", ""),
            "mkt": "台股" if is_tw else "美股",
            "signals": sorted(sigs, key=lambda s: _ep_num(s.get("episode_id", ""))),
            "total": len(sigs),
            "bullish": sum(1 for s in sigs if s.get("action") == "+1"),
            "bearish": sum(1 for s in sigs if s.get("action") == "-1"),
            "wins": wins,
            "decided": len(decided),
            "win_rate": round(wins / len(decided) * 100, 1) if decided else None,
            "avg_ret": round(sum(rets) / len(rets), 2) if rets else None,
            "latest_ep": max(sigs, key=lambda s: _ep_num(s.get("episode_id", ""))).get("episode_id", ""),
        })

    return sorted(out, key=lambda g: g["total"], reverse=True)


def _stock_tab_html(results: list[dict]) -> str:
    groups = _build_stock_groups(results)
    if not groups:
        return "<div style='padding:20px;color:#888;text-align:center;'>無標的資料</div>"

    rows_list = []
    for g in groups:
        wr = g["win_rate"]
        wr_color = "#d9534f" if wr and wr >= 50 else "#2b8a3e"
        wr_txt = f"{wr}%" if wr is not None else "待定"
        avg_color = _pct_color(g["avg_ret"])
        avg_txt = _fmt_pct(g["avg_ret"])
        bull_bear = ""
        if g["bullish"]: bull_bear += f'+{g["bullish"]}'
        if g["bearish"]: bull_bear += f' / -{g["bearish"]}'
        ep_tags = "".join(
            f'<span style="font-size:11px;background:#f0f0f0;padding:1px 5px;'
            f'border-radius:3px;margin:1px 2px;display:inline-block;">'
            f'{s.get("episode_id","")}</span>'
            for s in g["signals"]
        )
        rows_list.append(f"""
        <tr style="border-bottom:1px solid #f0f0f0;">
          <td style="padding:10px 12px;font-weight:bold;white-space:nowrap;">{g['name']}<br>
            <span style="color:#aaa;font-size:13px;">{g['code']}</span></td>
          <td style="padding:10px 8px;color:#888;font-size:13px;white-space:nowrap;">{g['mkt']}</td>
          <td style="padding:10px 8px;text-align:center;font-weight:bold;">{g['total']}</td>
          <td style="padding:10px 8px;text-align:center;color:#555;font-size:13px;">{bull_bear}</td>
          <td style="padding:10px 8px;text-align:center;font-weight:bold;color:{wr_color};">{wr_txt}</td>
          <td style="padding:10px 8px;text-align:center;font-weight:bold;color:{avg_color};">{avg_txt}</td>
          <td style="padding:10px 8px;color:#888;font-size:13px;white-space:nowrap;">{g['latest_ep']}</td>
          <td style="padding:10px 8px;line-height:1.8;">{ep_tags}</td>
        </tr>""")

    return f"""
    <table width="100%" style="border-collapse:collapse;font-size:15px;">
      <thead>
        <tr style="background:#f1f3f5;color:#495057;font-size:13px;">
          <th style="padding:10px 12px;text-align:left;">標的</th>
          <th style="padding:10px 8px;text-align:left;">市場</th>
          <th style="padding:10px 8px;text-align:center;">次數</th>
          <th style="padding:10px 8px;text-align:center;">多/空</th>
          <th style="padding:10px 8px;text-align:center;">勝率</th>
          <th style="padding:10px 8px;text-align:center;">均報酬</th>
          <th style="padding:10px 8px;text-align:left;">最近集</th>
          <th style="padding:10px 8px;text-align:left;">提及集數</th>
        </tr>
      </thead>
      <tbody>{"".join(rows_list)}</tbody>
    </table>"""


# ── 詳細版 row helpers ───────────────────────────────────────────────────────

def _render_ep_header(ep: str, ep_date: str, count: int) -> str:
    return f"""
        <tr class="ep-header" data-ep="{ep}"
            style="background:#e8ecf0;cursor:pointer;"
            onclick="toggleEp('{ep}')">
          <td colspan="8" style="padding:8px 12px;font-weight:bold;color:#1a252f;font-size:15px;">
            ▾ {ep}
            <span style="font-weight:normal;color:#7f8c8d;font-size:14px;margin-left:8px;">{ep_date} · {count} 筆</span>
          </td>
        </tr>"""


def _render_signal_row(r: dict, ep: str, ep_num_val: int) -> str:
    action     = r.get("action", "0")
    s_pct      = r.get("stock_return_pct")
    b_pct      = r.get("benchmark_return_pct")
    beat       = r.get("beat_benchmark")
    name       = r.get("stock_name", "")
    code       = r.get("stock_code", "")
    tag        = r.get("primary_tag", "")
    is_tw      = str(code).endswith(".TW") or str(code).endswith(".TWO")
    bm         = r.get("benchmark_ticker") or ("0050.TW" if is_tw else "SPY")
    action_lbl = _action_label(action, r.get("confidence_level", ""))
    short_badge = (
        '<span style="font-size:14px;background:#e8f4fd;color:#1a6b9a;'
        'border-radius:3px;padding:1px 4px;margin-left:4px;">空</span>'
        if action == "-1" else ""
    )
    _ep_p   = r.get("live_entry_price") or r.get("entry_price")
    entry_p = f"{_ep_p:.2f}" if _ep_p else "N/A"
    curr_p  = f"{r['current_price']:.2f}" if r.get("current_price") else "N/A"
    days    = r.get("days_held") or "N/A"

    s_pct_val = s_pct if s_pct is not None else -9999
    b_pct_val = b_pct if b_pct is not None else -9999
    beat_val  = 1 if beat is True else (0 if beat is False else -1)
    mkt       = "tw" if is_tw else "us"

    raw_reason  = (r.get("raw_reason")  or "").strip()
    exact_quote = (r.get("exact_quote") or "").strip()
    quote_html  = (
        f'<div style="margin-top:5px;padding-left:10px;border-left:3px solid #ccc;'
        f'color:#888;font-style:italic;font-size:14px;">「{exact_quote}」</div>'
        if exact_quote else ""
    )

    # 全站搜尋關鍵字：集數、數字、標的名、代碼、純數字代碼、主委觀點、原文引用
    kw = " ".join(filter(None, [
        ep, str(ep_num_val), name, code, code.split(".")[0], raw_reason, exact_quote
    ])).replace('"', ' ').replace('\n', ' ')

    reason_html = (
        f'<tr class="ep-row ep-{ep} reason-row" data-ep="{ep}" data-epnum="{ep_num_val}"'
        f' data-tag="{tag}" data-mkt="{mkt}" data-spct="{s_pct_val}"'
        f' data-bpct="{b_pct_val}" data-beat="{beat_val}"'
        f' data-name="{name}" data-code="{code}" data-kw="{kw}"'
        f' style="background:#f8f9fa;">'
        f'<td colspan="8" style="padding:7px 12px 10px 32px;border-bottom:1px solid #eee;">'
        f'<span style="font-size:14px;font-weight:bold;color:#3b6ea5;">主委觀點</span>'
        f'<span style="font-size:14px;color:#555;margin-left:6px;">{raw_reason}</span>'
        f'{quote_html}</td></tr>'
        if raw_reason or exact_quote else ""
    )

    return f"""
        <tr class="ep-row ep-{ep}"
            data-ep="{ep}" data-epnum="{ep_num_val}" data-tag="{tag}" data-mkt="{mkt}"
            data-spct="{s_pct_val}" data-bpct="{b_pct_val}"
            data-beat="{beat_val}" data-days="{days}"
            data-name="{name}" data-code="{code}" data-kw="{kw}"
            style="border-bottom:none;">
          <td style="padding:9px 12px 4px;font-weight:bold;color:#1a252f;white-space:nowrap;padding-left:24px;">{ep}</td>
          <td style="padding:9px 12px 4px;color:#888;font-size:14px;">{tag}</td>
          <td style="padding:9px 12px 4px;font-weight:bold;">{name}<br>
            <span style="color:#aaa;font-size:13px;">{code}</span></td>
          <td style="padding:9px 12px 4px;color:#666;font-size:14px;">{action_lbl}{short_badge}</td>
          <td style="padding:9px 12px 4px;">{r.get('entry_date','N/A')}<br>
            <span style="color:#aaa;font-size:13px;">{entry_p} → {curr_p}</span></td>
          <td style="padding:9px 12px 4px;font-weight:bold;color:{_pct_color(s_pct)};">{_fmt_pct(s_pct)}</td>
          <td style="padding:9px 12px 4px;color:#666;">{_fmt_pct(b_pct)}<br>
            <span style="color:#bbb;font-size:12px;">{bm}</span></td>
          <td style="padding:9px 12px 4px;">{_beat_label(beat)}</td>
        </tr>{reason_html}"""


# ── 詳細版 HTML（瀏覽器）────────────────────────────────────────────────────

def generate_html_detail(results: list[dict], title: str, stats: dict) -> str:
    all_tags = sorted({r.get("primary_tag", "") for r in results if r.get("primary_tag")})

    rows_by_ep = defaultdict(list)
    for r in results:
        rows_by_ep[r.get("episode_id", "")].append(r)

    rows_list = []
    for ep in sorted(rows_by_ep, key=_ep_num):
        ep_signals = rows_by_ep[ep]
        ep_date    = ep_signals[0].get("entry_date", "") or ""
        ep_num_val = _ep_num(ep)
        rows_list.append(_render_ep_header(ep, ep_date, len(ep_signals)))
        for r in ep_signals:
            rows_list.append(_render_signal_row(r, ep, ep_num_val))
    table_rows = "".join(rows_list)

    win_pct   = stats.get("win_rate", 0)
    win_color = "#d9534f" if win_pct >= 50 else "#2b8a3e"
    today     = date.today().isoformat()

    tag_btns = "".join(
        f'<button onclick="filterTag(\'{t}\')" style="margin:2px 4px;padding:4px 10px;'
        f'border:1px solid #ddd;border-radius:12px;background:#fff;cursor:pointer;font-size:14px;">{t}</button>'
        for t in all_tags
    )

    stock_tab_content = _stock_tab_html(results)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  body{{margin:0;padding:0;background:#f4f6f9;font-family:Arial,Helvetica,sans-serif;color:#333;}}
  .wrap{{max-width:860px;margin:20px auto;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 4px 12px rgba(0,0,0,.07);}}
  th{{cursor:pointer;user-select:none;}}
  th:hover{{background:#e2e6ea;}}
  .btn-active{{background:#1a252f!important;color:#fff!important;border-color:#1a252f!important;}}
  tr.ep-row.hidden{{display:none;}}
  .tab-btn{{margin:0 4px;padding:6px 16px;border:1px solid #ddd;border-radius:6px;
            background:#fff;cursor:pointer;font-size:14px;font-weight:bold;}}
  .fs-btn{{margin:0 2px;padding:4px 10px;border:1px solid #ddd;border-radius:6px;
           background:#fff;cursor:pointer;font-weight:bold;}}
</style>
<style id="dyn-font"></style>
</head>
<body>
<div class="wrap">

  <!-- Header -->
  <div style="background:#1a252f;padding:22px 20px;text-align:center;color:#fff;">
    <div style="font-size:22px;font-weight:bold;">股癌訊號勝率追蹤</div>
    <div style="color:#b3c1cd;font-size:14px;margin-top:4px;">{title} · {today}</div>
  </div>

  <!-- Stats -->
  <div style="display:flex;text-align:center;border-bottom:1px solid #eee;">
    <div style="flex:1;padding:16px 0;">
      <div style="font-size:13px;color:#999;">總訊號</div>
      <div style="font-size:26px;font-weight:bold;color:#2c3e50;">{stats['total']}</div>
    </div>
    <div style="flex:1;padding:16px 0;border-left:1px solid #eee;border-right:1px solid #eee;">
      <div style="font-size:13px;color:#999;">對標大盤勝率</div>
      <div style="font-size:26px;font-weight:bold;color:{win_color};">{win_pct}%</div>
    </div>
    <div style="flex:1;padding:16px 0;border-right:1px solid #eee;">
      <div style="font-size:13px;color:#999;">Win / Lose</div>
      <div style="font-size:24px;font-weight:bold;">
        <span style="color:#d9534f;">{stats['wins']}</span>
        <span style="color:#ccc;"> / </span>
        <span style="color:#2b8a3e;">{stats['losses']}</span>
      </div>
    </div>
    <div style="flex:1;padding:16px 0;">
      <div style="font-size:13px;color:#999;">待定</div>
      <div style="font-size:26px;font-weight:bold;color:#aaa;">{stats['total'] - stats['decided']}</div>
    </div>
  </div>

  <!-- Tab 切換 + 字體控制 -->
  <div style="padding:10px 16px;border-bottom:1px solid #eee;background:#fafafa;display:flex;align-items:center;gap:8px;">
    <button id="tab-ep" class="tab-btn btn-active" onclick="switchTab('ep')">以集數</button>
    <button id="tab-stock" class="tab-btn" onclick="switchTab('stock')">以標的</button>
    <div style="margin-left:auto;display:flex;align-items:center;gap:4px;">
      <span style="font-size:12px;color:#999;">字體</span>
      <button class="fs-btn" id="fs0" onclick="setFontSize(0)" style="font-size:11px;">小</button>
      <button class="fs-btn" id="fs1" onclick="setFontSize(1)" style="font-size:13px;">中</button>
      <button class="fs-btn" id="fs2" onclick="setFontSize(2)" style="font-size:15px;">大</button>
      <button class="fs-btn" id="fs3" onclick="setFontSize(3)" style="font-size:17px;">特大</button>
    </div>
  </div>

  <!-- 集數篩選工具列 -->
  <div id="view-filters" style="padding:10px 16px 6px;border-bottom:1px solid #eee;background:#fafafa;">
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap;">
      <span style="font-size:14px;color:#888;white-space:nowrap;">搜尋：</span>
      <input id="main-search" type="text"
        placeholder="集數、標的、代碼、主委觀點、任意關鍵字..."
        oninput="filterSearch(this.value)"
        style="flex:1;max-width:380px;padding:5px 12px;border:1px solid #ddd;border-radius:12px;
               font-size:14px;outline:none;">
      <button onclick="clearSearch()"
        style="padding:4px 10px;border:1px solid #ddd;border-radius:12px;background:#fff;
               cursor:pointer;font-size:14px;color:#888;">清除</button>
    </div>
    <div>
      <span style="font-size:14px;color:#888;margin-right:4px;">分類：</span>
      <button onclick="filterTag('all')" id="btn-all" class="btn-active"
        style="margin:2px 4px;padding:4px 10px;border:1px solid #ddd;border-radius:12px;background:#fff;cursor:pointer;font-size:14px;">全部</button>
      <button onclick="filterMkt('tw')"
        style="margin:2px 4px;padding:4px 10px;border:1px solid #ddd;border-radius:12px;background:#fff;cursor:pointer;font-size:14px;">台股</button>
      <button onclick="filterMkt('us')"
        style="margin:2px 4px;padding:4px 10px;border:1px solid #ddd;border-radius:12px;background:#fff;cursor:pointer;font-size:14px;">美股</button>
      {tag_btns}
    </div>
    <div style="font-size:12px;color:#bbb;margin-top:6px;">台股對比 0050.TW · 美股對比 SPY（同集台美混合時基準不同）</div>
  </div>

  <!-- 以集數 Table -->
  <div id="view-ep" style="padding:0 0 12px;">
    <table id="main-table" style="width:100%;border-collapse:collapse;font-size:15px;">
      <thead>
        <tr style="background:#f1f3f5;color:#495057;font-size:13px;">
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

  <!-- 以標的 Table -->
  <div id="view-stock" style="display:none;padding:0 0 12px;">
    {stock_tab_content}
  </div>

  <!-- Footer -->
  <div style="padding:10px;text-align:center;font-size:13px;color:#bbb;border-top:1px solid #f0f0f0;">
    台股基準 0050.TW · 美股基準 SPY · 僅供參考，非投資建議
  </div>
</div>

<script>
// ── 字體大小 ──────────────────────────────────────────────
const FS = [12, 14, 16, 18];
let fsIdx = parseInt(localStorage.getItem('fs-idx') || '1');

function applyFontSize() {{
  const s = FS[fsIdx];
  document.getElementById('dyn-font').textContent =
    `.wrap td, .wrap th, .wrap div, .wrap span, .wrap button {{ font-size: ${{s}}px !important; }}`;
  document.querySelectorAll('.fs-btn').forEach((b, i) =>
    b.classList.toggle('btn-active', i === fsIdx));
  localStorage.setItem('fs-idx', fsIdx);
}}
function setFontSize(i) {{ fsIdx = i; applyFontSize(); }}
document.addEventListener('DOMContentLoaded', applyFontSize);

// ── Tab 切換 ─────────────────────────────────────────────
function switchTab(tab) {{
  const isEp = tab === 'ep';
  document.getElementById('view-ep').style.display = isEp ? '' : 'none';
  document.getElementById('view-filters').style.display = isEp ? '' : 'none';
  document.getElementById('view-stock').style.display = isEp ? 'none' : '';
  document.getElementById('tab-ep').classList.toggle('btn-active', isEp);
  document.getElementById('tab-stock').classList.toggle('btn-active', !isEp);
}}

// ── 集數展開/收合 ─────────────────────────────────────────
function toggleEp(ep) {{
  const rows = document.querySelectorAll('.ep-' + ep);
  const hdr  = document.querySelector('.ep-header[data-ep="' + ep + '"] td');
  const collapsed = rows[0] && rows[0].classList.contains('hidden');
  rows.forEach(r => r.classList.toggle('hidden', !collapsed));
  if (hdr) hdr.innerHTML = hdr.innerHTML.replace(/[▾▸]/, collapsed ? '▾' : '▸');
}}

// ── 統一搜尋 ──────────────────────────────────────────────
let searchFilter = '';
function filterSearch(val) {{
  searchFilter = val.trim().toLowerCase();
  applyAllFilters();
}}
function clearSearch() {{
  searchFilter = '';
  document.getElementById('main-search').value = '';
  applyAllFilters();
}}

// ── 分類篩選 ──────────────────────────────────────────────
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
    const kwMatch  = !searchFilter || (r.dataset.kw || '').toLowerCase().includes(searchFilter);
    const tagMatch = tagFilter === 'all' || r.dataset.tag === tagFilter;
    const mktMatch = mktFilter === 'all' || r.dataset.mkt === mktFilter;
    r.classList.toggle('hidden', !(kwMatch && tagMatch && mktMatch));
  }});
  syncEpHeaders();
}}
function syncEpHeaders() {{
  document.querySelectorAll('.ep-header').forEach(hdr => {{
    const ep      = hdr.dataset.ep;
    const visible = document.querySelectorAll('.ep-' + ep + ':not(.hidden)').length;
    hdr.style.display = visible === 0 ? 'none' : '';
  }});
}}

// ── 欄位排序 ──────────────────────────────────────────────
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
    const headers = [...tbody.querySelectorAll('.ep-header')];
    const groups  = headers.map(h => {{
      const ep   = h.dataset.ep;
      const rows = [...tbody.querySelectorAll('.ep-' + CSS.escape(ep))];
      return {{ header: h, rows, epnum: parseInt(ep.replace(/[^0-9]/g, '')) }};
    }});
    groups.sort((a, b) => a.epnum > b.epnum ? dir : a.epnum < b.epnum ? -dir : 0);
    groups.forEach(g => {{
      tbody.appendChild(g.header);
      g.rows.forEach(r => tbody.appendChild(r));
    }});
  }} else {{
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


# ── 簡要版 HTML（Gmail）──────────────────────────────────────────────────────

def generate_html_email(results: list[dict], title: str, stats: dict,
                        detail_url: str = "") -> str:
    today     = date.today().isoformat()
    win_pct   = stats.get("win_rate", 0)
    win_color = "#d9534f" if win_pct >= 50 else "#2b8a3e"

    # 排序：獲勝（報酬高→低）→ 落後 → 待定
    def _sort_key(r):
        beat  = r.get("beat_benchmark")
        group = 0 if beat is True else (1 if beat is False else 2)
        s_pct = r.get("stock_return_pct") or -9999
        return (group, -s_pct)

    sorted_res = sorted(results, key=_sort_key)

    # 查看完整報告按鈕
    detail_btn = ""
    if detail_url:
        detail_btn = f"""
        <tr>
          <td align="center" style="padding:16px 20px 8px;">
            <a href="{detail_url}" style="display:inline-block;padding:12px 28px;background:#1a252f;
               color:#fff;text-decoration:none;border-radius:6px;font-size:15px;font-weight:bold;">
              查看完整報告 →
            </a>
          </td>
        </tr>"""

    # 結果列
    prev_group = None
    table_rows = ""
    group_labels  = ["獲勝", "落後", "待定"]
    group_counts  = [stats["wins"], stats["losses"], stats["total"] - stats["decided"]]
    group_colors  = ["#fff3f3", "#f3fff3", "#f8f8f8"]

    for r in sorted_res:
        beat  = r.get("beat_benchmark")
        group = 0 if beat is True else (1 if beat is False else 2)

        if group != prev_group:
            table_rows += f"""
              <tr>
                <td colspan="6" style="padding:6px 12px;background:{group_colors[group]};
                    font-size:13px;font-weight:bold;color:#777;border-top:2px solid #e8e8e8;">
                  {group_labels[group]}（{group_counts[group]} 筆）
                </td>
              </tr>"""
            prev_group = group

        code       = r.get("stock_code", "")
        name       = r.get("stock_name", "")
        ep         = r.get("episode_id", "")
        action     = r.get("action", "0")
        s_pct      = r.get("stock_return_pct")
        b_pct      = r.get("benchmark_return_pct")
        bm         = r.get("benchmark_ticker") or ("0050.TW" if str(code).endswith(".TW") else "SPY")
        action_lbl = _action_label(action, r.get("confidence_level", ""))
        badge      = (
            ' <span style="font-size:11px;background:#e8f4fd;color:#1a6b9a;'
            'border-radius:3px;padding:1px 4px;">空</span>'
            if action == "-1" else ""
        )
        row_bg = "#fffafa" if beat is True else ("#f5fff5" if beat is False else "#fafafa")

        table_rows += f"""
              <tr style="background:{row_bg};border-bottom:1px solid #f0f0f0;">
                <td style="padding:8px 10px;font-size:14px;font-weight:bold;">
                  {name}<br><span style="color:#aaa;font-size:12px;">{code}</span></td>
                <td style="padding:8px 6px;font-size:13px;color:#666;">{ep}</td>
                <td style="padding:8px 6px;font-size:13px;color:#555;">{action_lbl}{badge}</td>
                <td style="padding:8px 6px;font-size:14px;font-weight:bold;
                    color:{_pct_color(s_pct)};text-align:right;">{_fmt_pct(s_pct)}</td>
                <td style="padding:8px 6px;font-size:12px;color:#999;text-align:right;">
                  {_fmt_pct(b_pct)}<br><span style="color:#ccc;">{bm}</span></td>
                <td style="padding:8px 6px;text-align:center;">{_beat_label(beat)}</td>
              </tr>"""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f6f9;font-family:Arial,Helvetica,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" border="0">
  <tr>
    <td align="center" style="padding:20px 10px;">
      <table width="600" cellpadding="0" cellspacing="0" border="0"
             style="background:#fff;border-radius:8px;overflow:hidden;
                    box-shadow:0 2px 8px rgba(0,0,0,.08);">

        <!-- Header -->
        <tr>
          <td style="background:#1a252f;padding:22px 20px;text-align:center;">
            <div style="font-size:22px;font-weight:bold;color:#fff;">股癌訊號勝率追蹤</div>
            <div style="color:#b3c1cd;font-size:14px;margin-top:4px;">{title} · {today}</div>
          </td>
        </tr>

        {detail_btn}

        <!-- Stats -->
        <tr>
          <td style="padding:0;">
            <table width="100%" cellpadding="0" cellspacing="0" border="0"
                   style="border-bottom:1px solid #eee;">
              <tr>
                <td align="center" style="padding:14px 0;border-right:1px solid #eee;">
                  <div style="font-size:12px;color:#999;">總訊號</div>
                  <div style="font-size:24px;font-weight:bold;color:#2c3e50;">{stats['total']}</div>
                </td>
                <td align="center" style="padding:14px 0;border-right:1px solid #eee;">
                  <div style="font-size:12px;color:#999;">對標大盤勝率</div>
                  <div style="font-size:24px;font-weight:bold;color:{win_color};">{win_pct}%</div>
                </td>
                <td align="center" style="padding:14px 0;border-right:1px solid #eee;">
                  <div style="font-size:12px;color:#999;">Win / Lose</div>
                  <div style="font-size:22px;font-weight:bold;">
                    <span style="color:#d9534f;">{stats['wins']}</span>
                    <span style="color:#ccc;"> / </span>
                    <span style="color:#2b8a3e;">{stats['losses']}</span>
                  </div>
                </td>
                <td align="center" style="padding:14px 0;">
                  <div style="font-size:12px;color:#999;">待定</div>
                  <div style="font-size:24px;font-weight:bold;color:#aaa;">{stats['total'] - stats['decided']}</div>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- Results table -->
        <tr>
          <td>
            <table width="100%" cellpadding="0" cellspacing="0" border="0"
                   style="font-size:14px;border-collapse:collapse;">
              <thead>
                <tr style="background:#f1f3f5;">
                  <th style="padding:9px 10px;text-align:left;font-size:13px;color:#495057;">標的</th>
                  <th style="padding:9px 6px;text-align:left;font-size:13px;color:#495057;">集數</th>
                  <th style="padding:9px 6px;text-align:left;font-size:13px;color:#495057;">動作</th>
                  <th style="padding:9px 6px;text-align:right;font-size:13px;color:#495057;">個股報酬</th>
                  <th style="padding:9px 6px;text-align:right;font-size:13px;color:#495057;">大盤</th>
                  <th style="padding:9px 6px;text-align:center;font-size:13px;color:#495057;">勝負</th>
                </tr>
              </thead>
              <tbody>{table_rows}</tbody>
            </table>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="padding:12px;text-align:center;font-size:12px;color:#bbb;
              border-top:1px solid #f0f0f0;">
            台股基準 0050.TW · 美股基準 SPY · 僅供參考，非投資建議
          </td>
        </tr>

      </table>
    </td>
  </tr>
</table>
</body>
</html>"""


# ── 寄信 ────────────────────────────────────────────────────────────────────

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


# ── 主流程 ──────────────────────────────────────────────────────────────────

def run_report(ep_filter: str = None, last_n: int = 0, fill: bool = True,
               preview: bool = False, detail_url: str = ""):
    if fill:
        logging.info("補抓進場價中...")
        n = _fill_entry_prices()
        logging.info(f"已更新 {n} 筆進場價")

    results = calc_performance()

    if ep_filter:
        results = [r for r in results if r.get("episode_id") == ep_filter]
        title = f"集數 {ep_filter}"
    elif last_n:
        eps  = sorted({r["episode_id"] for r in results if r.get("episode_id")},
                      key=lambda e: int(re.sub(r"[^0-9]", "", e) or 0))
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
        with open("report_preview.html", "w", encoding="utf-8") as f:
            f.write(html)
        logging.info("預覽已存至 report_preview.html（未寄送）")
    else:
        # 儲存詳細版（供 workflow push 到 GitHub Pages）
        html_detail = generate_html_detail(results, title, stats)
        with open("report_detail.html", "w", encoding="utf-8") as f:
            f.write(html_detail)
        # 寄送簡要版 email
        html_email = generate_html_email(results, title, stats, detail_url)
        send_email(subject, html_email)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ep",         default="",  help="單集，如 --ep EP672")
    parser.add_argument("--last",       type=int, default=0, help="最新 N 集")
    parser.add_argument("--no-fill",    action="store_true", help="跳過補抓進場價")
    parser.add_argument("--preview",    action="store_true", help="只存 HTML 預覽，不寄信")
    parser.add_argument("--detail-url", default="",  help="詳細版 URL（加在 email 按鈕）")
    args = parser.parse_args()

    run_report(
        ep_filter  = args.ep or None,
        last_n     = args.last,
        fill       = not args.no_fill,
        preview    = args.preview,
        detail_url = args.detail_url,
    )


if __name__ == "__main__":
    main()
