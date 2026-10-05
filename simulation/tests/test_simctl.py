"""Resource admission, ownership and cancellation gates for the evaluator."""

import importlib.util
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

SIMULATION = Path(__file__).resolve().parents[1]
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
