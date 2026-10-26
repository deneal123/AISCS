"""Linux venv storage must span phases and be removed only with proven ownership."""

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import simctl


@pytest.mark.parametrize("body_fails", [False, True])
def test_owned_volume_cleanup_runs_after_success_or_stage_exception(
    tmp_path, monkeypatch, body_fails
):
    calls = []

    def command(args, **kwargs):
        calls.append(args)
        if args[:3] == ["docker", "volume", "create"]:
            return Mock(returncode=0, stdout=args[-1])
        if args[:3] == ["docker", "volume", "inspect"]:
            if any(x[:3] == ["docker", "volume", "rm"] for x in calls):
                return Mock(returncode=1, stderr="error: no such volume")
            return Mock(
                returncode=0,
                stdout=json.dumps(
                    [
                        {
                            "Name": args[-1],
                            "Labels": {
                                "aspa.simulation.owner": "simctl",
                                "aspa.simulation.id": "SIM-015",
                            },
                        }
                    ]
                ),
            )
        return Mock(returncode=0)

    monkeypatch.setattr(simctl, "command", command)
    monkeypatch.setattr(simctl, "save", lambda *_: None)
    profile = {"environment_storage": "docker-volume"}
    result = {}

    def use():
        with simctl.runtime_environment(
            {"id": "SIM-015"}, profile, tmp_path, result
        ) as runtime:
            assert (
                runtime["_environment_volume"] == result["environment_volume"]["name"]
            )
            assert runtime["_environment_volume"].startswith("aspa-sim-sim-015-env-")
            assert "_environment_volume" not in profile
            if body_fails:
                raise RuntimeError("stage failed")

    if body_fails:
        with pytest.raises(RuntimeError, match="stage failed"):
            use()
    else:
        use()
    assert result["environment_volume"]["status"] == "removed"
    assert sum(x[:3] == ["docker", "volume", "rm"] for x in calls) == 1


def test_volume_with_foreign_owner_is_kept(tmp_path, monkeypatch):
    calls = []

    def command(args, **kwargs):
        calls.append(args)
        if args[:3] == ["docker", "volume", "inspect"]:
            return Mock(
                returncode=0,
                stdout=json.dumps(
                    [{"Name": args[-1], "Labels": {"aspa.simulation.owner": "foreign"}}]
                ),
            )
        return Mock(returncode=0)

    monkeypatch.setattr(simctl, "command", command)
    monkeypatch.setattr(simctl, "save", lambda *_: None)
    result = {}
    with simctl.runtime_environment(
        {"id": "SIM-015"}, {"environment_storage": "docker-volume"}, tmp_path, result
    ):
        pass
    assert result["environment_volume"]["status"] == "cleanup_pending"
    assert not any(x[:3] == ["docker", "volume", "rm"] for x in calls)


def test_volume_backend_rejects_resume_before_touching_old_run():
    with pytest.raises(ValueError, match="fresh run"):
        simctl.evaluate(
            {}, {"environment_storage": "docker-volume"}, {}, resume="unused"
        )


def test_unknown_storage_cannot_silently_fall_back(tmp_path):
    with (
        pytest.raises(ValueError, match="Unknown environment storage"),
        simctl.runtime_environment({}, {"environment_storage": "typo"}, tmp_path, {}),
    ):
        pass


def test_same_venv_volume_is_mounted_into_each_stage(tmp_path, monkeypatch):
    monkeypatch.setattr(simctl, "free_memory", lambda: 1)
    monkeypatch.setattr(
        simctl.shutil, "disk_usage", lambda _: Mock(free=50 * simctl.GIB)
    )
    monkeypatch.setattr(simctl, "docker_memory", lambda _: 0)
    process = Mock(returncode=0)
    process.poll.return_value = 0
    popen = Mock(return_value=process)
    monkeypatch.setattr(subprocess, "Popen", popen)
    profile = {
        "_environment_volume": "aspa-sim-sim-015-env-known",
        "image": "python:3.10-slim",
        "install": "true",
        "smoke": "true",
    }
    policy = {
        "unrestricted_memory": True,
        "host_reserve_bytes": 0,
        "disk_reserve_bytes": 0,
        "cpu_threads": 4,
        "install_seconds": 10,
        "smoke_seconds": 10,
    }
    for stage in ["install", "smoke"]:
        result = simctl.phase({"id": "SIM-015"}, profile, stage, tmp_path, policy)
        assert result["status"] == "passed"
        assert "aspa-sim-sim-015-env-known:/work/env" in result["docker_command"]
