"""Сбой SDK ПОСЛЕ отданных токенов: ответ не задваивается, работа не бесплатна.

⚠️ Две беды в одной ветке `except` (`sdk_run.py`), и обе видны только вместе.

1. **Аварийный фолбэк запускался безусловно.** Проверки «а не ушёл ли контент уже
   пользователю» не было вовсе, хотя `streamed_chunks` и `collected_text` тут в области
   видимости. Сбой после нескольких дельт означал ПОЛНЫЙ второй провайдерский вызов,
   текст которого стримился ПОВЕРХ уже показанного: пользователь видел ответ дважды,
   платформа платила дважды. Образец правильного гейта лежит рядом —
   `execution_plan.run_with_reroute` держит ровно этот случай через `had_content`.

2. **Usage упавшего прогона терялся целиком.** `Runner.run_streamed` — это цикл вызовов
   инструментов; к моменту сбоя в `result.raw_responses` уже лежат завершённые
   `ModelResponse`, оплаченные нами. Их не читал никто: аварийный фолбэк тарифицировал
   только свой собственный вызов.

Путь живой для НАТИВНОГО OpenAI (`base.py`: остальные провайдеры уведены в
chat/completions ради реалтайм-стрима), поэтому «редко» тут означает «у части трафика
всегда», а не «никогда».
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from service.domain.subagents.general import GeneralAgent
from service.events import EventType
from service.schemas.agents import UserContext


def _ctx(**kwargs) -> UserContext:
    return UserContext(user_id="", request_time=datetime.now(UTC), **kwargs)


def _sdk_usage(prompt: int, completion: int):
    return SimpleNamespace(
        usage=SimpleNamespace(
            input_tokens=prompt, output_tokens=completion, total_tokens=prompt + completion
        )
    )


class _FailingRun:
    """Прогон SDK: отдал две дельты, успел закрыть один вызов, затем упал."""

    def __init__(self):
        self.raw_responses = [_sdk_usage(300, 25)]

    async def stream_events(self):
        for piece in ("Начало ", "ответа"):
            yield SimpleNamespace(
                type="raw_response_event",
                data=SimpleNamespace(type="response.output_text.delta", delta=piece),
            )
        raise RuntimeError("SDK stream died")


@pytest.fixture
def sdk_fails_midstream(monkeypatch):
    """Подменяем SDK так, чтобы прогон упал после отданных токенов."""

    class _Runner:
        @staticmethod
        def run_streamed(*args, **kwargs):
            return _FailingRun()

    fake_sdk = SimpleNamespace(
        Agent=lambda **kw: SimpleNamespace(**kw),
        Runner=_Runner,
        RunContextWrapper=lambda payload: payload,
        ModelSettings=lambda **kw: SimpleNamespace(**kw),
    )
    monkeypatch.setitem(__import__("sys").modules, "agents", fake_sdk)
    return fake_sdk


async def _run(agent) -> list:
    return [e async for e in agent._run_sdk_streamed("вопрос", _ctx())]


@pytest.mark.asyncio
async def test_partial_stream_is_not_answered_twice(sdk_fails_midstream, monkeypatch):
    """⚠️ ГЛАВНОЕ: аварийный прогон НЕ запускается поверх уже отданного текста."""
    called = {"fallback": 0}

    async def _never(self, user_input, seq):
        called["fallback"] += 1
        return
        yield  # pragma: no cover

    monkeypatch.setattr(GeneralAgent, "_emergency_chat_fallback", _never, raising=False)

    agent = GeneralAgent({"model": "test-model"})
    events = await _run(agent)

    text = "".join(str(e.data or "") for e in events if e.type == EventType.STREAM_CHUNK)
    assert "Начало ответа" in text, "частичный текст потерян"
    assert called["fallback"] == 0, (
        "аварийный прогон запущен поверх уже показанного текста — пользователь увидит "
        "ответ дважды, а заплатим мы за оба"
    )


@pytest.mark.asyncio
async def test_partial_stream_bills_what_the_provider_already_charged(sdk_fails_midstream):
    """Завершённые до сбоя вызовы SDK оплачены нами — счёт обязан их учесть."""
    agent = GeneralAgent({"model": "test-model"})
    events = await _run(agent)

    billed = 0
    for e in events:
        usage = (e.metadata or {}).get("token_usage") or {}
        billed += int(usage.get("prompt", 0) or 0) + int(usage.get("completion", 0) or 0)

    assert billed == 325, f"провайдер закрыл вызов на 300+25 токенов до сбоя, выставлено {billed}"


@pytest.mark.asyncio
async def test_user_is_told_the_answer_is_incomplete(sdk_fails_midstream):
    """Оборванный ответ помечается — иначе он неотличим от полного."""
    agent = GeneralAgent({"model": "test-model"})
    events = await _run(agent)

    text = "".join(str(e.data or "") for e in events if e.type == EventType.STREAM_CHUNK)
    assert "прерван" in text.lower()

    complete = [e for e in events if e.type == EventType.AGENT_COMPLETE]
    assert complete and complete[-1].metadata.get("interrupted") is True
