"""Линза — ЕДИНСТВЕННЫЙ способ получить текст личности в любой точке кода.

Пятнадцати способов впрыска не будет: всюду зовётся `persona.current().slot("<имя>")`
или `.wrap(промпт, "<имя>")`. У субагентов поверх этого есть тонкая обёртка
`persona_fragment()` — по симметрии с уже существующими `extra_user_context()` и
`preferred_model()` в `subagents/base.py`.

Линза НЕИЗМЕНЯЕМА и собирается один раз на прогон: композиция микса не должна считаться
заново на каждый чанк.
"""

from __future__ import annotations

from service.domain.persona import slots as slot_names
from service.domain.persona.schema import PersonaSpec

# Заголовок секции личности в системном промпте. Отдельной именованной секцией, а не
# вмешательством в базовый промпт: так базовый промпт остаётся диффабельным (регрессия
# личности не маскируется под регрессию агента), секция режется своим бюджетом, а страж
# может найти её по заголовку.
SECTION_TITLE = "## Специализация"

# Разрыв при смене роли посреди треда. Стоит ПЕРВОЙ строкой секции — до описания роли,
# потому что он объясняет, как читать всё остальное.
#
# 🔴 Зачем: личность живёт одной строкой в системной инструкции, а в истории лежат
# предыдущие ходы, где ассистент УЖЕ показал другое поведение. Инструкция не спорит с
# демонстрацией: в живом прогоне переключение на «учёного» не изменило ни жанр, ни тему —
# ответ остался в роли предыдущей личности. Нужен явный сигнал, что образец недействителен.
_SWITCH_NOTICE = (
    "⚠️ Роль в этом диалоге только что сменилась. Предыдущие ответы даны в ДРУГОЙ роли — "
    "не бери их формат, тон и ход мысли за образец, даже если тема та же."
)

# Обратный случай: личность СНЯЛИ. Секции с ролью больше нет, а история с ролью — есть,
# и без этой строки прежний жанр тянулся бы дальше по той же причине.
_SWITCH_OFF_NOTICE = (
    f"{SECTION_TITLE}\n"
    "⚠️ Специализация снята: отвечай как универсальный ассистент. Предыдущие ответы в "
    "этом диалоге даны в специализированной роли — их формат и тон больше не образец."
)


class PersonaLens:
    """Готовые фрагменты по слотам для одного прогона."""

    __slots__ = ("_fragments", "_ids", "_disclaimers", "_switched")

    def __init__(self, specs: list[PersonaSpec] | None = None, *, switched: bool = False) -> None:
        specs = list(specs or [])
        self._switched = bool(switched)
        self._ids: tuple[str, ...] = tuple(s.id for s in specs)
        self._fragments: dict[str, str] = _compose_slots(specs)
        # 🔴 ОГОВОРКИ — ТОЛЬКО У ВЕДУЩЕЙ, как тон, формат и инициатива.
        #
        # Складывались от ВСЕХ активных, и живой разбор резюме (психолог + таролог)
        # закончился строкой «Толкование — не предсказание и не медицинский совет» — при
        # том, что толкования в ответе не было ни одного. Оговорка не описывает личность,
        # она предупреждает о ЖАНРЕ ответа: «это не психотерапия», «это не инвестрекомендация».
        # А жанр по устройству задаёт ведущая — тон, формат и инициатива уже её.
        # Спутница даёт ВЗГЛЯД (identity + method), а взгляд собственного дисклеймера
        # не требует: ответ написан не в её жанре.
        #
        # ⚠️ РАЗМЕН, и он неприятный: если спутница — финансист, а ведёт учёный, ответ
        # может содержать разбор вложений без строки «не индивидуальная инвестиционная
        # рекомендация». Принято сознательно: оговорка, не совпадающая с содержанием,
        # обесценивает ВСЕ оговорки, включая те, что стоят по делу. Хочешь её гарантии —
        # ставь личность ведущей, тогда и жанр будет её.
        lead_disclaimers = specs[0].disclaimers if specs else []
        seen: dict[str, None] = {}
        for line in lead_disclaimers:
            text = str(line or "").strip()
            if text:
                seen.setdefault(text, None)
        self._disclaimers: tuple[str, ...] = tuple(seen)
        core = _compose_core(specs)
        if core:
            self._fragments[slot_names.CORE] = core

    @property
    def is_empty(self) -> bool:
        return not self._ids

    @property
    def ids(self) -> tuple[str, ...]:
        """Активные личности — для трейса и метаданных прогона."""
        return self._ids

    @property
    def disclaimers(self) -> tuple[str, ...]:
        return self._disclaimers

    def slot(self, name: str) -> str:
        """Фрагмент для точки впрыска. `""` — личность здесь молчит."""
        return self._fragments.get(name, "")

    def wrap(self, base_prompt: str, name: str) -> str:
        """Базовый промпт + фрагмент слота. Без фрагмента возвращает базовый БЕЗ ИЗМЕНЕНИЙ.

        Именно поэтому впрыск безопасно ставить где угодно: без активной личности строка
        не меняется даже пробелом, и все существующие сценарии остаются байт-в-байт.
        """
        fragment = self.slot(name)
        if not fragment:
            return base_prompt
        return f"{base_prompt}\n\n{fragment}"

    def section(self) -> str:
        """Секция личности для СИСТЕМНОГО промпта ядра (`core` + стиль + запреты)."""
        if self.is_empty:
            # Личности нет — но если её ТОЛЬКО ЧТО СНЯЛИ, молчать нельзя: см. комментарий
            # у `_SWITCH_OFF_NOTICE`. Без смены роли строка пустая, и промпт байт-в-байт
            # прежний — инвариант «нет личности → нет следов» сохранён для всех прогонов,
            # кроме одного-единственного хода сразу после снятия.
            return _SWITCH_OFF_NOTICE if self._switched else ""
        parts = [self.slot(slot_names.CORE), self.slot(slot_names.STYLE)]
        avoid = self.slot(slot_names.AVOID)
        if avoid:
            parts.append(f"Избегай: {avoid}")
        if self._disclaimers:
            # ⚠️ ТРЕБОВАНИЕ К ВЫВОДУ, А НЕ УТВЕРЖДЕНИЕ. Раньше оговорки стояли здесь
            # голым текстом среди описания роли — и модель читала их как ограничение
            # собственного поведения, а не как текст к показу: за весь живой диалог
            # таролога и психолога не выведено НИ ОДНОЙ. Для «финансиста» и «таролога»
            # это ровно тот текст, ради которого слот и заведён.
            joined = " ".join(self._disclaimers)
            parts.append(
                "Ответ, содержащий толкование или совет, заверши отдельной последней "
                f"строкой — дословно: «{joined}»"
            )
        body = "\n".join(p for p in parts if p)
        if not body:
            return ""
        head = f"{SECTION_TITLE}\n{_SWITCH_NOTICE}\n" if self._switched else f"{SECTION_TITLE}\n"
        return f"{head}{body}"


def _compose_core(specs: list[PersonaSpec]) -> str:
    """Ядро микса: содержание складывается, СТИЛЬ берётся у ведущей.

    `identity`/`method`/`initiative` конкатенируются — из этого и получается «связка»,
    ради которой микс затевался. А `tone`/`output` берутся ТОЛЬКО у ведущей (первой
    выбранной): сложенные стили дают кашу (см. `EXCLUSIVE_SLOTS`).
    """
    if not specs:
        return ""
    lines: list[str] = []
    if len(specs) > 1:
        lines.append("Ты совмещаешь роли: " + " + ".join(s.label for s in specs) + ".")
    for spec in specs:
        prefix = f"[{spec.label}] " if len(specs) > 1 else ""
        lines.append(f"{prefix}{spec.core.identity}".strip())
        if spec.core.method:
            lines.append(f"{prefix}{spec.core.method}".strip())
    lead = specs[0].core
    # 🔴 ИНИЦИАТИВА — ТОЛЬКО У ВЕДУЩЕЙ, наравне с тоном и форматом.
    #
    # Сначала она складывалась как содержание (рядом с identity/method) — и связка
    # «учёный+таролог» отвечала ЧИСТЫМ ТАРО: раскладом, позициями, без единой гипотезы.
    # Композиция при этом была верной, тон и формат брались у учёного. Причина в жанре:
    # `initiative` — не описание взгляда, а ПРИКАЗ К ДЕЙСТВИЮ («сделай расклад, вытяни
    # карты, работай по ним»). Против конкретного действия строчка «Тон: сдержанный» не
    # весит ничего, и вторая личность угоняла весь ответ независимо от того, кто ведущий.
    #
    # То же правило и по той же причине, что у `EXCLUSIVE_SLOTS`: два ответа на вопрос
    # «что делать, когда материала нет» — это не связка, а спор. Ведущая решает, ЧТО
    # делается; вторая личность окрашивает, КАК на это смотреть (identity + method).
    if lead.initiative:
        lines.append(lead.initiative)
    if lead.tone:
        lines.append(f"Тон: {lead.tone}")
    if lead.output:
        lines.append(f"Формат ответа: {lead.output}")
    return "\n".join(lines)


def _compose_slots(specs: list[PersonaSpec]) -> dict[str, str]:
    """Слоты микса по правилам: исключающие — у ведущей, союзные — дедуп, прочие — подряд."""
    out: dict[str, str] = {}
    for name in slot_names.SLOTS:
        if name in (slot_names.CORE,):
            continue
        pieces = [(s, s.slots.get(name, "").strip()) for s in specs]
        pieces = [(s, text) for s, text in pieces if text]
        if not pieces:
            continue
        if name in slot_names.EXCLUSIVE_SLOTS:
            out[name] = pieces[0][1]  # ведущая забирает слот целиком
        elif name in slot_names.UNION_SLOTS:
            seen: dict[str, None] = {}
            for _, text in pieces:
                seen.setdefault(text, None)
            # ⚠️ Разделитель «; », а не пробел. Через пробел два запрета склеивались в
            # одну неразборчивую фразу: «…ссылок на «исследования» без источника подмены
            # Таро астрологией…» — конец первого и начало второго читались как одно.
            out[name] = "; ".join(seen)
        elif len(pieces) == 1:
            out[name] = pieces[0][1]
        else:
            # Помечаем источник: в аналитическом слоте это и даёт «связку» вместо мешанины.
            out[name] = "\n".join(f"[{spec.label}] {text}" for spec, text in pieces)
    return out


EMPTY_LENS = PersonaLens()
