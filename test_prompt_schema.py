# -*- coding: utf-8 -*-
"""SYSTEM_PROMPT 的輸出 schema 與 claim_type 欄位的離線回歸測試。

為什麼有這支測試（2026-09-02，來源：
serenity-clone/remodel266_model_bakeoff_2026-08-27.md 第 7 節第 1 件）：
    現行 schema 只有 action（+1/-1/0），沒有「這句根本不是在猜未來」那一格，
    導致 2026-08-24 黃金標準裡 18/40 不是預測的句子全部被蓋上多空方向。
    這次把 claim_type（forward/notfwd/unclear）加進 schema。

🔴 這支測試**完全離線**：不呼叫任何模型、不連任何資料庫。
   它驗證的是「prompt 有沒有把這一欄講清楚」與「寫入路徑有沒有接上」，
   不是「模型標得準不準」——後者要有黃金標準才量得出來，見 serenity-clone。

跑法：
    python -X utf8 -m pytest test_prompt_schema.py -v
"""
import json
import re
from pathlib import Path

import pytest

import database
from prompt import CLAIM_TYPES, SYSTEM_PROMPT, rule_version

HERE = Path(__file__).parent


# ---------------------------------------------------------------------------
# 1. prompt 本身
# ---------------------------------------------------------------------------

def test_claim_types_值域就是三格():
    """三格＝黃金標準四選一扣掉方向那一維（方向住在 action 欄位）。"""
    assert CLAIM_TYPES == ("forward", "notfwd", "unclear")


@pytest.mark.parametrize("value", CLAIM_TYPES)
def test_每個合法值都出現在_prompt_裡(value):
    assert value in SYSTEM_PROMPT, f"{value} 沒有出現在 SYSTEM_PROMPT，模型不會知道有這一格"


def test_prompt_有問出那一題():
    """問法沿用 2026-08-24 丹尼爾親判時看到的那一句，人與機器要答同一題。"""
    assert "這句話，他是在猜未來嗎" in SYSTEM_PROMPT


def test_output_schema_區塊有_claim_type_欄位():
    schema_block = SYSTEM_PROMPT.split("# Output Format (JSON Schema)")[1]
    assert '"claim_type"' in schema_block


def test_prompt_明講_claim_type_不改變_action():
    """🔴 本次刻意不做的事：不因為 notfwd 就把 action 洗掉或把訊號濾掉。
    那會改變寄出去的信與回測母體，是要人點頭的行為改變。"""
    assert "claim_type` 不會改變 action 的填法" in SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# 2. few-shot 範例：模型照抄的東西必須自己合法
# ---------------------------------------------------------------------------

def _fewshot_signals():
    """把 SYSTEM_PROMPT 裡 few-shot 的『正確輸出』JSON 抓出來 parse。"""
    block = SYSTEM_PROMPT.split("[你的正確輸出]:")[1]
    start = block.index("{")
    depth, end = 0, None
    for i, ch in enumerate(block[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    assert end is not None, "few-shot JSON 大括號不成對，prompt 已經壞了"
    return json.loads(block[start:end])["extracted_signals"]


def test_fewshot_是合法_json_且母體不為零():
    signals = _fewshot_signals()
    assert len(signals) >= 2, f"few-shot 只有 {len(signals)} 筆，母體太小不算示範"


def test_fewshot_每一筆都填了合法的_claim_type():
    for s in _fewshot_signals():
        assert "claim_type" in s, f"{s.get('stock_name')} 這筆 few-shot 漏填 claim_type"
        assert s["claim_type"] in CLAIM_TYPES, f"{s['claim_type']!r} 不是合法值"


def test_fewshot_同時示範了_forward_與_notfwd():
    """只示範 forward 會讓模型學不會「不是預測」長什麼樣——這正是要修的偏誤。"""
    got = {s["claim_type"] for s in _fewshot_signals()}
    assert {"forward", "notfwd"} <= got, f"few-shot 只示範了 {got}"


def test_fewshot_有一筆是_notfwd_但_action_不是_0():
    """證明 prompt 真的把兩欄拆開：notfwd 不代表沒有多空立場。"""
    pairs = [(s["claim_type"], s["action"]) for s in _fewshot_signals()]
    assert ("notfwd", "-1") in pairs, f"沒有示範 notfwd × 有方向的組合，實際有：{pairs}"


# ---------------------------------------------------------------------------
# 3. 寫入路徑
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("forward", "forward"),
    ("notfwd", "notfwd"),
    ("unclear", "unclear"),
    ("  NOTFWD  ", "notfwd"),      # 大小寫與空白要收乾淨
    ("retrospective", None),        # 別的專案的詞彙，不是本 schema 的合法值
    ("", None),
    (None, None),
    (123, None),
])
def test_clean_claim_type(raw, expected):
    """非法值一律留 NULL，不猜一個值填進去——猜值等於製造假資料。"""
    assert database._clean_claim_type(raw) == expected


def test_insert_的欄位數與佔位符數一致():
    """把 12 欄改成 13 欄時最容易漏改 VALUES，那會在正式跑批時才爆。"""
    src = (HERE / "database.py").read_text(encoding="utf-8")
    m = re.search(r"INSERT INTO signals\s*\((.*?)\)\s*VALUES\s*\((.*?)\)", src, re.S)
    assert m, "找不到 signals 的 INSERT 敘述，本測試的假設已失效"
    cols = [c.strip() for c in m.group(1).split(",") if c.strip()]
    placeholders = [p.strip() for p in m.group(2).split(",") if p.strip()]
    assert len(cols) == len(placeholders), (
        f"欄位 {len(cols)} 個、佔位符 {len(placeholders)} 個：{cols}"
    )
    assert "claim_type" in cols, "claim_type 沒有被寫進 signals 表，這一欄等於白加"


def test_init_db_有加上_claim_type_欄位():
    src = (HERE / "database.py").read_text(encoding="utf-8")
    assert re.search(r"ADD COLUMN IF NOT EXISTS\s+claim_type\s+TEXT", src), (
        "init_db 沒有 additive migration，既有資料表不會長出這一欄"
    )


# ---------------------------------------------------------------------------
# 4. 規則版本
# ---------------------------------------------------------------------------

def test_rule_version_是_12_碼十六進位():
    rv = rule_version()
    assert re.fullmatch(r"[0-9a-f]{12}", rv), rv


def test_改動_prompt_會讓規則版本跟著變():
    """版本號是內容雜湊，改一個字就變——這次加 claim_type 之後的訊號會標成新版本，
    跟舊版訊號在 DB 裡分得開。"""
    import hashlib

    assert rule_version() == hashlib.sha256(
        SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12]
    assert rule_version() != hashlib.sha256(
        (SYSTEM_PROMPT + "x").encode("utf-8")).hexdigest()[:12]
