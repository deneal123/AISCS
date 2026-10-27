"""Explicit owned Save/history/restore. No blob identity or credentials in REST."""

from collections.abc import Awaitable
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from starlette.requests import HTTPConnection

from service.composition.ide_checkpoints import build_saved_projects
from service.composition.state import get_app_container, get_optional_redis_client
from service.models.auth_models import AuthProfile
from service.services.chat.application.ide.checkpoints.saved_projects import IdeSavedProjects
from service.services.chat.application.ide.repositories import IdeRepositoryNotFound
from service.services.chat.application.ide.runtime import IdeRuntimeService
from service.services.chat.domain.ide.checkpoints.blob import IdeCheckpointError
from service.services.chat.domain.ide.edits import EDIT_ERRORS, IdeEditError
from service.services.chat.domain.ide.files import READ_ERRORS, IdeReadError
from service.services.chat.domain.ide.runtime import RepositoryScope
from service.services.chat.presentation.routers.chat_api.ide.runtime import get_ide_runtime
from service.services.files.presentation.routers.files_api.private_route import PrivateFileRoute
from service.settings import config
from service.shared.repositories.exceptions import RepositoryError
from service.shared.security.auth_checker import check_auth

router = APIRouter(tags=["ide-checkpoints"], route_class=PrivateFileRoute)


class SaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    checkpoint_id: UUID
    base_checkpoint_id: UUID | None = None
    generation: str = Field(pattern=r"^[a-f0-9]{64}$")


class RestoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    restore_id: UUID
    checkpoint_id: UUID
    base_generation: str = Field(pattern=r"^[a-f0-9]{64}$")


class EmptyActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


def failure(status_code: int, code: str) -> HTTPException:
    # Production's HTTP mapper preserves explicit codes, not a string detail.
    # Every caller supplies a domain-validated code or a static closed constant.
    return HTTPException(status_code=status_code, detail={"code": code, "message": code})


async def respond[Result](operation: Awaitable[Result]) -> Result:
    try:
        return await operation
    except IdeRepositoryNotFound:
        raise failure(404, "ide_repository_not_found") from None
    except RepositoryError:
        raise failure(503, "ide_checkpoint_status_unknown") from None
    except IdeCheckpointError as error:
        status = (
            409
            if error.code
            in {
                "ide_command_busy",
                "ide_checkpoint_intent_mismatch",
                "ide_checkpoint_runtime_not_ready",
                "ide_checkpoint_not_published",
                "ide_checkpoint_restore_pending",
                "ide_checkpoint_quota_exceeded",
                "ide_checkpoint_pending",
                "ide_checkpoint_head_changed",
                "ide_checkpoint_not_discardable",
                "ide_checkpoint_not_abandonable",
            }
            else 400
            if error.code == "ide_checkpoint_invalid"
            else 503
        )
        raise failure(status, error.code) from None
    except IdeEditError as error:
        raise failure(EDIT_ERRORS[error.code], error.code) from None
    except IdeReadError as error:
        raise failure(READ_ERRORS[error.code], error.code) from None


def get_saved_projects(
    request: HTTPConnection,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    runtime: Annotated[IdeRuntimeService, Depends(get_ide_runtime)],
    redis: Annotated[Any, Depends(get_optional_redis_client)],
) -> IdeSavedProjects:
    try:
        return build_saved_projects(
            get_app_container(request).infra, runtime, redis, config.ide_checkpoints
        )
    except IdeCheckpointError:
        raise failure(503, "ide_checkpoint_storage_unavailable") from None


def scope_for(thread_id: UUID, repository_id: UUID, profile: AuthProfile) -> RepositoryScope:
    return RepositoryScope(thread_id, UUID(str(profile.user_id)), repository_id)


@router.get("/{thread_id}/ide/repositories/{repository_id}/checkpoints/capabilities")
async def capabilities(
    thread_id: UUID,
    repository_id: UUID,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    runtime: Annotated[IdeRuntimeService, Depends(get_ide_runtime)],
) -> dict[str, Any]:
    await respond(runtime._check_owner(scope_for(thread_id, repository_id, profile)))
    return {"enabled": config.ide_checkpoints.enabled}


@router.get("/{thread_id}/ide/repositories/{repository_id}/checkpoints")
async def history(
    thread_id: UUID,
    repository_id: UUID,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: Annotated[IdeSavedProjects, Depends(get_saved_projects)],
):
    return await respond(service.history(scope_for(thread_id, repository_id, profile)))


@router.post("/{thread_id}/ide/repositories/{repository_id}/checkpoints")
async def save(
    thread_id: UUID,
    repository_id: UUID,
    payload: SaveRequest,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: Annotated[IdeSavedProjects, Depends(get_saved_projects)],
    session: Annotated[str | None, Header(alias="X-Workspace-Session")] = None,
):
    return await respond(
        service.save(
            scope_for(thread_id, repository_id, profile),
            checkpoint_id=payload.checkpoint_id,
            base_checkpoint_id=payload.base_checkpoint_id,
            generation=payload.generation,
            session=session,
        )
    )


@router.get("/{thread_id}/ide/repositories/{repository_id}/checkpoints/{checkpoint_id}")
async def status(
    thread_id: UUID,
    repository_id: UUID,
    checkpoint_id: UUID,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: Annotated[IdeSavedProjects, Depends(get_saved_projects)],
):
    return await respond(
        service.status(scope_for(thread_id, repository_id, profile), checkpoint_id)
    )


@router.post("/{thread_id}/ide/repositories/{repository_id}/checkpoints/{checkpoint_id}/reconcile")
async def reconcile(
    thread_id: UUID,
    repository_id: UUID,
    checkpoint_id: UUID,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: Annotated[IdeSavedProjects, Depends(get_saved_projects)],
    payload: Annotated[EmptyActionRequest, Body(default_factory=EmptyActionRequest)],
):
    return await respond(
        service.reconcile(scope_for(thread_id, repository_id, profile), checkpoint_id)
    )


@router.post("/{thread_id}/ide/repositories/{repository_id}/checkpoints/{checkpoint_id}/abandon")
async def abandon(
    thread_id: UUID,
    repository_id: UUID,
    checkpoint_id: UUID,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: Annotated[IdeSavedProjects, Depends(get_saved_projects)],
    payload: Annotated[EmptyActionRequest, Body(default_factory=EmptyActionRequest)],
):
    return await respond(
        service.abandon(scope_for(thread_id, repository_id, profile), checkpoint_id)
    )


@router.post("/{thread_id}/ide/repositories/{repository_id}/checkpoints/{checkpoint_id}/discard")
async def discard(
    thread_id: UUID,
    repository_id: UUID,
    checkpoint_id: UUID,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: Annotated[IdeSavedProjects, Depends(get_saved_projects)],
    payload: Annotated[EmptyActionRequest, Body(default_factory=EmptyActionRequest)],
):
    return await respond(
        service.discard(scope_for(thread_id, repository_id, profile), checkpoint_id)
    )


@router.post("/{thread_id}/ide/repositories/{repository_id}/restores")
async def restore(
    thread_id: UUID,
    repository_id: UUID,
    payload: RestoreRequest,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: Annotated[IdeSavedProjects, Depends(get_saved_projects)],
):
    return await respond(
        service.restore(
            scope_for(thread_id, repository_id, profile),
            restore_id=payload.restore_id,
            checkpoint_id=payload.checkpoint_id,
            base_generation=payload.base_generation,
        )
    )


@router.get("/{thread_id}/ide/repositories/{repository_id}/restores/{restore_id}")
async def restore_status(
    thread_id: UUID,
    repository_id: UUID,
    restore_id: UUID,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: Annotated[IdeSavedProjects, Depends(get_saved_projects)],
):
    return await respond(
        service.restore_status(scope_for(thread_id, repository_id, profile), restore_id)
    )


@router.post("/{thread_id}/ide/repositories/{repository_id}/restores/{restore_id}/reconcile")
async def reconcile_restore(
    thread_id: UUID,
    repository_id: UUID,
    restore_id: UUID,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: Annotated[IdeSavedProjects, Depends(get_saved_projects)],
    payload: Annotated[EmptyActionRequest, Body(default_factory=EmptyActionRequest)],
):
    return await respond(
        service.reconcile_restore(scope_for(thread_id, repository_id, profile), restore_id)
    )
