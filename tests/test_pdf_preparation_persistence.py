from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from service.services.chat.domain.documents.preparation import PdfPreparationScope
from service.services.chat.persistence.documents.preparation import PdfPreparationRepository
from service.shared.repositories.exceptions import RepositoryError


def result(*, row=None, owner=False):
    value = MagicMock()
    value.first.return_value = (uuid4(),) if owner else None
    value.mappings.return_value.first.return_value = row
    value.mappings.return_value.one.return_value = row
    return value


@pytest.fixture
def setup():
    scope = PdfPreparationScope(uuid4(), uuid4())
    session = MagicMock(execute=AsyncMock())
    repository = PdfPreparationRepository(MagicMock())
    return SimpleNamespace(**locals())


@pytest.mark.asyncio
async def test_owned_scope_is_checked_before_claim_and_uses_thread_row_lock(setup):
    s = setup
    s.session.execute.return_value = result()
    assert await s.repository.claim(s.scope, ttl_sec=300, session=s.session) == (None, False)
    s.session.execute.assert_awaited_once()
    sql, params = s.session.execute.await_args.args
    assert "user_id=:user_id FOR UPDATE" in str(sql)
    assert params == s.scope.params()


@pytest.mark.asyncio
async def test_new_claim_is_fixed_and_replay_never_updates_identity_or_expiry(setup):
    s = setup
    row = {"allocation_id": uuid4(), "workspace_id": None, "expires_at": 12345678900}
    s.session.execute.side_effect = [result(owner=True), result(), result(row=row)]
    value, dispatch = await s.repository.claim(s.scope, ttl_sec=300, session=s.session)
    assert dispatch and value.allocation_id == row["allocation_id"]
    insert = s.session.execute.await_args.args
    assert "RETURNING allocation_id,workspace_id,expires_at" in str(insert[0])
    assert insert[1]["ttl_sec"] == 300 and insert[1]["expires_at"] is None
    s.session.execute.reset_mock(side_effect=True)
    s.session.execute.side_effect = [result(owner=True), result(row=row)]
    replay, dispatch = await s.repository.claim(s.scope, ttl_sec=999, session=s.session)
    assert replay == value and not dispatch
    assert all(
        "UPDATE" not in str(call.args[0]).replace("FOR UPDATE", "")
        and "INSERT" not in str(call.args[0])
        for call in s.session.execute.await_args_list
    )


@pytest.mark.asyncio
async def test_adoption_stores_only_private_identity_not_a_new_allocation(setup):
    s = setup
    row = {"allocation_id": None, "workspace_id": "a" * 32, "expires_at": 12345678900}
    s.session.execute.side_effect = [result(owner=True), result(), result(row=row)]
    value, dispatch = await s.repository.claim(
        s.scope,
        ttl_sec=1,
        workspace_id=row["workspace_id"],
        expires_at=row["expires_at"],
        session=s.session,
    )
    assert not dispatch and value.workspace_id == row["workspace_id"]
    params = s.session.execute.await_args.args[1]
    assert params["allocation_id"] is None
    assert "token" not in params


@pytest.mark.asyncio
async def test_ensure_owner_does_not_replace_another_accounts_thread(setup):
    s = setup
    s.session.execute.side_effect = [result(), result()]
    assert not await s.repository.ensure_owner(s.scope, session=s.session)
    assert "ON CONFLICT (thread_id) DO NOTHING" in str(s.session.execute.await_args_list[0].args[0])
    assert "user_id=:user_id" in str(s.session.execute.await_args_list[1].args[0])


@pytest.mark.asyncio
@pytest.mark.parametrize("ttl", [0, -1, True, 1.5, 2**31])
async def test_invalid_deadline_never_reaches_database(setup, ttl):
    s = setup
    with pytest.raises(RepositoryError):
        await s.repository.claim(s.scope, ttl_sec=ttl, session=s.session)
    s.session.execute.assert_not_awaited()
