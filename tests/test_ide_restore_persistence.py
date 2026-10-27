"""SQL owner/expiry/swap fences; real PostgreSQL coverage is opt-in separately."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from service.services.chat.domain.ide.runtime import RepositoryScope
from service.services.chat.persistence.ide.checkpoints.restore import IdeRestoreRepository


@pytest.fixture(autouse=True)
def command_gate(monkeypatch):
    guard = AsyncMock(return_value=False)
    monkeypatch.setattr(
        "service.services.chat.persistence.ide.checkpoints.restore.project_is_busy", guard
    )
    return guard


def result(row=None, exists=False):
    value = MagicMock()
    value.first.return_value = (uuid4(),) if exists else None
    value.mappings.return_value.first.return_value = row
    return value


@pytest.fixture
def fixture():
    scope = RepositoryScope(uuid4(), uuid4(), uuid4())
    row = {
        **scope.params(),
        "restore_id": uuid4(),
        "checkpoint_id": uuid4(),
        "base_allocation_id": uuid4(),
        "allocation_id": uuid4(),
        "expires_at": 2_000_000_000,
        "sha256": "a" * 64,
        "size": 100,
        "storage_namespace": "b" * 64,
        "state": "pending",
    }
    return scope, row, IdeRestoreRepository(MagicMock())


async def reserve(fixture, session, **kwargs):
    scope, row, repository = fixture
    return await repository.reserve(
        scope,
        row["restore_id"],
        row["checkpoint_id"],
        row["base_allocation_id"],
        ttl_sec=300,
        session=session,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_owned_status_does_not_mutate_or_lock(fixture):
    scope, row, repository = fixture
    session = MagicMock(execute=AsyncMock(return_value=result(row)))
    record = await repository.get_owned(scope, row["restore_id"], session=session)
    assert record.matches(row["checkpoint_id"], row["base_allocation_id"])
    query = str(session.execute.await_args.args[0])
    for fence in (
        "i.thread_id=:thread_id",
        "i.user_id=:user_id",
        "t.user_id=:user_id",
        "r.user_id=:user_id",
    ):
        assert fence in query
    assert "FOR UPDATE" not in query
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_missing_owner_never_reads_ledger_or_runtime(fixture):
    session = MagicMock(execute=AsyncMock(return_value=result()))
    assert (await reserve(fixture, session)).failure == "missing"
    assert session.execute.await_count == 1


@pytest.mark.asyncio
async def test_unknown_command_blocks_restore_before_claim_or_generation_swap(
    fixture, command_gate
):
    command_gate.return_value = True
    session = MagicMock(execute=AsyncMock(return_value=result(exists=True)))
    assert (await reserve(fixture, session)).failure == "command_busy"
    assert session.execute.await_count == 1
    command_gate.assert_awaited_once_with(session, fixture[0].repository_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["pending", "published", "expired", "conflict"])
async def test_exact_replay_never_dispatches_even_pending_or_after_expiry(fixture, state):
    _, row, _ = fixture
    row["state"] = state
    session = MagicMock(execute=AsyncMock(side_effect=[result(exists=True), result(row)]))
    claim = await reserve(fixture, session)
    assert claim.record.state == state and not claim.dispatch
    assert session.execute.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("runtime", [None, {"allocation_id": uuid4(), "expired": True}, "live"])
async def test_claim_cannot_replace_missing_changed_or_live_runtime(fixture, runtime):
    _, row, _ = fixture
    if runtime == "live":
        runtime = {"allocation_id": row["base_allocation_id"], "expired": False}
    session = MagicMock(
        execute=AsyncMock(side_effect=[result(exists=True), result(), result(runtime)])
    )
    assert (await reserve(fixture, session)).failure == "runtime_not_expired"
    assert session.execute.await_count == 3


@pytest.mark.asyncio
async def test_unpublished_checkpoint_cannot_create_restore_claim(fixture):
    _, row, _ = fixture
    session = MagicMock(
        execute=AsyncMock(
            side_effect=[
                result(exists=True),
                result(),
                result({"allocation_id": row["base_allocation_id"], "expired": True}),
                result(),
            ]
        )
    )
    assert (await reserve(fixture, session)).failure == "checkpoint_not_published"
    assert session.execute.await_count == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked", [False, True])
async def test_new_claim_freezes_checkpoint_and_deadline_without_swapping_runtime(fixture, blocked):
    _, row, _ = fixture
    saved = {key: row[key] for key in ("sha256", "size", "storage_namespace")}
    session = MagicMock(
        execute=AsyncMock(
            side_effect=[
                result(exists=True),
                result(),
                result({"allocation_id": row["base_allocation_id"], "expired": True}),
                result(saved),
                result(),
                result(),
                result(row),
            ]
        ),
        scalar=AsyncMock(return_value=1 if blocked else None),
    )
    claim = await reserve(fixture, session)
    assert claim.dispatch is not blocked
    if blocked:
        assert claim.failure == "restore_pending"
    statements = [str(call.args[0]) for call in session.execute.await_args_list]
    assert not any("UPDATE profile.ide_repository_runtime" in query for query in statements)
    assert any("expires_at<=extract(epoch FROM clock_timestamp())" in query for query in statements)
    if not blocked:
        query, params = session.execute.await_args_list[-2].args
        assert "floor(extract(epoch FROM clock_timestamp()))::bigint+:ttl_sec" in str(query)
        assert params["allocation_id"] != row["base_allocation_id"]
        assert {key: params[key] for key in saved} == saved


@pytest.mark.asyncio
@pytest.mark.parametrize("verified", [False, 1, True])
async def test_only_exact_verified_receipt_may_publish_expired_generation(fixture, verified):
    scope, row, repository = fixture
    next_row = {**row, "state": "published"}
    session = MagicMock(
        execute=AsyncMock(
            side_effect=[
                result(exists=True),
                result(row),
                result(
                    {
                        "allocation_id": row["base_allocation_id"],
                        "expired": True,
                        "target_alive": True,
                    }
                ),
                result(exists=True),
                result(),
                result(next_row),
            ]
        )
    )
    record = await repository.publish(scope, row["restore_id"], verified=verified, session=session)
    assert record.state == ("published" if verified is True else "pending")
    assert session.execute.await_count == (6 if verified is True else 3)
    if verified is True:
        query, params = session.execute.await_args_list[3].args
        assert "allocation_id=:base_allocation_id" in str(query)
        assert "AND :expires_at>extract(epoch FROM clock_timestamp())" in str(query)
        assert "retry_allowed=false,observation=observation+1" in str(query)
        assert params["expires_at"] == row["expires_at"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["expired", "changed", "missing", "live", "late_expiry"])
async def test_non_publishable_results_retire_without_overwriting_a_live_generation(fixture, kind):
    scope, row, repository = fixture
    runtime = {"allocation_id": row["base_allocation_id"], "expired": True, "target_alive": True}
    if kind == "expired":
        runtime["target_alive"] = False
    if kind == "changed":
        runtime["allocation_id"] = uuid4()
    if kind == "live":
        runtime["expired"] = False
    target = "expired" if kind in {"expired", "late_expiry"} else "conflict"
    outputs = [result(exists=True), result(row), result(None if kind == "missing" else runtime)]
    if kind == "late_expiry":
        outputs.append(result())
    outputs.extend([result(), result({**row, "state": target})])
    session = MagicMock(execute=AsyncMock(side_effect=outputs))
    record = await repository.publish(scope, row["restore_id"], verified=True, session=session)
    assert record.state == target
    assert session.execute.await_count == (6 if kind == "late_expiry" else 5)


@pytest.mark.asyncio
@pytest.mark.parametrize("ttl", [True, 0, -1, 2**31, 1.5])
async def test_invalid_ttl_cannot_open_any_dispatch(fixture, ttl):
    scope, row, repository = fixture
    session = MagicMock(execute=AsyncMock())
    from service.shared.repositories.exceptions import RepositoryError

    with pytest.raises(RepositoryError):
        await repository.reserve(
            scope,
            row["restore_id"],
            row["checkpoint_id"],
            row["base_allocation_id"],
            ttl_sec=ttl,
            session=session,
        )
    session.execute.assert_not_called()
