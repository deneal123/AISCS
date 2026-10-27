"""Library copy accepts identifiers/path only, never a browser URL or source bytes."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field

from service.composition.state import get_file_saver_service, get_optional_redis_client
from service.models.auth_models import AuthProfile
from service.services.chat.application.ide.edits import IdeEditService
from service.services.chat.application.ide.library import copy_library_file
from service.services.chat.application.ide.runtime import IdeRuntimeService
from service.services.chat.domain.ide.runtime import RepositoryScope
from service.services.chat.presentation.routers.chat_api.ide.edits import _edit
from service.services.chat.presentation.routers.chat_api.ide.runtime import get_ide_runtime
from service.services.files.application.file_saver_service import FileSaverService
from service.services.files.presentation.routers.files_api.private_route import PrivateFileRoute
from service.shared.security.auth_checker import check_auth

router = APIRouter(tags=["ide-library"], route_class=PrivateFileRoute)


class LibraryCopyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=1024)
    generation: str = Field(pattern=r"^[a-f0-9]{64}$")
    fence: int = Field(ge=1)


@router.post("/{thread_id}/ide/repositories/{repository_id}/library/{file_id}/copy")
async def copy(
    thread_id: UUID,
    repository_id: UUID,
    file_id: UUID,
    payload: LibraryCopyRequest,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    runtime: Annotated[IdeRuntimeService, Depends(get_ide_runtime)],
    files: Annotated[FileSaverService, Depends(get_file_saver_service)],
    redis: Annotated[Any, Depends(get_optional_redis_client)],
    session: Annotated[str | None, Header(alias="X-Workspace-Session")] = None,
):
    return await _edit(
        copy_library_file(
            IdeEditService(runtime, redis),
            files,
            RepositoryScope(thread_id, UUID(str(profile.user_id)), repository_id),
            file_id=file_id,
            **payload.model_dump(),
            session=session,
        )
    )
