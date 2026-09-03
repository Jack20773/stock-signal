# -*- coding: utf-8 -*-
"""業配關卡（第二道，確定性版本）——不問模型，用關鍵字比對擋在寄信之前。

## 這支存在的理由

2026-08-28：EP689 的保險套業配裡有一句「誠心推薦特斯拉，濕，大大的濕」，被 LLM
判成 TSLA 看多訊號，**自動寄給 8 位收件人**，事後才被發現。

當天的修法是在 `prompt.py` 加了 Rule 1-B（「業配段落一律不得產生訊號」）。那是
第一道關卡，而且**它跟出事的那一步是同一個原理**：同一顆模型、同一次推論、同一
種失敗模式。模型看漏一次，整條線就再破一次。

這支是**第二道、原理不同的關卡**：

    模型產出訊號  ──▶  [Rule 1-B：模型自己判斷]  ──▶  存進 signals 表
                                                          │
                                                          ▼
                              [ad_guard：確定性關鍵字比對]  ──▶  寄信
                                          │
                                          └──▶ 擋下 → 落檔 + 印出來，等人看

兩道是 AND 不是二選一。第一道負責「一開始就不要產生」，這一道負責「就算產生了
也寄不出去」。

## 三條不可協商的行為

1. **不刪任何資料。** 被擋的訊號在 `signals` 表裡一個欄位都不會被改動；擋下這件
   事只寫進 `config.AD_GUARD_BLOCKED_LOG`（append-only JSONL）。悄悄消失比寄錯
   還糟。
2. **母體 0 不算通過。** 沒有訊號可檢查時回傳 `population == 0`，呼叫端必須印
   警告而不是 ✅。`all([]) == True` 是這類檢查最常見的假綠燈。
3. **判準跟模型無關。** 純子字串比對、大小寫不敏感。看起來很笨是特性不是缺點：
   它笨得跟模型不會犯同一種錯。

## 已知限制（不要粉飾）

- 這道關卡**擋不了「業配段落沒有出現任何關鍵字」的情況**。它是安全網不是屏障。
- 逐字稿檔案不在版控裡（`.gitignore` 有 `transcripts/`）。在沒有逐字稿的環境
  （例如 GitHub Actions）只會比對訊號自己帶的文字欄位，涵蓋面較小——這件事會
  寫進每一筆結果的 `scope` 欄位，不會假裝檢查過整段。
- 「合作」「廣告」「置入」這種詞在正常投資討論裡也會出現，所以本關卡**必然有
  誤擋**。誤擋的代價是「這筆訊號今天沒寄、留給人看」，漏擋的代價是「錯誤訊號寄
  給 8 個人」——刻意選擇往誤擋那邊偏。實測誤擋率見 `test_ad_guard.py --survey`。
"""
import io
import json
import os
import re
from datetime import datetime, timezone

from config import (
    AD_GUARD_BLOCKED_LOG,
    AD_GUARD_ENABLED,
    AD_GUARD_WINDOW_CHARS,
    AD_KEYWORDS,
)

TRANSCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "transcripts")

# Markdown 標題行：`# 標題` ~ `###### 標題`
_HEADING_RE = re.compile(r"^#{1,6}\s+.*$", re.MULTILINE)

# 訊號自己帶的文字欄位裡，哪些要一起掃。stock_name 也掃是因為業配商品名常常
# 「就是」那個假股票名（EP689 的「特斯拉 Model Sox」）。
_SIGNAL_TEXT_FIELDS = ("exact_quote", "reasoning", "raw_reason", "stock_name",
                       "primary_tag", "secondary_tags")


def _norm(text) -> str:
    """比對用的正規化：轉字串、轉小寫。刻意不做全形/半形轉換或去空白——
    多一層轉換就多一層「為什麼這個沒擋到」的除錯成本，而關鍵字本身是中文，
    大小寫只影響 sponsor / promo 那兩個。"""
    if text is None:
        return ""
    if isinstance(text, (list, tuple)):
        return " ".join(_norm(t) for t in text)
    return str(text).lower()


def find_keywords(text) -> list:
    """回傳 text 命中的關鍵字（依 AD_KEYWORDS 原順序，不重複）。"""
    hay = _norm(text)
    if not hay:
        return []
    return [kw for kw in AD_KEYWORDS if _norm(kw) in hay]


# ---------------------------------------------------------------------------
# 逐字稿：把「訊號對應的那一段」挖出來
# ---------------------------------------------------------------------------
def _ep_num(episode_id: str):
    m = re.search(r"(\d+)", str(episode_id or ""))
    return int(m.group(1)) if m else None


def load_transcript(episode_id: str) -> str | None:
    """讀 transcripts/EP{n}_*.md。找不到回 None（不是空字串——「沒有逐字稿」
    跟「逐字稿是空的」必須分得出來，否則涵蓋範圍會被靜默縮小）。"""
    n = _ep_num(episode_id)
    if n is None or not os.path.isdir(TRANSCRIPTS_DIR):
        return None
    prefix = f"EP{n}_"
    for name in sorted(os.listdir(TRANSCRIPTS_DIR)):
        if name.startswith(prefix) and name.lower().endswith(".md"):
            try:
                with io.open(os.path.join(TRANSCRIPTS_DIR, name), encoding="utf-8") as f:
                    return f.read()
            except OSError:
                return None
    return None


def locate_quote(transcript: str, quote: str) -> int:
    """在逐字稿裡找 exact_quote 的位置，找不到回 -1。

    先直接 find；失敗再用「去掉所有空白後」的比對找一次（模型抄句子時空白常有
    出入）。不做更模糊的比對——模糊比對會讓「這筆是怎麼判的」變得說不清楚。
    """
    if not transcript or not quote:
        return -1
    i = transcript.find(quote)
    if i >= 0:
        return i
    squashed = re.sub(r"\s+", "", quote)
    if len(squashed) < 12:
        return -1
    flat_map, flat_chars = [], []
    for k, ch in enumerate(transcript):
        if not ch.isspace():
            flat_chars.append(ch)
            flat_map.append(k)
    j = "".join(flat_chars).find(squashed)
    return flat_map[j] if j >= 0 else -1


def heading_of(transcript: str, idx: int) -> str:
    """quote 所在段落的 Markdown 標題行（只有那一行，不含內文）。"""
    hs = [h for h in _HEADING_RE.finditer(transcript) if h.start() <= idx]
    return hs[-1].group(0) if hs else ""


def extract_segment(transcript: str, quote: str, window: int = None) -> tuple:
    """把 quote 所在的「那一段」切出來，回傳 (segment_text, how)。

    段落 = **quote 前後各 window 字**，再把所在段落的 Markdown 標題行接在前面。
    how 有三種值，會原樣寫進稽核檔，好讓之後看得出這筆是怎麼判的：
      "window"  — 正常情況：字元窗 + 標題行。
      "notfound"— quote 在逐字稿裡找不到（模型改寫過、或標點不同）。回傳 None，
                  呼叫端只比對訊號自己的文字欄位，並在結果標記涵蓋範圍縮小。

    🔴 為什麼不用「整個 Markdown 段落」，也不用「整集逐字稿」——這是量出來的，
       不是憑感覺（2026-09-03，母體 = signals 表 988 筆有效訊號）：

           整集逐字稿      幾乎每集都有 `## 贊助` → 接近 100% 全擋
           整個標題段落    擋下 310/988 = 31.4%
           窗 800 字       擋下  93/988 =  9.4%
           窗 500 字       擋下  65/988 =  6.6%
           窗 300 字       擋下  46/988 =  4.7%   ← 現行預設
           窗 150 字       擋下  29/988 =  2.9%
           只比對訊號欄位  擋下  23/988 =  2.3%

       EP689 那句「誠心推薦特斯拉」在上面**每一種**窗寬下都會被擋（命中
       業配／贊助／誠心推薦／本集節目由，外加標題 `## 贊助`），所以把窗縮到
       300 不會放過這次事故要防的東西，只是少誤擋 47 筆正常訊號。
       誤擋的大宗是「合作」——正常的產業合作討論，跟業配同字不同義。
       這道關卡沒有辦法分辨那兩者（它刻意不做語意判斷），所以誤擋是設計的一部分：
       誤擋的代價是「這筆今天沒寄、留給人看」，漏擋的代價是「錯誤訊號寄給 8 個人」。
    """
    window = AD_GUARD_WINDOW_CHARS if window is None else window
    if not transcript or not quote:
        return None, "notfound"

    idx = locate_quote(transcript, quote)
    if idx < 0:
        return None, "notfound"

    lo = max(0, idx - window)
    hi = min(len(transcript), idx + len(quote) + window)
    head = heading_of(transcript, idx)
    seg = transcript[lo:hi]
    return ((head + "\n" + seg) if head else seg), "window"


# ---------------------------------------------------------------------------
# 單筆訊號檢查
# ---------------------------------------------------------------------------
def check_signal(signal: dict, transcript: str = None) -> dict:
    """回傳 {"blocked": bool, "keywords": [...], "where": str, "scope": str, ...}

    transcript 傳 None 時自己去 load_transcript()；傳字串則直接用（測試用）。
    """
    quote = signal.get("exact_quote") or ""
    ep = signal.get("episode_id") or ""

    if transcript is None:
        transcript = load_transcript(ep)

    seg, how = extract_segment(transcript, quote) if transcript else (None, "no_transcript")

    hits_signal = []
    for field in _SIGNAL_TEXT_FIELDS:
        for kw in find_keywords(signal.get(field)):
            if kw not in hits_signal:
                hits_signal.append(kw)

    hits_seg = find_keywords(seg) if seg else []

    keywords = list(hits_seg)
    for kw in hits_signal:
        if kw not in keywords:
            keywords.append(kw)

    if hits_seg and hits_signal:
        where = "transcript_segment+signal_fields"
    elif hits_seg:
        where = "transcript_segment"
    elif hits_signal:
        where = "signal_fields"
    else:
        where = ""

    if seg:
        scope = f"transcript_segment({how},{len(seg)} chars)+signal_fields"
    elif transcript:
        scope = f"signal_fields_only(quote {how} in transcript)"
    else:
        scope = "signal_fields_only(no transcript file)"

    return {
        "blocked": bool(keywords),
        "keywords": keywords,
        "where": where,
        "scope": scope,
        "segment_kind": how,
    }


# ---------------------------------------------------------------------------
# 批次：寄信前的關卡本體
# ---------------------------------------------------------------------------
def _record_blocked(rows: list, log_path: str = None) -> str:
    """把被擋的訊號 append 進 JSONL 稽核檔。只 append，永不覆寫、永不刪除。"""
    path = log_path or AD_GUARD_BLOCKED_LOG
    os.makedirs(os.path.dirname(path), exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()
    with io.open(path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps({"blocked_at": ts, **r}, ensure_ascii=False, default=str) + "\n")
    return path


def screen_signals(signals: list, log_path: str = None, record: bool = True) -> dict:
    """寄信前的關卡。回傳 dict：

        population  這次檢查了幾筆（母體。0 不是通過，是「沒東西可檢查」）
        passed      通過、可以寄的訊號（原物件，順序不變）
        blocked     被擋的 [(signal, verdict), ...]
        log_path    稽核檔路徑（沒擋到東西就是 None）
        enabled     關卡是否啟用
        lines       給呼叫端直接印的字串清單

    🔴 population == 0 時 lines 印的是警告，不是 ✅。
    """
    signals = list(signals or [])
    population = len(signals)

    if not AD_GUARD_ENABLED:
        return {
            "population": population,
            "passed": signals,
            "blocked": [],
            "log_path": None,
            "enabled": False,
            "lines": [
                f"⚠ 業配關卡已被停用（AD_GUARD_ENABLED=0）：{population} 筆訊號未經檢查直接放行。"
                "這是設定造成的，不是檢查通過。"
            ],
        }

    if population == 0:
        return {
            "population": 0,
            "passed": [],
            "blocked": [],
            "log_path": None,
            "enabled": True,
            "lines": [
                "⚠ 業配關卡：母體 0 筆——這次沒有任何訊號可以檢查。"
                "這不是「檢查通過」，是「沒東西可檢查」；若你預期這次應該有訊號，先去看上游為什麼是空的。"
            ],
        }

    # 同一集的逐字稿只讀一次
    cache: dict = {}
    passed, blocked = [], []
    for s in signals:
        ep = s.get("episode_id") or ""
        if ep not in cache:
            cache[ep] = load_transcript(ep)
        v = check_signal(s, transcript=cache[ep])
        (blocked if v["blocked"] else passed).append((s, v))

    blocked_rows = [
        {
            "signal_id": s.get("id"),
            "episode_id": s.get("episode_id"),
            "stock_name": s.get("stock_name"),
            "stock_code": s.get("stock_code"),
            "action": s.get("action"),
            "exact_quote": s.get("exact_quote"),
            "matched_keywords": v["keywords"],
            "matched_where": v["where"],
            "checked_scope": v["scope"],
            "note": "held back from email by ad_guard; the row in the signals table is untouched",
        }
        for s, v in blocked
    ]

    path = None
    if blocked_rows and record:
        path = _record_blocked(blocked_rows, log_path)

    # 涵蓋範圍必須跟結論寫在一起：有多少筆其實只比對到訊號自己的文字（因為
    # exact_quote 在逐字稿裡找不到），不講的話「擋下 0 筆」會被讀成「都乾淨」，
    # 但實際上有一部分根本沒比對到逐字稿。
    reduced = sum(1 for _s, v in (passed + blocked) if v["segment_kind"] != "window")
    lines = [
        f"業配關卡｜母體 {population} 筆訊號｜放行 {len(passed)} 筆｜擋下 {len(blocked)} 筆",
    ]
    if reduced:
        lines.append(
            f"  ⚠ 涵蓋範圍：其中 {reduced}/{population} 筆在逐字稿裡找不到對應句子，"
            f"只比對了訊號自身的文字欄位（涵蓋較小，不等於乾淨）。"
        )
    if blocked:
        for s, v in blocked:
            lines.append(
                f"  ⛔ 擋下 {s.get('episode_id')} {s.get('stock_name')}"
                f"（{s.get('stock_code')}, action={s.get('action')}, id={s.get('id')}）"
                f"｜命中關鍵字：{'、'.join(v['keywords'])}"
                f"｜命中位置：{v['where']}｜檢查範圍：{v['scope']}"
            )
            q = (s.get("exact_quote") or "").replace("\n", " ")
            lines.append(f"      原句：{q[:80]}{'…' if len(q) > 80 else ''}")
        lines.append(f"  → 這 {len(blocked)} 筆**不會寄出**，已留存待人工判讀：{path}")
        lines.append("  → 資料庫裡的原始訊號一個字都沒有動（沒有刪除、沒有改欄位）。")
    else:
        lines.append("  → 這次沒有訊號命中業配關鍵字（已實際比對，非空母體）。")

    return {
        "population": population,
        "passed": [s for s, _ in passed],
        "blocked": blocked,
        "log_path": path,
        "enabled": True,
        "lines": lines,
    }
