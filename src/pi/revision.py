"""Which code a run used."""

import subprocess
from pathlib import Path


def code_revision(directory: Path) -> dict | None:
    """The commit checked out in `directory` and whether the tree differs from it.

    Returns None outside a git checkout. Untracked files count as differences,
    because a new file may be code the run imported.
    """
    revision = _git(directory, "rev-parse", "HEAD")
    if revision is None:
        return None
    status = _git(directory, "status", "--porcelain")
    return {"revision": revision, "dirty": bool(status)}


def _git(directory: Path, *arguments: str) -> str | None:
    try:
        done = subprocess.run(
            ["git", "-C", str(directory), *arguments], capture_output=True, text=True
        )
    except FileNotFoundError:
        return None
    return done.stdout.strip() if done.returncode == 0 else None
