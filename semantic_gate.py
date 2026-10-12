# -*- coding: utf-8 -*-
"""寄信前的第二意見關卡（語意版）——另開一次獨立的 `claude -p`，只問一題。

## 為什麼有這一支（2026-10-12）

2026-08-28：EP689 保險套業配「誠心推薦特斯拉，濕，大大的濕」被判成 TSLA 看多，
自動寄給 8 個人。輸出格式全對、只有語意錯，程式驗不出來。

既有兩道關卡：
  1. prompt.py Rule 1-B ——叫「做判讀的同一顆模型、同一次呼叫」自己注意業配。
     跟出事那一步同一個推論，看漏一次就整條破。
  2. ad_guard.py ——關鍵字黑名單。擋得到「有寫『業配』『贊助』」的段落，擋不到
     沒有關鍵字的玩笑、雙關、舉例、轉述別人。

這支是第三道，原理跟前兩道都不同：**另一次獨立呼叫、不給它分析規則、不給它
整集逐字稿、只給「原句＋前後文＋判出的訊號」**，只問一題：

    「講話者是不是真的在對這檔股票表態？」
    （業配、玩笑、雙關、舉例、轉述別人、講產品不講股票＝否）

它不知道第一個模型為什麼這樣判，所以不會被同一套推理帶著走。

## 不可協商的行為

1. **否＝不寄；不確定＝照寄但卡片加一行標註**（2026-10-12 協調者裁決：嚴格版
   模擬 4 封信擋掉 14/27 張卡片，信會空掉；id=985 是明確「否」，放寬不確定不會放過它）。
2. **關卡自己失敗（逾時、非零 exit、回覆不是合法 JSON、verdict 不在合法值）＝不寄**，
   並記錄原因。關卡壞掉不等於檢查通過。
3. **不默默消失。** 每一則被擋的都 append 進 `SEMANTIC_GATE_LOG`（JSONL），並由
   notifier 印進日誌、列在信末。
4. **不動資料庫。** 判決只寫本機 JSONL；signals 表一個欄位都不改。
5. **只快取明確判決（yes／no）。** 同一則訊號（id＋原句雜湊）判過就不再問；
   uncertain 與 error 不快取，下次寄信會再問一次。
6. **母體 0 不算通過**（同 ad_guard）。

## 檢查範圍（刻意的取捨）

只檢查「信裡真的會出現的訊號卡片」——最新 2 集、action 為 +1/-1 的訊號
（跟 report_html.generate_html_email 的「本週最新訊號」同一套挑法）。信裡其他
部分是全集統計數字，不是逐則訊號。公開網站 report_detail.html 不在這道關卡
範圍內（那是被動頁面不是主動推送，跟 ad_guard 同一個決定）。
"""
import hashlib
import io
import json
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from analyzer import (
    ISOLATED_CWD,
    ClaudeCLIError,
    _build_clean_env,
    _extract_first_json_object,
    _strip_fences,
    build_claude_args,
    parse_claude_envelope,
)
from ad_guard import heading_of, load_transcript, locate_quote

_HERE = os.path.dirname(os.path.abspath(__file__))

SEMANTIC_GATE_ENABLED = os.getenv("SEMANTIC_GATE_ENABLED", "1") not in ("0", "false", "False")
SEMANTIC_GATE_MODEL = os.getenv("SEMANTIC_GATE_MODEL", "sonnet")
SEMANTIC_GATE_TIMEOUT_S = float(os.getenv("SEMANTIC_GATE_TIMEOUT_S", "180"))
SEMANTIC_GATE_WORKERS = int(os.getenv("SEMANTIC_GATE_WORKERS", "3"))
SEMANTIC_GATE_CONTEXT_CHARS = int(os.getenv("SEMANTIC_GATE_CONTEXT_CHARS", "500"))
SEMANTIC_GATE_LOG = os.getenv(
    "SEMANTIC_GATE_LOG", os.path.join(_HERE, "ops", "semantic_gate_verdicts.jsonl"))

VALID_VERDICTS = ("yes", "no", "uncertain")

QUESTION = """你是一位只做一件事的覆核員。下面是一段台灣財經 Podcast（股癌）的逐字稿片段，
以及另一個模型從裡面判讀出來的「投資訊號」。你的工作不是重新分析，只回答一題：

這段話是不是講話者「真的」在對這檔股票（這家公司的股價／投資價值）表態？

以下情況一律答 "no"：
- 業配、贊助、廣告口播（即使提到的品牌名剛好跟某家上市公司同名，例如商品名叫「特斯拉」）
- 玩笑、雙關、諧音哏、反諷
- 舉例、比喻、假設情境（「比如說你買了 X…」）
- 轉述別人的看法（聽眾、分析師、朋友說的），講話者自己沒有表態
- 只談產品、服務、生活使用心得，沒有在談這家公司的股票或投資
- 判讀出來的方向（看多／看空）跟原句的意思明顯相反

只有在講話者明確以自己的立場、在談投資或公司前景時對這檔標的表達看好或看壞，才答 "yes"。
資訊不足以判斷時答 "uncertain"。

只輸出一個 JSON 物件，不要其他文字：
{"verdict": "yes" | "no" | "uncertain", "reason": "一句話理由（繁體中文，30 字內）"}
"""


class GateError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# 輸入組裝
# ---------------------------------------------------------------------------
def build_context(signal: dict, transcript: str | None,
                  window: int = None) -> tuple[str | None, str]:
    """回傳 (前後文, how)。how ∈ window / quote_notfound / no_transcript。

    前後文＝原句前後各 window 字的原始逐字稿＋所在段落的 Markdown 標題行。
    刻意不在段落斷點截斷（ad_guard 會截，因為它怕關鍵字誤黏；這裡要的是讓覆核員
    看得到「上一段是不是業配開場」）。
    """
    window = SEMANTIC_GATE_CONTEXT_CHARS if window is None else window
    if not transcript:
        return None, "no_transcript"
    quote = signal.get("exact_quote") or ""
    idx = locate_quote(transcript, quote)
    if idx < 0:
        # 模型抄原句時常用「...」「……」把中間省略掉，整句就對不上。退一步用
        # 被省略號切開的最長那一段去找（locate_quote 自己會拒絕太短的片段）。
        frags = sorted((f.strip() for f in re.split(r"\.{3,}|…+", quote) if f.strip()),
                       key=len, reverse=True)
        for f in frags[:2]:
            idx = locate_quote(transcript, f)
            if idx >= 0:
                quote = f
                break
    if idx < 0:
        # 再退一步：去掉所有標點與空白後比對（粉絲版逐字稿與模型抄的原句常常
        # 只差逗號／全半形標點，例如 EP696 整集 5 則原句都因此對不上）。
        idx, quote = _locate_loose(transcript, signal.get("exact_quote") or "")
    if idx < 0:
        return None, "quote_notfound"
    lo = max(0, idx - window)
    hi = min(len(transcript), idx + len(quote) + window)
    head = heading_of(transcript, idx)
    seg = transcript[lo:hi]
    if head and head not in seg:
        seg = f"（所在段落標題：{head.strip()}）\n…{seg}…"
    else:
        seg = f"…{seg}…"
    return seg, "window"


_PUNCT_RE = re.compile(r"[\W_]+", re.UNICODE)


def _locate_loose(transcript: str, quote: str) -> tuple[int, str]:
    """忽略標點與空白比對。回傳 (逐字稿中的起點, 用來定位的那段原句)；找不到 (-1, quote)。
    片段太短（<12 字）不比，避免誤配到別處。"""
    flat_map, flat = [], []
    for k, ch in enumerate(transcript):
        if not _PUNCT_RE.fullmatch(ch):
            flat.append(ch)
            flat_map.append(k)
    hay = "".join(flat)
    cands = [quote] + sorted(re.split(r"\.{3,}|…+", quote), key=len, reverse=True)[:2]
    for c in cands:
        needle = _PUNCT_RE.sub("", c or "")
        if len(needle) < 12:
            continue
        j = hay.find(needle)
        if j >= 0:
            return flat_map[j], c
    return -1, quote


def _direction(action) -> str:
    return {"+1": "看多", "-1": "看空", "0": "中立"}.get(str(action), str(action))


def build_prompt(signal: dict, context: str | None) -> str:
    parts = [QUESTION, "\n---\n", "【判讀出的訊號】",
             f"標的：{signal.get('stock_name')}（{signal.get('stock_code')}）",
             f"方向：{_direction(signal.get('action'))}",
             f"原句：「{signal.get('exact_quote') or ''}」"]
    if context:
        parts += ["", "【原句前後文（逐字稿原文）】", context]
    else:
        parts += ["", "【前後文】無法取得（逐字稿裡找不到這句原句），只能就原句本身判斷。"]
    return "\n".join(parts)


def signal_key(signal: dict) -> str:
    h = hashlib.sha1((signal.get("exact_quote") or "").encode("utf-8")).hexdigest()[:12]
    return f"{signal.get('id')}:{signal.get('stock_code')}:{signal.get('action')}:{h}"


# ---------------------------------------------------------------------------
# 呼叫 claude -p
# ---------------------------------------------------------------------------
def parse_verdict(text: str) -> dict:
    """嚴格解析：一定要是 JSON 物件且 verdict ∈ VALID_VERDICTS，否則 GateError。"""
    raw = _strip_fences(text)
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        chunk = _extract_first_json_object(raw or "")
        try:
            obj = json.loads(chunk) if chunk else None
        except json.JSONDecodeError:
            obj = None
    if not isinstance(obj, dict):
        raise GateError(f"覆核回覆不是 JSON 物件：{(text or '')[:200]!r}")
    v = str(obj.get("verdict", "")).strip().lower()
    if v not in VALID_VERDICTS:
        raise GateError(f"覆核回覆 verdict={obj.get('verdict')!r} 不在合法值 {VALID_VERDICTS}")
    return {"verdict": v, "reason": str(obj.get("reason", "")).strip()[:200]}


def ask_claude(prompt: str, timeout: float = None) -> dict:
    """真的開一次 claude -p。回傳 {"verdict","reason","duration_s"}；失敗丟 GateError。"""
    timeout = SEMANTIC_GATE_TIMEOUT_S if timeout is None else timeout
    args = build_claude_args(model=SEMANTIC_GATE_MODEL, safe_mode=True, max_budget_usd=0.5)
    os.makedirs(ISOLATED_CWD, exist_ok=True)
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            args, input=prompt, capture_output=True, text=True, encoding="utf-8",
            errors="replace", cwd=ISOLATED_CWD, env=_build_clean_env(), timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise GateError(f"claude -p 逾時（{timeout:.0f}s）") from exc
    except OSError as exc:
        raise GateError(f"claude -p 無法啟動：{exc}") from exc
    dt = time.monotonic() - t0
    if proc.returncode != 0:
        raise GateError(f"claude -p exit={proc.returncode}：{(proc.stderr or '')[-300:]}")
    try:
        text = parse_claude_envelope(proc.stdout)["text"]
    except ClaudeCLIError as exc:
        raise GateError(str(exc)[:300]) from exc
    out = parse_verdict(text)
    out["duration_s"] = round(dt, 1)
    return out


# ---------------------------------------------------------------------------
# 快取（append-only JSONL，同時是稽核檔）
# ---------------------------------------------------------------------------
def load_cache(path: str = None) -> dict:
    path = path or SEMANTIC_GATE_LOG
    cache = {}
    if not os.path.exists(path):
        return cache
    with io.open(path, encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("verdict") in ("yes", "no") and row.get("key"):
                cache[row["key"]] = row
    return cache


def _append(rows: list, path: str = None) -> None:
    if not rows:
        return
    path = path or SEMANTIC_GATE_LOG
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")


# ---------------------------------------------------------------------------
# 關卡本體
# ---------------------------------------------------------------------------
def judge_one(signal: dict, transcript: str | None, asker=None) -> dict:
    """判一則。asker 可注入（測試用）；預設 ask_claude。永不丟例外——失敗變 verdict=error。"""
    asker = asker or ask_claude
    context, how = build_context(signal, transcript)
    prompt = build_prompt(signal, context)
    t0 = time.monotonic()
    try:
        res = asker(prompt)
        verdict, reason = res["verdict"], res.get("reason", "")
    except Exception as exc:  # noqa: BLE001 — 關卡任何失敗都等於「不放行」
        verdict, reason = "error", f"{type(exc).__name__}: {exc}"[:300]
    return {
        "verdict": verdict,
        "reason": reason,
        "context_kind": how,
        "duration_s": round(time.monotonic() - t0, 1),
    }


def screen(signals: list, asker=None, log_path: str = None, use_cache: bool = True,
           record: bool = True, workers: int = None) -> dict:
    """回傳 dict：population / passed / blocked [(signal, verdict_row)] / lines / enabled。

    passed 含 yes 與 uncertain；uncertain 另列在 flagged [(signal, verdict_row)]，呼叫端要標註。"""
    signals = list(signals or [])
    population = len(signals)
    if not SEMANTIC_GATE_ENABLED:
        return {"population": population, "passed": signals, "blocked": [], "flagged": [], "enabled": False,
                "lines": [f"⚠ 語意覆核關卡已被停用（SEMANTIC_GATE_ENABLED=0）：{population} 筆"
                          "訊號未經覆核直接放行。這是設定造成的，不是檢查通過。"]}
    if population == 0:
        return {"population": 0, "passed": [], "blocked": [], "flagged": [], "enabled": True,
                "lines": ["⚠ 語意覆核關卡：母體 0 筆——沒東西可檢查，不等於檢查通過。"]}

    cache = load_cache(log_path) if use_cache else {}
    transcripts: dict = {}
    todo, results = [], {}
    for s in signals:
        k = signal_key(s)
        if k in cache:
            c = cache[k]
            results[k] = {"verdict": c["verdict"], "reason": c.get("reason", ""),
                          "context_kind": c.get("context_kind", ""), "duration_s": 0.0,
                          "cached": True}
        else:
            ep = s.get("episode_id") or ""
            if ep not in transcripts:
                transcripts[ep] = load_transcript(ep)
            todo.append((k, s, transcripts[ep]))

    t0 = time.monotonic()
    n_workers = max(1, min(workers or SEMANTIC_GATE_WORKERS, len(todo) or 1))
    with ThreadPoolExecutor(max_workers=n_workers) as ex:
        futs = {k: ex.submit(judge_one, s, tr, asker) for k, s, tr in todo}
        for k, fut in futs.items():
            r = fut.result()
            r["cached"] = False
            results[k] = r
    wall = round(time.monotonic() - t0, 1)

    ts = datetime.now(timezone.utc).isoformat()
    new_rows = []
    for k, s, _tr in todo:
        r = results[k]
        new_rows.append({
            "judged_at": ts, "key": k, "signal_id": s.get("id"),
            "episode_id": s.get("episode_id"), "stock_name": s.get("stock_name"),
            "stock_code": s.get("stock_code"), "action": s.get("action"),
            "exact_quote": s.get("exact_quote"), "verdict": r["verdict"],
            "reason": r["reason"], "context_kind": r["context_kind"],
            "duration_s": r["duration_s"], "model": SEMANTIC_GATE_MODEL,
        })
    if record:
        _append(new_rows, log_path)

    # 2026-10-12 協調者裁決：uncertain 照寄但卡片加標註（flagged）；no／error 照舊不寄。
    passed, blocked, flagged = [], [], []
    for s in signals:
        r = results[signal_key(s)]
        if r["verdict"] == "yes":
            passed.append(s)
        elif r["verdict"] == "uncertain":
            passed.append(s)
            flagged.append((s, r))
        else:
            blocked.append((s, r))

    n_new = len(todo)
    lines = [f"語意覆核關卡｜母體 {population} 筆（新問 {n_new}、沿用先前判決 {population - n_new}）"
             f"｜放行 {len(passed) - len(flagged)}｜標註照寄 {len(flagged)}｜擋下 {len(blocked)}"
             f"｜新問耗時 {wall}s（{n_workers} 並行）"]
    for s, r in flagged:
        lines.append(f"  ⚠ 標註照寄 {s.get('episode_id')} {s.get('stock_name')}（{s.get('stock_code')}, "
                     f"{_direction(s.get('action'))}, id={s.get('id')}）｜判決 uncertain｜{r['reason']}")
    for s, r in blocked:
        q = (s.get("exact_quote") or "").replace("\n", " ")
        lines.append(f"  ⛔ 擋下 {s.get('episode_id')} {s.get('stock_name')}（{s.get('stock_code')}, "
                     f"{_direction(s.get('action'))}, id={s.get('id')}）｜判決 {r['verdict']}｜{r['reason']}")
        lines.append(f"      原句：{q[:80]}{'…' if len(q) > 80 else ''}")
    if blocked:
        lines.append(f"  → 這 {len(blocked)} 筆不會寄出；判決紀錄：{log_path or SEMANTIC_GATE_LOG}"
                     "（資料庫未改動）")
    return {"population": population, "passed": passed, "blocked": blocked, "flagged": flagged,
            "enabled": True, "lines": lines, "wall_s": wall, "asked": n_new}
