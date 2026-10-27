"""Private managed audit replay/recovery never re-invokes the metered producer."""

import asyncio
import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from service.domain.execution.context import PrivateRunResources, use_run_execution
from service.presentation.routers.capabilities import document_audit as endpoint
from service.presentation.routers.capabilities import managed_document_audit as managed
from tests.test_document_audit_registry import RedisFixture


def payload():
    return endpoint.DocumentAuditRequest(
        build_id="fixture-build",
        workspace_ref={
            "user_id": str(uuid4()),
            "workspace_id": "fixture-workspace",
            "coordination_capability": "PRIVATE_CAPABILITY_MARKER",
        },
        checkpoint_attempt_id=uuid4(),
        fresh_attempt=True,
    )


@pytest.mark.parametrize("field", ["fresh_attempt", "recovery_only"])
@pytest.mark.parametrize("value", [1, "true", None])
def test_execution_ownership_flags_do_not_coerce_untrusted_values(field, value):
    body = payload().model_dump()
    body[field] = value
    with pytest.raises(ValidationError):
        endpoint.DocumentAuditRequest.model_validate(body)


async def receipt(execution, checkpoint):
    await checkpoint(execution.usage)
    execution.usage.record_usage(
        {"prompt": 30, "completion": 3},
        provider="gigachat",
        model="GigaChat-2-Max",
        kind="document_visual_audit",
        receipt_id="fixture-call",
    )
    await checkpoint(execution.usage)


@pytest.mark.asyncio
async def test_explicit_seal_replay_and_recovery_read_without_second_execution(monkeypatch):
    redis = RedisFixture()
    monkeypatch.setattr(managed, "get_redis", lambda: redis)
    monkeypatch.setattr(endpoint, "internal_auth", lambda _: None)
    request = payload()
    invoked = []

    async def execute(_payload, *, usage_checkpoint):
        invoked.append(True)
        with use_run_execution(PrivateRunResources()) as execution:
            await receipt(execution, usage_checkpoint)
            return {
                "status": "failed",
                "passed": False,
                "retryable": False,
                "usage": execution.usage.project_since(0),
            }

    first = await managed.execute_managed_audit(request, execute)
    replay = await managed.execute_managed_audit(request, execute)
    assert first["usage"]["total"] == replay["usage"]["total"] == 33
    assert replay["status"] == "failed" and invoked == [True]
    recovered = await endpoint.audit_document(request.model_copy(update={"recovery_only": True}))
    assert set(recovered) == {"state", "checkpoint", "result"}
    assert recovered["state"] == "terminal" and recovered["checkpoint"]["revision"] == 1
    assert "PRIVATE_CAPABILITY_MARKER" not in json.dumps(redis.values)
    assert "producer_token" not in json.dumps(recovered)
    mismatch = request.model_copy(
        update={"workspace_ref": {**request.workspace_ref, "user_id": str(uuid4())}}
    )
    assert await endpoint.audit_document(mismatch.model_copy(update={"recovery_only": True})) == {
        "state": "unavailable"
    }


@pytest.mark.asyncio
async def test_redis_unavailable_does_not_begin_metered_work(monkeypatch):
    monkeypatch.setattr(managed, "get_redis", lambda: None)
    invoked = []

    async def execute(*args, **kwargs):
        invoked.append(True)

    result = await managed.execute_managed_audit(payload(), execute)
    assert result["status"] == "unavailable" and not invoked


@pytest.mark.asyncio
async def test_exception_after_receipt_seals_known_expense_without_raw_body(monkeypatch):
    redis = RedisFixture()
    monkeypatch.setattr(managed, "get_redis", lambda: redis)
    request = payload()

    async def execute(_payload, *, usage_checkpoint):
        with use_run_execution(PrivateRunResources()) as execution:
            await receipt(execution, usage_checkpoint)
            raise RuntimeError("PRIVATE_PROVIDER_BODY_MARKER")

    result = await managed.execute_managed_audit(request, execute)
    snapshot = await managed.registry_for(request).snapshot()
    assert result["status"] == "internal" and result["usage"]["total"] == 33
    assert snapshot["state"] == "terminal" and snapshot["result"]["status"] == "internal"
    assert "PRIVATE_PROVIDER_BODY_MARKER" not in json.dumps([result, redis.values])


@pytest.mark.asyncio
async def test_cancelled_producer_flushes_receipt_and_seals_cancellation(monkeypatch):
    redis = RedisFixture()
    monkeypatch.setattr(managed, "get_redis", lambda: redis)
    request = payload()
    entered = asyncio.Event()

    async def execute(_payload, *, usage_checkpoint):
        with use_run_execution(PrivateRunResources()) as execution:
            await receipt(execution, usage_checkpoint)
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(managed.execute_managed_audit(request, execute))
    async with asyncio.timeout(1):
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    snapshot = await managed.registry_for(request).snapshot()
    assert snapshot["state"] == "terminal"
    assert snapshot["result"] == {"status": "cancelled", "passed": False, "retryable": True}
    assert len(snapshot["checkpoint"]["receipts"]) == 1
