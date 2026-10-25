"""Cleanup is constrained to disposable owned state and must retain evidence."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import cleanup


def test_cleanup_refuses_root_and_outside_workspace(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setattr(cleanup, "WORK", work)
    for target in (work, tmp_path / "other", work / "../other"):
        with pytest.raises(ValueError, match="unsafe cleanup"):
            cleanup.checked_target(target)


def test_cleanup_plan_preserves_files_then_apply_removes_only_disposable(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(cleanup, "ROOT", tmp_path)
    monkeypatch.setattr(cleanup, "WORK", tmp_path / "work")
    env = tmp_path / "work/SIM-001/run/env"
    env.mkdir(parents=True)
    (env / "package.py").write_bytes(b"temporary dependency")
    proof = env.parent / "result.json"
    proof.write_bytes(b"proof")
    plan = cleanup.remove_targets([env], {proof.resolve()}, [], apply=False)
    assert plan[0]["status"] == "planned"
    assert env.is_dir()
    result = cleanup.remove_targets([env], {proof.resolve()}, [], apply=True)
    assert result[0]["status"] == "removed"
    assert not env.exists()
    assert proof.read_bytes() == b"proof"


def test_cleanup_preserves_receipt_ancestors_and_active_mounts(tmp_path, monkeypatch):
    monkeypatch.setattr(cleanup, "ROOT", tmp_path)
    monkeypatch.setattr(cleanup, "WORK", tmp_path / "work")
    target = tmp_path / "work/SIM-001/run/env"
    target.mkdir(parents=True)
    proof = target / "result.json"
    proof.write_bytes(b"protected")
    assert (
        cleanup.remove_targets([target], {proof}, [], apply=True)[0]["status"]
        == "kept_proof"
    )
    assert (
        cleanup.remove_targets([target], set(), [target.parent], apply=True)[0][
            "status"
        ]
        == "kept_active_mount"
    )
    assert target.is_dir()


def test_cleanup_does_not_modify_registry_while_collecting_proofs(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(cleanup, "ROOT", tmp_path)
    registry = {"candidates": [{"launch_review": {"receipts": ["result.json"]}}]}
    cleanup.protected_paths(registry)
    assert registry["candidates"][0]["launch_review"]["receipts"] == ["result.json"]
