# Grading rules

How Pi decides whether a reply solved a problem. These are **rules version
1**, implemented in [`src/pi/grading.py`](../src/pi/grading.py). The brief has
the rules frozen before the scored run: after that, a change here is a new
rules version, and scores under different versions are not compared.

## What is graded

Only the visible text of the reply. The model's reasoning is never graded, so
an answer that appears there and not in the reply does not count.

## Finding the final answer

The final answer is the **last boxed expression** in the reply, `\boxed{...}`.
If the reply has none, an expression in math delimiters that it introduces
with the words "final answer is" is used instead. No other number or
expression in the text is ever taken for the answer, because that would credit
replies that never committed to one.

| Reply | Final answer |
| --- | --- |
| `... so $x^2 = \boxed{4}$. Then the sum is $\boxed{12}$.` | `12`, the last box |
| `The answer is $\boxed{12}$. This took 3 steps.` | `12`; the 3 is ignored |
| `The solutions are $\boxed{2}$ and $\boxed{4}$.` | `2` and `4` together, as one answer |
| `After simplifying, the final answer is $\frac{1}{2}$.` | `\frac{1}{2}`, announced |
| `So we get 12.` | None |
| `Thus, $x = 12$.` | None |
| An empty reply, or one that gives up | None |

The model is given only the problem text, so nothing asks it to box its
answer. It does so anyway: in a sample of eight original problems of different
answer types, every reply ended with one boxed answer. The
[experiment log](../experiments/README.md) has the sample.

## Comparing with the reference

The final answer and the reference answer are both parsed as mathematics and
compared for equivalence, not as text.

| Reference | Counts as correct | Does not |
| --- | --- | --- |
| `\frac{1}{2}` | `0.5`, `1/2`, `\frac{2}{4}` | `\frac{1}{3}` |
| `2\sqrt{3}` | `\sqrt{12}` | |
| `x^2+2x+1` | `(x+1)^2` | `x^2+2x-1` |
| `(3,\frac{\pi}{2})` | `(3, \pi/2)` | `(\frac{\pi}{2}, 3)`: order matters in a tuple |
| `[2,5)` | `[2, 5)` | `[2,5]` |
| `1,2,3` | `3, 2, 1`: order does not matter in a list of values | `1,2` |
| `\text{Evelyn}` | `Evelyn`, in any letter case | `\text{Briana}` |
| `12` | `12.0`, `x = 12` | `-12`, `13` |
| `\frac{1}{3}` | `0.3333333333` | `0.333`: decimals are compared to six places |
| `6` | | `six`: a number written as a word |

Three things are deliberately lenient, because benchmark references are not
consistent about them:

- **Units, degree signs and currency symbols are ignored.** `90^\circ` matches
  `90`, `10\text{ cm}` matches `10`, and `\$18.90` matches `18.9`.
- **A percentage matches either reading.** A reference of `10\%` accepts
  `10\%`, `10` and `0.1`.
- **A base subscript is ignored.** `4210_{5}` matches `4210`.

## Verdicts

| Verdict | Meaning |
| --- | --- |
| `correct` | The final answer is equivalent to the reference |
| `incorrect` | A final answer was found and is not equivalent, or could not be parsed |
| `missing` | No final answer was found |

Only `correct` counts as solved. A reference answer that cannot be parsed is
an error in the benchmark data: grading stops with an error and produces no
verdict. A benchmark run checks every reference before its first attempt.

## Attempts that hit a limit

A benchmark run gives each problem one attempt, within a time limit and an
output-token limit. An attempt that hits either is unsolved, whatever it had
written, and is not graded.

| Verdict | Meaning |
| --- | --- |
| `timed_out` | The model was still generating at the time limit |
| `cut_off` | The reply stopped before the model finished it, in practice at the output limit |

## The grader

Extraction and comparison are done by
[math-verify](https://github.com/huggingface/math-verify), pinned at 0.9.0 in
`pyproject.toml`, with its dependencies pinned in `uv.lock`. A saved verdict
names the rules version and the versions of math-verify, latex2sympy2-extended
and sympy that produced it.

Try the grader on a reply or on a saved record:

```sh
uv run pi grade --reference '\frac{1}{2}' --reply 'So the answer is $\boxed{0.5}$.'
uv run pi grade --reference 12 --record experiments/2026-11-20-checkpoint-probe/record.json
```
