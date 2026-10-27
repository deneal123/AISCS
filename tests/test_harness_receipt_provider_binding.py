"""Приватное состояние ответа не может подменить immutable provider grant."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.services.chat.persistence.harness import grants
from service.shared.harness_protocol import HarnessFailure
from tests.test_harness_late_usage_receipt import confirmation


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider,model,tool",
    [
        ("gigachat", "test", False),
        ("openai", "test", False),
        ("gigachat", "different", False),
        ("gigachat", "test", True),
    ],
)
async def test_state_is_bound_to_original_model_grant(monkeypatch, provider, model, tool):
    receipt = confirmation(str(uuid4()))
    receipt = type(receipt).model_validate(
        {
            **receipt.model_dump(),
            "provider_state": {"provider": provider, "model": model, "state_id": "PRIVATE_STATE"},
        }
    )
    request = {"provider": "gigachat", "model": "test", "prompt": 30, "completion": 20}
    if tool:
        request["billing_tool"] = "workspace_tool"
    monkeypatch.setattr(
        grants,
        "_read",
        AsyncMock(
            return_value={
                "state": "dispatched",
                "receipt": None,
                "request": request,
            }
        ),
    )
    db = SimpleNamespace(execute=AsyncMock())
    if provider == "gigachat" and model == "test" and not tool:
        assert await grants.record(db, {"task_id": uuid4()}, receipt) == {"status": "succeeded"}
        assert db.execute.await_count == 1
    else:
        with pytest.raises(HarnessFailure, match="provider_state_incompatible"):
            await grants.record(db, {"task_id": uuid4()}, receipt)
        db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_confirmed_receipt_duplicate_remains_idempotent(monkeypatch):
    receipt = confirmation(str(uuid4()))
    previous = receipt.model_dump(mode="json", exclude={"provider_state"})
    monkeypatch.setattr(
        grants,
        "_read",
        AsyncMock(
            return_value={
                "state": "succeeded",
                "receipt": previous,
                "request": {},
            }
        ),
    )
    db = SimpleNamespace(execute=AsyncMock())
    assert await grants.record(db, {"task_id": uuid4()}, receipt) == {"status": "succeeded"}
    db.execute.assert_not_awaited()
