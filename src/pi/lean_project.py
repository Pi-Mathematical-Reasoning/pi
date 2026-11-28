"""Lean benchmarks: a Lean project pinned by git commit, whose problems are one file's theorems.

A definition names a repository and a commit, the file holding the theorems, and a
judge repository (also pinned). Both are checked out under `<data dir>/lean/` and
never committed. A checkout that is at another commit or has changes is refused,
so what was graded is what the definition names.
"""

import contextlib
import hashlib
import os
import re
import secrets
import shutil
import signal
import subprocess
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from pi.benchmarks import BenchmarkError
from pi.lean_statements import StatementError, Theorem, split_theorems

COMMIT = re.compile(r"^[0-9a-f]{40}$")
STRINGS = ("name", "kind", "repository", "file", "judge_repository")
COMMITS = ("commit", "judge_commit")
LISTS = ("shipped_proofs", "lean_options", "allowed_axioms")
PROJECT_FILES = ("lean-toolchain", "lake-manifest.json", "lakefile.lean")
JUDGE_BINARY = Path(".lake") / "build" / "bin" / "safe_verify"
SETUP_HINT = "run `pi lean-setup` for this benchmark"


@dataclass(frozen=True)
class LeanBenchmark:
    name: str
    repository: str
    commit: str
    file: str
    theorems: int  # how many theorems the file must yield
    shipped_proofs: tuple[str, ...]
    lean_options: tuple[str, ...]
    allowed_axioms: tuple[str, ...]
    judge_repository: str
    judge_commit: str
    ids: tuple[str, ...] | None = None  # a frozen subset, or None for every theorem in the file
    scored: bool = False
    kind: str = "lean"


def load_lean_benchmark(path: Path, data: dict) -> LeanBenchmark:
    allowed = {*STRINGS, *COMMITS, *LISTS, "theorems", "ids", "scored"}
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise BenchmarkError(f"{path}: unknown setting {unknown[0]}")
    for key in STRINGS:
        if not isinstance(data.get(key), str) or not data[key]:
            raise BenchmarkError(f"{path}: {key} must be a non-empty string")
    for key in COMMITS:
        if not isinstance(data.get(key), str) or not COMMIT.match(data[key]):
            raise BenchmarkError(f"{path}: {key} must be a full 40-character commit hash")
    theorems = data.get("theorems")
    if not isinstance(theorems, int) or isinstance(theorems, bool) or theorems < 1:
        raise BenchmarkError(f"{path}: theorems must be a whole number, the count the file holds")
    for key in LISTS:
        if not _strings(data.get(key)):
            raise BenchmarkError(f"{path}: {key} must be a list of strings")
    ids = data.get("ids")
    if ids is not None and not (ids and _strings(ids)):
        raise BenchmarkError(f"{path}: ids must be a non-empty list of strings")
    scored = data.get("scored", False)
    if not isinstance(scored, bool):
        raise BenchmarkError(f"{path}: scored must be true or false, not {scored!r}")
    return LeanBenchmark(
        name=data["name"],
        repository=data["repository"],
        commit=data["commit"],
        file=data["file"],
        theorems=theorems,
        shipped_proofs=tuple(data["shipped_proofs"]),
        lean_options=tuple(data["lean_options"]),
        allowed_axioms=tuple(data["allowed_axioms"]),
        judge_repository=data["judge_repository"],
        judge_commit=data["judge_commit"],
        ids=None if ids is None else tuple(ids),
        scored=scored,
    )


def _strings(value) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def checkout_dir(data_dir: Path, repository: str, commit: str) -> Path:
    basename = repository.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
    return Path(data_dir) / "lean" / f"{basename}-{commit[:12]}"


def ensure_checkout(data_dir: Path, repository: str, commit: str, run=subprocess.run) -> Path:
    """The repository checked out at the commit under the data directory, cloned if absent."""
    path = checkout_dir(data_dir, repository, commit)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        _git(run, ["git", "clone", "--quiet", repository, str(path)], None)
        _git(run, ["git", "checkout", "--quiet", "--detach", commit], path)
    _check_clean(path, commit, run)
    return path


def _check_clean(path: Path, commit: str, run) -> None:
    if not path.is_dir():
        raise BenchmarkError(f"no checkout at {path}")
    head = _git(run, ["git", "rev-parse", "HEAD"], path)
    if head != commit:
        raise BenchmarkError(f"the checkout {path} is at {head}, not {commit}")
    if _git(run, ["git", "status", "--porcelain"], path):
        raise BenchmarkError(f"the checkout {path} has uncommitted changes")


def _git(run, command: list[str], cwd: Path | None) -> str:
    return _run(run, command, cwd).strip()


def _run(run, command: list[str], cwd: Path | None) -> str:
    """The output of a command, or a BenchmarkError carrying the command and its output's end."""
    try:
        done = run(command, cwd=cwd, capture_output=True, text=True)
    except FileNotFoundError:
        raise BenchmarkError(
            f"cannot run {' '.join(command)}: {command[0]} is not installed"
        ) from None
    if done.returncode != 0:
        tail = "\n".join(((done.stdout or "") + (done.stderr or "")).strip().splitlines()[-20:])
        raise BenchmarkError(f"`{' '.join(command)}` failed in {cwd or Path.cwd()}:\n{tail}")
    return done.stdout or ""


def load_theorems(benchmark: LeanBenchmark, data_dir: Path) -> list[Theorem]:
    """The benchmark's theorems, in the order of its id list or else of its file."""
    checkout = checkout_dir(data_dir, benchmark.repository, benchmark.commit)
    source = checkout / benchmark.file
    try:
        text = source.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise BenchmarkError(f"{benchmark.name}: {source} does not exist; {SETUP_HINT}") from None
    try:
        theorems = split_theorems(text)
    except StatementError as error:
        raise BenchmarkError(f"{benchmark.name}: {source}: {error}") from None
    if len(theorems) != benchmark.theorems:
        raise BenchmarkError(
            f"{benchmark.name}: expected {benchmark.theorems} theorems, found {len(theorems)}"
        )
    shipped = {t.id for t in theorems if t.shipped_proof is not None}
    named = set(benchmark.shipped_proofs)
    if shipped != named:
        differing = sorted(shipped ^ named)
        raise BenchmarkError(
            f"{benchmark.name}: the shipped proofs are not the ones the definition names; "
            f"these differ: {', '.join(differing)}"
        )
    if benchmark.ids is None:
        return theorems
    by_id = {t.id: t for t in theorems}
    for id in benchmark.ids:
        if id not in by_id:
            raise BenchmarkError(f"{benchmark.name}: no theorem with id {id}")
    return [by_id[id] for id in benchmark.ids]


def lean_environment(benchmark: LeanBenchmark, data_dir: Path, run=subprocess.run) -> dict:
    """What the proofs are checked against: the toolchain and the checksum of each input file."""
    if shutil.which("lake") is None:
        raise BenchmarkError(f"{benchmark.name}: lake is not on the PATH; {SETUP_HINT}")
    project = checkout_dir(data_dir, benchmark.repository, benchmark.commit)
    judge = checkout_dir(data_dir, benchmark.judge_repository, benchmark.judge_commit)
    for path, commit in ((project, benchmark.commit), (judge, benchmark.judge_commit)):
        try:
            _check_clean(path, commit, run)
        except BenchmarkError as error:
            raise BenchmarkError(f"{benchmark.name}: {error}; {SETUP_HINT}") from None
    if not (judge / JUDGE_BINARY).exists():
        raise BenchmarkError(f"{benchmark.name}: {judge / JUDGE_BINARY} is missing; {SETUP_HINT}")
    version = _run(run, ["lake", "env", "lean", "--version"], project)
    files = {}
    for name in (*PROJECT_FILES, benchmark.file):
        try:
            files[name] = hashlib.sha256((project / name).read_bytes()).hexdigest()
        except FileNotFoundError:
            raise BenchmarkError(f"{benchmark.name}: {project / name} is missing") from None
    return {
        "toolchain": (project / "lean-toolchain").read_text(encoding="utf-8").strip(),
        "lean_version": version.splitlines()[0] if version.strip() else "",
        "files": files,
        "options": list(benchmark.lean_options),
    }


def setup(
    benchmark: LeanBenchmark,
    data_dir: Path,
    report: Callable[[str], None] = print,
    run=subprocess.run,
) -> None:
    """Check out and build the benchmark's project and its judge, then count the theorems."""
    project = ensure_checkout(data_dir, benchmark.repository, benchmark.commit, run)
    report(f"{benchmark.name}: project at {project}")
    for command in (["lake", "exe", "cache", "get"], ["lake", "build"]):
        report(f"{benchmark.name}: {' '.join(command)}")
        _run(run, command, project)
    judge = ensure_checkout(data_dir, benchmark.judge_repository, benchmark.judge_commit, run)
    report(f"{benchmark.name}: judge at {judge}")
    command = ["lake", "build", "safe_verify"]
    report(f"{benchmark.name}: {' '.join(command)}")
    _run(run, command, judge)
    theorems = load_theorems(benchmark, data_dir)
    if benchmark.ids is None:
        report(f"{benchmark.name}: {len(theorems)} theorems")
    else:
        report(f"{benchmark.name}: {len(theorems)} of {benchmark.theorems} theorems")


# Running Lean and the judge: each in a fresh process, under a wall-clock limit.


@dataclass(frozen=True)
class Finished:
    exit_code: int | None  # None: killed at the limit
    stdout: str
    stderr: str
    seconds: float


def run_process(command: list[str], cwd: Path, limit: float) -> Finished:
    """Run a command; at `limit` seconds kill it and everything it started."""
    started = time.monotonic()
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except FileNotFoundError:
        raise BenchmarkError(
            f"cannot run {' '.join(command)}: {command[0]} was not found"
        ) from None
    exit_code: int | None
    try:
        stdout, stderr = process.communicate(timeout=limit)
        exit_code = process.returncode
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate()
        exit_code = None
    except BaseException:  # an interrupt must not leave Lean or the judge running
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        raise
    return Finished(
        exit_code=exit_code,
        stdout=stdout.decode("utf-8", errors="replace"),
        stderr=stderr.decode("utf-8", errors="replace"),
        seconds=time.monotonic() - started,
    )


class LeanRunner:
    """Builds the Lean and judge command lines; every path is relative to the checkout."""

    def __init__(
        self,
        benchmark: LeanBenchmark,
        data_dir: Path,
        run_process: Callable[[list[str], Path, float], Finished] = run_process,
    ):
        self.benchmark = benchmark
        self.data_dir = Path(data_dir)
        self.run_process = run_process
        self.checkout = checkout_dir(data_dir, benchmark.repository, benchmark.commit)
        self.judge_binary = (
            checkout_dir(data_dir, benchmark.judge_repository, benchmark.judge_commit)
            / JUDGE_BINARY
        )

    @contextlib.contextmanager
    def work_dir(self) -> Iterator[Path]:
        """A fresh directory under `<data dir>/lean/work/`, removed on exit."""
        parent = self.data_dir / "lean" / "work"
        parent.mkdir(parents=True, exist_ok=True)
        path = parent / secrets.token_hex(8)
        path.mkdir()
        try:
            yield path
        finally:
            shutil.rmtree(path, ignore_errors=True)

    def compile(self, source: Path, olean: Path, limit: float) -> Finished:
        options = [part for option in self.benchmark.lean_options for part in ("-D", option)]
        command = [
            "lake", "env", "lean", "--json", *options,
            f"--root={self._relative(Path(source).parent)}",
            "-o", self._relative(olean),
            self._relative(source),
        ]  # fmt: skip
        return self.run_process(command, self.checkout, limit)

    def judge(self, reference: Path, submission: Path, saved: Path, limit: float) -> Finished:
        command = [
            "lake", "env", self._relative(self.judge_binary),
            "--save", self._relative(saved),
            self._relative(reference), self._relative(submission),
        ]  # fmt: skip
        return self.run_process(command, self.checkout, limit)

    def _relative(self, path: Path) -> str:
        return os.path.relpath(path, self.checkout)
