# Experiment log

Each entry cites what was kept from the run. A record written by `pi` names
the exact checkpoint, runtime, configuration and code revision of the run it
describes, and holds the model's full reply. An entry says so when a run was
ad hoc and kept less.

## 2026-11-20: the original checkpoint runs at a practical speed

**Question.** Does Qwen3-14B, as already set up on the Mac, finish a
representative problem at a practical speed, and does it do so repeatably?

**Answer.** Yes to both. It solved the problem in a little over two minutes
using a fifth of the machine's memory, and a second run reproduced the reply
token for token. Repeatability holds only from a fresh load of the model.

**Setup.**

| | |
| --- | --- |
| Machine | MacBook Pro (Mac15,9), Apple M3 Max, 48 GB, macOS 26.6.2 |
| Checkpoint | `qwen3:14b` on Ollama: 14.8B parameters, Q4_K_M, digest `bdbd181c33f2` |
| Runtime | Ollama 0.40.13 |
| Settings | Reasoning on, temperature 0.6, top-p 0.95, top-k 20, seed 1, 16,384-token context, 8,192-token output limit |
| Problem | One original problem in the style of the harder MATH problems, from no benchmark. Its answer is 12. |
| Command | `uv run pi probe --config configs/qwen3-14b.toml` |

**Result.**

| Measurement | Value |
| --- | --- |
| Finished | Yes, with the correct answer |
| Output tokens | 2,487 |
| Speed | 19.0 tokens per second |
| Elapsed | 132.9 s, of which 1.6 s loading the model |
| Peak memory | 10.1 GiB, summed over the Ollama server and the process serving the model |
| Swap growth | None |

Record: [record.json](2026-11-20-checkpoint-probe/record.json). Its code
revision, `a21b775`, is the commit on the pull request branch the probe ran
from; the squash merge gave `main` a different one.

**Repeatability.** With the seed fixed, the reply still depends on whether the
model already holds the prompt in its cache. In an ad hoc comparison, the
probe's request was sent four times: twice to a freshly loaded model and twice
to a model that had just answered the same prompt. Each pair agreed with
itself, at 2,487 and 2,064 tokens, and the two pairs differed from each other
after the first 1,203 characters. All four answered 12.

The probe therefore unloads the model before it runs. With that in place, a
second probe returned the same reply as the recorded one, token for token, at
19.4 tokens per second. Only the recorded run is committed.

**What it means for the baseline.**

- **Memory is not a constraint.** The peak was 10.1 GiB of 48 GB, with no
  swap, at a 16,384-token context.
- **Time is the constraint.** *Note added after the development run:* this
  probe and the sample below ran on battery, in Low Power Mode. On mains the
  same checkpoint generates about 27 tokens per second, and the development
  run entry has the current estimate of laptop hours. If every MATH-500
  problem took as long as this one, 500 problems would take about 18 hours. If every problem ran to the
  8,192-token output limit, they would take about 60 hours. One problem cannot
  say where the average lies; the development run has to measure that before
  the limits are fixed.
- **The scored run needs a defined starting state for each problem.** A runner
  that keeps the model loaded between problems will not reproduce a problem's
  reply in isolation. Unloading before each problem cost 1.3 to 1.6 s here,
  roughly a quarter of an hour over 500 problems.
- **The limits and the seed in the configuration are provisional.** The brief
  has them fixed before the scored run.


## 2026-11-20: the checkpoint boxes its final answer without being asked

**Question.** Given only the problem text, how does the checkpoint present its
final answer, and does the grader read it?

**Answer.** All eight replies ended with exactly one boxed final answer, and
the grader read every one of them correctly. That is the evidence for grading
rules version 1, which accept a boxed or announced final answer and nothing
else.

**Setup.** Eight original problems from no benchmark, one per answer type.
The checkpoint and settings are those of `configs/qwen3-14b.toml`, with a
fresh load before each problem.

This was an ad hoc sample, run with a throwaway script and not a `pi`
command, so there is no full record. The problems, references, replies and
timings are kept in
[tests/replies/answer-format-sample.json](../tests/replies/answer-format-sample.json),
where the grader's tests use them.

**Result.**

| Answer type | Reference | Final answer as written | Verdict | Output tokens | Seconds |
| --- | --- | --- | --- | --- | --- |
| Fraction | `\frac{3}{28}` | `\boxed{\dfrac{3}{28}}` | correct | 2,203 | 113.5 |
| Interval | `[2,3]` | `\boxed{[2, 3]}` | correct | 1,493 | 77.3 |
| Ordered pair | `(2,1)` | `\boxed{(2, 1)}` | correct | 1,749 | 90.7 |
| Radical | `8\sqrt{2}` | `\boxed{8\sqrt{2}}` | correct | 2,174 | 118.9 |
| Word | `\text{Tuesday}` | `\boxed{Tuesday}` | correct | 3,174 | 180.6 |
| Polynomial | `x^3-7x-6` | `\boxed{x^3 - 7x - 6}` | correct | 3,199 | 174.8 |
| Degrees | `70` | `\boxed{70}` | correct | 1,494 | 85.2 |
| Money | `\$20.40` | `\boxed{20.40}` | correct | 1,564 | 85.7 |

**What it means for the baseline.**

- **The strict extraction rule fits what the model does.** Nothing asks it to
  box its answer, and it did so every time, so the grader does not need to
  guess an answer from the last number in a reply.
- **Eight problems cannot show that it always will.** The development run
  should count `missing` verdicts and look at each one before the rules are
  frozen.
- **Time per problem agrees with the probe.** The mean was 2,131 tokens and
  116 s, from 77 s to 181 s. These problems are easier than the hardest in
  MATH, so this is not an estimate for MATH-500.

## 2026-11-20: development run, 28 of 30 correct

**Question.** What does a problem really cost, and do the provisional limits
and the grading rules hold up on real MATH problems?

**Answer.** The checkpoint solved 28 of the 30 development problems. Both
misses ran out of output tokens; no reply was wrong or unreadable. A MATH-500
run would take roughly 16 to 19 hours on mains power. The run also showed
that this Mac generates a third slower on battery, which changes time but not
verdicts.

**This is not a MATH-500 score.** The development problems come from MATH's
training split, which the checkpoint may have seen in pretraining.

**Setup.** `benchmarks/math-dev.toml`: 30 MATH training problems, frozen in
advance in the proportions of MATH-500's levels. The checkpoint, runtime and
settings are those of `configs/qwen3-14b.toml`, graded under rules version 1.
One attempt per problem, each from a fresh load. The run was one
uninterrupted session of 87 minutes from a clean checkout of `ba7f663`:

```sh
uv run pi eval --config configs/qwen3-14b.toml --benchmark benchmarks/math-dev.toml --out experiments/2026-11-20-math-dev
```

**Result.**

| Measurement | Value |
| --- | --- |
| Correct | 28 of 30 (93.3%) |
| Unsolved | 2, both `cut_off` at the 8,192-token output limit |
| `incorrect`, `missing`, `timed_out` | 0 |
| Output tokens per problem | mean 3,660, median 2,602 |
| Time per problem | mean 173.8 s, median 147.9 s, longest 457.9 s |
| Peak memory | 10.8 GiB |
| Swap growth | None |

Kept from the run, in [2026-11-20-math-dev](2026-11-20-math-dev/):
[report.md](2026-11-20-math-dev/report.md), which `pi report` rebuilds from
the other two files; `run.json`; and `results.jsonl`, with every reply. The
records hold problem ids and the model's replies, not the dataset's problem
texts or solutions.

**What it means for the baseline.**

- **The output limit is what costs problems.** Two attempts hit 8,192 tokens,
  and three more finished within 15% of it (7,951, 7,425 and 7,182 tokens,
  all correct). One of the two cut-off attempts had finished reasoning and
  was writing out an answer equal to the reference. The other was still
  working. A higher limit would probably recover some of these, at a cost in
  time. The limit has to be fixed before the scored run.
- **The time limit never bound.** The slowest attempt took 458 s against a
  limit of 600 s. An attempt that runs to 8,192 tokens takes about 450 s on
  battery, so the token limit is always reached first while the speed stays
  above 14 tokens per second. Raising the output limit means raising the time
  limit with it.
- **The strict extraction rule cost nothing.** All 28 finished replies ended
  in a boxed answer. None was `missing`.
- **The power source changes the speed.** The charger was connected part way
  through. Problems 1 to 20 ran on battery, where macOS was set to Low Power
  Mode, at 18.4 tokens per second. Problems 22 to 30 ran on mains, in High
  Power Mode, at 27.0. Under the current limits this affects time only, but
  the records do not say which problems ran on which: a run should record its
  power source, and a scored run should stay on mains throughout.
- **Laptop hours for MATH-500.** At this run's mean of 3,660 tokens, 500
  problems take about 19 hours on mains and about 28 on battery. That is
  probably high: Intermediate Algebra used far more tokens than any other
  subject (mean 6,572) and is 30% of this sample but 19% of MATH-500.
  Weighting by MATH-500's subjects gives about 16 hours on mains. The subject
  samples are small, from one to nine problems, so 16 to 19 hours is a range
  and not a forecast.
