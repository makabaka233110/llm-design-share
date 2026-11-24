"""Pure functions of the experiment runner (no model, no index)."""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "eval"))
import run  # noqa: E402


def test_cer_ignores_punctuation_and_counts_characters():
    assert run.cer("RDB 快照，AOF 日志。", "rdb快照aof日志") == 0
    assert run.cer("沉没成本", "沉默成本") == 0.25
    assert run.cer("ab", "") == 1


def test_balanced_subset_is_fixed_and_balanced():
    cases = [{"id": f"{d}{i}{t}", "domain": d, "answer_type": t} for d in "abcd" for i in range(10) for t in ("strong", "flawed")]
    s1, s2 = run.balanced_subset(cases, 40), run.balanced_subset(list(reversed(cases)), 40)
    assert [c["id"] for c in s1] == [c["id"] for c in s2]          # depends on metadata only
    assert set(Counter((c["domain"], c["answer_type"]) for c in s1).values()) == {5}


def test_kappa():
    assert run.kappa(["1", "2", "1", "2"], ["1", "2", "1", "2"]) == 1
    assert run.kappa(["1", "2", "", "2"], ["2", "1", "1", ""]) < 0
