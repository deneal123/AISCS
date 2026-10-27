"""Private recovery context; catalog text stays in PostgreSQL, never public metadata."""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from service.services.chat.infrastructure.chat_worker.context.metadata import persistable_meta
from service.services.chat.infrastructure.chat_worker.results.checkpoint import (
    PreparedCheckpointInvalid,
    _validate_tree,
)

_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}")


def validate_context(context: Any, library_files: list[dict]) -> None:
    """No permissive str coercion, unknown keys, binary assets or credentials."""
    if not isinstance(context, dict) or set(context) != {"metadata", "observations", "executions"}:
        raise PreparedCheckpointInvalid("Materialization unavailable")
    _validate_tree(context)
    metadata = context["metadata"]
    if (
        not isinstance(metadata, dict)
        or metadata.get("generated_files", []) != library_files
        or persistable_meta(metadata, None) != metadata
    ):
        raise PreparedCheckpointInvalid("Materialization unavailable")
    observations, executions = context["observations"], context["executions"]
    for records in (observations, executions):
        if not isinstance(records, list) or len(records) > 32:
            raise PreparedCheckpointInvalid("Materialization unavailable")
    for item in observations:
        if not isinstance(item, dict) or set(item) != {"steps", "cost_class", "request_text"}:
            raise PreparedCheckpointInvalid("Materialization unavailable")
        steps, cost, request = item["steps"], item["cost_class"], item["request_text"]
        if (
            not isinstance(steps, list)
            or not 2 <= len(steps) <= 16
            or any(not isinstance(step, str) or not _NAME.fullmatch(step) for step in steps)
            or not isinstance(cost, str)
            or not _NAME.fullmatch(cost)
            or not isinstance(request, str)
            or not 0 < len(request) <= 16384
        ):
            raise PreparedCheckpointInvalid("Materialization unavailable")
    for item in executions:
        if not isinstance(item, dict) or set(item) != {"workflow_id", "version", "status"}:
            raise PreparedCheckpointInvalid("Materialization unavailable")
        if (
            str(UUID(item["workflow_id"])) != item["workflow_id"]
            or type(item["version"]) is not int
            or not 1 <= item["version"] <= 1000000
            or item["status"] not in {"succeeded", "failed", "cancelled"}
        ):
            raise PreparedCheckpointInvalid("Materialization unavailable")
