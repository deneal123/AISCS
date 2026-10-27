"""Кэш не превращает частичный или отфильтрованный model reply в обычный stop."""

import pytest

from service.domain.client.calls.harness_stream import paid_stream
from service.domain.client.calls.harness_transport import cached_response
from service.domain.client.protocol import ProviderRoundState
from service.domain.execution.context import PrivateRunResources, use_run_execution
from service.shared.harness_protocol import HarnessFailure
from tests.test_harness_reconciliation import Journal


@pytest.mark.parametrize("reason", ["length", "content_filter", "tool_calls", "stop"])
def test_cached_completion_retains_authoritative_finish_reason(reason):
    result = cached_response(
        "test-model",
        {
            "message": {"role": "assistant", "content": "Сохранённая часть"},
            "prompt": 10,
            "completion": 3,
            "finish_reason": reason,
        },
    )
    assert result.choices[0].finish_reason == reason
    assert result.usage.total_tokens == 13


@pytest.mark.parametrize("reason", [None, "", "unknown"])
def test_legacy_unknown_terminal_is_not_promoted_to_success(reason):
    with pytest.raises(HarnessFailure, match="provider_state_incompatible"):
        cached_response(
            "test-model",
            {
                "message": {"role": "assistant", "content": "Сохранённая часть"},
                "prompt": 10,
                "completion": 3,
                "finish_reason": reason,
            },
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["length", "content_filter", "stop"])
async def test_stream_replay_uses_original_terminal_and_never_redispatches(reason):
    journal, sends = Journal(None), []
    for replay in (False, True):
        with use_run_execution(PrivateRunResources()) as execution:
            execution.harness = journal.client()
            state = ProviderRoundState(prompt=10, completion=3, total=13, finish_reason=reason)

            async def send(operation_id, *, replay=replay):
                assert not replay, "provider_must_not_be_replayed"
                sends.append(operation_id)
                yield "Сохранённая часть"

            parts = [
                part
                async for part in paid_stream(
                    send,
                    provider="openai",
                    model="test",
                    messages=[],
                    parameters={"round_state": state, "max_tokens": 32},
                )
            ]
            assert parts == ["Сохранённая часть"]
            assert state.finish_reason == reason
            assert len(execution.usage.receipts) == 1
    assert len(sends) == journal.counts["dispatch"] == journal.counts["call_receipt"] == 1


@pytest.mark.asyncio
async def test_missing_saved_terminal_blocks_without_overwriting_confirmed_cost():
    journal = Journal(None)
    with use_run_execution(PrivateRunResources()) as execution:
        execution.harness = journal.client()

        async def send(operation_id):
            yield "Сохранённая часть"

        [
            part
            async for part in paid_stream(
                send,
                provider="openai",
                model="test",
                messages=[],
                parameters={
                    "round_state": ProviderRoundState(
                        prompt=10, completion=3, total=13, finish_reason="length"
                    ),
                    "max_tokens": 32,
                },
            )
        ]
    saved = next(iter(journal.operations.values()))["receipt"]
    saved.pop("finish_reason")
    with use_run_execution(PrivateRunResources()) as resumed:
        resumed.harness = journal.client()

        async def forbidden(operation_id):
            raise AssertionError("provider_must_not_be_replayed")
            yield

        with pytest.raises(HarnessFailure, match="provider_state_incompatible"):
            [
                part
                async for part in paid_stream(
                    forbidden,
                    provider="openai",
                    model="test",
                    messages=[],
                    parameters={"round_state": ProviderRoundState(), "max_tokens": 32},
                )
            ]
    assert saved["prompt"] == 10 and saved["completion"] == 3
    assert journal.counts["dispatch"] == journal.counts["call_receipt"] == 1
