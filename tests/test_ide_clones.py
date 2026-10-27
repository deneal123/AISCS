import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.services.chat.application.ide.clones import (
    IdeCloneService,
    public_clone,
    recovery_clone,
)
from service.services.chat.application.ide.edits import IdeEditService
from service.services.chat.application.ide.repositories import (
    IdeRepositoryIntentConflict,
    IdeRepositoryNotFound,
)
from service.services.chat.domain.ide.edits import IdeEditError
from service.services.chat.domain.ide.runtime import RepositoryScope, RuntimeAttempt
from service.shared.repositories.exceptions import RepositoryOperationalError


class Journal:
    def __init__(self):
        self.row = None
        self.claims = 0

    async def reserve(self, source, *, intent_id, request_digest, name, origin=None, branch=None):
        if self.row is None:
            self.row = dict(
                repository_id=uuid4(),
                source_repository_id=source.repository_id,
                name=name,
                created_at=None,
                state="reserved",
                started_at=None,
                request_digest=request_digest,
                code=None,
                intent_id=intent_id,
                origin=origin,
                branch=branch,
            )
        return dict(self.row)

    async def get_owned(self, **kwargs):
        return dict(self.row) if self.row else None

    async def latest_owned(self, scope):
        return dict(self.row) if self.row else None

    async def claim(self, **kwargs):
        if self.row["state"] != "reserved":
            return False
        self.claims += 1
        self.row.update(state="cloning", started_at=int(time.time()))
        return True

    async def finish(self, *, state, code, **kwargs):
        self.row.update(state=state, code=code)


@pytest.fixture
def setup(monkeypatch):
    source = RepositoryScope(uuid4(), uuid4(), uuid4())
    journal = Journal()
    attempt = RuntimeAttempt(uuid4(), int(time.time()) + 600, "ready", 1)
    runtime = SimpleNamespace(
        repository=SimpleNamespace(get_owned=AsyncMock(return_value={"name": "Original"})),
        provision=AsyncMock(return_value={"workspace": {"state": "ready"}}),
        status=AsyncMock(return_value={"workspace": {"state": "ready"}}),
        runtime=SimpleNamespace(get_owned=AsyncMock(return_value=attempt)),
    )
    git = AsyncMock(return_value={"initialized": True, "branch": "main"})
    monkeypatch.setattr(IdeEditService, "git", git)
    service = IdeCloneService(runtime, journal, None)
    args = dict(
        intent_id=uuid4(),
        origin="https://github.com/octocat/Hello-World",
        branch="",
        session="browser-session-0001",
    )
    return source, journal, runtime, git, service, args


@pytest.mark.asyncio
async def test_isolated_destination_and_lost_reply_replay_do_not_repeat_git(setup):
    source, journal, runtime, git, service, args = setup
    result = await service.clone(source, **args)
    assert result["state"] == "complete"
    assert result["repository"]["repository_id"] != str(source.repository_id)
    assert result["repository"]["name"] == "Hello-World"
    assert await service.clone(source, **args) == result
    assert journal.claims == 1
    git.assert_awaited_once()
    target = git.await_args.args[0]
    assert target == RepositoryScope(source.thread_id, source.user_id, journal.row["repository_id"])
    assert git.await_args.kwargs["operation"] == "clone"
    assert git.await_args.kwargs["clone_intent_id"] == args["intent_id"]
    assert git.await_args.kwargs["origin"] == args["origin"] + ".git"
    runtime.provision.assert_awaited_once_with(target, allow_retry=False)
    assert set(result) == {"repository", "state", "code"}
    assert not {"request_digest", "source_repository_id", "user_id"} & result.keys()


@pytest.mark.asyncio
async def test_parallel_delivery_observes_one_running_clone(setup):
    source, journal, _, git, service, args = setup
    entered, release = asyncio.Event(), asyncio.Event()

    async def blocked(*a, **kw):
        entered.set()
        await release.wait()
        return {"initialized": True}

    git.side_effect = blocked
    first = asyncio.create_task(service.clone(source, **args))
    await entered.wait()
    try:
        assert (await service.clone(source, **args))["state"] == "running"
        assert git.await_count == journal.claims == 1
    finally:
        release.set()
        await first


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes", [{"origin": "https://github.com/other/repo"}, {"branch": "other"}]
)
async def test_immutable_intent_cannot_redirect_after_completion(setup, changes):
    source, _, _, git, service, args = setup
    await service.clone(source, **args)
    with pytest.raises(IdeRepositoryIntentConflict):
        await service.clone(source, **{**args, **changes})
    assert git.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [{"origin": "https://token@github.com/a/b"}, {"branch": "../main"}, {"session": None}],
)
async def test_invalid_admission_has_no_descriptor_or_allocation(setup, changes):
    source, journal, runtime, git, service, args = setup
    with pytest.raises(IdeEditError):
        await service.clone(source, **{**args, **changes})
    assert journal.row is None
    runtime.provision.assert_not_awaited()
    git.assert_not_awaited()


@pytest.mark.asyncio
async def test_foreign_source_never_allocates_or_clones(setup):
    source, journal, runtime, git, service, args = setup
    journal.reserve = AsyncMock(return_value=None)
    with pytest.raises(IdeRepositoryNotFound):
        await service.clone(source, **args)
    runtime.provision.assert_not_awaited()
    git.assert_not_awaited()


@pytest.mark.asyncio
async def test_pending_allocation_is_observed_without_rearming_or_initializing_git(
    setup, monkeypatch
):
    source, _, runtime, git, service, args = setup
    runtime.provision.return_value = {"workspace": {"state": "pending"}}
    monkeypatch.setattr("service.services.chat.application.ide.clones.asyncio.sleep", AsyncMock())
    assert (await service.clone(source, **args))["state"] == "complete"
    runtime.status.assert_awaited_once()
    assert runtime.provision.await_args.kwargs == {"allow_retry": False}
    assert git.await_args.kwargs["operation"] == "clone"


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["expired", "unknown", "rejected"])
async def test_unready_destination_is_not_replaced_and_git_is_not_dispatched(setup, state):
    source, journal, runtime, git, service, args = setup
    runtime.provision.return_value = {"workspace": {"state": state}}
    one = await service.clone(source, **args)
    two = await service.clone(source, **args)
    assert one == two and one["state"] == "blocked"
    assert journal.claims == 0
    assert all(call.kwargs == {"allow_retry": False} for call in runtime.provision.await_args_list)
    git.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code,state",
    [
        ("ide_git_unconfirmed", "unconfirmed"),
        ("ide_generation_changed", "unconfirmed"),
        ("ide_git_fetch_failed", "failed"),
    ],
)
async def test_failed_or_uncertain_git_is_never_replayed(setup, code, state):
    source, _, _, git, service, args = setup
    git.side_effect = IdeEditError(code)
    result = await service.clone(source, **args)
    assert result["state"] == state and result["code"] == code
    assert await service.clone(source, **args) == result
    assert git.await_count == 1


@pytest.mark.asyncio
async def test_lost_completion_commit_ack_reconciles_without_git_replay(setup):
    source, journal, _, git, service, args = setup
    finish = journal.finish

    async def lost_ack(**kw):
        await finish(**kw)
        raise RepositoryOperationalError("unavailable")

    journal.finish = lost_ack
    with pytest.raises(RepositoryOperationalError):
        await service.clone(source, **args)
    assert (await service.clone(source, **args))["state"] == "complete"
    assert git.await_count == 1


@pytest.mark.asyncio
async def test_process_loss_is_not_a_permanent_spinner_or_permission_to_replay(setup):
    source, journal, _, git, service, args = setup
    git.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await service.clone(source, **args)
    journal.row["started_at"] = int(time.time()) - 91
    assert (await service.clone(source, **args))["state"] == "unconfirmed"
    assert git.await_count == 1
    assert "request_digest" not in repr(public_clone(journal.row))


@pytest.mark.asyncio
async def test_missing_status_cannot_provision_a_destination(setup):
    source, _, runtime, _, service, args = setup
    with pytest.raises(IdeRepositoryNotFound):
        await service.status(
            thread_id=source.thread_id, user_id=source.user_id, intent_id=args["intent_id"]
        )
    runtime.provision.assert_not_awaited()


@pytest.mark.asyncio
async def test_recovery_rebuilds_only_owned_pinned_parameters_without_runtime_work(setup):
    source, journal, runtime, git, service, args = setup
    assert await service.recover(source) == {"attempt": None}
    runtime.provision.assert_not_awaited()
    await service.clone(source, **args)
    runtime.provision.reset_mock()
    git.reset_mock()
    recovered = (await service.recover(source))["attempt"]
    assert recovered["intent_id"] == str(args["intent_id"])
    assert recovered["source_repository_id"] == str(source.repository_id)
    assert recovered["request"] == {"origin": args["origin"] + ".git", "branch": ""}
    assert recovered["repository"]["repository_id"] == str(journal.row["repository_id"])
    assert "request_digest" not in recovered and "started_at" not in recovered
    runtime.provision.assert_not_awaited()
    git.assert_not_awaited()
    runtime.repository.get_owned.return_value = None
    with pytest.raises(IdeRepositoryNotFound):
        await service.recover(source)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"origin": None},
        {"origin": "https://token@github.com/a/b"},
        {"branch": "../unsafe"},
        {"origin": "https://github.com/other/repo.git"},
        {"request_digest": "b" * 64},
    ],
)
async def test_legacy_or_changed_parameters_are_inspection_only(setup, changes):
    source, journal, _, _, service, args = setup
    await service.clone(source, **args)
    assert recovery_clone({**journal.row, **changes})["request"] is None
