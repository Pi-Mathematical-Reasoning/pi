"""The report of a run, rebuilt from its saved files with no model involved."""

import json
from collections import Counter
from pathlib import Path
from statistics import mean, median

from pi.evaluation import RUN, read_results

VERDICTS = ("correct", "incorrect", "missing", "cut_off", "timed_out")


def build_report(out: Path) -> str:
    """A Markdown report of the run saved in `out`."""
    out = Path(out)
    run = json.loads((out / RUN).read_text())
    results = read_results(out)
    benchmark = run["benchmark"]
    total = len(benchmark["ids"])
    correct = sum(result["verdict"] == "correct" for result in results)

    if run["complete"]:
        lines = [f"# {benchmark['name']}: {correct} of {total} correct ({correct / total:.1%})"]
    else:
        lines = [
            f"# {benchmark['name']}: incomplete, {len(results)} of {total} problems attempted",
            "",
            f"The run was interrupted. {correct} of the {len(results)} problems attempted so far "
            "are correct, which is not a score for the benchmark.",
        ]
    noun = "problem" if total == 1 else "problems"
    if benchmark["subset"]:
        lines += ["", f"A frozen subset of {total} {noun}.", ""]
    else:
        lines += ["", f"All {total} {noun} in the file.", ""]

    lines += _table(("", ""), _identity(run))
    lines += ["", "## Verdicts", "", "Only `correct` counts as solved.", ""]
    counts = [(v, sum(result["verdict"] == v for result in results)) for v in VERDICTS]
    lines += _table(("Verdict", "Problems"), counts)
    lines += ["", "## Cost", ""]
    lines += _table(("", ""), _cost(run, results))

    for heading, key in (("level", "level"), ("subject", "subject")):
        lines += ["", f"## By {heading}", ""]
        groups = sorted({result[key] for result in results}, key=str)
        rows = [
            (
                group,
                sum(r["verdict"] == "correct" for r in results if r[key] == group),
                sum(r[key] == group for r in results),
            )
            for group in groups
        ]
        lines += _table((heading.capitalize(), "Correct", "Problems"), rows)

    lines += ["", "## Unsolved", ""]
    unsolved = [result for result in results if result["verdict"] != "correct"]
    if unsolved:
        rows = [(r["id"], r["verdict"], _code(r["answer"])) for r in unsolved]
        lines += _table(("Problem", "Verdict", "Answer given"), rows)
    else:
        lines += ["None."]
    return "\n".join(lines) + "\n"


def _identity(run: dict) -> list[tuple]:
    model, settings, grader = run["model"], run["generation"], run["grader"]
    sessions = run["sessions"]

    revisions = []
    for session in sessions:
        code = session["code"]
        if code is None:
            shown = "not a git checkout"
        else:
            shown = f"`{code['revision'][:7]}`"
            if code["dirty"]:
                shown += " with uncommitted changes"
        if shown not in revisions:
            revisions.append(shown)

    return [
        (
            "Checkpoint",
            f"`{model['name']}`: {model['parameter_size']} parameters, "
            f"{model['quantization']}, digest `{model['digest'][:12]}`",
        ),
        ("Runtime", f"Ollama {run['runtime']['version']}"),
        (
            "Problems",
            f"`{run['benchmark']['name']}`, file checksum `{run['benchmark']['sha256'][:12]}`",
        ),
        ("Grader", f"rules {grader['rules']}, math-verify {grader['math_verify']}"),
        (
            "Settings",
            f"reasoning {'on' if settings['think'] else 'off'}, "
            f"temperature {settings['temperature']:g}, top-p {settings['top_p']:g}, "
            f"top-k {settings['top_k']}, seed {settings['seed']}, "
            f"{settings['context_length']}-token context, "
            f"{settings['max_output_tokens']}-token output limit, "
            f"{settings['time_limit_seconds']:g} s time limit",
        ),
        ("Code", ", ".join(revisions)),
        (
            "Sessions",
            "1" if len(sessions) == 1 else f"{len(sessions)}: the run was interrupted and resumed",
        ),
    ]


def _cost(run: dict, results: list[dict]) -> list[tuple]:
    seconds = [result["elapsed_seconds"] for result in results]
    tokens = [r["output_tokens"] for r in results if r["output_tokens"] is not None]
    speeds = [
        r["output_tokens_per_second"] for r in results if r["output_tokens_per_second"] is not None
    ]
    # A session stopped outright never recorded its memory or swap.
    sessions = run["sessions"]
    peaks = [s["peak_memory_bytes"] for s in sessions if s.get("peak_memory_bytes") is not None]
    swaps = [s["swap_growth_bytes"] for s in sessions if s.get("swap_growth_bytes") is not None]

    if not swaps:
        swap = "not measured"
    elif max(swaps) == 0:
        swap = "none"
    else:
        swap = f"{max(swaps) / 2**30:.2f} GiB"

    rows = [("Model time", f"{_duration(sum(seconds))} in total")]
    if seconds:
        rows.append(
            (
                "Time per problem",
                f"mean {mean(seconds):.1f} s, median {median(seconds):.1f} s, "
                f"longest {max(seconds):.1f} s",
            )
        )
    if tokens:
        rows.append(
            (
                "Output tokens per problem",
                f"mean {mean(tokens):.0f}, median {median(tokens):.0f}, most {max(tokens)}",
            )
        )
    if speeds:
        rows.append(("Speed", f"mean {mean(speeds):.1f} tokens per second"))
    rows.append(("Power", _power(results)))
    rows.append(("Peak memory", f"{max(peaks) / 2**30:.1f} GiB" if peaks else "not measured"))
    rows.append(("Swap growth", swap))
    return rows


def _power(results: list[dict]) -> str:
    """How many problems ran on each power source, in the order first seen."""
    counts = Counter()
    for result in results:
        power = result.get("power")  # absent from runs made before it was recorded
        counts[None if power is None else (power["source"], power.get("mode"))] += 1

    def problems(count: int) -> str:
        return f"{count} problem" if count == 1 else f"{count} problems"

    parts = [
        f"{source if mode is None else f'{source} ({mode})'} for {problems(count)}"
        for (source, mode), count in ((k, c) for k, c in counts.items() if k is not None)
    ]
    if not parts:
        return "not recorded"
    if counts[None]:
        parts.append(f"not recorded for {problems(counts[None])}")
    return ", ".join(parts)


def _duration(seconds: float) -> str:
    if seconds < 120:
        return f"{seconds:.1f} s"
    if seconds < 7200:
        return f"{seconds / 60:.1f} min"
    return f"{seconds / 3600:.1f} h"


def _code(text: str | None) -> str:
    """Text as inline code that cannot break out of a table cell."""
    return "none" if text is None else "`" + text.replace("|", r"\|") + "`"


def _table(header: tuple, rows: list[tuple]) -> list[str]:
    def line(cells):
        return "| " + " | ".join(str(cell) for cell in cells) + " |"

    empty = all(cell == "" for cell in header)
    head = "| | |" if empty else line(header)
    return [head, "| " + " | ".join("---" for _ in header) + " |", *(line(row) for row in rows)]
