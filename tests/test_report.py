"""The report: rebuilt from a run's saved files, with no model involved."""

import json
from pathlib import Path

from pi.report import build_report


def result(id, verdict, level, subject, elapsed, tokens, answer=None):
    return {
        "id": id,
        "subject": subject,
        "level": level,
        "verdict": verdict,
        "answer": answer,
        "response": None,
        "prompt_tokens": None if tokens is None else 30,
        "cached_prompt_tokens": None if tokens is None else 0,
        "output_tokens": tokens,
        "output_tokens_per_second": None if tokens is None else 20.0,
        "load_seconds": None if tokens is None else 1.5,
        "elapsed_seconds": elapsed,
    }


RESULTS = [
    result("dev/1", "correct", 1, "Algebra", 10.0, 100, answer="2"),
    result("dev/2", "incorrect", 1, "Geometry", 20.0, 200, answer="|x| + 4"),
    result("dev/3", "cut_off", 2, "Algebra", 30.0, 300),
    result("dev/4", "timed_out", 2, "Geometry", 60.0, None),
]

RUN = {
    "kind": "evaluation",
    "complete": True,
    "runtime": {"name": "ollama", "version": "0.40.13"},
    "model": {
        "name": "qwen3:14b",
        "digest": "bdbd181c33f2ed1b31c972991882db3cf4d192569092138a7d29e973cd9debe8",
        "parameter_size": "14.8B",
        "quantization": "Q4_K_M",
    },
    "generation": {
        "think": True,
        "context_length": 16384,
        "max_output_tokens": 8192,
        "temperature": 0.6,
        "top_p": 0.95,
        "top_k": 20,
        "seed": 1,
        "time_limit_seconds": 600.0,
    },
    "benchmark": {
        "name": "math-dev",
        "url": "https://example.com/train.parquet",
        "sha256": "5bb914caa970c120a9a139ccedef764da11e62965ac31f4dfff3ccf774199375",
        "subset": True,
        "ids": ["dev/1", "dev/2", "dev/3", "dev/4"],
    },
    "grader": {
        "rules": 1,
        "math_verify": "0.9.0",
        "latex2sympy2_extended": "1.11.0",
        "sympy": "1.14.0",
    },
    "sessions": [
        {
            "started_at": "2026-11-21T02:00:00+00:00",
            "ended_at": "2026-11-21T02:02:10+00:00",
            "command": ["pi", "eval"],
            "code": {"revision": "a21b7757798cc3a1bb9eb9cb6041e475a3cf6408", "dirty": False},
            "attempted": 4,
            "peak_memory_bytes": 10737418240,
            "swap_growth_bytes": 0,
            "runner_commands": ["llama-server -c 16384"],
        }
    ],
}

EXPECTED = r"""# math-dev: 1 of 4 correct (25.0%)

A frozen subset of 4 problems.

| | |
| --- | --- |
| Checkpoint | `qwen3:14b`: 14.8B parameters, Q4_K_M, digest `bdbd181c33f2` |
| Runtime | Ollama 0.40.13 |
| Problems | `math-dev`, file checksum `5bb914caa970` |
| Grader | rules 1, math-verify 0.9.0 |
| Settings | reasoning on, temperature 0.6, top-p 0.95, top-k 20, seed 1, 16384-token context, 8192-token output limit, 600 s time limit |
| Code | `a21b775` |
| Sessions | 1 |

## Verdicts

Only `correct` counts as solved.

| Verdict | Problems |
| --- | --- |
| correct | 1 |
| incorrect | 1 |
| missing | 0 |
| cut_off | 1 |
| timed_out | 1 |

## Cost

| | |
| --- | --- |
| Model time | 2.0 min in total |
| Time per problem | mean 30.0 s, median 25.0 s, longest 60.0 s |
| Output tokens per problem | mean 200, median 200, most 300 |
| Speed | mean 20.0 tokens per second |
| Power | not recorded |
| Peak memory | 10.0 GiB |
| Swap growth | none |

## By level

| Level | Correct | Problems |
| --- | --- | --- |
| 1 | 1 | 2 |
| 2 | 0 | 2 |

## By subject

| Subject | Correct | Problems |
| --- | --- | --- |
| Algebra | 1 | 2 |
| Geometry | 0 | 2 |

## Unsolved

| Problem | Verdict | Answer given |
| --- | --- | --- |
| dev/2 | incorrect | `\|x\| + 4` |
| dev/3 | cut_off | none |
| dev/4 | timed_out | none |
"""


def write_run(tmp_path, run=RUN, results=RESULTS):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "run.json").write_text(json.dumps(run))
    (tmp_path / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in results))
    return tmp_path


def test_reports_the_score_the_verdicts_and_the_cost_from_the_saved_files(tmp_path):
    assert build_report(write_run(tmp_path)) == EXPECTED


def test_an_interrupted_run_is_reported_as_incomplete_and_gives_no_score(tmp_path):
    run = {**RUN, "complete": False}

    report = build_report(write_run(tmp_path, run=run, results=RESULTS[:2]))

    assert report.startswith("# math-dev: incomplete, 2 of 4 problems attempted\n")
    assert "not a score" in report
    assert "%" not in report.split("\n")[0]


def test_a_run_of_the_whole_file_is_not_called_a_subset(tmp_path):
    whole = {**RUN, "benchmark": {**RUN["benchmark"], "subset": False}}

    assert "\nAll 4 problems in the file.\n" in build_report(write_run(tmp_path, run=whole))


def test_a_resumed_run_names_every_code_revision_and_says_it_was_resumed(tmp_path):
    second = {
        **RUN["sessions"][0],
        "code": {"revision": "f4353dcef1647593ef8a7c65dfb16d0ed9b48c98", "dirty": True},
        "peak_memory_bytes": 21474836480,
        "swap_growth_bytes": 536870912,
    }
    resumed = {**RUN, "sessions": [RUN["sessions"][0], second]}

    report = build_report(write_run(tmp_path, run=resumed))

    assert "| Code | `a21b775`, `f4353dc` with uncommitted changes |" in report
    assert "| Sessions | 2: the run was interrupted and resumed |" in report
    # The peak is the highest of the sessions, and swap growth the largest.
    assert "| Peak memory | 20.0 GiB |" in report
    assert "| Swap growth | 0.50 GiB |" in report


def test_memory_that_was_not_measured_is_reported_as_such(tmp_path):
    unmeasured = {**RUN["sessions"][0], "peak_memory_bytes": None, "swap_growth_bytes": None}

    report = build_report(write_run(tmp_path, run={**RUN, "sessions": [unmeasured]}))

    assert "| Peak memory | not measured |" in report
    assert "| Swap growth | not measured |" in report


def test_a_run_with_nothing_unsolved_says_so(tmp_path):
    report = build_report(write_run(tmp_path, results=[RESULTS[0]] * 4))

    assert report.endswith("## Unsolved\n\nNone.\n")


def test_a_run_of_one_problem_is_worded_in_the_singular(tmp_path):
    one = {**RUN, "benchmark": {**RUN["benchmark"], "ids": ["dev/1"]}}

    report = build_report(write_run(tmp_path, run=one, results=RESULTS[:1]))

    assert "\nA frozen subset of 1 problem.\n" in report


def test_says_how_many_problems_ran_on_battery_and_how_many_on_mains(tmp_path):
    battery = {"source": "Battery Power", "mode": "powermode 1"}
    mains = {"source": "AC Power", "mode": "powermode 2"}
    powered = [
        {**RESULTS[0], "power": battery},
        {**RESULTS[1], "power": mains},
        {**RESULTS[2], "power": mains},
        RESULTS[3],
    ]

    report = build_report(write_run(tmp_path, results=powered))

    assert (
        "| Power | Battery Power (powermode 1) for 1 problem, "
        "AC Power (powermode 2) for 2 problems, not recorded for 1 problem |"
    ) in report


def test_names_the_power_source_alone_when_the_machine_reports_no_energy_mode(tmp_path):
    mains = {"source": "AC Power", "mode": None}

    report = build_report(write_run(tmp_path, results=[{**r, "power": mains} for r in RESULTS]))

    assert "| Power | AC Power for 4 problems |" in report


def test_every_committed_report_is_what_its_saved_files_rebuild():
    # The brief's done condition: saved predictions regenerate the report with no model.
    experiments = Path(__file__).parent.parent / "experiments"
    runs = sorted(path.parent for path in experiments.glob("*/run.json"))

    assert runs, "no committed run to check"
    for run in runs:
        assert build_report(run) == (run / "report.md").read_text(), run.name
