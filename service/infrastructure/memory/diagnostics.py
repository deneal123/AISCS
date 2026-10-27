"""Closed diagnostic projections shared by memory integrations and services."""

import logging
from typing import Any

import httpx

_OPERATIONS = {
    "mem0.get_memory_context": "context",
    "mem0.save_messages": "save",
    "mem0.list_facts": "list",
    "mem0.add_fact": "add",
    "mem0.delete_fact": "delete",
    "memos.post /product/add": "save",
    "memos.post /product/search": "search",
    "memos.wipe": "wipe",
    "memos.forget_user": "forget",
    **{
        name: name
        for name in (
            "remember",
            "recall",
            "context",
            "save",
            "dashboard",
            "list",
            "add",
            "delete",
            "wipe",
            "forget",
        )
    },
}
_COUNTS = frozenset({"top_k", "memories", "saved", "messages", "facts"})


def failure_code(exc: Exception | None) -> str:
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return "timeout"
    if isinstance(exc, (OSError, httpx.HTTPError)):
        return "transport"
    return "unavailable"


def operation_metadata(operation: str, status: str, details: dict[str, Any] | None = None) -> dict:
    if status not in {"started", "completed", "failed"}:
        status = "other"
    data = {
        "component": "memory",
        "operation": _OPERATIONS.get(operation, "other"),
        "status": status,
    }
    for key, value in (details or {}).items():
        if key in _COUNTS and type(value) is int:
            data[key] = min(1_000_000, max(0, value))
    return data


def log_memory_failure(
    logger: logging.Logger,
    operation: str,
    exc: Exception | None = None,
    *,
    warning: bool = False,
    elapsed_ms: float | None = None,
) -> None:
    data = operation_metadata(operation, "failed")
    data["failure_code"] = failure_code(exc)
    if elapsed_ms is not None:
        data["elapsed_ms"] = max(0.0, elapsed_ms)
    logger.log(
        logging.WARNING if warning else logging.DEBUG,
        "Memory operation %s failed: %s",
        data["operation"],
        data["failure_code"],
        extra=data,
    )
