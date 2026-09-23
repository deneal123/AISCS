"""Инструменты одного раунда исполняются ПАРАЛЛЕЛЬНО.

⚠️ Шли строго по одному, хотя независимы по определению: модель запросила их вместе, ни
один не видит результата другого. Получалась СУММА латентностей вместо максимума — два
`fetch_url` с таймаутом 20 с давали 40 с, а `analyze_data` (сайдкар DuckDB) бюджетирует
60 с сам по себе. Для пользователя это тишина посреди уже начавшегося ответа.

## Что здесь легко сломать незаметно

Порядок. Провайдер ждёт ответы, соответствующие своим `tool_call_id`, и реплика
ассистента с вызовами уже лежит в `convo` перед результатами. Перепутай порядок — и
следующий раунд уедет с несоответствием, а выглядеть это будет как «модель вдруг
отвечает не по делу». Поэтому порядок проверяется отдельно от параллельности.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from service.domain.runners import tool_loop as chat_runner
from service.domain.runners.tool_execution import ToolCallCache, ToolCallOutcome
from service.domain.subagents.general import GeneralAgent
from service.events import EventType
from service.schemas.agents import UserContext


def _ctx(**kwargs) -> UserContext:
    return UserContext(user_id="", request_time=datetime.now(UTC), **kwargs)


def _calls(n: int) -> list[dict]:
    return [{"id": f"c{i}", "name": f"tool{i}", "arguments": "{}"} for i in range(n)]


@pytest.fixture
def slow_tools(monkeypatch):
    """Каждый инструмент «работает» 100 мс и отчитывается своим именем."""
    started: list[str] = []

    async def _fake_invoke(tool, ctx, arguments):
        started.append(tool)
        await asyncio.sleep(0.1)
        return f"результат {tool}"

    monkeypatch.setattr(chat_runner, "_invoke_tool", _fake_invoke)
    return started


async def _round(agent, calls, tool_index):
    convo: list[dict] = []
    events = [
        e
        async for e in agent._execute_tool_round(
            convo, calls, tool_index, None, "текст до вызова", set()
        )
    ]
    return convo, events


@pytest.mark.asyncio
async def test_tools_run_concurrently(slow_tools):
    """⚠️ ГЛАВНОЕ: четыре инструмента по 100 мс — это ~100 мс, а не ~400."""
    agent = GeneralAgent({"model": "test-model"})
    calls = _calls(4)
    index = {c["name"]: c["name"] for c in calls}

    started = asyncio.get_event_loop().time()
    await _round(agent, calls, index)
    elapsed = asyncio.get_event_loop().time() - started

    assert len(slow_tools) == 4, "не все инструменты вызваны"
    assert elapsed < 0.3, (
        f"раунд занял {elapsed:.2f} с при четырёх инструментах по 0.1 с — "
        "исполнение последовательное, пользователь ждёт сумму, а не максимум"
    )


@pytest.mark.asyncio
async def test_results_keep_the_order_of_calls(slow_tools):
    """⚠️ Порядок ответов = порядок вызовов: провайдер сопоставляет их по tool_call_id."""
    agent = GeneralAgent({"model": "test-model"})
    calls = _calls(4)
    index = {c["name"]: c["name"] for c in calls}

    convo, _ = await _round(agent, calls, index)

    tool_msgs = [m for m in convo if m.get("role") == "tool"]
    assert [m["tool_call_id"] for m in tool_msgs] == ["c0", "c1", "c2", "c3"]
    assert [m["content"] for m in tool_msgs] == [f"результат tool{i}" for i in range(4)]


@pytest.mark.asyncio
async def test_unknown_tool_does_not_break_the_round(slow_tools):
    """Неизвестный инструмент отвечает МОДЕЛИ текстом, а не роняет раунд."""
    agent = GeneralAgent({"model": "test-model"})
    calls = _calls(3)
    index = {"tool0": "tool0", "tool2": "tool2"}  # tool1 отсутствует

    convo, _ = await _round(agent, calls, index)

    tool_msgs = [m for m in convo if m.get("role") == "tool"]
    assert len(tool_msgs) == 3, "пропавший инструмент съел ответ — раунд уедет неполным"
    assert "недоступен" in tool_msgs[1]["content"]


@pytest.mark.asyncio
async def test_every_call_reports_start_and_complete(slow_tools):
    """Трейс не должен обеднеть от распараллеливания."""
    agent = GeneralAgent({"model": "test-model"})
    calls = _calls(3)
    index = {c["name"]: c["name"] for c in calls}

    _, events = await _round(agent, calls, index)

    starts = [e for e in events if e.type == EventType.TOOL_CALL_START]
    completes = [e for e in events if e.type == EventType.TOOL_CALL_COMPLETE]
    assert len(starts) == 3
    assert len(completes) == 3


@pytest.mark.asyncio
async def test_tool_lifecycle_statuses_are_safe_and_counted(slow_tools):
    """Новый trace-контракт не раскрывает arguments или результат инструмента."""
    agent = GeneralAgent({"model": "test-model"})
    calls = [{"id": "c0", "name": "tool0", "arguments": '{"secret":"never-send"}'}]
    summary: dict = {}

    events = [
        value
        async for value in agent._execute_tool_round(
            [], calls, {"tool0": "tool0"}, None, "", set(), round_number=2, summary=summary
        )
    ]

    statuses = [event for event in events if event.type == EventType.STATUS_UPDATE]
    progress = [
        event.metadata.get("tool_progress")
        for event in statuses
        if event.metadata.get("kind") == "tool_progress"
    ]
    assert [item["status"] for item in progress] == ["running", "succeeded"]
    assert all("secret" not in str(event.metadata) for event in statuses)
    assert summary == {"executed": 1, "succeeded": 1}


@pytest.mark.asyncio
async def test_identical_canonical_call_is_reused_without_a_second_charge(monkeypatch):
    invocations: list[str] = []
    charges: list[str] = []

    async def invoke(_tool, _ctx, arguments):
        invocations.append(arguments)
        return "cached-result"

    monkeypatch.setattr(chat_runner, "_invoke_tool", invoke)
    monkeypatch.setattr(
        GeneralAgent,
        "_billable_tools_meta",
        classmethod(lambda _cls, name, _billed: charges.append(name) or {"tool_name": name}),
    )
    agent = GeneralAgent({"model": "test-model"})
    cache = ToolCallCache()
    summary: dict = {}
    first = [{"id": "one", "name": "search_web", "arguments": '{"q":"same","n":1}'}]
    second = [{"id": "two", "name": "search_web", "arguments": '{"n":1,"q":"same"}'}]

    first_events = [
        event
        async for event in agent._execute_tool_round(
            [], first, {"search_web": "tool"}, None, "", set(), cache=cache, summary=summary
        )
    ]
    second_events = [
        event
        async for event in agent._execute_tool_round(
            [], second, {"search_web": "tool"}, None, "", set(), cache=cache, summary=summary
        )
    ]

    assert invocations == ['{"q":"same","n":1}']
    assert charges == ["search_web"]
    assert any(
        event.metadata.get("tool_progress", {}).get("status") == "reused" for event in second_events
    )
    assert summary["reused"] == 1 and summary["executed"] == 1
    assert all("q" not in str(event.metadata) for event in first_events + second_events)


@pytest.mark.asyncio
async def test_different_arguments_are_not_deduplicated(monkeypatch):
    invocations: list[str] = []

    async def invoke(_tool, _ctx, arguments):
        invocations.append(arguments)
        return "result"

    monkeypatch.setattr(chat_runner, "_invoke_tool", invoke)
    agent = GeneralAgent({"model": "test-model"})
    cache = ToolCallCache()
    for call in (
        {"id": "one", "name": "tool", "arguments": '{"q":"first"}'},
        {"id": "two", "name": "tool", "arguments": '{"q":"second"}'},
    ):
        _ = [
            event
            async for event in agent._execute_tool_round(
                [], [call], {"tool": "tool"}, None, "", set(), cache=cache
            )
        ]
    assert invocations == ['{"q":"first"}', '{"q":"second"}']


@pytest.mark.asyncio
async def test_dedup_observe_records_repeat_without_changing_execution(monkeypatch):
    invocations: list[str] = []

    async def invoke(_tool, _ctx, arguments):
        invocations.append(arguments)
        return "result"

    monkeypatch.setattr(chat_runner, "_invoke_tool", invoke)
    agent = GeneralAgent({"model": "test-model"})
    cache = ToolCallCache()
    summary: dict = {}
    call = {"id": "one", "name": "search_web", "arguments": "{}"}
    for call_id in ("one", "two"):
        call["id"] = call_id
        _ = [
            event
            async for event in agent._execute_tool_round(
                [],
                [call],
                {"search_web": "tool"},
                None,
                "",
                set(),
                cache=cache,
                dedup_mode="observe",
                summary=summary,
            )
        ]
    assert invocations == ["{}", "{}"]
    assert summary["dedup_observed"] == 1
    assert summary.get("reused", 0) == 0


@pytest.mark.asyncio
async def test_identical_safe_calls_coalesce_inside_one_parallel_round(monkeypatch):
    """S13: second equal call awaits the first one, keeps its own tool_call_id and is free."""
    invocations: list[str] = []
    charges: list[str] = []

    async def invoke(_tool, _ctx, arguments):
        invocations.append(arguments)
        await asyncio.sleep(0)
        return "shared-result"

    monkeypatch.setattr(chat_runner, "_invoke_tool", invoke)
    monkeypatch.setattr(
        GeneralAgent,
        "_billable_tools_meta",
        classmethod(lambda _cls, name, _billed: charges.append(name) or {"tool_name": name}),
    )
    calls = [
        {"id": "one", "name": "search_web", "arguments": '{"q":"same","n":1}'},
        {"id": "two", "name": "search_web", "arguments": '{"n":1,"q":"same"}'},
    ]
    convo: list[dict] = []
    events = [
        event
        async for event in GeneralAgent({"model": "test-model"})._execute_tool_round(
            convo,
            calls,
            {"search_web": "tool"},
            None,
            "",
            set(),
            cache=ToolCallCache(),
            dedup_mode="enforce",
        )
    ]

    assert invocations == ['{"q":"same","n":1}']
    assert charges == ["search_web"]
    assert [message["tool_call_id"] for message in convo if message.get("role") == "tool"] == [
        "one",
        "two",
    ]
    progress = [
        event.metadata["tool_progress"]
        for event in events
        if event.type == EventType.STATUS_UPDATE and event.metadata.get("kind") == "tool_progress"
    ]
    assert [item["status"] for item in progress] == ["running", "running", "succeeded", "reused"]
    assert progress[-1]["dedup_reason"] == "inflight"
    assert all("q" not in str(event.metadata) for event in events)


@pytest.mark.asyncio
async def test_retryable_failure_is_not_cached_for_later_model_round(monkeypatch):
    invocations = 0

    async def invoke(_tool, _ctx, _arguments):
        nonlocal invocations
        invocations += 1
        if invocations == 1:
            return ToolCallOutcome("temporary", "failed", 0.0, retryable=True, billable=False)
        return "recovered"

    monkeypatch.setattr(chat_runner, "_invoke_tool", invoke)
    cache = ToolCallCache()
    agent = GeneralAgent({"model": "test-model"})
    for call_id in ("one", "two"):
        _ = [
            event
            async for event in agent._execute_tool_round(
                [],
                [{"id": call_id, "name": "search_web", "arguments": "{}"}],
                {"search_web": "tool"},
                None,
                "",
                set(),
                cache=cache,
                dedup_mode="enforce",
            )
        ]

    assert invocations == 2


@pytest.mark.asyncio
async def test_terminal_failure_is_reused_without_a_second_invocation(monkeypatch):
    invocations = 0

    async def invoke(_tool, _ctx, _arguments):
        nonlocal invocations
        invocations += 1
        return ToolCallOutcome("terminal", "terminal", 0.0, billable=False)

    monkeypatch.setattr(chat_runner, "_invoke_tool", invoke)
    agent = GeneralAgent({"model": "test-model"})
    cache = ToolCallCache()
    events_by_round = []
    for call_id in ("one", "two"):
        events_by_round.append(
            [
                event
                async for event in agent._execute_tool_round(
                    [],
                    [{"id": call_id, "name": "search_web", "arguments": "{}"}],
                    {"search_web": "tool"},
                    None,
                    "",
                    set(),
                    cache=cache,
                    dedup_mode="enforce",
                )
            ]
        )

    assert invocations == 1
    reused = [
        event.metadata["tool_progress"]
        for event in events_by_round[-1]
        if event.type == EventType.STATUS_UPDATE
        and event.metadata.get("kind") == "tool_progress"
        and event.metadata.get("tool_progress", {}).get("status") == "reused"
    ]
    assert len(reused) == 1
    assert reused[0]["dedup_reason"] == "completed"
    assert reused[0]["retryable"] is False


@pytest.mark.asyncio
async def test_unsafe_tool_is_never_reused_even_in_enforce(monkeypatch):
    invocations: list[str] = []

    async def invoke(_tool, _ctx, arguments):
        invocations.append(arguments)
        return "done"

    monkeypatch.setattr(chat_runner, "_invoke_tool", invoke)
    calls = [
        {"id": "one", "name": "ws_write", "arguments": '{"path":"a","content":"x"}'},
        {"id": "two", "name": "ws_write", "arguments": '{"content":"x","path":"a"}'},
    ]
    events = [
        event
        async for event in GeneralAgent({"model": "test-model"})._execute_tool_round(
            [], calls, {"ws_write": "tool"}, None, "", set(), cache=ToolCallCache()
        )
    ]

    assert len(invocations) == 2
    assert not any(
        event.metadata.get("tool_progress", {}).get("status") == "reused" for event in events
    )
