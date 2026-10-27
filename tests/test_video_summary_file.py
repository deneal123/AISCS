from __future__ import annotations

import base64
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from service.domain.execution.context import PrivateRunResources, use_run_execution
from service.domain.integration_failure import IntegrationFailureCode
from service.domain.pipeline.processor_flow import build_user_context
from service.domain.runners.chat.tool_loop import ToolRoundMixin
from service.domain.tools import unbilled_calls, video_tool
from service.domain.tools.workspace import tools as workspace_tools
from service.domain.tools.workspace.client import WorkspaceUnavailable
from service.domain.video_summary import authoring, pipeline
from service.domain.video_summary.evidence import VideoEvidenceIndex
from service.domain.video_summary.source import (
    RESULT_KEY,
    SOURCE_KEY,
    VideoSummaryArtifact,
    VideoSummaryFailure,
    VideoTranscript,
    summary_video_url,
    video_request_kind,
)
from service.events import EventType
from service.infrastructure.sidecar import SidecarUnavailable
from service.infrastructure.video_stt import acquire_local_transcript

URL = "https://youtu.be/example"
REQUEST = URL + " Нужно сделать полный конспект видео"
REF = {
    "workspace_id": "w",
    "token": "private",
    "user_id": "u",
    "coordination_capability": "private",
}


def transcript(count=560):
    return {
        "title": "Example",
        "duration_sec": 684,
        "frames": [],
        "transcript": [{"t_sec": i, "text": f"PRIVATE-CUE-{i} " + "x" * 60} for i in range(count)],
    }


def test_every_cue_survives_description_budget_and_partitioning():
    source = VideoTranscript.from_response(URL, transcript())
    assert source is not None
    chunks = source.chunks()
    assert len(chunks) > 1
    for i in range(560):
        assert f"PRIVATE-CUE-{i} " in source.markdown()
        assert sum(f"PRIVATE-CUE-{i} " in chunk.text for chunk in chunks) == 1
    assert "PRIVATE-CUE-559" in chunks[-1].text


def test_long_single_cue_is_not_silently_clipped():
    raw = transcript(1)
    raw["transcript"][0]["text"] = "z" * 22000 + "LAST-MARKER"
    source = VideoTranscript.from_response(URL, raw)
    assert source is not None
    parts = [chunk.text.split("] ", 1)[1] for chunk in source.chunks()]
    assert "".join(parts) == raw["transcript"][0]["text"]


@pytest.mark.parametrize(
    "change",
    [
        {"duration_sec": "invalid"},
        {"duration_sec": float("nan")},
        {"transcript": [{"t_sec": -1, "text": "x"}]},
        {"transcript": [{"t_sec": 3, "text": "x"}, {"t_sec": 1, "text": "y"}]},
        {"transcript": [{"t_sec": 1, "text": "x" * 750001}]},
    ],
)
def test_invalid_sources_fail_closed(change):
    with pytest.raises(VideoSummaryFailure):
        VideoTranscript.from_response(URL, {**transcript(), **change})


def test_recognition_is_explicit_and_does_not_accept_spoofed_hosts():
    assert summary_video_url(REQUEST) == URL
    assert summary_video_url(f"[{URL}]({URL}) Сделай конспект") == URL
    assert summary_video_url(URL + " посмотри") is None
    assert summary_video_url("https://youtu.be.evil.test/v конспект") is None
    assert summary_video_url(REQUEST + " https://youtu.be/other") is None
    assert summary_video_url(REQUEST + " в PDF") is None
    assert summary_video_url(REQUEST + " как презентацию") is None


class Agent(ToolRoundMixin):
    name = "general"
    model_settings = {"model": "test-model"}


@pytest.fixture
def runtime(monkeypatch):
    files = {}
    calls = []
    raw = transcript()
    state = {"fail_write": None, "fail_model": False, "corrupt_download": False}

    class Client:
        available = True

        async def request_json(self, *args, **kwargs):
            calls.append("watch_video")
            return raw

    async def call(ref, operation, body):
        calls.append(operation)
        if operation == "collaboration/boundary":
            return {"state": "running"}
        if operation == "files/write":
            if state["fail_write"]:
                raise WorkspaceUnavailable(state["fail_write"])
            files[body["path"]] = body["content"]
            return {"written": True, "revision": "rev", "path": body["path"]}
        if operation == "files/download":
            text = "bad" if state["corrupt_download"] else files[body["path"]]
            return {"content_b64": base64.b64encode(text.encode()).decode()}
        raise AssertionError(operation)

    async def model(**kwargs):
        calls.append("model")
        if state["fail_model"]:
            raise RuntimeError("SECRET-PROVIDER-BODY")
        source = json.loads(kwargs["messages"][2]["content"].split("\n", 1)[1])
        assert "до 3 тезисов" in kwargs["messages"][0]["content"]
        assert "максимум 9 тезисов" in kwargs["messages"][0]["content"]
        groups = json.loads(kwargs["messages"][3]["content"].split("Группы cue_ids: ", 1)[1])
        assert [cid for group in groups for cid in group] == [cue["cue_id"] for cue in source]
        assert len(groups) == 3
        scopes = kwargs["tools"][0]["function"]["parameters"]["properties"]
        arguments = {}
        for name, scope in scopes.items():
            item = scope["properties"]["primary"]["properties"]["points"]["items"]
            ids = item["properties"]["evidence"]["items"]["properties"]["cue_ids"]["items"]["enum"]
            points = [
                {
                    "text": "Сведения источника",
                    "evidence": [{"cue_ids": [cue["cue_id"]], "quote": cue["text"]}],
                }
                for cue in source
                if cue["cue_id"] in ids
            ]
            arguments[name] = {"primary": {"title": "Раздел", "points": points[:3]}}
        # A scripted provider returns deterministic notes, with one real ledger receipt.
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="tool_calls",
                    message=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                function=SimpleNamespace(
                                    name="submit_video_notes", arguments=json.dumps(arguments)
                                )
                            )
                        ],
                    ),
                )
            ],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50),
        )

    monkeypatch.setattr(video_tool, "_client", lambda: Client())
    monkeypatch.setattr(workspace_tools, "call", call)
    monkeypatch.setattr(pipeline, "call", call)
    monkeypatch.setattr("service.domain.runners.chat.workspace_control.workspace_call", call)
    monkeypatch.setattr(authoring, "create_chat_completion", model)
    monkeypatch.setattr(authoring, "prompt_budget_per_run", lambda: 40000)
    return files, calls, raw, state


async def run_summary(consent=True, request=REQUEST):
    context = build_user_context(
        user_id="u",
        session=None,
        thread_id="t",
        workspace_ref=REF,
        video_tool_enabled=consent,
    )
    return [event async for event in pipeline.run_video_summary(Agent(), request, context, URL)]


@pytest.mark.asyncio
async def test_explicit_transcript_is_saved_without_llm_authoring(runtime):
    files, calls, raw, _ = runtime
    request = f"Сделай расшифровку видео {URL}"

    with use_run_execution(PrivateRunResources(workspace_ref=REF)) as execution:
        events = await run_summary(consent=True, request=request)

        result = execution.artifacts.get(RESULT_KEY, VideoSummaryArtifact)
        assert result is not None
        assert result.chunks == 0

    saved = files[result.path]
    assert "# Расшифровка: Example" in saved
    assert raw["transcript"][0]["text"] in saved
    assert raw["transcript"][-1]["text"] in saved
    assert calls.count("model") == 0
    assert calls.count("files/write") == 1
    assert any(event.data == "Расшифровка готова" for event in events)


@pytest.mark.asyncio
@pytest.mark.parametrize("interval", [False, True])
async def test_private_stt_to_verified_transcript_respects_range(runtime, monkeypatch, interval):
    files, calls, _, _ = runtime
    cues = [
        {"t_sec": 0, "end_sec": 5, "text": "PRIVATE-FIRST"},
        {"t_sec": 10, "end_sec": 15, "text": "PRIVATE-MIDDLE"},
        {"t_sec": 20, "end_sec": 25, "text": "PRIVATE-LAST"},
    ]
    result = {"duration_sec": 30, "segments": cues, "text": "\n".join(c["text"] for c in cues)}
    requests = []

    def backend(request):
        requests.append(request)
        assert request.headers["authorization"] == "Bearer private"
        return httpx.Response(
            200,
            headers={"content-type": "application/x-ndjson"},
            content=json.dumps({"type": "result", "result": result}) + "\n",
        )

    async def bridge(url):
        return await acquire_local_transcript(url, transport=httpx.MockTransport(backend))

    monkeypatch.setattr(
        video_tool,
        "acquire_video",
        AsyncMock(side_effect=SidecarUnavailable("video", "toolchain_failed")),
    )
    monkeypatch.setattr("service.infrastructure.video_stt.acquire_local_transcript", bridge)
    ref = {
        **REF,
        "video_stt": {
            "endpoint": "http://backend/internal/video-stt/from-video",
            "grant": "private",
        },
    }
    request = f"Сделай транскрипцию видео {URL}" + (" с 00:10 до 00:20" if interval else "")
    with (
        use_run_execution(PrivateRunResources(workspace_ref=ref)) as execution,
        unbilled_calls.collect(),
    ):
        events = await run_summary(request=request)
        artifact = execution.artifacts.get(RESULT_KEY, VideoSummaryArtifact)
        assert artifact is not None
        saved = files[artifact.path]
        assert "PRIVATE-MIDDLE" in saved
        assert ("PRIVATE-FIRST" in saved) is not interval
        assert ("PRIVATE-LAST" in saved) is not interval
        if interval:
            assert "00:10–00:20" in saved
            assert "Полная расшифровка" not in saved
        assert len(requests) == 1
        assert calls.count("files/write") == 1
        assert calls.count("files/download") == 1
        assert "model" not in calls
        assert not execution.usage.receipts
        assert not any(
            "watch_video" in (event.metadata or {}).get("billable_tools", []) for event in events
        )
        assert not any(event.type == EventType.ERROR for event in events)


@pytest.mark.asyncio
@pytest.mark.parametrize("selection", ["с 00:20 до 00:10", "с 10:00 до 12:00"])
async def test_invalid_transcription_range_does_not_publish(runtime, selection):
    files, calls, _, _ = runtime
    with use_run_execution(PrivateRunResources(workspace_ref=REF)) as execution:
        events = await run_summary(request=f"Сделай транскрипцию видео {URL} {selection}")
        assert not files and "model" not in calls
        assert execution.artifacts.get(RESULT_KEY, VideoSummaryArtifact) is None
        assert any(event.type == EventType.ERROR for event in events)
        assert not any(event.data == "Расшифровка готова" for event in events)
        assert any((event.metadata or {}).get("failure_code") == "invalid" for event in events)
        if selection == "с 00:20 до 00:10":
            assert "watch_video" not in calls


@pytest.mark.asyncio
async def test_failed_transcription_reports_the_failed_tool_without_summary_claims(
    runtime, monkeypatch
):
    from service.infrastructure.sidecar import SidecarUnavailable

    files, calls, _, _ = runtime

    async def unavailable(*args):
        raise SidecarUnavailable("video", "timeout", "PRIVATE-VIDEO-ERROR")

    monkeypatch.setattr(video_tool, "acquire_video", unavailable)
    with use_run_execution(PrivateRunResources(workspace_ref=REF)) as execution:
        events = await run_summary(request=f"{URL} Сделай транскрипцию видео")
        outcomes = [
            (event.metadata or {}).get("tool_progress", {})
            for event in events
            if (event.metadata or {}).get("tool_progress", {}).get("status")
            in {"failed", "completed", "succeeded"}
        ]
        assert any(item.get("status") == "failed" for item in outcomes)
        assert any((event.metadata or {}).get("failure_code") == "timeout" for event in events)
        assert not files and "model" not in calls
        assert not execution.usage.receipts
        assert execution.artifacts.get(RESULT_KEY, VideoSummaryArtifact) is None
        text = " ".join(str(event.data or "") for event in events)
        assert "конспект" not in text.lower()
        assert "расшифров" in text.lower()
        assert "PRIVATE-VIDEO-ERROR" not in json.dumps([e.model_dump(mode="json") for e in events])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code", ["source_rate_limited", "source_access_challenge", "source_access_denied"]
)
async def test_source_restriction_has_honest_recovery_without_file_or_model(
    runtime, monkeypatch, code
):
    from service.infrastructure.sidecar import SidecarUnavailable

    files, calls, _, _ = runtime

    async def unavailable(*args):
        raise SidecarUnavailable("video", code, "PRIVATE-RESPONSE")

    monkeypatch.setattr(video_tool, "acquire_video", unavailable)
    with use_run_execution(PrivateRunResources(workspace_ref=REF)) as execution:
        events = await run_summary(request=f"{URL} Сделай транскрипцию видео")
        assert not files and "model" not in calls and not execution.usage.receipts
        assert execution.artifacts.get(RESULT_KEY, VideoSummaryArtifact) is None
        text = " ".join(str(e.data or "") for e in events)
        assert "Источник" in text or "источник" in text
        assert "Готовый файл не создан" in text
        serialized = json.dumps([e.model_dump(mode="json") for e in events])
        assert code not in serialized and "PRIVATE-RESPONSE" not in serialized


def test_video_request_kind_distinguishes_transcript_from_notes():
    assert video_request_kind(f"Сделай расшифровку видео {URL}") == "transcript"
    assert video_request_kind(f"Сделай полный конспект видео {URL}") == "summary"


@pytest.mark.asyncio
async def test_protocol_repair_budget_is_shared_between_chunks(runtime, monkeypatch):
    _, calls, raw, _ = runtime

    async def invalid(**kwargs):
        calls.append("model")
        return SimpleNamespace(
            choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content="No"))],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20),
        )

    monkeypatch.setattr(authoring, "create_chat_completion", invalid)
    source = VideoTranscript.from_response(URL, raw)
    with use_run_execution(PrivateRunResources()) as execution:
        chunks = VideoEvidenceIndex.create(source).chunks
        for chunk in chunks[:2]:
            with pytest.raises(VideoSummaryFailure):
                await authoring.author_chunk(chunk, REQUEST, "test-model", execution)
        assert calls.count("model") == execution.usage.billable_calls == 3
        assert execution.policy.flags["video_protocol_repair_used"] is True


@pytest.mark.asyncio
async def test_complete_notes_are_verified_and_only_final_is_deliverable(runtime):
    files, calls, raw, _ = runtime
    with (
        use_run_execution(PrivateRunResources(workspace_ref=REF)) as execution,
        unbilled_calls.collect(),
    ):
        events = await run_summary()
        source = execution.artifacts.get(SOURCE_KEY, VideoTranscript)
        result = execution.artifacts.get(RESULT_KEY, VideoSummaryArtifact)
        assert source is not None and result is not None
        assert result.size == len(files[result.path].encode())
        assert result.sha256 == hashlib.sha256(files[result.path].encode()).hexdigest()
        assert "PRIVATE-CUE-559" in files[result.path]
        assert calls.count("watch_video") == 1
        assert execution.usage.billable_calls == calls.count("model") == result.chunks
        assert len(files) == 4  # transcript, structured checkpoint, draft, verified final
        assert not any(event.type == EventType.ERROR for event in events)
        serialized = json.dumps([event.model_dump(mode="json") for event in events])
        assert "PRIVATE-CUE" not in serialized and URL not in serialized
        billed = [
            event.metadata["billable_tools"]
            for event in events
            if "billable_tools" in (event.metadata or {})
        ]
        assert set(billed[-1]) == {"watch_video", "workspace_tool"}


@pytest.mark.asyncio
async def test_refusal_never_becomes_a_downloadable_summary(runtime, monkeypatch):
    files, calls, _, _ = runtime

    async def refusal(**kwargs):
        calls.append("model")
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(content="Мне необходим сам контент видео."),
                )
            ],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20),
        )

    monkeypatch.setattr(authoring, "create_chat_completion", refusal)
    with use_run_execution(PrivateRunResources(workspace_ref=REF)) as execution:
        events = await run_summary()
        assert execution.artifacts.get(RESULT_KEY, VideoSummaryArtifact) is None
        assert calls.count("model") == execution.usage.billable_calls == 2
        assert len(files) == 1  # Source remains inspectable, no draft/final refusal file.
        assert any(event.type == EventType.ERROR for event in events)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", [IntegrationFailureCode.CONFLICT, IntegrationFailureCode.UNAVAILABLE]
)
async def test_source_write_failure_never_starts_authoring_or_retries(runtime, failure):
    _, calls, _, state = runtime
    state["fail_write"] = failure
    with use_run_execution(PrivateRunResources(workspace_ref=REF)) as execution:
        events = await run_summary()
        assert "model" not in calls
        assert calls.count("files/write") == 1
        assert execution.artifacts.get(RESULT_KEY, VideoSummaryArtifact) is None
        assert any(event.type == EventType.ERROR for event in events)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario", ["no_consent", "cancel", "truncated", "model_failure", "corrupt_download"]
)
async def test_failures_do_not_create_download_promises(runtime, scenario):
    files, calls, raw, state = runtime
    raw["transcript_truncated"] = scenario == "truncated"
    state["fail_model"] = scenario == "model_failure"
    state["corrupt_download"] = scenario == "corrupt_download"
    with use_run_execution(PrivateRunResources(workspace_ref=REF)) as execution:
        if scenario == "cancel":
            execution.cancel()
        events = await run_summary(consent=scenario != "no_consent")
        assert execution.artifacts.get(RESULT_KEY, VideoSummaryArtifact) is None
        assert events[-1].type == EventType.AGENT_COMPLETE
        assert "SECRET-PROVIDER-BODY" not in json.dumps(
            [event.model_dump(mode="json") for event in events]
        )
        if scenario in {"cancel", "no_consent"}:
            assert not calls and not files
        if scenario == "truncated":
            assert calls.count("model") == 0 and len(files) == 0
        if scenario == "model_failure":
            assert calls.count("model") == 1 and len(files) == 1


@pytest.mark.asyncio
async def test_prompt_budget_stops_before_model_call(runtime, monkeypatch):
    _, calls, _, _ = runtime
    monkeypatch.setattr(authoring, "prompt_budget_per_run", lambda: 1)
    with use_run_execution(PrivateRunResources(workspace_ref=REF)):
        await run_summary()
        assert "model" not in calls


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("t_sec", False), ("transcript_truncated", None)])
async def test_malformed_source_scalar_stops_before_authoring_and_file_write(runtime, field, value):
    files, calls, raw, _ = runtime
    if field == "t_sec":
        raw["transcript"][0][field] = value
    else:
        raw[field] = value
    with use_run_execution(PrivateRunResources(workspace_ref=REF)) as execution:
        events = await run_summary()
        assert "model" not in calls
        assert not files
        assert execution.usage.billable_calls == 0
        assert execution.artifacts.get(RESULT_KEY, VideoSummaryArtifact) is None
        assert any(event.type == EventType.ERROR for event in events)
        assert events[-1].type == EventType.AGENT_COMPLETE


@pytest.mark.asyncio
async def test_late_failure_keeps_accepted_draft_without_restarting(runtime, monkeypatch):
    files, calls, _, _ = runtime
    original = authoring.create_chat_completion

    async def failing_model(**kwargs):
        if calls.count("model"):
            calls.append("model-failure")
            raise RuntimeError("PRIVATE-ERROR")
        return await original(**kwargs)

    monkeypatch.setattr(authoring, "create_chat_completion", failing_model)
    with use_run_execution(PrivateRunResources(workspace_ref=REF)) as execution:
        await run_summary()
        assert len(files) == 3
        assert any(path.endswith("draft.md") for path in files)
        assert calls.count("model") == calls.count("model-failure") == 1
        assert execution.usage.billable_calls == 1
        assert execution.artifacts.get(RESULT_KEY, VideoSummaryArtifact) is None


@pytest.mark.asyncio
async def test_cancel_between_parts_keeps_checkpoint_and_never_calls_next_model(
    runtime, monkeypatch
):
    files, calls, _, _ = runtime
    original = workspace_tools.call
    with use_run_execution(PrivateRunResources(workspace_ref=REF)) as execution:

        async def cancel_after_draft(ref, operation, body):
            result = await original(ref, operation, body)
            if operation == "files/write" and body["path"].endswith("draft.md"):
                execution.cancel()
            return result

        monkeypatch.setattr(workspace_tools, "call", cancel_after_draft)
        events = await run_summary()
        assert calls.count("model") == execution.usage.billable_calls == 1
        assert len(files) == 3
        saved = json.loads(
            next(content for path, content in files.items() if path.endswith(".json"))
        )
        assert len(saved["body"]["accepted_parts"]) == 1
        assert execution.artifacts.get(RESULT_KEY, VideoSummaryArtifact) is None
        assert any((event.metadata or {}).get("failure_code") == "cancelled" for event in events)


@pytest.mark.asyncio
async def test_late_revision_conflict_preserves_previous_checkpoint_without_refetch(
    runtime, monkeypatch
):
    files, calls, _, _ = runtime
    original = workspace_tools.call
    checkpoint_before = []

    async def conflict_on_checkpoint_update(ref, operation, body):
        if operation == "files/write" and body["path"].endswith("authoring.json"):
            if body["path"] in files:
                checkpoint_before.append(files[body["path"]])
                raise WorkspaceUnavailable(IntegrationFailureCode.CONFLICT)
        return await original(ref, operation, body)

    monkeypatch.setattr(workspace_tools, "call", conflict_on_checkpoint_update)
    with use_run_execution(PrivateRunResources(workspace_ref=REF)) as execution:
        events = await run_summary()
        saved = next(content for path, content in files.items() if path.endswith("authoring.json"))
        assert checkpoint_before == [saved]
        assert len(json.loads(saved)["body"]["accepted_parts"]) == 1
        assert calls.count("model") == execution.usage.billable_calls == 2
        assert "files/read" not in calls
        assert execution.artifacts.get(RESULT_KEY, VideoSummaryArtifact) is None
        assert any((event.metadata or {}).get("failure_code") == "conflict" for event in events)


@pytest.mark.asyncio
async def test_unknown_pause_boundary_never_starts_a_paid_step(runtime, monkeypatch):
    _, calls, _, _ = runtime

    async def unavailable(*args):
        raise WorkspaceUnavailable(IntegrationFailureCode.UNAVAILABLE)

    monkeypatch.setattr("service.domain.runners.chat.workspace_control.workspace_call", unavailable)
    with use_run_execution(PrivateRunResources(workspace_ref=REF)):
        await run_summary()
        assert not calls


@pytest.mark.asyncio
@pytest.mark.parametrize("accepted", [False, True])
async def test_terminal_inventory_excludes_old_partial_notes(runtime, monkeypatch, accepted):
    from service.application import agent_execution_service
    from service.application.reply_assembler import ReplyAssembler

    async def inventory(*args):
        return [{"path": "video-notes/old/draft.md", "size": 10}, {"path": "other.txt", "size": 5}]

    monkeypatch.setattr(agent_execution_service, "_workspace_artifacts", inventory)
    with use_run_execution(PrivateRunResources(workspace_ref=REF)) as execution:
        execution.policy.set_flag("video_summary_active", True)
        if accepted:
            execution.artifacts.publish(
                RESULT_KEY, VideoSummaryArtifact.for_content("video-notes/new/final.md", "notes", 1)
            )
        result = await agent_execution_service._finalize_reply(
            reply_assembler=ReplyAssembler(execution.usage),
            metadata={},
            timings=SimpleNamespace(as_meta=lambda: {}),
            workspace_ref=REF,
            resolved_model="test-model",
        )
        paths = [item["path"] for item in result["workspace_artifacts"]]
        assert "video-notes/old/draft.md" not in paths
        if accepted:
            assert result["workspace_artifacts"][0]["required"] is True
            assert (
                result["workspace_artifacts"][0]["sha256"] == hashlib.sha256(b"notes").hexdigest()
            )
        else:
            assert result["metadata"]["execution_status"] == "failed"
