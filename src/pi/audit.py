"""Auditing a finished run from its saved files, before it is published.

An audit takes nothing on trust from the run. It fetches the problem file again
and checks its checksum, grades every saved reply again under the same grader,
rebuilds the report, and checks that each result belongs to a recorded session.
For a scored run, it also checks the scored standard held throughout. It
records the SHA-256 of every file it audited, so a later change to any of them
shows.
"""

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from pi.benchmarks import Benchmark, BenchmarkError, fetch_file, load_problems
from pi.evaluation import RESULTS, RUN, read_results
from pi.grading import grade, grader_version
from pi.lean_project import LeanBenchmark
from pi.report import build_report
from pi.revision import code_revision

REPORT = "report.md"
AUDIT = "audit.json"
# How many offending problems a check names before it says "and N more".
_SHOWN = 5


def audit_run(out: Path, benchmark: Benchmark, data_dir: Path) -> dict:
    """Every check's outcome, and the checksum of each file audited."""
    if isinstance(benchmark, LeanBenchmark):
        from pi.lean_audit import audit_lean_run  # lean_audit imports this module

        return audit_lean_run(out, benchmark, data_dir)
    out = Path(out)
    run = json.loads((out / RUN).read_text())
    results = read_results(out)
    checks = []

    def check(name: str, problems: list[str], detail_when_fine: str = "") -> None:
        detail = detail_when_fine
        if problems:
            shown = ", ".join(problems[:_SHOWN])
            more = f" and {len(problems) - _SHOWN} more" if len(problems) > _SHOWN else ""
            detail = shown + more
        checks.append({"name": name, "passed": not problems, "detail": detail})

    check("complete", [] if run.get("complete") else ["the run is not marked complete"])

    expected = [problem.id for problem in load_problems(benchmark, data_dir)]
    recorded = run["benchmark"]
    differs = [
        field
        for field, value in (
            ("url", benchmark.url),
            ("sha256", benchmark.sha256),
            ("ids", expected),
        )
        if recorded.get(field) != value
    ]
    check("benchmark", [f"the definition's {field} differs from the run's" for field in differs])

    try:
        fetched = fetch_file(benchmark, data_dir)
        check("problem file", [], f"SHA-256 {benchmark.sha256} matches, from {fetched.source}")
    except BenchmarkError as error:
        check("problem file", [str(error)])

    counts = Counter(result["id"] for result in results)
    check(
        "one result per problem",
        [f"{id} has no result" for id in expected if counts[id] == 0]
        + [f"{id} has {n} results" for id, n in counts.items() if n > 1]
        + [f"{id} is not in the benchmark" for id in counts if id not in set(expected)],
    )

    current = grader_version()
    check(
        "grader",
        []
        if run["grader"] == current
        else [f"the run used {run['grader']}, this pi has {current}"],
    )

    answers = {problem.id: problem.answer for problem in load_problems(benchmark, data_dir)}
    check("verdicts", [r["id"] for r in results if not _verdict_follows(r, answers.get(r["id"]))])

    sessions = len(run.get("sessions", []))
    check(
        "sessions",
        [r["id"] for r in results if "session" in r and not 0 <= r["session"] < sessions],
    )

    if recorded.get("scored"):
        check("scored standard", _scored_problems(run, results))

    report_path = out / REPORT
    if not report_path.exists():
        check("report", [f"there is no {REPORT}"])
    else:
        rebuilt = build_report(out) == report_path.read_text()
        check("report", [] if rebuilt else [f"{REPORT} differs from what the records rebuild"])

    files = {
        name: _fingerprint(out / name) for name in (RUN, RESULTS, REPORT) if (out / name).exists()
    }
    return {
        "run": out.name,
        "audited_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "code": code_revision(Path(__file__).parent),
        "grader": current,
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "files": files,
    }


def fingerprint(path: Path) -> dict:
    """A file's SHA-256 and size."""
    return _fingerprint(Path(path))


def _verdict_follows(result: dict, reference: str | None) -> bool:
    """Whether the recorded verdict and answer are what the saved reply gives."""
    response = result["response"]
    if response is None:
        return result["verdict"] == "timed_out" and result["answer"] is None
    if response["done_reason"] != "stop":
        return result["verdict"] == "cut_off" and result["answer"] is None
    if reference is None:
        return False
    graded = grade(response["content"], reference)
    return (graded.verdict, graded.answer) == (result["verdict"], result["answer"])


def _scored_problems(run: dict, results: list[dict]) -> list[str]:
    problems = []
    for index, session in enumerate(run["sessions"]):
        code = session.get("code")
        if code is None or code.get("dirty"):
            problems.append(f"session {index} ran uncommitted code")
        if session.get("weights_verified") is not True:
            problems.append(f"session {index} did not verify the weights")
    for result in results:
        power = result.get("power")
        if power is not None and power.get("source") != "AC Power":
            problems.append(f"{result['id']} ran on {power.get('source')}")
    return problems


def _fingerprint(path: Path) -> dict:
    content = path.read_bytes()
    return {"sha256": hashlib.sha256(content).hexdigest(), "size": len(content)}
