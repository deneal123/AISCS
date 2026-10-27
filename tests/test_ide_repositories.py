from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from service.services.chat.application.ide.repositories import (
    IdeRepositoryIntentConflict,
    IdeRepositoryNotFound,
    IdeRepositoryService,
    normalize_repository_name,
)


def descriptor(name="Example"):
    return {
        "repository_id": uuid4(),
        "name": name,
        "created_at": datetime(2026, 10, 16, tzinfo=UTC),
        "token": "PRIVATE_TOKEN",
        "workspace_id": "PRIVATE_WORKSPACE",
        "creation_intent_id": "PRIVATE_INTENT",
    }


@pytest.mark.parametrize("name", ["", "   ", "a" * 121, "a\x00b", "a\nb", "a\x7fb", "a\u2028b"])
def test_invalid_repository_names_are_rejected(name):
    with pytest.raises(ValueError, match="invalid_repository_name"):
        normalize_repository_name(name)


def test_name_is_canonical_unicode_without_becoming_a_path():
    assert normalize_repository_name("  Cafe\u0301 project  ") == "Café project"


@pytest.mark.asyncio
async def test_public_page_is_bounded_and_does_not_expose_future_private_columns():
    persistence = MagicMock()
    persistence.list_owned = AsyncMock(return_value=[descriptor(), descriptor()])
    service = IdeRepositoryService(persistence)
    thread_id, user_id = uuid4(), uuid4()
    result = await service.list(thread_id=thread_id, user_id=user_id, limit=1, offset=5)
    assert result["next_offset"] == 6
    assert len(result["items"]) == 1
    assert set(result["items"][0]) == {"repository_id", "name", "created_at", "state"}
    assert result["items"][0]["state"] == "registered"
    assert "PRIVATE" not in str(result)
    persistence.list_owned.assert_awaited_once_with(
        thread_id=thread_id, user_id=user_id, limit=2, offset=5
    )


@pytest.mark.asyncio
async def test_empty_owned_page_is_not_a_missing_thread():
    persistence = MagicMock(list_owned=AsyncMock(return_value=[]))
    assert await IdeRepositoryService(persistence).list(
        thread_id=uuid4(), user_id=uuid4(), limit=30, offset=0
    ) == {"items": [], "next_offset": None}


@pytest.mark.asyncio
async def test_default_identity_does_not_reinterpret_private_provenance_or_create_a_runtime():
    row = {**descriptor(), "onboarding_created": True}
    persistence = MagicMock(ensure_default=AsyncMock(return_value=row))
    scope = {"thread_id": uuid4(), "user_id": uuid4()}
    result = await IdeRepositoryService(persistence).ensure_default(**scope)
    assert set(result) == {"repository_id", "name", "created_at", "state"}
    persistence.ensure_default.assert_awaited_once_with(**scope)
    assert "PRIVATE" not in str(result)
    persistence.register.assert_not_called()


@pytest.mark.asyncio
async def test_default_ownership_failure_never_falls_back_to_explicit_registration():
    persistence = MagicMock(ensure_default=AsyncMock(return_value=None))
    with pytest.raises(IdeRepositoryNotFound):
        await IdeRepositoryService(persistence).ensure_default(thread_id=uuid4(), user_id=uuid4())
    persistence.register.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["list", "get", "register"])
async def test_missing_or_unowned_resources_cannot_become_empty_or_created(operation):
    persistence = MagicMock(
        list_owned=AsyncMock(return_value=None),
        get_owned=AsyncMock(return_value=None),
        register=AsyncMock(return_value=None),
    )
    kwargs = {"thread_id": uuid4(), "user_id": uuid4()}
    kwargs.update(
        {
            "list": {"limit": 30, "offset": 0},
            "get": {"repository_id": uuid4()},
            "register": {"creation_intent_id": uuid4(), "name": "Example"},
        }[operation]
    )
    with pytest.raises(IdeRepositoryNotFound):
        await getattr(IdeRepositoryService(persistence), operation)(**kwargs)


@pytest.mark.asyncio
async def test_registration_retry_returns_the_winner_and_never_renames_it():
    row = descriptor()
    persistence = MagicMock(register=AsyncMock(return_value=row))
    service = IdeRepositoryService(persistence)
    args = {"thread_id": uuid4(), "user_id": uuid4(), "creation_intent_id": uuid4()}
    first = await service.register(**args, name=" Example ")
    second = await service.register(**args, name="Example")
    assert first == second
    with pytest.raises(IdeRepositoryIntentConflict):
        await service.register(**args, name="Different")
    assert row["name"] == "Example"


@pytest.mark.asyncio
@pytest.mark.parametrize("limit,offset", [(0, 0), (101, 0), (30, -1), (30, 100_001)])
async def test_invalid_page_is_rejected_before_database_access(limit, offset):
    persistence = MagicMock(list_owned=AsyncMock())
    with pytest.raises(ValueError, match="invalid_repository_page"):
        await IdeRepositoryService(persistence).list(
            thread_id=uuid4(), user_id=uuid4(), limit=limit, offset=offset
        )
    persistence.list_owned.assert_not_awaited()
