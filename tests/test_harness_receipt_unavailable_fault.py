"""Недоступность RPC до handler отличается от потерянного committed ACK."""

import json

import pytest

from scripts.harness.live.lost_ack import LostAck
from scripts.harness.live.receipt_unavailable import ReceiptUnavailableMiddleware


@pytest.mark.asyncio
async def test_first_receipt_is_not_committed_but_same_retry_reaches_actual_handler():
    committed = []

    async def handler(scope, receive, send):
        committed.append(json.loads((await receive())["body"]))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    fault = LostAck("paid_receipt_unavailable")
    middleware = ReceiptUnavailableMiddleware(handler, fault)
    payload = {"opcode": "call_receipt", "receipt": {"prompt": 12, "status": "succeeded"}}
    for expected, count in [(503, 0), (200, 1)]:
        observed = []

        async def receive():
            return {"type": "http.request", "body": json.dumps(payload).encode()}

        async def send(message, output=observed):
            output.append(message)

        await middleware({"path": "/internal/harness/v1/exchange"}, receive, send)
        assert observed[0]["status"] == expected and len(committed) == count
    assert committed == [payload] and fault.count == 1
