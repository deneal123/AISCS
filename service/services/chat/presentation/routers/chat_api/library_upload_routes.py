"""Library-only upload; no ignored flag may fall back to workspace activation."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile

from service.composition.state import get_chat_application_service, get_file_saver_service
from service.models.auth_models import AuthProfile
from service.services.chat.application.chat_application_service import ChatApplicationService
from service.services.chat.presentation.routers.chat_api.work_intake import (
    persist_and_import_uploaded_file,
)
from service.services.files.application.file_saver_service import FileSaverService
from service.services.files.presentation.routers.files_api.private_route import PrivateFileRoute
from service.shared.security.auth_checker import check_auth

router = APIRouter(tags=["library-upload"], route_class=PrivateFileRoute)


@router.post("/{thread_id}/work/library/upload")
async def upload_file_to_library(
    thread_id: str,
    file: Annotated[UploadFile, File(...)],
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: Annotated[ChatApplicationService, Depends(get_chat_application_service)],
    file_service: Annotated[FileSaverService, Depends(get_file_saver_service)],
    upload_intent_id: Annotated[UUID | None, Form()] = None,
):
    await service.ensure_thread_owner(thread_id, str(profile.user_id))
    return await persist_and_import_uploaded_file(
        file=file,
        user_id=profile.user_id,
        file_service=file_service,
        import_workspace=None,
        upload_intent_id=upload_intent_id,
    )
