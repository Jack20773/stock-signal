"""
HTML 報告生成模組（詳細版＋Email 版）。
由 notifier.py 呼叫；不直接執行。
"""
import html
import json
import logging
import os
import re
import shutil
import statistics
from datetime import date, timedelta

import attention
import prices

# ── 小工具 ──────────────────────────────────────────────────────────────────


def _esc(s) -> str:
    """2026-08-02 完工前 Codex 覆核指出：generate_html_email() 把 Gemini 分析結果
    的 stock_name/stock_code/raw_reason/exact_quote 直接用 f-string 塞進 email
    HTML，完全沒有跳脫——詳細版（JS 端 escapeHtml()，見 renderDetailTab()/
    renderStockTab()）已經修過同一類問題，這裡是 Python 端另一條輸出路徑，
    同樣風險、需要同樣的防護。用 Python 內建 html.escape() 跳脫 & < > " '。"""
    return html.escape(str(s or ""))

def _json_for_script(data, **kw) -> str:
    """給要塞進 <script> 標籤內的 JSON 字串用，把 '<' 轉成 \\u003c。

    signals_json 裡的 raw_reason/exact_quote 來自 Gemini 分析結果，內容源頭是
    Podcast 逐字稿——理論上不是使用者直接輸入，但這份 HTML 最終會被
    workflow push 到 GitHub Pages 公開頁面（見 notifier.py 的呼叫端），任何
    分析文字若剛好含有字面上的 "</script>"（例如逐字稿裡真的講到這個詞、
    或未來換一顆更容易被誘導輸出奇怪內容的模型），沒有跳脫就會提前結束
    script 區塊、後面的內容被當成 HTML 解析，等於一個儲存型 XSS 缺口。
    跳脫 '<' 不影響 JSON 語義（合法的 JSON 跳脫），瀏覽器解析出來的值
    跟原本完全一樣，純粹是防禦，不改變任何功能行為。
    2026-08-01 Codex 審查發現，索羅門本地修正。"""
    return json.dumps(data, **kw).replace("<", "\\u003c")


def _ep_num(ep: str) -> int:
    m = re.search(r"\d+", ep)
    return int(m.group()) if m else 0


# 三個獨立靜態頁面（報告/關注度/逐字稿）共用的導覽 tab 列（2026-08-02 索羅門
# 新增，任務1e）。三頁各自獨立生成（無SPA路由、無共用JS bundle），「分頁籤」
# 用「視覺上像tab、實際是三個獨立超連結」實作，href 對應 GitHub Pages 部署後
# 的實際檔名（見 .github/workflows/*.yml：report_detail.html→index.html、
# report_attention.html→attention.html、report_transcripts.html→
# transcripts.html）。用同一個函式產生，避免三處各寫一份風格漂移。
# Email版（generate_html_email()）不加這個——Email是獨立情境，比照1e任務檔
# 明確排除慣例。
_NAV_TABS = (
    ("report",      "index.html",       "📊 訊號報告"),
    ("attention",   "attention.html",   "🔥 目前關注度"),
    ("transcripts", "transcripts.html", "📄 逐字稿"),
)


def _render_nav_tabs(active: str) -> str:
    items = "".join(
        f'<a href="{href}" class="nav-tab{" nav-tab-active" if key == active else ""}">{label}</a>'
        for key, href, label in _NAV_TABS
    )
    return f'<div class="nav-tabs">{items}</div>'


_NAV_TABS_CSS = """
  .nav-tabs{display:flex;gap:6px;padding:8px 12px;background:#14202b;}
  .nav-tab{flex:1;text-align:center;padding:8px 4px;border-radius:6px;font-size:13px;
    color:#b3c1cd;text-decoration:none;background:rgba(255,255,255,.06);white-space:nowrap;}
  .nav-tab:hover{background:rgba(255,255,255,.12);}
  .nav-tab-active{background:#2b6cb0;color:#fff;font-weight:bold;}
  @media(max-width:600px){.nav-tab{font-size:11px;padding:7px 2px;}}
"""


# 三頁共用的「怎麼看這份報告」新手導覽（2026-08-02 索羅門新增，任務1f）。
# 純前端 localStorage 判斷（key 三頁各自獨立，不共用，見下方 storage_key
# 參數），不需要後端/DB配合。首次造訪（key 不存在）預設展開；使用者按過
# 「關閉」後記住不再自動展開，但保留一個常駐右下角「？」按鈕可隨時重新
# 叫出（不會反過來清掉 localStorage，重新整理後仍維持收合，符合任務檔
# 完成的定義第2點的兩個獨立驗證點）。
_ONBOARD_CSS = """
  .onboard-wrap{border-bottom:1px solid #eee;background:#f7fbff;}
  .onboard-head{display:flex;align-items:center;gap:8px;padding:10px 16px;font-size:13px;
    color:#2b6cb0;font-weight:bold;}
  .onboard-body{padding:0 16px 14px;font-size:13px;color:#555;line-height:1.8;}
  .onboard-body ul{margin:4px 0 0;padding-left:18px;}
  .onboard-dismiss{margin-left:auto;font-weight:normal;color:#8fb3dc;font-size:12px;
    cursor:pointer;white-space:nowrap;}
  .onboard-dismiss:hover{color:#2b6cb0;}
  .onboard-fab{position:fixed;right:16px;bottom:16px;width:34px;height:34px;border-radius:50%;
    background:#2b6cb0;color:#fff;align-items:center;justify-content:center;
    font-size:16px;font-weight:bold;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.25);
    z-index:50;display:none;}
"""


def _render_onboarding(storage_key: str, heading: str, bullets: list[str]) -> str:
    items = "".join(f"<li>{_esc(b)}</li>" for b in bullets)
    return f'''
    <div class="onboard-wrap" id="onboard-wrap" style="display:none;">
      <div class="onboard-head">
        <span>💡 {_esc(heading)}</span>
        <span class="onboard-dismiss" onclick="onboardDismiss()">知道了，不用每次都顯示 ✕</span>
      </div>
      <div class="onboard-body"><ul>{items}</ul></div>
    </div>
    <div class="onboard-fab" id="onboard-fab" onclick="onboardReopen()" title="重新打開新手導覽">？</div>'''


def _onboard_js(storage_key: str) -> str:
    return f"""
const ONBOARD_KEY = {json.dumps(storage_key)};
function onboardInit() {{
  const dismissed = localStorage.getItem(ONBOARD_KEY) === '1';
  document.getElementById('onboard-wrap').style.display = dismissed ? 'none' : '';
  document.getElementById('onboard-fab').style.display = dismissed ? 'flex' : 'none';
}}
function onboardDismiss() {{
  localStorage.setItem(ONBOARD_KEY, '1');
  document.getElementById('onboard-wrap').style.display = 'none';
  document.getElementById('onboard-fab').style.display = 'flex';
}}
function onboardReopen() {{
  document.getElementById('onboard-wrap').style.display = '';
  document.getElementById('onboard-fab').style.display = 'none';
}}
document.addEventListener('DOMContentLoaded', onboardInit);
"""


def _mini_bar(pct: float, color: str, label: str, n: int) -> str:
    w = min(max(round(pct), 0), 100)
    c = color if pct >= 50 else "#2b8a3e"
    return (
        f'<div style="margin-bottom:8px;">'
        f'<div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:3px;">'
        f'<span style="color:#555;">{label}</span>'
        f'<span style="font-weight:bold;color:{c};">{pct}%</span>'
        f'<span style="color:#ccc;font-size:11px;">{n}筆</span>'
        f'</div>'
        f'<div style="background:#eee;border-radius:3px;height:8px;overflow:hidden;">'
        f'<div style="background:{c};width:{w}%;height:8px;"></div>'
        f'</div></div>'
    )


def _conf_bars(high_wr, high_n, low_wr, low_n) -> str:
    rows = ""
    if high_wr is not None:
        rows += _mini_bar(high_wr, "#d9534f", "高信心（超級看好）", high_n)
    if low_wr is not None:
        rows += _mini_bar(low_wr, "#d9534f", "普通信心（看好/看壞）", low_n)
    return rows or '<span style="color:#ccc;font-size:12px;">尚無資料</span>'


def _hold_bars(hold_stats: dict) -> str:
    order = ["≤30天", "31–90天", "90天+"]
    rows = ""
    for g in order:
        if g in hold_stats:
            wr, n = hold_stats[g]
            rows += _mini_bar(wr, "#d9534f", g, n)
    return rows or '<span style="color:#ccc;font-size:12px;">尚無資料</span>'


# ── 詳細版 HTML（瀏覽器）────────────────────────────────────────────────────

def generate_html_detail(results: list[dict], title: str, stats: dict) -> str:
    # ── 增強版統計 ────────────────────────────────────────────
    bullish_dec = [r for r in results if r.get("action") == "+1" and r.get("beat_benchmark") is not None]
    bearish_dec = [r for r in results if r.get("action") == "-1" and r.get("beat_benchmark") is not None]
    all_rets    = sorted([r["stock_return_pct"] for r in results
                          if r.get("stock_return_pct") is not None and r.get("action") != "0"])
    avg_ret  = round(sum(all_rets) / len(all_rets), 2) if all_rets else None
    # 偶數筆數時原本只取「中間偏右」那一筆，不是統計學定義的中位數（該取中間兩筆
    # 平均）——2026-08-01 Codex 審查發現，改用 statistics.median 直接對齊定義。
    med_ret  = round(statistics.median(all_rets), 2) if all_rets else None
    latest_ep = max((r.get("episode_id", "") for r in results if r.get("episode_id")), key=_ep_num, default="N/A")

    # 信心等級準確率
    decided = [r for r in results if r.get("beat_benchmark") is not None and r.get("action") != "0"]
    high_dec = [r for r in decided if r.get("confidence_level") == "High"]
    low_dec  = [r for r in decided if r.get("confidence_level") != "High"]
    high_wr  = round(sum(1 for r in high_dec if r["beat_benchmark"]) / len(high_dec) * 100, 1) if high_dec else None
    low_wr   = round(sum(1 for r in low_dec  if r["beat_benchmark"]) / len(low_dec)  * 100, 1) if low_dec  else None

    # 持倉時間分組勝率
    def _hold_group(days):
        if days is None: return None
        return "≤30天" if days <= 30 else ("31–90天" if days <= 90 else "90天+")

    hold_groups: dict[str, list] = {"≤30天": [], "31–90天": [], "90天+": []}
    for r in decided:
        g = _hold_group(r.get("days_held"))
        if g:
            hold_groups[g].append(r)
    hold_stats = {
        g: (round(sum(1 for r in rs if r["beat_benchmark"]) / len(rs) * 100, 1), len(rs))
        for g, rs in hold_groups.items() if rs
    }

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
    # 先分組一次再逐集查表：原本每個集數都重新掃過整個 results（O(集數 × 總筆數)），
    # 集數與訊號數會隨時間持續成長，這裡改成先分組一次 O(N)，逐集查表變 O(1)
    # （2026-08-01 索羅門診斷發現，純本地邏輯變更，輸出不變，見驗證紀錄）。
    decided_by_ep: dict[str, list] = {}
    for r in results:
        ep = r.get("episode_id")
        if ep and r.get("beat_benchmark") is not None:
            decided_by_ep.setdefault(ep, []).append(r)
    trend_labels, trend_values = [], []
    cum_dec = cum_wins = 0
    for ep in eps_sorted:
        ep_dec    = decided_by_ep.get(ep, [])
        cum_dec  += len(ep_dec)
        cum_wins += sum(1 for r in ep_dec if r["beat_benchmark"])
        if cum_dec > 0:
            trend_labels.append(ep)
            trend_values.append(round(cum_wins / cum_dec * 100, 1))
    trend_labels_json = _json_for_script(trend_labels, ensure_ascii=False)
    trend_values_json = _json_for_script(trend_values)

    # ── Signals JSON：兩個 tab（以集數／以標的）共用同一份，前端 JS render ──
    _sigs = []
    for r in results:
        code  = r.get("stock_code") or ""
        is_tw = code.endswith(".TW") or code.endswith(".TWO")
        _sigs.append({
            "ep":         r.get("episode_id", ""),
            "ep_num":     _ep_num(r.get("episode_id", "")),
            "tag":        r.get("primary_tag") or "",
            "name":       r.get("stock_name") or "",
            "code":       code,
            "mkt":        "tw" if is_tw else "us",
            "action":     r.get("action", "0"),
            "conf":       r.get("confidence_level", ""),
            "entry_date": r.get("entry_date") or "",
            "entry_p":    r.get("live_entry_price") or r.get("entry_price"),
            "curr_p":     r.get("current_price"),
            "s_pct":      r.get("stock_return_pct"),
            "b_pct":      r.get("benchmark_return_pct"),
            "bm":         r.get("benchmark_ticker") or ("0050.TW" if is_tw else "SPY"),
            "beat":       r.get("beat_benchmark"),
            "days":       r.get("days_held"),
            "raw_reason": (r.get("raw_reason") or "").strip(),
            "quote":      (r.get("exact_quote") or "").strip(),
        })
    signals_json = _json_for_script(_sigs, ensure_ascii=False)

    # ── Sparkline 用歷史價格序列（2026-08-02 索羅門新增，任務1b）─────────────
    # 視窗定義（任務檔1b節，AI暫定+已核對渲染效果）：進場日→今日；持倉超過60個
    # 交易日只取最近60個交易日。每檔股票可能被多筆訊號（不同集數、不同進場日）
    # 提到，用「最早進場日」當序列起點——這是索羅門的聚合判斷（任務檔沒指定
    # 多筆訊號時用哪個進場日），跟卡片上「持倉天數」欄位（JS 端取最長天數）
    # 互相對應，兩者都反映「這檔從最早被提到到現在」的完整持有期間。
    # 下載時先把起點限制在「今日往前 100 個日曆天」內（涵蓋60個交易日的安全
    # 餘裕），避免對很久以前進場、早就超過視窗的標的下載整年份用不到的資料；
    # 下載完後不論這個 range 抓到幾筆，一律再 trim 到最近60筆，兩層保險確保
    # 序列長度符合定案規則。
    _SPARK_MAX_POINTS = 60
    _SPARK_LOOKBACK_CAP_DAYS = 100

    today_d = date.today()
    entry_by_code: dict[str, str] = {}
    for r in results:
        code    = r.get("stock_code") or ""
        entry_d = r.get("entry_date")
        if not code or not entry_d:
            continue
        if code not in entry_by_code or entry_d < entry_by_code[code]:
            entry_by_code[code] = entry_d

    price_series_reqs = []
    for code, entry_d in entry_by_code.items():
        try:
            entry_date_obj = date.fromisoformat(entry_d)
        except ValueError:
            continue
        cap_start = today_d - timedelta(days=_SPARK_LOOKBACK_CAP_DAYS)
        eff_start = max(entry_date_obj, cap_start)
        price_series_reqs.append((code, str(eff_start), str(today_d)))

    price_series: dict[str, list] = {}
    if price_series_reqs:
        try:
            raw_series = prices.batch_get_price_series(price_series_reqs)
            for code, pts in raw_series.items():
                price_series[code] = pts[-_SPARK_MAX_POINTS:] if len(pts) > _SPARK_MAX_POINTS else pts
        except Exception as ex:
            # sparkline 是加值資訊，不是報告能不能生成的關鍵路徑——yfinance 抓歷史
            # 序列失敗（網路/API限流等）不該讓整份報告生成失敗，只記警告、卡片
            # 改顯示「無足夠資料」（見前端 renderSparkline() 的 fallback）。
            logging.warning(f"[sparkline] 批次抓歷史價格序列失敗，本次報告卡片將無 sparkline：{ex}")
            price_series = {}

    price_series_json = _json_for_script(price_series, ensure_ascii=False)

    all_tags = sorted({r.get("primary_tag", "") for r in results if r.get("primary_tag")})

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
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<!-- 2026-08-11：本頁（站台首頁）原本沒有頁面標題也沒有主標題語意標籤，瀏覽器分頁與
     書籤只顯示網址、螢幕閱讀器抓不到主標題；另外兩頁都有。此處補上，視覺不變。 -->
<title>股癌訊號勝率追蹤</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<style>
  body{{margin:0;padding:0;background:#f4f6f9;font-family:Arial,Helvetica,sans-serif;color:#333;}}
  .wrap{{max-width:920px;margin:20px auto;background:#fff;border-radius:8px;box-shadow:0 4px 12px rgba(0,0,0,.07);overflow-x:clip;}}
  #main-table thead th{{position:sticky;top:0;background:#f1f3f5;z-index:2;}}
  @media(max-width:600px){{
    .wrap{{margin:0;border-radius:0;}}
    /* 手機版：拿掉表格最小寬度並藏次要欄位，讓內容塞進一屏、不用左右滑 */
    #main-table{{min-width:0!important;}}
    .hm{{display:none!important;}}
    .wrap th,.wrap td{{padding-left:6px!important;padding-right:6px!important;}}
    .reason-row td{{padding-left:12px!important;}}
    .wrap td{{word-break:break-word;}}
  }}
  th{{cursor:pointer;user-select:none;}}
  th:hover{{background:#e2e6ea;}}
  .btn-active{{background:#1a252f!important;color:#fff!important;border-color:#1a252f!important;}}
  tr.ep-row.hidden{{display:none;}}
  .fs-btn{{margin:0 2px;padding:4px 10px;border:1px solid #ddd;border-radius:6px;background:#fff;cursor:pointer;font-weight:bold;}}
  .filter-btn{{margin:2px 3px;padding:4px 10px;border:1px solid #ddd;border-radius:12px;background:#fff;cursor:pointer;font-size:13px;}}
  /* 個股排行卡片網格（2026-08-02 索羅門新增，任務1a：表格→卡片） */
  .card-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(148px,1fr));gap:10px;padding:12px 16px;}}
  .stock-card{{border:1px solid #eee;border-radius:8px;padding:12px;background:#fff;cursor:pointer;transition:box-shadow .15s;}}
  .stock-card:hover{{box-shadow:0 3px 10px rgba(0,0,0,.08);}}
  .sc-row1{{display:flex;align-items:center;justify-content:space-between;gap:6px;margin-bottom:2px;}}
  .sc-name{{font-size:14px;font-weight:bold;color:#1a252f;}}
  .sc-mkt-chip{{font-size:9.5px;font-weight:bold;padding:1px 5px;border-radius:4px;background:#f1f3f5;color:#888;margin-left:5px;white-space:nowrap;}}
  .sc-dir-chip{{font-size:10.5px;font-weight:bold;padding:2px 7px;border-radius:10px;border:1px solid #ddd;color:#666;white-space:nowrap;}}
  .sc-dir-chip.bull{{color:#d9534f;border-color:#f3c9c8;background:#fdecea;}}
  .sc-dir-chip.bear{{color:#1a6b9a;border-color:#c7e0f0;background:#e8f4fd;}}
  .sc-dir-chip.neutral{{color:#888;border-color:#ddd;background:#f5f5f5;}}
  .sc-code{{font-size:11px;color:#aaa;}}
  .sc-ret{{font-size:22px;font-weight:800;margin:8px 0 2px;letter-spacing:-.02em;}}
  .sc-ret.win{{color:#d9534f;}} .sc-ret.lose{{color:#2b8a3e;}} .sc-ret.pend{{color:#8a8f94;}}
  .sc-spark{{margin:6px 0 8px;}}
  .sc-meta{{display:flex;justify-content:space-between;font-size:11px;color:#999;}}
  .sc-detail{{display:none;grid-column:1/-1;background:#f8f9fa;border-radius:8px;padding:8px 14px;margin-top:-2px;border:1px solid #eee;font-size:13px;color:#555;}}
  .sc-detail-row{{padding:6px 0;border-bottom:1px solid #eee;}}
  .sc-detail-row:last-child{{border-bottom:none;}}
  .empty-state{{grid-column:1/-1;text-align:center;padding:30px 10px;color:#888;font-size:13px;}}
  /* ── 訊號帳本（2026-08-10 主次對調：原本收合的「依集數列表」升為主區，
       一筆訊號一張卡；個股排行降為收合次區。勝負一律以 beat 欄位為準，
       不再用 s_pct 的正負推導——看空訊號跌得比大盤多是「贏」，舊寫法會塗成輸）── */
  .led{{border-bottom:1px solid #eee;padding:13px 16px;cursor:pointer;}}
  .led:hover{{background:#fbfcfd;}}
  .led:focus-visible{{outline:2px solid #2a6fb0;outline-offset:-2px;}}
  .led-r1{{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;}}
  .led-nm{{font-size:16px;font-weight:700;color:#1a252f;}}
  .led-cd{{font-size:12px;color:#9aa4ad;}}
  .led-dir{{margin-left:auto;font-size:13px;font-weight:700;padding:2px 8px;border-radius:10px;white-space:nowrap;}}
  .led-dir.bull{{color:#8a8f94;background:#f2f4f6;}}
  .led-dir.bear{{color:#0d5c8a;background:#e2f1fb;border:1px solid #b9dcf2;}}
  .led-dir.neu{{color:#7a6a00;background:#fdf6dd;border:1px solid #ecdfa0;}}
  .led-r2{{font-size:12.5px;color:#7b858e;margin-top:3px;}}
  .led-q{{margin:8px 0 6px;padding:6px 10px;border-left:3px solid #dfe3e6;background:#fafbfc;
          font-size:14px;line-height:1.6;color:#4a5157;}}
  .led-st{{font-size:16px;font-weight:700;}}
  .led-st.win{{color:#c0392b;}} .led-st.lose{{color:#2b8a3e;}} .led-st.pend{{color:#8a8f94;}}
  .led-nums{{font-size:13.5px;color:#3d4650;margin-top:2px;}}
  .led-nums .sep{{color:#ccc;margin:0 6px;}}
  .led-hist{{margin-top:7px;font-size:12.5px;color:#6c757d;}}
  .led-detail{{display:none;background:#f8f9fa;border:1px solid #eee;border-radius:8px;
               padding:10px 14px;margin-top:9px;font-size:13px;color:#555;line-height:1.75;}}
  .led-detail b{{color:#1a252f;}}
  .led-dt-head{{font-weight:bold;color:#1a252f;font-size:13.5px;margin-bottom:5px;}}
  .sec-head{{padding:10px 16px;border-top:1px solid #eee;border-bottom:1px solid #eee;
             background:#f7f8fa;cursor:pointer;font-size:13px;color:#555;font-weight:bold;}}
  .lead-note{{padding:11px 16px;background:#fffdf3;border-bottom:1px solid #eee;
              font-size:12.5px;line-height:1.75;color:#5f5a45;}}
  .lead-note b{{color:#1a252f;}}
  .fld-note{{font-size:11px;color:#a6adb4;margin-top:2px;line-height:1.5;}}
  /* 手機首屏預算（2026-08-10）：改版後量到第一張卡掉到 y=1146px，比改版前還遠。
     這幾條專門把「前置區塊」壓扁——手機藏掉區塊說明長句、把第二排篩選收起來，
     內容本身一個字都沒有刪，桌面版維持原樣。 */
  .filter-row{{display:flex;align-items:center;gap:6px;flex-wrap:wrap;}}
  .m-only{{display:none;}}
  @media(max-width:600px){{
    .card-grid{{grid-template-columns:repeat(auto-fill,minmax(128px,1fr));gap:8px;padding:10px 10px;}}
    .sc-ret{{font-size:19px;}}
    .led{{padding:12px 12px;}}
    .led-nm{{font-size:15px;}}
    .led-q{{font-size:13.5px;}}
    .lead-note{{padding:9px 12px;font-size:12px;line-height:1.65;}}
    .m-only{{display:inline-block;}}
    #led-filter-adv{{display:none;}}
    #led-filter-adv.open{{display:flex;}}
  }}
{_NAV_TABS_CSS}
{_ONBOARD_CSS}
</style>
<style id="dyn-font"></style>
</head>
<body>
<div class="wrap">

  <!-- Header -->
  <div style="background:#1a252f;padding:20px;text-align:center;color:#fff;border-radius:8px 8px 0 0;">
    <h1 style="font-size:22px;font-weight:bold;margin:0;">股癌訊號勝率追蹤</h1>
    <div style="color:#b3c1cd;font-size:13px;margin-top:4px;">{title} · {today} · 最新分析至 {latest_ep}</div>
  </div>
  <!-- 2026-08-02 索羅門新增（任務1e）：三頁並列tab導覽，取代原本只有一行
       小字連結到attention.html的做法（完工前Codex審查曾指出小字連結太不
       顯眼），三個頁面共用 _render_nav_tabs()，避免風格漂移。 -->
  {_render_nav_tabs('report')}
  {_render_onboarding('sig_onboard_dismissed_report', '怎麼看這份報告', [
      "主區「最近訊號」＝一筆訊號一張卡：哪一集、哪一天、講了哪檔、看多還看空",
      "「跑贏／落後大盤」是這筆訊號期間內個股 vs 同期大盤（台股比0050、美股比SPY）；看空訊號以「跌得比大盤多」為贏",
      "勝率一律附分母（例如 8/11），分母不含「待觀察」；同一檔被提多次會算成多筆訊號，不代表獨立交易次數",
      "報酬＝播出日收盤價到資料截止日的漲跌幅，不是已經入袋的獲利，也未扣手續費",
      "點任一筆可展開原話、AI 摘要原因與進場價；「依標的查看履歷」在下方，收合起來的區塊點一下就開",
  ])}
  <!-- 常駐導讀（2026-08-10 新增）：onboarding 可以被關掉，關掉之後新訪客只會看到
       裸露的 KPI 數字——外部審查兩邊都點名這一條，所以定義不能只存在於可關閉的區塊。 -->
  <div class="lead-note">
    本頁整理 Podcast 逐字稿中<b>由 AI 萃取</b>的歷史訊號：主持人<b>在哪一集、哪一天</b>提到什麼標的、當時方向，
    以及截至 {today} 收盤<b>相對大盤</b>的結果。<br>
    「跑贏大盤」比較的是同一段期間的表現，<b>這是歷史追蹤紀錄，不是投資建議</b>；訊號由 AI 自動萃取，可能包含判斷錯誤，原話可展開查證。
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

  <!-- Stats 第二列（均報酬獨立常駐） -->
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
  <!-- 計算說明（常駐——使用者要靠它看懂報酬數字，不收進進階統計） -->
  <div style="padding:6px 20px 10px;background:#fafcff;font-size:11px;color:#aaa;border-bottom:1px solid #eee;">
    個股報酬＝播出日收盤價至今漲跌幅；對標大盤＝同期 0050（台股）或 SPY（美股）漲跌幅；未扣除手續費
  </div>

  <!-- 進階統計（預設收合，上色讓人知道可以點） -->
  <div onclick="toggleAdv()"
       style="padding:10px 20px;border-bottom:1px solid #dce9f7;background:#eef4fb;cursor:pointer;font-size:13px;color:#2b6cb0;font-weight:bold;">
    <span id="adv-arrow">▸</span> 進階統計
    <span style="color:#8fb3dc;font-size:12px;margin-left:6px;font-weight:normal;">信心等級 · 持倉分組 · 勝率趨勢圖</span>
    <span style="float:right;color:#8fb3dc;font-size:12px;font-weight:normal;">點擊展開</span>
  </div>
  <div id="adv-stats" style="display:none;">

  <!-- 信心等級 + 持倉時間分組勝率 -->
  <div style="display:flex;border-bottom:1px solid #eee;">

    <!-- 信心等級準確率 -->
    <div style="flex:1;padding:14px 20px;border-right:1px solid #eee;">
      <div style="font-size:12px;font-weight:bold;color:#666;margin-bottom:10px;">信心等級準確率</div>
      {_conf_bars(high_wr, len(high_dec), low_wr, len(low_dec))}
    </div>

    <!-- 持倉時間分組勝率 -->
    <div style="flex:1;padding:14px 20px;">
      <div style="font-size:12px;font-weight:bold;color:#666;margin-bottom:10px;">持倉時間分組勝率</div>
      {_hold_bars(hold_stats)}
    </div>

  </div>

  <!-- 趨勢圖 -->
  <div style="padding:14px 20px 10px;border-bottom:1px solid #eee;">
    <div style="font-size:12px;color:#999;margin-bottom:6px;font-weight:bold;">累計勝率趨勢（對標大盤）</div>
    <div style="position:relative;height:150px;">
      <canvas id="trendChart"></canvas>
    </div>
  </div>
  </div><!-- /adv-stats -->

  <!-- ── 主區：最近訊號帳本（2026-08-10 主次對調）──────────────────────────
       原本這個位置是「個股排行」卡片網格，而一筆一筆的訊號被收在下方「依集數列表」
       的收合區塊裡。兩位外部審查（Codex／DeepSeek，各自獨立）都指出：使用者—尤其
       是從週報連結進來的陌生訪客—打開第一頁要問的是「他最近講了什麼」，而那個答案
       原本藏在要點一下才打得開的灰橫條裡。因此兩區對調；個股排行整塊保留、改成收合。 -->
  <div style="padding:10px 16px;border-bottom:1px solid #eee;background:#fafafa;display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
    <span style="font-size:13px;font-weight:bold;color:#1a252f;">最近訊號</span>
    <span class="hm" style="font-size:12px;color:#999;">依節目上架日倒序，一筆訊號一張卡；點任一筆可展開原話、AI 摘要與進場價</span>
    <div style="margin-left:auto;display:flex;align-items:center;gap:4px;">
      <span style="font-size:12px;color:#999;">字體</span>
      <button class="fs-btn" id="fs0" onclick="setFontSize(0)" style="font-size:11px;">小</button>
      <button class="fs-btn" id="fs1" onclick="setFontSize(1)" style="font-size:13px;">中</button>
      <button class="fs-btn" id="fs2" onclick="setFontSize(2)" style="font-size:15px;">大</button>
      <button class="fs-btn" id="fs3" onclick="setFontSize(3)" style="font-size:17px;">特大</button>
    </div>
  </div>

  <!-- 帳本篩選列：新增「方向」維度——兩位審查者都獨立點名現況只有市場/範圍/排序，
       使用者無法回答「他過去看空過哪些標的」這種最基本的問題。 -->
  <div style="padding:9px 16px;border-bottom:1px solid #eee;background:#fafafa;display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
    <span style="font-size:13px;color:#888;white-space:nowrap;">搜尋：</span>
    <input id="led-search" type="text" placeholder="標的、代號、集數、原話..."
      oninput="lgSearch(this.value)"
      style="flex:1;max-width:260px;padding:5px 12px;border:1px solid #ddd;border-radius:12px;font-size:13px;outline:none;">
    <button id="lmkt-all" class="filter-btn led-mkt-btn btn-active" onclick="lgSetMkt('all')">全部</button>
    <button id="lmkt-tw"  class="filter-btn led-mkt-btn" onclick="lgSetMkt('tw')">台股</button>
    <button id="lmkt-us"  class="filter-btn led-mkt-btn" onclick="lgSetMkt('us')">美股</button>
    <button class="filter-btn m-only" id="led-filter-btn" onclick="toggleLedFilters()">範圍 · 方向 ▸</button>
    <span id="led-count" style="font-size:12px;color:#bbb;margin-left:auto;"></span>
  </div>
  <div id="led-filter-adv" class="filter-row" style="padding:8px 16px;border-bottom:1px solid #eee;background:#fafafa;">
    <span style="font-size:12px;color:#aaa;">範圍：</span>
    <button id="lr-0"   class="filter-btn lr-btn" onclick="lgSetRange(0)">全部</button>
    <button id="lr-100" class="filter-btn lr-btn" onclick="lgSetRange(100)">最新 100 集</button>
    <button id="lr-50"  class="filter-btn lr-btn" onclick="lgSetRange(50)">最新 50 集</button>
    <button id="lr-20"  class="filter-btn lr-btn btn-active" onclick="lgSetRange(20)">最新 20 集</button>
    <span style="font-size:12px;color:#aaa;margin-left:10px;">方向：</span>
    <button id="ld-all" class="filter-btn ld-btn btn-active" onclick="lgSetDir('all')">全部</button>
    <button id="ld-b"   class="filter-btn ld-btn" onclick="lgSetDir('+1')">看多</button>
    <button id="ld-s"   class="filter-btn ld-btn" onclick="lgSetDir('-1')">看空</button>
  </div>
  <!-- 區塊級說明（放這裡，不要放進每張卡——第一版每張卡都印一次同一句，太吵）。
       說明分三層：欄位級小字（卡片內）／區塊級（這一行）／完整方法（頁尾 details）。 -->
  <div class="fld-note" style="padding:7px 16px 8px;border-bottom:1px solid #eee;background:#fcfcfd;">
    「跑贏／落後大盤」＝這筆訊號期間內，個股表現與同期基準（台股比 0050、美股比 SPY）相比；
    <b>看空訊號以「跌得比大盤多」為贏</b>。「待觀察」表示還算不出結果，不列入勝率分母。
    同一標的多次提及會計為多筆訊號，<b>不代表獨立交易次數</b>。
  </div>
  <div id="ledger-list"></div>

  <!-- ── 次區：個股排行（原本的主區，整塊原樣保留，只是改成收合＋內容改用 beat）── -->
  <div class="sec-head" id="stock-section-toggle" role="button" tabindex="0"
       aria-expanded="false" aria-controls="stock-section-body"
       onclick="toggleStockSection()"
       onkeydown="if(event.key==='Enter'||event.key===' '){{event.preventDefault();toggleStockSection();}}">
    <span id="stock-section-arrow">▸</span> 依標的查看履歷
    <span class="hm" style="color:#aaa;font-size:12px;margin-left:6px;font-weight:normal;">依標的彙總：每檔被提到幾次、跑贏大盤幾次、最近一次是哪一集</span>
    <span style="float:right;color:#aaa;font-size:12px;font-weight:normal;">點擊展開</span>
  </div>
  <div id="stock-section-body" style="display:none;">

  <div id="view-stock" style="padding:0 0 8px;">
    <!-- 簡化篩選列（任務1c 定案：只留搜尋+市場，不做勝負/持倉天數篩選） -->
    <div style="padding:10px 16px;border-bottom:1px solid #eee;background:#fafafa;display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
      <span style="font-size:13px;color:#888;white-space:nowrap;">搜尋：</span>
      <input id="stock-search" type="text" placeholder="標的名稱、代號..."
        oninput="filterStock(this.value)"
        style="flex:1;max-width:260px;padding:5px 12px;border:1px solid #ddd;border-radius:12px;font-size:13px;outline:none;">
      <button id="smkt-all" class="filter-btn stock-mkt-btn btn-active" onclick="setStockMkt('all')">全部</button>
      <button id="smkt-tw"  class="filter-btn stock-mkt-btn" onclick="setStockMkt('tw')">台股</button>
      <button id="smkt-us"  class="filter-btn stock-mkt-btn" onclick="setStockMkt('us')">美股</button>
      <span id="stock-count" style="font-size:12px;color:#bbb;margin-left:auto;"></span>
    </div>
    <div style="padding:8px 16px;border-bottom:1px solid #eee;background:#fafafa;display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
      <span style="font-size:12px;color:#aaa;">範圍：</span>
      <button id="sr-0"   class="filter-btn sr-btn" onclick="setStockRange(0)">全部</button>
      <button id="sr-100" class="filter-btn sr-btn" onclick="setStockRange(100)">最新 100 集</button>
      <button id="sr-50"  class="filter-btn sr-btn" onclick="setStockRange(50)">最新 50 集</button>
      <button id="sr-20"  class="filter-btn sr-btn btn-active" onclick="setStockRange(20)">最新 20 集</button>
      <span style="font-size:12px;color:#aaa;margin-left:10px;">排序：</span>
      <button id="ss-total"    class="filter-btn ss-btn btn-active" onclick="sortStock('total')">次數</button>
      <button id="ss-win_rate" class="filter-btn ss-btn" onclick="sortStock('win_rate')">勝率</button>
      <button id="ss-avg_ret"  class="filter-btn ss-btn" onclick="sortStock('avg_ret')">均報酬</button>
      <button id="ss-latest"   class="filter-btn ss-btn" onclick="sortStock('latest')">最近集</button>
      <span style="font-size:12px;color:#bbb;margin-left:10px;">點卡片可展開該標的歷次訊號</span>
    </div>
    <div id="stock-card-grid" class="card-grid"></div>
  </div>
  </div><!-- /stock-section-body（2026-08-10 主次對調新增的收合外層） -->

  <!-- 依集數列表：降級為次要區塊，預設收合（任務1d 定案，比照 demo 的
       ep-toggle/ep-compact 收合行為——原本「每集訊號」的完整功能全部保留，
       只是從主要 Tab 改成點頭列展開的次要區塊） -->
  <div id="ep-section-toggle" onclick="toggleEpSection()"
       style="padding:10px 20px;border-top:1px solid #eee;border-bottom:1px solid #eee;background:#f7f8fa;cursor:pointer;font-size:13px;color:#555;font-weight:bold;">
    <span id="ep-section-arrow">▸</span> 依集數列表
    <span style="color:#aaa;font-size:12px;margin-left:6px;font-weight:normal;">依節目集數列出每一筆選股訊號：講了哪檔、看多還看空、至今績效如何</span>
    <span style="float:right;color:#aaa;font-size:12px;font-weight:normal;">已降級為次要區塊，點擊展開</span>
  </div>
  <div id="ep-section-body" style="display:none;">

  <!-- 集數篩選工具列 -->
  <div id="view-filters" style="padding:10px 16px 6px;border-bottom:1px solid #eee;background:#fafafa;">
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;flex-wrap:wrap;">
      <span style="font-size:13px;color:#888;white-space:nowrap;">搜尋：</span>
      <input id="main-search" type="text"
        placeholder="集數、標的、代碼、主委觀點..."
        oninput="filterSearch(this.value)"
        style="flex:1;max-width:340px;padding:5px 12px;border:1px solid #ddd;border-radius:12px;font-size:13px;outline:none;">
      <button onclick="clearSearch()" class="filter-btn" style="color:#888;">清除</button>
      <button onclick="toggleFilterAdv()" class="filter-btn" id="filter-adv-btn">篩選 ▸</button>
    </div>
    <div id="filter-adv" style="display:none;">
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
    </div><!-- /filter-adv -->
  </div>

  <!-- 以集數 Table -->
  <div id="view-ep" style="padding:0 0 12px;overflow-x:auto;-webkit-overflow-scrolling:touch;">
    <table id="main-table" style="width:100%;border-collapse:collapse;font-size:15px;min-width:720px;">
      <thead>
        <tr style="background:#f1f3f5;color:#495057;font-size:13px;">
          <th onclick="sortBy('epnum')" class="hm" style="padding:10px 12px;text-align:left;">集數 ↕</th>
          <th onclick="sortBy('tag')"   class="hm" style="padding:10px 12px;text-align:left;">分類 ↕</th>
          <th style="padding:10px 12px;text-align:left;">標的</th>
          <th style="padding:10px 12px;text-align:left;">動作</th>
          <th onclick="sortBy('date')"  class="hm" style="padding:10px 12px;text-align:left;">進場日 ↕</th>
          <th onclick="sortBy('spct')"  style="padding:10px 12px;text-align:left;">個股報酬 ↕</th>
          <th onclick="sortBy('bpct')"  class="hm" style="padding:10px 12px;text-align:left;">同期大盤 ↕</th>
          <th onclick="sortBy('days')"  class="hm" style="padding:10px 12px;text-align:center;">天數 ↕</th>
          <th onclick="sortBy('beat')"  style="padding:10px 12px;text-align:left;">勝負 ↕</th>
        </tr>
      </thead>
      <tbody id="tbody"></tbody>
    </table>
  </div>
  </div><!-- /ep-section-body -->

  <!-- Footer -->
  <div style="padding:10px;text-align:center;font-size:12px;color:#bbb;border-top:1px solid #f0f0f0;">
    台股基準 0050.TW · 美股基準 SPY · 僅供參考，非投資建議
  </div>
</div>

<script>
{_onboard_js('sig_onboard_dismissed_report')}
// ── 字體大小 ──────────────────────────────────────────────
const FS = [12, 14, 16, 18];
let fsIdx = parseInt(localStorage.getItem('fs-idx') || '1');
function applyFontSize() {{
  const s = FS[fsIdx];
  // 只縮放 td/th 基準字級，span/div 保留各自的行內字級，層級（主字/副字/徽章）才不會被壓平
  document.getElementById('dyn-font').textContent =
    `.wrap td, .wrap th {{ font-size: ${{s}}px !important; }}`;
  document.querySelectorAll('.fs-btn').forEach((b, i) => b.classList.toggle('btn-active', i === fsIdx));
  localStorage.setItem('fs-idx', fsIdx);
}}
function setFontSize(i) {{ fsIdx = i; applyFontSize(); }}
// 2026-08-02 索羅門改寫（任務1a/1d）：卡片網格現在是唯一主視圖，DOMContentLoaded
// 直接 renderStockTab()；原本的每集訊號表格（renderDetailTab）改成收合區塊
// 第一次展開時才 render（見下方 toggleEpSection()），沒展開過就不用付這筆算力。
// 2026-08-10 主次對調：主區改成訊號帳本（renderLedger），個股排行網格降級為收合
// 區塊，沿用「首次展開才 render」模式（見 toggleStockSection），沒展開就不付算力。
document.addEventListener('DOMContentLoaded', () => {{ applyFontSize(); renderLedger(); }});

// ── 個股排行收合（2026-08-10 新增，與 toggleEpSection/toggleAdv 同一套模式）──
let _stockSectionInited = false;
function toggleStockSection() {{
  const box  = document.getElementById('stock-section-body');
  const head = document.getElementById('stock-section-toggle');
  const open = box.style.display === 'none';
  box.style.display = open ? '' : 'none';
  document.getElementById('stock-section-arrow').textContent = open ? '▾' : '▸';
  head.setAttribute('aria-expanded', open ? 'true' : 'false');
  if (open && !_stockSectionInited) {{ _stockSectionInited = true; renderStockTab(); }}
}}

// ── 進階統計收合（趨勢圖等首次展開才初始化，收合狀態下 canvas 量不到尺寸）──
let _chartInited = false;
function toggleAdv() {{
  const box = document.getElementById('adv-stats');
  const open = box.style.display === 'none';
  box.style.display = open ? '' : 'none';
  document.getElementById('adv-arrow').textContent = open ? '▾' : '▸';
  if (open && !_chartInited) {{ _chartInited = true; initChart(); }}
}}

// ── 篩選按鈕群收合 ────────────────────────────────────────
function toggleFilterAdv() {{
  const box = document.getElementById('filter-adv');
  const open = box.style.display === 'none';
  box.style.display = open ? '' : 'none';
  document.getElementById('filter-adv-btn').textContent = open ? '篩選 ▾' : '篩選 ▸';
}}

// ── 依集數列表收合（任務1d：從主要 Tab 降級成次要區塊，預設收合，
// 比照 demo 的 ep-toggle/ep-compact 行為；沿用「進階統計」同一套
// 「首次展開才 render」模式，避免收合狀態下也要付渲染成本）───────
let _epSectionInited = false;
function toggleEpSection() {{
  const box = document.getElementById('ep-section-body');
  const open = box.style.display === 'none';
  box.style.display = open ? '' : 'none';
  document.getElementById('ep-section-arrow').textContent = open ? '▾' : '▸';
  if (open && !_epSectionInited) {{ _epSectionInited = true; renderDetailTab(); }}
}}

// ── 集數展開/收合 ─────────────────────────────────────────
function toggleEp(ep) {{
  const rows = document.querySelectorAll('.ep-' + ep);
  const hdr  = document.querySelector('.ep-header[data-ep="' + ep + '"] td');
  const collapsed = rows[0] && rows[0].classList.contains('hidden');
  rows.forEach(r => r.classList.toggle('hidden', !collapsed));
  if (hdr) hdr.innerHTML = hdr.innerHTML.replace(/[▾▸]/, collapsed ? '▾' : '▸');
}}

// ── HTML escape（2026-08-02 索羅門新增，任務第10項）──────────────────────
// SIGNALS_DATA 裡的 name/code/tag/raw_reason/quote 來自 Gemini 分析逐字稿的
// 自由文字輸出，不是這個網頁的使用者直接輸入，但這份 HTML 最終會 push 到
// GitHub Pages 公開頁面（同一份風險見上面 _json_for_script() 的說明）——
// renderDetailTab()/renderStockTab() 用樣板字串組 innerHTML 時，這幾個欄位
// 原本沒有跳脫直接塞進 HTML，如果分析文字剛好含有 <script>/<img onerror=...>
// 這類字面內容，會被瀏覽器當成真的標籤解析，等於儲存型 XSS。
function escapeHtml(str) {{
  if (str == null) return '';
  return String(str).replace(/[&<>"']/g, c => ({{
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }})[c]);
}}

// ── 以集數 Table：純前端從 SIGNALS_DATA render（與全集 HTML 分開存放會浪費一倍空間）──
function renderDetailTab() {{
  const pctColor  = v => v == null ? '#888' : (v >= 0 ? '#d9534f' : '#2b8a3e');
  const fmtPct    = v => v == null ? 'N/A' : (v >= 0 ? '+' : '') + v.toFixed(2) + '%';
  const beatFull  = b => b === true ? '<span style="background:#fdecea;color:#d9534f;font-weight:bold;font-size:12px;border-radius:10px;padding:2px 8px;white-space:nowrap;">獲勝</span>'
    : b === false ? '<span style="background:#e6f4ea;color:#2b8a3e;font-weight:bold;font-size:12px;border-radius:10px;padding:2px 8px;white-space:nowrap;">落後</span>'
    : '<span style="background:#f1f3f5;color:#888;font-size:12px;border-radius:10px;padding:2px 8px;white-space:nowrap;">待定</span>';
  const actionFull = (a, c) => a === '+1' ? (c === 'High' ? '超級看好' : '看好') : a === '-1' ? '看壞' : '中立';

  const byEp = {{}};
  SIGNALS_DATA.forEach(s => {{ (byEp[s.ep] = byEp[s.ep] || []).push(s); }});
  const eps = Object.keys(byEp).sort((a, b) => byEp[b][0].ep_num - byEp[a][0].ep_num);

  let html = '';
  eps.forEach(ep => {{
    const sigs   = byEp[ep];
    const epNum  = sigs[0].ep_num;
    const epDate = (sigs.find(x => x.entry_date) || sigs[0]).entry_date || '';
    const epRets = sigs.map(s => s.s_pct).filter(v => v !== null && v !== undefined);
    const epAvg  = epRets.length ? epRets.reduce((a,b)=>a+b,0)/epRets.length : null;
    const epAvgHtml = epAvg === null ? ''
      : ` · 均報酬 <span style="color:${{epAvg >= 0 ? '#d9534f' : '#2b8a3e'}};">${{(epAvg>=0?'+':'') + epAvg.toFixed(2)}}%</span>`;
    html += `<tr class="ep-header" data-ep="${{ep}}" style="background:#e8ecf0;cursor:pointer;" onclick="toggleEp('${{ep}}')">
      <td colspan="9" style="padding:8px 12px;font-weight:bold;color:#1a252f;font-size:15px;">
        ▾ ${{ep}}
        <span style="font-weight:normal;color:#7f8c8d;font-size:14px;margin-left:8px;">${{epDate}} · ${{sigs.length}} 筆${{epAvgHtml}}</span>
      </td>
    </tr>`;

    sigs.forEach(s => {{
      const isTw    = s.mkt === 'tw';
      const mktBadge = isTw
        ? '<span style="font-size:11px;background:#e8f0fe;color:#1a6b9a;border-radius:3px;padding:1px 4px;margin-left:4px;">台</span>'
        : '<span style="font-size:11px;background:#fff3cd;color:#856404;border-radius:3px;padding:1px 4px;margin-left:4px;">美</span>';
      const shortBadge = s.action === '-1'
        ? '<span style="font-size:14px;background:#e8f4fd;color:#1a6b9a;border-radius:3px;padding:1px 4px;margin-left:4px;">空</span>'
        : '';
      const entryP   = s.entry_p ? s.entry_p.toFixed(2) : 'N/A';
      const currP    = s.curr_p  ? s.curr_p.toFixed(2)  : 'N/A';
      // s.days ? ... 對 days=0（今天才進場）會誤判成沒有值顯示 N/A（0 是 falsy）——
      // 2026-08-01 Codex 審查發現，改用 != null 明確判斷有沒有值。
      const daysDisp = s.days != null ? s.days + '天' : 'N/A';
      const sPctVal  = s.s_pct ?? -9999, bPctVal = s.b_pct ?? -9999;
      const beatVal  = s.beat === true ? 1 : (s.beat === false ? 0 : -1);
      const kw = [ep, String(epNum), s.name, s.code, s.code.split('.')[0], s.raw_reason, s.quote]
        .filter(Boolean).join(' ').replace(/"/g, ' ').replace(/\\n/g, ' ');

      html += `<tr class="ep-row ep-${{ep}}" data-ep="${{ep}}" data-epnum="${{epNum}}" data-tag="${{escapeHtml(s.tag)}}" data-mkt="${{s.mkt}}"
          data-spct="${{sPctVal}}" data-bpct="${{bPctVal}}" data-beat="${{beatVal}}" data-days="${{s.days || -1}}"
          data-name="${{escapeHtml(s.name)}}" data-code="${{escapeHtml(s.code)}}" data-kw="${{escapeHtml(kw)}}" style="border-bottom:none;">
        <td class="hm" style="padding:9px 12px 4px;font-weight:bold;color:#1a252f;white-space:nowrap;padding-left:24px;">${{ep}}</td>
        <td class="hm" style="padding:9px 12px 4px;color:#888;font-size:14px;">${{escapeHtml(s.tag)}}</td>
        <td style="padding:9px 12px 4px;font-weight:bold;">${{escapeHtml(s.name)}}${{mktBadge}}<br>
          <span style="color:#aaa;font-size:13px;">${{escapeHtml(s.code)}}</span></td>
        <td style="padding:9px 12px 4px;color:#666;font-size:14px;">${{actionFull(s.action, s.conf)}}${{shortBadge}}</td>
        <td class="hm" style="padding:9px 12px 4px;">${{s.entry_date || 'N/A'}}<br>
          <span style="color:#aaa;font-size:13px;">${{entryP}} → ${{currP}}</span></td>
        <td style="padding:9px 12px 4px;font-weight:bold;color:${{pctColor(s.s_pct)}};">${{fmtPct(s.s_pct)}}</td>
        <td class="hm" style="padding:9px 12px 4px;color:#666;">${{fmtPct(s.b_pct)}}<br>
          <span style="color:#bbb;font-size:12px;">${{escapeHtml(s.bm)}}</span></td>
        <td class="hm" style="padding:9px 12px 4px;text-align:center;color:#888;font-size:13px;">${{daysDisp}}</td>
        <td style="padding:9px 12px 4px;">${{beatFull(s.beat)}}</td>
      </tr>`;

      if (s.raw_reason || s.quote) {{
        const quoteHtml = s.quote
          ? `<div style="margin-top:5px;padding-left:10px;border-left:3px solid #ccc;color:#888;font-style:italic;font-size:14px;">「${{escapeHtml(s.quote)}}」</div>`
          : '';
        html += `<tr class="ep-row ep-${{ep}} reason-row" data-ep="${{ep}}" data-epnum="${{epNum}}" data-tag="${{escapeHtml(s.tag)}}" data-mkt="${{s.mkt}}"
            data-spct="${{sPctVal}}" data-bpct="${{bPctVal}}" data-beat="${{beatVal}}"
            data-name="${{escapeHtml(s.name)}}" data-code="${{escapeHtml(s.code)}}" data-kw="${{escapeHtml(kw)}}" style="background:#f8f9fa;">
          <td colspan="9" style="padding:7px 12px 10px 32px;border-bottom:1px solid #eee;">
            <span style="font-size:14px;font-weight:bold;color:#3b6ea5;">主委觀點</span>
            <span style="font-size:14px;color:#555;margin-left:6px;">${{escapeHtml(s.raw_reason)}}</span>
            ${{quoteHtml}}</td></tr>`;
      }}
    }});
  }});

  document.getElementById('tbody').innerHTML = html;
  collapseOldEps();
}}

// ── ep → rows[] 索引（2026-08-02 索羅門新增，任務第4項）：原本每個集數各自
// document.querySelectorAll('.ep-' + ep) 掃一次全部列，集數(E)×列數(L) 規模一大
// 就是 O(E×L)；改成一次 O(L) 掃過 .ep-row 依 dataset.ep 分組建成 Map，後面
// collapseOldEps()/syncEpHeaders()/sortBy() 都改查這個索引，不再各自重新掃描。
function _buildEpRowIndex() {{
  const map = new Map();
  document.querySelectorAll('.ep-row').forEach(r => {{
    const ep = r.dataset.ep;
    if (!map.has(ep)) map.set(ep, []);
    map.get(ep).push(r);
  }});
  return map;
}}

// ── 預設只展開最新 3 集（搜尋/篩選中不收合，避免結果被藏）──
function collapseOldEps() {{
  const filtering = searchFilter || tagFilter !== 'all' || mktFilter !== 'all'
    || beatFilter !== 'all' || daysFilter !== 0;
  if (filtering) return;
  const epRowIndex = _buildEpRowIndex();
  document.querySelectorAll('.ep-header').forEach((hdr, i) => {{
    if (i < 3) return;
    const ep = hdr.dataset.ep;
    (epRowIndex.get(ep) || []).forEach(r => r.classList.add('hidden'));
    const td = hdr.querySelector('td');
    if (td) td.innerHTML = td.innerHTML.replace('▾', '▸');
  }});
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
  const epRowIndex = _buildEpRowIndex();
  document.querySelectorAll('.ep-header').forEach(hdr => {{
    const ep      = hdr.dataset.ep;
    const visible = (epRowIndex.get(ep) || []).filter(r => !r.classList.contains('hidden')).length;
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
  // 2026-08-02 索羅門修正（任務第4項）：原本每個集數各自 querySelectorAll('.ep-' + ep)
  // 掃一次全部列，集數×列數規模一大就是 O(E×L)；改成一次 _buildEpRowIndex() 建好
  // ep→rows[] 索引，且最後改用 DocumentFragment 一次性掛回 DOM（取代逐一
  // tbody.appendChild 造成的多次重排）。
  const epRowIndex = _buildEpRowIndex();
  const frag = document.createDocumentFragment();
  if (col === 'epnum') {{
    const headers = [...tbody.querySelectorAll('.ep-header')];
    const groups  = headers.map(h => {{
      const ep = h.dataset.ep;
      return {{ header: h, rows: epRowIndex.get(ep) || [], epnum: parseInt(ep.replace(/[^0-9]/g,'')) }};
    }});
    groups.sort((a,b) => (a.epnum - b.epnum) * dir);
    groups.forEach(g => {{ frag.appendChild(g.header); g.rows.forEach(r => frag.appendChild(r)); }});
  }} else {{
    const headers = [...tbody.querySelectorAll('.ep-header')];
    headers.map(h => {{
      const ep = h.dataset.ep;
      return {{ header: h, rows: epRowIndex.get(ep) || [] }};
    }}).forEach(g => {{
      g.rows.sort((a,b) => (rowVal(a) > rowVal(b) ? dir : rowVal(a) < rowVal(b) ? -dir : 0));
      frag.appendChild(g.header);
      g.rows.forEach(r => frag.appendChild(r));
    }});
  }}
  tbody.appendChild(frag);
}}

// ── 以標的 JS 動態渲染 ────────────────────────────────────
const SIGNALS_DATA = {signals_json};
const PRICE_SERIES = {price_series_json};
let _sr = 20, _sCol = 'total', _sDir = -1, _stockSearch = '', _stockMkt = 'all';

function setStockRange(n) {{
  _sr = n;
  document.querySelectorAll('.sr-btn').forEach(b => b.classList.remove('btn-active'));
  document.getElementById('sr-' + n).classList.add('btn-active');
  renderStockTab();
}}
function sortStock(col) {{
  _sDir = (_sCol === col) ? -_sDir : -1;
  _sCol = col;
  document.querySelectorAll('.ss-btn').forEach(b => b.classList.remove('btn-active'));
  const btn = document.getElementById('ss-' + col);
  if (btn) btn.classList.add('btn-active');
  renderStockTab();
}}
function filterStock(val) {{ _stockSearch = val.trim().toLowerCase(); renderStockTab(); }}
function setStockMkt(m) {{
  _stockMkt = m;
  document.querySelectorAll('.stock-mkt-btn').forEach(b => b.classList.remove('btn-active'));
  document.getElementById('smkt-' + m).classList.add('btn-active');
  renderStockTab();
}}

// ── sparkline：SVG 折線圖，資料來自 PRICE_SERIES（2026-08-02 索羅門新增，任務1b）
// points 是 [[dateStr, price], ...] 升序排列；資料不足（<2點）時顯示「無足夠資料」
// 佔位，不畫假圖騙使用者。顏色依這段序列自己的漲跌（首尾比較），跟卡片上方
// 報酬率大字（依 avg_ret 正負）是兩個獨立判斷，各自反映各自的意義。
function renderSparkline(points) {{
  if (!points || points.length < 2) {{
    return '<div style="height:32px;display:flex;align-items:center;justify-content:center;color:#ccc;font-size:11px;">無足夠資料</div>';
  }}
  const W = 160, H = 32, pad = 3;
  const vals = points.map(p => p[1]);
  const min = Math.min(...vals), max = Math.max(...vals);
  const x = i => pad + (i / (vals.length - 1)) * (W - pad * 2);
  const y = v => pad + (1 - (v - min) / ((max - min) || 1)) * (H - pad * 2);
  let d = `M ${{x(0)}} ${{y(vals[0])}} `;
  vals.forEach((v, i) => {{ if (i > 0) d += `L ${{x(i)}} ${{y(v)}} `; }});
  const areaD = d + `L ${{x(vals.length - 1)}} ${{H - pad}} L ${{x(0)}} ${{H - pad}} Z`;
  // 2026-08-10：改成中性灰。原本用「這段序列自己的首尾漲跌」上色，跟卡片上的
  // 勝負色是兩套語意，畫面上會出現「綠字配紅線」讓人以為是 bug（實例：聯發科）。
  // 這條線只是近 60 個交易日的股價脈絡，不承擔勝負語意，所以不給紅綠。
  const color = '#9aa4ad';
  const last  = vals.length - 1;
  return `<svg viewBox="0 0 ${{W}} ${{H}}" width="100%" height="${{H}}" preserveAspectRatio="none" style="display:block;">
    <path d="${{areaD}}" fill="${{color}}" opacity="0.12"></path>
    <path d="${{d}}" fill="none" stroke="${{color}}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"></path>
    <circle cx="${{x(last)}}" cy="${{y(vals[last])}}" r="2.4" fill="${{color}}"></circle>
  </svg>`;
}}

// ── 個股排行：卡片網格（2026-08-02 索羅門改寫，任務1a：表格→卡片，取代舊版 <table>）
function renderStockTab() {{
  const allNums = [...new Set(SIGNALS_DATA.map(s => s.ep_num))].sort((a,b)=>a-b);
  const keep    = _sr === 0 ? new Set(allNums) : new Set(allNums.slice(-_sr));
  const filt    = SIGNALS_DATA.filter(s => keep.has(s.ep_num));

  const gmap = {{}};
  filt.forEach(s => {{
    if (!s.code) return;
    if (!gmap[s.code]) gmap[s.code] = {{ code: s.code, name: s.name, mkt: s.mkt, sigs: [] }};
    gmap[s.code].sigs.push(s);
  }});
  const totalCount = Object.keys(gmap).length;

  let groups = Object.values(gmap).map(g => {{
    const dec  = g.sigs.filter(s => s.beat !== null && s.beat !== undefined);
    const wins = dec.filter(s => s.beat === true).length;
    const rets = g.sigs.filter(s => s.s_pct !== null && s.s_pct !== undefined).map(s => s.s_pct);
    const bull = g.sigs.filter(s=>s.action==='+1').length;
    const bear = g.sigs.filter(s=>s.action==='-1').length;
    // 卡片方向 chip：多空次數較多者當代表方向；平手看最新一筆訊號的方向
    // （多筆訊號跨集數，卡片只有一個 chip 位置，需要一個代表值——索羅門判斷）
    const latestSig = g.sigs.reduce((a,b) => b.ep_num > a.ep_num ? b : a);
    const dir  = bull === bear ? latestSig.action : (bull > bear ? '+1' : '-1');
    const daysVals = g.sigs.map(s=>s.days).filter(v => v != null);
    return {{
      ...g, total: g.sigs.length, bull, bear, dir,
      wins, dec: dec.length,
      // 2026-08-10：卡片要顯示「最近一次是哪一集、哪一天」——外部審查兩邊都指出
      // 舊卡片連 EP 號都沒有，使用者分不出「本週剛講」與「一年前講過」。
      latestEp: latestSig.ep, latestDate: latestSig.entry_date || '',
      win_rate: dec.length ? Math.round(wins/dec.length*1000)/10 : null,
      avg_ret:  rets.length ? Math.round(rets.reduce((a,b)=>a+b,0)/rets.length*100)/100 : null,
      latest:   Math.max(...g.sigs.map(s=>s.ep_num)),
      days:     daysVals.length ? Math.max(...daysVals) : null,
      spark:    PRICE_SERIES[g.code] || [],
    }};
  }});

  // 簡化篩選列（任務1c）：搜尋（標的名稱/代號）+ 市場切換
  groups = groups.filter(g => {{
    const mktOk    = _stockMkt === 'all' || g.mkt === _stockMkt;
    const kw       = (g.name + g.code).toLowerCase();
    const searchOk = !_stockSearch || kw.includes(_stockSearch);
    return mktOk && searchOk;
  }});

  groups.sort((a,b) => {{
    const va = a[_sCol] ?? -9999, vb = b[_sCol] ?? -9999;
    return (va > vb ? 1 : va < vb ? -1 : 0) * _sDir;
  }});

  document.getElementById('stock-count').textContent = `${{groups.length}} / ${{totalCount}} 檔`;

  if (!groups.length) {{
    document.getElementById('stock-card-grid').innerHTML =
      "<div class='empty-state'>沒有符合篩選條件的標的</div>";
    return;
  }}

  const fp = v => v == null ? 'N/A' : (v >= 0 ? '+' : '') + v.toFixed(2) + '%';
  const fc = v => v == null ? '#888' : v >= 0 ? '#d9534f' : '#2b8a3e';

  const html = groups.map((g, idx) => {{
    // 2026-08-02 完工前 Codex 覆核抓到：g.dir 除了 '+1'/'-1' 還可能是 '0'
    // （該標的全部訊號都是中性、或多空平手且最新一筆剛好是中性），原本只
    // 特判 '-1'，其餘（含 '0'）一律被畫成「看多」bull 樣式，是卡片化後
    // 新增的呈現錯誤——這裡補上中性樣式，不讓中性訊號被誤標成看多。
    const dirCls   = g.dir === '-1' ? 'bear' : g.dir === '0' ? 'neutral' : 'bull';
    const dirLabel = g.dir === '-1' ? '↓ 看空' : g.dir === '0' ? '— 中性' : '↑ 看多';
    const mktLabel = g.mkt === 'tw' ? '台股' : '美股';
    // 2026-08-10：主數字從「平均個股報酬」改成「跑贏大盤 x/y」。
    // 舊寫法 isWin = (avg_ret >= 0) 用個股報酬正負決定紅綠，但本站的勝負定義是
    // beat（對標大盤，且看空訊號是「跌得比大盤多」才算贏，見 performance.py:221-228）。
    // 實例：國巨 EP674 看空，個股 -50.54% vs 0050 -0.24%，beat=true 是大勝，
    // 舊卡片卻因為報酬是負的而塗成綠色 .lose，把一筆漂亮的戰績顯示成輸。
    // 勝率一律附分母（外部審查兩邊獨立點名：1/1 的 100% 會霸榜，沒有分母無法判斷可信度）。
    const pend     = g.total - g.dec;
    const rateTxt  = g.dec ? `${{g.wins}}/${{g.dec}}` : '—';
    const rateCls  = !g.dec ? 'pend' : (g.wins * 2 >= g.dec ? 'win' : 'lose');
    // 這裡的勝率是「目前選取的集數範圍」內的，跟帳本卡片上「本檔歷史（全期間）」
    // 不是同一個母體——實測時同一檔國巨出現 2/6 與 11/16 兩個數字，不標範圍會打架。
    const rateNote = g.dec
      ? `${{_sr === 0 ? '全期間' : '最新 ' + _sr + ' 集'}}跑贏 ${{Math.round(g.wins / g.dec * 100)}}%`
        + (pend ? ` · 待觀察 ${{pend}}` : '')
      : '此範圍內尚無可判定訊號';

    const detailRows = g.sigs.slice().sort((a,b) => b.ep_num - a.ep_num).map(s => {{
      const actLbl  = s.action === '+1' ? '看多' : s.action === '-1' ? '看空' : '中性';
      const beatLbl = s.beat === true ? '✅獲勝' : s.beat === false ? '❌落後' : '⏳待定';
      const quoteHtml = s.quote
        ? `<div style="margin-top:4px;padding-left:8px;border-left:2px solid #ccc;color:#888;font-style:italic;">「${{escapeHtml(s.quote)}}」</div>`
        : '';
      return `<div class="sc-detail-row">
        <span style="color:#888;">${{escapeHtml(s.ep)}}</span>
        <span style="margin-left:6px;">${{actLbl}}</span>
        <span style="margin-left:6px;color:${{fc(s.s_pct)}};font-weight:bold;">${{fp(s.s_pct)}}</span>
        <span style="margin-left:6px;">${{beatLbl}}</span>
        ${{s.raw_reason ? `<div style="margin-top:3px;color:#555;">${{escapeHtml(s.raw_reason)}}</div>` : ''}}
        ${{quoteHtml}}
      </div>`;
    }}).join('');

    return `<div class="stock-card" role="button" tabindex="0"
        aria-expanded="false" aria-controls="scd-${{idx}}"
        onclick="toggleCardDetail(${{idx}}, this)"
        onkeydown="if(event.key==='Enter'||event.key===' '){{event.preventDefault();toggleCardDetail(${{idx}}, this);}}">
        <div class="sc-row1">
          <span class="sc-name">${{escapeHtml(g.name)}}<span class="sc-mkt-chip">${{mktLabel}}</span></span>
          <span class="sc-dir-chip ${{dirCls}}">${{dirLabel}}</span>
        </div>
        <div class="sc-code">${{escapeHtml(g.code)}}</div>
        <div class="sc-ret ${{rateCls}}">${{rateTxt}}</div>
        <div class="fld-note">${{rateNote}}</div>
        <div class="sc-spark">${{renderSparkline(g.spark)}}</div>
        <div class="sc-meta"><span>最近 ${{escapeHtml(g.latestEp)}}</span><span>提及 ${{g.total}} 次</span></div>
        <div class="fld-note">${{g.latestDate ? '上架於 ' + g.latestDate + ' · ' : ''}}均報酬 ${{fp(g.avg_ret)}}</div>
      </div>
      <div class="sc-detail" id="scd-${{idx}}">
        <div class="led-dt-head">${{escapeHtml(g.name)}}（${{escapeHtml(g.code)}}）歷次訊號</div>
        ${{detailRows}}</div>`;
  }}).join('');

  document.getElementById('stock-card-grid').innerHTML = html;
}}

// 2026-08-10：加上 aria-expanded 同步（卡片是 div+role=button，螢幕閱讀器要靠這個
// 屬性才知道展開狀態；詳情區塊頂端另外重複一次股票名，避免展開後視覺/語音失去錨點）。
function toggleCardDetail(idx, el) {{
  const box = document.getElementById('scd-' + idx);
  if (!box) return;
  const open = box.style.display !== 'block';
  box.style.display = open ? 'block' : 'none';
  if (el) el.setAttribute('aria-expanded', open ? 'true' : 'false');
}}

// ── 訊號帳本（2026-08-10 新增，主區）──────────────────────────────────
// 一筆訊號一張卡，依節目上架日倒序。與個股排行的差別：這裡的單位是「事件」
// （誰、哪一集、哪一天、說了什麼、後來贏沒贏），不需要懂平均/勝率/樣本數就讀得懂。
const AS_OF = '{today}';
let _lgSearch = '', _lgMkt = 'all', _lgRange = 20, _lgDir = 'all';

function _lgDaysAgo(ds) {{
  if (!ds) return null;
  const a = Date.parse(ds + 'T00:00:00Z'), b = Date.parse(AS_OF + 'T00:00:00Z');
  if (isNaN(a) || isNaN(b)) return null;
  return Math.round((b - a) / 86400000);
}}

// 各標的的歷史戰績：用全期間資料算，**不受上方篩選影響**——「這檔歷來準不準」
// 不應該被「最新 20 集」這種檢視範圍改寫掉。
const _LG_HIST = (() => {{
  const m = {{}};
  SIGNALS_DATA.forEach(s => {{
    if (!s.code) return;
    const h = m[s.code] || (m[s.code] = {{ win: 0, dec: 0, pend: 0 }});
    if (s.beat === true)       {{ h.win++; h.dec++; }}
    else if (s.beat === false) {{ h.dec++; }}
    else                       {{ h.pend++; }}
  }});
  return m;
}})();

// 手機把「範圍／方向」那排收起來（桌面不受影響，CSS 只在 max-width:600px 生效）
function toggleLedFilters() {{
  const row = document.getElementById('led-filter-adv');
  const btn = document.getElementById('led-filter-btn');
  const open = row.classList.toggle('open');
  btn.textContent = open ? '範圍 · 方向 ▾' : '範圍 · 方向 ▸';
}}

function lgSearch(v) {{ _lgSearch = v.trim().toLowerCase(); renderLedger(); }}
function lgSetMkt(m) {{
  _lgMkt = m;
  document.querySelectorAll('.led-mkt-btn').forEach(b => b.classList.remove('btn-active'));
  document.getElementById('lmkt-' + m).classList.add('btn-active');
  renderLedger();
}}
function lgSetRange(n) {{
  _lgRange = n;
  document.querySelectorAll('.lr-btn').forEach(b => b.classList.remove('btn-active'));
  document.getElementById('lr-' + n).classList.add('btn-active');
  renderLedger();
}}
function lgSetDir(d) {{
  _lgDir = d;
  document.querySelectorAll('.ld-btn').forEach(b => b.classList.remove('btn-active'));
  document.getElementById(d === 'all' ? 'ld-all' : (d === '+1' ? 'ld-b' : 'ld-s')).classList.add('btn-active');
  renderLedger();
}}

function renderLedger() {{
  const allNums = [...new Set(SIGNALS_DATA.map(s => s.ep_num))].sort((a, b) => a - b);
  const keep    = _lgRange === 0 ? null : new Set(allNums.slice(-_lgRange));
  const fp      = v => v == null ? '—' : (v >= 0 ? '+' : '') + v.toFixed(2) + '%';

  const list = SIGNALS_DATA.filter(s => {{
    if (keep && !keep.has(s.ep_num)) return false;
    if (_lgMkt !== 'all' && s.mkt !== _lgMkt) return false;
    if (_lgDir !== 'all' && s.action !== _lgDir) return false;
    if (_lgSearch) {{
      const kw = [s.ep, s.name, s.code, s.raw_reason, s.quote].filter(Boolean).join(' ').toLowerCase();
      if (!kw.includes(_lgSearch)) return false;
    }}
    return true;
  }}).sort((a, b) => b.ep_num - a.ep_num);

  document.getElementById('led-count').textContent = list.length + ' 筆訊號';
  const box = document.getElementById('ledger-list');
  if (!list.length) {{
    box.innerHTML = "<div class='empty-state'>沒有符合篩選條件的訊號</div>";
    return;
  }}

  // 「全部」時有 600+ 筆，一次全畫會讓手機卡住；只畫最新 120 筆並明講還有幾筆。
  const MAX   = 120;
  const shown = list.slice(0, MAX);

  box.innerHTML = shown.map((s, i) => {{
    const dirCls = s.action === '-1' ? 'bear' : s.action === '0' ? 'neu' : 'bull';
    const dirLbl = s.action === '-1' ? '↓ 看空' : s.action === '0' ? '— 中性' : '↑ 看多';
    // 勝負一律讀 beat（performance.py 已對看空反向處理），不從 s_pct 正負推導。
    const stCls  = s.beat === true ? 'win' : s.beat === false ? 'lose' : 'pend';
    const stLbl  = s.beat === true ? '✓ 跑贏大盤' : s.beat === false ? '✕ 落後大盤' : '○ 待觀察';
    const mkt    = s.mkt === 'tw' ? '台股' : '美股';
    const ago    = _lgDaysAgo(s.entry_date);
    const agoTxt = ago == null ? '' : `（${{ago}} 天前）`;
    const h      = _LG_HIST[s.code] || {{ win: 0, dec: 0, pend: 0 }};
    const histTxt = h.dec
      ? `本檔歷史（全期間）：跑贏 <b>${{h.win}}/${{h.dec}}</b>` + (h.pend ? ` · 待觀察 ${{h.pend}}` : '')
      : '本檔歷史（全期間）：尚無可判定訊號';
    const q      = s.quote || s.raw_reason || '';
    const qShort = q.length > 80 ? q.slice(0, 80) + '…' : q;
    const entryP = s.entry_p != null ? s.entry_p.toFixed(2) : 'N/A';
    const currP  = s.curr_p  != null ? s.curr_p.toFixed(2)  : 'N/A';
    const daysD  = s.days != null ? s.days + ' 天' : 'N/A';

    return `<div class="led" role="button" tabindex="0" aria-expanded="false" aria-controls="lgd-${{i}}"
        onclick="toggleLed(${{i}}, this)"
        onkeydown="if(event.key==='Enter'||event.key===' '){{{{event.preventDefault();toggleLed(${{i}}, this);}}}}">
      <div class="led-r1">
        <span class="led-nm">${{escapeHtml(s.name)}}</span>
        <span class="led-cd">${{escapeHtml(s.code)}}</span>
        <span class="led-dir ${{dirCls}}">${{dirLbl}}</span>
      </div>
      <div class="led-r2">${{escapeHtml(s.ep)}} · 上架於 ${{s.entry_date || '日期不詳'}}${{agoTxt}} · ${{mkt}}</div>
      ${{qShort ? `<blockquote class="led-q">「${{escapeHtml(qShort)}}」</blockquote>` : ''}}
      <div class="led-st ${{stCls}}">${{stLbl}}</div>
      <div class="led-nums">個股 <b>${{fp(s.s_pct)}}</b><span class="sep">｜</span>同期 ${{escapeHtml(s.bm || '')}} <b>${{fp(s.b_pct)}}</b></div>
      <div class="led-hist">${{histTxt}}</div>
      <div class="led-detail" id="lgd-${{i}}">
        <div class="led-dt-head">${{escapeHtml(s.name)}}（${{escapeHtml(s.code)}}）· ${{escapeHtml(s.ep)}}</div>
        ${{s.quote ? `<div>原話：「${{escapeHtml(s.quote)}}」</div>` : ''}}
        ${{s.raw_reason ? `<div>AI 摘要原因：${{escapeHtml(s.raw_reason)}}</div>` : ''}}
        <div>進場價 ${{entryP}} → 現價 ${{currP}} · 觀察 ${{daysD}} · 信心等級 ${{escapeHtml(s.conf || 'N/A')}}${{s.tag ? ' · ' + escapeHtml(s.tag) : ''}}</div>
        <div class="fld-note">「信心等級」指節目中對這檔的信念強度（High／Medium／Low），不是 AI 對萃取正確性的信心；
          原因欄是 AI 從逐字稿摘要的，不是主持人的原句</div>
      </div>
    </div>`;
  }}).join('') + (list.length > MAX
    ? `<div class="empty-state">已顯示最新 ${{MAX}} 筆，符合條件的共 ${{list.length}} 筆——請用上方篩選縮小範圍</div>`
    : '');
}}

function toggleLed(i, el) {{
  const box = document.getElementById('lgd-' + i);
  if (!box) return;
  const open = box.style.display !== 'block';
  box.style.display = open ? 'block' : 'none';
  if (el) el.setAttribute('aria-expanded', open ? 'true' : 'false');
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
        name    = _esc(r.get("stock_name", ""))
        code    = _esc(r.get("stock_code", ""))
        ep      = _esc(r.get("episode_id", ""))
        reason  = (r.get("raw_reason") or "").strip()[:90]
        if reason and len(r.get("raw_reason", "")) > 90:
            reason += "..."
        reason  = _esc(reason)
        quote   = (r.get("exact_quote") or "").strip()[:120]
        if quote and len(r.get("exact_quote", "")) > 120:
            quote += "..."
        quote   = _esc(quote)
        entry_d = _esc(r.get("entry_date") or "")

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
      <table width="100%" cellpadding="0" cellspacing="0" border="0"
             style="max-width:620px;background:#fff;border-radius:10px;overflow:hidden;
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


# ── 目前關注度頁面（2026-08-02 索羅門新增，任務檔第8節）────────────────────
# 獨立頁面，不跟第一頁績效報告混在一起／不加 tab（任務檔8b：使用者已明確選
# 獨立頁面，避免「關注度」跟「歷史勝率」兩種不同性質的排序被誤讀成同一種
# 證據）。排名資料來自 attention.compute_attention()，這裡只負責渲染。
# 這裡走 Python 端字串直接渲染（不像主報告用 JS 從 JSON re-render）：排行榜
# 資料量遠小於主報告的全部訊號，不需要 client-side 大量互動式篩選，只留搜尋
# +市場兩個輕量 JS 篩選（跟1c簡化篩選列同一個產品判斷：夠用就好，不過度設計）。

def generate_html_attention(rows: list[dict], title: str = "目前節目關注度") -> str:
    """rows：attention.compute_attention() 的回傳值（已依 Attention 降冪排列、
    已排除60天下架的標的）。文字欄位一律套用 _esc()（比照1a的escapeHtml防護
    要求，這裡是純 Python 端渲染所以用 html.escape 版本的 _esc()，跟
    generate_html_email() 同一套防護）。"""
    today = date.today().isoformat()

    def _ep_link(ep_id: str) -> str:
        """把 EPxxx 變成可以直接開到第三頁那一集的連結。
        2026-08-11 雙審共識：訪客在這裡看到一句原話之後，想看上下文只能到第三頁
        685 集清單裡自己找，或觸發昂貴的全文搜尋——中間缺一個一鍵入口。"""
        n = _ep_num(ep_id)
        safe = _esc(ep_id)
        if n <= 0:
            return safe
        return (f'<a href="transcripts.html?ep={n}" style="color:#2b6cb0;text-decoration:none;'
                f'border-bottom:1px dotted #9dc0e0;" title="開啟 {safe} 的逐字稿">{safe}</a>')

    def _card(rank: int, r: dict) -> str:
        label, color = attention.consensus_label(r)
        name      = _esc(r["name"])
        code      = _esc(r["code"])
        mkt_label = "台股" if r["mkt"] == "tw" else "美股"
        last_ep   = _ep_link(r["last_episode"])
        age_last  = r.get("age_last")
        ago_txt   = f"（{age_last} 天前）" if isinstance(age_last, int) else ""

        # 近30天清單原本硬切 [:8] 且不加省略號，超過 8 集會靜默少列（雙審都點名）。
        all_recent = r["recent_30d_eps"]
        shown      = all_recent[:8]
        recent_eps = "、".join(_ep_link(e) for e in shown) or "無"
        if len(all_recent) > len(shown):
            recent_eps += f"…等 {len(all_recent)} 集"

        # 歷史累計次數：原本被塞進方向標籤的括號裡，跟「最近」的說明打架。
        # 拆出來獨立一行、明寫「歷史累計」，時間窗才不會被誤讀。
        # ⚠️ total_mentions 包含中性訊號（action=0），所以「N 次（X 多／Y 空）」的
        # 括號**加起來不等於 N**——實查 33 檔裡有 27 檔對不起來（台積電 128 次＝102 多
        # ＋2 空＋24 中性）。這是 2026-08-11 我自己加這一行時造成的，完工前 Codex 審查
        # 抓到。中性數不是 0 就一起列出來，不要讓卡片上出現算不平的數字。
        tot = r.get("total_mentions")
        neu = r.get("neutral_n") or 0
        if isinstance(tot, int):
            parts = f"{r['bull_n']} 多／{r['bear_n']} 空"
            if neu:
                parts += f"／{neu} 中性"
            cum_txt = f"歷史累計 {tot} 次提及（{parts}）"
        else:
            cum_txt = ""

        # 🔴 原話一律**預設展開**，不要改成點擊才展開的收合區塊。
        # 2026-08-11 外部審查（Codex）曾建議收合以縮短篇幅，2026-08-12 使用者裁決
        # 維持展開，理由是「說明要更詳細，不是更精簡」，且審查方追問後也同意照裁決走。
        # 這一行原話是訪客判斷「這個分數是怎麼來的」唯一的證據，收起來等於把佐證藏起來。
        quote_html = ""
        if r["quote"]:
            quote_html = (
                f'<div style="margin-top:6px;padding-left:10px;border-left:3px solid #ccc;'
                f'color:#888;font-style:italic;font-size:13px;">「{_esc(r["quote"])}」'
                f'<span style="color:#bbb;font-size:11px;margin-left:6px;">— {_ep_link(r["quote_ep"])}</span></div>'
            )

        # 搜尋範圍原本只有名稱＋代號，打「漲價」「AI」這類內容關鍵字一定落空。
        search_blob = _esc((r["name"] + r["code"] + " " + (r.get("quote") or "")).lower())

        return f'''
        <div class="att-card" data-name="{search_blob}" data-mkt="{r["mkt"]}">
          <div style="display:flex;align-items:center;gap:10px;">
            <div style="font-size:20px;font-weight:800;color:#bbb;min-width:28px;text-align:right;">{rank}</div>
            <div style="flex:1;min-width:0;">
              <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
                <span style="font-size:16px;font-weight:bold;color:#1a252f;">{name}</span>
                <span style="font-size:10px;background:#f1f3f5;color:#888;border-radius:4px;padding:1px 6px;">{mkt_label}</span>
                <span style="font-size:12px;color:#aaa;">{code}</span>
              </div>
              <div style="font-size:12px;margin-top:3px;color:{color};font-weight:bold;">{label}</div>
            </div>
            <div style="text-align:right;white-space:nowrap;">
              <div><span style="font-size:24px;font-weight:800;color:#2b6cb0;">{r["attention"]}</span><span style="font-size:13px;font-weight:600;color:#9db8d2;"> / 100</span></div>
              <div style="font-size:10px;color:#bbb;">近期討論熱度</div>
            </div>
          </div>
          <div style="display:flex;justify-content:space-between;margin-top:8px;font-size:11px;color:#999;flex-wrap:wrap;gap:4px;">
            <span>最後提及 {r["last_date"]}（{last_ep}）{ago_txt}</span>
            <span>{cum_txt}</span>
          </div>
          <div style="margin-top:3px;font-size:11px;color:#999;">近30天提及：{recent_eps}</div>
          {quote_html}
        </div>'''

    cards_html = "".join(_card(i + 1, r) for i, r in enumerate(rows))

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)}</title>
<style>
  body{{margin:0;padding:0;background:#f4f6f9;font-family:Arial,Helvetica,sans-serif;color:#333;}}
  .wrap{{max-width:760px;margin:20px auto;background:#fff;border-radius:8px;box-shadow:0 4px 12px rgba(0,0,0,.07);overflow:hidden;}}
  @media(max-width:600px){{.wrap{{margin:0;border-radius:0;}}}}
  .att-card{{border:1px solid #eee;border-radius:8px;padding:14px 16px;margin:0 16px 10px;background:#fff;}}
  .att-card.hidden{{display:none;}}
  .filter-btn{{margin:2px 3px;padding:5px 12px;border:1px solid #ddd;border-radius:12px;background:#fff;cursor:pointer;font-size:13px;}}
  .btn-active{{background:#1a252f!important;color:#fff!important;border-color:#1a252f!important;}}
{_NAV_TABS_CSS}
{_ONBOARD_CSS}
</style>
</head>
<body>
<div class="wrap">
  <div style="background:#1a252f;padding:20px;text-align:center;color:#fff;border-radius:8px 8px 0 0;">
    <h1 style="font-size:20px;font-weight:bold;margin:0;">{_esc(title)}</h1>
    <div style="color:#b3c1cd;font-size:13px;margin-top:4px;">{today}</div>
  </div>
  {_render_nav_tabs('attention')}
  <!-- 2026-08-11：這兩塊原本合計吃掉手機第一屏 792px（視窗才 844px），卡片幾乎看不到。
       改法是「壓密度不刪資訊」——去掉 onboarding 與黃框互相重複的那句定位說明，
       句子改短，事實一項沒少。 -->
  {_render_onboarding('sig_onboard_dismissed_attention', '怎麼看這個分數', [
      "分數 0–100，越常被提到、信心等級越高就越高；會隨時間衰減，久沒再提就會掉下來",
      "「近期偏多／偏空」是時間衰減加權後的方向；「歷史累計 N 次」是全部歷史的原始次數，兩者時間窗不同",
      "「近期立場分歧」＝加權後多空接近、講者立場不明確，不是無訊號",
      "超過60天沒被提到自動下架，歷史紀錄仍在主報告；卡片上的 EP 可以點開逐字稿",
  ])}

  <!-- 首屏警語（任務檔8b明確要求，定位差異必須在介面上明確標示）。
       2026-08-11 雙審：Codex 指出分數量尺只寫在可關閉的 onboarding 裡，關掉之後
       整頁最大的數字就變成沒有單位的裸數字；量尺說明因此併進這個常駐區塊。 -->
  <div style="margin:12px 16px;padding:10px 14px;background:#fff8e1;border:1px solid #ffe082;border-radius:8px;font-size:12.5px;color:#8a6d1f;line-height:1.6;">
    ⚠ 這是<b>節目近期討論熱度</b>，不是買賣建議，也不是這檔準不準——歷史勝率請看
    <a href="index.html" style="color:#8a6d1f;">主報告</a>。
    分數 <b>0–100</b>（提及次數 × 信心等級，再依距今天數衰減），<b>不是報酬率也不是勝率</b>；
    目前榜首 {max((r["attention"] for r in rows), default=0)} 分。
  </div>

  <div style="padding:0 16px 10px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
    <label for="att-search" style="position:absolute;left:-9999px;">搜尋標的名稱、代號或原話關鍵字</label>
    <input id="att-search" type="text" placeholder="搜尋名稱、代號或原話關鍵字..."
      aria-label="搜尋標的名稱、代號或原話關鍵字"
      oninput="attFilter()"
      style="flex:1;max-width:240px;padding:6px 12px;border:1px solid #ddd;border-radius:12px;font-size:13px;outline:none;">
    <button id="amkt-all" class="filter-btn btn-active" onclick="attSetMkt('all')">全部</button>
    <button id="amkt-tw"  class="filter-btn" onclick="attSetMkt('tw')">台股</button>
    <button id="amkt-us"  class="filter-btn" onclick="attSetMkt('us')">美股</button>
    <span id="att-count" style="font-size:12px;color:#bbb;margin-left:auto;"></span>
  </div>

  <div id="att-list">{cards_html}</div>
  <div id="att-empty" style="display:none;padding:30px;text-align:center;color:#888;font-size:13px;">沒有符合篩選條件的標的</div>

  <div style="padding:14px;text-align:center;font-size:11px;color:#bbb;border-top:1px solid #f0f0f0;">
    共 {len(rows)} 檔標的目前列入關注（超過 {attention.DELIST_DAYS} 天沒被提到自動下架，只留歷史頁）· 僅供參考，非投資建議
  </div>
</div>
<script>
{_onboard_js('sig_onboard_dismissed_attention')}
let _amkt = 'all';
function attSetMkt(m) {{
  _amkt = m;
  document.querySelectorAll('.filter-btn').forEach(b => {{
    if (b.id.startsWith('amkt-')) b.classList.toggle('btn-active', b.id === 'amkt-' + m);
  }});
  attFilter();
}}
function attFilter() {{
  const q = document.getElementById('att-search').value.trim().toLowerCase();
  const cards = document.querySelectorAll('.att-card');
  let visible = 0;
  cards.forEach(c => {{
    const nameOk = !q || (c.dataset.name || '').includes(q);
    const mktOk  = _amkt === 'all' || c.dataset.mkt === _amkt;
    const ok = nameOk && mktOk;
    c.classList.toggle('hidden', !ok);
    if (ok) visible++;
  }});
  document.getElementById('att-count').textContent = visible + ' / ' + cards.length + ' 檔';
  document.getElementById('att-empty').style.display = visible === 0 ? '' : 'none';
}}
document.addEventListener('DOMContentLoaded', attFilter);
</script>
</body>
</html>"""


# ── 逐字稿詳細頁（2026-08-02 索羅門新增，任務1d）───────────────────────────
# 目標：純瀏覽方便，不是訊號查核工具（不用對應到某筆訊號跳轉）。
#
# 679份逐字稿（episodes.json列680集，但transcripts/目錄實測只有679份.md檔，
# EP677缺檔——這是既有資料缺口，不是本工具的bug，見crosscheck.py同一輪的
# 發現與下方 export_transcripts_data() 的處理）共約35MB，遠超過任務檔提示的
# 5MB量級門檻，不可能全部塞進單一HTML的JSON blob。設計：
#   - 頁面只內嵌集數清單的中繼資料（集數/標題/日期），JSON payload維持KB等級。
#   - 每集預設收合，首次展開才用 fetch('transcripts_data/EP<n>.txt') 動態抓
#     該集全文（transcripts_data/ 由 export_transcripts_data() 從
#     transcripts/*.md 複製成純文字檔，部署時原樣複製進 _site/）。
#   - 全文搜尋：輸入關鍵字時才並行 fetch 全部集數全文做一次性搜尋（使用者
#     主動觸發才付出這個網路成本，不影響首屏載入），抓過的集數會快取，
#     不會同一集重複下載。
#   - 逐字稿內容一律用 textContent 賦值渲染（瀏覽器自動跳脫，等同於
#     escapeHtml() 的防護效果，比手動escape更不容易漏放）。

TRANSCRIPTS_DIR_NAME = "transcripts"
TRANSCRIPTS_DATA_DIR_NAME = "transcripts_data"


def export_transcripts_data(transcripts_dir: str = TRANSCRIPTS_DIR_NAME,
                             out_dir: str = TRANSCRIPTS_DATA_DIR_NAME) -> int:
    """把 transcripts/EP<n>_標題.md 逐一複製成 out_dir/EP<n>.txt（純文字，
    檔名正規化成不含中文/空白，前端 JS 用集數直接組 fetch 路徑，不用處理
    URL encoding）。只在來源檔比目的檔新，或目的檔不存在時才複製，避免
    每次跑報告都重複寫入679個檔案。回傳實際複製的檔案數。"""
    os.makedirs(out_dir, exist_ok=True)
    copied = 0
    for fname in os.listdir(transcripts_dir):
        m = re.match(r"EP(\d+)_", fname)
        if not m:
            continue
        src = os.path.join(transcripts_dir, fname)
        dst = os.path.join(out_dir, f"EP{m.group(1)}.txt")
        if not os.path.exists(dst) or os.path.getmtime(src) > os.path.getmtime(dst):
            shutil.copyfile(src, dst)
            copied += 1
    return copied


def _footer_counts(meta: list[dict]) -> str:
    """footer 原本寫死「共 N 集逐字稿」，但 N 是 episodes.json 的節目集數，
    不等於真的有逐字稿檔案的集數——已知至少 EP677 曾經缺檔。2026-08-11 外部審查
    點名這是「字面承諾全部都有」。改成實際去數 transcripts_data/ 裡有幾個檔案，
    缺的就老實講缺幾集。"""
    have = 0
    for m in meta:
        if os.path.exists(os.path.join(TRANSCRIPTS_DATA_DIR_NAME, f"EP{m['num']}.txt")):
            have += 1
    total = len(meta)
    missing = total - have
    if missing <= 0:
        return f"共 {total} 集節目，逐字稿全數齊備"
    return f"共 {total} 集節目，其中 {have} 集有逐字稿、{missing} 集檔案缺失（展開會顯示提示）"


def generate_html_transcripts(episodes: list[dict], title: str = "逐字稿") -> str:
    """episodes：episodes.json 內容（number/title/display_title/date...）。
    只用來組『集數清單』中繼資料，不讀逐字稿內容本身（內容由前端 lazy fetch）。
    找不到對應 transcripts_data/EP<n>.txt 的集數（目前已知 EP677）一樣列出來，
    展開時 fetch 404 會顯示清楚的「這集逐字稿檔案缺失」提示，不是靜默失敗。"""
    today = date.today().isoformat()
    eps_sorted = sorted(episodes, key=lambda e: e.get("number", 0), reverse=True)
    meta = []
    for e in eps_sorted:
        # 2026-08-02完工前Codex最終審查指出：number未經型別驗證就直接插進
        # HTML屬性與inline onclick JS（見下方_item()），episodes.json是從
        # 外部網站下載的資料，理論上若上游被污染塞進非整數字串，這裡會變成
        # 一個stored XSS缺口。用int()強制轉型當防線——轉不成功代表資料本身
        # 有問題，跳過這筆並警告，不要讓非整數值有機會流進HTML/JS。
        try:
            num = int(e.get("number"))
        except (TypeError, ValueError):
            logging.warning(f"[report_html] episodes.json 有一筆 number 不是合法整數，跳過：{e.get('number')!r}")
            continue
        meta.append({
            "num":   num,
            "title": e.get("display_title") or e.get("title") or "",
            "date":  e.get("date", ""),
        })
    meta_json = _json_for_script(meta, ensure_ascii=False)

    def _item(m: dict) -> str:
        num = m["num"]
        # 2026-08-11：補上鍵盤與螢幕閱讀器支援。第一頁的 .led / .stock-card 昨晚
        # 已經補過 role/tabindex/aria-expanded，這頁還停在純 div + onclick。
        return f'''
        <div class="tr-item" id="tr-item-{num}" data-num="{num}" data-title="{_esc(m["title"]).lower()}">
          <div class="tr-head" role="button" tabindex="0" aria-expanded="false"
               aria-controls="tr-body-{num}" id="tr-head-{num}"
               onclick="trToggle({num})" onkeydown="trKey(event,{num})">
            <span class="tr-num">EP{num}</span>
            <span class="tr-title">{_esc(m["title"])}</span>
            <span class="tr-date">{_esc(m["date"])}</span>
            <span class="tr-arrow" id="tr-arrow-{num}">&#9656;</span>
          </div>
          <div class="tr-body" id="tr-body-{num}" style="display:none;"></div>
        </div>'''

    items_html = "".join(_item(m) for m in meta)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)}</title>
<style>
  body{{margin:0;padding:0;background:#f4f6f9;font-family:Arial,Helvetica,sans-serif;color:#333;}}
  .wrap{{max-width:820px;margin:20px auto;background:#fff;border-radius:8px;box-shadow:0 4px 12px rgba(0,0,0,.07);overflow:hidden;}}
  @media(max-width:600px){{.wrap{{margin:0;border-radius:0;}}}}
  .tr-item{{border-bottom:1px solid #eee;}}
  .tr-head{{display:flex;align-items:center;gap:8px;padding:10px 16px;cursor:pointer;flex-wrap:wrap;}}
  .tr-head:hover{{background:#fafbfc;}}
  .tr-num{{font-size:12px;color:#fff;background:#2b6cb0;border-radius:4px;padding:2px 6px;font-weight:bold;white-space:nowrap;}}
  .tr-title{{font-size:14px;color:#1a252f;flex:1;min-width:120px;}}
  .tr-date{{font-size:11px;color:#aaa;white-space:nowrap;}}
  .tr-arrow{{color:#bbb;font-size:12px;}}
  .tr-body{{padding:4px 16px 16px;white-space:pre-wrap;word-break:break-word;font-size:13px;line-height:1.7;color:#444;background:#fafcff;}}
  .tr-item.hidden{{display:none;}}
{_NAV_TABS_CSS}
{_ONBOARD_CSS}
</style>
</head>
<body>
<div class="wrap">
  <div style="background:#1a252f;padding:20px;text-align:center;color:#fff;border-radius:8px 8px 0 0;">
    <div style="font-size:20px;font-weight:bold;">{_esc(title)}</div>
    <div style="color:#b3c1cd;font-size:13px;margin-top:4px;">{today} · 純瀏覽用，不是訊號查核工具</div>
  </div>
  {_render_nav_tabs('transcripts')}
  {_render_onboarding('sig_onboard_dismissed_transcripts', '這頁在做什麼', [
      "這裡是逐字稿原文，純瀏覽用，不是訊號查核工具",
      "點集數標題可以展開／收合看全文（也可以用鍵盤 Tab 移動、Enter 展開）",
      "打字＝只搜集數標題，立刻有結果；要連內文一起搜請按旁邊的按鈕（會下載約 35MB，有進度可取消）",
      "部分較舊集數逐字稿檔案可能缺失，會顯示明確提示；連不上網路是另一種提示，兩者不會混在一起",
      "從「目前關注度」頁點 EP 編號進來，會自動展開並跳到那一集",
  ])}

  <!-- 2026-08-11 雙審兩邊都把「首次全文搜尋」列為本頁最嚴重問題：一輸入就對
       685 集發並行請求（約 35MB），沒有進度、不能取消、失敗還會被靜默吞掉。
       改成兩段式：打字先即時篩標題（免費、零下載），要搜正文才按按鈕。 -->
  <div style="padding:0 16px 10px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:12px;">
    <label for="tr-search" style="position:absolute;left:-9999px;">搜尋集數標題或逐字稿全文</label>
    <input id="tr-search" type="text" placeholder="搜尋集數標題…"
      aria-label="搜尋集數標題或逐字稿全文"
      oninput="trOnSearchInput(this.value)" onkeydown="if(event.key==='Enter')trStartFullSearch()"
      style="flex:1;max-width:280px;padding:6px 12px;border:1px solid #ddd;border-radius:12px;font-size:13px;outline:none;">
    <button id="tr-full-btn" onclick="trStartFullSearch()"
      style="padding:6px 12px;border:1px solid #2b6cb0;background:#2b6cb0;color:#fff;border-radius:12px;font-size:12px;cursor:pointer;">
      連內文一起搜（約 35MB）</button>
    <button id="tr-cancel-btn" onclick="trCancelFullLoad()" style="display:none;padding:6px 12px;border:1px solid #ddd;background:#fff;color:#666;border-radius:12px;font-size:12px;cursor:pointer;">取消</button>
    <span id="tr-status" style="font-size:12px;color:#bbb;">共 {len(meta)} 集</span>
  </div>

  <div id="tr-list">{items_html}</div>
  <div id="tr-empty" style="display:none;padding:30px;text-align:center;color:#888;font-size:13px;">沒有符合搜尋條件的集數</div>

  <div style="padding:14px;text-align:center;font-size:11px;color:#bbb;border-top:1px solid #f0f0f0;">
    {_footer_counts(meta)} · 純瀏覽用，不代表節目立場
  </div>
</div>
<script>
{_onboard_js('sig_onboard_dismissed_transcripts')}
const TR_META = {meta_json};
const _trTextCache = {{}};    // num -> 全文（已完成的下載結果快取，不重複下載）
const _trPending = {{}};      // num -> 進行中的fetch Promise（2026-08-02完工前
                            // Codex最終審查指出：原本只靠_trTextCache擋重複
                            // 下載，但同一個num的fetch還沒resolve前，第二次
                            // 呼叫trFetchOne()看到cache還是undefined，會再送
                            // 一次fetch——尤其trEnsureAllLoaded()一次對679個
                            // num發動Promise.all時，若使用者手滑觸發第二次
                            // 搜尋，兩批Promise.all會互相疊加成上千個並行
                            // 請求。這裡改成同一個num的fetch進行中時直接回傳
                            // 同一個pending promise，不重新發起。
let _trFullLoaded = false;
let _trFullLoadPromise = null;
let _trSearchGen = 0;  // 搜尋世代計數器：避免舊搜尋在使用者已經改了關鍵字之後
                        // 才跑完，用過期結果覆蓋新搜尋的畫面（見trDoSearch()）

const _trErrKind = {{}};      // num -> 'missing' | 'network'（2026-08-11 新增）
                            // 原本 404、網路斷線、CORS 全部塞進同一個 null，
                            // 畫面一律說「檔案缺失」——使用者被錯誤診斷，
                            // 自己以為要去補檔案，實際上只是網路斷了。
let _trCancelled = false;   // 全文下載的取消旗標

async function trFetchOne(num) {{
  if (_trTextCache[num] !== undefined) return _trTextCache[num];
  if (_trPending[num]) return _trPending[num];
  const p = (async () => {{
    try {{
      const resp = await fetch('{TRANSCRIPTS_DATA_DIR_NAME}/EP' + num + '.txt');
      if (!resp.ok) {{
        // 404＝伺服器上沒有這個檔（多半是這集真的缺逐字稿，但也可能是部署漏拷貝）；
        // 其餘狀態碼視為暫時性問題。
        if (resp.status === 404) {{
          _trErrKind[num] = 'missing';
          _trTextCache[num] = null;      // 永久性結果，可以快取
        }} else {{
          _trErrKind[num] = 'network';
          delete _trTextCache[num];      // 暫時性失敗**不可以快取**，否則重試會直接
        }}                                // 讀到快取的 null、根本不會重新發請求
        return null;
      }}
      const text = await resp.text();
      _trTextCache[num] = text;
      return text;
    }} catch (e) {{
      _trErrKind[num] = 'network';   // fetch 直接 reject＝連不上，不是缺檔
      delete _trTextCache[num];      // 同上：留成 undefined 才有機會重試
      return null;
    }} finally {{
      delete _trPending[num];
    }}
  }})();
  _trPending[num] = p;
  return p;
}}

function trKey(ev, num) {{
  if (ev.key === 'Enter' || ev.key === ' ' || ev.key === 'Spacebar') {{
    ev.preventDefault();
    trToggle(num);
  }}
}}

async function trToggle(num, forceOpen) {{
  const body  = document.getElementById('tr-body-' + num);
  const arrow = document.getElementById('tr-arrow-' + num);
  const head  = document.getElementById('tr-head-' + num);
  if (!body) return;
  const isOpen = body.style.display !== 'none';
  if (isOpen && !forceOpen) {{
    body.style.display = 'none';
    arrow.innerHTML = '&#9656;';
    if (head) head.setAttribute('aria-expanded', 'false');
    return;
  }}
  if (!body.dataset.loaded) {{
    body.textContent = '載入中...';
    const text = await trFetchOne(num);
    if (text === null) {{
      body.textContent = (_trErrKind[num] === 'network')
        ? '載入失敗：連不到逐字稿檔案（網路或伺服器問題），請稍後再點一次重試。這不代表這集沒有逐字稿。'
        : '找不到這集的逐字稿檔案（伺服器回 404）。多半是這一集本來就缺逐字稿，也可能是部署時沒被複製上去；不是網頁壞了。';
      // 只有 404 這種永久性結果才標記 loaded；網路失敗不標記，配合 trFetchOne()
      // 不快取暫時性失敗，再點一次才會真的重新發請求。
      if (_trErrKind[num] !== 'network') body.dataset.loaded = '1';
    }} else {{
      body.textContent = text;
      body.dataset.loaded = '1';
    }}
  }}
  body.style.display = '';
  arrow.innerHTML = '&#9662;';
  if (head) head.setAttribute('aria-expanded', 'true');
}}

function trCancelFullLoad() {{
  // 誠實說明範圍：這是「停止排入新的下載」，已經送出的那幾個請求不會被中斷
  // （要真的中斷得用 AbortController，那是另一層改動）。
  _trCancelled = true;
  document.getElementById('tr-cancel-btn').style.display = 'none';
  document.getElementById('tr-status').textContent =
    '已停止排入新下載（少數已送出的請求會自己跑完）；已下載的集數仍可搜尋，按「連內文一起搜」可繼續';
}}

// 有界並行的全量下載：原本一次 Promise.all 685 個請求，瀏覽器自己排隊、
// 期間畫面完全沒有回饋。改成一次 8 個、每完成一個就更新進度，並可取消。
async function trEnsureAllLoaded() {{
  if (_trFullLoaded) return;
  if (_trFullLoadPromise) return _trFullLoadPromise;
  const status = document.getElementById('tr-status');
  const cancelBtn = document.getElementById('tr-cancel-btn');
  _trCancelled = false;
  cancelBtn.style.display = '';
  const queue = TR_META.map(m => m.num);
  const total = queue.length;
  let done = 0, failed = 0, netFail = 0, idx = 0;
  const CONC = 8;
  async function worker() {{
    while (idx < queue.length && !_trCancelled) {{
      const num = queue[idx++];
      const t = await trFetchOne(num);
      done++;
      if (t === null) {{
        failed++;
        if (_trErrKind[num] === 'network') netFail++;
      }}
      // 取消之後不要再蓋掉「已停止」那句提示
      if (!_trCancelled && (done % 10 === 0 || done === total)) {{
        status.textContent = '下載逐字稿中… ' + done + ' / ' + total
          + (failed ? '（' + failed + ' 集取不到）' : '');
      }}
    }}
  }}
  _trFullLoadPromise = Promise.all(Array.from({{length: CONC}}, worker)).then(() => {{
    // 有網路失敗就**不要**標記成全量完成，否則下次搜尋會直接 return、永遠不重試那幾集
    if (!_trCancelled && netFail === 0) _trFullLoaded = true;
    cancelBtn.style.display = 'none';
    _trFullLoadPromise = null;
  }});
  await _trFullLoadPromise;
}}

let _trSearchTimer = null;
function trOnSearchInput(v) {{
  clearTimeout(_trSearchTimer);
  // 世代號在**按鍵當下**就遞增，不能等 debounce 之後才進 trDoSearch() 才加——
  // 否則舊的全文搜尋若剛好在這 250ms 空窗內跑完，還是會蓋掉使用者已經改掉的關鍵字。
  _trSearchGen++;
  _trSearchTimer = setTimeout(() => trDoSearch(v, false), 250);
}}

// 打字時只搜標題（零下載、立即回應）；要搜正文得自己按按鈕，
// 才不會有人隨手打一個字就觸發 35MB 下載。
async function trStartFullSearch() {{
  const q = document.getElementById('tr-search').value.trim();
  if (!q) {{
    document.getElementById('tr-status').textContent = '請先輸入要搜尋的關鍵字';
    return;
  }}
  await trDoSearch(q, true);
}}

async function trDoSearch(q, fullText) {{
  q = (q || '').trim();
  const myGen = ++_trSearchGen;  // 世代號：舊搜尋跑完時若已不是最新，放棄更新畫面
  const status = document.getElementById('tr-status');
  const items = document.querySelectorAll('.tr-item');
  if (!q) {{
    items.forEach(el => el.classList.remove('hidden'));
    document.getElementById('tr-empty').style.display = 'none';
    status.textContent = '共 ' + TR_META.length + ' 集';
    return;
  }}
  if (fullText) {{
    await trEnsureAllLoaded();
    if (myGen !== _trSearchGen) return;
  }}
  const ql = q.toLowerCase();
  let matched = 0, bodyHit = 0;
  items.forEach(el => {{
    const num = el.dataset.num;
    const titleHit = (el.dataset.title || '').includes(ql);
    let hit = titleHit;
    if (fullText && !hit) {{
      const text = (_trTextCache[num] || '').toLowerCase();
      if (text.includes(ql)) {{ hit = true; bodyHit++; }}
    }}
    el.classList.toggle('hidden', !hit);
    if (hit) matched++;
  }});
  document.getElementById('tr-empty').style.display = matched === 0 ? '' : 'none';
  if (fullText) {{
    // 沒抓到的集數要老實講：原本靜默吞掉，結果數字照算，使用者不知道搜漏了。
    const missing = TR_META.filter(m => _trTextCache[m.num] === null).length;
    const notLoaded = TR_META.filter(m => _trTextCache[m.num] === undefined).length;
    let note = '';
    if (missing) note += '，' + missing + ' 集內文取不到';
    if (notLoaded) note += '，' + notLoaded + ' 集尚未下載（搜尋不含這些集）';
    status.textContent = matched + ' / ' + TR_META.length + ' 集符合「' + q + '」'
      + '（含內文命中 ' + bodyHit + ' 集）' + note;
  }} else {{
    status.textContent = matched + ' / ' + TR_META.length + ' 集標題符合「' + q
      + '」·　要連內文一起搜請按右邊按鈕';
  }}
}}

// 深連結：第二頁的 EP 編號會連到 transcripts.html?ep=685，這裡負責展開並捲過去。
async function trOpenFromUrl() {{
  const m = /[?&]ep=(\\d+)/.exec(location.search) || /^#ep-(\\d+)$/.exec(location.hash);
  if (!m) return;
  const num = parseInt(m[1], 10);
  const item = document.getElementById('tr-item-' + num);
  if (!item) return;
  await trToggle(num, true);
  item.scrollIntoView({{behavior: 'smooth', block: 'start'}});
  item.style.transition = 'background .4s';
  item.style.background = '#fffbe6';
  setTimeout(() => {{ item.style.background = ''; }}, 2000);
}}
trOpenFromUrl();
</script>
</body>
</html>"""

