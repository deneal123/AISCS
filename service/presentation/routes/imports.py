"""Atomic workspace import HTTP route."""

from __future__ import annotations

from application.files import FileConflict
from application.imports import ImportService
from fastapi import APIRouter, Header

from presentation.routes.contracts import ImportRequest
from presentation.routes.dependencies import WorkspaceRouteDependencies


def create_import_router(deps: WorkspaceRouteDependencies):
    router = APIRouter(tags=["workspace-import"])

    @router.post("/workspaces/{workspace_id}/import")
    async def import_files(
        workspace_id: str,
        payload: ImportRequest,
        authorization: str | None = Header(default=None),
    ):
        deps.auth(authorization)
        item, failure = deps.owned(workspace_id, payload)
        if failure is not None:
            return failure
        if payload.coordination_capability and not payload.expected_revision:
            return deps.error("invalid_request", "expected_revision is required", 422)
        guarded = await deps.coordination_guard(payload, "import", workspace_id=workspace_id)
        if deps.guard_denied(guarded):
            return guarded
        service = ImportService(
            deps.run_file_op,
            deps.snapshot,
            deps.revision,
            deps.fetch,
        )
        try:
            registry = deps.registry()
            if registry is not None:
                async with registry.operation(item):
                    result = await service.execute(
                        item,
                        payload.files,
                        expected_revision=payload.expected_revision,
                    )
            else:
                result = await service.execute(
                    item,
                    payload.files,
                    expected_revision=payload.expected_revision,
                )
        except FileConflict:
            return deps.error("workspace_conflict", "workspace revision changed", 409)
        result["revision"] = await deps.revision(item)
        return result

    return router, import_files
