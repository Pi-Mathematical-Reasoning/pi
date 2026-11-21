"""Checking that a weights file on disk is the one its name promises."""

import hashlib

from pi.checkpoint import verify_weights


def blob(directory, content):
    blobs = directory / "blobs"
    blobs.mkdir(parents=True, exist_ok=True)
    name = "sha256-" + hashlib.sha256(content).hexdigest()
    (blobs / name).write_bytes(content)
    return name


def test_accepts_a_file_whose_content_matches_its_name(tmp_path):
    name = blob(tmp_path, b"weights")

    assert verify_weights(name, models_dir=tmp_path) is True


def test_refuses_a_file_whose_content_has_changed(tmp_path):
    name = blob(tmp_path, b"weights")
    (tmp_path / "blobs" / name).write_bytes(b"damaged")

    assert verify_weights(name, models_dir=tmp_path) is False


def test_cannot_verify_a_file_that_is_not_there(tmp_path):
    assert verify_weights("sha256-" + "0" * 64, models_dir=tmp_path) is None


def test_cannot_verify_a_name_that_promises_no_checksum(tmp_path):
    assert verify_weights(None, models_dir=tmp_path) is None


def test_reads_the_models_directory_from_ollamas_setting(tmp_path, monkeypatch):
    name = blob(tmp_path, b"weights")
    monkeypatch.setenv("OLLAMA_MODELS", str(tmp_path))

    assert verify_weights(name) is True
