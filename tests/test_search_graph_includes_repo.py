"""search_knowledge_graph ищет КОД репозитория, а не только личные документы.

🔴 ЖИВОЙ ИНЦИДЕНТ: пользователь приложил src.zip для ревью, агент 9 раз вызвал
search_knowledge_graph — но искал в ЛИЧНОМ графе документов (PDF про TG-бота), а код
репозитория лежит в ОТДЕЛЬНОМ графе repo-{uuid}. Кода не нашёл, 9880 кредитов впустую.
Вариант B: backend привязывает repo-граф к треду (Redis) → передаёт repo_graph_ids в
контекст → инструмент спрашивает И личный граф, И графы репо этого треда.
"""

from __future__ import annotations

import json

import pytest

from service.domain.tools import function_tools as ft


class _Ctx:
    def __init__(self, data):
        self.context = data


@pytest.fixture
def wired(monkeypatch):
    queried: list[str] = []

    class _Client:
        async def query(self, question, graph_id):
            queried.append(graph_id)
            return f"связи[{graph_id}]"

    async def _no_passages(*a, **k):
        return []

    from service.domain.tools import graphify_client as _gc

    monkeypatch.setattr(_gc, "GraphifyClient", _Client)
    from service.domain.tools import vector_store

    monkeypatch.setattr(vector_store, "search", _no_passages)
    from service.domain.tools import graphify_client

    monkeypatch.setattr(graphify_client, "user_graph_id", lambda uid: f"user-{uid}")
    return queried


@pytest.mark.asyncio
async def test_repo_graphs_are_queried(wired):
    """⚠️ ГЛАВНОЕ. Инструмент спрашивает и личный граф, и графы репо треда."""
    ctx = _Ctx({"user_id": "u1", "repo_graph_ids": ["repo-abc", "repo-def"]})

    out = await ft.search_knowledge_graph_tool(ctx, json.dumps({"question": "где хот-пути"}))

    assert "user-u1" in wired, "личный граф не опрошен"
    assert "repo-abc" in wired and "repo-def" in wired, (
        "графы репозитория не опрошены — код не найдётся"
    )
    assert "репозитория" in out, "связи репо не помечены отдельно"


@pytest.mark.asyncio
async def test_without_repo_graphs_only_user_graph(wired):
    """Нет репо в треде → как раньше, только личный граф."""
    ctx = _Ctx({"user_id": "u1"})

    await ft.search_knowledge_graph_tool(ctx, json.dumps({"question": "q"}))

    assert wired == ["user-u1"], f"опрошены лишние графы: {wired}"


@pytest.mark.asyncio
async def test_repo_relations_labeled_distinctly(wired):
    """Связи репо помечены «репозитория», документов — «знаний»: агент их различает."""
    ctx = _Ctx({"user_id": "u1", "repo_graph_ids": ["repo-x"]})

    out = await ft.search_knowledge_graph_tool(ctx, json.dumps({"question": "q"}))

    assert "## Связи из графа знаний" in out
    assert "## Связи из графа репозитория" in out


@pytest.mark.asyncio
async def test_one_dead_repo_graph_does_not_kill_search(monkeypatch):
    """⚠️ БАГ-СТЫК (вариант B + отказ graphify). Один протухший repo-граф НЕ роняет весь
    поиск: Redis ещё держит graph_id, а сам граф удалён → query кидает. Раньше gather без
    return_exceptions ронял ВЕСЬ инструмент, и агент оставался без базы знаний.
    """

    class _Client:
        async def query(self, question, graph_id):
            if graph_id == "repo-dead":
                raise RuntimeError("graph 404: удалён")
            return f"связи[{graph_id}]"

    async def _passages(*a, **k):
        return []

    from service.domain.tools import graphify_client as _gc
    from service.domain.tools import vector_store

    monkeypatch.setattr(_gc, "GraphifyClient", _Client)
    monkeypatch.setattr(vector_store, "search", _passages)
    monkeypatch.setattr(_gc, "user_graph_id", lambda uid: f"user-{uid}")

    ctx = _Ctx({"user_id": "u1", "repo_graph_ids": ["repo-live", "repo-dead"]})
    out = await ft.search_knowledge_graph_tool(ctx, json.dumps({"question": "q"}))

    assert "repo-live" in out, "живой граф пропал из-за упавшего соседа"
    assert "404" not in out, "исключение утекло в ответ вместо тихого пропуска"


@pytest.mark.asyncio
async def test_dead_vector_store_does_not_kill_search(monkeypatch):
    """Падение vector_store тоже изолировано — граф-связи всё равно возвращаются."""

    class _Client:
        async def query(self, question, graph_id):
            return "связи"

    async def _boom(*a, **k):
        raise ConnectionError("qdrant down")

    from service.domain.tools import graphify_client as _gc
    from service.domain.tools import vector_store

    monkeypatch.setattr(_gc, "GraphifyClient", _Client)
    monkeypatch.setattr(vector_store, "search", _boom)
    monkeypatch.setattr(_gc, "user_graph_id", lambda uid: f"user-{uid}")

    ctx = _Ctx({"user_id": "u1"})
    out = await ft.search_knowledge_graph_tool(ctx, json.dumps({"question": "q"}))

    assert "связи" in out, "падение эмбеддингов уронило весь поиск"
