"""Default SQL-contract coverage; atomicity/concurrency also has a real PG probe."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError

from service.services.chat.domain.ide.checkpoints.blob import CheckpointBlob
from service.services.chat.domain.ide.checkpoints.revision import CheckpointIntent
from service.services.chat.domain.ide.runtime import RepositoryScope
from service.services.chat.persistence.ide.checkpoints.repository import IdeCheckpointRepository
from service.shared.repositories.exceptions import RepositoryOperationalError


def result(row=None, exists=False):
    value = MagicMock()
    value.first.return_value = (uuid4(),) if exists else None
    value.mappings.return_value.first.return_value = row
    return value


@pytest.fixture
def fixture():
    scope = RepositoryScope(uuid4(), uuid4(), uuid4())
    intent = CheckpointIntent(CheckpointBlob(scope, uuid4(), "a" * 64, 10), uuid4(), None, "b" * 64)
    row = {**intent.params(), "state": "pending", "current_checkpoint_id": None}
    repository = IdeCheckpointRepository(MagicMock())
    return scope, intent, row, repository


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["get_owned", "head"])
async def test_passive_reads_join_current_owner_and_never_mutate(fixture, operation):
    scope, intent, row, repository = fixture
    session = MagicMock(execute=AsyncMock(return_value=result(row)))
    args = [scope, intent.blob.checkpoint_id] if operation == "get_owned" else [scope]
    record = await getattr(repository, operation)(*args, session=session)
    assert record.intent == intent
    query, params = session.execute.await_args.args
    assert "t.user_id=:user_id" in str(query)
    assert "r.user_id=:user_id" in str(query)
    assert "c.user_id=:user_id" in str(query)
    assert "c.thread_id=:thread_id" in str(query)
    assert "c.repository_id" in str(query)
    assert params["user_id"] == scope.user_id
    session.commit.assert_not_called()
    session.rollback.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["reserve", "publish"])
async def test_no_owner_stops_before_ledger_runtime_or_head(fixture, operation):
    scope, intent, _, repository = fixture
    session = MagicMock(execute=AsyncMock(return_value=result()))
    args = [intent] if operation == "reserve" else [scope, intent.blob.checkpoint_id]
    outcome = await getattr(repository, operation)(*args, session=session)
    assert (outcome.failure == "missing") if operation == "reserve" else outcome is None
    assert session.execute.await_count == 1
    query, params = session.execute.await_args.args
    assert "FOR UPDATE OF r FOR SHARE OF t" in str(query)
    assert params == scope.params()


@pytest.mark.asyncio
async def test_existing_intent_is_returned_without_new_runtime_or_insert(fixture):
    _, intent, row, repository = fixture
    session = MagicMock(execute=AsyncMock(side_effect=[result(exists=True), result(row)]))
    reservation = await repository.reserve(intent, session=session)
    assert reservation.record.intent == intent and not reservation.dispatch
    assert session.execute.await_count == 2
    assert all("SELECT" == str(call.args[0]).split()[0] for call in session.execute.await_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["head", "expired", "unknown", "generation"])
@pytest.mark.parametrize("verified", [False, True])
async def test_historical_publication_keeps_head_fences_and_requires_verified_bytes(
    fixture, change, verified
):
    scope, intent, row, repository = fixture
    row = {**row, "current_checkpoint_id": uuid4() if change == "head" else None}
    runtime = {
        "allocation_id": uuid4() if change == "generation" else intent.allocation_id,
        "alive": change != "expired",
        "state": "unknown" if change == "unknown" else "ready",
    }
    expected = (
        "published"
        if verified
        else {"head": "conflict", "unknown": "pending"}.get(change, "retired")
    )
    calls = [result(exists=True), result(row)]
    if change != "head":
        calls.append(result(runtime))
    if expected != "pending":
        calls.extend([result(), result({**row, "state": expected})])
    session = MagicMock(execute=AsyncMock(side_effect=calls))
    record = await repository.publish(
        scope, intent.blob.checkpoint_id, verified=verified, historical=True, session=session
    )
    assert record.state == expected
    queries = [str(call.args[0]) for call in session.execute.await_args_list]
    assert not any(query.startswith("UPDATE profile.ide_repository_head") for query in queries)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["missing", "generation", "expiry", "unknown", "rejected"])
async def test_no_live_owned_generation_cannot_register_an_upload(fixture, change):
    _, intent, _, repository = fixture
    runtime = {"allocation_id": intent.allocation_id, "alive": True, "state": "ready"}
    if change == "generation":
        runtime["allocation_id"] = uuid4()
    elif change == "expiry":
        runtime["alive"] = False
    else:
        runtime["state"] = change
    session = MagicMock(
        execute=AsyncMock(
            side_effect=[
                result(exists=True),
                result(),
                result(None if change == "missing" else runtime),
            ]
        )
    )
    reservation = await repository.reserve(intent, session=session)
    assert reservation.failure == "runtime_not_ready" and not reservation.dispatch
    assert session.execute.await_count == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("conflict", [False, True])
async def test_new_intent_freezes_base_and_creates_ledger_before_dispatch(fixture, conflict):
    _, intent, row, repository = fixture
    runtime = {"allocation_id": intent.allocation_id, "alive": True, "state": "ready"}
    current = uuid4() if conflict else None
    row.update(state="conflict" if conflict else "pending", current_checkpoint_id=current)
    session = MagicMock(
        execute=AsyncMock(
            side_effect=[
                result(exists=True),
                result(),
                result(runtime),
                result(),
                result(),
                result(row),
            ]
        ),
        scalar=AsyncMock(return_value=current),
    )
    reservation = await repository.reserve(intent, session=session)
    assert reservation.dispatch is not conflict
    assert reservation.record.state == ("conflict" if conflict else "pending")
    query, params = session.execute.await_args_list[4].args
    assert str(query).startswith("INSERT INTO profile.ide_checkpoint_intent")
    assert params == {**intent.params(), "state": "conflict" if conflict else "pending"}
    session.commit.assert_not_called()  # Injected transaction belongs to the caller.


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [None, "published", "conflict", "retired"])
async def test_terminal_or_missing_record_is_never_republished(fixture, state):
    scope, intent, row, repository = fixture
    row["state"] = state
    session = MagicMock(
        execute=AsyncMock(
            side_effect=[
                result(exists=True),
                result(row if state else None),
            ]
        )
    )
    outcome = await repository.publish(scope, intent.blob.checkpoint_id, session=session)
    assert outcome.state == state if state else outcome is None
    assert session.execute.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["missing", "generation", "expiry", "expired", "rejected"])
async def test_retired_generation_keeps_object_reference_but_cannot_advance_head(fixture, change):
    scope, intent, row, repository = fixture
    runtime = {"allocation_id": intent.allocation_id, "alive": True, "state": "ready"}
    if change == "generation":
        runtime["allocation_id"] = uuid4()
    elif change == "expiry":
        runtime["alive"] = False
    else:
        runtime["state"] = change
    session = MagicMock(
        execute=AsyncMock(
            side_effect=[
                result(exists=True),
                result(row),
                result(None if change == "missing" else runtime),
                result(),
                result({**row, "state": "retired"}),
            ]
        )
    )
    assert (
        await repository.publish(scope, intent.blob.checkpoint_id, session=session)
    ).state == "retired"
    queries = [str(call.args[0]) for call in session.execute.await_args_list]
    assert not any(query.startswith("UPDATE profile.ide_repository_head") for query in queries)
    assert not any("DELETE" in query for query in queries)


@pytest.mark.asyncio
async def test_temporarily_unknown_runtime_leaves_pending_intent_unchanged(fixture):
    scope, intent, row, repository = fixture
    session = MagicMock(
        execute=AsyncMock(
            side_effect=[
                result(exists=True),
                result(row),
                result(
                    {
                        "allocation_id": intent.allocation_id,
                        "alive": True,
                        "state": "unknown",
                    }
                ),
            ]
        )
    )
    assert (
        await repository.publish(scope, intent.blob.checkpoint_id, session=session)
    ).state == "pending"
    assert session.execute.await_count == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("cas_success", [False, True])
async def test_head_update_contains_base_generation_and_final_expiry_fences(fixture, cas_success):
    scope, intent, row, repository = fixture
    terminal = {**row, "state": "published" if cas_success else "retired"}
    terminal["current_checkpoint_id"] = intent.blob.checkpoint_id if cas_success else None
    session = MagicMock(
        execute=AsyncMock(
            side_effect=[
                result(exists=True),
                result(row),
                result({"allocation_id": intent.allocation_id, "alive": True, "state": "ready"}),
                result(exists=cas_success),
                result(),
                result(terminal),
            ]
        )
    )
    saved = await repository.publish(
        scope, intent.blob.checkpoint_id, verified=True, session=session
    )
    assert saved.is_current is cas_success
    query, params = session.execute.await_args_list[3].args
    assert "checkpoint_id IS NOT DISTINCT FROM :base_checkpoint_id" in str(query)
    assert "w.allocation_id=:allocation_id" in str(query)
    assert "w.expires_at>extract(epoch FROM clock_timestamp())" in str(query)
    assert params == intent.params()
    assert session.execute.await_args_list[4].args[1]["published"] is cas_success


@pytest.mark.asyncio
@pytest.mark.parametrize("verified", [False, None, "true", 1])
async def test_unverified_intent_cannot_advance_head_even_when_generation_is_ready(
    fixture, verified
):
    scope, intent, row, repository = fixture
    session = MagicMock(
        execute=AsyncMock(
            side_effect=[
                result(exists=True),
                result(row),
                result({"allocation_id": intent.allocation_id, "alive": True, "state": "ready"}),
            ]
        )
    )
    record = await repository.publish(
        scope, intent.blob.checkpoint_id, verified=verified, session=session
    )
    assert record.state == "pending" and not record.is_current
    assert session.execute.await_count == 3


@pytest.mark.asyncio
async def test_database_error_stays_uncertain_and_private(fixture, caplog):
    scope, intent, _, repository = fixture
    session = MagicMock(
        execute=AsyncMock(
            side_effect=OperationalError(
                "PRIVATE_SQL",
                {"digest": "PRIVATE_DIGEST"},
                Exception("PRIVATE_DB"),
            )
        )
    )
    with pytest.raises(RepositoryOperationalError) as caught:
        await repository.get_owned(scope, intent.blob.checkpoint_id, session=session)
    assert "PRIVATE" not in str(caught.value)
    assert "PRIVATE" not in caplog.text
