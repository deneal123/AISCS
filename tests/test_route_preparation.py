"""Consent precedes downstream stages; routing retains the owning ledger and inputs."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from service.application.processing import context, processor, settings, steps
from service.application.processing.routing import preparation
from service.application.processing.routing.contracts import RouteInputs
from service.domain.execution.context import RunExecutionContext
from service.domain.pipeline.auto_mode import AutoPlan
from service.domain.usage.ledger import UsageKind
from service.events import AgentEvent, EventType
from service.schemas.agents import ModalityAttachment


def event(kind):
    return AgentEvent(type=EventType.STATUS_UPDATE, metadata={"kind": kind})


@pytest.fixture
def pipeline(monkeypatch):
    order = []
    execution = RunExecutionContext()
    execution.task.rounds = 9
    auto_event = event("auto")

    async def auto(**kwargs):
        order.append("auto")
        assert kwargs["execution"] is execution
        execution.usage.record_usage(
            {"prompt": 3, "completion": 2, "model": "synthetic"},
            provider="synthetic",
            kind=UsageKind.META,
            receipt_id="one-auto-call",
        )
        return AutoPlan(events=[auto_event])

    auto_mock = AsyncMock(side_effect=auto)
    offer = Mock(return_value=None)
    monkeypatch.setattr("service.domain.pipeline.video_offer.explicit_video_offer", offer)
    monkeypatch.setattr(preparation, "resolve_auto_plan", auto_mock)
    monkeypatch.setattr(settings, "_orchestrator_flags", lambda: {"enabled": True})
    apply = Mock(wraps=preparation.apply_plan)
    monkeypatch.setattr(preparation, "apply_plan", apply)

    async def fanout(*args, **kwargs):
        order.append("fanout")
        assert kwargs["execution"] is execution
        return "merged", [event("fanout")]

    async def workflow(**kwargs):
        order.append("workflow")
        assert kwargs["execution"] is execution
        return SimpleNamespace(
            subtasks=None,
            candidate=None,
            route_override=None,
            resolved_category="general",
            events=[event("workflow")],
        )

    async def plan(*args, **kwargs):
        order.append("plan")
        assert kwargs["execution"] is execution
        return "plan context", [event("plan")]

    fanout_mock = AsyncMock(side_effect=fanout)
    workflow_mock = AsyncMock(side_effect=workflow)
    plan_mock = AsyncMock(side_effect=plan)
    route_mock = AsyncMock(return_value=("general", event("route-start"), event("route-end")))
    monkeypatch.setattr(steps, "fanout_context", fanout_mock)
    monkeypatch.setattr(steps, "resolve_workflow_route", workflow_mock)
    monkeypatch.setattr(steps, "resolve_plan", plan_mock)
    monkeypatch.setattr(steps, "resolve_agent_route", route_mock)
    return SimpleNamespace(
        order=order,
        execution=execution,
        auto=auto_mock,
        offer=offer,
        apply=apply,
        fanout=fanout_mock,
        workflow=workflow_mock,
        plan=plan_mock,
        route=route_mock,
        auto_event=auto_event,
    )


async def run_route(pipeline, **overrides):
    kwargs = dict(
        user_input="PRIVATE_TASK",
        thread_id="thread",
        route_override=None,
        resolved_category=None,
        input_type="text",
        web_search=False,
        deep_research=False,
        multi_intent=None,
        planning=None,
        file_context="PRIVATE_FILE_TEXT",
        attachments=[
            {"kind": "image", "name": "image", "content": "PRIVATE_IMAGE"},
            {"kind": "audio", "name": "audio", "content": "PRIVATE_AUDIO"},
            {"kind": "image", "name": "empty", "content": ""},
        ],
        execution=pipeline.execution,
    )
    kwargs.update(overrides)
    return await steps.ProcessorStepsMixin._resolve_route_and_plan(
        SimpleNamespace(model_id="synthetic", orchestrator=object()), **kwargs
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["explicit_video", "auto_mode", "auto_tool"])
async def test_confirmation_parks_before_any_downstream_paid_stage(pipeline, monkeypatch, source):
    if source == "explicit_video":
        pipeline.offer.return_value = event("offer")
        flags = Mock(side_effect=AssertionError("settings read before explicit consent"))
        monkeypatch.setattr(settings, "_orchestrator_flags", flags)
    else:
        pipeline.auto.side_effect = None
        pipeline.auto.return_value = AutoPlan(
            offered_mode="pdf_gen" if source == "auto_mode" else None,
            offered_tool="watch_video" if source == "auto_tool" else None,
            events=[event("offer")],
        )
    decision, events = await run_route(pipeline)
    assert pipeline.execution.policy.flag("confirmation_pending")
    assert decision.agent_name == "general" and decision.subtasks is None
    assert decision.file_context == "PRIVATE_FILE_TEXT" and not decision.multimodal
    assert events[0].metadata["kind"] == "offer"
    assert events[-1].metadata["awaiting_confirmation"]
    assert events[-1].metadata["execution_status"] == "deferred"
    assert "PRIVATE" not in repr(events)
    pipeline.apply.assert_not_called()
    for call in (pipeline.fanout, pipeline.workflow, pipeline.plan, pipeline.route):
        call.assert_not_awaited()
    assert pipeline.execution.task.rounds == 9
    if source == "explicit_video":
        pipeline.auto.assert_not_awaited()
        flags.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("chain", [False, True])
async def test_fanout_and_multi_intent_stay_independent_after_preparation(pipeline, chain):
    pipeline.auto.side_effect = None
    pipeline.auto.return_value = AutoPlan(
        multi_intent=chain, planning=True, force_decompose=chain, events=[pipeline.auto_event]
    )
    pipeline.workflow.side_effect = None
    pipeline.workflow.return_value = SimpleNamespace(
        subtasks=["step"] if chain else None,
        candidate=None,
        route_override=None,
        resolved_category="general",
        events=[event("workflow")],
    )
    decision, events = await run_route(pipeline)
    pipeline.fanout.assert_awaited_once()
    assert len(pipeline.fanout.await_args.args[0]) == 2
    assert all(
        isinstance(item, ModalityAttachment)
        for item in decision.context_updates["current_attachments"]
    )
    assert decision.multimodal and decision.file_context == "merged"
    assert bool(decision.subtasks) is chain
    assert pipeline.workflow.await_args.kwargs["force_decompose"] is chain
    assert pipeline.workflow.await_args.kwargs["multi_intent"] is chain
    assert pipeline.plan.await_args.kwargs["planning"] is True
    assert decision.plan_context == "plan context"
    assert events[0] is pipeline.auto_event
    assert events[1].metadata["kind"] == "fanout"
    assert events[2].metadata["kind"] == "workflow"
    assert events[-1].metadata["kind"] == "plan"
    pipeline.route.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tabular,file_text,text_present,is_map",
    [
        (False, "PRIVATE_FILE_TEXT", True, False),
        (True, "PRIVATE_FILE_TEXT", False, False),
        (False, "# Graph Report\nGod Nodes\nPRIVATE_REPOSITORY_MAP", True, True),
        (False, " ", False, False),
    ],
)
async def test_prompt_facts_come_from_the_real_projection(
    pipeline, tabular, file_text, text_present, is_map
):
    request = RouteInputs(
        user_input="PRIVATE_TASK",
        file_context=file_text,
        context=SimpleNamespace(tabular_files=["table"] if tabular else None),
        history_messages=[{"role": "user", "content": "PRIVATE_HISTORY"}],
        compact_summary="PRIVATE_SUMMARY",
    )
    prepared = await preparation.prepare_route(
        request, execution=pipeline.execution, model="synthetic"
    )
    call = pipeline.auto.await_args.kwargs
    assert call["attachment_text_in_prompt"] is text_present
    assert call["attachment_text_in_prompt_is_a_map"] is is_map
    assert call["history_messages"] is request.history_messages
    assert call["compact_summary"] == request.compact_summary
    assert call["context"] is request.context
    assert prepared.parked is None
    assert "PRIVATE" not in repr(request) + repr(prepared)
    assert pipeline.execution.usage.cursor() == 1
    assert pipeline.execution.usage.as_token_usage(kind=UsageKind.META)["total"] == 5
    assert pipeline.execution.task.rounds == 9


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["auto", "fanout", "workflow", "plan"])
async def test_stage_failure_does_not_retry_or_discard_accepted_usage(pipeline, failure):
    target = getattr(pipeline, failure)
    if failure == "auto":
        original = target.side_effect

        async def fail_after_receipt(**kwargs):
            await original(**kwargs)
            raise RuntimeError("synthetic stage failure")

        target.side_effect = fail_after_receipt
    else:
        target.side_effect = RuntimeError("synthetic stage failure")
    with pytest.raises(RuntimeError, match="synthetic stage failure"):
        await run_route(pipeline)
    target.assert_awaited_once()
    stages = [pipeline.auto, pipeline.fanout, pipeline.workflow, pipeline.plan]
    for later in stages[stages.index(target) + 1 :]:
        later.assert_not_awaited()
    assert pipeline.execution.usage.cursor() == 1
    assert pipeline.execution.usage.as_token_usage(kind=UsageKind.META)["total"] == 5


def test_processing_stages_share_one_call_time_settings_adapter(monkeypatch):
    assert context._agent_flag is processor._agent_flag is steps._agent_flag is settings._agent_flag
    read = Mock(side_effect=[False, True])
    monkeypatch.setattr(settings.runtime_settings, "get_agents", read)
    assert settings._agent_flag("planning_enabled", None) is False
    assert settings._agent_flag("planning_enabled", None) is True
    assert read.call_count == 2
