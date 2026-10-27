import hashlib
import time
from uuid import uuid4

import pytest

from service.contracts import ExecutionRequest, SimulationConfig
from service.infrastructure.execution.process import Executions


def test_repeat_delivery_verified_files_ack_and_receipt_restart(tmp_path):
    manager = Executions(tmp_path)
    request = ExecutionRequest(execution_id=str(uuid4()), config=SimulationConfig(duration_ms=100))
    first = manager.start(request)
    repeated = manager.start(request)
    assert repeated["started_at"] == first["started_at"]
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        result = manager.status(request.execution_id)
        if result["status"] != "running":
            break
        time.sleep(0.1)
    assert result["status"] == "completed", result
    for item in result["manifest"]["files"]:
        path = tmp_path / request.execution_id / "output" / item["name"]
        assert path.stat().st_size == item["bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
    with pytest.raises(ValueError):
        manager.acknowledge(request.execution_id, "bad")
    manager.acknowledge(request.execution_id, request.config.digest())
    assert not (tmp_path / request.execution_id / "output").exists()
    restarted = Executions(tmp_path)
    assert restarted.status(request.execution_id)["acknowledged"] is True
    assert restarted.start(request)["status"] == "completed"
    manager.close()


def test_cancel_kills_owned_solver_and_preserves_terminal_state(tmp_path):
    manager = Executions(tmp_path)
    request = ExecutionRequest(execution_id=str(uuid4()), config=SimulationConfig(duration_ms=1000))
    manager.start(request)
    assert manager.cancel(request.execution_id)["status"] == "cancelled"
    assert not manager.processes[request.execution_id].is_alive()
    assert manager.status(request.execution_id)["status"] == "cancelled"
    manager.close()


def test_executor_shutdown_is_interruption_not_user_cancellation(tmp_path):
    manager = Executions(tmp_path)
    request = ExecutionRequest(execution_id=str(uuid4()), config=SimulationConfig(duration_ms=1000))
    manager.start(request)
    manager.close()
    assert not manager.processes[request.execution_id].is_alive()
    restarted = Executions(tmp_path)
    assert restarted.status(request.execution_id)["status"] == "interrupted"
    # Reusing the old attempt reports its actual terminal state, never a silent restart.
    assert restarted.start(request)["status"] == "interrupted"
