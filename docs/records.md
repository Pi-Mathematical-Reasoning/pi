# Run records

What a run directory holds, field by field, for anyone analysing a run in a
notebook. Both files are JSON: `results.jsonl` has one result per line and
loads directly with `spark.read.json` or `pandas.read_json(..., lines=True)`;
`run.json` is one object. A run published with `pi publish` has the same files
under `s3://jaws-pi-prover-artifacts/data/runs/<run>/`.

Fields marked *live* can only be measured while the problem runs. Runs made
before a field existed simply lack it.

A run on a Lean benchmark has the same files and fields, with the additions
in [Lean runs](#lean-runs) below.

## `results.jsonl`: one line per problem

| Field | Meaning |
| --- | --- |
| `session` | Index into `run.json`'s `sessions`: which session, and so which commit and machine, produced it |
| `id`, `subject`, `level` | The problem, as the benchmark names it. For a Lean theorem, `subject` is its family, read from its name (`mathd_algebra`, `mathd_numbertheory`, `amc12`, `aime`, `imo`, `induction`, `algebra`, `numbertheory` or `other`), and `level` is null |
| `verdict` | `correct`, `incorrect`, `missing`, `cut_off` or `timed_out` ([grading rules](grading.md)); for a Lean run, `proved`, `failed`, `missing`, `cut_off` or `timed_out` ([Lean rules](lean-grading.md)) |
| `answer` | The final answer the grader read, or null. Always null in a Lean run |
| `response` | `content` (the visible reply), `thinking` (the reasoning) and `done_reason` (`stop`, or `length` at the output limit). Null if timed out |
| `prompt_tokens`, `cached_prompt_tokens`, `output_tokens` | Token counts as Ollama reported them. Output tokens include the reasoning |
| `started_at`, `ended_at` | *Live.* UTC timestamps of the attempt |
| `elapsed_seconds` | *Live.* Wall-clock seconds of the attempt, measured by `pi` |
| `load_seconds`, `prompt_seconds`, `output_seconds`, `total_seconds` | *Live.* Ollama's own breakdown: loading the model, reading the prompt, generating, and all of it |
| `output_tokens_per_second` | `output_tokens / output_seconds` |
| `unload_seconds` | *Live.* Time spent unloading the previous model before the attempt |
| `progress` | *Live.* `[tokens, seconds]` pairs, seconds since the request was sent: the first token (time to first token), every 256th, and the last. Shows whether generation slows as the reply grows. Tokens are counted as streamed lines, about one token each |
| `peak_memory_bytes` | *Live.* Peak resident memory of the Ollama server and its runner during this attempt |
| `swap_used_bytes` | *Live.* Swap in use just after the attempt |
| `thermal` | *Live.* `pmset -g therm` as printed after the attempt, one line each |
| `power` | *Live.* `source` (`AC Power` or `Battery Power`) and the energy `mode` `pmset` reports |
| `discarded_attempts` | *Live.* Attempts thrown away because the Mac slept, each with `started_at`, `ended_at` and `reason`. Usually empty |
| `metrics` | *Live.* Every count and timing Ollama reported, in its own units (durations in nanoseconds) |

Not recorded, because they can be derived later from what is: the split of
output tokens between reasoning and answer (re-tokenize `response` with Qwen's
tokenizer), the problem's length, and any feature of the reply's text.

## `run.json`: the run as a whole

| Field | Meaning |
| --- | --- |
| `complete` | True once every problem has a result |
| `runtime`, `model` | Ollama's version; the checkpoint's name, digest, weights hash, quantization, default parameters and tokenizer settings |
| `generation` | The settings every attempt used |
| `benchmark` | Name, URL, file SHA-256, whether it is a subset or `scored`, and the problem ids in order |
| `grader` | Grading rules version and library versions |
| `runner` | The model runner's launch command, minus its port. Held fixed for the whole run |
| `sessions` | One per invocation of `pi eval`: `started_at`, `ended_at` (null if it was killed), `command`, `code` (commit and whether the tree was clean), `machine`, `problem_file` (where the problem file came from), `weights_verified`, `attempted`, and for sessions that ended, peak memory, swap growth and the runner commands seen |

## Beside them

| File | Written by | Meaning |
| --- | --- | --- |
| `report.md` | `pi report` or `pi audit` | The human-readable report, rebuilt from the two files above |
| `audit.json` | `pi audit` | Every audit check's outcome, and the SHA-256 and size of each file audited |
| `proofs/<id>.lean` | `pi eval`, Lean runs only | The submission file as checked, one per `proved` result. Published to the bucket, never committed |
| `_manifest.json` | `pi publish`, in the bucket only | The files published, their checksums, and the audit's outcome. Written last |

## Lean runs

A run on a Lean benchmark is graded by the [Lean rules](lean-grading.md). Its
results keep every field above, with `answer` always null, and add two
fields directly after `metrics` and before `discarded_attempts`:

| Field | Meaning |
| --- | --- |
| `proof` | The code block taken from the reply, before it was built into a file. Null for `missing`, `cut_off` and `timed_out` |
| `lean` | The check, below. Null for `missing`, `cut_off` and `timed_out`, which are not checked |

`lean` holds:

| Key | Meaning |
| --- | --- |
| `reason` | Why the check failed: `lean_error`, `sorry`, `statement_changed`, `axioms`, `kernel_rejected`, `check_timed_out` or `judge_error`. Null when `proved` |
| `exit_code` | The exit status of the last compile that ran: the submission's, or the reference's when the reference compile failed or timed out. Null if it was killed at its limit |
| `messages` | That compile's standard output, then its standard error, cut to the first 20,000 characters. Lean writes one JSON message per line to standard output |
| `judge` | Null if the judge did not run. Otherwise its `exit_code` (null if killed at its limit), its saved `outcome` (the parsed `judge.json`, or null if it saved none that could be read) and its `stderr` (the first 20,000 characters) |
| `axioms` | The axioms the judge's saved outcome lists for the theorem itself. Empty if it lists none |
| `flags` | The compile-time commands found in the block, from the list in the [Lean rules](lean-grading.md#the-known-limit). Recorded whatever the verdict |
| `compile_seconds` | Wall-clock seconds of that compile |
| `judge_seconds` | Wall-clock seconds of the judge, or null if it did not run |

`run.json` for a Lean run holds the same fields as for an answer run, with
these entries in place of or beside them:

| Field | Meaning |
| --- | --- |
| `benchmark` | `name`; `kind`, always `lean`; the project's `repository`, `commit` and theorem `file`; the file's `sha256`; whether it is a `subset` or `scored`; and the theorem `ids` in order |
| `grader` | `lean_rules`, the Lean rules version; the judge's `judge_repository` and `judge_commit`; and the `allowed_axioms` |
| `lean` | The Lean environment and settings: `toolchain` (the project's `lean-toolchain`), `lean_version` (the first line of `lean --version`), `files` (the SHA-256 of the project's `lean-toolchain`, `lake-manifest.json`, `lakefile.lean` and theorem file, by name), `options` (the Lean options passed to every compile), and from the configuration's `[lean]` section the `instruction` and the `compile_time_limit_seconds` and `judge_time_limit_seconds` |

Each session's `problem_file` is the project's repository and commit, as
`<repository>@<commit>`. A session refuses to resume a run whose `benchmark`,
`grader` or `lean` differ from its own.

Each `proved` result's submission file is written to `proofs/<id>.lean`, the
file exactly as Lean and the judge checked it. Every attempt at a theorem
first removes that theorem's proof file, so a file left by an attempt that
never reached the records is removed when the theorem is attempted again.
The files restate the benchmark's header and statement, so they are
published to the bucket with the run and never committed; they can also be
rebuilt from `results.jsonl` and the pinned benchmark. For a Lean run,
`audit.json` covers each file in `proofs/` as well as `run.json`,
`results.jsonl` and `report.md`, and `pi publish` uploads exactly the files
the audit names.
