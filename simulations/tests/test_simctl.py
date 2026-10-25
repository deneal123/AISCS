"""Resource admission, ownership and cancellation gates for the evaluator."""

import importlib.util
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

SIMULATION = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SIMULATION))
from acquire import select_commit

spec = importlib.util.spec_from_file_location("simctl", SIMULATION / "simctl.py")
simctl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(simctl)


def test_admission_keeps_entire_reserve():
    assert simctl.admit(3 * simctl.GIB, simctl.GIB, 2 * simctl.GIB)
    assert not simctl.admit(3 * simctl.GIB - 1, simctl.GIB, 2 * simctl.GIB)


def test_unrestricted_memory_attempts_launch_without_ram_flags(tmp_path, monkeypatch):
    monkeypatch.setattr(simctl, "free_memory", lambda: 1)
    monkeypatch.setattr(
        simctl.shutil, "disk_usage", lambda p: Mock(free=50 * simctl.GIB)
    )
    monkeypatch.setattr(simctl, "docker_memory", lambda n: 0)
    process = Mock(returncode=0)
    process.poll.return_value = 0
    launched = Mock(return_value=process)
    monkeypatch.setattr(subprocess, "Popen", launched)
    policy = {
        "unrestricted_memory": True,
        "host_reserve_bytes": 0,
        "disk_reserve_bytes": 0,
        "cpu_threads": 4,
        "memory_bytes": 0,
        "install_seconds": 1800,
    }
    result = simctl.phase(
        {"id": "SIM-TEST"},
        {
            "image": "python:3.12-slim",
            "install": "true",
            "admission_bytes": 20 * simctl.GIB,
        },
        "install",
        tmp_path,
        policy,
    )
    assert result["status"] == "passed"
    launched.assert_called_once()
    assert "--memory" not in result["docker_command"]
    assert "--memory-swap" not in result["docker_command"]


def test_snapshot_pin_survives_new_upstream_head():
    head = Mock(side_effect=AssertionError("A pinned snapshot must not follow HEAD"))
    assert (
        select_commit({"commit": "a" * 40, "recorded_commit": None}, head) == "a" * 40
    )
    assert not head.called


def test_conflicting_registered_pin_is_rejected():
    with pytest.raises(ValueError):
        select_commit(
            {"commit": "a" * 40, "recorded_commit": "b" * 40}, lambda: "c" * 40
        )


def test_workspace_escape_is_rejected():
    with pytest.raises(ValueError):
        simctl.checked_work(simctl.WORK / ".." / "outside")
    with pytest.raises(ValueError):
        simctl.checked_work(simctl.WORK)


def test_resource_block_does_not_launch_docker(tmp_path, monkeypatch):
    monkeypatch.setattr(simctl, "free_memory", lambda: simctl.GIB)
    launched = Mock(side_effect=AssertionError("Docker must not launch"))
    monkeypatch.setattr(subprocess, "Popen", launched)
    result = simctl.phase(
        {"id": "SIM-TEST"},
        {"install": "sleep 100"},
        "install",
        tmp_path,
        {"host_reserve_bytes": 2 * simctl.GIB},
    )
    assert result["reason"] == "host_memory_reserve"
    assert not launched.called


def test_only_owned_container_is_terminated(monkeypatch):
    calls = []
    monkeypatch.setattr(
        simctl, "command", lambda args, **kw: calls.append(args) or Mock(returncode=0)
    )
    process = Mock()
    assert simctl.terminate_container("aspa-sim-test-owned", process)
    assert calls == [["docker", "rm", "-f", "aspa-sim-test-owned"]]
    process.wait.assert_called_once_with(timeout=10)


def test_timeout_stops_owned_container_and_retains_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(simctl, "free_memory", lambda: 8 * simctl.GIB)
    monkeypatch.setattr(
        simctl.shutil, "disk_usage", lambda p: Mock(free=50 * simctl.GIB)
    )
    monkeypatch.setattr(simctl, "docker_memory", lambda n: 1)
    process = Mock(returncode=-1)
    process.poll.return_value = None
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: process)
    terminated = Mock(return_value=True)
    monkeypatch.setattr(simctl, "terminate_container", terminated)
    policy = {
        "host_reserve_bytes": 2 * simctl.GIB,
        "disk_reserve_bytes": 20 * simctl.GIB,
        "cpu_threads": 4,
        "memory_bytes": 4 * simctl.GIB,
        "install_seconds": 0,
    }
    result = simctl.phase(
        {"id": "SIM-TEST"},
        {"image": "python:3.12-slim", "install": "sleep 100"},
        "install",
        tmp_path,
        policy,
    )
    assert result["reason"] == "timeout"
    assert result["status"] == "blocked"
    assert result["termination_confirmed"]
    terminated.assert_called_once()


def test_memory_block_stops_queue_before_next_candidate(monkeypatch):
    registry = {
        "candidates": [
            {"id": "SIM-001", "status": "attached"},
            {"id": "SIM-002", "status": "attached"},
        ],
        "policy": {},
    }
    monkeypatch.setattr(sys, "argv", ["simctl.py", "evaluate"])
    monkeypatch.setattr(
        simctl,
        "load",
        lambda path: (
            registry
            if path == simctl.REGISTRY
            else {"SIM-001": {"image": "test"}, "SIM-002": {"image": "test"}}
        ),
    )
    evaluate = Mock(
        return_value={
            "status": "blocked",
            "run": "unused",
            "phases": [
                {
                    "stage": "install",
                    "status": "blocked",
                    "reason": "host_memory_reserve",
                }
            ],
        }
    )
    monkeypatch.setattr(simctl, "evaluate", evaluate)
    monkeypatch.setattr(simctl, "save", Mock())
    simctl.main()
    assert evaluate.call_count == 1


def test_resume_cannot_take_another_candidates_run(tmp_path, monkeypatch):
    monkeypatch.setattr(simctl, "WORK", tmp_path)
    other = tmp_path / "SIM-002" / "run"
    with pytest.raises(ValueError, match="does not belong"):
        simctl.evaluate({"id": "SIM-001"}, {}, {}, resume=str(other))


def test_completed_evaluation_preserves_review_added_during_run(monkeypatch):
    import copy

    original = {
        "candidates": [{"id": "SIM-006", "status": "attached", "commit": "a" * 40}],
        "policy": {},
    }
    latest = copy.deepcopy(original)
    latest["integrity_review"] = {"receipt": "new integrity receipt"}
    latest["candidates"][0]["launch_review"] = {
        "scope": "review added during execution"
    }
    monkeypatch.setattr(sys, "argv", ["simctl.py", "evaluate", "--id", "SIM-006"])
    monkeypatch.setattr(
        simctl,
        "load",
        Mock(
            side_effect=[
                original,
                {"SIM-006": {"image": "test"}},
                latest,
            ]
        ),
    )
    monkeypatch.setattr(
        simctl,
        "evaluate",
        Mock(
            return_value={
                "status": "partial",
                "run": "work",
                "phases": [],
            }
        ),
    )
    saved = Mock()
    monkeypatch.setattr(simctl, "save", saved)
    simctl.main()
    written = saved.call_args.args[1]
    assert written["integrity_review"]["receipt"] == "new integrity receipt"
    assert (
        written["candidates"][0]["launch_review"]["scope"]
        == "review added during execution"
    )
    assert written["candidates"][0]["evaluation"]["status"] == "partial"
    assert written["candidates"][0]["cleanup"]["status"] == "pending"


def test_evaluation_places_verified_asset_in_nested_directory(tmp_path, monkeypatch):
    import hashlib

    work = tmp_path / "work"
    cache = work / "cache/input.bin"
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b"registered input")
    monkeypatch.setattr(simctl, "ROOT", tmp_path)
    monkeypatch.setattr(simctl, "WORK", work)
    monkeypatch.setattr(simctl, "save", Mock())
    monkeypatch.setattr(
        simctl, "copy_checkout", lambda row, target: target.mkdir(parents=True)
    )
    monkeypatch.setattr(
        simctl,
        "phase",
        lambda row, profile, stage, run, policy: {
            "stage": stage,
            "status": "passed",
        },
    )
    result = simctl.evaluate(
        {"id": "SIM-TEST", "repository": "fixture", "commit": "a" * 40},
        {
            "image": "fixture",
            "install": "true",
            "assets": [
                {
                    "source": "cache/input.bin",
                    "destination": "nested/input.bin",
                    "sha256": hashlib.sha256(cache.read_bytes()).hexdigest(),
                }
            ],
        },
        {"unrestricted_memory": True},
    )
    assert (
        tmp_path / result["run"] / "assets/nested/input.bin"
    ).read_bytes() == cache.read_bytes()


def test_memory_probe_timeout_is_an_unavailable_observation(monkeypatch):
    monkeypatch.setattr(
        simctl, "command", Mock(side_effect=subprocess.TimeoutExpired("docker", 3))
    )
    assert simctl.docker_memory("owned-container") is None


def test_missing_memory_observation_does_not_terminate_live_job(tmp_path, monkeypatch):
    monkeypatch.setattr(simctl, "free_memory", lambda: 8 * simctl.GIB)
    monkeypatch.setattr(
        simctl.shutil, "disk_usage", lambda p: Mock(free=50 * simctl.GIB)
    )
    monkeypatch.setattr(simctl, "docker_memory", Mock(side_effect=[None, 100]))
    monkeypatch.setattr(simctl.time, "sleep", lambda seconds: None)
    process = Mock(returncode=0)
    process.poll.side_effect = [None, None, 0]
    monkeypatch.setattr(subprocess, "Popen", Mock(return_value=process))
    terminate = Mock()
    monkeypatch.setattr(simctl, "terminate_container", terminate)
    result = simctl.phase(
        {"id": "SIM-TEST"},
        {"image": "test", "install": "true"},
        "install",
        tmp_path,
        {
            "unrestricted_memory": True,
            "host_reserve_bytes": 0,
            "disk_reserve_bytes": 0,
            "cpu_threads": 4,
            "install_seconds": 100,
        },
    )
    assert result["status"] == "passed"
    assert (
        result["memory_observation_failures"] == 1
        and result["peak_memory_bytes"] == 100
    )
    terminate.assert_not_called()


def test_memory_monitor_records_low_reading_and_terminates(tmp_path, monkeypatch):
    readings = iter([8 * simctl.GIB, simctl.GIB])
    monkeypatch.setattr(simctl, "free_memory", lambda: next(readings))
    monkeypatch.setattr(
        simctl.shutil, "disk_usage", lambda p: Mock(free=50 * simctl.GIB)
    )
    process = Mock(returncode=-1)
    process.poll.return_value = None
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)
    terminate = Mock(return_value=True)
    monkeypatch.setattr(simctl, "terminate_container", terminate)
    policy = {
        "host_reserve_bytes": 2 * simctl.GIB,
        "disk_reserve_bytes": 20 * simctl.GIB,
        "cpu_threads": 4,
        "memory_bytes": 4 * simctl.GIB,
        "install_seconds": 1800,
    }
    result = simctl.phase(
        {"id": "SIM-TEST"},
        {"image": "test", "install": "sleep 100"},
        "install",
        tmp_path,
        policy,
    )
    assert result["reason"] == "host_memory_reserve"
    assert result["host_available_bytes_at_stop"] == simctl.GIB
    assert result["minimum_host_available_bytes"] == simctl.GIB
    assert result["termination_confirmed"]
    terminate.assert_called_once()
