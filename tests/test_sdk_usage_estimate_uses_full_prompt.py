"""Оценка usage на SDK-пути обязана считать ПО ТОМУ ЖЕ ПРОМПТУ, ЧТО РЕАЛЬНО УШЁЛ.

⚠️ ДЕНЕЖНЫЙ ТЕСТ. Когда SDK не отдал usage (а у mws/gigachat он его и не отдаёт —
`supports_stream_usage=False`), счёт считается ОЦЕНКОЙ. Оценка бралась по сырым
`self.instructions`, то есть без `system_context`: фактов о пользователе, вложений
текущей задачи, знаний, плана и резюме диалога. В живом запросе этот блок бывает в разы
больше самих инструкций — значит недобилл был систематическим и ровно там, где оценка и
нужна.

Тест держит инвариант «оценка ≈ то, что отправили», а не конкретную формулу.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from service.domain.subagents.general import GeneralAgent
from service.events import EventType
from service.schemas.agents import UserContext
from service.shared.token_budget import estimate_tokens

# Заметно больше инструкций агента — иначе разница утонет в округлении.
BIG_CONTEXT = "## Вложения текущей задачи\n" + ("Выручка за квартал составила 42 млн. " * 200)


def _ctx(**kwargs) -> UserContext:
    return UserContext(user_id="", request_time=datetime.now(UTC), **kwargs)


class _RunWithoutUsage:
    """Прогон SDK прошёл успешно, но usage не сообщил — включается оценка."""

    raw_responses: list = []

    async def stream_events(self):
        yield SimpleNamespace(
            type="raw_response_event",
            data=SimpleNamespace(type="response.output_text.delta", delta="Ответ модели"),
        )


@pytest.fixture
def sdk_without_usage(monkeypatch):
    class _Runner:
        @staticmethod
        def run_streamed(*args, **kwargs):
            return _RunWithoutUsage()

    fake_sdk = SimpleNamespace(
        Agent=lambda **kw: SimpleNamespace(**kw),
        Runner=_Runner,
        RunContextWrapper=lambda payload: payload,
        ModelSettings=lambda **kw: SimpleNamespace(**kw),
    )
    monkeypatch.setitem(__import__("sys").modules, "agents", fake_sdk)
    return fake_sdk


async def _usage_for(agent, context) -> dict:
    events = [e async for e in agent._run_sdk_streamed("вопрос", context)]
    complete = [e for e in events if e.type == EventType.AGENT_COMPLETE]
    assert complete, "прогон не завершился AGENT_COMPLETE"
    usage = complete[0].metadata.get("token_usage")
    assert usage, "SDK не отдал usage и оценка не сработала — ответ ушёл БЕСПЛАТНО"
    return usage


@pytest.mark.asyncio
async def test_estimate_includes_system_context(sdk_without_usage):
    """🔴 Контекст, отправленный модели, обязан попасть в оценку счёта."""
    agent = GeneralAgent({"model": "test-model"})

    usage = await _usage_for(agent, _ctx(system_context=BIG_CONTEXT))

    assert usage.get("estimated") is True, "это должна быть именно оценка"
    context_tokens = estimate_tokens(BIG_CONTEXT)
    assert usage["prompt"] >= context_tokens, (
        f"оценка prompt={usage['prompt']} меньше одного только system_context "
        f"(~{context_tokens} токенов) — значит контекст в счёт не попал (недобилл)"
    )


@pytest.mark.asyncio
async def test_estimate_grows_with_context(sdk_without_usage):
    """Тот же запрос с контекстом обязан стоить дороже, чем без него.

    Проверяет не формулу, а её ЧУВСТВИТЕЛЬНОСТЬ: если оценка считается по сырым
    инструкциям, оба прогона дадут одинаковое число.
    """
    agent = GeneralAgent({"model": "test-model"})

    without = await _usage_for(agent, _ctx())
    with_context = await _usage_for(agent, _ctx(system_context=BIG_CONTEXT))

    assert with_context["prompt"] > without["prompt"], (
        "оценка не изменилась от добавления контекста — считается по сырым instructions"
    )
