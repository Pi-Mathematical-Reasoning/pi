"""The report of a Lean run: what was run, how it went, and what a person should read."""

import copy
import json

from pi.report import build_report
from tests.test_report import RUN as ANSWER_RUN


def result(id, verdict, subject, lean, elapsed=10.0):
    return {
        "id": id,
        "subject": subject,
        "level": None,
        "verdict": verdict,
        "answer": None,
        "response": None,
        "prompt_tokens": 30,
        "cached_prompt_tokens": 0,
        "output_tokens": 100,
        "output_tokens_per_second": 20.0,
        "load_seconds": 1.5,
        "elapsed_seconds": elapsed,
        "proof": None if lean is None else "by simp",
        "lean": lean,
    }


def lean_record(reason, compile_seconds, judge_seconds, flags=()):
    return {
        "reason": reason,
        "exit_code": 0,
        "messages": [],
        "judge": [],
        "axioms": [],
        "flags": list(flags),
        "compile_seconds": compile_seconds,
        "judge_seconds": judge_seconds,
    }


RESULTS = [
    result("fixture_add_zero", "proved", "algebra", lean_record(None, 5.0, 2.0, ["#eval"])),
    result("fixture_bad_step", "failed", "number_theory", lean_record("lean_error", 250.0, None)),
    result("fixture_long_proof", "cut_off", "algebra", None, elapsed=60.0),
]

RUN = {
    **copy.deepcopy(ANSWER_RUN),
    "benchmark": {
        "name": "minif2f-dev",
        "kind": "lean",
        "repository": "https://github.com/example/miniF2F-lean4",
        "commit": "f0a20e14c1ee" + "0" * 28,
        "file": "Valid.lean",
        "sha256": "ab" * 32,
        "subset": True,
        "scored": True,
        "ids": [r["id"] for r in RESULTS],
    },
    "grader": {
        "lean_rules": 1,
        "judge_repository": "https://github.com/example/SafeVerify",
        "judge_commit": "b291b588a539" + "0" * 28,
        "allowed_axioms": ["propext", "Classical.choice", "Quot.sound"],
    },
    "lean": {
        "toolchain": "leanprover/lean4:v4.9.0",
        "lean_version": "Lean (version 4.9.0)",
        "files": {"Valid.lean": "ab" * 32},
        "options": ["maxHeartbeats=400000"],
        "instruction": "Prove it.",
        "compile_time_limit_seconds": 300,
        "judge_time_limit_seconds": 300,
    },
}


def save(tmp_path, run=RUN, results=RESULTS):
    (tmp_path / "run.json").write_text(json.dumps(run))
    (tmp_path / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in results))
    return build_report(tmp_path)


def test_the_title_counts_proved_theorems(tmp_path):
    report = save(tmp_path)

    assert report.splitlines()[0] == "# minif2f-dev: 1 of 3 proved (33.3%)"
    assert "A frozen subset of 3 theorems." in report


def test_a_run_of_the_whole_file_says_so(tmp_path):
    run = {**RUN, "benchmark": {**RUN["benchmark"], "subset": False}}

    assert "All 3 theorems in the file." in save(tmp_path, run)


def test_says_what_counts_and_tables_every_verdict_and_reason(tmp_path):
    report = save(tmp_path)

    assert "Only `proved` counts as solved." in report
    for line in ("| proved | 1 |", "| failed | 1 |", "| missing | 0 |", "| cut_off | 1 |"):
        assert line in report
    assert "| timed_out | 0 |" in report
    assert "| lean_error | 1 |" in report
    assert "| sorry |" not in report


def test_names_the_lean_project_the_judge_and_the_limits(tmp_path):
    report = save(tmp_path)

    assert "`f0a20e14c1ee`" in report
    assert "SafeVerify `b291b588a539`" in report
    assert "300 s per check step" in report
    assert "`miniF2F-lean4` at `f0a20e14c1ee`, file checksum `abababababab`" in report
    assert "`leanprover/lean4:v4.9.0`" in report and "`maxHeartbeats=400000`" in report
    assert "axioms `propext`, `Classical.choice`, `Quot.sound`" in report


def test_names_both_limits_when_they_differ(tmp_path):
    run = {**RUN, "lean": {**RUN["lean"], "judge_time_limit_seconds": 120}}

    report = save(tmp_path, run)

    assert "300 s compile limit, 120 s judge limit" in report
    assert "per check step" not in report


def test_reports_the_time_checks_took(tmp_path):
    report = save(tmp_path)

    assert "| Compile time per check | mean 127.5 s, median 127.5 s, longest 250.0 s |" in report
    assert "| Judge time per check | mean 2.0 s, median 2.0 s, longest 2.0 s |" in report


def test_counts_checks_that_came_within_a_fifth_of_a_limit(tmp_path):
    assert "| Checks within 20% of a limit | 1 |" in save(tmp_path)


def test_breaks_the_score_down_by_family(tmp_path):
    report = save(tmp_path)

    assert "## By family" in report
    assert "| algebra | 1 | 2 |" in report
    assert "| number_theory | 0 | 1 |" in report


def test_lists_accepted_proofs_that_run_code_at_compile_time(tmp_path):
    report = save(tmp_path)

    assert "## Flagged proofs" in report
    assert "| fixture_add_zero | `#eval` |" in report


def test_flagged_proofs_say_none_when_there_are_none(tmp_path):
    results = [result("fixture_add_zero", "proved", "algebra", lean_record(None, 5.0, 2.0))]
    run = {**RUN, "benchmark": {**RUN["benchmark"], "ids": ["fixture_add_zero"]}}

    report = save(tmp_path, run, results)

    assert "## Flagged proofs\n\nThese accepted proofs" in report
    assert report.split("## Flagged proofs")[1].split("## Unsolved")[0].strip().endswith("None.")
    assert report.endswith("## Unsolved\n\nNone.\n")
    assert "## Failure reasons\n\nNone." in report


def test_the_unsolved_table_gives_the_reason(tmp_path):
    report = save(tmp_path)

    assert "| fixture_bad_step | failed | lean_error |" in report
    assert "| fixture_long_proof | cut_off |  |" in report
    assert "| fixture_add_zero | proved |" not in report


def test_a_theorem_id_cannot_break_a_table_cell(tmp_path):
    results = [result("a|b", "failed", "x|y", lean_record("sorry", None, None))]
    run = {**RUN, "benchmark": {**RUN["benchmark"], "ids": ["a|b"]}}

    report = save(tmp_path, run, results)

    assert r"| a\|b | failed | sorry |" in report
    assert r"| x\|y | 0 | 1 |" in report


def test_a_run_with_no_results_yet_still_reports(tmp_path):
    run = {**RUN, "complete": False}

    report = save(tmp_path, run, [])

    assert "incomplete, 0 of 3 theorems attempted" in report
    assert "| Checks within 20% of a limit | 0 |" in report
    assert "Compile time per check" not in report


def test_an_interrupted_run_still_gives_the_notice_and_the_sections(tmp_path):
    report = save(tmp_path, {**RUN, "complete": False}, RESULTS[:2])

    assert report.startswith("# minif2f-dev: incomplete, 2 of 3 theorems attempted\n")
    assert "1 of the 2 theorems attempted so far are proved" in report
    assert "## Unsolved" in report


def test_the_same_files_always_give_the_same_report(tmp_path):
    assert save(tmp_path) == build_report(tmp_path)
