"""Prepare an owned repository run without starting a model or provisioning."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from service.composition.state import get_optional_redis_client
from service.models.auth_models import AuthProfile
from service.services.chat.application.ide.agent_context import resolve_ide_target
from service.services.chat.application.ide.run_ticket import issue_ticket
from service.services.chat.application.ide.runtime import IdeRuntimeService
from service.services.chat.domain.ide.edits import EDIT_ERRORS, IdeEditError
from service.services.chat.domain.ide.files import READ_ERRORS, IdeReadError
from service.services.chat.presentation.routers.chat_api.ide.repositories import _respond
from service.services.chat.presentation.routers.chat_api.ide.runtime import get_ide_runtime
from service.services.files.presentation.routers.files_api.private_route import PrivateFileRoute
from service.shared.security.auth_checker import check_auth

router = APIRouter(tags=["ide-agent"], route_class=PrivateFileRoute)


class AgentTargetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    generation: str = Field(pattern=r"^[a-f0-9]{64}$")


@router.post("/{thread_id}/ide/repositories/{repository_id}/agent/target")
async def prepare_target(
    thread_id: UUID,
    repository_id: UUID,
    payload: AgentTargetRequest,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    runtime: Annotated[IdeRuntimeService, Depends(get_ide_runtime)],
    redis: Annotated[Any, Depends(get_optional_redis_client)],
):
    raw = {"repository_id": str(repository_id), "generation": payload.generation}
    try:
        target, _ = await _respond(
            resolve_ide_target(runtime, str(thread_id), str(profile.user_id), raw)
        )
    except IdeEditError as error:
        raise HTTPException(EDIT_ERRORS[error.code], error.code) from None
    except IdeReadError as error:
        raise HTTPException(READ_ERRORS[error.code], error.code) from None
    return await issue_ticket(
        redis, thread_id=thread_id, user_id=profile.user_id, target=target.model_dump(mode="json")
    )
