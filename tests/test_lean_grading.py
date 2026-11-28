"""The Lean rules: pulling a proof out of a reply, building the file, reading the judge."""

import json
from pathlib import Path

import pytest

from pi.lean_grading import assemble, extract_code, flags, judgement, reference_source
from pi.lean_project import Finished
from pi.lean_statements import Theorem

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


def test_a_theorem_with_a_longer_name_is_not_taken_for_it():
    longer = FULL.replace("fixture_add_zero", "fixture_add_zero'")
    assert assemble(T, longer).startswith("import Mathlib\n\n" + T.statement + " := by\n")


def test_the_reference_is_the_statement_closed_with_sorry():
    assert reference_source(T) == "import Mathlib\n\n" + T.statement + " := by\n  sorry\n"


def test_flags_compile_time_commands_and_not_words_that_contain_them():
    assert flags('#eval IO.println "x"\nrun_cmd pure ()') == ["#eval", "run_cmd", "IO."]
    assert flags("-- elaborate the macroscopic syntaxes\nsimp") == []


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
