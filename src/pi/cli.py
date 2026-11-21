"""The `pi` command."""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from pi.config import ConfigError, load_config
from pi.ollama import OllamaClient, OllamaError
from pi.probe import ProbeError, run_probe, summarize
from pi.resources import ResourceSampler
from pi.revision import code_revision


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else list(argv)
    options = _parser().parse_args(arguments)

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
    except (ConfigError, ProbeError, OllamaError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    out = options.out or Path("runs") / f"probe-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=2) + "\n")
    print(summarize(record))
    print(f"record written to {out}")
    return 0


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
    return parser
