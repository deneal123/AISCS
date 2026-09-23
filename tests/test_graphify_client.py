"""Клиент сайдкара графа знаний.

⚠️ Тестов у него в backend НЕ БЫЛО: прежний `test_graphify.py` уехал в сабмодуль
`agents` вместе с доменом, а КЛИЕНТ остался здесь и покрытие потерял.

Предмет — различение исходов, а не HTTP как таковой. У всех методов fail-open, и именно
поэтому важно, чтобы «графа ещё нет» (нормальное состояние нового пользователя) не
сливалось с «сайдкар сломался»: на первое пользователю показывают «постройте граф», на
второе так отвечать нельзя — он построит его заново в упавший сервис.
"""

from __future__ import annotations

import httpx
import pytest

from service.infrastructure.graphify import GraphifyClient
from service.infrastructure.sidecar import SidecarError


@pytest.fixture()
def enabled(monkeypatch):
    from service.settings import config

    monkeypatch.setattr(config.agents, "graphify_url", "http://graphify:8080", raising=False)
    monkeypatch.setattr(config.agents, "graphify_enabled", True, raising=False)
    monkeypatch.setattr(
        "service.shared.agent_settings_port.runtime_settings.get_agents",
        lambda key, default=None: True if key == "graphify_enabled" else default,
    )


def _client(handler) -> GraphifyClient:
    """Настоящий клиент с подменённым ТРАНСПОРТОМ.

    Подмена самого клиента проверяла бы дублёр: срок, заголовки и классификация отказа
    остались бы непокрытыми — а это ровно то, ради чего клиент и заводился.
    """
    client = GraphifyClient()
    client._transport = httpx.MockTransport(handler)
    return client


def _respond(status: int, *, content: bytes = b"", json_body=None):
    def _handler(request: httpx.Request) -> httpx.Response:
        if json_body is not None:
            return httpx.Response(status, json=json_body)
        return httpx.Response(status, content=content)

    return _handler


# --------------------------------------------------------------------------- #
# /html — страница графа; не JSON, и раньше ходила мимо клиента                 #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_html_returns_page(enabled):
    page = b"<html>graph</html>"

    assert await _client(_respond(200, content=page)).html(graph_id="user-7") == page


@pytest.mark.asyncio
async def test_html_missing_graph_is_none_not_error(enabled):
    """404 = «графа ещё нет». У нового пользователя это норма, а не сбой."""
    assert await _client(_respond(404, json_body={"error": "not_found"})).html(graph_id="u") is None


@pytest.mark.asyncio
async def test_html_server_failure_raises_instead_of_pretending_no_graph(enabled):
    """⚠️ Ключевое различие. Раньше ЛЮБОЙ `>=400` (включая 500) вызывающий превращал в
    «граф ещё не построен», и пользователь строил бы граф заново в упавший сайдкар."""
    with pytest.raises(SidecarError):
        await _client(_respond(500, json_body={"error": "internal"})).html(graph_id="u")


@pytest.mark.asyncio
async def test_html_network_failure_raises(enabled):
    def _boom(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("сайдкар лёг")

    with pytest.raises(SidecarError):
        await _client(_boom).html(graph_id="u")


@pytest.mark.asyncio
async def test_html_uses_the_short_timeout_not_the_build_one(enabled):
    """Срок из конфига, а не литерал у вызывающего.

    ⚠️ Именно здесь жил ТРЕТИЙ источник таймаута на один сервис: `graph_api` поднимал
    свой `httpx.AsyncClient(timeout=30.0)`, при том что клиент уже объявлял, что
    источник один. Чтение готовой страницы — короткая операция, а не сборка на 900 с.
    """
    seen: dict = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        seen["timeout"] = request.extensions.get("timeout")
        return httpx.Response(200, content=b"<html/>")

    client = _client(_handler)
    await client.html(graph_id="u")

    assert seen["timeout"]["read"] == client._short
    assert client._short < client._timeout, "короткая ручка не должна ждать как сборка"


@pytest.mark.asyncio
async def test_disabled_client_does_not_call_the_sidecar(monkeypatch):
    """Выключенный граф — не поход в сеть с ошибкой, а сразу «нет».

    Транспорт намеренно взрывающийся: если бы вызов всё-таки ушёл, тест бы упал.
    """
    from service.settings import config

    monkeypatch.setattr(config.agents, "graphify_url", "http://graphify:8080", raising=False)
    monkeypatch.setattr(
        "service.shared.agent_settings_port.runtime_settings.get_agents",
        lambda key, default=None: False if key == "graphify_enabled" else default,
    )

    def _boom(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("выключенный клиент не должен ходить в сайдкар")

    assert await _client(_boom).html(graph_id="u") is None


# --------------------------------------------------------------------------- #
# query/summary — то же различение на уже существовавших методах                #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_query_returns_context(enabled):
    client = _client(_respond(200, json_body={"context": "  узел A → узел B  "}))

    assert await client.query("вопрос", graph_id="u") == "узел A → узел B"


@pytest.mark.asyncio
async def test_query_degrades_to_empty_on_failure(enabled):
    """Fail-open осознанный: граф — обогащение ответа, а не сам ответ."""
    assert (
        await _client(_respond(503, json_body={"error": "internal"})).query("в", graph_id="u") == ""
    )
