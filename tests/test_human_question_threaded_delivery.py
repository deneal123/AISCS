"""Фоновые потоки используют настроенное Celery-приложение; сеть не вызывается."""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from service.infrastructure.messaging import ports
from service.services.chat.infrastructure.chat_worker.continuation import dispatch
from service.settings import config


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
async def test_background_question_wakeup_never_uses_shared_task_default_app(monkeypatch, enabled):
    from service.infrastructure.messaging.celery_app import celery_app

    monkeypatch.setattr(config.human_questions, "enabled", enabled)
    shared = Mock()
    monkeypatch.setattr(dispatch, "dispatch_human_question_children", shared)
    publish = Mock()
    monkeypatch.setattr(celery_app, "send_task", publish)
    await asyncio.to_thread(dispatch.trigger_human_question_dispatch)
    shared.apply_async.assert_not_called()
    if enabled:
        publish.assert_called_once_with(dispatch.DISPATCH_TASK, retry=False)
    else:
        publish.assert_not_called()


@pytest.mark.asyncio
async def test_outbox_child_keeps_configured_broker_and_operation_identity_in_another_thread(
    monkeypatch,
):
    publish = Mock(return_value=SimpleNamespace(id="stable-child"))
    monkeypatch.setattr(ports.celery_app, "send_task", publish)
    shared = SimpleNamespace(name="canonical-task", apply_async=Mock())
    monkeypatch.setattr(ports.tasks, "process_agent_message", shared)
    result = await asyncio.to_thread(
        ports.CeleryJobQueuePort().enqueue_agent_message,
        job_id="stable-child",
        _delivery_task_id="stable-child",
        queue="agents",
    )
    assert result == "stable-child"
    publish.assert_called_once_with(
        "canonical-task",
        kwargs={"job_id": "stable-child"},
        task_id="stable-child",
        retry=False,
        queue="agents",
    )
    shared.apply_async.assert_not_called()
