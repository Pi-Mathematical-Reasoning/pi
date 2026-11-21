"""Benchmarks: a pinned problem file, fetched once, checked, and read."""

import hashlib
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from pi.benchmarks import Benchmark, BenchmarkError, Problem, load_benchmark, load_problems

ROWS = [
    {
        "unique_id": "train/algebra/1.json",
        "problem": "What is $1+1$?",
        "solution": "It is $\\boxed{2}$.",
        "answer": "2",
        "subject": "Algebra",
        "level": 1,
    },
    {
        "unique_id": "train/geometry/7.json",
        "problem": "How many sides has a triangle?",
        "solution": "It has $\\boxed{3}$.",
        "answer": "3",
        "subject": "Geometry",
        "level": 2,
    },
    {
        "unique_id": "train/algebra/9.json",
        "problem": "Solve $2x=1$.",
        "solution": "So $x=\\boxed{\\frac{1}{2}}$.",
        "answer": "\\frac{1}{2}",
        "subject": "Algebra",
        "level": 3,
    },
]


def jsonl_source(tmp_path, rows=ROWS):
    """A problem file on disk, with the URL and checksum that pin it."""
    path = tmp_path / "source" / "problems.jsonl"
    path.parent.mkdir(exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path.as_uri(), hashlib.sha256(path.read_bytes()).hexdigest()


def benchmark_for(tmp_path, rows=ROWS, **changes):
    url, sha256 = jsonl_source(tmp_path, rows)
    settings = {"name": "sample", "url": url, "sha256": sha256, "format": "jsonl", "ids": None}
    return Benchmark(**{**settings, **changes})


def test_reads_every_problem_in_the_order_of_the_file(tmp_path):
    problems = load_problems(benchmark_for(tmp_path), tmp_path / "data")

    assert problems == [
        Problem("train/algebra/1.json", "What is $1+1$?", "2", "Algebra", 1),
        Problem("train/geometry/7.json", "How many sides has a triangle?", "3", "Geometry", 2),
        Problem("train/algebra/9.json", "Solve $2x=1$.", "\\frac{1}{2}", "Algebra", 3),
    ]


def test_a_frozen_list_of_ids_selects_a_subset_in_the_listed_order(tmp_path):
    subset = benchmark_for(tmp_path, ids=("train/algebra/9.json", "train/algebra/1.json"))

    problems = load_problems(subset, tmp_path / "data")

    assert [problem.id for problem in problems] == ["train/algebra/9.json", "train/algebra/1.json"]


def test_refuses_a_file_that_does_not_match_the_pinned_checksum(tmp_path):
    tampered = benchmark_for(tmp_path, sha256="0" * 64)

    with pytest.raises(BenchmarkError, match="checksum"):
        load_problems(tampered, tmp_path / "data")

    assert list((tmp_path / "data").glob("*")) == []


def test_fetches_the_file_once_and_reads_it_from_the_data_directory_afterwards(tmp_path):
    benchmark = benchmark_for(tmp_path)
    load_problems(benchmark, tmp_path / "data")
    (tmp_path / "source" / "problems.jsonl").unlink()

    assert len(load_problems(benchmark, tmp_path / "data")) == 3


def test_refetches_a_stored_file_that_no_longer_matches_the_checksum(tmp_path):
    benchmark = benchmark_for(tmp_path)
    load_problems(benchmark, tmp_path / "data")
    (stored,) = (tmp_path / "data").glob("*")
    stored.write_text("corrupted")

    assert len(load_problems(benchmark, tmp_path / "data")) == 3


def test_names_an_id_that_is_not_in_the_file(tmp_path):
    subset = benchmark_for(tmp_path, ids=("train/algebra/1.json", "train/algebra/404.json"))

    with pytest.raises(BenchmarkError, match="train/algebra/404.json"):
        load_problems(subset, tmp_path / "data")


def test_refuses_an_id_that_names_more_than_one_problem(tmp_path):
    # The source of the development problems has one such id.
    twice = [*ROWS, {**ROWS[0], "problem": "A different problem under the same id."}]
    subset = benchmark_for(tmp_path, rows=twice, ids=("train/algebra/1.json",))

    with pytest.raises(BenchmarkError, match="more than one"):
        load_problems(subset, tmp_path / "data")


def test_refuses_a_problem_with_no_reference_answer(tmp_path):
    unanswered = [ROWS[0], {**ROWS[1], "answer": " "}]

    with pytest.raises(BenchmarkError, match="train/geometry/7.json"):
        load_problems(benchmark_for(tmp_path, rows=unanswered), tmp_path / "data")


def test_reads_a_parquet_file(tmp_path):
    path = tmp_path / "problems.parquet"
    pq.write_table(pa.Table.from_pylist(ROWS), path)
    benchmark = Benchmark(
        name="sample",
        url=path.as_uri(),
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        format="parquet",
        ids=("train/geometry/7.json",),
    )

    assert load_problems(benchmark, tmp_path / "data") == [
        Problem("train/geometry/7.json", "How many sides has a triangle?", "3", "Geometry", 2)
    ]


def test_explains_a_source_it_cannot_reach(tmp_path):
    unreachable = benchmark_for(tmp_path, url=(tmp_path / "absent.jsonl").as_uri())

    with pytest.raises(BenchmarkError, match="absent.jsonl"):
        load_problems(unreachable, tmp_path / "data")


DEFINITION = """
name = "math-dev"
url = "https://example.com/train.parquet"
sha256 = "abc123"
format = "parquet"
ids = ["train/algebra/1.json", "train/geometry/7.json"]
"""


def write(tmp_path, text):
    path = tmp_path / "benchmark.toml"
    path.write_text(text)
    return path


def test_loads_a_benchmark_definition(tmp_path):
    assert load_benchmark(write(tmp_path, DEFINITION)) == Benchmark(
        name="math-dev",
        url="https://example.com/train.parquet",
        sha256="abc123",
        format="parquet",
        ids=("train/algebra/1.json", "train/geometry/7.json"),
    )


def test_a_definition_without_ids_means_every_problem(tmp_path):
    whole = DEFINITION.replace('ids = ["train/algebra/1.json", "train/geometry/7.json"]\n', "")

    assert load_benchmark(write(tmp_path, whole)).ids is None


def test_refuses_a_definition_without_a_checksum(tmp_path):
    unpinned = DEFINITION.replace('sha256 = "abc123"\n', "")

    with pytest.raises(BenchmarkError, match="sha256"):
        load_benchmark(write(tmp_path, unpinned))


def test_refuses_a_format_it_cannot_read(tmp_path):
    with pytest.raises(BenchmarkError, match="csv"):
        load_benchmark(write(tmp_path, DEFINITION.replace('"parquet"', '"csv"')))


def test_refuses_a_setting_it_does_not_know(tmp_path):
    with pytest.raises(BenchmarkError, match="split"):
        load_benchmark(write(tmp_path, DEFINITION + 'split = "train"\n'))


def test_reports_a_missing_definition(tmp_path):
    with pytest.raises(BenchmarkError, match="absent.toml"):
        load_benchmark(tmp_path / "absent.toml")
