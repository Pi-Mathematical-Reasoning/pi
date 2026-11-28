"""Lean benchmarks: a definition pinned by commit, its checkout, its environment and setup."""

import contextlib
import hashlib
import os
import shutil
import signal
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from pi.benchmarks import Benchmark, BenchmarkError, load_benchmark
from pi.lean_project import (
    LOCK,
    Finished,
    LeanBenchmark,
    LeanRunner,
    ensure_checkout,
    lean_environment,
    load_lean_benchmark,
    load_theorems,
    run_process,
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


def _alive(pid: int) -> bool:
    """Whether the process runs; a killed one lingers as a zombie until reaped, and is not alive."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    state = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    ).stdout.strip()
    return bool(state) and not state.startswith("Z")


def test_a_process_past_its_limit_is_killed_with_everything_it_started(tmp_path):
    script = tmp_path / "start.sh"
    script.write_text("sleep 60 &\necho $! > pid\nsleep 60\n")
    try:
        done = run_process(["sh", str(script)], tmp_path, limit=1)
        pid = int((tmp_path / "pid").read_text())
        assert done.exit_code is None and 1 <= done.seconds < 5
        assert _dies_soon(pid)
    finally:  # leave no stray sleep behind if the assertions fail
        if (tmp_path / "pid").exists():
            with contextlib.suppress(ProcessLookupError):
                os.kill(int((tmp_path / "pid").read_text()), signal.SIGKILL)


def test_an_interrupted_wait_kills_the_process_group_and_propagates(tmp_path):
    script = tmp_path / "start.sh"
    script.write_text("sleep 60 &\necho $! > pid\nsleep 60\n")
    timer = threading.Timer(1, os.kill, [os.getpid(), signal.SIGINT])
    timer.start()
    try:
        with pytest.raises(KeyboardInterrupt):
            run_process(["sh", str(script)], tmp_path, limit=30)
        assert _dies_soon(int((tmp_path / "pid").read_text()))
    finally:  # leave no stray sleep behind if the assertions fail
        timer.cancel()
        if (tmp_path / "pid").exists():
            with contextlib.suppress(ProcessLookupError):
                os.kill(int((tmp_path / "pid").read_text()), signal.SIGKILL)


def _dies_soon(pid: int) -> bool:
    """Whether the process is gone within 5 seconds; a killed orphan is reaped a moment later."""
    deadline = time.monotonic() + 5
    while _alive(pid):
        if time.monotonic() > deadline:
            return False
        time.sleep(0.01)
    return True


def test_a_child_left_behind_by_a_command_that_exits_is_killed(tmp_path):
    script = tmp_path / "start.sh"
    script.write_text("sleep 60 < /dev/null > /dev/null 2>&1 &\necho $! > pid\nexit 0\n")
    try:
        done = run_process(["sh", str(script)], tmp_path, limit=30)
        pid = int((tmp_path / "pid").read_text())
        assert done.exit_code == 0 and done.seconds < 1
        assert _dies_soon(pid)
    finally:  # leave no stray sleep behind if the assertions fail
        if (tmp_path / "pid").exists():
            with contextlib.suppress(ProcessLookupError):
                os.kill(int((tmp_path / "pid").read_text()), signal.SIGKILL)


def test_a_permission_error_from_killing_the_group_does_not_escape(tmp_path, monkeypatch):
    # macOS sometimes answers EPERM, not ESRCH, for a group whose processes have all exited.
    real = os.killpg

    def killpg(pid, sig):
        with contextlib.suppress(OSError):
            real(pid, sig)
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr("pi.lean_project.os.killpg", killpg)
    done = run_process(["sh", "-c", "echo hi"], tmp_path, limit=10)
    assert (done.exit_code, done.stdout) == (0, "hi\n")
    assert run_process(["sleep", "60"], tmp_path, limit=1).exit_code is None


def _wait_for(path: Path, seconds: float = 10) -> int:
    deadline = time.monotonic() + seconds
    while not (path.exists() and path.read_text().strip()):
        assert time.monotonic() < deadline, f"{path} was never written"
        time.sleep(0.01)
    return int(path.read_text())


def test_a_descendant_that_escaped_the_group_cannot_hold_the_call_open(tmp_path, monkeypatch):
    monkeypatch.setattr("pi.lean_project.DRAIN_SECONDS", 1)
    escape = (
        "import os, time; os.setsid(); open('pid', 'w').write(str(os.getpid())); time.sleep(60)"
    )
    script = tmp_path / "start.sh"
    script.write_text(f'echo started\n{sys.executable} -c "{escape}" &\nsleep 60\n')
    try:
        done = run_process(["sh", str(script)], tmp_path, limit=1)
        assert done.exit_code is None and done.seconds < 10
        assert done.stdout == "started\n"
    finally:  # the escaped process holds the pipe until it is killed
        with contextlib.suppress(ProcessLookupError):
            os.kill(_wait_for(tmp_path / "pid"), signal.SIGKILL)


@pytest.mark.parametrize("number", [signal.SIGTERM, signal.SIGHUP])
def test_a_termination_signal_kills_what_the_check_started(tmp_path, number):
    script = tmp_path / "start.sh"
    script.write_text("sleep 60 &\necho $! > pid\nsleep 60\n")
    code = textwrap.dedent(
        f"""
        from pathlib import Path
        from pi.cli import termination_as_interrupt
        from pi.lean_project import run_process
        with termination_as_interrupt():
            run_process(["sh", {str(script)!r}], Path({str(tmp_path)!r}), 60)
        """
    )
    child = subprocess.Popen([sys.executable, "-c", code], cwd=REPO, stderr=subprocess.PIPE)
    try:
        grandchild = _wait_for(tmp_path / "pid")
        child.send_signal(number)
        _, stderr = child.communicate(timeout=10)
        assert b"KeyboardInterrupt" in stderr
        assert _dies_soon(grandchild)
    finally:  # leave nothing behind if the assertions fail
        child.kill()
        if (tmp_path / "pid").exists():
            with contextlib.suppress(ProcessLookupError, ValueError):
                os.kill(int((tmp_path / "pid").read_text()), signal.SIGKILL)


def test_output_is_read_as_utf8_whatever_the_locale(tmp_path, monkeypatch):
    monkeypatch.setenv("LC_ALL", "C")
    code = "import sys; sys.stdout.buffer.write('\u211d \u2211'.encode())"
    done = run_process([sys.executable, "-c", code], tmp_path, 10)
    assert done.stdout == "\u211d \u2211"


def test_a_command_that_cannot_start_is_named(tmp_path):
    with pytest.raises(BenchmarkError, match="no-such-program-xyz"):
        run_process(["no-such-program-xyz", "--flag"], tmp_path, 5)


def recording_runner(tmp_path):
    benchmark = LeanBenchmark(
        name="b",
        repository="https://example.com/miniF2F",
        commit="f0a20e14c1ee" + "0" * 28,
        file="A.lean",
        theorems=1,
        shipped_proofs=(),
        lean_options=("autoImplicit=false", "relaxedAutoImplicit=false"),
        allowed_axioms=(),
        judge_repository="https://example.com/SafeVerify",
        judge_commit="b291b588a539" + "0" * 28,
    )
    calls = []

    def record(command, cwd, limit):
        calls.append((command, cwd, limit))
        return Finished(0, "", "", 0.0)

    data = tmp_path / "data"
    return LeanRunner(benchmark, data, run_process=record), calls, data


def test_compile_runs_lean_in_the_checkout_with_the_options_and_relative_paths(tmp_path):
    runner, calls, data = recording_runner(tmp_path)
    work = data / "lean" / "work" / "x"
    runner.compile(work / "Submission.lean", work / "Submission.olean", 7)
    assert calls == [
        (
            [
                "lake", "env", "lean", "--json",
                "-D", "autoImplicit=false", "-D", "relaxedAutoImplicit=false",
                "--root=../work/x", "-o", "../work/x/Submission.olean", "../work/x/Submission.lean",
            ],
            data / "lean" / "miniF2F-f0a20e14c1ee",
            7,
        )
    ]  # fmt: skip


def test_judge_runs_safeverify_through_lake_env_with_relative_paths(tmp_path):
    runner, calls, data = recording_runner(tmp_path)
    work = data / "lean" / "work" / "x"
    runner.judge(work / "Reference.olean", work / "Submission.olean", work / "judge.json", 9)
    assert calls == [
        (
            [
                "lake", "env", "../SafeVerify-b291b588a539/.lake/build/bin/safe_verify",
                "--save", "../work/x/judge.json",
                "../work/x/Reference.olean", "../work/x/Submission.olean",
            ],
            data / "lean" / "miniF2F-f0a20e14c1ee",
            9,
        )
    ]  # fmt: skip


def test_a_work_directory_is_removed_even_when_the_check_raises(tmp_path):
    runner, _, data = recording_runner(tmp_path)
    with pytest.raises(RuntimeError), runner.work_dir() as work:
        assert work.parent == data / "lean" / "work" and work.is_dir()
        (work / "x.olean").write_text("x")
        seen = work
        raise RuntimeError("boom")
    assert not seen.exists()
    with runner.work_dir() as again:
        assert again != seen


WAITING = "waiting for another Lean check on this machine to finish\n"


def _enter_in_thread(runner):
    """Open `runner.work_dir()` in a thread; the events say when it is in and when to leave."""
    entered, leave = threading.Event(), threading.Event()

    def work():
        with runner.work_dir():
            entered.set()
            leave.wait(10)

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    return thread, entered, leave


def test_a_second_check_waits_for_the_first_then_proceeds(tmp_path, capsys):
    runner, _, data = recording_runner(tmp_path)
    other = LeanRunner(runner.benchmark, data)
    with runner.work_dir():
        thread, entered, leave = _enter_in_thread(other)
        try:
            assert not entered.wait(0.5)  # waiting, not refused
            assert len([p for p in (data / "lean" / "work").iterdir() if p.is_dir()]) == 1
        finally:
            leave.set()
    assert entered.wait(5)
    thread.join(5)
    assert capsys.readouterr().err == WAITING


def test_a_check_that_finds_the_lock_free_prints_nothing(tmp_path, capsys):
    runner, _, _ = recording_runner(tmp_path)
    with runner.work_dir() as work:
        assert work.is_dir()
    with runner.work_dir():
        pass
    assert capsys.readouterr().err == ""


def test_a_nested_work_directory_in_one_thread_is_a_programming_error(tmp_path):
    # Waiting for a lock the same thread holds would never end.
    runner, _, data = recording_runner(tmp_path)
    other = LeanRunner(runner.benchmark, data)
    nested = pytest.raises(RuntimeError, match="already open in this thread")
    with runner.work_dir(), nested, other.work_dir():
        pass
    with other.work_dir() as work:
        assert work.is_dir()


def test_the_lock_is_released_when_a_check_raises(tmp_path, capsys):
    runner, _, _ = recording_runner(tmp_path)
    with pytest.raises(RuntimeError), runner.work_dir():
        raise RuntimeError("boom")
    with runner.work_dir() as work:
        assert work.is_dir()
    assert capsys.readouterr().err == ""


def test_a_lock_held_by_a_process_that_dies_stops_blocking(tmp_path, capsys):
    runner, _, data = recording_runner(tmp_path)
    with runner.work_dir():
        pass
    lock = data / "lean" / "work" / LOCK
    hold = "import fcntl, os, sys, time; fd = os.open(sys.argv[1], os.O_RDWR); "
    hold += "fcntl.flock(fd, fcntl.LOCK_EX); print('locked', flush=True); time.sleep(60)"
    child = subprocess.Popen([sys.executable, "-c", hold, str(lock)], stdout=subprocess.PIPE)
    try:
        assert child.stdout.readline() == b"locked\n"
        thread, entered, leave = _enter_in_thread(runner)
        leave.set()
        assert not entered.wait(0.5)  # waits on the other process
        child.kill()  # dies holding the lock, as a crashed pi would
        child.wait(timeout=10)
        assert entered.wait(5)
        thread.join(5)
        assert lock.exists()
        assert capsys.readouterr().err == WAITING
    finally:
        child.kill()
        child.wait(timeout=10)
