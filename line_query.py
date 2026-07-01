"""
LINE Bot 查詢介面。由 linebot/stock_handler.py 以 subprocess 呼叫。
用法：
  python -X utf8 line_query.py query EP672
  python -X utf8 line_query.py perf
  python -X utf8 line_query.py latest
  python -X utf8 line_query.py analyze EP672
"""
import sys
import glob
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

from database import init_db, list_signals, save_result, _conn
from performance import calc_performance, _fill_entry_prices
from analyzer import analyze

ACTION_LABEL = {
    ("+1", "High"):   "🔥 超級看好",
    ("+1", "Medium"): "👍 看好",
    ("+1", "Low"):    "👍 看好",
    ("-1", "High"):   "👎 看壞",
    ("-1", "Medium"): "👎 看壞",
    ("-1", "Low"):    "👎 看壞",
}

TRANSCRIPT_DIR = Path(__file__).parent / "transcripts"


def fmt_pct(v) -> str:
    if v is None:
        return "N/A"
    return f"+{v:.1f}%" if v >= 0 else f"{v:.1f}%"


def _perf_map(episode_id: str) -> dict:
    try:
        return {
            r["stock_code"]: r
            for r in calc_performance()
            if r.get("episode_id") == episode_id
        }
    except Exception:
        return {}


def cmd_query(episode_id: str):
    init_db()
    signals  = list_signals(episode_id)
    non_zero = [s for s in signals if s.get("action") != "0"]

    if not signals:
        print(f"{episode_id} 尚未分析。\n傳「/股癌分析 {episode_id}」進行分析。")
        return

    perf = _perf_map(episode_id)
    lines = [f"📊 {episode_id}"]

    for s in non_zero:
        code   = s.get("stock_code", "")
        name   = s.get("stock_name", "")
        action = s.get("action", "0")
        conf   = s.get("confidence_level", "")
        quote  = (s.get("exact_quote") or "").strip()
        label  = ACTION_LABEL.get((action, conf), "👀")

        lines.append(f"\n{label} {name}（{code}）")

        p = perf.get(code)
        if p and p.get("stock_return_pct") is not None:
            s_pct = fmt_pct(p["stock_return_pct"])
            b_pct = fmt_pct(p.get("benchmark_return_pct"))
            bm    = p.get("benchmark_ticker", "")
            days  = p.get("days_held", 0)
            icon  = "✅" if p.get("beat_benchmark") else "❌"
            lines.append(f"{icon} {s_pct} vs {bm} {b_pct}（{days}天）")
        elif p:
            lines.append("⏳ 尚無價格資料")

        if quote:
            short_q = quote[:120] + "…" if len(quote) > 120 else quote
            lines.append(f"「{short_q}」")

    print("\n".join(lines))


def cmd_perf():
    init_db()
    results = calc_performance()
    decided = [r for r in results if r.get("beat_benchmark") is not None]
    wins    = [r for r in decided if r.get("beat_benchmark")]
    rate    = round(len(wins) / len(decided) * 100, 1) if decided else 0.0

    lines = [f"📈 股癌整體勝率：{len(wins)}/{len(decided)} = {rate}%\n"]

    for r in sorted(results, key=lambda x: x.get("entry_date") or "", reverse=True)[:12]:
        if r.get("action") == "0":
            continue
        ep    = r.get("episode_id", "?")
        name  = (r.get("stock_name") or "")[:8]
        label = ACTION_LABEL.get((r.get("action"), r.get("confidence_level", "")), "")[:2]
        s_pct = fmt_pct(r.get("stock_return_pct"))
        beat  = r.get("beat_benchmark")
        icon  = "✅" if beat else ("❌" if beat is False else "⏳")
        lines.append(f"{icon} {label} {ep} {name}  {s_pct}")

    print("\n".join(lines))


def cmd_latest():
    init_db()
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT episode_id FROM signals ORDER BY created_at DESC LIMIT 1")
            row = cur.fetchone()
    if not row:
        print("尚未分析任何集數。")
        return
    cmd_query(row["episode_id"])


def cmd_analyze(episode_id: str):
    ep_num  = episode_id.lstrip("EPep")
    matches = glob.glob(str(TRANSCRIPT_DIR / f"EP{ep_num}_*.md"))

    if not matches:
        print(f"找不到 {episode_id} 的逐字稿（本機 transcripts/）。\n先執行 download_transcripts.py 更新。")
        return

    transcript = Path(matches[0]).read_text(encoding="utf-8")

    existing = list_signals(episode_id)
    if existing:
        cmd_query(episode_id)
        return

    print(f"⏳ 分析 {episode_id} 中…", flush=True)

    try:
        result = analyze(transcript)
        count  = save_result(result)
        if count > 0:
            print(f"提取 {count} 個訊號，補抓進場價中…", flush=True)
            _fill_entry_prices()
        cmd_query(episode_id)
    except Exception as e:
        print(f"分析失敗：{e}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print("用法：python -X utf8 line_query.py [query EP672 | perf | latest | analyze EP672]")
        sys.exit(1)

    subcmd = args[0].lower()
    if subcmd == "query" and len(args) > 1:
        cmd_query(args[1].upper())
    elif subcmd == "perf":
        cmd_perf()
    elif subcmd == "latest":
        cmd_latest()
    elif subcmd == "analyze" and len(args) > 1:
        cmd_analyze(args[1].upper())
    else:
        print(f"未知指令：{' '.join(args)}")
        sys.exit(1)
