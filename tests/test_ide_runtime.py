import asyncio
import time
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from service.services.chat.application.ide.repositories import IdeRepositoryNotFound
from service.services.chat.application.ide.runtime import IdeRuntimeService
from service.services.chat.domain.ide.runtime import (
    RepositoryScope,
    RuntimeAttempt,
    RuntimeObservation,
    WorkspaceBinding,
)
from service.shared.repositories.exceptions import RepositoryOperationalError

pytestmark = pytest.mark.asyncio


class RuntimeStore:
    """In-memory orchestration fixture; real SQL is covered by the opt-in probe."""

    def __init__(self):
        self.current = None
        self.claims = 0

    async def get_owned(self, _scope):
        return self.current

    async def claim(self, _scope, *, ttl_sec, allow_retry=True):
        self.claims += 1
        if self.current is None:
            self.current = RuntimeAttempt(uuid4(), int(time.time()) + ttl_sec, "dispatching", 0)
            return self.current, True
        if allow_retry and self.current.retry_allowed and self.current.expires_at > time.time():
            self.current = replace(
                self.current,
                state="dispatching",
                retry_allowed=False,
                observation=self.current.observation + 1,
            )
            return self.current, True
        return self.current, False

    async def begin_observation(self, _scope, _attempt):
        self.current = replace(self.current, observation=self.current.observation + 1)
        return self.current

    async def record_observation(self, _scope, attempt, state, *, retry_allowed=False):
        if self.current.observation == attempt.observation:
            self.current = replace(self.current, state=state, retry_allowed=retry_allowed)
        return self.current


@pytest.fixture
def runtime_fixture():
    scope = RepositoryScope(uuid4(), uuid4(), uuid4())
    repository = MagicMock(get_owned=AsyncMock(return_value={"repository_id": scope.repository_id}))
    store = RuntimeStore()
    binding = WorkspaceBinding("a" * 32, "PRIVATE_TOKEN", int(time.time()) + 1800)
    client = MagicMock(
        allocation_ttl=AsyncMock(return_value=1800),
        observe=AsyncMock(return_value=RuntimeObservation("ready", binding)),
    )
    return scope, repository, store, client


def service(fixture):
    _, repository, store, client = fixture
    return IdeRuntimeService(repository, store, client)


async def test_initial_read_is_passive_and_empty_not_ready(runtime_fixture):
    scope, _, store, client = runtime_fixture
    result = await service(runtime_fixture).status(scope)
    assert result["workspace"] == {"state": "not_created", "expires_at": None, "can_retry": False}
    assert store.claims == 0 and store.current is None
    client.allocation_ttl.assert_not_awaited()
    client.observe.assert_not_awaited()


@pytest.mark.parametrize("method", ["status", "provision"])
async def test_no_owner_means_no_runtime_or_transport_action(runtime_fixture, method):
    scope, repository, store, client = runtime_fixture
    repository.get_owned.return_value = None
    with pytest.raises(IdeRepositoryNotFound):
        await getattr(service(runtime_fixture), method)(scope)
    assert store.current is None and store.claims == 0
    client.observe.assert_not_awaited()
    client.allocation_ttl.assert_not_awaited()


async def test_first_provision_dispatches_once_and_replay_only_looks_up(runtime_fixture):
    scope, _, store, client = runtime_fixture
    first = await service(runtime_fixture).provision(scope)
    attempt = store.current
    second = await service(runtime_fixture).provision(scope)
    assert first == second
    assert store.claims == 1 and store.current.allocation_id == attempt.allocation_id
    assert store.current.expires_at == attempt.expires_at
    assert [call.kwargs["create"] for call in client.observe.await_args_list] == [True, False]
    assert "PRIVATE" not in str(first)
    assert set(first) == {"repository_id", "workspace"}
    client.allocation_ttl.assert_awaited_once()


async def test_cancelled_dispatch_stays_claimed_across_service_instances(runtime_fixture):
    scope, _, store, client = runtime_fixture
    client.observe.side_effect = [asyncio.CancelledError(), RuntimeObservation("ready")]
    with pytest.raises(asyncio.CancelledError):
        await service(runtime_fixture).provision(scope)
    attempt = store.current
    assert attempt.state == "dispatching"
    recovered = await service(runtime_fixture).provision(scope)
    assert recovered["workspace"]["state"] == "ready"
    assert store.claims == 1 and store.current.allocation_id == attempt.allocation_id
    assert [call.kwargs["create"] for call in client.observe.await_args_list] == [True, False]


async def test_lost_database_claim_ack_cannot_dispatch(runtime_fixture):
    scope, _, store, client = runtime_fixture

    async def lost_ack(*args, **kwargs):
        await RuntimeStore.claim(store, *args, **kwargs)
        raise RepositoryOperationalError("Database unavailable")

    store.claim = lost_ack
    with pytest.raises(RepositoryOperationalError):
        await service(runtime_fixture).provision(scope)
    client.observe.assert_not_awaited()
    recovered = await service(runtime_fixture).provision(scope)
    assert recovered["workspace"]["state"] == "ready"
    assert client.observe.call_args.kwargs["create"] is False


async def test_missing_lookup_after_uncertain_dispatch_never_recreates(runtime_fixture):
    scope, _, store, client = runtime_fixture
    client.observe.side_effect = [RuntimeObservation("unavailable"), RuntimeObservation("unknown")]
    await service(runtime_fixture).provision(scope)
    attempt = store.current
    result = await service(runtime_fixture).provision(scope)
    assert result["workspace"]["state"] == "unknown"
    assert not result["workspace"]["can_retry"]
    assert store.current.allocation_id == attempt.allocation_id and store.claims == 1
    assert [call.kwargs["create"] for call in client.observe.await_args_list] == [True, False]


async def test_expiry_never_silently_starts_an_empty_generation(runtime_fixture):
    scope, _, store, client = runtime_fixture
    store.current = RuntimeAttempt(uuid4(), int(time.time()) - 1, "ready", 3)
    allocation_id = store.current.allocation_id
    result = await service(runtime_fixture).provision(scope)
    assert result["workspace"]["state"] == "expired"
    assert store.current.allocation_id == allocation_id and store.claims == 0
    client.observe.assert_not_awaited()


async def test_old_observation_cannot_replace_a_later_confirmed_result(runtime_fixture):
    scope, _, store, client = runtime_fixture
    entered, release = asyncio.Event(), asyncio.Event()

    async def observe(_user_id, _attempt, *, create):
        if create:
            entered.set()
            await release.wait()
            return RuntimeObservation("unavailable")
        return RuntimeObservation("ready")

    client.observe.side_effect = observe
    older = asyncio.create_task(service(runtime_fixture).provision(scope))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        newer = await service(runtime_fixture).status(scope)
        assert newer["workspace"]["state"] == "ready"
    finally:
        release.set()
    assert (await older)["workspace"]["state"] == "ready"
    assert store.current.state == "ready" and store.claims == 1


async def test_known_quota_rejection_can_only_retry_on_an_explicit_provision(runtime_fixture):
    scope, _, store, client = runtime_fixture
    client.observe.side_effect = [
        RuntimeObservation("rejected", retry_allowed=True),
        RuntimeObservation("ready"),
    ]
    rejected = await service(runtime_fixture).provision(scope)
    generation, deadline = store.current.allocation_id, store.current.expires_at
    assert rejected["workspace"]["can_retry"]
    assert (await service(runtime_fixture).status(scope)) == rejected
    assert client.observe.await_count == 1
    result = await service(runtime_fixture).provision(scope)
    assert result["workspace"]["state"] == "ready"
    assert store.current.allocation_id == generation and store.current.expires_at == deadline
    assert [call.kwargs["create"] for call in client.observe.await_args_list] == [True, True]


async def test_unsupported_old_sidecar_does_not_consume_a_dispatch_claim(runtime_fixture):
    scope, _, store, client = runtime_fixture
    client.allocation_ttl.return_value = None
    result = await service(runtime_fixture).provision(scope)
    assert result["workspace"]["state"] == "unavailable"
    assert store.claims == 0 and store.current is None
    client.observe.assert_not_awaited()


async def test_entry_replay_never_rearms_a_known_quota_rejection(runtime_fixture):
    scope, _, store, client = runtime_fixture
    client.observe.return_value = RuntimeObservation("rejected", retry_allowed=True)
    first = await service(runtime_fixture).provision(scope, allow_retry=False)
    generation = store.current.allocation_id
    second = await service(runtime_fixture).provision(scope, allow_retry=False)
    assert second == first
    assert store.current.allocation_id == generation and store.claims == 1
    client.observe.assert_awaited_once()


async def test_rejection_winning_between_entry_read_and_claim_cannot_rearm(runtime_fixture):
    scope, _, store, client = runtime_fixture
    original = store.claim

    async def rejection_wins(*args, **kwargs):
        store.current = RuntimeAttempt(uuid4(), int(time.time()) + 600, "rejected", 1, True)
        return await original(*args, **kwargs)

    store.claim = rejection_wins
    result = await service(runtime_fixture).provision(scope, allow_retry=False)
    assert result["workspace"]["state"] == "rejected"
    assert result["workspace"]["can_retry"]
    client.observe.assert_not_awaited()


@pytest.mark.parametrize("newer_state", ["ready", "unavailable", "expired"])
async def test_superseded_observation_cannot_project_private_binding(runtime_fixture, newer_state):
    from service.services.chat.domain.ide.files import IdeReadError

    scope, _, store, _ = runtime_fixture
    store.current = RuntimeAttempt(uuid4(), int(time.time()) + 600, "ready", 1)

    async def newer_wins(_scope, _attempt, _state, **kwargs):
        store.current = replace(
            store.current, observation=store.current.observation + 1, state=newer_state
        )
        return store.current

    store.record_observation = newer_wins
    with pytest.raises(IdeReadError, match="ide_generation_changed"):
        await service(runtime_fixture).resolve(scope)


async def test_concurrent_new_allocation_still_retires_private_binding(runtime_fixture):
    from service.services.chat.domain.ide.files import IdeReadError

    scope, _, store, _ = runtime_fixture
    store.current = RuntimeAttempt(uuid4(), int(time.time()) + 600, "ready", 1)

    async def newer_generation(_scope, _attempt, _state, **kwargs):
        store.current = replace(store.current, allocation_id=uuid4())
        return store.current

    store.record_observation = newer_generation
    with pytest.raises(IdeReadError, match="ide_generation_changed"):
        await service(runtime_fixture).resolve(scope)


async def test_one_competing_observer_requires_a_new_fenced_binding_not_reuse(runtime_fixture):
    scope, _, store, client = runtime_fixture
    store.current = RuntimeAttempt(uuid4(), int(time.time()) + 600, "ready", 1)
    stale = WorkspaceBinding("a" * 32, "STALE_PRIVATE", store.current.expires_at)
    fresh = WorkspaceBinding("a" * 32, "FRESH_PRIVATE", store.current.expires_at)
    calls = 0

    async def observe(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            store.current = replace(store.current, observation=store.current.observation + 1)
            return RuntimeObservation("ready", stale)
        return RuntimeObservation("ready", fresh)

    client.observe.side_effect = observe
    result = await service(runtime_fixture).resolve(scope)
    assert result.binding is fresh and result.binding is not stale
    assert result.attempt.observation == store.current.observation
    assert calls == 2 and store.claims == 0
    assert all(call.kwargs["create"] is False for call in client.observe.await_args_list)
