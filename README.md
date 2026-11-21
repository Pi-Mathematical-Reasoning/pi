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

**One thing runs so far: the checkpoint probe.** It loads the pinned
checkpoint, gives it one problem and records how fast it went and what it cost
the machine. Nothing is graded yet. The first deliverable is a reproducible
score for the original checkpoint; training comes after that measurement.

| Stage | What it measures | State |
| --- | --- | --- |
| Milestone 1: local baseline | Answer accuracy on MATH-500, one attempt per problem, run on a MacBook Pro | In progress: the checkpoint is pinned and probed; grading and the scored run are next |
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
  second, elapsed time, peak memory and swap growth.

Memory is measured over the Ollama server and the processes it launches, and
swap growth is measured on macOS only.

## Layout

```text
PI_PROJECT.md    the project brief
configs/         run configurations: a pinned checkpoint and its generation settings
experiments/     the experiment log, and the record of each run it cites
src/pi/          the Python package
tests/           tests, run with pytest
scripts/         the local check suite and the repository settings
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
