"""Real HTTPX transport and media adapter diagnostics never expose private material."""

import asyncio
import logging
from unittest.mock import AsyncMock

import httpx
import pytest

from service.infrastructure.sidecar import (
    SidecarBadRequest,
    SidecarClient,
    SidecarError,
    SidecarTimeout,
    SidecarUnavailable,
)
from service.services.chat.infrastructure.media import openai_media_analysis_adapter as media

MARKER = "PRIVATE_SIDECAR_MEDIA_REQUEST_RESPONSE_MARKER"


@pytest.fixture
def capture(monkeypatch, caplog):
    # Scope assertions to product-owned diagnostics, not HTTPX's independent logger.
    for name in (
        "service.sidecar.whisper",
        "service.sidecar.other",
        f"service.sidecar.{MARKER}",
        media.logger.name,
    ):
        logger = logging.getLogger(name)
        monkeypatch.setattr(logger, "handlers", [caplog.handler])
        monkeypatch.setattr(logger, "propagate", False)
        monkeypatch.setattr(logger, "disabled", False)
        monkeypatch.setattr(logger, "level", logging.DEBUG)
    return caplog


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,kind,failure",
    [
        (400, SidecarBadRequest, "invalid"),
        (429, SidecarBadRequest, "invalid"),
        (500, SidecarUnavailable, "unavailable"),
        (504, SidecarTimeout, "timeout"),
    ],
)
@pytest.mark.parametrize("service", ["whisper", MARKER])
async def test_http_failure_logs_are_closed_but_internal_taxonomy_is_preserved(
    status, kind, failure, service, capture
):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, json={"error": MARKER, "detail": MARKER})

    client = SidecarClient(
        service=service,
        base_url="http://fixture.invalid",
        timeout=1,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(kind) as caught:
        await client.request_json("POST", "/" + MARKER, json_body={"private": MARKER})
    assert caught.value.code == MARKER and caught.value.detail == MARKER
    assert len(requests) == 1  # No automatic tool/request retry.
    assert len(capture.records) == 1
    record = capture.records[0]
    assert MARKER not in str(record.__dict__)
    assert record.exc_info is None
    assert record.failure_code == failure
    assert record.component == ("whisper" if service == "whisper" else "other")


@pytest.mark.asyncio
@pytest.mark.parametrize("service", ["whisper", MARKER])
async def test_success_diagnostic_contains_no_request_path(service, capture):
    client = SidecarClient(
        service=service,
        base_url="http://fixture.invalid",
        timeout=1,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"ok": 1})),
    )
    assert await client.request_json("GET", "/" + MARKER) == {"ok": 1}
    assert len(capture.records) == 1
    assert MARKER not in str(capture.records[0].__dict__)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,failure",
    [
        (SidecarBadRequest, "invalid"),
        (SidecarTimeout, "timeout"),
        (SidecarUnavailable, "unavailable"),
        (SidecarError, "unavailable"),
    ],
)
async def test_media_failure_is_bounded_and_preserves_fallback(kind, failure, monkeypatch, capture):
    request = AsyncMock(side_effect=kind(MARKER, MARKER, MARKER))
    monkeypatch.setattr(media, "_client", lambda _: type("Probe", (), {"request_json": request})())
    metadata = {}
    assert await media._sidecar_media("/" + MARKER, {"private": MARKER}, meta_out=metadata) is None
    request.assert_awaited_once()
    assert metadata == {}
    assert len(capture.records) == 1
    record = capture.records[0]
    assert MARKER not in str(record.__dict__)
    assert record.exc_info is None and record.failure_code == failure
    assert record.operation == "other"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,operation",
    [
        ("/media/describe-image", "describe_image"),
        ("/media/transcribe", "transcribe"),
    ],
)
async def test_real_media_http_failure_has_two_safe_diagnostics(
    path, operation, monkeypatch, capture
):
    client = SidecarClient(
        service="whisper",
        base_url="http://fixture.invalid",
        timeout=1,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(500, json={"error": MARKER, "detail": MARKER})
        ),
    )
    monkeypatch.setattr(media, "_client", lambda _: client)
    assert await media._sidecar_media(path, {"private": MARKER}) is None
    assert len(capture.records) == 2
    assert all(
        MARKER not in str(record.__dict__) and record.exc_info is None for record in capture.records
    )
    assert capture.records[-1].operation == operation


@pytest.mark.asyncio
async def test_media_cancel_propagates_without_fallback_log(monkeypatch, capture):
    request = AsyncMock(side_effect=asyncio.CancelledError())
    monkeypatch.setattr(media, "_client", lambda _: type("Probe", (), {"request_json": request})())
    with pytest.raises(asyncio.CancelledError):
        await media._sidecar_media("/media/transcribe", {"private": MARKER})
    request.assert_awaited_once()
    assert not capture.records


@pytest.mark.asyncio
async def test_media_success_preserves_usage_for_billing(monkeypatch, capture):
    usage = {"total": 42, "model": "fixture"}
    request = AsyncMock(return_value={"text": "fixture", "usage": usage})
    monkeypatch.setattr(media, "_client", lambda _: type("Probe", (), {"request_json": request})())
    metadata = {}
    assert await media._sidecar_media("/media/describe-image", {}, meta_out=metadata) == "fixture"
    assert metadata == {"text": "fixture", "usage": usage}
    request.assert_awaited_once()
    assert not capture.records
