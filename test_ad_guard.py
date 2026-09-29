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
    # dirty 同時命中一個強詞（團購）跟一個弱詞（優惠碼）——單一弱詞不再夠格擋下
    # （見 2026-09-29 分層改動），這裡混一個強詞確保仍然測到「髒的被擋、乾淨
    # 的放行」這件事，而不是意外變成兩筆都放行。
    dirty = _sig(id=201, exact_quote="熱烈開放團購，輸入優惠碼 GOOAYE888 現折三百")
    clean = _sig(id=202, exact_quote="輝達的資料中心需求還在，我續抱")
    out = screen_signals([dirty, clean], log_path=log)

    assert out["population"] == 2
    assert [s["id"] for s in out["passed"]] == [202]
    assert [s.get("id") for s, _ in out["blocked"]] == [201]
    assert "優惠碼" in out["blocked"][0][1]["keywords"]
    assert "團購" in out["blocked"][0][1]["keywords"]


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
# ⑥ 2026-09-29 分層改動：強/弱關鍵字判斷式本身（不碰逐字稿，純測判斷邏輯）
#
# 背景：`000_Agent/008_remote/reports/2026-09-29_ad_guard_false_block.md`
# 逐筆人工判讀 09-14～09-27 全部 6 次批次、10 筆去重後被擋訊號，誤擋率
# 90%（9/10）——9 筆全部只命中「單一個」弱詞。丹尼爾裁決（Discord
# 1554303484587671827，回「對」1554312492551766020）：弱詞單獨命中不擋，
# 要跟另一個關鍵字（強或弱皆可）同時出現才擋；強詞維持單獨命中就擋。
# ---------------------------------------------------------------------------
def test_06_single_weak_keyword_alone_is_not_blocked():
    s = _sig(id=601, exact_quote="這集來聊聊最近很紅的開箱影片熱度")
    v = check_signal(s, transcript="")
    assert v["keywords"] == ["開箱"]
    assert v["blocked"] is False
    assert v["block_reason"] is None


def test_06b_two_weak_keywords_together_are_blocked():
    s = _sig(id=602, exact_quote="這支持誠心推薦，順便打個廣告")
    v = check_signal(s, transcript="")
    assert set(v["keywords"]) == {"誠心推薦", "廣告"}
    assert v["blocked"] is True
    assert v["block_reason"] == "weak_combo"


def test_06c_weak_plus_strong_is_blocked():
    s = _sig(id=603, exact_quote="業配時間到，順便幫大家開箱一下")
    v = check_signal(s, transcript="")
    assert set(v["keywords"]) >= {"業配", "開箱"}
    assert v["blocked"] is True
    assert v["block_reason"] == "strong_keyword"


def test_06d_single_strong_keyword_alone_is_still_blocked():
    s = _sig(id=604, exact_quote="這是一段置入內容")
    v = check_signal(s, transcript="")
    assert v["keywords"] == ["置入"]
    assert v["blocked"] is True
    assert v["block_reason"] == "strong_keyword"


# ---------------------------------------------------------------------------
# ⑦ 用 2026-09-29 誤擋報告裡實際查過的 DB 原句驗證（唯讀查證，欄位固定只取
# id/episode_id/stock_name/stock_code/action/exact_quote/reasoning/
# raw_reason/primary_tag/secondary_tags，非 SELECT *）。
#
# 9 筆誤擋樣本（去重母體）在改規則後全部必須放行；真業配 id=527 必須維持擋下。
# exact_quote/reasoning/raw_reason 逐字複製自 signals 表，不重新造句，避免
# 「自己出題自己過」。
# ---------------------------------------------------------------------------
FALSE_POSITIVE_SAMPLES = [
    _sig(id=383, episode_id="EP420", stock_name="玉晶光", stock_code="3406.TW",
         action="+1",
         exact_quote="Tier 1 就玉晶光，Tier 2 可能是揚明光。揚明光不一定會有 "
                      "supply，但是玉晶光就是穩的，Pancake 是他家的。",
         reasoning="講者點名玉晶光為 Vision Pro 供應鏈中的 Tier 1 供應商（Pancake "
                   "鏡頭），儘管目前營收貢獻有限，但認可其在 VR/MR 領域的關鍵地位，"
                   "屬重點觀察對象。",
         raw_reason="作為 Apple Vision Pro 的關鍵鏡頭供應商，隨 VR 題材發酵具備潛力。",
         primary_tag="#技術創新", secondary_tags=["#總經趨勢"]),
    _sig(id=628, episode_id="EP504", stock_name="蘋果", stock_code="AAPL",
         action="+1",
         exact_quote="我該把 Apple 買回來嗎？我不知道，我覺得 Apple 可以買，"
                      "我一直很喜歡 Apple。",
         reasoning="講者明確表示一直很喜歡 Apple，且針對聽眾詢問是否買回，給予肯定的"
                   "回應，態度偏向長期看好。",
         raw_reason="講者對該公司長期持正面看法，表達買入意願。",
         primary_tag="#總經趨勢", secondary_tags=["#估值過低"]),
    _sig(id=727, episode_id="EP549", stock_name="奇鋐", stock_code="3017.TW",
         action="+1",
         exact_quote="我自己手上的標的，只有奇鋐、健策的一兩支已經是回到了起跌點，"
                      "像是這個股災沒有發生過一樣",
         reasoning="講者明確提及持有的標的中，奇鋐與健策已回到起跌點，並表示若前面有"
                   "現金可加碼的，現在收復路上滿補的。此處視為持續持有且心態看好，"
                   "故判定為 +1。",
         raw_reason="股價收復速度快，展現強勢抗跌與反彈能力，講者持續持有。",
         primary_tag="#估值過低", secondary_tags=["#營收動能"]),
    _sig(id=728, episode_id="EP549", stock_name="健策", stock_code="3653.TW",
         action="+1",
         exact_quote="我自己手上的標的，只有奇鋐、健策的一兩支已經是回到了起跌點，"
                      "像是這個股災沒有發生過一樣",
         reasoning="同上，與奇鋐被歸類在表現亮眼、回到起跌點的標的，講者維持持有部位。",
         raw_reason="股價收復速度快，表現優於其他持倉，講者持續持有。",
         primary_tag="#估值過低", secondary_tags=["#營收動能"]),
    _sig(id=798, episode_id="EP578", stock_name="Google", stock_code="GOOGL",
         action="+1",
         exact_quote="所以整體看下來，Google 這家公司非常健康，他們可能在 AI 的初期，"
                      "有一個過度的政治正確事件...可是在他們修正之後，其實整體看下來，"
                      "Google 或是它的 Gemini，到現在都是一個可能在裡面是很強的一個"
                      "領跑集團，也不覺得有什麼太大的問題。",
         reasoning="講者明確指出 Google 在廣告表現與 AI 發展皆在正軌，且 AI 產品變現"
                   "策略（bundle）成功，整體公司非常健康，態度顯著看好。",
         raw_reason="AI 產品鋪陳完整且變現能力佳，廣告成長強勁，公司體質非常健康。",
         primary_tag="#營收動能", secondary_tags=["#技術創新"]),
    _sig(id=805, episode_id="EP580", stock_name="Amazon", stock_code="AMZN",
         action="+1",
         exact_quote="當然他有可能是因為目前供給是跟不上，我們都知道說 Annapurna、"
                      "Trainium 其實表現非常好的，所以有機會就是 Amazon 現在是一個"
                      "短暫的休息，後面那個成長性還是會拉出來給大家看到。",
         reasoning="講者認為其伺服器採購表現良好，目前股價修正僅是短暫休息，對其後續"
                   "成長性持樂觀看法。",
         raw_reason="受惠於 AI 基礎設施需求，看好短期修正後的成長潛力。",
         primary_tag="#總經趨勢", secondary_tags=["#產能擴充"]),
    _sig(id=806, episode_id="EP580", stock_name="Meta", stock_code="META",
         action="+1",
         exact_quote="所以祖克柏的股價非常強勢，因為他會講故事，外加他們的發展是符合"
                      "市場主流的一個敘事，我覺得就很好。",
         reasoning="講者認為 Meta 在 AI 敘事上表現極佳，將 Reality Labs 的支出成功"
                   "轉化為市場買單的 AI 競爭力，股價強勢。",
         raw_reason="成功轉型 AI 敘事，演算法優化提升廣告效益，市場評價正面。",
         primary_tag="#技術創新", secondary_tags=["#營收動能"]),
    _sig(id=905, episode_id="EP613", stock_name="Google", stock_code="GOOGL",
         action="+1",
         exact_quote="Google 是一個非常好的公司那也站在一個非常好的位置，那它在"
                      "供應鏈我們可以看到的環節都很好。",
         reasoning="講者明確指出 Google 體質改變（撤掉 DEI 等枷鎖）、基本面營收強勁，"
                   "且供應鏈開圖後需求恐怖（需求滿足率僅 40%-50%），屬於講者看好的"
                   "標的。",
         raw_reason="公司基本面體質改善，且 AI 運算需求極度強勁，供應鏈產能供不應求。",
         primary_tag="#總經趨勢", secondary_tags=["#營收動能", "#產能擴充"]),
    _sig(id=983, episode_id="EP687", stock_name="Meta", stock_code="META",
         action="+1",
         exact_quote="Meta 的做法是怎麼樣的？就是我們認為，雖然它在這次的 earnings "
                      "call 裡面還是講說這個算力能夠自己用就自己用，可是它的各項布局"
                      "跟我們最近看到的拉貨……它其實都是為了租賃去做的事情。",
         reasoning="講者提到 Meta 的佈局和最近的拉貨與 Google 類似，都是朝向算力"
                   "租賃與當房東的方向前進，且從廣告收入支撐與 TPU/採購指標來看，是"
                   "持續往這個方向加速的雙雄之一。",
         raw_reason="Meta 朝向算力租賃與基礎設施方向發展，配合廣告營收支撐，展現強勁"
                   "的基建佈局動能。",
         primary_tag="#技術創新", secondary_tags=["#營收動能"]),
]


def _real_transcript_or_skip(episode_id: str) -> str:
    t = ad_guard.load_transcript(episode_id)
    if t is None:
        pytest.skip(f"找不到 {episode_id} 逐字稿（.gitignore 排除，CI 上沒有）；"
                     "跳過不代表通過。")
    return t


@pytest.mark.parametrize("sample", FALSE_POSITIVE_SAMPLES, ids=lambda s: str(s["id"]))
def test_07_2026_09_29_false_positive_samples_now_pass_with_real_transcript(sample):
    """套真實逐字稿視窗（有本機檔案才跑）：改規則後這 9 筆都不該再被擋。"""
    t = _real_transcript_or_skip(sample["episode_id"])
    v = check_signal(sample, transcript=t)
    assert v["blocked"] is False, (
        f"id={sample['id']} 應該放行卻被擋：keywords={v['keywords']} "
        f"where={v['where']} reason={v['block_reason']}"
    )


@pytest.mark.parametrize("sample", FALSE_POSITIVE_SAMPLES, ids=lambda s: str(s["id"]))
def test_07b_2026_09_29_false_positive_samples_pass_from_signal_fields_alone(sample):
    """不靠逐字稿也要放行：只用訊號自身文字欄位判斷（CI 沒有逐字稿檔時的底線）。"""
    v = check_signal(sample, transcript="")
    assert v["blocked"] is False, (
        f"id={sample['id']} 光憑訊號自身欄位就被擋：keywords={v['keywords']} "
        f"reason={v['block_reason']}（如果這裡失敗，代表誤擋不是視窗誤黏，而是"
        f"訊號欄位本身文字造成，需要再檢查是不是真的該擋）"
    )


def test_07c_real_ad_id_527_still_blocked():
    """唯一的真業配樣本（EP468 國泰金，開頭即「本集節目由國泰證券贊助」）"""
    s = _sig(id=527, episode_id="EP468", stock_name="國泰金", stock_code="2882.TW",
              action="+1",
              exact_quote="國泰證券美股手續費要降價了！其實之前有聽眾在 QA 上分享過，"
                          "這一次個股手續費降價真是超便宜...想知道到底有多便宜，可以在"
                          "我們資訊欄這邊找到答案。",
              reasoning="節目由國泰證券贊助，講者大力宣傳其複委託美股手續費降價、定期"
                        "定額優惠及抽獎活動，屬明確的推廣行為。雖然屬於業配，但講者以"
                        "自身觀點推薦該券商服務，符合 +1 的開倉/留意訊息。",
              raw_reason="國泰證券複委託交易手續費大幅調降，具備市場競爭優勢，講者推薦"
                        "使用。",
              primary_tag="#估值過低", secondary_tags=["#籌碼面"])
    v = check_signal(s, transcript="")
    assert v["blocked"] is True
    assert set(v["keywords"]) >= {"業配", "贊助"}
    assert v["block_reason"] == "strong_keyword"


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
