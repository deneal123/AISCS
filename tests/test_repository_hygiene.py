"""Forced Git additions must not bypass exclusion and credential rules."""

import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "repository_check", ROOT / "scripts/check_repository.py"
)
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)


@pytest.mark.parametrize(
    "relative",
    [".env", ".work/worker-response.json", "build/output.pdf", "service/__pycache__/core.pyc"],
)
def test_forced_addition_of_local_state_is_rejected(monkeypatch, relative):
    original = checks.git

    def injected(root, *args):
        if args == ("ls-files", "-z"):
            return subprocess.CompletedProcess(args, 0, stdout=relative + "\0", stderr="")
        return original(root, *args)

    monkeypatch.setattr(checks, "git", injected)
    assert any("Tracked" in error for error in checks.check(ROOT))


def test_unregistered_cache_is_not_exempted_by_archive_location(monkeypatch):
    original = checks.git

    def injected(root, *args):
        if args == ("ls-files", "-z"):
            return subprocess.CompletedProcess(
                args, 0, stdout="archive/unregistered/__pycache__/a.pyc\0", stderr=""
            )
        return original(root, *args)

    monkeypatch.setattr(checks, "git", injected)
    assert "Tracked disposable file: archive/unregistered/__pycache__/a.pyc" in checks.check(ROOT)
