"""Redis command detection must not issue the command twice or block the loop."""

import threading
from types import SimpleNamespace

import pytest

from service.infrastructure.cache.manager import call_redis


@pytest.mark.asyncio
async def test_sync_command_executes_once_off_loop():
    loop_thread = threading.get_ident()
    calls = []

    def operation(value, *, nx):
        calls.append((value, nx, threading.get_ident()))
        return True

    assert await call_redis(SimpleNamespace(set=operation), "set", "safe", nx=True) is True
    assert len(calls) == 1
    assert calls[0][:2] == ("safe", True)
    assert calls[0][2] != loop_thread


@pytest.mark.asyncio
@pytest.mark.parametrize("plain_adapter", [False, True])
async def test_async_command_and_awaitable_adapter_execute_once(plain_adapter):
    calls = []

    async def operation(value):
        calls.append(value)
        return "value"

    def adapter(value):
        return operation(value)

    client = SimpleNamespace(get=adapter if plain_adapter else operation)
    assert await call_redis(client, "get", "safe") == "value"
    assert calls == ["safe"]
