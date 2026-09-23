"""Private backend seam for metered final-document visual audit."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from service.domain.documents import audit_document_build
from service.domain.run_context import PrivateRunResources, use_run_execution
from service.domain.tools.workspace_client import WorkspaceUnavailable
from service.presentation.deps import internal_auth

router = APIRouter(prefix="/document-audit")


class DocumentAuditRequest(BaseModel):
    build_id: str = Field(min_length=8, max_length=128)
    workspace_ref: dict[str, Any]


@router.post("")
async def audit_document(
    payload: DocumentAuditRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    internal_auth(authorization)
    resources = PrivateRunResources.from_request(workspace_ref=payload.workspace_ref)
    with use_run_execution(resources) as execution:
        try:
            result = await audit_document_build(
                dict(payload.workspace_ref), payload.build_id, execution=execution
            )
        except WorkspaceUnavailable as exc:
            return {
                "status": exc.reason_code,
                "passed": False,
                "retryable": exc.retryable,
                "usage": execution.usage.project_since(0),
            }
        return {
            "status": result.status,
            "passed": result.passed,
            "retryable": result.retryable,
            "diagnostic_count": len(result.diagnostics),
            "usage": execution.usage.project_since(0),
        }


__all__ = ["router"]
