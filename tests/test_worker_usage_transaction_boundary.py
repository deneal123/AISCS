"""The outer preflight transaction cannot block the private usage ACK writer."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from service.models.key_value import ProcessingStatus
from service.services.chat.infrastructure.chat_worker.execution import run as run_execution
from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.chat.infrastructure.chat_worker.run_contracts import (
    MutableRunState,
    WorkerRunRequest,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "commit", "stage"])
async def test_preflight_row_lock_is_released_before_provider_execution(monkeypatch, failure):
    request = WorkerRunRequest(str(uuid4()), str(uuid4()), "synthetic", str(uuid4()))
    session = AsyncMock()
    transaction = {"locked": False}

    async def commit():
        if failure == "commit" and session.commit.await_count == 2:
            raise RuntimeError("PRIVATE_COMMIT_MARKER")
        transaction["locked"] = False

    async def reserve(*_args, **_kwargs):
        transaction["locked"] = True
        return object(), None

    async def execute(*_args, **_kwargs):
        assert not transaction["locked"], "outer job row blocks independent usage commit"
        return {"synthetic": True}

    session.commit.side_effect = commit
    row = {"status": ProcessingStatus.PROCESSING, "payload": {}}

    async def claim(_job, _owner, thread, attempt, **_kwargs):
        row["payload"] = {"thread_id": thread, "_execution_attempt_v1": attempt}
        return True

    repository = SimpleNamespace(
        claim_chat_execution=claim,
        lock_prepared_turn=AsyncMock(return_value=row),
        stage_execution_accounting=AsyncMock(return_value=failure != "stage"),
    )
    monkeypatch.setattr(run_execution, "_reserve_run", reserve)
    monkeypatch.setattr(run_execution, "_prepare_context", AsyncMock(return_value=object()))
    provider = AsyncMock(side_effect=execute)
    monkeypatch.setattr(run_execution, "_execute_agent", provider)
    call = run_execution._run_or_restore(
        request,
        config=object(),
        pg_connector=object(),
        redis_client=None,
        publisher=Mock(),
        job_repo=repository,
        file_service=object(),
        session=session,
        state=MutableRunState(),
        hooks=SimpleNamespace(prepared_results=None),
        agent_execution=None,
    )
    if failure:
        with pytest.raises(JobStateUnavailable) as error:
            await call
        assert "PRIVATE_COMMIT_MARKER" not in str(error.value)
        provider.assert_not_awaited()
    else:
        result, _, short_circuit = await call
        assert result == {"synthetic": True} and short_circuit is None
    repository.stage_execution_accounting.assert_awaited_once()
    assert session.commit.await_count == (1 if failure == "stage" else 2)
