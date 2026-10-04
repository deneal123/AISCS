#!/usr/bin/env python3
"""HTTP composition for the workspace sidecar.

Route handlers live in :mod:`presentation.workspace_routes`; this module is
deliberately limited to FastAPI lifecycle, transport-wide error shape and
dependency wiring.
"""

import asyncio
import logging
import os

import uvicorn
from application.lifecycle import WorkspaceRegistry
from domain.contracts import (
    CREATE_RESPONSE_FIELDS,
    ERROR_CODES,
    EXEC_RESPONSE_FIELDS,
    MAX_BODY_BYTES,
    SERVICE_NAME,
    SERVICE_VERSION,
)
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from drivers import build_driver, driver_names
from presentation import workspace_routes
from presentation.collaboration_routes import CollaborationDependencies, create_collaboration_router

PORT = int(os.environ.get("PORT", "8080"))
logger = logging.getLogger("workspace-sidecar")

app = FastAPI(
    title="GPTHub workspace sidecar", version=SERVICE_VERSION, docs_url=None, redoc_url=None
)


@app.exception_handler(StarletteHTTPException)
async def http_error(_request: Request, exc: StarletteHTTPException):
    code = {401: "unauthorized", 403: "forbidden", 404: "not_found", 413: "request_too_large"}.get(
        exc.status_code, "internal"
    )
    return workspace_routes.error_response(code, str(exc.detail), exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, exc: RequestValidationError):
    return workspace_routes.error_response("invalid_request", str(exc.errors()[:3]), 422)


@app.middleware("http")
async def limit_body(request: Request, call_next):
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        return workspace_routes.error_response(
            "request_too_large", f"request body exceeds {MAX_BODY_BYTES} bytes", 413
        )
    return await call_next(request)


app.include_router(workspace_routes.router)
app.include_router(
    create_collaboration_router(
        CollaborationDependencies(
            auth=workspace_routes._auth,
            owned=workspace_routes._owned,
            error=workspace_routes.error_response,
        )
    )
)


@app.get("/health")
async def health():
    from domain.documents.runtime_digest import DOCUMENT_RUNTIME_DIGEST, DOCUMENT_RUNTIME_VERSION

    registry = workspace_routes.registry
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "driver": registry.driver_name if registry else workspace_routes.DRIVER,
        "drivers_available": driver_names(),
        "workspaces": registry.count() if registry else 0,
        "workspace_lifecycle": registry.health() if registry else {},
        "documents": {
            "status": "ok",
            "runtime_version": DOCUMENT_RUNTIME_VERSION,
            "runtime_digest": DOCUMENT_RUNTIME_DIGEST,
            "profile_version": workspace_routes.document_catalog.version,
            "profile_digest": workspace_routes.document_catalog.digest[:16],
            "profiles": len(workspace_routes.document_catalog.profiles),
            **workspace_routes.document_builds.health(),
            "source_publications": workspace_routes.document_source_recovery.health(),
        },
        "contract": {
            "create_response_fields": sorted(CREATE_RESPONSE_FIELDS),
            "exec_response_fields": sorted(EXEC_RESPONSE_FIELDS),
            "error_codes": sorted(ERROR_CODES),
        },
    }


@app.on_event("startup")
async def startup() -> None:
    workspace_routes.registry = WorkspaceRegistry(build_driver(workspace_routes.DRIVER))
    await workspace_routes.registry.reconcile()
    await workspace_routes.document_source_recovery.reconcile_registry(workspace_routes.registry)
    await workspace_routes.document_builds.reconcile_registry(workspace_routes.registry)
    asyncio.create_task(workspace_routes.registry.reap_forever())
    asyncio.create_task(
        workspace_routes.document_source_recovery.reconcile_forever(workspace_routes.registry)
    )
    asyncio.create_task(
        workspace_routes.document_builds.reconcile_forever(workspace_routes.registry)
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=PORT)
