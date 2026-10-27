"""Catalog and secret delivery failures retain semantics without private diagnostics."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from service.infrastructure.agents_client import sidecar_providers as catalog
from service.infrastructure.agents_client import workflow_catalog as delivery
from service.infrastructure.sidecar import (
    SidecarBadRequest,
    SidecarClient,
    SidecarError,
    SidecarTimeout,
    SidecarUnavailable,
)

MARKER = "PRIVATE_CATALOG_KEY_REQUEST_RESPONSE_MARKER"
OPERATIONS = [
    ("fetch_provider_health", "provider_health", None),
    ("fetch_chat_model_catalog", "model_catalog", None),
    ("fetch_agent_catalog", "agent_catalog", None),
    ("fetch_persona_catalog", "persona_catalog", []),
    ("fetch_keys_version", "keys_version", None),
    ("push_provider_keys", "push_keys", False),
]


@pytest.fixture
def capture(monkeypatch, caplog):
    for name in (catalog.logger.name, delivery.logger.name, "service.sidecar.agents"):
        logger = logging.getLogger(name)
        monkeypatch.setattr(logger, "handlers", [caplog.handler])
        monkeypatch.setattr(logger, "propagate", False)
        monkeypatch.setattr(logger, "disabled", False)
        monkeypatch.setattr(logger, "level", logging.DEBUG)
    return caplog


async def invoke(name):
    kwargs = {"version": 1, "overrides": {MARKER: MARKER}} if name == "push_provider_keys" else {}
    return await getattr(catalog, name)(None, **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("name,operation,expected", OPERATIONS)
@pytest.mark.parametrize(
    "kind,code",
    [
        (SidecarError, "unavailable"),
        (SidecarTimeout, "timeout"),
        (SidecarBadRequest, "invalid"),
        (SidecarUnavailable, "unavailable"),
    ],
)
async def test_catalog_typed_failure_has_safe_log_and_existing_fallback(
    name, operation, expected, kind, code, monkeypatch, capture
):
    request = AsyncMock(side_effect=kind(MARKER, MARKER, MARKER))
    client = SimpleNamespace(request_json=request, request=request)
    monkeypatch.setattr(catalog, "_client", lambda *_: client)
    assert await invoke(name) == expected
    request.assert_awaited_once()
    assert len(capture.records) == 1
    record = capture.records[0]
    assert MARKER not in str(record.__dict__)
    assert record.exc_info is None
    assert record.component == "agents" and record.operation == operation
    assert record.failure_code == code


@pytest.mark.asyncio
@pytest.mark.parametrize("name,operation,expected", OPERATIONS)
async def test_catalog_cancel_propagates_without_retry_or_log(
    name, operation, expected, monkeypatch, capture
):
    request = AsyncMock(side_effect=asyncio.CancelledError())
    monkeypatch.setattr(
        catalog, "_client", lambda *_: SimpleNamespace(request_json=request, request=request)
    )
    with pytest.raises(asyncio.CancelledError):
        await invoke(name)
    request.assert_awaited_once()
    assert not capture.records


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code", [(400, "invalid"), (500, "unavailable"), (504, "timeout")])
async def test_real_secret_push_transport_has_no_override_name_or_value(
    status, code, monkeypatch, capture
):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(status, json={"error": MARKER, "detail": MARKER})

    client = SidecarClient(
        service="agents",
        base_url="http://fixture.invalid",
        timeout=1,
        api_key=MARKER,
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setattr(catalog, "_client", lambda *_: client)
    assert await invoke("push_provider_keys") is False
    assert len(seen) == 1 and seen[0].headers["authorization"] == "Bearer " + MARKER
    assert MARKER.encode() in seen[0].content  # Private material still reaches its intended owner.
    assert len(capture.records) == 2
    assert all(
        MARKER not in str(record.__dict__)
        and record.exc_info is None
        and record.failure_code == code
        for record in capture.records
    )


@pytest.mark.asyncio
async def test_successful_empty_model_catalog_is_authoritative(monkeypatch, capture):
    request = AsyncMock(return_value={"models": [], "owners": {}})
    monkeypatch.setattr(catalog, "_client", lambda *_: SimpleNamespace(request_json=request))
    assert await catalog.fetch_chat_model_catalog(None) == ([], {})
    request.assert_awaited_once()
    assert not capture.records


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,code,expected",
    [
        (SidecarTimeout, MARKER, "timeout"),
        (SidecarUnavailable, MARKER, "remote"),
        (SidecarBadRequest, MARKER, "remote"),
        (SidecarError, MARKER, "unknown"),
        (SidecarUnavailable, "transport_error", "transport"),
        (SidecarError, "protocol_error", "protocol"),
    ],
)
async def test_outbox_failure_uses_type_or_exact_closed_code(
    kind, code, expected, monkeypatch, capture
):
    request = AsyncMock(side_effect=kind(MARKER, code, MARKER))
    monkeypatch.setattr(delivery, "_client", lambda _: SimpleNamespace(request_json=request))
    result = await delivery.deliver(None, {"action": "delete", "index_point_id": MARKER})
    assert result == delivery.DeliveryResult(False, expected)
    request.assert_awaited_once()
    assert len(capture.records) == 1
    record = capture.records[0]
    assert MARKER not in str(record.__dict__) and record.exc_info is None
    assert record.failure_code == expected and record.operation == "workflow_delivery"


@pytest.mark.asyncio
async def test_outbox_does_not_classify_private_text_by_substring(monkeypatch, capture):
    request = AsyncMock(side_effect=SidecarError(MARKER, "private-timeout-transport-http", MARKER))
    monkeypatch.setattr(delivery, "_client", lambda _: SimpleNamespace(request_json=request))
    assert await delivery.deliver(
        None, {"action": "delete", "index_point_id": MARKER}
    ) == delivery.DeliveryResult(False, "unknown")
    assert "private-timeout-transport-http" not in capture.text


@pytest.mark.asyncio
async def test_outbox_cancel_propagates_without_settlement_or_retry(monkeypatch, capture):
    request = AsyncMock(side_effect=asyncio.CancelledError())
    monkeypatch.setattr(delivery, "_client", lambda _: SimpleNamespace(request_json=request))
    with pytest.raises(asyncio.CancelledError):
        await delivery.deliver(None, {"action": "delete", "index_point_id": MARKER})
    request.assert_awaited_once()
    assert not capture.records


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"provider_keys": MARKER},
        {"provider_keys": [MARKER]},
        {"provider_keys": {"version": True}},
        {"provider_keys": {"version": MARKER}},
    ],
)
async def test_malformed_keys_health_is_unknown_not_a_version(payload, monkeypatch, capture):
    request = AsyncMock(return_value=payload)
    monkeypatch.setattr(catalog, "_client", lambda *_: SimpleNamespace(request_json=request))
    assert await catalog.fetch_keys_version(None) is None
    request.assert_awaited_once()
    assert MARKER not in capture.text


@pytest.mark.asyncio
async def test_unknown_delivery_failure_has_closed_diagnostics(monkeypatch, capture):
    request = AsyncMock(side_effect=ValueError(MARKER))
    monkeypatch.setattr(delivery, "_client", lambda _: SimpleNamespace(request_json=request))
    assert await delivery.deliver(
        None, {"action": "delete", "index_point_id": MARKER}
    ) == delivery.DeliveryResult(False, "unknown")
    request.assert_awaited_once()
    assert len(capture.records) == 1
    record = capture.records[0]
    assert MARKER not in str(record.__dict__) and record.exc_info is None
    assert record.failure_code == "unknown" and record.operation == "workflow_delivery"
