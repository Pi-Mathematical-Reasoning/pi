# Run records

What a run directory holds, field by field, for anyone analysing a run in a
notebook. Both files are JSON: `results.jsonl` has one result per line and
loads directly with `spark.read.json` or `pandas.read_json(..., lines=True)`;
`run.json` is one object. A run published with `pi publish` has the same files
under `s3://jaws-pi-prover-artifacts/data/runs/<run>/`.

Fields marked *live* can only be measured while the problem runs. Runs made
before a field existed simply lack it.

## `results.jsonl`: one line per problem

| Field | Meaning |
| --- | --- |
| `session` | Index into `run.json`'s `sessions`: which session, and so which commit and machine, produced it |
| `id`, `subject`, `level` | The problem, as the benchmark names it |
| `verdict` | `correct`, `incorrect`, `missing`, `cut_off` or `timed_out` ([grading rules](grading.md)) |
| `answer` | The final answer the grader read, or null |
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
| `_manifest.json` | `pi publish`, in the bucket only | The files published, their checksums, and the audit's outcome. Written last |
