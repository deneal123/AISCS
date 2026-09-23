"""Recovery payloads for interrupted NDJSON agent runs."""

from __future__ import annotations

from typing import Any


def build_timeout_result(recovery: Any, metadata: dict, payload: Any) -> dict:
    """Preserve streamed text and accounting when the outer deadline fires."""
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
