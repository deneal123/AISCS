"""Backend replay не получает новый usage ID и не вызывает модель повторно."""

import json
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from service.domain.client.calls.harness_stream import paid_stream
from service.domain.client.calls.harness_transport import paid_chat
from service.domain.client.protocol import ProviderRoundState
from service.domain.execution.context import PrivateRunResources, use_run_execution
from service.infrastructure.harness.call_payload import replay_receipt
from service.shared.harness_protocol import CallReceipt, HarnessFailure
from tests.test_harness_reconciliation import Journal
from tests.test_harness_runtime import response


class CompletedSlot(Journal):
    def __call__(self, request):
        payload = json.loads(request.content)
        if payload["opcode"] == "grant" and self.operations:
            self.counts["grant"] += 1
            record = next(iter(self.operations.values()))
            return httpx.Response(
                200,
                json={
                    "operation": {
                        "status": "succeeded",
                        "operation_id": record["operation_id"],
                        "receipt": record["receipt"],
                    }
                },
            )
        return super().__call__(request)


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_changed_request_replay_accounts_the_original_receipt_once(streaming):
    journal = CompletedSlot(None)
    send = AsyncMock(return_value=response())
    streamed = []

    async def stream(operation_id):
        streamed.append(operation_id)
        yield "done"

    with use_run_execution(PrivateRunResources()) as execution:
        execution.harness = journal.client()
        ids = []
        for temperature in (0.1, 0.9):
            if streaming:
                assert [
                    value
                    async for value in paid_stream(
                        stream,
                        provider="openai",
                        model="test",
                        messages=[],
                        parameters={
                            "temperature": temperature,
                            "max_tokens": 100,
                            "round_state": ProviderRoundState(
                                prompt=10, completion=2, total=12, finish_reason="stop"
                            ),
                        },
                    )
                ] == ["done"]
            else:
                _, identity = await paid_chat(
                    send, provider="openai", model="test", payload={"temperature": temperature}
                )
                ids.append(identity)
        assert len(execution.usage.receipts) == 1
        assert execution.usage.receipts[0].receipt_id == next(iter(journal.operations))[1]
        assert journal.counts["dispatch"] == journal.counts["call_receipt"] == 1
        if streaming:
            assert len(streamed) == 1
        else:
            assert send.await_count == 1 and ids[0] == ids[1]


@pytest.mark.parametrize("identity", [None, "invalid", str(uuid4())])
def test_mismatched_alias_cannot_redirect_accounting(identity):
    requested = str(uuid4())
    receipt = CallReceipt(
        operation_id=requested,
        status="succeeded",
        prompt=1,
        message={"role": "assistant", "content": "Ответ"},
    ).model_dump(mode="json")
    with pytest.raises(HarnessFailure, match="provider_state_incompatible"):
        replay_receipt(requested, {"operation_id": identity, "receipt": receipt})
