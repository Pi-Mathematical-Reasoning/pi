"""`check` against the real Lean and SafeVerify set up under `data/`: each captured case once.

Skipped unless PI_LEAN_TESTS=1. Needs `pi lean-setup --benchmark benchmarks/minif2f-test.toml`
first (the benchmark is used for its pins only; no theorem of it is checked). Each case imports
Mathlib three times and the judge peaks near 25 GB, so never run these in parallel.
"""

import os
from pathlib import Path

import pytest

from pi.benchmarks import load_benchmark
from pi.lean_grading import Limits, check
from pi.lean_project import LeanRunner
from pi.lean_statements import split_theorems

pytestmark = pytest.mark.skipif(
    os.environ.get("PI_LEAN_TESTS") != "1", reason="set PI_LEAN_TESTS=1 to run Lean"
)

REPO = Path(__file__).resolve().parents[1]
CASES = Path(__file__).parent / "lean_cases"
LIMITS = Limits(300, 300)

EXPECTED = {
    "valid": ("proved", None),
    "reformatted": ("proved", None),
    "skip_kernel": ("proved", None),
    "renamed_binders": ("proved", None),
    "sorry": ("failed", "sorry"),
    "helper_sorry": ("failed", "sorry"),
    "unused_sorry": ("failed", "sorry"),
    "helper_axiom": ("failed", "axioms"),
    "weakened": ("failed", "statement_changed"),
    # Not the original's name, so the rules take the block as a proof body, which Lean rejects.
    "renamed": ("failed", "lean_error"),
    "fake_success_exit": ("failed", "statement_changed"),
    "answer_wrapper": ("failed", "statement_changed"),
    "native_decide": ("failed", "kernel_rejected"),
    "replace_axiom": ("failed", "kernel_rejected"),
    "add_false_env": ("failed", "kernel_rejected"),
    "add_false": ("failed", "lean_error"),  # does not compile on Lean 4.27
}


@pytest.fixture(scope="module")
def benchmark():
    return load_benchmark(REPO / "benchmarks" / "minif2f-test.toml")


@pytest.fixture(scope="module")
def runner(benchmark):
    return LeanRunner(benchmark, REPO / "data")


def target(case):
    [theorem] = split_theorems((CASES / case / "Target.lean").read_text(encoding="utf-8"))
    return theorem


def fenced(code):
    return f"```lean4\n{code}\n```\n"


def grade(case, code, runner, benchmark, limits=LIMITS):
    return check(target(case), fenced(code), runner, limits, benchmark.allowed_axioms)


def outcome(result):
    return result.verdict, result.lean["reason"]


def test_every_case_has_an_expectation():
    assert sorted(EXPECTED) == sorted(path.name for path in CASES.iterdir() if path.is_dir())


@pytest.mark.parametrize("case, expected", EXPECTED.items())
def test_each_case_gets_its_verdict_and_reason(case, expected, runner, benchmark):
    code = (CASES / case / "Submission.lean").read_text(encoding="utf-8")
    assert outcome(grade(case, code, runner, benchmark)) == expected


def test_a_proof_only_reply_is_proved(runner, benchmark):
    assert outcome(grade("valid", "simpa using h", runner, benchmark)) == ("proved", None)


def test_a_reply_that_repeats_the_import_is_proved(runner, benchmark):
    statement = target("valid").statement
    code = "import Mathlib\nimport Mathlib\n\n" + statement + " := by\n  simpa using h"
    assert outcome(grade("valid", code, runner, benchmark)) == ("proved", None)


def test_a_proof_that_runs_past_the_limit_is_a_timeout(runner, benchmark):
    code = "sleep 120000\nsimpa using h"
    result = grade("valid", code, runner, benchmark, Limits(30, 30))
    assert outcome(result) == ("failed", "check_timed_out")
