"""Бюджет контекста, выведенный из реального окна выбранной модели.

Единственный источник истины о том, сколько токенов мы имеем право занять. Раньше
бюджет был константой (6000) и никак не зависел от модели: на 128k-окне мы
использовали ~5% доступного объёма, а на мелкой модели рисковали его переполнить,
потому что место под ответ вообще не резервировалось.

Формула::

    usable = window * safety_margin - output_reserve - prompt_overhead

где ``output_reserve`` — место, которое модель займёт СВОИМ ответом (иначе
``input + output`` вылезает за окно), а ``safety_margin`` — зазор на неточность
эвристической оценки токенов (``token_budget.estimate_tokens``, ~3.5 симв/токен —
для кириллицы это скорее занижение).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from service.domain import persona
from service.shared.token_budget import allocate_budget

logger = logging.getLogger(__name__)

# Секции контекста в порядке убывания приоритета: кого сохраняем до последнего, когда
# места не хватает. Вложения стоят ВЫШЕ истории и памяти — это задача, которую
# пользователь ставит прямо сейчас (раньше они склеивались последними и обрезались
# первыми). Реплика пользователя не входит в список: её не режем никогда.
SECTION_PRIORITY: tuple[str, ...] = (
    "facts",  # мелкие факты о пользователе из Postgres
    "files",  # вложения текущей задачи: документ/голос/картинка
    "knowledge",  # авто-подмешанная база знаний (для моделей без function-calling)
    "history",  # свежие реплики диалога
    "plan",  # план решения
    "memory",  # семантический recall из долговременной памяти MemOS
    "summary",  # резюме уже сжатой части диалога
)

# Факты о пользователе мелкие по своей природе; без потолка одна разросшаяся
# memory-таблица могла бы съесть долю, рассчитанную на документ.
FACTS_HARD_CAP_TOKENS = 600


@dataclass(frozen=True)
class ContextBudget:
    """Сколько токенов доступно под контекст и как они поделены по секциям."""

    window: int
    usable: int
    output_reserve: int
    prompt_overhead: int
    sections: dict[str, int] = field(default_factory=dict)
    # Окно взято из каталога/статической карты, а не подставлено дефолтом. False
    # означает «бюджет посчитан вслепую» — см. resolve_window.
    window_known: bool = True

    def for_section(self, name: str) -> int:
        return int(self.sections.get(name, 0))


def _flag(config, name: str, default):
    """Значение настройки с учётом runtime-оверлея админки (fail-open к config)."""
    try:
        from service.shared.agent_settings import runtime_settings

        return runtime_settings.get_agents(name, getattr(config.agents, name, default))
    except Exception:
        return getattr(config.agents, name, default)


async def resolve_window(model_id: str | None, config) -> tuple[int, bool]:
    """Реальное окно модели и признак того, что оно ИЗВЕСТНО, а не подставлено.

    Каталог OpenRouter — ленивый TTL-кэш, и в свежем воркере он пуст: без явного
    прогрева ВСЕ модели свалились бы в дефолт (128k-модель считалась бы 32k-й).
    Поэтому дёргаем ``get_openrouter_catalog()`` — она сама вернёт кэш, если он тёплый.
    Импорт ленивый: chat.infrastructure тянет httpx и не должен грузиться при импорте
    пайплайна агентов.

    ⚠️ ВТОРОЙ ЭЛЕМЕНТ — НЕ УКРАШЕНИЕ. Когда каталог недоступен, модель с окном 1M
    бюджетируется как 32k. Видимых ошибок нет: компрессор просто запускается там, где
    он не нужен (до 39 провайдерских вызовов на запрос), а кольцо на фронте показывает
    занятость от чужого знаменателя. Отличить «окно правда 32k» от «мы не знаем» по
    одному числу невозможно, поэтому признак едет рядом и попадает в трейс.
    """
    default_window = int(_flag(config, "context_default_window", 32768))
    if not model_id:
        return default_window, False
    try:
        from service.shared.model_catalog import (
            get_openrouter_catalog,
            resolve_context_window_ex,
        )

        catalog = await get_openrouter_catalog()
        window, known = resolve_context_window_ex(str(model_id), catalog)
        if not known:
            logger.warning(
                "Окно модели %s неизвестно (каталог пуст или без записи) — бюджет "
                "считаем по дефолту %d токенов",
                model_id,
                default_window,
            )
            return default_window, False
        return int(window) or default_window, True
    except Exception:
        logger.warning(
            "model context window unavailable",
            extra={"failure_code": "unavailable"},
        )
        return default_window, False


async def compute_budget(
    *,
    model_id: str | None,
    config,
    present: set[str] | None = None,
) -> ContextBudget:
    """Посчитать бюджет контекста для модели и поделить его по ПРИСУТСТВУЮЩИМ секциям.

    ``present`` — какие секции реально есть в этом запросе. Отсутствующие доли не
    получают, а их вес перераспределяется на остальные (нет вложения → его 0.35
    уходят истории и памяти). Так протокол не деградирует между моделями: на большом
    окне каждая секция просто получает больше места.

    Инвариант, который держим по построению::

        usable + output_reserve + prompt_overhead <= window * safety_margin <= window

    Поэтому резерв под ответ и оверхед промпта ограничены ДОЛЕЙ от окна, а не берутся
    константами: на модели с окном 4k константный резерв в 4096 токенов сам по себе
    съел бы всё окно и загнал usable в минус.
    """
    window, window_known = await resolve_window(model_id, config)
    margin = float(_flag(config, "context_safety_margin", 0.85))

    # Всё, что разрешаем себе занять от окна (с зазором на неточность оценки токенов).
    allowance = max(1, int(window * margin))

    # Оверхед системного промпта — не больше четверти доступного.
    # ⚠️ АКТИВНАЯ ЛИЧНОСТЬ РАСШИРЯЕТ РЕЗЕРВ. Резерв (дефолт 1000) считался под ОДИН
    # `GENERAL_PROMPT` (~700 токенов кириллицы). Секция «Специализация» приписывается к
    # тому же system-промпту, и без поправки она молча съедала бы место, отведённое
    # ВЛОЖЕНИЯМ: бюджет считает, что промпт короче, чем он есть. Потолок «не больше
    # четверти» остаётся — на маленьких окнах он и защищает от ухода usable в минус.
    prompt_overhead = int(_flag(config, "context_prompt_overhead", 1000))
    if not persona.current().is_empty:
        prompt_overhead += int(_flag(config, "persona_max_tokens", 800))
    overhead = min(prompt_overhead, allowance // 4)

    # Место под ответ модели — не больше половины того, что осталось после оверхеда.
    reserve_cfg = int(_flag(config, "context_output_reserve", 0)) or int(
        _flag(config, "chat_max_tokens", 4096)
    )
    reserve = min(reserve_cfg, (allowance - overhead) // 2)

    usable = allowance - overhead - reserve

    # Жёсткий потолок сверху (контроль стоимости): не раздуваем промпт даже на
    # моделях с окном в 1M, если админ выставил лимит.
    hard_cap = int(_flag(config, "context_token_budget", 0))
    if hard_cap > 0:
        usable = min(usable, hard_cap)

    names = set(present) if present else set(SECTION_PRIORITY)
    weights = {
        name: float(_flag(config, f"context_budget_{name}", 0.0))
        for name in SECTION_PRIORITY
        if name in names
    }
    sections = allocate_budget(usable, weights)

    if "facts" in sections:
        sections["facts"] = min(sections["facts"], FACTS_HARD_CAP_TOKENS)

    return ContextBudget(
        window=window,
        usable=usable,
        output_reserve=reserve,
        prompt_overhead=overhead,
        sections=sections,
        window_known=window_known,
    )
