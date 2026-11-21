"""The benchmark run: one attempt per problem, saved as it goes, resumable.

A run lives in a directory. `run.json` says what was run and whether it is
complete; `results.jsonl` holds one result per problem, appended as each
finishes. Running again in the same directory attempts only the problems that
have no result yet, and refuses if anything that affects the results differs.
"""

import json
import os
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from pi.benchmarks import Benchmark, Problem
from pi.checkpoint import inspect_checkpoint
from pi.config import Config
from pi.grading import grade, grader_version
from pi.ollama import OllamaClient, OllamaTimeout
from pi.resources import ResourceSampler, without_home

RUN = "run.json"
RESULTS = "results.jsonl"

# What must be the same for two sessions to belong to one run.
_IDENTITY = ("runtime", "model", "generation", "benchmark", "grader")


class EvaluationError(Exception):
    """The run cannot start or continue as asked."""


def run_evaluation(
    config: Config,
    benchmark: Benchmark,
    problems: list[Problem],
    client: OllamaClient,
    sampler: ResourceSampler,
    out: Path,
    *,
    command: list[str],
    code: dict | None,
    clock=time.monotonic,
    report=None,
) -> dict:
    """Attempt every problem that has no result yet, and return the run's description."""
    report = report or _announce
    out = Path(out)
    checkpoint = inspect_checkpoint(config, client)
    _check_references(problems)

    identity = {
        "runtime": checkpoint["runtime"],
        "model": checkpoint["model"],
        "generation": asdict(config.generation),
        "benchmark": {
            "name": benchmark.name,
            "url": benchmark.url,
            "sha256": benchmark.sha256,
            "subset": benchmark.ids is not None,
            "ids": [problem.id for problem in problems],
        },
        "grader": grader_version(),
    }

    if (out / RUN).exists():
        run = json.loads((out / RUN).read_text())
        for key in _IDENTITY:
            if run.get(key) != identity[key]:
                raise EvaluationError(
                    f"{out} holds a run with a different {key}; use another directory"
                )
        results = read_results(out)
        _write_results(out, results)  # drops a half-written last line
    else:
        out.mkdir(parents=True, exist_ok=True)
        run = {"kind": "evaluation", "complete": False, **identity, "sessions": []}
        _write(out / RUN, run)
        results = []

    done = {result["id"] for result in results}
    remaining = [problem for problem in problems if problem.id not in done]
    session = {
        "started_at": _now(),
        "command": command,
        "code": code,
        "attempted": 0,
    }
    try:
        with sampler, (out / RESULTS).open("a") as results_file:
            for problem in remaining:
                result = _attempt(config, client, problem, clock)
                results_file.write(json.dumps(result) + "\n")
                results_file.flush()
                os.fsync(results_file.fileno())
                done.add(problem.id)
                session["attempted"] += 1
                report(_progress(len(done), len(problems), result))
    finally:
        session["ended_at"] = _now()
        session["peak_memory_bytes"] = sampler.peak_resident_bytes
        session["swap_growth_bytes"] = sampler.swap_growth_bytes
        session["runner_commands"] = [without_home(c) for c in sampler.runner_commands]
        run["sessions"].append(session)
        run["complete"] = len(done) == len(problems)
        _write(out / RUN, run)
    return run


def read_results(out: Path) -> list[dict]:
    """The results saved so far, in the order they were written."""
    path = Path(out) / RESULTS
    if not path.exists():
        return []
    lines = path.read_text().splitlines()
    results = []
    for number, line in enumerate(lines, start=1):
        try:
            results.append(json.loads(line))
        except ValueError:
            if number == len(lines):
                break  # the run stopped while writing this line
            raise EvaluationError(f"{path}: line {number} is not a result") from None
    return results


def _attempt(config: Config, client: OllamaClient, problem: Problem, clock) -> dict:
    name = config.model.name
    # A fresh load for every problem: the same seed gives different text when
    # the model still holds an earlier prompt in its cache.
    client.unload(name)

    started = clock()
    try:
        reply = client.chat(name, problem.problem, config.generation)
    except OllamaTimeout:
        reply = None
    elapsed = clock() - started

    # An attempt that hits a limit is unsolved, whatever it had written.
    if reply is None:
        verdict, answer = "timed_out", None
    elif reply.done_reason != "stop":
        verdict, answer = "cut_off", None
    else:
        graded = grade(reply.content, problem.answer)
        verdict, answer = graded.verdict, graded.answer

    speed = None
    if reply is not None and reply.output_seconds > 0:
        speed = reply.output_tokens / reply.output_seconds
    return {
        "id": problem.id,
        "subject": problem.subject,
        "level": problem.level,
        "verdict": verdict,
        "answer": answer,
        "response": None
        if reply is None
        else {
            "content": reply.content,
            "thinking": reply.thinking,
            "done_reason": reply.done_reason,
        },
        "prompt_tokens": None if reply is None else reply.prompt_tokens,
        "cached_prompt_tokens": None if reply is None else reply.cached_prompt_tokens,
        "output_tokens": None if reply is None else reply.output_tokens,
        "output_tokens_per_second": speed,
        "load_seconds": None if reply is None else reply.load_seconds,
        "elapsed_seconds": elapsed,
    }


def _check_references(problems: list[Problem]) -> None:
    """Fail before the first attempt if any reference answer cannot be graded against."""
    unreadable = []
    for problem in problems:
        try:
            grade("", problem.answer)
        except ValueError:
            unreadable.append(problem.id)
    if unreadable:
        shown = ", ".join(unreadable[:5])
        raise EvaluationError(
            f"the grader cannot read the reference answer of {len(unreadable)} problem(s): {shown}"
        )


def _announce(line: str) -> None:
    # Flushed, so a run whose output is piped still shows each result as it finishes.
    print(line, flush=True)


def _progress(position: int, total: int, result: dict) -> str:
    tokens = "-" if result["output_tokens"] is None else result["output_tokens"]
    return (
        f"[{position}/{total}] {result['id']}  {result['verdict']}  "
        f"{tokens} tokens  {result['elapsed_seconds']:.1f} s"
    )


def _write_results(out: Path, results: list[dict]) -> None:
    (out / RESULTS).write_text("".join(json.dumps(result) + "\n" for result in results))


def _write(path: Path, content: dict) -> None:
    partial = path.with_suffix(".partial")
    partial.write_text(json.dumps(content, indent=2) + "\n")
    partial.replace(path)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
