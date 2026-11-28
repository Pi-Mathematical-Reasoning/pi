# Rules for coding agents

This file restates the repository conventions for coding agents. The
human-facing version, with setup details, is
[CONTRIBUTING.md](CONTRIBUTING.md). What Pi is, and what to build next, is in
the brief, [PI_PROJECT.md](PI_PROJECT.md).

## Non-negotiable

- **Never push to `main`.** Every change reaches `main` through a pull request.
  Direct pushes are blocked by a branch ruleset; do not try to work around it.
- **Open pull requests with a typed template and fill in every section:**

  ```sh
  gh pr create --template <type>.md   # feat.md | fix.md | docs.md | chore.md | refactor.md | ci.md
  ```

  Leaving a section empty or deleting it is not acceptable. `fix.md` also
  needs Bug, Root cause and Reproduction.
- **Pull request titles are Conventional Commits** (`type(scope)?: subject`,
  100 characters at most). The title becomes the squash-merge commit message.
- **Commits are a single line**: `type(scope)?: subject`, at most 100
  characters. After that line, only a blank line and
  `Co-authored-by: Name <email>` trailers are allowed. No body text; details
  go in the pull request description. Allowed types: `feat`, `fix`, `docs`,
  `chore`, `refactor`, `ci`, `build`, `perf`, `style`, `test`, `revert`.
  Breaking changes use `!` (`feat!: ...`).
- **Spell the trailer `Co-authored-by:` exactly.** The check is
  case-sensitive, so `Co-Authored-By:` fails it.
- **Merges are squash or rebase only.** History stays linear.
- **Releases are made by merging the Release Please pull request**, which is
  authored by the organization's release bot. Do not create tags or releases
  by hand, and do not edit `CHANGELOG.md` or `version.txt`.
- **Run the checks before opening a pull request:**

  ```sh
  scripts/check.sh
  ```

## Working in this repo

- **Read the brief before starting work.** It sets the order: the first
  deliverable is a reproducible score for the original checkpoint, and
  training comes after that measurement.
- **Python goes through uv.** The package is `src/pi/` and its tests are
  `tests/`. Add a dependency with `uv add` and commit `uv.lock`; CI installs
  with `uv sync --locked`, so a stale lock fails.
- **CI has no model weights and no GPU.** A test must pass without loading a
  model or downloading a dataset.
- **Evaluation problems stay out of training data**, along with their
  solutions and close variants.
- **Benchmark problem files are never committed.** A definition in
  `benchmarks/` pins a URL and a checksum, and `pi` fetches the file into the
  ignored `data/` directory. Use `benchmarks/math-dev.toml` for development;
  `benchmarks/math-500.toml` is for the scored run only.
- **Scored runs follow rules fixed in advance.** The prompt, sampling
  settings, limits and grader are frozen before a scored run and tuned only on
  development problems. A malformed answer or a timeout counts as unsolved.
- **The grading rules are versioned.** [docs/grading.md](docs/grading.md)
  states them. A change to how answers are found or compared bumps
  `RULES_VERSION` in `src/pi/grading.py` and updates that document. Debug the
  grader on development problems, never on evaluation problems.
- **Never run the model on `benchmarks/minif2f-test.toml`** outside a
  pre-registered run. It is the scored proof benchmark; its theorems are
  evaluation problems.
- **The Lean rules are versioned too.**
  [docs/lean-grading.md](docs/lean-grading.md) states them. A change to how
  the code is found, how the file is built or how the judge's outcome is read
  bumps `LEAN_RULES_VERSION` in `src/pi/lean_grading.py` and updates that
  document. Debug the Lean grader on the cases in `tests/lean_cases/` and on
  validation theorems, never on test theorems.
- **Run the real-Lean tests before a pull request that touches the Lean
  grader:**

  ```sh
  PI_LEAN_TESTS=1 uv run pytest tests/test_lean_real.py
  ```

  They need `uv run pi lean-setup --benchmark benchmarks/minif2f-test.toml`
  first and take about a quarter of an hour. One judge run peaks near 25 GB
  of memory, so never run two Lean checks at once. A lock on
  `data/lean/work/.lock` enforces it: a second `pi eval`, `pi audit`,
  `pi lean-check` or real-Lean test run started while a check runs stops
  with an error rather than wait.
- **Make Lean runs and audits in a shell without AWS credentials.** They need
  none, and the compile step runs code the model wrote. Only `pi publish`
  needs them. `pi` stops on SIGTERM and SIGHUP as on Ctrl-C, killing the Lean
  processes it started, so a run can be stopped with `kill` and resumed with
  the same command.
- **A Lean run's audit is long and comes last.** `pi audit` checks the
  records first and grades every saved reply again with Lean last, at four
  times the run's limits, printing a line per result as it goes; it skips
  that step when the benchmark, Lean environment, result-count or grader
  check failed. A run holding any `judge_error` result needs a person to look
  at it before it is published. `pi lean-check --run runs/<run>` checks the
  reply a run saved for one theorem.
- **Proof files are never committed.** A Lean run's `proofs/` directory
  restates the benchmark's theorems; it is published to the bucket with the
  run, and `.gitignore` keeps `experiments/*/proofs/` out of git.
- **Never publish to the artifacts bucket yourself.** `pi publish` uploads with
  the owner's admin credentials; the owner runs it, or asks you to.
- **Weights and checkpoints never go in git.** The brief keeps durable
  artifacts in S3, checksummed.

## Things that need the owner

Repository settings and secrets, and anything that costs money. Routine
inference and benchmarks run on the owner's Mac. AWS is for time-limited
training jobs, and the owner starts them: put the hypothesis, estimated cost
and stopping condition in the pull request instead of launching anything.
