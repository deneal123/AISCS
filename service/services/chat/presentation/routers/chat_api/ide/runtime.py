"""Owned IDE workspace status/provision; never repoint the thread's PDF binding."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from starlette.requests import HTTPConnection

from service.composition.state import get_app_container
from service.infrastructure.ide.workspace import IdeWorkspaceClient
from service.models.auth_models import AuthProfile
from service.services.chat.application.ide.runtime import IdeRuntimeService
from service.services.chat.domain.ide.runtime import RepositoryScope
from service.services.chat.persistence.ide.repositories import IdeRepositoryRepository
from service.services.chat.persistence.ide.runtime import IdeRuntimeRepository
from service.services.chat.presentation.routers.chat_api.ide.repositories import _respond
from service.settings import config
from service.shared.security.auth_checker import check_auth

router = APIRouter(tags=["ide-runtime"])


class RuntimeProvisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


def get_ide_runtime(request: HTTPConnection) -> IdeRuntimeService:
    connector = get_app_container(request).infra.pg_connector
    return IdeRuntimeService(
        IdeRepositoryRepository(connector),
        IdeRuntimeRepository(connector),
        IdeWorkspaceClient(config.agents),
    )


@router.get("/{thread_id}/ide/repositories/{repository_id}/runtime")
async def runtime_status(
    thread_id: UUID,
    repository_id: UUID,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: Annotated[IdeRuntimeService, Depends(get_ide_runtime)],
) -> dict[str, Any]:
    return await _respond(
        service.status(RepositoryScope(thread_id, UUID(str(profile.user_id)), repository_id))
    )


@router.post("/{thread_id}/ide/repositories/{repository_id}/runtime")
async def provision_runtime(
    thread_id: UUID,
    repository_id: UUID,
    payload: RuntimeProvisionRequest,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: Annotated[IdeRuntimeService, Depends(get_ide_runtime)],
) -> dict[str, Any]:
    return await _respond(
        service.provision(RepositoryScope(thread_id, UUID(str(profile.user_id)), repository_id))
    )
