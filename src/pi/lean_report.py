"""The report of a run on a Lean benchmark."""

from statistics import mean, median

from pi.report import _code, _cost, _identity, _table

VERDICTS = ("proved", "failed", "missing", "cut_off", "timed_out")
REASONS = (
    "lean_error",
    "sorry",
    "statement_changed",
    "axioms",
    "kernel_rejected",
    "check_timed_out",
    "judge_error",
)
NEAR_LIMIT = 0.8


def build_lean_report(run: dict, results: list[dict]) -> str:
    """A Markdown report of a Lean run, from its saved files alone."""
    benchmark = run["benchmark"]
    total = len(benchmark["ids"])
    proved = sum(result["verdict"] == "proved" for result in results)
    if run["complete"]:
        lines = [f"# {benchmark['name']}: {proved} of {total} proved ({proved / total:.1%})"]
    else:
        attempted = len(results)
        lines = [
            f"# {benchmark['name']}: incomplete, {attempted} of {total} theorems attempted",
            "",
            f"The run was interrupted. {proved} of the {attempted} theorems attempted so far "
            "are proved, which is not a score for the benchmark.",
        ]
    noun = "theorem" if total == 1 else "theorems"
    if benchmark["subset"]:
        lines += ["", f"A frozen subset of {total} {noun}.", ""]
    else:
        lines += ["", f"All {total} {noun} in the file.", ""]

    lines += _table(("", ""), _lean_identity(run))
    lines += _verdicts(results)
    lines += _failure_reasons(results)
    lines += _lean_cost(run, results)
    lines += _families(results)
    lines += _flagged(results)
    lines += _unsolved(results)
    return "\n".join(lines) + "\n"


def _text(value) -> str:
    """Text that cannot break out of a table cell."""
    return str(value).replace("|", r"\|").replace("\n", " ")


def _codes(items) -> str:
    return ", ".join(_code(item) for item in items)


def _lean_identity(run: dict) -> list[tuple]:
    # The rows the two kinds of run share come from the answer report's own builder,
    # which also reads an answer grader's fields; the Lean grader row replaces it.
    rows = dict(_identity({**run, "grader": {"rules": "", "math_verify": ""}}))
    benchmark, grader, lean = run["benchmark"], run["grader"], run["lean"]
    compile_limit = lean["compile_time_limit_seconds"]
    judge_limit = lean["judge_time_limit_seconds"]
    if compile_limit == judge_limit:
        limits = f"{compile_limit:g} s per check step"
    else:
        limits = f"{compile_limit:g} s compile limit, {judge_limit:g} s judge limit"
    options = _codes(lean["options"]) if lean["options"] else "no options"
    repository = benchmark["repository"].rstrip("/").rsplit("/", 1)[-1]
    return [
        ("Checkpoint", rows["Checkpoint"]),
        ("Runtime", rows["Runtime"]),
        (
            "Problems",
            f"`{benchmark['name']}`, `{repository}` at `{benchmark['commit'][:12]}`, "
            f"file checksum `{benchmark['sha256'][:12]}`",
        ),
        ("Lean", f"{_code(lean['toolchain'])}, {options}"),
        (
            "Grader",
            f"Lean rules {grader['lean_rules']}, SafeVerify `{grader['judge_commit'][:12]}`, "
            f"axioms {_codes(grader['allowed_axioms'])}",
        ),
        ("Settings", f"{rows['Settings']}, {limits}"),
        ("Code", rows["Code"]),
        ("Sessions", rows["Sessions"]),
    ]


def _verdicts(results: list[dict]) -> list[str]:
    counts = [(v, sum(result["verdict"] == v for result in results)) for v in VERDICTS]
    return [
        "",
        "## Verdicts",
        "",
        "Only `proved` counts as solved.",
        "",
        *_table(("Verdict", "Theorems"), counts),
    ]


def _reason(result: dict) -> str | None:
    lean = result.get("lean")
    return lean["reason"] if result["verdict"] == "failed" and lean else None


def _failure_reasons(results: list[dict]) -> list[str]:
    reasons = [_reason(result) for result in results]
    rows = [(reason, reasons.count(reason)) for reason in REASONS if reason in reasons]
    # A reason this report does not know is still shown, after the known ones.
    rows += [(r, reasons.count(r)) for r in sorted({r for r in reasons if r} - set(REASONS))]
    body = _table(("Reason", "Theorems"), [(_text(r), n) for r, n in rows]) if rows else ["None."]
    return ["", "## Failure reasons", "", *body]


def _spread(label: str, seconds: list[float]) -> list[tuple]:
    if not seconds:
        return []
    shown = (
        f"mean {mean(seconds):.1f} s, median {median(seconds):.1f} s, longest {max(seconds):.1f} s"
    )
    return [(label, shown)]


def _lean_cost(run: dict, results: list[dict]) -> list[str]:
    records = [r["lean"] for r in results if r.get("lean")]
    compiles = [x["compile_seconds"] for x in records if x.get("compile_seconds") is not None]
    judges = [x["judge_seconds"] for x in records if x.get("judge_seconds") is not None]
    compile_limit = run["lean"]["compile_time_limit_seconds"]
    judge_limit = run["lean"]["judge_time_limit_seconds"]
    # Only checks that finished: one killed at a limit is counted by its reason instead.
    near = sum(
        (x.get("compile_seconds") or 0) >= NEAR_LIMIT * compile_limit
        or (x.get("judge_seconds") or 0) >= NEAR_LIMIT * judge_limit
        for x in records
        if x.get("reason") != "check_timed_out"
    )
    # The answer report's rows; its peak memory is the model's alone, not Lean's or the judge's.
    shared = [
        ("Peak memory (model)", value) if label == "Peak memory" else (label, value)
        for label, value in _cost(run, results)
    ]
    rows = [
        *shared,
        *_spread("Compile time per check", compiles),
        *_spread("Judge time per check", judges),
        ("Checks within 20% of a limit", near),
    ]
    return ["", "## Cost", "", *_table(("", ""), rows)]


def _families(results: list[dict]) -> list[str]:
    groups = sorted({result.get("subject") for result in results}, key=str)
    rows = [
        (
            _text(group),
            sum(r["verdict"] == "proved" for r in results if r.get("subject") == group),
            sum(r.get("subject") == group for r in results),
        )
        for group in groups
    ]
    return ["", "## By family", "", *_table(("Family", "Proved", "Theorems"), rows)]


def _flagged(results: list[dict]) -> list[str]:
    flagged = [
        r for r in results if r["verdict"] == "proved" and (r.get("lean") or {}).get("flags")
    ]
    lines = [
        "",
        "## Flagged proofs",
        "",
        "These accepted proofs run code while Lean compiles them and should be read by a person.",
        "",
    ]
    if not flagged:
        return lines + ["None."]
    rows = [(_text(r["id"]), _codes(r["lean"]["flags"])) for r in flagged]
    return lines + _table(("Theorem", "Commands"), rows)


def _unsolved(results: list[dict]) -> list[str]:
    unsolved = [result for result in results if result["verdict"] != "proved"]
    lines = ["", "## Unsolved", ""]
    if not unsolved:
        return lines + ["None."]
    rows = [(_text(r["id"]), r["verdict"], _text(_reason(r) or "")) for r in unsolved]
    return lines + _table(("Theorem", "Verdict", "Reason"), rows)
