"""Agent-only collaboration endpoints for a workspace room."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse
from infrastructure.coordinator_client import (
    CoordinationCancelled,
    CoordinationConflict,
    CoordinationError,
    CoordinationForbidden,
    CoordinationPaused,
    list_issues,
    safe_boundary,
    update_issue,
)
from pydantic import BaseModel, Field


class CollaborationOwnerRequest(BaseModel):
    user_id: str
    token: str
    coordination_capability: str = Field(default="", max_length=2048)


class CollaborationIssueUpdateRequest(CollaborationOwnerRequest):
    message: str | None = None
    ref: str | None = None


@dataclass(frozen=True, slots=True)
class CollaborationDependencies:
    auth: Callable[[str | None], None]
    owned: Callable[[str, Any], tuple[Any | None, JSONResponse | None]]
    error: Callable[[str, str, int], JSONResponse]


def create_collaboration_router(deps: CollaborationDependencies) -> APIRouter:
    router = APIRouter(tags=["workspace-collaboration"])

    @router.post("/workspaces/{workspace_id}/collaboration/issues", response_model=None)
    async def issues(
        workspace_id: str,
        payload: CollaborationOwnerRequest,
        authorization: str | None = Header(default=None),
    ) -> Any:
        deps.auth(authorization)
        _item, failure = deps.owned(workspace_id, payload)
        if failure is not None:
            return failure
        capability = str(payload.coordination_capability or "")
        if not capability:
            return deps.error("forbidden", "workspace coordination capability is required", 403)
        try:
            return {"issues": await list_issues(capability)}
        except CoordinationForbidden:
            return deps.error("forbidden", "workspace coordination denied", 403)
        except CoordinationError:
            return deps.error("workspace_unavailable", "workspace coordination is unavailable", 503)

    @router.post("/workspaces/{workspace_id}/collaboration/boundary", response_model=None)
    async def boundary(
        workspace_id: str,
        payload: CollaborationOwnerRequest,
        authorization: str | None = Header(default=None),
    ) -> Any:
        deps.auth(authorization)
        _item, failure = deps.owned(workspace_id, payload)
        if failure is not None:
            return failure
        if not payload.coordination_capability:
            return {"state": "running"}
        try:
            return {"state": await safe_boundary(payload.coordination_capability)}
        except CoordinationPaused:
            return {"state": "paused"}
        except CoordinationCancelled:
            return {"state": "cancelled"}
        except CoordinationError:
            return deps.error("workspace_unavailable", "workspace coordination is unavailable", 503)

    @router.post("/workspaces/{workspace_id}/collaboration/issues/{issue_id}", response_model=None)
    async def issue_update(
        workspace_id: str,
        issue_id: str,
        payload: CollaborationIssueUpdateRequest,
        authorization: str | None = Header(default=None),
    ) -> Any:
        deps.auth(authorization)
        _item, failure = deps.owned(workspace_id, payload)
        if failure is not None:
            return failure
        capability = str(payload.coordination_capability or "")
        if not capability:
            return deps.error("forbidden", "workspace coordination capability is required", 403)
        try:
            return {
                "issue": await update_issue(
                    capability,
                    issue_id,
                    status=str(payload.message or "") or None,
                    revision=str(payload.ref or "") or None,
                )
            }
        except CoordinationConflict:
            return deps.error("workspace_conflict", "workspace issue changed", 409)
        except CoordinationForbidden:
            return deps.error("forbidden", "workspace coordination denied", 403)
        except CoordinationError:
            return deps.error("workspace_unavailable", "workspace coordination is unavailable", 503)

    return router
