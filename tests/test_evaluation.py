"""The benchmark run: one attempt per problem, saved as it goes, resumable."""

import json

import pytest

from pi.benchmarks import Benchmark, Problem
from pi.checkpoint import CheckpointError
from pi.config import Config, Generation, ModelPin, Probe, Runtime
from pi.evaluation import EvaluationError, read_results, run_evaluation
from pi.ollama import OllamaClient, OllamaError
from pi.resources import OllamaTree, ResourceSampler
from tests.ollama_stub import DIGEST

ONE = Problem("dev/1", "What is $1+1$?", "2", "Algebra", 1)
TWO = Problem("dev/2", "How many sides has a triangle?", "3", "Geometry", 2)
THREE = Problem("dev/3", "Solve $2x=1$.", r"\frac{1}{2}", "Algebra", 3)
PROBLEMS = [ONE, TWO, THREE]

BENCHMARK = Benchmark(
    name="sample",
    url="https://example.com/problems.jsonl",
    sha256="abc123",
    format="jsonl",
    ids=None,
)


@pytest.fixture
def ollama(ollama):
    """The stand-in server, answering the three problems: right, wrong and not at all."""
    ollama.replies = {
        ONE.problem: {"content": r"It is $\boxed{2}$."},
        TWO.problem: {"content": r"It has $\boxed{4}$."},
        THREE.problem: {"content": "I cannot tell."},
    }
    return ollama


def config_for(ollama, **generation):
    settings = {
        "think": True,
        "context_length": 16384,
        "max_output_tokens": 8192,
        "temperature": 0.6,
        "top_p": 0.95,
        "top_k": 20,
        "seed": 1,
        "time_limit_seconds": 30,
    }
    return Config(
        model=ModelPin(name="qwen3:14b", digest=DIGEST),
        runtime=Runtime(host=ollama.host),
        generation=Generation(**{**settings, **generation}),
        probe=Probe(problem="unused"),
    )


def quiet_sampler(trees=(None,), swap=(None,)):
    def reader(values):
        remaining = list(values)
        return lambda: remaining.pop(0) if len(remaining) > 1 else remaining[0]

    return ResourceSampler(reader(trees), reader(swap), interval=60)


def evaluate(ollama, out, **options):
    settings = {
        "config": config_for(ollama),
        "benchmark": BENCHMARK,
        "problems": PROBLEMS,
        "sampler": quiet_sampler(),
        "command": ["pi", "eval"],
        "code": {"revision": "abc123", "dirty": False},
        "report": lambda line: None,
        "read_power": lambda: None,
        "problem_file": "https://example.com/problems.jsonl",
    }
    settings.update(options)
    return run_evaluation(client=OllamaClient(ollama.host), out=out, **settings)


def chats(ollama):
    return [body["messages"] for _, _, body in ollama.requests_to("/api/chat")]


def test_saves_one_result_per_problem_with_its_verdict_and_answer(ollama, tmp_path):
    evaluate(ollama, tmp_path / "run")

    results = read_results(tmp_path / "run")
    assert [(r["id"], r["verdict"], r["answer"]) for r in results] == [
        ("dev/1", "correct", "2"),
        ("dev/2", "incorrect", "4"),
        ("dev/3", "missing", None),
    ]


def test_a_result_keeps_the_reply_the_token_counts_and_the_time(ollama, tmp_path):
    ticks = iter([0.0, 10.0, 20.0, 35.0, 40.0, 41.0])

    evaluate(ollama, tmp_path / "run", clock=lambda: next(ticks))

    first, second, _ = read_results(tmp_path / "run")
    assert first == {
        "id": "dev/1",
        "subject": "Algebra",
        "level": 1,
        "verdict": "correct",
        "answer": "2",
        "response": {
            "content": r"It is $\boxed{2}$.",
            "thinking": "Two cases.",
            "done_reason": "stop",
        },
        "prompt_tokens": 26,
        "cached_prompt_tokens": 0,
        "output_tokens": 256,
        "output_tokens_per_second": 20.0,
        "load_seconds": 9.0,
        "elapsed_seconds": 10.0,
        "power": None,
    }
    assert second["elapsed_seconds"] == 15.0


def test_a_result_says_what_power_the_machine_was_on(ollama, tmp_path):
    # The same checkpoint generates a third slower on battery, so a time
    # means little without knowing which it was.
    battery = {"source": "Battery Power", "mode": "powermode 1"}
    mains = {"source": "AC Power", "mode": "powermode 2"}
    readings = iter([battery, mains, mains])

    evaluate(ollama, tmp_path / "run", read_power=lambda: next(readings))

    assert [r["power"] for r in read_results(tmp_path / "run")] == [battery, mains, mains]


def test_each_problem_starts_from_a_fresh_load_and_is_sent_only_its_text(ollama, tmp_path):
    evaluate(ollama, tmp_path / "run")

    order = [path for _, path, _ in ollama.requests if path in ("/api/generate", "/api/chat")]
    assert order == ["/api/generate", "/api/chat"] * 3
    assert chats(ollama) == [[{"role": "user", "content": problem.problem}] for problem in PROBLEMS]


def test_an_attempt_that_runs_past_the_time_limit_is_timed_out(ollama, tmp_path):
    ollama.replies[TWO.problem] = {"delay": 5}

    evaluate(ollama, tmp_path / "run", config=config_for(ollama, time_limit_seconds=0.2))

    second = read_results(tmp_path / "run")[1]
    assert second["verdict"] == "timed_out"
    assert second["response"] is None
    assert second["answer"] is None
    assert second["output_tokens"] is None


def test_a_reply_cut_off_at_the_output_limit_is_unsolved_whatever_it_says(ollama, tmp_path):
    ollama.replies[ONE.problem] = {"content": r"It is $\boxed{2}$.", "done_reason": "length"}

    evaluate(ollama, tmp_path / "run")

    first = read_results(tmp_path / "run")[0]
    assert first["verdict"] == "cut_off"
    assert first["answer"] is None
    assert first["response"]["content"] == r"It is $\boxed{2}$."


def test_a_finished_run_is_marked_complete_and_says_what_it_ran(ollama, tmp_path):
    evaluate(ollama, tmp_path / "run")

    run = json.loads((tmp_path / "run" / "run.json").read_text())
    assert run["kind"] == "evaluation"
    assert run["complete"] is True
    assert run["benchmark"] == {
        "name": "sample",
        "url": "https://example.com/problems.jsonl",
        "sha256": "abc123",
        "subset": False,
        "ids": ["dev/1", "dev/2", "dev/3"],
    }
    assert run["model"]["digest"] == DIGEST
    assert run["runtime"] == {"name": "ollama", "version": "0.40.13"}
    assert run["generation"]["seed"] == 1
    assert run["grader"]["rules"] == 1
    assert [session["attempted"] for session in run["sessions"]] == [3]
    assert run["sessions"][0]["command"] == ["pi", "eval"]
    assert run["sessions"][0]["problem_file"] == "https://example.com/problems.jsonl"
    assert run["sessions"][0]["code"] == {"revision": "abc123", "dirty": False}


def test_a_benchmark_with_a_frozen_id_list_is_labelled_a_subset(ollama, tmp_path):
    subset = Benchmark("sample", "https://example.com/p.jsonl", "abc123", "jsonl", ("dev/1",))

    run = evaluate(ollama, tmp_path / "run", benchmark=subset, problems=[ONE])

    assert run["benchmark"]["subset"] is True
    assert run["benchmark"]["ids"] == ["dev/1"]


def test_an_interrupted_run_is_incomplete_and_resumes_where_it_stopped(ollama, tmp_path):
    ollama.replies[TWO.problem] = {"error": (500, "the runner crashed")}
    with pytest.raises(OllamaError, match="the runner crashed"):
        evaluate(ollama, tmp_path / "run")

    interrupted = json.loads((tmp_path / "run" / "run.json").read_text())
    assert interrupted["complete"] is False
    assert [r["id"] for r in read_results(tmp_path / "run")] == ["dev/1"]

    ollama.replies[TWO.problem] = {"content": r"It has $\boxed{3}$."}
    resumed = evaluate(ollama, tmp_path / "run")

    assert resumed["complete"] is True
    assert [session["attempted"] for session in resumed["sessions"]] == [1, 2]
    assert [(r["id"], r["verdict"]) for r in read_results(tmp_path / "run")] == [
        ("dev/1", "correct"),
        ("dev/2", "correct"),
        ("dev/3", "missing"),
    ]
    # The first problem was not attempted a second time.
    assert [messages[0]["content"] for messages in chats(ollama)].count(ONE.problem) == 1


def test_running_a_complete_run_again_attempts_nothing(ollama, tmp_path):
    evaluate(ollama, tmp_path / "run")
    before = len(chats(ollama))

    again = evaluate(ollama, tmp_path / "run")

    assert len(chats(ollama)) == before
    assert again["complete"] is True


def test_refuses_to_resume_with_different_generation_settings(ollama, tmp_path):
    evaluate(ollama, tmp_path / "run")

    with pytest.raises(EvaluationError, match="generation"):
        evaluate(ollama, tmp_path / "run", config=config_for(ollama, seed=2))


def test_refuses_to_resume_with_a_different_benchmark(ollama, tmp_path):
    evaluate(ollama, tmp_path / "run")
    other = Benchmark("sample", "https://example.com/problems.jsonl", "def456", "jsonl", None)

    with pytest.raises(EvaluationError, match="benchmark"):
        evaluate(ollama, tmp_path / "run", benchmark=other)


def test_a_half_written_result_is_discarded_and_attempted_again(ollama, tmp_path):
    evaluate(ollama, tmp_path / "run")
    results = tmp_path / "run" / "results.jsonl"
    lines = results.read_text().splitlines()
    results.write_text(lines[0] + "\n" + lines[1] + "\n" + lines[2][:40])
    run = json.loads((tmp_path / "run" / "run.json").read_text())
    (tmp_path / "run" / "run.json").write_text(json.dumps({**run, "complete": False}))

    evaluate(ollama, tmp_path / "run")

    assert [r["id"] for r in read_results(tmp_path / "run")] == ["dev/1", "dev/2", "dev/3"]
    assert [messages[0]["content"] for messages in chats(ollama)].count(THREE.problem) == 2


def test_stops_before_any_attempt_when_a_reference_answer_cannot_be_read(ollama, tmp_path):
    unreadable = Problem("dev/9", "What is this?", " ", "Algebra", 1)

    with pytest.raises(EvaluationError, match="dev/9"):
        evaluate(ollama, tmp_path / "run", problems=[ONE, unreadable])

    assert chats(ollama) == []
    assert not (tmp_path / "run").exists()


def test_the_wrong_checkpoint_stops_the_run_before_anything_is_written(ollama, tmp_path):
    config = config_for(ollama)
    wrong = Config(
        model=ModelPin(name="qwen3:14b", digest="0" * 64),
        runtime=config.runtime,
        generation=config.generation,
        probe=config.probe,
    )

    with pytest.raises(CheckpointError):
        evaluate(ollama, tmp_path / "run", config=wrong)

    assert not (tmp_path / "run").exists()


def test_reports_each_problem_as_it_finishes(ollama, tmp_path):
    lines = []

    evaluate(ollama, tmp_path / "run", report=lines.append)

    assert len(lines) == 3
    assert "1/3" in lines[0] and "dev/1" in lines[0] and "correct" in lines[0]
    assert "3/3" in lines[2] and "dev/3" in lines[2] and "missing" in lines[2]


def test_a_session_records_peak_memory_swap_growth_and_the_runner_command(ollama, tmp_path):
    loading = OllamaTree(resident_bytes=100, runner_commands=())
    loaded = OllamaTree(resident_bytes=900, runner_commands=("llama-server -c 16384",))

    run = evaluate(ollama, tmp_path / "run", sampler=quiet_sampler([loading, loaded], [10, 50]))

    session = run["sessions"][0]
    assert session["peak_memory_bytes"] == 900
    assert session["swap_growth_bytes"] == 40
    assert session["runner_commands"] == ["llama-server -c 16384"]
