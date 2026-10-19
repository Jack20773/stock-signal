# -*- coding: utf-8 -*-
"""performance._plan_entry_fills / _episode_date 的測試（2026-10-20，93 筆進場日錯的源頭修正）。

跑法：python -X utf8 -m pytest test_entry_date_resync.py -q
純邏輯，不連資料庫、不抓價。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import performance as P

AIR = {"EP432": "2024-03-02", "EP696": "2026-09-12"}


def row(i, ep, date=None, price=None, code="NVDA"):
    return {"id": i, "episode_id": ep, "stock_code": code, "analysis_date": "2026-07-01",
            "entry_date": date, "entry_price": price}


def test_missing_price_filled_with_air_date():
    meta, skipped, mism, alarm = P._plan_entry_fills([row(1, "EP432")], AIR)
    assert [(m["id"], m["date"], m["resync"]) for m in meta] == [(1, "2024-03-02", False)]
    assert not skipped and not mism and not alarm


def test_episode_not_in_json_is_skipped_not_analysis_date():
    meta, skipped, mism, alarm = P._plan_entry_fills([row(2, "EP999")], AIR)
    assert meta == [] and skipped == [2]


def test_wrong_written_date_is_resynced():
    # 2026-10-17 的實例：EP432 被寫成 2024-05-02（月份錯）
    meta, _, mism, alarm = P._plan_entry_fills([row(3, "EP432", "2024-05-02", 98.28)], AIR)
    assert not alarm
    assert [(m["id"], m["date"], m["resync"]) for m in meta] == [(3, "2024-03-02", True)]


def test_correct_written_date_untouched():
    meta, skipped, mism, alarm = P._plan_entry_fills([row(4, "EP696", "2026-09-12", 1.0)], AIR)
    assert meta == [] and mism == [] and skipped == []


def test_too_many_mismatches_alarm_and_no_rewrite():
    rows = [row(i, "EP432", "2024-05-02", 1.0) for i in range(5)]
    meta, _, mism, alarm = P._plan_entry_fills(rows, AIR, resync_max=3)
    assert alarm and len(mism) == 5 and meta == []


def test_episode_date_no_fallback(monkeypatch):
    monkeypatch.setattr(P, "_load_episodes", lambda: AIR)
    assert P._episode_date("EP432", "2026-07-01") == "2024-03-02"
    assert P._episode_date("EP999", "2026-07-01") is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
