"""獨立轉錄逐字稿來源：格式橋接 + video-transcribe 外部呼叫。

背景：stock-signal 的逐字稿目前唯一來源是第三方網站 whatmkreallysaid.com，若對方停止
更新，我們就永遠拿不到新集數（2026-08-02 索羅門 r3 任務動機）。本模組讓
`D:\\All claude\\300_Projects\\video-transcribe\\transcribe.py`（本地 yt-dlp 下載 +
faster-whisper 轉錄）產出的 .srt 逐字稿，轉換成 analyzer.py / batch.py 能吃的純文字
.md 格式（比照 transcripts/EP99_焦慮bad.md 這類既有檔案：純文字段落、無時間軸、無
metadata header），作為第二條逐字稿來源的地基。

範圍界線（任務檔第 3 節）：只能把 video-transcribe 的 transcribe.py 當外部 CLI 呼叫
（subprocess），不 import 該專案任何模組、不編輯該專案任何檔案。轉錄的中間產物
（下載的影片、.srt/.ass/.mkv）一律輸出到 stock-signal 自己的 media_work/ 底下
（用 --output-root 導向），不寫進 video-transcribe/media/。

⚠️ 2026-08-15：中間產物的位置從 transcripts_data/independent_media/ 搬到 media_work/
——原位置在部署腳本 `cp -r transcripts_data _site/` 的整包複製路徑上，等於讓下載回來
的影音檔走在通往公開網站的輸送帶上。詳見 INDEPENDENT_MEDIA_ROOT 的註解。
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
VIDEO_TRANSCRIBE_DIR = Path(r"D:\All claude\300_Projects\video-transcribe")
TRANSCRIBE_SCRIPT = VIDEO_TRANSCRIBE_DIR / "transcribe.py"

TRANSCRIPTS_DIR = HERE / "transcripts"
# 獨立轉錄的中間產物（下載的影片、.srt/.ass/.mkv）：不寫進 video-transcribe/media/，
# 維持「只能動 stock-signal 目錄底下」的範圍界線。
#
# 🔴 2026-08-15 搬家（原本是 transcripts_data/independent_media/）：
# 部署腳本有一行 `cp -r transcripts_data _site/transcripts_data`——**整包複製**。
# 把影音中間產物放在 transcripts_data/ 底下，等於讓「下載回來的影片與聲音檔」
# 走在通往公開網站的同一條輸送帶上。兩件事單獨看都合理，湊在一起就是外洩路徑。
# 目前 CI 跑在 GitHub runner、transcripts_data/ 是重新生成的，所以還沒真的漏過；
# 但丹尼爾 2026-08-15 定案的做法正是「本機當執行機、把結果推上去」，改成從本機
# 發佈的那一刻這條路就會通。
# 搬到 media_work/（不在任何會被複製進 _site 的目錄底下）。**這只是第一道**，
# 第二道是 check_site_payload.py 的白名單出門檢查——搬家防的是「這一個」錯誤，
# 白名單防的是「下一個我還沒想到的」。
INDEPENDENT_MEDIA_ROOT = HERE / "media_work"

#: 舊位置。**只讀不寫**：既有的 EP681 等中間產物還在那裡（self_improvement_試做/
#: 底下的三支試做腳本仍指向它），搬家不動既有檔案——移動使用者的資料是使用者的決定，
#: 不是我的。新產出一律進上面的新位置。
LEGACY_MEDIA_ROOT = HERE / "transcripts_data" / "independent_media"

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


# ---------------------------------------------------------------- 文字正規化

#: 產稿階段的異體字正規化對照表。目前只有一條：「臺」→「台」。
#:
#: 為什麼需要：ASR 本身輸出的就是「台」——實測 EP681~EP684、EP687 五份
#: `source.raw.srt`（Whisper 原始輸出），「臺」出現 0 次、「台」共 106 次。是
#: video-transcribe 的 OpenCC `s2twp` 把「台」當簡體字轉成「臺」（該專案
#: transcribe.py 自己的註解也寫了這件事），繁化後的 `source.srt` 才變成清一色的
#: 「臺灣／臺股／臺積電」。下游閱讀與引用比對一律用「台」，所以在產稿這一步轉回來。
#:
#: 為什麼修在這裡而不是修 OpenCC 那一步：本模組的範圍界線是「不編輯 video-transcribe
#: 任何檔案」（見檔頭），而且那一步是所有使用者共用的繁化階段，改了副作用跨專案。
#: 2026-08-26 丹尼爾裁決：只改 stock-signal 的產稿階段。
#:
#: ⚠️ **刻意不做例外白名單（取捨，下一個維護者請先讀這段）**：本專案查無任何既有的
#: 專有名詞白名單機制，這裡也不自行發明一份。代價是**正式名稱會被一併轉掉**——
#: 「臺灣銀行」→「台灣銀行」、「國立臺灣大學」→「國立台灣大學」、「臺灣證券交易所」
#: 亦同。在口語逐字稿的情境可接受（節目本來就唸「台」，且 ASR 原始輸出也是「台」），
#: 但若日後出現「必須保留正式名稱原字」的需求，正確做法是在這張表旁邊加白名單，
#: 不是回頭改下游。
TRANSCRIPT_CHAR_NORMALIZATION = {"臺": "台"}


def normalize_transcript_text(text: str) -> str:
    """把產稿輸出的異體字統一成下游慣用寫法（目前只做「臺」→「台」）。

    只做字元層級的等長取代：不碰標點、不做簡繁轉換、不增刪任何字，維持本模組既有的
    忠實度原則（見 cues_to_paragraphs()：不插入原文沒有的字元）。
    """
    for src_ch, dst_ch in TRANSCRIPT_CHAR_NORMALIZATION.items():
        text = text.replace(src_ch, dst_ch)
    return text


# ---------------------------------------------------------------- 標點復原（選用，可關）
#
# 背景：faster-whisper 對中文口語幾乎只產生逗號，不產生句號/問號，獨立轉錄出來的段落
# 讀起來比 whatmkreallysaid.com 版本生硬。這裡把 self_improvement_試做/
# trial1_punctuation_restore.py 的可行性試做（本機 Ollama qwen2.5:14b-instruct，
# video-transcribe 本來就用它做翻譯，零花費）併進生產線，接在 cues_to_paragraphs() 之後、
# normalize_transcript_text() 之前，逐段落呼叫。
#
# 三個設計要求（2026-09-03 任務書）都在這裡落地：
#   ①可關：環境變數 STOCK_SIGNAL_PUNCT_RESTORE=off（或 0/false/no）一鍵關掉，預設開；
#     另外開放函式參數 restore_punctuation 給程式化呼叫端（含測試）覆寫。
#   ②Ollama 連不上/逾時就退回原文，不准讓整條產稿流程掛掉：_call_ollama_for_punctuation()
#     把所有例外收斂成 PunctuationRestoreUnavailable，restore_paragraph_punctuation() 接住
#     後印 log「標點復原失敗，已退回原文」，回傳原段落文字，呼叫端完全不用處理例外。
#   ③不准改動時間碼、不准增刪任何字：本模組的 .md 輸出從頭到尾就不含時間碼（見
#     build_markdown()），時間碼這件事在格式層級就滿足了；增刪字元則由
#     _is_punctuation_only_change() 做程式化比對——去掉雙方的標點字元後，剩下的字元序列
#     必須完全相同，不同就整段丟棄、退回原文，不是註解，是真的會跑的檢查。


def _punct_restore_env_enabled() -> bool:
    v = os.environ.get("STOCK_SIGNAL_PUNCT_RESTORE", "on").strip().lower()
    return v not in ("off", "0", "false", "no")


#: 本機 Ollama 位置與模型：跟 video-transcribe 翻譯功能共用同一顆常駐模型，零花費、
#: 無次數上限。可用環境變數覆寫（例如指到測試用的假 port，見「退路實測」）。
PUNCT_OLLAMA_HOST = os.environ.get("STOCK_SIGNAL_PUNCT_OLLAMA_HOST", "http://localhost:11434")
PUNCT_MODEL = os.environ.get("STOCK_SIGNAL_PUNCT_MODEL", "qwen2.5:14b-instruct")
PUNCT_TIMEOUT_SECONDS = 120  # 對齊 trial1_punctuation_restore.py 的逾時值

PUNCT_PROMPT_TEMPLATE = """以下是語音辨識(ASR)產出的中文逐字稿片段，幾乎沒有句號，只有零星逗號。
請幫這段文字加上恰當的標點符號（句號、逗號、問號等），**不要改動任何文字內容、
不要增刪字詞、不要意譯**，只加標點與適當分段。直接輸出結果，不要加任何說明。

原文：
{text}"""

#: 判斷「這個字元算不算標點」用的白名單（全形/半形標點 + 空白/換行）。刻意用白名單
#: 而不是黑名單：白名單判斷錯了頂多把某個真標點誤判成內容字元、導致比對失敗、整段被
#: 丟棄退回原文（安全的失敗方向）；黑名單判斷錯了則可能把 LLM 真的改掉的內容字元
#: 誤認成標點而放行，違反硬要求③，方向是危險的。
_PUNCT_CHARS = set(
    "，,。.！!？?；;：:、~～…—-‐‑–－ 　\t\r\n"
    "「」『』（）()《》〈〉“”\"''‘’＂＇·•∙"
)


def _strip_punct(text: str) -> str:
    """去掉所有標點/空白，只留下要比對的字元序列。"""
    return "".join(ch for ch in text if ch not in _PUNCT_CHARS)


def _is_punctuation_only_change(original: str, restored: str) -> bool:
    """硬要求③的實際比對函式：去掉標點後兩邊字元序列必須完全相同。

    不相同代表 LLM 動到了非標點字元（增字/刪字/改字/意譯），這段輸出不可採用。
    這是程式化檢查，不是註解——build_markdown() 真的會呼叫這個函式，沒過就丟棄。
    """
    return _strip_punct(original) == _strip_punct(restored)


class PunctuationRestoreUnavailable(RuntimeError):
    """Ollama 連不上/逾時/回應格式不對。呼叫端一律接住這個例外，退回原文，不中斷主流程。"""


def _call_ollama_for_punctuation(text: str, *, host: str, model: str, timeout: int) -> str:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": PUNCT_PROMPT_TEMPLATE.format(text=text)}],
        "stream": False,
        "options": {"temperature": 0.1},
    }
    req = urllib.request.Request(
        f"{host}/api/chat",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["message"]["content"].strip()
    except Exception as e:  # noqa: BLE001 - 連不上/逾時/JSON壞掉/欄位缺失，任何失敗都要能退回原文
        raise PunctuationRestoreUnavailable(f"{type(e).__name__}: {e}") from e


def restore_paragraph_punctuation(paragraph: str, *, host: str | None = None,
                                   model: str | None = None, timeout: int | None = None) -> str:
    """幫單一段落補標點；任何失敗（連不上/逾時/驗證沒過）都退回原段落文字並印 log，
    絕不讓標點復原失敗中斷產稿流程（硬要求②）。

    host/model/timeout 三個參數只給程式化呼叫端（測試、手動實驗）覆寫用，正常生產路徑
    走 build_markdown()/srt_to_md() 傳下來的預設值即可。
    """
    if not paragraph.strip():
        return paragraph
    host = host or PUNCT_OLLAMA_HOST
    model = model or PUNCT_MODEL
    timeout = timeout or PUNCT_TIMEOUT_SECONDS
    try:
        restored = _call_ollama_for_punctuation(paragraph, host=host, model=model, timeout=timeout)
    except PunctuationRestoreUnavailable as e:
        print(f"[標點復原] 標點復原失敗，已退回原文：{e}", file=sys.stderr)
        return paragraph
    if not restored.strip():
        print("[標點復原] 標點復原失敗（Ollama 回傳空字串），已退回原文", file=sys.stderr)
        return paragraph
    if not _is_punctuation_only_change(paragraph, restored):
        print("[標點復原] 標點復原失敗（去標點後與原文不同，疑似增刪改字），已退回原文",
              file=sys.stderr)
        return paragraph
    return restored


def build_markdown(ep_id: str, title: str, cues: list[tuple[float, float, str]], *,
                    restore_punctuation: bool | None = None,
                    punct_host: str | None = None, punct_model: str | None = None,
                    punct_timeout: int | None = None) -> str:
    """組出符合 transcripts/*.md 既有格式的純文字內容：`# EPxxx 標題` + 段落，用空行分隔。

    刻意不產生 `## 小節標題`——那是 whatmkreallysaid.com 人工/編輯過的主題分節，獨立轉錄
    沒有主題偵測能力，勉強硬套會是假資訊。batch.py 不需要小節結構（見任務檔 DoD 1a 說明：
    只要求 analyzer.py 能正常解析成純文字，不需要格式完全一致）。

    2026-08-26：輸出前會過一次 normalize_transcript_text()（目前是「臺」→「台」），
    標題與內文都算在內。既有的 transcripts/*.md **不回填**，本函式只影響之後新產的稿。

    2026-09-03：段落切好之後、正規化之前，加一道選用的標點復原（見上方區塊）。
    restore_punctuation 為 None 時看環境變數 STOCK_SIGNAL_PUNCT_RESTORE（預設開）；
    傳 True/False 會直接覆寫環境變數，給測試與手動呼叫用。
    """
    paragraphs = cues_to_paragraphs(cues)
    do_restore = _punct_restore_env_enabled() if restore_punctuation is None else restore_punctuation
    if do_restore:
        paragraphs = [
            restore_paragraph_punctuation(p, host=punct_host, model=punct_model, timeout=punct_timeout)
            for p in paragraphs
        ]
    header = f"# {ep_id} {title}".rstrip()
    body = "\n\n".join(paragraphs)
    # 產稿的最後一步：標題與內文一起過異體字正規化（臺→台）。放在收口而不是散在
    # 各處，是為了讓「產稿輸出過哪些正規化」只有一個地方要看。
    return normalize_transcript_text(f"{header}\n\n{body}\n")


def srt_to_md(srt_path: Path, ep_id: str, title: str, *,
              restore_punctuation: bool | None = None,
              punct_host: str | None = None, punct_model: str | None = None,
              punct_timeout: int | None = None) -> str:
    cues = parse_srt(srt_path)
    if not cues:
        raise ValueError(f"從 {srt_path} 解析不出任何字幕 cue，檔案可能是空的或格式不符預期")
    return build_markdown(ep_id, title, cues, restore_punctuation=restore_punctuation,
                           punct_host=punct_host, punct_model=punct_model,
                           punct_timeout=punct_timeout)


# ---------------------------------------------------------------- 呼叫 video-transcribe


class IndependentTranscribeError(RuntimeError):
    pass


def run_independent_transcription(source: str, name: str, *, model: str = DEFAULT_MODEL,
                                   lang: str = "zh",
                                   timeout: int = DEFAULT_TIMEOUT_SECONDS,
                                   asr_guard: bool | str = False,
                                   hotwords_file: str | Path | None = None,
                                   prefer_raw_srt: bool = False) -> Path:
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

    2026-08-24 新增三個旗標，**全部預設關閉、不加就跟改動之前一模一樣**：
      asr_guard=True/"on"/"lite"
                          → 加 `--asr-guard <模式>`，把 condition_on_previous_text 關掉，
                            斷開「同一集裡某個專有名詞聽錯一次、被當上下文餵給下一窗、
                            整集跟著錯」的傳染鏈（EP684 的「力積電」5 次全錯就是這樣滾出來的）。
      hotwords_file=路徑  → 加 `--hotwords-file`，把常出現的公司名灌進每個解碼窗的 prompt。
                            這是解碼期引導，不是事後全域字串取代。
      prefer_raw_srt=True → 回傳 `source.raw.srt`（Whisper 原始輸出）而不是 `source.srt`
                            （OpenCC s2twp 之後）。s2twp 是「簡→繁 ＋ 台灣慣用詞替換」，
                            會把逐字稿裡的「支持」改寫成「支援」這類詞，下游要拿原文引用
                            比對站方版本時就對不上。要原汁原味就開這個。
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
    if asr_guard:
        # True/"on" → 完整 guard；"lite" → 只關跨窗上下文，不做逐字時間對齊與空窗重掃
        # （2026-08-24 EP684 A/B：那兩項才是 8 倍成本的來源，對 podcast 買不到東西）
        guard_mode = asr_guard if isinstance(asr_guard, str) else "on"
        if guard_mode not in ("on", "lite"):
            raise IndependentTranscribeError(
                f"asr_guard 只接受 True / 'on' / 'lite'，收到: {asr_guard!r}")
        cmd += ["--asr-guard", guard_mode]
    if hotwords_file:
        hw = Path(hotwords_file).expanduser()
        if not hw.exists():
            raise IndependentTranscribeError(f"hotwords 檔案不存在: {hw}")
        cmd += ["--hotwords-file", str(hw)]
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

    # prefer_raw_srt=True 時回傳未經 OpenCC s2twp 的原始輸出（見函式說明）。
    srt_name = "source.raw.srt" if prefer_raw_srt else "source.srt"
    for candidate in job_dir_candidates:
        srt_path = candidate / srt_name
        if srt_path.exists():
            return srt_path
    raise IndependentTranscribeError(
        "transcribe.py 回報成功但找不到預期的逐字稿檔案，找過："
        + "、".join(str(c / srt_name) for c in job_dir_candidates)
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
