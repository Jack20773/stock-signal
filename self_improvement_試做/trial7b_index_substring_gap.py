# -*- coding: utf-8 -*-
"""trial7b：補上 trial7 暴露的兩個缺口，量真正的代價（自我精進 Part B，2026-08-11）

trial7 的結果有兩個必須追下去的地方：

1. **修剪高頻 token 會砍死最熱門的查詢**：砍掉「>50% 集都出現」的 token 之後，
   「台積電」「NVIDIA」「AI」的召回率直接掉到 0%。所以索引不能靠這一刀壓縮。
2. **即使完全不修剪，召回率也不是 100%**：`AI` 70%、`CoWoS` 90%。
   原因是 trial7 的 ASCII token 是「整串」切的——`AIGC` 會變成 token `aigc`，
   所以查 `ai` 命中不到它；但現在線上的 `text.includes(q)` 是**子字串**語意，找得到。
   換句話說：**索引方案跟現行行為不等價，會靜默漏搜。**

這支腳本補 ASCII 也做 n-gram，讓索引回到子字串語意，然後量它到底變多大。
結論寫在 trial7b_demo_output.txt。

跑法：
    python -X utf8 self_improvement_試做/trial7b_index_substring_gap.py
"""
from __future__ import annotations

import gzip
import json
import os
import re
import sys
import time
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "transcripts_data")

_CJK_RUN = re.compile(r"[一-鿿]+")
_ASCII_RUN = re.compile(r"[a-z0-9]+")


def tokens_substring(text: str, ascii_n: int = 3) -> set[str]:
    """中文 2-gram ＋ ASCII n-gram（預設 3）。兩者都是「滑動視窗」，
    所以 `ai` 能命中 `aigc`、`cowos` 能命中 `cowos-l`，回到子字串語意。"""
    low = text.lower()
    out: set[str] = set()
    for run in _CJK_RUN.findall(low):
        for i in range(len(run) - 1):
            out.add(run[i:i + 2])
    for run in _ASCII_RUN.findall(low):
        if len(run) <= ascii_n:
            out.add(run)
            continue
        for i in range(len(run) - ascii_n + 1):
            out.add(run[i:i + ascii_n])
    return out


def query_tokens(q: str, ascii_n: int = 3) -> list[str]:
    return sorted(tokens_substring(q, ascii_n))


def build(ascii_n: int):
    idx: dict[str, set[int]] = defaultdict(set)
    n_eps = 0
    raw = 0
    t0 = time.perf_counter()
    for fname in sorted(os.listdir(DATA_DIR)):
        m = re.match(r"EP(\d+)\.txt$", fname)
        if not m:
            continue
        num = int(m.group(1))
        with open(os.path.join(DATA_DIR, fname), encoding="utf-8") as f:
            text = f.read()
        n_eps += 1
        raw += len(text.encode("utf-8"))
        for t in tokens_substring(text, ascii_n):
            idx[t].add(num)
    return ({k: sorted(v) for k, v in idx.items()},
            {"eps": n_eps, "raw": raw, "sec": round(time.perf_counter() - t0, 2)})


def exact_hits(q: str, nums) -> set[int]:
    ql = q.lower()
    hit = set()
    for n in nums:
        p = os.path.join(DATA_DIR, f"EP{n}.txt")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                if ql in f.read().lower():
                    hit.add(n)
    return hit


def candidates(idx, q, ascii_n):
    ts = query_tokens(q, ascii_n)
    if not ts:
        return None
    acc = None
    for t in ts:
        s = set(idx.get(t, ()))
        acc = s if acc is None else (acc & s)
        if not acc:
            break
    return acc or set()


def main() -> int:
    if not os.path.isdir(DATA_DIR):
        print("找不到 transcripts_data/，先跑一次 notifier.py")
        return 1

    queries = ["台積電", "NVIDIA", "輝達", "漲價", "美債", "800V", "CoWoS",
               "降息", "AI", "散熱", "馬斯克", "記憶體"]

    print("=" * 74)
    print("trial7b：把索引改回『子字串語意』要付多少代價")
    print("=" * 74)

    for ascii_n in (3, 2):
        idx, st = build(ascii_n)
        blob = json.dumps(idx, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        gz = gzip.compress(blob, 9)
        raw_mb = st["raw"] / 1024 / 1024
        all_nums = sorted({n for v in idx.values() for n in v})

        print(f"\n── ASCII {ascii_n}-gram ＋ 中文 2-gram ──")
        print(f"  建索引 {st['sec']} 秒｜token {len(idx):,}")
        print(f"  JSON {len(blob)/1024/1024:.2f} MB → gzip {len(gz)/1024/1024:.2f} MB"
              f"（原始全文 {raw_mb:.1f} MB，佔 {len(gz)/st['raw']*100:.1f}%）")

        bad = []
        print(f"  {'關鍵字':<10}{'候選':>7}{'真實':>7}{'召回':>7}{'候選膨脹':>10}")
        for q in queries:
            cand = candidates(idx, q, ascii_n)
            truth = exact_hits(q, all_nums)
            conf = exact_hits(q, sorted(cand)) if cand else set()
            recall = (len(conf & truth) / len(truth) * 100) if truth else 100.0
            infl = (len(cand) / len(truth)) if truth else 0
            print(f"  {q:<10}{len(cand):>7}{len(truth):>7}{recall:>6.0f}%{infl:>9.2f}x")
            if recall < 99.9:
                bad.append((q, recall))
        print(f"  → 召回不足 100% 的關鍵字：{bad if bad else '無'}")

    print("\n" + "=" * 74)
    print("怎麼讀這份數字：見 trial7b_demo_output.txt 末段")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
