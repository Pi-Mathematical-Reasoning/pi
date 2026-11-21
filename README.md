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

**Nothing runs yet.** The repository holds the brief and an empty Python
package. The first deliverable is a reproducible score for the original
checkpoint; training comes after that measurement.

| Stage | What it measures | State |
| --- | --- | --- |
| Milestone 1: local baseline | Answer accuracy on MATH-500, one attempt per problem, run on a MacBook Pro | Not started |
| Milestone 2: proof writing | Fraction of a pinned miniF2F subset proved, graded by Lean 4 | Not started |
| Later experiments | Lean-guided revision, fine-tuning on AWS, a larger-model comparison | Not started |

## Layout

```text
PI_PROJECT.md    the project brief
src/pi/          the Python package, empty so far
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
