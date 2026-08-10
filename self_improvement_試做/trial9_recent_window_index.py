# -*- coding: utf-8 -*-
"""trial9：只對「最近 N 集」建搜尋索引，大小與代價（自我精進 Part B，2026-08-11）

**為什麼做這個**：trial7b 收尾時我在報告裡丟了一個「選項 C：只對最近 100 集建索引，
大小可降到 1 MB 量級」——**但那個數字是我猜的，沒有量過**。
把沒量過的數字寫進給使用者做決定的文件裡，跟上次「工程量不小」那種空話是同一個毛病，
只是換了個外觀。這支腳本把它量掉。

同時量一件更重要的事：**只索引最近 N 集，會漏掉多少搜尋結果**——
因為使用者搜「台積電」時，期待的是全部 446 集，不是最近 100 集裡的那幾集。

跑法：
    python -X utf8 self_improvement_試做/trial9_recent_window_index.py
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
N_ASCII = 2   # trial7b 證明 ASCII 2-gram 才能等價於現行 substring 語意


def tokens(text: str) -> set[str]:
    low = text.lower()
    out: set[str] = set()
    for run in _CJK_RUN.findall(low):
        for i in range(len(run) - 1):
            out.add(run[i:i + 2])
    for run in _ASCII_RUN.findall(low):
        if len(run) <= N_ASCII:
            out.add(run)
        else:
            for i in range(len(run) - N_ASCII + 1):
                out.add(run[i:i + N_ASCII])
    return out


def episode_files() -> list[tuple[int, str]]:
    out = []
    for f in os.listdir(DATA_DIR):
        m = re.match(r"EP(\d+)\.txt$", f)
        if m:
            out.append((int(m.group(1)), os.path.join(DATA_DIR, f)))
    return sorted(out, reverse=True)   # 最新在前


def build(files) -> tuple[dict, float, int]:
    idx: dict[str, set[int]] = defaultdict(set)
    raw = 0
    t0 = time.perf_counter()
    for num, path in files:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        raw += len(text.encode("utf-8"))
        for t in tokens(text):
            idx[t].add(num)
    return ({k: sorted(v) for k, v in idx.items()},
            round(time.perf_counter() - t0, 2), raw)


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


def main() -> int:
    if not os.path.isdir(DATA_DIR):
        print("找不到 transcripts_data/")
        return 1

    files = episode_files()
    all_nums = [n for n, _ in files]
    print("=" * 78)
    print("trial9：只索引最近 N 集，省多少、漏多少")
    print("=" * 78)
    print(f"語料共 {len(files)} 集")

    queries = ["台積電", "NVIDIA", "漲價", "美債", "CoWoS", "降息", "AI", "馬斯克"]
    truth = {q: exact_hits(q, all_nums) for q in queries}

    print(f"\n{'視窗':<12}{'集數':>6}{'索引gzip':>11}{'原文':>10}{'建置':>8}   平均涵蓋率")
    print("-" * 78)
    for n in (50, 100, 200, 400, len(files)):
        subset = files[:n]
        nums = {x for x, _ in subset}
        idx, sec, raw = build(subset)
        blob = json.dumps(idx, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        gz = len(gzip.compress(blob, 9))
        covs = []
        for q in queries:
            t = truth[q]
            covs.append(len(t & nums) / len(t) * 100 if t else 100.0)
        avg = sum(covs) / len(covs)
        label = f"最近 {n} 集" if n < len(files) else "全部"
        print(f"{label:<12}{len(subset):>6}{gz/1024/1024:>9.2f}MB{raw/1024/1024:>8.1f}MB"
              f"{sec:>7}s   {avg:>6.1f}%")

    print("\n各關鍵字在『最近 100 集』視窗下的涵蓋率（＝使用者會搜到的比例）")
    nums100 = {x for x, _ in files[:100]}
    print(f"  {'關鍵字':<10}{'全站命中':>9}{'視窗內':>8}{'涵蓋率':>9}")
    for q in queries:
        t = truth[q]
        inw = len(t & nums100)
        print(f"  {q:<10}{len(t):>9}{inw:>8}{(inw/len(t)*100 if t else 100):>8.0f}%")

    print("\n" + "=" * 78)
    print("怎麼讀：見 trial9_demo_output.txt 末段與 ROUND_2026-08-11.md")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
