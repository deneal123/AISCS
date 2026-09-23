"""Добавление инструмента требует ОДНОГО места — и отказ в выдаче не молчит.

⚠️ ЗАЧЕМ. Знание об инструменте жило в трёх разных местах: гейт применимости в `base.py`,
имя надбавки в раннере и потолок результата одним числом на всех. Пропуск любого молчал:
инструмент без гейта уезжал схемой в каждый запрос, инструмент без имени надбавки работал
бесплатно, а канонические чтения резались тем же потолком, что дампы таблиц.

🔴 Отдельная тема — САМ ОТКАЗ. Инструмент, которому не с чем работать, просто исчезал из
списка, и снаружи это неотличимо от «модель решила им не пользоваться»: человек видел
уверенный ответ по памяти вместо поиска. Теперь причина типизирована и уезжает в трейс.
"""

from __future__ import annotations

import sys
import types

import pytest

from service.domain.capabilities import tool_registry
from service.domain.capabilities.tool_spec import (
    CATALOG_UNKNOWN,
    MISSING_DATA,
    MODEL_NO_TOOL_SUPPORT,
    Omission,
    ToolSpec,
)

DUMMY_PATH = "service.domain.tools.dummy_tool_for_test"


class _FakeTool:
    """Утиный двойник `FunctionTool`: раннеру нужно только имя."""

    def __init__(self, name: str):
        self.name = name


DUMMY_TOOL = _FakeTool("dummy_tool")
DUMMY_SPEC = ToolSpec(
    name="dummy_tool",
    tool=DUMMY_TOOL,
    requires_context_attr="dummy_data",
    billing_name="dummy_tool_billing",
    result_limit_chars=42,
)


@pytest.fixture
def dummy_tool(monkeypatch):
    """Зарегистрировать инструмент ТАК ЖЕ, как это сделал бы новый модуль в `tools/`."""
    module = types.ModuleType(DUMMY_PATH)
    module.SPECS = [DUMMY_SPEC]
    monkeypatch.setitem(sys.modules, DUMMY_PATH, module)
    monkeypatch.setattr(
        tool_registry, "_TOOL_SOURCES", (*tool_registry._TOOL_SOURCES, DUMMY_PATH), raising=True
    )
    return DUMMY_TOOL


class _Ctx:
    def __init__(self, **kw):
        self.__dict__.update(kw)


# --------------------------------------------------------------------------- #
# Реестр                                                                        #
# --------------------------------------------------------------------------- #
def test_registry_resolves_the_new_tool(dummy_tool):
    assert tool_registry.get_tool_spec("dummy_tool") is DUMMY_SPEC


def test_deduplication_is_explicitly_opted_in_by_tool_policy(dummy_tool):
    """A future tool cannot get reuse merely by joining the shared executor."""
    assert DUMMY_SPEC.dedup_safe is False
    assert tool_registry.tool_dedup_safe("dummy_tool") is False
    assert tool_registry.tool_dedup_safe("search_web") is True
    assert tool_registry.tool_dedup_safe("ws_write") is False


def test_billing_name_comes_from_the_spec(dummy_tool):
    """Иначе инструмент работает, а надбавка не берётся: счёт просто меньше."""
    from service.domain.runners.tool_loop import ToolRoundMixin as ChatRunMixin

    billed: set[str] = set()
    meta = ChatRunMixin._billable_tools_meta("dummy_tool", billed)

    assert meta is not None, "надбавка не найдена — вызов ушёл бесплатно"
    assert meta["billable_tools"] == ["dummy_tool_billing"]


def test_result_limit_comes_from_the_spec(dummy_tool):
    """Потолок у каждого инструмента свой: 6000 на всех — это про дампы, не про файлы."""
    from service.domain.runners.tool_loop import _TOOL_TRUNCATION_NOTE, _trim_tool_result

    trimmed, _report = _trim_tool_result("x" * 500, "dummy_tool")

    # ⚠️ Проверяем ПОТОЛОК, а не «первые 42 символа»: результат теперь укладывается
    # сохранением головы И хвоста, и требование начинаться с головы кодировало бы
    # СПОСОБ укладки вместо правила «потолок берётся из спеки».
    assert len(trimmed) <= 42 + len(_TOOL_TRUNCATION_NOTE)
    assert len(trimmed) < 500


def test_unlimited_tool_is_not_truncated():
    """⚠️ Для канонического чтения обрезка — это НЕВЕРНЫЙ результат, а не короткий."""
    from service.domain.runners.tool_loop import _trim_tool_result

    spec = ToolSpec(name="canonical", tool=_FakeTool("canonical"), result_limit_chars=None)
    module = types.ModuleType("service.domain.tools.canonical_for_test")
    module.SPECS = [spec]
    sys.modules[module.__name__] = module
    original = tool_registry._TOOL_SOURCES
    tool_registry._TOOL_SOURCES = (*original, module.__name__)
    try:
        assert _trim_tool_result("y" * 50_000, "canonical")[0] == "y" * 50_000
    finally:
        tool_registry._TOOL_SOURCES = original
        sys.modules.pop(module.__name__, None)


# --------------------------------------------------------------------------- #
# Отказ в выдаче: причина, а не тишина                                          #
# --------------------------------------------------------------------------- #
def test_missing_data_is_reported_with_the_attribute(dummy_tool):
    """Не просто «нет» — сказано, ЧЕГО не хватило."""
    result = tool_registry.resolve_toolset([dummy_tool], _Ctx(dummy_data=None))

    assert result.tools == []
    assert result.omissions == [Omission("dummy_tool", MISSING_DATA, "dummy_data")]


def test_tool_is_given_when_its_data_is_present(dummy_tool):
    result = tool_registry.resolve_toolset([dummy_tool], _Ctx(dummy_data=["file"]))

    assert result.tools == [dummy_tool]
    assert result.omissions == []


def test_model_without_support_and_unknown_catalog_are_different(dummy_tool):
    """🔴 Оба дают ПУСТОЙ список, но значат разное и требуют разных действий."""
    no_support = tool_registry.resolve_toolset([dummy_tool], None, model_supports=False)
    unknown = tool_registry.resolve_toolset([dummy_tool], None, model_supports=None)

    assert [o.reason for o in no_support.omissions] == [MODEL_NO_TOOL_SUPPORT]
    assert [o.reason for o in unknown.omissions] == [CATALOG_UNKNOWN]
    assert no_support.tools == unknown.tools == []


def test_omission_reason_vocabulary_is_closed():
    """Произвольная строка вместо причины сделала бы отчёт неразбираемым."""
    with pytest.raises(ValueError, match="неизвестная причина"):
        Omission("x", "потому что")


def test_nameless_tool_still_appears_in_the_report():
    """⚠️ Пропуск «неудобной» записи — это ровно то молчание, ради которого отчёт заведён."""
    result = tool_registry.resolve_toolset([object()], None, model_supports=False)

    assert len(result.omissions) == 1
    assert result.omissions[0].tool == "<без имени>"


# --------------------------------------------------------------------------- #
# Отчёт доезжает до потребителя                                                 #
# --------------------------------------------------------------------------- #
def test_omissions_reach_the_event_stream(dummy_tool):
    """Причина обязана доехать до трейса: в логе её видит только оператор."""
    from service.domain.capabilities.tool_spec import ToolSet
    from service.domain.runners.tool_loop import _omissions_event

    event = _omissions_event(
        ToolSet(omissions=[Omission("dummy_tool", MISSING_DATA, "dummy_data")]), "general"
    )

    assert event is not None
    assert event.metadata["kind"] == "tool_omissions"
    assert event.metadata["omissions"] == [
        {"tool": "dummy_tool", "reason": MISSING_DATA, "detail": "dummy_data"}
    ]


def test_no_event_when_everything_was_given(dummy_tool):
    """Событие без содержания — шум, который научатся не читать."""
    from service.domain.capabilities.tool_spec import ToolSet
    from service.domain.runners.tool_loop import _omissions_event

    assert _omissions_event(ToolSet(tools=[dummy_tool]), "general") is None


def test_omission_kind_is_classified_as_non_usage():
    """⚠️ Вид события без классификации молча считается ОТВЕТОМ и зажигает ложный бейдж."""
    from service.contracts import NON_USAGE_KINDS

    assert "tool_omissions" in NON_USAGE_KINDS
