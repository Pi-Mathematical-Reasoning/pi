"""Auditing a finished run from its saved files, before it is published."""

import json

import pytest

from pi.audit import audit_run
from pi.benchmarks import load_benchmark
from pi.evaluation import RESULTS, RUN
from pi.report import build_report
from tests.test_cli import answer_one_of_three, eval_arguments, main


@pytest.fixture
def finished(ollama, tmp_path):
    """A complete run of the three-problem benchmark, made by `pi eval`, and its definition."""
    answer_one_of_three(ollama)
    arguments = eval_arguments(tmp_path, ollama)
    assert main(arguments) == 0
    out = tmp_path / "run"
    (out / "report.md").write_text(build_report(out))
    definition = arguments[arguments.index("--benchmark") + 1]
    return out, load_benchmark(definition), tmp_path / "data"


def checks(audit):
    return {check["name"]: check["passed"] for check in audit["checks"]}


def failed(audit):
    return {check["name"]: check["detail"] for check in audit["checks"] if not check["passed"]}


def edit_results(out, change):
    rows = [json.loads(line) for line in (out / RESULTS).read_text().splitlines()]
    change(rows)
    (out / RESULTS).write_text("".join(json.dumps(row) + "\n" for row in rows))


def test_a_sound_run_passes_every_check(finished):
    out, benchmark, data = finished

    audit = audit_run(out, benchmark, data)

    assert audit["passed"] is True
    assert set(checks(audit)) == {
        "complete",
        "benchmark",
        "problem file",
        "one result per problem",
        "grader",
        "verdicts",
        "sessions",
        "report",
    }


def test_records_the_checksum_and_size_of_every_file_it_audited(finished):
    out, benchmark, data = finished

    audit = audit_run(out, benchmark, data)

    assert set(audit["files"]) == {RUN, RESULTS, "report.md"}
    assert audit["files"][RESULTS]["size"] == (out / RESULTS).stat().st_size
    assert len(audit["files"][RESULTS]["sha256"]) == 64


def test_a_verdict_that_does_not_follow_from_its_reply_fails(finished):
    out, benchmark, data = finished
    # dev/2's reply boxes 4; the reference is 3. Claim it was correct.
    edit_results(out, lambda rows: rows[1].update(verdict="correct"))

    audit = audit_run(out, benchmark, data)

    assert audit["passed"] is False
    assert "dev/2" in failed(audit)["verdicts"]


def test_a_missing_result_fails(finished):
    out, benchmark, data = finished
    edit_results(out, lambda rows: rows.pop())

    audit = audit_run(out, benchmark, data)

    assert "dev/3" in failed(audit)["one result per problem"]


def test_a_problem_answered_twice_fails(finished):
    out, benchmark, data = finished
    edit_results(out, lambda rows: rows.append(rows[0]))

    assert "dev/1" in failed(audit_run(out, benchmark, data))["one result per problem"]


def test_an_incomplete_run_fails(finished):
    out, benchmark, data = finished
    run = json.loads((out / RUN).read_text())
    (out / RUN).write_text(json.dumps({**run, "complete": False}))

    assert "complete" in failed(audit_run(out, benchmark, data))


def test_a_report_that_does_not_match_the_records_fails(finished):
    out, benchmark, data = finished
    (out / "report.md").write_text("# sample: 3 of 3 correct (100.0%)\n")

    assert "report" in failed(audit_run(out, benchmark, data))


def test_a_definition_that_names_other_problems_fails(finished, tmp_path):
    out, benchmark, data = finished
    other = tmp_path / "other.toml"
    other.write_text(
        'name = "sample"\n'
        f'url = "{benchmark.url}"\n'
        f'sha256 = "{benchmark.sha256}"\n'
        'format = "jsonl"\n'
        'ids = ["dev/1", "dev/2"]\n'
    )

    audit = audit_run(out, load_benchmark(other), data)

    assert "benchmark" in failed(audit)


def test_a_run_graded_under_another_grader_fails(finished):
    out, benchmark, data = finished
    run = json.loads((out / RUN).read_text())
    run["grader"]["rules"] = 0
    (out / RUN).write_text(json.dumps(run))

    assert "grader" in failed(audit_run(out, benchmark, data))


def test_a_result_naming_a_session_that_does_not_exist_fails(finished):
    out, benchmark, data = finished
    edit_results(out, lambda rows: rows[0].update(session=7))

    assert "dev/1" in failed(audit_run(out, benchmark, data))["sessions"]


def scored(out):
    run = json.loads((out / RUN).read_text())
    run["benchmark"]["scored"] = True
    run["sessions"][0]["weights_verified"] = True
    # As a scored run's session records it: made from a clean checkout.
    run["sessions"][0]["code"] = {"revision": "abc123", "dirty": False}
    (out / RUN).write_text(json.dumps(run))


def test_a_scored_run_must_have_kept_the_scored_standard(finished):
    out, benchmark, data = finished
    scored(out)
    edit_results(
        out, lambda rows: [r.update(power={"source": "AC Power", "mode": None}) for r in rows]
    )

    audit = audit_run(out, benchmark, data)

    assert checks(audit)["scored standard"] is True


def test_a_scored_run_with_an_attempt_on_battery_fails(finished):
    out, benchmark, data = finished
    scored(out)
    battery = {"source": "Battery Power", "mode": "powermode 1"}
    edit_results(out, lambda rows: [r.update(power=battery) for r in rows])

    assert "dev/1" in failed(audit_run(out, benchmark, data))["scored standard"]


def test_a_scored_run_from_uncommitted_code_fails(finished):
    out, benchmark, data = finished
    scored(out)
    run = json.loads((out / RUN).read_text())
    run["sessions"][0]["code"]["dirty"] = True
    (out / RUN).write_text(json.dumps(run))

    assert "scored standard" in failed(audit_run(out, benchmark, data))
