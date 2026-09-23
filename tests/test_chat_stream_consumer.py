"""ChatStreamConsumer.consume_events: устойчивость к сбоям.

Регрессия: широкий except ловил в т.ч. ошибки отправки в мёртвый сокет, затем
sleep(1) и цикл крутился ВЕЧНО (без backoff-капа и без выхода), спамя логами.
Теперь: выход на WebSocketDisconnect и give-up после N подряд ошибок.
"""

import asyncio

import pytest
from starlette.websockets import WebSocketDisconnect

import service.services.chat.presentation.ws.chat_ws.stream_consumer as sc_mod
from service.infrastructure.agents_client.contracts.events import EventSerializer, EventType
from service.services.chat.presentation.ws.chat_ws.metrics import ChatWsMetrics
from service.services.chat.presentation.ws.chat_ws.stream_consumer import ChatStreamConsumer


class _Metrics:
    def __init__(self):
        self.counts: dict = {}
        self.tool_events: list[dict] = []
        self.run_integrity_events: list[dict] = []
        self.usage_integrity_events: list[dict] = []
        self.grounding_events: list[dict] = []
        self.provider_qualification_events: list[dict] = []
        self.stream_protocol_events: list[dict] = []

    def inc(self, key):
        self.counts[key] = self.counts.get(key, 0) + 1

    def tool_event(self, **kwargs):
        self.tool_events.append(kwargs)

    def run_integrity(self, **kwargs):
        self.run_integrity_events.append(kwargs)

    def usage_integrity(self, **kwargs):
        self.usage_integrity_events.append(kwargs)

    def grounding(self, **kwargs):
        self.grounding_events.append(kwargs)

    def provider_qualification(self, **kwargs):
        self.provider_qualification_events.append(kwargs)

    def stream_protocol(self, **kwargs):
        self.stream_protocol_events.append(kwargs)


class _WS:
    def __init__(self):
        self.sent: list = []

    async def send_json(self, payload):
        self.sent.append(payload)


class _LabelCounter:
    def __init__(self):
        self.labels_seen = []
        self.values = []

    def labels(self, **labels):
        self.labels_seen.append(labels)
        return self

    def inc(self, value=1):
        self.values.append(value)


@pytest.mark.asyncio
async def test_consume_events_gives_up_after_consecutive_errors(monkeypatch) -> None:
    calls = {"n": 0}

    async def _xread_always_fails(*a, **k):
        calls["n"] += 1
        raise RuntimeError("redis down")

    async def _no_sleep(_d):
        return None

    monkeypatch.setattr(sc_mod.stream_helpers, "xread", _xread_always_fails)
    monkeypatch.setattr(sc_mod.asyncio, "sleep", _no_sleep)

    metrics = _Metrics()
    consumer = ChatStreamConsumer(redis_client=object(), settings=object(), metrics=metrics)

    # НЕ должно крутиться вечно: выходит после _MAX_CONSECUTIVE_STREAM_ERRORS.
    await asyncio.wait_for(consumer.consume_events(_WS(), "chat:t:stream", "g", "c"), timeout=2.0)
    assert calls["n"] == sc_mod._MAX_CONSECUTIVE_STREAM_ERRORS
    assert metrics.counts.get("stream_consumer_gave_up_total") == 1


@pytest.mark.asyncio
async def test_consume_events_stops_on_websocket_disconnect(monkeypatch) -> None:
    async def _xread_disconnect(*a, **k):
        raise WebSocketDisconnect(code=1000)

    monkeypatch.setattr(sc_mod.stream_helpers, "xread", _xread_disconnect)

    metrics = _Metrics()
    consumer = ChatStreamConsumer(redis_client=object(), settings=object(), metrics=metrics)

    await asyncio.wait_for(consumer.consume_events(_WS(), "chat:t:stream", "g", "c"), timeout=2.0)
    # Дисконнект — штатный выход, НЕ через give-up.
    assert metrics.counts.get("stream_consumer_gave_up_total") is None


def test_tool_lifecycle_metrics_use_bounded_metadata_only() -> None:
    metrics = _Metrics()
    consumer = ChatStreamConsumer(redis_client=object(), settings=object(), metrics=metrics)

    consumer._record_tool_metrics(
        {
            "type": "status_update",
            "metadata": {
                "kind": "tool_progress",
                "tool_progress": {
                    "tool": "web_search",
                    "status": "succeeded",
                    "duration_ms": 25,
                    "arguments": "must-not-be-metric",
                },
            },
        }
    )

    assert metrics.tool_events == [
        {"kind": "progress", "status": "succeeded", "reason": "", "duration_ms": 25}
    ]


def test_tool_dedup_metric_reason_is_bounded_and_has_no_arguments() -> None:
    metrics = _Metrics()
    consumer = ChatStreamConsumer(redis_client=object(), settings=object(), metrics=metrics)

    consumer._record_tool_metrics(
        {
            "type": "status_update",
            "metadata": {
                "kind": "tool_progress",
                "tool_progress": {
                    "tool": "search_web",
                    "status": "reused",
                    "dedup_reason": "inflight",
                    "arguments": '{"secret":"must-not-be-metric"}',
                },
            },
        }
    )

    assert metrics.tool_events == [
        {"kind": "progress", "status": "reused", "reason": "dedup_inflight", "duration_ms": None}
    ]


def test_run_integrity_metrics_use_only_bounded_reasons() -> None:
    metrics = _Metrics()
    consumer = ChatStreamConsumer(redis_client=object(), settings=object(), metrics=metrics)

    consumer._record_tool_metrics(
        {
            "type": "status_update",
            "metadata": {
                "kind": "run_integrity",
                "run_integrity": {
                    "reasons": ["duplicate_result", "event_after_result"],
                    "raw_result": "must-not-be-metric",
                },
            },
        }
    )

    assert metrics.run_integrity_events == [
        {"reason": "duplicate_result"},
        {"reason": "event_after_result"},
    ]
    assert metrics.stream_protocol_events == [
        {"stage": "ndjson", "reason": "duplicate_result"},
        {"stage": "ndjson", "reason": "event_after_result"},
    ]
    assert "must-not-be-metric" not in str(metrics.run_integrity_events)


def test_ledger_and_grounding_metrics_project_only_bounded_aggregates() -> None:
    metrics = _Metrics()
    consumer = ChatStreamConsumer(redis_client=object(), settings=object(), metrics=metrics)

    consumer._record_tool_metrics(
        {
            "type": "agent_reply",
            "metadata": {
                "usage_integrity": {
                    "anomaly_count": 1,
                    "reason_codes": ["missing_provider"],
                    "prompt": "must-not-be-metric",
                }
            },
        }
    )
    consumer._record_tool_metrics(
        {
            "type": "status_update",
            "metadata": {
                "kind": "tool_intent",
                "tool_intent": {
                    "state": "repair",
                    "reason": "missing_call",
                    "tool": "must-not-be-metric",
                },
            },
        }
    )

    assert metrics.usage_integrity_events == [{"reason": "missing_provider"}]
    assert metrics.grounding_events == [{"state": "repair", "reason": "missing_call"}]
    assert "must-not-be-metric" not in str(
        metrics.usage_integrity_events + metrics.grounding_events
    )


def test_new_integrity_metrics_bound_every_label() -> None:
    metrics = ChatWsMetrics.__new__(ChatWsMetrics)
    metrics.usage_integrity_total = _LabelCounter()
    metrics.grounding_total = _LabelCounter()
    metrics.provider_qualification_total = _LabelCounter()
    metrics.stream_protocol_total = _LabelCounter()

    metrics.usage_integrity(reason="private-request")
    metrics.grounding(state="secret-state", reason="private-request")
    metrics.provider_qualification(provider="private-provider", status="private-status")
    metrics.stream_protocol(stage="private-stage", reason="private-reason")

    assert metrics.usage_integrity_total.labels_seen == [{"reason": "unknown"}]
    assert metrics.grounding_total.labels_seen == [{"state": "unknown", "reason": "unknown"}]
    assert metrics.provider_qualification_total.labels_seen == [
        {"provider": "unknown", "status": "unknown"}
    ]
    assert metrics.stream_protocol_total.labels_seen == [{"stage": "unknown", "reason": "unknown"}]


def test_stream_mode_offer_redacts_legacy_request_text() -> None:
    payload = ChatStreamConsumer.build_event_payload(
        {
            "type": "status_update",
            "metadata": {
                "kind": "mode_offer",
                "mode_offer": {"mode": "deep_research", "prompt": "exact private request"},
            },
        }
    )

    assert payload["metadata"]["mode_offer"] == {"mode": "deep_research"}
    assert "exact private request" not in str(payload)


def test_serializer_redacts_legacy_mode_offer_before_redis_projection() -> None:
    event = type(
        "Event",
        (),
        {
            "type": EventType.STATUS_UPDATE,
            "data": "confirmation",
            "agent_name": "router",
            "metadata": {
                "kind": "mode_offer",
                "mode_offer": {"mode": "deep_research", "prompt": "exact private request"},
            },
            "seq": 1,
        },
    )()

    payload = EventSerializer().serialize(event=event, job_id="job")

    assert payload["metadata"]["mode_offer"] == {"mode": "deep_research"}
    assert "exact private request" not in str(payload)


def test_serializer_redacts_auto_mode_rationale_before_redis_projection() -> None:
    marker = "synthetic-model-rationale-must-not-stream"
    event = type(
        "Event",
        (),
        {
            "type": EventType.STATUS_UPDATE,
            "data": "auto",
            "agent_name": "router",
            "metadata": {
                "kind": "auto_decision",
                "auto": {"reason": marker, "reason_code": "model_classification"},
            },
            "seq": 1,
        },
    )()

    payload = EventSerializer().serialize(event=event, job_id="job")

    assert payload["metadata"]["auto"] == {"reason_code": "model_classification"}
    assert marker not in str(payload)
