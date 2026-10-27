"""Scoped, bounded progress while a tool is awaiting an integration."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import Any

from service.events import AgentEvent, EventType

VIDEO_STAGES = frozenset(
    {
        "probe",
        "proxy_retry",
        "download",
        "frames",
        "transcript",
        "source_ready",
        "authoring",
        "workspace_save",
        "library_delivery",
    }
)
_REPORT: ContextVar[Callable[[dict], None] | None] = ContextVar("tool_progress", default=None)


def video_progress_event(payload: Any) -> AgentEvent:
    return AgentEvent(
        type=EventType.STATUS_UPDATE,
        agent_name="general",
        data="",
        metadata={"kind": "video_progress", "video_progress": payload},
    )


def report_video_progress(payload: dict) -> None:
    callback = _REPORT.get()
    if callback is not None:
        callback(payload)


async def execute_with_progress(operation: Awaitable):
    """Yield progress and then one result; preserve tool ordering and cancellation."""
    queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=32)

    def report(payload: dict) -> None:
        if payload.get("stage") in VIDEO_STAGES and not queue.full():
            queue.put_nowait(payload)

    token = _REPORT.set(report)
    task = asyncio.create_task(operation)
    reader = None
    try:
        while not task.done() or not queue.empty():
            reader = asyncio.create_task(queue.get())
            done, _ = await asyncio.wait({task, reader}, return_when=asyncio.FIRST_COMPLETED)
            if reader in done:
                yield video_progress_event(reader.result())
            else:
                reader.cancel()
                await asyncio.gather(reader, return_exceptions=True)
            reader = None
        yield task.result()
    finally:
        _REPORT.reset(token)
        for pending in (reader, task):
            if pending is not None and not pending.done():
                pending.cancel()
        await asyncio.gather(*(p for p in (reader, task) if p is not None), return_exceptions=True)
