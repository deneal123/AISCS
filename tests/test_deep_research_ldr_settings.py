"""LDR: разрешение настроек — per-user → overlay (админка) → config.

Регрессия, которую ловит первый тест: `search_engines` в `_resolve_ldr_settings` не
было ВООБЩЕ, поэтому клиент падал на `config.agents.ldr_search_engines` напрямую и
смена движка в админке НЕ ДОЕЗЖАЛА до запроса. Ровно тот же дефект однажды чинили для
`ldr_model`, но движок при этом пропустили.

Второй тест про то, что стратегия — per-user, третий — что мусорная стратегия не
проезжает: `search_system_factory` на незнакомое имя не падает, а МОЛЧА берёт
`source-based`, и пользователь получил бы другой продукт, думая, что выбрал глубокий.
"""

import pytest

from service.domain.subagents import deep_research as dr_mod


@pytest.fixture
def overlay(monkeypatch):
    """Подменяет admin-overlay: `runtime_settings.get_agents(key, default)`."""
    values: dict = {}

    def _get_agents(key, default=None):
        return values.get(key, default)

    monkeypatch.setattr(dr_mod, "logger", dr_mod.logger)
    import service.shared.agent_settings as agent_settings

    monkeypatch.setattr(agent_settings.runtime_settings, "get_agents", _get_agents)
    return values


def _agent(**model_settings):
    return dr_mod.DeepResearchAgent(model_settings=model_settings)


def test_admin_engine_override_reaches_request(overlay) -> None:
    """Движок из админки доезжает до настроек клиента (раньше — нет)."""
    overlay["ldr_search_engines"] = "arxiv"

    resolved = _agent()._resolve_ldr_settings()

    assert resolved["search_engines"] == "arxiv"


def test_engine_is_admin_only_not_per_user(overlay) -> None:
    """Движок сознательно НЕ per-user: под langgraph-agent он почти ни на что не
    влияет, выбор движков делает сама стратегия."""
    overlay["ldr_search_engines"] = "arxiv"

    resolved = _agent(ldr_search_engines="pubmed")._resolve_ldr_settings()

    assert resolved["search_engines"] == "arxiv"


def test_per_user_strategy_wins_over_admin(overlay) -> None:
    overlay["ldr_strategy"] = "source-based"

    resolved = _agent(ldr_strategy="focused-iteration")._resolve_ldr_settings()

    assert resolved["strategy"] == "focused-iteration"


def test_admin_strategy_used_when_user_silent(overlay) -> None:
    overlay["ldr_strategy"] = "topic-organization"

    resolved = _agent()._resolve_ldr_settings()

    assert resolved["strategy"] == "topic-organization"


@pytest.mark.parametrize("bogus", ["mcp", "agentic", "не-стратегия", "", None])
def test_unknown_strategy_falls_back_to_default(overlay, bogus) -> None:
    """⚠️ Молчаливая подмена продукта. LDR на незнакомое имя откатывается на
    `source-based` — более мелкий и дешёвый ресёрч, — и пользователь об этом не
    узнает. Поэтому имя проверяем у себя и берём СВОЙ дефолт, а не чужой."""
    resolved = _agent(ldr_strategy=bogus)._resolve_ldr_settings()

    assert resolved["strategy"] == dr_mod.DEFAULT_LDR_STRATEGY


def test_resolved_settings_are_accepted_by_the_real_client(overlay) -> None:
    """Замыкаем цепочку до клиента: имена ключей обязаны совпасть с сигнатурой.

    Без этого опечатка в имени kwarg прошла бы мимо тестов выше — словарь бы
    разрешался «правильно», а `LDRResearchClient(**resolved)` тихо взял бы значение
    из конфига (лишние ключи он бы не принял, но переименованный — просто не
    применил бы). Проверяем по факту: движок из админки оказался в клиенте.
    """
    from service.infrastructure.integration.ldr_research import LDRResearchClient

    overlay["ldr_search_engines"] = "arxiv"
    overlay["ldr_strategy"] = "source-based"

    resolved = _agent()._resolve_ldr_settings()
    client = LDRResearchClient(**resolved)

    assert client._engines[0] == "arxiv"
    assert client._strategy == "source-based"


def test_declared_strategies_exist_in_ldr() -> None:
    """Список, который отдаём пользователю, должен состоять из имён, которые LDR
    действительно знает. Иначе пункт меню тихо деградирует в `source-based`."""
    assert dr_mod.DEFAULT_LDR_STRATEGY in dr_mod.LDR_STRATEGIES
    assert dr_mod.LDR_STRATEGIES == {
        "langgraph-agent",
        "source-based",
        "focused-iteration",
        "topic-organization",
    }
