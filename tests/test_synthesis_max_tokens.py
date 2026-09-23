"""Потолок синтеза мульти-интента ДЕЙСТВУЕТ.

⚠️ Он не действовал вовсе. `synthesis_max_tokens` объявлен в настройках ОБОИХ сервисов,
задан во всех трёх env-файлах (включая прод) значением 1200, доезжает параметром до
`execute_steps` — и в теле функции не читался ни разу. Синтез генерировал до общего
`chat_max_tokens`, то есть 4096. Админ, выставивший потолок, был уверен, что выставил
его; ошибок при этом не было нигде.

Полный набор из 775 тестов не заметил ни того, что потолка нет, ни того, что он
появился, — поэтому файл и написан.
"""

from __future__ import annotations

import pytest

from service.domain.runners.support import _resolve_chat_max_tokens, max_tokens_override


@pytest.fixture
def general_limit(monkeypatch):
    """Общий потолок чата — 4096, как в дефолте конфига."""
    from service.settings import config

    monkeypatch.setattr(config.agents, "chat_max_tokens", 4096)
    from service.shared.agent_settings import runtime_settings

    monkeypatch.setattr(runtime_settings, "get_agents", lambda name, default=None: default)
    return monkeypatch


def test_override_lowers_the_limit(general_limit):
    with max_tokens_override(1200):
        assert _resolve_chat_max_tokens() == 1200


def test_override_cannot_raise_above_the_admin_limit(general_limit):
    """⚠️ Только ВНИЗ.

    Иначе отдельный шаг конвейера обходил бы лимит, выставленный админом на весь чат, —
    то есть настройка «максимум токенов ответа» переставала бы быть потолком.
    """
    with max_tokens_override(99999):
        assert _resolve_chat_max_tokens() == 4096


@pytest.mark.parametrize("limit", [None, 0, -1], ids=["None", "ноль", "отрицательный"])
def test_absent_override_changes_nothing(general_limit, limit):
    with max_tokens_override(limit):
        assert _resolve_chat_max_tokens() == 4096


def test_override_is_released_after_the_block(general_limit):
    """⚠️ Значение не должно пережить блок: следующий вызов агента — не синтез."""
    with max_tokens_override(1200):
        pass

    assert _resolve_chat_max_tokens() == 4096


def test_override_is_released_on_exception(general_limit):
    """И при исключении тоже — иначе один сбой урезал бы все последующие ответы."""
    with pytest.raises(RuntimeError), max_tokens_override(1200):
        raise RuntimeError("сбой синтеза")

    assert _resolve_chat_max_tokens() == 4096


@pytest.mark.asyncio
async def test_override_does_not_leak_between_concurrent_requests(general_limit):
    """⚠️ ContextVar живёт в пределах задачи — соседний запрос не должен пострадать.

    Это и есть причина выбрать ContextVar, а не глобал: параллельные запросы в одном
    процессе — норма, и урезанный синтез одного не должен обрезать ответ другому.
    """
    import asyncio

    seen: dict[str, int] = {}

    async def with_cap():
        with max_tokens_override(1200):
            await asyncio.sleep(0)
            seen["capped"] = _resolve_chat_max_tokens()

    async def without_cap():
        await asyncio.sleep(0)
        seen["free"] = _resolve_chat_max_tokens()

    await asyncio.gather(with_cap(), without_cap())

    assert seen == {"capped": 1200, "free": 4096}


@pytest.mark.asyncio
async def test_synthesis_runs_under_the_cap(monkeypatch, general_limit):
    """Сквозной: `execute_steps` действительно оборачивает синтез потолком."""
    from service.domain.pipeline import execution_plan
    from service.domain.pipeline.decomposition import SubTask
    from service.events import AgentEvent, EventType

    observed: list[int] = []

    class _Agent:
        name = "general"

        async def process(self, user_input, context):
            observed.append(_resolve_chat_max_tokens())
            yield AgentEvent(type=EventType.STREAM_CHUNK, agent_name="general", data="ответ")

    class _Orch:
        def get_agent(self, _name):
            return _Agent()

    events = [
        e
        async for e in execution_plan.execute_steps(
            orchestrator=_Orch(),
            subtasks=[SubTask(category="general", instruction="шаг")],
            context=None,
            user_input="запрос",
            synthesis_max_tokens=1200,
        )
    ]

    assert events, "синтез не отработал — предпосылка теста неверна"
    assert observed[-1] == 1200, (
        f"синтез шёл с потолком {observed[-1]} вместо 1200 — настройка снова не действует"
    )
