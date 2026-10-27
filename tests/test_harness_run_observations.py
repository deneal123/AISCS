"""Наблюдатель приёмки сохраняет только закрытые статусы, не payload и секреты."""

from unittest.mock import AsyncMock

import pytest

from scripts.harness_live.run_observations import ObserveRuns


@pytest.mark.asyncio
async def test_run_observation_is_bounded_and_does_not_copy_private_requests_or_outputs():
    response = {"type": "http.response.body", "body": b"PRIVATE_TRANSCRIPT"}

    async def handler(scope, receive, send):
        await receive()
        await send({"type": "http.response.start", "status": 200})
        await send(response)

    rows = []
    observer = ObserveRuns(handler, rows)
    receive = AsyncMock(return_value={"type": "http.request", "body": b"PRIVATE_CAPABILITY"})
    send = AsyncMock()
    for _ in range(20):
        await observer({"type": "http", "path": "/run"}, receive, send)
    assert rows == [{"status": 200, "completed": True}] * 16
    assert "PRIVATE" not in str(rows)
    assert send.call_args_list[-1].args[0] is response


@pytest.mark.asyncio
async def test_unrelated_routes_are_not_recorded():
    handler = AsyncMock()
    rows = []
    scope, receive, send = {"type": "http", "path": "/health"}, AsyncMock(), AsyncMock()
    await ObserveRuns(handler, rows)(scope, receive, send)
    handler.assert_awaited_once_with(scope, receive, send)
    assert rows == []


@pytest.mark.asyncio
async def test_failed_stream_does_not_claim_completion_or_expose_exception_text():
    async def handler(scope, receive, send):
        await send({"type": "http.response.start", "status": 200})
        await send({"type": "http.response.body", "body": b"PRIVATE", "more_body": True})
        raise RuntimeError("PRIVATE_PROVIDER_DETAILS")

    rows = []
    with pytest.raises(RuntimeError):
        await ObserveRuns(handler, rows)({"path": "/run"}, AsyncMock(), AsyncMock())
    assert rows == [{"status": 200, "completed": False, "failure": "RuntimeError"}]


@pytest.mark.asyncio
async def test_unknown_exception_type_is_not_a_diagnostic_label():
    class PrivateProviderException(Exception):
        pass

    async def handler(scope, receive, send):
        raise PrivateProviderException()

    rows = []
    with pytest.raises(PrivateProviderException):
        await ObserveRuns(handler, rows)({"path": "/run"}, AsyncMock(), AsyncMock())
    assert rows == [{"status": None, "completed": False, "failure": "internal"}]
