"""Recovery payloads for interrupted NDJSON agent runs."""

from __future__ import annotations

from typing import Any


def event_recovery_metadata(event: Any) -> dict:
    """Event accounting remains a projection, never transport metadata."""
    return {
        key: value
        for key, value in (getattr(event, "metadata", None) or {}).items()
        if key != "token_usage"
    }


def build_timeout_result(recovery: Any, metadata: dict, payload: Any) -> dict:
    """Preserve streamed text and accounting when the outer deadline fires."""
    recovery.finalize_usage()
    metadata = {key: value for key, value in metadata.items() if key != "usage_integrity"}
    if integrity := recovery.metadata.get("usage_integrity"):
        metadata["usage_integrity"] = integrity
    reply = recovery.build_reply().strip()
    if not reply:
        reply = "Не удалось завершить ответ до истечения времени. Попробуйте повторить запрос."
    return {
        "reply": reply,
        "metadata": {
            **metadata,
            "execution_status": "timed_out",
            "deadline_exceeded": True,
            "partial_failure": True,
            "provider_error": "timeout",
        },
        "resolved_model": payload.selected_model or "",
        "reply_parts_count": len(recovery.reply_parts),
        "reply_chars_count": len(reply),
        "prompt_tokens": recovery.prompt_tokens,
        "completion_tokens": recovery.completion_tokens,
        "total_tokens": recovery.total_tokens,
        "per_call_usage": list(recovery.per_call_usage),
        "workspace_artifacts": [],
    }


def build_failure_result(recovery: Any, metadata: dict, payload: Any) -> dict:
    """A failure does not erase accepted receipts or expose its exception body."""
    result = build_timeout_result(recovery, metadata, payload)
    result["metadata"].pop("deadline_exceeded", None)
    result["metadata"].update({"execution_status": "failed", "provider_error": "internal"})
    if not recovery.build_reply().strip():
        result["reply"] = "Не удалось завершить ответ. Попробуйте повторить запрос."
        result["reply_chars_count"] = len(result["reply"])
    return result
