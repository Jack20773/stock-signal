"""
Gemini/DeepSeek 分歧仲裁工具（索羅門 2026-08-02 第二輪任務 1a）。

目的：讓「這集分析到底準不準」變得可查證，不再是黑盒信任單一免費模型
（Gemini）。流程：
  1. 讀 transcripts/ 對應集數逐字稿全文
  2. 呼叫 DeepSeek（deepseek-chat）用同一套 SYSTEM_PROMPT 分析同一集，
     拿到 DeepSeek 版的 extracted_signals
  3. 跟 DB 裡這集既有的 Gemini 分析結果（signals 表）比對，用 stock_code
     對齊，判定分歧
  4. 有分歧時，組出仲裁 prompt（含完整逐字稿+兩邊判斷），呼叫
     `codex exec -s read-only`（gpt-5.6-terra，read-only，不寫檔不動網路）
     拿到仲裁結論
  5. 結果寫進新表 signal_review（純記錄，絕對不 UPDATE signals 表）

用法：
  python crosscheck.py EP677 EP678 EP679
  python crosscheck.py EP680 --no-codex   # 只跑 DeepSeek+分歧偵測，不燒 Codex 額度

不接進 GitHub Actions／週排程——本機執行即可（見任務檔1a說明：Codex CLI
用本機 ChatGPT 登入 session，不是可攜的 API key，不貿然匯出成 GitHub Secret）。
"""
import argparse
import glob
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date

import requests

from prompt import SYSTEM_PROMPT
from database import _conn, init_db, list_signals

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                     handlers=[logging.StreamHandler(sys.stdout)])

TRANSCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "transcripts")
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"

# DeepSeek 官網公告費率（2026-08-01 索羅門主控session查證，deepseek-chat；
# 之後如需精確費率請重新查證 platform.deepseek.com 帳務頁，不要沿用此日期後的數字）
_DEEPSEEK_INPUT_USD_PER_M  = 0.14
_DEEPSEEK_OUTPUT_USD_PER_M = 0.28


class CrosscheckError(Exception):
    """逐字稿找不到、DeepSeek 回傳格式錯誤、Codex 仲裁失敗等，一律用這個擋，
    不要讓呼叫端把「這集沒東西可比對」跟「這集真的沒分歧」混為一談。"""
    pass


# ── 逐字稿 ──────────────────────────────────────────────────────────────────

def _find_transcript(episode_id: str) -> str:
    m = re.search(r"\d+", episode_id)
    if not m:
        raise CrosscheckError(f"無法從 {episode_id!r} 解析出集數編號")
    pattern = os.path.join(TRANSCRIPTS_DIR, f"EP{m.group()}_*.md")
    matches = glob.glob(pattern)
    if not matches:
        raise CrosscheckError(
            f"找不到 {episode_id} 的逐字稿檔案（pattern={pattern}）——"
            f"transcripts/ 目錄可能缺這一集，需要另外補下載，不是本工具的 bug"
        )
    if len(matches) > 1:
        raise CrosscheckError(f"{episode_id} 比對到多個逐字稿檔案，無法判斷用哪個：{matches}")
    return matches[0]


def _read_transcript(episode_id: str) -> str:
    path = _find_transcript(episode_id)
    with open(path, encoding="utf-8") as f:
        return f.read()


# ── DeepSeek ────────────────────────────────────────────────────────────────

def call_deepseek(transcript: str) -> dict:
    """回傳 {"signals": [...], "usage": {...}}；signals 是跟 Gemini
    analyzer.py::analyze() 同一套 schema 的 extracted_signals 陣列。"""
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise CrosscheckError("環境變數 DEEPSEEK_API_KEY 未設定，無法呼叫 DeepSeek")

    today = date.today().isoformat()
    user_content = f"今天日期：{today}\n\n以下是今天的逐字稿：\n\n{transcript}"

    resp = requests.post(
        DEEPSEEK_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0,
        },
        timeout=180,
    )
    resp.raise_for_status()
    data = resp.json()
    raw = data["choices"][0]["message"]["content"].strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise CrosscheckError(f"DeepSeek 回傳內容不是合法 JSON：{e}\n原始內容前500字：{raw[:500]}") from e
    if not isinstance(parsed, dict) or not isinstance(parsed.get("extracted_signals"), list):
        raise CrosscheckError(f"DeepSeek 回傳格式不符（缺 extracted_signals 或型別不對）：{str(parsed)[:500]}")

    usage = data.get("usage", {})
    return {"signals": parsed["extracted_signals"], "usage": usage}


def estimate_deepseek_cost_usd(usage: dict) -> float:
    inp  = usage.get("prompt_tokens", 0)
    outp = usage.get("completion_tokens", 0)
    return (inp / 1_000_000) * _DEEPSEEK_INPUT_USD_PER_M + (outp / 1_000_000) * _DEEPSEEK_OUTPUT_USD_PER_M


# ── 分歧偵測 ────────────────────────────────────────────────────────────────

def detect_divergences(gemini_signals: list[dict], deepseek_signals: list[dict]) -> list[dict]:
    """判定分歧的條件（兩者皆需觸發，缺一都算分歧，任務檔1a暫定可調整）：
      - 同一 stock_code 兩邊 action 不同
      - 一邊有抓到某 stock_code、另一邊完全沒有這筆（不對稱偵測）
    gemini_signals：DB signals 表的 row（dict，欄位含 stock_code/action/...）
    deepseek_signals：DeepSeek 回傳的 extracted_signals（欄位含 stock_code/action/...）
    """
    g_by_code = {s["stock_code"]: s for s in gemini_signals
                 if s.get("stock_code") and s["stock_code"] != "Unknown"}
    d_by_code = {s.get("stock_code"): s for s in deepseek_signals
                 if s.get("stock_code") and s.get("stock_code") != "Unknown"}

    divergences = []
    for code in sorted(set(g_by_code) | set(d_by_code)):
        g, d = g_by_code.get(code), d_by_code.get(code)
        if g is None:
            divergences.append({"stock_code": code, "type": "deepseek_only", "gemini": None, "deepseek": d})
        elif d is None:
            divergences.append({"stock_code": code, "type": "gemini_only", "gemini": g, "deepseek": None})
        elif str(g.get("action")) != str(d.get("action")):
            divergences.append({"stock_code": code, "type": "action_diff", "gemini": g, "deepseek": d})
    return divergences


# ── Codex 仲裁 ──────────────────────────────────────────────────────────────

_ARBITRATION_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {
            "type": "string",
            "enum": ["gemini_correct", "deepseek_correct", "both_wrong", "both_correct_ambiguous"],
        },
        "correct_action": {"type": "string", "enum": ["+1", "-1", "0"]},
        "reasoning": {"type": "string"},
    },
    "required": ["verdict", "correct_action", "reasoning"],
    "additionalProperties": False,
}


def _fmt_side(label: str, sig: dict | None) -> str:
    if sig is None:
        return f"{label}：（沒有抓到這檔標的，或判定為反串/無訊號過濾掉了）"
    return (
        f"{label}：action={sig.get('action')}, confidence={sig.get('confidence_level')}\n"
        f"  reasoning: {sig.get('reasoning') or ''}\n"
        f"  exact_quote: {sig.get('exact_quote') or ''}"
    )


def build_arbitration_prompt(episode_id: str, transcript: str, divergence: dict) -> str:
    code = divergence["stock_code"]
    return f"""你是量化交易研究員，任務是仲裁兩個 AI 模型對同一份 Podcast《股癌》逐字稿
分析出的投資訊號分歧，判斷哪一方比較貼近逐字稿原意。以下是完整的分析規則
（跟兩個模型分析時用的是同一份 system prompt，你可以拿來對照兩邊的判斷有沒有
誤用規則）：

# 分析規則（system prompt 全文）
{SYSTEM_PROMPT}

# 這次要仲裁的分歧
集數：{episode_id}
標的：{code}
分歧類型：{divergence['type']}（action_diff=兩邊都抓到但action不同／
gemini_only=只有Gemini抓到／deepseek_only=只有DeepSeek抓到）

{_fmt_side('Gemini 的判斷', divergence.get('gemini'))}

{_fmt_side('DeepSeek 的判斷', divergence.get('deepseek'))}

# 完整逐字稿
{transcript}

# 你的任務
仔細讀完逐字稿裡所有跟「{code}」有關的發言脈絡（包含前後文語氣、產業鏈判定
基準、反串過濾規則），判斷哪一方的 action 判定比較正確，或者兩者都不夠精確
時直接給出你認為正確的淨訊號。只輸出符合 schema 的 JSON，不要有其他文字。"""


def call_codex_arbitrate(episode_id: str, transcript: str, divergence: dict) -> dict:
    prompt = build_arbitration_prompt(episode_id, transcript, divergence)
    with tempfile.TemporaryDirectory() as td:
        schema_path = os.path.join(td, "schema.json")
        out_path = os.path.join(td, "out.json")
        with open(schema_path, "w", encoding="utf-8") as f:
            json.dump(_ARBITRATION_SCHEMA, f)

        codex_bin = shutil.which("codex")
        if not codex_bin:
            raise CrosscheckError("找不到 codex 執行檔（PATH 裡沒有 codex），無法仲裁")
        try:
            proc = subprocess.run(
                [codex_bin, "exec", "-s", "read-only", "-c", "model_reasoning_effort=high",
                 "--output-schema", schema_path, "-o", out_path, "-"],
                input=prompt, capture_output=True, text=True, encoding="utf-8",
                timeout=300,
            )
        except subprocess.TimeoutExpired as e:
            raise CrosscheckError(f"Codex 仲裁逾時（300秒）：{episode_id} {divergence['stock_code']}") from e

        if proc.returncode != 0:
            raise CrosscheckError(
                f"Codex 仲裁失敗（returncode={proc.returncode}）：{episode_id} {divergence['stock_code']}\n"
                f"stderr: {proc.stderr[-1000:]}"
            )
        if not os.path.exists(out_path):
            raise CrosscheckError(
                f"Codex 仲裁沒有寫出結果檔：{episode_id} {divergence['stock_code']}\n"
                f"stdout 尾段: {proc.stdout[-1000:]}"
            )
        with open(out_path, encoding="utf-8") as f:
            result = json.load(f)

    for key in ("verdict", "correct_action", "reasoning"):
        if key not in result:
            raise CrosscheckError(f"Codex 仲裁結果缺少 {key} 欄位：{result}")
    return result


# ── signal_review 表 ─────────────────────────────────────────────────────────

def ensure_review_table() -> None:
    """純附加 DDL（CREATE TABLE IF NOT EXISTS），屬章程「自主決策範圍5」已放寬
    的自主範圍，dry-run（用 information_schema 查現況）後直接執行。"""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS signal_review (
                    id              SERIAL PRIMARY KEY,
                    episode_id      TEXT,
                    stock_code      TEXT,
                    gemini_action   TEXT,
                    deepseek_action TEXT,
                    codex_verdict   TEXT,
                    codex_reasoning TEXT,
                    reviewed_at     TIMESTAMP DEFAULT now()
                )
            """)


def save_review(episode_id: str, divergence: dict, codex_result: dict | None) -> None:
    g, d = divergence.get("gemini"), divergence.get("deepseek")
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO signal_review
                    (episode_id, stock_code, gemini_action, deepseek_action,
                     codex_verdict, codex_reasoning)
                VALUES (%s,%s,%s,%s,%s,%s)
            """, (
                episode_id,
                divergence["stock_code"],
                g.get("action") if g else None,
                d.get("action") if d else None,
                codex_result.get("verdict") if codex_result else None,
                codex_result.get("reasoning") if codex_result else None,
            ))


# ── 主流程 ──────────────────────────────────────────────────────────────────

def run_crosscheck(episode_id: str, use_codex: bool = True) -> dict:
    """回傳這集的完整分析結果：{"episode_id", "gemini_signals", "deepseek_signals",
    "deepseek_usage", "divergences": [{"stock_code","type","gemini","deepseek","codex_verdict"}]}

    絕對不對 signals 表做任何寫入——分歧仲裁結果只供人審閱，是否據此修正正式
    訊號是主控session/使用者的決定。
    """
    init_db()
    ensure_review_table()

    transcript = _read_transcript(episode_id)
    gemini_signals = list_signals(episode_id)
    ds_result = call_deepseek(transcript)
    deepseek_signals = ds_result["signals"]
    ds_cost = estimate_deepseek_cost_usd(ds_result["usage"])

    divergences = detect_divergences(gemini_signals, deepseek_signals)

    for div in divergences:
        codex_result = None
        if use_codex:
            try:
                codex_result = call_codex_arbitrate(episode_id, transcript, div)
            except CrosscheckError as e:
                logging.error(f"[{episode_id}] Codex仲裁失敗，記錄分歧但不含仲裁結論：{e}")
        div["codex_result"] = codex_result
        save_review(episode_id, div, codex_result)

    return {
        "episode_id": episode_id,
        "gemini_signals": gemini_signals,
        "deepseek_signals": deepseek_signals,
        "deepseek_usage": ds_result["usage"],
        "deepseek_cost_usd": ds_cost,
        "divergences": divergences,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("episodes", nargs="+", help="集數，如 EP677 EP678")
    parser.add_argument("--no-codex", action="store_true", help="只跑DeepSeek+分歧偵測，不燒Codex額度")
    args = parser.parse_args()

    total_ds_cost = 0.0
    for ep in args.episodes:
        logging.info(f"=== {ep} ===")
        try:
            result = run_crosscheck(ep, use_codex=not args.no_codex)
        except CrosscheckError as e:
            logging.error(f"[{ep}] 失敗：{e}")
            continue
        total_ds_cost += result["deepseek_cost_usd"]
        logging.info(f"[{ep}] Gemini {len(result['gemini_signals'])} 筆 / "
                     f"DeepSeek {len(result['deepseek_signals'])} 筆 / "
                     f"分歧 {len(result['divergences'])} 筆（DeepSeek估計花費 ${result['deepseek_cost_usd']:.4f}）")
        for div in result["divergences"]:
            cr = div.get("codex_result")
            verdict = cr["verdict"] if cr else "（未跑Codex仲裁）"
            logging.info(f"    {div['stock_code']} [{div['type']}] Codex裁定：{verdict}")

    logging.info(f"總計 DeepSeek 估計花費：${total_ds_cost:.4f}")


if __name__ == "__main__":
    main()
