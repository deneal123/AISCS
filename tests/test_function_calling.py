"""Function-calling на нашем стриме (chat/completions).

Регрессия, которую эти тесты закрывают: SDK-путь Agents SDK (где tools передавались
корректно) обойдён для ВСЕХ наших провайдеров ради реалтайм-стрима, а собственный
стрим `tools` не отправлял и `delta.tool_calls` выбрасывал — то есть модель физически
не могла вызвать ни один инструмент.
"""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from service.domain import base as base_mod

# ⚠️ Модуль-ВЛАДЕЛЕЦ, а не фасад: `_accumulate_tool_calls` живёт в `streaming.py`.
from service.domain.client.calls import streaming as client_mod

# ⚠️ Прямой chat/completions-стрим переехал из `base.py` в примесь `runners/chat_run.py`.
# Патчить надо МОДУЛЬ-ВЛАДЕЛЕЦ: `base_mod.stream_chat_completion` после разделения
# перестал бы существовать (AttributeError), а если бы имя там осталось — подмена молча
# ничего бы не делала, и тест был бы зелёным, не проверив ничего.
from service.domain.runners import chat_run as chat_runner
from service.domain.runners import support
from service.domain.subagents.general import GeneralAgent
from service.events import EventType
from service.schemas.agents import UserContext


def _ctx(**kwargs) -> UserContext:
    return UserContext(user_id="", request_time=datetime.now(UTC), **kwargs)


# --------------------------------------------------------------------------- #
# Сборка tool_calls из дельт                                                   #
# --------------------------------------------------------------------------- #
def _tc(index, *, id=None, name=None, arguments=None):
    fn = SimpleNamespace(name=name, arguments=arguments)
    return SimpleNamespace(index=index, id=id, function=fn)


def test_accumulate_tool_calls_joins_argument_fragments():
    """Провайдер шлёт вызов по кускам: id/name только в первом фрагменте, дальше —
    обрывки arguments, которые надо склеить в валидный JSON."""
    acc: dict[int, dict] = {}
    client_mod._accumulate_tool_calls(
        SimpleNamespace(tool_calls=[_tc(0, id="call_1", name="fetch_url", arguments='{"te')]),
        acc,
    )
    client_mod._accumulate_tool_calls(
        SimpleNamespace(tool_calls=[_tc(0, arguments='xt": "прив')]), acc
    )
    client_mod._accumulate_tool_calls(SimpleNamespace(tool_calls=[_tc(0, arguments='ет"}')]), acc)

    assert acc == {0: {"id": "call_1", "name": "fetch_url", "arguments": '{"text": "привет"}'}}


def test_accumulate_tool_calls_keeps_parallel_calls_apart():
    """Параллельные вызовы различаются по index — склеивать их в один нельзя."""
    acc: dict[int, dict] = {}
    client_mod._accumulate_tool_calls(
        SimpleNamespace(
            tool_calls=[
                _tc(0, id="a", name="one", arguments="{}"),
                _tc(1, id="b", name="two", arguments='{"x'),
            ]
        ),
        acc,
    )
    client_mod._accumulate_tool_calls(SimpleNamespace(tool_calls=[_tc(1, arguments='": 1}')]), acc)

    assert acc[0]["name"] == "one"
    assert acc[1] == {"id": "b", "name": "two", "arguments": '{"x": 1}'}


def test_accumulate_ignores_delta_without_tool_calls():
    acc: dict[int, dict] = {}
    client_mod._accumulate_tool_calls(SimpleNamespace(content="просто текст"), acc)
    assert acc == {}


# --------------------------------------------------------------------------- #
# Сериализация FunctionTool → OpenAI                                           #
# --------------------------------------------------------------------------- #
def test_tools_to_openai_shape():
    from service.domain.tools.function_tools import DEFAULT_FUNCTION_TOOLS

    payload = support._tools_to_openai(DEFAULT_FUNCTION_TOOLS)
    assert payload, "инструменты должны сериализоваться"
    names = {t["function"]["name"] for t in payload}
    assert {"fetch_url", "ws_read"} <= names
    for tool in payload:
        assert tool["type"] == "function"
        assert isinstance(tool["function"]["parameters"], dict)


# --------------------------------------------------------------------------- #
# Tool-loop в _run_chat_streamed                                               #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_tool_loop_executes_tool_and_finishes_answer(monkeypatch):
    """Модель просит инструмент → исполняем → второй раунд с результатом → ответ."""
    rounds: list[list[dict]] = []

    async def _fake_stream(*, messages, model, round_state=None, tools=None, **kwargs):
        rounds.append(list(messages))
        if len(rounds) == 1:
            assert tools, "в первый раунд инструменты обязаны уйти в запрос"
            if round_state is not None:
                round_state.update(
                    {
                        "provider": "routerai",
                        "finish_reason": "tool_calls",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "name": "fetch_url",
                                "arguments": '{"text": "очень длинный текст"}',
                            }
                        ],
                    }
                )
            return
        yield "Готово"
        if round_state is not None:
            round_state.update({"prompt": 10, "completion": 2, "total": 12, "model": model})

    monkeypatch.setattr(chat_runner, "stream_chat_completion", _fake_stream)
    # Модель «умеет» tools — гейт не должен их срезать.
    monkeypatch.setattr(
        base_mod.SimpleStreamingAgent, "_resolve_toolset", _always_tools, raising=False
    )

    agent = GeneralAgent({"model": "test-model"})
    events = [e async for e in agent._run_chat_streamed("сократи", _ctx())]

    kinds = [e.type for e in events]
    assert EventType.TOOL_CALL_START in kinds
    assert EventType.TOOL_CALL_COMPLETE in kinds

    # Второй раунд получил и вызов ассистента, и результат инструмента.
    assert len(rounds) == 2
    second = rounds[1]
    assistant_call = next(m for m in second if m.get("tool_calls"))
    assert assistant_call["tool_calls"][0]["function"]["name"] == "fetch_url"
    tool_reply = next(m for m in second if m.get("role") == "tool")
    assert tool_reply["tool_call_id"] == "call_1"
    # ⚠️ Проверяем, что результат инструмента ДОЕХАЛ до второго раунда, а не его текст:
    # раньше здесь стоял `summarize_brief`, который просто возвращал переданную строку.
    # Его удалили (детерминированная обрезка, выданная модели как «сделать резюме»), и
    # содержимое ответа теперь принадлежит инструменту, а не тесту.
    assert tool_reply["content"].strip()

    # Пользователь видит ТОЛЬКО текст, никакого JSON аргументов.
    text = "".join(e.data for e in events if e.type == EventType.STREAM_CHUNK)
    assert text == "Готово"


@pytest.mark.asyncio
async def test_tools_not_sent_when_model_lacks_support(monkeypatch):
    """Модель без function-calling: `tools` в payload не уходит (иначе провайдер даёт 400)."""
    seen: dict = {}

    async def _fake_stream(*, messages, model, round_state=None, tools=None, **kwargs):
        seen["tools"] = tools
        yield "ответ"
        if round_state is not None:
            round_state.update({"prompt": 1, "completion": 1, "total": 2, "model": model})

    async def _no_tools(_self, _model, _context=None):
        from service.domain.capabilities.tool_spec import ToolSet

        return ToolSet()

    monkeypatch.setattr(chat_runner, "stream_chat_completion", _fake_stream)
    monkeypatch.setattr(base_mod.SimpleStreamingAgent, "_resolve_toolset", _no_tools, raising=False)

    agent = GeneralAgent({"model": "test-model"})
    events = [e async for e in agent._run_chat_streamed("привет", _ctx())]

    assert seen["tools"] is None
    assert "".join(e.data for e in events if e.type == EventType.STREAM_CHUNK) == "ответ"


@pytest.mark.asyncio
async def test_tool_loop_pins_provider_across_rounds(monkeypatch):
    """Раунды tool-loop обязаны идти к ОДНОМУ провайдеру: иначе второй раунд уедет к
    тому, кто про этот tool_call_id ничего не знает."""
    pins: list[str | None] = []

    async def _fake_stream(*, messages, model, round_state=None, pin_provider=None, **kwargs):
        pins.append(pin_provider)
        if len(pins) == 1:
            if round_state is not None:
                round_state.update(
                    {
                        "provider": "gigachat",
                        "tool_calls": [{"id": "c1", "name": "fetch_url", "arguments": "{}"}],
                    }
                )
            return
        yield "ок"

    monkeypatch.setattr(chat_runner, "stream_chat_completion", _fake_stream)
    monkeypatch.setattr(
        base_mod.SimpleStreamingAgent, "_resolve_toolset", _always_tools, raising=False
    )

    agent = GeneralAgent({"model": "test-model"})
    [e async for e in agent._run_chat_streamed("который час", _ctx())]

    assert pins == [None, "gigachat"]


@pytest.mark.asyncio
async def test_unknown_tool_reported_to_model_not_crash(monkeypatch):
    """Модель выдумала инструмент — сообщаем ей об этом, а не роняем ход."""

    calls: list[list[dict]] = []

    async def _fake_stream(*, messages, model, round_state=None, **kwargs):
        calls.append(list(messages))
        if len(calls) == 1:
            if round_state is not None:
                round_state.update(
                    {
                        "provider": "routerai",
                        "tool_calls": [{"id": "c1", "name": "не_существует", "arguments": "{}"}],
                    }
                )
            return
        yield "продолжаю"

    monkeypatch.setattr(chat_runner, "stream_chat_completion", _fake_stream)
    monkeypatch.setattr(
        base_mod.SimpleStreamingAgent, "_resolve_toolset", _always_tools, raising=False
    )

    agent = GeneralAgent({"model": "test-model"})
    events = [e async for e in agent._run_chat_streamed("зови", _ctx())]

    assert not any(e.type == EventType.ERROR for e in events)
    tool_reply = next(m for m in calls[1] if m.get("role") == "tool")
    assert "недоступен" in tool_reply["content"]


async def _always_tools(_self, _model, _context=None):
    from service.domain.capabilities.tool_spec import ToolSet
    from service.domain.tools.function_tools import DEFAULT_FUNCTION_TOOLS

    return ToolSet(tools=support._tools_to_openai(DEFAULT_FUNCTION_TOOLS))
