"""Authenticated internal coordinator used by the isolated workspace sidecar.

This router has no user authentication path.  Every request is body-bound HMAC
authenticated before decoding and accepts only opaque capabilities and bounded
operation codes.  It deliberately never transports file content, commands,
URLs, prompts, or tool results.
"""

from __future__ import annotations

import hmac
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from service.composition.state import get_optional_redis_client
from service.services.chat.application.workspace_collaboration import (
    SAFE_MUTATIONS,
    CollaborationCancelled,
    CollaborationConflict,
    CollaborationError,
    CollaborationForbidden,
    CollaborationPaused,
    WorkspaceCollaborationStore,
    verify_capability,
    verify_internal_request,
)

router = APIRouter(prefix="/internal/workspace-coordination", tags=["internal"])


class PreflightPayload(BaseModel):
    capability: str = Field(..., min_length=16, max_length=2048)
    mutation: str = Field(..., max_length=24)
    path: str = Field(default="", max_length=1024)
    workspace_id: str = Field(default="", max_length=128)
    fence: int | None = Field(default=None, ge=1)


class BoundaryPayload(BaseModel):
    capability: str = Field(..., min_length=16, max_length=2048)


class IssuesPayload(BaseModel):
    capability: str = Field(..., min_length=16, max_length=2048)


class IssueActionPayload(IssuesPayload):
    issue_id: str = Field(..., min_length=4, max_length=64)
    status: str | None = Field(default=None, pattern="^(open|resolved|stale)$")
    revision: str | None = Field(default=None, max_length=64)
    start_line: int | None = Field(default=None, ge=1, le=1_000_000)
    end_line: int | None = Field(default=None, ge=1, le=1_000_000)


def _error(exc: CollaborationError) -> HTTPException:
    if isinstance(exc, CollaborationConflict):
        return HTTPException(status_code=409, detail={"code": exc.code})
    if isinstance(exc, CollaborationPaused):
        return HTTPException(status_code=423, detail={"code": exc.code})
    if isinstance(exc, CollaborationCancelled):
        return HTTPException(status_code=409, detail={"code": exc.code})
    if isinstance(exc, CollaborationForbidden):
        return HTTPException(status_code=403, detail={"code": exc.code})
    return HTTPException(status_code=503, detail={"code": "workspace_unavailable"})


def _capability_matches_route(capability, workspace_id: str) -> bool:
    """Reject a valid capability replayed against another workspace route."""
    return bool(workspace_id) and hmac.compare_digest(capability.workspace_id, workspace_id)


async def _authenticated_payload(
    request: Request,
    timestamp: str | None,
    signature: str | None,
) -> bytes:
    body = await request.body()
    try:
        verify_internal_request(
            request.method, request.url.path, body, timestamp or "", signature or ""
        )
    except CollaborationError as exc:
        raise _error(exc) from exc
    return body


@router.post("/preflight")
async def preflight(
    request: Request,
    payload: PreflightPayload,
    timestamp: Annotated[str | None, Header(alias="X-Workspace-Timestamp")] = None,
    signature: Annotated[str | None, Header(alias="X-Workspace-Signature")] = None,
    redis: Any = Depends(get_optional_redis_client),  # noqa: B008
):
    await _authenticated_payload(request, timestamp, signature)
    try:
        capability = verify_capability(payload.capability)
        if not _capability_matches_route(capability, payload.workspace_id):
            raise CollaborationForbidden("workspace capability does not match the route")
        if payload.mutation not in SAFE_MUTATIONS:
            raise CollaborationForbidden("unsupported workspace mutation")
        store = WorkspaceCollaborationStore(
            redis, workspace_id=capability.workspace_id, expires_at=capability.expires_at
        )
        return await store.preflight(
            capability, mutation=payload.mutation, path=payload.path, fence=payload.fence
        )
    except CollaborationError as exc:
        raise _error(exc) from exc


@router.post("/boundary")
async def safe_boundary(
    request: Request,
    payload: BoundaryPayload,
    timestamp: Annotated[str | None, Header(alias="X-Workspace-Timestamp")] = None,
    signature: Annotated[str | None, Header(alias="X-Workspace-Signature")] = None,
    redis: Any = Depends(get_optional_redis_client),  # noqa: B008
):
    await _authenticated_payload(request, timestamp, signature)
    try:
        capability = verify_capability(payload.capability, required_role="agent")
        store = WorkspaceCollaborationStore(
            redis, workspace_id=capability.workspace_id, expires_at=capability.expires_at
        )
        return {"state": await store.agent_safe_boundary(capability)}
    except CollaborationError as exc:
        raise _error(exc) from exc


@router.post("/issues")
async def list_agent_issues(
    request: Request,
    payload: IssuesPayload,
    timestamp: Annotated[str | None, Header(alias="X-Workspace-Timestamp")] = None,
    signature: Annotated[str | None, Header(alias="X-Workspace-Signature")] = None,
    redis: Any = Depends(get_optional_redis_client),  # noqa: B008
):
    await _authenticated_payload(request, timestamp, signature)
    try:
        capability = verify_capability(payload.capability, required_role="agent")
        store = WorkspaceCollaborationStore(
            redis, workspace_id=capability.workspace_id, expires_at=capability.expires_at
        )
        return {"issues": await store.list_issues(include_resolved=False)}
    except CollaborationError as exc:
        raise _error(exc) from exc


@router.post("/issues/update")
async def update_agent_issue(
    request: Request,
    payload: IssueActionPayload,
    timestamp: Annotated[str | None, Header(alias="X-Workspace-Timestamp")] = None,
    signature: Annotated[str | None, Header(alias="X-Workspace-Signature")] = None,
    redis: Any = Depends(get_optional_redis_client),  # noqa: B008
):
    await _authenticated_payload(request, timestamp, signature)
    try:
        capability = verify_capability(payload.capability, required_role="agent")
        store = WorkspaceCollaborationStore(
            redis, workspace_id=capability.workspace_id, expires_at=capability.expires_at
        )
        issue = await store.update_issue(
            capability,
            payload.issue_id,
            status=payload.status,
            revision=payload.revision,
            start_line=payload.start_line,
            end_line=payload.end_line,
        )
        return {"issue": issue}
    except CollaborationError as exc:
        raise _error(exc) from exc
