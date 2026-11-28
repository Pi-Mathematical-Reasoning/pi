"""Publishing an audited run to Pi's artifacts bucket, manifest last.

The layout is Jaws' convention for run artifacts: every file of a run under
`data/runs/<run>/`, then `_manifest.json`, written last, whose presence means
the run is complete. Nothing is ever overwritten: a key that already holds the
same bytes is left alone, and one that holds other bytes stops the publish.
"""

import hashlib
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import yaml

from pi.audit import AUDIT, fingerprint
from pi.revision import code_revision

MANIFEST = "_manifest.json"
PROOFS = "proofs"


class PublishError(Exception):
    """The run cannot be published as it stands."""


def run_bucket(project_file: Path) -> tuple[str, str]:
    """The artifacts bucket the jaws project file declares, and where runs go in it."""
    project = yaml.safe_load(Path(project_file).read_text()) or {}
    datasets = [c for c in project.get("components") or [] if c.get("kind") == "dataset"]
    if len(datasets) != 1:
        raise PublishError(f"{project_file} must declare exactly one dataset")
    return datasets[0]["bucket"], f"{datasets[0]['prefix']}runs/"


def publish_run(out: Path, bucket: str, s3, prefix: str = "data/runs/") -> dict:
    """Upload the run's files, then its manifest. Each file's outcome, by name."""
    out = Path(out)
    audit = _passed_audit(out)
    names = [*audit["files"], AUDIT]
    for name in names:
        _inside(out, name)
    for name, recorded in audit["files"].items():
        path = out / name
        if not path.is_file() or fingerprint(path) != recorded:
            raise PublishError(f"{name} has changed since it was audited; run `pi audit` again")
    folder = out / PROOFS
    if folder.is_symlink():
        raise PublishError(f"{PROOFS} is a symbolic link; nothing was published")
    if folder.is_dir():
        for path in sorted(folder.iterdir()):
            if f"{PROOFS}/{path.name}" not in audit["files"]:
                raise PublishError(f"{PROOFS}/{path.name} was not audited; run `pi audit` again")
    files = {name: fingerprint(out / name) for name in names}

    base = f"{prefix}{out.name}/"
    outcome = {name: _put(s3, bucket, base + name, out / name) for name in names}

    manifest = {
        "run": out.name,
        "published_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "code": code_revision(Path(__file__).parent),
        "files": files,
        "audit": {"passed": audit["passed"], "audited_at": audit["audited_at"]},
    }
    outcome[MANIFEST] = _put_manifest(s3, bucket, base + MANIFEST, manifest)
    return outcome


def _inside(out: Path, name: str) -> None:
    """Refuse a name from the audit that points outside the run's directory."""
    if Path(name).is_absolute() or ".." in Path(name).parts:
        raise PublishError(f"{name!r} in the audit points outside {out}; nothing was published")
    here = out
    for part in Path(name).parts:
        here = here / part
        if here.is_symlink():
            raise PublishError(f"{name} is a symbolic link (via {part}); nothing was published")
    if not (out / name).resolve().is_relative_to(out.resolve()):
        raise PublishError(f"{name} lies outside {out}; nothing was published")


def _passed_audit(out: Path) -> dict:
    path = out / AUDIT
    if not path.exists():
        raise PublishError(f"{out} has not been audited: run `pi audit {out}` first")
    audit = json.loads(path.read_text())
    if not audit.get("passed"):
        failed = [check["name"] for check in audit.get("checks", []) if not check["passed"]]
        raise PublishError(f"{out}'s audit failed ({', '.join(failed)}): fix it and audit again")
    return audit


def _put(s3, bucket: str, key: str, path: Path) -> str:
    """Upload a file without overwriting, and prove the object holds its bytes."""
    created = s3.put_new(bucket, key, path)
    want = hashlib.sha256(path.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory() as directory:
        copy = Path(directory) / "copy"
        if not s3.get(bucket, key, copy):
            raise PublishError(f"s3://{bucket}/{key} cannot be read back after the upload")
        found = hashlib.sha256(copy.read_bytes()).hexdigest()
    if found != want:
        raise PublishError(
            f"s3://{bucket}/{key} already holds different bytes from {path.name}; "
            "nothing was overwritten"
        )
    return "uploaded" if created else "already present"


def _put_manifest(s3, bucket: str, key: str, manifest: dict) -> str:
    """Write the manifest last, or accept one already there that names the same files."""
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / MANIFEST
        path.write_text(json.dumps(manifest, indent=2) + "\n")
        if s3.put_new(bucket, key, path):
            return "uploaded"
        existing = Path(directory) / "existing"
        s3.get(bucket, key, existing)
        if json.loads(existing.read_text()).get("files") != manifest["files"]:
            raise PublishError(
                f"s3://{bucket}/{key} names different files; nothing was overwritten"
            )
        return "already present"
