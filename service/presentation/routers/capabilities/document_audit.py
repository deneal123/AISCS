"""Private backend seam for metered final-document visual audit."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, StrictBool

from service.domain.documents import audit_document_build
from service.domain.execution.context import PrivateRunResources, use_run_execution
from service.domain.tools.workspace.client import WorkspaceUnavailable
from service.domain.usage.ledger import UsageLedger
from service.infrastructure.document_audit.registry import AuditRegistryUnavailable
from service.presentation.deps import internal_auth
from service.presentation.routers.capabilities.audit_usage_stream import stream_audit_usage
from service.presentation.routers.capabilities.managed_document_audit import (
    execute_managed_audit,
    registry_for,
)
from service.shared.deadline import RunDeadline, use_deadline
from service.shared.provider_policy_context import use_snapshot

router = APIRouter(prefix="/document-audit")

# Backend's private RPC budget is 180 seconds. Reserve time to serialize usage
# and release the run's clients rather than continuing paid work after it leaves.
_AUDIT_BUDGET_SEC = 150.0


class DocumentAuditRequest(BaseModel):
    build_id: str = Field(min_length=8, max_length=128)
    workspace_ref: dict[str, Any]
    provider_policy: dict[str, Any] | None = None
    checkpoint_attempt_id: UUID | None = None
    fresh_attempt: StrictBool = False
    recovery_only: StrictBool = False


@router.post("")
async def audit_document(
    payload: DocumentAuditRequest,
    authorization: str | None = Header(default=None),
) -> Any:
    internal_auth(authorization)
    if payload.recovery_only:
        try:
            return await registry_for(payload).snapshot()
        except AuditRegistryUnavailable:
            return {"state": "unavailable"}
    if payload.checkpoint_attempt_id is not None:
        return StreamingResponse(
            stream_audit_usage(
                str(payload.checkpoint_attempt_id),
                lambda: execute_managed_audit(payload, _execute_audit),
            ),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-store"},
        )
    return await _execute_audit(payload)


@router.post("/v2", include_in_schema=False)
async def audit_document_v2(
    payload: DocumentAuditRequest,
    authorization: str | None = Header(default=None),
) -> Any:
    """Versioned private admission never falls through to legacy execution."""
    internal_auth(authorization)
    if payload.checkpoint_attempt_id is None or not (
        payload.recovery_only or payload.fresh_attempt
    ):
        return {"status": "protocol", "passed": False, "retryable": True}
    return await audit_document(payload, authorization=authorization)


async def _execute_audit(
    payload: DocumentAuditRequest,
    *,
    usage_checkpoint: Callable[[UsageLedger], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    resources = PrivateRunResources.from_request(workspace_ref=payload.workspace_ref)
    # The last chat's process-level policy is not the deferred job's policy.
    # Keep this private request scope isolated, including concurrent audits.
    with (
        use_snapshot(payload.provider_policy),
        use_deadline(RunDeadline.start(_AUDIT_BUDGET_SEC, reserve_sec=10)),
        use_run_execution(resources) as execution,
    ):
        try:
            if usage_checkpoint is not None:
                await usage_checkpoint(execution.usage)
                operation = audit_document_build(
                    dict(payload.workspace_ref),
                    payload.build_id,
                    execution=execution,
                    usage_checkpoint=usage_checkpoint,
                )
            else:
                operation = audit_document_build(
                    dict(payload.workspace_ref), payload.build_id, execution=execution
                )
            result = await asyncio.wait_for(
                operation,
                timeout=_AUDIT_BUDGET_SEC,
            )
        except TimeoutError:
            return {
                "status": "timeout",
                "passed": False,
                "retryable": True,
                "usage": execution.usage.project_since(0),
            }
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
