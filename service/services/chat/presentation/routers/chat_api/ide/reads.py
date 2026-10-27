"""Source paths/bodies stay in protected REST bodies, not URLs, WS or telemetry."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from service.models.auth_models import AuthProfile
from service.services.chat.application.ide.reads import IdeReadService
from service.services.chat.application.ide.runtime import IdeRuntimeService
from service.services.chat.domain.ide.files import READ_ERRORS, IdeReadError
from service.services.chat.domain.ide.runtime import RepositoryScope
from service.services.chat.presentation.routers.chat_api.ide.repositories import _respond
from service.services.chat.presentation.routers.chat_api.ide.runtime import get_ide_runtime
from service.services.files.presentation.routers.files_api.private_route import PrivateFileRoute
from service.shared.security.auth_checker import check_auth

router = APIRouter(tags=["ide-reads"], route_class=PrivateFileRoute)


class RepositoryTreeRead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(default="", max_length=1024)
    generation: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class RepositoryFileRead(RepositoryTreeRead):
    path: str = Field(min_length=1, max_length=1024)
    generation: str = Field(pattern=r"^[a-f0-9]{64}$")


async def read(service, scope, payload, operation):
    try:
        return await _respond(
            IdeReadService(service).read(
                scope, operation=operation, path=payload.path, generation=payload.generation
            )
        )
    except IdeReadError as error:
        raise HTTPException(status_code=READ_ERRORS[error.code], detail=error.code) from None


@router.post("/{thread_id}/ide/repositories/{repository_id}/files/tree")
async def repository_tree(
    thread_id: UUID,
    repository_id: UUID,
    payload: RepositoryTreeRead,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: Annotated[IdeRuntimeService, Depends(get_ide_runtime)],
) -> dict[str, Any]:
    return await read(
        service,
        RepositoryScope(thread_id, UUID(str(profile.user_id)), repository_id),
        payload,
        "tree",
    )


@router.post("/{thread_id}/ide/repositories/{repository_id}/files/read")
async def repository_file(
    thread_id: UUID,
    repository_id: UUID,
    payload: RepositoryFileRead,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: Annotated[IdeRuntimeService, Depends(get_ide_runtime)],
) -> dict[str, Any]:
    return await read(
        service,
        RepositoryScope(thread_id, UUID(str(profile.user_id)), repository_id),
        payload,
        "file",
    )
