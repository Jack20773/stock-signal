"""
股癌語言習慣詞典 Phase 1 研究工具（索羅門 2026-08-02 第二輪任務 1b）。

目的：驗證「餵給模型股癌的個人語言習慣背景知識」有沒有用，用低成本方式做，
不直接跳去 fine-tune。

技術做法（任務檔1b交給索羅門自行判斷）：
  - 680 集全部塞進單一 context 大概率超過視窗，這裡採「取樣＋分批萃取＋
    二次彙整去重」：
    1. 取樣：不是隨機抽，是刻意分兩段——「最近15集」(語言習慣跟現在的分析
       pipeline最相關) + 「歷史8集分散取樣」(EP50/130/210/290/370/450/530/610，
       約略等距分佈在680集歷史裡，捕捉長期存在的口頭禪/黑話)，共23集抽樣
       目標，其中 EP677 逐字稿檔案缺失（見 crosscheck.py 同一輪的發現），
       實際跑 22 集。
    2. 逐集萃取：每次1集丟給 DeepSeek，請它找「隱性指涉／反諷句型／口頭禪」
       三類、每條要附原文引用，不要空泛描述（原本設計是每批3集，實測發現
       候選數量多的批次會撞到completion輸出上限被截斷、JSON解析失敗、整批
       候選歸零，改成逐集呼叫規避這個風險，見BATCH_SIZE註解與_call_deepseek()
       的finish_reason檢查）。
    3. 二次彙整：把全部批次的候選結果（不是原始逐字稿，只是萃取出的候選
       清單，體積小很多）餵給另一次 DeepSeek 呼叫做去重＋挑出證據最充分的
       條目，輸出最終詞典。

用法：
  python build_idiom_glossary.py
輸出：docs/host_idiom_glossary.md
"""
import glob
import json
import logging
import os
import re
import sys
from datetime import date

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                     handlers=[logging.StreamHandler(sys.stdout)])

TRANSCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "transcripts")
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"

RECENT_SAMPLE = list(range(666, 681))
HISTORICAL_SAMPLE = [50, 130, 210, 290, 370, 450, 530, 610]
SAMPLE_EPISODES = RECENT_SAMPLE + HISTORICAL_SAMPLE
# 2026-08-02 索羅門修正：原本 BATCH_SIZE=3 時，兩批（[666,667,668]／
# [290,370,450]，剛好是候選數量特別多的集數）輸出被 completion tokens
# 上限（實測卡在8192，疑似deepseek-chat未指定max_tokens時的預設輸出上限）
# 截斷，JSON解析失敗、整批候選直接歸零，且原本沒有察覺、差點被當成
# 「這幾集真的沒有模式」蒙混過去。改成每集單獨呼叫（BATCH_SIZE=1），
# 單集候選數遠低於會撞到輸出上限的量，用呼叫次數增加換取不再截斷，
# 22次呼叫成本仍在US$0.1量級，遠低於US$5預算。
BATCH_SIZE = 1

_DEEPSEEK_INPUT_USD_PER_M = 0.14
_DEEPSEEK_OUTPUT_USD_PER_M = 0.28

_total_cost_usd = 0.0


def _find_transcript(num: int) -> str | None:
    matches = glob.glob(os.path.join(TRANSCRIPTS_DIR, f"EP{num}_*.md"))
    return matches[0] if matches else None


def _call_deepseek(system_prompt: str, user_content: str, max_tokens: int = 8192) -> str:
    """回傳內容字串；若 finish_reason=='length'（輸出被max_tokens截斷），
    直接丟例外而不是讓呼叫端拿到殘缺JSON去解析失敗後才後知後覺——這是
    2026-08-02修正的bug：原本兩批候選因為這個狀況被截斷、JSON解析失敗、
    候選直接歸零卻沒有明顯警訊，靠事後人工看log才發現。"""
    global _total_cost_usd
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("環境變數 DEEPSEEK_API_KEY 未設定")
    resp = requests.post(
        DEEPSEEK_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.2,
            "max_tokens": max_tokens,
        },
        timeout=180,
    )
    resp.raise_for_status()
    data = resp.json()
    usage = data.get("usage", {})
    cost = (usage.get("prompt_tokens", 0) / 1_000_000) * _DEEPSEEK_INPUT_USD_PER_M \
         + (usage.get("completion_tokens", 0) / 1_000_000) * _DEEPSEEK_OUTPUT_USD_PER_M
    _total_cost_usd += cost
    finish_reason = data["choices"][0].get("finish_reason")
    logging.info(f"  DeepSeek呼叫：prompt={usage.get('prompt_tokens')} completion={usage.get('completion_tokens')} "
                 f"finish_reason={finish_reason} cost=${cost:.4f} (累計 ${_total_cost_usd:.4f})")
    if finish_reason == "length":
        raise RuntimeError(
            f"DeepSeek輸出被max_tokens={max_tokens}截斷（finish_reason=length），"
            f"內容不完整不能解析，呼叫端應該用更小的批次重試，不是硬解析殘缺JSON"
        )
    return data["choices"][0]["message"]["content"].strip()


def _parse_json_array(raw: str) -> list:
    """2026-08-02完工前Codex最終審查指出：原本沒驗證陣列元素本身是不是dict，
    模型若回傳像 ["foo"] 這種「合法JSON但元素不是物件」的格式，會在下游
    _fallback_group()/render_markdown() 呼叫 .get() 時整個腳本崩潰——這裡
    在源頭就把非dict元素過濾掉並警告，不讓格式不對的東西混進候選清單。"""
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logging.warning(f"  JSON解析失敗，原始內容前300字：{raw[:300]}")
        return []
    if isinstance(parsed, dict):
        # 有些回應可能包成 {"patterns": [...]}，容錯抓第一個 list 欄位
        found = None
        for v in parsed.values():
            if isinstance(v, list):
                found = v
                break
        parsed = found or []
    elif not isinstance(parsed, list):
        parsed = []
    non_dict = [x for x in parsed if not isinstance(x, dict)]
    if non_dict:
        logging.warning(f"  萃取結果混入 {len(non_dict)} 個非物件元素，已過濾：{non_dict[:3]}")
    return [x for x in parsed if isinstance(x, dict)]


_EXTRACT_SYSTEM = """你是研究台灣財經Podcast《股癌》主持人謝孟恭語言習慣的分析師。
你的任務是從逐字稿裡找出三類模式，只找「真的反覆出現、有明確語言特徵」的東西，
找不到就回傳空陣列，不要為了湊數硬拗。

1. 隱性指涉（inexplicit_reference）：不直接講股票代號/公司全名，而是用綽號、
   簡稱、業內黑話、或某種迂迴說法指涉特定產業或個股。
2. 反諷句型（irony_pattern）：明顯是反串/自嘲/誇飾的固定句型或用詞組合
   （跟「這檔穩死的啦、財富自由靠這次、開槓桿梭哈」這種已知反串語氣類似的
   變體或延伸用法）。
3. 口頭禪（catchphrase）：反覆出現、會影響「看多/看空/中立」判讀的比喻或
   語氣詞（例如某種說法代表他其實在講反話，或某個詞是他的招牌講法）。

輸出格式：JSON陣列，每個元素：
{"category": "inexplicit_reference 或 irony_pattern 或 catchphrase",
 "pattern": "這個模式的簡短命名/描述",
 "quote": "逐字稿裡的原文引用（盡量精簡但要能佐證）",
 "episode": "EPxxx",
 "meaning": "這個模式實際代表什麼意思、怎麼影響多空判讀"}
只輸出JSON陣列本身，不要有其他文字。"""


_CONSOLIDATE_SYSTEM = """你是整理研究筆記的分析師。以下是多批次分析累積出的候選清單
（可能有重複、相似、或證據薄弱的條目）。請去重、合併相似項目，只保留有明確
原文引用佐證、且模式清楚可辨識的條目，依三個類別分組，每個類別內按重要性
排序。保留最有代表性的引用範例（可以合併同一模式的多個引用，最多列2個）。

**每個類別最多輸出15條**（依重要性/證據充分程度篩選，捨棄較弱或重複的，
不要為了保留全部候選硬把輸出撐大——這是為了避免輸出被截斷，寧可篩選精簡
也不要輸出不完整的JSON）。

輸出格式：JSON物件 {"inexplicit_reference": [...], "irony_pattern": [...],
"catchphrase": [...]}，每個陣列元素跟輸入格式一樣但quote改成陣列（1-2則）：
{"pattern": "...", "quotes": ["...", "..."], "episodes": ["EPxxx", "EPyyy"],
 "meaning": "..."}
只輸出JSON物件本身，不要有其他文字。"""


def run_batch(nums: list[int]) -> list[dict]:
    parts = []
    for n in nums:
        path = _find_transcript(n)
        if not path:
            logging.warning(f"  EP{n} 逐字稿缺失，跳過（不是bug，見docs說明）")
            continue
        with open(path, encoding="utf-8") as f:
            parts.append(f"### EP{n}\n{f.read()}")
    if not parts:
        return []
    user_content = "\n\n".join(parts)
    try:
        raw = _call_deepseek(_EXTRACT_SYSTEM, user_content)
    except (RuntimeError, requests.RequestException, KeyError) as e:
        # 2026-08-02完工前Codex最終審查指出：原本只接RuntimeError（自訂的
        # 截斷偵測），網路逾時/HTTP錯誤/回應缺欄位(KeyError)都會直接讓整個
        # main()迴圈中斷、後面還沒跑的集數全部沒有機會執行——改成這批失敗
        # 只記錯誤、回空清單，其餘集數繼續跑，不因單一批次失敗就整個沒產出。
        logging.error(f"  批次 {nums} 呼叫失敗（{type(e).__name__}: {e}），這批候選會是空的，不是這幾集真的沒有模式")
        return []
    return _parse_json_array(raw)


def _fallback_group(all_candidates: list[dict]) -> dict:
    """consolidate() 的LLM呼叫萬一還是失敗/截斷時的保底方案：純程式化分組+
    去重（用pattern文字完全相同去重，不做語意合併），不寄望LLM，確保腳本
    無論如何都能產出一份可用的詞典，不會因為最後一步失敗就整個沒有產出。"""
    grouped: dict[str, dict[str, dict]] = {"inexplicit_reference": {}, "irony_pattern": {}, "catchphrase": {}}
    for c in all_candidates:
        cat = c.get("category")
        if cat not in grouped:
            continue
        key = (c.get("pattern") or "").strip()
        if not key:
            continue
        if key not in grouped[cat]:
            grouped[cat][key] = {
                "pattern": key, "quotes": [], "episodes": [], "meaning": c.get("meaning", ""),
            }
        entry = grouped[cat][key]
        if c.get("quote") and c["quote"] not in entry["quotes"]:
            entry["quotes"].append(c["quote"])
        if c.get("episode") and c["episode"] not in entry["episodes"]:
            entry["episodes"].append(c["episode"])
    return {cat: list(items.values()) for cat, items in grouped.items()}


def consolidate(all_candidates: list[dict]) -> dict:
    if not all_candidates:
        return {"inexplicit_reference": [], "irony_pattern": [], "catchphrase": []}
    try:
        raw = _call_deepseek(_CONSOLIDATE_SYSTEM, json.dumps(all_candidates, ensure_ascii=False))
        parsed = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip()))
        if not isinstance(parsed, dict):
            raise ValueError(f"彙整結果最外層不是物件，而是 {type(parsed).__name__}")
        for key in ("inexplicit_reference", "irony_pattern", "catchphrase"):
            items = parsed.get(key, [])
            # 同樣過濾非dict元素（見_parse_json_array同款防護理由）
            parsed[key] = [x for x in items if isinstance(x, dict)] if isinstance(items, list) else []
        return parsed
    except (RuntimeError, requests.RequestException, KeyError, json.JSONDecodeError, ValueError) as e:
        # 2026-08-02完工前Codex最終審查指出：原本只接(RuntimeError,
        # JSONDecodeError)，網路錯誤/回應缺欄位不會被擋下；擴大例外範圍，
        # 任何一種失敗都落到程式化保底方案，不讓腳本整個崩潰、沒有任何產出。
        logging.error(f"  二次彙整LLM呼叫失敗/解析失敗（{type(e).__name__}: {e}），改用純程式化去重當保底方案"
                       f"（沒有語意合併，只是精簡展示原始候選，品質比LLM彙整版粗糙，"
                       f"完工報告會如實揭露這個降級）")
        return _fallback_group(all_candidates)


def render_markdown(final: dict, sample_episodes: list[int], missing: list[int],
                     n_candidates: int, cost_usd: float) -> str:
    today = date.today().isoformat()
    lines = [
        "# 股癌語言習慣詞典（Phase 1，研究產出）",
        "",
        f"產出日期：{today} · 索羅門第二輪任務1b",
        "",
        "## 方法論（老實交代處理範圍，不是全部680集）",
        "",
        f"- 全部逐字稿共680集，本次**取樣22集**（未做680集全量分析）：",
        f"  - 最近15集（EP666-EP680，跟目前正式分析pipeline最相關）",
        f"  - 歷史8集等距抽樣（EP50/130/210/290/370/450/530/610，捕捉長期存在的口頭禪/黑話）",
        f"  - 取樣清單中 EP677 逐字稿檔案在 transcripts/ 目錄缺失（既有資料缺口，"
        f"跟 crosscheck.py 那輪的發現一致），實際處理 {len(sample_episodes) - len(missing)} 集",
        f"- 逐集萃取（每次1集，避免批次過大導致輸出被截斷）+ 二次彙整去重，"
        f"共產生 {n_candidates} 條候選、"
        f"彙整後保留下方列出的條目",
        f"- DeepSeek 呼叫總花費：約 ${cost_usd:.4f}",
        "",
        "## 為什麼取樣而非全量680集",
        "",
        "680集全部塞進單一context會超過視窗；即使分批，680集全量跑法會是這次",
        "取樣範圍的約30倍呼叫量與花費。這是Phase 1驗證「詞典有沒有用」的探索",
        "任務，不是要一次做到最終版——先用取樣版本驗證方向對不對，如果決定要",
        "接進正式pipeline，之後可以再擴大取樣或做全量分析（任務檔明確定位這輪",
        "是Phase 1，fine-tune等更高成本方案留待之後）。",
        "",
    ]

    labels = {
        "inexplicit_reference": "## 隱性指涉（不直接點名，但固定用某種說法指涉特定產業/個股）",
        "irony_pattern": "## 反諷句型（跟現有Rule 1反串過濾機制對照，看有沒有現有規則沒覆蓋到的變體）",
        "catchphrase": "## 口頭禪／比喻（反覆出現、會影響看多看空判讀的語氣詞）",
    }
    total_items = 0
    for key, heading in labels.items():
        items = final.get(key, [])
        lines.append(heading)
        lines.append("")
        if not items:
            lines.append("（這次取樣沒有找到夠明確、可驗證的模式）")
            lines.append("")
            continue
        for i, item in enumerate(items, 1):
            total_items += 1
            pattern = item.get("pattern", "")
            meaning = item.get("meaning", "")
            episodes = item.get("episodes") or ([item["episode"]] if item.get("episode") else [])
            quotes = item.get("quotes") or ([item["quote"]] if item.get("quote") else [])
            lines.append(f"**{i}. {pattern}**")
            lines.append(f"- 意義／怎麼影響判讀：{meaning}")
            for q, ep in zip(quotes, episodes + [""] * len(quotes)):
                ep_note = f"（{ep}）" if ep else ""
                lines.append(f"- 原文佐證{ep_note}：「{q}」")
            lines.append("")

    lines.append("## 殘餘風險與下一步建議")
    lines.append("")
    lines.append(f"- 這份詞典基於22集取樣，不是680集全量分析，可能遺漏取樣範圍外才出現的模式")
    lines.append("- 條目本身若有誤判（DeepSeek萃取階段可能誤把單次用法當成反覆模式），"
                  "接進SYSTEM_PROMPT前建議人工快速過目一次")
    lines.append(f"- 共 {total_items} 條最終條目，DoD要求至少5條——{'已達成' if total_items >= 5 else '未達成，需要擴大取樣'}")
    lines.append("")
    return "\n".join(lines)


def main():
    logging.info(f"取樣集數：{SAMPLE_EPISODES}")
    all_candidates = []
    missing = []
    batches = [SAMPLE_EPISODES[i:i + BATCH_SIZE] for i in range(0, len(SAMPLE_EPISODES), BATCH_SIZE)]
    for batch in batches:
        logging.info(f"=== 批次 {batch} ===")
        for n in batch:
            if not _find_transcript(n):
                missing.append(n)
        candidates = run_batch(batch)
        logging.info(f"  萃取出 {len(candidates)} 條候選")
        all_candidates.extend(candidates)

    logging.info(f"全部批次共 {len(all_candidates)} 條候選，開始二次彙整去重...")

    os.makedirs("docs", exist_ok=True)
    # 留存原始候選清單（去重前），方便事後稽核彙整階段有沒有漏掉或誤刪條目，
    # 不是只看最終markdown（2026-08-02 修正truncation bug時發現原本完全沒
    # 留中間產物，差點無法察覺兩批候選被截斷歸零）。
    with open(os.path.join("docs", "host_idiom_glossary_raw_candidates.json"), "w", encoding="utf-8") as f:
        json.dump(all_candidates, f, ensure_ascii=False, indent=2)

    final = consolidate(all_candidates)
    md = render_markdown(final, SAMPLE_EPISODES, sorted(set(missing)), len(all_candidates), _total_cost_usd)
    out_path = os.path.join("docs", "host_idiom_glossary.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)
    logging.info(f"完成，已寫入 {out_path}")
    logging.info(f"DeepSeek 總花費：${_total_cost_usd:.4f}")


if __name__ == "__main__":
    main()
