# Pi

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

**Three things run so far: the checkpoint probe, the answer grader and the
benchmark run.** The probe loads the pinned checkpoint, gives it one problem
and records how fast it went and what it cost the machine. The grader finds
the final answer in a reply and decides whether it matches a reference. The
benchmark run attempts every problem of a pinned benchmark once and reports
the score. It has been run on the 30 development problems and not yet on
MATH-500. The first deliverable is a reproducible score for the original
checkpoint; training comes after that measurement.

| Stage | What it measures | State |
| --- | --- | --- |
| Milestone 1: local baseline | Answer accuracy on MATH-500, one attempt per problem, run on a MacBook Pro | In progress: the development run is done and the limits are set; the scored MATH-500 run has not been started |
| Milestone 2: proof writing | Fraction of a pinned miniF2F subset proved, graded by Lean 4 | Not started |
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
- **The model runner's launch settings.** These include the cache type and
  flash attention, which change the numbers. If they change part way through,
  the run stops before keeping the attempt.
- **Awake attempts only.** An attempt the Mac slept through is thrown away and
  made again, because its time measured the sleep. A fresh load makes the new
  attempt write the same reply.

A problem takes two to three minutes on average and up to ten, so the 30
development problems take about an hour and a half. On a Mac, run on mains
power: this checkpoint generates a third slower on battery. Start a long run
with `caffeinate -i` in front of the command so the machine does not sleep
part way.

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
benchmarks/      benchmark definitions: a pinned problem file, or a frozen subset of one
configs/         run configurations: a pinned checkpoint and its generation settings
docs/            the grading rules
experiments/     the experiment log, and the record of each run it cites
src/pi/          the Python package
tests/           tests, run with pytest
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
