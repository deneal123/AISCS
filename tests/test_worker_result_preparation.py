"""Canonical acceptance precedes materialization; preparation has no charge authority."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from service.infrastructure.agents_client import required_artifacts
from service.services.chat.infrastructure.chat_worker.continuation import confirmation
from service.services.chat.infrastructure.chat_worker.harness import recovery
from service.services.chat.infrastructure.chat_worker.phases import RunPhase
from service.services.chat.infrastructure.chat_worker.results import preparation
from service.services.chat.infrastructure.chat_worker.run_contracts import (
    MutableRunState,
    WorkerRunRequest,
)

ORDER = [
    "usage",
    "parse",
    "anchor",
    "fence",
    "accepted",
    "stream_complete",
    "artifacts",
    "normalize",
    "display",
    "catalog",
    "prepared",
]


@pytest.fixture
def setup(monkeypatch):
    order = []
    fault = [None]
    request = WorkerRunRequest(str(uuid4()), str(uuid4()), "PRIVATE_TASK", str(uuid4()))
    state = MutableRunState()
    state.phase.advance(RunPhase.RESERVED)
    state.phase.advance(RunPhase.EXECUTING)
    original = {"source": "PRIVATE_PROVIDER_METADATA"}
    result = dict(resolved_model="synthetic", reply_parts_count=2, reply_chars_count=8)

    def step(name):
        order.append(name)
        if fault[0] == name:
            raise RuntimeError("synthetic preparation failure")

    def usage(*args):
        step("usage")

    def parse(_result):
        step("parse")
        return "PRIVATE_CANONICAL_REPLY", original

    async def anchor(_redis, _request, metadata):
        step("anchor")
        metadata["anchored"] = True
        return metadata

    async def fence(_session, _request, _state):
        step("fence")
        assert _state is state and _state.phase.phase is RunPhase.RESULT_LATCHED

    async def accepted(**kwargs):
        step("accepted")
        assert kwargs["reply"] == "PRIVATE_CANONICAL_REPLY"
        assert kwargs["metadata"].get("artifact") is None

    def publish(payload):
        step(payload["type"])
        assert set(payload["metadata"]) == {"chunks", "reply_chars"}
        assert "PRIVATE" not in str(payload)

    async def artifacts(*args):
        step("artifacts")
        assert args[1] == request.user_id and args[-1] == request.text
        return "file-url", {**args[2], "artifact": True}

    def normalize(metadata, **kwargs):
        step("normalize")
        assert kwargs["selected_model"] == "synthetic"
        return {**metadata, "normalized": True}

    def display(reply, metadata, _result):
        step("display")
        assert reply == "PRIVATE_CANONICAL_REPLY" and metadata["artifact"]
        return "PRIVATE_DISPLAY_REPLY"

    async def catalog(*args, **kwargs):
        step("catalog")
        assert kwargs["reply"] == "PRIVATE_DISPLAY_REPLY"

    async def prepared(**kwargs):
        step("prepared")
        assert kwargs["reply"] == "PRIVATE_DISPLAY_REPLY"
        assert kwargs["canonical_reply"] == "PRIVATE_CANONICAL_REPLY"
        assert kwargs["metadata"]["normalized"]
        assert kwargs["file_url"] == "file-url"

    hooks = SimpleNamespace(
        reply_or_provider_failure=Mock(side_effect=parse),
        record_catalog_events=AsyncMock(side_effect=catalog),
        prepared_results=SimpleNamespace(
            capture_accepted=AsyncMock(side_effect=accepted),
            capture=AsyncMock(side_effect=prepared),
        ),
        charge_and_describe=AsyncMock(),
        persist_chat_turn=AsyncMock(),
        publish_committed_turn=AsyncMock(),
    )
    artifact_mock = AsyncMock(side_effect=artifacts)
    monkeypatch.setattr(preparation, "require_terminal_usage", usage)
    monkeypatch.setattr(confirmation, "anchor_pending_offer", AsyncMock(side_effect=anchor))
    monkeypatch.setattr(recovery, "verify_harness_attempt", AsyncMock(side_effect=fence))
    monkeypatch.setattr(preparation, "persist_all_artifacts", artifact_mock)
    monkeypatch.setattr(preparation, "normalize_response_metadata", normalize)
    monkeypatch.setattr(required_artifacts, "delivery_reply", display)
    return SimpleNamespace(
        order=order,
        fault=fault,
        request=request,
        state=state,
        result=result,
        original=original,
        hooks=hooks,
        artifacts=artifact_mock,
        publisher=Mock(publish_payload=Mock(side_effect=publish)),
        session=AsyncMock(),
    )


async def prepare(setup):
    return await preparation.prepare_turn_content(
        setup.request,
        setup.result,
        SimpleNamespace(workflow_observations=[], workflow_executions=[]),
        redis_client=None,
        publisher=setup.publisher,
        job_repo=object(),
        file_service=object(),
        session=setup.session,
        state=setup.state,
        hooks=setup.hooks,
        started_at=0,
    )


def assert_no_settlement(setup):
    setup.hooks.charge_and_describe.assert_not_awaited()
    setup.hooks.persist_chat_turn.assert_not_awaited()
    setup.hooks.publish_committed_turn.assert_not_awaited()
    # Hook implementations retain their existing durable checkpoint commits;
    # the preparation stage does not add a turn commit of its own.
    setup.session.commit.assert_not_awaited()
    setup.session.rollback.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("question_pause", [False, True])
async def test_fresh_content_keeps_canonical_checkpoint_and_display_projection_distinct(
    setup, question_pause
):
    if question_pause:
        setup.result["_human_question_pause_v1"] = {"private": "checkpoint"}
    content = await prepare(setup)
    assert setup.order == ORDER
    assert content.reply == "PRIVATE_DISPLAY_REPLY" and content.file_url == "file-url"
    assert content.resolved_model == "synthetic"
    assert content.metadata["artifact"] and content.metadata["normalized"]
    assert "PRIVATE" not in repr(content)
    if question_pause:
        assert setup.original == {"source": "PRIVATE_PROVIDER_METADATA"}
    assert setup.state.phase.phase is RunPhase.RESULT_LATCHED
    assert_no_settlement(setup)


@pytest.mark.asyncio
async def test_backend_downgrade_protects_display_not_canonical_acceptance(setup, monkeypatch):
    from service.services.chat.infrastructure.chat_worker.harness import finalization
    from service.shared.task_contract import CompletionVerifier
    from tests.test_task_contract import evidence, state

    confirmed = CompletionVerifier.evaluate(state(evidence=[evidence(), evidence("test")]))
    current = CompletionVerifier.evaluate(state())
    setup.original.update(task_result=confirmed, ide_summary="Всё готово")
    setup.state.harness_task_id = str(uuid4())
    projection = AsyncMock(
        side_effect=lambda _db, _request, _state, meta: {**meta, "task_result": current}
    )
    monkeypatch.setattr(finalization, "project_current_result", projection)
    setup.hooks.record_catalog_events = AsyncMock()
    setup.hooks.prepared_results.capture = AsyncMock()
    content = await prepare(setup)
    assert content.reply == finalization.UNVERIFIED_REPLY
    assert content.metadata["ide_summary"] == content.reply
    assert content.metadata["task_result"] == current
    assert setup.original["task_result"] == confirmed
    accepted = setup.hooks.prepared_results.capture_accepted.await_args.kwargs
    prepared = setup.hooks.prepared_results.capture.await_args.kwargs
    assert accepted["reply"] == prepared["canonical_reply"] == "PRIVATE_CANONICAL_REPLY"
    assert prepared["reply"] == content.reply
    assert accepted["metadata"]["task_result"] == current
    assert_no_settlement(setup)


@pytest.mark.asyncio
async def test_restored_content_still_fences_but_never_repeats_preparation_effects(
    setup, monkeypatch
):
    from service.services.chat.infrastructure.chat_worker.harness import finalization

    projection = AsyncMock(side_effect=AssertionError("stored_terminal_must_not_be_reprojected"))
    monkeypatch.setattr(finalization, "project_current_result", projection)
    setup.state.harness_task_id = str(uuid4())
    metadata = {"restored": "PRIVATE_RESTORED_METADATA"}
    setup.state.restored_result = dict(
        reply="stored display", metadata=metadata, file_url="stored-url"
    )
    content = await prepare(setup)
    assert setup.order == ["fence"]
    assert content.reply == "stored display" and content.file_url == "stored-url"
    assert content.metadata == metadata and content.metadata is not metadata
    content.metadata["later"] = True
    assert "later" not in metadata
    setup.hooks.reply_or_provider_failure.assert_not_called()
    setup.artifacts.assert_not_awaited()
    setup.hooks.record_catalog_events.assert_not_awaited()
    setup.hooks.prepared_results.capture_accepted.assert_not_awaited()
    setup.hooks.prepared_results.capture.assert_not_awaited()
    setup.publisher.publish_payload.assert_not_called()
    assert_no_settlement(setup)
    projection.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ORDER)
async def test_preparation_failure_stops_before_later_effects_or_settlement(setup, fault):
    setup.fault[0] = fault
    with pytest.raises(RuntimeError, match="synthetic preparation failure"):
        await prepare(setup)
    assert setup.order == ORDER[: ORDER.index(fault) + 1]
    expected = (
        RunPhase.EXECUTING if fault in {"usage", "parse", "anchor"} else RunPhase.RESULT_LATCHED
    )
    assert setup.state.phase.phase is expected
    assert_no_settlement(setup)
