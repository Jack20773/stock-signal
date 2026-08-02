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
import re
import subprocess
import sys
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


_TRAILING_PUNCT = ("，", ",", "。", "！", "!", "？", "?", "、", "：", ":")
_COMMA_CHARS = ("，", ",")
_GAP_SENTINEL = "\x00"  # 只在函式內部暫用，絕不會出現在最終輸出（split 時就地消耗掉）


def _split_by_length(text: str, max_len: int) -> list[str]:
    """把一段連續文字依 max_len 字數上限切成多段，優先在逗號處切，避免硬腰斬句子。

    找逗號的順序：先往後找最近的逗號（讓段落不會太短），找不到才往前找
    （這段話真的很長一段都沒有逗號，退而求其次在視窗內找），兩者都找不到才硬切。
    """
    paras = []
    start = 0
    n = len(text)
    while start < n:
        if n - start <= max_len:
            paras.append(text[start:])
            break
        window_end = start + max_len
        idx = -1
        for ch in _COMMA_CHARS:
            p = text.find(ch, window_end)
            if p != -1 and (idx == -1 or p < idx):
                idx = p
        if idx == -1:
            for ch in _COMMA_CHARS:
                p = text.rfind(ch, start, window_end)
                if p != -1 and p > idx:
                    idx = p
        if idx == -1:
            idx = window_end - 1  # 真的找不到逗號，硬切避免無限迴圈
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
    1. 先把整份逐字稿接成一條連續文字，只在間隔 >= gap_break_seconds（通常對應廣告
       口播/話題轉場這類真正的長停頓）的地方強制斷開。
    2. 每一段連續文字再依 max_para_chars 字數門檻，在**最近的逗號處**（而不是要求剛好
       在 cue 邊界上）切成人類讀起來大小合理的段落——實測 Whisper 產出的逗號幾乎不會
       剛好落在 cue 結尾，用「cue 結尾要有標點才斷段」這個舊版寫法幾乎永遠不觸發，
       所以改成允許在段落中段切，找最近的逗號當自然斷點。

    這是格式橋接的 AI 暫定決定（一般分岔點）：不影響 batch.py/analyzer.py 的相容性
    ——它們只把整份檔案當純文字字串餵給 Gemini，不解析段落結構，只影響人類讀起來的
    分段自然度。若門檻不理想之後可直接調整這兩個常數，不需要改呼叫端。
    """
    parts: list[str] = []
    prev_end: float | None = None
    for start, end, text in cues:
        if prev_end is not None and start - prev_end >= gap_break_seconds and parts:
            parts.append(_GAP_SENTINEL)
        elif parts and parts[-1] != _GAP_SENTINEL and not parts[-1].endswith(_TRAILING_PUNCT):
            # 前一個 cue 沒有以標點收尾：插入逗號避免兩句話黏在一起變得難以閱讀
            # （Whisper 對中文口語只會產出逗號，幾乎不產出句號，見模組頂端說明）。
            parts.append("，")
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

    已知既有限制（不是本模組造成，見 video-transcribe/OVERNIGHT_REPORT_2026-07-31.md
    第三節）：mux_softsub 後的 verify() 對某些「視訊軌不是從 0.000 秒開始」的來源
    會把時間碼整體平移誤判成失敗，導致 transcribe.py 進程以非零 exit code 結束，
    即使語音辨識本身（我們唯一需要的部分）已經在 verify() 之前就成功寫檔。這裡的
    處理方式：exit code 非零時，先檢查 source.srt 是否已存在且非空，是的話當作
    「轉錄本身成功，只是我們用不到的封裝驗證步驟失敗」處理，印警告後繼續，不因為
    下游一個我們不需要的驗證步驟擋住整份任務。
    """
    if not TRANSCRIBE_SCRIPT.exists():
        raise IndependentTranscribeError(f"找不到 video-transcribe 的 transcribe.py: {TRANSCRIBE_SCRIPT}")

    INDEPENDENT_MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
    job_dir = INDEPENDENT_MEDIA_ROOT / name
    cmd = [sys.executable, str(TRANSCRIBE_SCRIPT), source,
           "--model", model, "--lang", lang,
           "--name", name, "--output-root", str(INDEPENDENT_MEDIA_ROOT)]
    print(f"[independent_transcribe] 執行: {' '.join(cmd)}", flush=True)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise IndependentTranscribeError(
            f"transcribe.py 逾時（超過 {timeout}s），來源: {source}") from e

    srt_path = job_dir / "source.srt"
    if proc.returncode != 0:
        if srt_path.exists() and srt_path.stat().st_size > 0:
            print(f"[independent_transcribe][警告] transcribe.py exit {proc.returncode}，"
                  f"但 {srt_path} 已存在且非空，視為轉錄本身成功"
                  f"（可能是已知的 mux/verify 時間碼平移誤判，語音辨識不受影響）",
                  file=sys.stderr, flush=True)
            return srt_path
        raise IndependentTranscribeError(
            f"transcribe.py 執行失敗 (exit {proc.returncode})，來源: {source}\n"
            f"--- stdout 尾段 ---\n{proc.stdout[-3000:]}\n"
            f"--- stderr 尾段 ---\n{proc.stderr[-2000:]}")

    if not srt_path.exists():
        raise IndependentTranscribeError(
            f"transcribe.py 回報成功但找不到預期的逐字稿檔案: {srt_path}\n"
            f"stdout 尾段: {proc.stdout[-2000:]}")
    return srt_path


def safe_filename(name: str) -> str:
    """比照 download_transcripts.py::safe_filename()，維持同一套檔名清理規則。"""
    for ch in r'\/:*?"<>|':
        name = name.replace(ch, "_")
    return name
