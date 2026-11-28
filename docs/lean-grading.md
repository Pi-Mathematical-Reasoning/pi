# Lean grading rules

How Pi decides whether a reply proved a Lean theorem. These are **Lean rules
version 1**, implemented in
[`src/pi/lean_grading.py`](../src/pi/lean_grading.py) and numbered by
`LEAN_RULES_VERSION` there. They are frozen before a scored run: after that, a
change here is a new rules version, and scores under different versions are
not compared. The answer rules for MATH-style benchmarks are a separate
document, [grading.md](grading.md).

A proof passes only when the judge positively confirms it. Anything
unexpected, missing or unreadable is a failure with a reason.

## What is graded

Only the visible text of the reply. The model's reasoning is never graded, so
a proof that appears there and not in the reply does not count.

## Finding the code

The code is the content of the **last closed code block** in the reply whose
tag is `lean` or `lean4` (in any letter case) or empty, and that holds
something other than blank lines. The tag is the whole of what follows the
opening backticks, with spaces at either end ignored, so it must be exactly
one of those: a block tagged `python`, or `lean title=x`, is skipped. A line
that starts with three backticks, after any spaces, opens a block, or closes
the open one whatever follows the backticks, so a fence that is never closed
holds no code. A reply with no such block is `missing`.

| Reply | Code taken |
| --- | --- |
| A `lean4` block, then a `lean` block | The `lean` block, the last |
| An untagged block | That block |
| A `lean4` block, then a `python` block and a `text` block | The `lean4` block; the others are skipped |
| A `Lean4` block | That block: the tag's letter case does not matter |
| A block tagged `lean title=x` | None from it: the tag is not exactly `lean` |
| A `lean4` fence opened and never closed | None: `missing` |
| A `lean4` block holding only spaces | None: `missing` |
| No code block at all | None: `missing` |

## Building the file

The code is turned into one Lean file, the submission, by four rules:

1. **The benchmark's header comes first**: the `import` and `open` lines at
   the top of the benchmark file, then a blank line.
2. **The block is tidied, and only so far.** Lines holding only whitespace
   at its start and end are removed. The lines at its start that begin with
   `import ` (after any spaces), and the blank lines among and after them,
   are dropped, since the header supplies the imports; every later line, an
   `open` line included, is kept. The block is then dedented as a whole: the
   leading whitespace that all its non-blank lines share is removed, and a
   line holding only whitespace becomes empty. Nothing else in a line is
   changed here; rule 4 changes the first line of a proof body.
3. **A block that declares the theorem under its original name is used as it
   stands**, after the header: the tidied block, then a newline. It declares
   the theorem when some line of the tidied block begins, with nothing before
   it, with `theorem` or `lemma`, then whitespace, then the theorem's exact
   name, followed by none of a letter, digit, `_`, `.`, `'`, `!` or `?`.
   Helper lemmas and any other commands in the block stay where they are. A
   declaration with anything before the keyword does not count, so
   `@[simp] theorem …`, `private theorem …`, or a theorem indented inside a
   `namespace`, makes the block a proof body.
4. **Any other block is a proof body**, built from the tidied block in these
   steps:
   1. All leading whitespace is removed from its first line.
   2. If that line then starts with `:=`, the `:=` and the whitespace after
      it are removed.
   3. If it then starts with the word `by`, the `by` and the whitespace after
      it are removed. (`by_cases` is not the word `by`.)
   4. If nothing is left of the first line, it is dropped.
   5. The lines, the first one if kept and all the others, are dedented
      together, as in rule 2.
   6. Every non-blank line is indented by two spaces; empty lines stay empty.
   7. The file is the header, a blank line, the original statement followed
      by ` := by`, then those lines (none, if nothing is left of the block),
      each ending in a newline.

   So the lines after the first keep their indentation relative to each
   other. When the first line keeps code, they also keep their indentation
   relative to the block's left edge, and the first line's own indentation
   is lost; when it is dropped, they are dedented together.

The examples use the statement
`theorem fixture_add_zero (a : ℕ) : a + 0 = a`, an original theorem from
`tests/lean_fixture/Split.lean`. That file's header also has two
`open scoped` lines; the examples use a shorter header, `import Mathlib`
alone, as the unit tests do.

| Block | Taken as | Lines after the header |
| --- | --- | --- |
| `simp` | Proof body | The statement with ` := by`, then `  simp` |
| `by` on one line, `  simp` on the next | Proof body | The same |
| `:= by` on one line, `  simp` on the next | Proof body | The same |
| `by simp` | Proof body | The same |
| `intro x`, then `  simp` | Proof body | The statement with ` := by`, then `  intro x` and `    simp`: relative indentation kept |
| `  intro x`, then `simp` | Proof body | The statement with ` := by`, then `  intro x` and `  simp`: the first line's own indentation is lost |
| `by simp [foo]`, then `  <;> omega` | Proof body | `  simp [foo]`, then `    <;> omega` under the statement |
| `:= by` alone | Proof body | The statement with ` := by`, and nothing under it |
| The whole theorem, `theorem fixture_add_zero (a : ℕ) : a + 0 = a := by` and `  simp` | The theorem | The block as it stands |
| The whole theorem, every line indented by two spaces | The theorem | The block, dedented |
| `import Mathlib`, `import Aesop`, `open Nat`, then the whole theorem | The theorem | `open Nat`, then the theorem: the imports are dropped |
| A helper `lemma fixture_helper …`, then `lemma fixture_add_zero …` using it | The theorem | Both lemmas, as they stand |
| `@[simp] theorem fixture_add_zero (a : ℕ) : a + 0 = a := by`, then `  simp` | Proof body | The whole block, indented under the original statement: the declaration does not begin its line |
| `theorem fixture_add_zero' …`, the theorem under another name | Proof body | The whole block, indented under the original statement |

The last row is worth knowing: a reply that proves the theorem under another
name is treated as a proof body, so Lean rejects the file and the verdict is
`failed` with `lean_error`.

For example, the proof body

```lean
intro x
  simp
```

becomes the file

```lean
import Mathlib

theorem fixture_add_zero (a : ℕ) : a + 0 = a := by
  intro x
    simp
```

## Checking the file

A check has two steps. Each runs in a fresh process, from the benchmark's
pinned project checkout, under its own wall-clock limit, as does the compile
of the reference below. The files of a check are written to a fresh work
directory, removed when the check ends. When a process ends, `pi` kills
every process in its process group, so nothing it started in the usual way
outlives it.

**One check at a time.** One judge run peaks near 25 GB of memory, so only
one check runs on a machine at a time, and a lock enforces it. A check holds
an exclusive lock on `<data dir>/lean/work/.lock` (`data/lean/work/.lock` by
default) from before it makes its work directory until after it removes it.
A check that finds the lock held does not run: it stops with an error saying
that another Lean check is running, and gives no verdict. The lock is
released when the check ends, however it ends, and when its process dies, so
a crash leaves nothing to clear. Every command that checks a proof (`pi eval`,
`pi audit`, `pi lean-check` and the real-Lean tests) takes it.

**The reference.** Before the submission, `pi` compiles a reference file
itself: the header and the original statement closed with `sorry`. It never
comes from the reply, and it is compiled before any of the reply's code runs.
The reference compile must finish within the compile limit, exit with status
0, print no message of severity `error`, and write `Reference.olean`. If it
does not, the check gives **no verdict**: the reference is `pi`'s own file,
so the Lean setup or the machine is at fault, not the model. `pi` stops with
an error that names the theorem, shows the end of Lean's output and says to
fix the setup (`pi lean-setup`) and run the same command again. In a run
nothing is recorded for that theorem, and the same command resumes the run
at it; in an audit, the audit stops.

Once the reference has compiled, `pi` takes the SHA-256 of the compiled
reference, again after the submission's compile, and again after the judge.
If it has changed, the check fails as `judge_error`: the submission's code
had run by then, so it may have caused the change.

**Step 1: compile.** `lake env lean --json` compiles the submission with the
benchmark's Lean options (for `minif2f-test`, `autoImplicit=false` and
`relaxedAutoImplicit=false`) into a `.olean` file. The compile fails if Lean
exits with any status other than 0 or prints any message of severity `error`.
Warnings, such as `declaration uses 'sorry'`, do not fail it.

**Step 2: the judge.** [SafeVerify](https://github.com/GasStationManager/SafeVerify),
at the commit the benchmark pins, compares the compiled submission with the
compiled reference. It replays the submission's declarations in Lean's
kernel, checks that the reference's theorem is there with the same
statement, and checks the axioms that each declaration of the submission
depends on. It saves its outcome to a file, `judge.json`, and writes its
progress to standard error. `pi` refuses anything already at the path of
`judge.json` before the judge runs: that check fails as `judge_error`.

**A pass.** A check gives a verdict only once the reference has compiled, as
above. A result is `proved` when, and only when, code was found, the
reference compiled, and all of these hold:

- the submission compile finished within its limit, exited with status 0 and
  printed no message of severity `error`;
- the compiled reference has the same SHA-256 after the submission's compile
  as after its own compile;
- the submission compile wrote `Submission.olean`;
- nothing was at the path of `judge.json` before the judge ran;
- the judge finished within its limit and exited with status 0;
- the judge's standard error contains neither `uncaught exception: (kernel)`
  nor `kernel verification failed`, and has no line containing
  `used disallowed axioms`;
- `judge.json` holds JSON that is a non-empty list of pairs, each a name and
  an object with a `failureMode` key;
- one pair's name is the theorem's name;
- every pair's `failureMode` is null;
- every pair's `solutionInfo` has an `axioms` list of names, and every name
  in every such list is on the allowlist;
- the compiled reference has the same SHA-256 after the judge as after its
  own compile.

The axioms recorded for a result are the ones the judge lists for the theorem
itself.

## Verdicts

| Verdict | Meaning |
| --- | --- |
| `proved` | Every condition of [a pass](#checking-the-file) holds |
| `failed` | Code was found and the check did not pass; the record gives the reason |
| `missing` | No code was found (see [Finding the code](#finding-the-code)), so nothing was checked |
| `cut_off` | The reply stopped before the model finished it, in practice at the output limit. Not checked |
| `timed_out` | The model was still generating at the time limit. Not checked |

Only `proved` counts as solved. `cut_off` and `timed_out` mean what they mean
for answer runs: an attempt that hits a limit is unsolved, whatever it had
written.

## Reasons

A `failed` result has exactly one reason. The examples are the cases in
[`tests/lean_cases/`](../tests/lean_cases/README.md), all original theorems,
which [`tests/test_lean_real.py`](../tests/test_lean_real.py) grades with the
real Lean and judge, and the tests in
[`tests/test_lean_grading.py`](../tests/test_lean_grading.py).

| Reason | Meaning | Example |
| --- | --- | --- |
| `lean_error` | The submission did not compile | `renamed`: the theorem proved as `pi_case'`, so the block is a proof body and Lean rejects it. `add_false` does not compile on Lean 4.27 |
| `sorry` | The proof, or a declaration in the file, depends on `sorry` | `sorry`; `helper_sorry`, a helper lemma closed with `sorry`; `unused_sorry`, an unused helper closed with `sorry` |
| `statement_changed` | The judge did not find the theorem with the original statement | `weakened`: `a + 0 ≤ b + 1` for `a + 0 ≤ b`. `fake_success_exit`: `#exit` before the theorem, so it is absent |
| `axioms` | The proof, or a declaration in the file, depends on an axiom outside the allowlist | `helper_axiom`: `axiom pi_helper` declared and used |
| `kernel_rejected` | The judge's kernel replay rejected a declaration | `add_false_env`: a declaration added to the file without the kernel checking it. `replace_axiom`: an imported axiom replaced. `native_decide` |
| `check_timed_out` | The submission compile or the judge was killed at its limit | A proof body that runs `sleep 120000`, with 30-second limits |
| `judge_error` | The judge gave no usable verdict, or refused the submission for a reason that has no label of its own | The judge exits 0 and saves no outcome; the judge refuses an `unsafe` definition; the judge is killed by a signal; the reference changes during the check |

The reference compile gives no reason: if it fails, there is no verdict
(see [the reference](#checking-the-file)). Once it has compiled, the reasons
are decided in this order, and the first that applies is given:

1. The submission compile was killed at its limit: `check_timed_out`. It
   failed: `lean_error`.
2. The reference changed during the submission's compile, the submission
   wrote no `.olean`, or `judge.json` already exists: `judge_error`.
3. The judge was killed at its limit: `check_timed_out`.
4. The judge's standard error contains `uncaught exception: (kernel)` or
   `kernel verification failed`: `kernel_rejected`.
5. A pair's failure mode is `thmType` (the statement differs), `notFound` (no
   such theorem), or an object, which is how the judge reports a declaration
   of another kind: `statement_changed`.
6. A pair's failure mode is `axioms`, or a line of the judge's standard error
   says a declaration `used disallowed axioms`: `sorry` if `sorryAx` is among
   the axioms those pairs list or in one of those lines, otherwise `axioms`.
7. The conditions for a pass hold except that an axiom is off the allowlist:
   `axioms`.
8. Anything else that is not a pass: `judge_error`.

Whatever the outcome of steps 3 to 8, a reference that changed while the
judge ran makes the result `judge_error`.

**What `judge_error` covers.** It means the judge gave no usable verdict, or
refused the submission for a reason that has no label of its own. These are
the cases that reach it:

- the compiled reference changed, or disappeared, during the submission's
  compile or while the judge ran;
- the submission compile succeeded but wrote no `Submission.olean`;
- something was already at the path of `judge.json` before the judge ran;
- the judge exited with status 0 but saved no outcome, or one that is not
  JSON, or not a non-empty list of name and outcome pairs, or names no pair
  after the theorem, or gives a failure mode the rules do not know, or lacks
  a list of axioms;
- the judge refused the submission for a reason of its own, without saving
  an outcome or printing a message the earlier steps read. It refuses an
  `unsafe` definition (`unsafe constant … detected`). It also refuses a
  `partial` one, but only when asked to with `--disallow-partial`, which
  `pi` does not pass, so a `partial` definition is not refused today. It
  refuses a submission that does not import everything the reference
  imports, and a numeric literal that looks corrupted;
- the judge died by a signal (a negative exit status), for example when the
  system killed it for its memory;
- the judge exited with a status other than 0 and no earlier step applies.

These stay verdicts, because a submission can cause each of them and a reply
must never be able to stop a run. But `judge_error` can also mean the judge
or the machine failed, so **a run holding any `judge_error` result needs a
person to look at it before it is published.**

## The axiom allowlist

`propext`, `Classical.choice` and `Quot.sound`. The benchmark definition
records the list, and the run records it with the grader. Every other axiom
is rejected: `sorryAx`, any axiom the reply declares, and any axiom a helper
lemma brings in.

## Limits

The limits that bind are wall-clock: one for the compile step and one for the
judge, set in the `[lean]` section of the run configuration
(`compile_time_limit_seconds` and `judge_time_limit_seconds`). The reference
compile and the submission compile each get the compile limit. A submission
compile or judge that reaches its limit is killed, and the result is
`check_timed_out`. A reference compile that reaches it is killed too, and the
check gives no verdict, as [above](#checking-the-file).

`pi` does not set Lean's own per-declaration budget, `maxHeartbeats`: the
benchmark's Lean options are the only ones passed, and a proof may raise it
with `set_option`, as Mathlib's own proofs do. The wall-clock limit is what
stops it.

The generation limits are separate: the output-token limit and the time
limit in the configuration's `[generation]` section (`max_output_tokens` and
`time_limit_seconds`) are what produce `cut_off` and `timed_out`, before any
check. A run records its generation settings in `run.json`'s `generation`
and its two check limits in its `lean` entry.

An attempt that the machine slept through, its check included, is thrown
away and made again, as for answer runs.

## What the judge did with the harder cases

Each case was run by hand with Lean 4.27 and the pinned judge, and its output
is captured in [`tests/lean_cases/`](../tests/lean_cases/README.md);
`tests/test_lean_real.py` grades each one with these rules.

- **`unused_sorry`**: a valid proof of the theorem, and a lemma it never uses
  closed with `sorry`. The judge's outcome for the theorem itself is clean.
  It exits 1, and only its standard error names the unused lemma's
  disallowed axiom. The rules read that line, so the result is `sorry`.
- **`native_decide`**: a proof by `native_decide`. The judge's kernel replay
  rejects it before any axiom check, so the result is `kernel_rejected`.
- **`skip_kernel`**: a valid proof under `set_option debug.skipKernelTC true
  in`. It is still `proved`. The option changes nothing for a valid proof,
  because the judge replays the compiled file in the kernel either way. The
  evidence that the replay checks is `add_false_env`, whose unchecked
  declaration the replay rejects.
- **`renamed_binders`**: the theorem restated with other names for its bound
  variables, `(x y : ℕ) (hxy : x ≤ y)` for `(a b : ℕ) (h : a ≤ b)`. It is
  `proved`: bound-variable names do not matter.
- **`answer_wrapper`**: a statement of the form `x = answer(2)`, restated as
  `x = 2`. The judge reports the statement changed, so the result is
  `statement_changed`: a submission has to keep the `answer(…)` form. This
  notation appears only in miniF2F's validation split.

An `#print axioms` command inside the submission is not evidence of anything.
On `add_false_env`, appending one to the file reports that the theorem
depends on no axioms, though its proof rests on a false declaration. Only the
judge's replay of the compiled file is trusted.

## The known limit

The compile step runs the model's code, and Lean code can run programs while
it compiles. The judge defends the verdict against that: it replays the
compiled file on its own, and the compile step's output can fail a proof but
never pass one. `pi` kills what a step leaves behind in its process group.
But the compile step is not sandboxed: code that starts a
process in a new session, or that attacks files on the machine, is not
prevented.

As a watch on this, `pi` records the compile-time commands each block uses.
An accepted proof whose block contains any of these is flagged in its record
and listed in the report for a person to read. It is not rejected for that
alone.

These are the fourteen, in the order a record lists them:

`#eval`, `run_cmd`, `run_tac`, `run_elab`, `run_meta`, `elab`, `elab_rules`,
`macro`, `macro_rules`, `syntax`, `declare_syntax_cat`, `initialize`, `IO.`,
`unsafe`

Each is matched as a whole word anywhere in the block, comments and strings
included: not preceded by a letter, digit, `_`, `.` or `'`, and not followed
by a letter, digit, `_` or `'`. So `elab` does not match `elaborate`, and
`unsafe` does not match `unsafeCast` or `Foo.unsafe`. `IO.` matches only at
the start of a name, so not in `MyIO.x` or `Foo.IO.x`, and anything may
follow its dot. Every result with code records its flags; the report lists
only the accepted ones.

## The grader

The project, the judge and the axiom allowlist are pinned in the benchmark
definition: the project's repository and commit, the theorem file, the Lean
options, the judge's repository and commit. A run records them, the Lean
toolchain, `lean --version`, the SHA-256 of the project's `lean-toolchain`,
`lake-manifest.json`, `lakefile.lean` and theorem file, and the rules
version, and a session refuses to resume a run whose Lean environment
differs. [records.md](records.md) has every field.

Check one reply to one theorem with Lean, after `pi lean-setup`:

```sh
uv run pi lean-check --config configs/qwen3-14b-lean.toml \
  --benchmark benchmarks/<lean benchmark>.toml --id <theorem> --reply reply.md
```

It prints the verdict, the reason, the axioms, the flags, and the time of
each step. `reply.md` holds the reply's text, code block included.
