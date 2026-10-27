import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from service.infrastructure.ide.workspace import IdeWorkspaceClient
from service.services.chat.application.ide.console import IdeConsoleService
from service.services.chat.application.ide.repositories import IdeRepositoryNotFound
from service.services.chat.domain.ide.console import CommandInput, ConsoleError
from service.services.chat.domain.ide.runtime import RepositoryScope

RESULT = dict(
    exit_code=0,
    stdout="Hello, world!\n",
    stderr="",
    truncated=False,
    duration_sec=0.05,
    timed_out=False,
)


class Redis:
    async def execute_command(self):
        raise AssertionError("Redis adapter marker; not called")

    def __init__(self):
        self.data = {}
        self.fail = False

    async def get(self, key):
        if self.fail:
            raise RuntimeError("PRIVATE")
        return self.data.get(key)

    async def set(self, key, value, *, nx=False, xx=False, ex):
        assert ex > 0
        if self.fail:
            raise RuntimeError("PRIVATE")
        if (nx and key in self.data) or (xx and key not in self.data):
            return None
        self.data[key] = value
        return True


@pytest.fixture
def console(monkeypatch):
    scope = RepositoryScope(uuid4(), uuid4(), uuid4())
    payload = CommandInput(
        execution_id=uuid4(), generation="a" * 64, command="python src/hello_world.py"
    )
    runtime = SimpleNamespace(
        mutation_guard=None,
        _check_owner=AsyncMock(),
        client=SimpleNamespace(execute=AsyncMock(return_value=RESULT)),
    )
    store = SimpleNamespace(preflight=AsyncMock())
    redis = Redis()
    service = IdeConsoleService(runtime, redis)
    binding = SimpleNamespace(expires_at=time.time() + 300)
    service.edits._context = AsyncMock(
        return_value=(SimpleNamespace(binding=binding), "PRIVATE_CAP", store)
    )
    service.edits._current = AsyncMock()
    monkeypatch.setattr(
        "service.services.chat.application.ide.console.verify_capability", lambda value: value
    )
    return SimpleNamespace(**locals())


@pytest.mark.asyncio
async def test_confirmed_output_and_same_intent_replay_never_executes_twice(console):
    s = console
    first = await s.service.execute(s.scope, s.payload, "session")
    assert first["state"] == "completed" and first["result"] == RESULT
    assert await s.service.execute(s.scope, s.payload, "session") == first
    assert await s.service.status(s.scope, s.payload.execution_id) == first
    s.runtime.client.execute.assert_awaited_once()
    assert s.payload.command not in repr(s.redis.data)
    assert "PRIVATE_CAP" not in repr(first)


@pytest.mark.asyncio
async def test_changed_command_with_same_id_is_rejected(console):
    s = console
    await s.service.execute(s.scope, s.payload, "session")
    with pytest.raises(ConsoleError, match="ide_console_intent_conflict"):
        await s.service.execute(
            s.scope, s.payload.model_copy(update={"command": "touch second"}), "session"
        )
    s.runtime.client.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_concurrent_replay_observes_dispatch_without_duplicate_command(console):
    s = console
    started, finish = asyncio.Event(), asyncio.Event()

    async def execute(*args, **kwargs):
        started.set()
        await finish.wait()
        return RESULT

    s.runtime.client.execute.side_effect = execute
    task = asyncio.create_task(s.service.execute(s.scope, s.payload, "session"))
    await started.wait()
    try:
        replay = await s.service.execute(s.scope, s.payload, "session")
        assert replay["state"] == "dispatching" and replay["result"] is None
        s.runtime.client.execute.assert_awaited_once()
    finally:
        finish.set()
        await task


@pytest.mark.asyncio
async def test_remote_timeout_is_unknown_and_never_replayed(console):
    s = console
    s.runtime.client.execute.side_effect = TimeoutError
    result = await s.service.execute(s.scope, s.payload, "session")
    assert result["state"] == "unknown"
    assert await s.service.execute(s.scope, s.payload, "session") == result
    s.runtime.client.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_redis_unavailable_or_foreign_owner_cannot_dispatch(console):
    s = console
    s.redis.fail = True
    with pytest.raises(ConsoleError):
        await s.service.execute(s.scope, s.payload, "session")
    s.runtime.client.execute.assert_not_awaited()
    s.runtime._check_owner.side_effect = IdeRepositoryNotFound
    with pytest.raises(IdeRepositoryNotFound):
        await s.service.execute(s.scope, s.payload, "session")
    with pytest.raises(IdeRepositoryNotFound):
        await s.service.status(s.scope, s.payload.execution_id)


@pytest.mark.asyncio
async def test_missing_status_is_unknown_not_permission_to_execute(console):
    s = console
    with pytest.raises(ConsoleError, match="ide_console_status_unknown"):
        await s.service.status(s.scope, s.payload.execution_id)
    s.runtime.client.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_malformed_output_is_not_a_confirmed_completion(console):
    s = console
    s.runtime.client.execute.return_value = {**RESULT, "token": "PRIVATE"}
    result = await s.service.execute(s.scope, s.payload, "session")
    assert result["state"] == "unknown" and result["result"] is None


@pytest.mark.parametrize("command", ["", " ", "a\nb", "a\x00b", "a" * 8193])
def test_command_validation(command):
    with pytest.raises(ValidationError):
        CommandInput(execution_id=uuid4(), generation="a" * 64, command=command)


@pytest.mark.asyncio
async def test_transport_uses_owned_isolated_exec_without_retry_or_allocation():
    calls = []

    async def transport(request):
        calls.append(json.loads(request.content))
        assert request.url.path == "/workspaces/owned/exec"
        return httpx.Response(200, json=RESULT)

    settings = SimpleNamespace(
        workspace_enabled=True,
        workspace_url="http://workspace",
        workspace_api_key="PRIVATE",
        workspace_timeout_sec=10,
        workspace_ttl_sec=300,
    )
    client = IdeWorkspaceClient(settings, transport=httpx.MockTransport(transport))
    result = await client.execute(
        uuid4(),
        SimpleNamespace(workspace_id="owned", token="PRIVATE_TOKEN"),
        command="python main.py",
        capability="PRIVATE_CAP",
    )
    assert result == RESULT and len(calls) == 1
    assert calls[0]["token"] == "PRIVATE_TOKEN"
    assert calls[0]["coordination_capability"] == "PRIVATE_CAP"
