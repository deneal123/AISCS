"""Деньги на ВЕТКАХ ОШИБКИ: вызов состоялся, что-то пошло не так — кто заплатил.

⚠️ Общая форма дыры в покрытии. Денежные тесты репозитория плотно закрывают путь «вызов
состоялся → usage посчитан» и почти не закрывают «вызов состоялся → сбой → usage». Все
находки ниже живут именно в ветках лимита, таймаута и исключения.

## Когда потеря — настоящая (проверено чтением backend'а)

`chat_worker_tasks.py:668`: если `total_tokens <= 0` (usage не пришёл вовсе) и ответ
отдан — списывается резерв-флор, то есть запрос НЕ бесплатен. Цена при этом считается из
`per_call_usage` (`pricing_service.py:87-102`), поле `total` в ней не участвует.

Отсюда: **вызов достаётся даром ровно тогда, когда он отсутствует в `per_call_usage`, а
запрос в целом usage отдал** — тогда флор не включается и недостача не видна ничем. Это
типовой случай: мета-вызовы (роутинг, декомпозиция) обычно отчитываются, поэтому
`total_tokens > 0` почти всегда.

## Образец правильного поведения — рядом, в том же файле

`chat_run.py:269-281`: обрыв стрима после отданных токенов финализирует частичный ответ
И отдаёт `token_usage` (пусть оценкой). Ветки `tool_cap` (`:300-305`) и «пустой ответ»
(`:307-312`) устроены иначе — сравнение с соседом и есть аргумент.

⚠️ Почему это не поймал существующий тест `test_chat_streaming.py:157`: его фейк-стрим
кладёт в `usage_out` только `tool_calls`, без `prompt`/`completion`. Токенов в сценарии
нет вовсе, поэтому их нечего было потерять — путь исполняется, но проверяется лишь флаг
`tool_cap_reached`. Тест выглядит покрывающим и легитимизирует бесплатные раунды.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from service.domain.runners import chat_run as chat_runner
from service.domain.subagents.general import GeneralAgent
from service.events import EventType
from service.schemas.agents import UserContext


def _ctx(**kwargs) -> UserContext:
    return UserContext(user_id="", request_time=datetime.now(UTC), **kwargs)


def _billed(events) -> int:
    """Сколько токенов доехало до счёта: сумма prompt+completion по token_usage."""
    total = 0
    for e in events:
        usage = (e.metadata or {}).get("token_usage") or {}
        total += int(usage.get("prompt", 0) or 0) + int(usage.get("completion", 0) or 0)
    return total


# --------------------------------------------------------------------------- #
# tool_cap: модель израсходовала раунды, не дав текста                          #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_tool_cap_bills_the_rounds_it_already_paid_for(monkeypatch):
    """⚠️ Каждый tool-раунд — полный провайдерский вызов с растущим контекстом.

    Упереться в лимит — не повод отдать их даром: работа выполнена и оплачена нами.
    Это самые дорогие запросы во всём потоке (до `max_tool_rounds` вызовов подряд).
    """
    rounds = {"n": 0}

    async def _always_tools_stream(*, messages, model, round_state=None, **kwargs):
        rounds["n"] += 1
        if round_state is not None:
            round_state.update(
                {
                    "prompt": 500,
                    "completion": 40,
                    "total": 540,
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
    monkeypatch.setattr(GeneralAgent, "_resolve_toolset", _tools, raising=False)

    agent = GeneralAgent({"model": "test-model"})
    events = [e async for e in agent._run_chat_streamed("вопрос", _ctx())]

    complete = [e for e in events if e.type == EventType.AGENT_COMPLETE]
    assert complete, "AGENT_COMPLETE не отдан — предпосылка теста неверна"
    assert complete[-1].metadata.get("tool_cap_reached") is True

    spent = rounds["n"] * 540
    assert spent > 0, "провайдера не звали — предпосылка теста неверна"
    assert _billed(events) == spent, (
        f"провайдеру заплачено за {rounds['n']} раунд(ов) = {spent} токенов, "
        f"пользователю выставлено {_billed(events)}"
    )


# --------------------------------------------------------------------------- #
# Пустой ответ модели                                                           #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_empty_response_still_bills_the_prompt(monkeypatch):
    """⚠️ «Модель вернула пустой ответ» — промпт уже обработан и оплачен.

    Провайдер тарифицирует prompt-токены независимо от того, что он сгенерировал.
    """

    async def _empty_stream(*, messages, model, round_state=None, **kwargs):
        if round_state is not None:
            round_state.update({"prompt": 800, "completion": 0, "total": 800, "model": model})
        return
        yield  # pragma: no cover

    monkeypatch.setattr(chat_runner, "stream_chat_completion", _empty_stream)

    agent = GeneralAgent({"model": "test-model"})
    events = [e async for e in agent._run_chat_streamed("вопрос", _ctx())]

    assert any(e.type == EventType.ERROR for e in events), "предпосылка: путь пустого ответа"
    assert _billed(events) == 800, (
        f"промпт на 800 токенов обработан провайдером, выставлено {_billed(events)}"
    )


# --------------------------------------------------------------------------- #
# Контроль: сосед по файлу делает правильно                                     #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_interrupted_stream_bills_and_is_the_reference(monkeypatch):
    """Обрыв после отданных токенов тарифицируется — с этим сравниваем две ветки выше.

    Если этот тест когда-нибудь покраснеет, значит сломался ОБРАЗЕЦ, а не находка.
    """

    async def _fake_stream(*, messages, model, usage_out=None, **kwargs):
        yield "частичный ответ"
        raise TimeoutError("provider ReadTimeout")

    monkeypatch.setattr(chat_runner, "stream_chat_completion", _fake_stream)

    agent = GeneralAgent({"model": "test-model"})
    events = [e async for e in agent._run_chat_streamed("вопрос", _ctx())]

    assert _billed(events) > 0, "прерванный стрим не тарифицируется — сломан образец"
