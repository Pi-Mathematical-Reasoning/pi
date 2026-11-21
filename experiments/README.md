# Experiment log

Each entry cites a record committed beside it. A record names the exact
checkpoint, runtime, configuration and code revision of the run it describes,
and holds the model's full reply.

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
- **Time is the constraint.** If every MATH-500 problem took as long as this
  one, 500 problems would take about 18 hours. If every problem ran to the
  8,192-token output limit, they would take about 60 hours. One problem cannot
  say where the average lies; the development run has to measure that before
  the limits are fixed.
- **The scored run needs a defined starting state for each problem.** A runner
  that keeps the model loaded between problems will not reproduce a problem's
  reply in isolation. Unloading before each problem cost 1.3 to 1.6 s here,
  roughly a quarter of an hour over 500 problems.
- **The limits and the seed in the configuration are provisional.** The brief
  has them fixed before the scored run.
