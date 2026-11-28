"""Auditing a finished Lean run: every saved proof is checked again with Lean.

Like the answer audit, it takes nothing on trust and only reads the run. Here a verdict means
"Lean and a judge program accepted this proof", so the `verdicts` check grades each saved reply
again, one Lean check at a time. It takes hours, so it comes last and runs only when the checks
it rests on passed. When in doubt a check fails and names the theorem.
"""

import json
import time
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

from pi.audit import REPORT, _scored_problems, fingerprint
from pi.evaluation import RESULTS, RUN, read_results, shown_verdict
from pi.lean_evaluation import PROOFS
from pi.lean_grading import Limits, assemble, check, extract_code, flags, lean_grader_version
from pi.lean_project import LeanBenchmark, LeanRunner, lean_environment, load_theorems
from pi.lean_statements import Theorem
from pi.report import build_report
from pi.revision import code_revision

# How many offending theorems a check names before it says "and N more".
_SHOWN = 5
# A result is checked again with this many times the limits the run was made under, so a check
# that finished within a limit in the run has room to finish again on a busier machine.
_FACTOR = 4
# The checks `verdicts` rests on: when one failed, the long re-check is not run.
_PREREQUISITES = ("benchmark", "lean environment", "grader", "one result per problem")
_NOT_RUN = "not run: an earlier check failed"
# What a record with a missing key or a value of the wrong type raises when it is read.
_MALFORMED = (KeyError, TypeError, AttributeError, ValueError, IndexError)
_ENVIRONMENT_KEYS = ("toolchain", "lean_version", "files", "options")


def audit_lean_run(
    out: Path,
    benchmark: LeanBenchmark,
    data_dir: Path,
    runner=None,
    report: Callable[[str], None] = lambda line: None,
) -> dict:
    """Every check's outcome, and the checksum of each file audited.

    `report` is given one line for each result checked again with Lean, as it finishes.
    """
    out = Path(out)
    # Without Lean set up this raises the error that names `pi lean-setup`: the audit stops.
    environment = lean_environment(benchmark, data_dir)
    theorems = load_theorems(benchmark, data_dir)
    runner = runner or LeanRunner(benchmark, data_dir)
    run = json.loads((out / RUN).read_text())
    results = [r if isinstance(r, dict) else {} for r in read_results(out)]
    checks: list[dict] = []

    def record(name: str, problems: Callable[[], list[str]], when_fine: str = "") -> None:
        try:
            found = problems()
        except _MALFORMED as error:
            found = [f"the records are malformed ({type(error).__name__}: {error})"]
        detail = when_fine
        if found:
            more = f" and {len(found) - _SHOWN} more" if len(found) > _SHOWN else ""
            detail = ", ".join(found[:_SHOWN]) + more
        checks.append({"name": name, "passed": not found, "detail": detail})

    record("complete", lambda: [] if run.get("complete") else ["the run is not marked complete"])
    record("benchmark", lambda: _benchmark_problems(run, benchmark, theorems, environment))
    record("lean environment", lambda: _environment_problems(run, environment))
    record("one result per problem", lambda: _result_count_problems(results, theorems))
    current = lean_grader_version(benchmark)
    record("grader", lambda: _grader_problems(run, current))
    record("proof files", lambda: _proof_file_problems(out, results, theorems))
    sessions = len(run.get("sessions", []))
    record("sessions", lambda: [r["id"] for r in results if _bad_session(r, sessions)])
    if run["benchmark"].get("scored"):
        record("scored standard", lambda: _scored_problems(run, results))
    record("report", lambda: _report_problems(out))
    if any(not c["passed"] for c in checks if c["name"] in _PREREQUISITES):
        checks.append({"name": "verdicts", "passed": False, "detail": _NOT_RUN})
    else:
        record(
            "verdicts", lambda: _verdict_problems(run, results, theorems, benchmark, runner, report)
        )

    return {
        "run": out.name,
        "audited_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "code": code_revision(Path(__file__).parent),
        "grader": current,
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "files": _fingerprints(out),
    }


def _benchmark_problems(
    run: dict, benchmark: LeanBenchmark, theorems: list[Theorem], environment: dict
) -> list[str]:
    recorded = run["benchmark"]
    wanted = (
        ("kind", "lean"),
        ("name", benchmark.name),
        ("subset", benchmark.ids is not None),
        ("scored", benchmark.scored),
        ("sha256", environment["files"][benchmark.file]),
        ("repository", benchmark.repository),
        ("commit", benchmark.commit),
        ("file", benchmark.file),
        ("ids", [theorem.id for theorem in theorems]),
    )
    return [
        f"the definition's {field} differs from the run's"
        for field, value in wanted
        if recorded.get(field) != value
    ]


def _environment_problems(run: dict, environment: dict) -> list[str]:
    saved = run["lean"]
    return [
        f"{key} differs from the run's"
        for key in _ENVIRONMENT_KEYS
        if saved.get(key) != environment[key]
    ]


def _result_count_problems(results: list[dict], theorems: list[Theorem]) -> list[str]:
    expected = [theorem.id for theorem in theorems]
    counts = Counter(result.get("id") for result in results)
    return (
        [f"{id} has no result" for id in expected if counts[id] == 0]
        + [f"{id} has {n} results" for id, n in counts.items() if n > 1]
        + [f"{id} is not in the benchmark" for id in counts if id not in set(expected)]
    )


def _grader_problems(run: dict, current: dict) -> list[str]:
    if run["grader"] == current:
        return []
    return [f"the run used {run['grader']}, this pi has {current}"]


def _bad_session(result: dict, sessions: int) -> bool:
    if "session" not in result:
        return False
    session = result["session"]
    return not (
        isinstance(session, int) and not isinstance(session, bool) and 0 <= session < sessions
    )


def _report_problems(out: Path) -> list[str]:
    path = out / REPORT
    if not path.exists():
        return [f"there is no {REPORT}"]
    if build_report(out) != path.read_text():
        return [f"{REPORT} differs from what the records rebuild"]
    return []


# The verdicts check: each saved reply is graded again.


def _verdict_problems(
    run: dict,
    results: list[dict],
    theorems: list[Theorem],
    benchmark: LeanBenchmark,
    runner,
    report: Callable[[str], None],
) -> list[str]:
    by_id = {theorem.id: theorem for theorem in theorems}
    settings = run["lean"]
    limits = Limits(
        _seconds(settings["compile_time_limit_seconds"]),
        _seconds(settings["judge_time_limit_seconds"]),
    )
    problems = []
    for position, result in enumerate(results, start=1):
        name = result.get("id")
        done = partial(_report_recheck, report, position, len(results), result)
        try:
            follows = _verdict_follows(result, by_id.get(name), limits, benchmark, runner, done)
        except _MALFORMED:
            follows = False
        if not follows:
            problems.append(str(name))
    return problems


def _report_recheck(
    report: Callable[[str], None], position: int, total: int, result: dict, seconds: float
) -> None:
    try:
        verdict = shown_verdict(result)
    except _MALFORMED:
        verdict = "?"
    report(f"[{position}/{total}] {result.get('id')}  {verdict}  re-checked in {seconds:.1f} s")


def _seconds(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise ValueError(f"{value!r} is not a time limit")
    return value


def _verdict_follows(
    result: dict,
    theorem: Theorem | None,
    limits: Limits,
    benchmark: LeanBenchmark,
    runner,
    done: Callable[[float], None],
) -> bool:
    """Whether the recorded verdict, proof and Lean record are what the saved reply gives.

    `limits` are the run's own; a result checked again with Lean is checked at `_FACTOR` times
    them, and `done` is then given the seconds that took.
    """
    if theorem is None or result["answer"] is not None:
        return False
    response = result["response"]
    if response is None:
        return _ungraded(result, "timed_out")
    if response["done_reason"] != "stop":
        return _ungraded(result, "cut_off")
    code = extract_code(response["content"])
    if code is None:
        return _ungraded(result, "missing")
    if result["proof"] != code or not isinstance(result["lean"], dict):
        return False
    recorded = result["lean"]
    if recorded["flags"] != flags(code):
        return False
    verdict = result["verdict"]
    if verdict not in ("proved", "failed"):
        return False
    reason = recorded["reason"]
    if verdict == "failed" and reason == "check_timed_out":
        return _ran_to_the_limit(recorded, limits)
    longer = Limits(limits.compile_seconds * _FACTOR, limits.judge_seconds * _FACTOR)
    started = time.monotonic()
    again = _graded(theorem, response, runner, longer, benchmark)
    done(time.monotonic() - started)
    if verdict == "proved":
        return again.verdict == "proved" and reason is None and _same_axioms(recorded, again.lean)
    return (
        again.verdict == "failed"
        and again.lean["reason"] == reason
        and _same_axioms(recorded, again.lean)
    )


def _same_axioms(recorded: dict, again: dict) -> bool:
    """The same axioms, in any order and however often each is listed."""
    axioms = recorded["axioms"]
    return isinstance(axioms, list) and set(axioms) == set(again["axioms"])


def _ungraded(result: dict, verdict: str) -> bool:
    return (result["verdict"], result["proof"], result["lean"]) == (verdict, None, None)


def _graded(theorem: Theorem, response: dict, runner, limits: Limits, benchmark: LeanBenchmark):
    return check(theorem, response["content"], runner, limits, benchmark.allowed_axioms)


def _ran_to_the_limit(lean: dict, limits: Limits) -> bool:
    """Whether the time of the step that timed out reached that step's limit.

    The judge did not run when `judge_seconds` is None, so the compile timed out.
    """
    if lean["judge_seconds"] is None:
        return _at_least(lean["compile_seconds"], limits.compile_seconds)
    return _at_least(lean["judge_seconds"], limits.judge_seconds)


def _at_least(seconds: object, limit: float) -> bool:
    return isinstance(seconds, int | float) and not isinstance(seconds, bool) and seconds >= limit


# The proof files.


def _proof_file_problems(out: Path, results: list[dict], theorems: list[Theorem]) -> list[str]:
    by_id = {theorem.id: theorem for theorem in theorems}
    folder = out / PROOFS
    proved = {r.get("id"): r for r in results if r.get("verdict") == "proved"}
    problems = []
    for name, result in proved.items():
        path = folder / f"{name}.lean"
        try:
            expected = assemble(by_id[name], result["proof"])
            same = path.is_file() and not path.is_symlink() and path.read_text("utf-8") == expected
        except (*_MALFORMED, OSError):
            same = False
        if not same:
            problems.append(f"{name} has no proof file that matches its proof")
    if folder.exists() or folder.is_symlink():
        if not folder.is_dir():
            return problems + [f"{PROOFS} is not a directory"]
        wanted = {f"{name}.lean" for name in proved}
        problems += [
            f"{PROOFS}/{p.name} is not a proved theorem's proof file: remove it"
            for p in _listing(folder)
            if p.name not in wanted
        ]
    return problems


def _listing(folder: Path) -> list[Path]:
    return sorted(folder.iterdir())


def _fingerprints(out: Path) -> dict:
    files = {
        name: fingerprint(out / name) for name in (RUN, RESULTS, REPORT) if (out / name).exists()
    }
    folder = out / PROOFS
    if folder.is_dir():
        for path in _listing(folder):
            if path.is_file():
                files[f"{PROOFS}/{path.name}"] = fingerprint(path)
    return files
