"""Workspace create, execute, policy and destroy HTTP routes."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from application.lifecycle import TooManyWorkspaces, WorkspaceNotFound
from domain.contracts import GIT_AUTHOR
from domain.files import git_init_command, reject_control_bytes
from domain.ownership import OwnershipError
from domain.policy import StaticPolicyLocked, policy_from_request
from fastapi import APIRouter, Header

from drivers import DriverError, IsolationUnverified
from presentation.routes.contracts import CreateRequest, ExecRequest, OwnerRequest, PolicyRequest
from presentation.routes.dependencies import WorkspaceRouteDependencies

logger = logging.getLogger("workspace-sidecar")


@dataclass(frozen=True, slots=True)
class LifecycleHandlers:
    create_workspace: Any
    exec_in_workspace: Any
    update_policy: Any
    delete_workspace: Any


def create_lifecycle_router(
    deps: WorkspaceRouteDependencies,
) -> tuple[APIRouter, LifecycleHandlers]:
    router = APIRouter(tags=["workspace-lifecycle"])

    @router.post("/workspaces")
    async def create_workspace(
        payload: CreateRequest, authorization: str | None = Header(default=None)
    ):
        deps.auth(authorization)
        registry = deps.registry()
        if registry is None:
            return deps.error("workspace_unavailable", "workspace registry is not ready", 503)
        try:
            policy = policy_from_request(payload.policy)
            item, token = await registry.create(payload.user_id, policy, ttl_sec=payload.ttl_sec)
        except (TypeError, ValueError):
            return deps.error("invalid_request", "workspace policy is invalid", 422)
        except TooManyWorkspaces:
            return deps.error("quota_exceeded", "workspace capacity is exhausted", 413)
        except IsolationUnverified:
            logger.error("workspace isolation was not verified")
            return deps.error("isolation_unverified", "workspace isolation was not verified", 500)
        except DriverError:
            return deps.error("driver_failed", "workspace driver failed", 502)
        versioned = False
        try:
            result = await registry.exec_raw(
                item, git_init_command(item.policy.root, GIT_AUTHOR), max_output_chars=4096
            )
            versioned = "__OK__" in (result.stdout or "")
        except Exception:  # noqa: BLE001 - workspace remains usable without git history.
            logger.warning(
                "workspace git initialization failed",
                extra={"failure_code": "history_init"},
            )
        return {
            "versioned": versioned,
            "workspace_id": item.workspace_id,
            "token": token,
            "root": item.policy.root,
            "expires_at": item.expires_at,
            "policy": item.policy.as_dict(),
        }

    @router.post("/workspaces/{workspace_id}/exec")
    async def exec_in_workspace(
        workspace_id: str,
        payload: ExecRequest,
        authorization: str | None = Header(default=None),
    ):
        deps.auth(authorization)
        item, failure = deps.owned(workspace_id, payload)
        if failure is not None:
            return failure
        try:
            command = reject_control_bytes(payload.command, "command")
        except Exception:
            return deps.error("invalid_request", "command is invalid", 422)
        guarded = await deps.coordination_guard(payload, "exec", workspace_id=workspace_id)
        if deps.guard_denied(guarded):
            return guarded
        registry = deps.registry()
        if registry is None:
            return deps.error("workspace_unavailable", "workspace registry is not ready", 503)
        try:
            async with registry.operation(item):
                result = await registry.exec(item, command)
        except DriverError:
            return deps.error("driver_failed", "workspace driver failed", 502)
        return {
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "truncated": result.truncated,
            "duration_sec": result.duration_sec,
            "timed_out": result.timed_out,
        }

    @router.patch("/workspaces/{workspace_id}/policy")
    async def update_policy(
        workspace_id: str,
        payload: PolicyRequest,
        authorization: str | None = Header(default=None),
    ):
        deps.auth(authorization)
        item, failure = deps.owned(workspace_id, payload)
        if failure is not None:
            return failure
        guarded = await deps.coordination_guard(payload, "policy", workspace_id=workspace_id)
        if deps.guard_denied(guarded):
            return guarded
        registry = deps.registry()
        if registry is None:
            return deps.error("workspace_unavailable", "workspace registry is not ready", 503)
        try:
            policy = await registry.update_policy(item, payload.update)
        except StaticPolicyLocked:
            return deps.error("static_policy_locked", "static workspace policy is locked", 409)
        except (TypeError, ValueError):
            return deps.error("invalid_request", "workspace policy is invalid", 422)
        return {"policy": policy.as_dict()}

    @router.delete("/workspaces/{workspace_id}")
    async def delete_workspace(
        workspace_id: str,
        payload: OwnerRequest,
        authorization: str | None = Header(default=None),
    ):
        deps.auth(authorization)
        registry = deps.registry()
        if registry is None:
            return deps.error("workspace_unavailable", "workspace registry is not ready", 503)
        try:
            registry.get(workspace_id, payload.user_id, payload.token)
            await registry.destroy(workspace_id)
        except OwnershipError:
            return deps.error("forbidden", "workspace ownership mismatch", 403)
        except WorkspaceNotFound:
            return deps.error("workspace_not_found", "workspace not found", 404)
        return {"deleted": workspace_id}

    return router, LifecycleHandlers(
        create_workspace=create_workspace,
        exec_in_workspace=exec_in_workspace,
        update_policy=update_policy,
        delete_workspace=delete_workspace,
    )
