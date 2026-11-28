"""Lean statements: a split file read into its theorems."""

from pathlib import Path

import pytest

from pi.lean_statements import StatementError, family, split_theorems

FIXTURE = Path(__file__).parent / "lean_fixture" / "Split.lean"

THEOREMS = split_theorems(FIXTURE.read_text(encoding="utf-8"))
BY_ID = {t.id: t for t in THEOREMS}


def test_finds_each_theorem_in_file_order_and_skips_commented_ones():
    assert [t.id for t in THEOREMS] == [
        "fixture_add_zero",
        "fixture_no_docstring",
        "amc12a_2099_p1",
        "mathd_algebra_9001",
        "fixture_poly.variants.Polynomial",
        "mathd_numbertheory_9002",
        "fixture_tight_above",
        "fixture_tight_below",
    ]


def test_the_header_runs_from_the_first_import_to_the_first_theorem():
    assert THEOREMS[0].header == "import Mathlib\n\nopen scoped Nat\nopen scoped Real\n"


def test_a_statement_stops_at_its_last_assignment():
    assert BY_ID["fixture_no_docstring"].statement == (
        "theorem fixture_no_docstring (a b : ℕ) (h : a ≤ b) :\n    a ≤ b + 1"
    )
    assert BY_ID["mathd_algebra_9001"].statement.endswith("    P a")


def test_an_open_in_line_belongs_to_the_statement_below_it():
    assert BY_ID["fixture_poly.variants.Polynomial"].statement.startswith(
        "open scoped Polynomial in\ntheorem fixture_poly.variants.Polynomial"
    )


def test_reads_the_docstring_even_past_a_line_comment():
    assert BY_ID["fixture_add_zero"].informal == "Add zero."
    assert BY_ID["amc12a_2099_p1"].informal.startswith("A comment sits")
    assert BY_ID["fixture_no_docstring"].informal is None


def test_a_docstring_may_touch_the_proof_above_it_and_span_a_blank_line():
    assert BY_ID["fixture_tight_above"].statement.endswith(": a = a")
    assert BY_ID["fixture_tight_below"].informal.endswith("a blank line itself.")


def test_only_a_theorem_the_file_proves_carries_a_shipped_proof():
    assert BY_ID["mathd_numbertheory_9002"].shipped_proof == "rfl"
    assert BY_ID["fixture_add_zero"].shipped_proof is None


@pytest.mark.parametrize(
    "name, expected",
    [
        ("mathd_algebra_478", "mathd_algebra"),
        ("mathd_numbertheory_66", "mathd_numbertheory"),
        ("amc12a_2019_p21", "amc12"),
        ("aimeII_2020_p6", "aime"),
        ("aime_1983_p1", "aime"),
        ("imo_1964_p1", "imo"),
        ("imoshortlist_2006_n5", "imo"),
        ("induction_sum_odd", "induction"),
        ("algebra_sqineq", "algebra"),
        ("numbertheory_4x3m7y3neq2003", "numbertheory"),
        ("fixture_add_zero", "other"),
    ],
)
def test_a_theorem_s_family_is_read_from_its_name(name, expected):
    assert family(name) == expected


@pytest.mark.parametrize(
    "bad, said",
    [
        ("import Mathlib\n\ndef helper := 1\n", "line 3"),
        ("import Mathlib\n\ntheorem t : True\n", "no proof"),
        (
            "import Mathlib\n\ntheorem t : True := by\n  sorry\n\n"
            "theorem t : True := by\n  sorry\n",
            "twice",
        ),
        ("theorem t : True := by\n  sorry\n", "import"),
    ],
)
def test_refuses_what_it_does_not_understand(bad, said):
    with pytest.raises(StatementError, match=said):
        split_theorems(bad)
