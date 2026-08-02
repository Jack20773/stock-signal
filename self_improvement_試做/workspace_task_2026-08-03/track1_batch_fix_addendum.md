# Track 1 收尾補充：batch.py 根因修正demo

`dedup_prototype_v2.py` 結尾原本把「batch.py根因修正」列為「這輪故意沒做」的延伸建議
（因為屬於正式檔案，範圍不能碰）。這次補上**具體demo**（不是只寫文字建議）：

- `batch_dedup_selection_prototype.py::load_transcripts_dedup_aware()`——在「挑選哪個
  檔案送進分析」這一步，用manifest.json判斷同EP重複時優先選官方版，不改動檔案系統
  本身（不刪不搬），只改選擇邏輯。
- `batch_dedup_selection_test.py`：5個測試全PASS，含跟正式`transcripts/`目錄
  （684個檔案）交叉比對，確認目前無重複情況下這個邏輯完全不影響現有行為（684=684）。

**建議定位**：這個demo跟Track 1主線的quarantine方案（`dedup_prototype_v2.py`）是
**互補關係**，不是二選一——quarantine解決「目錄不要留兩份檔案」，這個解決「即使
兩份檔案還沒被quarantine掉，分析也不會碰運氣選錯版本」。理想情況兩個都採用：
quarantine定期清理 + batch.py選擇邏輯當最後一道防線。

如果使用者只想採用一個，索羅門建議優先這個（`load_transcripts_dedup_aware`）而不是
quarantine——因為它是non-destructive（不刪不搬任何檔案，風險更低），且直接命中
DeepSeek審查說的「根因」，而quarantine終究只是治標。這是索羅門的建議排序，不是
索羅門自己拍板，兩個demo程式碼都已經在這個資料夾裡，使用者可以自己決定要不要
採用、採用哪一個、或兩個都要。

具體要套用時的改法（人工比對用，不是自動patch）：`batch.py::load_transcripts()`
第71-77行目前是：
```python
def load_transcripts(from_ep: int = 0, last_n: int = 0) -> list[Path]:
    files = sorted(TRANSCRIPTS_DIR.glob("EP*.md"), key=ep_number)
    if from_ep:
        files = [f for f in files if ep_number(f) >= from_ep]
    if last_n:
        files = files[-last_n:]
    return files
```
建議改成呼叫 `load_transcripts_dedup_aware()`（需要額外傳入manifest.json路徑，
`sync_independent_transcripts.py`裡已經有現成的`MANIFEST_PATH`常數可以複用）。
