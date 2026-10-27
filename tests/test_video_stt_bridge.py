import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from service.domain.execution.context import PrivateRunResources, use_run_execution
from service.domain.runners.tool_runtime.progress import execute_with_progress
from service.domain.tools import unbilled_calls, video_tool
from service.domain.video_summary.source import SOURCE_KEY, VideoTranscript
from service.infrastructure.sidecar import SidecarUnavailable
from service.infrastructure.video_stt import acquire_local_transcript

REF = {
    "video_stt": {"endpoint": "http://backend/internal/video-stt/from-video", "grant": "private"}
}
RESULT = {
    "text": "source words",
    "duration_sec": 30,
    "segments": [{"t_sec": 0, "end_sec": 30, "text": "source words"}],
}


def transport(frames):
    def handle(request):
        assert request.headers["authorization"] == "Bearer private"
        assert request.url.path == "/internal/video-stt/from-video"
        return httpx.Response(
            200,
            headers={"content-type": "application/x-ndjson"},
            content="".join(json.dumps(frame) + "\n" for frame in frames),
        )

    return httpx.MockTransport(handle)


@pytest.mark.asyncio
async def test_private_stt_projects_only_bounded_progress():
    frames = [
        {"type": "progress", "stage": "transcript", "elapsed_sec": 7, "raw": "private"},
        {"type": "result", "result": RESULT},
    ]
    with use_run_execution(PrivateRunResources(workspace_ref=REF)) as execution:
        execution.policy.set_flag("video_summary_active", True)
        received = [
            part
            async for part in execute_with_progress(
                acquire_local_transcript("private url", transport=transport(frames))
            )
        ]
        assert received[-1]["transcript"] == RESULT["segments"]
        assert "private" not in str(received[:-1])
        assert len(received) == 2
        assert not execution.usage.receipts


@pytest.mark.asyncio
async def test_without_confirmed_job_binding_does_not_access_backend():
    handle = AsyncMock()
    with use_run_execution(PrivateRunResources(workspace_ref=REF)):
        assert await acquire_local_transcript("url", transport=httpx.MockTransport(handle)) is None
    with use_run_execution(PrivateRunResources()) as execution:
        execution.policy.set_flag("video_summary_active", True)
        assert await acquire_local_transcript("url", transport=httpx.MockTransport(handle)) is None
    handle.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result", [None, {}, {**RESULT, "text": "invented"}, {**RESULT, "duration_sec": -1}]
)
async def test_invalid_result_is_not_a_transcript(result):
    with use_run_execution(PrivateRunResources(workspace_ref=REF)) as execution:
        execution.policy.set_flag("video_summary_active", True)
        with pytest.raises(SidecarUnavailable, match="protocol"):
            await acquire_local_transcript(
                "url", transport=transport([{"type": "result", "result": result}])
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["duration_sec", "t_sec", "end_sec"])
@pytest.mark.parametrize(
    "value",
    [10**1000, -(10**1000), float("nan"), float("inf")],
    ids=["huge_positive", "huge_negative", "nan", "infinity"],
)
async def test_unbounded_transcript_numbers_have_closed_protocol_failure(field, value):
    result = {**RESULT, "segments": [dict(RESULT["segments"][0])]}
    if field == "duration_sec":
        result[field] = value
    else:
        result["segments"][0][field] = value
    with use_run_execution(PrivateRunResources(workspace_ref=REF)) as execution:
        execution.policy.set_flag("video_summary_active", True)
        with pytest.raises(SidecarUnavailable) as error:
            await acquire_local_transcript(
                "url", transport=transport([{"type": "result", "result": result}])
            )
        assert error.value.code == "protocol"
        assert not execution.usage.receipts


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [123, ["source words"], {"source": "words"}])
async def test_aggregate_transcript_requires_text_not_stringified_json(value):
    result = {
        **RESULT,
        "text": value,
        "segments": [{**RESULT["segments"][0], "text": str(value)}],
    }
    with use_run_execution(PrivateRunResources(workspace_ref=REF)) as execution:
        execution.policy.set_flag("video_summary_active", True)
        with pytest.raises(SidecarUnavailable) as error:
            await acquire_local_transcript(
                "url", transport=transport([{"type": "result", "result": result}])
            )
        assert error.value.code == "protocol"
        assert not execution.usage.receipts


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code,expected",
    [
        ("source_access_challenge", "source_access_challenge"),
        ("source_rate_limited", "source_rate_limited"),
        ("source_access_denied", "source_access_denied"),
        ("timeout", "timeout"),
        ("private-provider-body", "unavailable"),
        ({"private": "marker"}, "unavailable"),
    ],
)
async def test_private_failure_is_closed_and_source_reason_is_preserved(code, expected):
    with use_run_execution(PrivateRunResources(workspace_ref=REF)) as execution:
        execution.policy.set_flag("video_summary_active", True)
        with pytest.raises(SidecarUnavailable) as error:
            await acquire_local_transcript(
                "url", transport=transport([{"type": "error", "code": code}])
            )
        assert error.value.code == expected
        assert "private-provider-body" not in str(error.value)
        assert not execution.usage.receipts


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", [False, True])
async def test_tool_fallback_publishes_source_without_watch_surcharge(monkeypatch, missing):
    acquire = AsyncMock(
        return_value={"frames": [], "transcript": []},
        side_effect=None if missing else SidecarUnavailable("video", "toolchain_failed"),
    )
    fallback = AsyncMock(return_value={"duration_sec": 30, "transcript": RESULT["segments"]})
    monkeypatch.setattr(video_tool, "_client", lambda: object())
    monkeypatch.setattr(video_tool, "acquire_video", acquire)
    monkeypatch.setattr("service.infrastructure.video_stt.acquire_local_transcript", fallback)
    with (
        use_run_execution(PrivateRunResources(workspace_ref=REF)) as execution,
        unbilled_calls.collect(),
    ):
        execution.policy.set_flag("video_summary_active", True)
        unbilled_calls.count_call("watch_video")
        reply = await video_tool.watch_video_tool(SimpleNamespace(context=None), '{"url":"url"}')
        assert isinstance(reply, str)
        assert execution.artifacts.get(SOURCE_KEY, VideoTranscript).cues[0].text == "source words"
        assert not unbilled_calls.billable("watch_video")
        acquire.assert_awaited_once()
        fallback.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancel_closes_private_backend_stream():
    stopped = asyncio.Event()

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"type":"progress","stage":"download"}\n'
            await asyncio.Event().wait()

        async def aclose(self):
            stopped.set()

    with use_run_execution(PrivateRunResources(workspace_ref=REF)) as execution:
        execution.policy.set_flag("video_summary_active", True)
        task = asyncio.create_task(
            acquire_local_transcript(
                "url",
                transport=httpx.MockTransport(
                    lambda _: httpx.Response(
                        200, headers={"content-type": "application/x-ndjson"}, stream=Body()
                    )
                ),
            )
        )
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stopped.is_set()
