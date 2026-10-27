"""Backend не сбрасывает continuation counters и не придумывает terminal старого receipt."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.services.chat.persistence.harness import grants
from service.services.chat.persistence.harness.runtime import _checkpoint
from service.shared.harness_protocol import CallReceipt, Continuation, HarnessFailure


@pytest.mark.asyncio
@pytest.mark.parametrize("counter", [0, 1])
async def test_checkpoint_cannot_reset_consumed_length_continuations(counter):
    current = SimpleNamespace(
        state=object(), continuation=Continuation(length_continuations=2, call_payload_version=2)
    )
    request = SimpleNamespace(
        continuation=Continuation(
            length_continuations=counter,
            call_payload_version=2,
        )
    )
    db = SimpleNamespace(execute=AsyncMock())
    with pytest.raises(HarnessFailure, match="operation_conflict"):
        await _checkpoint(db, {}, request, current)
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_receipt_repeat_remains_an_accounting_noop(monkeypatch):
    receipt = CallReceipt(
        operation_id=str(uuid4()),
        status="succeeded",
        prompt=10,
        completion=3,
        message={"role": "assistant", "content": "Сохранённая часть"},
    )
    legacy = receipt.model_dump(mode="json")
    legacy.pop("finish_reason")
    legacy.pop("provider_state")
    row = {"state": "succeeded", "receipt": legacy}
    monkeypatch.setattr(grants, "_read", AsyncMock(return_value=row))
    db = SimpleNamespace(execute=AsyncMock())
    assert await grants.record(db, {}, receipt) == {"status": "succeeded"}
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_known_cost_cannot_gain_an_invented_finish_reason(monkeypatch):
    receipt = CallReceipt(
        operation_id=str(uuid4()),
        status="succeeded",
        prompt=10,
        completion=3,
        message={"role": "assistant", "content": "Сохранённая часть"},
    )
    original = receipt.model_dump(mode="json")
    row = {"state": "succeeded", "receipt": deepcopy(original), "request": {}}
    monkeypatch.setattr(grants, "_read", AsyncMock(return_value=row))
    db = SimpleNamespace(execute=AsyncMock())
    with pytest.raises(HarnessFailure, match="operation_unknown"):
        await grants.record(db, {}, receipt.model_copy(update={"finish_reason": "stop"}))
    assert row["receipt"] == original
    db.execute.assert_not_awaited()
