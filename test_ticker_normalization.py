# -*- coding: utf-8 -*-
"""代號校正的回歸測試（2026-08-24 索羅門分身新增）。

不連 DB、不連網路，只吃本機的 `tw_listing_map.json`。
用 `python -X utf8 test_ticker_normalization.py` 或 `pytest` 都能跑。

保護的是 serenity-clone 回測實測抓到的那一類 bug：
上櫃股被標成 `.TW`（yfinance 抓不到）、代號指向另一家公司（抓得到但算錯家）。
"""
import stock_dict
from stock_dict import normalize_tw_suffix, resolve_by_official_name, resolve_code

# (Gemini 可能吐出的 stock_name, stock_code) -> 期望寫進 DB 的代號
CASES_FIXED = [
    # ① 上櫃股被標成 .TW —— 本次 DB 實測到的 19 檔全列在這裡
    ("光洋科", "1785.TW", "1785.TWO"),
    ("富喬", "1815.TW", "1815.TWO"),
    ("穩懋", "3105.TW", "3105.TWO"),
    ("原相", "3227.TW", "3227.TWO"),
    ("力旺", "3529.TW", "3529.TWO"),
    ("兆利", "3548.TW", "3548.TWO"),
    ("安瑞-KY", "3664.TW", "3664.TWO"),
    ("漢磊", "3707.TW", "3707.TWO"),
    ("信驊", "5274.TW", "5274.TWO"),
    ("台半", "5425.TW", "5425.TWO"),
    ("智冠", "5478.TW", "5478.TWO"),
    ("龍巖", "5530.TW", "5530.TWO"),
    ("茂達", "6138.TW", "6138.TWO"),
    ("萬潤", "6187.TW", "6187.TWO"),
    ("立端", "6245.TW", "6245.TWO"),
    ("環球晶", "6488.TW", "6488.TWO"),
    ("元太科技", "8069.TW", "8069.TWO"),
    ("群聯", "8299.TW", "8299.TWO"),
    # ② 代號指向別家公司，靠官方名單用「公司全名」救回來（比 ① 危險：抓得到價、不報錯）
    ("昇達科", "3511.TW", "3491.TWO"),   # 3511 是矽瑪
    ("立隆電", "2471.TW", "2472.TW"),    # 2471 是資通
    ("阜爾運通", "6585.TW", "6914.TW"),   # 6585 是鼎基
    # ③ 反方向也要對：上市股不能被翻成 .TWO
    ("台積電", "2330.TWO", "2330.TW"),
]

# 這些**必須原樣通過**，不准被「校正」壞掉
CASES_UNCHANGED = [
    ("台積電", "2330.TW", "2330.TW"),
    ("鴻海", "2317.TW", "2317.TW"),
    ("群聯", "8299.TWO", "8299.TWO"),
    # 6176 瑞儀：當日官方收盤行情檔裡沒有這檔（無成交/暫停），但它確實是上市股。
    # 白名單查不到就不准動——這是「查不到 != 錯」的護欄。
    ("瑞儀", "6176.TW", "6176.TW"),
    ("蘋果", "AAPL", "AAPL"),
    ("Pure Storage", "PSTG", "P"),  # 人工字典優先，且 2026-04-17 起 PSTG 已更名為 P
]


def test_suffix_and_company_fixes():
    bad = []
    for name, given, want in CASES_FIXED:
        got = resolve_code(name, given)
        if got != want:
            bad.append((name, given, want, got))
    assert not bad, f"校正失敗：{bad}"
    assert len(CASES_FIXED) == 22, "母體數變了，請一併更新註解"


def test_correct_codes_are_left_alone():
    bad = []
    for name, given, want in CASES_UNCHANGED:
        got = resolve_code(name, given)
        if got != want:
            bad.append((name, given, want, got))
    assert not bad, f"不該被動的代號被改壞：{bad}"


def test_no_fake_ticker_survives_validation():
    """`6elf.TW` 這種「把公司名塞進代號欄」的假代號，必須被 _valid_ticker 擋掉。"""
    from database import _valid_ticker
    assert _valid_ticker("6elf.TW") is False
    assert _valid_ticker("3105.TWO") is True
    assert _valid_ticker("P") is True


def test_dict_entries_agree_with_official_registry():
    """人工字典 `_TW` 的每一筆都要通得過官方名單（後綴正確）。

    這一條就是 2026-08-24 抓到 `奇景 -> 3533.TW`（3533 其實是嘉澤）那類錯誤的守門員。
    """
    checked = wrong = 0
    problems = []
    for name, code in stock_dict._TW.items():
        num, _, suf = code.rpartition(".")
        official = stock_dict._LISTING.get(num)
        if official is None:
            continue  # 下市/興櫃/名單當日缺席，不在本測試的判定範圍
        checked += 1
        if official != suf:
            wrong += 1
            problems.append((name, code, f"{num}.{official}"))
    assert checked > 0, "母體為 0：白名單沒載入，這個測試等於沒跑"
    print(f"[POP] _TW 條目 {len(stock_dict._TW)} 筆，其中 {checked} 筆在官方名單內、實際比對 {checked} 筆")
    assert not problems, f"字典後綴與官方名單不符：{problems}"


def test_official_name_lookup_is_exact_only():
    assert resolve_by_official_name("昇達科") == "3491.TWO"
    assert resolve_by_official_name("昇達") is None          # 不做前綴/模糊比對
    assert resolve_by_official_name("這家公司不存在") is None


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(f"[POP] 測試函式 {len(fns)} 支；CASES_FIXED {len(CASES_FIXED)} 筆、"
          f"CASES_UNCHANGED {len(CASES_UNCHANGED)} 筆")
    assert len(fns) > 0 and len(CASES_FIXED) > 0
    for fn in fns:
        fn()
        print(f"  PASS  {fn.__name__}")
    print("ALL PASS")
