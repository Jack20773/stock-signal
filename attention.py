"""
「目前節目關注度／方向共識」評分模組（2026-08-02 索羅門新增，任務檔第8節）。

完整背景、Codex 原始分析、定案參數見
100_Todo/projects/2026-08-02_stock-signal報告第二頁-關注度排序計畫.md
（讀該檔「定案補充」段落——4個參數 h/h_g/k/60天下架門檻已由使用者拍板，
不是索羅門自己調校出來的，這裡直接套用，不做任何反向優化）。

核心判斷：這個分數量化「節目近期反覆在談什麼」（討論熱度），不是「建議
強度」——不能直接證明現在值得買賣，使用介面必須明確標示這個定位差異
（見 report_html.py::generate_html_attention() 的首屏警語）。
"""
import json
import logging
import math
import re
from datetime import date
from pathlib import Path

# ── 已拍板定案參數（使用者2026-08-01深夜裁決，h/h_g/60天門檻不可反向優化調整）
H = 21           # 一般衰減半衰期（天）
H_G = 14         # 最後提及防呆項半衰期（天）
DELIST_DAYS = 60  # 下架門檻：超過這麼多天沒被提到，不列入「目前關注」榜單

# K：飽和常數——2026-08-02 索羅門「重大自主決策」，見 SOLOMON_HANDOFF.md /
# 完工報告的 autonomous_decisions 詳細記錄，這裡只留精簡結論：
#
# 原拍板值 K=5 是用「近90天內同標的未衰減原始提及次數」反推的（查到台積電
# 12次、代入 100×(1-e^(-count/5)) 得91%飽和，覺得曲線合理），但正式公式
# 實際餵給 K 的是 A（時間衰減後的加權和），量綱跟校準時的「未衰減次數」
# 不一致——純數學可證：即使每集都提、永遠持續、每次都最高信心的理論上限
# 情境，週更間隔下 A 穩態上限僅約4.85，套 K=5 只能到62%飽和，10天間隔約
# 51%、14天間隔約42%，連校準設想的91%都到不了。套用真實DB資料（935筆
# 訊號/680集），全部標的分數集中在1~7分（滿分100），連討論度最高的台積電
# （97次看多）都只有6.52分——命中任務檔8d.4自訂的「參數明顯不合理」觸發
# 條件。經 Codex challenge-mode 覆核（session 019fbe0b，read-only，2026-08-02）
# 確認判斷成立，建議 K 落在1-2量級（同樣三個時間參數h/h_g/60天不動）。索羅門
# 最終選擇 K=2（Codex建議區間上緣，取整數方便解釋）：驗證後「每週穩定被高
# 信心提及、且今天剛被提到」的標的可達約99%飽和（K=1時）、K=2時約91%
# （對照原始12次校準的目標曲線），比K=5的62%上限更貼近校準原意，同時不像
# K=1那樣過度靈敏（單次提及就衝很高分）。這次真實資料抓到的分數仍普遍偏低
# （最高約12分）是另一個獨立因素：資料庫最新分析集數的實際上架日距抓取當下
# 已有約15-30+天空窗（沒有更近期的已分析集數），h_g=14天防呆項本來就設計成
# 懲罰這種「好一陣子沒提」的情況——這部分是h_g參數原本設計的正常行為，不是
# K失配的一部分，索羅門沒有連帶調整h_g。
K = 2

# confidence_level → q_i 權重映射：任務檔/計畫檔只定義「q_i = confidence_level
# 映射權重」，沒有給具體數值——這是索羅門的判斷（一般分岔點，非任務檔已拍板
# 的4個參數之一）。DB 實際只出現 High/Medium/Low 三種值（2026-08-01 索羅門
# 查證），採用線性遞減：High=1.0（超級看好/超級看壞，語意=講者投資信念強度，
# 見計畫檔定案補充第1點）、Medium=0.6、Low=0.3。未知/缺值時保守給 Medium
# 同等權重，不當作 0（避免資料品質問題讓某檔標的整批訊號憑空消失）。
_CONF_WEIGHT = {"High": 1.0, "Medium": 0.6, "Low": 0.3}
_DEFAULT_WEIGHT = 0.6

# 共識分歧顯示門檻：|consensus| 小於這個值且多空皆有 → 顯示「高度關注但分歧」，
# 不是「無訊號」（任務檔8b明確要求，數值本身是索羅門判斷，非拍板參數）。
_DIVERGENCE_THRESHOLD = 0.15

_EPISODES_PATH = Path(__file__).parent / "episodes.json"
_ep_date_cache: dict[str, str] | None = None


def _load_episode_dates() -> dict[str, str]:
    """沿用 performance.py::_load_episodes() 的模式：讀本地 episodes.json，
    episode_id (EPxxx) -> 上架日 (YYYY-MM-DD)。不用 signals.analysis_date
    （已查證是AI處理當天，不是真實上架日，見計畫檔定案補充第2點）——這條規則
    是任務檔明確拍板的核心設計，讀取失敗時**不能悄悄退回 analysis_date**，
    寧可讓呼叫端拿不到日期而跳過該筆訊號（見 compute_attention() 的
    ep_date is None 分支），也不要用錯誤時間基準算出一個看起來正常、實際
    不可信的分數（2026-08-02 完工前 Codex 覆核抓到：原本的 fallback 設計會
    讓這條核心規則在 episodes.json 讀取失敗或某集查無資料時被悄悄違反且無
    警告，這裡修正）。"""
    global _ep_date_cache
    if _ep_date_cache is not None:
        return _ep_date_cache
    _ep_date_cache = {}
    if not _EPISODES_PATH.exists():
        logging.warning(
            f"[attention] 找不到 {_EPISODES_PATH}，所有訊號都無法計算真實上架日，"
            f"這次「目前關注度」榜單會是空的（不會用 analysis_date 頂替）"
        )
        return _ep_date_cache
    try:
        data = json.loads(_EPISODES_PATH.read_text(encoding="utf-8"))
        _ep_date_cache = {
            f"EP{e['number']}": e["date"]
            for e in data if e.get("date") and e.get("number")
        }
    except Exception as ex:
        logging.warning(
            f"[attention] episodes.json 讀取/解析失敗，所有訊號都無法計算真實上架日："
            f"{ex}（不會用 analysis_date 頂替）"
        )
    return _ep_date_cache


def _ep_num(ep: str) -> int:
    """沿用 report_html.py::_ep_num() 同一套 regex，任務檔8a明確要求不重新發明。"""
    m = re.search(r"\d+", ep or "")
    return int(m.group()) if m else 0


def _episode_date(episode_id: str) -> str | None:
    """回傳 episode_id 對應的真實上架日；episodes.json 裡找不到就回傳 None
    ——**不 fallback 到 analysis_date**，那是任務檔明確禁止的時間基準（見
    上方 _load_episode_dates() 說明）。呼叫端（compute_attention()）據此
    跳過這筆訊號，不用錯誤日期硬湊出一個分數。已知代價：極少數 episode_id
    在 episodes.json 查無資料時（本輪查證是680集裡有679集有完整date+number，
    覆蓋率高但非100%），那幾筆訊號會被排除在關注度計算外，不會讓整檔標的
    消失（除非該標的全部訊號都剛好卡在這極少數集數）。"""
    return _load_episode_dates().get(episode_id)


def _conf_weight(level) -> float:
    return _CONF_WEIGHT.get(level, _DEFAULT_WEIGHT)


def _sat(x: float) -> float:
    """飽和函數 100×(1-e^(-x/k))，Attention 與 U_bull/U_bear 共用同一個形狀
    （計畫檔定案補充：「U_bull/U_bear 用同樣的加權飽和邏輯分別算」）。"""
    return 100 * (1 - math.exp(-x / K))


def compute_attention(signals: list[dict], today: date | None = None) -> list[dict]:
    """signals：database.list_signals() 或等效 dict list，需含 episode_id/
    stock_code/stock_name/action/confidence_level/analysis_date/raw_reason/
    exact_quote 欄位。回傳依 Attention 分數降冪排列的標的清單，已依60天
    下架規則排除 age_last > 60 的標的（歷史頁另外查，這次不做）。"""
    today = today or date.today()

    # 去重規則（計畫檔定案）：(episode_number, stock_code, action) 三元組，
    # 同集同標的同方向只算一次，避免同集重述虛增次數。
    dedup: dict[tuple, dict] = {}
    for s in signals:
        code = s.get("stock_code")
        if not code or code == "Unknown":
            continue
        ep_id  = s.get("episode_id") or ""
        ep_num = _ep_num(ep_id)
        action = s.get("action", "0")
        key = (ep_num, code, action)
        if key in dedup:
            continue

        ep_date_str = _episode_date(ep_id)
        try:
            ep_date = date.fromisoformat(ep_date_str) if ep_date_str else None
        except ValueError:
            ep_date = None
        if ep_date is None:
            continue  # 沒有可用日期就無法算 age，不用猜測值硬湊

        age = (today - ep_date).days
        if age < 0:
            age = 0  # 保險絲：理論上不會有未來日期，防禦負值讓衰減公式爆炸（>1)

        dedup[key] = {**s, "_ep_num": ep_num, "_ep_date": ep_date_str, "_age": age}

    by_code: dict[str, list[dict]] = {}
    for item in dedup.values():
        by_code.setdefault(item["stock_code"], []).append(item)

    results = []
    for code, items in by_code.items():
        name = next((i.get("stock_name") for i in items if i.get("stock_name")), code)

        weighted = [(_conf_weight(i.get("confidence_level")) * (2 ** (-i["_age"] / H)), i)
                    for i in items]
        A = sum(w for w, _ in weighted)

        bull_w = sum(w for w, i in weighted if i.get("action") == "+1")
        bear_w = sum(w for w, i in weighted if i.get("action") == "-1")
        U_bull = _sat(bull_w)
        U_bear = _sat(bear_w)
        consensus = (U_bull - U_bear) / (U_bull + U_bear) if (U_bull + U_bear) > 0 else None

        last_item = min(items, key=lambda i: i["_age"])
        age_last  = last_item["_age"]

        if age_last > DELIST_DAYS:
            continue  # 60天下架規則：只影響是否列入「目前關注」榜單，不刪除資料

        attention = _sat(A) * (2 ** (-age_last / H_G))

        recent_30_eps = sorted({i["_ep_num"] for i in items if i["_age"] <= 30}, reverse=True)

        quote_item = max(
            (i for i in items if (i.get("exact_quote") or "").strip()),
            key=lambda i: i["_ep_num"], default=None,
        )

        bull_n = sum(1 for i in items if i.get("action") == "+1")
        bear_n = sum(1 for i in items if i.get("action") == "-1")

        results.append({
            "code": code,
            "name": name,
            "mkt": "tw" if (code.endswith(".TW") or code.endswith(".TWO")) else "us",
            "attention": round(attention, 2),
            "consensus": round(consensus, 3) if consensus is not None else None,
            "bull_n": bull_n,
            "bear_n": bear_n,
            "neutral_n": sum(1 for i in items if i.get("action") == "0"),
            "total_mentions": len(items),
            "age_last": age_last,
            "last_episode": last_item.get("episode_id", ""),
            "last_date": last_item["_ep_date"],
            "recent_30d_eps": [f"EP{n}" for n in recent_30_eps],
            "quote": (quote_item.get("exact_quote") or "").strip() if quote_item else "",
            "quote_ep": quote_item.get("episode_id", "") if quote_item else "",
            "raw_reason": (last_item.get("raw_reason") or "").strip(),
            "is_divergent": bull_n > 0 and bear_n > 0
                             and consensus is not None and abs(consensus) < _DIVERGENCE_THRESHOLD,
        })

    results.sort(key=lambda r: r["attention"], reverse=True)
    return results


def consensus_label(row: dict) -> tuple[str, str]:
    """回傳 (顯示文字, 顏色)。5次看多5次看空這種情況要老實標成「高度關注但
    分歧」，不能顯示成「無訊號」（任務檔8b明確要求）。"""
    bull_n, bear_n, consensus = row["bull_n"], row["bear_n"], row["consensus"]
    if bull_n == 0 and bear_n == 0:
        return ("中性／無方向", "#999")
    if row["is_divergent"]:
        return (f"高度關注但分歧（{bull_n}次看多／{bear_n}次看空）", "#c77c1f")
    if consensus is not None and consensus > 0:
        return (f"偏多共識（{bull_n}多／{bear_n}空）", "#d9534f")
    return (f"偏空共識（{bull_n}多／{bear_n}空）", "#2b8a3e")
