"""Изменение step или кода предложения не разрешает вторую платную операцию."""

import json
from unittest.mock import AsyncMock

import httpx
import pytest

from service.domain.client.calls.harness_transport import (
    paid_chat,
    use_kind,
    use_refinement_operation,
)
from service.domain.execution.context import PrivateRunResources, use_run_execution
from service.shared.harness_protocol import HarnessFailure, PaidCall
from service.shared.task_contract import digest_payload
from tests.test_harness_reconciliation import Journal
from tests.test_harness_runtime import response


class StrictJournal(Journal):
    def __call__(self, request):
        payload = json.loads(request.content)
        if payload["opcode"] == "grant":
            call = PaidCall.model_validate(payload["call"])
            old = self.operations.get(("paid", call.operation_id))
            if old and old["request_digest"] != digest_payload(call.model_dump(mode="json")):
                return httpx.Response(409, json={"detail": {"code": "operation_conflict"}})
        return super().__call__(request)


@pytest.mark.asyncio
@pytest.mark.parametrize("lost", [None, "grant", "call_receipt"])
async def test_same_refinement_is_replayed_after_step_change_without_new_charge(lost):
    journal = StrictJournal(lost)
    send = AsyncMock(return_value=response())
    with use_run_execution(PrivateRunResources()) as execution:
        execution.harness = journal.client()
        identities = []
        for step in (0, 1):
            execution.harness.current = execution.harness.current.model_copy(
                update={
                    "continuation": execution.harness.current.continuation.model_copy(
                        update={"next_step": step}
                    )
                }
            )
            with use_kind("meta_usage"), use_refinement_operation():
                _, identity = await paid_chat(
                    send, provider="openai", model="test", payload={"max_tokens": 100}
                )
            identities.append(identity)
        assert identities[0] == identities[1]
        assert len(execution.usage.receipts) == 1
    assert send.await_count == journal.counts["dispatch"] == journal.counts["call_receipt"] == 1


@pytest.mark.asyncio
async def test_changed_refinement_request_blocks_instead_of_allocating_new_paid_operation():
    journal = StrictJournal(None)
    send = AsyncMock(return_value=response())
    with use_run_execution(PrivateRunResources()) as execution:
        execution.harness = journal.client()
        with use_kind("meta_usage"), use_refinement_operation():
            await paid_chat(send, provider="openai", model="test", payload={"max_tokens": 100})
            with pytest.raises(HarnessFailure, match="operation_conflict"):
                await paid_chat(send, provider="openai", model="test", payload={"max_tokens": 99})
    assert send.await_count == journal.counts["dispatch"] == 1
