"""
索羅門工作區任務（2026-08-03）Track 4試做：LINE Bot「/股癌績效」回應速度優化。

背景（實測發現，不是猜測）：直接跑 `python -X utf8 line_query.py perf` 量到
**19.4秒**（見同目錄 perf_timing_demo_output.txt）。這個指令是LINE bot
`stock_handler.py::handle()` 裡「快速指令」分支之一，同步呼叫、沒有像
`/股癌分析`那樣有背景thread+推播——**使用者在LINE裡打「/股癌績效」，會盯著
已讀但沒有任何回應的畫面19秒**，這是真實會被使用者感受到的延遲，不是後端
技術債。

根因：`performance.py::calc_performance()` 每次呼叫都對全部 391+ 筆「已有結果」
的訊號重新批次查詢即時股價（`batch_get_latest_close`），即使兩次LINE查詢間隔
只有幾分鐘、股價根本沒有變化空間，也會整批重新打一次外部行情來源。

**這是試做/demo，不是正式程式碼**——不import進stock_handler.py或performance.py，
不修改任何正式檔案。用真實的 `calc_performance()`（讀專案正式模組，不改它）示範
一個「結果層TTL快取」能不能有效解決，並用真實計時量測改善幅度。

設計：
- 快取檔案存在**本試做資料夾**（不是正式專案目錄），避免任何正式檔案被寫入。
- get_performance_cached(ttl_seconds)：檢查快取檔案的時間戳，未過期直接回傳快取內容
  （不呼叫 calc_performance()，也就不會觸發它内部的DB UPDATE，這是預期行為——TTL窗口內
  沒有新資料，不需要重算也不需要重寫）；過期或無快取才真的呼叫 calc_performance()。
"""
import json
import sys
import time
from pathlib import Path

STOCK_SIGNAL_DIR = Path(__file__).parent.parent.parent  # .../stock-signal/
sys.path.insert(0, str(STOCK_SIGNAL_DIR))

CACHE_FILE = Path(__file__).parent / "perf_cache_demo.json"


def get_performance_cached(ttl_seconds: int = 600) -> tuple[list[dict], bool]:
    """回傳 (results, was_cache_hit)。真正的 calc_performance() 來自正式模組，
    這裡只加一層TTL快取，不改動它本身的邏輯。"""
    if CACHE_FILE.exists():
        try:
            payload = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            age = time.time() - payload["cached_at"]
            if age < ttl_seconds:
                return payload["results"], True
        except Exception:
            pass  # 快取壞掉就當作沒有快取，走正常路徑重算

    from performance import calc_performance  # 讀正式模組的真實函式，不改它
    results = calc_performance()
    CACHE_FILE.write_text(
        json.dumps({"cached_at": time.time(), "results": results}, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return results, False


if __name__ == "__main__":
    print("=== 第一次呼叫（預期cache miss，跟正常calc_performance()一樣慢）===")
    t0 = time.time()
    results1, hit1 = get_performance_cached(ttl_seconds=600)
    t1 = time.time()
    print(f"耗時：{t1 - t0:.2f}秒，cache_hit={hit1}，取得{len(results1)}筆結果")

    print("\n=== 第二次呼叫（模擬使用者幾分鐘內又查一次，預期cache hit）===")
    t2 = time.time()
    results2, hit2 = get_performance_cached(ttl_seconds=600)
    t3 = time.time()
    print(f"耗時：{t3 - t2:.2f}秒，cache_hit={hit2}，取得{len(results2)}筆結果")

    print(f"\n=== 對照 ===")
    print(f"第一次（無快取）：{t1 - t0:.2f}秒")
    print(f"第二次（有快取）：{t3 - t2:.2f}秒")
    if t1 - t0 > 0:
        speedup = (t1 - t0) / max(t3 - t2, 0.001)
        print(f"加速倍數：{speedup:.0f}x")

    # 驗證資料一致性（2026-08-03依DeepSeek審查意見修正：原本只比對筆數+第一筆，
    # 不夠嚴謹；改成逐筆逐欄位完整比對，JSON往返會把date物件序列化成字串，
    # 比對時要把這個已知的型別差異排除，不是真正的資料不一致）
    def _normalize(row: dict) -> dict:
        return {k: (str(v) if v is not None else None) for k, v in row.items()}

    assert len(results1) == len(results2), f"筆數不一致！{len(results1)} vs {len(results2)}"
    mismatches = []
    for i, (r1, r2) in enumerate(zip(results1, results2)):
        n1, n2 = _normalize(r1), _normalize(r2)
        if n1 != n2:
            diff_keys = {k for k in n1 if n1.get(k) != n2.get(k)}
            mismatches.append((i, diff_keys))
    print(f"\n資料一致性驗證（逐筆逐欄位，已排除JSON往返的date->str型別差異）：")
    print(f"  筆數相同={len(results1) == len(results2)}")
    print(f"  {len(mismatches)}/{len(results1)} 筆有欄位差異"
          f"{('：' + str(mismatches[:3])) if mismatches else '（完全一致）'}")
