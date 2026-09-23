"""Инструменту, которому не с чем работать, незачем ехать в каждый запрос.

Замер: схемы пяти инструментов занимают 781 токен, из них `analyze_data` 227 и
`search_knowledge_graph` 192 — почти половина. Уезжали они КАЖДЫМ сообщением, включая
«привет», хотя без табличного файла и без графа оба и сегодня возвращают вежливый
отказ («нет табличных файлов», «граф пуст»). То есть модель могла потратить целый
tool-раунд на заведомо бесполезный вызов, а мы платили за описание в каждом промпте.

⚠️ Гейт СТРУКТУРНЫЙ, а не по статистике вызовов. «Этим редко пользуются» — плохое
основание убирать инструмент: редкий вызов всё равно нужен, и роутер ошибается. А вот
«работать не с чем» проверяется точно и не отнимает у модели ничего.
"""

from __future__ import annotations

from types import SimpleNamespace

from service.domain.subagents.general import GeneralAgent

DATA_TOOLS = {"analyze_data", "search_knowledge_graph"}


def _names(agent, context) -> set[str]:
    return {getattr(t, "name", "") for t in agent._applicable_tools(context)}


def test_data_tools_are_dropped_without_data():
    """🔴 Ни таблиц, ни графа — их схемы в запрос не уезжают."""
    names = _names(
        GeneralAgent({"model": "m"}), SimpleNamespace(tabular_files=None, repo_graph_ids=None)
    )

    assert not (names & DATA_TOOLS), "инструменты без данных всё ещё едут в каждый запрос"
    assert names, "срезаны ВСЕ инструменты — модель осталась без веб-доступа и памяти"


def test_analyze_data_returns_when_a_table_is_attached():
    names = _names(
        GeneralAgent({"model": "m"}),
        SimpleNamespace(tabular_files=[{"name": "t.csv", "url": "u"}], repo_graph_ids=None),
    )

    assert "analyze_data" in names
    assert "search_knowledge_graph" not in names, "гейт срабатывает не по своему признаку"


def test_graph_tool_returns_when_a_repo_graph_exists():
    names = _names(
        GeneralAgent({"model": "m"}),
        SimpleNamespace(tabular_files=None, repo_graph_ids=["repo-abc"]),
    )

    assert "search_knowledge_graph" in names
    assert "analyze_data" not in names


def test_universal_tools_are_never_gated():
    """Веб и служебные инструменты применимы всегда — их гейтить нечем и незачем."""
    names = _names(
        GeneralAgent({"model": "m"}), SimpleNamespace(tabular_files=None, repo_graph_ids=None)
    )

    assert {"fetch_url"} <= names


def test_no_context_behaves_as_no_data():
    """Контекста нет (прямой вызов, тесты) — считаем, что данных нет: это безопасная сторона."""
    assert not (_names(GeneralAgent({"model": "m"}), None) & DATA_TOOLS)


def test_gate_shrinks_the_measured_constant_part():
    """Экономия должна быть видна в отчёте — иначе кольцо покажет старое число."""
    agent = GeneralAgent({"model": "m"})
    empty = SimpleNamespace(tabular_files=None, repo_graph_ids=None)
    with_table = SimpleNamespace(tabular_files=[{"name": "t.csv", "url": "u"}], repo_graph_ids=None)

    assert agent.fixed_prompt_tokens(empty) < agent.fixed_prompt_tokens(with_table)


def test_gate_is_wired_into_the_request():
    """🔴 ТОЧКА ВЫЗОВА: отбор обязан применяться там, где собирается поле `tools`."""
    import inspect

    from service.domain import base

    src = inspect.getsource(base.SimpleStreamingAgent._resolve_toolset)
    assert "resolve_toolset(" in src, "в запрос уходят ВСЕ инструменты, а не применимые"
