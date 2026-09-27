#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""專有名詞正確率量尺（粉絲版 vs 自建版逐字稿）

用途
----
股癌**沒有官方逐字稿**。我們手上只有兩種來源：

  * **粉絲版**：來源 whatmkreallysaid.com，未經驗證，且已證實是**編輯過的稿子**
    （有分段標題、標點、書面化潤飾），不是逐字稿。
  * **自建版**：我們自己跑 faster-whisper 產生的本地聽寫。

兩版都沒有「標準答案」的身分，所以本尺**不用人工校對**，改用**客觀名冊**當標準答案：
名冊裡有的專有名詞才算「可驗證實體」，名冊外的一律不計分。

名冊來源（全部是專案內既有資產，不是本腳本新編的）
--------------------------------------------------
1. ``stock_dict.py`` 的 ``_TW`` / ``_US`` / ``_JP``（人工維護的公司名→代號對照表）。
   實體 ID = 代號，別名（台積電 / TSMC）視為同一個實體。
2. ``asr/hotwords_gooaye.txt``（ASR 熱詞表）。其中能用官方上市櫃名單
   （``tw_listing_map.json`` → ``stock_dict._OFFICIAL_BY_NAME``）解析出代號的，
   併入股票實體；解析不出來的（股癌／聯準會／鮑爾／費半…）列為「固定專有名詞」。
3. ``FIXED_EXTRA``：節目本身的固定名詞（Gooaye、謝孟恭的常見簡稱「孟恭」）。

三個數（每一版、每一集各算一次）
--------------------------------
* **命中 hit**：名冊實體的**正確寫法**出現在該版正文裡（**以實體去重**，不是數出現次數）。
* **漏 miss**：該集的聯集事實 U（= 任一版命中過的實體）裡，這一版沒有的。
* **幻覺 hallu**：正文裡有一個字串**長得像名冊實體但名冊查無**
  （與某個名冊寫法的 Levenshtein 距離 = 1，且不是它的縮寫／延伸，
  也不在官方 2326 檔上市櫃名單裡）。

正確率
------
* 主指標 ``recall = 命中 / |U|``，母體 = ``|U|``（該集可驗證實體數，兩版共用）。
* 罰分版 ``penalized = 命中 / (|U| + 幻覺)``，母體 = ``|U| + 幻覺``（該版自己的母體）。
* **母體為 0 一律判 FAIL**（``all([]) == True`` 的陷阱）。

為什麼要相信這把尺（鑑別度）
----------------------------
``--selftest`` 是兩個方向的對照組，任何一條沒過就 exit 1：
  * 注入一筆**真的**新實體提及 → 命中必須 +1；
  * 注入一行只是「提到」既有關鍵字的**敘述文字** → 三個數一律不准動；
  * 注入重複提及（同一個實體再講十次）→ 數字不准動（防「同一份檔案量三次得到 59/58/60」）；
  * 注入 HTML 註解裡的新實體名 → 不准動（註解不是逐字稿正文）；
  * 空語料 → 必須 FAIL，不准綠燈。

重跑
----
    python -X utf8 eval/proper_noun_accuracy.py --selftest
    python -X utf8 eval/proper_noun_accuracy.py
    python -X utf8 eval/proper_noun_accuracy.py --audit    # 逐實體列出命中/漏/幻覺與上下文

本腳本**只讀**逐字稿，不寫入 transcripts/，不動生產路徑上的程式。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import stock_dict  # noqa: E402  （專案既有字典，只讀）

# --------------------------------------------------------------------------
# 受測集數。兩版都在的集數才能量，這是本尺的母體限制。
# provenance 欄位說明這一版的來源憑證。
# --------------------------------------------------------------------------
PAIRS = [
    {
        "ep": "EP681",
        "fan": "transcripts/EP681_人道走廊與沙沙西瓜.md",
        "self": "transcripts/independent_superseded/EP681_再一次相信真愛存在的機會.md",
        "self_provenance": "manifest",
    },
    {
        "ep": "EP682",
        "fan": "transcripts/EP682_紅眼路比與魂系股災.md",
        "self": "transcripts/independent_superseded/EP682_魂系 everywhere.md",
        "self_provenance": "manifest",
    },
    {
        "ep": "EP683",
        "fan": "transcripts/EP683_DUV鬼故事與黃金葛玄學.md",
        "self": "transcripts/independent_superseded/EP683_一個月前的自己對未來寄予厚望.md",
        "self_provenance": "manifest",
    },
    {
        "ep": "EP684",
        "fan": "transcripts/EP684_五歲家書與降槓桿浩劫.md",
        "self": "transcripts/independent_superseded/EP684_終於可以喘一下.md",
        "self_provenance": "manifest",
    },
    {
        "ep": "EP687",
        "fan": "transcripts/EP687_峇里島下單記與Google房東論.md",
        "self": "docs/pairing_samples/EP687_independent.md",
        # EP687 的自建版是配對樣本，不在 independent_transcribe/manifest.json 裡，
        # 憑證是 docs/pairing_samples/EP687_raw.srt（同目錄的 faster-whisper 原始輸出）。
        "self_provenance": "pairing_sample",
    },
]

MANIFEST = "transcripts_data/independent_transcribe/manifest.json"

# --------------------------------------------------------------------------
# 名冊歧義排除（對兩版對稱套用，不偏袒任何一版）。每一條都要寫理由。
# --------------------------------------------------------------------------
AMBIGUOUS_SURFACES = {
    # 中文：這些寫法在一般中文裡就是常用詞／地名，當成公司名會製造假命中
    "南亞": "南亞塑膠 vs「南亞地區」，後者在時事討論裡極常見",
    "陽明": "陽明海運 vs 陽明山／陽明交大",
    "長榮": "長榮航／長榮海運 vs 長榮中學等；且與『長榮航』重疊",
    "統一": "統一企業 vs 動詞『統一』",
    # 英文：太短或本身是常用英文單字，且大小寫在逐字稿裡不穩定
    "ST": "意法半導體縮寫，但 ST 兩字母在英數串裡誤命中率高",
    "TI": "德州儀器縮寫，同上",
    "Arm": "公司名 vs 英文單字 arm",
    "Block": "公司名 vs 英文單字 block",
    "Square": "公司名 vs 英文單字 square",
    "Coherent": "公司名 vs 英文形容詞 coherent",
    "DISCO": "日商迪思科 vs disco",
    "Vshare": "stock_dict 內疑似 Vishay 的錯別名，不當成獨立寫法",
}

# 節目本身的固定名詞（名冊來源 3）
FIXED_EXTRA = {
    "股癌": ["股癌", "Gooaye"],
    "謝孟恭": ["謝孟恭", "孟恭"],  # 「孟恭」是節目裡最常用的稱呼，屬正確寫法
}

# 名冊補的「正確簡稱」。加進來的條件：它本身就是該公司的通用正確寫法，
# 不是訛寫。兩版對稱受益。
ALIAS_EXTRA = {
    "2330.TW": ["台積"],  # 「台積」是台積電的通用簡稱，節目裡比全名還常講
}

# 正體/異體字歸一。逐字稿是口語轉文字，「臺」「台」是同一個字的兩種寫法，
# 不是專有名詞錯誤（實測：自建版寫「臺積電」、粉絲版寫「台積電」，
# 不歸一的話會把自建版的正確結果誤判成「漏 + 幻覺」）。兩版對稱套用。
VARIANT_CHARS = {"臺": "台"}


def normalize(text):
    for a, b in VARIANT_CHARS.items():
        text = text.replace(a, b)
    return text

# 幻覺掃描的已確認誤報（= 正常中文詞，不是 ASR 訛寫）。對兩版對稱套用。
# 這份清單跟腳本一起進版控，改動看得到 diff。
HALLU_STOPLIST_FILE = Path(__file__).resolve().parent / "hallucination_stoplist.txt"

CJK = re.compile(r"[一-鿿]")
HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
FENCE = re.compile(r"^```.*?^```", re.S | re.M)
HEADING = re.compile(r"^#{1,6}\s.*$", re.M)


# --------------------------------------------------------------------------
# 名冊
# --------------------------------------------------------------------------
class Entity:
    __slots__ = ("eid", "kind", "canonical", "surfaces")

    def __init__(self, eid, kind, canonical, surfaces):
        self.eid = eid
        self.kind = kind          # "stock" | "fixed"
        self.canonical = canonical
        self.surfaces = surfaces  # list[str]

    def __repr__(self):
        return f"<{self.kind} {self.eid} {self.canonical}>"


def load_roster(verbose=False):
    by_eid = {}

    def add(eid, kind, surface):
        if surface in AMBIGUOUS_SURFACES:
            return
        surface = surface.strip()
        if not surface:
            return
        ent = by_eid.get(eid)
        if ent is None:
            by_eid[eid] = Entity(eid, kind, surface, [surface])
        elif surface not in ent.surfaces:
            ent.surfaces.append(surface)

    # 1) stock_dict 人工字典
    for name, code in stock_dict._ALL.items():
        add(code, "stock", name)

    # 2) ASR 熱詞表
    hot_path = REPO / "asr" / "hotwords_gooaye.txt"
    hot_words = []
    if hot_path.exists():
        hot_words = [w for w in hot_path.read_text(encoding="utf-8").split() if w]
    for w in hot_words:
        if w in AMBIGUOUS_SURFACES:
            continue
        code = stock_dict._ALL.get(w)
        if code is None:
            code = stock_dict._OFFICIAL_BY_NAME.get(w)
            if code and not code.startswith(("TW", "TWO")):
                pass
        if code:
            add(code, "stock", w)
        else:
            add("FIXED:" + w, "fixed", w)

    # 3) 節目固定名詞
    for canon, surfaces in FIXED_EXTRA.items():
        eid = "FIXED:" + canon
        for s in surfaces:
            add(eid, "fixed", s)
        by_eid[eid].canonical = canon

    # 3b) 補正確簡稱
    for eid, surfaces in ALIAS_EXTRA.items():
        if eid in by_eid:
            for s in surfaces:
                add(eid, by_eid[eid].kind, s)

    # 3c) 異體字歸一（名冊側）
    for ent in by_eid.values():
        seen = []
        for s in ent.surfaces:
            ns = normalize(s)
            if ns not in seen:
                seen.append(ns)
        ent.surfaces = seen
        ent.canonical = normalize(ent.canonical)

    roster = sorted(by_eid.values(), key=lambda e: e.eid)
    if verbose:
        print(f"[roster] 實體 {len(roster)} 個 / 寫法 {sum(len(e.surfaces) for e in roster)} 條"
              f"（股票 {sum(1 for e in roster if e.kind=='stock')}"
              f" / 固定 {sum(1 for e in roster if e.kind=='fixed')}）", file=sys.stderr)
    return roster


def load_hallu_stoplist():
    if not HALLU_STOPLIST_FILE.exists():
        return set()
    out = set()
    for line in HALLU_STOPLIST_FILE.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.add(line)
    return out


# --------------------------------------------------------------------------
# 正文抽取
# --------------------------------------------------------------------------
def extract_body(md_text, include_headings=False):
    """把 markdown 變成「可計分的正文」。

    拿掉的東西（兩版對稱）：
      * HTML 註解 ``<!-- ... -->``——註解是給人看的旁白，不是逐字稿內容
      * ``` 圍欄程式碼區塊
      * markdown 標題行（粉絲版有編輯自己下的分段標題，自建版沒有；留著對自建版不公平）

    **不拿掉** ``>`` 引言行：粉絲版用 `>` 排版「聽眾掛號來信」，那是節目真實內容，
    自建版同一段是純文字。拿掉會直接砍掉粉絲版的真實語料。
    """
    t = HTML_COMMENT.sub(" ", md_text)
    t = FENCE.sub(" ", t)
    if not include_headings:
        t = HEADING.sub(" ", t)
    return normalize(t)


# --------------------------------------------------------------------------
# 命中
# --------------------------------------------------------------------------
def _ascii_find(body, surf):
    """在 body 裡找 ASCII 寫法（大小寫敏感），回傳第一個合法邊界的位置，找不到回 -1。

    邊界為什麼不能只用 ``\\b``：自建版是 faster-whisper 的原始輸出，**英文字之間沒有空格**
    （實測 EP684 自建版寫成 ``...n EnergyMicronSK Hynix``）。只用 ``(?<![A-Za-z0-9])``
    會讓自建版的英文公司名全部漏掉——那是量尺的偏誤，不是自建版的錯誤。
    所以另外承認 **駝峰式交界**：前一個字元是小寫、本寫法首字是大寫（``…yMicron``），
    或下一個字元是大寫、本寫法尾字是小寫／數字（``Micron`` + ``SK``）。
    反例守住：``TIME`` 不會命中 ``TI``（尾字 I 是大寫，右邊 M 也是大寫，不算交界）；
    ``Intelligent`` 不會命中 ``Intel``（右邊 l 是小寫）。
    """
    start = 0
    n = len(body)
    while True:
        i = body.find(surf, start)
        if i < 0:
            return -1
        j = i + len(surf)
        prev = body[i - 1] if i > 0 else ""
        nxt = body[j] if j < n else ""
        # 注意：中文字的 str.isalnum() 也是 True，所以這裡必須限定「ASCII 英數」才算黏字，
        # 否則「我覺得Google很強」會因為左右都是中文而被判成沒有邊界，整個漏掉。
        pa = bool(prev) and prev.isascii() and prev.isalnum()
        na = bool(nxt) and nxt.isascii() and nxt.isalnum()
        lok = (not pa) or (prev.islower() and surf[0].isupper())
        rok = (not na) or (nxt.isupper() and (surf[-1].islower() or surf[-1].isdigit()))
        if lok and rok:
            return i
        start = i + 1


def find_hits(body, roster):
    """回傳 {eid: [(surface, 第一次出現的位置), ...]}，以實體去重。"""
    hits = {}
    for ent in roster:
        found = []
        for s in ent.surfaces:
            if CJK.search(s):
                idx = body.find(s)
                if idx >= 0:
                    found.append((s, idx))
            else:
                idx = _ascii_find(body, s)
                if idx >= 0:
                    found.append((s, idx))
        if found:
            hits[ent.eid] = found
    return hits


# --------------------------------------------------------------------------
# 幻覺（名冊實體的近形訛寫）
# --------------------------------------------------------------------------
def _lev(a, b):
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return 2
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        ca = a[i - 1]
        for j in range(1, lb + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != b[j - 1]))
        prev = cur
    return prev[lb]


def _char_positions(text):
    pos = {}
    for i, ch in enumerate(text):
        pos.setdefault(ch, []).append(i)
    return pos


def _mask(body, phrases):
    """把 phrases 在 body 裡的每個出現位置標記成「已被正常字串佔用」。"""
    m = bytearray(len(body))
    for p in phrases:
        if not p:
            continue
        st = 0
        while True:
            i = body.find(p, st)
            if i < 0:
                break
            for k in range(i, i + len(p)):
                m[k] = 1
            st = i + 1
    return m


def find_hallucinations(body, roster, stoplist, min_len=3):
    """找「長得像名冊實體、但名冊查無」的字串。

    規則（全部客觀、可重算）：
      * 只掃長度 >= ``min_len`` 的純中日文寫法。2 字寫法的近形鄰居幾乎都是正常中文詞
        （「聯電」→「發電/停電/用電」），鑑別度為 0，所以排除。
      * 候選字串與某個名冊寫法 Levenshtein 距離 = 1。
      * 候選本身不是名冊寫法（那是命中，不是幻覺）。
      * 候選與該寫法互為子字串（縮寫／延伸，例如「台積」之於「台積電」）→ 不算幻覺。
      * 候選出現在官方 2326 檔上市櫃公司名單裡 → 不算幻覺（是別家真公司）。
      * **該次出現的位置與任何名冊寫法的出現位置重疊 → 不算幻覺。**
        這條是在擋「跨詞誤切」：粉絲版寫「祝孟恭一家」，掃描器會截出「祝孟恭」，
        它跟「謝孟恭」距離 1，但正確寫法「孟恭」就在原地——那不是幻覺，是我的網子太寬。
      * 該次出現與 ``eval/hallucination_stoplist.txt`` 裡某個正常詞的出現位置重疊
        → 不算幻覺（例：「大安森林公園」會被截出「安森林」≈「安森美」）。

    已知限制（會**低估**自建版的幻覺，不會高估）：
      本通道只抓「同長度或差一字、且距離 1」的訛寫。自建版最嚴重的兩個錯——
      「股癌」→「古愛」（兩字全錯，距離 2）、「謝孟恭」→「孟公／專案公」（長度差 1 以上
      且距離 >= 2）——本通道抓不到，它們是靠「漏」那一欄記下來的。
    """
    official = set(stock_dict._OFFICIAL_BY_NAME.keys())
    all_surfaces = set()
    targets = []
    for ent in roster:
        for s in ent.surfaces:
            all_surfaces.add(s)
            if len(s) >= min_len and all(CJK.match(c) for c in s):
                targets.append((s, ent))

    protected = _mask(body, list(all_surfaces) + sorted(stoplist))
    cpos = _char_positions(body)
    n = len(body)
    out = {}
    for surf, ent in targets:
        L = len(surf)
        cands = set()
        for ch in set(surf):
            for p in cpos.get(ch, ()):
                for ln in (L - 1, L, L + 1):
                    if ln < 2:
                        continue
                    lo = max(0, p - ln + 1)
                    hi = min(p, n - ln)
                    for s0 in range(lo, hi + 1):
                        cands.add(body[s0:s0 + ln])
        for g in cands:
            if g in all_surfaces or g in official:
                continue
            if not all(CJK.match(c) for c in g):
                continue
            if g in surf or surf in g:
                continue
            if _lev(g, surf) != 1:
                continue
            # 逐個出現位置檢查：有任何一次出現「沒有」落在正常字串上，才算幻覺
            free_pos = -1
            st = 0
            while True:
                i = body.find(g, st)
                if i < 0:
                    break
                if not any(protected[i:i + len(g)]):
                    free_pos = i
                    break
                st = i + 1
            if free_pos < 0:
                continue
            rec = out.setdefault(g, {"variant": g, "of": [], "pos": free_pos})
            if surf not in rec["of"]:
                rec["of"].append(surf)
    return out


# --------------------------------------------------------------------------
# 量測
# --------------------------------------------------------------------------
def score_pair(ep, fan_text, self_text, roster, stoplist, include_headings=False):
    res = {"ep": ep, "versions": {}}
    bodies = {
        "粉絲版": extract_body(fan_text, include_headings),
        "自建版": extract_body(self_text, include_headings),
    }
    hits = {k: find_hits(v, roster) for k, v in bodies.items()}
    union = set(hits["粉絲版"]) | set(hits["自建版"])
    res["union_size"] = len(union)
    res["union"] = sorted(union)
    for k, body in bodies.items():
        h = hits[k]
        miss = sorted(union - set(h))
        hal = find_hallucinations(body, roster, stoplist)
        res["versions"][k] = {
            "hit": len(h),
            "miss": len(miss),
            "hallu": len(hal),
            "hit_ids": sorted(h),
            "miss_ids": miss,
            "hallu_items": sorted(hal.values(), key=lambda d: d["variant"]),
            "chars": len(body),
            "_hits_detail": h,
        }
    return res


def rate(hit, pop):
    return (hit / pop) if pop else None


def canon_map(roster):
    return {e.eid: e.canonical for e in roster}


# --------------------------------------------------------------------------
# 鑑別度對照組
# --------------------------------------------------------------------------
FIXTURE_FAN = """# EPxxx 測試用語料

歡迎收聽股癌，我是謝孟恭。今天想聊一下台積電的法說會，還有聯發科的展望。
輝達那邊的資料中心需求還是很猛，聯準會的態度倒是沒變。
"""

FIXTURE_SELF = """# EPxxx 測試用語料

歡迎收聽古愛我是孟公今天想聊一下台積電的法說會還有聯發課的展望
輝達那邊的資料中心需求還是很猛聯準會的態度倒是沒變
"""


def selftest():
    roster = load_roster()
    stoplist = load_hallu_stoplist()
    failures = []
    lines = []

    def run(fan, slf, tag):
        r = score_pair(tag, fan, slf, roster, stoplist)
        return r

    def snap(r, ver):
        v = r["versions"][ver]
        return (v["hit"], v["miss"], v["hallu"], r["union_size"])

    def check(name, ok, detail=""):
        lines.append(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
        if not ok:
            failures.append(name)

    base = run(FIXTURE_FAN, FIXTURE_SELF, "FIXTURE")
    b_fan, b_self = snap(base, "粉絲版"), snap(base, "自建版")
    lines.append(f"  baseline 粉絲版 hit/miss/hallu/U = {b_fan}")
    lines.append(f"  baseline 自建版 hit/miss/hallu/U = {b_self}")

    # 0) 母體不得為 0
    check("母體 > 0（all([])==True 防呆）", base["union_size"] > 0,
          f"U={base['union_size']}")

    # 0b) baseline 必須抓到已知落差：自建版少了「股癌」「謝孟恭」，且「聯發課」是幻覺
    cm = canon_map(roster)
    self_miss = {cm[i] for i in base["versions"]["自建版"]["miss_ids"]}
    check("baseline 抓到自建版漏掉『股癌』與『謝孟恭』",
          {"股癌", "謝孟恭"} <= self_miss, f"miss={sorted(self_miss)}")
    self_hallu = {d["variant"] for d in base["versions"]["自建版"]["hallu_items"]}
    check("baseline 抓到自建版幻覺『聯發課』", "聯發課" in self_hallu,
          f"hallu={sorted(self_hallu)}")

    # 1) 正向對照組：注入一筆真的新實體提及 → 命中必須 +1、漏必須 -1
    pos_fan = FIXTURE_FAN + "\n另外我昨天還買了一點京元電，覺得測試端還可以。\n"
    r1 = run(pos_fan, FIXTURE_SELF, "POS")
    f1 = snap(r1, "粉絲版")
    check("正向：注入真實新提及（京元電）→ 粉絲版命中 +1",
          f1[0] == b_fan[0] + 1, f"{b_fan[0]} -> {f1[0]}")
    check("正向：聯集母體 +1", r1["union_size"] == base["union_size"] + 1,
          f"{base['union_size']} -> {r1['union_size']}")
    s1 = snap(r1, "自建版")
    check("正向：自建版沒講到 → 漏 +1", s1[1] == b_self[1] + 1,
          f"{b_self[1]} -> {s1[1]}")

    # 2) 反向對照組 A：注入一行只是「提到」既有關鍵字的敘述文字 → 數字不准動
    narr = ("\n（校稿備註：本集大量討論台積電與聯發科，輝達也提了好幾次，"
            "謝孟恭在開頭有自報節目名稱股癌，請留意用詞一致性。）\n")
    r2 = run(FIXTURE_FAN + narr, FIXTURE_SELF, "NEG-A")
    check("反向A：敘述行只重述既有關鍵字 → 粉絲版三個數不動",
          snap(r2, "粉絲版") == b_fan, f"{b_fan} -> {snap(r2, '粉絲版')}")
    check("反向A：自建版三個數不動", snap(r2, "自建版") == b_self,
          f"{b_self} -> {snap(r2, '自建版')}")

    # 3) 反向對照組 B：同一個實體重複提及 10 次 → 數字不准動（防 59/58/60 漂移）
    rep = "\n" + "台積電真的很強，台積電。" * 10 + "\n"
    r3 = run(FIXTURE_FAN + rep, FIXTURE_SELF, "NEG-B")
    check("反向B：同實體重複 10 次 → 粉絲版三個數不動",
          snap(r3, "粉絲版") == b_fan, f"{b_fan} -> {snap(r3, '粉絲版')}")

    # 4) 反向對照組 C：HTML 註解裡寫一個新實體名 → 不准算進去
    r4 = run(FIXTURE_FAN + "\n<!-- 註：本集沒有提到京元電，這行只是註解 -->\n",
             FIXTURE_SELF, "NEG-C")
    check("反向C：HTML 註解裡的新實體名 → 粉絲版三個數不動",
          snap(r4, "粉絲版") == b_fan, f"{b_fan} -> {snap(r4, '粉絲版')}")

    # 5) 幻覺通道的正反向
    r5 = run(FIXTURE_FAN + "\n我看台機電這家公司最近很兇。\n", FIXTURE_SELF, "HAL-POS")
    check("幻覺正向：注入近形訛寫『台機電』→ 粉絲版幻覺 +1",
          snap(r5, "粉絲版")[2] == b_fan[2] + 1,
          f"{b_fan[2]} -> {snap(r5,'粉絲版')[2]}")
    r6 = run(FIXTURE_FAN + "\n我看台積電這家公司最近很兇。\n", FIXTURE_SELF, "HAL-NEG")
    check("幻覺反向：注入正確寫法『台積電』→ 粉絲版幻覺不動",
          snap(r6, "粉絲版")[2] == b_fan[2],
          f"{b_fan[2]} -> {snap(r6,'粉絲版')[2]}")

    # 5b) ASCII 邊界規則的正反向（自建版英文字沒有空格，不能用 \b）
    cm2 = canon_map(roster)
    r5b = run(FIXTURE_FAN, FIXTURE_SELF + "\n那時候ConstellationEnergyMicronSK Hynix都在講\n",
              "ASCII-POS")
    got = {cm2[i] for i in r5b["versions"]["自建版"]["hit_ids"]}
    check("ASCII 正向：無空格串接的 Micron 要算命中", "美光" in got or "Micron" in got,
          f"hits={sorted(got)}")
    r5d = run(FIXTURE_FAN, FIXTURE_SELF + "\n我覺得Google很強然後Microsoft也不錯\n",
              "ASCII-CJK")
    got_d = {cm2[i] for i in r5d["versions"]["自建版"]["hit_ids"]}
    check("ASCII 邊界：夾在中文裡的 Google/Microsoft 要算命中（中文字的 isalnum() 也是 True）",
          {"谷歌", "微軟"} <= got_d, f"hits={sorted(got_d)}")
    r5c = run(FIXTURE_FAN + "\n他真的很 Intelligent，也很 Applespice。\n",
              FIXTURE_SELF, "ASCII-NEG")
    got2 = {cm2[i] for i in r5c["versions"]["粉絲版"]["hit_ids"]}
    base_got = {cm2[i] for i in base["versions"]["粉絲版"]["hit_ids"]}
    check("ASCII 反向：Intelligent 不算 Intel、Applespice 不算 Apple",
          got2 == base_got, f"{sorted(base_got)} -> {sorted(got2)}")

    # 6) 空語料 → 母體 0 → 必須 FAIL，不准綠燈
    r7 = run("", "", "EMPTY")
    check("空語料 → 母體 0 被判定為不通過", r7["union_size"] == 0,
          "母體 0，下游一律 FAIL")
    check("空語料的正確率回傳 None 而不是 1.0",
          rate(r7["versions"]["粉絲版"]["hit"], r7["union_size"]) is None)

    print("=== --selftest（鑑別度對照組）===")
    print("\n".join(lines))
    print(f"=== 結果：{len(lines) - len(failures)}/{len(lines)} 通過 ===")
    if failures:
        print("FAILED: " + "; ".join(failures))
        return 1
    print("ALL PASS")
    return 0


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def check_provenance():
    """用 manifest.json 驗證「自建版」身分，印出憑證。"""
    p = REPO / MANIFEST
    recorded = {}
    if p.exists():
        data = json.loads(p.read_text(encoding="utf-8"))
        for rec in data.get("records", []):
            recorded[rec["ep_id"]] = os.path.basename(str(rec.get("path", "")).replace("\\", "/"))
    out = []
    for pair in PAIRS:
        ep = pair["ep"]
        self_name = os.path.basename(pair["self"])
        if pair["self_provenance"] == "manifest":
            ok = recorded.get(ep) == self_name
            out.append((ep, "manifest", ok, recorded.get(ep, "(無紀錄)")))
        else:
            srt = REPO / "docs" / "pairing_samples" / f"{ep}_raw.srt"
            out.append((ep, "pairing_sample", srt.exists(), str(srt.relative_to(REPO))))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="專有名詞正確率量尺（粉絲版 vs 自建版）")
    ap.add_argument("--selftest", action="store_true", help="跑鑑別度對照組")
    ap.add_argument("--audit", action="store_true", help="逐集列出命中/漏/幻覺明細")
    ap.add_argument("--include-headings", action="store_true",
                    help="把 markdown 標題行也算進正文（預設不算，因為只有粉絲版有編輯下的標題）")
    ap.add_argument("--json", metavar="PATH", help="把完整結果寫成 JSON")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    roster = load_roster(verbose=True)
    stoplist = load_hallu_stoplist()
    cm = canon_map(roster)

    print("=== 版本憑證 ===")
    for ep, kind, ok, note in check_provenance():
        print(f"  {ep} 自建版 憑證={kind} {'OK' if ok else 'MISSING'} :: {note}")
    print()

    results = []
    for pair in PAIRS:
        fan_p, self_p = REPO / pair["fan"], REPO / pair["self"]
        if not fan_p.exists() or not self_p.exists():
            print(f"!! {pair['ep']} 檔案缺失，跳過：{fan_p.exists()=} {self_p.exists()=}")
            continue
        results.append(score_pair(pair["ep"],
                                  fan_p.read_text(encoding="utf-8"),
                                  self_p.read_text(encoding="utf-8"),
                                  roster, stoplist, args.include_headings))

    if not results:
        print("FAIL：一集都沒量到，母體 0，不算通過。")
        return 1

    print("=== 逐集（母體 U = 該集兩版聯集的可驗證實體數）===")
    hdr = f"{'集數':<8}{'母體U':>6}{'版本':>8}{'命中':>6}{'漏':>5}{'幻覺':>6}{'正確率':>9}{'罰分後':>9}"
    print(hdr)
    print("-" * 62)
    tot = {"粉絲版": [0, 0, 0], "自建版": [0, 0, 0]}
    totU = 0
    for r in results:
        U = r["union_size"]
        totU += U
        for ver in ("粉絲版", "自建版"):
            v = r["versions"][ver]
            tot[ver][0] += v["hit"]
            tot[ver][1] += v["miss"]
            tot[ver][2] += v["hallu"]
            rec = rate(v["hit"], U)
            pen = rate(v["hit"], U + v["hallu"])
            print(f"{r['ep']:<8}{U:>6}{ver:>8}{v['hit']:>6}{v['miss']:>5}{v['hallu']:>6}"
                  f"{('%.1f%%' % (rec*100)) if rec is not None else 'N/A':>9}"
                  f"{('%.1f%%' % (pen*100)) if pen is not None else 'N/A':>9}")
    print("-" * 62)
    for ver in ("粉絲版", "自建版"):
        h, m, x = tot[ver]
        rec = rate(h, totU)
        pen = rate(h, totU + x)
        print(f"{'合計':<8}{totU:>6}{ver:>8}{h:>6}{m:>5}{x:>6}"
              f"{('%.1f%%' % (rec*100)) if rec is not None else 'N/A':>9}"
              f"{('%.1f%%' % (pen*100)) if pen is not None else 'N/A':>9}")
    print(f"\n母體（合計可驗證實體數，逐集聯集加總）= {totU}")
    if totU == 0:
        print("FAIL：母體 0，不算通過。")
        return 1

    if args.audit:
        print("\n=== --audit 明細 ===")
        for r in results:
            print(f"\n## {r['ep']}（母體 U={r['union_size']}）")
            for ver in ("粉絲版", "自建版"):
                v = r["versions"][ver]
                print(f"  [{ver}] 命中 {v['hit']}：" +
                      "、".join(cm[i] for i in v["hit_ids"]))
                print(f"  [{ver}] 漏 {v['miss']}：" +
                      ("、".join(cm[i] for i in v["miss_ids"]) or "（無）"))
                if v["hallu_items"]:
                    print(f"  [{ver}] 幻覺 {v['hallu']}：" + "、".join(
                        f"{d['variant']}(≈{'/'.join(d['of'])})" for d in v["hallu_items"]))
                else:
                    print(f"  [{ver}] 幻覺 0")

    if args.json:
        out = []
        for r in results:
            rr = json.loads(json.dumps(r, ensure_ascii=False, default=str))
            for ver in rr["versions"]:
                rr["versions"][ver].pop("_hits_detail", None)
            out.append(rr)
        Path(args.json).write_text(
            json.dumps({"pairs": out,
                        "total": {"union": totU,
                                  "粉絲版": tot["粉絲版"],
                                  "自建版": tot["自建版"]}},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[json] 已寫入 {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
