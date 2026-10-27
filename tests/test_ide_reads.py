import time
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from service.services.chat.application.ide.reads import IdeReadService
from service.services.chat.application.ide.repositories import IdeRepositoryNotFound
from service.services.chat.application.ide.runtime import IdeRuntimeService
from service.services.chat.domain.ide.files import IdeReadError
from service.services.chat.domain.ide.runtime import (
    RepositoryScope,
    RuntimeAttempt,
    RuntimeObservation,
    WorkspaceBinding,
    generation_tag,
)
from tests.test_ide_runtime import RuntimeStore

pytestmark = pytest.mark.asyncio


@pytest.fixture
def fixture():
    scope = RepositoryScope(uuid4(), uuid4(), uuid4())
    repository = MagicMock(get_owned=AsyncMock(return_value={"repository_id": scope.repository_id}))
    store = RuntimeStore()
    store.current = RuntimeAttempt(uuid4(), int(time.time()) + 600, "ready", 0)
    binding = WorkspaceBinding("a" * 32, "PRIVATE_TOKEN", store.current.expires_at)
    client = MagicMock(
        observe=AsyncMock(return_value=RuntimeObservation("ready", binding)),
        read=AsyncMock(return_value={"entries": [], "truncated": False}),
        allocation_ttl=AsyncMock(),
    )
    runtime = IdeRuntimeService(repository, store, client)
    return scope, runtime, store, client


async def test_owned_tree_reads_only_lookup_existing_generation(fixture):
    scope, runtime, store, client = fixture
    result = await IdeReadService(runtime).read(scope, operation="tree", path="")
    assert result == {
        "repository_id": str(scope.repository_id),
        "generation": generation_tag(store.current),
        "entries": [],
        "truncated": False,
    }
    assert store.claims == 0
    client.observe.assert_awaited_once()
    assert client.observe.await_args.kwargs == {"create": False}
    client.allocation_ttl.assert_not_awaited()
    client.read.assert_awaited_once_with(
        scope.user_id, client.observe.return_value.binding, operation="tree", path=""
    )
    assert "PRIVATE" not in str(result)


@pytest.mark.parametrize("state", [None, "rejected"])
async def test_missing_runtime_never_creates_on_file_read(fixture, state):
    scope, runtime, store, client = fixture
    store.current = None if state is None else replace(store.current, state=state)
    with pytest.raises(IdeReadError, match="ide_runtime_not_ready"):
        await IdeReadService(runtime).read(scope, operation="tree", path="")
    assert store.claims == 0
    client.observe.assert_not_awaited()
    client.read.assert_not_awaited()


async def test_foreign_owner_cannot_lookup_or_read(fixture):
    scope, runtime, _, client = fixture
    runtime.repository.get_owned.return_value = None
    with pytest.raises(IdeRepositoryNotFound):
        await IdeReadService(runtime).read(scope, operation="tree", path="")
    client.observe.assert_not_awaited()
    client.read.assert_not_awaited()


async def test_stale_file_selection_cannot_read_a_new_generation(fixture):
    scope, runtime, _, client = fixture
    with pytest.raises(IdeReadError, match="ide_generation_changed"):
        await IdeReadService(runtime).read(
            scope, operation="file", path="main.py", generation="0" * 64
        )
    client.read.assert_not_awaited()


@pytest.mark.parametrize(
    "change,code",
    [
        ("generation", "ide_generation_changed"),
        ("expiry", "ide_runtime_expired"),
        ("state", "ide_runtime_not_ready"),
        ("delete", None),
    ],
)
async def test_retirement_during_rpc_cannot_publish_old_contents(fixture, change, code):
    scope, runtime, store, client = fixture

    async def retire(*args, **kwargs):
        if change == "generation":
            store.current = replace(store.current, allocation_id=uuid4())
        elif change == "expiry":
            store.current = replace(store.current, expires_at=1)
        elif change == "state":
            store.current = replace(store.current, state="unknown")
        else:
            store.current = None
        return {"content": "RETIRED_CONTENT"}

    client.read.side_effect = retire
    with pytest.raises(IdeReadError if code else IdeRepositoryNotFound, match=code):
        await IdeReadService(runtime).read(scope, operation="tree", path="")


async def test_expired_binding_skips_sidecar(fixture):
    scope, runtime, store, client = fixture
    store.current = replace(store.current, expires_at=1)
    with pytest.raises(IdeReadError, match="ide_runtime_expired"):
        await IdeReadService(runtime).read(scope, operation="tree", path="")
    client.observe.assert_not_awaited()
    client.read.assert_not_awaited()


async def test_superseded_observation_never_exposes_its_private_binding(fixture):
    scope, runtime, store, client = fixture

    async def raced(*args, **kwargs):
        store.current = replace(store.current, observation=store.current.observation + 1)
        return client.observe.return_value

    client.observe.side_effect = raced
    with pytest.raises(IdeReadError, match="ide_generation_changed"):
        await IdeReadService(runtime).read(scope, operation="tree", path="")
    client.read.assert_not_awaited()
