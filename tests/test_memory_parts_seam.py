"""Швы входных данных для выноса agents в сайдкар (Фаза 0b, stateless).

`resolve_memory_parts` / `resolve_history` — единый контракт «prefer passed-in, else
fetch»: бэкенд собирает данные (память, историю, резюме) и кладёт их в запрос, а
пайплайн НЕ лезет в MemoryService / PG-сессию, если данные уже пришли. Fallback
(данных нет) грузит сам, как раньше. Эти тесты фиксируют контракт, чтобы Фаза 4
(HTTP-движок) не всплыла регрессией — сайдкар не имеет доступа к MemOS/PG/Redis
backend'а и обязан получать данные телом запроса.
"""

import logging

import pytest

from service.domain.pipeline import context_enricher

logger = logging.getLogger(__name__)


@pytest.mark.asyncio
async def test_passed_in_parts_used_verbatim_without_fetch(monkeypatch) -> None:
    """Готовая память из запроса возвращается как есть; собственный fetch НЕ дёргается."""
    called = False

    async def _spy(*a, **k):
        nonlocal called
        called = True
        return "SHOULD-NOT", "BE-USED"

    monkeypatch.setattr(context_enricher, "load_memory_parts", _spy)

    facts, recall = await context_enricher.resolve_memory_parts(
        ("FACTS", "RECALL"),
        user_id=42,
        memory_enabled=True,
        query="привет",
        logger=logger,
    )

    assert (facts, recall) == ("FACTS", "RECALL")
    assert called is False, "память пришла готовой — MemoryService трогать нельзя (не stateless)"


@pytest.mark.asyncio
async def test_passed_in_parts_win_even_when_memory_disabled(monkeypatch) -> None:
    """Гейт memory_enabled НЕ применяется к готовым данным — их уже отгейтил бэкенд."""

    async def _boom(*a, **k):
        raise AssertionError("fetch не должен вызываться при готовых memory_parts")

    monkeypatch.setattr(context_enricher, "load_memory_parts", _boom)

    # Бэкенд при выключенной памяти передаёт пустые слои — их и возвращаем как есть.
    assert await context_enricher.resolve_memory_parts(
        ("", ""), user_id=1, memory_enabled=False, query="q", logger=logger
    ) == ("", "")


@pytest.mark.asyncio
async def test_none_disabled_returns_empty_without_fetch(monkeypatch) -> None:
    """Данных нет + память выключена → пустые слои, БЕЗ обращения к MemoryService."""

    async def _boom(*a, **k):
        raise AssertionError("выключенная память не должна ходить в MemoryService")

    monkeypatch.setattr(context_enricher, "load_memory_parts", _boom)

    assert await context_enricher.resolve_memory_parts(
        None, user_id=7, memory_enabled=False, query="q", logger=logger
    ) == ("", "")


@pytest.mark.asyncio
async def test_none_enabled_falls_back_to_fetch(monkeypatch) -> None:
    """Fallback (данных нет, память включена): грузим сами, query прокидывается в recall."""
    seen: dict = {}

    async def _fetch(user_id, log, query=None):
        seen["user_id"] = user_id
        seen["query"] = query
        return "F-fetched", "R-fetched"

    monkeypatch.setattr(context_enricher, "load_memory_parts", _fetch)

    facts, recall = await context_enricher.resolve_memory_parts(
        None, user_id=99, memory_enabled=True, query="что нового", logger=logger
    )

    assert (facts, recall) == ("F-fetched", "R-fetched")
    assert seen == {"user_id": 99, "query": "что нового"}


# --------------------------------------------------------------------------- #
# resolve_history — история диалога (Фаза 0b.3)                                 #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_history_passed_in_used_verbatim_without_session_read(monkeypatch) -> None:
    """Готовая история из запроса возвращается как есть; сессию НЕ читаем."""

    async def _boom(*a, **k):
        raise AssertionError("история пришла готовой — сессию трогать нельзя (не stateless)")

    monkeypatch.setattr(context_enricher, "load_history_items", _boom)

    given = [
        {"role": "user", "content": "привет"},
        {"role": "assistant", "content": "здравствуйте"},
    ]
    out = await context_enricher.resolve_history(
        given,
        object(),  # сессия-заглушка: не должна быть прочитана
        logger,
        compact_summary="есть резюме",
        history_limit=8,
        summary_keep_recent=6,
    )
    assert out is given


@pytest.mark.asyncio
async def test_history_fallback_uses_full_limit_without_summary(monkeypatch) -> None:
    """Fallback без резюме: грузим из сессии с полным history_limit."""
    seen: dict = {}

    async def _load(session, log, *, limit_messages):
        seen["limit"] = limit_messages
        return [{"role": "user", "content": "x"}]

    monkeypatch.setattr(context_enricher, "load_history_items", _load)

    out = await context_enricher.resolve_history(
        None, object(), logger, compact_summary="", history_limit=8, summary_keep_recent=6
    )
    assert out == [{"role": "user", "content": "x"}]
    assert seen["limit"] == 8  # без резюме — полный лимит


@pytest.mark.asyncio
async def test_history_fallback_uses_keep_recent_with_summary(monkeypatch) -> None:
    """Fallback с резюме (компактизация): живая история обрезается до keep_recent."""
    seen: dict = {}

    async def _load(session, log, *, limit_messages):
        seen["limit"] = limit_messages
        return []

    monkeypatch.setattr(context_enricher, "load_history_items", _load)

    await context_enricher.resolve_history(
        None, object(), logger, compact_summary="РЕЗЮМЕ", history_limit=8, summary_keep_recent=6
    )
    assert seen["limit"] == 6  # есть резюме — обрезаем живую историю до keep_recent


# --------------------------------------------------------------------------- #
# Интеграция: переданные история+резюме доходят до СОБРАННОГО контекста          #
# --------------------------------------------------------------------------- #
class _CapturingGeneral:
    """general-агент, запоминающий полученный контекст (как в test_multimodal_fanout)."""

    name = "general"

    def __init__(self) -> None:
        self.last_context = None

    async def process(self, user_input, context):
        from service.events import AgentEvent, EventType

        self.last_context = context
        yield AgentEvent(type=EventType.STREAM_CHUNK, agent_name="general", data="OK")


@pytest.mark.asyncio
async def test_passed_history_and_summary_reach_assembled_context() -> None:
    """Сквозь РЕАЛЬНЫЙ process_message_stream: собранные бэкендом история и резюме
    доходят до собранного контекста БЕЗ чтения сессии/Redis (session=None,
    compact_summary передан). Если бы пайплайн грузил сам — при session=None история
    была бы пустой, а резюме — прочитанным из Redis (пусто в тесте)."""
    from service.application.processor import AgentProcessor

    processor = AgentProcessor()
    cap = _CapturingGeneral()
    processor.orchestrator._agents["general"] = cap

    async for _ in processor.process_message_stream(
        "текущий вопрос",
        "t-0b3",
        user_id=None,  # без user_id память/knowledge не дёргаются
        session=None,  # сессии нет: история может прийти ТОЛЬКО из history_messages
        input_type="image",  # форсит general без LLM-роутинга
        history_messages=[{"role": "user", "content": "ПРОШЛЫЙ-ВОПРОС-XYZ"}],
        compact_summary="РЕЗЮМЕ-ИЗ-ЗАПРОСА",
    ):
        pass

    ctx = cap.last_context
    assert ctx is not None, "general не получил контекст"
    # Резюме отрендерено секцией в system_context.
    assert "РЕЗЮМЕ-ИЗ-ЗАПРОСА" in (ctx.system_context or "")
    # История дошла репликами (session=None → взяться могла ТОЛЬКО из history_messages).
    hist_blob = " ".join(str(m.get("content", "")) for m in (ctx.history_messages or []))
    assert "ПРОШЛЫЙ-ВОПРОС-XYZ" in hist_blob
