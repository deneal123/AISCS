"""Workspace Git snapshot, history, diff and revert HTTP routes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from domain.files import (
    UnsafePath,
    git_diff_command,
    git_log_command,
    git_revert_command,
    parse_git_log,
)
from fastapi import APIRouter, Header

from presentation.routes.contracts import FileRequest
from presentation.routes.dependencies import WorkspaceRouteDependencies


@dataclass(frozen=True, slots=True)
class HistoryHandlers:
    snapshot_workspace: Any
    history_workspace: Any
    diff_workspace: Any
    revert_workspace: Any


def create_history_router(
    deps: WorkspaceRouteDependencies,
) -> tuple[APIRouter, HistoryHandlers]:
    router = APIRouter(tags=["workspace-history"])

    @router.post("/workspaces/{workspace_id}/snapshot")
    async def snapshot_workspace(
        workspace_id: str,
        payload: FileRequest,
        authorization: str | None = Header(default=None),
    ):
        deps.auth(authorization)
        item, failure = deps.owned(workspace_id, payload)
        if failure is not None:
            return failure
        guarded = await deps.coordination_guard(payload, "snapshot", workspace_id=workspace_id)
        if deps.guard_denied(guarded):
            return guarded
        registry = deps.registry()
        if registry is None:
            return await deps.snapshot(item, "agent_run")
        async with registry.operation(item):
            snapshot = await deps.snapshot(item, "agent_run")
            snapshot["revision"] = await deps.revision(item)
            return snapshot

    @router.post("/workspaces/{workspace_id}/history")
    async def history_workspace(
        workspace_id: str,
        payload: FileRequest,
        authorization: str | None = Header(default=None),
    ):
        deps.auth(authorization)
        item, failure = deps.owned(workspace_id, payload)
        if failure is not None:
            return failure
        result = await deps.run_file_op(item, git_log_command(item.policy.root))
        return {
            "entries": parse_git_log(result.stdout),
            "revision": await deps.revision(item),
            "recovered": item.recovered,
        }

    @router.post("/workspaces/{workspace_id}/diff")
    async def diff_workspace(
        workspace_id: str,
        payload: FileRequest,
        authorization: str | None = Header(default=None),
    ):
        deps.auth(authorization)
        item, failure = deps.owned(workspace_id, payload)
        if failure is not None:
            return failure
        try:
            result = await deps.run_file_op(
                item,
                git_diff_command(item.policy.root, payload.ref or "", payload.path or ""),
            )
        except UnsafePath:
            return deps.error("forbidden", "workspace path is invalid", 403)
        text = result.stdout or ""
        if text.strip() in ("__NO_GIT__", "__NO_REPO__"):
            return {"diff": "", "available": False}
        return {"diff": text, "available": True, "truncated": result.truncated}

    @router.post("/workspaces/{workspace_id}/revert")
    async def revert_workspace(
        workspace_id: str,
        payload: FileRequest,
        authorization: str | None = Header(default=None),
    ):
        deps.auth(authorization)
        item, failure = deps.owned(workspace_id, payload)
        if failure is not None:
            return failure
        if not payload.expected_revision:
            return deps.error("invalid_request", "expected_revision is required", 422)
        guarded = await deps.coordination_guard(
            payload,
            "revert",
            path=payload.path or "",
            workspace_id=workspace_id,
        )
        if deps.guard_denied(guarded):
            return guarded
        registry = deps.registry()
        if registry is None:
            return deps.error("workspace_unavailable", "workspace registry is not ready", 503)
        async with registry.operation(item):
            if await deps.revision(item) != payload.expected_revision:
                return deps.error("workspace_conflict", "workspace revision changed", 409)
            try:
                result = await deps.run_file_op(
                    item,
                    git_revert_command(
                        item.policy.root,
                        payload.ref or "",
                        payload.path or "",
                    ),
                )
            except UnsafePath:
                return deps.error("invalid_request", "workspace path is invalid", 422)
            snapshot = await deps.snapshot(item, "revert")
            return {
                "reverted": "__OK__" in (result.stdout or ""),
                "revision": await deps.revision(item),
                **snapshot,
            }

    return router, HistoryHandlers(
        snapshot_workspace=snapshot_workspace,
        history_workspace=history_workspace,
        diff_workspace=diff_workspace,
        revert_workspace=revert_workspace,
    )
