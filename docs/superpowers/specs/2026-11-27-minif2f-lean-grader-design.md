# Design: a Lean grader and a miniF2F proof baseline

Date: 2026-11-27. Status: approved by the owner on 2026-11-27. A builder's
review is folded in (see "Decided calls").

## Intent

The brief's Milestone 2 asks for a second baseline: the fraction of a fixed set
of formal theorem statements that the original Qwen3-14B checkpoint proves in
Lean 4, with one attempt each, graded by Lean afterwards. It is reported beside
the MATH-500 answer accuracy (477 of 500), which it does not replace: the two
scores answer different questions.

Why now: MATH-500 is close to its ceiling for this checkpoint, so it can say
little about whether fine-tuning helps. Lean proof writing is what Pi is for,
and every later stage of the brief builds on a trustworthy Lean grader:
Lean-guided revision, the fine-tuning comparison, and the eventual
natural-language interface.

Success: a pre-registered, audited, reproduced and published score on all 244
test theorems of the pinned benchmark, in the same shape as the MATH-500
baseline, with every accepted proof saved as a file anyone can replay.

## Goals

1. **A Lean grader** that accepts a proof only when Lean's kernel checks a
   theorem with the original statement and the proof depends on no axiom
   outside a recorded allowlist (brief, Milestone 2).
2. **miniF2F as a benchmark `pi` can run**, pinned to an exact commit of
   `google-deepmind/miniF2F`, with its Lean toolchain and Mathlib pinned by
   that commit's own files.
3. **`pi eval`, `pi audit`, `pi report` and `pi publish` work for Lean runs**
   with the same guarantees as for MATH-500: resumable by problem id, one
   result per problem, scored standard (committed code, mains, verified
   weights), audit regrades from saved files, report rebuilds from records.
4. **A development run** on a frozen sample of the validation split, to set
   the prompt and limits, then a **pre-registered scored run** on the test
   split, following the same after-the-run procedure as MATH-500 (audit,
   reproduce five pre-chosen problems, publish, commit).

## Non-goals

- Lean-guided revision, multiple attempts, or pass@k. The first proof
  baseline is one attempt per theorem (brief). These come later.
- A long-running Lean REPL (approach B). It may be added beside this grader
  for the revision experiment; it is not used for scored grading.
- Other Lean benchmarks (the `yangky11` port, miniF2F-v2, PutnamBench,
  ProofNet). Cheap to add once this exists; not part of this work.
- Fine-tuning, or any AWS compute. This milestone costs $0 in cloud compute.
- Changing anything about MATH-500 runs: their records, grader rules version 1
  and audit must keep working unchanged.

## Anti-goals: failure even if it "works"

- **A grader that can accept something Lean did not fully check.** It fails
  closed: any error, timeout, missing output or unexpected output is a
  rejection. A proof passes only on positive confirmation from a program that
  runs none of the model's code.
- **A proof of a different statement.** The model must not be able to pass by
  restating, weakening or redefining the theorem.
- **Touching the test split before the scored run.** The prompt, limits and
  extraction rules are tuned only on validation problems, as MATH's training
  problems were for MATH-500.
- **A score that measures formatting rather than proving.** If the
  development run shows most failures are Lean 3 syntax or a missing code
  block, that is fixed in the prompt or the extraction rules before
  pre-registration, not reported as the model's proving ability.

## Constraints

- **The Mac:** M3 Max, 48 GB. Generation through Ollama as today
  (`qwen3:14b`, digest `bdbd181c33f2`). Lean and Mathlib run locally.
- **CI has no Lean, no model, no GPU and no dataset downloads** (AGENTS.md).
  Tests that need Lean run only where it is installed and are skipped
  otherwise. CI tests everything around Lean with its output faked.
- **The repository is public, and benchmark problem files are never
  committed** (AGENTS.md). The miniF2F checkout lives in the git-ignored
  `data/` directory. What a run commits is set out in section 4.
- **Evaluation problems stay out of training data,** with their solutions and
  close variants (brief). Accepted proofs of test theorems are evaluation
  solutions and never enter any training set.
- **Grading rules are versioned** (AGENTS.md). The Lean grader has its own
  rules document and version, separate from the answer grader's rules
  version 1.
- **Repository conventions:** pull requests with typed templates, one-line
  Conventional Commits, `scripts/check.sh` before each PR.

## Approaches considered

How the grader runs Lean:

| | Approach | Trade-off |
| --- | --- | --- |
| **A (chosen)** | A fresh Lean process per proof, on a generated file, with a wall-clock limit | Matches "a clean environment" literally; fewest moving parts; each check replayable alone. Re-imports Mathlib per check, a few seconds against minutes of generation |
| B | One long-running Lean REPL with Mathlib imported once | Faster, and gives goal states for the later revision experiment; but state can leak between proofs and it has more failure modes. Wrong trade for a scored grader |
| C | An existing verification server (Kimina Lean Server, LeanInteract) | Least code; adds a third-party service, often Docker, between Lean and the verdict, and less control over the axiom check |

The owner chose A on 2026-11-27.

How a compiled proof is judged, within A:

| | Approach | Trade-off |
| --- | --- | --- |
| A1 (first draft) | `pi` appends its own check (`#print axioms`, a type comparison) to the same file and reads Lean's output | Simplest. But the check runs in the same process as the model's code, which can run arbitrary programs while Lean elaborates it: it could print the confirmation itself and stop the file with `#exit`, or add a declaration the kernel never checked. Not fail-closed |
| **A2 (chosen)** | Compile the model's file to a compiled module, then judge that module with a separate program that runs none of the model's code: [SafeVerify](https://github.com/GasStationManager/SafeVerify), pinned | Replays every declaration through the kernel, compares the theorem's type with a reference, and checks axioms, all from compiled files. One pinned dependency: about 35 KB of Lean, Apache-2.0, built on the same Lean 4.27.0 and the same Mathlib commit as the benchmark. PutnamBench's leaderboard uses it |

A2 was chosen after the builder's review (Claude's call; see "Decided calls").

Which miniF2F:

| | Version | Trade-off |
| --- | --- | --- |
| **`google-deepmind/miniF2F` (chosen)** | Lean 4.27, Mathlib `v4.27.0`, CI, Apache-2.0; "all known false statements removed"; informal statements as docstrings; AlphaProof's evaluation set | Newest and most corrected; needs `formal_conjectures`; splits differ in form (see below); fewer published comparisons |
| `yangky11/miniF2F-lean4` | The port most papers descend from; Lean 4.24 | Comparable with more papers; audits keep finding unfaithful statements; README says not maintained regularly |
| miniF2F-v2 | Hand-audited, >300 statements corrected | Dataset files, not a buildable Lean project; last updated 2025-11; an audit found defects its corrections introduced |

The owner chose the DeepMind fork on 2026-11-27, because Pi's key comparison is
base against fine-tuned on one frozen set under its own grader, so correct
statements matter more than comparability with published numbers.

## The design

### 1. The benchmark: a pinned Lean project

A new benchmark definition kind, beside the existing problem-file kind, for a
Lean project pinned by git commit:

```toml
# benchmarks/minif2f-test.toml (sketch)
name = "minif2f-test"
kind = "lean"
repository = "https://github.com/google-deepmind/miniF2F"
commit = "f0a20e14c1eeccd859d51bb4c2b3ee487889c303"   # main on 2026-02-18, "Update to Lean 4.27.0"
file = "MiniF2F/Test.lean"
scored = true
```

and `benchmarks/minif2f-dev.toml` with `file = "MiniF2F/Valid.lean"` and a
frozen `ids` list (section 6).

- `pi` clones the repository into `data/` and checks out the commit. The
  commit hash is the content pin, as the SHA-256 is for a problem file; `pi`
  also records the SHA-256 of the split file, `lean-toolchain` and
  `lake-manifest.json`, and refuses if the checkout is dirty.
- The toolchain is the one the commit's `lean-toolchain` names
  (`leanprover/lean4:v4.27.0`), installed through elan. Dependencies are the
  ones its `lake-manifest.json` pins (Mathlib `a3a10db0e9d6`,
  `formal_conjectures` `f564f8d7a6d2`, and the rest). Mathlib's compiled files
  come from `lake exe cache get`; the rest is built once with `lake build`.
  Setup is one documented command after installing elan.
- **Problems are theorems.** `pi` splits the split file into one problem per
  `theorem` declaration: its id is the theorem name; its statement is the
  declaration text up to its `:=`; its header is the file's preamble
  (imports, `open` lines); its informal statement is the docstring, when
  there is one (210 of the 244 test theorems have one). The parser fails
  loudly on anything it does not understand. The test split must yield
  exactly 244 theorems.
- **Two test theorems ship with a proof.** `mathd_numbertheory_66`
  (`:= rfl`) and `mathd_algebra_302` (`:= by norm_num [div_pow]`) are proved
  in the file; the other 242 end in `sorry`. The proof is stripped: the model
  sees every theorem the same way, ending in `:= by`, and never sees a
  shipped proof. Both stay in the 244, which is the benchmark as published;
  the log entry names them. The parser checks that exactly these two carry a
  proof at the pinned commit and fails otherwise.
- **Splits differ in form.** Most validation theorems (204 of 256) mark the
  expected value as `answer(…)`, a `formal_conjectures` notation; the test
  split never does. The development sample includes both kinds, and the log
  entry notes the difference. The builder's Lean tests must show what happens
  when a model restates such a theorem without the `answer(…)` wrapper, since
  that may or may not compare as the same statement; the finding goes in the
  rules document.
- A mirror of the pinned checkout in the `pi-benchmarks` bucket is a later
  nicety, not part of this work. The commit pin guarantees content; only
  availability depends on GitHub.

### 2. The prompt

The model gets one user message: a short fixed instruction, then the header
and the theorem statement ending in `:= by`, in a Lean code block. The
instruction says it is Lean 4 with Mathlib, asks for the complete theorem
with its proof in a single Lean code block, and allows helper lemmas before
the theorem. Nothing else: no examples, no informal statement (see decided
calls).

The exact wording is fixed during the development run and frozen in the
pre-registration. Reasoning mode stays on.

### 3. From reply to verdict

**Finding the code.** The model's code is the **last fenced code block** in
the visible reply (language tag `lean` or `lean4`, or untagged); the
reasoning is never read, as with MATH-500. No block: `missing`. A reply that
hits the output or time limit: `cut_off` or `timed_out`, as today.

**Assembling the file.** `pi` builds the submission file; it is never the
model's text alone. The rules are few, fixed, and written in the rules
document:

1. The benchmark's header, verbatim, comes first.
2. Leading `import` lines in the model's block are dropped. Lean allows
   imports only at the top of a file, and the header already imports all of
   Mathlib.
3. If the block declares a theorem with the original theorem's name, the rest
   of the block is used as it stands, helper lemmas included.
4. Otherwise the block is taken to be the proof body, and is placed after the
   original statement's `:= by`. This is the brief's "fill in only the proof
   body", and keeps a correct proof from failing on its wrapping.

These rules may be extended from what the development run shows, on
validation theorems only, and are frozen at pre-registration.

**Checking it, in two steps, each a fresh process:**

1. **Compile.** Lean compiles the submission file to a compiled module, in
   the pinned project, with the project's own Lean options (its lakefile sets
   `autoImplicit` false, among others), under a wall-clock limit. Any error,
   or a `sorry`, is a failure.
2. **Judge.** SafeVerify, pinned to commit
   `b291b588a53999a7e837dda61c7dbfe8c550c814` and built once at setup, is
   given two compiled files: the **reference** and the submission. The
   reference is compiled from a file `pi` writes alone: the header and the
   original statement, closed with `sorry`. SafeVerify:
   - replays every declaration of the submission through Lean's kernel, so a
     declaration that got into the file without being checked is caught;
   - requires a theorem of the same name and the same elaborated type as the
     reference's (types are compared, not text, so reformatting passes and
     any change of meaning does not);
   - requires that the theorem depends only on allowed axioms.

   The judge runs none of the model's code. `pi` checks the reference file's
   checksum before each judgement, and takes a pass only from SafeVerify's
   exit status and its saved JSON outcome, never from text the compile step
   printed.

**Verdicts:** `proved` only if both steps succeed. Otherwise `failed`, with a
reason recorded: `lean_error`, `sorry`, `statement_changed`, `axioms`,
`kernel_rejected`, `check_timed_out` or `judge_error`. Generation verdicts
`missing`, `cut_off` and `timed_out` stay as they are. The score is `proved`
divided by all selected theorems. Everything that is not `proved` is
unsolved.

**Axiom allowlist:** `propext`, `Classical.choice`, `Quot.sound`, recorded in
the benchmark definition (and SafeVerify's own default). That rejects
`sorryAx`, any newly declared `axiom`, and `Lean.ofReduceBool` (so
`native_decide`), including when used through a helper lemma.

**Limits.** The limits that bind are wall-clock: one for the compile step and
one for the judge step (provisionally 300 s each, fixed after the development
run). Lean's own per-declaration budget (`maxHeartbeats`) is left at the
pinned project's default, and the model's code may raise it, as Mathlib's own
proofs do; the wall-clock limit is what stops it. A check the Mac slept
through is run again, as a slept-through generation is today. The report
counts the checks that finished within 20% of the limit.

**Known limit, stated in the rules document.** The compile step runs the
model's code, and Lean code can run programs while it compiles. The judge
defends the verdict against that: a proof cannot be accepted by tricking the
compile step. It does not sandbox the compile step against code that
deliberately attacks files on the Mac. As a cheap watch on this, an accepted
proof whose code contains a compile-time command (`#eval`, `run_cmd`,
`elab`, `macro`, `syntax`, `initialize`, or `IO.`) is flagged in its record
and listed in the report for a person to read. It is not rejected for that
alone.

### 4. Records, and what is committed

Each result keeps today's fields and adds: `proof` (the extracted code block,
or null), and `lean` with `reason`, the compile step's `exit_code` and
`messages` (Lean's errors and warnings, capped in size), the judge's saved
outcome, `axioms`, `flags` (the compile-time commands found), and
`compile_seconds` and `judge_seconds`. Each accepted proof is also written as
a standalone file `proofs/<id>.lean` in the run directory (the submission
file as checked), so anyone can replay it with the pinned project.

`run.json`'s identity gains the Lean environment: the repository and commit,
the SHA-256 of the split file, `lean-toolchain` and `lake-manifest.json`, the
`lean --version` output, the SafeVerify commit, the Lean options, the
allowlist, the limits, and the Lean grader's rules version. A session refuses
to resume a run whose Lean environment differs.

**What goes where.** The repository is public, so this follows the line the
MATH-500 records drew: the model's replies are committed, the benchmark's own
text is not.

| | In git (`experiments/`) | In the artifacts bucket |
| --- | --- | --- |
| `run.json`, `results.jsonl`, `report.md`, `audit.json` | yes | yes |
| `proofs/<id>.lean` | no: each file is the benchmark's header and statement verbatim | yes |

`results.jsonl` holds the model's replies and extracted proofs, which will
usually restate the theorem; that is the model's text, as a MATH-500 reply
restating its problem is. `pi publish` is extended to upload `proofs/` and
list it in the manifest, and `pi audit` to cover it. The proof files can
also be rebuilt from `results.jsonl` and the pinned benchmark.

`docs/records.md` documents the new fields.

### 5. Grading rules document and version

`docs/lean-grading.md` states the Lean rules: extraction, file assembly, the
two-step check, the allowlist, the limits, the known limit, and the verdicts,
with worked examples, as `docs/grading.md` does for answers. It is Lean rules
version 1, held in its own constant. The rules are frozen at
pre-registration; any later change is a new version.

### 6. The development run, the scored run, and the audit

- **Development sample:** 30 validation theorems, frozen in advance by a
  seeded script as `scripts/select_dev_problems.py` did for MATH, spread across
  the competition families (`mathd_algebra`, `mathd_numbertheory`, `amc12`,
  `aime`, `imo`, induction) roughly in the test split's proportions, and
  including both `answer(…)` and plain theorems.
- It is run with the provisional prompt and limits to measure: the proof
  rate, the failure reasons, time per problem, check time and memory, and how
  often replies are cut off. The prompt, extraction rules and limits are
  fixed from it. Several development runs are fine, all on validation
  theorems.
- **Scored run:** all 244 test theorems, pre-registered in the experiment log
  before the first attempt, exactly as the MATH-500 entry was, including five
  problems chosen in advance by seed for the reproduction step.
- **After the run:** audit, reproduce the five, the owner publishes, commit
  the records and a log entry.
- **What the audit re-checks.** Every `proved` result is compiled and judged
  again and must pass again; the audit's time limit is four times the run's,
  because here the limit is not a budget and a busier machine must not turn a
  real proof into a failure. Every `failed` result with a deterministic
  reason is checked again and must fail for the same reason. A
  `check_timed_out` result is a budget verdict, like a generation time-out:
  the audit checks its recorded time against the limit and does not re-derive
  it. The audit also checks the Lean environment, the reference files and the
  scored standard.

### 7. Tests

- **Always run (CI):** splitting the split files (using a small fixture file,
  not the dataset), code block extraction, the assembly rules, verdict
  decisions from faked compile and judge output (errors, `sorry`, disallowed
  axiom, changed statement, kernel rejection, timeout, a judge that prints
  success but exits non-zero), records and identity checks, audit and report
  logic.
- **Run where Lean is installed** (skipped otherwise, run before every PR that
  touches the grader), against the real pinned project and SafeVerify: the
  brief's three cases: a valid proof passes; a proof containing `sorry`
  fails; a helper lemma that assumes the conclusion fails. Plus: a proof of a
  weakened statement fails; a declared `axiom` fails; `native_decide` fails;
  code that adds a false declaration by metaprogramming fails; code that
  prints a fake success line and stops the file with `#exit` fails; a
  kernel-check bypass option fails; a tactics-only block passes; a block with
  repeated `import` lines passes; reformatting the statement still passes.

### 8. What the build covers, and who signs off

The implementation plan covers three stages, each ending in a pull request
the owner merges:

1. The benchmark kind, the grader, records, audit, report and publish
   changes, with their tests. Its first task is a short spike on the Mac
   proving the whole check works end to end on Lean 4.27: compile, judge, and
   the adversarial test cases above. If it cannot be made to work, the build
   stops and comes back to the owner; there is no weaker fallback.
2. The development sample and development run(s), with a log entry.
3. The pre-registration entry for the scored run. The owner's merge of this
   pull request is what freezes the prompt, the rules and the limits, as it
   was for MATH-500.

The scored run, its audit, reproduction, publication and commit follow the
MATH-500 procedure after that, and are not part of the build plan. Runs
occupy the Mac for hours: the owner launches the scored run, and Claude asks
before starting a development run.

## Decided calls (Claude's, accepted with the design)

- **A separate judge, SafeVerify, instead of a check appended to the file.**
  The appended check of the first draft ran beside the model's code and could
  be forged. SafeVerify matches the benchmark's Lean and Mathlib versions
  exactly, and is small enough to read in full before trusting it. There is
  no fallback to a weaker check.
- **`pi` may strip repeated imports and wrap a proof-only reply** (section 3).
  Without this, a correct proof could fail on packaging, which is the
  formatting anti-goal. Nothing else in the model's code is touched.
- **Wall-clock limits, and an audit that re-proves rather than re-times**
  (sections 3 and 6). Wall-clock limits are the convention for this
  benchmark; a heartbeat limit would be more repeatable but the model's code
  can override it.
- **What is committed** (section 4): the same four files as MATH-500; proof
  files only in the bucket. Nothing is committed from a scored run until
  after it, so this can still be changed.
- **No informal statement in the prompt.** The brief says to supply the
  imports, hypotheses and statement; 34 of the 244 test theorems have no
  docstring, so including it would give the model unequal help across
  problems. It is recorded with each problem and can be studied later.
- **Grade right after each attempt, inside `pi eval`.** The model gets no
  feedback; "Lean grades afterwards" is satisfied because grading happens
  after generation ends. Grading inline keeps one complete result per problem
  and keeps resume by id working unchanged.
- **Same checkpoint settings as MATH-500** (reasoning on, temperature 0.6,
  top-p 0.95, top-k 20, seed 1, pinned batch and memory-mapping). The output,
  time and check limits are provisional until the development run; starting
  points are 16,384 output tokens, 1,200 s generation and 300 s per check
  step. A separate config file, `configs/qwen3-14b-lean.toml`, keeps
  `configs/qwen3-14b.toml` untouched.
- **Helper lemmas are allowed.** The brief describes Pi proposing and proving
  lemmas; forbidding them would penalise a good habit. They are covered by the
  axiom check.
- **The build ends at the pre-registration** (section 8).

## Left to the builder

- How `pi` drives elan, lake and SafeVerify (commands, where the compiled
  files go), and the setup command's shape.
- How the parser splits the split file, and how the reference files are built
  and cached.
- The cap on saved Lean messages, and the CLI surface (flags, messages).
- Module layout inside `src/pi/`, as long as MATH-500's paths keep working.
