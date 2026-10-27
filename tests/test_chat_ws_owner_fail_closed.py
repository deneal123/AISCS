"""An ownership lookup outage must not expose Redis replay/stream data."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from service.services.chat.presentation.ws.chat_ws.connection import ChatWsConnectionService


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["outage", "other_owner"])
async def test_denied_owner_check_stops_before_any_stream_access(failure, caplog):
    private_marker = "PRIVATE_DATABASE_EXCEPTION_MARKER"
    lookup = AsyncMock(
        side_effect=RuntimeError(private_marker) if failure == "outage" else None,
        return_value="another-owner",
    )
    stream = SimpleNamespace(
        ensure_group=AsyncMock(),
        handle_replay=AsyncMock(),
        handle_pending_messages=AsyncMock(),
        resolve_cursor=AsyncMock(),
        consume_events=AsyncMock(),
    )
    websocket = SimpleNamespace(close=AsyncMock())
    handler = SimpleNamespace(handle_incoming_messages=AsyncMock())
    metrics = Mock()
    service = ChatWsConnectionService(
        SimpleNamespace(authenticate=AsyncMock(return_value={"user_id": "requesting-owner"})),
        stream,
        handler,
        SimpleNamespace(),
        metrics,
        chat_service=SimpleNamespace(persistence_service=SimpleNamespace(get_thread_owner=lookup)),
    )
    await service.run(websocket, "requested-thread", last_id="replay-cursor")
    websocket.close.assert_awaited_once_with(code=1011 if failure == "outage" else 1008)
    for operation in vars(stream).values():
        operation.assert_not_called()
    handler.handle_incoming_messages.assert_not_called()
    metrics.inc.assert_not_called()
    assert private_marker not in caplog.text
    assert "requested-thread" not in caplog.text


@pytest.mark.asyncio
async def test_confirmed_owner_is_allowed():
    service = ChatWsConnectionService(
        object(),
        object(),
        object(),
        object(),
        object(),
        chat_service=SimpleNamespace(
            persistence_service=SimpleNamespace(get_thread_owner=AsyncMock(return_value="owner"))
        ),
    )
    websocket = SimpleNamespace(close=AsyncMock())
    assert await service._ensure_thread_owner(websocket, "owned-thread", "owner") is True
    websocket.close.assert_not_called()
