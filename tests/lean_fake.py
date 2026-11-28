"""A stand-in for `LeanRunner` that runs nothing: queued results, real files, recorded calls.

`compile` writes bytes to the `.olean` path it is given (so hashing works), then calls
`on_compile(source, olean)` if one was given (a test can rewrite or delete a file there), and
returns the next queued `Finished`. `judge` writes the next queued `saved` value to the saved
path (as JSON; `bytes` are written as they are; `None` writes nothing) and returns the next
queued `Finished`. Every call is appended to `calls` with its limit, in order, and the text of
each compiled source is kept in `sources` by file name, since the work directory is removed.
"""

import contextlib
import json
import tempfile
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

from pi.lean_project import Finished


class FakeRunner:
    def __init__(
        self,
        compiles: Sequence[Finished] = (),
        judges: Sequence[Finished] = (),
        saved: Sequence[object] = (),
        on_compile: Callable[[Path, Path], None] | None = None,
    ):
        self.compiles = list(compiles)
        self.judges = list(judges)
        self.saved = list(saved)
        self.on_compile = on_compile
        self.calls: list[tuple] = []
        self.sources: dict[str, str] = {}
        self.work: Path | None = None

    @contextlib.contextmanager
    def work_dir(self) -> Iterator[Path]:
        with tempfile.TemporaryDirectory() as path:
            self.work = Path(path)
            yield self.work

    def compile(self, source: Path, olean: Path, limit: float) -> Finished:
        self.calls.append(("compile", source.name, olean.name, limit))
        self.sources[source.name] = source.read_text(encoding="utf-8")
        olean.write_bytes(b"olean of " + source.name.encode())
        if self.on_compile is not None:
            self.on_compile(source, olean)
        return self.compiles.pop(0)

    def judge(self, reference: Path, submission: Path, saved: Path, limit: float) -> Finished:
        self.calls.append(("judge", reference.name, submission.name, saved.name, limit))
        value = self.saved.pop(0) if self.saved else None
        if isinstance(value, bytes):
            saved.write_bytes(value)
        elif value is not None:
            saved.write_text(json.dumps(value), encoding="utf-8")
        return self.judges.pop(0)

    def judge_calls(self) -> list[tuple]:
        return [call for call in self.calls if call[0] == "judge"]
