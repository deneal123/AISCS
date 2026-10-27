import asyncio
import json

import httpx
import pytest

from service.application.reply_assembler import ReplyAssembler
from service.domain.runners.tool_runtime.progress import (
    execute_with_progress,
    report_video_progress,
)
from service.events import AgentEvent, EventSerializer, EventType
from service.infrastructure.sidecar import SidecarClient, SidecarError
from service.infrastructure.video_stream import acquire_video


def test_progress_never_overwrites_reply_billing_kind():
    assembler = ReplyAssembler()
    assembler.metadata = {"kind": "video_summary"}
    assembler.consume(
        event=AgentEvent(
            type=EventType.STATUS_UPDATE,
            metadata={"kind": "video_progress", "video_progress": {"stage": "download"}},
        ),
        stream_chunk_type=EventType.STREAM_CHUNK,
        error_type=EventType.ERROR,
        structured_output_type=EventType.STRUCTURED_OUTPUT,
    )
    assert assembler.metadata == {"kind": "video_summary"}


@pytest.mark.asyncio
async def test_progress_is_visible_before_tool_finishes_and_does_not_repeat_execution():
    gate = asyncio.Event()
    calls = 0

    async def work():
        nonlocal calls
        calls += 1
        report_video_progress({"stage": "download", "url": "PRIVATE", "elapsed_sec": 8})
        await gate.wait()
        return ["outcome"]

    events = execute_with_progress(work())
    first = await anext(events)
    assert first.metadata["video_progress"] == {
        "stage": "download",
        "elapsed_sec": 8,
        "heartbeat": False,
    }
    gate.set()
    assert [item async for item in events] == [["outcome"]]
    assert calls == 1


@pytest.mark.asyncio
async def test_close_relay_cancels_inflight_tool_and_clears_callback():
    cancelled = asyncio.Event()

    async def work():
        report_video_progress({"stage": "download"})
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    stream = execute_with_progress(work())
    await anext(stream)
    await stream.aclose()
    assert cancelled.is_set()
    report_video_progress({"stage": "download"})


def test_serializer_redacts_untrusted_progress_fields_and_data():
    event = AgentEvent(
        type=EventType.STATUS_UPDATE,
        data="PRIVATE",
        metadata={
            "kind": "video_progress",
            "url": "PRIVATE",
            "video_progress": {
                "stage": "download",
                "current": -1,
                "total": True,
                "schema": "PRIVATE",
            },
        },
    )
    for serialized in (event.model_dump(), EventSerializer().serialize(event=event, job_id="job")):
        assert "PRIVATE" not in json.dumps(serialized)
        assert serialized["metadata"]["video_progress"] == {
            "stage": "download",
            "heartbeat": False,
        }


@pytest.mark.asyncio
async def test_private_stream_delivers_transcript_but_only_projects_safe_progress():
    frames = [
        {"type": "progress", "stage": "transcript", "url": "PRIVATE"},
        {"type": "result", "result": {"transcript": [{"text": "PRIVATE"}]}},
    ]

    async def handler(request):
        assert request.headers["accept"] == "application/x-ndjson"
        return httpx.Response(
            200,
            headers={"Content-Type": "application/x-ndjson"},
            content="\n".join(json.dumps(frame) for frame in frames) + "\n",
        )

    client = SidecarClient(
        service="video", base_url="http://video", timeout=1, transport=httpx.MockTransport(handler)
    )
    events = [item async for item in execute_with_progress(acquire_video(client, {}, "key"))]
    assert events[-1]["transcript"][0]["text"] == "PRIVATE"
    assert "PRIVATE" not in events[0].model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code",
    ["watch_timeout", "source_rate_limited", "source_access_challenge", "source_access_denied"],
)
async def test_stream_failure_does_not_retry_or_return_phantom_success(code):
    count = 0

    async def handler(request):
        nonlocal count
        count += 1
        return httpx.Response(
            200,
            headers={"Content-Type": "application/x-ndjson"},
            content=json.dumps({"type": "error", "status": 504, "code": code}) + "\n",
        )

    client = SidecarClient(
        service="video", base_url="http://video", timeout=1, transport=httpx.MockTransport(handler)
    )
    with pytest.raises(SidecarError) as failure:
        await acquire_video(client, {}, "key")
    assert failure.value.code == code
    assert count == 1
