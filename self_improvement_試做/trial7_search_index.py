# -*- coding: utf-8 -*-
"""trial7：第三頁「靜態搜尋索引」可行性實測（自我精進 Part B，2026-08-11）

**為什麼做這個**：2026-08-11 雙審時 Codex 的建議是「在 Python 產生流程新增靜態搜尋索引檔，
前端以 Web Worker 載入單一壓縮索引做查找」。我當下沒做，理由寫成「工程量另一個級別，
應該由使用者決定要不要投入」——但那句話沒有任何數字支撐，等於把決定丟回去卻沒給判斷依據。
這支腳本補上數字：索引多大、建多久、查多快、能不能取代現在那個 35MB 下載。

**這是試做，不是正式功能**：不修改任何正式檔案，不接進 notifier.py，不動部署流程。

跑法：
    python -X utf8 self_improvement_試做/trial7_search_index.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import gzip
import random
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "transcripts_data")
OUT_DIR = os.path.dirname(os.path.abspath(__file__))

# 中文沒有空白斷詞，用 2-gram 當索引單位（不引入斷詞套件，維持零新依賴）。
# 英數字則整段當一個 token（NVDA、AI、800V 這類要能整串命中）。
_ASCII_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_CJK = re.compile(r"[一-鿿]")


def tokens_of(text: str) -> set[str]:
    out: set[str] = set()
    for m in _ASCII_TOKEN.finditer(text):
        t = m.group().lower()
        if len(t) >= 2:
            out.add(t)
    # 中文 2-gram：只對連續中文字產生，避免把標點也串進去
    cjk_runs = re.findall(r"[一-鿿]+", text)
    for run in cjk_runs:
        for i in range(len(run) - 1):
            out.add(run[i:i + 2])
    return out


def build_index() -> tuple[dict[str, list[int]], dict]:
    idx: dict[str, set[int]] = defaultdict(set)
    stats = {"episodes": 0, "raw_bytes": 0}
    t0 = time.perf_counter()
    for fname in sorted(os.listdir(DATA_DIR)):
        m = re.match(r"EP(\d+)\.txt$", fname)
        if not m:
            continue
        num = int(m.group(1))
        path = os.path.join(DATA_DIR, fname)
        with open(path, encoding="utf-8", errors="strict") as f:
            text = f.read()
        stats["episodes"] += 1
        stats["raw_bytes"] += len(text.encode("utf-8"))
        for t in tokens_of(text):
            idx[t].add(num)
    stats["build_seconds"] = round(time.perf_counter() - t0, 2)
    # set -> 排序過的 list，JSON 才存得下，也讓輸出穩定可重現
    return {k: sorted(v) for k, v in idx.items()}, stats


def prune(idx: dict[str, list[int]], total_eps: int, max_df_ratio: float) -> dict[str, list[int]]:
    """砍掉「幾乎每集都出現」的 token——它們對搜尋沒有鑑別度，卻佔掉最多空間。
    這是壓縮索引最有效的一刀，也是最容易砍過頭的一刀，所以下面會量它砍掉多少召回。"""
    cap = total_eps * max_df_ratio
    return {k: v for k, v in idx.items() if len(v) <= cap}


def search(idx: dict[str, list[int]], q: str) -> set[int] | None:
    """回傳可能含這個關鍵字的集數；索引查不到就回 None（代表要退回逐集比對）。
    注意：2-gram 索引是**近似**——命中代表「這幾集含有全部這些 2-gram」，
    不保證它們真的相鄰成詞，所以正式用途仍需對候選集做一次精確比對。"""
    ts = tokens_of(q)
    if not ts:
        return None
    sets = []
    for t in ts:
        hit = idx.get(t)
        if hit is None:
            return set()   # 有任一 token 完全不存在 → 一定沒有命中
        sets.append(set(hit))
    out = sets[0]
    for s in sets[1:]:
        out &= s
    return out


def exact_hits(q: str, nums: list[int]) -> set[int]:
    """對照組：直接讀檔做 substring 比對（＝目前線上的作法）。"""
    ql = q.lower()
    hit = set()
    for n in nums:
        p = os.path.join(DATA_DIR, f"EP{n}.txt")
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as f:
            if ql in f.read().lower():
                hit.add(n)
    return hit


def main() -> int:
    if not os.path.isdir(DATA_DIR):
        print(f"找不到 {DATA_DIR}，先跑一次 notifier.py 產生 transcripts_data/")
        return 1

    print("=" * 72)
    print("trial7：第三頁靜態搜尋索引 可行性實測")
    print("=" * 72)

    idx, stats = build_index()
    all_nums = sorted({n for v in idx.values() for n in v})
    total_eps = len(all_nums)

    raw_mb = stats["raw_bytes"] / 1024 / 1024
    print(f"\n[1] 語料：{stats['episodes']} 集，原始全文 {raw_mb:.1f} MB")
    print(f"    建索引耗時：{stats['build_seconds']} 秒（純 Python、無外部套件）")
    print(f"    未修剪索引 token 數：{len(idx):,}")

    variants = {}
    for ratio, label in [(1.0, "不修剪"), (0.5, "砍掉 >50% 集都有的"), (0.2, "砍掉 >20% 集都有的")]:
        pruned = prune(idx, total_eps, ratio)
        blob = json.dumps(pruned, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        gz = gzip.compress(blob, 9)
        variants[label] = (pruned, len(blob), len(gz))
        print(f"\n[2] 索引大小（{label}）：token {len(pruned):,}")
        print(f"    JSON {len(blob)/1024/1024:.2f} MB → gzip 後 {len(gz)/1024/1024:.2f} MB"
              f"（線上是 gzip 傳輸，實際下載量看 gzip 這欄）")
        print(f"    相對於現在的 {raw_mb:.1f} MB 全文下載：{len(gz)/stats['raw_bytes']*100:.1f}%")

    # ── 鑑別度測試：索引找到的，跟逐集精確比對找到的，一不一樣？ ──────────
    print("\n[3] 正確性對照（索引 vs 逐集精確比對）")
    queries = ["台積電", "NVIDIA", "輝達", "漲價", "美債", "800V", "CoWoS", "降息", "AI", "散熱"]
    random.seed(0)
    for label in ["不修剪", "砍掉 >50% 集都有的", "砍掉 >20% 集都有的"]:
        pruned = variants[label][0]
        rows = []
        for q in queries:
            cand = search(pruned, q)
            truth = exact_hits(q, all_nums)
            if cand is None:
                rows.append((q, "N/A", len(truth), "-", "-"))
                continue
            # 索引是近似的：真正的用法是「用索引縮小候選，再對候選做精確比對」
            confirmed = exact_hits(q, sorted(cand))
            recall = len(confirmed & truth) / len(truth) * 100 if truth else 100.0
            rows.append((q, len(cand), len(truth), len(confirmed), f"{recall:.0f}%"))
        print(f"\n  ── {label} ──")
        print(f"  {'關鍵字':<10}{'索引候選':>8}{'真實命中':>8}{'確認後':>8}{'召回率':>8}")
        for q, c, t, cf, r in rows:
            print(f"  {q:<10}{str(c):>8}{str(t):>8}{str(cf):>8}{r:>8}")

    # ── 查詢速度 ────────────────────────────────────────────────
    print("\n[4] 查詢速度（索引在記憶體裡，模擬前端載入後的狀態）")
    pruned = variants["砍掉 >50% 集都有的"][0]
    t0 = time.perf_counter()
    N = 200
    for i in range(N):
        search(pruned, queries[i % len(queries)])
    dt = (time.perf_counter() - t0) / N * 1000
    print(f"    平均每次查詢 {dt:.3f} ms（{N} 次平均）")

    print("\n" + "=" * 72)
    print("結論看 trial7_demo_output.txt 末段的『怎麼讀這份數字』")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
