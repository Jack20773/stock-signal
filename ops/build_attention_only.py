# -*- coding: utf-8 -*-
"""只重建 report_attention.html（不寄信、不寫 signals、不算績效）。

2026-09-17 新增，給「病歷卡」驗證用；跟 notifier.run_report() 裡產 attention 那一段
走同一條路（compute_attention → company_notes.attach_history → generate_html_attention），
差別只有多幾個開關做對照組：

  python -X utf8 ops/build_attention_only.py                     # 正常
  python -X utf8 ops/build_attention_only.py --no-history        # 對照：history 清空，卡片要退回原樣
  python -X utf8 ops/build_attention_only.py --null-summary NVDA # 對照：某檔 summary 全設 NULL（只在記憶體裡）
  python -X utf8 ops/build_attention_only.py --out X.html        # 輸出到別的檔

唯一會寫 DB 的地方是 prices 的 price_cache upsert（既有快取機制，純附加）。
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])

from attention import compute_attention  # noqa: E402
from database import list_signals  # noqa: E402
from report_html import generate_html_attention  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-history", action="store_true", help="對照組：不掛 history")
    ap.add_argument("--no-prices", action="store_true", help="不抓股價（離線測版面）")
    ap.add_argument("--null-summary", default="", help="對照組：把這檔的 summary 清成空（只在記憶體）")
    ap.add_argument("--out", default="report_attention.html")
    a = ap.parse_args()

    rows = compute_attention(list_signals())
    print(f"上榜 N 檔 = {len(rows)}")
    stats = None
    if not a.no_history:
        from company_notes import attach_history
        stats = attach_history(rows, with_prices=not a.no_prices)
        print("company_notes stats:", stats)
        if a.null_summary:
            hit = 0
            for r in rows:
                if r["code"] == a.null_summary:
                    for h in r.get("history") or []:
                        h["summary"] = ""
                        hit += 1
            print(f"--null-summary {a.null_summary}: 清了 {hit} 條")
    html = generate_html_attention(rows)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"寫入 {a.out}（{len(html):,} bytes）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
