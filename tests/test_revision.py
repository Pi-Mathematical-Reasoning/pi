"""Which code a run used: the git revision, and whether the tree matched it."""

import subprocess

import pytest

from pi.revision import code_revision


def git(directory, *arguments):
    done = subprocess.run(
        ["git", "-C", str(directory), *arguments], capture_output=True, text=True, check=True
    )
    return done.stdout.strip()


@pytest.fixture
def checkout(tmp_path):
    git(tmp_path, "init", "--quiet")
    git(tmp_path, "config", "user.name", "Test")
    git(tmp_path, "config", "user.email", "test@example.com")
    (tmp_path / "tracked.txt").write_text("one\n")
    git(tmp_path, "add", "tracked.txt")
    git(tmp_path, "commit", "--quiet", "--no-verify", "-m", "chore: first")
    return tmp_path


def test_reports_the_commit_of_a_clean_checkout(checkout):
    assert code_revision(checkout) == {
        "revision": git(checkout, "rev-parse", "HEAD"),
        "dirty": False,
    }


def test_marks_a_checkout_with_an_edited_file_as_dirty(checkout):
    (checkout / "tracked.txt").write_text("two\n")

    assert code_revision(checkout)["dirty"] is True


def test_marks_a_checkout_with_a_new_file_as_dirty(checkout):
    # A file git does not track yet may still be code the run imported.
    (checkout / "new.py").write_text("x = 1\n")

    assert code_revision(checkout)["dirty"] is True


def test_reports_nothing_outside_a_git_checkout(tmp_path):
    assert code_revision(tmp_path) is None
