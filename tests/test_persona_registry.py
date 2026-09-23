"""Реестр личностей: загрузчик обязан быть ТОТАЛЬНЫМ.

Реестр правится руками в админке, то есть источник заведомо ненадёжен. Прогон
пользователя не должен падать из-за чужой опечатки: битая личность отбрасывается,
остальные работают.
"""

from __future__ import annotations

import pytest

from service.domain.persona import registry

GOOD = {
    "analyst": {
        "label": "Аналитик",
        "priority": 50,
        "core": {"identity": "Считаю."},
        "slots": {"search.query": "Ищи статистику."},
    }
}


@pytest.fixture
def registry_value(monkeypatch):
    """Подменяем ИСТОЧНИК реестра, а не разобранный результат."""

    def _set(value):
        monkeypatch.setattr(registry, "_raw_registry", lambda: value)

    return _set


def test_broken_persona_is_dropped_others_survive(registry_value, caplog):
    """🔴 Одна невалидная личность НЕ должна выключать остальные."""
    registry_value(
        {
            **GOOD,
            "broken": {"label": "Битая", "core": {}},  # нет identity
            "typo": {"label": "Опечатка", "core": {"identity": "x"}, "slots": {"нет-слота": "y"}},
        }
    )

    specs = registry.load_specs()

    assert set(specs) == {"analyst"}, "битые личности утащили за собой рабочую"


@pytest.mark.parametrize(
    "value",
    [None, [], "строка", 42, {"x": "не объект"}],
    ids=["none", "список", "строка", "число", "личность-не-объект"],
)
def test_registry_never_raises(registry_value, value):
    """Любой мусор в настройке → пустой реестр, а не исключение наружу."""
    registry_value(value)

    assert registry.load_specs() == {} or isinstance(registry.load_specs(), dict)
    assert registry.build_lens(["analyst"]).is_empty


def test_unknown_id_does_not_break_the_run(registry_value):
    """Фронт новее реестра — не повод ронять запрос: ответ без личности лучше ошибки."""
    registry_value(GOOD)

    lens = registry.build_lens(["analyst", "не-существует"])

    assert lens.ids == ("analyst",)


def test_disabled_persona_is_not_selectable(registry_value):
    """Выключенная личность не применяется, даже если её явно попросили (тёмная выкатка)."""
    registry_value({"analyst": {**GOOD["analyst"], "enabled": False}})

    assert registry.build_lens(["analyst"]).is_empty
    assert registry.catalog() == []


def test_catalog_lists_enabled_personas_for_the_picker(registry_value):
    """Включённая личность обязана появиться в каталоге — иначе селектор пуст всегда.

    Обратная сторона `test_disabled_persona_is_not_selectable`: тот держит тёмную
    выкатку, а этот — что выкатка вообще может закончиться.
    """
    registry_value({"analyst": {**GOOD["analyst"], "enabled": True}})

    # `hint` — пояснение для человека; в промпт не идёт, но в каталог обязано,
    # иначе новая личность из админского JSON появится в списке без объяснения.
    assert registry.catalog() == [{"id": "analyst", "label": "Аналитик", "hint": ""}]


def test_empty_selection_gives_empty_lens(registry_value):
    registry_value(GOOD)

    assert registry.build_lens(None).is_empty
    assert registry.build_lens([]).is_empty
    assert registry.build_lens(["", "  "]).is_empty


def test_id_comes_from_the_key(registry_value):
    """`id` берётся из ключа: дублировать имя внутри значит однажды разъехаться."""
    registry_value(GOOD)

    assert registry.load_specs()["analyst"].id == "analyst"


def test_shipped_registry_is_valid_and_usable():
    """Поставляемый реестр обязан быть валидным И иметь включённые личности.

    ⚠️ Раньше страж требовал ОБРАТНОГО — чтобы все были выключены (тёмная выкатка). Это
    поменялось вместе с продуктовым решением: выбор личности стал главным экраном чата,
    и пустой реестр означает пустую стену вместо интерфейса. Валидность проверяем по
    той же причине, что и раньше: дефолт, не проходящий собственную схему, — это
    личность, которая молча не применяется.
    """
    from service.settings import config

    shipped = config.agents.personas
    assert shipped, "дефолтный реестр пуст — нечего прототипировать"

    import service.domain.persona.registry as reg

    original = reg._raw_registry
    try:
        reg._raw_registry = lambda: shipped
        specs = reg.load_specs()
    finally:
        reg._raw_registry = original

    assert set(specs) == set(shipped), "поставляемая личность не прошла собственную валидацию"
    assert any(s.enabled for s in specs.values()), (
        "все личности выключены — стена выбора будет пустой"
    )
