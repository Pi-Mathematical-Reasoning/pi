"""A Lean benchmark through the run loop: Ollama and Lean both stood in for."""

import json

import pytest

from pi.config import LeanSettings
from pi.evaluation import EvaluationError, _progress, read_results
from pi.lean_evaluation import LeanTask, lean_prompt
from pi.lean_project import BenchmarkError, Finished, LeanBenchmark
from pi.lean_statements import Theorem
from pi.report import build_report
from tests.lean_fake import FakeRunner
from tests.test_evaluation import chats, evaluate

HEADER = "import Mathlib\n"
INSTRUCTION = "Prove it."
ENVIRONMENT = {
    "toolchain": "leanprover/lean4:v4.99.0",
    "lean_version": "Lean (version 4.99.0)",
    "files": {"Split.lean": "ab" * 32},
    "options": ["autoImplicit=false"],
}
SETTINGS = LeanSettings(INSTRUCTION, 11, 22)
BENCHMARK = LeanBenchmark(
    name="sample",
    repository="https://example.com/project",
    commit="c" * 40,
    file="Split.lean",
    theorems=3,
    shipped_proofs=(),
    lean_options=("autoImplicit=false",),
    allowed_axioms=("propext",),
    judge_repository="https://example.com/judge",
    judge_commit="d" * 40,
)


def theorem(name):
    return Theorem(name, HEADER, f"theorem {name} (a : ℕ) : a + 0 = a", None, None, "other")


ONE, TWO, THREE = (theorem(n) for n in ("fixture_add_zero", "fixture_second", "fixture_third"))


def proof(name):
    return f"Here.\n```lean4\ntheorem {name} (a : ℕ) : a + 0 = a := by\n  simp\n```\n"


def outcome(name):
    info = {"constInfo": {"kind": "theorem"}, "axioms": ["propext"]}
    return [[name, {"targetInfo": info, "solutionInfo": info, "failureMode": None}]]


OK = Finished(0, "", "", 1.0)
JUDGED = Finished(0, "", "SafeVerify check passed.\n", 2.0)


def proving_runner(*names):
    """A runner that accepts the proof of each named theorem, in turn."""
    return FakeRunner(
        compiles=[OK, OK] * len(names),
        judges=[JUDGED] * len(names),
        saved=[outcome(name) for name in names],
    )


def task_for(out, runner, **changes):
    values = {"environment": ENVIRONMENT, "settings": SETTINGS, "release": lambda: None}
    values.update(changes)
    return LeanTask(
        BENCHMARK, values["settings"], runner, values["environment"], out, values["release"]
    )


@pytest.fixture
def ollama(ollama):
    """The stand-in server: a proof of the first theorem, a failing one, and no code block."""
    ollama.replies = {
        lean_prompt(INSTRUCTION, ONE): {"content": proof(ONE.id)},
        lean_prompt(INSTRUCTION, TWO): {"content": proof(TWO.id)},
        lean_prompt(INSTRUCTION, THREE): {"content": "I cannot tell."},
    }
    return ollama


def run_lean(ollama, out, runner, **options):
    task = options.pop("task", None) or task_for(out, runner)
    options.setdefault("problems", [ONE, TWO, THREE])
    return evaluate(ollama, out, benchmark=BENCHMARK, task=task, **options)


def mixed_runner():
    """Accepts the first proof; compiles the second without error but then fails it."""
    return FakeRunner(
        compiles=[OK, OK, OK, Finished(1, "", "", 3.0)],
        judges=[JUDGED],
        saved=[outcome(ONE.id)],
    )


def test_a_theorem_is_sent_as_the_instruction_and_its_statement(ollama, tmp_path):
    run_lean(ollama, tmp_path / "run", proving_runner(ONE.id), problems=[ONE])

    assert chats(ollama)[0][0]["content"] == (
        "Prove it.\n\n```lean4\nimport Mathlib\n\n"
        "theorem fixture_add_zero (a : ℕ) : a + 0 = a := by\n```\n"
    )


def test_results_record_the_verdict_the_proof_and_what_lean_said(ollama, tmp_path):
    run_lean(ollama, tmp_path / "run", mixed_runner())

    results = read_results(tmp_path / "run")
    assert [r["verdict"] for r in results] == ["proved", "failed", "missing"]
    assert [r["answer"] for r in results] == [None, None, None]
    assert results[0]["proof"] == "theorem fixture_add_zero (a : ℕ) : a + 0 = a := by\n  simp"
    assert results[2]["proof"] is None
    assert [r["lean"] and r["lean"]["reason"] for r in results] == [None, "lean_error", None]
    assert results[2]["lean"] is None


def test_a_lean_result_has_the_proof_and_lean_after_the_metrics(ollama, tmp_path):
    run_lean(ollama, tmp_path / "run", mixed_runner(), problems=[ONE])

    (result,) = read_results(tmp_path / "run")
    assert list(result)[-4:] == ["metrics", "proof", "lean", "discarded_attempts"]


def test_an_accepted_proof_is_saved_as_a_file_and_no_other_is(ollama, tmp_path):
    out = tmp_path / "run"
    run_lean(ollama, out, mixed_runner())

    assert [p.name for p in (out / "proofs").iterdir()] == ["fixture_add_zero.lean"]
    saved = (out / "proofs/fixture_add_zero.lean").read_text(encoding="utf-8")
    assert saved == "import Mathlib\n\ntheorem fixture_add_zero (a : ℕ) : a + 0 = a := by\n  simp\n"


def test_a_run_without_an_accepted_proof_saves_no_proof_file(ollama, tmp_path):
    run_lean(ollama, tmp_path / "run", FakeRunner(), problems=[THREE])

    assert not (tmp_path / "run" / "proofs").exists()


def test_a_cut_off_reply_has_no_proof_and_no_lean_record(ollama, tmp_path):
    ollama.replies[lean_prompt(INSTRUCTION, ONE)]["done_reason"] = "length"
    runner = FakeRunner()

    run_lean(ollama, tmp_path / "run", runner, problems=[ONE])

    (result,) = read_results(tmp_path / "run")
    assert (result["verdict"], result["answer"], result["proof"], result["lean"]) == (
        "cut_off",
        None,
        None,
        None,
    )
    assert runner.calls == []


def test_the_run_names_its_lean_environment_rules_and_limits(ollama, tmp_path):
    run_lean(ollama, tmp_path / "run", FakeRunner(), problems=[THREE])

    run = json.loads((tmp_path / "run" / "run.json").read_text())
    assert run["benchmark"] == {
        "name": "sample",
        "kind": "lean",
        "repository": "https://example.com/project",
        "commit": "c" * 40,
        "file": "Split.lean",
        "sha256": "ab" * 32,
        "subset": False,
        "scored": False,
        "ids": ["fixture_third"],
    }
    assert run["grader"]["lean_rules"] == 1
    assert run["grader"]["judge_commit"] == "d" * 40
    assert run["lean"] == {
        **ENVIRONMENT,
        "instruction": "Prove it.",
        "compile_time_limit_seconds": 11,
        "judge_time_limit_seconds": 22,
    }
    assert list(run)[:8] == [
        "kind",
        "complete",
        "runtime",
        "model",
        "generation",
        "benchmark",
        "grader",
        "lean",
    ]


@pytest.mark.parametrize(
    "changes",
    [
        {"settings": LeanSettings("Prove it carefully.", 11, 22)},
        {"settings": LeanSettings(INSTRUCTION, 12, 22)},
        {"settings": LeanSettings(INSTRUCTION, 11, 23)},
        {"environment": {**ENVIRONMENT, "toolchain": "leanprover/lean4:v4.100.0"}},
    ],
)
def test_refuses_to_resume_under_a_different_instruction_or_toolchain(ollama, tmp_path, changes):
    out = tmp_path / "run"
    run_lean(ollama, out, FakeRunner(), problems=[THREE])

    with pytest.raises(EvaluationError, match="different lean"):
        run_lean(
            ollama, out, FakeRunner(), problems=[THREE], task=task_for(out, FakeRunner(), **changes)
        )


def test_an_attempt_the_machine_slept_through_is_checked_again(ollama, tmp_path):
    wakes = iter(["06:00", "07:00", "07:00", "07:00"])

    run_lean(
        ollama,
        tmp_path / "run",
        proving_runner(ONE.id, ONE.id),
        problems=[ONE],
        read_wake=lambda: next(wakes),
    )

    assert len(read_results(tmp_path / "run")) == 1
    assert len(chats(ollama)) == 2


def test_the_model_is_released_before_lean_runs(ollama, tmp_path):
    events = []
    runner = proving_runner(ONE.id)
    runner.on_compile = lambda source, olean: events.append("compile")

    run_lean(
        ollama,
        tmp_path / "run",
        runner,
        problems=[ONE],
        task=task_for(tmp_path / "run", runner, release=lambda: events.append("release")),
    )

    assert events == ["release", "compile", "compile"]


def test_a_finished_lean_run_s_report_starts_with_its_score(ollama, tmp_path):
    run_lean(ollama, tmp_path / "run", mixed_runner())

    assert build_report(tmp_path / "run").splitlines()[0] == "# sample: 1 of 3 proved (33.3%)"


def test_an_interrupted_lean_run_s_report_says_it_is_incomplete(ollama, tmp_path):
    def stop(line):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_lean(ollama, tmp_path / "run", proving_runner(ONE.id), report=stop)

    report = build_report(tmp_path / "run")
    assert report.splitlines()[0] == "# sample: incomplete, 1 of 3 theorems attempted"
    assert "1 of the 1 theorems attempted so far are proved" in report


def test_the_task_sends_the_prompt_built_from_its_instruction(tmp_path):
    assert task_for(tmp_path, FakeRunner()).prompt(ONE) == lean_prompt(INSTRUCTION, ONE)


def slept_once():
    wakes = iter(["06:00", "07:00", "07:00", "07:00"])
    return lambda: next(wakes)


def test_a_proof_file_of_a_discarded_attempt_does_not_outlive_a_failed_redo(ollama, tmp_path):
    out = tmp_path / "run"
    runner = FakeRunner(
        compiles=[OK, OK, OK, Finished(1, "", "", 3.0)],
        judges=[JUDGED],
        saved=[outcome(ONE.id)],
    )

    run_lean(ollama, out, runner, problems=[ONE], read_wake=slept_once())

    (result,) = read_results(out)
    assert result["verdict"] == "failed"
    assert not (out / "proofs" / "fixture_add_zero.lean").exists()


def test_a_proof_file_of_a_discarded_attempt_does_not_outlive_a_cut_off_redo(ollama, tmp_path):
    out = tmp_path / "run"

    def cut_off_from_now_on(line):
        ollama.replies[lean_prompt(INSTRUCTION, ONE)]["done_reason"] = "length"

    run_lean(
        ollama,
        out,
        proving_runner(ONE.id),
        problems=[ONE],
        read_wake=slept_once(),
        report=cut_off_from_now_on,
    )

    (result,) = read_results(out)
    assert result["verdict"] == "cut_off"
    assert not (out / "proofs" / "fixture_add_zero.lean").exists()


def test_a_proof_file_left_by_an_earlier_session_is_gone_when_the_attempt_is_not_proved(
    ollama, tmp_path
):
    out = tmp_path / "run"
    (out / "proofs").mkdir(parents=True)
    (out / "proofs" / "fixture_third.lean").write_text("stale", encoding="utf-8")
    (out / "proofs" / "fixture_add_zero.lean").write_text("stale", encoding="utf-8")

    run_lean(ollama, out, proving_runner(ONE.id), problems=[ONE, THREE])

    assert [p.name for p in (out / "proofs").iterdir()] == ["fixture_add_zero.lean"]
    assert "stale" not in (out / "proofs" / "fixture_add_zero.lean").read_text(encoding="utf-8")


def test_a_check_that_raises_stops_the_run_and_the_same_command_resumes_at_its_theorem(
    ollama, tmp_path
):
    out = tmp_path / "run"
    # The first theorem is proved; the second theorem's reference does not compile.
    broken = FakeRunner(
        compiles=[OK, OK, Finished(1, "", "Mathlib is not built", 1.0)],
        judges=[JUDGED],
        saved=[outcome(ONE.id)],
    )

    with pytest.raises(BenchmarkError, match="(?s)fixture_second: .*Mathlib is not built"):
        run_lean(ollama, out, broken)

    assert [r["id"] for r in read_results(out)] == ["fixture_add_zero"]
    assert json.loads((out / "run.json").read_text())["complete"] is False
    asked = len(chats(ollama))

    run_lean(ollama, out, FakeRunner(compiles=[OK, Finished(1, "", "", 3.0)]))

    results = read_results(out)
    assert [r["id"] for r in results] == ["fixture_add_zero", "fixture_second", "fixture_third"]
    assert [r["session"] for r in results] == [0, 1, 1]
    assert chats(ollama)[asked][0]["content"] == lean_prompt(INSTRUCTION, TWO)
    assert json.loads((out / "run.json").read_text())["complete"] is True


def test_the_progress_line_of_a_failed_lean_result_gives_its_reason(ollama, tmp_path):
    lines = []

    run_lean(ollama, tmp_path / "run", mixed_runner(), report=lines.append)

    verdicts = [line.split("  ")[1] for line in lines]
    assert verdicts == ["proved", "failed (lean_error)", "missing"]


def test_the_progress_line_of_an_answer_result_is_unchanged():
    result = {"id": "dev/2", "verdict": "incorrect", "output_tokens": 812, "elapsed_seconds": 41.25}
    assert _progress(2, 3, result) == "[2/3] dev/2  incorrect  812 tokens  41.2 s"
    result = {**result, "verdict": "timed_out", "output_tokens": None}
    assert _progress(2, 3, result) == "[2/3] dev/2  timed_out  - tokens  41.2 s"
