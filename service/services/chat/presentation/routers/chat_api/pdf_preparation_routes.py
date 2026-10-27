"""Authenticated first-entry preparation; GET snapshots remain read-only."""

from functools import partial
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from starlette.requests import HTTPConnection

from service.composition.state import get_app_container, get_optional_redis_client
from service.infrastructure.ide.workspace import IdeWorkspaceClient
from service.models.auth_models import AuthProfile
from service.services.chat.application.documents.initial_content import (
    initialize_first_pdf_document,
)
from service.services.chat.application.documents.preparation import PdfPreparationService
from service.services.chat.domain.documents.preparation import (
    PdfPreparationNotFound,
    PdfPreparationScope,
    PdfPreparationUnavailable,
)
from service.services.chat.persistence.documents.preparation import PdfPreparationRepository
from service.settings import config
from service.shared.repositories.exceptions import RepositoryError
from service.shared.security.auth_checker import check_auth

router = APIRouter(tags=["pdf-preparation"])


class PdfPreparationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    retry: bool = Field(default=False, strict=True)


def get_pdf_preparation(
    request: HTTPConnection,
    redis=Depends(get_optional_redis_client),  # noqa: B008
) -> PdfPreparationService:
    return PdfPreparationService(
        PdfPreparationRepository(get_app_container(request).infra.pg_connector),
        IdeWorkspaceClient(config.agents),
        redis,
        initialize=partial(initialize_first_pdf_document, config=config, redis=redis),
    )


@router.post("/{thread_id}/work/pdf/prepare")
async def prepare_pdf(
    thread_id: UUID,
    payload: PdfPreparationRequest,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: Annotated[PdfPreparationService, Depends(get_pdf_preparation)],
) -> dict:
    try:
        return await service.prepare(
            PdfPreparationScope(thread_id, UUID(str(profile.user_id))), retry_scaffold=payload.retry
        )
    except PdfPreparationNotFound:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "pdf_project_not_found",
                "message": "PDF project not found",
            },
        ) from None
    except (PdfPreparationUnavailable, RepositoryError):
        raise HTTPException(
            status_code=503,
            detail={
                "code": "pdf_preparation_unavailable",
                "message": "PDF preparation unavailable",
            },
        ) from None
