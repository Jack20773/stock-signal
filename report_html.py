"""
HTML 報告生成模組（詳細版＋Email 版）。
由 notifier.py 呼叫；不直接執行。
"""
import json
import re
from collections import defaultdict
from datetime import date
from prices import benchmark_for

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
        wr_color = "#d9534f" if wr is not None and wr >= 50 else "#2b8a3e"
        wr_txt = f"{wr}%" if wr is not None else "待定"
        avg_color = _pct_color(g["avg_ret"])
        avg_txt = _fmt_pct(g["avg_ret"])
        parts = ([f'+{g["bullish"]}'] if g["bullish"] else []) + ([f'-{g["bearish"]}'] if g["bearish"] else [])
        bull_bear = " / ".join(parts)
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

    mkt_badge = (
        '<span style="font-size:11px;background:#e8f0fe;color:#1a6b9a;'
        'border-radius:3px;padding:1px 4px;margin-left:4px;">台</span>'
        if is_tw else
        '<span style="font-size:11px;background:#fff3cd;color:#856404;'
        'border-radius:3px;padding:1px 4px;margin-left:4px;">美</span>'
    )
    days_disp = f"{days}天" if isinstance(days, int) else "N/A"

    return f"""
        <tr class="ep-row ep-{ep}"
            data-ep="{ep}" data-epnum="{ep_num_val}" data-tag="{tag}" data-mkt="{mkt}"
            data-spct="{s_pct_val}" data-bpct="{b_pct_val}"
            data-beat="{beat_val}" data-days="{days if isinstance(days, int) else -1}"
            data-name="{name}" data-code="{code}" data-kw="{kw}"
            style="border-bottom:none;">
          <td style="padding:9px 12px 4px;font-weight:bold;color:#1a252f;white-space:nowrap;padding-left:24px;">{ep}</td>
          <td style="padding:9px 12px 4px;color:#888;font-size:14px;">{tag}</td>
          <td style="padding:9px 12px 4px;font-weight:bold;">{name}{mkt_badge}<br>
            <span style="color:#aaa;font-size:13px;">{code}</span></td>
          <td style="padding:9px 12px 4px;color:#666;font-size:14px;">{action_lbl}{short_badge}</td>
          <td style="padding:9px 12px 4px;">{r.get('entry_date','N/A')}<br>
            <span style="color:#aaa;font-size:13px;">{entry_p} → {curr_p}</span></td>
          <td style="padding:9px 12px 4px;font-weight:bold;color:{_pct_color(s_pct)};">{_fmt_pct(s_pct)}</td>
          <td style="padding:9px 12px 4px;color:#666;">{_fmt_pct(b_pct)}<br>
            <span style="color:#bbb;font-size:12px;">{bm}</span></td>
          <td style="padding:9px 12px 4px;text-align:center;color:#888;font-size:13px;">{days_disp}</td>
          <td style="padding:9px 12px 4px;">{_beat_label(beat)}</td>
        </tr>{reason_html}"""


# ── 詳細版 HTML（瀏覽器）────────────────────────────────────────────────────

def generate_html_detail(results: list[dict], title: str, stats: dict) -> str:
    # ── 增強版統計 ────────────────────────────────────────────
    bullish_dec = [r for r in results if r.get("action") == "+1" and r.get("beat_benchmark") is not None]
    bearish_dec = [r for r in results if r.get("action") == "-1" and r.get("beat_benchmark") is not None]
    all_rets    = sorted([r["stock_return_pct"] for r in results
                          if r.get("stock_return_pct") is not None and r.get("action") != "0"])
    avg_ret  = round(sum(all_rets) / len(all_rets), 2) if all_rets else None
    med_ret  = round(all_rets[len(all_rets) // 2], 2) if all_rets else None
    latest_ep = max((r.get("episode_id", "") for r in results if r.get("episode_id")), key=_ep_num, default="N/A")

    def _fs(v, pct=True):
        if v is None: return "N/A"
        color = "#d9534f" if v >= 0 else "#2b8a3e"
        sign  = "+" if v >= 0 else ""
        suf   = "%" if pct else ""
        return f'<span style="color:{color};">{sign}{v}{suf}</span>'

    avg_ret_html = _fs(avg_ret)
    med_ret_html = _fs(med_ret)

    # ── 趨勢圖資料（累計勝率按集數） ──────────────────────────
    eps_sorted = sorted({r.get("episode_id", "") for r in results if r.get("episode_id")}, key=_ep_num)
    trend_labels, trend_values = [], []
    cum_dec = cum_wins = 0
    for ep in eps_sorted:
        ep_dec    = [r for r in results if r.get("episode_id") == ep and r.get("beat_benchmark") is not None]
        cum_dec  += len(ep_dec)
        cum_wins += sum(1 for r in ep_dec if r["beat_benchmark"])
        if cum_dec > 0:
            trend_labels.append(ep)
            trend_values.append(round(cum_wins / cum_dec * 100, 1))
    trend_labels_json = json.dumps(trend_labels, ensure_ascii=False)
    trend_values_json = json.dumps(trend_values)

    # ── Signals JSON for JS stock tab ──────────────────────────
    _sigs = []
    for r in results:
        code  = r.get("stock_code") or ""
        is_tw = code.endswith(".TW") or code.endswith(".TWO")
        ep_id = r.get("episode_id", "")
        _sigs.append({
            "ep_num":           _ep_num(ep_id),
            "episode_id":       ep_id,
            "stock_name":       r.get("stock_name") or "",
            "stock_code":       code,
            "action":           r.get("action", "0"),
            "primary_tag":      r.get("primary_tag") or "",
            "beat_benchmark":   r.get("beat_benchmark"),
            "stock_return_pct": r.get("stock_return_pct"),
            "is_tw":            is_tw,
        })
    signals_json = json.dumps(_sigs, ensure_ascii=False)

    # ── Build ep rows ─────────────────────────────────────────
    all_tags   = sorted({r.get("primary_tag", "") for r in results if r.get("primary_tag")})
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
        f'<button onclick="filterTag(\'{t}\')" class="filter-btn cls-btn"'
        f' style="margin:2px 3px;padding:4px 10px;border:1px solid #ddd;border-radius:12px;'
        f'background:#fff;cursor:pointer;font-size:13px;">{t}</button>'
        for t in all_tags
    )

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<style>
  body{{margin:0;padding:0;background:#f4f6f9;font-family:Arial,Helvetica,sans-serif;color:#333;}}
  .wrap{{max-width:920px;margin:20px auto;background:#fff;border-radius:8px;box-shadow:0 4px 12px rgba(0,0,0,.07);overflow-x:clip;}}
  @media(max-width:600px){{.wrap{{margin:0;border-radius:0;}}}}
  th{{cursor:pointer;user-select:none;}}
  th:hover{{background:#e2e6ea;}}
  .btn-active{{background:#1a252f!important;color:#fff!important;border-color:#1a252f!important;}}
  tr.ep-row.hidden{{display:none;}}
  .tab-btn{{margin:0 4px;padding:6px 16px;border:1px solid #ddd;border-radius:6px;background:#fff;cursor:pointer;font-size:14px;font-weight:bold;}}
  .fs-btn{{margin:0 2px;padding:4px 10px;border:1px solid #ddd;border-radius:6px;background:#fff;cursor:pointer;font-weight:bold;}}
  .filter-btn{{margin:2px 3px;padding:4px 10px;border:1px solid #ddd;border-radius:12px;background:#fff;cursor:pointer;font-size:13px;}}
</style>
<style id="dyn-font"></style>
</head>
<body>
<div class="wrap">

  <!-- Header -->
  <div style="background:#1a252f;padding:20px;text-align:center;color:#fff;border-radius:8px 8px 0 0;">
    <div style="font-size:22px;font-weight:bold;">股癌訊號勝率追蹤</div>
    <div style="color:#b3c1cd;font-size:13px;margin-top:4px;">{title} · {today} · 最新分析至 {latest_ep}</div>
  </div>

  <!-- Stats 第一列 -->
  <div style="display:flex;text-align:center;border-bottom:1px solid #eee;">
    <div style="flex:1;padding:14px 0;">
      <div style="font-size:12px;color:#999;">總訊號</div>
      <div style="font-size:24px;font-weight:bold;color:#2c3e50;">{stats['total']}</div>
    </div>
    <div style="flex:1;padding:14px 0;border-left:1px solid #eee;border-right:1px solid #eee;">
      <div style="font-size:12px;color:#999;">對標大盤勝率</div>
      <div style="font-size:24px;font-weight:bold;color:{win_color};">{win_pct}%</div>
    </div>
    <div style="flex:1;padding:14px 0;border-right:1px solid #eee;">
      <div style="font-size:12px;color:#999;">Win / Lose</div>
      <div style="font-size:22px;font-weight:bold;">
        <span style="color:#d9534f;">{stats['wins']}</span>
        <span style="color:#ccc;"> / </span>
        <span style="color:#2b8a3e;">{stats['losses']}</span>
      </div>
    </div>
    <div style="flex:1;padding:14px 0;">
      <div style="font-size:12px;color:#999;">待定</div>
      <div style="font-size:24px;font-weight:bold;color:#aaa;">{stats['total'] - stats['decided']}</div>
    </div>
  </div>

  <!-- Stats 第二列 -->
  <div style="display:flex;text-align:center;border-bottom:1px solid #eee;background:#fafcff;">
    <div style="flex:1;padding:10px 0;">
      <div style="font-size:11px;color:#aaa;">均個股報酬</div>
      <div style="font-size:17px;" title="播出日收盤價→今日收盤價漲跌幅，未扣手續費">{avg_ret_html}</div>
      <div style="font-size:10px;color:#ccc;margin-top:2px;">播出日→今日，未扣費</div>
    </div>
    <div style="flex:1;padding:10px 0;border-left:1px solid #eee;">
      <div style="font-size:11px;color:#aaa;">中位數報酬</div>
      <div style="font-size:17px;" title="排除極端值，更能反映典型表現">{med_ret_html}</div>
      <div style="font-size:10px;color:#ccc;margin-top:2px;">排除極端值</div>
    </div>
  </div>
  <!-- 計算說明 -->
  <div style="padding:6px 20px 10px;background:#fafcff;font-size:11px;color:#bbb;border-bottom:1px solid #eee;">
    個股報酬＝播出日收盤價至今漲跌幅；對標大盤＝同期 0050（台股）或 SPY（美股）漲跌幅；未扣除手續費
  </div>

  <!-- 趨勢圖 -->
  <div style="padding:14px 20px 10px;border-bottom:1px solid #eee;">
    <div style="font-size:12px;color:#999;margin-bottom:6px;font-weight:bold;">累計勝率趨勢（對標大盤）</div>
    <div style="position:relative;height:150px;">
      <canvas id="trendChart"></canvas>
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
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;flex-wrap:wrap;">
      <span style="font-size:13px;color:#888;white-space:nowrap;">搜尋：</span>
      <input id="main-search" type="text"
        placeholder="集數、標的、代碼、主委觀點..."
        oninput="filterSearch(this.value)"
        style="flex:1;max-width:340px;padding:5px 12px;border:1px solid #ddd;border-radius:12px;font-size:13px;outline:none;">
      <button onclick="clearSearch()" class="filter-btn" style="color:#888;">清除</button>
    </div>
    <div style="margin-bottom:4px;">
      <span style="font-size:12px;color:#aaa;margin-right:4px;">分類：</span>
      <button onclick="filterTag('all')" id="btn-all" class="filter-btn cls-btn btn-active">全部</button>
      <button onclick="filterMkt('tw')" class="filter-btn cls-btn">台股</button>
      <button onclick="filterMkt('us')" class="filter-btn cls-btn">美股</button>
      {tag_btns}
    </div>
    <div style="margin-bottom:4px;">
      <span style="font-size:12px;color:#aaa;margin-right:4px;">勝負：</span>
      <button onclick="filterBeat('all')"  id="beat-all"  class="filter-btn beat-btn btn-active">全部</button>
      <button onclick="filterBeat('win')"  id="beat-win"  class="filter-btn beat-btn">獲勝</button>
      <button onclick="filterBeat('lose')" id="beat-lose" class="filter-btn beat-btn">落後</button>
      <button onclick="filterBeat('tbd')"  id="beat-tbd"  class="filter-btn beat-btn">待定</button>
    </div>
    <div style="margin-bottom:4px;">
      <span style="font-size:12px;color:#aaa;margin-right:4px;">持倉天數：</span>
      <button onclick="filterDays(0)"  id="days-0"  class="filter-btn days-btn btn-active">全部</button>
      <button onclick="filterDays(30)" id="days-30" class="filter-btn days-btn">≥30天</button>
      <button onclick="filterDays(60)" id="days-60" class="filter-btn days-btn">≥60天</button>
      <button onclick="filterDays(90)" id="days-90" class="filter-btn days-btn">≥90天</button>
    </div>
    <div style="font-size:11px;color:#ccc;">台股對比 0050.TW · 美股對比 SPY</div>
  </div>

  <!-- 以集數 Table -->
  <div id="view-ep" style="padding:0 0 12px;overflow-x:auto;-webkit-overflow-scrolling:touch;">
    <table id="main-table" style="width:100%;border-collapse:collapse;font-size:15px;min-width:720px;">
      <thead>
        <tr style="background:#f1f3f5;color:#495057;font-size:13px;">
          <th onclick="sortBy('epnum')" style="padding:10px 12px;text-align:left;">集數 ↕</th>
          <th onclick="sortBy('tag')"   style="padding:10px 12px;text-align:left;">分類 ↕</th>
          <th style="padding:10px 12px;text-align:left;">標的</th>
          <th style="padding:10px 12px;text-align:left;">動作</th>
          <th onclick="sortBy('date')"  style="padding:10px 12px;text-align:left;">進場日 ↕</th>
          <th onclick="sortBy('spct')"  style="padding:10px 12px;text-align:left;">個股報酬 ↕</th>
          <th onclick="sortBy('bpct')"  style="padding:10px 12px;text-align:left;">同期大盤 ↕</th>
          <th onclick="sortBy('days')"  style="padding:10px 12px;text-align:center;">天數 ↕</th>
          <th onclick="sortBy('beat')"  style="padding:10px 12px;text-align:left;">勝負 ↕</th>
        </tr>
      </thead>
      <tbody id="tbody">{table_rows}</tbody>
    </table>
  </div>

  <!-- 以標的 Table (JS driven) -->
  <div id="view-stock" style="display:none;padding:0 0 12px;">
    <div style="padding:10px 16px;border-bottom:1px solid #eee;background:#fafafa;display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
      <span style="font-size:13px;color:#888;">範圍：</span>
      <button id="sr-0"   class="filter-btn sr-btn btn-active" onclick="setStockRange(0)">全部</button>
      <button id="sr-100" class="filter-btn sr-btn" onclick="setStockRange(100)">最新 100 集</button>
      <button id="sr-50"  class="filter-btn sr-btn" onclick="setStockRange(50)">最新 50 集</button>
      <button id="sr-20"  class="filter-btn sr-btn" onclick="setStockRange(20)">最新 20 集</button>
      <span style="font-size:12px;color:#bbb;margin-left:6px;">點標的名稱可展開詳情</span>
    </div>
    <div id="stock-table-container" style="overflow-x:auto;-webkit-overflow-scrolling:touch;"></div>
  </div>

  <!-- Footer -->
  <div style="padding:10px;text-align:center;font-size:12px;color:#bbb;border-top:1px solid #f0f0f0;">
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
  document.querySelectorAll('.fs-btn').forEach((b, i) => b.classList.toggle('btn-active', i === fsIdx));
  localStorage.setItem('fs-idx', fsIdx);
}}
function setFontSize(i) {{ fsIdx = i; applyFontSize(); }}
document.addEventListener('DOMContentLoaded', () => {{ applyFontSize(); initChart(); }});

// ── Tab 切換 ─────────────────────────────────────────────
function switchTab(tab) {{
  const isEp = tab === 'ep';
  document.getElementById('view-ep').style.display = isEp ? '' : 'none';
  document.getElementById('view-filters').style.display = isEp ? '' : 'none';
  document.getElementById('view-stock').style.display = isEp ? 'none' : '';
  document.getElementById('tab-ep').classList.toggle('btn-active', isEp);
  document.getElementById('tab-stock').classList.toggle('btn-active', !isEp);
  if (!isEp) renderStockTab();
}}

// ── 集數展開/收合 ─────────────────────────────────────────
function toggleEp(ep) {{
  const rows = document.querySelectorAll('.ep-' + ep);
  const hdr  = document.querySelector('.ep-header[data-ep="' + ep + '"] td');
  const collapsed = rows[0] && rows[0].classList.contains('hidden');
  rows.forEach(r => r.classList.toggle('hidden', !collapsed));
  if (hdr) hdr.innerHTML = hdr.innerHTML.replace(/[▾▸]/, collapsed ? '▾' : '▸');
}}

// ── 搜尋 ──────────────────────────────────────────────────
let searchFilter = '';
function filterSearch(val) {{ searchFilter = val.trim().toLowerCase(); applyAllFilters(); }}
function clearSearch() {{ searchFilter = ''; document.getElementById('main-search').value = ''; applyAllFilters(); }}

// ── 篩選狀態 ──────────────────────────────────────────────
let tagFilter = 'all', mktFilter = 'all', beatFilter = 'all', daysFilter = 0;

function filterTag(tag) {{
  tagFilter = tag; mktFilter = 'all';
  document.querySelectorAll('.cls-btn').forEach(b => b.classList.remove('btn-active'));
  event.target.classList.add('btn-active');
  applyAllFilters();
}}
function filterMkt(mkt) {{
  mktFilter = mkt; tagFilter = 'all';
  document.querySelectorAll('.cls-btn').forEach(b => b.classList.remove('btn-active'));
  event.target.classList.add('btn-active');
  applyAllFilters();
}}
function filterBeat(val) {{
  beatFilter = val;
  document.querySelectorAll('.beat-btn').forEach(b => b.classList.remove('btn-active'));
  document.getElementById('beat-' + val).classList.add('btn-active');
  applyAllFilters();
}}
function filterDays(n) {{
  daysFilter = n;
  document.querySelectorAll('.days-btn').forEach(b => b.classList.remove('btn-active'));
  document.getElementById('days-' + n).classList.add('btn-active');
  applyAllFilters();
}}

function applyAllFilters() {{
  document.querySelectorAll('.ep-row').forEach(r => {{
    const kwMatch   = !searchFilter || (r.dataset.kw || '').toLowerCase().includes(searchFilter);
    const tagMatch  = tagFilter === 'all' || r.dataset.tag === tagFilter;
    const mktMatch  = mktFilter === 'all' || r.dataset.mkt === mktFilter;
    const beat      = parseInt(r.dataset.beat);
    const beatMatch = beatFilter === 'all'
      || (beatFilter === 'win'  && beat === 1)
      || (beatFilter === 'lose' && beat === 0)
      || (beatFilter === 'tbd'  && beat === -1);
    const days      = parseInt(r.dataset.days);
    const daysMatch = daysFilter === 0 || days >= daysFilter;
    r.classList.toggle('hidden', !(kwMatch && tagMatch && mktMatch && beatMatch && daysMatch));
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

// ── 欄位排序（以集數）─────────────────────────────────────
let sortDir = {{}};
function sortBy(col) {{
  const tbody = document.getElementById('tbody');
  const dir   = (sortDir[col] === 1) ? -1 : 1;
  sortDir[col] = dir;
  const rowVal = r => {{
    if (col === 'epnum') return parseInt(r.dataset.epnum);
    if (col === 'spct')  return parseFloat(r.dataset.spct);
    if (col === 'bpct')  return parseFloat(r.dataset.bpct);
    if (col === 'beat')  return parseInt(r.dataset.beat);
    if (col === 'days')  return parseInt(r.dataset.days);
    if (col === 'date')  return r.querySelector('td:nth-child(5)') ? r.querySelector('td:nth-child(5)').innerText : '';
    if (col === 'tag')   return r.dataset.tag || '';
    return 0;
  }};
  if (col === 'epnum') {{
    const headers = [...tbody.querySelectorAll('.ep-header')];
    const groups  = headers.map(h => {{
      const ep = h.dataset.ep;
      return {{ header: h, rows: [...tbody.querySelectorAll('.ep-' + CSS.escape(ep))], epnum: parseInt(ep.replace(/[^0-9]/g,'')) }};
    }});
    groups.sort((a,b) => (a.epnum - b.epnum) * dir);
    groups.forEach(g => {{ tbody.appendChild(g.header); g.rows.forEach(r => tbody.appendChild(r)); }});
  }} else {{
    const headers = [...tbody.querySelectorAll('.ep-header')];
    headers.map(h => {{
      const ep = h.dataset.ep;
      return {{ header: h, rows: [...tbody.querySelectorAll('.ep-' + CSS.escape(ep))] }};
    }}).forEach(g => {{
      g.rows.sort((a,b) => (rowVal(a) > rowVal(b) ? dir : rowVal(a) < rowVal(b) ? -dir : 0));
      tbody.appendChild(g.header);
      g.rows.forEach(r => tbody.appendChild(r));
    }});
  }}
}}

// ── 以標的 JS 動態渲染 ────────────────────────────────────
const SIGNALS_DATA = {signals_json};
let _sr = 0, _sCol = 'total', _sDir = -1;

function setStockRange(n) {{
  _sr = n;
  document.querySelectorAll('.sr-btn').forEach(b => b.classList.remove('btn-active'));
  document.getElementById('sr-' + n).classList.add('btn-active');
  renderStockTab();
}}
function sortStock(col) {{
  _sDir = (_sCol === col) ? -_sDir : -1;
  _sCol = col;
  renderStockTab();
}}

function renderStockTab() {{
  const allNums = [...new Set(SIGNALS_DATA.map(s => s.ep_num))].sort((a,b)=>a-b);
  const keep    = _sr === 0 ? new Set(allNums) : new Set(allNums.slice(-_sr));
  const filt    = SIGNALS_DATA.filter(s => keep.has(s.ep_num));

  const gmap = {{}};
  filt.forEach(s => {{
    if (!s.stock_code) return;
    if (!gmap[s.stock_code]) gmap[s.stock_code] = {{ code: s.stock_code, name: s.stock_name, mkt: s.is_tw ? '台股' : '美股', sigs: [] }};
    gmap[s.stock_code].sigs.push(s);
  }});

  const groups = Object.values(gmap).map(g => {{
    const dec  = g.sigs.filter(s => s.beat_benchmark !== null && s.beat_benchmark !== undefined);
    const wins = dec.filter(s => s.beat_benchmark === true).length;
    const rets = g.sigs.filter(s => s.stock_return_pct !== null && s.stock_return_pct !== undefined).map(s => s.stock_return_pct);
    return {{
      ...g, total: g.sigs.length,
      bull: g.sigs.filter(s=>s.action==='+1').length,
      bear: g.sigs.filter(s=>s.action==='-1').length,
      wins, dec: dec.length,
      win_rate: dec.length ? Math.round(wins/dec.length*1000)/10 : null,
      avg_ret:  rets.length ? Math.round(rets.reduce((a,b)=>a+b,0)/rets.length*100)/100 : null,
      latest:   Math.max(...g.sigs.map(s=>s.ep_num)),
    }};
  }}).sort((a,b) => {{
    const va = a[_sCol] ?? -9999, vb = b[_sCol] ?? -9999;
    return (va > vb ? 1 : va < vb ? -1 : 0) * _sDir;
  }});

  if (!groups.length) {{
    document.getElementById('stock-table-container').innerHTML =
      "<div style='padding:20px;color:#888;text-align:center;'>此範圍內無標的資料</div>";
    return;
  }}

  const fp  = v => v == null ? 'N/A' : (v >= 0 ? '+' : '') + v.toFixed(2) + '%';
  const fc  = v => v == null ? '#888' : v >= 0 ? '#d9534f' : '#2b8a3e';
  const arr = c => c === _sCol ? (_sDir === -1 ? ' ↓' : ' ↑') : ' ↕';

  const rows = groups.map((g, idx) => {{
    const wrC   = g.win_rate !== null && g.win_rate >= 50 ? '#d9534f' : '#2b8a3e';
    const wrT   = g.win_rate !== null ? g.win_rate + '%' : '待定';
    const bb    = [g.bull ? '+'+g.bull : '', g.bear ? '-'+g.bear : ''].filter(Boolean).join(' / ');
    const chips = [...new Set(g.sigs.map(s=>s.ep_num))].sort((a,b)=>a-b).map(n=>
      `<span style="font-size:11px;background:#f0f0f0;padding:1px 5px;border-radius:3px;margin:1px 2px;display:inline-block;">EP${{n}}</span>`
    ).join('');
    const actLbl = s => s.action==='+1' ? '看好' : s.action==='-1' ? '看壞' : '中性';
    const beatLbl = s => s.beat_benchmark===true ? '✅' : s.beat_benchmark===false ? '❌' : '⏳';
    const detailHtml = g.sigs.map(s => `
      <tr class="sd-${{idx}}" style="display:none;background:#f8f9fa;">
        <td colspan="8" style="padding:5px 12px 5px 28px;border-bottom:1px solid #f0f0f0;font-size:13px;color:#555;">
          <span style="color:#888;margin-right:6px;">EP${{s.ep_num}}</span>
          ${{actLbl(s)}}
          <span style="margin:0 6px;color:#ccc;">|</span>
          <span style="color:${{fc(s.stock_return_pct)}};">${{fp(s.stock_return_pct)}}</span>
          <span style="margin-left:6px;">${{beatLbl(s)}}</span>
        </td>
      </tr>`).join('');
    return `<tr style="border-bottom:1px solid #f0f0f0;cursor:pointer;" onclick="toggleSD(${{idx}}, this)">
      <td style="padding:10px 12px;font-weight:bold;white-space:nowrap;">
        <span class="sd-arrow-${{idx}}">▸</span> ${{g.name}}<br><span style="color:#aaa;font-size:13px;">${{g.code}}</span></td>
      <td style="padding:10px 8px;color:#888;font-size:13px;">${{g.mkt}}</td>
      <td style="padding:10px 8px;text-align:center;font-weight:bold;">${{g.total}}</td>
      <td style="padding:10px 8px;text-align:center;color:#555;font-size:13px;">${{bb}}</td>
      <td style="padding:10px 8px;text-align:center;font-weight:bold;color:${{wrC}};">${{wrT}}</td>
      <td style="padding:10px 8px;text-align:center;font-weight:bold;color:${{fc(g.avg_ret)}};">${{fp(g.avg_ret)}}</td>
      <td style="padding:10px 8px;color:#888;font-size:13px;white-space:nowrap;">EP${{g.latest}}</td>
      <td style="padding:10px 8px;line-height:1.8;">${{chips}}</td>
    </tr>${{detailHtml}}`;
  }}).join('');

  document.getElementById('stock-table-container').innerHTML = `
  <table width="100%" style="border-collapse:collapse;font-size:15px;">
    <thead><tr style="background:#f1f3f5;color:#495057;font-size:13px;">
      <th onclick="sortStock('name')"     style="padding:10px 12px;text-align:left;cursor:pointer;">標的${{arr('name')}}</th>
      <th style="padding:10px 8px;text-align:left;">市場</th>
      <th onclick="sortStock('total')"    style="padding:10px 8px;text-align:center;cursor:pointer;">次數${{arr('total')}}</th>
      <th style="padding:10px 8px;text-align:center;">多/空</th>
      <th onclick="sortStock('win_rate')" style="padding:10px 8px;text-align:center;cursor:pointer;">勝率${{arr('win_rate')}}</th>
      <th onclick="sortStock('avg_ret')"  style="padding:10px 8px;text-align:center;cursor:pointer;">均報酬${{arr('avg_ret')}}</th>
      <th onclick="sortStock('latest')"   style="padding:10px 8px;text-align:left;cursor:pointer;">最近集${{arr('latest')}}</th>
      <th style="padding:10px 8px;text-align:left;">提及集數</th>
    </tr></thead>
    <tbody>${{rows}}</tbody>
  </table>`;
}}

function toggleSD(idx, clickedRow) {{
  const rows  = document.querySelectorAll('.sd-' + idx);
  const arrow = document.querySelector('.sd-arrow-' + idx);
  const open  = rows.length > 0 && rows[0].style.display === 'table-row';
  rows.forEach(r => r.style.display = open ? 'none' : 'table-row');
  if (arrow) arrow.textContent = open ? '▸' : '▾';
}}

// ── 趨勢圖 ────────────────────────────────────────────────
function initChart() {{
  const ctx = document.getElementById('trendChart');
  if (!ctx || typeof Chart === 'undefined') return;
  new Chart(ctx, {{
    type: 'line',
    data: {{
      labels: {trend_labels_json},
      datasets: [
        {{
          label: '累計勝率',
          data: {trend_values_json},
          borderColor: '#1a252f',
          backgroundColor: 'rgba(26,37,47,0.07)',
          borderWidth: 2,
          pointRadius: 3,
          tension: 0.3,
          fill: true,
        }},
        {{
          label: '50% 基準',
          data: Array({len(trend_labels)}).fill(50),
          borderColor: '#e74c3c',
          borderWidth: 1,
          borderDash: [4,4],
          pointRadius: 0,
          fill: false,
        }}
      ]
    }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{ callbacks: {{ label: c => c.dataset.label + ': ' + c.parsed.y + '%' }} }}
      }},
      scales: {{
        x: {{ ticks: {{ maxTicksLimit: 10, font: {{ size: 11 }} }}, grid: {{ display: false }} }},
        y: {{ min: 0, max: 100, ticks: {{ callback: v => v + '%', font: {{ size: 11 }} }} }}
      }}
    }}
  }});
}}
</script>
</body>
</html>"""


# ── 簡要版 HTML（Gmail）──────────────────────────────────────────────────────

def _pbar(pct: float, color: str = "#d9534f") -> str:
    """純 HTML 進度條，email 相容。"""
    w = min(max(round(pct), 0), 100)
    rest = 100 - w
    return (
        f'<table width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="border-radius:4px;overflow:hidden;background:#eee;">'
        f'<tr>'
        f'<td width="{w}%" style="background:{color};height:10px;font-size:0;line-height:0;">&nbsp;</td>'
        f'<td style="height:10px;font-size:0;line-height:0;"></td>'
        f'</tr></table>'
    )


def generate_html_email(results: list[dict], title: str, stats: dict,
                        detail_url: str = "") -> str:
    today   = date.today().isoformat()
    win_pct = stats.get("win_rate", 0)
    win_color = "#d9534f" if win_pct >= 50 else "#2b8a3e"

    # ── 額外統計 ─────────────────────────────────────────────

    # ── 本週最新訊號（最新 2 集，僅看多/看空，排除中立）────────
    eps_sorted     = sorted({r["episode_id"] for r in results if r.get("episode_id")}, key=_ep_num)
    latest_ep_ids  = set(eps_sorted[-2:])
    latest_signals = [
        r for r in results
        if r.get("episode_id") in latest_ep_ids and r.get("action") in ("+1", "-1")
    ]
    latest_signals.sort(key=lambda r: (
        -_ep_num(r.get("episode_id", "")),
        0 if r.get("confidence_level") == "High" else 1,
        r.get("action") != "+1",
    ))

    latest_cards = ""
    for r in latest_signals:
        action  = r.get("action", "0")
        conf    = r.get("confidence_level", "")
        name    = r.get("stock_name", "")
        code    = r.get("stock_code", "")
        ep      = r.get("episode_id", "")
        reason  = (r.get("raw_reason") or "").strip()[:90]
        if reason and len(r.get("raw_reason", "")) > 90:
            reason += "..."
        quote   = (r.get("exact_quote") or "").strip()[:120]
        if quote and len(r.get("exact_quote", "")) > 120:
            quote += "..."
        entry_d = r.get("entry_date") or ""

        if action == "+1" and conf == "High":
            badge_txt = "超級看好"
            border_c  = "#c0392b"
            bg_c      = "#fff5f5"
        elif action == "+1":
            badge_txt = "看好"
            border_c  = "#d9534f"
            bg_c      = "#fff8f8"
        else:
            badge_txt = "看壞"
            border_c  = "#888"
            bg_c      = "#f8f9fa"

        latest_cards += f"""
          <div style="background:{bg_c};border-left:6px solid {border_c};
                      padding:20px 22px;margin-bottom:14px;border-radius:0 8px 8px 0;">
            <table width="100%" cellpadding="0" cellspacing="0" border="0">
              <tr>
                <td>
                  <span style="font-weight:bold;font-size:24px;color:#1a252f;">{name}</span>
                  <span style="color:#bbb;font-size:14px;margin-left:10px;">{code}</span>
                </td>
                <td align="right" style="vertical-align:top;">
                  <span style="background:{border_c};color:#fff;font-size:14px;font-weight:bold;
                               padding:6px 14px;border-radius:5px;">{badge_txt}</span>
                  <br><span style="color:#bbb;font-size:13px;margin-top:4px;display:block;">{ep}</span>
                </td>
              </tr>
            </table>
            {'<div style="color:#333;font-size:16px;margin-top:12px;line-height:1.7;">' + reason + '</div>' if reason else ''}
            {'<div style="margin-top:10px;padding:12px 16px;background:rgba(0,0,0,.04);border-radius:6px;color:#777;font-style:italic;font-size:15px;line-height:1.7;">「' + quote + '」</div>' if quote else ''}
            {'<div style="color:#ccc;font-size:13px;margin-top:8px;">進場日 ' + entry_d + '</div>' if entry_d else ''}
          </div>"""

    latest_section = ""
    if latest_cards:
        latest_ep_label = "、".join(sorted(latest_ep_ids, key=_ep_num))
        latest_section = f"""
        <tr>
          <td style="padding:28px 24px 12px;">
            <div style="font-size:18px;font-weight:bold;color:#1a252f;margin-bottom:16px;">
              🔥 本週最新訊號
              <span style="font-size:14px;font-weight:normal;color:#aaa;margin-left:8px;">{latest_ep_label}</span>
            </div>
            {latest_cards}
          </td>
        </tr>
        <tr><td><div style="height:1px;background:#f0f0f0;"></div></td></tr>"""

    # ── 績效儀表板 ───────────────────────────────────────────
    overall_bar = _pbar(win_pct)

    dashboard = f"""
        <tr>
          <td style="padding:24px 24px 20px;">
            <div style="font-size:18px;font-weight:bold;color:#1a252f;margin-bottom:6px;">
              📊 績效儀表板
            </div>
            <div style="font-size:13px;color:#bbb;margin-bottom:18px;line-height:1.8;">
              <b style="color:#aaa;">勝率</b>：主委看好/看壞的標的，個股漲跌是否跑贏同期大盤（台股 0050，美股 SPY）<br>
              <b style="color:#aaa;">個股報酬</b>：集數播出日收盤價 → 今日最新收盤價的漲跌幅，未扣手續費
            </div>
            <table width="100%" cellpadding="0" cellspacing="0" border="0">
              <tr>
                <td width="110" style="font-size:15px;color:#555;padding-bottom:8px;vertical-align:top;padding-top:4px;">
                  整體勝率<br><span style="font-size:13px;color:#bbb;">全部看多看空</span>
                </td>
                <td style="padding-bottom:8px;">
                  <div style="margin-bottom:6px;">{overall_bar}</div>
                  <span style="font-size:32px;font-weight:bold;color:{win_color};">{win_pct}%</span>
                  <span style="font-size:14px;color:#aaa;margin-left:10px;">{stats['wins']}勝 / {stats['losses']}負 / {stats['total']-stats['decided']}待定</span>
                </td>
              </tr>
            </table>
          </td>
        </tr>
        <tr><td><div style="height:1px;background:#f0f0f0;"></div></td></tr>"""

    # ── 查看完整報告按鈕 ─────────────────────────────────────
    detail_btn = ""
    if detail_url:
        detail_btn = f"""
        <tr>
          <td align="center" style="padding:20px 24px 16px;">
            <a href="{detail_url}"
               style="display:inline-block;padding:16px 40px;background:#d9534f;
                      color:#fff;text-decoration:none;border-radius:8px;
                      font-size:18px;font-weight:bold;letter-spacing:0.5px;">
              查看完整報告 →
            </a>
          </td>
        </tr>
        <tr><td><div style="height:1px;background:#f0f0f0;"></div></td></tr>"""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f6f9;font-family:Arial,Helvetica,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" border="0">
  <tr>
    <td align="center" style="padding:24px 10px;">
      <table width="620" cellpadding="0" cellspacing="0" border="0"
             style="background:#fff;border-radius:10px;overflow:hidden;
                    box-shadow:0 2px 12px rgba(0,0,0,.1);">

        <!-- Header -->
        <tr>
          <td style="background:#1a252f;padding:28px 24px;text-align:center;">
            <div style="font-size:26px;font-weight:bold;color:#fff;letter-spacing:0.5px;">股癌訊號勝率追蹤</div>
            <div style="color:#b3c1cd;font-size:15px;margin-top:6px;">{title} · {today}</div>
          </td>
        </tr>

        <!-- 查看完整報告（最頂） -->
        {detail_btn}

        <!-- 績效儀表板 -->
        {dashboard}

        <!-- 本週最新訊號 -->
        {latest_section}

        <!-- Footer -->
        <tr>
          <td style="padding:16px;text-align:center;font-size:13px;color:#bbb;
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

