"""Ledger-native model-call and partial-stream accounting regressions."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from service.application.reply_assembler import ReplyAssembler
from service.domain.client.protocol import PinSource, ProviderStreamEventKind
from service.domain.legacy_usage import accumulate_usage
from service.domain.model_runtime import invoke_model_call
from service.domain.run_context import PrivateRunResources, current_execution, use_run_execution
from service.domain.runners.chat_provider_round import provider_events
from service.domain.subagents.context_query import resolve_query
from service.domain.subagents.runtime import StageContext, StageReceipt, StageStatus
from service.domain.usage_ledger import UsageKind, receipt_from_usage


def _response(*, prompt: int | None = 7, completion: int | None = 3):
    usage = None
    if prompt is not None and completion is not None:
        usage = SimpleNamespace(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=prompt + completion,
        )
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="answer"), finish_reason="stop")],
        usage=usage,
    )


@pytest.mark.asyncio
async def test_context_query_cannot_copy_a_run_receipt_into_a_second_ledger(monkeypatch) -> None:
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content='{"query":"standalone synthetic query"}'),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(prompt_tokens=2, completion_tokens=1, total_tokens=3),
    )

    async def call(**_kwargs):
        return response

    monkeypatch.setattr("service.domain.subagents.context_query.create_chat_completion", call)
    context = SimpleNamespace(history_messages=[{"role": "user", "content": "synthetic history"}])
    with use_run_execution(PrivateRunResources()) as execution:
        await resolve_query(
            "standalone synthetic query",
            context,
            "model-a",
        )

        assert len(execution.usage.receipts) == 1


@pytest.mark.asyncio
async def test_model_call_records_once_and_compatibility_is_projection_only() -> None:
    response = _response()

    async def call(**kwargs):
        execution = current_execution()
        assert execution is not None
        execution.register_response_provider(response, "provider-a", kwargs["model"])
        return response

    projected: dict = {}
    with use_run_execution(PrivateRunResources()) as execution:
        result = await invoke_model_call(
            call,
            model="model-a",
            kind=UsageKind.META,
            messages=[{"role": "user", "content": "synthetic"}],
        )
        accumulate_usage(projected, response, "model-a", kind=UsageKind.META.value)
        accumulate_usage(projected, response, "model-a", kind=UsageKind.META.value)
        assembler = ReplyAssembler(execution.usage)
        assembler.add_usage(projected)
        assembler.add_usage(projected)
        assembler.finalize_usage()

        assert result.provider == "provider-a"
        assert result.finish_reason == "stop"
        assert result.usage.receipt_id == projected["calls"][0]["receipt_id"]
        assert len(execution.usage.receipts) == 1
        assert len(projected["calls"]) == 1
        assert assembler.total_tokens == 10
        assert len(assembler.per_call_usage) == 1


@pytest.mark.asyncio
async def test_usage_absence_creates_an_estimated_receipt() -> None:
    response = _response(prompt=None, completion=None)

    async def call(**_kwargs):
        return response

    with use_run_execution(PrivateRunResources()) as execution:
        result = await invoke_model_call(
            call,
            model="model-a",
            kind=UsageKind.QUERY_RESOLUTION,
            messages=[{"role": "user", "content": "synthetic prompt"}],
        )

        assert result.usage.estimated is True
        assert result.usage.prompt > 0
        assert result.usage.completion > 0
        assert execution.usage.receipts == (result.usage,)


@pytest.mark.asyncio
async def test_partial_accepted_stream_is_pinned_and_billed_before_error() -> None:
    async def stream(*, provider_session=None, round_state=None, model=None, **_kwargs):
        assert provider_session is not None
        provider_session.pin("provider-a", model, source=PinSource.STREAM_DELTA)
        if round_state is not None:
            round_state.update({"provider": "provider-a", "model": model})
        yield "accepted"
        raise RuntimeError("PRIVATE_PROVIDER_BODY")

    with use_run_execution(PrivateRunResources()) as execution:
        observed = []
        with pytest.raises(RuntimeError):
            async for event in provider_events(
                stream,
                messages=[{"role": "user", "content": "synthetic"}],
                model="model-a",
                max_tokens=50,
                tools=None,
                pin_provider=None,
                tool_choice=None,
                provider_session=execution.provider_session,
            ):
                observed.append(event)

        assert [event.kind for event in observed] == [ProviderStreamEventKind.DELTA]
        assert execution.provider_session.pinned_provider == "provider-a"
        assert execution.provider_session.round_count == 1
        assert len(execution.usage.receipts) == 1
        receipt = execution.usage.receipts[0]
        assert receipt.estimated is True
        assert receipt.prompt > 0
        assert receipt.completion > 0
        assert "PRIVATE_PROVIDER_BODY" not in str(receipt.as_dict())


@pytest.mark.asyncio
async def test_provider_session_result_does_not_create_a_second_receipt() -> None:
    response = _response()

    async def call(*, provider_session=None, model=None, **_kwargs):
        provider_session.complete_round(
            provider="provider-a",
            model=model,
            response=response,
            kind=UsageKind.CHAT,
            call_id="answer-call",
        )
        return response

    with use_run_execution(PrivateRunResources()) as execution:
        result = await invoke_model_call(
            call,
            model="model-a",
            kind=UsageKind.CHAT,
            provider_session=execution.provider_session,
            messages=[{"role": "user", "content": "synthetic"}],
        )

        assert result.call_id == "answer-call"
        assert len(execution.usage.receipts) == 1
        assert execution.usage.receipts[0].receipt_id == "answer-call"


@pytest.mark.asyncio
async def test_completed_stream_event_carries_opaque_call_provenance() -> None:
    async def stream(*, provider_session=None, round_state=None, model=None, **_kwargs):
        assert provider_session is not None
        provider_session.complete_round(
            provider="provider-a",
            model=model,
            usage={"prompt": 2, "completion": 1},
            finish_reason="stop",
            source=PinSource.STREAM_DELTA,
            call_id="opaque-call",
        )
        if round_state is not None:
            round_state.update(
                {
                    "prompt": 2,
                    "completion": 1,
                    "provider": "provider-a",
                    "model": model,
                    "finish_reason": "stop",
                }
            )
        yield "ok"

    with use_run_execution(PrivateRunResources()) as execution:
        observed = [
            event
            async for event in provider_events(
                stream,
                messages=[{"role": "user", "content": "synthetic"}],
                model="model-a",
                max_tokens=50,
                tools=None,
                pin_provider=None,
                tool_choice=None,
                provider_session=execution.provider_session,
            )
        ]

    completed = observed[-1]
    assert completed.kind is ProviderStreamEventKind.COMPLETED
    assert completed.call_id == "opaque-call"
    assert completed.provider == "provider-a"
    assert completed.model == "model-a"
    assert completed.finish_reason == "stop"


def test_stage_projection_does_not_rebill_unrelated_run_receipts() -> None:
    with use_run_execution(PrivateRunResources()) as execution:
        execution.usage.record_usage(
            {"prompt": 90, "completion": 10},
            provider="provider-a",
            model="router-model",
            kind=UsageKind.ROUTE_MODEL,
            receipt_id="earlier-router",
        )
        stages = StageContext()
        research_receipt = receipt_from_usage(
            {"prompt": 7, "completion": 3},
            provider="provider-b",
            model="research-model",
            kind=UsageKind.RESEARCH_PLAN,
            receipt_id="research-plan",
        )
        stages.record(
            StageReceipt(
                stage="research_plan",
                status=StageStatus.SUCCEEDED,
                usage=research_receipt,
            )
        )
        projected = execution.usage.project_kind_since(1, UsageKind.RESEARCH_PLAN)

    assert projected["prompt"] == 7
    assert projected["completion"] == 3
    assert [call["receipt_id"] for call in projected["calls"]] == ["research-plan"]
