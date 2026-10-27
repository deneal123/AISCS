import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service.services.chat.application.video_stt import stream as stream
from service.services.chat.application.video_stt.execution import (
    AuthorizedVideoSttJob,
    VideoSttFailure,
)


@pytest.fixture
def operation(monkeypatch):
    fetch = AsyncMock(return_value=SimpleNamespace(duration_sec=30, content=b"audio"))
    execute = AsyncMock(return_value={"text": "private transcript"})
    monkeypatch.setattr(stream, "fetch_video_audio", fetch)
    monkeypatch.setattr(stream, "WhisperLocalTranscriber", lambda: object())
    monkeypatch.setattr(stream, "VideoSttExecutor", lambda *args: SimpleNamespace(execute=execute))
    return fetch, execute, AuthorizedVideoSttJob("owner", "job", "base", "auto", 7200)


@pytest.mark.asyncio
async def test_source_reauthorizes_before_metered_stt(operation):
    fetch, execute, job = operation
    authorize = AsyncMock()
    response = stream.source_transcription_stream(
        job, redis=None, billing=None, url="private source", authorize=authorize
    )
    frames = [json.loads(part) async for part in response.body_iterator]
    assert [frame.get("stage") for frame in frames[:-1]] == ["download", "transcript"]
    assert frames[-1] == {"type": "result", "result": {"text": "private transcript"}}
    authorize.assert_awaited_once()
    assert execute.await_args.args[0].duration_limit_sec == 31
    assert all("private" not in str(frame) for frame in frames[:-1])
    fetch.assert_awaited_once()


@pytest.mark.asyncio
async def test_terminal_job_cannot_start_stt_after_download(operation):
    _, execute, job = operation
    response = stream.source_transcription_stream(
        job,
        redis=None,
        billing=None,
        url="private source",
        authorize=AsyncMock(side_effect=VideoSttFailure("forbidden")),
    )
    frames = [json.loads(part) async for part in response.body_iterator]
    assert frames[-1] == {"type": "error", "code": "forbidden"}
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_source_error_does_not_disclose_body_or_start_stt(operation):
    fetch, execute, job = operation
    fetch.side_effect = RuntimeError("private credentials body")
    response = stream.source_transcription_stream(
        job, redis=None, billing=None, url="private source", authorize=AsyncMock()
    )
    frames = [json.loads(part) async for part in response.body_iterator]
    assert frames[-1] == {"type": "error", "code": "unavailable"}
    assert "private" not in str(frames)
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_disconnect_cancels_and_joins_download(operation):
    fetch, execute, job = operation
    started, stopped = asyncio.Event(), asyncio.Event()

    async def download(*args, **kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    fetch.side_effect = download
    response = stream.source_transcription_stream(
        job, redis=None, billing=None, url="private source", authorize=AsyncMock()
    )
    await anext(response.body_iterator)
    await started.wait()
    await response.body_iterator.aclose()
    assert stopped.is_set()
    execute.assert_not_awaited()
