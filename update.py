"""
一鍵更新：下載新逐字稿 → 批次分析 → 補進場價 → 生成詳細報告

用法：
  python -X utf8 update.py              # 分析最新 20 集
  python -X utf8 update.py --last 50    # 分析最新 50 集
  python -X utf8 update.py --preview    # 存 report_preview.html（不寄信）
  python -X utf8 update.py --send       # 完整流程 + 寄信
"""
import sys
import argparse
import logging

sys.stdout.reconfigure(encoding="utf-8")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

STEP_SEP = "─" * 50


def step(n: int, title: str):
    logging.info(f"\n{STEP_SEP}\n[Step {n}] {title}\n{STEP_SEP}")


def run(args):
    # ── Step 1：下載新逐字稿 ─────────────────────────────────────────
    step(1, "下載新逐字稿")
    from download_transcripts import main as dl_main
    dl_main(last_n=args.last)

    # ── Step 2：批次分析（跳過已分析集數）────────────────────────────
    step(2, f"批次分析最新 {args.last} 集（Gemini API）")
    from database import init_db
    from batch import load_transcripts, run_batch
    init_db()
    files = load_transcripts(last_n=args.last)
    if files:
        logging.info(f"待處理 {len(files)} 集")
        run_batch(files, dry_run=args.dry_run)
    else:
        logging.info("無新集數需要分析")

    if args.dry_run:
        logging.info("\ndry-run 模式，跳過後續步驟")
        return

    # ── Step 3：補進場價 + 計算勝率快照 ─────────────────────────────
    step(3, "補進場價 + 更新績效快照")
    from performance import _fill_entry_prices, calc_performance
    n = _fill_entry_prices()
    logging.info(f"已補 {n} 筆進場價")
    results = calc_performance()
    logging.info(f"績效快照已更新（{len(results)} 筆）")

    # ── Step 4：生成報告 ─────────────────────────────────────────────
    step(4, "生成 HTML 報告")
    from notifier import run_report
    run_report(
        fill       = False,     # Step 3 已做過，跳過
        last_n     = args.report_last,
        preview    = not args.send,
        no_send    = not args.send,
        detail_url = args.detail_url,
    )

    logging.info(f"\n{'='*50}")
    logging.info("✅ 更新完成")
    if not args.send:
        logging.info("→ 預覽：report_preview.html（未寄信，加 --send 才寄）")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--last",       type=int, default=20, help="分析最新 N 集（預設 20）")
    parser.add_argument("--dry-run",    action="store_true",  help="只列清單，不呼叫 Gemini API")
    parser.add_argument("--send",       action="store_true",  help="完成後寄出 email 報告")
    parser.add_argument("--report-last", type=int, default=50, help="email 只顯示最新 N 集（預設 50）")
    parser.add_argument("--detail-url", default="",           help="詳細版 URL（加在 email 按鈕）")
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
