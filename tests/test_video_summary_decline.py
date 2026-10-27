from types import SimpleNamespace

import pytest

from service.domain.execution.context import PrivateRunResources, use_run_execution
from service.domain.subagents.general import GeneralAgent
from service.events import EventType


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_unconfirmed_transcription_never_falls_through_to_a_webpage_answer(
    monkeypatch, enabled
):
    monkeypatch.setattr("service.domain.pipeline.video_offer._video_offer_allowed", lambda: enabled)
    agent = GeneralAgent.__new__(GeneralAgent)
    agent.name = "general"
    with use_run_execution(PrivateRunResources()) as execution:
        events = [
            event
            async for event in agent.process(
                "https://www.youtube.com/watch?v=sXKnmgmbkoE Сделай транскрипцию видео",
                SimpleNamespace(video_tool_enabled=False),
            )
        ]
        assert execution.policy.flag("confirmation_pending") is enabled
        assert not execution.usage.receipts
        assert not any(event.type == EventType.STREAM_CHUNK for event in events)
        if enabled:
            assert events[-1].metadata["awaiting_confirmation"] is True
            assert events[0].metadata["mode_offer"]["mode"] == "watch_video"
        else:
            assert events[0].type == EventType.ERROR
            assert events[0].metadata["failure_code"] == "unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("task", "label"),
    [
        ("Сделай транскрипцию видео", "Готовлю файл расшифровки"),
        ("Сделай конспект видео", "Готовлю конспект-файл"),
    ],
)
async def test_explicit_video_task_has_an_accurate_start_label(monkeypatch, task, label):
    from service.domain.video_summary import pipeline

    agent = GeneralAgent.__new__(GeneralAgent)
    agent.name = "general"

    async def guard(_request):
        return None

    async def process(*args):
        if False:
            yield None

    agent._input_guardrail_block = guard
    monkeypatch.setattr(pipeline, "run_video_summary", process)
    events = [
        event
        async for event in agent.process(
            f"https://youtu.be/example {task}", SimpleNamespace(video_tool_enabled=True)
        )
    ]
    assert len(events) == 1
    assert events[0].type == EventType.AGENT_START
    assert events[0].data == label


@pytest.mark.asyncio
async def test_declined_video_summary_is_honest_without_authoring_or_file():
    agent = GeneralAgent.__new__(GeneralAgent)
    agent.name = "general"
    with use_run_execution(PrivateRunResources()) as execution:
        execution.policy.set_flag("confirmation_declined", True)
        events = [
            event
            async for event in agent.process(
                "https://youtu.be/uTR9FdR3Ob0 Нужно сделать полный конспект видео",
                SimpleNamespace(video_tool_enabled=False),
            )
        ]
        assert [event.type for event in events] == [
            EventType.STREAM_CHUNK,
            EventType.AGENT_COMPLETE,
        ]
        assert "Файл конспекта не создавался" in events[0].data
        assert "приват" not in events[0].data.lower()
        assert not execution.usage.receipts
        assert not any((event.metadata or {}).get("generated_files") for event in events)
