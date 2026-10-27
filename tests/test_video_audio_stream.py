import asyncio
import hashlib

import httpx
import pytest

from service.services.chat.application.video_stt.execution import VideoSttFailure
from service.services.chat.infrastructure.media.video_audio import fetch_video_audio


class AudioStream(httpx.AsyncByteStream):
    def __init__(self, chunks, *, delay=0):
        self.chunks = chunks
        self.delay = delay
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            if self.delay:
                await asyncio.sleep(self.delay)
            yield chunk

    async def aclose(self):
        self.closed = True


def response(stream, *, headers=None, status=200):
    metadata = {
        "content-type": "audio/mpeg",
        "content-length": "5",
        "x-audio-duration": "12",
        "x-audio-sha256": hashlib.sha256(b"audio").hexdigest(),
    }
    metadata.update(headers or {})
    return httpx.Response(status, headers=metadata, stream=stream)


async def fetch(result, *, timeout=1):
    async def handle(request):
        assert request.url.path == "/audio"
        assert request.headers["authorization"] == "Bearer private-test-key"
        return result

    return await fetch_video_audio(
        "http://video",
        "private-test-key",
        "https://youtu.be/sXKnmgmbkoE",
        timeout_sec=timeout,
        transport=httpx.MockTransport(handle),
    )


@pytest.mark.asyncio
async def test_verified_stream_is_bounded_and_closed():
    stream = AudioStream([b"au", b"dio"])
    result = await fetch(response(stream))
    assert result.content == b"audio"
    assert result.duration_sec == 12
    assert result.sha256 == hashlib.sha256(b"audio").hexdigest()
    assert "audio" not in repr(result).split("duration_sec")[0]
    assert stream.closed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers",
    [
        {"content-length": "999999999"},
        {"content-type": "text/html"},
        {"x-audio-duration": "nan"},
        {"x-audio-sha256": "0" * 64},
        {"content-length": "6"},
    ],
)
async def test_invalid_audio_never_crosses_stt_boundary(headers):
    stream = AudioStream([b"audio"])
    with pytest.raises(VideoSttFailure):
        await fetch(response(stream, headers=headers))
    assert stream.closed


@pytest.mark.asyncio
async def test_actual_size_ceiling_is_enforced_on_chunks():
    stream = AudioStream([b"audio", b"too much"])
    with pytest.raises(VideoSttFailure, match="too_large"):
        await fetch(response(stream))
    assert stream.closed


@pytest.mark.asyncio
async def test_read_deadline_closes_stream():
    stream = AudioStream([b"audio"], delay=1)
    with pytest.raises(VideoSttFailure, match="unavailable"):
        await fetch(response(stream), timeout=0.01)
    assert stream.closed


@pytest.mark.asyncio
async def test_redirect_not_followed_and_error_body_not_consumed():
    stream = AudioStream([b"private body with credentials"])
    with pytest.raises(VideoSttFailure, match="unavailable"):
        await fetch(response(stream, status=302, headers={"location": "http://127.0.0.1"}))
    assert stream.closed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,header,expected",
    [
        (502, "source_access_challenge", "source_access_challenge"),
        (502, "source_rate_limited", "source_rate_limited"),
        (502, "source_access_denied", "source_access_denied"),
        (502, "watch_timeout", "timeout"),
        (413, "too_long", "too_long"),
        (502, "private-credential-marker", "unavailable"),
        (302, "source_access_challenge", "unavailable"),
        (401, "source_access_challenge", "unavailable"),
    ],
)
async def test_only_allowlisted_source_headers_cross_boundary(status, header, expected):
    class UnreadableError(AudioStream):
        async def __aiter__(self):
            raise AssertionError("error_body_must_not_be_read")
            yield b""

    stream = UnreadableError([])
    with pytest.raises(VideoSttFailure) as error:
        await fetch(response(stream, status=status, headers={"x-video-failure": header}))
    assert error.value.code == expected
    assert stream.closed
