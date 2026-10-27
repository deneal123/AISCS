"""Video transport admission, bounded reads and deterministic cleanup."""

import asyncio

import httpx
import pytest

from service.infrastructure import video_stream
from service.infrastructure.sidecar import SidecarClient, SidecarUnavailable


class ChunkStream(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.reads = 0
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            self.reads += 1
            yield chunk

    async def aclose(self):
        self.closed = True


def client_for(stream, content_type):
    def handle(_request):
        return httpx.Response(200, headers={"content-type": content_type}, stream=stream)

    return SidecarClient(
        service="video",
        base_url="http://video-fixture",
        timeout=2,
        transport=httpx.MockTransport(handle),
    )


@pytest.mark.asyncio
async def test_legacy_json_limit_stops_before_reading_entire_body(monkeypatch):
    monkeypatch.setattr(video_stream, "_MAX_FRAME_BYTES", 8)
    stream = ChunkStream([b"xxxx"] * 100)
    with pytest.raises(SidecarUnavailable) as error:
        await video_stream.acquire_video(client_for(stream, "application/json"), {}, "")
    assert error.value.code == "protocol"
    assert stream.reads <= 3
    assert stream.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("content_type", ["application/json", "application/x-ndjson"])
@pytest.mark.parametrize("raw", [b"PRIVATE-BODY\n", b"\xff\n", b"[]\n"])
async def test_malformed_wire_is_protocol_failure_not_transport(content_type, raw, caplog):
    stream = ChunkStream([raw])
    with pytest.raises(SidecarUnavailable) as error:
        await video_stream.acquire_video(client_for(stream, content_type), {}, "")
    assert error.value.code == "protocol"
    assert "PRIVATE" not in str(error.value) + caplog.text
    assert stream.closed and stream.reads == 1


@pytest.mark.asyncio
async def test_network_failure_retains_transport_classification(caplog):
    calls = 0

    def handle(request):
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("PRIVATE-NETWORK", request=request)

    client = SidecarClient(
        service="video",
        base_url="http://video-fixture",
        timeout=2,
        transport=httpx.MockTransport(handle),
    )
    with pytest.raises(SidecarUnavailable) as error:
        await video_stream.acquire_video(client, {}, "")
    assert error.value.code == "transport_error" and calls == 1
    assert "PRIVATE" not in str(error.value) + caplog.text


@pytest.mark.asyncio
async def test_fragmented_json_at_exact_limit_remains_supported(monkeypatch):
    raw = '{"title":"Видео","transcript":[]}'.encode()
    monkeypatch.setattr(video_stream, "_MAX_FRAME_BYTES", len(raw))
    stream = ChunkStream([bytes([item]) for item in raw])
    result = await video_stream.acquire_video(client_for(stream, "application/json"), {}, "")
    assert result == {"title": "Видео", "transcript": []}
    assert stream.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("content_type", ["application/json", "application/x-ndjson"])
async def test_cancellation_closes_pending_stream_without_retry(content_type):
    entered = asyncio.Event()

    class PendingStream(ChunkStream):
        async def __aiter__(self):
            self.reads += 1
            entered.set()
            await asyncio.Event().wait()
            yield b"{}"

    stream = PendingStream([])
    task = asyncio.create_task(video_stream.acquire_video(client_for(stream, content_type), {}, ""))
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stream.closed and stream.reads == 1
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
