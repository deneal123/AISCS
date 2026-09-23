"""Память отбирается ПО ВОПРОСУ, а не по свежести.

🔴 Замер по живой базе: из 34 фактов в промпт уезжали 5 самых свежих. Вопрос про Python
получал «знак зодиака: близнец» и «количество бывших: четыре», а «язык: Python», «роль:
senior-инженер» и «задача: рефакторинг» не доезжали НИКОГДА. Память была наполнена, но
отвечала не на тот вопрос — и заметить это можно было только сравнив запрос с тем, что
реально ушло в промпт.
"""

from __future__ import annotations

import pytest

from service.services.analytics.application.memory_service import MemoryService

FACTS = [
    # Порядок как из репозитория: свежие первыми. Релевантные — НАМЕРЕННО в хвосте,
    # иначе тест прошёл бы и на старом отборе по свежести.
    {"fact_type": "identity", "fact_key": "знак зодиака", "fact_value": "Пользователь близнец."},
    {"fact_type": "context", "fact_key": "отношения", "fact_value": "Страдает по бывшим."},
    {"fact_type": "identity", "fact_key": "город", "fact_value": "Живёт в Москве."},
    {"fact_type": "preference", "fact_key": "язык", "fact_value": "Использует Python."},
    {"fact_type": "context", "fact_key": "задача", "fact_value": "Занимается рефакторингом."},
    {"fact_type": "identity", "fact_key": "роль", "fact_value": "Senior-инженер и ревьюер."},
]


def _top(query: str, k: int = 3) -> list[str]:
    return [f["fact_key"] for f in MemoryService._rank_by_relevance(FACTS, query, k)]


def test_relevant_fact_wins_over_fresh_one():
    """🔴 ГЛАВНОЕ: вопрос про Python поднимает факт про Python, а не свежий про зодиак."""
    assert _top("Как оптимизировать код на Python?")[0] == "язык"


def test_morphology_does_not_break_the_match():
    """«рефакторингА» в вопросе и «рефакторингОМ» в факте — разные токены.

    Без склейки основ лексический отбор на русском почти не работает: факт про текущую
    задачу не находился именно из-за падежа.
    """
    assert _top("Составь план рефакторинга сервиса")[0] == "задача"


def test_identity_bonus_does_not_outrank_a_weak_topic_hit():
    """⚠️ Надбавка типу разнимает РАВНЫХ, а не вытесняет попадание в тему.

    ⚠️ Факт намеренно ДЛИННЫЙ: при коротком совпадение даёт долю 0.25-0.33, и разница
    между надбавкой 0.05 и 0.15 не видна — тест проходил бы при любой. Здесь совпадает
    одно слово из восьми (0.125), то есть слабее прежней надбавки: ровно тот случай,
    когда «знак зодиака» вытеснял ответ по существу.
    """
    facts = [
        {"fact_type": "identity", "fact_key": "знак зодиака", "fact_value": "Близнец."},
        {
            "fact_type": "context",
            "fact_key": "проект",
            "fact_value": (
                "Пользователь ведёт большой долгий проект миграции внутренних сервисов "
                "компании на новую версию платформы Kubernetes постепенно"
            ),
        },
    ]

    top = [f["fact_key"] for f in MemoryService._rank_by_relevance(facts, "Kubernetes", 1)]

    assert top == ["проект"], "надбавка типу перебила слабое, но настоящее попадание в тему"


def test_topic_hit_wins_in_a_real_conversation():
    top = _top("Почему я страдаю по бывшим?")

    assert top[0] == "отношения"


def test_identity_still_fills_the_rest():
    """Когда по теме ничего нет, базовые факты о человеке лучше случайных."""
    top = _top("Расскажи что-нибудь", k=3)

    assert all(
        next(f for f in FACTS if f["fact_key"] == key)["fact_type"] == "identity" for key in top
    )


def test_empty_query_falls_back_to_recency():
    """Запроса нет — прежний порядок (свежие первыми), без выдумывания релевантности."""
    assert _top("", k=2) == ["знак зодиака", "отношения"]


@pytest.mark.asyncio
async def test_query_reaches_the_selection():
    """🔴 ТОЧКА ВЫЗОВА: запрос обязан доехать до отбора, иначе он бессмыслен."""
    import inspect

    from service.services.chat.infrastructure import agent_context

    src = inspect.getsource(agent_context.load_memory_parts)
    assert "get_memory_context(str(user_id), query=" in src, (
        "запрос не передан — отбор снова вырождается в «самые свежие»"
    )


@pytest.mark.asyncio
async def test_selection_sees_more_than_the_freshest_dozen():
    """Тянем ШИРОКО, отбираем узко: иначе релевантность выбирает из тех же свежих."""

    class _Repo:
        def __init__(self):
            self.limit = 0

        async def list_facts(self, *, user_id, limit):
            self.limit = limit
            return FACTS

    repo = _Repo()
    await MemoryService(integration=object(), facts_repo=repo).get_memory_context(
        "u1", query="Python"
    )

    assert repo.limit >= 50, "выборка узкая — нужный факт не попадёт даже в кандидаты"
