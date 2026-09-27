#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""固定名詞改字表（asr/fixed_term_corrections.tsv）的自測：正向 + 反向對照組。

背景
----
eval/proper_noun_accuracy.py 量到自建版（faster-whisper）逐字稿在「股癌」「謝孟恭」
「聯準會」這類節目固定用語上系統性聽錯（EP681/682/683/684/687 五集，母體 50，
自建版 32/50=64%），本改字表接進 independent_transcribe.normalize_transcript_text()
修這批錯。本腳本回答判斷力二之 7：「如果我要修的東西根本不存在，這個測試會不會照樣
綠燈？」——所以每個正向斷言都有一個成對的反向斷言在盯著同一段程式碼。

**本腳本只讀 transcripts/、transcripts/independent_superseded/、docs/pairing_samples/
與 asr/fixed_term_corrections.tsv，全程只在記憶體裡跑 normalize_transcript_text()，
不 write() 任何逐字稿檔案。** 驗證用「複本（記憶體字串）+ mtime/內容比對」證明檔案沒被動。

跑法
----
    python -X utf8 eval/fixed_term_corrections_test.py

退出碼：全部通過 = 0，任何一條失敗 = 1。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "eval"))

import independent_transcribe as it  # noqa: E402  （生產路徑，只呼叫 normalize_transcript_text）
import proper_noun_accuracy as pna   # noqa: E402  （既有的量尺，只讀）

FIXED_TERM_TSV = REPO / "asr" / "fixed_term_corrections.tsv"

failures: list[str] = []
lines: list[str] = []
total_checks = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global total_checks
    total_checks += 1
    lines.append(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(name)


# --------------------------------------------------------------------------
# 0) 前置：改字表存在、有內容、規則能編譯成功（母體 0 直接判 FAIL，不准綠燈）
# --------------------------------------------------------------------------
def section_0_table_sanity():
    lines.append("=== 0) 改字表本身 ===")
    check("asr/fixed_term_corrections.tsv 存在", FIXED_TERM_TSV.exists(),
          str(FIXED_TERM_TSV))
    rules = it.load_fixed_term_corrections()
    check("規則數 > 0（母體 0 不算通過）", len(rules) > 0, f"n={len(rules)}")
    return rules


# --------------------------------------------------------------------------
# 1) 正向對照組：套用改字表後，用既有量尺重量，自建版正確率必須上升
# --------------------------------------------------------------------------
def section_1_forward(roster, stoplist):
    lines.append("\n=== 1) 正向對照組（套改字表前 vs 後，用 eval/proper_noun_accuracy.py 重量）===")
    before_hit = before_pop = after_hit = after_pop = 0
    recovered_all = []
    for pair in pna.PAIRS:
        ep = pair["ep"]
        fan_text = (REPO / pair["fan"]).read_text(encoding="utf-8")
        self_text_raw = (REPO / pair["self"]).read_text(encoding="utf-8")
        # 只在記憶體裡跑正規化；不寫回檔案。
        self_text_fixed = it.normalize_transcript_text(self_text_raw)

        r_before = pna.score_pair(ep, fan_text, self_text_raw, roster, stoplist)
        r_after = pna.score_pair(ep, fan_text, self_text_fixed, roster, stoplist)

        cm = pna.canon_map(roster)
        hit_before = set(r_before["versions"]["自建版"]["hit_ids"])
        hit_after = set(r_after["versions"]["自建版"]["hit_ids"])
        recovered = sorted(cm[i] for i in (hit_after - hit_before))
        newly_broken = sorted(cm[i] for i in (hit_before - hit_after))
        recovered_all.extend((ep, name) for name in recovered)

        U = r_before["union_size"]
        hb = r_before["versions"]["自建版"]["hit"]
        ha = r_after["versions"]["自建版"]["hit"]
        before_hit += hb
        before_pop += U
        after_hit += ha
        after_pop += r_after["union_size"]

        lines.append(f"  {ep}: U={U} 自建版 hit {hb}->{ha}"
                      + (f"  回收：{'、'.join(recovered)}" if recovered else "")
                      + (f"  ⚠新漏：{'、'.join(newly_broken)}" if newly_broken else ""))
        check(f"{ep}: 母體不變（改字不准動聯集）", r_after["union_size"] == U,
              f"{U} -> {r_after['union_size']}")
        check(f"{ep}: 沒有本來對的實體被改壞", not newly_broken, str(newly_broken))

    check("正向總計：母體 > 0", before_pop > 0, f"pop={before_pop}")
    check("正向總計：自建版命中數上升", after_hit > before_hit,
          f"{before_hit}/{before_pop} -> {after_hit}/{after_pop}")
    before_rate = before_hit / before_pop if before_pop else None
    after_rate = after_hit / after_pop if after_pop else None
    lines.append(f"  合計：改前 {before_hit}/{before_pop}="
                 f"{before_rate*100:.1f}%　改後 {after_hit}/{after_pop}={after_rate*100:.1f}%")
    lines.append(f"  回收實體：{recovered_all}")
    check("正向總計：至少救回 5 個實體（股癌/謝孟恭至少各救回幾集）",
          len(recovered_all) >= 5, f"n={len(recovered_all)}")
    return before_hit, before_pop, after_hit, after_pop, recovered_all


# --------------------------------------------------------------------------
# 2) 反向對照組 A：粉絲版套同一張表，數字不准變壞（它本來 50/50=100%）
# --------------------------------------------------------------------------
def section_2_reverse_fan(roster, stoplist):
    lines.append("\n=== 2) 反向對照組 A：粉絲版套同一張表，正確率不准變壞 ===")
    for pair in pna.PAIRS:
        ep = pair["ep"]
        fan_text_raw = (REPO / pair["fan"]).read_text(encoding="utf-8")
        self_text_raw = (REPO / pair["self"]).read_text(encoding="utf-8")
        fan_text_fixed = it.normalize_transcript_text(fan_text_raw)

        r_before = pna.score_pair(ep, fan_text_raw, self_text_raw, roster, stoplist)
        r_after = pna.score_pair(ep, fan_text_fixed, self_text_raw, roster, stoplist)
        fb = r_before["versions"]["粉絲版"]
        fa = r_after["versions"]["粉絲版"]
        check(f"{ep}: 粉絲版命中數不變（本來就 100%，不准變壞）", fa["hit"] == fb["hit"],
              f"{fb['hit']} -> {fa['hit']}")
        check(f"{ep}: 粉絲版漏不變", fa["miss"] == fb["miss"], f"{fb['miss']} -> {fa['miss']}")
        check(f"{ep}: 粉絲版幻覺不變", fa["hallu"] == fb["hallu"], f"{fb['hallu']} -> {fa['hallu']}")


# --------------------------------------------------------------------------
# 3) 反向對照組 B/C：全庫 700+ 檔逐字稿套改字表，只准動該動的 5 個檔案，
#    「孟公」暱稱與其他正常字串一個字都不准被改。
#
#    「孟公」暱稱的保護判定不能用天真的 ``(?<!我是)孟公``：規則 2 有一個變體
#    「孫孟公」（EP682），整串會被規則 2 吃掉，但「孟公」子字串前一個字是「孫」不是
#    「我是」，天真判定會誤以為那是被誤傷的暱稱。正確做法是先跑一次規則 2，記錄它
#    實際吃掉的字元範圍（span），只把「落在這個範圍之外」的「孟公」算進暱稱母體。
# --------------------------------------------------------------------------
MENTION_PATTERN = re.compile("孟公")


def _consumed_spans(text: str, rule2_pattern: re.Pattern) -> list[tuple[int, int]]:
    return [m.span() for m in rule2_pattern.finditer(text)]


def _in_any_span(pos_start: int, pos_end: int, spans: list[tuple[int, int]]) -> bool:
    return any(s <= pos_start and pos_end <= e for s, e in spans)


def section_3_corpus_wide():
    lines.append("\n=== 3) 反向對照組 B/C：全庫逐字稿套改字表（只讀，記憶體內比對，不寫檔）===")
    roots = [REPO / "transcripts", REPO / "docs" / "pairing_samples"]
    files: list[Path] = []
    for r in roots:
        if r.exists():
            files.extend(sorted(r.rglob("*.md")))
    check("全庫掃描檔案數 > 0（母體 0 不算通過）", len(files) > 0, f"n={len(files)}")

    expected_touched = {
        (REPO / "transcripts" / "independent_superseded" / "EP681_再一次相信真愛存在的機會.md").resolve(),
        (REPO / "transcripts" / "independent_superseded" / "EP682_魂系 everywhere.md").resolve(),
        (REPO / "transcripts" / "independent_superseded" / "EP683_一個月前的自己對未來寄予厚望.md").resolve(),
        (REPO / "transcripts" / "independent_superseded" / "EP684_終於可以喘一下.md").resolve(),
        (REPO / "docs" / "pairing_samples" / "EP687_independent.md").resolve(),
    }

    rules = it.load_fixed_term_corrections()
    rule2_pattern = next(p for p, repl, _ in rules if repl == "謝孟恭")

    touched_files = []
    nickname_before_total = 0  # 「孟公」暱稱：落在規則2替換範圍之外的出現次數
    nickname_after_total = 0
    correct_terms_untouched_before = {"股癌": 0, "謝孟恭": 0, "聯準會": 0}
    correct_terms_untouched_after = {"股癌": 0, "謝孟恭": 0, "聯準會": 0}
    correct_terms_touched_before = {"股癌": 0, "謝孟恭": 0, "聯準會": 0}
    correct_terms_touched_after = {"股癌": 0, "謝孟恭": 0, "聯準會": 0}
    mtimes_before = {}
    n_scanned = 0

    for f in files:
        mtimes_before[f] = (f.stat().st_mtime_ns, f.stat().st_size)
        raw = f.read_text(encoding="utf-8")
        n_scanned += 1
        # 只跑固定名詞改字，隔開臺→台那一步，這裡只在乎「改字表」本身的效果。
        fixed = raw
        for pattern, replacement, _reason in rules:
            fixed = pattern.sub(replacement, fixed)
        is_touched = fixed != raw
        if is_touched:
            touched_files.append(f.resolve())

        # 「孟公」暱稱母體：規則2實際吃掉的範圍之外的出現次數，改前只能在原文算，
        # 改後的文字裡已經沒有被規則2吃掉的那個範圍了，所以改後直接數全部「孟公」
        # 出現次數即可（規則2消耗掉的那些已經不在文字裡，不會被算進去）。
        spans = _consumed_spans(raw, rule2_pattern)
        for m in MENTION_PATTERN.finditer(raw):
            if not _in_any_span(*m.span(), spans):
                nickname_before_total += 1
        nickname_after_total += len(MENTION_PATTERN.findall(fixed))

        before_bucket = correct_terms_touched_before if is_touched else correct_terms_untouched_before
        after_bucket = correct_terms_touched_after if is_touched else correct_terms_untouched_after
        for term in before_bucket:
            before_bucket[term] += raw.count(term)
            after_bucket[term] += fixed.count(term)

    check("全庫掃描母體 > 0", n_scanned > 0, f"n_scanned={n_scanned}")
    touched_set = set(touched_files)
    unexpected = touched_set - expected_touched
    missing = expected_touched - touched_set
    check("只有預期的 5 個自建版檔案被改到，其餘 696+ 個檔案（含全部粉絲版）一個字都沒變",
          not unexpected, f"意外被改到：{sorted(str(p) for p in unexpected)}")
    check("5 個目標自建版檔案全部確實被改到（不是誤判成 0 命中就綠燈）",
          not missing, f"沒被改到：{sorted(str(p) for p in missing)}")
    check("touched_files 數 == 5", len(touched_files) == 5, f"n={len(touched_files)}")

    check("留言引用裡的『孟公』暱稱（規則2替換範圍以外的『孟公』）在全庫裡一個都沒被動到",
          nickname_after_total == nickname_before_total,
          f"改前 {nickname_before_total} -> 改後 {nickname_after_total}")
    check("『孟公』暱稱母體 > 0（不然上面那條反向測試沒有意義）",
          nickname_before_total > 0, f"n={nickname_before_total}")

    for term in correct_terms_untouched_before:
        b, a = correct_terms_untouched_before[term], correct_terms_untouched_after[term]
        check(f"未被動到的 696+ 檔裡，本來就寫對的『{term}』出現次數不變（正確寫法不准被動到）",
              a == b, f"改前 {b} -> 改後 {a}")
        check(f"『{term}』（未觸動檔案）母體 > 0", b > 0, f"n={b}")
    for term in correct_terms_touched_before:
        b, a = correct_terms_touched_before[term], correct_terms_touched_after[term]
        lines.append(f"  [info] 5 個目標檔案裡『{term}』出現次數：改前 {b} -> 改後 {a}"
                      f"（預期上升，是改字表把訛寫修對後新增的正確寫法）")
        check(f"5 個目標檔案裡『{term}』出現次數不減少（新增沒問題，變少代表改壞了）",
              a >= b, f"改前 {b} -> 改後 {a}")

    # 檔案本身不准被動：重讀一次 mtime/size，證明我們全程沒有 write()。
    unchanged_on_disk = True
    for f, (mt, sz) in mtimes_before.items():
        cur = f.stat()
        if (cur.st_mtime_ns, cur.st_size) != (mt, sz):
            unchanged_on_disk = False
            lines.append(f"  ⚠ 檔案被動到：{f}")
    check("逐字稿檔案本身（磁碟上）一個位元組都沒被本腳本動到", unchanged_on_disk)

    return touched_files


def main():
    print("=== 固定名詞改字表自測（正向 + 反向對照組）===\n")
    rules = section_0_table_sanity()
    roster = pna.load_roster()
    stoplist = pna.load_hallu_stoplist()

    section_1_forward(roster, stoplist)
    section_2_reverse_fan(roster, stoplist)
    section_3_corpus_wide()

    print("\n".join(lines))
    print(f"\n=== 結果：{total_checks} 條斷言、{total_checks - len(failures)} 通過、"
          f"{len(failures)} 條失敗 ===")
    if failures:
        print("FAILED: " + "; ".join(failures))
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
