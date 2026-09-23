"""Словарь СЛОТОВ личности — точек, куда впрыскивается специализация.

⚠️ СЛОВАРЬ ЗАКРЫТЫЙ, И ЭТО ГЛАВНОЕ РЕШЕНИЕ ЭТОГО МОДУЛЯ. Слоты объявлены здесь
константой, а не берутся из JSON свободными ключами: опечатка в имени слота даёт
МОЛЧА пустой впрыск — личность настроена, а в промпт ничего не уходит, и заметить это
можно только по качеству ответов. Ровно с этим классом отказов в проекте уже борются
`test_settings_are_alive` и `_check_knobs_actually_apply`. Закрытый словарь позволяет
проверить и конфиг, и код стражем.

⚠️ `vision` И `analyst.image` — РАЗНЫЕ СЛОТЫ, а не дубль. Это два РАЗНЫХ слоя:
`vision` инструктирует саму VLM (`domain/media.py:describe_image`), которая смотрит на
пиксели, а `analyst.image` — аналитика, который работает уже по ГОТОВОМУ ТЕКСТУ описания
и прямо инструктирован не домысливать. «Посчитай людей на фото» обязано попасть в
`vision`: если VLM их не посчитала, аналитику считать уже нечего.
"""

from __future__ import annotations

from typing import Final

# --- Ядро: кто ты и как говоришь ------------------------------------------------
CORE: Final = "core"
STYLE: Final = "style"
AVOID: Final = "avoid"

# --- Модальности: угол зрения на материале ---------------------------------------
VISION: Final = "vision"  # сама VLM (пиксели)
ANALYST_IMAGE: Final = "analyst.image"  # аналитик по тексту описания
ANALYST_AUDIO: Final = "analyst.audio"
ANALYST_DOCUMENT: Final = "analyst.document"
ANALYST_DATA: Final = "analyst.data"
ANALYST_CODE: Final = "analyst.code"

# --- Внешние операции -------------------------------------------------------------
SEARCH_QUERY: Final = "search.query"
SEARCH_SOURCES: Final = "search.sources"
SEARCH_SYNTHESIS: Final = "search.synthesis"
RESEARCH_PLAN: Final = "research.plan"
RESEARCH_SYNTHESIS: Final = "research.synthesis"

# ⚠️ СЛОТА `graph.query` ЗДЕСЬ НЕТ, И ЭТО РЕШЕНИЕ, А НЕ ПРОПУСК. Он был в замысле, но обе
# точки обращения к графу его не принимают:
#   * `search_knowledge_graph` — вопрос формулирует САМА МОДЕЛЬ, а у неё личность уже есть
#     в системном промпте; отдельный слот дублировал бы ядро;
#   * `_auto_knowledge` — запрос уходит в СЕМАНТИЧЕСКИЙ поиск как есть, и дописывание к
#     нему инструкции («ищи узлы с метриками») загрязняет вектор запроса, то есть ухудшает
#     выдачу. Честная переформулировка стоила бы отдельного LLM-вызова на каждый запрос.
# Пустой слот в словаре был бы «редактируемым no-op»: админ его заполнит, а эффекта нет.

# --- Работа с контекстом ----------------------------------------------------------
COMPRESSION: Final = "compression"
DECOMPOSITION: Final = "decomposition"

SLOTS: Final[frozenset[str]] = frozenset(
    {
        CORE,
        STYLE,
        AVOID,
        VISION,
        ANALYST_IMAGE,
        ANALYST_AUDIO,
        ANALYST_DOCUMENT,
        ANALYST_DATA,
        ANALYST_CODE,
        SEARCH_QUERY,
        SEARCH_SOURCES,
        SEARCH_SYNTHESIS,
        RESEARCH_PLAN,
        RESEARCH_SYNTHESIS,
        COMPRESSION,
        DECOMPOSITION,
    }
)

# ⚠️ ИСКЛЮЧАЮЩИЕ СЛОТЫ: вклад даёт ТОЛЬКО ведущая личность, остальные молчат.
# Сложить «сухо, вывод числом» и «образно, за метафорой прикладное прочтение» — значит
# получить кашу, и это самый заметный для пользователя способ испортить микс. Тон и форма
# вывода взаимоисключающи по природе, поэтому правило живёт КОНСТАНТОЙ СИСТЕМЫ, а не
# полем личности: иначе прототипировщик обязан был бы согласовывать N правил между собой.
EXCLUSIVE_SLOTS: Final[frozenset[str]] = frozenset({STYLE, SEARCH_SYNTHESIS, RESEARCH_SYNTHESIS})

# Слоты-ограничения объединяются союзом: накопление запретов безопасно (односторонне
# в сторону осторожности), в отличие от накопления стилей.
UNION_SLOTS: Final[frozenset[str]] = frozenset({AVOID})


def unknown_slots(names: object) -> list[str]:
    """Имена, которых нет в словаре. Пусто — всё в порядке.

    Возвращает список, а не bool: сообщение об ошибке обязано называть опечатку, иначе
    автор личности будет искать её глазами по всему конфигу.
    """
    if not isinstance(names, dict):
        return []
    return sorted(str(name) for name in names if str(name) not in SLOTS)
