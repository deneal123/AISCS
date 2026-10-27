"""Only exact committed local adapter facts can resolve an uncertain fee."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4, uuid5

import pytest
from pydantic import ValidationError

from service.services.chat.persistence.harness.fee_reconciliation import reconcile_tool_fees
from service.shared.harness_protocol import EffectIntent, EffectResult, PaidCall
from service.shared.task_contract import digest_payload


def known_effect(*, charged=True, status="succeeded"):
    effect = EffectIntent(
        operation_id=str(uuid4()),
        name="ide_write_file",
        action="write",
        arguments='{"path":"a.py"}',
        source_revision="r1",
    )
    fee = PaidCall(
        operation_id=str(uuid5(UUID(effect.operation_id), "billing")),
        provider="local",
        model="workspace_tool",
        prompt=0,
        completion=0,
        request_digest=digest_payload(effect.model_dump(mode="json")),
        kind="tool",
        billing_tool="workspace_tool",
    )
    return {
        "operation_id": UUID(fee.operation_id),
        "request": fee.model_dump(mode="json"),
        "intent": effect.model_dump(mode="json"),
        "receipt": EffectResult(
            operation_id=effect.operation_id,
            status=status,
            text="PRIVATE_RESULT",
            charged=charged,
        ).model_dump(mode="json"),
    }


def session(rows):
    return SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: rows))
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "charged,status", [(True, "succeeded"), (False, "succeeded"), (False, "failed")]
)
async def test_fee_resolves_without_dispatch_or_new_charge(charged, status):
    row, task = known_effect(charged=charged, status=status), uuid4()
    db = session([row])
    assert await reconcile_tool_fees(db, task) == 1
    query, params = db.execute.call_args.args
    assert params["state"] == ("succeeded" if charged else "waived")
    assert params["task"] == task and params["operation"] == row["operation_id"]
    assert "state IN ('dispatched','unknown')" in str(query)
    assert "token_reservations" not in str(query) and "PRIVATE_RESULT" not in params["receipt"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault",
    [
        "legacy",
        "unknown",
        "fee_id",
        "operation",
        "receipt_id",
        "digest",
        "provider",
        "tokens",
    ],
)
async def test_missing_or_unrelated_proof_cannot_release_uncertainty(fault):
    row = known_effect()
    if fault == "legacy":
        row["receipt"].pop("charged")
    elif fault == "unknown":
        row["receipt"].update(status="unknown", charged=None)
    elif fault == "fee_id":
        row["request"]["operation_id"] = str(uuid4())
    elif fault == "operation":
        row["operation_id"] = uuid4()
    elif fault == "receipt_id":
        row["receipt"]["operation_id"] = str(uuid4())
    elif fault == "digest":
        row["request"]["request_digest"] = "0" * 64
    elif fault == "provider":
        row["request"]["provider"] = "openai"
    elif fault == "tokens":
        row["request"]["prompt"] = 1
    db = session([row])
    assert await reconcile_tool_fees(db, uuid4()) == 0
    assert db.execute.await_count == 1


@pytest.mark.parametrize(
    "status,charged", [("unknown", True), ("unknown", False), ("failed", True)]
)
def test_unknown_or_failed_adapter_cannot_assert_a_charge(status, charged):
    with pytest.raises(ValidationError):
        known_effect(status=status, charged=charged)
