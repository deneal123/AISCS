"""Bounded HTTP metrics for chat-scoped workspace operations.

The route wrapper deliberately derives labels from the registered endpoint name
and HTTP status only.  Request paths, workspace identities, file names and
exception details never cross this boundary.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from fastapi import HTTPException, Request, Response
from fastapi.routing import APIRoute

logger = logging.getLogger(__name__)

_OPERATIONS = {
    "activate",
    "collaboration",
    "control",
    "copy",
    "diff",
    "file_read",
    "history",
    "import",
    "issue",
    "lease",
    "library",
    "revert",
    "snapshot",
    "tree",
    "write",
    "unknown",
}
_STATUSES = {
    "succeeded",
    "failed",
    "conflict",
    "locked",
    "unavailable",
    "expired",
    "unknown",
}

_ENDPOINT_OPERATIONS = {
    "workspace_tree": "tree",
    "workspace_file": "file_read",
    "workspace_history": "history",
    "workspace_diff": "diff",
    "workspace_revert": "revert",
    "workspace_room": "collaboration",
    "work_snapshot": "snapshot",
    "activate_work": "activate",
    "account_work_library": "library",
    "acquire_workspace_lease": "lease",
    "renew_workspace_lease": "lease",
    "release_workspace_lease": "lease",
    "write_workspace_file": "write",
    "copy_library_file_to_workspace": "copy",
    "upload_file_to_workspace": "import",
    "workspace_issues": "issue",
    "create_workspace_issue": "issue",
    "update_workspace_issue": "issue",
    "workspace_control": "control",
    "apply_document_vendor_overlay": "import",
    "activate_document_vendor_profile": "import",
    "publish_document_source": "write",
}


def bounded_workspace_operation(endpoint_name: object) -> str:
    operation = _ENDPOINT_OPERATIONS.get(str(endpoint_name), "unknown")
    return operation if operation in _OPERATIONS else "unknown"


def bounded_workspace_status(status_code: object) -> str:
    if not isinstance(status_code, (int, float, str, bytes, bytearray)):
        return "unknown"
    try:
        status = int(status_code)
    except (TypeError, ValueError):
        return "unknown"
    if 200 <= status < 400:
        return "succeeded"
    return {
        409: "conflict",
        410: "expired",
        423: "locked",
        502: "unavailable",
        503: "unavailable",
        504: "unavailable",
    }.get(status, "failed")


class WorkspaceOperationMetrics:
    def __init__(self) -> None:
        self.operation_total = None
        try:
            from prometheus_client import Counter

            self.operation_total = Counter(
                "workspace_operation_total",
                "Bounded outcomes of chat-scoped workspace operations",
                ["operation", "status"],
            )
        except Exception:
            logger.debug("Workspace operation metric is unavailable")

    def record(self, *, operation: object, status: object) -> None:
        if self.operation_total is None:
            return
        try:
            self.operation_total.labels(
                operation=(str(operation) if str(operation) in _OPERATIONS else "unknown"),
                status=str(status) if str(status) in _STATUSES else "unknown",
            ).inc()
        except Exception:
            logger.debug("Workspace operation metric update failed")


workspace_operation_metrics = WorkspaceOperationMetrics()


class WorkspaceMetricsRoute(APIRoute):
    """Record a bounded operation/status pair around every workspace route."""

    def get_route_handler(self) -> Callable:
        original_handler = super().get_route_handler()
        operation = bounded_workspace_operation(self.name)

        async def measured_handler(request: Request) -> Response:
            try:
                response = await original_handler(request)
            except HTTPException as exc:
                workspace_operation_metrics.record(
                    operation=operation,
                    status=bounded_workspace_status(exc.status_code),
                )
                raise
            except Exception:
                workspace_operation_metrics.record(operation=operation, status="failed")
                raise
            workspace_operation_metrics.record(
                operation=operation,
                status=bounded_workspace_status(response.status_code),
            )
            return response

        return measured_handler
