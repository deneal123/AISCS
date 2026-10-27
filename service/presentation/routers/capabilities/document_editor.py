"""Private, non-metered renderer RPC. Backend owns authorization and persistence."""

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from service.domain.documents.evidence.registered_sources import (
    MAX_BIBLIOGRAPHY_BYTES,
    registered_sources,
)
from service.domain.documents.semantic.editor import render_edit, render_initial
from service.presentation.deps import internal_auth

router = APIRouter(prefix="/document-editor")


class RenderEditRequest(BaseModel):
    files: dict[str, str] = Field(min_length=1, max_length=128)
    draft: dict
    authoring_version: int = Field(ge=0, le=1_000_000)
    draft_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    project: dict | None = None


class RegisteredSourcesRequest(BaseModel):
    bibliography: str = Field(max_length=MAX_BIBLIOGRAPHY_BYTES)


@router.post("/sources")
async def document_sources(
    payload: RegisteredSourcesRequest,
    authorization: str | None = Header(default=None),
) -> dict:
    internal_auth(authorization)
    try:
        return registered_sources(payload.bibliography)
    except ValueError:
        raise HTTPException(status_code=422, detail="bibliography_invalid") from None


@router.post("/render")
async def render_document_edit(
    payload: RenderEditRequest,
    authorization: str | None = Header(default=None),
) -> dict:
    internal_auth(authorization)
    try:
        if payload.authoring_version == 0 and payload.project is not None:
            return render_initial(payload.files, payload.draft, payload.project)
        if payload.draft_digest is None:
            raise ValueError("authoring_invalid")
        return render_edit(
            payload.files, payload.draft, payload.authoring_version, payload.draft_digest
        )
    except (ValueError, TypeError, KeyError) as exc:
        code = (
            str(exc) if str(exc) in {"source_changed", "citation_unknown"} else "authoring_invalid"
        )
        raise HTTPException(
            status_code=409 if code == "source_changed" else 422, detail=code
        ) from None
