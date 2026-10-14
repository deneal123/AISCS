"""Incoming import bodies must stop at the byte budget and close on every exit."""

import asyncio

import httpx
import pytest
from application import importer


class TrackedBody(httpx.AsyncByteStream):
    def __init__(self, chunks, failure=None, delay=0):
        self.chunks = chunks
        self.failure = failure
        self.consumed = 0
        self.closed = False
        self.delay = delay

    async def __aiter__(self):
        for chunk in self.chunks:
            if self.delay:
                await asyncio.sleep(self.delay)
            self.consumed += 1
            yield chunk
        if self.failure:
            raise self.failure

    async def aclose(self):
        self.closed = True


def install_transport(monkeypatch, body, status=200):
    original = httpx.AsyncClient

    async def public(_host):
        return None

    def response(_request):
        return httpx.Response(status, stream=body)

    monkeypatch.setattr(importer, "assert_public_host", public)
    monkeypatch.setattr(importer, "MAX_FILE_BYTES", 10)
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(response), **kw)
    )


async def test_over_budget_body_stops_before_remaining_chunks(monkeypatch):
    body = TrackedBody([b"123456", b"78901", b"never read"])
    install_transport(monkeypatch, body)
    with pytest.raises(importer.ImportRefused, match="10"):
        await importer.fetch("https://example.test/file")
    assert body.consumed == 2
    assert body.closed


async def test_exact_budget_body_is_accepted_and_closed(monkeypatch):
    body = TrackedBody([b"123456", b"7890"])
    install_transport(monkeypatch, body)
    assert await importer.fetch("https://example.test/file") == b"1234567890"
    assert body.closed


@pytest.mark.parametrize("status", [302, 403, 503])
async def test_rejected_status_does_not_consume_body(monkeypatch, status):
    body = TrackedBody([b"private body"])
    install_transport(monkeypatch, body, status)
    with pytest.raises(importer.ImportRefused):
        await importer.fetch("https://example.test/file")
    assert body.consumed == 0
    assert body.closed


async def test_cancelled_stream_closes_without_conversion(monkeypatch):
    body = TrackedBody([b"123"], asyncio.CancelledError())
    install_transport(monkeypatch, body)
    with pytest.raises(asyncio.CancelledError):
        await importer.fetch("https://example.test/file")
    assert body.closed


async def test_midstream_transport_failure_is_bounded(monkeypatch, caplog):
    body = TrackedBody([b"123"], httpx.ReadError("PRIVATE_BODY_SENTINEL"))
    install_transport(monkeypatch, body)
    with pytest.raises(importer.ImportRefused, match="temporarily unavailable") as caught:
        await importer.fetch("https://example.test/file")
    assert body.closed
    assert "PRIVATE_BODY_SENTINEL" not in str(caught.value)
    assert "PRIVATE_BODY_SENTINEL" not in caplog.text


async def test_total_deadline_stops_a_body_which_keeps_making_progress(monkeypatch):
    body = TrackedBody([b"x"] * 5, delay=0.03)
    install_transport(monkeypatch, body)
    with pytest.raises(importer.ImportRefused, match="temporarily unavailable"):
        await asyncio.wait_for(importer.fetch("https://example.test/file", timeout_sec=0.05), 1)
    assert body.consumed < 5
    assert body.closed


async def test_total_deadline_includes_address_validation(monkeypatch):
    body = TrackedBody([b"x"])
    install_transport(monkeypatch, body)
    completed = False

    async def slow_validation(_host):
        nonlocal completed
        await asyncio.sleep(0.15)
        completed = True

    monkeypatch.setattr(importer, "assert_public_host", slow_validation)
    with pytest.raises(importer.ImportRefused, match="temporarily unavailable"):
        await asyncio.wait_for(importer.fetch("https://example.test/file", timeout_sec=0.05), 1)
    assert not completed
    assert body.consumed == 0
