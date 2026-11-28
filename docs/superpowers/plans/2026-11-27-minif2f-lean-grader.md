# Lean Grader and miniF2F Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `pi eval` can run the pinned miniF2F theorems against Qwen3-14B and grade each proof with Lean, so a pre-registered proof baseline can be run, audited and published like the MATH-500 one.

**Architecture:** A Lean benchmark is a git repository pinned by commit, checked out under the git-ignored `data/lean/`. Each reply is graded in fresh processes: Lean compiles a file `pi` assembles, then SafeVerify (pinned) judges the compiled file against a reference `pi` compiled itself. `run_evaluation` gains a small "task" seam so the existing answer path and the new Lean path share the run loop, records, resume and scored standard.

**Tech Stack:** Python 3.13 through uv, pytest, ruff. Lean `leanprover/lean4:v4.27.0` through elan and lake; Mathlib `v4.27.0`; SafeVerify. Ollama as today.

**Spec:** `docs/superpowers/specs/2026-11-27-minif2f-lean-grader-design.md`. Read it first; this plan argues from it.

## Global Constraints

- Benchmark: `https://github.com/google-deepmind/miniF2F` at `f0a20e14c1eeccd859d51bb4c2b3ee487889c303`. Judge: `https://github.com/GasStationManager/SafeVerify` at `b291b588a53999a7e837dda61c7dbfe8c550c814`. Both need Lean `v4.27.0`.
- Checkouts live at `data/lean/miniF2F-f0a20e14c1ee/` and `data/lean/SafeVerify-b291b588a539/`; scratch files under `data/lean/work/`. Nothing under `data/` is committed.
- Allowed axioms: `propext`, `Classical.choice`, `Quot.sound`. Lean options for every compile: `autoImplicit=false`, `relaxedAutoImplicit=false`.
- Verdicts: `proved`, `failed`, `missing`, `cut_off`, `timed_out`. Only `proved` is solved. Reasons for `failed`: `lean_error`, `sorry`, `statement_changed`, `axioms`, `kernel_rejected`, `check_timed_out`, `judge_error`.
- Provisional limits: 16,384 output tokens, 1,200 s generation, 300 s per check step. The audit re-checks `proved` results at four times the check limits.
- Fail closed: a proof is `proved` only on the judge's exit status 0 and its saved JSON. There is no weaker fallback; if Task 1 cannot make the check work, stop and tell the owner.
- The model is never run on `benchmarks/minif2f-test.toml` in this plan. Lean-backed tests use the original theorems in `tests/lean_cases/`, never benchmark theorems.
- CI has no Lean: tests that need it run only with `PI_LEAN_TESTS=1` and are skipped otherwise. Every other test passes without Lean, a model or a download.
- MATH-500 behaviour is unchanged: `tests/test_evaluation.py`, `tests/test_report.py`, `tests/test_audit.py` and `tests/test_publish.py` pass without edits to their existing tests.
- Paths given to Lean and the judge are relative to the checkout, so no home directory reaches a record or a fixture.
- Commits are one line, Conventional Commits, at most 100 characters, with the trailer spelled exactly: `git commit -m "<subject>" -m "Co-authored-by: Claude Fable 5.2 <noreply@anthropic.com>"`. Never push to `main`; run `scripts/check.sh` before each pull request; fill every section of the typed PR template.
- The design and this plan reach `main` through a docs pull request before Task 1. Stage 1 then works on a new branch, `feat/lean-grader`.

## Review Focus

1. **Lean is not set up, or the checkout moved.** A missing or dirty checkout, a different commit, or no `lake` on the PATH must stop `pi eval` and `pi audit` before the first attempt with a message naming `pi lean-setup`, not grade 244 theorems as `judge_error`. Pinned in Tasks 3, 9 and 11.
2. **A Lean process that hangs.** At the limit the whole process tree must die (lake starts lean); orphaned `lean` processes over 244 problems would exhaust memory. Pinned in Task 4.
3. **The last code block is not the proof.** Replies ending in a ```` ```text ```` summary, an unclosed fence, or an empty block must not be compiled as Lean: the last closed Lean or untagged block is used, else `missing`. Pinned in Task 5.
4. **Lean prints megabytes.** A failing `simp` trace or a `#print` loop must not bloat `results.jsonl`: saved messages and judge output are capped at 20,000 characters. Pinned in Task 6.
5. **Non-ASCII everywhere.** Statements hold `ℝ`, `∑`, `₀`; Lean's output does too. Files are read and written as UTF-8 and process output is decoded as UTF-8 whatever the shell's locale. Pinned in Tasks 4 and 9.

## File Structure

| File | Responsibility |
| --- | --- |
| `src/pi/lean_statements.py` (new) | Split a Lean split file into theorems. Pure text |
| `src/pi/lean_project.py` (new) | The Lean benchmark definition, pinned checkouts, environment identity, setup, and the two commands (`LeanRunner`) |
| `src/pi/lean_grading.py` (new) | Lean rules version 1: extraction, assembly, flags, the judge's outcome as a reason, and `check` |
| `src/pi/lean_evaluation.py` (new) | `LeanTask`: prompt, grading, identity and proof files for `run_evaluation` |
| `src/pi/lean_report.py`, `src/pi/lean_audit.py` (new) | Report and audit of a Lean run |
| `src/pi/evaluation.py` | Gains the task seam and `AnswerTask` |
| `src/pi/benchmarks.py`, `report.py`, `audit.py`, `publish.py`, `config.py`, `cli.py` | Dispatch on the benchmark kind; optional `[lean]` config section; publish the files the audit names; `lean-setup` and `lean-check` commands |
| `benchmarks/minif2f-test.toml`, `benchmarks/minif2f-dev.toml`, `configs/qwen3-14b-lean.toml` (new) | Definitions and configuration |
| `tests/lean_cases/`, `tests/lean_fixture/Split.lean` (new) | Captured real Lean output per case; a split file in miniF2F's layout with original theorems |
| `docs/lean-grading.md` (new), `docs/records.md`, `README.md`, `AGENTS.md` | Rules and documentation |

---

# Stage 1: the grader (one pull request)

### Task 1: Prove the check works on Lean 4.27 (gate)

**Files:**
- Create: `tests/lean_cases/README.md`, and per case `tests/lean_cases/<case>/{Target.lean,Submission.lean,compile.stdout,compile.exit,judge.stderr,judge.exit,judge.json}`

**Interfaces:**
- Produces: the captured files Task 5 parses and Task 6 replays; the verified command forms Task 4 hard-codes.

- [ ] **Step 1: Ask the owner before installing.** elan installs Lean under `~/.elan`; the two checkouts and Mathlib's cache take several GB under `data/lean/`. Proceed on a yes.

- [ ] **Step 2: Install elan and both checkouts**

```sh
brew install elan-init && elan --version
mkdir -p data/lean && cd data/lean
git clone https://github.com/google-deepmind/miniF2F miniF2F-f0a20e14c1ee
git -C miniF2F-f0a20e14c1ee checkout --detach f0a20e14c1eeccd859d51bb4c2b3ee487889c303
(cd miniF2F-f0a20e14c1ee && lake exe cache get && lake build)
git clone https://github.com/GasStationManager/SafeVerify SafeVerify-b291b588a539
git -C SafeVerify-b291b588a539 checkout --detach b291b588a53999a7e837dda61c7dbfe8c550c814
(cd SafeVerify-b291b588a539 && lake build safe_verify)
```

Expected: both builds complete; `SafeVerify-b291b588a539/.lake/build/bin/safe_verify` exists; `git -C miniF2F-f0a20e14c1ee status --porcelain` prints nothing.

- [ ] **Step 3: Write the case files.** Every `Target.lean` and `Submission.lean` starts with `import Mathlib` and a blank line. Unless a row says otherwise, the target is

```lean
theorem pi_case (a b : ℕ) (h : a ≤ b) : a + 0 ≤ b := by
  sorry
```

| Case | `Submission.lean` after the import | Expected |
| --- | --- | --- |
| `valid` | the theorem, proved `by simpa using h` | `proved` |
| `sorry` | the theorem, `by sorry` | `sorry` |
| `helper_sorry` | `lemma pi_helper (a b : ℕ) : a + 0 ≤ b := by sorry`, then the theorem `:= pi_helper a b` | `sorry` |
| `helper_axiom` | `axiom pi_helper (a b : ℕ) : a + 0 ≤ b`, then the theorem `:= pi_helper a b` | `axioms` |
| `unused_sorry` | the valid proof, then `lemma pi_unused : (1 : ℕ) = 1 := by sorry` | `sorry` |
| `weakened` | `theorem pi_case (a b : ℕ) (h : a ≤ b) : a + 0 ≤ b + 1 := by omega` | `statement_changed` |
| `renamed` | the valid proof under the name `pi_case'` | `statement_changed` |
| `reformatted` | the valid proof with the statement broken over three lines and extra spaces | `proved` |
| `native_decide` | target `theorem pi_case : (2 : ℕ) ^ 10 = 1024 := by sorry`; proof `by native_decide` | `axioms` |
| `fake_success_exit` | `#eval IO.println "Finished."`, then `#exit`, then the valid proof | `statement_changed` |
| `add_false` | `SafeVerifyTest/AddFalse/Bad.lean` from the judge checkout, with `import Mathlib` in place of its import; target `theorem falseThm : False := by sorry` | not `proved` |
| `replace_axiom` | `SafeVerifyTest/ReplaceAxiom/Bad.lean`, same change; its `Target.lean` with `import Mathlib` added | not `proved` |
| `skip_kernel` (record only) | the valid proof under `set_option debug.skipKernelTC true in` (the judge replays it in the kernel either way) | record |
| `renamed_binders` (record only) | `theorem pi_case (x y : ℕ) (hxy : x ≤ y) : x + 0 ≤ y := by simpa using hxy` | record |
| `answer_wrapper` (record only) | both files `import MiniF2F.ProblemImports`; target `theorem pi_case (x : ℕ) (h : x = 2) : x = answer(2) := by sorry`; submission states `x = 2`, proved `h` | record |

- [ ] **Step 4: Run each case by hand and capture the output.** From `data/lean/miniF2F-f0a20e14c1ee`, with `W=../work/<case>` holding copies of the two files and `C=<repo>/tests/lean_cases/<case>`:

```sh
O="-D autoImplicit=false -D relaxedAutoImplicit=false"
lake env lean --json $O -o $W/Target.olean $W/Target.lean
lake env lean --json $O -o $W/Submission.olean $W/Submission.lean > $C/compile.stdout; echo $? > $C/compile.exit
lake env ../SafeVerify-b291b588a539/.lake/build/bin/safe_verify --save $W/judge.json \
  $W/Target.olean $W/Submission.olean 2> $C/judge.stderr; echo $? > $C/judge.exit
cp $W/judge.json $C/ 2>/dev/null
```

Skip the judge when the submission did not compile (`fake_success_exit` compiles; check). Keep paths relative as shown.

- [ ] **Step 5: Gate.** Compare each case with its expected column: `proved` means `judge.exit` is 0 and `judge.json` holds one outcome with a null `failureMode`. **If `add_false`, `replace_axiom`, or any case expected to fail is accepted, or the pipeline cannot be made to run, stop here and report to the owner.** If a failing case fails for a different reason than its row, record that and carry on: Task 5's rules must then be read against the captured output, and the row corrected in this plan. The two exploit cases are SafeVerify's own tests at this commit and should compile; if one does not, record it and drop it from Task 5's list.

- [ ] **Step 6: Write `tests/lean_cases/README.md`**: the exact commands that worked, `lake env lean --version`, the wall time and peak memory of the `valid` compile (`/usr/bin/time -l`), disk used by `data/lean/`, what `skip_kernel`, `renamed_binders` and `answer_wrapper` did, any deviation from Step 4's commands, and that `add_false` and `replace_axiom` are adapted from SafeVerify (Apache-2.0).

- [ ] **Step 7: Commit** `test: capture lean and safeverify output for the grader's cases`

### Task 2: Split a Lean file into theorems

**Files:**
- Create: `src/pi/lean_statements.py`, `tests/lean_fixture/Split.lean`, `tests/test_lean_statements.py`

**Interfaces:**
- Produces:

```python
class StatementError(Exception): ...

@dataclass(frozen=True)
class Theorem:
    id: str                    # the theorem's full name
    header: str                # first `import` line up to the first docstring or theorem; ends "\n"
    statement: str             # the declaration up to its last ":=", right-stripped
    informal: str | None       # the docstring's text
    shipped_proof: str | None  # what follows ":=" when it is not `by sorry`, whitespace-normalised
    subject: str               # family(id)
    level: None = None

def split_theorems(text: str) -> list[Theorem]
def family(name: str) -> str
```

- [ ] **Step 1: Write the fixture `tests/lean_fixture/Split.lean`**

```lean
/-
A fixture in the layout of a miniF2F split file. Original statements only.
-/
import Mathlib

open scoped Nat
open scoped Real

/--
Add zero. -/
theorem fixture_add_zero (a : ℕ) : a + 0 = a := by
  sorry

theorem fixture_no_docstring (a b : ℕ) (h : a ≤ b) :
    a ≤ b + 1 := by
  sorry

/-- A comment sits between this docstring and its theorem. -/
-- a note the parser skips
theorem amc12a_2099_p1 (x : ℝ) (h₀ : x = 2) : x ^ 2 = 4 := by
  sorry

/- theorem fixture_commented_out (a : ℕ) : a = a := by
  sorry -/

theorem mathd_algebra_9001 (a : ℕ) :
    letI P : ℕ → Prop := fun n => n = n
    P a := by
  sorry

open scoped Polynomial in
theorem fixture_poly.variants.Polynomial (f : ℝ[X]) : f = f := by
  sorry

theorem mathd_numbertheory_9002 : 194 % 11 = 7 :=
  rfl
```

- [ ] **Step 2: Write the failing tests**

```python
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
            "import Mathlib\n\ntheorem t : True := by\n  sorry\n\ntheorem t : True := by\n  sorry\n",
            "twice",
        ),
        ("theorem t : True := by\n  sorry\n", "import"),
    ],
)
def test_refuses_what_it_does_not_understand(bad, said):
    with pytest.raises(StatementError, match=said):
        split_theorems(bad)
```

- [ ] **Step 3: Run** `uv run pytest tests/test_lean_statements.py -q`. Expected: FAIL, `No module named 'pi.lean_statements'`.

- [ ] **Step 4: Implement.** Walk the lines once, tracking `/- … -/` block comments. Outside comments a column-0 line may only be `import`, `open` (a header line, or one ending ` in` directly above a theorem), `theorem`, or a `--` comment; anything else raises with its line number. A declaration runs from its `theorem` line (and an `open … in` line above it) to the next blank line. The docstring is the `/-- … -/` block that ends directly above it, `--` lines allowed between.

- [ ] **Step 5: Run the tests.** Expected: PASS.

- [ ] **Step 6: Commit** `feat: split a lean split file into theorems`

### Task 3: The Lean benchmark definition, its checkout and `pi lean-setup`

**Files:**
- Create: `src/pi/lean_project.py`, `benchmarks/minif2f-test.toml`, `tests/test_lean_project.py`
- Modify: `src/pi/benchmarks.py` (`load_benchmark`), `src/pi/cli.py`, `tests/test_benchmarks.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `split_theorems`, `Theorem` (Task 2); `BenchmarkError`.
- Produces:

```python
@dataclass(frozen=True)
class LeanBenchmark:
    name: str; repository: str; commit: str; file: str
    theorems: int                      # how many the file must yield
    shipped_proofs: tuple[str, ...]; lean_options: tuple[str, ...]; allowed_axioms: tuple[str, ...]
    judge_repository: str; judge_commit: str
    ids: tuple[str, ...] | None = None
    scored: bool = False
    kind: str = "lean"

def load_lean_benchmark(path: Path, data: dict) -> LeanBenchmark
def checkout_dir(data_dir: Path, repository: str, commit: str) -> Path  # data_dir/"lean"/f"{basename}-{commit[:12]}"
def ensure_checkout(data_dir: Path, repository: str, commit: str, run=subprocess.run) -> Path
def load_theorems(benchmark: LeanBenchmark, data_dir: Path) -> list[Theorem]
def lean_environment(benchmark: LeanBenchmark, data_dir: Path, run=subprocess.run) -> dict
def setup(benchmark: LeanBenchmark, data_dir: Path, report=print, run=subprocess.run) -> None
```

`lean_environment` returns `{"toolchain": str, "lean_version": str, "files": {"lean-toolchain": sha, "lake-manifest.json": sha, "lakefile.lean": sha, <benchmark.file>: sha}, "options": [...]}`.

- [ ] **Step 1: Write `benchmarks/minif2f-test.toml`**

```toml
# miniF2F's test split, as corrected by Google DeepMind: 244 theorems in Lean 4.27.
# The scored proof benchmark. The model is never run on it before a pre-registered run.
name = "minif2f-test"
kind = "lean"
repository = "https://github.com/google-deepmind/miniF2F"
commit = "f0a20e14c1eeccd859d51bb4c2b3ee487889c303"
file = "MiniF2F/Test.lean"
theorems = 244
# The file proves these two itself. pi strips the proofs; they stay in the 244.
shipped_proofs = ["mathd_numbertheory_66", "mathd_algebra_302"]
lean_options = ["autoImplicit=false", "relaxedAutoImplicit=false"]
allowed_axioms = ["propext", "Classical.choice", "Quot.sound"]
judge_repository = "https://github.com/GasStationManager/SafeVerify"
judge_commit = "b291b588a53999a7e837dda61c7dbfe8c550c814"
scored = true
```

- [ ] **Step 2: Write the failing tests.** `tests/test_lean_project.py` builds a local git repository in `tmp_path` holding `lean-toolchain`, `lake-manifest.json`, `lakefile.lean` and the fixture as `Split.lean`, and uses its path as `repository`.

```python
def test_a_definition_of_kind_lean_loads_as_a_lean_benchmark():      # via pi.benchmarks.load_benchmark
    assert isinstance(load_benchmark(REPO / "benchmarks/minif2f-test.toml"), LeanBenchmark)
def test_an_answer_definition_still_loads_as_before():                # math-500.toml -> Benchmark
def test_refuses_an_unknown_setting_and_a_short_commit():             # BenchmarkError, names the setting
def test_ensure_checkout_clones_at_the_commit_and_is_then_a_no_op()
def test_refuses_a_checkout_at_another_commit():                      # match="is at"
def test_refuses_a_checkout_with_changes():                           # match="has uncommitted changes"
def test_theorems_come_in_file_order_or_in_the_order_of_the_ids()
def test_refuses_a_file_with_the_wrong_number_of_theorems():          # match="expected 7 theorems, found 6"
def test_refuses_when_the_shipped_proofs_are_not_the_ones_named():    # match="mathd_numbertheory_9002"
def test_refuses_an_id_the_file_does_not_hold()
def test_the_environment_names_the_toolchain_and_each_file_s_checksum()
def test_an_environment_that_is_not_set_up_says_to_run_lean_setup():  # match="pi lean-setup"  (Review Focus 1)
def test_setup_runs_the_builds_in_order():
    # with a recording `run`: ["lake","exe","cache","get"], ["lake","build"] in the benchmark
    # checkout, then ["lake","build","safe_verify"] in the judge checkout
```

- [ ] **Step 3: Run** `uv run pytest tests/test_lean_project.py tests/test_benchmarks.py -q`. Expected: FAIL on the new tests.

- [ ] **Step 4: Implement.** `load_benchmark` reads the TOML and, when `kind == "lean"`, returns `load_lean_benchmark(path, data)` (import it inside the function). `lean_environment` raises `BenchmarkError` naming `pi lean-setup` when `lake` is missing, either checkout is missing, at another commit or dirty, or `.lake/build/bin/safe_verify` is absent; `lean_version` is the first line of `lake env lean --version` run in the checkout.

- [ ] **Step 5: Add `pi lean-setup --benchmark B [--data-dir data]`** to `cli.py`, calling `setup` and printing each step; test that it reports a `BenchmarkError` as `error: …` with exit 1.

- [ ] **Step 6: Run the tests.** Expected: PASS.

- [ ] **Step 7: Commit** `feat: add lean benchmarks pinned by commit and pi lean-setup`

### Task 4: Run Lean and the judge

**Files:**
- Modify: `src/pi/lean_project.py`, `tests/test_lean_project.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class Finished:
    exit_code: int | None   # None: killed at the limit
    stdout: str; stderr: str; seconds: float

def run_process(command: list[str], cwd: Path, limit: float) -> Finished

class LeanRunner:
    def __init__(self, benchmark: LeanBenchmark, data_dir: Path, run_process=run_process): ...
    def work_dir(self) -> ContextManager[Path]   # data_dir/lean/work/<random>/, removed on exit
    def compile(self, source: Path, olean: Path, limit: float) -> Finished
    def judge(self, reference: Path, submission: Path, saved: Path, limit: float) -> Finished
```

- [ ] **Step 1: Write the failing tests**

```python
def test_a_process_past_its_limit_is_killed_with_everything_it_started(tmp_path):   # Review Focus 2
    # a shell script that starts `sleep 60 &`, writes the child's pid to a file, then sleeps
    done = run_process(["sh", str(script)], tmp_path, limit=1)
    assert done.exit_code is None and 1 <= done.seconds < 5
    assert not _alive(int((tmp_path / "pid").read_text()))

def test_output_is_read_as_utf8_whatever_the_locale(tmp_path, monkeypatch):          # Review Focus 5
    monkeypatch.setenv("LC_ALL", "C")
    done = run_process([sys.executable, "-c", "import sys; sys.stdout.buffer.write('ℝ ∑'.encode())"], tmp_path, 10)
    assert done.stdout == "ℝ ∑"

def test_compile_runs_lean_in_the_checkout_with_the_options_and_relative_paths():
    # recording run_process; assert the command is exactly
    # ["lake","env","lean","--json","-D","autoImplicit=false","-D","relaxedAutoImplicit=false",
    #  "-o","../work/x/Submission.olean","../work/x/Submission.lean"] and cwd is the checkout

def test_judge_runs_safeverify_through_lake_env_with_relative_paths():
    # ["lake","env","../SafeVerify-b291b588a539/.lake/build/bin/safe_verify","--save",
    #  "../work/x/judge.json","../work/x/Reference.olean","../work/x/Submission.olean"]

def test_a_work_directory_is_removed_even_when_the_check_raises()
```

- [ ] **Step 2: Run them.** Expected: FAIL, `run_process` not defined.

- [ ] **Step 3: Implement.** `run_process` starts the command in a new session and, at the limit, sends `SIGKILL` to the process group; it decodes both streams as UTF-8 with `errors="replace"`. If Task 1's README records a different working command form, use that form here and in the two command tests.

- [ ] **Step 4: Run the tests.** Expected: PASS.

- [ ] **Step 5: Commit** `feat: run lean and safeverify in fresh processes under a limit`

### Task 5: Lean rules: extraction, assembly, flags and the judge's outcome

**Files:**
- Create: `src/pi/lean_grading.py`, `tests/test_lean_grading.py`

**Interfaces:**
- Consumes: `Theorem`, `Finished`; the captured files of Task 1.
- Produces:

```python
LEAN_RULES_VERSION = 1
MESSAGE_CAP = 20_000

def extract_code(reply: str) -> str | None
def assemble(theorem: Theorem, code: str) -> str          # the submission file
def reference_source(theorem: Theorem) -> str             # header + "\n" + statement + " := by\n  sorry\n"
def flags(code: str) -> list[str]                         # of: #eval run_cmd elab macro syntax initialize IO.
def judgement(done: Finished, saved: list | None, allowed: Sequence[str]) -> tuple[str | None, list[str]]
    # (None when it passes, else the reason; the submission theorem's axioms)
```

- [ ] **Step 1: Write the failing tests**

```python
T = Theorem("fixture_add_zero", "import Mathlib\n", "theorem fixture_add_zero (a : ℕ) : a + 0 = a",
            None, None, "other")
FULL = "theorem fixture_add_zero (a : ℕ) : a + 0 = a := by\n  simp"

def fenced(code, tag="lean4"): return f"Here it is.\n```{tag}\n{code}\n```\n"

def test_takes_the_last_lean_block():
    assert extract_code(fenced("first") + fenced(FULL, "lean")) == FULL
def test_takes_an_untagged_block():
    assert extract_code(fenced(FULL, "")) == FULL
def test_skips_a_later_block_in_another_language():                    # Review Focus 3
    assert extract_code(fenced(FULL) + fenced("print(1)", "python") + fenced("Done.", "text")) == FULL
@pytest.mark.parametrize("reply", ["No code.", "```lean4\n" + FULL, fenced("   \n")])
def test_no_closed_block_with_code_in_it_is_no_proof(reply):           # Review Focus 3
    assert extract_code(reply) is None

def test_a_block_that_declares_the_theorem_follows_the_header():
    assert assemble(T, FULL) == "import Mathlib\n\n" + FULL + "\n"
def test_leading_imports_are_dropped_and_nothing_else():
    code = "import Mathlib\nimport Aesop\n\nopen Real\n\n" + FULL
    assert assemble(T, code) == "import Mathlib\n\nopen Real\n\n" + FULL + "\n"
def test_a_lemma_of_the_same_name_counts_as_declaring_it():
    assert assemble(T, FULL.replace("theorem", "lemma", 1)).count("fixture_add_zero") == 1
@pytest.mark.parametrize("body", ["simp", "by\n  simp", ":= by\n  simp", "  simp"])
def test_a_proof_only_block_is_placed_under_the_original_statement(body):
    assert assemble(T, body) == "import Mathlib\n\n" + T.statement + " := by\n  simp\n"
def test_a_theorem_with_a_longer_name_is_not_taken_for_it():
    assert assemble(T, FULL.replace("fixture_add_zero", "fixture_add_zero'")).startswith(
        "import Mathlib\n\n" + T.statement + " := by\n")

def test_flags_compile_time_commands_and_not_words_that_contain_them():
    assert flags('#eval IO.println "x"\nrun_cmd pure ()') == ["#eval", "run_cmd", "IO."]
    assert flags("-- elaborate the macroscopic syntaxes\nsimp") == []

EXPECTED = {"valid": None, "sorry": "sorry", "helper_sorry": "sorry", "helper_axiom": "axioms",
            "unused_sorry": "sorry", "weakened": "statement_changed", "renamed": "statement_changed",
            "reformatted": None, "native_decide": "axioms", "fake_success_exit": "statement_changed"}
@pytest.mark.parametrize("case, reason", EXPECTED.items())
def test_reads_each_captured_judgement(case, reason):
    assert judgement(*captured(case), ALLOWED)[0] == reason
@pytest.mark.parametrize("case", ["add_false", "replace_axiom"])
def test_an_exploit_is_never_a_pass(case):
    assert judgement(*captured(case), ALLOWED)[0] is not None

def test_a_judge_killed_at_its_limit_is_a_timeout():       # exit_code None -> "check_timed_out"
def test_success_without_a_saved_outcome_is_a_judge_error()  # exit 0, saved None
def test_printed_success_with_a_failing_exit_is_a_judge_error():
    assert judgement(Finished(1, "Finished.\n", "", 1.0), PASSING_OUTCOME, ALLOWED)[0] == "judge_error"
def test_an_axiom_outside_the_allowlist_fails_even_if_the_judge_passed_it():
    # exit 0, failureMode None, solutionInfo.axioms == ["propext", "Lean.ofReduceBool"] -> "axioms"
```

`captured(case)` builds a `Finished` from the case's `judge.exit` and `judge.stderr` and loads `judge.json` if present.

- [ ] **Step 2: Run them.** Expected: FAIL, `No module named 'pi.lean_grading'`.

- [ ] **Step 3: Implement.** A block declares the theorem when it has a line matching `^(theorem|lemma)\s+<name>(?![\w.'!?])`. `judgement` applies these rules in order; `saved` is SafeVerify's JSON, a list of `{targetInfo, solutionInfo, failureMode}`:

1. `exit_code is None` → `check_timed_out`.
2. stderr contains `kernel verification failed` → `kernel_rejected`.
3. any `failureMode` of `thmType`, `notFound` or a `kind` object → `statement_changed`.
4. a `failureMode` of `axioms`, or stderr containing `used disallowed axioms` → `sorry` if `sorryAx` is among the axioms named, else `axioms`.
5. exit 0, exactly one outcome, null `failureMode`, a `solutionInfo` whose axioms are all allowed → pass; a disallowed axiom there → `axioms`.
6. anything else → `judge_error`.

- [ ] **Step 4: Run the tests.** Expected: PASS.

- [ ] **Step 5: Commit** `feat: add lean grading rules version 1`

### Task 6: Check one reply end to end, and `pi lean-check`

**Files:**
- Modify: `src/pi/lean_grading.py`, `src/pi/cli.py`, `tests/test_lean_grading.py`, `tests/test_cli.py`
- Create: `tests/test_lean_real.py`, `tests/lean_fake.py`

**Interfaces:**
- Consumes: `LeanRunner` (Task 4), Task 5's functions.
- Produces:

```python
@dataclass(frozen=True)
class Limits:
    compile_seconds: float; judge_seconds: float

@dataclass(frozen=True)
class LeanGrade:
    verdict: str             # "proved", "failed" or "missing"
    proof: str | None        # the extracted block
    submission: str | None   # the file as checked
    lean: dict | None        # the record's `lean` field

def check(theorem: Theorem, reply: str, runner, limits: Limits, allowed: Sequence[str]) -> LeanGrade
def lean_grader_version(benchmark: LeanBenchmark) -> dict
    # {"lean_rules": 1, "judge_repository": ..., "judge_commit": ..., "allowed_axioms": [...]}
```

`lean` is `{"reason", "exit_code", "messages", "judge": {"exit_code", "outcome", "stderr"} | None, "axioms", "flags", "compile_seconds", "judge_seconds"}`; `None` when the verdict is `missing`.

`tests/lean_fake.py` provides `FakeRunner(compiles=..., judges=...)`: same methods as `LeanRunner`, writes the `.olean` files it is asked for, returns the queued `Finished` values and records its calls.

- [ ] **Step 1: Write the failing tests** (`FakeRunner`; `LIMITS = Limits(300, 300)`)

```python
def test_a_reply_without_code_is_missing_and_runs_nothing()
def test_a_proof_the_judge_passes_is_proved_with_its_axioms_flags_and_times()
def test_a_compile_error_fails_without_asking_the_judge():        # exit 1 -> lean_error, judge calls == []
def test_an_error_message_fails_even_when_lean_exits_zero():       # stdout line {"severity":"error",...}
def test_a_compile_killed_at_its_limit_is_a_timeout():             # reason check_timed_out
def test_a_reference_that_does_not_compile_is_a_judge_error()
def test_a_reference_that_changed_before_the_judge_ran_is_a_judge_error():
    # the fake's submission compile rewrites Reference.olean
def test_saved_output_is_capped():                                  # Review Focus 4
    grade = check(T, fenced(FULL), FakeRunner(compiles=[OK, Finished(1, "x" * 50_000, "", 2.0)]), LIMITS, ALLOWED)
    assert len(grade.lean["messages"]) == MESSAGE_CAP
def test_the_submission_is_what_assemble_built()
```

- [ ] **Step 2: Run them.** Expected: FAIL, `check` not defined.

- [ ] **Step 3: Implement `check`.** Inside `runner.work_dir()`: write and compile `Reference.lean`; hash `Reference.olean`; write and compile `Submission.lean`; fail on a non-zero exit or any stdout JSON line whose `severity` is `error`; hash the reference again and compare; run the judge; apply `judgement`. Cap `messages` and the judge's `stderr` at `MESSAGE_CAP`. Files are written as UTF-8.

- [ ] **Step 4: Write `tests/test_lean_real.py`**, skipped unless `PI_LEAN_TESTS=1`. It uses a real `LeanRunner` on `data/` and `benchmarks/minif2f-test.toml` (for the pins only). For each case of Task 1 with an expected column it builds the theorem with `split_theorems(Target.lean)`, passes `Submission.lean` as a fenced reply, and asserts the verdict and reason. Three more with the default target: a proof-only reply `simpa using h` is `proved`; a reply repeating `import Mathlib` twice is `proved`; `Limits(5, 5)` gives `check_timed_out`.

- [ ] **Step 5: Add `pi lean-check --config C --benchmark B --id ID --reply FILE`**: grades one saved reply against one theorem and prints the verdict, reason and axioms.

- [ ] **Step 6: Run** `uv run pytest -q`, then `PI_LEAN_TESTS=1 uv run pytest tests/test_lean_real.py -q`. Expected: PASS both.

- [ ] **Step 7: Commit** `feat: check a reply with lean and safeverify, and add pi lean-check`

### Task 7: The `[lean]` configuration section

**Files:**
- Modify: `src/pi/config.py`, `tests/test_config.py`
- Create: `configs/qwen3-14b-lean.toml`

**Interfaces:**
- Produces: `LeanSettings(instruction: str, compile_time_limit_seconds: float, judge_time_limit_seconds: float)`; `Config.lean: LeanSettings | None = None`.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_configuration_without_a_lean_section_has_none():      # configs/qwen3-14b.toml -> config.lean is None
def test_a_lean_section_must_state_every_setting():              # match="missing setting lean.instruction"
def test_refuses_an_unknown_lean_setting()
def test_the_lean_configuration_differs_from_the_baseline_only_in_its_lean_section():
    lean, base = load_config("configs/qwen3-14b-lean.toml"), load_config("configs/qwen3-14b.toml")
    assert (lean.model, lean.runtime, lean.generation) == (base.model, base.runtime, base.generation)
    assert (lean.lean.compile_time_limit_seconds, lean.lean.judge_time_limit_seconds) == (300, 300)
```

- [ ] **Step 2: Run them.** Expected: FAIL.

- [ ] **Step 3: Implement,** and write `configs/qwen3-14b-lean.toml`: the four sections of `configs/qwen3-14b.toml` unchanged, a header comment saying the limits and the instruction are provisional until the development run, and

```toml
[lean]
instruction = "Complete the following Lean 4 theorem. It is checked with Lean 4 and Mathlib. Reply with the complete theorem, its statement unchanged and its proof in full, in a single Lean 4 code block. You may state and prove helper lemmas before it. Do not use `sorry`."
compile_time_limit_seconds = 300
judge_time_limit_seconds = 300
```

- [ ] **Step 4: Run the tests.** Expected: PASS.

- [ ] **Step 5: Commit** `feat: add the optional lean section of a run configuration`

### Task 8: A task seam in the run loop

**Files:**
- Modify: `src/pi/evaluation.py`, `tests/test_evaluation.py` (new tests only)

**Interfaces:**
- Produces: `run_evaluation(..., task=None)`, and

```python
class AnswerTask:
    solved = "correct"
    blank: dict = {}                                        # extra fields of an ungraded result
    def identity(self, benchmark, problems) -> dict         # {"benchmark": {...as today...}, "grader": grader_version()}
    def check(self, problems) -> None                       # today's _check_references
    def prompt(self, problem) -> str                        # problem.problem
    def grade(self, problem, content: str) -> dict          # {"verdict": ..., "answer": ...}
```

A result is today's dictionary, with `verdict` and `answer` from the task and any other keys the task returns appended after `metrics`. Sessions must agree on `runtime`, `model`, `generation` and every key of `task.identity(...)`.

- [ ] **Step 1: Write the failing tests**

```python
class Shouting(AnswerTask):
    blank = {"extra": None}
    def identity(self, benchmark, problems): return {**super().identity(benchmark, problems), "loud": True}
    def prompt(self, problem): return problem.problem.upper()
    def grade(self, problem, content): return {"verdict": "correct", "answer": None, "extra": len(content)}

def test_a_task_writes_the_prompt_and_adds_its_fields_after_the_rest(ollama, tmp_path):
    # chats(ollama)[0][0]["content"] == ONE.problem.upper(); list(result)[-1] == "extra"
def test_an_ungraded_result_carries_the_task_s_blank_fields():   # a cut-off reply -> result["extra"] is None
def test_a_run_records_and_compares_every_identity_key_of_its_task():
    # run.json has "loud": True; resuming with a task whose identity says False raises EvaluationError
```

- [ ] **Step 2: Run** `uv run pytest tests/test_evaluation.py -q`. Expected: the three new tests FAIL; the others pass.

- [ ] **Step 3: Implement.** Move the benchmark dictionary, `grader_version()`, `_check_references` and the `grade` call into `AnswerTask`; `_attempt` takes the task.

- [ ] **Step 4: Run** `uv run pytest -q`. Expected: PASS, with no change to any existing test.

- [ ] **Step 5: Commit** `refactor: give the run loop a task that prompts and grades`

### Task 9: Lean runs through `pi eval`

**Files:**
- Create: `src/pi/lean_evaluation.py`, `tests/test_lean_evaluation.py`
- Modify: `src/pi/cli.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `check`, `Limits`, `lean_grader_version`, `LeanRunner`, `lean_environment`, `load_theorems`, `LeanSettings`, the task seam.
- Produces:

```python
def lean_prompt(instruction: str, theorem: Theorem) -> str
    # f"{instruction}\n\n```lean4\n{theorem.header}\n{theorem.statement} := by\n```\n"

class LeanTask:
    solved = "proved"
    blank = {"proof": None, "lean": None}
    def __init__(self, benchmark: LeanBenchmark, settings: LeanSettings, runner, environment: dict, out: Path): ...
    # identity(): "benchmark" {name, kind, repository, commit, file, sha256, subset, scored, ids},
    #             "grader" lean_grader_version(benchmark),
    #             "lean" {**environment, instruction, compile_time_limit_seconds, judge_time_limit_seconds}
    # grade(): {"verdict", "answer": None, "proof", "lean"}; writes out/proofs/<id>.lean when proved
```

- [ ] **Step 1: Write the failing tests** (Ollama stub answering with fenced proofs; `FakeRunner`)

```python
def test_a_theorem_is_sent_as_the_instruction_and_its_statement(ollama, tmp_path):
    assert chats(ollama)[0][0]["content"] == (
        "Prove it.\n\n```lean4\nimport Mathlib\n\ntheorem fixture_add_zero (a : ℕ) : a + 0 = a := by\n```\n")
def test_results_record_the_verdict_the_proof_and_what_lean_said():
    # verdicts ["proved", "failed", "missing"]; answer None; r["lean"] in turn a record with
    # reason None, a record with reason "lean_error", and None
def test_an_accepted_proof_is_saved_as_a_file_and_no_other_is(tmp_path):
    assert [p.name for p in (out / "proofs").iterdir()] == ["fixture_add_zero.lean"]
    assert (out / "proofs/fixture_add_zero.lean").read_text(encoding="utf-8") == grade.submission   # Review Focus 5
def test_a_cut_off_reply_has_no_proof_and_no_lean_record()
def test_the_run_names_its_lean_environment_rules_and_limits():   # run["benchmark"]["kind"] == "lean"; run["grader"]["lean_rules"] == 1
def test_refuses_to_resume_under_a_different_instruction_or_toolchain():   # EvaluationError
def test_an_attempt_the_machine_slept_through_is_checked_again():  # read_wake changes once -> two chats, one result
```

and in `tests/test_cli.py`:

```python
def test_eval_of_a_lean_benchmark_needs_a_lean_section(...):         # error names "[lean]"; nothing written
def test_eval_stops_before_any_attempt_when_lean_is_not_set_up(...): # Review Focus 1: error names "pi lean-setup";
                                                                     # no run.json; the stub saw no /api/chat
```

- [ ] **Step 2: Run them.** Expected: FAIL.

- [ ] **Step 3: Implement.** In `cli._eval`, when the definition is a `LeanBenchmark`: require `config.lean`, call `lean_environment` (before anything is written), `load_theorems`, build the runner and the task, and call `run_evaluation(..., problem_file=f"{repository}@{commit}", task=task)`. Print `lean project <checkout> at <commit[:12]>` in place of the problem-file line.

- [ ] **Step 4: Run** `uv run pytest -q`. Expected: PASS.

- [ ] **Step 5: Commit** `feat: run lean benchmarks through pi eval`

### Task 10: The report of a Lean run

**Files:**
- Create: `src/pi/lean_report.py`, `tests/test_lean_report.py`
- Modify: `src/pi/report.py` (`build_report` dispatches when `run["benchmark"].get("kind") == "lean"`)

**Interfaces:**
- Produces: `build_lean_report(run: dict, results: list[dict]) -> str`. It reuses `report._table`, `_cost`, `_duration` and `_code`.

- [ ] **Step 1: Write the failing tests** against a saved three-theorem run (one proved and flagged, one `failed`/`lean_error` whose compile took 250 s of 300, one `cut_off`)

```python
def test_the_title_counts_proved_theorems():
    assert report.splitlines()[0] == "# minif2f-dev: 1 of 3 proved (33.3%)"
def test_says_what_counts_and_tables_every_verdict_and_reason():
    assert "Only `proved` counts as solved." in report
    assert "| lean_error | 1 |" in report and "| cut_off | 1 |" in report
def test_names_the_lean_project_the_judge_and_the_limits():
    assert "`f0a20e14c1ee`" in report and "SafeVerify `b291b588a539`" in report and "300 s per check step" in report
def test_counts_checks_that_came_within_a_fifth_of_a_limit():
    assert "| Checks within 20% of a limit | 1 |" in report
def test_breaks_the_score_down_by_family():           # "## By family"
def test_lists_accepted_proofs_that_run_code_at_compile_time():
    assert "| fixture_add_zero | `#eval` |" in report   # and "None." when there are none
def test_the_unsolved_table_gives_the_reason()
def test_an_answer_run_s_report_is_unchanged()         # tests/test_report.py still passes
```

- [ ] **Step 2: Run them.** Expected: FAIL.

- [ ] **Step 3: Implement,** sections in this order: title; subset or "All N theorems"; identity table (Checkpoint, Runtime, Problems, Lean, Grader, Settings, Code, Sessions); Verdicts; Failure reasons; Cost (today's rows, then compile and judge time: mean, median, longest; then the within-20% count); By family; Flagged proofs; Unsolved.

- [ ] **Step 4: Run the tests.** Expected: PASS.

- [ ] **Step 5: Commit** `feat: report lean runs`

### Task 11: The audit of a Lean run

**Files:**
- Create: `src/pi/lean_audit.py`, `tests/test_lean_audit.py`
- Modify: `src/pi/audit.py` (`audit_run` dispatches on `LeanBenchmark`), `src/pi/cli.py`

**Interfaces:**
- Produces: `audit_lean_run(out: Path, benchmark: LeanBenchmark, data_dir: Path, runner=None) -> dict`, in the shape `audit_run` returns. `files` holds `run.json`, `results.jsonl`, `report.md` and every `proofs/<id>.lean`.

Checks, by name: `complete`; `benchmark` (repository, commit, file, ids); `lean environment` (today's `lean_environment` equals the run's); `one result per problem`; `grader`; `verdicts`; `proof files`; `sessions`; `scored standard` (scored runs); `report`.

`verdicts` rules: the saved `proof` must be what `extract_code` gives for the saved reply. `missing`, `cut_off` and `timed_out` follow from the response as today. A `proved` result is checked again with `Limits` of four times the run's and must be `proved`. A `failed` result is checked again at the run's limits and must fail for the same reason, except `check_timed_out`, which is not run again: its recorded compile or judge time must be at least that step's limit.

- [ ] **Step 1: Write the failing tests** (`FakeRunner`)

```python
def test_a_sound_run_passes_every_check()
def test_a_proved_result_is_checked_again_at_four_times_the_limits():   # the runner saw limit == 1200
def test_a_proof_that_no_longer_checks_fails_the_verdicts_check()
def test_a_failure_must_fail_again_for_the_same_reason()
def test_a_timed_out_check_is_not_run_again_but_its_time_must_reach_the_limit():
    # recorded compile_seconds 300.2 -> passes, runner calls == []; 12.0 -> fails
def test_an_altered_proof_field_fails_the_verdicts_check()
def test_a_missing_altered_or_extra_proof_file_fails_the_proof_files_check()
def test_a_different_lean_environment_fails_its_check()
def test_the_audit_fingerprints_the_proof_files()        # "proofs/fixture_add_zero.lean" in audit["files"]
def test_audit_without_lean_set_up_says_so(...):         # Review Focus 1: cli prints "cannot audit … pi lean-setup", exit 1
```

- [ ] **Step 2: Run them.** Expected: FAIL.

- [ ] **Step 3: Implement,** reusing `audit._scored_problems` and `audit.fingerprint`.

- [ ] **Step 4: Run** `uv run pytest -q`. Expected: PASS.

- [ ] **Step 5: Commit** `feat: audit lean runs by checking every proof again`

### Task 12: Publish the proof files, and keep them out of git

**Files:**
- Modify: `src/pi/publish.py`, `tests/test_publish.py`, `.gitignore`

**Interfaces:**
- Produces: `publish_run` uploads every file the audit fingerprinted, then `audit.json`, then the manifest.

- [ ] **Step 1: Write the failing tests**

```python
def test_publishes_every_file_the_audit_names(aws, ...):
    assert "proofs/fixture_add_zero.lean" in outcome and "proofs/fixture_add_zero.lean" in manifest["files"]
def test_refuses_when_a_proof_file_changed_since_the_audit()
def test_an_answer_run_publishes_the_same_four_files_as_before()
```

- [ ] **Step 2: Run them.** Expected: the first two FAIL.

- [ ] **Step 3: Implement,** and add to `.gitignore`:

```gitignore
# Accepted proofs restate benchmark theorems verbatim: published to the bucket, never committed
experiments/*/proofs/
```

- [ ] **Step 4: Run** `uv run pytest -q`. Expected: PASS.

- [ ] **Step 5: Commit** `feat: publish the proof files of a lean run`

### Task 13: Documentation, and the Stage 1 pull request

**Files:**
- Create: `docs/lean-grading.md`
- Modify: `docs/records.md`, `README.md`, `AGENTS.md`

- [ ] **Step 1: Write `docs/lean-grading.md`** as Lean rules version 1, in the manner of `docs/grading.md`: what is graded; finding the code (a table of replies and what is taken, as Task 5's tests); the four assembly rules; the two steps; the verdicts and each reason with one example; the allowlist; the limits; the known limit and the flags; what the judge did with `unused_sorry`, `skip_kernel`, `renamed_binders` and `answer_wrapper` in Task 1.

- [ ] **Step 2: Update the rest.** `docs/records.md`: the `proof` and `lean` fields, the `lean` entry of `run.json`, the `proofs/` directory, and the Lean verdicts. `README.md`: a "Lean benchmarks" section after "After a run: audit, then publish" (install elan, `pi lean-setup`, `pi eval` with the Lean configuration, `pi lean-check`, `PI_LEAN_TESTS=1`), the new files in "Layout", and "Status". `AGENTS.md`: the model is never run on `benchmarks/minif2f-test.toml` outside a pre-registered run; debug the Lean grader on `tests/lean_cases/` and validation theorems; run `PI_LEAN_TESTS=1 uv run pytest tests/test_lean_real.py` before a pull request that touches the grader; proof files are never committed.

- [ ] **Step 3: Verify the whole stage**

Run: `scripts/check.sh`, then `PI_LEAN_TESTS=1 uv run pytest tests/test_lean_real.py -q`, then `uv run pi lean-setup --benchmark benchmarks/minif2f-test.toml`.
Expected: all checks pass; the Lean tests pass; setup reports both checkouts ready and `244 theorems`.

- [ ] **Step 4: Commit** `docs: state the lean grading rules and the lean run records`, then open the pull request with `gh pr create --template feat.md`, title `feat: grade lean proofs and run lean benchmarks`. Its "How it was verified" section quotes the three commands of Step 3 and Task 1's gate table.

---

# Stage 2: the development run (one pull request)

### Task 14: Freeze the development sample

**Files:**
- Create: `scripts/select_lean_dev_problems.py`, `benchmarks/minif2f-dev.toml`

- [ ] **Step 1: Write the script,** after `scripts/select_dev_problems.py`. `SEED = 20261127`. Candidates are the theorems of `MiniF2F/Valid.lean` at the pinned commit whose names hold no `.` (the 12 `.variants.` restatements are left out). From the sorted ids of each family it samples, in this order:

```python
# 30 theorems in the proportions of the test split's families (70, 60, 45, 15, 20, 18, 8, 8 of 244).
PER_FAMILY = {
    "mathd_algebra": 9,
    "mathd_numbertheory": 7,
    "amc12": 6,
    "aime": 2,
    "imo": 2,
    "algebra": 2,
    "numbertheory": 1,
    "induction": 1,
}
```

It prints the `ids` list, and on a comment line how many of the 30 use `answer(…)`.

- [ ] **Step 2: Write `benchmarks/minif2f-dev.toml`**: as `minif2f-test.toml` with `name = "minif2f-dev"`, `file = "MiniF2F/Valid.lean"`, `theorems = 256`, `shipped_proofs = []`, no `scored`, the printed `ids`, and a header comment saying what it is for and how the ids were chosen.

- [ ] **Step 3: Verify.** Run the script twice: the output is identical. Run `uv run pi lean-setup --benchmark benchmarks/minif2f-dev.toml`: it reports `30 of 256 theorems`. If the sample holds no plain theorem or no `answer(…)` theorem, stop and tell the owner rather than changing the seed.

- [ ] **Step 4: Commit** `feat: freeze thirty validation theorems as the lean development sample`

### Task 15: Development run, and what it fixes

**Files:**
- Create: `experiments/<date>-minif2f-dev/` (`run.json`, `results.jsonl`, `report.md`)
- Modify: `experiments/README.md`, and if the run calls for it `configs/qwen3-14b-lean.toml`, `src/pi/lean_grading.py`, `docs/lean-grading.md`

- [ ] **Step 1: Ask the owner before starting.** The run holds the Mac for about two hours, on mains.

- [ ] **Step 2: Run**

```sh
caffeinate -i uv run pi eval --config configs/qwen3-14b-lean.toml \
  --benchmark benchmarks/minif2f-dev.toml --out experiments/<date>-minif2f-dev
```

Expected: 30 results, and a first line `minif2f-dev: N of 30 proved`.

- [ ] **Step 3: Read every failure and tabulate:** verdicts and reasons; for each `lean_error`, whether the first error is packaging (imports, a restated statement that does not parse, Lean 3 syntax, a missing block) or mathematics; the proof rate for `answer(…)` and plain theorems apart; output tokens against the limit; compile and judge times against theirs; flags.

- [ ] **Step 4: Decide, by these rules.**
  - A third or more of the failures are packaging: change the instruction or add an assembly rule (with its test, on a validation reply), and run again in a new directory. At most three development runs; after the third, take what is left to the owner.
  - More than 3 of 30 replies are `cut_off`: propose a higher output limit to the owner with its cost in hours, as the MATH-500 development run did.
  - Any check within 20% of its limit: raise that limit to 600 s and re-check those replies with `pi lean-check`.
  - After packaging is fixed, 0 or 1 of 30 proved, or 27 or more: stop and take it to the owner before any pre-registration. This is the "too hard or too easy" question the owner raised.

- [ ] **Step 5: Write the log entry** in `experiments/README.md`, after the manner of "2026-11-20: development run, 28 of 30 correct": question, answer, that it is not a miniF2F score and why, setup and command, the result table, the failure table of Step 3, what was changed between runs, and what it fixes for the scored run (instruction, rules, the three limits, expected hours).

- [ ] **Step 6: Verify and open the pull request.** `scripts/check.sh` passes; `git status` shows no file under `proofs/`. Commit `docs(experiments): record the lean development run`, plus one commit per rule or configuration change; open with `gh pr create --template docs.md` (or `feat.md` if a rule changed).

---

# Stage 3: the pre-registration (one pull request)

### Task 16: Pre-register the scored run

**Files:**
- Modify: `experiments/README.md`

- [ ] **Step 1: Choose the five reproduction theorems in advance:** `random.Random(<seed>).sample(sorted(ids), 5)` over the 244 test ids, with the seed the entry's date as `YYYYMMDD`. This reads theorem names only.

- [ ] **Step 2: Write the entry** `## <date>: miniF2F proof baseline, pre-registered`, in the form of the MATH-500 one: status line; the question; a "Fixed in advance" table (theorems: all 244 of `benchmarks/minif2f-test.toml`, its commit, and the two shipped proofs by name; score: `proved` over 244; checkpoint; settings and the three limits from `configs/qwen3-14b-lean.toml`; the instruction, quoted in full; grader: Lean rules version 1, SafeVerify commit, allowlist; what counts as unsolved); how it is run (clean checkout, mains, lid open, the `caffeinate -i uv run pi eval … --out runs/<date>-minif2f-test` command); after the run (audit, reproduce the five named theorems, the owner publishes, commit the four record files and not `proofs/`); expected cost in hours from the development run; what would be surprising.

- [ ] **Step 3: Verify and open the pull request.** `scripts/check.sh` passes; `uv run pi lean-setup --benchmark benchmarks/minif2f-test.toml` reports 244 theorems and a clean checkout. Commit `docs(experiments): pre-register the minif2f proof baseline`; open with `gh pr create --template docs.md`. **The owner's merge freezes the prompt, the rules and the limits.** The scored run is the owner's to launch and is not part of this plan.
