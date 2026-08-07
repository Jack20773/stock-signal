# stock-signal 備份體檢報告　2026-08-08

> 執行者：Claude Opus 5（主控 session）　驗證環境：Neon `neondb`，Claude Code 2.1.211
> 觸發：計畫看板 `db-backup-gap`（priority: next）
> ⚠️ 本報告尚未併入 `000_Agent/001_memory/project_stocksignal.md` 與計畫看板——
> 當時另一個 session（索羅門六小時任務）正在寫 `000_Agent/`，為避免撞檔而暫存於此。**收工時要補。**

---

## 一句話結論

備份腳本本身是活的，但**還原路徑是壞的**——照現況還原出來的資料庫，第一次正常寫入就會爆。
而且從 2026-08-01 起，整個工作區沒有任何異地備份。

---

## 一、實測結果（全部為實跑，非推論）

| 測項 | 方法 | 結果 |
|---|---|---|
| `backup_db.py` 在 Neon 遷移後可用？ | 實際執行 | ✅ 6 表全 dump，1,347,770 bytes |
| dump 是否可重現 | sha256 比對 8/7 與 8/8 兩份 | ✅ 完全相同（期間 DB 無異動，合理） |
| `restore_db.py` 還原路徑 | `--dry-run` | ✅ 6 表 SQL 正確；外鍵數 0，還原順序無所謂 |
| Schema DDL 有沒有備份 | grep 版控檔案 | ✅ 6 張表全在版控：`database.py`（5 張）＋ `crosscheck.py`（`signal_review`） |
| **sequence 是否會被重設** | **TEMP 表實測** | 🔴 **不會 → 還原後第一次寫入必爆** |

### sequence 缺陷的實測證據

```
還原後 sequence 停在: 1 （資料已有 id 1~3）
結果: 失敗 -> UniqueViolation duplicate key value violates unique constraint "seqtest_pkey"
```

用 `CREATE TEMP TABLE`（session 結束即消失、不進 schema、不碰現有資料）模擬
「帶明確 id 值 INSERT」→「系統之後正常寫入」的完整循環，重現成功。

受影響的表：`signals`、`subscribers`、`signal_review`（三張的 id 都走 `nextval`）。

---

## 二、已知缺陷清單（依使用者 2026-08-08 裁決：**先不修，只記錄**）

| # | 缺陷 | 嚴重度 | 後果 |
|---|---|---|---|
| 1 | `restore_db.py` 不重設 sequence | 🔴 高 | 還原後系統第一次寫入 `UniqueViolation`，服務等於沒救回來 |
| 2 | `ON CONFLICT DO NOTHING` 未指定衝突目標 | 🟡 中 | 還原到非空 DB 時靜默跳過，畫面照印「已還原 N 筆」但實際零筆進去 |
| 3 | 每張表重開一次連線（`restore()` 迴圈內） | 🟢 低 | 大表慢，非致命 |
| 4 | 本機無 `pg_dump` | 🟡 中 | 只能走 JSON 這條路，沒有業界標準的 schema+data 完整 dump |

**修法已寫進 `restore_db.py` 檔頭註解**（含三行 `setval` 指令），災難還原時照著補跑即可。

---

## 三、備份現況

- 本地 `backups/`：只有 **8/7、8/8 兩份**（皆手動觸發），已被 `.gitignore` 正確擋住、未進版控 ✅
- `backup_db.py` / `restore_db.py`：**2026-07-06 起躺在工作區未進版控**，本次已 commit（`bb1f79a`）
- **無任何自動排程**——備份只在有人想到的時候才發生

---

## 四、異地備份現狀（2026-08-08 查證）

| 查核點 | 結果 |
|---|---|
| `ClaudeCloudSyncPush` 排程 | **Disabled** |
| Google Drive 鏡像最新檔案 | **2026-08-01 15:08**，之後零更新 |
| `GoogleDriveFS` 行程 | 執行中（Drive 資料夾本身有在同步到雲端） |

→ **機制沒壞，壞的是「D: → Drive 資料夾」那一段推送被停用**。
Drive 那頭還在忠實同步一個 7 天前就凍結的快照。

🔴 **自 2026-08-01 起，整個工作區沒有異地備份**：又仟案全部產出、計畫看板、
制度改動、hook 合併——只存在 D: 這一顆硬碟上。

### 鏡像上的敏感檔盤點（只檢查檔名／表名／欄名，未讀取任何值）

| 檔案 | 判定 |
|---|---|
| 任何真實 `.env` | ✅ **沒有**（只有 `.env.example`） |
| `003_hooks/_backup_2026-07-16/settings.json` | ✅ 無 `env` 區塊，**無密鑰** |
| `stock-signal/signals.db`、`signals_backup_20260701.db` | ✅ 只有 `signals`／`price_cache`，**無個資** |
| `stock-signal/backups/backup_stocksignal_db_2026-07-06.json` | ⚠️ **5 位訂閱者 email ＋ 退訂 token 明文** |
| `linebot/backups/backup_linebot_db_2026-07-06.json` | ⚠️ 2 位 LINE `user_id` ＋ `display_name`（量小） |

兩份都是 **7/6 的過期快照**，留著沒有備份價值，只有風險。刪除需使用者自己動手（NEVER 規則）。

---

## 五、待使用者裁決

1. **異地備份要不要恢復**——重新啟用 `ClaudeCloudSyncPush`？改別的機制？還是接受單點風險？（優先度高於下一項）
2. 雲端那兩份含個資的過期備份要不要清掉
3. `restore_db.py` 的 sequence 缺陷何時修（目前狀態：**只能看、不能真還原**）
4. 定期自動備份 vs 維持手動

---

## 附：本次未處理

- `migrate_to_neon.py`、`email_subscriber_preview.html` 仍未進版控（使用者裁決先留著不動）
- 記憶檔與計畫看板未更新（避免與索羅門 session 撞檔）
