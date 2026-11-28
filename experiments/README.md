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
  probe and the sample below ran on battery. On mains the same checkpoint
  generates about 27 tokens per second, and the development run entry has the
  current estimate of laptop hours. If every MATH-500
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
  through. Problems 1 to 20 ran on battery at 18.4 tokens per second, and
  problems 22 to 30 ran on mains at 27.0. macOS's energy mode differs between
  the two on this Mac: `pmset` reports `powermode 1` on battery and
  `powermode 2` on mains. Under the current limits this affects time only.
  This run's records do not say which problems ran on which. Runs made since
  record the power source of every attempt, and a scored run should stay on
  mains throughout.
- **Laptop hours for MATH-500.** At this run's mean of 3,660 tokens, 500
  problems take about 19 hours on mains and about 28 on battery. That is
  probably high: Intermediate Algebra used far more tokens than any other
  subject (mean 6,572) and is 30% of this sample but 19% of MATH-500.
  Weighting by MATH-500's subjects gives about 16 hours on mains. The subject
  samples are small, from one to nine problems, so 16 to 19 hours is a range
  and not a forecast.

## 2026-11-20: the output limit is set to 16,384 tokens

**Question.** Would the two development problems that were cut off at 8,192
output tokens finish with more room?

**Answer.** Yes. Both finished, and both were correct. One needed 399 more
tokens and the other 5,304 more. The output limit is now 16,384 tokens, with
the context and the time limit raised to match.

**Setup.** The two cut-off problems, attempted again with a 16,384-token
output limit, a 24,576-token context and a 1,200 s time limit. Nothing else
changed. The Mac was on mains throughout. The run was made from a clean
checkout of `7c5f762`, which is older than power-source recording, so its
records do not carry the power source.

The definitions the run used are kept beside its results as `config.toml` and
`benchmark.toml`. They were in `runs/output-limit/` when the run was made,
which is the path the recorded command shows.

**Result.**

| Problem | At 8,192 | At 16,384 | Output tokens | Time |
| --- | --- | --- | --- | --- |
| `train/intermediate_algebra/290.json` | cut_off | correct | 13,496 | 467 s |
| `train/intermediate_algebra/1720.json` | cut_off | correct | 8,591 | 296 s |

Peak memory was 11.5 GiB, up from 10.8 GiB with the larger context, and
there was no swap. Kept from the run, in
[2026-11-20-output-limit](2026-11-20-output-limit/):
[report.md](2026-11-20-output-limit/report.md), `run.json` and
`results.jsonl`.

**What it means for the baseline.**

- **The new limits change where an attempt stops and nothing else.** In both
  problems the reasoning matched the cut-off attempt character for character,
  up to the point where that attempt had been cut. So the 28 problems that
  finished under the old limits should come out the same, which makes the
  development score 30 of 30 under the new ones. That is inferred: the 28
  were not attempted again.
- **The cost is small.** Over the 30 development problems the higher limit
  adds 5,703 output tokens, about 5%. For MATH-500 that is roughly an hour,
  for an estimate of 17 to 20 hours on mains.
- **The time limit stays out of the way.** At 1,200 s it is reached only
  below 14 tokens per second, and this Mac ran at 18.4 on battery.
- **It is still a limit.** The harder of the two problems used 82% of it. A
  problem that needs more than 16,384 tokens is unsolved by rule.

## 2026-11-21: MATH-500 baseline, pre-registered

**Status: run, audited, reproduced and published.** The result is the next
entry, [477 of 500 correct](#2026-11-26-math-500-baseline-477-of-500-correct).
This entry fixes everything about the
scored run before it starts. The pull request that adds it is merged before the
first attempt, so the git history shows the rules came before the results.
Nothing below changes once the run starts. If something must change, the run is
abandoned, its records are kept, and a new run starts in a new directory under
a new entry.

**Question.** What fraction of the 500 MATH-500 problems does the original
Qwen3-14B checkpoint answer correctly, with one attempt each, on this Mac?

**Fixed in advance.**

| | |
| --- | --- |
| Problems | All 500 of MATH-500 (`benchmarks/math-500.toml`), file SHA-256 `35dc41080a36`. Not a subset |
| Score | Problems whose verdict is `correct`, divided by 500 |
| Checkpoint | `qwen3:14b` on Ollama 0.40.13, digest `bdbd181c33f2`, weights `sha256-a8cc1361f314` |
| Settings | `configs/qwen3-14b.toml`: reasoning on, temperature 0.6, top-p 0.95, top-k 20, seed 1, 24,576-token context, 16,384-token output limit, 1,200 s time limit, batch size 1,024, weights memory-mapped |
| Prompt | The problem text alone, as the only user message |
| Grader | Rules version 1 ([docs/grading.md](../docs/grading.md)), math-verify 0.9.0 |
| Unsolved | `incorrect`, `missing`, `cut_off` and `timed_out` all count as unsolved |

**How it is run.**

- From a clean checkout of a commit that contains this entry, on mains power,
  with the lid open:

  ```sh
  caffeinate -i uv run pi eval --config configs/qwen3-14b.toml \
    --benchmark benchmarks/math-500.toml --out runs/2026-11-21-math-500
  ```

- The records are written under the git-ignored `runs/`. A scored run refuses
  uncommitted changes, and records written into the repository would count as
  one. They are copied into `experiments/` when the run is complete.
- `pi eval` enforces the rest: verified weights at each session, mains power
  at each attempt, a fixed runner launch, and no attempt the Mac slept through.
  Each session is on record from its start. An interruption is resumed with
  the same command.

**After the run, in this order.**

1. **Audit** the records with `pi audit`. It checks the problem file's
   checksum, that each problem has exactly one result, and each verdict
   against the saved reply under the same grader. It also checks the report
   rebuilds from the records, then writes a SHA-256 manifest of the files.
2. **Reproduce** five problems chosen in advance with seed 20261121, each from
   a fresh load, and compare the replies with the recorded ones:
   `test/algebra/305.json`, `test/counting_and_probability/25149.json`,
   `test/geometry/456.json`, `test/intermediate_algebra/232.json` and
   `test/precalculus/675.json`.
3. **Publish** the audited records to `jaws-pi-prover-artifacts` with
   `pi publish`, under `data/runs/2026-11-21-math-500/`, with `_manifest.json`
   written last.
4. **Commit** the records, the audit and the report to this repository, with
   the result in a new entry below this one.

**Pre-flight, done before this entry was merged.** A scored run of two
development problems, never MATH-500, from a fresh clone of `pi`:

- On battery, it stopped before its first attempt and said how to resume.
- On mains, it was killed with `SIGKILL` after its first result and resumed.
  The result survived, the killed session stayed on record, and the run
  completed, 2 of 2 correct. The S3 mirror served the problem file, and the
  weights file verified in each session.
- `pi audit` passed it, and failed a copy with one altered answer.
- It found one bug: the report assumed every session had ended cleanly, so a
  killed session crashed it. It was fixed in pi#19 before this entry.
- The run is published to `jaws-pi-prover-artifacts` as
  `data/runs/2026-11-21-preflight/`, the first use of `pi publish`.

**Amended on 2026-11-21, before the run started.** Two changes, both found
while preparing it:

- **Two launch settings are pinned:** batch size 1,024 and memory-mapped
  weights. Ollama otherwise picks both from free memory at each load. A check
  run on four development problems caught it halving the batch and turning
  memory-mapping off part way through (`reason=metal_partial` in its log), and
  the batch size changes the arithmetic. The pinned values are the ones every
  earlier run was launched with.
- **Replies are streamed,** so that each result can record the time to first
  token and how far the reply had got every 256 tokens, along with Ollama's
  full timing breakdown, per-problem memory, swap and thermal state, and any
  attempt thrown away ([docs/records.md](../docs/records.md)). Streamed
  replies matched the recorded unstreamed ones character for character on the
  same development problems.

**Expected cost.** About 17 to 20 hours of the Mac on mains, from the
development run's mean of 3,660 output tokens at 27 tokens per second, plus
about 5% for the higher output limit. Peak memory about 11.5 GiB. No cloud
compute.

**What would be surprising.** The 30 development problems scored 28 of 30, and
an inferred 30 of 30 under these limits. Those problems come from MATH's
training split, which the checkpoint may have seen in pretraining. A MATH-500
score well below that would be an honest baseline, not a sign of a fault.


## 2026-11-26: MATH-500 baseline, 477 of 500 correct

**Question.** What fraction of the 500 MATH-500 problems does the original
Qwen3-14B checkpoint answer correctly, with one attempt each, on this Mac?

**Answer.** 477 of 500, **95.4%**, under the rules fixed in the
[pre-registered entry](#2026-11-21-math-500-baseline-pre-registered) above,
with nothing changed during the run. Running out of output tokens cost far
more problems than wrong answers did: 17 replies were cut off at the
16,384-token limit and 6 gave a wrong answer. The run passed `pi audit`, five
problems chosen in advance reproduced token for token from fresh loads, and
the records are published.

**Setup.** As pre-registered: all 500 problems of `benchmarks/math-500.toml`,
`configs/qwen3-14b.toml`, grader rules version 1 with math-verify 0.9.0, one
attempt per problem from a fresh load. Both sessions ran from a clean checkout
of `20323d0`, on mains power, with the weights file verified:

```sh
caffeinate -i uv run pi eval --config configs/qwen3-14b.toml \
  --benchmark benchmarks/math-500.toml --out runs/2026-11-21-math-500
```

| Session | Started (UTC) | Ended (UTC) | Problems |
| --- | --- | --- | --- |
| 0 | 2026-11-25 06:59 | 2026-11-25 13:58 | 164 |
| 1 | 2026-11-25 16:19 | 2026-11-26 06:00 | 336 |

The second session resumed with the same command and directory.

**Result.**

| Measurement | Value |
| --- | --- |
| Correct | 477 of 500 (95.4%) |
| `cut_off` | 17, all at the 16,384-token output limit |
| `incorrect` | 6 |
| `missing`, `timed_out` | 0 |
| Model time | 20.6 h |
| Time per problem | mean 148.5 s, median 100.0 s, longest 546.0 s |
| Output tokens per problem | mean 4,719, median 3,313 |
| Speed | mean 33.2 tokens per second |
| Peak memory | 10.9 GiB |
| Swap growth | None |
| Discarded attempts | None |

| Level | Correct | | Subject | Correct |
| --- | --- | --- | --- | --- |
| 1 | 43 of 43 | | Algebra | 123 of 124 |
| 2 | 90 of 90 | | Counting & Probability | 35 of 38 |
| 3 | 103 of 105 | | Geometry | 36 of 41 |
| 4 | 124 of 128 | | Intermediate Algebra | 89 of 97 |
| 5 | 117 of 134 | | Number Theory | 62 of 62 |
| | | | Prealgebra | 79 of 82 |
| | | | Precalculus | 53 of 56 |

Kept from the run, in [2026-11-21-math-500](2026-11-21-math-500/):
`run.json`, `results.jsonl` with every reply, [report.md](2026-11-21-math-500/report.md),
which `pi report` rebuilds from the other two, and `audit.json`. They are the
files published to `jaws-pi-prover-artifacts` under
`data/runs/2026-11-21-math-500/` on 2026-11-27, byte for byte: their SHA-256
values match the published `_manifest.json`. As with the development run, the
records hold problem ids and the model's replies, not the dataset's problem
texts or solutions.

**Audit.** `pi audit` passed every check on 2026-11-26: the run is complete,
the problem file matches its checksum, each problem has exactly one result,
every saved reply grades to its recorded verdict, every result belongs to a
recorded session, the scored standard held throughout, and the report
rebuilds from the records. The problem file's source is recorded as
"unknown: fetched before sources were recorded": it was fetched before `pi`
began writing down whether a file came from the mirror or the upstream URL.
The checksum is what makes the two interchangeable, and it matched.

**Reproduction.** The five problems chosen in advance with seed 20261121 were
run again from fresh loads on 2026-11-27, from the same clean checkout, on
mains, through `pi eval` with a benchmark definition that lists only those
five ids. Every reply matched the recorded one exactly, thinking and final
text, with the same answer, verdict and token count:

| Problem | Level | Output tokens | Reply |
| --- | --- | --- | --- |
| `test/algebra/305.json` | 5 | 1,982 | identical |
| `test/counting_and_probability/25149.json` | 4 | 3,696 | identical |
| `test/geometry/456.json` | 2 | 1,871 | identical |
| `test/intermediate_algebra/232.json` | 5 | 10,097 | identical |
| `test/precalculus/675.json` | 5 | 5,209 | identical |

The reproduction run also passed `pi audit`. A first attempt on 2026-11-26
stopped before its first problem because the Mac was on battery; that session
attempted nothing and stays on record in its `run.json`. The launch command
matched the scored run's except for the local port. Kept in
[2026-11-21-math-500/reproduction](2026-11-21-math-500/reproduction/): the
benchmark definition, `compare-reproduce.py` and its output
`comparison.json`, and the run's `run.json`, `results.jsonl`, `report.md` and
`audit.json`.

**What it means.**

- **The output limit, not reasoning errors, sets most of the gap.** 15 of the
  17 cut-off replies were still thinking at 16,384 tokens and had written no
  final text; the other 2 had started it but not reached a boxed answer. 15
  were level 5, and 8 were Intermediate Algebra. Eight correct replies used
  14,000 tokens or more, the longest 16,014. The time limit never bound: no
  attempt took more than 546 s of its 1,200 s.
- **Six answers were wrong**, at levels 3 to 5: `counting_and_probability/134`,
  `prealgebra/1646`, `algebra/661`, `prealgebra/874`, `precalculus/768` and
  `geometry/465`. Every finished reply ended in a boxed answer, so the strict
  extraction rule again cost nothing.
- **The estimate held.** The pre-registration expected 17 to 20 hours and about
  11.5 GiB; the run took 20.6 hours of model time and peaked at 10.9 GiB.
- **The score sits close to the ceiling.** It is above the 28 of 30 on the
  development problems. Levels 1 and 2 were solved without a miss, and nearly
  all the remaining headroom is at level 5. MATH-500 leaves little room to show
  an improvement from fine-tuning, and the checkpoint may have seen MATH in
  pretraining, so a later comparison needs a harder or fresher benchmark
  alongside it.
