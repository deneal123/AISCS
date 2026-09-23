import importlib

import pytest


class _FakeMessage:
    def __init__(self, content: str):
        self.content = content


class _FakeChoice:
    def __init__(self, content: str):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content: str):
        self.choices = [_FakeChoice(content)]


@pytest.mark.asyncio
async def test_deep_research_fast_fallback_when_no_sources(monkeypatch):
    dr = importlib.import_module("service.domain.tools.deep_research")

    async def fake_create_chat_completion(messages, model, temperature, max_tokens):
        # Только шаг планирования
        return _FakeResponse('["тестовый запрос"]')

    async def fake_web_search(query: str, num_results: int = 5):
        return []

    monkeypatch.setattr(dr, "create_chat_completion", fake_create_chat_completion)
    monkeypatch.setattr(dr, "web_search", fake_web_search)

    chunks = [chunk async for chunk in dr.deep_research("тема", "fake-model")]
    # ⚠️ Вехи хода — ОТДЕЛЬНЫЙ род значений (`ResearchProgress`), в тело отчёта они не
    # попадают: раньше «Этап 2/4», «Поиск 1/4», «Читаю…» печатались текстом и оседали
    # в сохранённом сообщении. Здесь нас интересует именно содержимое ответа.
    text = "".join(c for c in chunks if isinstance(c, str))
    assert any(isinstance(c, dr.ResearchProgress) for c in chunks), (
        "исследование не сообщило ни одной вехи — прогресс-бар будет пустым"
    )
    assert "Этап" not in text and "Читаю" not in text, (
        f"ход работы снова печатается в тело отчёта: {text[:200]!r}"
    )

    # «Ничего не нашли» — тоже веха хода, а не строка отчёта.
    milestones = [c.label for c in chunks if isinstance(c, dr.ResearchProgress)]
    assert any("Найдено источников: 0" in m for m in milestones), (
        f"пустая выдача не отражена в ходе исследования: {milestones}"
    )
    assert "Внешние источники по теме сейчас недоступны" in text
    assert "### Источники" in text
