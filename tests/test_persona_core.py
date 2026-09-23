"""Каркас личностей: композиция, изоляция прогонов и НЕЙТРАЛЬНОСТЬ без личности.

Главный инвариант фазы 0 — механизм есть, но поведение платформы не изменилось ни на
символ. Остальные тесты держат правила микса, которые иначе разъедутся молча.
"""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from service.domain import persona
from service.domain.persona import slots as slot_names
from service.domain.persona.lens import PersonaLens
from service.domain.persona.schema import MAX_ACTIVE, PersonaSpec, resolve_bundle

ANALYST = {
    "id": "analyst",
    "label": "Аналитик",
    "priority": 50,
    "core": {"identity": "Считаю.", "method": "От данных.", "tone": "сухо", "output": "число"},
    "slots": {
        "analyst.image": "Считай людей.",
        "search.query": "Ищи статистику.",
        # ⚠️ Исключающий слот есть У ОБЕИХ личностей НАРОЧНО: иначе «ведущая забирает
        # целиком» и «складываем подряд» дают одинаковый результат, и тест ничего не ловит.
        "search.synthesis": "Сведи в таблицу с числами.",
    },
    "disclaimers": ["Не финансовый совет."],
}
TAROT = {
    "id": "tarot",
    "label": "Таролог",
    "priority": 70,
    "core": {"identity": "Читаю символы.", "method": "Через архетипы.", "tone": "образно"},
    "slots": {"analyst.image": "Читай символику.", "search.synthesis": "Сравни школы."},
    "disclaimers": ["Не предсказание.", "Не финансовый совет."],
}


def _spec(raw: dict, **over) -> PersonaSpec:
    return PersonaSpec(**{**raw, **over})


def _lens(*raws: dict) -> PersonaLens:
    return PersonaLens(resolve_bundle([_spec(r) for r in raws]))


# --------------------------------------------------------------------------- #
# Нейтральность: без личности ничего не меняется                               #
# --------------------------------------------------------------------------- #
def test_without_persona_everything_is_empty():
    """🔴 ГЛАВНЫЙ ИНВАРИАНТ: пустая линза не даёт НИ ОДНОГО символа ни в один слот."""
    lens = PersonaLens()

    assert lens.is_empty
    assert lens.ids == ()
    assert lens.section() == ""
    for name in slot_names.SLOTS:
        assert lens.slot(name) == "", f"слот {name} не пуст без личности"


def test_wrap_returns_prompt_byte_identical_without_persona():
    """Обёртка обязана вернуть промпт БЕЗ ИЗМЕНЕНИЙ — иначе впрыск нельзя ставить всюду."""
    base = "Ты полезный ассистент.\n\nПравила: отвечай кратко."

    assert PersonaLens().wrap(base, slot_names.SEARCH_QUERY) is base


def test_current_without_context_is_empty_lens():
    """Вне прогона линза пустая, а не `None`: вызывающему не нужна проверка."""
    assert persona.current().is_empty


# --------------------------------------------------------------------------- #
# Изоляция прогонов                                                            #
# --------------------------------------------------------------------------- #
def test_scope_is_reset_on_exit():
    """🔴 После выхода из области личность обязана ИСЧЕЗНУТЬ.

    ⚠️ Проверяется в ТОМ ЖЕ контексте намеренно. Соседний тест с `asyncio.gather` этого
    поймать НЕ МОЖЕТ: каждая задача получает КОПИЮ контекста, поэтому пропажу `reset`
    там не видно — параллельные прогоны изолированы и без него. А вот последовательные
    запросы в одном воркере разделяют контекст: без сброса личность первого запроса
    досталась бы второму, где её не просили.
    """
    assert persona.current().is_empty

    with persona.use_persona(_lens(ANALYST)):
        assert persona.current().ids == ("analyst",)

    assert persona.current().is_empty, "личность пережила свою область — утечёт в чужой запрос"


def test_nested_scopes_restore_the_outer_one():
    """Вложенная область возвращает ПРЕДЫДУЩУЮ личность, а не пустоту."""
    with persona.use_persona(_lens(ANALYST)):
        with persona.use_persona(_lens(TAROT)):
            assert persona.current().ids == ("tarot",)
        assert persona.current().ids == ("analyst",), "внешняя личность не восстановилась"


@pytest.mark.asyncio
async def test_persona_does_not_leak_between_runs():
    """🔴 Личность одного прогона НЕ видна в прогоне без личности.

    У снимка настроек есть процессный фолбэк `_LAST_SEEN`, и если скопировать его сюда,
    личность прошлого запроса подмешается в чужой ответ. Проверяем оба направления:
    параллельный прогон и последовательный.
    """
    seen: dict[str, tuple[str, ...]] = {}

    async def with_persona():
        with persona.use_persona(_lens(ANALYST)):
            await asyncio.sleep(0)  # уступаем управление — здесь и протекло бы
            seen["inside"] = persona.current().ids

    async def without_persona():
        await asyncio.sleep(0)
        seen["parallel"] = persona.current().ids

    await asyncio.gather(with_persona(), without_persona())
    assert seen["inside"] == ("analyst",)
    assert seen["parallel"] == (), "личность протекла в параллельный прогон"
    assert persona.current().ids == (), "личность осталась после выхода из области"


@pytest.mark.asyncio
async def test_lens_visible_in_child_tasks():
    """Обратная сторона: веер аналитиков (`gather`) обязан личность ВИДЕТЬ."""
    with persona.use_persona(_lens(ANALYST)):
        ids = await asyncio.gather(*(asyncio.create_task(_read_ids()) for _ in range(3)))
    assert ids == [("analyst",)] * 3


async def _read_ids() -> tuple[str, ...]:
    return persona.current().ids


# --------------------------------------------------------------------------- #
# Композиция микса                                                             #
# --------------------------------------------------------------------------- #
def test_mix_is_deterministic_for_the_same_list():
    """Один и тот же СПИСОК — байт-идентичный промпт.

    ⚠️ Формулировка инварианта изменилась осознанно. Раньше здесь стояло «один и тот же
    НАБОР, независимо от порядка», и держала это сортировка по `priority`. Она давала
    воспроизводимость, но отнимала управляемость: ведущую выбрать было нельзя, а
    «таролог» с приоритетом 70 не возглавлял ни одну пару в поставке — пользователь
    выбирал связку психолог+таролог и получал голос психолога без всякого объяснения.
    Порядок теперь часть ВХОДА (он приезжает в `persona_ids` и виден в селекторе), а
    воспроизводимость держится на нём же.
    """
    assert _lens(ANALYST, TAROT).section() == _lens(ANALYST, TAROT).section()
    assert _lens(ANALYST, TAROT).ids == ("analyst", "tarot")


def test_leading_persona_is_the_first_selected():
    """Ведущая — ПЕРВАЯ ВЫБРАННАЯ, а не старшая по `priority`.

    `priority` у таролога (70) больше, чем у аналитика (50): при старом правиле аналитик
    вёл бы в обоих случаях, и перестановка ничего бы не меняла.
    """
    assert "Тон: сухо" in _lens(ANALYST, TAROT).section()
    assert "Тон: образно" in _lens(TAROT, ANALYST).section()


def test_leading_persona_owns_tone():
    """Стиль НЕ складывается: тон берёт ведущая, вклад второй не примешивается."""
    section = _lens(ANALYST, TAROT).section()

    assert "Тон: сухо" in section
    assert "образно" not in section, "тона сложились — это каша, а не связка"


def test_initiative_belongs_to_the_leading_persona_only():
    """🔴 ПРИКАЗ К ДЕЙСТВИЮ — только у ведущей, наравне с тоном и форматом.

    Живая жалоба: связка «учёный+таролог» отвечала чистым Таро — раскладом, позициями,
    без единой гипотезы. Композиция была ВЕРНОЙ, тон и формат брались у учёного. Дело в
    жанре поля: `initiative` — не описание взгляда, а инструкция «сделай X». Против
    конкретного действия строчка «Тон: сдержанный» не весит ничего, и вторая личность
    угоняла ответ независимо от того, кто ведущий.
    """
    ведущая = {**ANALYST, "core": {**ANALYST["core"], "initiative": "СЧИТАЙ."}}
    вторая = {**TAROT, "core": {**TAROT["core"], "initiative": "СДЕЛАЙ РАСКЛАД."}}

    assert "СЧИТАЙ." in _lens(ведущая).section(), "одиночная личность лишилась инициативы"

    section = _lens(ведущая, вторая).section()

    assert "СЧИТАЙ." in section, "ведущая осталась без инициативы"
    assert "СДЕЛАЙ РАСКЛАД." not in section, (
        "приказ второй личности попал в промпт — он угонит ответ у ведущей"
    )


def test_union_slots_are_readably_separated():
    """Склейка запретов через пробел давала неразборчивую фразу из двух хвостов."""
    mixed = _lens(
        {**ANALYST, "slots": {**ANALYST["slots"], "avoid": "догадок"}},
        {**TAROT, "slots": {**TAROT["slots"], "avoid": "астрологии"}},
    )

    assert mixed.slot(slot_names.AVOID) == "догадок; астрологии"


def test_content_slots_accumulate_with_source_labels():
    """Содержательные слоты складываются с пометкой источника — это и есть связка."""
    fragment = _lens(ANALYST, TAROT).slot(slot_names.ANALYST_IMAGE)

    assert "[Аналитик] Считай людей." in fragment
    assert "[Таролог] Читай символику." in fragment


def test_exclusive_slot_goes_to_leading_only():
    """Исключающий слот забирает ведущая ЦЕЛИКОМ — вклад второй личности не примешивается.

    Обе личности объявляют `search.synthesis`, иначе тест не различал бы «ведущая
    забирает» и «складываем подряд».
    """
    mixed = _lens(ANALYST, TAROT).slot(slot_names.SEARCH_SYNTHESIS)

    assert mixed == "Сведи в таблицу с числами.", "вклад ведущей потерян"
    assert "школ" not in mixed, "исключающий слот сложился — стили смешались в кашу"
    # Одиночная личность получает свой слот как есть.
    assert _lens(TAROT).slot(slot_names.SEARCH_SYNTHESIS) == "Сравни школы."


def test_disclaimers_come_from_the_leader_only():
    """🔴 ЖИВАЯ ЖАЛОБА: разбор резюме (психолог + таролог) кончался строкой «Толкование —
    не предсказание», хотя толкования в ответе не было ни одного.

    Оговорка предупреждает о ЖАНРЕ ответа, а жанр задаёт ведущая — тон, формат и
    инициатива уже её. Спутница даёт ВЗГЛЯД, и взгляд собственной оговорки не требует.
    Оговорка, не совпадающая с содержанием, обесценивает и те, что стоят по делу.
    """
    lens = _lens(ANALYST, TAROT)

    assert lens.disclaimers == ("Не финансовый совет.",)
    assert "Не предсказание." not in lens.disclaimers, (
        "оговорка спутницы приехала на ответ, написанный не в её жанре"
    )


def test_leader_disclaimers_are_deduped():
    """Повтор внутри списка одной личности не печатается дважды."""
    dup = dict(TAROT, disclaimers=["Не предсказание.", "Не предсказание."])

    assert _lens(dup).disclaimers == ("Не предсказание.",)


def test_swapping_the_leader_swaps_the_disclaimer():
    """Порядок выбора решает: ведущая — первая выбранная, её жанр и её оговорка."""
    assert _lens(TAROT, ANALYST).disclaimers == ("Не предсказание.", "Не финансовый совет.")


def test_cap_on_active_personas():
    """Потолок соблюдается, лишние отбрасываются, прогон не падает."""
    many = [_spec(ANALYST, id=f"p{i}", label=f"P{i}", priority=i) for i in range(MAX_ACTIVE + 2)]

    assert len(resolve_bundle(many)) == MAX_ACTIVE


def test_blend_deny_drops_the_junior():
    """Несовместимая пара: остаётся выбранная ПЕРВОЙ."""
    kept = resolve_bundle([_spec(ANALYST, blend_deny=["tarot"]), _spec(TAROT)])

    assert [s.id for s in kept] == ["analyst"]


def test_disabled_persona_is_not_applied():
    kept = resolve_bundle([_spec(ANALYST, enabled=False), _spec(TAROT)])

    assert [s.id for s in kept] == ["tarot"]


# --------------------------------------------------------------------------- #
# Валидация конфига                                                            #
# --------------------------------------------------------------------------- #
def test_unknown_slot_is_an_error_not_silence():
    """🔴 Опечатка в имени слота обязана падать, а не молча ничего не делать."""
    with pytest.raises(ValidationError) as exc:
        _spec(ANALYST, slots={"analist.image": "текст"})

    assert "analist.image" in str(exc.value), "ошибка не называет опечатку"


def test_identity_is_required():
    with pytest.raises(ValidationError):
        PersonaSpec(id="x", label="X", core={"method": "без identity"})
