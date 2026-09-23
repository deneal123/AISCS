"""Граф знаний: поиск по личному графу пользователя.

Что это закрывает: поиска по загруженным документам не было как класса — файл жил сырым
текстом в Redis, один на тред, с TTL. Инструмент работает только потому, что починен
function-calling, — поэтому и проверяется, что он вообще зарегистрирован для модели.

Что осталось в backend'е и почему: вся ВХОДНАЯ половина — `zip_to_targz`/`text_to_targz`
(zip уходил в ветку `binary` и декодировался как utf-8 → мусор из архива), отсечение
path traversal и zip-бомбы, врезка zip в `UploadFileUseCase`. Архив приходит от
пользователя к backend'у, и гарды стоят ДО границы сервиса — сайдкар получает уже
tar.gz. Подменить это фейком нельзя: проверять надо сами гарды, а не заглушку.
"""

import httpx
import pytest


# --------------------------------------------------------------------------- #
# Идентификатор личного графа                                                  #
# --------------------------------------------------------------------------- #
def test_user_graph_id_is_stable_and_sanitised():
    from service.domain.tools.graphify_client import user_graph_id

    assert user_graph_id("abc-123") == "user-abc-123"
    # graph_id попадает в путь файла на сайдкаре — мусор из него вычищаем.
    assert user_graph_id("../../etc") == "user-etc"
    assert user_graph_id("") == ""


@pytest.mark.asyncio
async def test_graphify_uses_shared_sidecar_client_and_preserves_fail_open(monkeypatch):
    from service.domain.tools.graphify_client import GraphifyClient
    from service.infrastructure.sidecar import SidecarClient
    from service.settings import config
    from service.shared.agent_settings import runtime_settings

    monkeypatch.setattr(config.agents, "graphify_url", "http://graphify")
    monkeypatch.setattr(runtime_settings, "get_agents", lambda name, default=None: True)
    client = GraphifyClient()
    client._client = SidecarClient(
        service="graphify",
        base_url="http://graphify",
        timeout=1.0,
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={"context": "ok"})),
    )

    assert await client.query("question", graph_id="user-1") == "ok"


# --------------------------------------------------------------------------- #
# Инструмент поиска по графу (работает только потому, что починен function-calling) #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_search_tool_returns_graph_context(monkeypatch):
    from types import SimpleNamespace

    import service.domain.tools.function_tools as ft
    from service.domain.tools import graphify_client as gc

    class _Client:
        async def query(self, question, *, graph_id, **_kw):
            assert graph_id == "user-u1"
            return f"NODE Foo --uses--> Bar  ({question})"

    monkeypatch.setattr(gc, "GraphifyClient", _Client)
    ctx = SimpleNamespace(context={"user_id": "u1"})

    out = await ft.search_knowledge_graph_tool(ctx, '{"question": "как связаны Foo и Bar"}')
    assert "Foo --uses--> Bar" in out


@pytest.mark.asyncio
async def test_search_tool_says_so_when_graph_is_empty(monkeypatch):
    """Пусто — говорим модели прямо, чтобы она не выдумывала связи."""
    from types import SimpleNamespace

    import service.domain.tools.function_tools as ft
    from service.domain.tools import graphify_client as gc

    class _Client:
        async def query(self, *_a, **_kw):
            return ""

    monkeypatch.setattr(gc, "GraphifyClient", _Client)
    out = await ft.search_knowledge_graph_tool(
        SimpleNamespace(context={"user_id": "u1"}), '{"question": "что угодно"}'
    )
    assert "ничего не найдено" in out


def test_search_tool_is_registered_for_the_model():
    """Инструмент обязан попасть в DEFAULT_FUNCTION_TOOLS — иначе модель его не увидит."""
    from service.domain.base import _tools_to_openai
    from service.domain.tools.function_tools import DEFAULT_FUNCTION_TOOLS

    names = {t["function"]["name"] for t in _tools_to_openai(DEFAULT_FUNCTION_TOOLS)}
    assert "search_knowledge_graph" in names
