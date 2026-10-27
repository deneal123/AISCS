"""Диагностика приёмки прозрачна для handler и не копирует приватные значения."""

from unittest.mock import AsyncMock

import pytest

from scripts.harness.live.crash_boundary import CrashAfterWrite, CrashBoundaryMiddleware


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        b"not-json",
        b"[]",
        b'{"opcode":[]}',
        b'{"opcode":"PRIVATE_CAPABILITY"}',
    ],
)
async def test_invalid_requests_do_not_change_the_handler_response_or_leak_opcode(body):
    response = {"type": "http.response.body", "body": b'{"detail":{"code":"PRIVATE_ERROR"}}'}

    async def handler(scope, receive, send):
        await receive()
        await send({"type": "http.response.start", "status": 422, "headers": []})
        await send(response)

    fault = CrashAfterWrite()
    receive = AsyncMock(return_value={"type": "http.request", "body": body})
    send = AsyncMock()
    await CrashBoundaryMiddleware(handler, fault)(
        {"type": "http", "path": "/internal/harness/v1/exchange"}, receive, send
    )
    assert send.call_args_list[-1].args[0] is response
    assert fault.responses == [{"opcode": None, "status": 422, "code": None}]
    assert "PRIVATE" not in str(fault.responses)
