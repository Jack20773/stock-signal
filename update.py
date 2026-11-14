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


def _warn_analysis_failed(failed: int):
    """重試後仍失敗：寫警告檔＋戰情室卡（best-effort，本身出錯不再往上拋）。"""
    import datetime, subprocess
    from pathlib import Path
    msg = (f"{datetime.datetime.now():%Y-%m-%d %H:%M} 有 {failed} 集逐字稿分析重試後仍失敗，"
           f"看 batch.log 與 ops/logs/daily_*.log；下次排程會再自動重跑未分析集數。")
    logging.error("🔴 " + msg)
    try:
        here = Path(__file__).resolve().parent
        (here / "ops" / "ANALYSIS_FAILED_WARNING.txt").write_text(msg + "\n", encoding="utf-8")
        task = Path(r"D:/All claude/000_Agent/007_dashboard/task.py")
        if task.exists():
            subprocess.run([sys.executable, "-X", "utf8", str(task), "new",
                            "--id", f"stocksignal-analysis-failed-{datetime.date.today():%Y%m%d}",
                            "--title", "股癌逐字稿分析重試後仍失敗", "--owner", "ai", "--dept", "invest",
                            "--plain", msg, "--color", "red", "--status", "open", "--no-dispatch"],
                           timeout=60, capture_output=True)
    except Exception as e:
        logging.error(f"寫警告失敗：{e}")


def run(args):
    # ── Step 1：下載新逐字稿 ─────────────────────────────────────────
    step(1, "下載新逐字稿")
    from download_transcripts import main as dl_main
    dl_main(last_n=args.last)
    # 2026-11-14：第三方逐字稿站常晚好幾天才上新集，本機 asr-lab 其實早轉好了——先橋接進來
    # （RSS 有、episodes.json 沒有、asr-lab/out_best 有 SRT 才補；失敗不擋後面）
    if not getattr(args, "dry_run", False):
        from bridge_asrlab import bridge
        bridge()

    # ── Step 2：批次分析（跳過已分析集數）────────────────────────────
    from_ep = getattr(args, "from_ep", 0) or 0
    label = f"EP{from_ep}+" if from_ep else f"最新 {args.last} 集"
    step(2, f"批次分析 {label}（Gemini API）")
    from database import init_db
    from batch import load_transcripts, run_batch
    init_db()
    files = load_transcripts(from_ep=from_ep, last_n=0 if from_ep else args.last)
    if files:
        logging.info(f"待處理 {len(files)} 集")
        _done, _skipped, failed = run_batch(files, dry_run=args.dry_run)
        if failed and not args.dry_run:
            # 2026-11-14：單集內的 5s/10s 重試只隔 15 秒，API 短暫異常（11/12 EP713 claude -p exit=1）
            # 擋不住。這裡等 2 分鐘後整批再跑一次（已分析的集數會自動跳過，只重跑失敗的）；
            # 仍失敗就寫警告檔＋戰情室卡，不再靜默。
            import time
            logging.warning(f"⚠ 有 {failed} 集分析失敗，120 秒後自動重試一次")
            time.sleep(120)
            _d2, _s2, failed = run_batch(files, dry_run=False)
            if failed:
                _warn_analysis_failed(failed)
        elif failed:
            logging.warning(f"⚠ 有 {failed} 集分析失敗（dry-run）")
    else:
        logging.info("無新集數需要分析")

    if args.dry_run:
        logging.info("\ndry-run 模式，跳過後續步驟")
        return

    # ── Step 3：補進場價 + 計算勝率快照 ─────────────────────────────
    step(3, "補進場價 + 更新績效快照")
    from performance import _fill_entry_prices, calc_performance, win_rate
    n = _fill_entry_prices()
    logging.info(f"已補 {n} 筆進場價")
    results = calc_performance()
    stats = win_rate(results)  # 跟 notifier.run_report() 內部原本重算的口徑一致（全集計算）
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
        results    = results,   # 2026-08-02：Step3 已經算過，直接傳給 Step4，不重算一次
        stats      = stats,     # calc_performance()/win_rate()（任務第2項）
    )

    logging.info(f"\n{'='*50}")
    logging.info("✅ 更新完成")
    if not args.send:
        logging.info("→ 預覽：report_preview.html（未寄信，加 --send 才寄）")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--last",       type=int, default=20,  help="分析最新 N 集（預設 20）")
    parser.add_argument("--from-ep",    type=int, default=0,   help="從第幾集開始分析（例：400 = EP400 起）")
    parser.add_argument("--dry-run",    action="store_true",  help="只列清單，不呼叫 Gemini API")
    parser.add_argument("--send",       action="store_true",  help="完成後寄出 email 報告")
    parser.add_argument("--report-last", type=int, default=50, help="email 只顯示最新 N 集（預設 50）")
    parser.add_argument("--detail-url", default="",           help="詳細版 URL（加在 email 按鈕）")
    args = parser.parse_args()
    if args.last < 0 or args.from_ep < 0 or args.report_last < 0:
        # 負數不報錯，但下游全靠 list[-N:] 切片，語意跟使用者想少跑幾集的直覺
        # 相反——2026-08-01 索羅門診斷 + Codex 審查一起發現，三個數量型參數一起擋。
        parser.error("--last / --from-ep / --report-last 不可為負數")
    run(args)


if __name__ == "__main__":
    main()
