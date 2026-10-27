"""Repository metadata only; opening/registering cannot provision a sandbox."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.requests import HTTPConnection

from service.composition.state import get_app_container
from service.models.auth_models import AuthProfile
from service.services.chat.application.ide.repositories import (
    IdeRepositoryIntentConflict,
    IdeRepositoryNotFound,
    IdeRepositoryService,
    normalize_repository_name,
)
from service.services.chat.persistence.ide.repositories import IdeRepositoryRepository
from service.shared.repositories.exceptions import RepositoryError
from service.shared.security.auth_checker import check_auth

router = APIRouter(tags=["ide-repositories"])


class RepositoryRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    creation_intent_id: UUID
    create_thread_if_missing: bool = False

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return normalize_repository_name(value)


class DefaultRepositoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


def get_ide_repositories(request: HTTPConnection) -> IdeRepositoryService:
    connector = get_app_container(request).infra.pg_connector
    return IdeRepositoryService(IdeRepositoryRepository(connector))


async def _respond[ResponseValue](operation: Awaitable[ResponseValue]) -> ResponseValue:
    try:
        return await operation
    except IdeRepositoryNotFound:
        raise HTTPException(status_code=404, detail="ide_repository_not_found") from None
    except IdeRepositoryIntentConflict:
        raise HTTPException(status_code=409, detail="ide_repository_intent_conflict") from None
    except RepositoryError:
        raise HTTPException(status_code=503, detail="ide_repository_unavailable") from None


@router.get("/{thread_id}/ide/repositories")
async def list_repositories(
    thread_id: UUID,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: Annotated[IdeRepositoryService, Depends(get_ide_repositories)],
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> dict[str, Any]:
    return await _respond(
        service.list(
            thread_id=thread_id, user_id=UUID(str(profile.user_id)), limit=limit, offset=offset
        )
    )


@router.post("/{thread_id}/ide/repositories")
async def register_repository(
    thread_id: UUID,
    payload: RepositoryRegistration,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: Annotated[IdeRepositoryService, Depends(get_ide_repositories)],
) -> dict[str, Any]:
    return await _respond(
        service.register(
            thread_id=thread_id,
            user_id=UUID(str(profile.user_id)),
            creation_intent_id=payload.creation_intent_id,
            name=payload.name,
            create_thread_if_missing=payload.create_thread_if_missing,
        )
    )


@router.get("/{thread_id}/ide/repositories/{repository_id}")
async def get_repository(
    thread_id: UUID,
    repository_id: UUID,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: Annotated[IdeRepositoryService, Depends(get_ide_repositories)],
) -> dict[str, Any]:
    return await _respond(
        service.get(
            thread_id=thread_id, user_id=UUID(str(profile.user_id)), repository_id=repository_id
        )
    )


@router.post("/{thread_id}/ide/repositories/default")
async def ensure_default_repository(
    thread_id: UUID,
    payload: DefaultRepositoryRequest,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: Annotated[IdeRepositoryService, Depends(get_ide_repositories)],
) -> dict[str, Any]:
    del payload
    return await _respond(
        service.ensure_default(thread_id=thread_id, user_id=UUID(str(profile.user_id)))
    )
