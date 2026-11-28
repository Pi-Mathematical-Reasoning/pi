"""The audit of a Lean run: Lean stood in for, and the saved run made without it."""

import json

import pytest

from pi.audit import AUDIT, audit_run
from pi.config import LeanSettings
from pi.evaluation import RESULTS, read_results
from pi.lean_audit import audit_lean_run
from pi.lean_evaluation import lean_prompt
from pi.lean_project import BenchmarkError, Finished
from pi.publish import publish_run
from pi.report import build_report
from pi.s3 import AwsCli
from tests.lean_fake import FakeRunner
from tests.test_lean_evaluation import (
    BENCHMARK,
    ENVIRONMENT,
    INSTRUCTION,
    JUDGED,
    OK,
    ONE,
    THREE,
    TWO,
    outcome,
    proof,
    run_lean,
    task_for,
)

SETTINGS = LeanSettings(INSTRUCTION, 300, 600)
NAMES = [
    "complete",
    "benchmark",
    "lean environment",
    "one result per problem",
    "grader",
    "proof files",
    "sessions",
    "report",
    "verdicts",
]
NOT_RUN = "not run: an earlier check failed"


@pytest.fixture
def ollama(ollama):
    ollama.replies = {
        lean_prompt(INSTRUCTION, ONE): {"content": proof(ONE.id)},
        lean_prompt(INSTRUCTION, TWO): {"content": proof(TWO.id)},
        lean_prompt(INSTRUCTION, THREE): {"content": "I cannot tell."},
    }
    return ollama


@pytest.fixture(autouse=True)
def lean_set_up(monkeypatch):
    monkeypatch.setattr("pi.lean_audit.lean_environment", lambda benchmark, data_dir: ENVIRONMENT)
    monkeypatch.setattr(
        "pi.lean_audit.load_theorems", lambda benchmark, data_dir: [ONE, TWO, THREE]
    )


LEAN_ERROR = Finished(1, "", "", 3.0)


def making_runner(second=LEAN_ERROR):
    """Accepts the first proof; compiles the second without error, then fails it."""
    return FakeRunner(
        compiles=[OK, OK, OK, second],
        judges=[JUDGED],
        saved=[outcome(ONE.id)],
    )


def again_runner(second=LEAN_ERROR):
    return making_runner(second)


@pytest.fixture
def finished(ollama, tmp_path):
    out = tmp_path / "run"
    runner = making_runner()
    run_lean(ollama, out, runner, task=task_for(out, runner, settings=SETTINGS))
    (out / "report.md").write_text(build_report(out))
    return out


def audit(out, runner=None, benchmark=BENCHMARK):
    return audit_lean_run(out, benchmark, out.parent / "data", runner or again_runner())


def failed(result):
    return [c["name"] for c in result["checks"] if not c["passed"]]


def detail(result, name):
    return next(c["detail"] for c in result["checks"] if c["name"] == name)


def edit_results(out, change, rebuild=True):
    results = read_results(out)
    change(results)
    (out / RESULTS).write_text("".join(json.dumps(r) + "\n" for r in results))
    if rebuild:
        (out / "report.md").write_text(build_report(out))


def edit_run(out, change, rebuild=True):
    run = json.loads((out / "run.json").read_text())
    change(run)
    (out / "run.json").write_text(json.dumps(run))
    if rebuild:
        (out / "report.md").write_text(build_report(out))


def test_a_sound_run_passes_every_check(finished):
    result = audit(finished)

    assert [c["name"] for c in result["checks"]] == NAMES
    assert failed(result) == []
    assert result["passed"] is True
    assert set(result) == {"run", "audited_at", "code", "grader", "passed", "checks", "files"}


def test_audit_run_dispatches_a_lean_definition_to_the_lean_audit(finished, monkeypatch):
    runner = again_runner()
    monkeypatch.setattr("pi.lean_audit.LeanRunner", lambda benchmark, data_dir: runner)

    assert audit_run(finished, BENCHMARK, finished.parent / "data")["passed"] is True


def test_every_result_checked_again_is_checked_at_four_times_the_limits(finished):
    runner = again_runner()

    audit(finished, runner)

    # The proved result, then the failed one, each at four times the run's 300 and 600 s.
    assert [call[-1] for call in runner.calls] == [1200, 1200, 2400, 1200, 1200]


def test_a_proof_that_no_longer_checks_fails_the_verdicts_check(finished):
    runner = FakeRunner(compiles=[OK, Finished(1, "", "", 1.0), OK, Finished(1, "", "", 3.0)])

    result = audit(finished, runner)

    assert failed(result) == ["verdicts"]
    assert detail(result, "verdicts") == "fixture_add_zero"


def test_a_failure_must_fail_again_for_the_same_reason(finished):
    # The failed theorem now compiles and is accepted, instead of failing as before.
    runner = FakeRunner(
        compiles=[OK, OK, OK, OK],
        judges=[JUDGED, JUDGED],
        saved=[outcome(ONE.id), outcome(TWO.id)],
    )

    result = audit(finished, runner)

    assert failed(result) == ["verdicts"]
    assert detail(result, "verdicts") == "fixture_second"


def test_a_failure_for_another_reason_fails_the_verdicts_check(finished):
    result = audit(finished, again_runner(Finished(None, "", "", 300.0)))

    assert detail(result, "verdicts") == "fixture_second"


@pytest.fixture
def timed_out(ollama, tmp_path):
    out = tmp_path / "run"
    runner = FakeRunner(compiles=[OK, OK, OK, Finished(None, "", "", 300.2)])
    runner.judges, runner.saved = [JUDGED], [outcome(ONE.id)]
    run_lean(ollama, out, runner, task=task_for(out, runner, settings=SETTINGS))
    (out / "report.md").write_text(build_report(out))
    assert read_results(out)[1]["lean"]["reason"] == "check_timed_out"
    return out


def test_a_timed_out_check_is_not_run_again_but_its_time_must_reach_the_limit(timed_out):
    runner = FakeRunner(compiles=[OK, OK], judges=[JUDGED], saved=[outcome(ONE.id)])

    result = audit(timed_out, runner)

    assert failed(result) == []
    assert len(runner.calls) == 3  # only the proved theorem was checked again

    def too_quick(results):
        results[1]["lean"]["compile_seconds"] = 12.0

    edit_results(timed_out, too_quick)
    result = audit(
        timed_out, FakeRunner(compiles=[OK, OK], judges=[JUDGED], saved=[outcome(ONE.id)])
    )
    assert failed(result) == ["verdicts"]
    assert detail(result, "verdicts") == "fixture_second"


@pytest.mark.parametrize(
    "change",
    [
        lambda r: r[0].update(proof="theorem fixture_add_zero : True := by trivial"),
        lambda r: r[0].update(proof=None),
        lambda r: r[1].update(proof="other"),
        lambda r: r[0].update(answer="3"),
        lambda r: r[2].update(verdict="failed"),
        lambda r: r[2].update(proof="x"),
        lambda r: r[1].update(verdict="missing"),
        lambda r: r[0].update(verdict="correct"),
        lambda r: r[0]["response"].update(done_reason="length"),
        lambda r: r[0].update(response=None),
        lambda r: r[0].update(lean=None),
    ],
)
def test_an_altered_result_fails_the_verdicts_check(finished, change):
    edit_results(finished, lambda results: change(results))

    result = audit(finished)

    assert "verdicts" in failed(result)


def test_an_altered_proof_field_fails_the_verdicts_check(finished):
    edit_results(finished, lambda r: r[0].update(proof="theorem x := by\n  rfl"))

    result = audit(finished, FakeRunner(compiles=[OK, Finished(1, "", "", 3.0)]))

    assert detail(result, "verdicts") == "fixture_add_zero"


def test_a_failed_verdict_for_a_reply_that_proves_fails(finished):
    def claim_failure(results):
        results[0].update(verdict="failed", lean={**results[0]["lean"], "reason": "lean_error"})

    edit_results(finished, claim_failure)

    assert "verdicts" in failed(audit(finished, again_runner_proving()))


def again_runner_proving():
    return FakeRunner(
        compiles=[OK, OK, OK, OK],
        judges=[JUDGED, JUDGED],
        saved=[outcome(ONE.id), outcome(TWO.id)],
    )


def test_a_missing_verdict_for_a_reply_with_code_fails(finished):
    def claim_missing(results):
        results[1].update(verdict="missing", proof=None, lean=None)

    edit_results(finished, claim_missing)

    result = audit(finished)

    assert detail(result, "verdicts") == "fixture_second"


@pytest.mark.parametrize(
    "mutilate",
    [
        lambda out: (out / "proofs/fixture_add_zero.lean").unlink(),
        lambda out: (out / "proofs/fixture_add_zero.lean").write_text("theorem x := rfl\n"),
        lambda out: (out / "proofs/fixture_second.lean").write_text("import Mathlib\n"),
        lambda out: (out / "proofs/notes.txt").write_text("hi"),
        lambda out: (out / "proofs/sub").mkdir(),
    ],
)
def test_a_missing_altered_or_extra_proof_file_fails_the_proof_files_check(finished, mutilate):
    mutilate(finished)

    assert failed(audit(finished)) == ["proof files"]


@pytest.mark.parametrize("name", [".DS_Store", "fixture_add_zero.lean~", "sub"])
def test_a_stray_entry_in_the_proofs_folder_is_named_with_what_to_do(finished, name):
    (finished / "proofs" / name).mkdir() if name == "sub" else (finished / "proofs" / name).touch()

    assert detail(audit(finished), "proof files") == (
        f"proofs/{name} is not a proved theorem's proof file: remove it"
    )


def test_proof_files_without_a_proved_result_fail(finished):
    edit_results(finished, lambda r: r[0].update(verdict="failed"))

    assert "proof files" in failed(audit(finished, again_runner_proving()))


def test_a_different_lean_environment_fails_its_check(finished, monkeypatch):
    other = {**ENVIRONMENT, "toolchain": "leanprover/lean4:v4.100.0"}
    monkeypatch.setattr("pi.lean_audit.lean_environment", lambda benchmark, data_dir: other)

    runner = again_runner()
    result = audit(finished, runner)

    assert failed(result) == ["lean environment", "verdicts"]
    assert detail(result, "verdicts") == NOT_RUN
    assert runner.calls == []


def test_a_different_judge_fails_the_grader_check(finished):
    from dataclasses import replace

    other = replace(BENCHMARK, judge_commit="e" * 40)

    assert failed(audit(finished, benchmark=other)) == ["grader", "verdicts"]


def test_a_definition_with_another_commit_fails_the_benchmark_check(finished):
    from dataclasses import replace

    result = audit(finished, benchmark=replace(BENCHMARK, commit="e" * 40))

    assert "benchmark" in failed(result)


def test_a_theorem_not_in_the_benchmark_or_answered_twice_fails(finished):
    def change(results):
        results.append({**results[0], "id": "stray"})
        results.append(dict(results[2]))

    edit_results(finished, change)

    result = audit(finished)

    assert "one result per problem" in failed(result)
    assert "stray is not in the benchmark" in detail(result, "one result per problem")
    assert "fixture_third has 2 results" in detail(result, "one result per problem")


def test_a_missing_result_fails(finished):
    edit_results(finished, lambda r: r.pop())

    assert "one result per problem" in failed(audit(finished))


def test_an_incomplete_run_fails(finished):
    edit_run(finished, lambda run: run.update(complete=False))

    assert "complete" in failed(audit(finished))


def test_a_report_that_does_not_match_fails(finished):
    (finished / "report.md").write_text("tampered\n")

    assert failed(audit(finished)) == ["report"]


def test_a_result_naming_a_session_that_does_not_exist_fails(finished):
    edit_results(finished, lambda r: r[0].update(session=7))

    assert failed(audit(finished)) == ["sessions"]


def test_a_scored_run_must_have_kept_the_scored_standard(finished):
    edit_run(finished, lambda run: run["benchmark"].update(scored=True))

    result = audit(finished)

    assert [c["name"] for c in result["checks"]][-3:] == ["scored standard", "report", "verdicts"]
    assert "scored standard" in failed(result)


@pytest.mark.parametrize(
    "change",
    [
        lambda r: r[0].pop("response"),
        lambda r: r[0].update(response="text"),
        lambda r: r[0].update(lean="oops"),
        lambda r: r[1].update(lean=None),
        lambda r: r[1]["lean"].pop("reason"),
        lambda r: r[0].pop("verdict"),
    ],
)
def test_a_malformed_record_fails_and_names_the_theorem(finished, change):
    edit_results(finished, lambda results: change(results), rebuild=False)

    result = audit(finished, again_runner_proving())

    assert "verdicts" in failed(result)
    assert detail(result, "verdicts").startswith("fixture_")


def test_a_malformed_environment_in_the_run_fails_a_check_instead_of_raising(finished):
    edit_run(finished, lambda run: run.update(lean=None), rebuild=False)

    result = audit(finished)

    assert "lean environment" in failed(result)


def test_the_audit_fingerprints_the_proof_files(finished):
    result = audit(finished)

    assert list(result["files"]) == [
        "run.json",
        "results.jsonl",
        "report.md",
        "proofs/fixture_add_zero.lean",
    ]
    assert result["files"]["run.json"]["size"] == (finished / "run.json").stat().st_size


def test_the_audit_does_not_change_the_run(finished):
    before = {p: p.read_bytes() for p in finished.rglob("*") if p.is_file()}

    audit(finished)

    assert {p: p.read_bytes() for p in finished.rglob("*") if p.is_file()} == before


def test_the_audit_checks_one_proof_at_a_time(finished):
    runner = again_runner()
    live = []
    overlap = []

    original = runner.work_dir

    def counted():
        manager = original()

        class Counting:
            def __enter__(self):
                live.append(1)
                overlap.append(len(live))
                return manager.__enter__()

            def __exit__(self, *exc):
                live.pop()
                return manager.__exit__(*exc)

        return Counting()

    runner.work_dir = counted

    audit(finished, runner)

    assert overlap == [1, 1]


def test_lean_not_set_up_stops_the_audit_with_the_error(finished, monkeypatch):
    def refuse(benchmark, data_dir):
        raise BenchmarkError(
            "sample: lake is not on the PATH; run `pi lean-setup` for this benchmark"
        )

    monkeypatch.setattr("pi.lean_audit.lean_environment", refuse)

    with pytest.raises(BenchmarkError, match="pi lean-setup"):
        audit(finished)


@pytest.mark.parametrize(
    ("index", "field", "value"),
    [
        (0, "flags", ["#eval"]),  # a flag added to a proved result
        (0, "reason", "lean_error"),
        (0, "axioms", ["sorryAx"]),
        (1, "flags", ["#eval"]),  # other flags on a failed result
        (1, "axioms", ["propext"]),
    ],
)
def test_a_recorded_lean_field_that_the_reply_does_not_give_fails(finished, index, field, value):
    edit_results(finished, lambda r: r[index]["lean"].update({field: value}))

    result = audit(finished)

    assert "verdicts" in failed(result)
    assert ["fixture_add_zero", "fixture_second"][index] in detail(result, "verdicts")


def test_flags_emptied_from_a_flagged_proof_fail(ollama, tmp_path):
    ollama.replies[lean_prompt(INSTRUCTION, ONE)] = {
        "content": (
            "```lean4\ntheorem fixture_add_zero (a : ℕ) : a + 0 = a := by\n  #eval 1\n  simp\n```\n"
        )
    }
    out = tmp_path / "run"
    runner = making_runner()
    run_lean(ollama, out, runner, task=task_for(out, runner, settings=SETTINGS))
    (out / "report.md").write_text(build_report(out))
    assert read_results(out)[0]["lean"]["flags"] == ["#eval"]
    assert failed(audit(out)) == []

    edit_results(out, lambda r: r[0]["lean"].update(flags=[]))

    runner = FakeRunner(compiles=[OK, LEAN_ERROR])  # only the failed theorem reaches Lean
    assert detail(audit(out, runner), "verdicts") == "fixture_add_zero"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("kind", "answer"),
        ("name", "other"),
        ("subset", True),
        ("scored", True),
        ("sha256", "cd" * 32),
    ],
)
def test_a_benchmark_identity_that_differs_from_the_definition_fails(finished, field, value):
    edit_run(finished, lambda run: run["benchmark"].update({field: value}), rebuild=False)

    assert "benchmark" in failed(audit(finished))


@pytest.mark.parametrize(
    ("compile_seconds", "judge_seconds", "passes"),
    [
        (300.0, None, True),  # the compile timed out
        (12.0, None, False),
        (12.0, 700.0, True),  # the judge ran and timed out
        (5.0, 600.0, True),  # the judge timed out
        (400.0, 12.0, False),  # the judge ran, so its time is the one that must reach its limit
        (None, None, False),
        (5.0, "long", False),
        (None, 700.0, True),
    ],
)
def test_a_timed_out_check_s_time_is_that_of_the_step_that_timed_out(
    timed_out, compile_seconds, judge_seconds, passes
):
    def record(results):
        results[1]["lean"].update(compile_seconds=compile_seconds, judge_seconds=judge_seconds)

    edit_results(timed_out, record, rebuild=False)  # the report cannot be rebuilt from nulls
    runner = FakeRunner(compiles=[OK, OK], judges=[JUDGED], saved=[outcome(ONE.id)])

    assert ("verdicts" not in failed(audit(timed_out, runner))) is passes


@pytest.mark.parametrize(
    "change",
    [
        lambda run: run["benchmark"].update(commit="e" * 40),  # benchmark
        lambda run: run["grader"].update(judge_commit="e" * 40),  # grader
    ],
)
def test_verdicts_are_not_checked_when_an_earlier_check_they_rest_on_failed(finished, change):
    edit_run(finished, change)
    runner = again_runner()

    result = audit(finished, runner)

    assert result["checks"][-1] == {"name": "verdicts", "passed": False, "detail": NOT_RUN}
    assert runner.calls == []


def test_verdicts_are_not_checked_when_a_result_is_missing(finished):
    edit_results(finished, lambda r: r.pop())
    runner = again_runner()

    result = audit(finished, runner)

    assert failed(result) == ["one result per problem", "verdicts"]
    assert detail(result, "verdicts") == NOT_RUN
    assert runner.calls == []


def test_verdicts_are_checked_after_a_failed_proof_files_check(finished):
    (finished / "proofs" / ".DS_Store").touch()
    runner = again_runner()

    result = audit(finished, runner)

    assert failed(result) == ["proof files"]
    assert len(runner.calls) == 5


def test_each_result_checked_again_is_reported_as_it_finishes(finished):
    lines = []

    result = audit_lean_run(
        finished, BENCHMARK, finished.parent / "data", again_runner(), report=lines.append
    )

    assert result["passed"] is True
    assert [line.rsplit(" in ", 1)[0] for line in lines] == [
        "[1/3] fixture_add_zero  proved  re-checked",
        "[2/3] fixture_second  failed (lean_error)  re-checked",
    ]
    assert all(line.endswith(" s") for line in lines)


def run_with_axioms(ollama, tmp_path, axioms):
    """A run whose first theorem fails for an axiom off the allowlist, the judge naming these."""
    out = tmp_path / "run"
    info = {"constInfo": {"kind": "theorem"}, "axioms": axioms}
    saved = [[ONE.id, {"targetInfo": info, "solutionInfo": info, "failureMode": None}]]
    runner = FakeRunner(compiles=[OK, OK, OK, LEAN_ERROR], judges=[JUDGED], saved=[saved])
    run_lean(ollama, out, runner, task=task_for(out, runner, settings=SETTINGS))
    (out / "report.md").write_text(build_report(out))
    assert read_results(out)[0]["lean"]["reason"] == "axioms"
    return out


def test_axioms_are_compared_without_regard_to_order(ollama, tmp_path):
    out = run_with_axioms(ollama, tmp_path, ["Quot.sound", "propext"])
    again = run_with_axioms(ollama, tmp_path / "again", ["propext", "Quot.sound"])
    runner = FakeRunner(
        compiles=[OK, OK, OK, LEAN_ERROR],
        judges=[JUDGED],
        saved=[read_results(again)[0]["lean"]["judge"]["outcome"]],
    )

    assert failed(audit(out, runner)) == []


def test_axioms_are_compared_without_regard_to_repeats(finished):
    edit_results(finished, lambda r: r[0]["lean"].update(axioms=["propext", "propext"]))

    assert failed(audit(finished)) == []


def test_axioms_other_than_those_recorded_still_fail(finished):
    edit_results(finished, lambda r: r[0]["lean"].update(axioms=["propext", "Quot.sound"]))

    assert detail(audit(finished), "verdicts") == "fixture_add_zero"


def test_a_lean_run_s_audit_lets_it_be_published_with_its_proof_files(finished, aws):
    (finished / AUDIT).write_text(json.dumps(audit(finished)))

    publish_run(finished, "jaws-pi-prover-artifacts", AwsCli())

    stored = aws / "jaws-pi-prover-artifacts" / "data" / "runs" / finished.name
    proof = "proofs/fixture_add_zero.lean"
    assert (stored / proof).read_bytes() == (finished / proof).read_bytes()
    manifest = json.loads((stored / "_manifest.json").read_text())
    assert manifest["audit"]["passed"] is True
    assert list(manifest["files"]) == [
        "run.json",
        "results.jsonl",
        "report.md",
        proof,
        "audit.json",
    ]


def test_a_reference_that_no_longer_compiles_stops_the_audit(finished):
    runner = FakeRunner(compiles=[Finished(1, "", "Mathlib is not built", 1.0)])

    with pytest.raises(BenchmarkError, match="(?s)fixture_add_zero: .*pi lean-setup"):
        audit(finished, runner)
