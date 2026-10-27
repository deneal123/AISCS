from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError

from service.services.chat.persistence.ide.repositories import IdeRepositoryRepository
from service.shared.repositories.exceptions import RepositoryOperationalError


def result(*, row=None, rows=None, owner=False):
    value = MagicMock()
    value.first.return_value = (uuid4(),) if owner else None
    value.mappings.return_value.first.return_value = row
    value.mappings.return_value.all.return_value = rows or []
    return value


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["register"])
async def test_missing_owner_stops_before_insert_or_listing(method):
    session = MagicMock(execute=AsyncMock(return_value=result()))
    args = {"thread_id": uuid4(), "user_id": uuid4(), "session": session}
    args.update(
        {"creation_intent_id": uuid4(), "name": "Example"}
        if method == "register"
        else {"limit": 30, "offset": 0}
    )
    assert await getattr(IdeRepositoryRepository(MagicMock()), method)(**args) is None
    assert session.execute.await_count == 1
    sql, params = session.execute.call_args.args
    assert "thread_id = :thread_id AND user_id = :user_id" in str(sql)
    assert params["user_id"] == args["user_id"]


@pytest.mark.asyncio
async def test_draft_list_is_empty_without_inserting_but_foreign_thread_is_denied():
    user_id = uuid4()
    session = MagicMock(execute=AsyncMock(return_value=result()))
    repository = IdeRepositoryRepository(MagicMock())
    args = {"thread_id": uuid4(), "user_id": user_id, "limit": 30, "offset": 0, "session": session}
    assert await repository.list_owned(**args) == []
    assert session.execute.await_count == 1
    assert "INSERT" not in str(session.execute.await_args.args[0])
    denied = result()
    denied.first.return_value = (uuid4(),)
    session.execute.return_value = denied
    assert await repository.list_owned(**args) is None


@pytest.mark.asyncio
async def test_explicit_setup_inserts_draft_then_checks_owner_in_same_transaction():
    row = {"repository_id": uuid4(), "name": "Example", "created_at": None}
    session = MagicMock(
        execute=AsyncMock(side_effect=[result(), result(owner=True), result(row=row)])
    )
    args = {"thread_id": uuid4(), "user_id": uuid4(), "creation_intent_id": uuid4()}
    assert (
        await IdeRepositoryRepository(MagicMock()).register(
            **args, name="Example", create_thread_if_missing=True, session=session
        )
        == row
    )
    calls = session.execute.await_args_list
    assert "ON CONFLICT (thread_id) DO NOTHING" in str(calls[0].args[0])
    assert "FOR KEY SHARE" in str(calls[1].args[0])
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_concurrent_registration_loser_reads_only_its_owned_intent():
    row = {"repository_id": uuid4(), "name": "Example", "created_at": None}
    session = MagicMock(
        execute=AsyncMock(
            side_effect=[
                result(owner=True),
                result(),
                result(row=row),
            ]
        )
    )
    args = {"thread_id": uuid4(), "user_id": uuid4(), "creation_intent_id": uuid4()}
    assert (
        await IdeRepositoryRepository(MagicMock()).register(**args, name="Example", session=session)
        == row
    )
    calls = session.execute.call_args_list
    assert "FOR KEY SHARE" in str(calls[0].args[0])
    assert "ON CONFLICT (user_id, thread_id, creation_intent_id) DO NOTHING" in str(
        calls[1].args[0]
    )
    assert "DO UPDATE" not in str(calls[1].args[0])
    query, params = calls[2].args
    assert "r.creation_intent_id = :creation_intent_id" in str(query)
    assert "t.user_id = :user_id" in str(query)
    assert params == args
    session.commit.assert_not_called()  # An injected caller owns this transaction.


@pytest.mark.asyncio
async def test_get_requires_repo_thread_and_owner_in_the_same_query():
    session = MagicMock(execute=AsyncMock(return_value=result()))
    args = {"thread_id": uuid4(), "user_id": uuid4(), "repository_id": uuid4()}
    assert await IdeRepositoryRepository(MagicMock()).get_owned(**args, session=session) is None
    query, params = session.execute.call_args.args
    assert "r.user_id = :user_id AND t.user_id = :user_id" in str(query)
    assert "r.thread_id = :thread_id" in str(query)
    assert "r.repository_id = :repository_id" in str(query)
    assert params == args


@pytest.mark.asyncio
async def test_transport_failure_does_not_become_empty_or_leak_sql(caplog):
    session = MagicMock(
        execute=AsyncMock(
            side_effect=OperationalError(
                "PRIVATE_SQL", {"password": "PRIVATE_SECRET"}, Exception("PRIVATE_DRIVER")
            )
        )
    )
    with pytest.raises(RepositoryOperationalError) as captured:
        await IdeRepositoryRepository(MagicMock()).get_owned(
            thread_id=uuid4(), user_id=uuid4(), repository_id=uuid4(), session=session
        )
    assert "PRIVATE" not in str(captured.value)
    assert "PRIVATE" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("existing", [False, True])
async def test_default_identity_serializes_on_owned_thread_before_observing_absence(existing):
    row = {
        "repository_id": uuid4(),
        "name": "Existing" if existing else "Новый проект",
        "created_at": None,
    }
    responses = [result(), result(owner=True), result(row=row if existing else None)]
    if not existing:
        responses.append(result(row=row))
    session = MagicMock(execute=AsyncMock(side_effect=responses))
    scope = {"thread_id": uuid4(), "user_id": uuid4()}
    assert (
        await IdeRepositoryRepository(MagicMock()).ensure_default(**scope, session=session) == row
    )
    calls = session.execute.await_args_list
    assert "ON CONFLICT (thread_id) DO NOTHING" in str(calls[0].args[0])
    assert "FOR UPDATE" in str(calls[1].args[0])
    assert "user_id = :user_id" in str(calls[1].args[0])
    assert "ORDER BY r.created_at DESC" in str(calls[2].args[0])
    if not existing:
        assert "onboarding_created" in str(calls[3].args[0])
        assert "TRUE" in str(calls[3].args[0])
        assert not {"workspace_id", "remote_url", "token"} & calls[3].args[1].keys()
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_default_does_not_claim_foreign_thread_or_insert_its_repository():
    session = MagicMock(execute=AsyncMock(side_effect=[result(), result()]))
    assert (
        await IdeRepositoryRepository(MagicMock()).ensure_default(
            thread_id=uuid4(), user_id=uuid4(), session=session
        )
        is None
    )
    assert session.execute.await_count == 2
