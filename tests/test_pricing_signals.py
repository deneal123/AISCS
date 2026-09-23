"""Сбор инструментов для надбавок (аудит T2.3).

Раньше `_pricing_signals` считал только top-level `routing.tool`. Мульти-интент запускает
под-агенты разных категорий (web_search + pptx_gen + …), а его top-level маршрут —
«general», поэтому надбавки под-задач не билли́лись вовсе. PricingService суммирует надбавку
на каждый элемент списка, поэтому собираем ВСЕ исполненные инструменты (с повторами).
"""

# ⚠️ Импорт из НАСТОЯЩЕГО места (`pricing_signals`), а не из воркера: раньше функция
# проходила через `chat_worker_tasks` транзитом, и тест зависел от чужого импорта.
from service.services.chat.infrastructure.pricing_signals import _pricing_signals


def test_collects_multi_intent_subtask_tools():
    # pptx_gen — artifact-надбавка: она берётся только если файл создан, поэтому даём
    # артефакт под-шага (иначе гейт справедливо срежет её — см.
    # test_artifact_surcharge_requires_artifact).
    is_complex, tools = _pricing_signals(
        {
            "metadata": {
                "model_routing": {"tool": "general", "complexity": "high"},
                "steps": ["web_search", "pptx_gen", "general"],
                "multi_intent_artifacts": [{"pptx_b64": "UEsDB..."}],
            }
        }
    )
    assert tools == ["web_search", "pptx_gen"], f"надбавки под-задач не собраны: {tools}"
    assert is_complex is True


def test_single_route_unchanged():
    _, tools = _pricing_signals({"metadata": {"model_routing": {"tool": "web_search"}}})
    assert tools == ["web_search"]


def test_top_level_plus_subtasks_combined():
    """Форс-маршрут + под-задачи: считаем и то, и другое."""
    _, tools = _pricing_signals(
        {"metadata": {"model_routing": {"tool": "deep_research"}, "steps": ["web_search"]}}
    )
    assert tools == ["deep_research", "web_search"]


def test_surcharge_follows_executed_agent_not_router_intent():
    """🔴 Выбранная модель + тумблер поиска: надбавка обязана браться.

    Живой недобилл: при выборе КОНКРЕТНОЙ модели роутер уходит в manual-ветку и не кладёт
    `tool` вовсе (`source:"manual"`). Поиск при этом отрабатывает — его включает тумблер, а
    не роутер. Раньше надбавка висела только на мнении роутера, поэтому один и тот же
    запрос билли́лся по-разному: на модели `auto` — с надбавкой, на выбранной — без неё.
    Источник истины — `agent_type` (агент, который РЕАЛЬНО отработал).
    """
    _, tools = _pricing_signals(
        {"metadata": {"model_routing": {"source": "manual"}, "agent_type": "web_search"}}
    )
    assert tools == ["web_search"], f"надбавка за реально отработавший поиск потеряна: {tools}"


def test_executed_agent_replaces_router_intent_no_double_charge():
    """Факт ЗАМЕЩАЕТ намерение: отработал один агент — одна надбавка.

    Обратная сторона: роутер предположил image_gen, пользователь форсировал поиск —
    отработал ТОЛЬКО поиск. Сложить обе надбавки было бы перебиллом.
    """
    _, tools = _pricing_signals(
        {"metadata": {"model_routing": {"tool": "image_gen"}, "agent_type": "web_search"}}
    )
    assert tools == ["web_search"]


def test_executed_general_agent_is_not_surcharged():
    """Обычный чат не должен получать надбавку из-за нового источника."""
    _, tools = _pricing_signals(
        {"metadata": {"model_routing": {"tool": "none"}, "agent_type": "general"}}
    )
    assert tools == []


def test_executed_artifact_agent_still_needs_the_artifact():
    """Гейт артефакта сильнее факта исполнения: нет файла — нет надбавки."""
    _, without = _pricing_signals(
        {"metadata": {"model_routing": {"tool": "image_gen"}, "agent_type": "image_gen"}}
    )
    assert without == []
    _, with_file = _pricing_signals(
        {
            "metadata": {
                "model_routing": {"tool": "image_gen"},
                "agent_type": "image_gen",
                "b64_json": "iVBOR...",
            }
        }
    )
    assert with_file == ["image_gen"]


def test_counts_duplicate_tool_uses():
    """Два одинаковых инструмента → две надбавки (per-occurrence, не уникальные)."""
    _, tools = _pricing_signals({"metadata": {"steps": ["web_search", "web_search"]}})
    assert tools == ["web_search", "web_search"]


def test_no_tools_when_general_only():
    _, tools = _pricing_signals(
        {"metadata": {"model_routing": {"tool": "general"}, "steps": ["general"]}}
    )
    assert tools == []


# --------------------------------------------------------------------------- #
# Инструментальный веб-поиск: надбавка берётся не по маршруту                   #
# --------------------------------------------------------------------------- #
def test_tool_search_inside_general_is_billed():
    """🔴 ДЫРА В ВЫРУЧКЕ. Надбавка берётся по МАРШРУТУ (`agent_type`), а веб-поиск,
    вызванный моделью по ходу обычного ответа, маршрута не меняет: снаружи прогон
    выглядит как `general`. Без отдельного сигнала поиск был бы бесплатным, и заметить
    это по поведению нельзя — ошибок нет, счёт просто меньше.
    """
    _is_complex, tools = _pricing_signals(
        {"metadata": {"agent_type": "general", "billable_tools": ["web_search_tool"]}}
    )

    assert tools == ["web_search_tool"], f"инструментальный поиск не тарифицирован: {tools}"


def test_route_search_and_tool_search_do_not_merge():
    """Имена РАЗНЫЕ, и это несущее: у инструмента своя цена, вдвое ниже маршрутной."""
    _is_complex, tools = _pricing_signals(
        {"metadata": {"agent_type": "web_search", "billable_tools": ["web_search_tool"]}}
    )

    assert sorted(tools) == ["web_search", "web_search_tool"]


def test_unknown_tool_names_are_ignored():
    """Список приходит от сайдкара: незнакомое имя не должно превращаться в надбавку."""
    _is_complex, tools = _pricing_signals(
        {"metadata": {"agent_type": "general", "billable_tools": ["телепатия", None, ""]}}
    )

    assert tools == []


def test_missing_marker_changes_nothing():
    """Обычный ответ без инструментов остаётся бесплатным по надбавкам."""
    _is_complex, tools = _pricing_signals({"metadata": {"agent_type": "general"}})

    assert tools == []
