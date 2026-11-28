# Lean grader cases

Captured output of the two-step Lean check, run by hand on 2026-11-27 on an Apple-silicon Mac
(48 GB). Each directory holds one case: `Target.lean` (the statement closed with `sorry`),
`Submission.lean` (the proof under test), and what the tools printed for it. The theorems are
original to this repository, except `add_false` and `replace_axiom` (see the end).
`add_false_env` uses the same idea as SafeVerify's AddFalse test but is written here.

The captured files are the tools' real output and must not be edited. A later task parses them.

## Versions

| Component | Version |
| --- | --- |
| elan | 4.4.0 (Homebrew `elan-init`) |
| `lake env lean --version` | `Lean (version 4.27.0, arm64-apple-darwin24.6.0, commit db93fe1608548721853390a10cd40580fe7d22ae, Release)` |
| Lake | 5.0.0-src+db93fe1 |
| miniF2F | `google-deepmind/miniF2F` at `f0a20e14c1eeccd859d51bb4c2b3ee487889c303`, in `data/lean/miniF2F-f0a20e14c1ee` |
| SafeVerify | `GasStationManager/SafeVerify` at `b291b588a53999a7e837dda61c7dbfe8c550c814`, in `data/lean/SafeVerify-b291b588a539` |

Both checkouts pin `leanprover/lean4:v4.27.0`. `lake exe cache get` fetched 7869 Mathlib files.
After `lake build` (both checkouts), `git status --porcelain` printed nothing for either checkout.

## Commands that worked

Run from `data/lean/miniF2F-f0a20e14c1ee`, with `W=../work/<case>` holding copies of the two
`.lean` files and `C=<repo>/tests/lean_cases/<case>`:

```sh
O="-D autoImplicit=false -D relaxedAutoImplicit=false"
lake env lean --json $O --root=$W -o $W/Target.olean $W/Target.lean
lake env lean --json $O --root=$W -o $W/Submission.olean $W/Submission.lean > $C/compile.stdout; echo $? > $C/compile.exit
lake env ../SafeVerify-b291b588a539/.lake/build/bin/safe_verify --save $W/judge.json \
  $W/Target.olean $W/Submission.olean 2> $C/judge.stderr; echo $? > $C/judge.exit
cp $W/judge.json $C/ 2>/dev/null
```

The judge was skipped when the submission did not compile (only `add_false`).

**One deviation from the plan's command: `--root=$W` is required.** Without it, Lean 4.27
refuses the file, prints this to stderr, and exits 1:

```
input file '<abs>/data/lean/work/valid/Target.lean' must be contained in root directory (<abs>/data/lean/miniF2F-f0a20e14c1ee/)
```

The root defaults to the working directory, and `../work/...` lies outside it. Setting the root
to the case's own directory keeps every path relative, leaves the miniF2F checkout clean, and
makes the module names simply `Target` and `Submission`. `-D name=value` (with a space after
`-D`) and `--json` work as written.

## Where the output goes

- `lean --json` writes one JSON message per line to **stdout** (`compile.stdout`). Each message
  has `fileName` (the relative path as given, such as `../work/valid/Submission.lean`), `pos`,
  `endPos`, `severity` (`information` / `warning` / `error`), `kind`, and `data`. A clean
  compile prints nothing. `declaration uses 'sorry'` is a `warning` with `kind` `hasSorry`, and
  the compile still exits 0.
- `safe_verify` writes its progress and verdict to **stderr** (`judge.stderr`). It exits 0 with
  `SafeVerify check passed.` or exits 1 with an `uncaught exception: ...` line.
- `judge.json` (from `--save`) is a JSON **list of `[name, outcome]` pairs**, not a bare list of
  outcomes, for example
  `[["pi_case", {"targetInfo": {...}, "solutionInfo": {...} | null, "failureMode": ...}]]`.
  `targetInfo` and `solutionInfo` hold only `{"constInfo": {"kind": ...}, "axioms": [...]}`.
  **`valid/judge.json` holds exactly one pair.** It is written only when the judge gets as far as
  the declaration checks. A kernel or replay exception (`native_decide`, `replace_axiom`,
  `add_false_env`) exits 1
  before writing it, so those cases have no `judge.json`.
- SafeVerify writes `judge.json` without a final newline. The repository's `end-of-file-fixer`
  hook added one when the files were committed. That is the only change from the tools' bytes.

## Cases

"Compile" and "judge" are the exit codes. All targets compiled (exit 0) with the expected
`declaration uses 'sorry'` warning.

| Case | Expected | Compile | Judge | What the judge reported | Matches |
| --- | --- | --- | --- | --- | --- |
| `valid` | proved | 0 | 0 | `failureMode` null, one pair, `SafeVerify check passed.` | yes |
| `sorry` | sorry | 0 | 1 | `failureMode` `"axioms"`, solution axioms `["sorryAx"]` | yes |
| `helper_sorry` | sorry | 0 | 1 | `failureMode` `"axioms"`, solution axioms `["sorryAx"]`; stderr names `pi_helper` and `pi_case` | yes |
| `helper_axiom` | axioms | 0 | 1 | `failureMode` `"axioms"`, solution axioms `["pi_helper"]` | yes |
| `unused_sorry` | sorry | 0 | 1 | `failureMode` **null** for `pi_case`; the rejection is only in stderr: `pi_unused used disallowed axioms. #[sorryAx]` | rejected, see note 1 |
| `weakened` | statement_changed | 0 | 1 | `failureMode` `"thmType"` (`theorem type mismatch`) | yes |
| `renamed` | statement_changed | 0 | 1 | `failureMode` `"notFound"`, `solutionInfo` null | yes (through `pi`: `lean_error`, see below) |
| `reformatted` | proved | 0 | 0 | `failureMode` null | yes |
| `native_decide` | kernel_rejected | 0 | 1 | no `judge.json`; stderr `uncaught exception: (kernel) (interpreter) unknown declaration 'pi_case._nativeDecide_1_1'` | rejected, see note 2 |
| `fake_success_exit` | statement_changed | 0 | 1 | `failureMode` `"notFound"`; the compile printed `Finished.` (information) and `using 'exit' to interrupt Lean` (warning) | yes |
| `add_false` | not proved | **1** | skipped | did not compile on Lean 4.27, see note 3 | not proved |
| `replace_axiom` | not proved | 0 | 1 | no `judge.json`; stderr `uncaught exception: (kernel) application type mismatch` / `False.elim @propext` | not proved, see note 4 |
| `add_false_env` | not proved | 0 | 1 | no `judge.json`; stderr `uncaught exception: (kernel) declaration type mismatch, 'pi_false' has type` / `True` / `but it is expected to have type` / `False` | not proved, see note 5 |
| `skip_kernel` | record | 0 | 0 | `failureMode` null (accepted) | recorded |
| `renamed_binders` | record | 0 | 0 | `failureMode` null (accepted) | recorded |
| `answer_wrapper` | record | 0 | 1 | `failureMode` `"thmType"` | recorded |

No case expected to fail was accepted, and none of the three exploits was accepted.

The table records the judge's result on the raw files. Through `pi`, the `renamed` block declares
`pi_case'`, not `pi_case`, so it is treated as a proof body and graded `lean_error`.

### Notes

1. `unused_sorry`: SafeVerify checks the axioms of every submission declaration, not only the
   targets. An extra `sorry` lemma makes the judge exit 1, but `pi_case`'s own outcome in
   `judge.json` is clean (`failureMode` null, axioms `["propext"]`). So "proved" has to require
   judge exit 0 as well as a null `failureMode`, and the stderr line
   `<name> used disallowed axioms. #[...]` is the only place the reason appears.
2. `native_decide`: an `axioms` failure (`Lean.ofReduceBool`) never happens. During
   replay of the submission, SafeVerify's kernel check throws because the auxiliary declaration
   `pi_case._nativeDecide_1_1` is unknown to the interpreter, and the judge exits 1 with no
   `judge.json`. The submission is rejected, but through an uncaught exception, not a
   `failureMode`.
3. `add_false`: the submission fails to compile. `open private mk from Lean.Environment` is
   ambiguous on Lean 4.27 (14 private `mk` declarations), so `add_false` is never defined. The
   unmodified `SafeVerifyTest/AddFalse/Bad.lean` (with its original
   `import Batteries.Tactic.OpenPrivate`) fails with the same four errors, so the cause is not the
   import change. This case has no judge files. Drop it from the list of judge-replay cases.
   `add_false_env` is the false-declaration exploit that does compile on 4.27.
4. `replace_axiom`: the submission compiles. Its `#eval` rewrites `propext` to `False` in the
   elaborator's environment, and its `#guard_msgs` passes. SafeVerify's `Environment.replay`
   re-checks the submission's declarations against the real `propext` and throws
   `(kernel) application type mismatch`, so the judge exits 1 with no `judge.json`. The message is
   not the `kernel verification failed for '...'` form. That form comes from SafeVerify's later
   `Kernel.check` pass, which this case never reaches.
5. `add_false_env`: the submission's `#eval` calls the public `Environment.addDeclCore` with
   `doCheck := false`. That adds a new theorem `pi_false : False` whose value is `True.intro`,
   which the kernel never checks. Then `theorem falseThm : False := pi_false` is accepted by the
   compiler (exit 0, no messages). Inserting the constant only into the kernel's constant map, the
   way `replace_axiom` does, is not enough on 4.27: the elaborator then reports
   ``Unknown constant `pi_false` ``, because it looks up local constants through its own map.
   The `.olean` carries `pi_false`. SafeVerify's `Environment.replay` type-checks it, throws
   `(kernel) declaration type mismatch`, and the judge exits 1 with no `judge.json`.
   An in-file axiom check would have been fooled. Appending `#print axioms falseThm` to the
   submission (run by hand, not captured) compiles with exit 0 and prints the `information`
   message `'falseThm' does not depend on any axioms`.

### Record-only cases

- `skip_kernel`: a valid proof under `set_option debug.skipKernelTC true in` is still accepted,
  because the judge replays it in the kernel either way. The evidence that the replay checks is
  `add_false_env`, whose declaration the kernel never checked during the compile and the replay
  rejects.
- `renamed_binders`: binder names are not part of the comparison. `(x y : ℕ) (hxy : x ≤ y)`
  passes against a target written with `(a b : ℕ) (h : a ≤ b)`.
- `answer_wrapper`: with `import MiniF2F.ProblemImports`, a target stating `x = answer(2)` does
  **not** match a submission stating `x = 2` (`thmType`). `answer(...)` elaborates to something
  other than the bare literal, so a submission has to keep the target's `answer(...)` form.

## Cost

- `valid` submission compile, `/usr/bin/time -l` (two runs): **7.3 s and 7.5 s wall**. Maximum
  resident set size **5.4 GB**. That is `time`'s child-rusage figure, so it includes the `lean`
  process under `lake` and is mostly memory-mapped Mathlib `.olean` files. The peak memory
  footprint reported for `lake` itself was 138 MB.
- `valid` judge, `/usr/bin/time -l` (one run): **26.1 s wall**, maximum resident set size
  **24.6 GB**. SafeVerify imports Mathlib several times (the import superset check, then both
  replays).
- Disk: `data/lean/` is **7.7 GB** (miniF2F checkout with Mathlib cache 6.9 GB, SafeVerify
  checkout 847 MB, `work/` 1.7 MB). The Lean toolchain under `~/.elan` adds 2.3 GB.
- First-time setup: `lake exe cache get` 69 s, miniF2F `lake build` 29 s (after the cache),
  SafeVerify `lake build safe_verify` 90 s.

## Attribution

Three files are adapted from SafeVerify (https://github.com/GasStationManager/SafeVerify) at
commit `b291b588a53999a7e837dda61c7dbfe8c550c814`, under the Apache License 2.0. Its licence
text is in [`SafeVerify-LICENSE.txt`](SafeVerify-LICENSE.txt).

| File here | SafeVerify's file | What was changed |
| --- | --- | --- |
| `add_false/Submission.lean` | `SafeVerifyTest/AddFalse/Bad.lean` | `import Mathlib` replaces the first line, `import Batteries.Tactic.OpenPrivate` |
| `replace_axiom/Submission.lean` | `SafeVerifyTest/ReplaceAxiom/Bad.lean` | `import Mathlib` replaces the first line, `import Batteries.Tactic.OpenPrivate` |
| `replace_axiom/Target.lean` | `SafeVerifyTest/ReplaceAxiom/Target.lean` | `import Mathlib` is added as the first line |

Each of the three ends with a comment line saying so. That line was added after the output was
captured; it follows every other line, so it moves none of the positions the captured messages
give. `add_false/Target.lean` restates that test's target with `by sorry`.
