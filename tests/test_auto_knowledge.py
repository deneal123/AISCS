"""База знаний для моделей БЕЗ function-calling.

Инструмент `search_knowledge_graph` модель зовёт сама — но только если провайдер
поддерживает tools. Поддерживают 263 модели из 462: за бортом остаются GigaChat и вообще
все российские провайдеры. Отрезать их из пикера — значит выбросить мультипровайдер, ради
которого всё и делалось.

Поэтому деградация, а не запрет: умеет tools → зовёт сама; не умеет → ищем сами и кладём
найденное в контекст отдельной секцией.
"""

import pytest

from service.application.processor import AgentProcessor
from service.domain.pipeline import context_assembler, context_budget


@pytest.fixture
def stub_knowledge(monkeypatch):
    """Подменить оба источника базы знаний на предсказуемые."""
    from service.domain.tools import graphify_client, vector_store

    async def _passages(**_kw):
        return [{"filename": "dogovor.md", "text": "Срок оплаты: 45 дней.", "score": 0.9}]

    class _Graph:
        async def query(self, *_a, **_kw):
            return "NODE Договор --references--> Покупатель"

    monkeypatch.setattr(vector_store, "search", _passages)
    monkeypatch.setattr(graphify_client, "GraphifyClient", _Graph)


def _patch_tool_support(monkeypatch, supported: bool):
    # Патчим ИМЕННО service.shared.model_catalog — каталог переехал туда (общий с сайдкаром),
    # и процессор импортит tool-support оттуда. Патч старого chat-шима сюда бы не долетел:
    # шим лишь ре-экспортит, а движок берёт функцию из первоисточника.
    import service.shared.model_catalog as catalog

    async def _supports(_model):
        return supported

    monkeypatch.setattr(catalog, "model_supports_tools", _supports)


@pytest.mark.asyncio
async def test_model_without_tools_gets_knowledge_in_context(monkeypatch, stub_knowledge):
    """GigaChat не умеет tools → база знаний обязана доехать сама, иначе граф на нём
    бесполезен."""
    _patch_tool_support(monkeypatch, supported=False)

    processor = AgentProcessor({"model": "GigaChat-2-Max"})
    knowledge = await processor._auto_knowledge("u1", "какой срок оплаты")

    assert "Срок оплаты: 45 дней." in knowledge
    assert "--references-->" in knowledge


@pytest.mark.asyncio
async def test_model_with_tools_gets_nothing_extra(monkeypatch, stub_knowledge):
    """Модель с tools позовёт инструмент сама — подмешивать то же самое значит платить
    за контекст дважды."""
    _patch_tool_support(monkeypatch, supported=True)

    processor = AgentProcessor({"model": "openai/gpt-4o-mini"})
    assert await processor._auto_knowledge("u1", "какой срок оплаты") == ""


@pytest.mark.asyncio
async def test_no_user_no_lookup(monkeypatch, stub_knowledge):
    _patch_tool_support(monkeypatch, supported=False)
    processor = AgentProcessor({"model": "GigaChat-2-Max"})
    assert await processor._auto_knowledge(None, "вопрос") == ""
    assert await processor._auto_knowledge("u1", "  ") == ""


@pytest.mark.asyncio
async def test_lookup_failure_is_fail_open(monkeypatch):
    """Сайдкар/Qdrant легли — ход диалога не должен падать."""
    from service.domain.tools import graphify_client, vector_store

    _patch_tool_support(monkeypatch, supported=False)

    async def _boom(**_kw):
        raise RuntimeError("qdrant лёг")

    class _Graph:
        async def query(self, *_a, **_kw):
            raise RuntimeError("сайдкар лёг")

    monkeypatch.setattr(vector_store, "search", _boom)
    monkeypatch.setattr(graphify_client, "GraphifyClient", _Graph)

    processor = AgentProcessor({"model": "GigaChat-2-Max"})
    assert await processor._auto_knowledge("u1", "вопрос") == ""


# --------------------------------------------------------------------------- #
# Секция контекста                                                             #
# --------------------------------------------------------------------------- #
def test_knowledge_is_a_budgeted_section():
    """Без места в приоритете секция не получила бы доли бюджета и молча пропала."""
    assert "knowledge" in context_budget.SECTION_PRIORITY
    assert "knowledge" in context_assembler.SECTION_TITLES
    # Сжимаемая: найденное может быть объёмным, а резать по хвосту — терять конец.
    assert "knowledge" in context_assembler.COMPRESSIBLE


@pytest.mark.asyncio
async def test_knowledge_reaches_the_prompt():
    from service.settings import config

    assembled = await context_assembler.assemble_context(
        model_id="GigaChat-2-Max",
        config=config,
        user_input="какой срок оплаты",
        knowledge="[dogovor.md]\nСрок оплаты: 45 дней.",
    )

    assert "## Из вашей базы знаний" in assembled.system_context
    assert "Срок оплаты: 45 дней." in assembled.system_context
    assert assembled.by_section.get("knowledge", 0) > 0
