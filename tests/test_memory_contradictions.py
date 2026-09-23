"""Противоречащие факты не попадают в промпт одновременно.

🔴 Замер по живой базе: у одного пользователя ПЯТЬ разных значений ключа «имя»
(«Данил», «Мария Иванова», «Елизавета Смирнова», «Лиза», …) и ЧЕТЫРЕ у «роль» — и все
подмешивались в контекст сразу. Модель получала взаимоисключающие утверждения о том,
как зовут собеседника, и выбирала между ними как придётся.

Существующие фильтры этого не ловили и не могли: дедуп на запись сравнивает ХЭШ текста
(у разных имён он разный), а `_dedupe_facts` — Jaccard значимых слов; у «Пользователь
зовут Данил» и «Пользователь зовут Мария Иванова» он равен 0.4 при пороге 0.6. Оба
фильтра ищут ПОВТОР, а здесь ПРОТИВОРЕЧИЕ — это разные задачи.
"""

from __future__ import annotations

import pytest

from service.services.analytics.application.memory_service import MemoryService


def _fact(key: str, value: str, *, when: str) -> dict:
    return {
        "id": value,
        "fact_type": "identity",
        "fact_key": key,
        "fact_value": value,
        "updated_at": when,
    }


# Порядок как из репозитория: `ORDER BY updated_at DESC` — свежие первыми.
NEWEST_FIRST = [
    _fact("имя", "Пользователь зовут Мария Иванова.", when="2026-07-26"),
    _fact("имя", "Пользователь зовут Данил.", when="2026-07-24"),
    _fact("город", "Мария Иванова живёт в Москве.", when="2026-07-23"),
]


def test_only_the_newest_value_per_key_survives():
    kept = MemoryService._newest_per_key(NEWEST_FIRST)

    assert [f["fact_value"] for f in kept] == [
        "Пользователь зовут Мария Иванова.",
        "Мария Иванова живёт в Москве.",
    ]


def test_old_value_is_dropped_not_the_new_one():
    """🔴 Направление важно: победить обязан СВЕЖИЙ, иначе память замерзает навсегда."""
    kept = MemoryService._newest_per_key(NEWEST_FIRST)

    assert all("Данил" not in f["fact_value"] for f in kept)


def test_empty_keys_are_not_collapsed_together():
    """У безымянных фактов «одинаковый ключ» ничего не значит — склеились бы по совпадению."""
    facts = [_fact("", "Факт один.", when="2026-07-26"), _fact("", "Факт два.", when="2026-07-25")]

    assert len(MemoryService._newest_per_key(facts)) == 2


def test_keys_are_compared_case_insensitively():
    facts = [
        _fact("Роль", "аналитик", when="2026-07-26"),
        _fact("роль", "редактор", when="2026-07-25"),
    ]

    assert [f["fact_value"] for f in MemoryService._newest_per_key(facts)] == ["аналитик"]


@pytest.mark.asyncio
async def test_prompt_context_carries_one_value_per_key(monkeypatch):
    """ТОЧКА ПРИМЕНЕНИЯ: правило обязано действовать там, где собирается промпт."""

    class _Repo:
        async def list_facts(self, *, user_id, limit):
            return NEWEST_FIRST

    service = MemoryService(integration=object(), facts_repo=_Repo())
    context = await service.get_memory_context("u1")

    assert "Мария Иванова" in context
    assert "Данил" not in context, "в промпт уехали два разных имени сразу"


@pytest.mark.asyncio
async def test_panel_shows_everything_but_marks_the_stale(monkeypatch):
    """🔴 Панель ПОКАЗЫВАЕТ всё и ПОМЕЧАЕТ вытесненное.

    Прятать нельзя: расхождение видно только когда оба значения рядом, а удалять
    данные по нашей эвристике — не наше решение. Скрытая запись, которая при этом
    как-то влияет на ответы, необъяснима для пользователя.
    """

    class _Repo:
        async def list_facts(self, *, user_id, limit):
            return NEWEST_FIRST

    service = MemoryService(integration=object(), facts_repo=_Repo())
    facts = await service.list_facts("u1")

    assert len(facts) == 3, "панель потеряла факты — их удаляет пользователь, а не мы"
    stale = [f for f in facts if f["superseded"]]
    assert [f["fact_value"] for f in stale] == ["Пользователь зовут Данил."]
