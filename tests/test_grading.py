"""The answer grader: find the final answer in a reply and compare it with the reference."""

import json
from pathlib import Path

import pytest

from pi.grading import Grade, grade, grader_version

# Eight replies the checkpoint gave to original problems of different answer
# types, each of which it solved. See the experiment log.
REAL_REPLIES = json.loads(
    (Path(__file__).parent / "replies" / "answer-format-sample.json").read_text()
)


def boxed(answer):
    return rf"Working it through, the result is $\boxed{{{answer}}}$."


# (reference answer, the model's final answer)
EQUIVALENT = [
    (r"\frac{1}{2}", "0.5"),
    (r"\frac{1}{2}", "1/2"),
    (r"\frac{1}{2}", r"\dfrac12"),
    (r"\frac{1}{2}", r"\frac{2}{4}"),
    ("0.5", r"\frac{1}{2}"),
    ("12", "12.0"),
    ("12", "x = 12"),
    ("1000", "1,000"),
    (r"\frac{3}{2}", r"1\frac{1}{2}"),
    (r"2\sqrt{3}", r"\sqrt{12}"),
    (r"\frac{\sqrt{3}}{3}", r"\frac{1}{\sqrt{3}}"),
    ("x^2+2x+1", "(x+1)^2"),
    ("p - q", "-q + p"),
    (r"\left( 3, \frac{\pi}{2} \right)", r"(3, \pi/2)"),
    ("[2,5)", "[2, 5)"),
    (r"(-\infty, 3]", r"(-\infty,3]"),
    ("1,2,3", "3, 2, 1"),
    (r"\text{Evelyn}", r"\text{Evelyn}"),
    (r"\text{Evelyn}", "Evelyn"),
    (r"90^\circ", "90"),
    (r"\$18.90", "18.9"),
    (r"10\text{ cm}", "10"),
    (r"\begin{pmatrix} 1 \\ 2 \end{pmatrix}", r"\begin{pmatrix} 1 \\ 2 \end{pmatrix}"),
    (r"(-\infty, -14)\cup(-3,\infty)", r"(-3,\infty) \cup (-\infty,-14)"),
    (r"3 \pm 2 \sqrt{2}", r"3 + 2\sqrt{2}, 3 - 2\sqrt{2}"),
    (r"1,-2", r"x = 1 \text{ or } x = -2"),
    (r"-2 + 7i", "7i - 2"),
    (r"\$32,\!348", "32348"),
    (r"\text{east}", r"\text{East}"),
    # Decimals are compared to six places.
    (r"\frac{1}{3}", "0.333333"),
    (r"\sqrt{2}", "1.41421356"),
    # A percentage matches either reading, and a base subscript is ignored.
    (r"10\%", r"10\%"),
    (r"10\%", "10"),
    (r"10\%", "0.1"),
    (r"4210_{5}", "4210"),
]

DIFFERENT = [
    ("12", "13"),
    ("12", "-12"),
    (r"\frac{1}{2}", r"\frac{1}{3}"),
    ("3.14", "3.1416"),
    ("x^2+2x+1", "x^2+2x-1"),
    (r"(3,\frac{\pi}{2})", r"(\frac{\pi}{2}, 3)"),
    ("[2,5)", "[2,5]"),
    ("1,2", "1,2,3"),
    (r"\text{Evelyn}", r"\text{Briana}"),
    (r"90^\circ", "45"),
    (r"\begin{pmatrix} 1 \\ 2 \end{pmatrix}", r"\begin{pmatrix} 1 \\ 3 \end{pmatrix}"),
    ("6", "six"),
    (r"(-\infty, -14)\cup(-3,\infty)", r"(-\infty,-14] \cup (-3,\infty)"),
    (r"-2 + 7i", "-2 - 7i"),
    (r"\frac{1}{3}", "0.33333"),
    (r"\frac{2}{3}", "0.67"),
    (r"10\%", r"11\%"),
]


@pytest.mark.parametrize(("reference", "answer"), EQUIVALENT)
def test_an_equivalent_form_of_the_reference_is_correct(reference, answer):
    assert grade(boxed(answer), reference).verdict == "correct"


@pytest.mark.parametrize(("reference", "answer"), DIFFERENT)
def test_a_different_answer_is_incorrect(reference, answer):
    assert grade(boxed(answer), reference).verdict == "incorrect"


@pytest.mark.parametrize(
    "reply",
    [
        "",
        "I am not able to determine the value from the information given.",
        r"The answer is $\boxed{}$.",
    ],
)
def test_a_reply_without_a_final_answer_is_missing(reply):
    assert grade(reply, "12") == Grade(verdict="missing", answer=None)


@pytest.mark.parametrize(
    "reply",
    [
        "So we get 12.",
        "**Answer:** 12",
        r"Thus, $x = 12$.",
        r"We have $3 \cdot 4 = 12$ and then $12 + 0 = 12$.",
    ],
)
def test_an_answer_that_is_neither_boxed_nor_announced_is_missing(reply):
    # Taking the last number in a reply for its answer would credit replies
    # that never committed to one.
    assert grade(reply, "12").verdict == "missing"


@pytest.mark.parametrize("item", REAL_REPLIES, ids=lambda item: item["kind"])
def test_a_real_reply_from_the_checkpoint_is_graded_correct(item):
    assert grade(item["content"], item["reference"]).verdict == "correct"


def test_a_real_reply_is_incorrect_against_a_different_reference():
    replies = {item["kind"]: item for item in REAL_REPLIES}

    assert grade(replies["fraction"]["content"], r"\frac{3}{14}").verdict == "incorrect"
    assert grade(replies["interval"]["content"], "(2,3)").verdict == "incorrect"


def test_reports_the_final_answer_it_graded():
    assert grade(boxed(r"\frac{3}{28}"), r"\frac{3}{28}") == Grade(
        verdict="correct", answer=r"\frac{3}{28}"
    )


def test_the_last_boxed_expression_is_the_final_answer():
    reply = r"First, $x^2 = \boxed{4}$. Then the sum is $$\boxed{12}$$"

    assert grade(reply, "12").verdict == "correct"
    assert grade(reply, "4").verdict == "incorrect"


def test_numbers_after_the_boxed_answer_are_not_the_answer():
    reply = r"The answer is $\boxed{12}$. This took 3 steps and 7 cases."

    assert grade(reply, "12").verdict == "correct"
    assert grade(reply, "7").verdict == "incorrect"


def test_solutions_boxed_side_by_side_are_read_as_one_answer():
    reply = r"The solutions are $\boxed{2}$ and $\boxed{4}$."

    assert grade(reply, "2,4").verdict == "correct"
    assert grade(reply, "4").verdict == "incorrect"


def test_a_malformed_box_is_incorrect():
    assert grade(r"The answer is $\boxed{12$", "12").verdict == "incorrect"


def test_an_expression_announced_as_the_final_answer_is_read_without_a_box():
    reply = r"After simplifying, the final answer is $\frac{1}{2}$."

    assert grade(reply, "0.5").verdict == "correct"


def test_a_reference_that_cannot_be_read_is_an_error_not_a_verdict():
    # A broken reference is a fault in the benchmark data, not a wrong answer.
    with pytest.raises(ValueError, match="reference"):
        grade(boxed("12"), "")


def test_names_the_rules_and_the_library_versions_it_graded_with():
    version = grader_version()

    assert version["rules"] >= 1
    assert set(version) == {"rules", "math_verify", "latex2sympy2_extended", "sympy"}
    libraries = [version[name] for name in version if name != "rules"]
    assert all(isinstance(installed, str) and installed for installed in libraries)
