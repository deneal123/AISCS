"""Protected IDE reads cannot allocate, execute repo code, or create Git history."""

from __future__ import annotations

import asyncio

from application.ide_reads import IdeReadFailure, IdeReadService
from fastapi import APIRouter, Header
from pydantic import BaseModel, ConfigDict, Field

from presentation.routes.dependencies import WorkspaceRouteDependencies


class IdeReadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str
    token: str
    path: str = Field(default="", max_length=1024)


def create_ide_read_router(deps: WorkspaceRouteDependencies) -> APIRouter:
    router = APIRouter(tags=["ide-reads"])

    async def read(workspace_id, payload, authorization, operation):
        deps.auth(authorization)
        item, failure = deps.owned(workspace_id, payload)
        if failure is not None:
            return failure
        registry = deps.registry()
        if registry is None:
            return deps.error("workspace_unavailable", "workspace registry is not ready", 503)

        async def run(item, command, *, stdin_payload):
            return await registry.exec_raw(
                item, command, stdin_payload=stdin_payload, max_output_chars=6 * 256 * 1024 + 65536
            )

        try:
            async with asyncio.timeout(10), registry.operation(item):
                return await IdeReadService(run).read(item, operation=operation, path=payload.path)
        except IdeReadFailure as error:
            status = {
                "ide_path_forbidden": 403,
                "ide_file_missing": 404,
                "ide_file_changed": 409,
                "ide_file_unsupported": 422,
                "invalid_request": 422,
            }.get(error.code, 503)
            return deps.error(error.code, "repository read is unavailable", status)
        except TimeoutError:
            return deps.error("ide_read_unavailable", "repository read timed out", 503)

    @router.post("/workspaces/{workspace_id}/ide/tree")
    async def tree(
        workspace_id: str, payload: IdeReadRequest, authorization: str | None = Header(default=None)
    ):
        return await read(workspace_id, payload, authorization, "tree")

    @router.post("/workspaces/{workspace_id}/ide/file")
    async def file(
        workspace_id: str, payload: IdeReadRequest, authorization: str | None = Header(default=None)
    ):
        return await read(workspace_id, payload, authorization, "file")

    return router
