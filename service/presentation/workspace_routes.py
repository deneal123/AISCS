"""Workspace HTTP route handlers.

The module owns request parsing and HTTP error mapping.  Application services
own mutations; ``presentation.http`` only composes this router with FastAPI.
"""

import logging
import os

from application.coordination_guard import GuardFailure, require_mutation
from application.documents import (
    DocumentBuildManager,
    DocumentCheckpointService,
    DocumentProjectService,
    DocumentSourceService,
    DocumentVendorOverlayService,
    DocumentVendorProfileService,
)
from application.documents.source_recovery import SourcePublicationRecovery
from application.history import HistoryService
from application.importer import fetch
from application.lifecycle import WorkspaceNotFound, WorkspaceRegistry
from domain.contracts import ERROR_CODES
from domain.documents import load_profile_catalog
from domain.files import MAX_READ_BYTES
from domain.ownership import OwnershipError
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from infrastructure.document_compiler import DockerDocumentCompiler
from starlette.exceptions import HTTPException as StarletteHTTPException

from drivers import DriverError
from presentation.routes.contracts import CreateRequest as CreateRequest
from presentation.routes.contracts import ExecRequest as ExecRequest
from presentation.routes.contracts import FileRequest as FileRequest
from presentation.routes.contracts import ImportRequest as ImportRequest
from presentation.routes.contracts import OwnerRequest as OwnerRequest
from presentation.routes.contracts import PolicyRequest as PolicyRequest
from presentation.routes.dependencies import WorkspaceRouteDependencies
from presentation.routes.documents import DocumentRouteDependencies, create_documents_router
from presentation.routes.files import create_files_router
from presentation.routes.history import create_history_router
from presentation.routes.ide_capture import create_ide_capture_router
from presentation.routes.ide_commands import create_ide_command_router
from presentation.routes.ide_git import create_ide_git_router
from presentation.routes.ide_reads import create_ide_read_router
from presentation.routes.ide_restore import create_ide_restore_router
from presentation.routes.ide_writes import create_ide_write_router
from presentation.routes.imports import create_import_router
from presentation.routes.lifecycle import create_lifecycle_router

logger = logging.getLogger("workspace-sidecar")
router = APIRouter()
DRIVER = os.environ.get("WORKSPACE_DRIVER", "docker")
SERVICE_KEY = str(os.environ.get("WORKSPACE_API_KEY", "") or "")
registry: WorkspaceRegistry | None = None

# Compatibility anchor for a direct-handler regression.  Runtime history uses
# the same allowlisted snapshot type, never a request-derived commit message.
IMPORT_MESSAGE = "import"


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
    except OwnershipError:
        return None, _error("forbidden", "workspace ownership mismatch", 403)
    except WorkspaceNotFound:
        return None, _error("workspace_not_found", "workspace not found", 404)


async def _coordination_guard(payload, mutation: str, *, path: str = "", workspace_id: str = ""):
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


async def _route_coordination_guard(*args, **kwargs):
    return await _coordination_guard(*args, **kwargs)


async def _route_run_file_op(*args, **kwargs):
    return await _run_file_op(*args, **kwargs)


async def _route_revision(item):
    return await _revision(item)


async def _route_snapshot(item, message: str):
    return await _snapshot(item, message)


async def _route_fetch(*args, **kwargs):
    return await fetch(*args, **kwargs)


_route_dependencies = WorkspaceRouteDependencies(
    auth=lambda authorization: _auth(authorization),
    error=lambda code, detail, status: _error(code, detail, status),
    registry=lambda: registry,
    owned=lambda workspace_id, payload: _owned(workspace_id, payload),
    coordination_guard=_route_coordination_guard,
    guard_denied=lambda guarded: _guard_denied(guarded),
    run_file_op=_route_run_file_op,
    revision=_route_revision,
    snapshot=_route_snapshot,
    fetch=_route_fetch,
)
_lifecycle_router, _lifecycle_handlers = create_lifecycle_router(_route_dependencies)
router.include_router(_lifecycle_router)
create_workspace = _lifecycle_handlers.create_workspace
exec_in_workspace = _lifecycle_handlers.exec_in_workspace
update_policy = _lifecycle_handlers.update_policy
delete_workspace = _lifecycle_handlers.delete_workspace
_files_router, _file_handlers = create_files_router(_route_dependencies)
router.include_router(_files_router)
router.include_router(create_ide_read_router(_route_dependencies))
router.include_router(create_ide_write_router(_route_dependencies))
router.include_router(create_ide_git_router(_route_dependencies))
router.include_router(create_ide_capture_router(_route_dependencies))
router.include_router(create_ide_command_router(_route_dependencies))
router.include_router(create_ide_restore_router(_route_dependencies))
list_files = _file_handlers.list_files
tree_files = _file_handlers.tree_files
workspace_view = _file_handlers.workspace_view
read_file = _file_handlers.read_file
write_file = _file_handlers.write_file
grep_files = _file_handlers.grep_files
list_artifacts = _file_handlers.list_artifacts
download_file = _file_handlers.download_file
_import_router, import_files = create_import_router(_route_dependencies)
router.include_router(_import_router)
_history_router, _history_handlers = create_history_router(_route_dependencies)
router.include_router(_history_router)
snapshot_workspace = _history_handlers.snapshot_workspace
history_workspace = _history_handlers.history_workspace
diff_workspace = _history_handlers.diff_workspace
revert_workspace = _history_handlers.revert_workspace

# Trusted profiles fail fast at import/startup. Runtime Docker access remains lazy.
document_catalog = load_profile_catalog()
document_projects = DocumentProjectService(_route_run_file_op, _route_snapshot, document_catalog)
document_checkpoints = DocumentCheckpointService(_route_run_file_op, document_projects)
document_source_recovery = SourcePublicationRecovery(_route_run_file_op, _route_snapshot)
document_sources = DocumentSourceService(
    _route_run_file_op,
    _route_snapshot,
    _route_revision,
    document_projects,
    document_checkpoints,
    document_source_recovery,
)
document_vendors = DocumentVendorOverlayService(
    _route_run_file_op,
    _route_snapshot,
    _route_revision,
    document_projects,
    _route_fetch,
)
document_compiler = DockerDocumentCompiler()
document_vendor_profiles = DocumentVendorProfileService(
    _route_run_file_op,
    _route_snapshot,
    _route_revision,
    document_projects,
    document_vendors,
    document_compiler,
)
document_builds = DocumentBuildManager(document_compiler, document_projects, _route_revision)
router.include_router(
    create_documents_router(
        DocumentRouteDependencies(
            common=_route_dependencies,
            catalog=document_catalog,
            projects=document_projects,
            sources=document_sources,
            checkpoints=document_checkpoints,
            vendors=document_vendors,
            vendor_profiles=document_vendor_profiles,
            builds=document_builds,
        )
    )
)
