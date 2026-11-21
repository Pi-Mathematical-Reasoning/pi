"""The answer grader: find a reply's final answer and compare it with the reference.

Both steps are done by math-verify, whose version is pinned in pyproject.toml.
RULES_VERSION changes whenever the way it is called here changes, so a saved
verdict can name the rules that produced it.

math-verify limits its work with signal-based timeouts, so grading must run on
the main thread.
"""

from dataclasses import dataclass
from importlib.metadata import version

from math_verify import LatexExtractionConfig, parse, verify

RULES_VERSION = 1

_REFERENCE = [LatexExtractionConfig()]

# The final answer is the last boxed expression or, failing that, one the reply
# announces as its final answer. Any other number in the text is never taken
# for the answer.
_REPLY = [LatexExtractionConfig(boxed_match_priority=0, try_extract_without_anchor=False)]


@dataclass(frozen=True)
class Grade:
    verdict: str  # "correct", "incorrect" or "missing"
    answer: str | None  # the final answer that was graded, as math-verify read it


def grade(reply: str, reference: str) -> Grade:
    """Grade the visible text of a reply against a reference answer in LaTeX."""
    gold = parse(f"${reference}$", extraction_config=_REFERENCE)
    if not gold:
        raise ValueError(f"cannot read the reference answer {reference!r}")

    found = parse(reply, extraction_config=_REPLY)
    if not found:
        return Grade(verdict="missing", answer=None)

    answer = found[-1] if isinstance(found[-1], str) else str(found[-1])
    return Grade(verdict="correct" if verify(gold, found) else "incorrect", answer=answer)


def grader_version() -> dict:
    """What a verdict was produced with: these rules and the libraries under them."""
    return {
        "rules": RULES_VERSION,
        "math_verify": version("math-verify"),
        "latex2sympy2_extended": version("latex2sympy2_extended"),
        "sympy": version("sympy"),
    }
