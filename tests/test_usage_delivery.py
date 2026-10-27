"""Private ACK commits a fresh owned transaction, never emits public events or charges."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.models.key_value import ProcessingStatus
from service.services.chat.infrastructure.chat_worker.billing.usage.delivery import (
    usage_checkpoint_sink,
)
from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.chat.infrastructure.chat_worker.run_contracts import (
    MutableRunState,
    WorkerRunRequest,
)


def fixture():
    request = WorkerRunRequest(str(uuid4()), str(uuid4()), "synthetic", str(uuid4()))
    state = MutableRunState(execution_attempt_id=str(uuid4()))
    session = AsyncMock()

    @asynccontextmanager
    async def transaction():
        yield session

    repo = SimpleNamespace(
        connector=SimpleNamespace(get_session_context=transaction),
        lock_prepared_turn=AsyncMock(
            return_value={
                "status": ProcessingStatus.PROCESSING,
                "payload": {
                    "thread_id": request.thread_id,
                    "_execution_attempt_v1": state.execution_attempt_id,
                },
            }
        ),
        stage_usage_journal=AsyncMock(return_value=True),
    )
    payload = {
        "schema_version": 1,
        "attempt_id": state.execution_attempt_id,
        "revision": 1,
        "receipts": [
            {
                "receipt_id": "call",
                "provider": "openai",
                "model": "synthetic",
                "kind": None,
                "prompt": 2,
                "completion": 1,
                "estimated": False,
            }
        ],
    }
    return request, state, session, repo, payload


@pytest.mark.asyncio
async def test_private_checkpoint_ack_requires_commit():
    request, state, session, repo, payload = fixture()
    await usage_checkpoint_sink(repo, request, state)(payload)
    assert state.usage_checkpoint_observed and state.usage_checkpointed
    assert state.usage_journal.payload() == payload
    session.commit.assert_awaited_once()
    repo.stage_usage_journal.assert_awaited_once()


@pytest.mark.asyncio
async def test_commit_uncertainty_keeps_observed_usage_without_false_ack():
    request, state, session, repo, payload = fixture()
    session.commit.side_effect = RuntimeError("PRIVATE_COMMIT_MARKER")
    with pytest.raises(JobStateUnavailable) as error:
        await usage_checkpoint_sink(repo, request, state)(payload)
    assert state.usage_checkpoint_observed and not state.usage_checkpointed
    assert state.usage_journal is None
    assert "PRIVATE_COMMIT_MARKER" not in str(error.value)


@pytest.mark.asyncio
async def test_foreign_attempt_never_opens_storage_transaction():
    request, state, session, repo, payload = fixture()
    payload["attempt_id"] = str(uuid4())
    with pytest.raises(JobStateUnavailable):
        await usage_checkpoint_sink(repo, request, state)(payload)
    assert not state.usage_checkpoint_observed and not state.usage_checkpointed
    repo.lock_prepared_turn.assert_not_awaited()
    session.commit.assert_not_awaited()
