"""Сборка контекста: единый структурированный блок под общий бюджет окна модели.

Раньше контекст собирался в ДВУХ независимых местах, каждое со своей отсечкой:
``build_history_messages`` (история) и ``build_system_context`` (память+план+файлы,
склейка в один блоб и обрезка с хвоста). Итоговый размер не считал никто, поэтому
суммарный контекст мог вдвое превысить заявленный лимит, а вложения — стоявшие в
склейке последними — обрезались первыми, хотя это ровно та задача, которую
пользователь ставит прямо сейчас.

Здесь всё сводится в одну точку с ОДНИМ потолком:

1. **Измерить** — сколько токенов просит каждый реально присутствующий источник.
2. **Распределить** — доли из :mod:`context_budget` (веса перенормируются по
   присутствующим секциям).
3. **Вернуть излишки** — секция, которой нужно меньше выделенного, отдаёт остаток в
   общий котёл; котёл раздаётся тем, кто не влез, по приоритету. Именно это не даёт
   протоколу деградировать: короткая история → документ получает больше места.
4. **Уместить** — то, что и после добавки не влезло, сжимается (если умеет) или
   обрезается.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from service.domain.pipeline.context_budget import (
    SECTION_PRIORITY,
    ContextBudget,
    compute_budget,
)
from service.shared import step_timing
from service.shared.token_budget import (
    estimate_tokens,
    trim_messages_to_tokens,
    trim_text_to_tokens,
)

logger = logging.getLogger(__name__)

# Заголовки секций в системном блоке. Модель должна понимать, ОТКУДА кусок контекста,
# иначе она путает факты о пользователе с содержимым документа.
SECTION_TITLES: dict[str, str] = {
    "facts": "## Факты о пользователе",
    "memory": "## Из долговременной памяти (похожие задачи)",
    "files": "## Вложения текущей задачи",
    "knowledge": "## Из вашей базы знаний (документы и репозитории)",
    "plan": "## План решения (придерживайся его)",
    "summary": "## Резюме предыдущего диалога",
}

# Какие секции имеет смысл сжимать LLM, а не резать по хвосту. Факты и резюме и так
# мелкие; план — структурная вещь, обрезка хвоста ему менее вредна, чем пересказ.
COMPRESSIBLE: frozenset[str] = frozenset({"files", "memory", "knowledge"})

# Сжиматель: (текст, целевой бюджет, вид секции) -> сжатый текст. Подставляется
# снаружи (см. context_compressor). По умолчанию сжатия нет — только обрезка.
Compressor = Callable[[str, int, str], Awaitable[str]]

# Запас на разделители между секциями (переводы строк, пометка о сжатии).
_SEPARATOR_TOKENS = 12


@dataclass
class ContextSection:
    """Один источник контекста со своим бюджетом и судьбой при нехватке места."""

    kind: str
    raw: str
    raw_tokens: int = 0
    budget: int = 0
    content: str = ""
    tokens: int = 0
    compressed: bool = False
    # Почему секция приехала хуже, чем могла: compress_failed / compress_empty /
    # compress_useless. None — всё штатно.
    degraded: str | None = None

    @property
    def title(self) -> str:
        return SECTION_TITLES.get(self.kind, f"## {self.kind}")

    @property
    def compressible(self) -> bool:
        return self.kind in COMPRESSIBLE


@dataclass
class AssembledContext:
    """Результат сборки + отчёт о том, чем занят контекст (для кольца и трейса)."""

    system_context: str
    history_messages: list[dict]
    budget: ContextBudget
    used: int = 0
    by_section: dict[str, int] = field(default_factory=dict)
    compressed: list[str] = field(default_factory=list)
    # Что поехало не так при сборке: «files:compress_failed» и т.п. Пустой список —
    # нормальный день.
    degraded: list[str] = field(default_factory=list)

    @property
    def pct(self) -> float:
        """Заполненность бюджета — ровно то, что показывает кольцо на фронте."""
        return (self.used / self.budget.usable * 100.0) if self.budget.usable else 0.0

    def as_meta(self, *, threshold_pct: int = 85) -> dict[str, Any]:
        """Компактный отчёт для metadata ответа (кольцо считает used/usable).

        ``threshold_pct`` едет вместе с отчётом, чтобы порог авто-сжатия задавался в
        ОДНОМ месте — админ-настройкой, — а не дублировался константой на фронте.
        """
        meta: dict[str, Any] = {
            "window": self.budget.window,
            "usable": self.budget.usable,
            "used": self.used,
            "by_section": dict(self.by_section),
            "compressed": list(self.compressed),
            "threshold_pct": threshold_pct,
        }
        # Отчитываемся только о ПЛОХОМ: штатный случай не должен раздувать метаданные
        # каждого ответа, а вот деградация обязана быть видна без чтения логов.
        if not self.budget.window_known:
            meta["window_known"] = False
        if self.degraded:
            meta["degraded"] = list(self.degraded)
        return meta


# Человекочитаемые имена секций для трейса — пользователь должен понимать, ЧЕМ занят
# его контекст, без чтения кода.
_SECTION_LABELS: dict[str, str] = {
    "input": "запрос",
    "system": "инструкции агента",
    "facts": "факты",
    "memory": "память",
    "files": "вложения",
    "knowledge": "база знаний",
    "plan": "план",
    "summary": "резюме",
    "history": "история",
}


def _fmt_tokens(n: int) -> str:
    return f"{n / 1000:.1f}k".replace(".0k", "k") if n >= 1000 else str(n)


def build_context_summary(assembled: AssembledContext) -> str:
    """Строка для трейса: «Контекст 21.4k/103.7k (18%) · вложения 3.1k · история 8.2k»."""
    parts = [
        f"{_SECTION_LABELS.get(kind, kind)} {_fmt_tokens(tokens)}"
        for kind, tokens in sorted(assembled.by_section.items(), key=lambda kv: kv[1], reverse=True)
        if tokens
    ]
    head = (
        f"Контекст {_fmt_tokens(assembled.used)}/{_fmt_tokens(assembled.budget.usable)} "
        f"({assembled.pct:.0f}%)"
    )
    if assembled.compressed:
        compressed = ", ".join(_SECTION_LABELS.get(k, k) for k in assembled.compressed)
        head += f" · сжато: {compressed}"
    return " · ".join([head, *parts])


def _redistribute(sections: list[ContextSection], pool: int) -> int:
    """Раздать общий котёл секциям, которым не хватило, по приоритету.

    Возвращает нераспределённый остаток. Секции идут в порядке ``SECTION_PRIORITY``,
    поэтому вложения текущей задачи получают добавку раньше, чем recall из памяти.
    """
    order = {kind: i for i, kind in enumerate(SECTION_PRIORITY)}
    hungry = sorted(
        (s for s in sections if s.raw_tokens > s.budget),
        key=lambda s: order.get(s.kind, len(order)),
    )
    for section in hungry:
        if pool <= 0:
            break
        need = section.raw_tokens - section.budget
        give = min(need, pool)
        section.budget += give
        pool -= give
    return pool


async def _fit(section: ContextSection, compressor: Compressor | None) -> None:
    """Уместить секцию в её бюджет: сжать (если умеет) либо обрезать по хвосту."""
    if section.raw_tokens <= section.budget:
        section.content = section.raw
        section.tokens = section.raw_tokens
        return

    if compressor is not None and section.compressible and section.budget > 0:
        try:
            compressed = await compressor(section.raw, section.budget, section.kind)
            # Оценка одна на два использования: `estimate_tokens` — посимвольный проход
            # по строке, а сжатая секция это десятки килобайт. Считать её дважды подряд
            # значит зря блокировать event loop процесса.
            compressed_tokens = estimate_tokens(compressed) if compressed else 0
            if compressed and compressed_tokens <= section.budget:
                section.content = compressed
                section.tokens = compressed_tokens
                section.compressed = True
                return
            # Сжиматель отработал, но результат не пригодился: пусто (все куски упали)
            # либо всё ещё не влезает. Ниже будет обрезка — то есть документ приедет
            # усечённым, хотя пользователь заплатил за map-reduce.
            section.degraded = "compress_useless" if compressed else "compress_empty"
            logger.warning(
                "Сжатие секции %s не дало пригодного результата (%s): %d → %d при бюджете %d",
                section.kind,
                section.degraded,
                section.raw_tokens,
                compressed_tokens,
                section.budget,
            )
        except Exception:  # noqa: BLE001 — сжатие не должно ронять запрос
            # ⚠️ Было `pass` без единой строчки лога. Сжатие — это до 13 вызовов к
            # провайдеру; когда оно падало целиком, наблюдаемым следствием была лишь
            # обрезка документа по хвосту, неотличимая от штатной. Диагностировать
            # «модель не видит вторую половину файла» было нечем.
            section.degraded = "compress_failed"
            logger.warning(
                "context compression unavailable",
                extra={"component": section.kind, "failure_code": "unavailable"},
            )

    section.content = trim_text_to_tokens(section.raw, section.budget)
    section.tokens = estimate_tokens(section.content) if section.content else 0


_HISTORY_KIND = "history"


def _enforce_ceiling(
    sections: list[ContextSection],
    history_messages: list[dict],
    *,
    usable: int,
    input_tokens: int,
) -> tuple[str, list[dict], int, int]:
    """Дожать промпт под потолок окна, жертвуя МЕНЕЕ приоритетным.

    Потолок держится по построению, но оценка токенов эвристическая, и разметка
    склеенных секций считается не совсем как их сумма — поэтому нужна страховка.

    ⚠️ РЕЖЕМ С ХВОСТА ПРИОРИТЕТА, А НЕ САМОЕ КРУПНОЕ. Раньше жертвой выбиралась
    ``max(sections, key=tokens)``, и это систематически било по вложению текущей
    задачи: документ почти всегда крупнейший из присутствующего. Получалось прямое
    противоречие с ``SECTION_PRIORITY``, где вложения стоят вторыми после фактов —
    протокол объявлял их почти неприкосновенными, а страховка резала первыми.
    Пользователь прикладывал файл и слышал «не вижу вложение».

    История участвует в той же очереди на общих основаниях: она приоритетнее плана,
    памяти и резюме, но уступает вложениям и базе знаний.
    """
    order = {kind: i for i, kind in enumerate(SECTION_PRIORITY)}

    def _measure() -> tuple[str, int, int]:
        rendered = _render(sections)
        history_tokens = sum(estimate_tokens(str(m.get("content", ""))) for m in history_messages)
        return rendered, history_tokens, estimate_tokens(rendered) + history_tokens + input_tokens

    system_context, history_tokens, used = _measure()
    if used <= usable:
        return system_context, history_messages, history_tokens, used

    by_kind = {s.kind: s for s in sections}
    victims = sorted(
        [s.kind for s in sections] + ([_HISTORY_KIND] if history_messages else []),
        key=lambda kind: order.get(kind, len(order)),
        reverse=True,
    )

    for kind in victims:
        if used <= usable:
            break
        overflow = used - usable
        if kind == _HISTORY_KIND:
            history_messages = trim_messages_to_tokens(
                history_messages, max(0, history_tokens - overflow)
            )
        else:
            section = by_kind[kind]
            if not section.tokens:
                continue
            section.budget = max(0, section.tokens - overflow)
            section.content = (
                trim_text_to_tokens(section.content, section.budget) if section.budget else ""
            )
            section.tokens = estimate_tokens(section.content) if section.content else 0
        system_context, history_tokens, used = _measure()

    return system_context, history_messages, history_tokens, used


def _render(sections: list[ContextSection]) -> str:
    """Собрать размеченный markdown-блок. Помечаем сжатые секции, чтобы модель знала:
    это пересказ документа, а не сам документ."""
    blocks: list[str] = []
    for section in sections:
        if not section.content:
            continue
        head = section.title
        if section.compressed:
            head += f" — сжато {section.raw_tokens:,} → {section.tokens:,} токенов".replace(
                ",", " "
            )
        blocks.append(f"{head}\n{section.content}")
    return "\n\n".join(blocks)


@step_timing.measure("assemble_context")
async def assemble_context(
    *,
    model_id: str | None,
    config,
    user_input: str = "",
    facts: str = "",
    memory: str = "",
    files: str = "",
    knowledge: str = "",
    plan: str = "",
    summary: str = "",
    history: list[dict] | None = None,
    compressor: Compressor | None = None,
    fixed_tokens: int = 0,
) -> AssembledContext:
    """Собрать весь контекст под ОДИН бюджет, выведенный из окна модели.

    Реплика пользователя не режется никогда — она резервируется из бюджета до того,
    как секции начнут делить остаток.

    ``fixed_tokens`` — постоянная часть промпта агента (базовые инструкции, секция
    личности, схемы инструментов). 🔴 Она НЕ участвует в дележе бюджета: её нельзя ни
    сжать, ни обрезать, — но в ОТЧЁТ входить обязана. Без неё `used` показывал 14
    токенов там, где в модель уходило 1123, и кольцо занятости рисовало ноль.
    """
    history = list(history or [])

    raw_sections = [
        ContextSection(kind=kind, raw=str(text or "").strip())
        for kind, text in (
            ("facts", facts),
            ("memory", memory),
            ("files", files),
            ("knowledge", knowledge),
            ("plan", plan),
            ("summary", summary),
        )
    ]
    sections = [s for s in raw_sections if s.raw]

    present = {s.kind for s in sections}
    if history:
        present.add("history")

    budget = await compute_budget(model_id=model_id, config=config, present=present)

    # Реплика пользователя — вне конкуренции: сначала вычитаем её из общего бюджета,
    # остаток делят секции. Иначе длинный вопрос мог бы вытеснить сам себя.
    input_tokens = estimate_tokens(user_input)
    # Разметка (заголовки секций + разделители) тоже занимает место. Не зарезервируешь —
    # итоговый промпт вылезет за потолок ровно на размер шапок.
    render_overhead = sum(estimate_tokens(s.title) + _SEPARATOR_TOKENS for s in sections)
    available = max(0, budget.usable - input_tokens - render_overhead)

    # ⚠️ Одна реплика больше всего бюджета: секциям достаётся ноль, а раньше каждая всё
    # равно обрезалась до символа и рендерилась с заголовком — в переполненный промпт мы
    # ДОБАВЛЯЛИ мусор. Реплику не режем по дизайну, но и притворяться не будем.
    if sections and available <= 0:
        logger.warning(
            "Запрос (%d токенов) не оставляет места контексту при usable=%d — секции (%s) "
            "выброшены целиком",
            input_tokens,
            budget.usable,
            ", ".join(s.kind for s in sections),
        )
        for section in sections:
            section.degraded = "no_room_for_context"
        return AssembledContext(
            system_context="",
            history_messages=[],
            budget=budget,
            used=input_tokens,
            by_section={"input": input_tokens} if input_tokens else {},
            degraded=[f"{s.kind}:no_room_for_context" for s in sections],
        )

    for section in sections:
        section.raw_tokens = estimate_tokens(section.raw)
        section.budget = min(budget.for_section(section.kind), available)

    # История, как и секции, клампится в ОСТАТОК после резерва под ввод: без этого
    # длинный вопрос ужимал available к нулю, а история продолжала требовать всю свою
    # долю → claimed > available, промпт вылезал за окно, а safety-net историю не трогал.
    history_budget = min(budget.for_section("history"), available) if history else 0
    history_need = sum(estimate_tokens(str(m.get("content", ""))) for m in history)

    # Излишки: всё, что секции и история НЕ выбрали из своих долей, плюс доли секций,
    # которых в запросе нет (их вес уже перенормирован в compute_budget, но округление
    # и hard-cap фактов оставляют неразобранный остаток).
    claimed = sum(min(s.raw_tokens, s.budget) for s in sections) + min(history_need, history_budget)
    pool = max(0, available - claimed)

    pool = _redistribute(sections, pool)
    if history and history_need > history_budget and pool > 0:
        give = min(history_need - history_budget, pool)
        history_budget += give
        pool -= give

    # ⚠️ ПАРАЛЛЕЛЬНО, и это не то же самое, что параллельность внутри одного сжатия.
    # Секции независимы — `_fit` трогает только свою, — а при переполнении сразу файлов,
    # памяти и знаний это ТРИ последовательных map-reduce, каждый из которых сам по себе
    # до 13 вызовов. Складывались они в минуты тишины перед первым токеном.
    await asyncio.gather(*(_fit(section, compressor) for section in sections))

    history_messages = trim_messages_to_tokens(history, history_budget) if history else []

    # Считаем по ФАКТИЧЕСКИ отрендеренному промпту, а не по сумме секций: разметка
    # тоже занимает токены, и кольцо должно показывать правду, а не заниженную оценку.
    # Ввод (реплику юзера) не режем по дизайну — только секции и историю.
    system_context, history_messages, history_tokens, used = _enforce_ceiling(
        sections, history_messages, usable=budget.usable, input_tokens=input_tokens
    )

    by_section = {s.kind: s.tokens for s in sections if s.tokens}
    if history_tokens:
        by_section["history"] = history_tokens
    if input_tokens:
        by_section["input"] = input_tokens
    # Отдельной строкой, а не растворить в общем числе: на коротком диалоге постоянная
    # часть и есть весь контекст, и человек должен видеть, что занято НЕ его перепиской.
    if fixed_tokens:
        by_section["system"] = int(fixed_tokens)

    return AssembledContext(
        system_context=system_context,
        history_messages=history_messages,
        budget=budget,
        used=used + int(fixed_tokens),
        by_section=by_section,
        compressed=[s.kind for s in sections if s.compressed],
        degraded=[f"{s.kind}:{s.degraded}" for s in sections if s.degraded],
    )
