"""Конфликт продолжения виден пользователю, но не создаёт terminal или списание."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from service.services.chat.infrastructure.chat_worker.execution.job_state import (
    HarnessAdmissionUnavailable,
)
from service.services.chat.infrastructure.chat_worker.execution.preflight import (
    abort_unverified_job,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["binding_changed", "project_unavailable", "PRIVATE_RAW_REASON"])
async def test_admission_failure_publishes_only_closed_reason_and_keeps_state(reason):
    session = SimpleNamespace(rollback=AsyncMock(), execute=AsyncMock(), commit=AsyncMock())
    publisher = SimpleNamespace(publish_payload=Mock())
    result = await abort_unverified_job(
        session=session,
        publisher=publisher,
        error=HarnessAdmissionUnavailable(reason),
        job_id="own-job",
    )
    assert result["status"] == "error" and "заблокировано" in result["error"]
    assert "PRIVATE" not in str(result) and "PRIVATE" not in str(
        publisher.publish_payload.call_args
    )
    session.rollback.assert_awaited_once()
    session.execute.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_denied_worker_admission_never_enters_agents_dispatch(monkeypatch):
    from service.services.chat.infrastructure.chat_worker.execution.dispatch import _execute_agent
    from service.services.chat.infrastructure.chat_worker.harness import admission
    from service.services.chat.infrastructure.chat_worker.run_contracts import (
        MutableRunState,
        WorkerRunRequest,
    )
    from service.shared.harness_protocol import HarnessFailure

    attach = AsyncMock(side_effect=HarnessFailure("binding_changed"))
    monkeypatch.setattr(admission, "attach_harness", attach)
    engine = SimpleNamespace(execute=AsyncMock())
    redis = object()
    with pytest.raises(HarnessAdmissionUnavailable) as raised:
        await _execute_agent(
            WorkerRunRequest(job_id="job", thread_id="thread", text="Продолжи", user_id="owner"),
            None,
            config=None,
            redis_client=redis,
            state=MutableRunState(),
            hooks=None,
            agent_execution=engine,
            job_repo=None,
        )
    assert "версия исходников" in raised.value.public_message
    assert attach.await_args.kwargs["redis_client"] is redis
    engine.execute.assert_not_awaited()
