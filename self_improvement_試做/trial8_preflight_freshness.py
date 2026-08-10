# -*- coding: utf-8 -*-
"""trial8：驗證前的「資料忠實度 pre-flight」（自我精進 Part B，2026-08-11）

**為什麼做這個**：今晚差點交出一份錯的報告。

第一次用真實 DB 產出三頁之後，第二頁只有 28 檔、逐字稿頁只有 680 集，看起來像程式壞了。
追下去才發現是**本機 `episodes.json` 停在 8/2**，遠端早就有 685 集——我驗的是一份失真的快照。
如果沒追下去，我會寫出「線上第二頁少了近一個月資料」這種假的正式站 bug 報告。

記憶正本裡早就有一條規則：「查證『缺口/異常』結論前，先確認比對目標本身對不對」
（`feedback_verify_target_not_just_rerun_command.md`）。但那條規則**沒有任何機制**，
全靠當下想不想得到。這支腳本就是把那條規則變成一個跑得動的檢查。

**這是試做，不是正式功能**：不修改任何正式檔案、不接進 notifier.py、不寫任何東西進 DB。
全部是唯讀檢查。

跑法：
    python -X utf8 self_improvement_試做/trial8_preflight_freshness.py
    python -X utf8 self_improvement_試做/trial8_preflight_freshness.py --offline   # 不連網

離開碼：0＝可以放心驗證　1＝有落差，先處理再驗
"""
from __future__ import annotations

import collections
import json
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

EPISODES_LOCAL = os.path.join(ROOT, "episodes.json")
EPISODES_URL = "https://whatmkreallysaid.com/episodes.json"
TRANSCRIPTS = os.path.join(ROOT, "transcripts")
TR_DATA = os.path.join(ROOT, "transcripts_data")


class Check:
    def __init__(self):
        self.rows: list[tuple[str, bool, str]] = []

    def add(self, name: str, ok: bool, detail: str):
        self.rows.append((name, ok, detail))

    def report(self) -> int:
        print("=" * 78)
        print("驗證前 pre-flight：我等一下要驗的資料，本身是新鮮的嗎？")
        print("=" * 78)
        worst = 0
        for name, ok, detail in self.rows:
            mark = "  OK " if ok else "  !! "
            print(f"{mark}{name}")
            for line in detail.splitlines():
                print(f"       {line}")
            if not ok:
                worst = 1
        print("-" * 78)
        print("結論：" + ("全部一致，可以放心把產出的畫面當成「線上會長的樣子」"
                        if worst == 0 else
                        "**有落差 → 先補齊再驗證**，否則你驗到的是失真的快照"))
        print("=" * 78)
        return worst


def local_eps() -> list[int]:
    if not os.path.exists(EPISODES_LOCAL):
        return []
    data = json.loads(open(EPISODES_LOCAL, encoding="utf-8").read())
    return sorted(int(e["number"]) for e in data if str(e.get("number", "")).isdigit())


def remote_eps(timeout: int = 30) -> list[int] | None:
    try:
        req = urllib.request.Request(EPISODES_URL, headers={"User-Agent": "Mozilla/5.0"})
        data = json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8"))
        return sorted(int(e["number"]) for e in data if str(e.get("number", "")).isdigit())
    except Exception as ex:
        print(f"[warn] 抓不到遠端 episodes.json：{ex}")
        return None


def db_eps() -> list[int] | None:
    try:
        import database
        rows = database.list_signals()
        out = set()
        for r in rows:
            m = re.search(r"\d+", r.get("episode_id") or "")
            if m:
                out.add(int(m.group()))
        return sorted(out)
    except Exception as ex:
        print(f"[warn] 連不上 DB：{ex}")
        return None


def main() -> int:
    offline = "--offline" in sys.argv
    c = Check()

    le = local_eps()
    c.add("本機 episodes.json 存在且可解析",
          bool(le),
          f"{len(le)} 集，最新 EP{le[-1] if le else '—'}")

    if not offline:
        re_ = remote_eps()
        if re_ is None:
            c.add("遠端 episodes.json", False, "抓不到（網路問題或對方站台異常），無法比對新鮮度")
        else:
            gap = sorted(set(re_) - set(le))
            c.add("本機 episodes.json 跟得上遠端",
                  not gap,
                  f"遠端 {len(re_)} 集（最新 EP{re_[-1]}）／本機 {len(le)} 集"
                  + (f"\n落後 {len(gap)} 集：{['EP%d' % n for n in gap[-8:]]}"
                     f"\n→ 先跑 `python -X utf8 download_transcripts.py` 再驗證" if gap else ""))

    de = db_eps()
    if de is not None:
        missing_date = sorted(set(de) - set(le))
        c.add("DB 裡的集數，本機都查得到上架日",
              not missing_date,
              f"DB 有 {len(de)} 集訊號（最新 EP{de[-1] if de else '—'}）"
              + (f"\n有 {len(missing_date)} 集在 episodes.json 查不到："
                 f"{['EP%d' % n for n in missing_date[-8:]]}"
                 f"\n→ 這些集的訊號會被關注度頁排除（第二頁會少東西）" if missing_date else ""))

    # 重複逐字稿：同一集兩個檔名（獨立轉錄版 vs 官方下載版）
    if os.path.isdir(TRANSCRIPTS):
        m = collections.defaultdict(list)
        for f in os.listdir(TRANSCRIPTS):
            mo = re.match(r"EP(\d+)", f)
            if mo:
                m[int(mo.group(1))].append(f)
        dup = {k: v for k, v in m.items() if len(v) > 1}
        c.add("transcripts/ 沒有同集重複檔",
              not dup,
              f"{len(m)} 集"
              + (f"\n{len(dup)} 集有重複：" + "、".join(f"EP{k}" for k in sorted(dup)[:6])
                 + "\n→ export_transcripts_data() 會讓後複製的蓋掉前一個，順序取決於 os.listdir"
                 if dup else ""))

    # 產出檔比資料新嗎
    outs = ["report_detail.html", "report_attention.html", "report_transcripts.html"]
    if os.path.exists(EPISODES_LOCAL):
        src_m = os.path.getmtime(EPISODES_LOCAL)
        stale = [o for o in outs
                 if os.path.exists(os.path.join(ROOT, o))
                 and os.path.getmtime(os.path.join(ROOT, o)) < src_m]
        c.add("三頁產出檔比 episodes.json 新",
              not stale,
              "、".join(outs) if not stale else
              f"這幾份比資料舊，你看到的是上一輪的畫面：{stale}\n→ 重跑 notifier.py")

    return c.report()


if __name__ == "__main__":
    sys.exit(main())
