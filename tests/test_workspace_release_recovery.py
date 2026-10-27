"""Destruction is independent of allocation policy and clears only its exact binding."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service.infrastructure import workspace_client as wc


@pytest.mark.asyncio
@pytest.mark.parametrize("cleanup_result", [0, 1])
@pytest.mark.parametrize(
    "status,body,acknowledged",
    [
        (200, {"deleted": "owned"}, True),
        (404, {"error": "workspace_not_found"}, True),
        (200, {"deleted": "other"}, False),
        (404, {"detail": "Not Found"}, False),
        (403, {"error": "forbidden"}, False),
        (409, {"error": "workspace_cleanup_pending"}, False),
        (503, {"error": "unavailable"}, False),
    ],
)
async def test_release_requires_exact_destruction_ack_even_with_autocreate_off(
    monkeypatch,
    status,
    body,
    acknowledged,
    cleanup_result,
):
    ref = {"workspace_id": "owned", "user_id": "fixture-owner", "token": "private-token"}
    redis = SimpleNamespace(
        get=AsyncMock(return_value=json.dumps(ref)),
        eval=AsyncMock(return_value=cleanup_result),
        delete=AsyncMock(),
    )
    monkeypatch.setattr(wc, "_is_async_client", lambda _: True)
    monkeypatch.setattr(wc, "_config", lambda: (False, "http://workspace:8080", 30, "key", 600))
    client = AsyncMock()
    client.request.return_value = SimpleNamespace(status_code=status, json=lambda: body)
    client.__aenter__.return_value = client
    monkeypatch.setattr(wc.httpx, "AsyncClient", lambda **_: client)
    result = await wc.release_workspace(redis, "fixture-thread")
    assert result is (acknowledged and cleanup_result == 1)
    client.request.assert_awaited_once()
    redis.delete.assert_not_awaited()
    if acknowledged:
        redis.eval.assert_awaited_once()
        assert redis.eval.call_args.args[1:] == (1, "chat:fixture-thread:workspace", "owned")
    else:
        redis.eval.assert_not_awaited()
