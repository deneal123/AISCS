"""Сбой записи receipt не повторяет provider call и не стирает известный результат."""

import json
from unittest.mock import AsyncMock

import httpx
import pytest

from service.domain.client.calls.harness_stream import paid_stream
from service.domain.client.calls.harness_transport import paid_chat
from service.domain.client.protocol import ProviderRoundState
from service.domain.execution.context import PrivateRunResources, use_run_execution
from service.shared.harness_protocol import HarnessFailure
from tests.test_harness_reconciliation import Journal
from tests.test_harness_runtime import response


class ReceiptStorage(Journal):
    def __init__(self, *, always=False, lose_second_ack=False):
        super().__init__(None)
        self.failed = False
        self.always = always
        self.sent_receipts = []
        self.lose_second_ack = lose_second_ack

    def __call__(self, request):
        payload = json.loads(request.content)
        if payload["opcode"] == "call_receipt":
            self.sent_receipts.append(payload["receipt"])
            if self.always or not self.failed:
                self.failed = True
                self.counts["call_receipt"] += 1
                return httpx.Response(503, json={"detail": {"code": "checkpoint_unavailable"}})
        result = super().__call__(request)
        if (
            payload["opcode"] == "call_receipt"
            and self.lose_second_ack
            and len(self.sent_receipts) == 2
        ):
            raise httpx.ReadTimeout("PRIVATE_SECOND_RECEIPT_ACK")
        return result


@pytest.mark.asyncio
@pytest.mark.parametrize("lose_second_ack", [False, True])
async def test_uncommitted_receipt_is_reposted_once_after_read_without_provider_replay(
    lose_second_ack,
):
    journal = ReceiptStorage(lose_second_ack=lose_second_ack)
    client = journal.client()
    with use_run_execution(PrivateRunResources()) as execution:
        execution.harness = client
        send = AsyncMock(return_value=response())
        result, _ = await paid_chat(
            send, provider="openai", model="test", payload={"max_tokens": 100}
        )
        assert result.choices[0].message.content == "done"
        assert send.await_count == journal.counts["dispatch"] == 1
        assert journal.counts["call_receipt"] == 2
        assert journal.sent_receipts[0] == journal.sent_receipts[1]
        assert all(item["status"] == "succeeded" for item in journal.sent_receipts)
        assert client.failure == "" and len(execution.usage.receipts) == 1


@pytest.mark.asyncio
async def test_unavailable_receipt_storage_does_not_replace_known_usage_with_unknown():
    journal = ReceiptStorage(always=True)
    client = journal.client()
    with use_run_execution(PrivateRunResources()) as execution:
        execution.harness = client
        send = AsyncMock(return_value=response())
        with pytest.raises(HarnessFailure, match="checkpoint_unavailable"):
            await paid_chat(send, provider="openai", model="test", payload={"max_tokens": 100})
        assert send.await_count == 1
        assert len(journal.sent_receipts) == 2
        assert journal.sent_receipts[0] == journal.sent_receipts[1]
        assert all(item["status"] == "succeeded" for item in journal.sent_receipts)
        assert next(iter(journal.operations.values()))["status"] == "dispatched"


@pytest.mark.asyncio
@pytest.mark.parametrize("always", [False, True])
async def test_stream_preserves_known_receipt_and_never_replays_the_provider(always):
    journal = ReceiptStorage(always=always)
    client = journal.client()
    sent = []
    state = ProviderRoundState(prompt=10, completion=2, total=12, finish_reason="stop")

    async def send(operation):
        sent.append(operation)
        yield "done"

    async def collect():
        return [
            item
            async for item in paid_stream(
                send,
                provider="openai",
                model="test",
                messages=[],
                parameters={"round_state": state, "max_tokens": 100},
            )
        ]

    with use_run_execution(PrivateRunResources()) as execution:
        execution.harness = client
        if always:
            with pytest.raises(HarnessFailure, match="checkpoint_unavailable"):
                await collect()
        else:
            assert await collect() == ["done"]
        assert len(sent) == 1 and len(journal.sent_receipts) == 2
        assert journal.sent_receipts[0] == journal.sent_receipts[1]
        assert all(item["status"] == "succeeded" for item in journal.sent_receipts)
