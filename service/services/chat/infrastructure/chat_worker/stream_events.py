"""Safe conversion of agent-sidecar events into the chat worker stream."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from service.infrastructure.agents_client.contracts.events import EventType


def make_agent_event_handler(
    *,
    publisher: Any,
    job_id: str,
    streamed_parts: list[str],
    workflow_observations: list[dict[str, Any]],
    workflow_executions: list[dict[str, Any]],
) -> Callable[[Any], None]:
    """Return the sole event bridge used by a worker run.

    Catalog observations deliberately remain inside the worker transaction: their
    request text must never be forwarded to Redis or a WebSocket consumer.
    """

    sequence = 0

    def on_event(event: Any) -> None:
        nonlocal sequence
        event_type = event.type.value if hasattr(event.type, "value") else str(event.type)
        metadata = getattr(event, "metadata", None) or {}
        kind = metadata.get("kind") if isinstance(metadata, dict) else None
        if event_type == EventType.STATUS_UPDATE and kind == "workflow_observed":
            observed = metadata.get("workflow_observed") or {}
            steps = observed.get("steps") if isinstance(observed, dict) else None
            if (
                isinstance(steps, list)
                and len(steps) >= 2
                and all(isinstance(step, str) and step for step in steps)
                and isinstance(observed.get("request_text"), str)
            ):
                workflow_observations.append(
                    {
                        "steps": steps,
                        "cost_class": str(observed.get("cost_class") or "cheap"),
                        "request_text": observed["request_text"],
                    }
                )
            return
        if event_type == EventType.STATUS_UPDATE and kind == "workflow_execution":
            execution = metadata.get("workflow_execution") or {}
            if isinstance(execution, dict) and execution.get("workflow_id"):
                workflow_executions.append(dict(execution))
        if event_type == EventType.STREAM_CHUNK and event.data:
            streamed_parts.append(str(event.data))
            publisher.publish_payload(
                {
                    "type": "stream_chunk",
                    "job_id": job_id,
                    "data": str(event.data),
                    "seq": sequence,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
            sequence += 1
            return
        publisher.publish_agent_event(event=event, job_id=job_id)

    return on_event
