# -*- coding: utf-8 -*-
"""出門檢查：`_site/` 要被公開發佈之前，逐檔比對白名單，有名單外的東西就中止部署。

## 為什麼需要這個（2026-08-15，丹尼爾裁決後新增）

`stock-signal` 是 **public repo ＋ public GitHub Pages**。部署腳本裡有一行
`cp -r transcripts_data _site/transcripts_data`——**整包複製**。而
`independent_transcribe.py` 的中間產物（yt-dlp 下載回來的影音檔、.srt/.mkv）原本就
落在 `transcripts_data/independent_media/` 底下。

**兩件事單獨看都合理，湊在一起就是「下載回來的影音檔會被公開上網」。**

目前 CI 跑在 GitHub runner 上、`transcripts_data/` 是 gitignore 的衍生產物，所以那個
目錄在 CI 裡是重新生成的、不含影音——**這個洞今天還沒真的漏過**。但丹尼爾 2026-08-15
定案的新做法正是「**本機當執行機**、把結果推上去」，一旦改成從本機發佈，那一行
`cp -r` 就會把整包影音一起帶出門。

**寫成白名單而不是黑名單**是刻意的：黑名單要求「我事先想得到所有不該出門的東西」，
而這次的洞恰恰來自「沒想到那個資料夾底下會多出東西」。白名單的失敗模式是「擋到不
該擋的」（部署失敗、有人來看），黑名單的失敗模式是「放行不該放的」（悄悄公開、沒
人知道）。**兩種都會錯，但只有一種錯得無聲。**

## 白名單怎麼改

改 `ALLOWED` 就好。**每一條都要寫理由**——一條沒有理由的白名單規則，日後沒有人敢
刪，於是白名單會愈長愈鬆，最後等於沒有。

用法：`python -X utf8 check_site_payload.py [_site 目錄]`（預設 `_site`）
不合規就 exit code 1 並列出違規檔案，CI 據此中止部署。
"""
from __future__ import annotations

import sys
from pathlib import Path

#: (glob 樣式, 為什麼這個東西可以公開)
ALLOWED = [
    ("index.html", "報告主頁，本專案的公開產出"),
    ("attention.html", "關注度頁"),
    ("transcripts.html", "逐字稿瀏覽頁（頁面本身只含集數 metadata）"),
    ("transcripts_data/*.txt", "逐字稿純文字全文——丹尼爾 2026-08-15 明確裁決維持公開"),
]

#: 就算副檔名對，這些也一律不准出門（第二層，防「.txt 裡塞了不該有的東西」的粗略
#: 情況；主要防線仍是上面的白名單）。
FORBIDDEN_NAME_PARTS = (".env", "backup", "credential", "secret", "token", ".db")

#: 單檔大小上限：逐字稿純文字最大約 100 KB。影音檔一定超過，**就算哪天有人把
#: 影音檔改名成 .txt 也擋得住**——這一條的存在理由就是「不依賴副檔名說實話」。
MAX_FILE_BYTES = 2 * 1024 * 1024


def check(site_dir: Path) -> list:
    """回傳違規清單 [(相對路徑, 原因)]；空清單＝可以出門。"""
    if not site_dir.is_dir():
        return [(str(site_dir), "站台目錄不存在——部署前必須先建好，不確定的狀態不放行")]

    violations = []
    files = [p for p in site_dir.rglob("*") if p.is_file()]
    if not files:
        return [(str(site_dir), "站台目錄是空的——空站台八成是前面某一步失敗了，不放行")]

    for path in sorted(files):
        rel = path.relative_to(site_dir).as_posix()
        if not any(Path(rel).match(pattern) for pattern, _why in ALLOWED):
            violations.append((rel, "不在白名單內"))
            continue
        lowered = rel.lower()
        hit = next((w for w in FORBIDDEN_NAME_PARTS if w in lowered), None)
        if hit:
            violations.append((rel, f"檔名含禁止字樣 {hit!r}"))
            continue
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            violations.append(
                (rel, f"{size:,} bytes 超過單檔上限 {MAX_FILE_BYTES:,}"
                      f"（影音檔就算改名成 .txt 也會卡在這裡）")
            )
    return violations


def main() -> int:
    site_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "_site")
    violations = check(site_dir)
    if not violations:
        n = sum(1 for p in site_dir.rglob("*") if p.is_file())
        print(f"✅ 出門檢查通過：{n} 個檔案全部在白名單內（{site_dir}）")
        return 0

    print(f"🔴 出門檢查不通過——{len(violations)} 個檔案不該被公開，部署中止：")
    for rel, why in violations[:50]:
        print(f"   - {rel}  ← {why}")
    if len(violations) > 50:
        print(f"   …另外還有 {len(violations) - 50} 個")
    print()
    print("白名單（改 check_site_payload.py 的 ALLOWED）：")
    for pattern, why in ALLOWED:
        print(f"   {pattern:<28} {why}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
