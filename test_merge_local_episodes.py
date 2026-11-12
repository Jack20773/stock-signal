# -*- coding: utf-8 -*-
"""download_transcripts.main() 不可蓋掉「本地有、上游沒有」的集數（EP712/713 事故）。

跑的是真的 main()，只把網路、輸出目錄、RSS 校正換成假的；不碰正式 episodes.json。
"""
import json
import shutil
from pathlib import Path

import download_transcripts as DT

HERE = Path(__file__).resolve().parent
REAL = HERE / "episodes.json"


def run_main(mod, tmp_path, upstream_bytes, local_bytes, monkeypatch):
    local = tmp_path / "episodes.json"
    local.write_bytes(local_bytes)
    monkeypatch.setattr(mod, "EPISODES_LOCAL", local)
    monkeypatch.setattr(mod, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(mod, "fetch",
                        lambda url, retries=3: upstream_bytes if url == mod.EPISODES_URL else b"x")
    monkeypatch.setattr(mod, "fix_episode_dates", lambda *a, **k: {"fixed": 0, "status": "ok", "message": ""})
    mod.main(last_n=1)
    return json.loads(local.read_text(encoding="utf-8"))


def _data():
    raw = REAL.read_bytes()
    full = json.loads(raw.decode("utf-8"))
    return raw, full, [e for e in full if e["number"] not in (712, 713)]


def test_local_only_episodes_survive_main(tmp_path, monkeypatch):
    raw, full, up = _data()
    assert len(full) - len(up) == 2, "前提：正式檔含 712/713"
    up_bytes = DT._dump_bytes(up, raw)
    res = run_main(DT, tmp_path, up_bytes, raw, monkeypatch)
    assert [e["number"] for e in res] == [e["number"] for e in full]
    assert res == full                      # 其他筆一個字都不變


def test_upstream_wins_and_no_local_only_keeps_raw(tmp_path, monkeypatch):
    raw, full, up = _data()
    up2 = json.loads(json.dumps(up))
    up2[10]["title"] = "上游改過的標題"
    up_bytes = DT._dump_bytes(up2, raw)
    res = run_main(DT, tmp_path, up_bytes, raw, monkeypatch)
    assert res[10]["title"] == "上游改過的標題"      # 上游有的以上游為準
    # 本地沒有獨有集數時，維持逐位元複製上游
    res2_path = tmp_path / "b"
    res2_path.mkdir()
    run_main(DT, res2_path, up_bytes, up_bytes, monkeypatch)
    assert (res2_path / "episodes.json").read_bytes() == up_bytes
