"""A Lean benchmark in the run loop: the prompt for a theorem and the grading of its reply."""

from collections.abc import Callable
from pathlib import Path

from pi.config import LeanSettings
from pi.lean_grading import Limits, check, lean_grader_version
from pi.lean_project import LeanBenchmark
from pi.lean_statements import Theorem

PROOFS = "proofs"


def lean_prompt(instruction: str, theorem: Theorem) -> str:
    """The instruction, then the theorem's header and statement with its proof left open."""
    return f"{instruction}\n\n```lean4\n{theorem.header}\n{theorem.statement} := by\n```\n"


class LeanTask:
    """A benchmark whose reply holds a Lean proof, graded by Lean and a judge program."""

    blank: dict = {"proof": None, "lean": None}  # extra fields of an ungraded result

    def __init__(
        self,
        benchmark: LeanBenchmark,
        settings: LeanSettings,
        runner,
        environment: dict,
        out: Path,
        release: Callable[[], None] = lambda: None,
    ):
        self.benchmark = benchmark
        self.settings = settings
        self.runner = runner
        self.environment = environment
        self.out = Path(out)
        # Called before each check, so the model and the judge are never in memory together.
        self.release = release

    def identity(self, benchmark: LeanBenchmark, problems: list[Theorem]) -> dict:
        """What, besides the model and its settings, must stay the same across sessions."""
        return {
            "benchmark": {
                "name": benchmark.name,
                "kind": "lean",
                "repository": benchmark.repository,
                "commit": benchmark.commit,
                "file": benchmark.file,
                "sha256": self.environment["files"][benchmark.file],
                "subset": benchmark.ids is not None,
                "scored": benchmark.scored,
                "ids": [theorem.id for theorem in problems],
            },
            "grader": lean_grader_version(benchmark),
            "lean": {
                **self.environment,
                "instruction": self.settings.instruction,
                "compile_time_limit_seconds": self.settings.compile_time_limit_seconds,
                "judge_time_limit_seconds": self.settings.judge_time_limit_seconds,
            },
        }

    def check(self, problems: list[Theorem]) -> None:
        """Nothing to verify in advance: the statements are the benchmark's own."""
        return None

    def prompt(self, theorem: Theorem) -> str:
        return lean_prompt(self.settings.instruction, theorem)

    def grade(self, theorem: Theorem, content: str) -> dict:
        self.release()
        limits = Limits(
            self.settings.compile_time_limit_seconds, self.settings.judge_time_limit_seconds
        )
        graded = check(theorem, content, self.runner, limits, self.benchmark.allowed_axioms)
        if graded.verdict == "proved":
            folder = self.out / PROOFS
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"{theorem.id}.lean").write_text(graded.submission, encoding="utf-8")
        return {
            "verdict": graded.verdict,
            "answer": None,
            "proof": graded.proof,
            "lean": graded.lean,
        }
