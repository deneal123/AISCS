"""Дорогой инструмент не уезжает модели, пока человек не согласился.

🔴 КЛАСС ЦЕНЫ БЫЛ У МАРШРУТА, НО НЕ У ИНСТРУМЕНТА. Разница между ними существенна:
маршрут выбирает оркестратор ДО прогона, и дорогой он предлагает кнопкой; инструмент
зовёт МОДЕЛЬ посреди прогона, и спросить в этот момент уже некого. Значит инструмент,
стоящий как маршрут, без объявленной цены тратил бы деньги без спроса — а такие
появляются: просмотр часового видео это сотня кадров (десятки тысяч токенов изображений)
плюс расшифровка, и всё это переезжает в КАЖДОЕ следующее сообщение треда.

⚠️ Новой машинерии не заводится. Согласие приезжает ПРИЗНАКОМ В КОНТЕКСТЕ — тем же
способом, что `web_tool_enabled` и `workspace_tools_enabled`, — а предложение кнопкой у
нас уже есть. Второй механизм рядом с ним разошёлся бы с первым.
"""

from __future__ import annotations

import pytest

from service.domain.capabilities.agent_spec import COST_CHEAP, COST_EXPENSIVE, COST_PAID
from service.domain.capabilities.tool_registry import resolve_toolset
from service.domain.capabilities.tool_spec import (
    MISSING_DATA,
    NEEDS_CONFIRMATION,
    OMISSION_REASONS,
    ToolSpec,
)


class _Tool:
    def __init__(self, name: str):
        self.name = name
        self.description = ""
        self.params_json_schema: dict = {}


def test_an_expensive_tool_without_a_lock_is_refused_at_declaration():
    """⚠️ ГЛАВНОЕ. Объявить цену и оставить инструмент в наборе — это и есть «без спроса».

    Проверка в КОНСТРУКТОРЕ, а не в резолвере: забыть признак можно ровно один раз — при
    объявлении, и падать за это должно там же, а не через прогон в неочевидном месте.
    """
    with pytest.raises(ValueError, match="без согласия"):
        ToolSpec(name="watch_video", tool=_Tool("watch_video"), cost_class=COST_EXPENSIVE)


def test_confirm_by_default_without_a_lock_is_refused_too():
    """`confirm_by_default` без признака ничего не запирает — это ложное чувство защиты."""
    with pytest.raises(ValueError, match="ничего не"):
        ToolSpec(name="x", tool=_Tool("x"), confirm_by_default=True)


def test_an_expensive_tool_with_a_lock_is_allowed():
    """🔴 ГРАНИЦА. Запрет на объявление дорогого инструмента вообще был бы не починкой."""
    spec = ToolSpec(
        name="watch_video",
        tool=_Tool("watch_video"),
        cost_class=COST_EXPENSIVE,
        confirm_by_default=True,
        requires_context_attr="video_tool_enabled",
    )

    assert spec.cost_class == COST_EXPENSIVE


def test_an_unknown_cost_class_is_refused():
    """Словарь классов ОБЩИЙ с маршрутами: своя шкала у инструментов разошлась бы с их."""
    with pytest.raises(ValueError, match="класс цены"):
        ToolSpec(name="x", tool=_Tool("x"), cost_class="дороговато")


def test_cheap_and_paid_tools_need_no_lock():
    """Дешёвое и платное запирать нечем и незачем — гейт по данным у них свой."""
    assert ToolSpec(name="a", tool=_Tool("a"), cost_class=COST_CHEAP).requires_context_attr is None
    assert ToolSpec(name="b", tool=_Tool("b"), cost_class=COST_PAID).requires_context_attr is None


@pytest.fixture
def registry(monkeypatch):
    """Подменяет реестр спек на заданный набор."""

    def _install(*specs: ToolSpec):
        from service.domain.capabilities import tool_registry as tr

        monkeypatch.setattr(tr, "_discover", lambda: {s.name: s for s in specs})
        monkeypatch.setattr(tr, "_run_scoped_specs", tuple)

    return _install


def _specs():
    expensive = ToolSpec(
        name="watch_video",
        tool=_Tool("watch_video"),
        cost_class=COST_EXPENSIVE,
        confirm_by_default=True,
        requires_context_attr="video_tool_enabled",
    )
    plain = ToolSpec(
        name="analyze_data",
        tool=_Tool("analyze_data"),
        requires_context_attr="tabular_files",
    )
    return expensive, plain


def test_withholding_for_money_is_not_called_missing_data(registry):
    """🔴 «Нет данных» и «человек не соглашался» — РАЗНЫЕ причины, хоть запор один.

    Первая — норма. Вторая означает, что способность есть, стоит денег и ждёт кнопки:
    назвав её «нет данных», мы сообщили бы человеку, что делать нечего, — а сделать можно,
    надо лишь спросить.
    """
    expensive, plain = _specs()
    registry(expensive, plain)

    result = resolve_toolset([expensive.tool, plain.tool], context=None)

    reasons = {o.tool: o.reason for o in result.omissions}
    assert reasons["watch_video"] == NEEDS_CONFIRMATION
    assert reasons["analyze_data"] == MISSING_DATA, (
        "обычный отсев по данным переименован — трейс начнёт обещать кнопку там, где её нет"
    )


def test_a_confirmed_expensive_tool_does_reach_the_model(registry):
    """🔴 БЕЗ ЭТОГО правило выше зелено и от «дорогое не выдавать никогда»."""
    expensive, plain = _specs()
    registry(expensive, plain)

    class _Ctx:
        video_tool_enabled = True

    result = resolve_toolset([expensive.tool], context=_Ctx())

    assert [t.name for t in result.tools] == ["watch_video"]
    assert result.omissions == []


def test_the_new_reason_is_in_the_closed_vocabulary():
    """⚠️ Причина вне словаря роняет `Omission` — отчёт молчал бы весь, а не про одно."""
    assert NEEDS_CONFIRMATION in OMISSION_REASONS
