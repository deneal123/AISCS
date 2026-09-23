"""Backend собирает графы репозиториев треда для search_knowledge_graph (вариант B)."""

from __future__ import annotations

import pytest

from service.services.chat.infrastructure import agent_context as ac


class _Redis:
    def __init__(self, members):
        self._members = members

    def lrange(self, key, start, end):
        return list(self._members)[start : (end + 1 if end >= 0 else None)]


@pytest.mark.asyncio
async def test_reads_repo_graphs_of_thread():
    """⚠️ ГЛАВНОЕ. Возвращает graph_id, привязанные к треду (bytes и str терпит)."""
    r = _Redis({b"repo-abc", "repo-def"})

    out = await ac.read_thread_repo_graphs(r, "t1")

    assert set(out) == {"repo-abc", "repo-def"}, f"графы репо треда не собраны: {out}"


@pytest.mark.asyncio
async def test_no_redis_or_thread_is_empty():
    assert await ac.read_thread_repo_graphs(None, "t1") == []
    assert await ac.read_thread_repo_graphs(_Redis(set()), "") == []


@pytest.mark.asyncio
async def test_redis_failure_is_best_effort():
    class _Boom:
        def lrange(self, key, start, end):
            raise ConnectionError("down")

    assert await ac.read_thread_repo_graphs(_Boom(), "t1") == []


@pytest.mark.asyncio
async def test_collect_extras_includes_repo_graphs(monkeypatch):
    """Обёртка отдаёт repo-графы третьим элементом."""

    async def _no_img(tid):
        return None

    monkeypatch.setattr(ac, "recall_last_thread_image_url", _no_img)

    ref, has_doc, repos = await ac.collect_message_extras(_Redis({"repo-1"}), "t1", [])

    assert repos == ["repo-1"]


def test_wired_into_worker():
    """⚠️ repo_graph_ids собираются и доезжают до execute."""
    import inspect

    from service.services.chat.infrastructure.chat_worker import run_execution

    src = inspect.getsource(run_execution._execute_agent)
    assert "repo_graph_ids" in src and "repo_graph_ids=prepared.repo_graph_ids" in src, (
        "repo_graph_ids не передаются в execute — инструмент не найдёт код репо"
    )


@pytest.mark.asyncio
async def test_detach_erases_repo_graphs(monkeypatch):
    """⚠️ БАГ-СТЫК (detach + вариант B). Открепление стирает и графы репо треда.

    Иначе: открепил репозиторий крестиком → карта ушла из промпта, но
    search_knowledge_graph продолжал искать в его графе → код откреплённого репо утекал.
    detach_files стирает chat:{thread}:repo_graphs заодно с last_file/file_ids.
    """
    deleted: list[str] = []

    class _Redis:
        def lrange(self, key, start, end):
            return {"repo-x"}

        def delete(self, key):
            deleted.append(key)

    async def _no_img(tid):
        return None

    import service.services.chat.infrastructure.agent_context as ac

    monkeypatch.setattr(ac, "recall_last_thread_image_url", _no_img)

    _, _, repos = await ac.collect_message_extras(_Redis(), "t1", [], detach_files=True)

    assert repos == [], "при откреплении графы репо не обнулены"
    assert "chat:t1:repo_graphs" in deleted, "ключ графов репо не стёрт при откреплении"


@pytest.mark.asyncio
async def test_no_detach_keeps_repo_graphs(monkeypatch):
    """Без открепления графы репо треда сохраняются (follow-up по коду работает)."""

    class _Redis:
        def lrange(self, key, start, end):
            return {"repo-x"}

        def delete(self, key):
            raise AssertionError("не должны стирать без detach")

    async def _no_img(tid):
        return None

    import service.services.chat.infrastructure.agent_context as ac

    monkeypatch.setattr(ac, "recall_last_thread_image_url", _no_img)

    _, _, repos = await ac.collect_message_extras(_Redis(), "t1", [], detach_files=False)

    assert repos == ["repo-x"]


def test_upload_caps_repo_graphs_with_ltrim():
    """⚠️ Аплоад ограничивает набор графов (lpush+ltrim), а не копит через sadd.

    Каждая загрузка репо даёт новый graph_id (uuid). Через set набор рос бы без предела:
    перезагрузил репо после правки — старый граф в поиске (устаревший код), десять репо =
    десять graphify-запросов на каждый search. Держим только N последних.
    """
    import inspect

    from service.services.chat.presentation.http import upload_api

    src = inspect.getsource(upload_api.upload_file_to_chat)
    assert ".lpush(" in src and ".ltrim(" in src, (
        "репо-графы копятся без предела (нет lpush+ltrim) — устаревшие версии и рост стоимости"
    )
    assert ".sadd(" not in src, "sadd копит графы без порядка и предела"
