import hashlib
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from service.infrastructure.ide.workspace import IdeWorkspaceClient
from service.services.chat.application.ide.edits import IdeEditService
from service.services.chat.domain.ide.edits import IdeEditError
from service.services.chat.domain.ide.runtime import (
    RepositoryScope,
    RuntimeAttempt,
    WorkspaceBinding,
    generation_tag,
)


def setup_runtime():
    scope = RepositoryScope(uuid4(), uuid4(), uuid4())
    attempt = RuntimeAttempt(uuid4(), int(time.time()) + 600, "ready", 1)
    binding = WorkspaceBinding("a" * 32, "123." + "b" * 64, attempt.expires_at)
    resolved = SimpleNamespace(attempt=attempt, binding=binding)
    runtime = SimpleNamespace(
        mutation_guard=None,
        resolve=AsyncMock(return_value=resolved),
        runtime=SimpleNamespace(get_owned=AsyncMock(return_value=attempt)),
        client=SimpleNamespace(write=AsyncMock()),
    )
    return scope, attempt, runtime


@pytest.mark.asyncio
async def test_active_command_returns_busy_without_dispatching_or_enqueuing_write(monkeypatch):
    from service.services.chat.persistence.harness.commands.gate import IdeCommandBusy
    from tests.test_workspace_collaboration import FakeRedis

    monkeypatch.setenv("WORKSPACE_COORDINATION_SECRET", "test-only-coordination-secret")
    scope, attempt, runtime = setup_runtime()
    runtime.mutation_guard = AsyncMock(side_effect=IdeCommandBusy())
    with pytest.raises(IdeEditError, match="ide_command_busy"):
        await IdeEditService(runtime, FakeRedis()).write(
            scope,
            path="main.py",
            generation=generation_tag(attempt),
            session="browser-session-0123456789",
            fence=1,
            operation="file",
            content="edit",
            expected_digest=None,
        )
    runtime.client.write.assert_not_awaited()


@pytest.mark.asyncio
async def test_session_and_generation_are_checked_before_lease_or_write(monkeypatch):
    monkeypatch.setenv("WORKSPACE_COORDINATION_SECRET", "test-only-coordination-secret")
    scope, attempt, runtime = setup_runtime()
    service = IdeEditService(runtime, None)
    for generation, session, code in (
        (generation_tag(attempt), "", "ide_edit_session_required"),
        ("f" * 64, "browser-session-0123456789", "ide_generation_changed"),
    ):
        with pytest.raises(IdeEditError, match=code):
            await service.lease(
                scope,
                path="main.py",
                generation=generation,
                session=session,
                action="acquire",
                fence=None,
            )
    runtime.client.write.assert_not_awaited()


@pytest.mark.asyncio
async def test_unavailable_coordination_never_dispatches_write(monkeypatch):
    monkeypatch.setenv("WORKSPACE_COORDINATION_SECRET", "test-only-coordination-secret")
    scope, attempt, runtime = setup_runtime()
    with pytest.raises(IdeEditError, match="ide_edit_unavailable"):
        await IdeEditService(runtime, None).write(
            scope,
            path="main.py",
            generation=generation_tag(attempt),
            session="browser-session-0123456789",
            fence=1,
            operation="file",
            content="",
            expected_digest=None,
        )
    runtime.client.write.assert_not_awaited()


@pytest.mark.asyncio
async def test_transport_carries_only_owned_binding_and_rejects_changed_ack():
    calls = []

    async def transport(request):
        import json

        body = json.loads(request.content)
        calls.append(body)
        return httpx.Response(
            200,
            json={
                "written": True,
                "path": "wrong.py",
                "kind": "file",
                "digest": hashlib.sha256(b"hello").hexdigest(),
                "size": 5,
            },
        )

    settings = SimpleNamespace(
        workspace_enabled=True,
        workspace_url="http://workspace",
        workspace_api_key="private",
        workspace_timeout_sec=10,
        workspace_ttl_sec=600,
    )
    client = IdeWorkspaceClient(settings, transport=httpx.MockTransport(transport))
    binding = WorkspaceBinding("a" * 32, "123." + "b" * 64, int(time.time()) + 600)
    with pytest.raises(IdeEditError, match="ide_write_unconfirmed"):
        await client.write(
            uuid4(),
            binding,
            path="main.py",
            operation="file",
            content="hello",
            expected_digest=None,
            capability="signed-private",
            fence=2,
        )
    assert len(calls) == 1
    assert calls[0]["coordination_fence"] == 2
    assert calls[0]["expected_digest"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("starter", [False, True, None])
async def test_clone_seed_replacement_comes_only_from_owned_server_provenance(monkeypatch, starter):
    from service.services.chat.application.ide.repositories import IdeRepositoryNotFound
    from tests.test_workspace_collaboration import FakeRedis

    monkeypatch.setenv("WORKSPACE_COORDINATION_SECRET", "test-only-coordination-secret")
    scope, attempt, runtime = setup_runtime()
    runtime.repository = SimpleNamespace(
        is_onboarding_owned=AsyncMock(return_value=starter),
        is_clone_destination=AsyncMock(return_value=False),
    )
    runtime.client.read = AsyncMock(return_value={"entries": [], "truncated": False})
    runtime.client.git = AsyncMock(return_value={"initialized": True, "branch": "main"})
    fetch = AsyncMock(return_value=(b"PACKfixture", "main", "a" * 40))
    monkeypatch.setattr("service.infrastructure.ide.transports.git_fetch.fetch_pack", fetch)
    operation = IdeEditService(runtime, FakeRedis()).git(
        scope,
        generation=generation_tag(attempt),
        session="browser-session-0123456789",
        operation="clone",
        origin="https://github.com/fixture/repo.git",
    )
    if starter is None:
        with pytest.raises(IdeRepositoryNotFound):
            await operation
        fetch.assert_not_awaited()
        runtime.client.git.assert_not_awaited()
    else:
        result = await operation
        assert result["repository_id"] == str(scope.repository_id)
        private = runtime.client.git.await_args.kwargs
        assert private.get("replace_pristine_starter", False) is starter
        assert "onboarding_created" not in result
    runtime.repository.is_onboarding_owned.assert_awaited_once_with(**scope.params())


@pytest.mark.asyncio
async def test_nonempty_clone_rejects_before_network_fetch_without_changing_the_source(monkeypatch):
    from tests.test_workspace_collaboration import FakeRedis

    monkeypatch.setenv("WORKSPACE_COORDINATION_SECRET", "test-only-coordination-secret")
    scope, attempt, runtime = setup_runtime()
    runtime.repository = SimpleNamespace(
        is_onboarding_owned=AsyncMock(return_value=True),
        is_clone_destination=AsyncMock(return_value=False),
    )
    runtime.client.read = AsyncMock(
        return_value={"entries": [{"path": "user.py"}], "truncated": False}
    )
    runtime.client.git = AsyncMock()
    fetch = AsyncMock()
    monkeypatch.setattr("service.infrastructure.ide.transports.git_fetch.fetch_pack", fetch)
    with pytest.raises(IdeEditError, match="ide_git_not_empty"):
        await IdeEditService(runtime, FakeRedis()).git(
            scope,
            generation=generation_tag(attempt),
            session="browser-session-0123456789",
            operation="clone",
            origin="https://github.com/fixture/repo",
        )
    fetch.assert_not_awaited()
    runtime.client.git.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("permission", [None, False, True])
async def test_clone_destination_cannot_bypass_its_durable_dispatch_claim(monkeypatch, permission):
    from tests.test_workspace_collaboration import FakeRedis

    monkeypatch.setenv("WORKSPACE_COORDINATION_SECRET", "test-only-coordination-secret")
    scope, attempt, runtime = setup_runtime()
    intent = uuid4() if permission is not None else None
    runtime.repository = SimpleNamespace(
        is_clone_destination=AsyncMock(return_value=True),
        clone_dispatch_owned=AsyncMock(return_value=permission),
        is_onboarding_owned=AsyncMock(return_value=False),
    )
    runtime.client.read = AsyncMock(return_value={"entries": [], "truncated": False})
    runtime.client.git = AsyncMock(return_value={"initialized": True, "branch": "main"})
    fetch = AsyncMock(return_value=(b"PACKfixture", "main", "a" * 40))
    monkeypatch.setattr("service.infrastructure.ide.transports.git_fetch.fetch_pack", fetch)
    operation = IdeEditService(runtime, FakeRedis()).git(
        scope,
        generation=generation_tag(attempt),
        session="browser-session-0123456789",
        operation="clone",
        origin="https://github.com/fixture/repo",
        clone_intent_id=intent,
    )
    if permission is True:
        assert (await operation)["initialized"] is True
        runtime.repository.clone_dispatch_owned.assert_awaited_once_with(
            **scope.params(), intent_id=intent
        )
        fetch.assert_awaited_once()
    else:
        with pytest.raises(
            IdeEditError, match="ide_git_conflict" if permission is None else "ide_git_unconfirmed"
        ):
            await operation
        fetch.assert_not_awaited()
        runtime.client.git.assert_not_awaited()
        runtime.client.read.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("starter", [False, True])
async def test_private_git_transport_never_invents_starter_permission(starter):
    import json

    seen = []

    async def transport(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"initialized": True, "branch": "main"})

    settings = SimpleNamespace(
        workspace_enabled=True,
        workspace_url="http://workspace",
        workspace_api_key="private",
        workspace_timeout_sec=10,
        workspace_ttl_sec=600,
    )
    client = IdeWorkspaceClient(settings, transport=httpx.MockTransport(transport))
    binding = WorkspaceBinding("a" * 32, "123." + "b" * 64, int(time.time()) + 600)
    await client.git(
        uuid4(),
        binding,
        operation="clone",
        capability="signed-private",
        replace_pristine_starter=starter,
    )
    assert len(seen) == 1
    assert seen[0].get("replace_pristine_starter", False) is starter
    if not starter:
        assert "replace_pristine_starter" not in seen[0]
