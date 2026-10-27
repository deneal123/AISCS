"""Точное позднее usage подтверждает прежнюю операцию, но не выдаёт новый dispatch."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from service.services.chat.persistence.harness import grants
from service.shared.harness_protocol import CallReceipt, HarnessFailure


def confirmation(operation_id):
    return CallReceipt(
        operation_id=operation_id,
        status="succeeded",
        prompt=12,
        completion=3,
        message={"role": "assistant", "content": "PRIVATE_RESPONSE"},
    )


@pytest.mark.asyncio
async def test_exact_late_model_receipt_can_resolve_unknown_without_dispatch(monkeypatch):
    operation = str(uuid4())
    read = AsyncMock(
        return_value={
            "state": "unknown",
            "receipt": None,
            "request": {"prompt": 30, "completion": 20},
        }
    )
    monkeypatch.setattr(grants, "_read", read)
    db = SimpleNamespace(execute=AsyncMock())
    result = await grants.record(db, {"task_id": uuid4()}, confirmation(operation))
    assert result == {"status": "succeeded"}
    assert db.execute.await_count == 1
    query, params = db.execute.await_args.args
    assert "harness_grant SET state" in str(query)
    assert "dispatched" not in str(query) and "token_reservations" not in str(query)
    assert params["operation_id"] == UUID(operation)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"estimated": True},
        {"status": "unknown"},
        {"status": "waived"},
        {"prompt": 0, "completion": 0},
        {"message": None},
        {"prompt": 31},
    ],
)
async def test_unknown_cannot_be_refined_by_an_estimate_empty_response_or_waiver(
    monkeypatch, change
):
    operation = str(uuid4())
    monkeypatch.setattr(
        grants,
        "_read",
        AsyncMock(
            return_value={
                "state": "unknown",
                "receipt": None,
                "request": {"prompt": 30, "completion": 20},
            }
        ),
    )
    receipt = confirmation(operation).model_copy(update=change)
    db = SimpleNamespace(execute=AsyncMock())
    with pytest.raises(HarnessFailure):
        await grants.record(db, {"task_id": uuid4()}, receipt)
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_tool_fee_unknown_still_requires_committed_adapter_reconciliation(monkeypatch):
    monkeypatch.setattr(
        grants,
        "_read",
        AsyncMock(
            return_value={
                "state": "unknown",
                "receipt": None,
                "request": {"billing_tool": "workspace_tool", "prompt": 30, "completion": 20},
            }
        ),
    )
    db = SimpleNamespace(execute=AsyncMock())
    with pytest.raises(HarnessFailure, match="operation_unknown"):
        await grants.record(db, {"task_id": uuid4()}, confirmation(str(uuid4())))
    db.execute.assert_not_awaited()
