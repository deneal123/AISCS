"""The outbox retries one committed child, never a user request or transcript."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4, uuid5

import pytest

from service.services.chat.application.human_questions.dispatch import dispatch_question_children
from service.services.chat.domain.human_questions.dispatch import QuestionDispatch
from service.services.chat.domain.human_questions.resume import RESUME_JOB_KEY


def claim():
    question = uuid4()
    return QuestionDispatch(
        uuid5(question, "gpthub:human-question:resume:v1"), uuid4(), uuid4(), question, uuid4()
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, None, 1])
async def test_disabled_dispatcher_does_not_read_or_send(enabled):
    repository, queue = (
        SimpleNamespace(claim_pending=AsyncMock()),
        SimpleNamespace(enqueue_agent_message=Mock()),
    )
    assert await dispatch_question_children(repository, queue, enabled=enabled) == {
        "claimed": 0,
        "acknowledged": 0,
        "deferred": 0,
    }
    repository.claim_pending.assert_not_awaited()
    queue.enqueue_agent_message.assert_not_called()


@pytest.mark.asyncio
async def test_commit_failure_cannot_authorize_broker_delivery():
    queue = SimpleNamespace(enqueue_agent_message=Mock())
    repository = SimpleNamespace(claim_pending=AsyncMock(side_effect=RuntimeError("PRIVATE")))
    with pytest.raises(RuntimeError):
        await dispatch_question_children(repository, queue, enabled=True)
    queue.enqueue_agent_message.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome", ["ack", "lost_broker_ack", "wrong_id", "lost_storage_ack", "stale_lease"]
)
async def test_only_matching_receipt_acknowledges_and_unknown_retry_uses_same_child(outcome):
    item = claim()
    repository = SimpleNamespace(
        claim_pending=AsyncMock(return_value=(item,)), acknowledge=AsyncMock(return_value=True)
    )
    queue = SimpleNamespace(enqueue_agent_message=Mock(return_value=item.task_id))
    if outcome == "lost_broker_ack":
        queue.enqueue_agent_message.side_effect = RuntimeError("PRIVATE")
    if outcome == "wrong_id":
        queue.enqueue_agent_message.return_value = str(uuid4())
    if outcome == "lost_storage_ack":
        repository.acknowledge.side_effect = RuntimeError("PRIVATE")
    if outcome == "stale_lease":
        repository.acknowledge.return_value = False
    counts = await dispatch_question_children(repository, queue, enabled=True)
    assert counts == {
        "claimed": 1,
        "acknowledged": int(outcome == "ack"),
        "deferred": int(outcome != "ack"),
    }
    payload = queue.enqueue_agent_message.call_args.kwargs
    assert payload == {
        "job_id": str(item.job_id),
        "thread_id": str(item.thread_id),
        "user_id": str(item.user_id),
        "text": "",
        "session_data": {RESUME_JOB_KEY: str(item.job_id)},
        "_delivery_task_id": item.task_id,
        "queue": "agents",
    }
    if outcome in {"lost_broker_ack", "wrong_id"}:
        repository.acknowledge.assert_not_awaited()
    queue.enqueue_agent_message.side_effect = None
    queue.enqueue_agent_message.return_value = item.task_id
    repository.acknowledge.side_effect = None
    repository.acknowledge.return_value = True
    await dispatch_question_children(repository, queue, enabled=True)
    assert queue.enqueue_agent_message.call_args.kwargs == payload


def test_celery_delivery_identity_is_transport_only_and_does_not_retry_publish(monkeypatch):
    from service.infrastructure.messaging import ports

    publish = Mock(return_value=SimpleNamespace(id="stable-child"))
    monkeypatch.setattr(ports.celery_app, "send_task", publish)
    queue = ports.CeleryJobQueuePort()
    assert (
        queue.enqueue_agent_message(
            job_id="stable-child", _delivery_task_id="stable-child", queue="agents"
        )
        == "stable-child"
    )
    publish.assert_called_once_with(
        ports.tasks.process_agent_message.name,
        kwargs={"job_id": "stable-child"},
        task_id="stable-child",
        retry=False,
        queue="agents",
    )


def test_disabled_maintenance_never_builds_connector_or_broker(monkeypatch):
    from service.services.chat.infrastructure.chat_worker.continuation.dispatch import (
        dispatch_human_question_children,
    )

    monkeypatch.setattr(
        "service.settings.Config",
        lambda: SimpleNamespace(human_questions=SimpleNamespace(enabled=False)),
    )
    assert dispatch_human_question_children() == {"status": "skipped", "reason": "disabled"}
