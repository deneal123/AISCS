"""Only confirmed pre-create validation failures may close an exec intent."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.services.chat.persistence.harness.commands import recipes
from service.shared.harness_protocol import HarnessFailure


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code",
    [
        "task_permission_denied",
        "operation_conflict",
        "usage_limit_exceeded",
        "verification_unavailable",
    ],
)
async def test_known_recipe_refusal_gets_backend_failed_receipt(monkeypatch, code):
    failure = HarnessFailure(code)
    monkeypatch.setattr(recipes, "bind_recipe", AsyncMock(side_effect=failure))
    record = AsyncMock()
    monkeypatch.setattr(recipes.effects, "record", record)
    operation = uuid4()
    actual = await recipes.bind_or_reject(None, {}, SimpleNamespace(), None, operation)
    assert actual is failure
    receipt = record.await_args.args[2]
    assert receipt.operation_id == str(operation) and receipt.status == "failed"
    assert receipt.charged is False and not receipt.evidence
    assert record.await_args.kwargs["reconciled"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["checkpoint_unavailable", "operation_unknown", "binding_changed"])
async def test_uncertain_failures_do_not_mint_a_failed_receipt(monkeypatch, code):
    monkeypatch.setattr(recipes, "bind_recipe", AsyncMock(side_effect=HarnessFailure(code)))
    record = AsyncMock()
    monkeypatch.setattr(recipes.effects, "record", record)
    with pytest.raises(HarnessFailure, match=code):
        await recipes.bind_or_reject(None, {}, SimpleNamespace(), None, uuid4())
    record.assert_not_awaited()


@pytest.mark.asyncio
async def test_successful_recipe_binding_does_not_settle_an_effect(monkeypatch):
    monkeypatch.setattr(recipes, "bind_recipe", AsyncMock())
    record = AsyncMock()
    monkeypatch.setattr(recipes.effects, "record", record)
    assert await recipes.bind_or_reject(None, {}, SimpleNamespace(), None, uuid4()) is None
    record.assert_not_awaited()
