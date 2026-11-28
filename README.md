[![Pi: irrationally good at math](https://raw.githubusercontent.com/Pi-Mathematical-Reasoning/pi-branding/main/assets/banner/pi-readme-banner.png)](https://github.com/Pi-Mathematical-Reasoning)

# Pi

[![GitHub release](https://img.shields.io/github/v/release/Pi-Mathematical-Reasoning/pi?label=release)](https://github.com/Pi-Mathematical-Reasoning/pi/releases/latest)
[![CI](https://github.com/Pi-Mathematical-Reasoning/pi/actions/workflows/ci.yml/badge.svg?event=pull_request)](https://github.com/Pi-Mathematical-Reasoning/pi/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/Pi-Mathematical-Reasoning/pi/blob/main/LICENSE)

Pi is a local-first mathematical reasoning project. You ask an open-weight
model for a proof and get back a Lean 4 file that can be checked
independently. Given a compute budget, Pi returns either a complete,
`sorry`-free proof or a record of where it stopped.

The research question is whether a model small enough to run on a personal
laptop can, after math-specific fine-tuning, solve more unseen problems than
its original checkpoint, and eventually outperform a larger model on the same
tasks.

The full brief, with each milestone and its done condition, is
[PI_PROJECT.md](PI_PROJECT.md).

## Status

**Four things run so far: the checkpoint probe, the answer grader, the
benchmark run and the Lean grader.** The probe loads the pinned checkpoint,
gives it one problem and records how fast it went and what it cost the
machine. The grader finds the final answer in a reply and decides whether it
matches a reference. The benchmark run attempts every problem of a pinned
benchmark once and reports the score. It has been run on the 30 development
problems and not yet on MATH-500. The Lean grader checks a proof of a Lean 4
theorem with Lean and a separate judge, and the benchmark run uses it for
Lean benchmarks; no Lean run has been made yet. The first deliverable is a
reproducible score for the original checkpoint; training comes after that
measurement.

| Stage | What it measures | State |
| --- | --- | --- |
| Milestone 1: local baseline | Answer accuracy on MATH-500, one attempt per problem, run on a MacBook Pro | In progress: the development run is done and the limits are set; the scored MATH-500 run has not been started |
| Milestone 2: proof writing | Fraction of miniF2F's 244 test theorems proved, pinned by commit and graded by Lean 4 and SafeVerify | In progress: the Lean grader and Lean runs are built, and the grader is checked on 16 captured cases; the development run has not been made, and there is no Lean score yet |
| Later experiments | Lean-guided revision, fine-tuning on AWS, a larger-model comparison | Not started |

Measurements are in the [experiment log](experiments/README.md).

## Run the checkpoint probe

The probe needs [Ollama](https://ollama.com) running with the pinned model:

```sh
ollama pull qwen3:14b
uv run pi probe --config configs/qwen3-14b.toml
```

It refuses to run unless the installed model's digest matches the one pinned
in the configuration. Then it unloads the model, so every run starts from a
fresh load, sends the model one problem, prints the measurements and writes a
JSON record under `runs/`. The fresh load is what makes a run repeatable: with
the same seed, a model that already holds the prompt in its cache writes
different text. The record holds:

- **The checkpoint:** the Ollama digest, the hash of the weights file, the
  quantization and the tokenizer settings.
- **The runtime:** the Ollama version and the command it launched the model
  with.
- **The run:** the configuration, the command line and the git revision.
- **The result:** the reply with its reasoning, the token counts, tokens per
  second, elapsed time, peak memory, swap growth and the power source.

Memory is measured over the Ollama server and the processes it launches, and
swap growth is measured on macOS only.

## Grade a reply

```sh
uv run pi grade --reference '\frac{1}{2}' --reply 'So the answer is $\boxed{0.5}$.'
uv run pi grade --reference 12 --record experiments/2026-11-20-checkpoint-probe/record.json
```

The grader takes the last boxed expression in the reply as the final answer
and compares it with the reference as mathematics, so `0.5` matches
`\frac{1}{2}`. It prints `correct`, `incorrect` or `missing`. The rules, with
examples of what does and does not count, are in
[docs/grading.md](docs/grading.md). Grading needs no model.

## Run a benchmark

```sh
uv run pi eval --config configs/qwen3-14b.toml --benchmark benchmarks/math-dev.toml --out runs/dev
uv run pi report runs/dev
```

`pi eval` attempts every problem once, from a fresh load of the model, and
sends it only the problem text. Each result is saved as it finishes. If the
run stops for any reason, the same command resumes it at the first problem
with no result. It refuses to continue if the checkpoint, the settings, the
problems or the grader have changed since the run began.

A run directory holds two files. `run.json` says what was run and whether it
is complete. `results.jsonl` has one line per problem: the reply, the final
answer read from it, the verdict, the token counts, the time, and whether the
machine was on battery or mains. `pi report` rebuilds the score from those
two files alone, so it needs no model.

Every field is described in [docs/records.md](docs/records.md), for analysis
in a notebook.

| Benchmark | Problems | Use |
| --- | --- | --- |
| `benchmarks/math-dev.toml` | A frozen sample of 30 MATH training problems | Tuning the limits and debugging the grader |
| `benchmarks/math-500.toml` | The 500 problems of MATH-500 | The scored baseline, and never tuning |

The problem file is fetched on first use into `data/` and checked against the
checksum pinned in the benchmark definition. Problem files are never
committed.

Each definition also names a mirror: the same file in Pi's own S3 bucket,
kept by [pi-benchmarks](https://github.com/Pi-Mathematical-Reasoning/pi-benchmarks)
in case an upstream disappears. `pi eval` tries the mirror first, with the AWS
CLI and whatever credentials the shell has, and falls back to the upstream
with a warning. The checksum is checked either way, so both give the same
results, and each session of a run records where its file came from. To use
the mirror, sign in first:

```sh
aws sso login --profile jaws-prod
export AWS_PROFILE=jaws-prod
```

### Scored runs

A benchmark definition with `scored = true` (today, `math-500`) is held to a
stricter standard, so that its score can be trusted:

- **Committed code only.** `pi eval` refuses to start or resume from a working
  tree with uncommitted changes, so every result names the commit it came from.
- **Verified weights.** Each session hashes Ollama's weights file, about six
  seconds for Qwen3-14B, and refuses one whose content does not match its name.
- **Mains power.** An attempt never starts on battery, where this Mac generates
  a third slower. The run stops instead; plug in and resume.

Every run, scored or not, also keeps:

- **Its sessions.** Each one is recorded when it starts, with the command, the
  commit, the machine, macOS and Python, so a run killed outright still says
  what produced its results. Each result names its session and start time.
- **The model runner's launch settings.** These include the cache type, flash
  attention and batch size, which change the numbers. The batch size and
  memory-mapping are pinned in the configuration, because Ollama otherwise
  picks them from free memory. If the launch changes part way through, the run
  stops before keeping the attempt.
- **Awake attempts only.** An attempt the Mac slept through is thrown away and
  made again, because its time measured the sleep. A fresh load makes the new
  attempt write the same reply.

### After a run: audit, then publish

```sh
uv run pi audit runs/<run> --benchmark benchmarks/<benchmark>.toml
uv run pi publish runs/<run>
```

`pi audit` checks a finished run from its saved files alone, with no model. It
fetches the problem file and checks its checksum. It checks that each problem
has exactly one result, grades every saved reply again under the same grader,
and checks each result belongs to a recorded session. It also rebuilds the
report, and for a scored run checks the scored standard held throughout. It
writes `report.md` if missing and `audit.json`, which records every check and
the SHA-256 of each file it audited.

`pi publish` uploads an audited run to Pi's artifacts bucket under
`data/runs/<run>/`, then writes `_manifest.json` last, as Jaws lays out run
artifacts. It refuses a run whose audit failed or whose files changed since
the audit. It never overwrites: it reads each file back and checks it, and
publishing again changes nothing. It needs AWS credentials, as the mirror
does.

A problem takes two to three minutes on average and up to ten, so the 30
development problems take about an hour and a half. On a Mac, run on mains
power: this checkpoint generates a third slower on battery. Start a long run
with `caffeinate -i` in front of the command so the machine does not sleep
part way.

## Lean benchmarks

A Lean benchmark is a file of Lean 4 theorems. The model is asked for a
proof, Lean compiles it, and a separate program,
[SafeVerify](https://github.com/GasStationManager/SafeVerify), judges
whether it proves the original statement using only allowed axioms. The
rules, with examples, are in [docs/lean-grading.md](docs/lean-grading.md).

It needs:

- **elan**, which installs the Lean toolchain the project pins:
  `brew install elan-init`.
- **Disk:** about 8 GB under `data/lean/` (the project checkout with its
  Mathlib build cache, and the judge) and 2.3 GB for the toolchain under
  `~/.elan`.
- **Memory:** one judge run peaks near 25 GB, so checks run one at a time and
  the model is unloaded before each.

```sh
brew install elan-init
uv run pi lean-setup --benchmark benchmarks/minif2f-test.toml
```

`pi lean-setup` clones the benchmark's project and the judge into
`data/lean/` at the commits the definition pins, fetches Mathlib's build
cache, builds both, and counts the theorems; for `minif2f-test` it ends with
`244 theorems`. It refuses a checkout at another commit or with changes.
Nothing under `data/` is committed.

| Benchmark | Theorems | Use |
| --- | --- | --- |
| `benchmarks/minif2f-test.toml` | The 244 theorems of miniF2F's test split, as corrected by Google DeepMind, in Lean 4.27 | The scored proof baseline. The model is never run on it outside a pre-registered run |

A Lean run uses a configuration with a `[lean]` section, which holds the
instruction placed above each theorem and the two check limits:

```sh
uv run pi eval --config configs/qwen3-14b-lean.toml \
  --benchmark benchmarks/<lean benchmark>.toml --out runs/<run>
uv run pi report runs/<run>
```

`pi eval` works as for answer runs, and resumes and refuses in the same way;
a scored definition is held to the same standard. Before it writes anything
or contacts the model, it checks that Lean and the judge are set up. The
prompt is the instruction, then the theorem's header and statement with its
proof left open. Each result records the proof taken from the reply and the
Lean check, and each proved theorem's file is saved as `proofs/<id>.lean` in
the run directory. Those files restate the benchmark, so they are never
committed. `pi report` gives the fraction proved, the failure reasons, the
time Lean and the judge took, the results by family, and the accepted proofs
that use compile-time commands, for a person to read.

Check one reply to one theorem, outside a run:

```sh
uv run pi lean-check --config configs/qwen3-14b-lean.toml \
  --benchmark benchmarks/<lean benchmark>.toml --id <theorem> --reply reply.md
```

`reply.md` holds the reply's text, code block included. It prints the
verdict, the reason, the axioms, the flags and the time of each step.

`pi audit` and `pi publish` work as for answer runs. The audit needs Lean set
up: it grades every saved reply again, checking the proofs with Lean one at
a time. A `proved` result must be proved again at four
times the run's limits, and a `failed` one must fail again for the same
reason; one that failed by timing out is not run again, but its recorded
time must reach the limit. A full run takes hours to audit. The audit also
checks the benchmark's pins, the Lean environment and the proof files, and
`pi publish` uploads the proof files with the rest.

The real-Lean tests grade the captured cases in `tests/lean_cases/` with Lean
and the judge, after `pi lean-setup`. They take about a quarter of an hour and
are skipped unless asked for:

```sh
PI_LEAN_TESTS=1 uv run pytest tests/test_lean_real.py
```

Never run two Lean checks at once, a test run included: each judge run needs
about 25 GB.

## Cloud resources

Pi's AWS resources are provisioned by [Jaws](https://github.com/Jaws-Platform/jaws)
from [`jaws.yaml`](jaws.yaml), as the project `pi-prover`. Today that is one
private, versioned bucket, `jaws-pi-prover-artifacts`, which keeps the record
of every published run under `data/runs/<run>/`. Training will add a task
runner to the same project.

## Layout

```text
PI_PROJECT.md    the project brief
jaws.yaml        the Jaws project file: Pi's cloud resources
benchmarks/      benchmark definitions: a pinned problem file, a frozen subset of one, or a Lean project pinned by commit
configs/         run configurations: a pinned checkpoint, its generation settings, and the Lean instruction and limits
data/            fetched problem files and Lean checkouts, never committed
docs/            the grading rules for answers and for Lean proofs, and the run records
experiments/     the experiment log, and the record of each run it cites
src/pi/          the Python package
tests/           tests, run with pytest; lean_cases/ holds the Lean grader's captured cases
scripts/         the local check suite, the repository settings and the choice of development problems
tools/           the commit message rule
```

## Development

Pi uses [uv](https://docs.astral.sh/uv/), which installs the pinned Python
(3.13) and the dependencies:

```sh
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

## Contributing

Every change reaches `main` through a pull request with a Conventional
Commit title, and commits are a single line. [CONTRIBUTING.md](CONTRIBUTING.md)
has the setup and the rules; coding agents read [AGENTS.md](AGENTS.md).

## License

[MIT](LICENSE)
