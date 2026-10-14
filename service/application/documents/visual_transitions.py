"""Durable, operation-guarded visual audit and recovered cancellation transitions."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from domain.documents import DocumentBuild, DocumentDiagnostic

from .projects import DocumentProjectError

VISUAL_DIAGNOSTIC_CODES = frozenset(
    {
        "visual_blank_page",
        "visual_clipping",
        "visual_overlap",
        "visual_readability",
        "visual_table_overflow",
        "visual_image_quality",
        "visual_header_footer",
        "visual_composition",
    }
)
VISUAL_AUDIT_LEASE_SEC = 120
_TRANSITION_FIELDS = frozenset(
    {
        "state",
        "failure_code",
        "diagnostics",
        "completed_at",
        "compiler_ref",
        "visual_audit_version",
        "visual_audit_claimed_at",
    }
)


async def _read_uncertain(manager: Any, registry: Any, item: Any, build: DocumentBuild):
    records = await manager.store.load(registry, item)
    matches = [entry for entry in records if entry.build_id == build.build_id]
    if len(matches) != 1:
        raise RuntimeError("transition manifest unavailable")
    record = matches[0]
    before, after = build.manifest_dict(), record.manifest_dict()
    if any(
        value != after.get(key) for key, value in before.items() if key not in _TRANSITION_FIELDS
    ):
        raise RuntimeError("transition manifest unavailable")
    for field in _TRANSITION_FIELDS:
        setattr(build, field, getattr(record, field))
    build.manifest_uncertain = False
    return record


async def resolve_observed(manager: Any, registry: Any, item: Any, build: DocumentBuild):
    if not build.manifest_uncertain:
        return build
    try:
        async with registry.operation(item):
            if build.manifest_uncertain:
                await _read_uncertain(manager, registry, item, build)
    except Exception:
        manager.manifest_failures += 1
        raise DocumentProjectError("runtime_unavailable") from None
    return build


async def commit_transition(
    manager: Any,
    registry: Any,
    item: Any,
    build: DocumentBuild,
    prepare: Callable[[DocumentBuild], dict[str, Any]],
) -> DocumentBuild:
    """Keep observed state unchanged until a staged manifest is acknowledged.

    Validation and persistence share the workspace operation guard. In particular,
    a waiting attestation rechecks cancellation before it can persist ready. Never
    hold the manager's inventory lock while acquiring the workspace guard.
    """
    counted = False
    try:
        async with registry.operation(item):
            if build.manifest_uncertain:
                await _read_uncertain(manager, registry, item, build)
            changes = prepare(build)
            if not changes:
                return build
            candidate = replace(build, **changes, manifest_uncertain=False)
            build.manifest_uncertain = True
            try:
                await manager.store.save(registry, item, candidate)
            except Exception:
                manager.manifest_failures += 1
                counted = True
                record = await _read_uncertain(manager, registry, item, build)
                if record.manifest_dict() != candidate.manifest_dict():
                    raise DocumentProjectError("runtime_unavailable") from None
            for field, value in changes.items():
                setattr(build, field, value)
            build.manifest_uncertain = False
    except DocumentProjectError:
        raise
    except Exception:
        if not counted:
            manager.manifest_failures += 1
        raise DocumentProjectError("runtime_unavailable") from None
    return build


async def claim_visual(manager: Any, registry: Any, item: Any, build: DocumentBuild):
    def prepare(current: DocumentBuild) -> dict[str, Any]:
        claim_expired = (
            current.state == "visual_audit"
            and current.visual_audit_claimed_at is not None
            and time.time() - current.visual_audit_claimed_at >= VISUAL_AUDIT_LEASE_SEC
        )
        if current.state == "visual_audit" and not claim_expired:
            raise DocumentProjectError("audit_busy")
        if current.state not in {"visual_pending", "visual_audit"} or not current.final:
            raise DocumentProjectError("audit_unavailable")
        return {
            "state": "visual_audit",
            "failure_code": "",
            "visual_audit_claimed_at": time.time(),
        }

    return await commit_transition(manager, registry, item, build, prepare)


async def cancel_recovered(manager: Any, registry: Any, item: Any, build: DocumentBuild):
    def prepare(current: DocumentBuild) -> dict[str, Any]:
        if current.terminal:
            return {}
        return {
            "state": "cancelled",
            "failure_code": "build_cancelled",
            "completed_at": time.time(),
            "visual_audit_claimed_at": None,
        }

    return await commit_transition(manager, registry, item, build, prepare)


def _diagnostics(build: DocumentBuild, diagnostics: list[dict[str, object]]):
    return tuple(
        DocumentDiagnostic(
            severity="error",
            code=str(entry.get("code") or "")[:64],
            line=(int(entry["page"]) if isinstance(entry.get("page"), int) else None),
            count=max(1, int(entry.get("count") or 1)),
            block_id=(
                build.page_blocks[int(entry["page"])][0]
                if isinstance(entry.get("page"), int)
                and len(build.page_blocks.get(int(entry["page"]), ())) == 1
                else ""
            ),
        )
        for entry in diagnostics[:100]
        if isinstance(entry, dict) and str(entry.get("code") or "") in VISUAL_DIAGNOSTIC_CODES
    )


async def complete_visual(
    manager: Any,
    registry: Any,
    item: Any,
    build: DocumentBuild,
    *,
    source_digest: str,
    artifact_sha256: str,
    passed: bool,
    retryable: bool,
    audit_version: int,
    diagnostics: list[dict[str, object]],
) -> DocumentBuild:
    def prepare(current: DocumentBuild) -> dict[str, Any]:
        if current.state not in {"visual_pending", "visual_audit"}:
            raise DocumentProjectError("audit_unavailable")
        pdf = next((artifact for artifact in current.artifacts if artifact.role == "pdf"), None)
        if pdf is None or source_digest != current.source_digest or artifact_sha256 != pdf.sha256:
            raise DocumentProjectError("source_changed")
        visual = _diagnostics(current, diagnostics)
        changes: dict[str, Any] = {
            "visual_audit_version": max(1, int(audit_version or 1)),
            "visual_audit_claimed_at": None,
        }
        if passed and not visual:
            changes.update(state="ready", failure_code="", completed_at=time.time())
        elif retryable:
            changes.update(state="visual_pending", failure_code="visual_unavailable")
        else:
            changes.update(
                state="failed",
                failure_code="visual_audit_failed",
                completed_at=time.time(),
                diagnostics=(*current.diagnostics, *visual)[:100],
            )
        return changes

    return await commit_transition(manager, registry, item, build, prepare)
