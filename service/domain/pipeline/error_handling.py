"""Error handling helpers for agent pipeline."""

from __future__ import annotations

from service.domain.client.protocol import safe_failure_metadata
from service.events import AgentEvent, EventType

_DETAIL_LIMIT = 0  # compatibility constant; raw details are no longer transported


def build_processing_error_event(exc: Exception, *, thread_id: str, logger) -> AgentEvent:
    """Project an exception to the closed, trace-safe failure contract.

    The exception message, class name and request/thread contents deliberately do not
    cross this boundary.  Diagnostics retain only the bounded failure taxonomy.
    """
    del thread_id
    failure = safe_failure_metadata(exc)
    logger.warning("Agent processing failed code=%s", failure["failure_code"])
    return AgentEvent(
        type=EventType.ERROR,
        data="Выполнение завершилось безопасно обработанной ошибкой.",
        metadata={
            **failure,
            "category": "provider",
            "status_family": failure.get("status_family", "none"),
        },
    )
