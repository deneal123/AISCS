"""Owned IDE descriptors. Registration is not sandbox/Git initialization."""

from __future__ import annotations

import unicodedata
from typing import Any
from uuid import UUID

from service.services.chat.persistence.ide.repositories import IdeRepositoryRepository


class IdeRepositoryNotFound(Exception):
    pass


class IdeRepositoryIntentConflict(Exception):
    pass


def normalize_repository_name(value: str) -> str:
    name = unicodedata.normalize("NFC", value).strip()
    if not 1 <= len(name) <= 120 or any(
        ord(char) < 32 or ord(char) == 127 or char in "\u2028\u2029" for char in name
    ):
        raise ValueError("invalid_repository_name")
    return name


def public_repository(row: dict[str, Any]) -> dict[str, Any]:
    # Deliberate allowlist: future private runtime/origin columns cannot leak.
    return {
        "repository_id": str(row["repository_id"]),
        "name": row["name"],
        "created_at": row["created_at"],
        "state": "registered",
    }


class IdeRepositoryService:
    def __init__(self, repository: IdeRepositoryRepository) -> None:
        self.repository = repository

    async def ensure_default(self, *, thread_id: UUID, user_id: UUID) -> dict[str, Any]:
        row = await self.repository.ensure_default(thread_id=thread_id, user_id=user_id)
        if row is None:
            raise IdeRepositoryNotFound
        return public_repository(row)

    async def list(
        self, *, thread_id: UUID, user_id: UUID, limit: int, offset: int
    ) -> dict[str, Any]:
        if not 1 <= limit <= 100 or not 0 <= offset <= 100_000:
            raise ValueError("invalid_repository_page")
        rows = await self.repository.list_owned(
            thread_id=thread_id, user_id=user_id, limit=limit + 1, offset=offset
        )
        if rows is None:
            raise IdeRepositoryNotFound
        return {
            "items": [public_repository(row) for row in rows[:limit]],
            "next_offset": offset + limit if len(rows) > limit else None,
        }

    async def get(self, *, thread_id: UUID, user_id: UUID, repository_id: UUID) -> dict[str, Any]:
        row = await self.repository.get_owned(
            thread_id=thread_id, user_id=user_id, repository_id=repository_id
        )
        if row is None:
            raise IdeRepositoryNotFound
        return public_repository(row)

    async def register(
        self,
        *,
        thread_id: UUID,
        user_id: UUID,
        creation_intent_id: UUID,
        name: str,
        create_thread_if_missing: bool = False,
    ) -> dict[str, Any]:
        name = normalize_repository_name(name)
        row = await self.repository.register(
            thread_id=thread_id,
            user_id=user_id,
            creation_intent_id=creation_intent_id,
            name=name,
            create_thread_if_missing=create_thread_if_missing,
        )
        if row is None:
            raise IdeRepositoryNotFound
        if row["name"] != name:
            raise IdeRepositoryIntentConflict
        return public_repository(row)
