"""獨立轉錄逐字稿來源：格式橋接 + video-transcribe 外部呼叫。

背景：stock-signal 的逐字稿目前唯一來源是第三方網站 whatmkreallysaid.com，若對方停止
更新，我們就永遠拿不到新集數（2026-08-02 索羅門 r3 任務動機）。本模組讓
`D:\\All claude\\300_Projects\\video-transcribe\\transcribe.py`（本地 yt-dlp 下載 +
faster-whisper 轉錄）產出的 .srt 逐字稿，轉換成 analyzer.py / batch.py 能吃的純文字
.md 格式（比照 transcripts/EP99_焦慮bad.md 這類既有檔案：純文字段落、無時間軸、無
metadata header），作為第二條逐字稿來源的地基。

範圍界線（任務檔第 3 節）：只能把 video-transcribe 的 transcribe.py 當外部 CLI 呼叫
（subprocess），不 import 該專案任何模組、不編輯該專案任何檔案。轉錄的中間產物
（下載的影片、.srt/.ass/.mkv）一律輸出到 stock-signal 自己的
transcripts_data/independent_media/ 底下（用 --output-root 導向），不寫進
video-transcribe/media/。
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
VIDEO_TRANSCRIBE_DIR = Path(r"D:\All claude\300_Projects\video-transcribe")
TRANSCRIBE_SCRIPT = VIDEO_TRANSCRIBE_DIR / "transcribe.py"

TRANSCRIPTS_DIR = HERE / "transcripts"
# 獨立轉錄的中間產物（下載的影片、.srt/.ass/.mkv）：不寫進 video-transcribe/media/，
# 維持「只能動 stock-signal 目錄底下」的範圍界線。
INDEPENDENT_MEDIA_ROOT = HERE / "transcripts_data" / "independent_media"

DEFAULT_MODEL = "large-v3-turbo"
DEFAULT_TIMEOUT_SECONDS = 5400  # 90 分鐘：長節目下載+轉錄的保守上限，避免無限期卡住


# ---------------------------------------------------------------- SRT 解析


def _srt_ts_to_seconds(ts: str) -> float:
    h, m, rest = ts.split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def parse_srt(srt_path: Path) -> list[tuple[float, float, str]]:
    """解析 .srt，回傳依原始順序排列的 [(開始秒數, 結束秒數, 文字)]。

    只取每個 block 文字部分的第一行——雙語字幕（--translate auto 時是「原文\\n譯文」）
    會把譯文放第二行，這裡固定只用第一行的原文，不會把可能存在的譯文誤併入逐字稿
    （本模組呼叫 transcribe.py 時固定 --translate off，正常情況下每個 block 只有一行，
    這裡的處理純粹是防禦性寫法，不依賴呼叫端一定守規矩）。
    """
    text = srt_path.read_text(encoding="utf-8")
    cues: list[tuple[float, float, str]] = []
    for block in text.strip().split("\n\n"):
        lines = block.strip("\n").splitlines()
        if len(lines) < 3:
            continue
        ts_line = lines[1]
        if "-->" not in ts_line:
            continue
        start_s, end_s = (p.strip() for p in ts_line.split("-->"))
        try:
            start, end = _srt_ts_to_seconds(start_s), _srt_ts_to_seconds(end_s)
        except ValueError:
            continue
        first_text_line = lines[2].strip() if len(lines) >= 3 else ""
        if first_text_line:
            cues.append((start, end, first_text_line))
    return cues


# ---------------------------------------------------------------- 段落合併


_COMMA_CHARS = ("，", ",")
_GAP_SENTINEL = "\x00"  # 只在函式內部暫用，絕不會出現在最終輸出（split 時就地消耗掉）
_SPLIT_SEARCH_SLACK = 150  # 逗號搜尋視窗：超過 max_len 這麼多字還找不到逗號就放棄找，直接硬切


def _split_by_length(text: str, max_len: int) -> list[str]:
    """把一段連續文字依 max_len 字數上限切成多段，優先在逗號處切，避免硬腰斬句子。

    2026-08-02 索羅門依 Codex 完工前獨立審查（挑戰模式）意見修正：原版往後找逗號
    沒有搜尋範圍上限，遇到一段話很長都沒有逗號時，段落可能被拉到遠超 550 字（Codex
    實測舉例：下一個逗號在 2000 字後，段落就會長達 2000 字，等於字數上限形同虛設）。
    改成明確的搜尋視窗：往後找不超過 max_len + _SPLIT_SEARCH_SLACK 字，找不到才退而
    求其次往前找，兩者都找不到才在門檻處硬切——確保段落長度真的有上界。
    """
    paras = []
    start = 0
    n = len(text)
    while start < n:
        if n - start <= max_len:
            paras.append(text[start:])
            break
        window_end = start + max_len
        search_limit = min(n, window_end + _SPLIT_SEARCH_SLACK)
        idx = -1
        for ch in _COMMA_CHARS:
            p = text.find(ch, window_end, search_limit)
            if p != -1 and (idx == -1 or p < idx):
                idx = p
        if idx == -1:
            for ch in _COMMA_CHARS:
                p = text.rfind(ch, start, window_end)
                if p != -1 and p > idx:
                    idx = p
        if idx == -1:
            idx = window_end - 1  # 真的找不到逗號，硬切避免段落無上界
        paras.append(text[start:idx + 1])
        start = idx + 1
    return [p for p in paras if p.strip()]


def cues_to_paragraphs(cues: list[tuple[float, float, str]],
                        max_para_chars: int = 550,
                        gap_break_seconds: float = 0.8) -> list[str]:
    """把連續的字幕 cue 合併成人類可讀的段落文字。

    為什麼不用「靜音間隔」當主要分段依據：實測 2 小時份的真實 podcast（EP680，1917 筆
    cue），間隔 >= 1 秒的只有 3 筆——Whisper 對這種幾乎不停頓的口語內容，cue 之間的
    間隔本來就趨近 0，純靠間隔偵測段落幾乎起不了作用。改成兩階段：
    1. 先把整份逐字稿接成一條連續文字（cue 之間**直接串接、不插入任何原文沒有的字元**
       ——2026-08-02 索羅門依 Codex 審查意見修正：舊版會在前一個 cue 沒有標點收尾時
       插入逗號，Codex 指出這等於竄改逐字稿內容，Whisper 的 segment 邊界不保證剛好落
       在語意斷點，插入的逗號有可能改變語意，也會誤導下游 Gemini 判讀「一字不漏」的
       exact_quote 欄位。中文不需要空白分詞，直接串接不影響可讀性，只是偶爾兩個分句
       間少一個停頓標點，這是可接受的忠實度換讀起來稍微緊湊一點點的權衡），只在間隔
       >= gap_break_seconds（通常對應廣告口播/話題轉場這類真正的長停頓）的地方強制斷開。
    2. 每一段連續文字再依 max_para_chars 字數門檻，在**最近的逗號處**（而不是要求剛好
       在 cue 邊界上）切成人類讀起來大小合理的段落——實測 Whisper 產出的逗號幾乎不會
       剛好落在 cue 結尾，用「cue 結尾要有標點才斷段」這個舊版寫法幾乎永遠不觸發，
       所以改成允許在段落中段切，找最近的逗號當自然斷點（搜尋視窗見 _split_by_length()）。

    這是格式橋接的 AI 暫定決定（一般分岔點）：不影響 batch.py/analyzer.py 的相容性
    ——它們只把整份檔案當純文字字串餵給 Gemini，不解析段落結構，只影響人類讀起來的
    分段自然度。若門檻不理想之後可直接調整這兩個常數，不需要改呼叫端。

    2026-08-02 索羅門補充更正（自我精進 Part B 試做 2 意外發現，見
    self_improvement_試做/trial2_finer_diff_alignment.py）：任務完工後精確計數
    EP680 真實逐字稿的**逐字內容**（排除 SRT 時間碼本身的逗號分隔符，兩者容易混淆
    ——時間碼格式是 `00:00:04,240`，本身就含逗號，先前分析 `text.count(',')`
    沒排除這個來源，把時間碼的逗號也算進去，誤以為逐字稿內容逗號很多），發現
    1917 筆 cue、約 2 萬字的內容裡**只有 2 個真正的內容逗號**。也就是說上面「找最近
    的逗號當自然斷點」這個策略在實務上幾乎不會被觸發，`_split_by_length()` 絕大多數
    情況下是靠「找不到逗號→硬切在門檻處」這個 fallback 在運作，不是逗號策略在運作
    ——程式行為本身沒有錯（fallback 本來就會保證段落長度有上界），只是先前文件描述
    對「逗號策略是主力」的預期程度有落差，這裡更正說明，避免之後誤判成 bug。
    """
    parts: list[str] = []
    prev_end: float | None = None
    for start, end, text in cues:
        if prev_end is not None and start - prev_end >= gap_break_seconds and parts:
            parts.append(_GAP_SENTINEL)
        parts.append(text)
        prev_end = end
    full_text = "".join(parts)

    paragraphs: list[str] = []
    for forced_chunk in full_text.split(_GAP_SENTINEL):
        paragraphs.extend(_split_by_length(forced_chunk, max_para_chars))
    return paragraphs


def build_markdown(ep_id: str, title: str, cues: list[tuple[float, float, str]]) -> str:
    """組出符合 transcripts/*.md 既有格式的純文字內容：`# EPxxx 標題` + 段落，用空行分隔。

    刻意不產生 `## 小節標題`——那是 whatmkreallysaid.com 人工/編輯過的主題分節，獨立轉錄
    沒有主題偵測能力，勉強硬套會是假資訊。batch.py 不需要小節結構（見任務檔 DoD 1a 說明：
    只要求 analyzer.py 能正常解析成純文字，不需要格式完全一致）。
    """
    paragraphs = cues_to_paragraphs(cues)
    header = f"# {ep_id} {title}".rstrip()
    body = "\n\n".join(paragraphs)
    return f"{header}\n\n{body}\n"


def srt_to_md(srt_path: Path, ep_id: str, title: str) -> str:
    cues = parse_srt(srt_path)
    if not cues:
        raise ValueError(f"從 {srt_path} 解析不出任何字幕 cue，檔案可能是空的或格式不符預期")
    return build_markdown(ep_id, title, cues)


# ---------------------------------------------------------------- 呼叫 video-transcribe


class IndependentTranscribeError(RuntimeError):
    pass


def run_independent_transcription(source: str, name: str, *, model: str = DEFAULT_MODEL,
                                   lang: str = "zh",
                                   timeout: int = DEFAULT_TIMEOUT_SECONDS) -> Path:
    """呼叫 video-transcribe/transcribe.py 做本地下載+轉錄，回傳繁體 .srt 的路徑。

    只把 transcribe.py 當外部 CLI 呼叫（subprocess.run），不 import 該專案任何模組、
    不編輯該專案任何檔案。輸出目錄固定指到 INDEPENDENT_MEDIA_ROOT/<name>，在
    stock-signal 自己的目錄底下。

    2026-08-02 索羅門修正（完工前 Codex 獨立審查挑戰意見）：初版曾經對非零 exit code
    做「source.srt 存在且非空就視為成功」的寬容處理，理由是 video-transcribe 曾有一個
    已知 bug（見 OVERNIGHT_REPORT_2026-07-31.md 第三節：mux_softsub 後的 verify() 對
    某些視訊軌不是從 0 秒開始的來源會把時間碼平移誤判成失敗）。Codex 實際重讀當前版本
    的 transcribe.py::verify()（1534-1626 行左右）指出：**這個 bug 現在已經修好了**
    ——目前的 verify() 已經明確接受「所有字幕筆數的時間碼平移量一致」為通過條件，只有
    平移量不一致或文字/樣式不符才會真的報錯。也就是說，這個寬容處理現在是在繞過一個
    已經不存在的問題，反而會把下載失敗/GPU錯誤/舊工作目錄殘留的過期 source.srt 都誤判
    成「這次成功」——尤其重跑同一個 --name 時，舊的 source.srt 可能還在，這次若下載或
    轉錄真的失敗，會被誤判為成功並回傳一份不是這次產生的舊資料。已移除這個寬容處理，
    改成嚴格要求 exit code 為 0 才算成功；若未來真的又出現類似的封裝驗證步驟誤判，
    應該先去 video-transcribe 那邊確認、修正 verify() 本身，不應該在呼叫端矇混過去。
    """
    if not TRANSCRIBE_SCRIPT.exists():
        raise IndependentTranscribeError(f"找不到 video-transcribe 的 transcribe.py: {TRANSCRIBE_SCRIPT}")

    INDEPENDENT_MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
    # 2026-08-15：video-transcribe 在 760a1c2 之後把工作檔收進 <output-root>/_工作檔/<name>/，
    # 舊版是直接放 <output-root>/<name>/。兩個位置都找，找不到才報錯，這樣跟新舊版
    # video-transcribe 都相容（該專案的輸出配置不歸我們管，只能容納它的兩種擺法）。
    job_dir_candidates = [INDEPENDENT_MEDIA_ROOT / "_工作檔" / name,
                          INDEPENDENT_MEDIA_ROOT / name]
    cmd = [sys.executable, str(TRANSCRIBE_SCRIPT), source,
           "--model", model, "--lang", lang,
           "--name", name, "--output-root", str(INDEPENDENT_MEDIA_ROOT)]
    print(f"[independent_transcribe] 執行: {' '.join(cmd)}", flush=True)
    # 2026-08-15：子程序鏈（transcribe.py → yt-dlp）在 Windows 上預設用 gbk 寫 stdout，
    # 接收端一律以 utf-8 解讀，因此路徑裡的中文會變成 U+FFFD。video-transcribe 在
    # 2026-08-12（commit 760a1c2）把工作目錄改名成中文的 `_工作檔` 之後，yt-dlp 回報的
    # 下載路徑就解不回來，transcribe.py 的 `video.exists()` 判定失敗、整支中止。
    # PYTHONIOENCODING 會被子孫程序一起繼承，是不改動 video-transcribe 的最小修法。
    child_env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=timeout, env=child_env)
    except subprocess.TimeoutExpired as e:
        raise IndependentTranscribeError(
            f"transcribe.py 逾時（超過 {timeout}s），來源: {source}") from e

    if proc.returncode != 0:
        raise IndependentTranscribeError(
            f"transcribe.py 執行失敗 (exit {proc.returncode})，來源: {source}\n"
            f"--- stdout 尾段 ---\n{proc.stdout[-3000:]}\n"
            f"--- stderr 尾段 ---\n{proc.stderr[-2000:]}")

    for candidate in job_dir_candidates:
        srt_path = candidate / "source.srt"
        if srt_path.exists():
            return srt_path
    raise IndependentTranscribeError(
        "transcribe.py 回報成功但找不到預期的逐字稿檔案，找過："
        + "、".join(str(c / "source.srt") for c in job_dir_candidates)
        + f"\nstdout 尾段: {proc.stdout[-2000:]}")


def atomic_write_text(path: Path, text: str):
    """同目錄建立唯一暫存檔 → 寫完關檔 → os.replace 覆蓋目標，避免中途中斷留下半截檔案。

    2026-08-02 索羅門新增（完工前 Codex 獨立審查指出 load_local_episode_numbers() 不檢查
    檔案大小，若寫到一半被中斷，半截檔案會被誤判成「已處理」永久跳過）。比照
    video-transcribe/transcribe.py::_atomic_write_text() 的手法（同檔案系統同目錄才具備
    原子性，Windows 上必須先關檔才能 replace）。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def safe_filename(name: str) -> str:
    """比照 download_transcripts.py::safe_filename()，維持同一套檔名清理規則。"""
    for ch in r'\/:*?"<>|':
        name = name.replace(ch, "_")
    return name
