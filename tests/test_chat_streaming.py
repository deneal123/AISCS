"""Tests for real-time chat streaming + message-based context (no repetition)."""

from datetime import UTC, datetime

import pytest

from service.domain import base as base_mod

# ⚠️ Прямой chat/completions-стрим переехал из `base.py` в примесь `runners/chat_run.py`.
# Патчить надо МОДУЛЬ-ВЛАДЕЛЕЦ: `base_mod.stream_chat_completion` после разделения
# перестал бы существовать (AttributeError), а если бы имя там осталось — подмена молча
# ничего бы не делала, и тест был бы зелёным, не проверив ничего.
from service.domain.runners import chat_run as chat_runner
from service.domain.subagents.general import GeneralAgent
from service.events import EventType
from service.schemas.agents import UserContext


def _ctx(**kwargs) -> UserContext:
    return UserContext(user_id="", request_time=datetime.now(UTC), **kwargs)


def test_build_messages_uses_history_and_system_context():
    agent = GeneralAgent({"model": "test-model"})
    ctx = _ctx(
        history_messages=[
            {"role": "user", "content": "как дела"},
            {"role": "assistant", "content": "всё отлично"},
        ],
        system_context="Память: пользователя зовут Данил",
    )
    messages = agent._build_messages("какая погода", ctx)

    assert messages[0]["role"] == "system"
    assert "Память: пользователя зовут Данил" in messages[0]["content"]
    # История — отдельными репликами, не текстом в вопросе.
    assert messages[1] == {"role": "user", "content": "как дела"}
    assert messages[2] == {"role": "assistant", "content": "всё отлично"}
    # Текущий вопрос — последним user-сообщением (без подмешанной истории).
    assert messages[-1] == {"role": "user", "content": "какая погода"}


@pytest.mark.asyncio
async def test_run_chat_streamed_yields_realtime_deltas(monkeypatch):
    # **kwargs: стрим принимает ещё tools/tool_choice/pin_provider (function-calling).
    # Фейк не должен падать на каждом новом параметре транспорта.
    async def _fake_stream(*, messages, model, round_state=None, **kwargs):
        for delta in ["Прив", "ет, ", "Данил"]:
            yield delta
        if round_state is not None:
            round_state.update({"prompt": 12, "completion": 8, "total": 20, "model": model})

    monkeypatch.setattr(chat_runner, "stream_chat_completion", _fake_stream)

    agent = GeneralAgent({"model": "test-model"})
    events = []
    async for event in agent._run_chat_streamed("привет", _ctx()):
        events.append(event)

    chunks = [e for e in events if e.type == EventType.STREAM_CHUNK]
    # Дельты отдаются по мере генерации (реалтайм), а не одним куском в конце.
    assert [c.data for c in chunks] == ["Прив", "ет, ", "Данил"]
    complete = [e for e in events if e.type == EventType.AGENT_COMPLETE]
    assert complete
    # Учёт токенов прикреплён к финальному AGENT_COMPLETE (захват usage Фазы 1).
    assert complete[-1].metadata.get("token_usage") == {
        "prompt": 12,
        "completion": 8,
        "total": 20,
        "model": "test-model",
    }


@pytest.mark.asyncio
async def test_run_chat_streamed_empty_reply_is_error(monkeypatch):
    async def _empty_stream(*, messages, model, round_state=None, **kwargs):
        return
        yield  # pragma: no cover

    monkeypatch.setattr(chat_runner, "stream_chat_completion", _empty_stream)

    agent = GeneralAgent({"model": "test-model"})
    events = [e async for e in agent._run_chat_streamed("привет", _ctx())]
    assert any(e.type == EventType.ERROR for e in events)


# --------------------------------------------------------------------------- #
# Регресс критических веток _run_chat_streamed (страховка под будущий рефактор) #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_run_chat_streamed_seamless_continuation_on_length(monkeypatch):
    """finish_reason=='length' → бесшовное авто-продолжение вторым вызовом, usage
    суммируется по ВСЕМ раундам (провайдер тарифит каждый)."""
    calls = {"n": 0}

    async def _fake_stream(*, messages, model, round_state=None, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            yield "Начало ответа"
            if round_state is not None:
                round_state.update(
                    {
                        "prompt": 10,
                        "completion": 5,
                        "total": 15,
                        "model": model,
                        "finish_reason": "length",
                    }
                )
        else:
            yield " и продолжение"
            if round_state is not None:
                round_state.update(
                    {
                        "prompt": 4,
                        "completion": 6,
                        "total": 10,
                        "model": model,
                        "finish_reason": "stop",
                    }
                )

    monkeypatch.setattr(chat_runner, "stream_chat_completion", _fake_stream)
    agent = GeneralAgent({"model": "test-model"})
    events = [e async for e in agent._run_chat_streamed("длинный вопрос", _ctx())]

    text = "".join(e.data for e in events if e.type == EventType.STREAM_CHUNK)
    assert "Начало ответа" in text and "и продолжение" in text
    assert calls["n"] == 2  # авто-продолжение сделало второй вызов
    complete = [e for e in events if e.type == EventType.AGENT_COMPLETE][-1]
    assert complete.metadata["token_usage"]["completion"] == 11  # 5+6 суммарно


@pytest.mark.asyncio
async def test_run_chat_streamed_interruption_finalizes_partial_and_bills(monkeypatch):
    """Обрыв стрима ПОСЛЕ отданных токенов → финализируем частичное с пометкой и
    ТАРИФИЦИРУЕМ (estimated), а не роняем ошибкой и не отдаём бесплатно."""

    async def _fake_stream(*, messages, model, round_state=None, **kwargs):
        yield "частичный ответ"
        raise TimeoutError("provider ReadTimeout")

    monkeypatch.setattr(chat_runner, "stream_chat_completion", _fake_stream)
    agent = GeneralAgent({"model": "test-model"})
    events = [e async for e in agent._run_chat_streamed("вопрос", _ctx())]

    text = "".join(e.data for e in events if e.type == EventType.STREAM_CHUNK)
    assert "частичный ответ" in text
    assert "прерван" in text.lower()  # пометка о прерывании дописана
    complete = [e for e in events if e.type == EventType.AGENT_COMPLETE]
    assert complete and complete[-1].metadata.get("interrupted") is True
    tu = complete[-1].metadata["token_usage"]
    assert tu["completion"] > 0 and tu.get("estimated") is True


@pytest.mark.asyncio
async def test_run_chat_streamed_tool_cap_graceful_message(monkeypatch):
    """Модель упёрлась в лимит tool-раундов, не дав текста → грациозное сообщение и
    tool_cap_reached, а не голая ошибка «пустой ответ»."""

    async def _always_tools_stream(*, messages, model, round_state=None, **kwargs):
        if round_state is not None:
            round_state.update(
                {
                    "tool_calls": [{"id": "c1", "name": "unknown_tool", "arguments": "{}"}],
                    "finish_reason": "tool_calls",
                    "model": model,
                }
            )
        return
        yield  # pragma: no cover

    async def _tools(self, model, _context=None):
        from service.domain.capabilities.tool_spec import ToolSet

        return ToolSet(tools=[{"type": "function", "function": {"name": "x"}}])

    monkeypatch.setattr(chat_runner, "stream_chat_completion", _always_tools_stream)
    monkeypatch.setattr(base_mod.SimpleStreamingAgent, "_resolve_toolset", _tools, raising=False)
    agent = GeneralAgent({"model": "test-model"})
    agent.max_turns = 2  # быстро упереться в потолок раундов
    events = [e async for e in agent._run_chat_streamed("зациклись на инструментах", _ctx())]

    text = "".join(e.data for e in events if e.type == EventType.STREAM_CHUNK)
    assert "переформул" in text.lower()  # грациозное «переформулируйте запрос…»
    complete = [e for e in events if e.type == EventType.AGENT_COMPLETE]
    assert complete and complete[-1].metadata.get("tool_cap_reached") is True


# --------------------------------------------------------------------------- #
# Учёт токенов: один расчёт на оба выхода                                       #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("reported", "expect_estimated", "why"),
    [
        (
            {"prompt": 100, "completion": 50, "total": 150},
            False,
            "провайдер отчитался полностью — оценивать нечего",
        ),
        (
            {},
            True,
            "MWS/GigaChat не отдают usage в стриме вовсе — без оценки запрос уходит бесплатно",
        ),
        (
            {"prompt": 100},
            True,
            "⚠️ ЧАСТИЧНЫЙ usage: раньше completion уходил нулём, то есть недобилл",
        ),
    ],
)
@pytest.mark.asyncio
async def test_usage_is_never_zero_when_the_model_answered(
    monkeypatch, reported, expect_estimated, why
):
    """За отданный пользователю текст счёт выставляется ВСЕГДА.

    Раньше расчёт жил в двух местах (обрыв стрима и штатное завершение) и расходился:
    штатная ветка работала по принципу «всё или ничего» и при частичном usage
    отправляла completion=0 — платформа платила провайдеру за генерацию, а
    пользователю выставляла счёт только за промпт.
    """

    async def _fake_stream(*, messages, model, round_state=None, **kwargs):
        if round_state is not None:
            round_state.update(reported)
        yield "содержательный ответ модели"

    monkeypatch.setattr(chat_runner, "stream_chat_completion", _fake_stream)
    agent = GeneralAgent({"model": "test-model"})
    events = [e async for e in agent._run_chat_streamed("вопрос", _ctx())]

    tu = [e for e in events if e.type == EventType.AGENT_COMPLETE][-1].metadata["token_usage"]

    assert tu["prompt"] > 0, why
    assert tu["completion"] > 0, why
    assert tu["total"] > 0, why
    assert bool(tu.get("estimated")) is expect_estimated, why


@pytest.mark.asyncio
async def test_reported_usage_is_not_overwritten_by_estimate(monkeypatch):
    """⚠️ Обратная сторона: реальные числа провайдера НЕ подменяются оценкой.

    Иначе «всегда оцениваем» превратилось бы в систематический перебилл, и тесты выше
    этого бы не заметили — они проверяют только, что счёт не нулевой.
    """

    async def _fake_stream(*, messages, model, round_state=None, **kwargs):
        if round_state is not None:
            round_state.update({"prompt": 7, "completion": 3, "total": 10, "model": "real-model"})
        yield "очень длинный ответ, оценка по которому дала бы совсем другие числа " * 20

    monkeypatch.setattr(chat_runner, "stream_chat_completion", _fake_stream)
    agent = GeneralAgent({"model": "test-model"})
    events = [e async for e in agent._run_chat_streamed("вопрос", _ctx())]

    tu = [e for e in events if e.type == EventType.AGENT_COMPLETE][-1].metadata["token_usage"]

    assert (tu["prompt"], tu["completion"], tu["total"]) == (7, 3, 10)
    assert tu["model"] == "real-model"
    assert "estimated" not in tu
