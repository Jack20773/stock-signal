# -*- coding: utf-8 -*-
"""download_transcripts.fix_episode_dates() 的測試。

背景：episodes.json 是上游 whatmkreallysaid.com 的逐位元複本，上游把英文月份縮寫
Mar/May、Jun/Jul 解析錯（2026-09-03 實測 97 集日期錯）。download_transcripts.py
每次跑都會無條件覆寫 episodes.json，所以修正必須做在下載流程裡。

這裡測的是「實際會跑到的那個函式」，不是等價重寫版。
"""
import json
import shutil
from datetime import date
from pathlib import Path

import pytest

import download_transcripts as DT

HERE = Path(__file__).resolve().parent
REAL_EPISODES = HERE / "episodes.json"
RSS_CACHE = HERE / "_cache" / "gooaye_rss.xml"

# 非日期欄位：這幾個一個字都不准動
NON_DATE_FIELDS = ("number", "title", "filename", "description",
                   "display_title", "summary")


def _ep(number, d, **over):
    """造一筆跟 episodes.json 同結構的紀錄。"""
    rec = {
        "number": number,
        "title": f"EP{number} 標題",
        "filename": f"EP{number}_標題.md",
        "description": "歡迎收聽《股癌》，我是謝孟恭。",
        "display_title": f"EP{number} 顯示標題",
        "summary": "摘要摘要摘要。",
    }
    if d is not None:
        rec.update(DT.derive_date_fields(d))
    rec.update(over)
    return rec


@pytest.fixture
def sample(tmp_path):
    """5 筆：3 筆正常、1 筆缺日期（EP162 那種）、1 筆 RSS 沒有的。"""
    eps = [
        _ep(1, date(2020, 2, 27)),
        _ep(32, date(2020, 5, 3)),
        _ep(583, date(2025, 7, 2)),
        _ep(162, None),                     # 缺值，不是錯值 → 不處理
        _ep(999, date(2030, 1, 1)),         # RSS 裡沒有 → 無從比對
    ]
    p = tmp_path / "episodes.json"
    p.write_bytes(json.dumps(eps, ensure_ascii=False, indent=2).encode("utf-8"))
    rss = {1: date(2020, 2, 27), 32: date(2020, 5, 3),
           583: date(2025, 7, 2), 162: date(2021, 5, 6)}
    return p, rss


def _load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# 1. 故意改壞 → 修回來，而且只有日期欄位變動
# --------------------------------------------------------------------------
def test_corrupted_dates_are_restored_and_only_date_fields_change(sample):
    p, rss = sample
    before = _load(p)

    data = _load(p)
    # EP32：上游 May→Mar 的典型錯法（同年同日、只差月份）
    data[1].update(DT.derive_date_fields(date(2020, 3, 3)))
    # EP583：只差日
    data[2].update(DT.derive_date_fields(date(2025, 6, 30)))
    # EP1：只把衍生欄位弄壞，date 本身是對的 → 也要被補正
    data[0]["month_name"] = "Wrongmonth"
    data[0]["date_display"] = "Xxx 99, 1999"
    p.write_bytes(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))

    res = DT.fix_episode_dates(p, rss_dates=rss)

    assert res["status"] == "ok"
    assert res["population"] == 3          # 1 / 32 / 583（162 缺值、999 不在 RSS）
    assert res["fixed"] == 3
    assert res["no_date"] == 1
    assert res["not_in_rss"] == 1
    assert sorted(c[0] for c in res["changes"]) == [1, 32, 583]

    after = _load(p)
    # 全部欄位（含日期）回到原始正確值
    assert after == before
    # 非日期欄位逐筆確認沒被碰
    for a, b in zip(after, before):
        for k in NON_DATE_FIELDS:
            assert a[k] == b[k]


def test_only_date_fields_are_written(sample):
    """把非日期欄位改成別的值，跑完修正後那些值必須原封不動留著。"""
    p, rss = sample
    data = _load(p)
    data[1].update(DT.derive_date_fields(date(2020, 3, 3)))   # 弄壞日期
    data[1]["summary"] = "這段摘要不准被動到"
    data[1]["title"] = "這個標題不准被動到"
    p.write_bytes(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))

    res = DT.fix_episode_dates(p, rss_dates=rss)
    assert res["fixed"] == 1

    ep32 = next(e for e in _load(p) if e["number"] == 32)
    assert ep32["date"] == "2020-05-03"
    assert ep32["summary"] == "這段摘要不准被動到"
    assert ep32["title"] == "這個標題不准被動到"


# --------------------------------------------------------------------------
# 2. 冪等
# --------------------------------------------------------------------------
def test_idempotent(sample):
    p, rss = sample
    data = _load(p)
    data[1].update(DT.derive_date_fields(date(2020, 3, 3)))
    p.write_bytes(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))

    first = DT.fix_episode_dates(p, rss_dates=rss)
    snapshot = Path(p).read_bytes()
    second = DT.fix_episode_dates(p, rss_dates=rss)

    assert first["fixed"] == 1
    assert second["fixed"] == 0
    assert second["population"] == first["population"]
    assert second["status"] == "ok"
    assert Path(p).read_bytes() == snapshot   # 第二次連檔案 byte 都沒動


def test_clean_file_is_not_rewritten(sample):
    """本來就正確的檔案，跑一次不該被改寫（含 mtime 與 byte）。"""
    p, rss = sample
    snapshot = Path(p).read_bytes()
    res = DT.fix_episode_dates(p, rss_dates=rss)
    assert res["fixed"] == 0
    assert Path(p).read_bytes() == snapshot


# --------------------------------------------------------------------------
# 3. RSS 拿不到 / 拿到空的 → 不修、不靜默
# --------------------------------------------------------------------------
def test_rss_unavailable_leaves_file_untouched(sample, monkeypatch, capsys):
    p, _ = sample
    data = _load(p)
    data[1].update(DT.derive_date_fields(date(2020, 3, 3)))   # 檔裡有錯值
    p.write_bytes(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
    snapshot = Path(p).read_bytes()

    def boom(*a, **kw):
        raise OSError("連不上 feeds.soundon.fm")
    monkeypatch.setattr(DT.gooaye_rss, "fetch_rss", boom)

    res = DT.fix_episode_dates(p)      # 不給 rss_dates → 會真的走 load_rss_dates()

    assert res["status"] == "rss_unavailable"
    assert res["fixed"] == 0
    assert res["population"] == 0
    assert "本次未校正" in res["message"]
    assert Path(p).read_bytes() == snapshot          # 錯值留著，不會被亂改
    assert "[date-fix][警告]" in capsys.readouterr().out   # 不是靜默放行


def test_rss_parses_to_zero_episodes(sample, monkeypatch, capsys):
    p, _ = sample
    monkeypatch.setattr(DT.gooaye_rss, "fetch_rss", lambda *a, **kw: b"<rss/>")
    monkeypatch.setattr(DT.gooaye_rss, "parse_episodes", lambda raw: {})
    res = DT.fix_episode_dates(p)
    assert res["status"] == "rss_empty"
    assert res["fixed"] == 0
    assert "[date-fix][警告]" in capsys.readouterr().out


def test_empty_population_is_not_a_pass(sample, capsys):
    """RSS 有集數、但跟 episodes.json 完全對不上 → 母體 0，不得視為通過。"""
    p, _ = sample
    res = DT.fix_episode_dates(p, rss_dates={7777: date(2030, 5, 5)})
    assert res["status"] == "empty_population"
    assert res["population"] == 0
    assert res["fixed"] == 0
    assert "[date-fix][失敗]" in capsys.readouterr().out


def test_unreadable_file_reports_instead_of_crashing(tmp_path):
    p = tmp_path / "broken.json"
    p.write_text("{ 這不是 JSON", encoding="utf-8")
    res = DT.fix_episode_dates(p, rss_dates={1: date(2020, 2, 27)})
    assert res["status"] == "read_failed"
    assert res["fixed"] == 0


# --------------------------------------------------------------------------
# 4. 缺值（EP162）不處理、也不能炸
# --------------------------------------------------------------------------
def test_missing_date_is_left_alone(sample):
    p, rss = sample
    res = DT.fix_episode_dates(p, rss_dates=rss)     # rss 裡 162 有日期
    ep162 = next(e for e in _load(p) if e["number"] == 162)
    assert "date" not in ep162 or ep162["date"] is None
    assert "date_display" not in ep162
    assert res["no_date"] == 1


def test_explicit_null_date_is_left_alone(tmp_path):
    p = tmp_path / "e.json"
    rec = _ep(162, None)
    rec["date"] = None                     # 明寫 null 的情況
    p.write_bytes(json.dumps([rec], ensure_ascii=False, indent=2).encode("utf-8"))
    res = DT.fix_episode_dates(p, rss_dates={162: date(2021, 5, 6)})
    assert res["status"] == "empty_population"   # 沒有任何可比對的 → 不算通過
    assert res["no_date"] == 1
    assert _load(p)[0]["date"] is None


# --------------------------------------------------------------------------
# 5. 衍生欄位格式要跟真實檔案一致（不是我自己想的格式）
# --------------------------------------------------------------------------
@pytest.mark.skipif(not REAL_EPISODES.exists(), reason="沒有本地 episodes.json")
def test_derive_matches_real_file_format():
    data = json.loads(REAL_EPISODES.read_text(encoding="utf-8"))
    checked = 0
    for e in data:
        if not e.get("date"):
            continue
        y, m, d = (int(x) for x in e["date"].split("-"))
        expect = DT.derive_date_fields(date(y, m, d))
        for k, v in expect.items():
            assert e.get(k) == v, f"EP{e['number']} 欄位 {k}: {e.get(k)!r} != {v!r}"
        checked += 1
    assert checked > 0, "母體 0 筆不算通過"


# --------------------------------------------------------------------------
# 6. 對真實檔案 + 真實 RSS 快取跑一次（複本，不動正本，不連外網）
# --------------------------------------------------------------------------
@pytest.mark.skipif(not (REAL_EPISODES.exists() and RSS_CACHE.exists()),
                    reason="缺 episodes.json 或 RSS 離線快取")
def test_real_file_against_cached_rss_is_clean(tmp_path):
    p = tmp_path / "episodes.json"
    shutil.copy2(REAL_EPISODES, p)
    before = Path(p).read_bytes()
    # max_age_hours 給極大值 → 一定用離線快取，不會對外連線
    res = DT.fix_episode_dates(p, cache_path=RSS_CACHE, max_age_hours=10 ** 9)
    assert res["status"] == "ok"
    assert res["population"] >= 600, f"母體只有 {res['population']}，太少"
    assert res["fixed"] == 0, f"現況還有 {res['fixed']} 筆日期不對：{res['changes'][:10]}"
    assert Path(p).read_bytes() == before
