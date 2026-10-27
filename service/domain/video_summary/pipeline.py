"""Explicit confirmed video notes: acquisition → every chunk → verified workspace file."""

from __future__ import annotations

import base64
import hashlib
from types import SimpleNamespace
from uuid import uuid4

from service.domain.execution.context import require_current_execution, set_policy_flag
from service.domain.runners.chat.stream_state import workspace_safe_boundary
from service.domain.runners.tool_runtime.progress import video_progress_event
from service.domain.tools.workspace.client import WorkspaceUnavailable, call
from service.domain.video_summary.acquisition import source_failure_message
from service.domain.video_summary.authoring import author_chunk
from service.domain.video_summary.evidence import (
    VideoEvidenceIndex,
    VideoNotesDraft,
    plain_markdown,
)
from service.domain.video_summary.render import checkpoint, render_part
from service.domain.video_summary.source import (
    RESULT_KEY,
    SOURCE_KEY,
    VideoSummaryArtifact,
    VideoSummaryFailure,
    VideoTranscript,
    requested_time_range,
    timestamp,
    video_request_kind,
)
from service.domain.video_summary.tools import VideoSummaryTools
from service.events import AgentEvent, EventType
from service.shared import deadline


def status(message: str) -> AgentEvent:
    return AgentEvent(type=EventType.STATUS_UPDATE, agent_name="general", data=message)


async def boundary(context, execution) -> list[AgentEvent]:
    if execution.cancelled or deadline.must_finalize():
        raise VideoSummaryFailure("cancelled" if execution.cancelled else "timeout")
    events = []
    state = SimpleNamespace(context=context, execution=execution)
    async for event in workspace_safe_boundary(state, agent_name="general"):
        if event is True:
            raise VideoSummaryFailure("cancelled" if execution.cancelled else "timeout")
        if isinstance(event, AgentEvent):
            if (event.metadata or {}).get("state") == "unavailable":
                raise VideoSummaryFailure("unavailable")
            events.append(event)
    return events


async def verified_file(ref: dict, path: str, content: str) -> None:
    """Download the written file privately; do not mistake truncated reads for success."""
    result = await call(ref, "files/download", {"path": path})
    try:
        encoded = result.get("content_b64")
        if not isinstance(encoded, str) or len(encoded) > 1_400_000:
            raise ValueError
        actual = base64.b64decode(encoded, validate=True)
    except (TypeError, ValueError):
        raise VideoSummaryFailure("protocol") from None
    if hashlib.sha256(actual).digest() != hashlib.sha256(content.encode()).digest():
        raise VideoSummaryFailure("conflict")


def transcript_document(source: VideoTranscript, interval: tuple[int, int] | None = None) -> str:
    completeness = (
        "Полная расшифровка по данным сервиса."
        if not source.truncated
        else "⚠️ Источник пометил расшифровку как неполную."
    )
    if interval is not None:
        completeness = (
            f"Расшифровка выбранного диапазона: {timestamp(interval[0])}–"
            f"{timestamp(interval[1])}. Границы определяются по началу сегментов; "
            "слова внутри пограничного сегмента не обрезаются."
        )
    cues = "\n".join(f"[{timestamp(cue.second)}] {plain_markdown(cue.text)}" for cue in source.cues)
    return (
        f"# Расшифровка: {plain_markdown(source.title)}\n\n"
        f"Источник: {source.url}\n\n{completeness}\n\n{cues}\n"
    )


def note_document(
    source: VideoTranscript,
    sections: list[str],
    *,
    complete: bool,
    interval: tuple[int, int] | None = None,
) -> str:
    scope = "Все части доступной расшифровки обработаны." if complete else "Неполный черновик."
    visual = "Конспект основан на речи; визуальные детали не проверялись."
    selection = (
        f"Выбранный диапазон: {timestamp(interval[0])}–{timestamp(interval[1])}.\n"
        if interval
        else ""
    )
    return (
        f"# Конспект видео: {plain_markdown(source.title)}\n\nИсточник: {source.url}\n\n"
        f"{scope}\n{selection}{visual}\n\n" + "\n\n".join(sections) + "\n"
    )


async def run_video_summary(agent, request: str, context, url: str):
    execution = require_current_execution()
    execution.policy.flags["video_summary_active"] = True
    ref = execution.resources.workspace_ref
    model = str(agent.model_settings.get("model") or "")
    tool_round = VideoSummaryTools(agent, context, execution).execute
    request_kind = video_request_kind(request)

    try:
        if not getattr(context, "video_tool_enabled", False):
            raise VideoSummaryFailure("policy")
        if not isinstance(ref, dict) or not ref.get("coordination_capability") or not model:
            raise VideoSummaryFailure("unavailable")
        # Reject malformed ranges before any metered source acquisition.
        interval = requested_time_range(request)
        set_policy_flag(context, "workspace_tools_enabled", True)
        for event in await boundary(context, execution):
            yield event
        async for event in tool_round("watch_video", {"url": url, "detail": "quick"}):
            yield event
        source = execution.artifacts.get(SOURCE_KEY, VideoTranscript)
        if source is None:
            raise VideoSummaryFailure("unavailable")
        if source.truncated:
            raise VideoSummaryFailure("protocol")
        yield video_progress_event({"stage": "source_ready"})
        folder = f"video-notes/{uuid4().hex}"
        for event in await boundary(context, execution):
            yield event
        yield video_progress_event({"stage": "workspace_save"})
        if request_kind == "transcript":
            path = folder + "/transcription.md"
            content = transcript_document(source.scoped(interval), interval)
            async for event in tool_round("ws_write", {"path": path, "content": content}):
                yield event
            await verified_file(ref, path, content)
            execution.artifacts.publish(
                RESULT_KEY, VideoSummaryArtifact.for_content(path, content, 0)
            )
            yield video_progress_event({"stage": "library_delivery"})
            yield AgentEvent(
                type=EventType.STREAM_CHUNK,
                agent_name="general",
                data="Расшифровка сохранена и проверена в Работе. "
                "Готовлю файл для скачивания из Библиотеки.",
            )
            yield AgentEvent(
                type=EventType.AGENT_COMPLETE,
                agent_name="general",
                data="Расшифровка готова",
            )
            return
        async for event in tool_round(
            "ws_write", {"path": folder + "/transcript.md", "content": source.markdown()}
        ):
            yield event
        index = VideoEvidenceIndex.create(source, interval)
        source = source.scoped(interval)
        chunks = index.chunks
        sections: list[str] = []
        drafts: list[VideoNotesDraft] = []
        for chunk in chunks:
            for event in await boundary(context, execution):
                yield event
            yield video_progress_event(
                {"stage": "authoring", "current": chunk.index + 1, "total": len(chunks)}
            )
            draft = await author_chunk(chunk, request, model, execution)
            drafts.append(draft)
            sections.append(render_part(draft, source.url))
            # A user can inspect accepted work after failure; no partial download card.
            for event in await boundary(context, execution):
                yield event
            async for event in tool_round(
                "ws_write", {"path": folder + "/authoring.json", "content": checkpoint(drafts)}
            ):
                yield event
            async for event in tool_round(
                "ws_write",
                {
                    "path": folder + "/draft.md",
                    "content": note_document(source, sections, complete=False, interval=interval),
                },
            ):
                yield event
        path = folder + f"/video-notes-{folder.rsplit('/', 1)[-1][:12]}.md"
        yield video_progress_event({"stage": "workspace_save"})
        content = note_document(source, sections, complete=True, interval=interval)
        for event in await boundary(context, execution):
            yield event
        async for event in tool_round("ws_write", {"path": path, "content": content}):
            yield event
        await verified_file(ref, path, content)
        execution.artifacts.publish(
            RESULT_KEY, VideoSummaryArtifact.for_content(path, content, len(chunks))
        )
        yield video_progress_event({"stage": "library_delivery"})
        yield AgentEvent(
            type=EventType.STREAM_CHUNK,
            agent_name="general",
            data="Конспект сохранён в рабочем месте. Готовлю файл для скачивания из Библиотеки.",
        )
    except Exception as exc:
        code = (
            exc.reason_code
            if isinstance(exc, WorkspaceUnavailable)
            else (exc.code if isinstance(exc, VideoSummaryFailure) else "internal")
        )
        code = (
            code
            if code
            in {"conflict", "unavailable", "timeout", "cancelled", "protocol", "policy", "invalid"}
            else "internal"
        )
        yield AgentEvent(
            type=EventType.ERROR,
            agent_name="general",
            data="Не удалось подготовить расшифровку."
            if request_kind == "transcript"
            else "Не удалось завершить конспект.",
            metadata={"failure_code": code},
        )
        recovery = source_failure_message(execution)
        yield AgentEvent(
            type=EventType.STREAM_CHUNK,
            agent_name="general",
            data=(
                recovery + " Готовый файл не создан."
                if recovery
                else (
                    "Не удалось подготовить файл расшифровки. Готовый файл не создан. "
                    "Если материалы уже сохранены, они остались в Работе."
                    if request_kind == "transcript"
                    else "Не удалось завершить конспект-файл. Если расшифровка или части конспекта "
                    "уже сохранены, они остались в Работе. Готовый файл не объявлен созданным."
                )
            ),
        )
    yield AgentEvent(
        type=EventType.AGENT_COMPLETE,
        agent_name="general",
        data="Подготовка расшифровки завершена"
        if request_kind == "transcript"
        else "Подготовка конспекта завершена",
    )
