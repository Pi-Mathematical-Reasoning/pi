"""The `pi` command."""

import argparse
import contextlib
import json
import signal
import sys
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from pi.audit import AUDIT, REPORT, audit_run
from pi.benchmarks import BenchmarkError, fetch_file, load_benchmark, load_problems
from pi.checkpoint import CheckpointError
from pi.config import ConfigError, load_config
from pi.evaluation import RUN, EvaluationError, run_evaluation
from pi.grading import grade, grader_version
from pi.lean_audit import audit_lean_run
from pi.lean_evaluation import LeanTask
from pi.lean_grading import Limits
from pi.lean_grading import check as check_proof
from pi.lean_project import (
    LeanBenchmark,
    LeanRunner,
    checkout_dir,
    lean_environment,
    load_theorems,
    setup,
)
from pi.lean_statements import Theorem
from pi.ollama import OllamaClient, OllamaError
from pi.probe import run_probe, summarize
from pi.publish import PublishError, publish_run, run_bucket
from pi.report import build_report
from pi.resources import ResourceSampler
from pi.revision import code_revision
from pi.s3 import AwsCli, S3Error

#: The repository's jaws project file, which names the artifacts bucket.
PROJECT_FILE = Path(__file__).resolve().parents[2] / "jaws.yaml"


def main(argv: list[str] | None = None) -> int:
    with termination_as_interrupt():
        return _main(argv)


@contextlib.contextmanager
def termination_as_interrupt() -> Iterator[None]:
    """Stop on SIGTERM and SIGHUP as on Ctrl-C, so the paths that kill Lean's process group run.

    Without this the signal ends Python at once, and a check's processes outlive it with no
    limit, since the limit is kept by the process that died. The old handlers come back after.
    """
    if threading.current_thread() is not threading.main_thread():
        yield  # only the main thread may set signal handlers
        return

    def interrupt(number, frame):
        raise KeyboardInterrupt

    numbers = (signal.SIGTERM, signal.SIGHUP)
    previous = {number: signal.signal(number, interrupt) for number in numbers}
    try:
        yield
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


def _main(argv: list[str] | None) -> int:
    arguments = sys.argv[1:] if argv is None else list(argv)
    options = _parser().parse_args(arguments)
    if options.command == "probe":
        return _probe(options, arguments)
    if options.command == "grade":
        return _grade(options)
    if options.command == "eval":
        return _eval(options, arguments)
    if options.command == "audit":
        return _audit(options)
    if options.command == "publish":
        return _publish(options)
    if options.command == "lean-setup":
        return _lean_setup(options)
    if options.command == "lean-check":
        return _lean_check(options)
    return _report(options)


def _audit(options: argparse.Namespace) -> int:
    out = options.run
    try:
        benchmark = load_benchmark(options.benchmark)
        if not (out / REPORT).exists():
            (out / REPORT).write_text(build_report(out))
            print(f"wrote {out / REPORT} from the records")
        if isinstance(benchmark, LeanBenchmark):  # hours of Lean: each re-check is shown
            audit = audit_lean_run(out, benchmark, options.data_dir, report=_announce)
        else:
            audit = audit_run(out, benchmark, options.data_dir)
    except (OSError, ValueError, KeyError, BenchmarkError, EvaluationError) as error:
        return _fail(f"cannot audit {out}: {error}")

    (out / AUDIT).write_text(json.dumps(audit, indent=2) + "\n")
    for check in audit["checks"]:
        mark = "passed" if check["passed"] else "FAILED"
        detail = f" ({check['detail']})" if check["detail"] else ""
        print(f"{mark}: {check['name']}{detail}")
    verdict = "audit passed" if audit["passed"] else "audit FAILED"
    print(f"{verdict}; written to {out / AUDIT}")
    return 0 if audit["passed"] else 1


def _lean_setup(options: argparse.Namespace) -> int:
    try:
        setup(_lean_benchmark(options.benchmark), options.data_dir)
    except BenchmarkError as error:
        return _fail(error)
    return 0


def _lean_check(options: argparse.Namespace) -> int:
    try:
        config = load_config(options.config)
        if config.lean is None:
            raise ConfigError(f"{options.config} has no [lean] section, which sets the limits")
        benchmark = _lean_benchmark(options.benchmark)
        lean_environment(benchmark, options.data_dir)
        theorem = _theorem(benchmark, options.data_dir, options.id)
        reply = options.reply.read_text(encoding="utf-8")
        settings = config.lean
        limits = Limits(settings.compile_time_limit_seconds, settings.judge_time_limit_seconds)
        runner = LeanRunner(benchmark, options.data_dir)
        result = check_proof(theorem, reply, runner, limits, benchmark.allowed_axioms)
    except (OSError, UnicodeDecodeError, ConfigError, BenchmarkError) as error:
        return _fail(error)

    print(result.verdict)
    lean = result.lean
    if lean is None:
        print("  reason         no closed Lean code block in the reply")
        return 0
    judge_seconds = "not run" if lean["judge_seconds"] is None else f"{lean['judge_seconds']:.1f} s"
    print(f"  reason         {lean['reason'] or 'none'}")
    print(f"  axioms         {', '.join(lean['axioms']) or 'none'}")
    print(f"  flags          {', '.join(lean['flags']) or 'none'}")
    print(f"  compile        {lean['compile_seconds']:.1f} s")
    print(f"  judge          {judge_seconds}")
    return 0


def _lean_benchmark(path: Path) -> LeanBenchmark:
    benchmark = load_benchmark(path)
    if not isinstance(benchmark, LeanBenchmark):
        raise BenchmarkError(f'{path} is not a Lean benchmark (kind = "lean")')
    return benchmark


def _theorem(benchmark: LeanBenchmark, data_dir: Path, id: str) -> Theorem:
    for theorem in load_theorems(benchmark, data_dir):
        if theorem.id == id:
            return theorem
    raise BenchmarkError(f"{benchmark.name}: no theorem with id {id}")


def _publish(options: argparse.Namespace) -> int:
    try:
        bucket, prefix = run_bucket(PROJECT_FILE)
        outcome = publish_run(options.run, bucket, AwsCli(profile=options.profile), prefix)
    except (OSError, PublishError, S3Error) as error:
        return _fail(error)
    for name, result in outcome.items():
        print(f"{name}: {result}")
    print(f"published to s3://{bucket}/{prefix}{options.run.name}/")
    return 0


def _probe(options: argparse.Namespace, arguments: list[str]) -> int:
    try:
        config = load_config(options.config)
        record = run_probe(
            config,
            OllamaClient(config.runtime.host),
            ResourceSampler(),
            command=["pi", *arguments],
            # The checkout this package was imported from, wherever pi was run.
            code=code_revision(Path(__file__).parent),
        )
    except (ConfigError, CheckpointError, OllamaError) as error:
        return _fail(error)

    out = options.out or Path("runs") / f"probe-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=2) + "\n")
    print(summarize(record))
    print(f"record written to {out}")
    return 0


def _grade(options: argparse.Namespace) -> int:
    try:
        reply = options.reply if options.record is None else _reply_in(options.record)
        result = grade(reply, options.reference)
    except (OSError, ValueError) as error:
        return _fail(error)

    version = grader_version()
    print(result.verdict)
    print(f"  final answer   {'none found' if result.answer is None else result.answer}")
    print(f"  reference      {options.reference}")
    print(f"  grader         rules {version['rules']}, math-verify {version['math_verify']}")
    return 0


def _eval(options: argparse.Namespace, arguments: list[str]) -> int:
    resume = f"the run is incomplete: run the same command again to resume {options.out}"
    try:
        config = load_config(options.config)
        benchmark = load_benchmark(options.benchmark)
        if isinstance(benchmark, LeanBenchmark):
            _eval_lean(options, arguments, config, benchmark)
            return _finished(options)
        fetched = fetch_file(benchmark, options.data_dir)
        for warning in fetched.warnings:
            print(f"warning: {warning}", file=sys.stderr)
        print(f"problem file from {fetched.source}", flush=True)
        problems = load_problems(benchmark, options.data_dir)
        run_evaluation(
            config,
            benchmark,
            problems,
            OllamaClient(config.runtime.host),
            # A run lasts hours, so memory is sampled less often than in the probe.
            ResourceSampler(interval=5),
            options.out,
            command=["pi", *arguments],
            code=code_revision(Path(__file__).parent),
            problem_file=fetched.source,
        )
    except KeyboardInterrupt:
        print(f"\ninterrupted; {resume}", file=sys.stderr)
        return 130
    except (
        ConfigError,
        BenchmarkError,
        CheckpointError,
        EvaluationError,
        OllamaError,
    ) as error:
        status = _fail(error)
        if (options.out / RUN).exists():
            print(resume, file=sys.stderr)
        return status

    return _finished(options)


def _eval_lean(
    options: argparse.Namespace, arguments: list[str], config, benchmark: LeanBenchmark
) -> None:
    """Run a Lean benchmark; nothing is written and no model is contacted until Lean is ready."""
    if config.lean is None:
        raise ConfigError(
            f"{options.config} has no [lean] section, which holds the instruction and the limits"
        )
    environment = lean_environment(benchmark, options.data_dir)
    theorems = load_theorems(benchmark, options.data_dir)
    checkout = checkout_dir(options.data_dir, benchmark.repository, benchmark.commit)
    print(f"lean project {checkout} at {benchmark.commit[:12]}", flush=True)
    client = OllamaClient(config.runtime.host)
    task = LeanTask(
        benchmark,
        config.lean,
        LeanRunner(benchmark, options.data_dir),
        environment,
        options.out,
        release=lambda: client.unload(config.model.name),
    )
    run_evaluation(
        config,
        benchmark,
        theorems,
        client,
        ResourceSampler(interval=5),
        options.out,
        command=["pi", *arguments],
        code=code_revision(Path(__file__).parent),
        problem_file=f"{benchmark.repository}@{benchmark.commit}",
        task=task,
    )


def _finished(options: argparse.Namespace) -> int:
    print(build_report(options.out).splitlines()[0].removeprefix("# "))
    print(f"results in {options.out}; `pi report {options.out}` prints the full report")
    return 0


def _report(options: argparse.Namespace) -> int:
    try:
        report = build_report(options.run)
    except (OSError, ValueError, KeyError, EvaluationError) as error:
        return _fail(f"cannot read a run in {options.run}: {error}")

    if options.out is None:
        print(report, end="")
    else:
        options.out.parent.mkdir(parents=True, exist_ok=True)
        options.out.write_text(report)
        print(f"report written to {options.out}")
    return 0


def _announce(line: str) -> None:
    print(line, flush=True)


def _reply_in(record: Path) -> str:
    """The visible reply saved in a record: never the reasoning, and empty if there was none."""
    response = json.loads(record.read_text()).get("response") or {}
    return response.get("content", "")


def _fail(error: Exception | str) -> int:
    print(f"error: {error}", file=sys.stderr)
    return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pi", description="Local-first mathematical reasoning.")
    commands = parser.add_subparsers(dest="command", required=True)

    probe = commands.add_parser(
        "probe",
        help="run one problem and record the checkpoint, its speed and its memory",
    )
    probe.add_argument("--config", required=True, type=Path, help="the run configuration, in TOML")
    probe.add_argument(
        "--out", type=Path, help="where to write the record (default: runs/probe-<time>.json)"
    )

    grading = commands.add_parser(
        "grade",
        help="find the final answer in a reply and compare it with a reference answer",
    )
    grading.add_argument("--reference", required=True, help="the reference answer, in LaTeX")
    source = grading.add_mutually_exclusive_group(required=True)
    source.add_argument("--reply", help="the reply text to grade")
    source.add_argument("--record", type=Path, help="a record whose saved reply to grade")

    evaluation = commands.add_parser(
        "eval",
        help="attempt every problem of a benchmark once, saving each result as it finishes",
    )
    evaluation.add_argument(
        "--config", required=True, type=Path, help="the run configuration, in TOML"
    )
    evaluation.add_argument(
        "--benchmark", required=True, type=Path, help="the benchmark definition, in TOML"
    )
    evaluation.add_argument(
        "--out",
        required=True,
        type=Path,
        help="the run directory; give the same one again to resume an interrupted run",
    )
    evaluation.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data"),
        help="where fetched problem files are kept (default: data)",
    )

    audit = commands.add_parser(
        "audit",
        help="check a finished run from its saved files and write audit.json, without the model",
    )
    audit.add_argument("run", type=Path, help="the run directory")
    audit.add_argument(
        "--benchmark", required=True, type=Path, help="the benchmark definition it was run on"
    )
    audit.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data"),
        help="where fetched problem files are kept (default: data)",
    )

    lean_setup = commands.add_parser(
        "lean-setup",
        help="check out and build a Lean benchmark's project and judge at their pinned commits",
    )
    lean_setup.add_argument(
        "--benchmark", required=True, type=Path, help="the Lean benchmark definition, in TOML"
    )
    lean_setup.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data"),
        help="where checkouts are kept, under lean/ (default: data)",
    )

    lean_check = commands.add_parser(
        "lean-check",
        help="check one saved reply's proof of one theorem of a Lean benchmark with Lean",
    )
    lean_check.add_argument(
        "--config", required=True, type=Path, help="the run configuration, with a [lean] section"
    )
    lean_check.add_argument(
        "--benchmark", required=True, type=Path, help="the Lean benchmark definition, in TOML"
    )
    lean_check.add_argument("--id", required=True, help="the theorem's name")
    lean_check.add_argument(
        "--reply", required=True, type=Path, help="a file holding the reply, with its code block"
    )
    lean_check.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data"),
        help="where checkouts are kept, under lean/ (default: data)",
    )

    publish = commands.add_parser(
        "publish", help="upload an audited run to Pi's artifacts bucket, manifest last"
    )
    publish.add_argument("run", type=Path, help="the run directory, audited")
    publish.add_argument("--profile", help="the AWS CLI profile (default: AWS_PROFILE)")

    report = commands.add_parser(
        "report", help="rebuild the report of a saved run, without the model"
    )
    report.add_argument("run", type=Path, help="the run directory")
    report.add_argument("--out", type=Path, help="write the report here instead of printing it")
    return parser
