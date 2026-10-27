"""Build a replay plan before I/O; no credentials or binary assets are serialized."""

from __future__ import annotations

import time
from typing import Any

from service.services.chat.infrastructure.chat_worker.context.metadata import persistable_meta
from service.services.chat.infrastructure.chat_worker.materialization.recovery import (
    MaterializationPlan,
)
from service.services.chat.infrastructure.chat_worker.materialization.workspace import (
    validated_inventory,
)
from service.services.chat.infrastructure.chat_worker.results.artifacts import (
    _collectable_workspace_inventory,
)
from service.services.chat.infrastructure.chat_worker.results.prepared import _safe_files
from service.services.chat.infrastructure.pricing_signals import _pricing_signals
from service.services.chat.persistence.documents.publication import normalize_descriptors


def build_materialization_plan(
    *,
    metadata: dict[str, Any],
    execution_result: dict[str, Any],
    state: Any,
    prepared: Any,
    started_at: float,
) -> MaterializationPlan:
    """Classify unresolved legacy assets explicitly rather than lose them on replay."""
    ref = state.engine_env.get("workspace_ref") or {}
    public = persistable_meta(metadata, None)
    files = _safe_files(public)
    # Old artifact bridges omitted kind/MIME. Opaque records must not invent a
    # specialized media type; octet-stream is the conservative compatibility case.
    files = [
        {
            **item,
            "mime_type": item.get("mime_type") or "application/octet-stream",
            "kind": item.get("kind") or "file",
        }
        for item in files
    ]
    if "generated_files" in public:
        public["generated_files"] = files
    descriptors = normalize_descriptors(metadata.get("document_artifacts") or [])
    complex_run, tools = _pricing_signals(execution_result)
    inventory = _collectable_workspace_inventory(execution_result.get("workspace_artifacts"))
    planned: list[dict[str, Any]] = []
    unresolved = len(metadata.get("_pending_artifacts") or [])
    for item in inventory:
        try:
            projected = {key: item[key] for key in ("path", "size", "sha256")}
            projected["required"] = bool(item.get("required"))
            validated_inventory([*planned, projected])
            planned.append(projected)
        except Exception:
            unresolved += 1
    unresolved += sum(bool(metadata.get(key)) for key in ("image", "images", "pptx_b64"))
    return MaterializationPlan.from_payload(
        {
            "version": 3,
            "workspace_files": planned,
            "reservation_id": state.reservation_id,
            "reserved_estimate": state.reserved_estimate,
            "workspace_id": ref.get("workspace_id"),
            "expires_at": ref.get("expires_at"),
            "publications": list(descriptors),
            "pricing": {"is_complex": complex_run, "tools": tools},
            "elapsed_seconds": max(0.0, time.monotonic() - started_at),
            "library_files": files,
            "unresolved_assets": unresolved,
            "context": {
                "metadata": public,
                "observations": prepared.workflow_observations,
                "executions": prepared.workflow_executions,
            },
        }
    )
