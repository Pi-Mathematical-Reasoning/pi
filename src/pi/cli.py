"""The `pi` command."""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from pi.benchmarks import BenchmarkError, load_benchmark, load_problems
from pi.checkpoint import CheckpointError
from pi.config import ConfigError, load_config
from pi.evaluation import RUN, EvaluationError, run_evaluation
from pi.grading import grade, grader_version
from pi.ollama import OllamaClient, OllamaError
from pi.probe import run_probe, summarize
from pi.report import build_report
from pi.resources import ResourceSampler
from pi.revision import code_revision


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else list(argv)
    options = _parser().parse_args(arguments)
    if options.command == "probe":
        return _probe(options, arguments)
    if options.command == "grade":
        return _grade(options)
    if options.command == "eval":
        return _eval(options, arguments)
    return _report(options)


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

    report = commands.add_parser(
        "report", help="rebuild the report of a saved run, without the model"
    )
    report.add_argument("run", type=Path, help="the run directory")
    report.add_argument("--out", type=Path, help="write the report here instead of printing it")
    return parser
