"""Выбранный provider фиксируется до чтения уроков, не после первого inference."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service.domain.client.protocol import PinSource
from service.domain.execution.context import PrivateRunResources, use_run_execution
from service.domain.runners.harness.lessons import with_verified_lessons
from service.settings import config
from service.shared.harness_protocol import Continuation, HarnessFailure
from tests.test_task_contract import state


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["gigachat", "routerai", "openai", "local"])
async def test_initial_binding_checkpoint_precedes_lesson_lookup_without_consuming_limits(
    monkeypatch, provider
):
    monkeypatch.setattr(config.agents, "harness_refinement_enabled", True)
    with use_run_execution(PrivateRunResources()) as execution:
        execution.bind_task_state(state(rounds=7, repairs=1))
        execution.provider_session.pin(provider, "test", source=PinSource.NON_STREAM_RESPONSE)
        calls = []
        client = SimpleNamespace(current=SimpleNamespace(continuation=Continuation()))

        async def checkpoint(owner, messages, **kwargs):
            calls.append("checkpoint")
            assert owner is execution and messages == [] and kwargs == {"phase": "model"}
            client.current.continuation = Continuation(
                provider={"provider": provider, "model": "test"}
            )

        async def exchange(**kwargs):
            calls.append("lessons")
            assert client.current.continuation.provider is not None
            return {"lessons": [{"instruction": "Прочитай исходник до ответа.", "tools": []}]}

        client.checkpoint, client.exchange = (
            AsyncMock(side_effect=checkpoint),
            AsyncMock(side_effect=exchange),
        )
        execution.harness = client
        original = [{"role": "user", "content": "Прочитай исходник"}]
        prepared = await with_verified_lessons(original, [], execution)
        assert calls == ["checkpoint", "lessons"]
        assert prepared[:1] == original and len(prepared) == 2
        assert execution.task_state.rounds == 7 and execution.task_state.repairs == 1
        assert (
            client.current.continuation.next_step == 0 and not client.current.continuation.messages
        )


@pytest.mark.asyncio
async def test_unknown_initial_binding_ack_does_not_load_advice_or_start_any_model(monkeypatch):
    monkeypatch.setattr(config.agents, "harness_refinement_enabled", True)
    with use_run_execution(PrivateRunResources()) as execution:
        execution.bind_task_state(state())
        execution.provider_session.pin("local", "test", source=PinSource.NON_STREAM_RESPONSE)
        client = SimpleNamespace(
            current=SimpleNamespace(continuation=Continuation()),
            checkpoint=AsyncMock(side_effect=HarnessFailure("checkpoint_unavailable")),
            exchange=AsyncMock(return_value={"lessons": []}),
        )
        execution.harness = client
        with pytest.raises(HarnessFailure, match="checkpoint_unavailable"):
            await with_verified_lessons([], [], execution)
        client.exchange.assert_not_awaited()


@pytest.mark.asyncio
async def test_lesson_lookup_does_not_choose_or_guess_an_unpinned_provider(monkeypatch):
    monkeypatch.setattr(config.agents, "harness_refinement_enabled", True)
    with use_run_execution(PrivateRunResources()) as execution:
        client = SimpleNamespace(
            current=SimpleNamespace(continuation=Continuation()),
            checkpoint=AsyncMock(),
            exchange=AsyncMock(),
        )
        execution.harness = client
        original = [{"role": "user", "content": "Прочитай исходник"}]
        assert await with_verified_lessons(original, [], execution) is original
        client.exchange.assert_not_awaited()
        client.checkpoint.assert_not_awaited()
