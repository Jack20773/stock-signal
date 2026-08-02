"""可重用觸發腳本：偵測 YouTube 頻道新集數，自動判斷走「缺口補齊」還是「交叉驗證」，
用獨立轉錄（video-transcribe 本地 yt-dlp + faster-whisper）補上 stock-signal 的逐字稿。

背景見 stock-signal_TASK_2026-08-02_r3.md（1b-1e）。這輪只交手動可執行的工具，
**不設定任何常駐/自動排程**——要不要接 Windows Task Scheduler、多久跑一次，
留給使用者看過這輪成果後再決定。

用法：
  python sync_independent_transcripts.py --check-only     # 只做偵測，列出清單，不下載不轉錄
  python sync_independent_transcripts.py                  # 完整跑一次：偵測 + 缺口補齊 + 最新2集交叉驗證
  python sync_independent_transcripts.py --limit 2         # 這次最多處理幾集（保護，避免不小心觸發大量下載）

三步：
  1. 用 yt-dlp --flat-playlist 取得 YouTube 頻道完整集數清單（EP 編號 -> 影片網址）
  2. 跟本地 transcripts/ 與本地 episodes.json（whatmkreallysaid.com 的鏡像）比對，
     找出「YouTube 有、但本地跟對方都沒有」的集數
  3. 對每個待處理集數：
     - 若跟 YouTube 最新 2 集重疊，且 whatmkreallysaid.com 剛好已經有這集了 → 跑獨立轉錄
       後逐段落比對差異，只記錄不覆蓋既有檔案（寫進 docs/independent_transcript_diffs.md）
     - 否則（對方也還沒有這集，或不是最新 2 集）→ 直接把獨立轉錄結果寫進
       transcripts/EPxxx_*.md（純附加，不覆蓋任何既有檔案），並在
       transcripts_data/independent_transcribe/manifest.json 留下「這是純獨立轉錄來源，
       沒有第二方交叉驗證」的紀錄
"""
import argparse
import difflib
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

import urllib.error

from independent_transcribe import (
    run_independent_transcription, srt_to_md, safe_filename, atomic_write_text,
    TRANSCRIPTS_DIR, IndependentTranscribeError,
)

HERE = Path(__file__).parent
CHANNEL_URL = "https://www.youtube.com/@Gooaye/videos"
EPISODES_LOCAL = HERE / "episodes.json"
MANIFEST_DIR = HERE / "transcripts_data" / "independent_transcribe"
MANIFEST_PATH = MANIFEST_DIR / "manifest.json"
DIFF_REPORT_PATH = HERE / "docs" / "independent_transcript_diffs.md"

EP_TITLE_RE = re.compile(r"^EP\s*0*(\d+)\b")


# ---------------------------------------------------------------- 1b：偵測


def fetch_youtube_episodes(timeout: int = 120) -> dict[int, dict]:
    """用 yt-dlp --flat-playlist 抓頻道完整影片清單，回傳 {EP編號: {video_id, title, url}}。

    抽查驗證（2026-08-02 索羅門實測）：對 683 部影片跑過一次，100% 成功解析出 EP 編號
    （唯一的「無法解析」情況是 EP232 整個不在 YouTube 頻道清單裡，不是解析失敗——這集
    在 whatmkreallysaid.com 上有資料，猜測是後來從 YouTube 下架/設為非公開，不影響本腳本
    運作，episode_map 裡自然就不會有 232 這個 key）。標題格式一律是 "EPxxx | <emoji>"，
    沒有描述性文字（跟任務檔原本假設的「Gooaye 股癌- EP629」格式不同，經實測確認）。
    """
    import subprocess
    cmd = ["yt-dlp", "--flat-playlist", "-J", CHANNEL_URL]
    # 2026-08-02 索羅門修正（Codex 審查指出）：errors="replace" 會把解碼不出來的位元組
    # 靜默換成 U+FFFD，JSON 仍可能解析成功，但欄位內容已經被污染——這裡改成嚴格 UTF-8
    # （不帶 errors=），解碼失敗就整段報錯，不讓壞資料悄悄流進 EP 編號/標題。
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"yt-dlp 取得頻道清單失敗 (exit {proc.returncode}): {proc.stderr[-2000:]}")
    data = json.loads(proc.stdout)
    entries = data.get("entries", [])
    result: dict[int, dict] = {}
    unparsed = []
    for e in entries:
        title = (e.get("title") or "").strip()
        m = EP_TITLE_RE.match(title)
        if not m:
            unparsed.append({"video_id": e.get("id"), "title": title})
            continue
        num = int(m.group(1))
        result[num] = {
            "video_id": e.get("id"),
            "title": title,
            "url": f"https://www.youtube.com/watch?v={e.get('id')}",
        }
    if unparsed:
        print(f"[警告] {len(unparsed)} 部影片標題解析不出 EP 編號，略過：{unparsed[:10]}")
    return result


def load_local_episode_numbers() -> set[int]:
    nums = set()
    for f in TRANSCRIPTS_DIR.glob("EP*.md"):
        m = re.match(r"EP(\d+)", f.stem, re.IGNORECASE)
        if m:
            nums.add(int(m.group(1)))
    return nums


def load_remote_episode_map() -> dict[int, dict]:
    """讀本地 episodes.json（download_transcripts.py 從 whatmkreallysaid.com 鏡像下來的清單）。

    這個檔案的權威來源是遠端網站，本腳本只讀不寫——寫入會在下次 download_transcripts.py
    整份覆蓋重抓時被蓋掉，語意上也不該由本腳本假造遠端網站沒有的資料。
    """
    if not EPISODES_LOCAL.exists():
        print("[警告] episodes.json 不存在，視為遠端清單為空（建議先跑一次 download_transcripts.py）")
        return {}
    data = json.loads(EPISODES_LOCAL.read_text(encoding="utf-8"))
    return {e["number"]: e for e in data if isinstance(e.get("number"), int)}


def detect_gap_episodes(yt_map: dict[int, dict], local_nums: set[int],
                         remote_map: dict[int, dict]) -> list[int]:
    """找出「YouTube 有、但本地跟 whatmkreallysaid.com 都沒有」的集數，由小到大排序。"""
    remote_nums = set(remote_map.keys())
    gaps = sorted(n for n in yt_map if n not in local_nums and n not in remote_nums)
    return gaps


def detect_duplicate_episode_files() -> dict[int, list[str]]:
    """掃 transcripts/ 找出同一個 EP 編號對到 2 個以上檔案的情況，回傳 {EP編號: [檔名,...]}。

    2026-08-02 索羅門新增（完工前 Codex 獨立審查指出最重要的相容性風險）：如果獨立轉錄
    寫入的 `EPxxx_我的標題.md` 之後，whatmkreallysaid.com 又補上同一集，
    `download_transcripts.py` 是依「完整檔名」判斷是否已下載（不是依 EP 號），通常會
    另外寫一份 `EPxxx_對方的標題.md`——這樣 transcripts/ 就會有同一集兩個檔案。
    `batch.py::load_transcripts()` 用 glob 抓全部 `EP*.md`，兩份都會被讀到、都映射成
    同一個 `episode_id`；哪一份先被分析、寫進 `episode_analysis` 表，另一份就會因為
    「已分析」被永久跳過——分析結果會卡在先分析到的那個版本，即使後來 whatmkreallysaid.com
    版本品質更好也不會被拿去重新分析。這是這一輪機制無法在不動 batch.py 核心邏輯（任務
    範圍明確排除）的前提下完全解決的問題，只能做偵測+警告，讓使用者知道要處理，
    詳見完工報告「殘餘風險」。
    """
    by_ep: dict[int, list[str]] = {}
    for f in TRANSCRIPTS_DIR.glob("EP*.md"):
        m = re.match(r"EP(\d+)", f.stem, re.IGNORECASE)
        if m:
            by_ep.setdefault(int(m.group(1)), []).append(f.name)
    return {ep: names for ep, names in by_ep.items() if len(names) > 1}


# ---------------------------------------------------------------- 標題產生


def _title_from_description(video_id: str, timeout: int = 30) -> str:
    """獨立轉錄的來源影片標題本身沒有描述性文字（一律是「EPxxx | emoji」），
    改抓 YouTube 影片描述的第一行當展示標題，比照 whatmkreallysaid.com 用主題短句
    當檔名的既有慣例。抓不到就退回「獨立轉錄」，不讓整個流程因為這個裝飾性資訊卡住。

    2026-08-02 索羅門修正一個實測踩到的編碼 bug：原本用 `yt-dlp --print "%(description)s"`
    抓純文字，`subprocess.run(text=True, encoding="utf-8")` 在這台 Windows 機器上解出來的
    是亂碼（yt-dlp 的 `--print` 純文字輸出實際上是照本機主控台編碼 cp950 寫出，不是
    UTF-8，強制用 utf-8 解碼等於把 cp950 位元組誤讀，產生無法復原的亂碼字元，不是單純
    的顯示問題——已實測跑出 4 個檔名/標題被寫壞的檔案，見 SOLOMON_HANDOFF.md）。改用
    `-J`（JSON dump）：JSON 輸出的編碼是定義明確的 UTF-8，不受主控台編碼影響，跟本模組
    抓頻道清單（fetch_youtube_episodes()）用的是同一種可靠做法。

    2026-08-02 索羅門修正（Codex 審查指出）：這裡故意保留嚴格 UTF-8 解碼（不帶
    errors="replace"）——跟 fetch_youtube_episodes() 同一個理由，解碼失敗就當標題抓取
    失敗（回退到「獨立轉錄」），不讓亂碼字元悄悄寫進檔名。這個函式本身允許失敗退化
    （裝飾性資訊），跟前者「失敗就整段報錯」的處理不同，是因為這裡影響範圍只是檔名
    好不好看，不影響資料正確性。
    """
    import subprocess
    try:
        proc = subprocess.run(
            ["yt-dlp", "--skip-download", "-J",
             f"https://www.youtube.com/watch?v={video_id}"],
            capture_output=True, text=True, encoding="utf-8", timeout=timeout)
        if proc.returncode != 0:
            return "獨立轉錄"
        data = json.loads(proc.stdout)
        description = (data.get("description") or "").strip()
        first_line = description.splitlines()[0].strip() if description else ""
        first_line = re.sub(r"[\\/:*?\"<>|]", "_", first_line)
        return first_line[:40] or "獨立轉錄"
    except Exception:  # noqa: BLE001 - 裝飾性資訊，任何失敗（含解碼失敗）都退回預設值，不擋主流程
        return "獨立轉錄"


# ---------------------------------------------------------------- manifest / 留痕


def _load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return {"records": []}


def _save_manifest(data: dict):
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_manifest_record(record: dict):
    data = _load_manifest()
    data["records"].append(record)
    _save_manifest(data)


# ---------------------------------------------------------------- 交叉驗證（1d）


class RemoteFetchTransportError(RuntimeError):
    """連線層失敗（逾時/DNS/TLS/5xx等）——跟「這一集真的不存在（404）」是不同性質的問題，
    不能都當「對方沒有」處理，否則暫時性網路故障會被誤判成真缺口，寫出一份獨立轉錄版，
    等網路恢復、whatmkreallysaid.com 其實一直都有這集時，會造成同一集兩個檔案並存
    （2026-08-02 索羅門依 Codex 完工前獨立審查意見修正，原版把所有例外都吞成 None）。"""


def _fetch_remote_md(filename: str, timeout: int = 20) -> str | None:
    """直接向 whatmkreallysaid.com 要單一集的逐字稿內容（不透過本地 transcripts/，
    因為這個情境下本地本來就還沒有這一集）。

    回傳 None 只代表「確認是 404，這一集真的不存在」；其他任何連線層問題（逾時/DNS/
    TLS/5xx/解碼失敗）一律拋出 RemoteFetchTransportError，呼叫端要分開處理，不能把
    「連不上」跟「查證過真的沒有」混為一談。
    """
    url = f"https://whatmkreallysaid.com/episodes/{urllib.parse.quote(filename)}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise RemoteFetchTransportError(f"HTTP {e.code}（非 404，視為暫時性錯誤）: {e}") from e
    except Exception as e:  # noqa: BLE001 - 逾時/DNS/TLS/解碼失敗都算連線層問題
        raise RemoteFetchTransportError(f"{type(e).__name__}: {e}") from e


def compare_paragraphs(remote_text: str, independent_text: str) -> dict:
    """逐段落比對差異。回傳整體相似度 + 差異區塊清單，只記錄不覆蓋任何檔案。

    誠實邊界（2026-08-02 索羅門依 Codex 完工前獨立審查意見補強說明）：
    - 這是**字串對齊層級**的差異候選，不是語意判斷。`difflib.SequenceMatcher` 在段落
      陣列上只會把完全相等的段落當錨點——whatmkreallysaid.com 版有人工主題分節，獨立
      轉錄版是純字數切段，兩者分段方式不同時，即使文字內容幾乎一樣，也可能整篇被判成
      一大塊「replace」，這時「diff_count」與各區塊的「類型」主要反映的是分段方式差異，
      不是內容差異——不能把這個腳本的分類當成「這裡真的漏字/這裡真的省略」的定論。
    - `similarity_ratio` 是對含標題/`##`/空行/標點的原始 markdown 全文算的，這些格式
      字元本身就會拉低分數，不是內容相似度的精確量測，只能當粗略參考。
    - 只回報，不下因果結論；不能輸出「官方省略」這種帶因果意味的字眼（見下方 whatmkreallysaid.com
      不是股癌官方這件事的說明）。
    """
    def paras(text):
        return [p.strip() for p in text.split("\n\n") if p.strip() and not p.strip().startswith("#")]

    remote_paras, indep_paras = paras(remote_text), paras(independent_text)
    overall_ratio = difflib.SequenceMatcher(None, remote_text, independent_text, autojunk=False).ratio()

    sm = difflib.SequenceMatcher(None, remote_paras, indep_paras, autojunk=False)
    diffs = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        remote_chunk = "\n\n".join(remote_paras[i1:i2])
        indep_chunk = "\n\n".join(indep_paras[j1:j2])
        if tag == "delete":
            dtype = ("whatmkreallysaid.com 版有、獨立轉錄沒有（可能是獨立轉錄辨識遺漏，也可能只是"
                     "兩邊段落切法不同、內容其實有對齊到別的區塊，需人工複核，這是字串對齊層級的"
                     "差異候選，不是語意判斷）")
        elif tag == "insert":
            dtype = ("獨立轉錄有、whatmkreallysaid.com 版沒有（可能是對方逐字稿省略贊助口白/開場白，"
                     "也可能是獨立轉錄誤聽多出的內容，也可能只是段落切法不同，需人工複核，這是字串"
                     "對齊層級的差異候選，不是語意判斷）")
        else:
            dtype = ("兩邊都有但內容不同（可能是實質差異，也可能只是措辭/斷句不同或段落切法不同，"
                     "需人工複核，這是字串對齊層級的差異候選，不是語意判斷）")
        diffs.append({"type": dtype,
                       "remote_excerpt": remote_chunk[:200],
                       "independent_excerpt": indep_chunk[:200]})
    return {"similarity_ratio": round(overall_ratio, 4), "diff_count": len(diffs), "diffs": diffs}


def _md_code_safe(text: str) -> str:
    """把要塞進 Markdown inline code（反引號包住）的片段做最小清理：反引號跟換行
    都會讓 inline code 語法壞掉，換成全形反引號/空格分隔，不影響閱讀。"""
    return text.replace("`", "｀").replace("\n", " ")


def _append_diff_report(ep_id: str, comparison: dict, remote_filename: str):
    DIFF_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    is_new = not DIFF_REPORT_PATH.exists()
    with DIFF_REPORT_PATH.open("a", encoding="utf-8") as f:
        if is_new:
            f.write("# 獨立轉錄 vs whatmkreallysaid.com 交叉驗證差異紀錄\n\n"
                     "純附加紀錄，只記錄差異，不覆蓋任何既有 .md 檔案內容。\n"
                     "由 `sync_independent_transcripts.py` 自動產生。\n\n"
                     "**用詞說明**：whatmkreallysaid.com 是第三方粉絲網站，不是股癌節目"
                     "官方逐字稿來源，下面一律稱「whatmkreallysaid.com 版」，不稱「官方版」。\n\n"
                     "**方法論說明**：差異是字串對齊層級的候選，不是語意判斷，見\n"
                     "`compare_paragraphs()` 的 docstring；下面每筆差異都需要人工複核，"
                     "不能直接當結論引用。\n\n---\n\n")
        f.write(f"## {ep_id}（比對時間 {datetime.now(timezone.utc).isoformat()}）\n\n")
        f.write(f"- whatmkreallysaid.com 版逐字稿檔名：`{remote_filename}`\n")
        f.write(f"- 整體字元相似度（粗略參考，見方法論說明）：{comparison['similarity_ratio']:.2%}\n")
        f.write(f"- 差異區塊數：{comparison['diff_count']}\n\n")
        for i, d in enumerate(comparison["diffs"], 1):
            f.write(f"### 差異 {i}：{d['type']}\n\n")
            f.write(f"- whatmkreallysaid.com 版片段：`{_md_code_safe(d['remote_excerpt'])}`\n")
            f.write(f"- 獨立轉錄版片段：`{_md_code_safe(d['independent_excerpt'])}`\n\n")
        f.write("---\n\n")


# ---------------------------------------------------------------- 主流程


def _cross_validated_path(ep_id: str) -> Path:
    return MANIFEST_DIR / "cross_validated_raw" / f"{ep_id}_independent.md"


def process_episode(ep_num: int, yt_info: dict, remote_map: dict[int, dict],
                     latest_2: set[int]) -> str:
    """處理單一集數，回傳狀態字串（OK / SKIP / FAIL），log 風格比照 download_transcripts.py。"""
    ep_id = f"EP{ep_num}"
    prefix = f"[{ep_num:>4}]"

    existing = list(TRANSCRIPTS_DIR.glob(f"{ep_id}_*.md")) + list(TRANSCRIPTS_DIR.glob(f"{ep_id}.md"))
    if existing:
        print(f"{prefix} SKIP   {ep_id}（transcripts/ 已有檔案 {existing[0].name}）")
        return "SKIP"

    # 2026-08-02 索羅門新增（Codex 審查指出交叉驗證分支原本不可重複執行：驗證完不寫
    # transcripts/，下次重跑會重新下載+轉錄+重複寫入差異報告，浪費時間與 GPU）。
    # 用「已經寫過查核用副本」當交叉驗證的 SKIP 判準。
    if _cross_validated_path(ep_id).exists():
        print(f"{prefix} SKIP   {ep_id}（先前已完成交叉驗證，查核副本在 "
              f"{_cross_validated_path(ep_id).relative_to(HERE)}）")
        return "SKIP"

    remote_entry = remote_map.get(ep_num)
    do_cross_validate = ep_num in latest_2 and remote_entry is not None

    video_id = yt_info["video_id"]
    try:
        srt_path = run_independent_transcription(yt_info["url"], name=ep_id)
    except IndependentTranscribeError as e:
        print(f"{prefix} FAIL   {ep_id}  獨立轉錄失敗：{e}")
        return "FAIL"

    title = _title_from_description(video_id)
    try:
        md_text = srt_to_md(srt_path, ep_id, title)
    except ValueError as e:
        print(f"{prefix} FAIL   {ep_id}  格式轉換失敗：{e}")
        return "FAIL"

    if do_cross_validate:
        remote_filename = remote_entry["filename"]
        try:
            remote_text = _fetch_remote_md(remote_filename)
        except RemoteFetchTransportError as e:
            # 2026-08-02 索羅門新增（Codex 審查指出原版把連線失敗也當「對方沒有」，
            # 會讓暫時性網路故障誤判成真缺口、寫出獨立版，之後跟 whatmkreallysaid.com
            # 補上的版本同集雙檔衝突）。連線層問題一律當這集這輪處理不了，不猜測、
            # 不降級成缺口補齊，轉錄結果先保留在查核目錄，下次重跑再試一次交叉驗證。
            audit_dir = MANIFEST_DIR / "cross_validated_raw"
            atomic_write_text(audit_dir / f"{ep_id}_independent_pending.md", md_text)
            print(f"{prefix} FAIL   {ep_id}  交叉驗證查詢 whatmkreallysaid.com 失敗（{e}），"
                  f"不假設對方沒有這集，轉錄結果暫存待下次重試，不寫入 transcripts/")
            return "FAIL"
        if remote_text is not None:
            comparison = compare_paragraphs(remote_text, md_text)
            _append_diff_report(ep_id, comparison, remote_filename)
            print(f"{prefix} OK     {ep_id}  交叉驗證完成，相似度 {comparison['similarity_ratio']:.2%}，"
                  f"{comparison['diff_count']} 處差異已寫入 {DIFF_REPORT_PATH.name}"
                  f"（誠實邊界：字串對齊層級候選，不是語意判斷，需人工複核）")
            print(f"{prefix}        whatmkreallysaid.com 版本已存在（{remote_filename}），"
                  f"獨立轉錄結果**不**覆蓋，只留在 transcripts_data/independent_transcribe/ "
                  f"供比對，transcripts/ 維持 whatmkreallysaid.com 版本")
            # 交叉驗證情境下，transcripts/ 保留 whatmkreallysaid.com 版本不覆蓋
            # ——把獨立轉錄結果另存查核用途，並用這個檔案的存在當下次重跑的 SKIP 判準。
            atomic_write_text(_cross_validated_path(ep_id), md_text)
            _append_manifest_record({
                "ep_id": ep_id, "video_id": video_id, "processed_at": datetime.now(timezone.utc).isoformat(),
                "mode": "cross_validated", "written_to_transcripts": False,
                "similarity_ratio": comparison["similarity_ratio"], "diff_count": comparison["diff_count"],
            })
            return "OK"
        else:
            print(f"{prefix}        確認 whatmkreallysaid.com 對 {ep_id} 回應 404（真的還沒有這集），"
                  f"改走缺口補齊流程")
            # 掉回缺口補齊分支，往下走

    # 2026-08-02 索羅門新增（Codex 審查指出原版只在函式開頭檢查一次 existing，
    # 轉錄可能長達 90 分鐘，這段期間若 download_transcripts.py 剛好把
    # whatmkreallysaid.com 版本寫進來，原版會直接覆蓋掉）。寫入前再檢查一次，
    # 大幅縮小競態視窗（從 ~90 分鐘縮到毫秒級，仍非嚴格互斥鎖，但已是低成本的
    # 高性價比防護，完整解法需要跨 process 鎖，這輪範圍不含）。
    existing_now = list(TRANSCRIPTS_DIR.glob(f"{ep_id}_*.md")) + list(TRANSCRIPTS_DIR.glob(f"{ep_id}.md"))
    if existing_now:
        print(f"{prefix} SKIP   {ep_id}（轉錄期間 whatmkreallysaid.com 版本已出現："
              f"{existing_now[0].name}，獨立轉錄結果不寫入，避免同集雙檔）")
        return "SKIP"

    filename = safe_filename(f"{ep_id}_{title}.md")
    out_path = TRANSCRIPTS_DIR / filename
    atomic_write_text(out_path, md_text)
    _append_manifest_record({
        "ep_id": ep_id, "video_id": video_id, "processed_at": datetime.now(timezone.utc).isoformat(),
        "mode": "gap_fill", "written_to_transcripts": True, "path": str(out_path),
        "note": "純獨立轉錄來源，沒有第二方（whatmkreallysaid.com）交叉驗證",
    })
    print(f"{prefix} OK     {ep_id}  獨立轉錄完成 → {out_path.name}"
          f"（{len(md_text):,} 字，純獨立轉錄來源，無第二方交叉驗證）")
    return "OK"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-only", action="store_true", help="只做 1b 偵測，不下載不轉錄")
    parser.add_argument("--limit", type=int, default=0, help="這次最多處理幾集（0=不限制）")
    args = parser.parse_args()

    print("=== 步驟 1：抓 YouTube 頻道集數清單 ===")
    yt_map = fetch_youtube_episodes()
    print(f"YouTube 共 {len(yt_map)} 集（EP{min(yt_map)}–EP{max(yt_map)}）")

    local_nums = load_local_episode_numbers()
    remote_map = load_remote_episode_map()
    print(f"本地 transcripts/ 共 {len(local_nums)} 集，本地 episodes.json（鏡像遠端）共 {len(remote_map)} 集")

    duplicates = detect_duplicate_episode_files()
    if duplicates:
        print(f"\n[警告] 發現 {len(duplicates)} 個 EP 編號在 transcripts/ 有多個檔案（可能是獨立轉錄版"
              f"與 whatmkreallysaid.com 版並存，batch.py 只會分析其中一份、另一份被永久跳過，"
              f"見 detect_duplicate_episode_files() docstring）：")
        for ep, names in sorted(duplicates.items()):
            print(f"  EP{ep}: {names}")

    gaps = detect_gap_episodes(yt_map, local_nums, remote_map)
    print(f"\n=== 步驟 2：三方比對結果 ===")
    if gaps:
        print(f"YouTube 有、但本地與 whatmkreallysaid.com 都沒有的集數（共 {len(gaps)} 集）：{gaps}")
    else:
        print("沒有發現任何缺口（YouTube 上的集數本地或對方至少有一邊已經涵蓋）")

    latest_2 = set(sorted(yt_map.keys())[-2:]) if len(yt_map) >= 2 else set(yt_map.keys())
    print(f"YouTube 最新 2 集：{sorted(latest_2)}（交叉驗證對象，若對方還沒有資料則併入缺口補齊）")

    if args.check_only:
        print("\n--check-only：只做偵測，不下載不轉錄。")
        return

    # 2026-08-02 索羅門修正（Codex 審查指出 --limit 原本用 sorted() 由小到大截斷，
    # `--limit 2` 會先處理編號最小的兩集，不是任務明確指定優先要處理的「最新 2 集」）。
    # 改成最新 2 集優先排在前面，其餘缺口依編號由小到大排在後面，--limit 截斷時才會
    # 真的先做到使用者最在意的最新內容。
    remaining_gaps = sorted(n for n in gaps if n not in latest_2)
    targets = sorted(latest_2, reverse=True) + remaining_gaps
    if args.limit > 0:
        targets = targets[:args.limit]

    print(f"\n=== 步驟 3：處理 {len(targets)} 集 ===")
    ok = skip = fail = 0
    for ep_num in targets:
        if ep_num not in yt_map:
            continue
        status = process_episode(ep_num, yt_map[ep_num], remote_map, latest_2)
        if status == "OK":
            ok += 1
        elif status == "SKIP":
            skip += 1
        else:
            fail += 1

    print(f"\nDone. OK={ok} SKIP={skip} FAIL={fail}")


if __name__ == "__main__":
    main()
