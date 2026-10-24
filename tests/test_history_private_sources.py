"""Настоящий Git: private PDF journals не попадают в source history."""

import shutil
import subprocess

import pytest
from domain.files import git_commit_command, git_init_command

pytestmark = pytest.mark.skipif(
    not shutil.which("git") or not shutil.which("sh"), reason="Нужны Git и POSIX shell"
)


def shell(command):
    return subprocess.run(["sh", "-c", command], capture_output=True, text=True, check=True).stdout


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def test_snapshot_never_commits_root_or_nested_private_pdf_state(tmp_path):
    root = tmp_path.as_posix()
    assert "__OK__" in shell(git_init_command(root, "Fixture <fixture@example.test>"))
    for path in (
        ".gpthub-document/proposals/private.json",
        "documents/cats/.gpthub-document/authoring-checkpoint.json",
        ".gpthub-import-staging/private.json",
        "documents/cats/.gpthub-import-staging/private.json",
    ):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("PRIVATE_SYNTHETIC_STATE")
    source = tmp_path / "documents/cats/main.tex"
    source.write_text("source")
    assert "__OK__" in shell(git_commit_command(root, "document_authoring"))
    assert git(tmp_path, "ls-files") == "documents/cats/main.tex"
    assert "__NO_CHANGES__" in shell(git_commit_command(root, "document_authoring"))


def test_previously_staged_private_state_blocks_commit_without_erasing_index(tmp_path):
    root = tmp_path.as_posix()
    shell(git_init_command(root, "Fixture <fixture@example.test>"))
    before = git(tmp_path, "rev-parse", "HEAD")
    private = tmp_path / ".gpthub-document/private.json"
    private.parent.mkdir()
    private.write_text("PRIVATE_SYNTHETIC_STATE")
    git(tmp_path, "add", ".gpthub-document/private.json")
    (tmp_path / "main.tex").write_text("source")
    assert "__FAILED__" in shell(git_commit_command(root, "document_authoring"))
    assert git(tmp_path, "rev-parse", "HEAD") == before
    assert ".gpthub-document/private.json" in git(tmp_path, "ls-files", "--cached")


def test_legacy_tracked_private_blob_is_not_updated_or_erased_implicitly(tmp_path):
    root = tmp_path.as_posix()
    shell(git_init_command(root, "Fixture <fixture@example.test>"))
    private = tmp_path / ".gpthub-document/private.json"
    private.parent.mkdir()
    private.write_text("HISTORICAL_FIXTURE")
    git(tmp_path, "add", ".gpthub-document/private.json")
    git(tmp_path, "commit", "-qm", "legacy fixture")
    private.write_text("NEW_PRIVATE_STATE")
    (tmp_path / "main.tex").write_text("source")
    assert "__OK__" in shell(git_commit_command(root, "document_authoring"))
    assert git(tmp_path, "show", "HEAD:.gpthub-document/private.json") == "HISTORICAL_FIXTURE"
    assert private.read_text() == "NEW_PRIVATE_STATE"
    assert git(tmp_path, "show", "HEAD:main.tex") == "source"
