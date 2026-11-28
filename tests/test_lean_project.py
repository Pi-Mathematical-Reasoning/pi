"""Lean benchmarks: a definition pinned by commit, its checkout, its environment and setup."""

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

from pi.benchmarks import Benchmark, BenchmarkError, load_benchmark
from pi.lean_project import (
    LeanBenchmark,
    ensure_checkout,
    lean_environment,
    load_lean_benchmark,
    load_theorems,
    setup,
)

REPO = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).parent / "lean_fixture" / "Split.lean"
ORDER = [
    "fixture_add_zero",
    "fixture_no_docstring",
    "amc12a_2099_p1",
    "mathd_algebra_9001",
    "fixture_poly.variants.Polynomial",
    "mathd_numbertheory_9002",
    "fixture_tight_above",
    "fixture_tight_below",
]
SHA = "a" * 40


def git(directory: Path, *arguments: str) -> str:
    done = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *arguments],
        cwd=directory,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def make_repository(root: Path, name: str) -> tuple[Path, str]:
    source = root / name
    source.mkdir(parents=True)
    git(source, "init", "-q")
    (source / "lean-toolchain").write_text("leanprover/lean4:v4.99.0\n")
    (source / "lake-manifest.json").write_text("{}\n")
    (source / "lakefile.lean").write_text("-- lakefile\n")
    (source / ".gitignore").write_text(".lake/\n")
    shutil.copy(FIXTURE, source / "Split.lean")
    git(source, "add", ".")
    git(source, "commit", "-q", "-m", "fixture")
    return source, git(source, "rev-parse", "HEAD")


def make_benchmark(root: Path, **changes) -> LeanBenchmark:
    source, commit = make_repository(root / "remote", "project")
    judge, judge_commit = make_repository(root / "remote", "judge")
    values = {
        "name": "fixture-lean",
        "repository": str(source),
        "commit": commit,
        "file": "Split.lean",
        "theorems": 8,
        "shipped_proofs": ("mathd_numbertheory_9002",),
        "lean_options": ("autoImplicit=false",),
        "allowed_axioms": ("propext",),
        "judge_repository": str(judge),
        "judge_commit": judge_commit,
    }
    return LeanBenchmark(**{**values, **changes})


def definition(**changes) -> dict:
    values = {
        "name": "d",
        "kind": "lean",
        "repository": "https://example.com/p",
        "commit": SHA,
        "file": "A.lean",
        "theorems": 3,
        "shipped_proofs": [],
        "lean_options": [],
        "allowed_axioms": [],
        "judge_repository": "https://example.com/j",
        "judge_commit": SHA,
    }
    values.update(changes)
    return {key: value for key, value in values.items() if value is not None}


def test_a_definition_of_kind_lean_loads_as_a_lean_benchmark():
    benchmark = load_benchmark(REPO / "benchmarks/minif2f-test.toml")
    assert isinstance(benchmark, LeanBenchmark)
    assert benchmark.theorems == 244
    assert benchmark.scored is True
    assert benchmark.ids is None


def test_an_answer_definition_still_loads_as_before():
    assert isinstance(load_benchmark(REPO / "benchmarks/math-500.toml"), Benchmark)


def test_loads_the_optional_settings():
    benchmark = load_lean_benchmark(Path("d.toml"), definition(ids=["a", "b"], scored=True))
    assert benchmark.ids == ("a", "b")
    assert benchmark.scored is True


@pytest.mark.parametrize(
    ("changes", "setting"),
    [
        ({"surprise": 1}, "surprise"),
        ({"commit": "abc123"}, "commit"),
        ({"judge_commit": "abc123"}, "judge_commit"),
        ({"theorems": "8"}, "theorems"),
        ({"theorems": True}, "theorems"),
        ({"shipped_proofs": "x"}, "shipped_proofs"),
        ({"lean_options": [1]}, "lean_options"),
        ({"ids": []}, "ids"),
        ({"scored": "yes"}, "scored"),
        ({"file": None}, "file"),
    ],
)
def test_refuses_an_unknown_setting_and_a_short_commit(changes, setting):
    with pytest.raises(BenchmarkError, match=setting):
        load_lean_benchmark(Path("d.toml"), definition(**changes))


def test_ensure_checkout_clones_at_the_commit_and_is_then_a_no_op(tmp_path):
    source, commit = make_repository(tmp_path / "remote", "project")
    data = tmp_path / "data"
    path = ensure_checkout(data, str(source), commit)
    assert path == data / "lean" / f"project-{commit[:12]}"
    assert git(path, "rev-parse", "HEAD") == commit
    (path / "marker").write_text("")
    git(path, "add", "marker")
    git(path, "commit", "-q", "-m", "more")
    git(path, "reset", "-q", "--hard", commit)
    calls = []

    def refuse(command, **kwargs):
        calls.append(command)
        return subprocess.run(command, **kwargs)

    assert ensure_checkout(data, str(source), commit, run=refuse) == path
    assert not any("clone" in command for command in calls)


def test_refuses_a_checkout_at_another_commit(tmp_path):
    source, commit = make_repository(tmp_path / "remote", "project")
    path = ensure_checkout(tmp_path / "data", str(source), commit)
    (path / "x").write_text("x")
    git(path, "add", "x")
    git(path, "commit", "-q", "-m", "x")
    with pytest.raises(BenchmarkError, match="is at"):
        ensure_checkout(tmp_path / "data", str(source), commit)


def test_refuses_a_checkout_with_changes(tmp_path):
    source, commit = make_repository(tmp_path / "remote", "project")
    path = ensure_checkout(tmp_path / "data", str(source), commit)
    (path / "lakefile.lean").write_text("-- edited\n")
    with pytest.raises(BenchmarkError, match="has uncommitted changes"):
        ensure_checkout(tmp_path / "data", str(source), commit)


def test_theorems_come_in_file_order_or_in_the_order_of_the_ids(tmp_path):
    benchmark = make_benchmark(tmp_path, theorems=8)
    ensure_checkout(tmp_path / "data", benchmark.repository, benchmark.commit)
    assert [t.id for t in load_theorems(benchmark, tmp_path / "data")] == ORDER
    chosen = make_benchmark(tmp_path / "again", ids=("mathd_algebra_9001", "fixture_add_zero"))
    ensure_checkout(tmp_path / "data", chosen.repository, chosen.commit)
    found = load_theorems(chosen, tmp_path / "data")
    assert [t.id for t in found] == ["mathd_algebra_9001", "fixture_add_zero"]


def test_refuses_a_file_with_the_wrong_number_of_theorems(tmp_path):
    benchmark = make_benchmark(tmp_path, theorems=9)
    ensure_checkout(tmp_path / "data", benchmark.repository, benchmark.commit)
    with pytest.raises(BenchmarkError, match="expected 9 theorems, found 8"):
        load_theorems(benchmark, tmp_path / "data")


def test_refuses_when_the_shipped_proofs_are_not_the_ones_named(tmp_path):
    benchmark = make_benchmark(tmp_path, shipped_proofs=())
    ensure_checkout(tmp_path / "data", benchmark.repository, benchmark.commit)
    with pytest.raises(BenchmarkError, match="mathd_numbertheory_9002"):
        load_theorems(benchmark, tmp_path / "data")


def test_refuses_an_id_the_file_does_not_hold(tmp_path):
    benchmark = make_benchmark(tmp_path, ids=("no_such_theorem",))
    ensure_checkout(tmp_path / "data", benchmark.repository, benchmark.commit)
    with pytest.raises(BenchmarkError, match="no_such_theorem"):
        load_theorems(benchmark, tmp_path / "data")


def test_a_missing_checkout_says_to_run_lean_setup(tmp_path):
    benchmark = make_benchmark(tmp_path)
    with pytest.raises(BenchmarkError, match="pi lean-setup"):
        load_theorems(benchmark, tmp_path / "data")


def prepare(tmp_path, benchmark, build_judge=True):
    data = tmp_path / "data"
    project = ensure_checkout(data, benchmark.repository, benchmark.commit)
    judge = ensure_checkout(data, benchmark.judge_repository, benchmark.judge_commit)
    if build_judge:
        binary = judge / ".lake" / "build" / "bin" / "safe_verify"
        binary.parent.mkdir(parents=True)
        binary.write_text("")
    return data, project


def fake_lake(command, **kwargs):
    if command[0] != "lake":
        return subprocess.run(command, **kwargs)
    assert command == ["lake", "env", "lean", "--version"]
    return subprocess.CompletedProcess(command, 0, "Lean (version 4.99.0, x)\nsecond\n", "")


def test_the_environment_names_the_toolchain_and_each_file_s_checksum(tmp_path, monkeypatch):
    benchmark = make_benchmark(tmp_path)
    data, project = prepare(tmp_path, benchmark)
    monkeypatch.setattr(shutil, "which", lambda name: "/bin/lake")

    environment = lean_environment(benchmark, data, run=fake_lake)

    def sha(name):
        return hashlib.sha256((project / name).read_bytes()).hexdigest()

    assert environment == {
        "toolchain": "leanprover/lean4:v4.99.0",
        "lean_version": "Lean (version 4.99.0, x)",
        "files": {
            "lean-toolchain": sha("lean-toolchain"),
            "lake-manifest.json": sha("lake-manifest.json"),
            "lakefile.lean": sha("lakefile.lean"),
            "Split.lean": sha("Split.lean"),
        },
        "options": ["autoImplicit=false"],
    }


def test_an_environment_that_is_not_set_up_says_to_run_lean_setup(tmp_path, monkeypatch):
    benchmark = make_benchmark(tmp_path)
    monkeypatch.setattr(shutil, "which", lambda name: "/bin/lake")
    with pytest.raises(BenchmarkError, match="pi lean-setup"):
        lean_environment(benchmark, tmp_path / "data", run=fake_lake)
    data, project = prepare(tmp_path, benchmark, build_judge=False)
    with pytest.raises(BenchmarkError, match="pi lean-setup"):
        lean_environment(benchmark, data, run=fake_lake)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(BenchmarkError, match="pi lean-setup"):
        lean_environment(benchmark, data, run=fake_lake)
    monkeypatch.setattr(shutil, "which", lambda name: "/bin/lake")
    (project / "lakefile.lean").write_text("-- edited\n")
    with pytest.raises(BenchmarkError, match="pi lean-setup"):
        lean_environment(benchmark, data, run=fake_lake)


def test_setup_runs_the_builds_in_order(tmp_path):
    benchmark = make_benchmark(tmp_path)
    calls = []

    def record(command, **kwargs):
        if command[0] != "lake":
            return subprocess.run(command, **kwargs)
        calls.append((command, Path(kwargs["cwd"]).name))
        return subprocess.CompletedProcess(command, 0, "", "")

    lines = []
    setup(benchmark, tmp_path / "data", report=lines.append, run=record)

    project = f"project-{benchmark.commit[:12]}"
    judge = f"judge-{benchmark.judge_commit[:12]}"
    assert calls == [
        (["lake", "exe", "cache", "get"], project),
        (["lake", "build"], project),
        (["lake", "build", "safe_verify"], judge),
    ]
    assert lines[-1] == "fixture-lean: 8 theorems"


def test_setup_reports_a_subset_as_a_share_of_the_file(tmp_path):
    benchmark = make_benchmark(tmp_path, ids=("fixture_add_zero", "mathd_algebra_9001"))
    lines = []
    setup(
        benchmark,
        tmp_path / "data",
        report=lines.append,
        run=lambda command, **kw: (
            subprocess.CompletedProcess(command, 0, "", "")
            if command[0] == "lake"
            else subprocess.run(command, **kw)
        ),
    )
    assert lines[-1] == "fixture-lean: 2 of 8 theorems"


def test_a_failing_build_carries_the_command_and_the_end_of_its_output(tmp_path):
    benchmark = make_benchmark(tmp_path)

    def failing(command, **kwargs):
        if command[0] != "lake":
            return subprocess.run(command, **kwargs)
        return subprocess.CompletedProcess(command, 1, "", "boom: the real reason")

    with pytest.raises(BenchmarkError, match=r"(?s)lake exe cache get.*boom: the real reason"):
        setup(benchmark, tmp_path / "data", report=lambda line: None, run=failing)
