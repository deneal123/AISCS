import json

from service.infrastructure.agents_client.contracts.events import (
    AgentEvent,
    EventSerializer,
    EventType,
)


def test_video_progress_projection_does_not_carry_source_or_response():
    event = AgentEvent(
        type=EventType.STATUS_UPDATE,
        data="PRIVATE",
        metadata={
            "kind": "video_progress",
            "capability": "PRIVATE",
            "video_progress": {
                "stage": "transcript",
                "elapsed_sec": 15,
                "url": "PRIVATE",
                "result": "PRIVATE",
            },
        },
    )
    payload = EventSerializer().serialize(event=event, job_id="opaque-job")
    assert "PRIVATE" not in json.dumps(payload)
    assert payload["metadata"] == {
        "kind": "video_progress",
        "video_progress": {
            "stage": "transcript",
            "elapsed_sec": 15,
            "heartbeat": False,
        },
    }


def test_malformed_video_stage_is_neutral_and_cannot_break_transport():
    event = AgentEvent(
        type=EventType.STATUS_UPDATE,
        metadata={
            "kind": "video_progress",
            "video_progress": {
                "stage": ["not a stage"],
                "elapsed_sec": "PRIVATE",
                "current": True,
            },
        },
    )
    assert event.model_dump()["metadata"]["video_progress"] == {"heartbeat": False}
