"""Откат с LDR на нативный путь обязан быть ВИДЕН, а не только записан в лог.

🔴 ЖИВАЯ ЖАЛОБА: «сработал фоллбек, почему ldr недоступен?» — понять это по ответу было
нельзя. LDR не поднялся (в стенде он за отдельным compose-профилем), сабагент честно
записал в свой лог

    LDR deep research unavailable, falling back to native: LDR login failed

и молча выдал упрощённое исследование. Пользователь получил «Составляю план
исследования…», отчёт с выводами — и счёт, будучи уверен, что отработал движок глубоких
исследований. Самый тихий случай был ещё хуже: если LDR не настроен вовсе, до попытки
подключения дело не доходило, и не появлялось даже WARNING.

Это ровно тот класс, что уже ловили у стратегии LDR: незнакомое имя молча откатывало на
более дешёвый поиск, «пользователь получил бы совсем другой ресёрч, будучи уверенным,
что выбрал глубокий». Тихая подмена продукта — дефект, а не деталь реализации.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from service.domain.subagents.deep_research import DeepResearchAgent
from service.events import EventType
from service.schemas.agents import UserContext


def _ctx() -> UserContext:
    return UserContext(user_id="", request_time=datetime.now(UTC))


@pytest.fixture
def native_only(monkeypatch):
    """LDR выбран, но недоступен; нативный путь отвечает мгновенно."""

    async def _native(self, user_input, context, usage_acc, meta):
        meta["model"] = "fake-model"
        yield await self.stream_text_event("отчёт")

    monkeypatch.setattr(DeepResearchAgent, "_run_native", _native)
    monkeypatch.setattr(DeepResearchAgent, "_resolve_provider", staticmethod(lambda: "auto"))


async def _events(agent):
    return [e async for e in agent.process("тема", _ctx())]


@pytest.mark.asyncio
async def test_unconfigured_ldr_is_announced(native_only, monkeypatch):
    """⚠️ САМЫЙ ТИХИЙ ПУТЬ: LDR не настроен — раньше не было даже строчки в логе."""
    monkeypatch.setattr(
        DeepResearchAgent,
        "_resolve_ldr_settings",
        lambda self: {"base_url": "", "username": "", "password": ""},
    )

    events = await _events(DeepResearchAgent({"model": "fake-model"}))

    degraded = [e for e in events if (e.metadata or {}).get("degraded")]
    assert degraded, (
        "откат на упрощённый путь не отражён нигде — пользователь платит за другой "
        "продукт, не зная об этом"
    )
    assert any(e.type == EventType.STATUS_UPDATE for e in degraded), (
        "признак есть только в метаданных: в трейсе пользователь ничего не увидит"
    )


@pytest.mark.asyncio
async def test_unreachable_ldr_is_announced(native_only, monkeypatch):
    """Настроен, но не отвечает (ровно случай из жалобы: имя `ldr` не резолвится)."""
    from service.infrastructure.integration import ldr_research as ldr_mod

    class _Dead:
        available = True
        active_research_id = None
        model = "fake"

        def __init__(self, **kwargs):
            pass

        async def start_research(self, topic):
            raise ldr_mod.LDRUnavailableError("LDR login failed: No address associated")

        async def aclose(self):
            return None

    monkeypatch.setattr(ldr_mod, "LDRResearchClient", _Dead)

    events = await _events(DeepResearchAgent({"model": "fake-model"}))

    degraded = [e for e in events if (e.metadata or {}).get("degraded")]
    assert degraded, "недоступность движка исследований осталась только в логах"
    reason = str(degraded[0].metadata.get("degraded_reason") or "")
    assert "недоступен" in reason, f"причина не названа: {reason!r}"


@pytest.mark.asyncio
async def test_completion_carries_the_degraded_marker(native_only, monkeypatch):
    """⚠️ Пометка и в итоговых метаданных: событие можно не увидеть.

    Свёрнутый трейс, сторонний клиент, аналитика по прогонам — во всех этих случаях
    нужен признак на самом результате, а не только промежуточное сообщение.
    """
    monkeypatch.setattr(
        DeepResearchAgent,
        "_resolve_ldr_settings",
        lambda self: {"base_url": "", "username": "", "password": ""},
    )

    events = await _events(DeepResearchAgent({"model": "fake-model"}))

    complete = [e for e in events if e.type == EventType.AGENT_COMPLETE]
    assert complete, "нет события завершения"
    assert (complete[-1].metadata or {}).get("degraded") is True, (
        f"результат не помечен как упрощённый: {complete[-1].metadata}"
    )


@pytest.mark.asyncio
async def test_healthy_ldr_is_not_marked_degraded(monkeypatch):
    """Обратная сторона: успешный прогон LDR НЕ помечается деградацией.

    Иначе пометка обесценится — она должна значить «продукт был подменён», а не
    появляться всегда.
    """
    from service.infrastructure.integration import ldr_research as ldr_mod

    async def _ldr(self, client, user_input, context, usage_acc, meta):
        meta["model"] = "ldr-model"
        yield await self.stream_text_event("полноценный отчёт")

    class _Alive:
        available = True
        active_research_id = None
        model = "fake"

        def __init__(self, **kwargs):
            pass

        async def aclose(self):
            return None

    monkeypatch.setattr(ldr_mod, "LDRResearchClient", _Alive)
    monkeypatch.setattr(DeepResearchAgent, "_run_ldr", _ldr)
    monkeypatch.setattr(DeepResearchAgent, "_resolve_provider", staticmethod(lambda: "auto"))

    events = await _events(DeepResearchAgent({"model": "fake-model"}))

    assert not [e for e in events if (e.metadata or {}).get("degraded")], (
        "успешный глубокий ресёрч помечен как упрощённый — признак перестанет что-либо значить"
    )
