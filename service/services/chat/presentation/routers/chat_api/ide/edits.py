"""Owned repository mutations. Paths/content stay in protected request bodies."""

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from service.composition.state import get_optional_redis_client
from service.models.auth_models import AuthProfile
from service.services.chat.application.ide.clones import IdeCloneService
from service.services.chat.application.ide.edits import IdeEditService
from service.services.chat.application.ide.prepare import IdePrepareService
from service.services.chat.application.ide.runtime import IdeRuntimeService
from service.services.chat.domain.ide.edits import EDIT_ERRORS, IdeEditError
from service.services.chat.domain.ide.files import READ_ERRORS, IdeReadError
from service.services.chat.domain.ide.runtime import RepositoryScope
from service.services.chat.persistence.ide.clones import IdeCloneRepository
from service.services.chat.presentation.routers.chat_api.ide.repositories import _respond
from service.services.chat.presentation.routers.chat_api.ide.runtime import get_ide_runtime
from service.services.files.presentation.routers.files_api.private_route import PrivateFileRoute
from service.shared.security.auth_checker import check_auth

router = APIRouter(tags=["ide-edits"], route_class=PrivateFileRoute)


def get_ide_clones(
    runtime: Annotated[IdeRuntimeService, Depends(get_ide_runtime)],
    redis: Annotated[Any, Depends(get_optional_redis_client)],
) -> IdeCloneService:
    return IdeCloneService(runtime, IdeCloneRepository(runtime.repository.connector), redis)


class CloneRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent_id: UUID
    source_repository_id: UUID
    origin: str = Field(min_length=1, max_length=512)
    branch: str = Field(default="", max_length=200)


@router.get("/{thread_id}/ide/repositories/{repository_id}/clone-attempt")
async def recover_clone(
    thread_id: UUID,
    repository_id: UUID,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: Annotated[IdeCloneService, Depends(get_ide_clones)],
):
    return await _edit(
        service.recover(RepositoryScope(thread_id, UUID(str(profile.user_id)), repository_id))
    )


@router.post("/{thread_id}/ide/clones")
async def clone_isolated(
    thread_id: UUID,
    payload: CloneRequest,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: Annotated[IdeCloneService, Depends(get_ide_clones)],
    session: Annotated[str | None, Header(alias="X-Workspace-Session")] = None,
):
    return await _edit(
        service.clone(
            RepositoryScope(thread_id, UUID(str(profile.user_id)), payload.source_repository_id),
            intent_id=payload.intent_id,
            origin=payload.origin,
            branch=payload.branch,
            session=session,
        )
    )


@router.get("/{thread_id}/ide/clones/{intent_id}")
async def clone_status(
    thread_id: UUID,
    intent_id: UUID,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: Annotated[IdeCloneService, Depends(get_ide_clones)],
):
    return await _edit(
        service.status(thread_id=thread_id, user_id=UUID(str(profile.user_id)), intent_id=intent_id)
    )


class PrepareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repository_id: UUID | None = None


@router.post("/{thread_id}/ide/prepare")
async def prepare(
    thread_id: UUID,
    payload: PrepareRequest,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    runtime: Annotated[IdeRuntimeService, Depends(get_ide_runtime)],
    redis: Annotated[Any, Depends(get_optional_redis_client)],
    session: Annotated[str | None, Header(alias="X-Workspace-Session")] = None,
):
    return await _edit(
        IdePrepareService(runtime, redis).prepare(
            thread_id=thread_id,
            user_id=UUID(str(profile.user_id)),
            session=session,
            repository_id=payload.repository_id,
        )
    )


class LeaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=1024)
    generation: str = Field(pattern=r"^[a-f0-9]{64}$")
    action: Literal["acquire", "renew", "release"]
    fence: int | None = Field(default=None, ge=1)


class WriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=1024)
    generation: str = Field(pattern=r"^[a-f0-9]{64}$")
    operation: Literal["file", "directory"]
    content: str = Field(default="", max_length=262144)
    expected_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    fence: int = Field(ge=1)


class MoveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=1024)
    destination: str = Field(min_length=1, max_length=1024)
    generation: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    fence: int = Field(ge=1)
    destination_fence: int = Field(ge=1)


@router.post("/{thread_id}/ide/repositories/{repository_id}/files/move")
async def move(
    thread_id: UUID,
    repository_id: UUID,
    payload: MoveRequest,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    runtime: Annotated[IdeRuntimeService, Depends(get_ide_runtime)],
    redis: Annotated[Any, Depends(get_optional_redis_client)],
    session: Annotated[str | None, Header(alias="X-Workspace-Session")] = None,
):
    return await _edit(
        IdeEditService(runtime, redis).move(
            RepositoryScope(thread_id, UUID(str(profile.user_id)), repository_id),
            **payload.model_dump(),
            session=session,
        )
    )


class GitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    generation: str = Field(pattern=r"^[a-f0-9]{64}$")
    operation: Literal["status", "init", "clone"]
    origin: str = Field(default="", max_length=512)
    branch: str = Field(default="", max_length=200)


@router.post("/{thread_id}/ide/repositories/{repository_id}/git")
async def git(
    thread_id: UUID,
    repository_id: UUID,
    payload: GitRequest,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    runtime: Annotated[IdeRuntimeService, Depends(get_ide_runtime)],
    redis: Annotated[Any, Depends(get_optional_redis_client)],
    session: Annotated[str | None, Header(alias="X-Workspace-Session")] = None,
):
    return await _edit(
        IdeEditService(runtime, redis).git(
            RepositoryScope(thread_id, UUID(str(profile.user_id)), repository_id),
            **payload.model_dump(),
            session=session,
        )
    )


async def _edit(operation):
    try:
        return await _respond(operation)
    except IdeEditError as error:
        raise HTTPException(
            status_code=EDIT_ERRORS[error.code], detail={"code": error.code, "message": error.code}
        ) from None
    except IdeReadError as error:
        raise HTTPException(
            status_code=READ_ERRORS[error.code], detail={"code": error.code, "message": error.code}
        ) from None


@router.post("/{thread_id}/ide/repositories/{repository_id}/files/lease")
async def lease(
    thread_id: UUID,
    repository_id: UUID,
    payload: LeaseRequest,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    runtime: Annotated[IdeRuntimeService, Depends(get_ide_runtime)],
    redis: Annotated[Any, Depends(get_optional_redis_client)],
    session: Annotated[str | None, Header(alias="X-Workspace-Session")] = None,
):
    return await _edit(
        IdeEditService(runtime, redis).lease(
            RepositoryScope(thread_id, UUID(str(profile.user_id)), repository_id),
            **payload.model_dump(),
            session=session,
        )
    )


@router.post("/{thread_id}/ide/repositories/{repository_id}/files/write")
async def write(
    thread_id: UUID,
    repository_id: UUID,
    payload: WriteRequest,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    runtime: Annotated[IdeRuntimeService, Depends(get_ide_runtime)],
    redis: Annotated[Any, Depends(get_optional_redis_client)],
    session: Annotated[str | None, Header(alias="X-Workspace-Session")] = None,
):
    return await _edit(
        IdeEditService(runtime, redis).write(
            RepositoryScope(thread_id, UUID(str(profile.user_id)), repository_id),
            **payload.model_dump(),
            session=session,
        )
    )
