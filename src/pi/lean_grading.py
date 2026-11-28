"""Lean rules version 1: turn a reply into a Lean file and the judge's output into a verdict.

A proof passes only on positive confirmation from the judge (SafeVerify): exit status 0 and a
saved outcome that says so. Anything unexpected, missing or unparsable is a failure with a
reason. Nothing here runs Lean.
"""

import re
import textwrap
from collections.abc import Sequence

from pi.lean_project import Finished
from pi.lean_statements import Theorem

LEAN_RULES_VERSION = 1
MESSAGE_CAP = 20_000

_TAGS = {"", "lean", "lean4"}
_FLAGGED = [
    "#eval",
    "run_cmd",
    "elab",
    "elab_rules",
    "macro",
    "macro_rules",
    "syntax",
    "declare_syntax_cat",
    "initialize",
    "IO.",
]
_SORRY = "sorryAx"


def extract_code(reply: str) -> str | None:
    """The content of the last closed lean (or untagged) block that has code in it."""
    found: str | None = None
    tag: str | None = None
    lines: list[str] = []
    for line in reply.splitlines():
        stripped = line.strip()
        if not stripped.startswith("```"):
            lines.append(line)
        elif tag is None:
            tag, lines = stripped[3:].strip().lower(), []
        else:
            content = "\n".join(lines).strip("\n")
            if tag in _TAGS and content.strip():
                found = content
            tag = None
    return found


def _declares(theorem: Theorem, code: str) -> bool:
    pattern = rf"^(theorem|lemma)\s+{re.escape(theorem.id)}(?![\w.'!?])"
    return re.search(pattern, code, re.MULTILINE) is not None


def _trim_blank_lines(lines: list[str]) -> list[str]:
    start, end = 0, len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return lines[start:end]


def _drop_imports(lines: list[str]) -> list[str]:
    start = 0
    while start < len(lines) and (
        not lines[start].strip() or lines[start].strip().startswith("import ")
    ):
        start += 1
    return lines[start:]


def _dedent(lines: list[str]) -> list[str]:
    return textwrap.dedent("\n".join(lines)).split("\n") if lines else []


def _proof_body(lines: list[str]) -> list[str]:
    """The tactic lines of a proof-only block, without its `:=` and `by`."""
    first = lines[0].lstrip()
    if first.startswith(":="):
        first = first[2:].lstrip()
    if re.match(r"by\b", first):
        first = first[2:].lstrip()
    rest = _dedent(([first] if first else []) + lines[1:])
    return [("  " + line) if line.strip() else line for line in rest]


def assemble(theorem: Theorem, code: str) -> str:
    """The submission file: the header, then the block (or its proof under the statement)."""
    lines = _dedent(_drop_imports(_trim_blank_lines(code.splitlines())))
    remainder = "\n".join(lines)
    if _declares(theorem, remainder):
        return theorem.header + "\n" + remainder + "\n"
    body = _proof_body(lines) if lines else []
    tail = "".join(line + "\n" for line in body)
    return theorem.header + "\n" + theorem.statement + " := by\n" + tail


def reference_source(theorem: Theorem) -> str:
    return theorem.header + "\n" + theorem.statement + " := by\n  sorry\n"


def flags(code: str) -> list[str]:
    """Compile-time commands the code uses, as whole tokens."""
    found = []
    for token in _FLAGGED:
        before = r"(?<![\w.])" if token == "IO." else r"(?<![\w.'])"
        after = "" if token == "IO." else r"(?![\w'])"
        if re.search(before + re.escape(token) + after, code):
            found.append(token)
    return found


def _pairs(saved: object) -> list[tuple[str, dict]] | None:
    """The `[name, outcome]` pairs of the saved JSON, or None if it has any other shape."""
    if not isinstance(saved, list) or not saved:
        return None
    pairs = []
    for pair in saved:
        if not (isinstance(pair, list) and len(pair) == 2):
            return None
        name, result = pair
        if not (isinstance(name, str) and isinstance(result, dict) and "failureMode" in result):
            return None
        pairs.append((name, result))
    return pairs


def _axioms(result: dict) -> list[str] | None:
    info = result.get("solutionInfo")
    axioms = info.get("axioms") if isinstance(info, dict) else None
    if isinstance(axioms, list) and all(isinstance(axiom, str) for axiom in axioms):
        return axioms
    return None


def _disallowed_lines(stderr: str) -> list[str]:
    return [line for line in stderr.splitlines() if "used disallowed axioms" in line]


def judgement(
    done: Finished, saved: list | None, allowed: Sequence[str], name: str
) -> tuple[str | None, list[str]]:
    """(None when the proof passes, else the reason; the submission theorem's axioms)."""
    pairs = _pairs(saved) or []
    own = next((result for pair_name, result in pairs if pair_name == name), None)
    axioms = (own and _axioms(own)) or []
    modes = [result.get("failureMode") for _, result in pairs]

    if done.exit_code is None:
        return "check_timed_out", axioms
    if "uncaught exception: (kernel)" in done.stderr or "kernel verification failed" in done.stderr:
        return "kernel_rejected", axioms
    if any(mode in ("thmType", "notFound") or isinstance(mode, dict) for mode in modes):
        return "statement_changed", axioms
    lines = _disallowed_lines(done.stderr)
    if "axioms" in modes or lines:
        named = [
            a
            for _, result in pairs
            if result.get("failureMode") == "axioms"
            for a in _axioms(result) or []
        ]
        sorry = _SORRY in named or any(_SORRY in line for line in lines)
        return ("sorry" if sorry else "axioms"), axioms
    if done.exit_code == 0 and own is not None and all(mode is None for mode in modes):
        every = [_axioms(result) for _, result in pairs]
        if all(item is not None for item in every):
            if any(axiom not in allowed for item in every for axiom in item or []):
                return "axioms", axioms
            return None, axioms
    return "judge_error", axioms
