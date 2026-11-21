"""What keeps a run's records trustworthy: sessions, sleep, power, code, runner, weights."""

import json

import pytest

from pi.benchmarks import Benchmark
from pi.evaluation import EvaluationError, read_results, run_evaluation
from pi.ollama import OllamaClient
from pi.resources import OllamaTree
from tests.test_evaluation import (
    ONE,
    PROBLEMS,
    THREE,
    TWO,
    chats,
    config_for,
    quiet_sampler,
)

UNSCORED = Benchmark("sample", "https://example.com/problems.jsonl", "abc123", "jsonl", None)
SCORED = Benchmark(
    "sample", "https://example.com/problems.jsonl", "abc123", "jsonl", None, scored=True
)
CLEAN = {"revision": "abc123", "dirty": False}
MAINS = {"source": "AC Power", "mode": "powermode 2"}
BATTERY = {"source": "Battery Power", "mode": "powermode 1"}
MACHINE = {"model": "Mac15,9", "chip": "Apple M3 Max", "memory_bytes": 51539607552}
RUNNER = "llama-server --model ~/.ollama/models/blobs/sha256-a8cc -c 24576 --cache-type-k q8_0"


@pytest.fixture
def ollama(ollama):
    """The stand-in server, answering every problem correctly."""
    ollama.replies = {
        ONE.problem: {"content": r"It is $\boxed{2}$."},
        TWO.problem: {"content": r"It has $\boxed{3}$."},
        THREE.problem: {"content": r"So $x = \boxed{\frac{1}{2}}$."},
    }
    return ollama


def sequence(values):
    """A reader that returns each value in turn, then repeats the last."""
    remaining = list(values)
    return lambda *arguments: remaining.pop(0) if len(remaining) > 1 else remaining[0]


def runner_tree(command=RUNNER):
    return OllamaTree(resident_bytes=1, runner_commands=(f"{command} --port 50001",))


def evaluate(ollama, out, **options):
    settings = {
        "config": config_for(ollama),
        "benchmark": UNSCORED,
        "problems": PROBLEMS,
        "sampler": quiet_sampler(),
        "command": ["pi", "eval"],
        "code": CLEAN,
        "report": lambda line: None,
        "read_power": lambda: MAINS,
        "read_wake": lambda: None,
        "read_machine": lambda: MACHINE,
        "verify_weights": lambda name: True,
    }
    settings.update(options)
    return run_evaluation(client=OllamaClient(ollama.host), out=out, **settings)


def run_file(out):
    return json.loads((out / "run.json").read_text())


# Sessions: written when they start, so a hard stop still leaves a record.


def test_a_session_is_on_record_before_its_first_attempt_finishes(ollama, tmp_path):
    seen = []

    def report(line):
        seen.append(run_file(tmp_path / "run")["sessions"])

    evaluate(ollama, tmp_path / "run", report=report)

    (session,) = seen[0]
    assert session["command"] == ["pi", "eval"]
    assert session["code"] == CLEAN
    assert session["ended_at"] is None


def test_a_finished_session_records_when_it_ended(ollama, tmp_path):
    run = evaluate(ollama, tmp_path / "run")

    (session,) = run["sessions"]
    assert session["ended_at"] is not None
    assert session["attempted"] == 3


def test_each_result_names_its_session_and_when_it_started(ollama, tmp_path):
    ollama.replies[TWO.problem] = {"error": (500, "the runner crashed")}
    with pytest.raises(Exception, match="the runner crashed"):
        evaluate(ollama, tmp_path / "run")
    ollama.replies[TWO.problem] = {"content": r"It has $\boxed{3}$."}
    evaluate(ollama, tmp_path / "run")

    results = read_results(tmp_path / "run")
    assert [r["session"] for r in results] == [0, 1, 1]
    assert all(r["started_at"].endswith("+00:00") for r in results)


def test_a_session_records_the_machine(ollama, tmp_path):
    run = evaluate(ollama, tmp_path / "run")

    # What the machine reader returns; tests/test_resources.py tests the reader.
    assert run["sessions"][0]["machine"] == MACHINE


# Sleep: an attempt the machine slept through is redone, never recorded.


def test_an_attempt_during_which_the_machine_slept_is_redone(ollama, tmp_path):
    # Before and after each attempt; the wake time moves once, during the first.
    wakes = sequence(["06:00", "07:00", "07:00", "07:00"])
    lines = []

    evaluate(ollama, tmp_path / "run", problems=[ONE], read_wake=wakes, report=lines.append)

    assert len(read_results(tmp_path / "run")) == 1
    assert [m[0]["content"] for m in chats(ollama)] == [ONE.problem, ONE.problem]
    assert any("slept" in line for line in lines)


def test_a_machine_that_keeps_sleeping_stops_the_run_without_a_result(ollama, tmp_path):
    wakes = iter(range(100))

    with pytest.raises(EvaluationError, match="slept"):
        evaluate(ollama, tmp_path / "run", problems=[ONE], read_wake=lambda: next(wakes))

    assert read_results(tmp_path / "run") == []
    assert run_file(tmp_path / "run")["complete"] is False


# Power: a scored run is made on mains only.


def test_a_scored_run_stops_on_battery_and_resumes_on_mains(ollama, tmp_path):
    power = sequence([MAINS, BATTERY])

    with pytest.raises(EvaluationError, match="battery"):
        evaluate(ollama, tmp_path / "run", benchmark=SCORED, read_power=power)

    assert [r["id"] for r in read_results(tmp_path / "run")] == ["dev/1"]
    run = evaluate(ollama, tmp_path / "run", benchmark=SCORED)
    assert run["complete"] is True


def test_an_unscored_run_carries_on_on_battery_and_records_it(ollama, tmp_path):
    evaluate(ollama, tmp_path / "run", read_power=lambda: BATTERY)

    assert [r["power"] for r in read_results(tmp_path / "run")] == [BATTERY] * 3


def test_a_scored_run_carries_on_where_the_power_source_cannot_be_read(ollama, tmp_path):
    run = evaluate(ollama, tmp_path / "run", benchmark=SCORED, read_power=lambda: None)

    assert run["complete"] is True


# Code: a scored run is made from committed code only.


@pytest.mark.parametrize("code", [{"revision": "abc123", "dirty": True}, None])
def test_a_scored_run_refuses_code_that_is_not_committed(ollama, tmp_path, code):
    with pytest.raises(EvaluationError, match="commit"):
        evaluate(ollama, tmp_path / "run", benchmark=SCORED, code=code)

    assert chats(ollama) == []
    assert not (tmp_path / "run").exists()


def test_an_unscored_run_accepts_uncommitted_code(ollama, tmp_path):
    run = evaluate(ollama, tmp_path / "run", code={"revision": "abc123", "dirty": True})

    assert run["complete"] is True


def test_the_run_says_whether_it_is_scored(ollama, tmp_path):
    assert evaluate(ollama, tmp_path / "run", benchmark=SCORED)["benchmark"]["scored"] is True


# The model runner: its launch settings change the numbers, so they must not drift.


def test_records_the_runners_launch_settings_without_its_port(ollama, tmp_path):
    run = evaluate(ollama, tmp_path / "run", sampler=quiet_sampler([runner_tree()]))

    assert run["runner"] == [RUNNER]


def test_a_change_in_the_runners_settings_stops_the_run_before_its_result_is_kept(ollama, tmp_path):
    changed = runner_tree(RUNNER.replace("q8_0", "f16"))
    sampler = quiet_sampler([runner_tree(), runner_tree(), changed])

    with pytest.raises(EvaluationError, match="runner"):
        evaluate(ollama, tmp_path / "run", sampler=sampler)

    assert [r["id"] for r in read_results(tmp_path / "run")] == ["dev/1"]


def test_a_resumed_run_must_launch_the_runner_as_before(ollama, tmp_path):
    ollama.replies[TWO.problem] = {"error": (500, "the runner crashed")}
    with pytest.raises(Exception, match="the runner crashed"):
        evaluate(ollama, tmp_path / "run", sampler=quiet_sampler([runner_tree()]))
    ollama.replies[TWO.problem] = {"content": r"It has $\boxed{3}$."}
    changed = quiet_sampler([runner_tree(RUNNER.replace("-c 24576", "-c 8192"))])

    with pytest.raises(EvaluationError, match="runner"):
        evaluate(ollama, tmp_path / "run", sampler=changed)

    assert [r["id"] for r in read_results(tmp_path / "run")] == ["dev/1"]


# The weights: the file on disk must be the one its name promises.


def test_a_scored_session_checks_the_weights_file(ollama, tmp_path):
    checked = []

    def verify(name):
        checked.append(name)
        return True

    run = evaluate(ollama, tmp_path / "run", benchmark=SCORED, verify_weights=verify)

    assert checked == ["sha256-a8cc1361f3145dc01f6d77c6c82c9116b9ffe3c97b34716fe20418455876c40e"]
    assert run["sessions"][0]["weights_verified"] is True


@pytest.mark.parametrize("outcome", [False, None])
def test_a_scored_run_refuses_weights_it_could_not_verify(ollama, tmp_path, outcome):
    with pytest.raises(EvaluationError, match="weights"):
        evaluate(ollama, tmp_path / "run", benchmark=SCORED, verify_weights=lambda name: outcome)

    assert chats(ollama) == []


def test_an_unscored_session_skips_the_weights_check(ollama, tmp_path):
    def verify(name):
        raise AssertionError("an unscored run does not hash the weights")

    run = evaluate(ollama, tmp_path / "run", verify_weights=verify)

    assert run["sessions"][0]["weights_verified"] is None
