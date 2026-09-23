"""Дедлайн стал БЮДЖЕТОМ: прогон заканчивает сам и отдаёт собранное.

🔴 ЗАЧЕМ. Ограничитель был один — внешний `asyncio.wait_for`. Он умеет только оборвать, в
произвольной точке и вместе с накопленным `per_call_usage`. Прогон, сжёгший десятки тысяч
токенов и упёршийся в дедлайн, тарифицировался по минимальному флору: наружу уходил только
`__error__`, а backend на нём бросал исключение и результата не видел вовсе.

Теперь уровня два:
* МЯГКИЙ живёт в окружении прогона, останавливает работу с резервом на финальный вызов
  модели и отдаёт обычный результат с пометкой `deadline_exceeded`;
* ЖЁСТКИЙ (`wait_for`) остаётся снаружи с запасом и срабатывает только там, где изнутри
  останавливать нечего — провайдер держит соединение и не отдаёт ни дельты.

Про сам `run_timeout_sec` (откуда читается, почему 570) — соседний `test_run_deadline.py`.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from service.events import EventType
from service.shared import deadline as dl


def _at(elapsed: float, limit: float | None, reserve: float = 45.0) -> dl.RunDeadline:
    """Дедлайн, стартовавший `elapsed` секунд назад."""
    return dl.RunDeadline(time.monotonic() - elapsed, limit, reserve)


# --------------------------------------------------------------------------- #
# Арифметика бюджета                                                            #
# --------------------------------------------------------------------------- #
def test_no_limit_means_no_budget_at_all():
    """Ноль/None — аварийный выключатель, и он не должен становиться нулевым бюджетом."""
    d = _at(10, None)

    assert d.remaining() is None
    assert d.clamp(90) == 90
    assert d.must_finalize() is False


def test_clamp_leaves_room_for_the_answer():
    """🔴 Инструменту достаётся остаток МИНУС резерв, иначе ответ уже не успеет."""
    d = _at(elapsed=500, limit=570, reserve=45)  # осталось 70

    assert d.clamp(90) == pytest.approx(25, abs=1), "инструмент забрал время, нужное на ответ"


def test_clamp_never_returns_zero():
    """⚠️ Нулевой таймаут превратил бы «мало времени» в «инструмент всегда падает»."""
    assert _at(elapsed=569, limit=570, reserve=45).clamp(90) == 1.0


def test_clamp_does_not_inflate_a_short_timeout():
    """Бюджет ограничивает сверху, но не раздаёт время сверх запрошенного."""
    assert _at(elapsed=1, limit=570).clamp(20) == 20


def test_must_finalize_turns_on_inside_the_reserve():
    assert _at(elapsed=500, limit=570, reserve=45).must_finalize() is False
    assert _at(elapsed=530, limit=570, reserve=45).must_finalize() is True


def test_without_a_deadline_helpers_are_transparent():
    """Вне прогона (тесты, /v1-шлюз) бюджета нет, и поведение обязано быть прежним."""
    assert dl.clamp(90) == 90
    assert dl.must_finalize() is False
    assert dl.remaining() is None


# --------------------------------------------------------------------------- #
# Вызов инструмента                                                             #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_tool_call_is_clamped_by_the_run_budget(monkeypatch):
    """Медленный инструмент не может съесть время, нужное чтобы ответить."""
    from service.domain.runners import support

    seen: dict = {}
    real_wait_for = asyncio.wait_for

    class _Slow:
        name = "search_web"

        async def on_invoke_tool(self, _ctx, _args):
            await asyncio.sleep(10)
            return "поздно"

    async def _spy(coro, timeout=None):
        seen["timeout"] = timeout
        return await real_wait_for(coro, timeout=0.01)

    monkeypatch.setattr(support.asyncio, "wait_for", _spy)

    with dl.use_deadline(_at(elapsed=540, limit=570, reserve=45)):
        result = await support._invoke_tool(_Slow(), None, "{}")

    assert seen["timeout"] == 1.0, "инструменту дали больше, чем осталось сверх резерва"
    assert "не успел ответить" in result, "модель обязана узнать, что инструмент не ответил"


@pytest.mark.asyncio
async def test_tool_timeout_is_told_to_the_model_not_raised():
    """⚠️ Возврат ТЕКСТОМ, а не исключением: иначе один медленный вызов рушит весь ход."""
    from service.domain.runners import support

    class _Hanging:
        name = "fetch_url"

        async def on_invoke_tool(self, _ctx, _args):
            await asyncio.sleep(5)

    with dl.use_deadline(dl.RunDeadline.start(0.05, reserve_sec=0.0)):
        result = await support._invoke_tool(_Hanging(), None, "{}")

    assert "fetch_url" in result and "Ответь тем, что уже есть" in result


# --------------------------------------------------------------------------- #
# Цикл инструментов                                                             #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_no_new_tool_round_when_only_answer_time_is_left(monkeypatch):
    """🔴 Раунд — это вызовы инструментов ПЛЮС ещё один вызов модели.

    Начав его на исходе бюджета, мы гарантированно не успеваем ничего сказать, и уже
    оплаченная работа пропадает целиком.
    """
    from service.domain.runners import chat_run as runner
    from service.domain.subagents.general import GeneralAgent

    rounds: list[list[dict]] = []

    async def _fake_stream(*, messages, round_state=None, tools=None, **kw):
        rounds.append(list(messages))
        if len(rounds) == 1:
            if round_state is not None:
                round_state.update(
                    {"tool_calls": [{"id": "1", "name": "search_web", "arguments": "{}"}]}
                )
            return
        yield "итоговый ответ"
        if round_state is not None:
            round_state.update({"prompt": 5, "completion": 2, "total": 7, "model": "m"})

    async def _toolset(_self, _model, _context=None):
        from service.domain.capabilities.tool_spec import ToolSet

        return ToolSet(tools=[{"type": "function", "function": {"name": "search_web"}}])

    monkeypatch.setattr(runner, "stream_chat_completion", _fake_stream)
    monkeypatch.setattr(GeneralAgent, "_resolve_toolset", _toolset, raising=False)

    agent = GeneralAgent({"model": "m"})
    with dl.use_deadline(_at(elapsed=540, limit=570, reserve=45)):
        events = [e async for e in agent._run_chat_streamed("вопрос", None)]

    assert EventType.TOOL_CALL_START not in [e.type for e in events], (
        "раунд инструментов запущен на исходе бюджета — ответить уже не успеем"
    )
    assert any(e.type == EventType.STREAM_CHUNK and "итоговый" in str(e.data) for e in events)
    assert any("Время на этот запрос заканчивается" in str(m.get("content", "")) for m in rounds[1])


@pytest.mark.asyncio
async def test_tool_rounds_run_normally_while_there_is_time(monkeypatch):
    """Контроль: без исчерпанного бюджета раунд идёт как раньше.

    Без него предыдущая проверка не отличала бы «инструменты сняты дедлайном» от
    «инструменты не работают вовсе».
    """
    from service.domain.runners import chat_run as runner
    from service.domain.runners import tool_loop
    from service.domain.subagents.general import GeneralAgent

    calls = {"n": 0}

    async def _fake_stream(*, messages, round_state=None, tools=None, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            if round_state is not None:
                round_state.update(
                    {"tool_calls": [{"id": "1", "name": "search_web", "arguments": "{}"}]}
                )
            return
        yield "ответ по найденному"
        if round_state is not None:
            round_state.update({"prompt": 5, "completion": 2, "total": 7, "model": "m"})

    async def _toolset(_self, _model, _context=None):
        from service.domain.capabilities.tool_spec import ToolSet

        return ToolSet(tools=[{"type": "function", "function": {"name": "search_web"}}])

    monkeypatch.setattr(runner, "stream_chat_completion", _fake_stream)
    monkeypatch.setattr(GeneralAgent, "_resolve_toolset", _toolset, raising=False)
    monkeypatch.setattr(tool_loop, "_invoke_tool", lambda *a, **k: _ok())

    async def _ok():
        return "нашлось"

    agent = GeneralAgent({"model": "m"})
    with dl.use_deadline(_at(elapsed=10, limit=570, reserve=45)):
        events = [e async for e in agent._run_chat_streamed("вопрос", None)]

    assert EventType.TOOL_CALL_START in [e.type for e in events]


# --------------------------------------------------------------------------- #
# Деньги: результат доезжает                                                    #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_exhausted_deadline_still_returns_the_bill():
    """🔴 ГЛАВНОЕ. Исчерпанный дедлайн обязан дать результат С УЧТЁННЫМИ токенами.

    Раньше здесь терялся весь `per_call_usage`: задача отменялась внешним `wait_for`,
    наружу уходил только `__error__`, и вызовы, за которые платформа уже заплатила
    провайдеру, в счёт не попадали.
    """
    from service.application.reply_assembler import ReplyAssembler
    from service.application.use_cases.agent_execution_use_cases import RunAgentUseCase
    from service.events import AgentEvent

    class _Processor:
        async def process_message_stream(self, **_kw):
            # Дорогая работа УЖЕ сделана и оплачена провайдеру — именно её счёт и терялся.
            yield AgentEvent(
                type=EventType.STATUS_UPDATE,
                agent_name="general",
                data="",
                metadata={
                    "token_usage": {
                        "prompt": 40_000,
                        "completion": 500,
                        "total": 40_500,
                        "model": "m",
                    }
                },
            )
            yield AgentEvent(type=EventType.STREAM_CHUNK, agent_name="general", data="часть ответа")
            # Дальше прогон продолжался бы — и вот ровно здесь прилетала отмена,
            # уносившая накопленное.
            for _ in range(100):
                yield AgentEvent(type=EventType.STREAM_CHUNK, agent_name="general", data="ещё")

    assembler = ReplyAssembler()
    metadata: dict = {}

    with dl.use_deadline(_at(elapsed=560, limit=570, reserve=45)):
        await RunAgentUseCase().execute(
            processor=_Processor(), reply_assembler=assembler, metadata=metadata, on_event=None
        )

    assert metadata.get("deadline_exceeded") is True, "прогон не пометил, что упёрся в дедлайн"
    assert assembler.per_call_usage, "🔴 счёт потерян: за уже оплаченные вызовы не спишется ничего"
    assert assembler.total_tokens >= 40_500


@pytest.mark.asyncio
async def test_run_is_not_cut_short_while_there_is_time():
    """Контроль: без исчерпанного бюджета прогон дочитывается до конца."""
    from service.application.reply_assembler import ReplyAssembler
    from service.application.use_cases.agent_execution_use_cases import RunAgentUseCase
    from service.events import AgentEvent

    class _Processor:
        async def process_message_stream(self, **_kw):
            for i in range(5):
                yield AgentEvent(type=EventType.STREAM_CHUNK, agent_name="general", data=str(i))

    assembler = ReplyAssembler()
    metadata: dict = {}

    with dl.use_deadline(_at(elapsed=1, limit=570, reserve=45)):
        await RunAgentUseCase().execute(
            processor=_Processor(), reply_assembler=assembler, metadata=metadata, on_event=None
        )

    assert "deadline_exceeded" not in metadata
    assert assembler.build_reply() == "01234"


def test_hard_stop_leaves_room_for_the_soft_one():
    """⚠️ Внешний `wait_for` обязан срабатывать ПОЗЖЕ мягкого, иначе мягкий бесполезен."""
    from service.presentation.routers.agent.run import _HARD_STOP_GRACE_SEC

    assert _HARD_STOP_GRACE_SEC > 0, "жёсткий стоп совпал бы с мягким и снова унёс бы счёт"
