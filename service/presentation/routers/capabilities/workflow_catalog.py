"""Private projection endpoint for backend's autonomous workflow catalog outbox."""

from __future__ import annotations

from fastapi import APIRouter, Header

from service.domain.workflows import catalog
from service.presentation.deps import internal_auth
from service.presentation.errors import error
from service.schemas.workflow_catalog import (
    WorkflowCatalogDeleteRequest,
    WorkflowCatalogUpsertRequest,
)

router = APIRouter(prefix="/workflow-catalog")


@router.post("/upsert")
async def upsert(
    payload: WorkflowCatalogUpsertRequest, authorization: str | None = Header(default=None)
) -> dict:
    internal_auth(authorization)
    if not catalog.enabled():
        return error("workflow_catalog_unavailable", "workflow catalog is unavailable", 503)
    projected = await catalog.upsert(**payload.model_dump())
    if not projected:
        return error("workflow_catalog_unavailable", "workflow catalog projection failed", 503)
    return {"indexed": True}


@router.post("/delete")
async def delete(
    payload: WorkflowCatalogDeleteRequest, authorization: str | None = Header(default=None)
) -> dict:
    internal_auth(authorization)
    if not catalog.enabled():
        return error("workflow_catalog_unavailable", "workflow catalog is unavailable", 503)
    deleted = await catalog.delete(payload.point_id)
    if not deleted:
        return error("workflow_catalog_unavailable", "workflow catalog projection failed", 503)
    return {"deleted": True}
