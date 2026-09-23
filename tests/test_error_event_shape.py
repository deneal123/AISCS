"""Processing errors expose only the closed, trace-safe failure contract."""

from __future__ import annotations

import logging

from service.domain.pipeline.error_handling import build_processing_error_event
from service.events import EventSerializer, EventType

logger = logging.getLogger(__name__)


def _event(exc: Exception):
    return build_processing_error_event(exc, thread_id="t-1", logger=logger)


def test_user_sees_safe_text_not_exception():
    marker = "S24_PRIVATE_PROVIDER_BODY"
    event = _event(TimeoutError(f"HTTPSConnectionPool(host='api.provider.io'): {marker}"))

    assert event.type == EventType.ERROR
    assert event.data == "Выполнение временно недоступно; повторите запрос позже."
    serialized = str(EventSerializer().serialize(event=event, job_id="job"))
    assert marker not in serialized
    assert "api.provider.io" not in serialized


def test_metadata_contains_only_bounded_failure_fields():
    marker = "S24_PRIVATE_EXCEPTION"
    event = _event(ValueError(marker))

    assert set(event.metadata) == {
        "failure_code",
        "category",
        "retryable",
        "status_family",
    }
    assert event.metadata["failure_code"] == "remote"
    assert event.metadata["category"] == "provider"
    assert marker not in str(event.model_dump())


def test_legacy_error_payload_is_defensively_stripped():
    marker = "S24_LEGACY_SECRET"
    from service.events import AgentEvent

    event = AgentEvent(
        type=EventType.ERROR,
        data=marker,
        metadata={
            "failure_code": "unknown-secret-code",
            "category": "private-component",
            "retryable": False,
            "status_family": "999",
            "original_error": marker,
            "error_detail": marker,
            "error_type": "SensitiveException",
        },
    )
    serialized = str(EventSerializer().serialize(event=event, job_id="job"))
    assert marker not in serialized
    assert event.metadata == {
        "failure_code": "internal",
        "category": "internal",
        "retryable": False,
        "status_family": "none",
    }
