# -*- coding: utf-8 -*-
"""語意覆核關卡測試。

  python -X utf8 -m pytest test_semantic_gate.py -q     # 離線：打樁，不開 claude、不寄信、不碰 DB
  python -X utf8 test_semantic_gate.py --live           # 實跑：題庫每題真的開一次 claude -p

--live 用的題庫 eval/semantic_gate_regression.json（2026-10-12 從 signals 表唯讀撈出）：
  must_block  id=985 EP689 保險套業配「誠心推薦特斯拉」→ 必須擋
  must_pass   5 則真的在講股票的看多／看空 → 必須寄出（yes，或 uncertain 帶標註）
  observe     只記錄、不判對錯
--live 不讀也不寫快取（每題都真的問），判決寫到暫存檔，不污染正式稽核檔。
"""
import json
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")

import semantic_gate as sg

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "eval", "semantic_gate_regression.json")


def _sig(i, ep, action="+1", quote="台積電我覺得還會漲，我自己持續加碼"):
    return {"id": i, "episode_id": ep, "stock_name": f"S{i}", "stock_code": f"C{i}",
            "action": action, "exact_quote": quote + str(i)}


def _tmp_log():
    fd, p = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    return p


# ---------------------------------------------------------------- 離線測試
def test_parse_verdict_strict():
    assert sg.parse_verdict('{"verdict":"no","reason":"業配"}')["verdict"] == "no"
    assert sg.parse_verdict('```json\n{"verdict":"YES","reason":"x"}\n```')["verdict"] == "yes"
    assert sg.parse_verdict('好的：{"verdict":"uncertain","reason":"x"} 以上')["verdict"] == "uncertain"
    for bad in ('', 'yes', '{"verdict":"maybe"}', '{"reason":"x"}', '[1]'):
        try:
            sg.parse_verdict(bad)
        except sg.GateError:
            continue
        raise AssertionError(f"應該拒收：{bad!r}")


def test_yes_passes_uncertain_flagged_no_and_errors_fail_closed():
    answers = {"1": "yes", "2": "no", "3": "uncertain"}

    def asker(prompt):
        for k, v in answers.items():
            if f"持續加碼{k}" in prompt:
                return {"verdict": v, "reason": "stub"}
        raise TimeoutError("模擬逾時")

    sigs = [_sig(1, "EP1"), _sig(2, "EP1"), _sig(3, "EP1"), _sig(4, "EP1")]
    log = _tmp_log()
    res = sg.screen(sigs, asker=asker, log_path=log, use_cache=False)
    assert [s["id"] for s in res["passed"]] == [1, 3]
    assert [s["id"] for s, _ in res["flagged"]] == [3]
    got = {s["id"]: v["verdict"] for s, v in res["blocked"]}
    assert got == {2: "no", 4: "error"}, got
    rows = [json.loads(l) for l in open(log, encoding="utf-8")]
    assert len(rows) == 4                       # 每一則都留紀錄，包含失敗的
    assert any("TimeoutError" in r["reason"] for r in rows)


def test_cache_only_decisive_verdicts():
    calls = []

    def asker(prompt):
        calls.append(prompt)
        return {"verdict": "yes" if "加碼1" in prompt else "uncertain", "reason": "stub"}

    log = _tmp_log()
    sigs = [_sig(1, "EP1"), _sig(2, "EP1")]
    sg.screen(sigs, asker=asker, log_path=log)
    assert len(calls) == 2
    sg.screen(sigs, asker=asker, log_path=log)
    assert len(calls) == 3                      # yes 沿用、uncertain 重問


def test_population_zero_is_not_pass():
    res = sg.screen([], asker=lambda p: {"verdict": "yes"})
    assert res["population"] == 0 and "不等於檢查通過" in res["lines"][0]


def test_notifier_gate_backfills_older_episode_and_injects_note():
    """最新一集整集被擋 → 遞補上來的前一集卡片也必須被覆核；信末列出被擋的。"""
    import notifier
    results = [_sig(1, "EP10"), _sig(2, "EP9"), _sig(3, "EP8"), _sig(4, "EP8", action="0")]
    seen = []

    def asker(prompt):
        seen.append(prompt)
        return {"verdict": "no" if "加碼1" in prompt else "yes", "reason": "stub 理由"}

    pool, blocked, flagged, lines = notifier.apply_semantic_gate(results, asker=asker, log_path=_tmp_log())
    assert flagged == []
    assert [s["id"] for s, _ in blocked] == [1]
    assert {r["id"] for r in notifier.email_card_signals(pool)} == {2, 3}
    assert len(seen) == 3                       # EP8 的卡片是遞補上來後才被問的
    html = notifier._inject_gate_note("<html><body>x</body></html>", blocked)
    assert "擋下 1／標註 0" in html and "加碼1" in html and html.endswith("</body></html>")


def test_notifier_send_path_is_stubbed_end_to_end(monkeypatch=None):
    """走 run_report 的寄信分支，但 send_email / 訂閱者 / save_latest_report 全打樁，
    確認被擋的訊號不在信裡、信末有註記。不寄任何真信、不寫 DB。"""
    import notifier
    sent = {}
    orig = {k: getattr(notifier, k) for k in
            ("send_email", "send_subscriber_emails", "save_latest_report",
             "generate_html_detail", "compute_attention", "list_signals",
             "generate_html_transcripts", "export_transcripts_data", "screen_signals")}
    orig_screen = sg.screen
    try:
        notifier.send_email = lambda subj, html, override_to="": sent.setdefault("html", html) or True
        notifier.send_subscriber_emails = lambda subj, html: sent.setdefault("subs", True)
        notifier.save_latest_report = lambda subj, html: None
        notifier.generate_html_detail = lambda *a, **k: ""
        notifier.compute_attention = lambda rows: []
        notifier.list_signals = lambda: []
        notifier.generate_html_transcripts = lambda eps: ""
        notifier.export_transcripts_data = lambda: 0
        notifier.screen_signals = lambda rs: {"passed": rs, "population": len(rs), "lines": [],
                                              "log_path": None}
        log = _tmp_log()
        sg.screen = lambda sigs, asker=None, log_path=None: orig_screen(
            sigs, asker=lambda p: {"verdict": "no" if "大大的濕" in p else "yes", "reason": "stub"},
            log_path=log)
        ad = {"id": 985, "episode_id": "EP689", "stock_name": "特斯拉", "stock_code": "TSLA",
              "action": "+1", "exact_quote": "誠心推薦特斯拉，濕，大大的濕。", "entry_date": "2026-08-19"}
        ok = {"id": 1, "episode_id": "EP689", "stock_name": "台積電", "stock_code": "2330.TW",
              "action": "+1", "exact_quote": "台積電我覺得根本不該在這個價格", "entry_date": "2026-08-19"}
        cwd = os.getcwd()
        os.chdir(tempfile.mkdtemp())            # run_report 會寫 report_*.html，寫到暫存目錄
        try:
            notifier.run_report(results=[ad, ok], stats={"win_rate": 50, "wins": 1, "losses": 1, "decided": 2, "total": 2},
                                detail_url="https://example.invalid/")
        finally:
            os.chdir(cwd)
        html = sent["html"]
        body, note = html.split("品管覆核")
        assert "台積電" in body and "大大的濕" not in body
        assert "大大的濕" in note
    finally:
        for k, v in orig.items():
            setattr(notifier, k, v)
        sg.screen = orig_screen


def test_gate_outage_does_not_send_and_partial_block_still_sends():
    """關卡全壞（每則都 error）→ 不寄；有判決只是被擋 → 照寄、信末列出。"""
    import notifier
    names = ("send_email", "send_subscriber_emails", "save_latest_report", "generate_html_detail",
             "compute_attention", "list_signals", "generate_html_transcripts",
             "export_transcripts_data", "screen_signals")
    orig = {k: getattr(notifier, k) for k in names}
    orig_screen = sg.screen
    stats = {"win_rate": 50, "wins": 1, "losses": 1, "decided": 2, "total": 2}
    sigs = [{"id": 1, "episode_id": "EP1", "stock_name": "A", "stock_code": "A", "action": "+1",
             "exact_quote": "q1", "entry_date": "2026-01-01"}]
    try:
        notifier.send_subscriber_emails = lambda subj, html: None
        notifier.save_latest_report = lambda subj, html: None
        notifier.generate_html_detail = lambda *a, **k: ""
        notifier.compute_attention = lambda rows: []
        notifier.list_signals = lambda: []
        notifier.generate_html_transcripts = lambda eps: ""
        notifier.export_transcripts_data = lambda: 0
        notifier.screen_signals = lambda rs: {"passed": rs, "population": len(rs), "lines": [],
                                              "log_path": None}
        cwd = os.getcwd()
        os.chdir(tempfile.mkdtemp())
        try:
            for verdict, expect_sent in (("error", False), ("no", True)):
                sent = []
                notifier.send_email = lambda subj, html, override_to="": sent.append(html) or True
                log = _tmp_log()

                def _asker(p, v=verdict):
                    if v == "error":
                        raise RuntimeError("claude 沒登入")
                    return {"verdict": v, "reason": "stub"}
                sg.screen = lambda s_, asker=None, log_path=None, a=_asker, l=log: orig_screen(
                    s_, asker=a, log_path=l)
                notifier.run_report(results=[dict(x) for x in sigs], stats=stats)
                assert bool(sent) == expect_sent, (verdict, sent)
                if sent:
                    assert "品管覆核：擋下 1／標註 0" in sent[0]
        finally:
            os.chdir(cwd)
    finally:
        for k, v in orig.items():
            setattr(notifier, k, v)
        sg.screen = orig_screen


def test_uncertain_is_sent_with_card_note_and_counted():
    """不確定→照寄，卡片上有小字標註，信末分開算「擋下 N／標註 M」；否→不寄。"""
    import notifier
    from report_html import generate_html_email
    results = [_sig(1, "EP10"), _sig(2, "EP10"), _sig(3, "EP10")]
    verdicts = {"加碼1": "yes", "加碼2": "uncertain", "加碼3": "no"}

    def asker(prompt):
        for k, v in verdicts.items():
            if k in prompt:
                return {"verdict": v, "reason": "stub"}
        raise AssertionError(prompt)

    pool, blocked, flagged, _ = notifier.apply_semantic_gate(results, asker=asker, log_path=_tmp_log())
    cards = {r["id"]: r for r in notifier.email_card_signals(pool)}
    assert set(cards) == {1, 2}
    assert cards[2]["qc_note"] == notifier.QC_UNCERTAIN_NOTE and "qc_note" not in cards[1]
    assert "qc_note" not in results[1]          # 不改到原物件
    stats = {"win_rate": 50, "wins": 1, "losses": 1, "decided": 2, "total": 2}
    html = notifier._inject_gate_note(generate_html_email(pool, "t", stats), blocked, flagged)
    body, note = html.split("品管覆核：")
    assert body.count(notifier.QC_UNCERTAIN_NOTE) == 1
    assert "加碼2" in body and "加碼3" not in body
    assert note.startswith("擋下 1／標註 1")


# ---------------------------------------------------------------- 實跑
def live():
    from ad_guard import load_transcript
    fx = json.load(open(FIXTURE, encoding="utf-8"))
    groups = [("must_block", "擋"), ("must_pass", "放行"), ("observe", "觀察")]
    ok_all = True
    times = []
    for g, want in groups:
        for s in fx[g]:
            r = sg.judge_one(s, load_transcript(s["episode_id"]))
            times.append(r["duration_s"])
            passed = r["verdict"] in ("yes", "uncertain")   # 會寄出（uncertain 帶標註）
            good = (g == "observe") or (passed == (g == "must_pass"))
            ok_all &= good
            print(f"[{'OK ' if good else 'BAD'}] {g:10s} id={s['id']:<5} {s['episode_id']} "
                  f"{s['stock_name']}({s['action']}) 前後文={r['context_kind']:<14} "
                  f"判決={r['verdict']:<9} {r['duration_s']:>5.1f}s｜{r['reason']}")
    print(f"每則耗時：min {min(times):.1f}s / avg {sum(times)/len(times):.1f}s / max {max(times):.1f}s")
    print("全部符合預期" if ok_all else "有不符合預期的題目")
    return 0 if ok_all else 1


if __name__ == "__main__":
    if "--live" in sys.argv:
        sys.exit(live())
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
