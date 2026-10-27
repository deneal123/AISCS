"""Worker передаёт проверенную среду в admission, не данные предложения модели."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.services.chat.infrastructure.chat_worker.harness import admission as module


@pytest.mark.asyncio
async def test_new_ide_task_seals_private_workspace_from_resolved_reference(monkeypatch):
    flags = SimpleNamespace(
        ide_enabled=True, pdf_enabled=True, prompt_limit=32768, completion_limit=4096
    )
    monkeypatch.setattr(module, "settings", lambda: flags)
    monkeypatch.setattr(module, "freeze_pricing", AsyncMock(return_value=object()))
    admit = AsyncMock()
    monkeypatch.setattr(module.HarnessRuntimeRepository, "admit", admit)
    request = SimpleNamespace(
        job_id=str(uuid4()),
        thread_id=str(uuid4()),
        user_id=str(uuid4()),
        selected_model="test",
        text="Прочитай a.py",
        question_resume=None,
    )
    state = SimpleNamespace(
        engine_env={
            "workspace_ref": {
                "workspace_id": "a" * 32,
                "ide_context": {"repository_id": str(uuid4()), "generation": "generation"},
            }
        },
        harness_task_id=None,
        reservation_id=str(uuid4()),
        execution_attempt_id=str(uuid4()),
        reserved_estimate=100,
        harness_epoch=1,
    )
    await module.attach_harness(
        request, state, SimpleNamespace(connector=object()), SimpleNamespace(billing=object())
    )
    accepted = admit.await_args.args[1]
    assert accepted.workspace_id == "a" * 32
    assert accepted.goal == request.text and accepted.actions == ("read", "write", "exec")
    assert state.harness_task_id == request.job_id
