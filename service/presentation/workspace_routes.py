"""Workspace HTTP route handlers.

The module owns request parsing and HTTP error mapping.  Application services
own mutations; ``presentation.http`` only composes this router with FastAPI.
"""

import logging
import os

from application.coordination_guard import GuardFailure, require_mutation
from application.files import FileConflict, FileService, FileWriteFailed
from application.history import HistoryService
from application.importer import fetch
from application.imports import ImportService
from application.lifecycle import TooManyWorkspaces, WorkspaceNotFound, WorkspaceRegistry
from domain.contracts import DEFAULT_TTL_SEC, ERROR_CODES, GIT_AUTHOR
from domain.files import (
    BAD_PATTERN_MARKER,
    MAX_DOWNLOAD_BYTES,
    MAX_READ_BYTES,
    IsADirectory,
    UnsafePath,
    artifacts_command,
    download_command,
    git_diff_command,
    git_init_command,
    git_log_command,
    git_revert_command,
    grep_command,
    list_command,
    parse_artifacts,
    parse_download,
    parse_git_log,
    parse_read,
    read_command,
    reject_control_bytes,
    tree_command,
)
from domain.ownership import OwnershipError
from domain.policy import StaticPolicyLocked, policy_from_request
from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from drivers import DriverError, IsolationUnverified

logger = logging.getLogger("workspace-sidecar")
router = APIRouter()
DRIVER = os.environ.get("WORKSPACE_DRIVER", "docker")
SERVICE_KEY = str(os.environ.get("WORKSPACE_API_KEY", "") or "")
registry: WorkspaceRegistry | None = None

# Compatibility anchor for a direct-handler regression.  Runtime history uses
# the same allowlisted snapshot type, never a request-derived commit message.
IMPORT_MESSAGE = "import"


class CreateRequest(BaseModel):
    user_id: str
    ttl_sec: float = DEFAULT_TTL_SEC
    policy: dict | None = None


class ExecRequest(BaseModel):
    user_id: str
    token: str
    command: str = Field(min_length=1)
    coordination_capability: str = Field(default="", max_length=2048)
    coordination_fence: int | None = Field(default=None, ge=1)


class PolicyRequest(BaseModel):
    user_id: str
    token: str
    update: dict
    coordination_capability: str = Field(default="", max_length=2048)


class OwnerRequest(BaseModel):
    user_id: str
    token: str
    coordination_capability: str = Field(default="", max_length=2048)


class ImportRequest(BaseModel):
    user_id: str
    token: str
    files: list[dict]
    coordination_capability: str = Field(default="", max_length=2048)


class FileRequest(BaseModel):
    user_id: str
    token: str
    path: str = ""
    content: str | None = None
    pattern: str | None = None
    ref: str | None = None
    message: str | None = None
    expected_revision: str | None = None
    coordination_capability: str = Field(default="", max_length=2048)
    coordination_fence: int | None = Field(default=None, ge=1)


def error_response(code: str, detail: str, status: int) -> JSONResponse:
    assert code in ERROR_CODES, f"undeclared workspace error: {code!r}"
    return JSONResponse({"error": code, "detail": detail}, status_code=status)


def _error(code: str, detail: str, status: int) -> JSONResponse:
    """Compatibility alias used by direct route tests and collaboration routes."""
    return error_response(code, detail, status)


def _auth(authorization: str | None) -> None:
    if not SERVICE_KEY:
        raise RuntimeError("WORKSPACE_API_KEY is required for the workspace sidecar")
    if str(authorization or "") != f"Bearer {SERVICE_KEY}":
        raise StarletteHTTPException(status_code=401, detail="service authorization required")


def _resolve(workspace_id: str, user_id: str, token: str):
    if registry is None:
        raise WorkspaceNotFound("workspace registry is not ready")
    return registry.get(workspace_id, user_id, token)


def _owned(workspace_id: str, payload):
    try:
        return _resolve(workspace_id, payload.user_id, payload.token), None
    except OwnershipError as exc:
        return None, _error("forbidden", str(exc), 403)
    except WorkspaceNotFound as exc:
        return None, _error("not_found", str(exc), 404)


async def _coordination_guard(
    payload, mutation: str, *, path: str = "", workspace_id: str = ""
):
    try:
        return await require_mutation(payload, mutation, path=path, workspace_id=workspace_id)
    except GuardFailure as exc:
        return _error(exc.code, exc.detail, exc.status)


async def _run_file_op(item, command: str, *, stdin_payload: bytes | None = None):
    if registry is None:
        raise DriverError("workspace registry is not ready")
    return await registry.exec_raw(
        item, command, max_output_chars=MAX_READ_BYTES * 2, stdin_payload=stdin_payload
    )


async def _revision(item) -> str:
    return await HistoryService(_run_file_op).revision(item)


async def _snapshot(item, message: str) -> dict:
    return await HistoryService(_run_file_op).snapshot(item, message)


def _guard_denied(guarded):
    return guarded is not None and not hasattr(guarded, "allowed")


@router.post("/workspaces")
async def create_workspace(
    payload: CreateRequest, authorization: str | None = Header(default=None)
):
    _auth(authorization)
    if registry is None:
        return _error("workspace_unavailable", "workspace registry is not ready", 503)
    try:
        policy = policy_from_request(payload.policy)
        item, token = await registry.create(payload.user_id, policy, ttl_sec=payload.ttl_sec)
    except (TypeError, ValueError) as exc:
        return _error("invalid_request", str(exc), 422)
    except TooManyWorkspaces as exc:
        return _error("quota_exceeded", str(exc), 413)
    except IsolationUnverified as exc:
        logger.error("workspace isolation was not verified: %s", exc)
        return _error("isolation_unverified", str(exc), 500)
    except DriverError as exc:
        return _error("driver_failed", str(exc), 502)
    versioned = False
    try:
        result = await registry.exec_raw(
            item, git_init_command(item.policy.root, GIT_AUTHOR), max_output_chars=4096
        )
        versioned = "__OK__" in (result.stdout or "")
    except Exception:  # noqa: BLE001 - a workspace remains usable without git.
        logger.warning("workspace git initialization failed", exc_info=True)
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
    workspace_id: str, payload: ExecRequest, authorization: str | None = Header(default=None)
):
    _auth(authorization)
    item, failure = _owned(workspace_id, payload)
    if failure is not None:
        return failure
    try:
        command = reject_control_bytes(payload.command, "command")
    except UnsafePath as exc:
        return _error("invalid_request", str(exc), 422)
    guarded = await _coordination_guard(payload, "exec", workspace_id=workspace_id)
    if _guard_denied(guarded):
        return guarded
    try:
        async with registry.operation(item):
            result = await registry.exec(item, command)
    except DriverError as exc:
        return _error("driver_failed", str(exc), 502)
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
    workspace_id: str, payload: PolicyRequest, authorization: str | None = Header(default=None)
):
    _auth(authorization)
    item, failure = _owned(workspace_id, payload)
    if failure is not None:
        return failure
    guarded = await _coordination_guard(payload, "policy", workspace_id=workspace_id)
    if _guard_denied(guarded):
        return guarded
    try:
        policy = await registry.update_policy(item, payload.update)
    except StaticPolicyLocked as exc:
        return _error("static_policy_locked", str(exc), 409)
    except (TypeError, ValueError) as exc:
        return _error("invalid_request", str(exc), 422)
    return {"policy": policy.as_dict()}


@router.delete("/workspaces/{workspace_id}")
async def delete_workspace(
    workspace_id: str, payload: OwnerRequest, authorization: str | None = Header(default=None)
):
    _auth(authorization)
    try:
        _resolve(workspace_id, payload.user_id, payload.token)
        await registry.destroy(workspace_id)
    except OwnershipError as exc:
        return _error("forbidden", str(exc), 403)
    except WorkspaceNotFound as exc:
        return _error("not_found", str(exc), 404)
    return {"deleted": workspace_id}


def _parse_entries(stdout: str | None) -> list[dict]:
    entries: list[dict] = []
    for line in (stdout or "").splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            entries.append({"type": parts[0], "size": int(parts[1] or 0), "path": parts[2]})
    return entries


@router.post("/workspaces/{workspace_id}/files/list")
async def list_files(
    workspace_id: str, payload: FileRequest, authorization: str | None = Header(default=None)
):
    _auth(authorization)
    item, failure = _owned(workspace_id, payload)
    if failure is not None:
        return failure
    try:
        result = await _run_file_op(item, list_command(item.policy.root, payload.path))
    except UnsafePath as exc:
        return _error("forbidden", str(exc), 403)
    return {"entries": _parse_entries(result.stdout), "truncated": result.truncated}


@router.post("/workspaces/{workspace_id}/files/tree")
async def tree_files(
    workspace_id: str, payload: FileRequest, authorization: str | None = Header(default=None)
):
    _auth(authorization)
    item, failure = _owned(workspace_id, payload)
    if failure is not None:
        return failure
    try:
        result = await _run_file_op(item, tree_command(item.policy.root, payload.path))
    except UnsafePath as exc:
        return _error("forbidden", str(exc), 403)
    return {
        "entries": _parse_entries(result.stdout),
        "truncated": result.truncated,
        "root": item.policy.root,
        "revision": await _revision(item),
        "recovered": item.recovered,
    }


@router.post("/workspaces/{workspace_id}/files/read")
async def read_file(
    workspace_id: str, payload: FileRequest, authorization: str | None = Header(default=None)
):
    _auth(authorization)
    item, failure = _owned(workspace_id, payload)
    if failure is not None:
        return failure
    try:
        result = await _run_file_op(item, read_command(item.policy.root, payload.path))
        content, truncated = parse_read(result.stdout)
    except UnsafePath as exc:
        return _error("forbidden", str(exc), 403)
    except IsADirectory:
        return _error("invalid_request", "path is a directory", 422)
    except FileNotFoundError:
        return _error("not_found", "file not found", 404)
    except ValueError as exc:
        return _error("driver_failed", f"read failed: {exc}", 502)
    return {"path": payload.path, "content": content, "truncated": truncated}


@router.post("/workspaces/{workspace_id}/files/write")
async def write_file(
    workspace_id: str, payload: FileRequest, authorization: str | None = Header(default=None)
):
    _auth(authorization)
    item, failure = _owned(workspace_id, payload)
    if failure is not None:
        return failure
    if payload.coordination_capability and not payload.expected_revision:
        return _error("invalid_request", "expected_revision is required", 422)
    guarded = await _coordination_guard(
        payload, "write", path=payload.path, workspace_id=workspace_id
    )
    if _guard_denied(guarded):
        return guarded
    service = FileService(_run_file_op, _revision, _snapshot)
    try:
        if registry is not None:
            async with registry.operation(item):
                return await service.write(
                    item,
                    path=payload.path,
                    content=payload.content or "",
                    expected_revision=payload.expected_revision,
                    snapshot_user_edit=bool(payload.coordination_capability),
                )
        return await service.write(
            item,
            path=payload.path,
            content=payload.content or "",
            expected_revision=payload.expected_revision,
            snapshot_user_edit=bool(payload.coordination_capability),
        )
    except FileConflict:
        return _error("workspace_conflict", "workspace revision changed", 409)
    except FileWriteFailed:
        return _error("driver_failed", "write failed", 502)


@router.post("/workspaces/{workspace_id}/files/grep")
async def grep_files(
    workspace_id: str, payload: FileRequest, authorization: str | None = Header(default=None)
):
    _auth(authorization)
    item, failure = _owned(workspace_id, payload)
    if failure is not None:
        return failure
    if not (payload.pattern or "").strip():
        return _error("invalid_request", "a search pattern is required", 422)
    try:
        result = await _run_file_op(
            item, grep_command(item.policy.root, payload.pattern, payload.path)
        )
    except UnsafePath as exc:
        return _error("forbidden", str(exc), 403)
    lines = (result.stdout or "").splitlines()
    if lines and lines[0].strip() == BAD_PATTERN_MARKER:
        return _error("invalid_request", "invalid grep pattern", 422)
    return {"matches": lines, "truncated": result.truncated}


@router.post("/workspaces/{workspace_id}/import")
async def import_files(
    workspace_id: str, payload: ImportRequest, authorization: str | None = Header(default=None)
):
    _auth(authorization)
    item, failure = _owned(workspace_id, payload)
    if failure is not None:
        return failure
    guarded = await _coordination_guard(payload, "import", workspace_id=workspace_id)
    if _guard_denied(guarded):
        return guarded
    service = ImportService(_run_file_op, _snapshot, fetch)
    if registry is not None:
        async with registry.operation(item):
            return await service.execute(item, payload.files)
    return await service.execute(item, payload.files)


@router.post("/workspaces/{workspace_id}/snapshot")
async def snapshot_workspace(
    workspace_id: str, payload: FileRequest, authorization: str | None = Header(default=None)
):
    _auth(authorization)
    item, failure = _owned(workspace_id, payload)
    if failure is not None:
        return failure
    guarded = await _coordination_guard(payload, "snapshot", workspace_id=workspace_id)
    if _guard_denied(guarded):
        return guarded
    if registry is None:
        return await _snapshot(item, "agent_run")
    async with registry.operation(item):
        snapshot = await _snapshot(item, "agent_run")
        snapshot["revision"] = await _revision(item)
        return snapshot


@router.post("/workspaces/{workspace_id}/history")
async def history_workspace(
    workspace_id: str, payload: FileRequest, authorization: str | None = Header(default=None)
):
    _auth(authorization)
    item, failure = _owned(workspace_id, payload)
    if failure is not None:
        return failure
    result = await _run_file_op(item, git_log_command(item.policy.root))
    return {
        "entries": parse_git_log(result.stdout),
        "revision": await _revision(item),
        "recovered": item.recovered,
    }


@router.post("/workspaces/{workspace_id}/diff")
async def diff_workspace(
    workspace_id: str, payload: FileRequest, authorization: str | None = Header(default=None)
):
    _auth(authorization)
    item, failure = _owned(workspace_id, payload)
    if failure is not None:
        return failure
    try:
        result = await _run_file_op(
            item, git_diff_command(item.policy.root, payload.ref or "", payload.path or "")
        )
    except UnsafePath as exc:
        return _error("forbidden", str(exc), 403)
    text = result.stdout or ""
    if text.strip() in ("__NO_GIT__", "__NO_REPO__"):
        return {"diff": "", "available": False}
    return {"diff": text, "available": True, "truncated": result.truncated}


@router.post("/workspaces/{workspace_id}/revert")
async def revert_workspace(
    workspace_id: str, payload: FileRequest, authorization: str | None = Header(default=None)
):
    _auth(authorization)
    item, failure = _owned(workspace_id, payload)
    if failure is not None:
        return failure
    if not payload.expected_revision:
        return _error("invalid_request", "expected_revision is required", 422)
    guarded = await _coordination_guard(
        payload, "revert", path=payload.path or "", workspace_id=workspace_id
    )
    if _guard_denied(guarded):
        return guarded
    async with registry.operation(item):
        if await _revision(item) != payload.expected_revision:
            return _error("workspace_conflict", "workspace revision changed", 409)
        try:
            result = await _run_file_op(
                item, git_revert_command(item.policy.root, payload.ref or "", payload.path or "")
            )
        except UnsafePath as exc:
            return _error("invalid_request", str(exc), 422)
        snapshot = await _snapshot(item, "revert")
        return {
            "reverted": "__OK__" in (result.stdout or ""),
            "revision": await _revision(item),
            **snapshot,
        }


@router.post("/workspaces/{workspace_id}/artifacts")
async def list_artifacts(
    workspace_id: str, payload: OwnerRequest, authorization: str | None = Header(default=None)
):
    _auth(authorization)
    item, failure = _owned(workspace_id, payload)
    if failure is not None:
        return failure
    result = await _run_file_op(item, artifacts_command(item.policy.root))
    return {
        "artifacts": parse_artifacts(result.stdout, item.policy.root, item.imported),
        "truncated": result.truncated,
    }


@router.post("/workspaces/{workspace_id}/files/download")
async def download_file(
    workspace_id: str, payload: FileRequest, authorization: str | None = Header(default=None)
):
    _auth(authorization)
    item, failure = _owned(workspace_id, payload)
    if failure is not None:
        return failure
    try:
        command = download_command(item.policy.root, payload.path)
    except UnsafePath as exc:
        return _error("forbidden", str(exc), 403)
    try:
        result = await registry.exec_raw(item, command, max_output_chars=MAX_DOWNLOAD_BYTES * 2)
        content, truncated = parse_download(result.stdout)
    except FileNotFoundError:
        return _error("not_found", "file not found", 404)
    if truncated:
        return _error("request_too_large", "file is too large", 413)
    return {"path": payload.path, "content_b64": content}
