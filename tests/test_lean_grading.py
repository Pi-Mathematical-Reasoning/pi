"""The Lean rules: pulling a proof out of a reply, building the file, reading the judge."""

import json
from pathlib import Path

import pytest

from pi.lean_grading import (
    LEAN_RULES_VERSION,
    MESSAGE_CAP,
    LeanGrade,
    Limits,
    assemble,
    check,
    extract_code,
    flags,
    judgement,
    lean_grader_version,
    reference_source,
)
from pi.lean_project import BenchmarkError, Finished, LeanBenchmark
from pi.lean_statements import Theorem
from tests.lean_fake import FakeRunner

CASES = Path(__file__).parent / "lean_cases"
ALLOWED = ["propext", "Classical.choice", "Quot.sound"]

T = Theorem(
    "fixture_add_zero",
    "import Mathlib\n",
    "theorem fixture_add_zero (a : ℕ) : a + 0 = a",
    None,
    None,
    "other",
)
FULL = "theorem fixture_add_zero (a : ℕ) : a + 0 = a := by\n  simp"


def fenced(code, tag="lean4"):
    return f"Here it is.\n```{tag}\n{code}\n```\n"


def captured(case):
    folder = CASES / case
    stderr = (folder / "judge.stderr").read_text()
    exit_code = int((folder / "judge.exit").read_text())
    saved_file = folder / "judge.json"
    saved = json.loads(saved_file.read_text()) if saved_file.exists() else None
    return Finished(exit_code, "", stderr, 0.0), saved, _NAMES.get(case, "pi_case")


_NAMES = {"replace_axiom": "efsq", "add_false_env": "falseThm"}


def outcome(axioms, failure=None, solution=True):
    info = {"constInfo": {"kind": "theorem"}, "axioms": axioms}
    return {"targetInfo": info, "solutionInfo": info if solution else None, "failureMode": failure}


PASSING_OUTCOME = [["pi_case", outcome(["propext"])]]
PASSED = Finished(0, "", "SafeVerify check passed.\n", 1.0)


def test_takes_the_last_lean_block():
    assert extract_code(fenced("first") + fenced(FULL, "lean")) == FULL


def test_takes_an_untagged_block():
    assert extract_code(fenced(FULL, "")) == FULL


def test_skips_a_later_block_in_another_language():
    reply = fenced(FULL) + fenced("print(1)", "python") + fenced("Done.", "text")
    assert extract_code(reply) == FULL


@pytest.mark.parametrize("reply", ["No code.", "```lean4\n" + FULL, fenced("   \n")])
def test_no_closed_block_with_code_in_it_is_no_proof(reply):
    assert extract_code(reply) is None


def test_a_block_that_declares_the_theorem_follows_the_header():
    assert assemble(T, FULL) == "import Mathlib\n\n" + FULL + "\n"


def test_leading_imports_are_dropped_and_nothing_else():
    code = "import Mathlib\nimport Aesop\n\nopen Real\n\n" + FULL
    assert assemble(T, code) == "import Mathlib\n\nopen Real\n\n" + FULL + "\n"


def test_a_lemma_of_the_same_name_counts_as_declaring_it():
    assert assemble(T, FULL.replace("theorem", "lemma", 1)).count("fixture_add_zero") == 1


@pytest.mark.parametrize("body", ["simp", "by\n  simp", ":= by\n  simp", "  simp"])
def test_a_proof_only_block_is_placed_under_the_original_statement(body):
    assert assemble(T, body) == "import Mathlib\n\n" + T.statement + " := by\n  simp\n"


BODY = "import Mathlib\n\n" + T.statement + " := by\n  intro x\n  simp\n"


@pytest.mark.parametrize(
    "body", ["  intro x\n  simp", "by\n  intro x\n  simp", ":= by\n  intro x\n  simp"]
)
def test_an_evenly_indented_proof_body_keeps_its_lines_aligned(body):
    assert assemble(T, body) == BODY


def test_relative_indentation_in_a_proof_body_is_kept():
    expected = "import Mathlib\n\n" + T.statement + " := by\n  intro x\n    simp\n"
    assert assemble(T, "intro x\n  simp") == expected


def test_a_continuation_line_stays_under_the_tactic_it_continues():
    expected = "import Mathlib\n\n" + T.statement + " := by\n  simp [foo]\n    <;> linarith\n"
    assert assemble(T, "by simp [foo]\n  <;> linarith") == expected


def test_an_indented_full_theorem_is_recognised_and_dedented():
    indented = "\n".join("  " + line for line in FULL.splitlines())
    assert assemble(T, indented) == "import Mathlib\n\n" + FULL + "\n"


def test_an_empty_proof_body_ends_with_one_newline():
    assert assemble(T, ":= by") == "import Mathlib\n\n" + T.statement + " := by\n"


def test_an_indented_proof_body_survives_extraction():
    assert assemble(T, extract_code(fenced("  intro x\n  simp"))) == BODY


def test_a_theorem_with_a_longer_name_is_not_taken_for_it():
    longer = FULL.replace("fixture_add_zero", "fixture_add_zero'")
    assert assemble(T, longer).startswith("import Mathlib\n\n" + T.statement + " := by\n")


def test_the_reference_is_the_statement_closed_with_sorry():
    assert reference_source(T) == "import Mathlib\n\n" + T.statement + " := by\n  sorry\n"


def test_flags_compile_time_commands_and_not_words_that_contain_them():
    assert flags('#eval IO.println "x"\nrun_cmd pure ()') == ["#eval", "run_cmd", "IO."]
    assert flags("-- elaborate the macroscopic syntaxes\nsimp") == []


def test_flags_the_meta_commands_and_unsafe_in_the_list_s_order():
    code = "unsafe def f := 1\nrun_meta pure ()\nrun_elab pure ()\nrun_tac simp\nrun_cmd pure ()"
    assert flags(code) == ["run_cmd", "run_tac", "run_elab", "run_meta", "unsafe"]
    assert flags("simp [unsafeCast, my_unsafe, Foo.unsafe, run_tactic, run_meta']") == []


def test_flags_the_rule_and_category_commands_as_themselves():
    code = "elab_rules : tactic\nmacro_rules\ndeclare_syntax_cat foo"
    assert flags(code) == ["elab_rules", "macro_rules", "declare_syntax_cat"]


def test_flags_io_only_when_it_starts_a_name():
    assert flags("simp [MyIO.x, Foo.IO.y, RIO.z]") == []


EXPECTED = {
    "valid": None,
    "sorry": "sorry",
    "helper_sorry": "sorry",
    "helper_axiom": "axioms",
    "unused_sorry": "sorry",
    "weakened": "statement_changed",
    "renamed": "statement_changed",
    "reformatted": None,
    "native_decide": "kernel_rejected",
    "fake_success_exit": "statement_changed",
    "replace_axiom": "kernel_rejected",
    "add_false_env": "kernel_rejected",
}


@pytest.mark.parametrize("case, reason", EXPECTED.items())
def test_reads_each_captured_judgement(case, reason):
    assert judgement(*captured(case)[:2], ALLOWED, captured(case)[2])[0] == reason


@pytest.mark.parametrize("case", ["add_false_env", "replace_axiom"])
def test_an_exploit_is_never_a_pass(case):
    done, saved, name = captured(case)
    assert judgement(done, saved, ALLOWED, name)[0] is not None


@pytest.mark.parametrize("case", ["skip_kernel", "renamed_binders"])
def test_recorded_cases_the_judge_accepted_pass(case):
    done, saved, name = captured(case)
    assert judgement(done, saved, ALLOWED, name)[0] is None


def test_a_passing_case_reports_the_submission_axioms():
    done, saved, name = captured("valid")
    assert judgement(done, saved, ALLOWED, name)[1] == saved[0][1]["solutionInfo"]["axioms"]


def test_a_judge_killed_at_its_limit_is_a_timeout():
    assert judgement(Finished(None, "", "", 9.0), None, ALLOWED, "pi_case")[0] == "check_timed_out"


def test_success_without_a_saved_outcome_is_a_judge_error():
    assert judgement(PASSED, None, ALLOWED, "pi_case")[0] == "judge_error"


def test_printed_success_with_a_failing_exit_is_a_judge_error():
    done = Finished(1, "Finished.\n", "", 1.0)
    assert judgement(done, PASSING_OUTCOME, ALLOWED, "pi_case")[0] == "judge_error"


def test_a_passing_outcome_passes():
    assert judgement(PASSED, PASSING_OUTCOME, ALLOWED, "pi_case") == (None, ["propext"])


def test_an_axiom_outside_the_allowlist_fails_even_if_the_judge_passed_it():
    saved = [["pi_case", outcome(["propext", "Lean.ofReduceBool"])]]
    assert judgement(PASSED, saved, ALLOWED, "pi_case")[0] == "axioms"


@pytest.mark.parametrize(
    "saved",
    [
        {},
        "text",
        [],
        ["pi_case"],
        [["pi_case"]],
        [["pi_case", "x"]],
        [["pi_case", {}]],
        [["pi_case", {"failureMode": None}]],
        [["pi_case", {"solutionInfo": {"axioms": ["propext"]}}]],
        [["pi_case", outcome(["propext"], solution=False)]],
        [["pi_case", {"failureMode": None, "solutionInfo": {"axioms": "propext"}}]],
        [["pi_case", outcome([1])]],
        [["other", outcome(["propext"])]],
        [["pi_case", outcome(["propext"], failure="strange")]],
        [["pi_case", outcome(["propext"]), "extra"]],
        PASSING_OUTCOME + [["pi_helper", outcome(["propext"], failure="strange")]],
        PASSING_OUTCOME + [["pi_helper", {}]],
    ],
)
def test_a_malformed_saved_outcome_is_a_judge_error_never_a_pass(saved):
    assert judgement(PASSED, saved, ALLOWED, "pi_case")[0] == "judge_error"


def test_a_failure_mode_of_another_kind_object_is_a_changed_statement():
    saved = [["pi_case", outcome(["propext"], failure={"kind": "def"})]]
    assert judgement(Finished(1, "", "", 1.0), saved, ALLOWED, "pi_case")[0] == "statement_changed"


def test_a_kernel_message_wins_over_a_saved_pass():
    done = Finished(1, "", "uncaught exception: (kernel) boom", 1.0)
    assert judgement(done, PASSING_OUTCOME, ALLOWED, "pi_case")[0] == "kernel_rejected"
    done = Finished(1, "", "kernel verification failed for 'x'", 1.0)
    assert judgement(done, None, ALLOWED, "pi_case")[0] == "kernel_rejected"


# Checking one reply: the two compiles and the judge, run by a stand-in for Lean.

LIMITS = Limits(300, 300)
OK = Finished(0, "", "", 1.5)
JUDGED = Finished(0, "", "SafeVerify check passed.\n", 3.0)
PASSING = [["fixture_add_zero", outcome(["propext"])]]


def passing_runner(**changes):
    values = {"compiles": [OK, Finished(0, "", "", 2.0)], "judges": [JUDGED], "saved": [PASSING]}
    return FakeRunner(**{**values, **changes})


def test_a_reply_without_code_is_missing_and_runs_nothing():
    runner = FakeRunner()
    assert check(T, "I could not prove it.", runner, LIMITS, ALLOWED) == LeanGrade(
        "missing", None, None, None
    )
    assert runner.calls == []


def test_a_proof_the_judge_passes_is_proved_with_its_axioms_flags_and_times():
    code = "#eval 1\n\n" + FULL
    runner = passing_runner()
    grade = check(T, fenced(code), runner, LIMITS, ALLOWED)
    assert grade.verdict == "proved"
    assert grade.proof == code
    assert grade.lean == {
        "reason": None,
        "exit_code": 0,
        "messages": "",
        "judge": {"exit_code": 0, "outcome": PASSING, "stderr": "SafeVerify check passed.\n"},
        "axioms": ["propext"],
        "flags": ["#eval"],
        "compile_seconds": 2.0,
        "judge_seconds": 3.0,
    }
    assert runner.calls == [
        ("compile", "Reference.lean", "Reference.olean", 300),
        ("compile", "Submission.lean", "Submission.olean", 300),
        ("judge", "Reference.olean", "Submission.olean", "judge.json", 300),
    ]


def test_each_step_runs_under_its_own_limit():
    runner = passing_runner()
    check(T, fenced(FULL), runner, Limits(5, 7), ALLOWED)
    assert [call[-1] for call in runner.calls] == [5, 5, 7]


def test_a_compile_error_fails_without_asking_the_judge():
    error = '{"severity": "error", "data": "unknown tactic"}\n'
    runner = FakeRunner(compiles=[OK, Finished(1, error, "", 2.0)])
    grade = check(T, fenced(FULL), runner, LIMITS, ALLOWED)
    assert (grade.verdict, grade.lean["reason"]) == ("failed", "lean_error")
    assert (grade.lean["exit_code"], grade.lean["messages"]) == (1, error)
    assert grade.lean["judge"] is None and grade.lean["judge_seconds"] is None
    assert grade.lean["axioms"] == []
    assert runner.judge_calls() == []


def test_an_error_message_fails_even_when_lean_exits_zero():
    stdout = 'not json\n{"severity": "warning"}\n{"severity": "error", "data": "x"}\n'
    runner = FakeRunner(compiles=[OK, Finished(0, stdout, "", 2.0)])
    grade = check(T, fenced(FULL), runner, LIMITS, ALLOWED)
    assert grade.lean["reason"] == "lean_error"
    assert runner.judge_calls() == []


def test_lines_that_are_not_error_messages_do_not_fail_a_compile():
    stdout = 'severity: error\n{"severity": "warning", "data": "declaration uses sorry"}\n[1]\n'
    runner = passing_runner(compiles=[OK, Finished(0, stdout, "", 2.0)])
    grade = check(T, fenced(FULL), runner, LIMITS, ALLOWED)
    assert grade.verdict == "proved"


def test_a_compile_killed_at_its_limit_is_a_timeout():
    runner = FakeRunner(compiles=[OK, Finished(None, "", "", 300.0)])
    grade = check(T, fenced(FULL), runner, LIMITS, ALLOWED)
    assert (grade.verdict, grade.lean["reason"]) == ("failed", "check_timed_out")
    assert grade.lean["exit_code"] is None and grade.lean["compile_seconds"] == 300.0
    assert runner.judge_calls() == []


@pytest.mark.parametrize(
    "done",
    [
        Finished(1, "", "boom", 1.0),
        Finished(0, '{"severity": "error", "data": "boom"}\n', "", 1.0),
        Finished(None, "boom", "", 300.0),  # killed at its limit
    ],
)
def test_a_reference_that_does_not_compile_stops_the_check_without_a_verdict(done):
    runner = FakeRunner(compiles=[done])
    with pytest.raises(BenchmarkError) as raised:
        check(T, fenced(FULL), runner, LIMITS, ALLOWED)
    message = str(raised.value)
    assert message.startswith("fixture_add_zero: ")
    assert "pi's own file" in message and "boom" in message
    assert "pi lean-setup" in message and "run the same command again" in message
    assert [call[1] for call in runner.calls] == ["Reference.lean"]
    assert runner.work is not None and not runner.work.exists()


def test_a_reference_compile_that_leaves_no_olean_stops_the_check_without_a_verdict():
    runner = FakeRunner(compiles=[OK], on_compile=lambda source, olean: olean.unlink())
    with pytest.raises(BenchmarkError, match="(?s)fixture_add_zero: .*no .olean.*pi lean-setup"):
        check(T, fenced(FULL), runner, LIMITS, ALLOWED)
    assert [call[1] for call in runner.calls] == ["Reference.lean"]


def test_the_reference_error_shows_the_end_of_lean_s_output():
    lines = "".join(f"line {n}\n" for n in range(100))
    runner = FakeRunner(compiles=[Finished(1, lines, "", 1.0)])
    with pytest.raises(BenchmarkError) as raised:
        check(T, fenced(FULL), runner, LIMITS, ALLOWED)
    assert "line 99" in str(raised.value) and "line 50\n" not in str(raised.value)


def _rewrite_reference(source, olean):
    if source.name == "Submission.lean":
        (olean.parent / "Reference.olean").write_bytes(b"a different reference")


def test_a_reference_that_changed_before_the_judge_ran_is_a_judge_error():
    runner = passing_runner(on_compile=_rewrite_reference)
    grade = check(T, fenced(FULL), runner, LIMITS, ALLOWED)
    assert (grade.verdict, grade.lean["reason"]) == ("failed", "judge_error")
    assert runner.judge_calls() == []


def test_a_reference_removed_before_the_judge_ran_is_a_judge_error():
    def remove(source, olean):
        if source.name == "Submission.lean":
            (olean.parent / "Reference.olean").unlink()

    runner = passing_runner(on_compile=remove)
    assert check(T, fenced(FULL), runner, LIMITS, ALLOWED).lean["reason"] == "judge_error"
    assert runner.judge_calls() == []


def _spoil(path):
    """Leave something at the path that cannot be read as a file."""
    path.unlink()
    path.mkdir()


@pytest.mark.parametrize("spoil", ["directory", "unreadable"])
def test_a_reference_spoiled_by_the_submission_s_compile_is_a_judge_error(spoil):
    def spoiled(source, olean):
        if source.name == "Submission.lean":
            reference = olean.parent / "Reference.olean"
            _spoil(reference) if spoil == "directory" else reference.chmod(0)

    runner = passing_runner(on_compile=spoiled)
    grade = check(T, fenced(FULL), runner, LIMITS, ALLOWED)
    assert (grade.verdict, grade.lean["reason"]) == ("failed", "judge_error")
    assert runner.judge_calls() == []


def test_a_reference_spoiled_while_the_judge_ran_is_a_judge_error():
    runner = passing_runner(on_judge=lambda reference, submission, saved: _spoil(reference))
    grade = check(T, fenced(FULL), runner, LIMITS, ALLOWED)
    assert (grade.verdict, grade.lean["reason"]) == ("failed", "judge_error")
    assert len(runner.judge_calls()) == 1


def test_a_reference_unreadable_after_its_own_compile_stops_the_check_without_a_verdict():
    runner = FakeRunner(compiles=[OK], on_compile=lambda source, olean: _spoil(olean))
    with pytest.raises(BenchmarkError, match="(?s)fixture_add_zero: .*pi lean-setup"):
        check(T, fenced(FULL), runner, LIMITS, ALLOWED)
    assert [call[1] for call in runner.calls] == ["Reference.lean"]


@pytest.mark.parametrize("saved", [None, b'[["fixture_add_zero", {', b"\xff\xfe"])
def test_a_judge_pass_without_a_readable_saved_outcome_is_a_judge_error(saved):
    grade = check(T, fenced(FULL), passing_runner(saved=[saved]), LIMITS, ALLOWED)
    assert (grade.verdict, grade.lean["reason"]) == ("failed", "judge_error")
    assert grade.lean["judge"]["outcome"] is None


def test_a_judge_failure_fails_with_its_reason():
    sorry = [["fixture_add_zero", outcome(["sorryAx"], failure="axioms")]]
    runner = passing_runner(judges=[Finished(1, "", "", 3.0)], saved=[sorry])
    grade = check(T, fenced(FULL), runner, LIMITS, ALLOWED)
    assert (grade.verdict, grade.lean["reason"]) == ("failed", "sorry")
    assert grade.lean["axioms"] == ["sorryAx"]


@pytest.mark.parametrize("saved", [PASSING, None])
def test_a_judge_killed_by_a_signal_is_a_judge_error(saved):
    runner = passing_runner(judges=[Finished(-9, "", "", 3.0)], saved=[saved])
    grade = check(T, fenced(FULL), runner, LIMITS, ALLOWED)
    assert (grade.verdict, grade.lean["reason"]) == ("failed", "judge_error")
    assert grade.lean["judge"]["exit_code"] == -9


def test_paths_under_the_home_directory_are_written_with_a_tilde(monkeypatch):
    home = str(Path.home())
    missing = f"object file {home}/x/Mathlib.olean of module Mathlib does not exist\n"
    runner = passing_runner(
        compiles=[OK, Finished(0, '{"severity": "warning"}\n', missing, 2.0)],
        judges=[Finished(1, "", missing, 3.0)],
    )
    grade = check(T, fenced(FULL), runner, LIMITS, ALLOWED)
    tilde = "object file ~/x/Mathlib.olean of module Mathlib does not exist\n"
    assert grade.lean["messages"] == '{"severity": "warning"}\n' + tilde
    assert grade.lean["judge"]["stderr"] == tilde


def test_saved_output_is_capped():
    runner = FakeRunner(compiles=[OK, Finished(1, "x" * 50_000, "", 2.0)])
    grade = check(T, fenced(FULL), runner, LIMITS, ALLOWED)
    assert len(grade.lean["messages"]) == MESSAGE_CAP


def test_the_judge_s_stderr_is_capped_and_stderr_follows_stdout():
    runner = passing_runner(
        compiles=[OK, Finished(0, "out\n", "err\n", 2.0)],
        judges=[Finished(0, "", "y" * 50_000, 3.0)],
    )
    grade = check(T, fenced(FULL), runner, LIMITS, ALLOWED)
    assert grade.lean["messages"] == "out\nerr\n"
    assert len(grade.lean["judge"]["stderr"]) == MESSAGE_CAP


def test_the_submission_is_what_assemble_built():
    runner = passing_runner()
    grade = check(T, fenced("simp"), runner, LIMITS, ALLOWED)
    assert grade.submission == assemble(T, "simp")
    assert runner.sources == {
        "Reference.lean": reference_source(T),
        "Submission.lean": grade.submission,
    }


def test_the_work_directory_is_removed_even_when_the_runner_raises():
    def explode(source, olean):
        raise RuntimeError("lean crashed")

    runner = FakeRunner(compiles=[OK], on_compile=explode)
    with pytest.raises(RuntimeError):
        check(T, fenced(FULL), runner, LIMITS, ALLOWED)
    assert runner.work is not None and not runner.work.exists()


def test_the_grader_version_names_the_rules_the_judge_and_the_allowlist():
    benchmark = LeanBenchmark(
        name="b",
        repository="https://example.com/p",
        commit="a" * 40,
        file="A.lean",
        theorems=1,
        shipped_proofs=(),
        lean_options=(),
        allowed_axioms=("propext", "Quot.sound"),
        judge_repository="https://example.com/j",
        judge_commit="b" * 40,
    )
    assert lean_grader_version(benchmark) == {
        "lean_rules": LEAN_RULES_VERSION,
        "judge_repository": "https://example.com/j",
        "judge_commit": "b" * 40,
        "allowed_axioms": ["propext", "Quot.sound"],
    }


def _plant_passing_outcome(source, olean):
    if source.name == "Submission.lean":
        (olean.parent / "judge.json").write_text(json.dumps(PASSING))


def test_a_judge_outcome_planted_before_the_judge_ran_is_a_judge_error():
    runner = passing_runner(on_compile=_plant_passing_outcome, saved=[None])
    grade = check(T, fenced(FULL), runner, LIMITS, ALLOWED)
    assert (grade.verdict, grade.lean["reason"]) == ("failed", "judge_error")
    assert runner.judge_calls() == []


@pytest.mark.parametrize("kind", ["directory", "symlink"])
def test_any_entry_at_the_judge_s_path_before_it_ran_is_a_judge_error(kind):
    def plant(source, olean):
        if source.name == "Submission.lean":
            path = olean.parent / "judge.json"
            path.mkdir() if kind == "directory" else path.symlink_to(olean.parent / "absent")

    runner = passing_runner(on_compile=plant)
    assert check(T, fenced(FULL), runner, LIMITS, ALLOWED).lean["reason"] == "judge_error"
    assert runner.judge_calls() == []


def test_a_reference_changed_while_the_judge_ran_is_a_judge_error():
    def rewrite(reference, submission, saved):
        reference.write_bytes(b"a different reference")

    runner = passing_runner(on_judge=rewrite)
    grade = check(T, fenced(FULL), runner, LIMITS, ALLOWED)
    assert (grade.verdict, grade.lean["reason"]) == ("failed", "judge_error")
    assert len(runner.judge_calls()) == 1


def test_a_clean_compile_that_left_no_submission_olean_is_a_judge_error():
    def remove(source, olean):
        if source.name == "Submission.lean":
            olean.unlink()

    runner = passing_runner(on_compile=remove)
    grade = check(T, fenced(FULL), runner, LIMITS, ALLOWED)
    assert (grade.verdict, grade.lean["reason"]) == ("failed", "judge_error")
    assert runner.judge_calls() == []
