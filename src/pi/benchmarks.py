"""Benchmarks: a pinned problem file, fetched once, checked, and read.

A benchmark definition is a TOML file naming a URL and the SHA-256 of what it
must return. Problem files are never committed: they are fetched into a data
directory and checked against the pin every time they are read.
"""

import hashlib
import json
import tomllib
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pyarrow.parquet

FORMATS = ("jsonl", "parquet")


class BenchmarkError(Exception):
    """A benchmark definition or its problem file cannot be used."""


@dataclass(frozen=True)
class Problem:
    id: str
    problem: str
    answer: str
    subject: str | None
    level: int | None


@dataclass(frozen=True)
class Benchmark:
    name: str
    url: str
    sha256: str
    format: str
    ids: tuple[str, ...] | None  # a frozen subset, or None for every problem in the file


def load_benchmark(path: Path) -> Benchmark:
    path = Path(path)
    try:
        data = tomllib.loads(path.read_text())
    except FileNotFoundError:
        raise BenchmarkError(f"no benchmark definition at {path}") from None
    except tomllib.TOMLDecodeError as error:
        raise BenchmarkError(f"{path} is not valid TOML: {error}") from None

    required = ("name", "url", "sha256", "format")
    unknown = sorted(set(data) - {*required, "ids"})
    if unknown:
        raise BenchmarkError(f"{path}: unknown setting {unknown[0]}")
    for key in required:
        if not isinstance(data.get(key), str) or not data[key]:
            raise BenchmarkError(f"{path}: {key} must be a non-empty string")
    if data["format"] not in FORMATS:
        raise BenchmarkError(f"{path}: cannot read format {data['format']!r}; use jsonl or parquet")

    ids = data.get("ids")
    if ids is not None and not (ids and all(isinstance(i, str) for i in ids)):
        raise BenchmarkError(f"{path}: ids must be a non-empty list of strings")
    return Benchmark(
        name=data["name"],
        url=data["url"],
        sha256=data["sha256"],
        format=data["format"],
        ids=None if ids is None else tuple(ids),
    )


def load_problems(benchmark: Benchmark, data_dir: Path) -> list[Problem]:
    """The benchmark's problems, in the order of its id list or else of its file."""
    rows = read_rows(benchmark, data_dir)
    counts = Counter(row["unique_id"] for row in rows)

    if benchmark.ids is None:
        selected = rows
        repeated = sorted(id for id, count in counts.items() if count > 1)
    else:
        absent = [id for id in benchmark.ids if id not in counts]
        if absent:
            raise BenchmarkError(f"{benchmark.name}: no problem with id {absent[0]}")
        by_id = {row["unique_id"]: row for row in rows}
        selected = [by_id[id] for id in benchmark.ids]
        repeated = sorted({id for id in benchmark.ids if counts[id] > 1})
        repeated += sorted(id for id, count in Counter(benchmark.ids).items() if count > 1)
    if repeated:
        raise BenchmarkError(f"{benchmark.name}: the id {repeated[0]} names more than one problem")

    problems = [
        Problem(
            id=row["unique_id"],
            problem=row["problem"],
            answer=row["answer"] or "",
            subject=row.get("subject"),
            level=row.get("level"),
        )
        for row in selected
    ]
    for problem in problems:
        if not problem.answer.strip():
            raise BenchmarkError(f"{benchmark.name}: {problem.id} has no reference answer")
    return problems


def read_rows(benchmark: Benchmark, data_dir: Path) -> list[dict]:
    """Every row of the benchmark's file as it stands, checked against the pin only."""
    return _rows(benchmark, _fetch(benchmark, Path(data_dir)))


def _fetch(benchmark: Benchmark, data_dir: Path) -> Path:
    """The problem file in the data directory, downloaded if it is absent or damaged."""
    stored = data_dir / f"{benchmark.name}-{benchmark.sha256[:12]}.{benchmark.format}"
    if stored.exists() and _sha256(stored.read_bytes()) == benchmark.sha256:
        return stored

    request = urllib.request.Request(benchmark.url, headers={"User-Agent": "pi"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            content = response.read()
    except (urllib.error.URLError, OSError) as error:
        raise BenchmarkError(f"cannot fetch {benchmark.url}: {error}") from None

    found = _sha256(content)
    if found != benchmark.sha256:
        raise BenchmarkError(
            f"{benchmark.name}: checksum mismatch for {benchmark.url}: "
            f"expected {benchmark.sha256}, got {found}"
        )
    data_dir.mkdir(parents=True, exist_ok=True)
    partial = stored.with_suffix(".partial")
    partial.write_bytes(content)
    partial.replace(stored)
    return stored


def _rows(benchmark: Benchmark, path: Path) -> list[dict]:
    if benchmark.format == "parquet":
        return pyarrow.parquet.read_table(path).to_pylist()
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
