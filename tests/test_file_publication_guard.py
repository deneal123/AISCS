"""Guard admission and deletion in the same caller-owned SQL transaction."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from service.models.db.db_models import UserFile
from service.services.files.persistence.file_repository import FileRepository


def session_fixture(row):
    order, locks = [], []

    async def execute(statement, parameters=None):
        if "pg_advisory_xact_lock" in str(statement):
            order.append("lock")
            locks.append(parameters)
        elif str(statement).startswith("SELECT"):
            order.append("select")
        else:
            order.append("delete")
        return SimpleNamespace(scalar_one_or_none=lambda: row)

    async def flush():
        order.append("flush")

    session = SimpleNamespace(
        execute=AsyncMock(side_effect=execute),
        add=Mock(side_effect=lambda _row: order.append("add")),
        flush=AsyncMock(side_effect=flush),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )
    connector = SimpleNamespace(get_session_context=Mock())
    return FileRepository(connector), session, order, locks, connector


@pytest.mark.asyncio
@pytest.mark.parametrize("referenced", [False, True])
async def test_pending_reaper_checks_all_references_under_same_publication_lock(referenced):
    repository, session, order, locks, connector = session_fixture(None)
    owner, file_id = uuid4(), uuid4()

    async def lookup(statement):
        order.append("reference")
        # The query is by exact key, not owner/id: legacy or cross-owner references protect it.
        assert "file_name" in str(statement)
        assert "user_id" not in str(statement)
        return uuid4() if referenced else None

    async def remove():
        order.append("remove")
        return True

    session.scalar = AsyncMock(side_effect=lookup)
    assert await repository.remove_unreferenced_pending(
        owner, file_id, "fixture-pending-key", remove, session=session
    ) is (not referenced)
    assert order == (["lock", "reference"] if referenced else ["lock", "reference", "remove"])
    assert len(locks) == 1
    connector.get_session_context.assert_not_called()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_publication_and_delete_use_same_lock_without_second_session():
    owner, file_id = uuid4(), uuid4()
    row = UserFile(id=file_id, user_id=owner)
    repository, session, order, locks, connector = session_fixture(row)

    async def verify():
        order.append("verify")
        return True

    async def remove(found):
        assert found is row
        order.append("remove")

    assert await repository.add_direct_file_metadata(row, verify, session=session) is row
    assert order == ["lock", "verify", "add", "flush"]
    order.clear()
    assert await repository.delete_owned_file_atomically(owner, file_id, remove, session=session)
    assert order == ["lock", "select", "remove", "delete"]
    assert locks[0] == locks[1]
    assert set(locks[0]) == {"lock_id"}
    assert -(2**63) <= locks[0]["lock_id"] < 2**63
    connector.get_session_context.assert_not_called()
    session.commit.assert_not_awaited()  # External caller still owns transaction completion.


@pytest.mark.asyncio
async def test_missing_owned_row_never_invokes_external_delete():
    repository, session, order, _locks, _connector = session_fixture(None)
    remove = AsyncMock()
    assert not await repository.delete_owned_file_atomically(
        uuid4(), uuid4(), remove, session=session
    )
    assert order == ["lock", "select"]
    remove.assert_not_awaited()


@pytest.mark.asyncio
async def test_revoked_admission_never_adds_or_flushes_metadata():
    row = UserFile(id=uuid4(), user_id=uuid4())
    repository, session, order, _locks, connector = session_fixture(row)
    verify = AsyncMock(return_value=False)
    assert await repository.add_direct_file_metadata(row, verify, session=session) is None
    assert order == ["lock"]
    session.add.assert_not_called()
    session.flush.assert_not_awaited()
    connector.get_session_context.assert_not_called()


@pytest.mark.asyncio
async def test_cancelled_lock_never_reaches_admission_or_mutation():
    row = UserFile(id=uuid4(), user_id=uuid4())
    repository, session, _order, _locks, _connector = session_fixture(row)
    session.execute.side_effect = asyncio.CancelledError()
    verify = AsyncMock()
    with pytest.raises(asyncio.CancelledError):
        await repository.add_direct_file_metadata(row, verify, session=session)
    verify.assert_not_awaited()
    session.add.assert_not_called()
