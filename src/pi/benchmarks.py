"""Benchmarks: a pinned problem file, fetched once, checked, and read.

A benchmark definition is a TOML file naming a URL and the SHA-256 of what it
must return, and optionally an S3 mirror holding the same bytes. Problem files
are never committed: they are fetched into a data directory, from the mirror
first when there is one, and checked against the pin every time they are read.
"""

import hashlib
import json
import re
import subprocess
import tempfile
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
    mirror: str | None = None  # s3://bucket/key holding the same bytes, tried first
    # A scored benchmark is held to a stricter standard: committed code, mains
    # power and verified weights (pi.evaluation).
    scored: bool = False


@dataclass(frozen=True)
class Fetched:
    path: Path
    source: str  # where the bytes came from: the mirror or the upstream URL
    warnings: list[str]


def load_benchmark(path: Path) -> Benchmark:
    path = Path(path)
    try:
        data = tomllib.loads(path.read_text())
    except FileNotFoundError:
        raise BenchmarkError(f"no benchmark definition at {path}") from None
    except tomllib.TOMLDecodeError as error:
        raise BenchmarkError(f"{path} is not valid TOML: {error}") from None

    required = ("name", "url", "sha256", "format")
    unknown = sorted(set(data) - {*required, "ids", "mirror", "scored"})
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
    mirror = data.get("mirror")
    if mirror is not None and not (isinstance(mirror, str) and _S3_URI.match(mirror)):
        raise BenchmarkError(f"{path}: mirror must be an s3://bucket/key URI, not {mirror!r}")
    scored = data.get("scored", False)
    if not isinstance(scored, bool):
        raise BenchmarkError(f"{path}: scored must be true or false, not {scored!r}")
    return Benchmark(
        name=data["name"],
        url=data["url"],
        sha256=data["sha256"],
        format=data["format"],
        ids=None if ids is None else tuple(ids),
        mirror=mirror,
        scored=scored,
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
    return _rows(benchmark, fetch_file(benchmark, data_dir).path)


def fetch_file(benchmark: Benchmark, data_dir: Path) -> Fetched:
    """The problem file in the data directory, fetched first if it is absent or damaged.

    The mirror is tried first and the upstream URL second. Either must return the
    pinned bytes, so the two are interchangeable; a mirror that fails for any
    reason is a warning, not an error. The source is recorded beside the file.
    """
    data_dir = Path(data_dir)
    stored = data_dir / f"{benchmark.name}-{benchmark.sha256[:12]}.{benchmark.format}"
    origin = stored.with_name(stored.name + ".source")
    if stored.exists() and _sha256(stored.read_bytes()) == benchmark.sha256:
        recorded = origin.read_text().strip() if origin.exists() else ""
        return Fetched(stored, recorded or "unknown: fetched before sources were recorded", [])

    warnings = []
    content = source = None
    if benchmark.mirror is not None:
        try:
            content = _checked(benchmark, benchmark.mirror, _from_s3(benchmark.mirror))
            source = benchmark.mirror
        except BenchmarkError as error:
            warnings.append(f"the mirror did not serve the file, so the upstream will: {error}")
    if content is None:
        try:
            content = _checked(benchmark, benchmark.url, _from_url(benchmark.url))
        except BenchmarkError as error:
            tried = "" if benchmark.mirror is None else f"; the mirror failed too ({warnings[0]})"
            raise BenchmarkError(f"{error}{tried}") from None
        source = benchmark.url

    data_dir.mkdir(parents=True, exist_ok=True)
    partial = stored.with_suffix(".partial")
    partial.write_bytes(content)
    partial.replace(stored)
    origin.write_text(source + "\n")
    return Fetched(stored, source, warnings)


_S3_URI = re.compile(r"^s3://([a-z0-9][a-z0-9.-]{1,61}[a-z0-9])/(.+)$")
_AWS_ERROR = re.compile(r"An error occurred \(([A-Za-z]+)\)")
_SIGN_IN = {
    "ExpiredToken",
    "ExpiredTokenException",
    "InvalidClientTokenId",
    "NoCredentials",
    "UnauthorizedSSOToken",
}


def _from_url(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "pi"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.read()
    except (urllib.error.URLError, OSError) as error:
        raise BenchmarkError(f"cannot fetch {url}: {error}") from None


def _from_s3(uri: str) -> bytes:
    """An object's bytes, through the AWS CLI with whatever credentials the shell has."""
    bucket, key = _S3_URI.match(uri).groups()
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / "object"
        command = ["aws", "s3api", "get-object", "--bucket", bucket, "--key", key, str(target)]
        try:
            done = subprocess.run(command, capture_output=True, text=True, timeout=300)
        except FileNotFoundError:
            raise BenchmarkError(f"cannot read {uri}: the AWS CLI is not installed") from None
        except subprocess.TimeoutExpired:
            raise BenchmarkError(f"cannot read {uri}: the AWS CLI timed out") from None
        if done.returncode != 0:
            match = _AWS_ERROR.search(done.stderr)
            code = match.group(1) if match else done.stderr.strip() or f"exit {done.returncode}"
            hint = (
                " (run `aws sso login --profile jaws-prod` and set AWS_PROFILE=jaws-prod)"
                if code in _SIGN_IN
                else ""
            )
            raise BenchmarkError(f"cannot read {uri}: {code}{hint}")
        return target.read_bytes()


def _checked(benchmark: Benchmark, source: str, content: bytes) -> bytes:
    found = _sha256(content)
    if found != benchmark.sha256:
        raise BenchmarkError(
            f"{benchmark.name}: checksum mismatch for {source}: "
            f"expected {benchmark.sha256}, got {found}"
        )
    return content


def _rows(benchmark: Benchmark, path: Path) -> list[dict]:
    if benchmark.format == "parquet":
        return pyarrow.parquet.read_table(path).to_pylist()
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
