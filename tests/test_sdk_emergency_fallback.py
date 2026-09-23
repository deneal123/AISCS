"""Аварийный chat-вызов, когда SDK-прогон упал целиком.

⚠️ Эта ветка была НЕ ПОКРЫТА ВООБЩЕ — из всего пути проверялось только `callable()`.
При этом она отвечает за две вещи сразу: пользователь получает ответ вместо слова
«ошибка» при живых провайдерах, а платформа выставляет за этот ответ счёт. Молчаливая
поломка здесь означала бы либо «агент не работает», либо бесплатные провайдерские
вызовы — и то и другое незаметно в зелёных тестах.

Пока фолбэк жил внутри `except`, дотянуться до него можно было только уронив SDK.
Теперь это метод, и он проверяется напрямую.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from service.domain.runners import sdk_run
from service.domain.runners.sdk_run import SdkRunMixin, _describe_failure
from service.events import AgentEvent, EventType


class _Agent(SdkRunMixin):
    name = "test-agent"
    instructions = "делай хорошо"
    model_settings: dict = {"model": "acme/chat"}

    def _is_blocked_chat_model(self, model):
        return model == "acme/blocked"

    def _pick_chat_capable_model(self, models):
        return models[0] if models else None

    def _compose_system_instructions(self, context):
        """Зеркало `BaseAgent._compose_system_instructions` (`domain/base.py:158-164`).

        Миксин ОБЯЗАН строить системный промпт общей склейкой, а не из сырых
        `self.instructions`: иначе аварийный ответ теряет `system_context` (факты,
        вложения, знания, план). Фейк повторяет базовое поведение, чтобы тест ловил
        именно это, а не отсутствие метода.
        """
        base = str(self.instructions or "")[:3000]
        extra = getattr(context, "system_context", None) if context else None
        return f"{base}\n\n{extra}" if extra else base


def _resp(text: str, usage: dict | None = None):
    """Ответ провайдера читается через getattr, не как словарь — форму держим такой же."""
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        usage=SimpleNamespace(**usage) if usage else None,
    )


@pytest.fixture
def agent(monkeypatch):
    async def _models():
        return ["acme/auto"]

    monkeypatch.setattr(sdk_run, "list_qualified_models", _models)
    return _Agent()


async def _drain(agent, **_kw):
    return [e async for e in agent._emergency_chat_fallback("вопрос", 0)]


@pytest.mark.asyncio
async def test_fallback_streams_answer_and_bills_it(agent, monkeypatch):
    """Ответ доехал чанками, помечен моделью фолбэка И ПРОТАРИФИЦИРОВАН."""

    async def _completion(**_kw):
        return _resp("Ответ " * 100, {"prompt_tokens": 11, "completion_tokens": 22})

    monkeypatch.setattr(sdk_run, "create_chat_completion", _completion)

    events = await _drain(agent)

    chunks = [e for e in events if e.type == EventType.STREAM_CHUNK]
    complete = [e for e in events if e.type == EventType.AGENT_COMPLETE]
    assert chunks, "аварийный ответ не доехал до пользователя"
    assert all(e.metadata["fallback_model"] == "acme/chat" for e in chunks)
    assert len(complete) == 1
    usage = complete[0].metadata.get("token_usage")
    assert usage, "аварийный ответ ушёл БЕСПЛАТНО — провайдеру заплатили, счёт не выставлен"
    assert usage["model"] == "acme/chat"


@pytest.mark.asyncio
async def test_fallback_carries_system_context(agent, monkeypatch):
    """🔴 Аварийный ответ обязан нести `system_context`, а не голые инструкции.

    Здесь брались сырые `self.instructions[:3000]` мимо `_compose_system_instructions`,
    и аварийный путь терял ВСЁ, что пайплайн собрал: факты о пользователе, вложения
    текущей задачи, знания, план, резюме диалога. Наружу это выглядит не как авария, а
    как «модель вдруг забыла мой файл» — то есть беззвучно и неотличимо от деградации
    качества модели.
    """
    seen: dict = {}

    async def _completion(**kw):
        seen.update(kw)
        return _resp("ок")

    monkeypatch.setattr(sdk_run, "create_chat_completion", _completion)

    context = SimpleNamespace(system_context="## Вложения текущей задачи\nотчёт.pdf: выручка 42")
    events = [e async for e in agent._emergency_chat_fallback("вопрос", 0, context)]

    assert events, "аварийный прогон не дал событий"
    system = next(m["content"] for m in seen["messages"] if m["role"] == "system")
    assert "отчёт.pdf" in system, "аварийный ответ потерял system_context (вложения/факты/план)"
    assert "делай хорошо" in system, "базовые инструкции агента тоже должны остаться"


@pytest.mark.asyncio
async def test_blocked_model_is_replaced_not_used(agent, monkeypatch):
    """Не-чат модель из настроек не должна уехать в chat/completions."""
    agent.model_settings = {"model": "acme/blocked"}
    seen: dict = {}

    async def _completion(**kw):
        seen.update(kw)
        return _resp("ок")

    monkeypatch.setattr(sdk_run, "create_chat_completion", _completion)

    await _drain(agent)

    assert seen["model"] == "acme/auto", "в чат ушла заблокированная модель"


@pytest.mark.parametrize(
    ("scenario", "why"),
    [
        ("no_model", "подходящей модели нет — восстанавливаться нечем"),
        ("empty_text", "пустой ответ не ответ"),
        ("raises", "упал и фолбэк"),
    ],
)
@pytest.mark.asyncio
async def test_fallback_stays_silent_when_it_cannot_recover(agent, monkeypatch, scenario, why):
    """⚠️ Молчание — это контракт: по отсутствию AGENT_COMPLETE вызывающий шлёт ошибку.

    Если бы фолбэк отдал хоть что-то, пользователь получил бы пустой «успех» вместо
    сообщения о сбое.
    """
    if scenario == "no_model":
        agent.model_settings = {}

        async def _none():
            return []

        monkeypatch.setattr(sdk_run, "list_qualified_models", _none)

    async def _completion(**_kw):
        if scenario == "raises":
            raise RuntimeError("провайдер лёг")
        return _resp("   " if scenario == "empty_text" else "ок")

    monkeypatch.setattr(sdk_run, "create_chat_completion", _completion)

    assert await _drain(agent) == [], why


class _BrokenRun(_Agent):
    """Агент, у которого падает подготовка SDK-прогона — штатный вход в аварийную ветку."""

    tools: list = []
    input_guardrails: list = []
    output_guardrails: list = []

    def _compose_system_instructions(self, context):
        raise RuntimeError("SDK-прогон не собрался")


@pytest.mark.asyncio
async def test_caller_emits_error_when_fallback_recovered_nothing():
    """Обратная сторона контракта: пусто от фолбэка → наверх едет ERROR."""

    class _Failing(_BrokenRun):
        async def _emergency_chat_fallback(self, user_input, seq, context=None):
            return
            yield  # pragma: no cover — делает метод генератором

    events = [e async for e in _Failing()._run_sdk_streamed("вопрос", None)]

    assert [e.type for e in events] == [EventType.ERROR]
    assert events[0].metadata["failure_code"] == "remote"
    assert "SDK-прогон не собрался" not in str(events[0].model_dump())


@pytest.mark.asyncio
async def test_caller_returns_quietly_when_fallback_worked():
    """А если фолбэк дал AGENT_COMPLETE — ошибку сверху НЕ дублируем."""

    class _Recovering(_BrokenRun):
        async def _emergency_chat_fallback(self, user_input, seq, context=None):
            yield AgentEvent(type=EventType.STREAM_CHUNK, agent_name=self.name, data="привет")
            yield AgentEvent(type=EventType.AGENT_COMPLETE, agent_name=self.name, data="ok")

    events = [e async for e in _Recovering()._run_sdk_streamed("вопрос", None)]

    assert EventType.ERROR not in [e.type for e in events], "ошибка поверх удавшегося фолбэка"
    assert [e.type for e in events][-1] == EventType.AGENT_COMPLETE


@pytest.mark.asyncio
async def test_missing_sdk_package_does_not_reach_the_fallback(monkeypatch):
    """⚠️ Отсутствие пакета SDK — НЕ повод для аварийного вызова, и это осознанно.

    Проверка импорта стоит до основного try, поэтому фолбэк здесь не запускается: это
    поломка сборки образа, а не сбой провайдера, и подменять её платным chat-вызовом на
    каждом запросе значило бы прятать причину.
    """
    called = False

    class _Watch(_Agent):
        async def _emergency_chat_fallback(self, user_input, seq, context=None):
            nonlocal called
            called = True
            return
            yield  # pragma: no cover

    monkeypatch.setitem(__import__("sys").modules, "agents", None)

    events = [e async for e in _Watch()._run_sdk_streamed("вопрос", None)]

    assert [e.type for e in events] == [EventType.ERROR]
    assert events[0].metadata["failure_code"] == "internal"
    assert "Agent SDK not available" not in str(events[0].model_dump())
    assert not called, "аварийный платный вызов на отсутствующем пакете"


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (ConnectionError("reset"), "Provider temporarily unavailable. Please try again."),
        (TimeoutError(), "Request timed out. Please try again."),
        (
            RuntimeError("request timeout after 30s"),
            "Provider temporarily unavailable. Please try again.",
        ),
        (ValueError("что-то своё"), "Provider temporarily unavailable. Please try again."),
    ],
)
def test_failure_descriptions(exc, expected):
    assert _describe_failure(exc) == expected
