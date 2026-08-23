# -*- coding: utf-8 -*-
"""重新產生 `tw_listing_map.json`：台股「代號 → 上市/上櫃」對照白名單。

2026-08-24 索羅門分身新增。背景見 stock_dict.normalize_tw_suffix() 的 docstring：
Gemini 標代號時一律加 `.TW`（prompt 舊版就是這樣寫的），上櫃股因此全錯，
yfinance 一根 K 棒都抓不到。這支腳本從**官方 open API** 抓當日全市場報價，
把出現在證交所的代號記成 `TW`、只出現在櫃買中心的記成 `TWO`。

用法（需要對外網路，平常不用跑；季度或發現新股抓不到價時再跑）：
    python -X utf8 refresh_tw_listing_map.py

刻意設計成「離線資料檔 + 手動更新腳本」而不是寫入時即時查詢：
分析管線每集會寫十幾筆訊號，每筆都打官方 API 會拖慢並增加失敗點，
而上市/上櫃的歸屬是**極少變動**的靜態事實，快取成本遠低於即時查詢。
"""
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

TWSE_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
OUT = Path(__file__).with_name("tw_listing_map.json")

# 只收兩種代號：①4 碼普通股 ②`00` 開頭的 ETF/受益憑證（5~6 碼，可帶一個英文字尾，如 00679B、006208）。
# **不能只用「純數字 4~6 碼」當條件**：台股權證的代號正是 6 碼純數字
# （櫃買 70/71/72/73 開頭共 9,573 檔，證交所另有 0x 開頭），
# 一收進來白名單會從 ~2,000 檔膨脹到 ~11,000 檔，全是雜訊。
# 2026-08-24 第一版就是這樣寫錯的，實查代號長度分布才發現。
_CODE_OK = re.compile(r"^(\d{4}|00\d{2,4}[A-Z]?)$")


def _get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8-sig"))


def main() -> None:
    twse = {row["Code"]: row.get("Name", "") for row in _get(TWSE_URL)
            if _CODE_OK.match(row.get("Code", ""))}
    tpex = {row["SecuritiesCompanyCode"]: row.get("CompanyName", "")
            for row in _get(TPEX_URL)
            if _CODE_OK.match(row.get("SecuritiesCompanyCode", ""))}

    overlap = sorted(set(twse) & set(tpex))
    # 上市優先：真的兩邊都出現（理論上不該發生）就記 TW，並在檔案裡留紀錄供人工檢查。
    listing = {c: "TWO" for c in tpex}
    listing.update({c: "TW" for c in twse})
    names = {**tpex, **twse}

    payload = {
        "_generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "_sources": {"twse": TWSE_URL, "tpex": TPEX_URL},
        "_counts": {"twse": len(twse), "tpex": len(tpex),
                    "total": len(listing), "overlap": len(overlap)},
        "_overlap_codes": overlap,
        "listing": listing,
        "names": names,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[OK] 上市 {len(twse)} 檔｜上櫃 {len(tpex)} 檔｜合計 {len(listing)} 檔"
          f"｜重疊 {len(overlap)} 檔 -> {OUT}")


if __name__ == "__main__":
    main()
