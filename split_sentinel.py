"""分割哨兵：偵測最近發生股票分割/減資的標的，自動清除其價格快取讓系統重抓調整後價格。

背景：price_cache 存的歷史價是「抓取當下」的調整基準；標的之後若發生分割，
快取裡的舊價與新抓的現價基準不同，報酬會爆掉（2026-07-12 CRWD 4:1 分割後
被算成 -73% 並誤判落後，實際 +6.8%）。本腳本在每次排程生成報告前執行，
發現近期分割就清該標的快取，calc_performance 會自動用調整後價格重算。

用法：python split_sentinel.py [--days 21]
"""
import argparse
import logging
import os
import sys
import time

import psycopg2
import yfinance as yf
from datetime import date, timedelta
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv(override=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=21,
                        help="回看幾天內的分割事件（預設 21，需大於排程間隔才不會漏）")
    args = parser.parse_args()
    cutoff = date.today() - timedelta(days=args.days)

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    cur.execute("""SELECT DISTINCT stock_code FROM signals
                   WHERE action != '0' AND stock_code IS NOT NULL AND stock_code != 'Unknown'""")
    tickers = sorted(r[0] for r in cur.fetchall())
    logging.info(f"分割哨兵：檢查 {len(tickers)} 個標的（回看 {args.days} 天）")

    purged = []
    failed = []
    for code in tickers:
        try:
            splits = yf.Ticker(code).splits
            if splits is None or len(splits) == 0:
                continue
            recent = [(ts, ratio) for ts, ratio in splits.items() if ts.date() >= cutoff]
            if not recent:
                continue
            cur.execute("DELETE FROM price_cache WHERE ticker = %s", (code,))
            conn.commit()
            for ts, ratio in recent:
                logging.warning(f"⚠ {code} 於 {ts.date()} 發生分割（倍率 {ratio}），已清除 {cur.rowcount} 筆價格快取重抓")
            purged.append(code)
        except Exception as e:
            failed.append(f"{code}({type(e).__name__})")
        time.sleep(0.2)

    conn.close()
    if purged:
        logging.info(f"共清除 {len(purged)} 個標的的快取：{', '.join(purged)}")
    else:
        logging.info("未偵測到近期分割事件")
    if failed:
        logging.info(f"查詢失敗（下次再試）：{', '.join(failed)}")


if __name__ == "__main__":
    main()
