"""Ход исследования — СОБЫТИЯ, а не текст в теле отчёта. Один стиль на оба пути.

🔴 ЖИВАЯ ЖАЛОБА. Deep research, ушедший на нативный путь (LDR был недоступен), выдал в
сам ответ вот это:

    **Этап 2/4:** Выполняю веб-поиск...
    🔍 Поиск 1/4: «...»
    📄 Читаю: Центр карьеры МГИМО...
    **Проанализировано:** 4 источников

То есть ход работы оседал в сохранённом сообщении навсегда, вперемешку с отчётом, и
оформлен был эмодзи — вопреки дизайну платформы. При этом путь через LDR ровно те же
вехи давно отдавал статус-событиями с процентом, и панель рисовала прогресс-бар. Больше
того, эмодзи из меток LDR тут же и ВЫРЕЗАЮТСЯ (`research_labels.clean_label`) — правило
стиля в проекте существовало, а нативный путь его нарушал, сам же эмодзи и вставляя.

Отсюда два инварианта:
* вехи хода не попадают в текст отчёта (они отдельный тип `ResearchProgress`);
* контракт события один и тот же у обоих путей — `kind=research_progress` + процент,
  иначе фронт нарисует прогресс-бар только одному из них.
"""

from __future__ import annotations

import pytest

from service.domain.run_context import RunExecutionContext
from service.domain.tools import deep_research as dr


class _FakeResponse:
    def __init__(self, content: str):
        self.choices = [type("C", (), {"message": type("M", (), {"content": content})()})()]
        self.usage = None


@pytest.fixture
def research_stream(monkeypatch):
    """Полный прогон инструмента на подставных поиске и чтении страниц."""

    async def _completion(messages, model, temperature, max_tokens):
        return _FakeResponse('["первый запрос", "второй запрос"]')

    async def _search(query: str, num_results: int = 5):
        return [{"title": "Заголовок", "url": "https://example.com/a", "snippet": "текст"}]

    async def _parse(url: str, max_chars: int = 2200):
        return {"title": "Заголовок", "content": "содержимое страницы " * 20}

    monkeypatch.setattr(dr, "create_chat_completion", _completion)
    monkeypatch.setattr(dr, "web_search", _search)
    monkeypatch.setattr(dr, "parse_url", _parse)


@pytest.mark.asyncio
async def test_report_body_carries_no_progress_chatter(research_stream):
    """⚠️ ГЛАВНОЕ. В тексте отчёта нет ни этапов, ни «читаю», ни эмодзи-иконок."""
    chunks = [c async for c in dr.deep_research("тема", "fake-model")]
    text = "".join(c for c in chunks if isinstance(c, str))

    for junk in ("Этап", "Поиск ", "Читаю", "Проанализировано", "Всего найдено"):
        assert junk not in text, f"ход работы снова в теле отчёта ({junk!r}): {text[:200]!r}"
    assert "🔍" not in text and "📄" not in text, (
        f"декоративные эмодзи вернулись в ответ: {text[:200]!r}"
    )


@pytest.mark.asyncio
async def test_milestones_are_reported_with_progress(research_stream):
    """Вехи есть, у них растущий процент — иначе прогресс-бар нечем заполнять."""
    chunks = [c async for c in dr.deep_research("тема", "fake-model")]
    milestones = [c for c in chunks if isinstance(c, dr.ResearchProgress)]

    assert len(milestones) >= 4, f"вех слишком мало для прогресс-бара: {milestones}"
    percents = [m.progress for m in milestones]
    assert percents == sorted(percents), f"процент не монотонен: {percents}"
    assert all(0 <= p <= 100 for p in percents), f"процент вне диапазона: {percents}"


@pytest.mark.asyncio
async def test_milestone_labels_are_clean(research_stream):
    """⚠️ Метки без эмодзи — как и у LDR, где они вырезаются на входе.

    Оформление берёт на себя трейс-панель; эмодзи в тексте метки — это ровно то, на что
    пришла жалоба («не соответствует нашему стилю»).
    """
    chunks = [c async for c in dr.deep_research("тема", "fake-model")]

    from service.domain.subagents.research_labels import clean_label

    for m in (c for c in chunks if isinstance(c, dr.ResearchProgress)):
        assert m.label == clean_label(m.label), f"в метке есть эмодзи: {m.label!r}"
        assert m.label and not m.label.startswith("**"), f"метка с разметкой: {m.label!r}"


@pytest.mark.asyncio
async def test_native_path_emits_the_same_event_contract_as_ldr(monkeypatch):
    """⚠️ Контракт события ОДИН на оба пути: `kind=research_progress` + процент.

    Разъедься он — прогресс-бар остался бы только у LDR, а фоллбек снова выглядел бы
    иначе. Проверяем на сабагенте: именно он превращает вехи инструмента в события.
    """
    from service.domain.subagents.deep_research import DeepResearchAgent
    from service.events import EventType

    async def _fake_tool(topic, model):
        yield dr.ResearchProgress(42, "Ищу источники", ["запрос"])
        yield "тело отчёта"

    monkeypatch.setattr(dr, "deep_research", _fake_tool)

    async def _models():
        return ["fake-model"]

    import service.domain.client as client_mod
    import service.domain.subagents.context_query as cq

    monkeypatch.setattr(client_mod, "list_qualified_models", _models)

    async def _topic(user_input, context, model, *, execution=None):
        return user_input

    monkeypatch.setattr(cq, "build_standalone_query", _topic)

    from datetime import UTC, datetime

    from service.schemas.agents import UserContext

    agent = DeepResearchAgent({"model": "fake-model"})
    events = [
        e
        async for e in agent._run_native(
            "тема",
            UserContext(user_id="", request_time=datetime.now(UTC)),
            RunExecutionContext(),
            {"emitted": 0},
        )
    ]

    progress_events = [
        e
        for e in events
        if e.type == EventType.STATUS_UPDATE
        and (e.metadata or {}).get("kind") == "research_progress"
    ]
    assert progress_events, (
        "нативный путь не шлёт research_progress — прогресс-бар будет только у LDR"
    )
    assert progress_events[0].metadata.get("progress") == 42, (
        f"процент не доехал до события: {progress_events[0].metadata}"
    )
    assert progress_events[0].data == "Ищу источники"
