"""Composition facade for Work Hub and workspace HTTP routes.

Endpoint orchestration is split by responsibility. The exports keep the
long-standing in-process contract while FastAPI receives one stable router and
the existing public URLs.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Header

from service.infrastructure import workspace_client  # noqa: F401
from service.services.chat.application.workspace_collaboration import (  # noqa: F401
    CollaborationConflict,
    CollaborationError,
    CollaborationPaused,
    CollaborationUnavailable,
    verify_capability,
)
from service.services.chat.presentation.routers.chat_api.workspace_access import (  # noqa: F401
    _alive,
    _collaboration,
    _collaboration_http_error,
    _ref,
    _request_active_run_cancellation,
    _ui_capability,
)
from service.services.chat.presentation.routers.chat_api.workspace_contracts import (
    ControlRequest,
    DiffRequest,
    IssueCreateRequest,
    IssueUpdateRequest,
    LeaseRequest,
    LibraryCopyRequest,
    PathRequest,
    RevertRequest,
    WriteRequest,
)
from service.services.chat.presentation.routers.chat_api.workspace_coordination_routes import (
    acquire_workspace_lease,
    create_workspace_issue,
    pin_workflow,
    release_workspace_lease,
    renew_workspace_lease,
    update_workspace_issue,
    workspace_control,
    workspace_issues,
    write_workspace_file,
)
from service.services.chat.presentation.routers.chat_api.workspace_coordination_routes import (
    router as coordination_router,
)
from service.services.chat.presentation.routers.chat_api.workspace_document_routes import (
    router as document_router,
)
from service.services.chat.presentation.routers.chat_api.workspace_file_routes import (
    router as file_router,
)
from service.services.chat.presentation.routers.chat_api.workspace_file_routes import (
    workspace_diff,
    workspace_file,
    workspace_history,
    workspace_revert,
    workspace_tree,
)
from service.services.chat.presentation.routers.chat_api.workspace_intake_routes import (
    copy_library_file_to_workspace,
    upload_file_to_workspace,
)
from service.services.chat.presentation.routers.chat_api.workspace_intake_routes import (
    router as intake_router,
)
from service.services.chat.presentation.routers.chat_api.workspace_metrics import (
    WorkspaceMetricsRoute,
)
from service.services.chat.presentation.routers.chat_api.workspace_snapshot_routes import (
    account_work_library,
    activate_work,
    ready_work_snapshot,
    work_snapshot,
    workspace_room,
)
from service.services.chat.presentation.routers.chat_api.workspace_snapshot_routes import (
    router as snapshot_router,
)

logger = logging.getLogger(__name__)

workspace_router = APIRouter(route_class=WorkspaceMetricsRoute)
workspace_router.include_router(file_router)
workspace_router.include_router(snapshot_router)
workspace_router.include_router(coordination_router)
workspace_router.include_router(intake_router)
workspace_router.include_router(document_router)

WorkspaceSessionHeader = Annotated[str | None, Header(alias="X-Workspace-Session")]


def _request_ui_capability(ref: dict, user_id: str, workspace_session: str | None) -> str:
    """Mint a server-owned UI capability, honoring only an opaque actor session."""
    if workspace_session:
        return _ui_capability(ref, user_id, workspace_session)
    return _ui_capability(ref, user_id)


_ready_work_snapshot = ready_work_snapshot

__all__ = [
    "ControlRequest",
    "DiffRequest",
    "IssueCreateRequest",
    "IssueUpdateRequest",
    "LeaseRequest",
    "LibraryCopyRequest",
    "PathRequest",
    "RevertRequest",
    "WorkspaceSessionHeader",
    "WriteRequest",
    "account_work_library",
    "acquire_workspace_lease",
    "activate_work",
    "copy_library_file_to_workspace",
    "create_workspace_issue",
    "pin_workflow",
    "release_workspace_lease",
    "renew_workspace_lease",
    "update_workspace_issue",
    "upload_file_to_workspace",
    "work_snapshot",
    "workspace_control",
    "workspace_diff",
    "workspace_file",
    "workspace_history",
    "workspace_issues",
    "workspace_revert",
    "workspace_room",
    "workspace_router",
    "workspace_tree",
    "write_workspace_file",
]
