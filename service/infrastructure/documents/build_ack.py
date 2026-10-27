"""Неизвестный ACK сборки разрешается чтением того же ID, а не новым POST запуска."""

import re

from service.shared.document_review import operation_build_id


def matches_build(value, build_id, payload):
    return (
        isinstance(value, dict)
        and value.get("build_id") == build_id
        and value.get("source_revision") == payload["expected_revision"]
        and value.get("final") is payload["final"]
        and isinstance(value.get("state"), str)
        and value.get("state")
        in {
            "queued",
            "preparing",
            "building",
            "deterministic_audit",
            "visual_pending",
            "visual_audit",
            "publishing",
            "preview_ready",
            "ready",
            "failed",
            "cancelled",
        }
        and isinstance(value.get("source_digest"), str)
        and re.fullmatch(r"[a-f0-9]{64}", value["source_digest"]) is not None
    )


async def start_versioned_build(call, ref, payload):
    from service.infrastructure.workspace_client import WorkspaceUnavailable

    try:
        build_id = operation_build_id((ref or {}).get("workspace_id"), payload["operation_id"])
    except (TypeError, ValueError):
        raise WorkspaceUnavailable("document build identity is invalid") from None
    try:
        value = await call(ref, "documents/builds", payload)
    except WorkspaceUnavailable:
        value = None
    if matches_build(value, build_id, payload):
        return value
    # Только одно чтение. Отсутствие/ошибка статуса не доказывает отсутствие compiler create.
    try:
        observed = await call(ref, "documents/builds/" + build_id, {})
    except WorkspaceUnavailable:
        observed = None
    if not matches_build(observed, build_id, payload):
        raise WorkspaceUnavailable("document build outcome is unknown") from None
    return observed
