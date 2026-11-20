# Pi

Pi is a local-first mathematical reasoning project. The goal is to ask an open-weight model for a proof and get back a Lean 4 file that can be checked independently. Pi should be able to propose intermediate lemmas, prove them, and use Lean’s feedback to revise an argument. Given a compute budget, it should return either a complete, `sorry`-free proof or a record of where it stopped.

The research question is whether a model small enough to run on a personal laptop can, after math-specific fine-tuning, solve more unseen problems than its original checkpoint and eventually outperform a larger model on the same tasks. **The first deliverable is a reproducible score for the original checkpoint.** Training comes after that measurement.

## Milestone 1 — Establish the local baseline

Use the MacBook Pro with an M3 Max and 48 GB of unified memory for inference and grading. This milestone should cost $0 in cloud compute.

1. **Get one checkpoint running repeatably.** Start with the Qwen3-14B setup already used on this Mac. Record the exact weights, tokenizer, quantization, runtime version, and launch command. If a fresh backend is needed, MLX LM is a candidate. Run a representative problem at the intended context and output lengths. Measure peak memory, swap growth, tokens per second, and elapsed time. A model that loads still has to finish proofs at a practical speed. [Qwen3-14B model card](https://huggingface.co/Qwen/Qwen3-14B) · [MLX LM](https://github.com/ml-explore/mlx-lm)
2. **Choose a benchmark and freeze the grading rules.** Start with MATH-500 for natural-language problem solving. Give the model only the problem text. Extract its final answer and score mathematical equivalence with a pinned grader. Test the grader on equivalent forms such as `1/2` and `0.5`, an incorrect answer, and a missing answer. Use separate development problems to refine prompts and debug grading. [MATH-500 dataset](https://huggingface.co/datasets/HuggingFaceH4/MATH-500)
3. **Run one attempt per problem.** Fix the prompt, reasoning mode, sampling settings, and token and time limits before the scored run. Use the development run to estimate laptop hours. Run all 500 problems if practical, or freeze a smaller list of IDs in advance and label the result as a subset. Report correct answers divided by all selected problems. Count malformed answers and model timeouts as unsolved. Mark interrupted runs incomplete and resume them by problem ID.
4. **Preserve the experiment.** Save one record per problem with its ID, raw response, extracted answer, verdict, token count, and elapsed time. Alongside it, save the command, configuration, code revision, model and dataset revisions, and grader version. Publish the numerator, denominator, percentage, and runtime in the project’s experiment log. If another open-weight model looks promising, compare it on the development set for accuracy and speed, and check that its license and estimated training cost suit the project before selecting it for fine-tuning.

**Done when** a fresh checkout can run a small evaluation on the Mac with one documented command after setup, and the saved predictions can regenerate the first baseline report without loading the model. A modest score is a successful first milestone if it can be reproduced and explained.

## Milestone 2 — Measure proof writing with Lean

Start with a fixed set of formal theorem statements, such as a pinned subset of miniF2F for Lean 4. Use the benchmark’s compatible Lean and mathlib revisions. Supply the imports, hypotheses, and theorem statement. Have the model fill in only the proof body. For this first proof baseline, give it one attempt and let Lean grade the result afterward. Report the fraction of theorems proved alongside the MATH-500 answer accuracy. These scores answer different questions. [miniF2F for Lean 4](https://github.com/yangky11/miniF2F-lean4)

A proof passes when Lean checks the original theorem in a clean environment and its axiom dependencies are all on the recorded allowlist for the benchmark. Inspect the theorem with `#print axioms` and reject any dependence on `sorryAx` or a newly introduced axiom, including through helper lemmas. Test the grader with a valid proof, a proof containing `sorry`, and a helper that assumes the conclusion. Save accepted proof files so anyone can replay them. [Lean’s reference on axioms](https://lean-lang.org/doc/reference/latest/Axioms/)

## Experiments after the baselines

| Experiment | Question | Comparison |
| --- | --- | --- |
| Lean-guided revision | Can the original checkpoint use a goal state or error message to finish a proof? | Compare feedback-guided attempts with independent attempts from the same checkpoint under the same total generation and time limits. |
| Fine-tuning on AWS | Does training on mathematical proofs improve the small model? | Evaluate the original and tuned checkpoints on the same Mac with matched quantization, prompts, grader, and inference budget. Report newly solved and newly missed problems. |
| Larger-model comparison | Can the specialized model beat a larger open-weight model on these tasks? | Run both against the same held-out problems and scoring rules. Report accuracy, elapsed time, and peak memory for each. |

Keep evaluation problems, their solutions, and close variants out of Pi’s training data. Public benchmarks may already be familiar to a model from pretraining. Before claiming improvement on unseen mathematics, repeat the comparison on a fresh held-out set, including undergraduate theorems representative of the intended use.

For the eventual natural-language interface, show the formal statement alongside the original request so the user can check that the translation captures the intended mathematics. Lean certifies the proof of that formal statement. During search, Pi can introduce a lemma such as “the product of two odd integers is odd,” but it must supply a proof or cite an existing theorem before using the result.

## Cost and project ownership

Keep source code, evaluation configurations, and experiment reports in the Pi GitHub repository under the planned organization. Run routine inference and benchmarks on the Mac. Use AWS for time-limited training jobs and durable artifacts such as checksummed checkpoints in S3. Aim to spend a few hundred dollars across the project, with roughly $1,000 as a possible upper bound. Before each training experiment, write down the hypothesis, estimated cost, and stopping condition. Record actual spend beside the resulting score.
