"""Publishing an audited run to the bucket, manifest last."""

import json

import pytest

from pi.audit import AUDIT, audit_run, fingerprint
from pi.publish import PublishError, publish_run, run_bucket
from pi.s3 import AwsCli
from tests.test_audit import finished  # noqa: F401  (the fixture)

BUCKET = "jaws-pi-prover-artifacts"
FILES = ["run.json", "results.jsonl", "report.md", "audit.json"]


@pytest.fixture
def audited(finished):  # noqa: F811
    out, benchmark, data = finished
    (out / AUDIT).write_text(json.dumps(audit_run(out, benchmark, data)))
    return out


def stored(aws, out, name):
    return aws / BUCKET / "data" / "runs" / out.name / name


def test_uploads_every_file_then_the_manifest(aws, audited):
    outcome = publish_run(audited, BUCKET, AwsCli())

    assert outcome == {**{name: "uploaded" for name in FILES}, "_manifest.json": "uploaded"}
    for name in FILES:
        assert stored(aws, audited, name).read_bytes() == (audited / name).read_bytes()
    keys = [call[call.index("--key") + 1] for call in calls(aws) if call[1] == "put-object"]
    assert keys[-1].endswith("/_manifest.json")


def test_the_manifest_names_each_files_checksum_and_size(aws, audited):
    publish_run(audited, BUCKET, AwsCli())

    manifest = json.loads(stored(aws, audited, "_manifest.json").read_text())
    assert manifest["run"] == audited.name
    assert set(manifest["files"]) == set(FILES)
    assert manifest["files"]["results.jsonl"]["size"] == (audited / "results.jsonl").stat().st_size
    assert manifest["audit"]["passed"] is True


def test_publishing_again_changes_nothing(aws, audited):
    publish_run(audited, BUCKET, AwsCli())

    outcome = publish_run(audited, BUCKET, AwsCli())

    assert set(outcome.values()) == {"already present"}


def test_refuses_a_run_that_has_not_been_audited(aws, finished):  # noqa: F811
    out, _, _ = finished

    with pytest.raises(PublishError, match="pi audit"):
        publish_run(out, BUCKET, AwsCli())

    assert not (aws / BUCKET).exists()


def test_refuses_a_run_whose_audit_failed(aws, audited):
    audit = json.loads((audited / AUDIT).read_text())
    (audited / AUDIT).write_text(json.dumps({**audit, "passed": False}))

    with pytest.raises(PublishError, match="failed"):
        publish_run(audited, BUCKET, AwsCli())


def test_refuses_a_file_changed_since_the_audit(aws, audited):
    with (audited / "results.jsonl").open("a") as results:
        results.write("\n")

    with pytest.raises(PublishError, match="results.jsonl"):
        publish_run(audited, BUCKET, AwsCli())

    assert not (aws / BUCKET).exists()


def test_refuses_to_replace_a_published_file_that_differs(aws, audited):
    other = stored(aws, audited, "report.md")
    other.parent.mkdir(parents=True)
    other.write_text("a different report\n")

    with pytest.raises(PublishError, match="report.md"):
        publish_run(audited, BUCKET, AwsCli())

    assert other.read_text() == "a different report\n"
    assert not stored(aws, audited, "_manifest.json").exists()


def test_reads_the_bucket_from_the_project_file(tmp_path):
    project = tmp_path / "jaws.yaml"
    project.write_text(
        "version: 1\ncomponents:\n  - kind: dataset\n    name: artifacts\n"
        "    bucket: jaws-pi-prover-artifacts\n    prefix: data/\n"
    )

    assert run_bucket(project) == ("jaws-pi-prover-artifacts", "data/runs/")


def test_the_committed_project_file_names_the_bucket():
    from pathlib import Path

    assert run_bucket(Path(__file__).parent.parent / "jaws.yaml") == (BUCKET, "data/runs/")


def calls(aws):
    return [json.loads(line) for line in (aws / "calls.jsonl").read_text().splitlines()]


PROOF = "proofs/fixture_add_zero.lean"


@pytest.fixture
def audited_with_proofs(audited):
    (audited / "proofs").mkdir()
    (audited / PROOF).write_text("theorem fixture_add_zero : 0 + 0 = 0 := rfl\n")
    audit = json.loads((audited / AUDIT).read_text())
    audit["files"][PROOF] = fingerprint(audited / PROOF)
    (audited / AUDIT).write_text(json.dumps(audit))
    return audited


def test_publishes_every_file_the_audit_names(aws, audited_with_proofs):
    outcome = publish_run(audited_with_proofs, BUCKET, AwsCli())

    assert outcome[PROOF] == "uploaded"
    assert (
        stored(aws, audited_with_proofs, PROOF).read_bytes()
        == (audited_with_proofs / PROOF).read_bytes()
    )
    manifest = json.loads(stored(aws, audited_with_proofs, "_manifest.json").read_text())
    assert PROOF in manifest["files"]
    assert list(outcome)[-2:] == ["audit.json", "_manifest.json"]


def test_refuses_when_a_proof_file_changed_since_the_audit(aws, audited_with_proofs):
    (audited_with_proofs / PROOF).write_text("theorem other : True := trivial\n")

    with pytest.raises(PublishError, match="fixture_add_zero.lean"):
        publish_run(audited_with_proofs, BUCKET, AwsCli())

    assert not (aws / BUCKET).exists()


def test_refuses_when_a_proof_file_is_missing(aws, audited_with_proofs):
    (audited_with_proofs / PROOF).unlink()

    with pytest.raises(PublishError, match="fixture_add_zero.lean"):
        publish_run(audited_with_proofs, BUCKET, AwsCli())

    assert not (aws / BUCKET).exists()


def test_refuses_a_proof_file_the_audit_does_not_name(aws, audited_with_proofs):
    (audited_with_proofs / "proofs/extra.lean").write_text("import Mathlib\n")

    with pytest.raises(PublishError, match="extra.lean"):
        publish_run(audited_with_proofs, BUCKET, AwsCli())

    assert not (aws / BUCKET).exists()


@pytest.mark.parametrize("name", ["../outside.txt", "/etc/hosts", "proofs/../../x"])
def test_refuses_a_name_that_leaves_the_run_directory(aws, audited, name):
    audit = json.loads((audited / AUDIT).read_text())
    audit["files"][name] = {"sha256": "0", "size": 0}
    (audited / AUDIT).write_text(json.dumps(audit))

    with pytest.raises(PublishError, match="outside"):
        publish_run(audited, BUCKET, AwsCli())

    assert not (aws / BUCKET).exists()


def test_an_answer_run_publishes_the_same_four_files_as_before(aws, audited):
    publish_run(audited, BUCKET, AwsCli())

    keys = [
        call[call.index("--key") + 1].split("/")[-1]
        for call in calls(aws)
        if call[1] == "put-object"
    ]
    assert [k for k in keys if k != "_manifest.json"][:4] == FILES
    manifest = json.loads(stored(aws, audited, "_manifest.json").read_text())
    assert list(manifest["files"]) == FILES
