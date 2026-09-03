# -*- coding: utf-8 -*-
"""ad_guard.py 的測試——第二道業配關卡（確定性關鍵字比對）。

跑法：
    python -X utf8 -m pytest test_ad_guard.py -q
    python -X utf8 test_ad_guard.py --survey    # 拿資料庫真實訊號量誤擋率

四件事一定要驗（對應 2026-09-03 丹尼爾指定的驗收條件）：
  ① 命中關鍵字的訊號被擋，而且有留下紀錄
  ② 沒命中的照常通過
  ③ 母體 0 時輸出是警告，不是「通過」
  ④ 被擋的訊號沒有從資料裡消失

外加一項實測：拿 EP689 那集**真實逐字稿**（就是 2026-08-28 出事的那集），
餵一筆假造的「特斯拉 +1」訊號，證明這道關卡真的會擋下來。
刻意不重新呼叫 Claude 分析那一集——關卡驗的是關卡，不是模型。
"""
import io
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ad_guard
from ad_guard import check_signal, extract_segment, screen_signals

HERE = os.path.dirname(os.path.abspath(__file__))


def _sig(**kw):
    base = {
        "id": 1,
        "episode_id": "EP999",
        "stock_name": "台積電",
        "stock_code": "2330.TW",
        "action": "+1",
        "exact_quote": "",
        "reasoning": "",
        "raw_reason": "",
        "primary_tag": "#產能擴充",
        "secondary_tags": [],
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# ① 命中關鍵字 → 被擋，且有紀錄
# ---------------------------------------------------------------------------
def test_01_keyword_hit_is_blocked_and_recorded(tmp_path):
    log = str(tmp_path / "blocked.jsonl")
    s = _sig(id=101, exact_quote="今天的節目由 Dr. 情趣贊助，誠心推薦特斯拉",
             stock_name="特斯拉", stock_code="TSLA")
    out = screen_signals([s], log_path=log)

    assert out["population"] == 1
    assert len(out["blocked"]) == 1
    assert out["passed"] == []
    assert "贊助" in out["blocked"][0][1]["keywords"]

    # 有留下紀錄，而且紀錄裡看得出是哪個關鍵字
    assert os.path.exists(log)
    rows = [json.loads(l) for l in io.open(log, encoding="utf-8") if l.strip()]
    assert len(rows) == 1
    assert rows[0]["signal_id"] == 101
    assert "贊助" in rows[0]["matched_keywords"]
    assert rows[0]["exact_quote"] == s["exact_quote"]

    # 輸出裡真的印出「擋下 N 筆、命中哪個關鍵字」
    text = "\n".join(out["lines"])
    assert "擋下 1 筆" in text
    assert "贊助" in text
    assert "母體 1 筆" in text


# ---------------------------------------------------------------------------
# ② 沒命中 → 照常通過
# ---------------------------------------------------------------------------
def test_02_clean_signal_passes(tmp_path):
    log = str(tmp_path / "blocked.jsonl")
    s = _sig(id=102,
             exact_quote="台積電下半年產能開出來，我自己是有繼續撿",
             reasoning="產能開出是直接利多，講者明確表示加碼")
    out = screen_signals([s], log_path=log)

    assert out["population"] == 1
    assert out["blocked"] == []
    assert out["passed"] == [s]
    # 沒擋到就不該生出稽核檔（不要用空檔案假裝有在檢查）
    assert not os.path.exists(log)
    assert "擋下 0 筆" in "\n".join(out["lines"])


def test_02b_mixed_batch_only_blocks_the_dirty_one(tmp_path):
    log = str(tmp_path / "blocked.jsonl")
    dirty = _sig(id=201, exact_quote="輸入優惠碼 GOOAYE888 現折三百")
    clean = _sig(id=202, exact_quote="輝達的資料中心需求還在，我續抱")
    out = screen_signals([dirty, clean], log_path=log)

    assert out["population"] == 2
    assert [s["id"] for s in out["passed"]] == [202]
    assert [s.get("id") for s, _ in out["blocked"]] == [201]
    assert "優惠碼" in out["blocked"][0][1]["keywords"]


# ---------------------------------------------------------------------------
# ③ 母體 0 → 警告，不是通過
# ---------------------------------------------------------------------------
def test_03_zero_population_is_a_warning_not_a_pass():
    out = screen_signals([])
    assert out["population"] == 0
    text = "\n".join(out["lines"])
    # 必須明說是母體 0，而且必須明說這不是通過
    assert "母體 0" in text
    assert "不是" in text and "通過" in text
    # 絕對不准出現綠燈
    assert "✅" not in text
    assert "無問題" not in text


def test_03b_disabled_guard_says_so_instead_of_pretending_to_pass(monkeypatch):
    monkeypatch.setattr(ad_guard, "AD_GUARD_ENABLED", False)
    out = screen_signals([_sig(id=301, exact_quote="今天由 X 贊助")])
    assert out["enabled"] is False
    text = "\n".join(out["lines"])
    assert "停用" in text
    assert "✅" not in text
    # 停用時放行是設定造成的，必須講清楚不是檢查通過
    assert "不是檢查通過" in text


# ---------------------------------------------------------------------------
# ④ 被擋的訊號沒有從資料裡消失
# ---------------------------------------------------------------------------
def test_04_blocked_signal_is_not_destroyed(tmp_path):
    log = str(tmp_path / "blocked.jsonl")
    s = _sig(id=401, exact_quote="本集節目由某某贊助播出")
    original = dict(s)
    batch = [s]

    out = screen_signals(batch, log_path=log)

    # a. 傳進去的 list 沒有被就地改動
    assert batch == [s]
    assert len(batch) == 1
    # b. 訊號物件本身沒有被改欄位
    assert s == original
    # c. 被擋的那筆原物件仍拿得到（不是只剩一個 id）
    assert out["blocked"][0][0] is s
    # d. 落檔留存，內容足以人工判讀
    rows = [json.loads(l) for l in io.open(log, encoding="utf-8") if l.strip()]
    assert rows[0]["episode_id"] == s["episode_id"]
    assert rows[0]["stock_code"] == s["stock_code"]
    assert rows[0]["action"] == s["action"]
    assert "untouched" in rows[0]["note"]


def test_04b_audit_log_is_append_only(tmp_path):
    log = str(tmp_path / "blocked.jsonl")
    screen_signals([_sig(id=411, exact_quote="這段是業配")], log_path=log)
    screen_signals([_sig(id=412, exact_quote="這段也是業配")], log_path=log)
    rows = [json.loads(l) for l in io.open(log, encoding="utf-8") if l.strip()]
    assert [r["signal_id"] for r in rows] == [411, 412]  # 第二次沒有蓋掉第一次


# ---------------------------------------------------------------------------
# ⑤ EP689 真實逐字稿實測——2026-08-28 出事的那一集
# ---------------------------------------------------------------------------
EP689_QUOTE = "誠心推薦特斯拉，濕，大大的濕"


def _ep689_transcript():
    t = ad_guard.load_transcript("EP689")
    if t is None:
        pytest.skip(
            "找不到 transcripts/EP689_*.md（該目錄在 .gitignore 裡，CI 上沒有）。"
            "這一項是本機實測，跳過不代表通過。"
        )
    return t


def test_05_ep689_real_transcript_locates_the_sponsor_section():
    t = _ep689_transcript()
    assert EP689_QUOTE in t, "逐字稿內容變了，這個測試的前提不成立"
    seg, how = extract_segment(t, EP689_QUOTE)
    assert how == "window", f"應該切出字元窗，實際 how={how}"
    # 段落開頭要接上所在段落的 Markdown 標題行，`## 贊助` 本身就是最強的線索
    assert seg.lstrip().startswith("## 贊助"), seg[:40]
    assert EP689_QUOTE in seg


def test_05b_ep689_fake_tesla_signal_is_blocked():
    """把 2026-08-28 真正寄出去的那種訊號重建一次，證明這道關卡會擋下來。

    刻意不重新呼叫 Claude 分析 EP689（省訂閱額度，而且要驗的是關卡不是模型）：
    直接餵一筆假造的「特斯拉 +1」，exact_quote 用逐字稿裡真正那一句。
    """
    t = _ep689_transcript()
    fake = _sig(id=985, episode_id="EP689", stock_name="特斯拉",
                stock_code="TSLA", action="+1", exact_quote=EP689_QUOTE,
                reasoning="講者誠心推薦特斯拉，情緒明顯偏多")
    v = check_signal(fake, transcript=t)
    assert v["blocked"] is True
    assert v["keywords"], "應該要命中至少一個關鍵字"
    assert "贊助" in v["keywords"]
    assert v["segment_kind"] == "window"


def test_05c_ep689_real_signal_from_the_same_episode_still_passes():
    """同一集的正常訊號不該被連坐。

    EP689 的真實訊號之一（貿聯，來自 2026-09-03 的實跑輸出），它落在別的段落，
    不該因為這一集有業配段就整集被擋——那樣關卡會被當成壞掉而關掉。
    """
    t = _ep689_transcript()
    quote = "因為在投資貿聯的時候就要去了解每一條 cable"
    if quote not in t:
        pytest.skip("逐字稿內容已變，跳過（跳過不代表通過）")
    ok = _sig(id=986, episode_id="EP689", stock_name="貿聯-KY",
              stock_code="3665.TW", action="0", exact_quote=quote,
              reasoning="以過去研究 cable 產品的經驗說明研究方法論")
    v = check_signal(ok, transcript=t)
    assert v["blocked"] is False, f"誤擋，命中：{v['keywords']}"


# ---------------------------------------------------------------------------
# 誤擋率量測（不是測試，是拿真實資料看這道關卡有多兇）
# ---------------------------------------------------------------------------
def survey():
    from database import list_signals
    rows = list_signals()
    print(f"母體：signals 表 invalid_reason IS NULL 的訊號 {len(rows)} 筆")
    if not rows:
        print("⚠ 母體 0，這次什麼都沒比對到——不是通過。")
        return
    out = screen_signals(rows, record=False)
    blocked = out["blocked"]
    print(f"擋下 {len(blocked)} 筆／{out['population']} 筆 "
          f"= {len(blocked) / out['population'] * 100:.1f}%")
    kinds = {}
    for _s, v in blocked:
        for kw in v["keywords"]:
            kinds[kw] = kinds.get(kw, 0) + 1
    print("命中關鍵字分布：", dict(sorted(kinds.items(), key=lambda x: -x[1])))
    scopes = {}
    for s in rows:
        v = check_signal(s)
        k = v["segment_kind"]
        scopes[k] = scopes.get(k, 0) + 1
    print("檢查範圍分布（segment_kind）：", scopes)
    print("\n前 15 筆被擋的：")
    for s, v in blocked[:15]:
        q = (s.get("exact_quote") or "").replace("\n", " ")
        print(f"  {s.get('episode_id')} {s.get('stock_name')} action={s.get('action')} "
              f"kw={v['keywords']} where={v['where']}")
        print(f"     {q[:70]}")


if __name__ == "__main__":
    if "--survey" in sys.argv:
        sys.stdout.reconfigure(encoding="utf-8")
        survey()
    else:
        raise SystemExit(pytest.main([__file__, "-q"]))
