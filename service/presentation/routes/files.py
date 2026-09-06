"""Workspace tree, file and artifact HTTP routes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from application.files import FileConflict, FileService, FileWriteFailed
from application.view import WorkspaceViewService
from domain.files import (
    BAD_PATTERN_MARKER,
    MAX_DOWNLOAD_BYTES,
    IsADirectory,
    UnsafePath,
    artifacts_command,
    download_command,
    grep_command,
    list_command,
    parse_artifacts,
    parse_download,
    parse_read,
    read_command,
    tree_command,
)
from fastapi import APIRouter, Header

from presentation.routes.contracts import FileRequest, OwnerRequest
from presentation.routes.dependencies import WorkspaceRouteDependencies


@dataclass(frozen=True, slots=True)
class FileHandlers:
    list_files: Any
    tree_files: Any
    workspace_view: Any
    read_file: Any
    write_file: Any
    grep_files: Any
    list_artifacts: Any
    download_file: Any


def _parse_entries(stdout: str | None) -> list[dict]:
    entries: list[dict] = []
    for line in (stdout or "").splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            entries.append({"type": parts[0], "size": int(parts[1] or 0), "path": parts[2]})
    return entries


def create_files_router(deps: WorkspaceRouteDependencies) -> tuple[APIRouter, FileHandlers]:
    router = APIRouter(tags=["workspace-files"])

    @router.post("/workspaces/{workspace_id}/files/list")
    async def list_files(
        workspace_id: str,
        payload: FileRequest,
        authorization: str | None = Header(default=None),
    ):
        deps.auth(authorization)
        item, failure = deps.owned(workspace_id, payload)
        if failure is not None:
            return failure
        try:
            result = await deps.run_file_op(item, list_command(item.policy.root, payload.path))
        except UnsafePath:
            return deps.error("forbidden", "workspace path is invalid", 403)
        return {"entries": _parse_entries(result.stdout), "truncated": result.truncated}

    @router.post("/workspaces/{workspace_id}/files/tree")
    async def tree_files(
        workspace_id: str,
        payload: FileRequest,
        authorization: str | None = Header(default=None),
    ):
        deps.auth(authorization)
        item, failure = deps.owned(workspace_id, payload)
        if failure is not None:
            return failure
        try:
            result = await deps.run_file_op(item, tree_command(item.policy.root, payload.path))
        except UnsafePath:
            return deps.error("forbidden", "workspace path is invalid", 403)
        return {
            "entries": _parse_entries(result.stdout),
            "truncated": result.truncated,
            "root": item.policy.root,
            "revision": await deps.revision(item),
            "recovered": item.recovered,
        }

    @router.post("/workspaces/{workspace_id}/view")
    async def workspace_view(
        workspace_id: str,
        payload: FileRequest,
        authorization: str | None = Header(default=None),
    ):
        """Return tree, history and revision from one operation boundary."""
        deps.auth(authorization)
        item, failure = deps.owned(workspace_id, payload)
        if failure is not None:
            return failure
        service = WorkspaceViewService(deps.run_file_op, deps.revision)
        try:
            registry = deps.registry()
            if registry is None:
                return await service.snapshot(item, payload.path)
            async with registry.operation(item):
                return await service.snapshot(item, payload.path)
        except UnsafePath:
            return deps.error("forbidden", "workspace path is invalid", 403)

    @router.post("/workspaces/{workspace_id}/files/read")
    async def read_file(
        workspace_id: str,
        payload: FileRequest,
        authorization: str | None = Header(default=None),
    ):
        deps.auth(authorization)
        item, failure = deps.owned(workspace_id, payload)
        if failure is not None:
            return failure
        try:
            registry = deps.registry()
            if registry is None:
                result = await deps.run_file_op(item, read_command(item.policy.root, payload.path))
                content, truncated = parse_read(result.stdout)
                revision = await deps.revision(item)
            else:
                async with registry.operation(item):
                    result = await deps.run_file_op(
                        item, read_command(item.policy.root, payload.path)
                    )
                    content, truncated = parse_read(result.stdout)
                    revision = await deps.revision(item)
        except UnsafePath:
            return deps.error("forbidden", "workspace path is invalid", 403)
        except IsADirectory:
            return deps.error("invalid_request", "path is a directory", 422)
        except FileNotFoundError:
            return deps.error("not_found", "file not found", 404)
        except ValueError:
            return deps.error("driver_failed", "workspace read failed", 502)
        return {
            "path": payload.path,
            "content": content,
            "truncated": truncated,
            "revision": revision,
        }

    @router.post("/workspaces/{workspace_id}/files/write")
    async def write_file(
        workspace_id: str,
        payload: FileRequest,
        authorization: str | None = Header(default=None),
    ):
        deps.auth(authorization)
        item, failure = deps.owned(workspace_id, payload)
        if failure is not None:
            return failure
        if payload.coordination_capability and not payload.expected_revision:
            return deps.error("invalid_request", "expected_revision is required", 422)
        guarded = await deps.coordination_guard(
            payload, "write", path=payload.path, workspace_id=workspace_id
        )
        if deps.guard_denied(guarded):
            return guarded
        service = FileService(deps.run_file_op, deps.revision, deps.snapshot)
        try:
            registry = deps.registry()
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
            return deps.error("workspace_conflict", "workspace revision changed", 409)
        except FileWriteFailed:
            return deps.error("driver_failed", "workspace write failed", 502)

    @router.post("/workspaces/{workspace_id}/files/grep")
    async def grep_files(
        workspace_id: str,
        payload: FileRequest,
        authorization: str | None = Header(default=None),
    ):
        deps.auth(authorization)
        item, failure = deps.owned(workspace_id, payload)
        if failure is not None:
            return failure
        if not (payload.pattern or "").strip():
            return deps.error("invalid_request", "a search pattern is required", 422)
        try:
            result = await deps.run_file_op(
                item, grep_command(item.policy.root, payload.pattern, payload.path)
            )
        except UnsafePath:
            return deps.error("forbidden", "workspace path is invalid", 403)
        lines = (result.stdout or "").splitlines()
        if lines and lines[0].strip() == BAD_PATTERN_MARKER:
            return deps.error("invalid_request", "invalid grep pattern", 422)
        return {"matches": lines, "truncated": result.truncated}

    @router.post("/workspaces/{workspace_id}/artifacts")
    async def list_artifacts(
        workspace_id: str,
        payload: OwnerRequest,
        authorization: str | None = Header(default=None),
    ):
        deps.auth(authorization)
        item, failure = deps.owned(workspace_id, payload)
        if failure is not None:
            return failure
        result = await deps.run_file_op(item, artifacts_command(item.policy.root))
        return {
            "artifacts": parse_artifacts(result.stdout, item.policy.root, item.imported),
            "truncated": result.truncated,
        }

    @router.post("/workspaces/{workspace_id}/files/download")
    async def download_file(
        workspace_id: str,
        payload: FileRequest,
        authorization: str | None = Header(default=None),
    ):
        deps.auth(authorization)
        item, failure = deps.owned(workspace_id, payload)
        if failure is not None:
            return failure
        try:
            command = download_command(item.policy.root, payload.path)
        except UnsafePath:
            return deps.error("forbidden", "workspace path is invalid", 403)
        registry = deps.registry()
        if registry is None:
            return deps.error("workspace_unavailable", "workspace registry is not ready", 503)
        try:
            result = await registry.exec_raw(item, command, max_output_chars=MAX_DOWNLOAD_BYTES * 2)
            content, truncated = parse_download(result.stdout)
        except FileNotFoundError:
            return deps.error("not_found", "file not found", 404)
        if truncated:
            return deps.error("request_too_large", "file is too large", 413)
        return {"path": payload.path, "content_b64": content}

    return router, FileHandlers(
        list_files=list_files,
        tree_files=tree_files,
        workspace_view=workspace_view,
        read_file=read_file,
        write_file=write_file,
        grep_files=grep_files,
        list_artifacts=list_artifacts,
        download_file=download_file,
    )
