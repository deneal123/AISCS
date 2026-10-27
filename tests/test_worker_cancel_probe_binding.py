"""Executing worker supplies owned, fresh-session cancellation observation."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.services.chat.infrastructure.chat_worker.execution.run import _execute_agent
from service.services.chat.infrastructure.chat_worker.phases import RunPhase
from service.services.chat.infrastructure.chat_worker.run_contracts import (
    MutableRunState,
    PreparedRunContext,
    WorkerRunRequest,
)


@pytest.mark.asyncio
async def test_execution_binds_durable_probe_to_exact_owner_job_thread():
    owner, job = uuid4(), uuid4()
    request = WorkerRunRequest(
        job_id=str(job),
        user_id=str(owner),
        thread_id="synthetic-thread",
        text="synthetic",
        celery_task_id="synthetic-task",
    )
    prepared = PreparedRunContext(
        pseudo_session=None,
        file_context="",
        memory_parts=("", ""),
        history_messages=[],
        compact_summary="",
        persona_switched=False,
        tabular_files=[],
        reference_image_url=None,
        has_non_tabular_attachment=False,
        repo_graph_ids=[],
        attachments=[],
        on_event=None,
        workflow_observations=[],
        workflow_executions=[],
    )
    repository = SimpleNamespace(is_chat_cancel_requested=AsyncMock(return_value=False))
    engine = SimpleNamespace(execute=AsyncMock(return_value={"reply": "accepted"}))

    async def watcher(awaitable, *, durable_cancel, redis_client, celery_task_id):
        assert redis_client is None
        assert celery_task_id == "synthetic-task"
        assert await durable_cancel() is False
        return await awaitable

    state = MutableRunState()
    state.phase.advance(RunPhase.RESERVED)
    result = await _execute_agent(
        request,
        prepared,
        config=None,
        redis_client=None,
        state=state,
        hooks=SimpleNamespace(run_with_cancel=watcher),
        agent_execution=engine,
        job_repo=repository,
    )
    assert result == {"reply": "accepted"}
    repository.is_chat_cancel_requested.assert_awaited_once_with(job, owner, "synthetic-thread")
    assert state.phase.phase == RunPhase.EXECUTING
