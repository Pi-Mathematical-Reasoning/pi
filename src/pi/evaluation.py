"""The benchmark run: one attempt per problem, saved as it goes, resumable.

A run lives in a directory. `run.json` says what was run and whether it is
complete; `results.jsonl` holds one result per problem, appended as each
finishes. Running again in the same directory attempts only the problems that
have no result yet, and refuses if anything that affects the results differs.
"""

import json
import os
import re
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from pi.benchmarks import Benchmark, Problem
from pi.checkpoint import inspect_checkpoint, verify_weights
from pi.config import Config
from pi.grading import grade, grader_version
from pi.ollama import OllamaClient, OllamaTimeout
from pi.resources import (
    ResourceSampler,
    read_machine,
    read_power,
    read_thermal,
    read_wake,
    without_home,
)

RUN = "run.json"
RESULTS = "results.jsonl"

# What must be the same for two sessions to belong to one run, besides what the task adds.
_IDENTITY = ("runtime", "model", "generation")

# How many times one problem is attempted again when the machine sleeps through it.
_SLEEP_RETRIES = 3


class EvaluationError(Exception):
    """The run cannot start or continue as asked."""


class AnswerTask:
    """A benchmark whose reply ends in an answer, graded against a reference answer."""

    blank: dict = {}  # extra fields of an ungraded result

    def identity(self, benchmark: Benchmark, problems: list[Problem]) -> dict:
        """What, besides the model and its settings, must stay the same across sessions."""
        return {
            "benchmark": {
                "name": benchmark.name,
                "url": benchmark.url,
                "sha256": benchmark.sha256,
                "subset": benchmark.ids is not None,
                "scored": benchmark.scored,
                "ids": [problem.id for problem in problems],
            },
            "grader": grader_version(),
        }

    def check(self, problems: list[Problem]) -> None:
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
                f"the grader cannot read the reference answer of {len(unreadable)} "
                f"problem(s): {shown}"
            )

    def begin(self, problem: Problem) -> None:
        """Called first in every attempt; an answer run keeps nothing outside its records."""

    def prompt(self, problem: Problem) -> str:
        return problem.problem

    def grade(self, problem: Problem, content: str) -> dict:
        graded = grade(content, problem.answer)
        return {"verdict": graded.verdict, "answer": graded.answer}


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
    read_power=read_power,
    problem_file: str | None = None,
    read_wake=read_wake,
    read_machine=read_machine,
    verify_weights=verify_weights,
    read_thermal=read_thermal,
    task=None,
) -> dict:
    """Attempt every problem that has no result yet, and return the run's description.

    A scored benchmark also requires committed code, mains power at every
    attempt, and a weights file whose content matches its checksum.
    """
    report = report or _announce
    task = task or AnswerTask()
    out = Path(out)
    if benchmark.scored and (code is None or code["dirty"]):
        raise EvaluationError(
            "a scored run needs committed code: commit or stash every change, "
            "and run pi from a git checkout"
        )
    checkpoint = inspect_checkpoint(config, client)
    task.check(problems)
    weights_verified = None
    if benchmark.scored:
        weights_verified = verify_weights(checkpoint["model"]["weights"])
        if weights_verified is not True:
            why = (
                "its content does not match its name"
                if weights_verified is False
                else ("it was not found")
            )
            raise EvaluationError(
                f"the weights file {checkpoint['model']['weights']} could not be verified: {why}"
            )

    identity = {
        "runtime": checkpoint["runtime"],
        "model": checkpoint["model"],
        "generation": asdict(config.generation),
        **task.identity(benchmark, problems),
    }

    if (out / RUN).exists():
        run = json.loads((out / RUN).read_text())
        for key in (*_IDENTITY, *task.identity(benchmark, problems)):
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
        "ended_at": None,
        "command": command,
        "code": code,
        "machine": read_machine(),
        # Where this session's copy of the problem file came from: the mirror or
        # the upstream. Not part of the run's identity: the bytes are the same.
        "problem_file": problem_file,
        "weights_verified": weights_verified,
        "attempted": 0,
    }
    # On record before the first attempt, so a hard stop still leaves it.
    run["sessions"].append(session)
    index = len(run["sessions"]) - 1
    _write(out / RUN, run)
    try:
        with sampler, (out / RESULTS).open("a") as results_file:
            for problem in remaining:
                result = _attempt_awake(
                    config,
                    client,
                    problem,
                    clock,
                    read_power,
                    read_wake,
                    benchmark,
                    report,
                    sampler,
                    read_thermal,
                    task,
                )
                _check_runner(run, sampler, out)
                result = {"session": index, **result}
                results_file.write(json.dumps(result) + "\n")
                results_file.flush()
                os.fsync(results_file.fileno())
                done.add(problem.id)
                session["attempted"] += 1
                # Kept current, so a session stopped outright still has its count.
                _write(out / RUN, run)
                report(_progress(len(done), len(problems), result))
    finally:
        session["ended_at"] = _now()
        session["peak_memory_bytes"] = sampler.peak_resident_bytes
        session["swap_growth_bytes"] = sampler.swap_growth_bytes
        session["runner_commands"] = [without_home(c) for c in sampler.runner_commands]
        run["complete"] = len(done) == len(problems)
        _write(out / RUN, run)
    return run


def _attempt_awake(
    config,
    client,
    problem,
    clock,
    read_power,
    read_wake,
    benchmark,
    report,
    sampler,
    read_thermal,
    task,
):
    """One attempt the machine stayed awake through.

    An attempt the machine slept through is thrown away and made again: its time
    measured the sleep, and a time limit it hit would be the laptop's, not the
    model's. A fresh load makes the new attempt write the same reply.
    """
    discarded = []
    for _ in range(_SLEEP_RETRIES + 1):
        if benchmark.scored:
            power = read_power()
            if power is not None and power["source"] != "AC Power":
                raise EvaluationError(
                    f"the machine is on {power['source'].lower()}: a scored run is made on "
                    "mains power, which is a third faster; plug in and run the same "
                    "command again to resume"
                )
        before = read_wake()
        result = _attempt(config, client, problem, task, clock, read_power, sampler, read_thermal)
        if read_wake() == before:
            return {**result, "discarded_attempts": discarded}
        discarded.append(
            {
                "started_at": result["started_at"],
                "ended_at": result["ended_at"],
                "reason": "the machine slept",
            }
        )
        report(f"the machine slept during {problem.id}; attempting it again")
    raise EvaluationError(
        f"the machine slept during {_SLEEP_RETRIES + 1} attempts at {problem.id}; keep it "
        "awake (on mains, lid open, `caffeinate -i`) and run the same command again"
    )


_PORT = re.compile(r"\s--port\s+\d+")


def _check_runner(run: dict, sampler: ResourceSampler, out: Path) -> None:
    """Hold the model runner's launch settings fixed for the whole run.

    They include the cache type and flash attention, which change the numbers. The
    first settings seen are recorded; a different launch stops the run before the
    attempt it made is kept. Only the port, which changes at every load, is ignored.
    """
    # In an answer run the model of the attempt just made is still loaded. A Lean run unloads
    # it before its check, so this sample finds no runner and the commands stay those the
    # attempt's own sample saw, taken while the model was loaded.
    sampler.sample()
    seen = [_PORT.sub("", without_home(c)) for c in sampler.runner_commands]
    if not seen:
        return
    recorded = run.get("runner")
    if recorded is None:
        run["runner"] = seen
        _write(out / RUN, run)
    elif seen != recorded:
        raise EvaluationError(
            "the model runner was launched with different settings from the rest of the "
            f"run: {seen} instead of {recorded}; restore Ollama's settings to resume"
        )


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


def _attempt(
    config: Config,
    client: OllamaClient,
    problem: Problem,
    task,
    clock,
    read_power,
    sampler: ResourceSampler | None = None,
    read_thermal=lambda: None,
) -> dict:
    task.begin(problem)
    name = config.model.name
    # Battery or mains: the machine generates markedly slower on battery.
    power = read_power()
    # A fresh load for every problem: the same seed gives different text when
    # the model still holds an earlier prompt in its cache.
    unload_started = time.monotonic()
    client.unload(name)
    unload_seconds = time.monotonic() - unload_started

    if sampler is not None:
        sampler.begin_attempt()
    started_at = _now()
    started = clock()
    try:
        reply = client.chat(name, task.prompt(problem), config.generation)
    except OllamaTimeout:
        reply = None
    elapsed = clock() - started
    ended_at = _now()
    if sampler is not None:
        sampler.sample()  # the model is still loaded: this attempt's own figures
    thermal = read_thermal()

    # An attempt that hits a limit is unsolved, whatever it had written.
    if reply is None:
        graded = {"verdict": "timed_out", "answer": None, **task.blank}
    elif reply.done_reason != "stop":
        graded = {"verdict": "cut_off", "answer": None, **task.blank}
    else:
        graded = task.grade(problem, reply.content)

    speed = None
    if reply is not None and reply.output_seconds > 0:
        speed = reply.output_tokens / reply.output_seconds
    return {
        "id": problem.id,
        "started_at": started_at,
        "subject": problem.subject,
        "level": problem.level,
        "verdict": graded["verdict"],
        "answer": graded["answer"],
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
        "prompt_seconds": None if reply is None else reply.prompt_seconds,
        "output_seconds": None if reply is None else reply.output_seconds,
        "total_seconds": None if reply is None else reply.total_seconds,
        "elapsed_seconds": elapsed,
        "ended_at": ended_at,
        "unload_seconds": unload_seconds,
        # (tokens so far, seconds since the request): time to first token, then
        # every 256 tokens, then the last.
        "progress": None if reply is None else reply.progress,
        "peak_memory_bytes": None if sampler is None else sampler.attempt_peak_resident_bytes,
        "swap_used_bytes": None if sampler is None else sampler.last_swap_bytes,
        "thermal": thermal,
        "power": power,
        # Everything Ollama reported about the attempt, as it reported it.
        "metrics": None if reply is None else reply.metrics,
        **{key: value for key, value in graded.items() if key not in ("verdict", "answer")},
    }


def _announce(line: str) -> None:
    # Flushed, so a run whose output is piped still shows each result as it finishes.
    print(line, flush=True)


def _progress(position: int, total: int, result: dict) -> str:
    tokens = "-" if result["output_tokens"] is None else result["output_tokens"]
    return (
        f"[{position}/{total}] {result['id']}  {shown_verdict(result)}  "
        f"{tokens} tokens  {result['elapsed_seconds']:.1f} s"
    )


def shown_verdict(result: dict) -> str:
    """The verdict, and for a failed Lean result its reason: `failed (lean_error)`."""
    lean = result.get("lean")  # only Lean results have it
    if result["verdict"] == "failed" and isinstance(lean, dict) and lean.get("reason"):
        return f"failed ({lean['reason']})"
    return result["verdict"]


def _write_results(out: Path, results: list[dict]) -> None:
    (out / RESULTS).write_text("".join(json.dumps(result) + "\n" for result in results))


def _write(path: Path, content: dict) -> None:
    partial = path.with_suffix(".partial")
    partial.write_text(json.dumps(content, indent=2) + "\n")
    partial.replace(path)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
