"""
CLI 績效報告：python -X utf8 report.py [--fill] [--ep EP672]
  --fill   先補抓所有缺少進場價的訊號（第一次跑必須加）
  --ep     只顯示特定集數
"""
import sys
import textwrap
from performance import _fill_entry_prices, calc_performance, win_rate

sys.stdout.reconfigure(encoding="utf-8")

WIN_MARK = {"True": "✅ Win", "False": "❌ Lose", "None": "⏳ N/A"}


def action_label(action: str, confidence: str) -> str:
    if action == "+1":
        return "超級看好" if confidence == "High" else "看好"
    if action == "-1":
        return "看壞"
    return "中性"


def fmt_pct(v) -> str:
    if v is None:
        return "  N/A  "
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.2f}%"


def main():
    args = sys.argv[1:]
    fill      = "--fill" in args
    ep_filter = None
    if "--ep" in args:
        idx = args.index("--ep")
        ep_filter = args[idx + 1] if idx + 1 < len(args) else None

    if fill:
        print("補抓進場價中...")
        n = _fill_entry_prices()
        print(f"已更新 {n} 筆\n")

    results = calc_performance()
    if ep_filter:
        results = [r for r in results if r.get("episode_id") == ep_filter]

    if not results:
        print("無資料（先跑 main.py 分析集數，再用 --fill 補進場價）")
        return

    results.sort(key=lambda r: (r.get("entry_date") or "", r.get("episode_id") or ""))

    header = (f"{'EP':<8} {'股票':<18} {'代號':<12} {'動作':<6} "
              f"{'進場價':>8} {'現價':>8} {'個股報酬':>9} {'大盤報酬':>9} {'天數':>5} {'勝負':<10}")
    sep = "─" * len(header)
    print(header)
    print(sep)

    for r in results:
        ep      = r.get("episode_id", "?")
        name    = (r.get("stock_name") or "")[:16]
        code    = (r.get("stock_code") or "")[:10]
        label   = action_label(r.get("action", "0"), r.get("confidence_level", ""))
        entry_p = f"{r['entry_price']:.2f}" if r.get("entry_price") else "  N/A"
        curr_p  = f"{r['current_price']:.2f}" if r.get("current_price") else "  N/A"
        s_pct   = fmt_pct(r.get("stock_return_pct"))
        b_pct   = fmt_pct(r.get("benchmark_return_pct"))
        days    = str(r.get("days_held") or "N/A")
        beat    = WIN_MARK.get(str(r.get("beat_benchmark")), "⏳ N/A")

        print(f"{ep:<8} {name:<18} {code:<12} {label:<6} "
              f"{entry_p:>8} {curr_p:>8} {s_pct:>9} {b_pct:>9} {days:>5} {beat}")

        quote = (r.get("exact_quote") or "").strip()
        if quote:
            # 折行顯示，縮排 4 格，每行限 100 字
            for line in textwrap.wrap(quote, width=100):
                print(f"    「{line}」")

    print(sep)

    stats = win_rate(results)
    print(f"\n總訊號：{stats['total']}  已有報酬資料：{stats['decided']}  "
          f"Win：{stats['wins']}  Lose：{stats['losses']}  "
          f"勝率：{stats['win_rate']}%")

    for action_key, lbl in [("+1", "看好/超級看好"), ("-1", "看壞")]:
        sub = [r for r in results if r.get("action") == action_key and r.get("beat_benchmark") is not None]
        if sub:
            w = sum(1 for r in sub if r["beat_benchmark"])
            print(f"  {lbl}勝率：{w}/{len(sub)} = {w/len(sub)*100:.1f}%")


if __name__ == "__main__":
    main()
