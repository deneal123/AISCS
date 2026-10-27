"""Root restore harness must be opt-in and never delete deployment containers."""

import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def smoke():
    path = Path(__file__).resolve().parents[2] / "scripts" / "smoke_postgres_restore.py"
    if not path.exists():
        pytest.skip("root restore harness belongs to the superproject")
    spec = importlib.util.spec_from_file_location("restore_smoke_boundary", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_restore_requires_explicit_opt_in(smoke, monkeypatch):
    monkeypatch.delenv("S37_LIVE_POSTGRES_RESTORE", raising=False)
    monkeypatch.setattr(smoke.subprocess, "run", lambda *_a, **_k: pytest.fail("docker accessed"))
    with pytest.raises(RuntimeError, match="restore_opt_in_required"):
        smoke.run()


@pytest.mark.parametrize("target", ["gpthub-dev-postgres-1", "s37-pg-restore-incorrect", ""])
def test_cleanup_rejects_broad_or_foreign_target(smoke, monkeypatch, target):
    monkeypatch.setattr(smoke, "command", lambda *_a, **_k: pytest.fail("docker accessed"))
    with pytest.raises(RuntimeError, match="restore_cleanup_target"):
        smoke.cleanup(target)


def test_cleanup_checks_container_label_before_remove(smoke, monkeypatch):
    calls = []

    def command(args):
        calls.append(args)
        return json.dumps([{"Config": {"Labels": {"gpthub.acceptance": "foreign"}}}]).encode()

    monkeypatch.setattr(smoke, "command", command)
    with pytest.raises(RuntimeError, match="restore_cleanup_owner"):
        smoke.cleanup("s37-pg-restore-" + "a" * 32)
    assert len(calls) == 1 and calls[0][1] == "inspect"


def test_subprocess_error_does_not_disclose_stderr(smoke, monkeypatch):
    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            args=a, returncode=1, stdout=b"PRIVATE_DUMP", stderr=b"PRIVATE_CREDENTIAL"
        ),
    )
    with pytest.raises(RuntimeError) as failure:
        smoke.command(["docker", "exec"])
    assert str(failure.value) == "restore_command_failed"


def test_lost_container_start_ack_still_runs_exact_cleanup(smoke, monkeypatch):
    monkeypatch.setenv("S37_LIVE_POSTGRES_RESTORE", "1")
    calls, removed = [], []

    def command(args, **_kwargs):
        calls.append(args)
        if args[:2] == ["docker", "inspect"]:
            return b"sha256:" + b"a" * 64
        if "pg_dump" in args[-1]:
            return b"CREATE SCHEMA synthetic_fixture;"
        if "id" in args:
            return b"999"
        if args[:2] == ["docker", "run"]:
            # The daemon may have created the container before the CLI loses
            # its acknowledgement. Local return code cannot prove absence.
            raise RuntimeError("restore_command_failed")
        pytest.fail("unexpected command")

    monkeypatch.setattr(smoke, "command", command)
    monkeypatch.setattr(smoke, "cleanup", lambda target: removed.append(target))
    with pytest.raises(RuntimeError, match="restore_command_failed"):
        smoke.run()
    assert len(removed) == 1
    allocation = next(args for args in calls if args[:2] == ["docker", "run"])
    assert removed[0] == allocation[allocation.index("--name") + 1]


@pytest.mark.skipif(
    os.getenv("S37_LIVE_POSTGRES_RESTORE") != "1", reason="isolated offline dev schema restore"
)
def test_live_schema_and_synthetic_data_restore(smoke):
    assert smoke.run() == {
        "schema_restored": True,
        "synthetic_data_restored": True,
        "offline": True,
    }


@pytest.mark.skipif(
    os.getenv("S37_LIVE_POSTGRES_RESTORE") != "1", reason="isolated Docker lost-ACK boundary"
)
def test_live_lost_ack_removes_created_offline_container(smoke, monkeypatch):
    original_command = smoke.command
    targets = []

    def lost_ack(args, **kwargs):
        result = original_command(args, **kwargs)
        if args[:2] == ["docker", "run"]:
            targets.append(args[args.index("--name") + 1])
            raise RuntimeError("restore_command_failed")
        return result

    monkeypatch.setattr(smoke, "command", lost_ack)
    with pytest.raises(RuntimeError, match="restore_command_failed"):
        smoke.run()
    assert len(targets) == 1
    inventory = original_command(["docker", "ps", "-aq", "--filter", "name=^/" + targets[0] + "$"])
    assert not inventory.strip()
