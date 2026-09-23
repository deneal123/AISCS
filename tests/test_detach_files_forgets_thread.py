"""Явное открепление файла стирает thread-память, а не воскрешает его.

🔴 ЖИВАЯ ЖАЛОБА: «прикрепил general.json, нажал крестик открепить, но он всё равно попал
в контекст». Файл, приложенный в треде ранее, персистится в Redis
(`_recall_or_persist_thread_file`/`_recall_or_persist_thread_tabular`) для follow-up. При
следующем сообщении БЕЗ вложений эта память ВОСКРЕШАЛА прежний файл — и явное
открепление ничего не меняло: система не отличала «не прикреплял» от «убрал крестиком».

Клиент шлёт `detach_files=true`, воркер трактует его как `has_new_file`: та же ветка
delete+return"" стирает память и не подмешивает прежний.
"""

from __future__ import annotations

import pytest

from service.services.chat.infrastructure import chat_worker_tasks as cwt


class _Redis:
    def __init__(self, seed=None):
        self.store = dict(seed or {})
        self.deleted = []

    def get(self, k):
        return self.store.get(k)

    def set(self, k, v, ex=None):
        self.store[k] = v

    def delete(self, k):
        self.deleted.append(k)
        self.store.pop(k, None)


@pytest.mark.asyncio
async def test_detach_erases_remembered_file():
    """⚠️ ГЛАВНОЕ. Файл был в треде; открепил + отправил пустое → память стёрта, не подмешан."""
    r = _Redis({"chat:t1:last_file": "ТЕКСТ general.json"})

    # has_new_file=True моделирует detach (воркер так его и трактует).
    out = await cwt._recall_or_persist_thread_file(r, "t1", "", has_new_file=True)

    assert out == "", f"прежний файл воскрешён при откреплении: {out!r}"
    assert "chat:t1:last_file" in r.deleted, "thread-память файла не стёрта"


@pytest.mark.asyncio
async def test_without_detach_followup_still_works():
    """Без открепления (has_new_file=False) follow-up-память жива — фичу не сломали."""
    r = _Redis({"chat:t1:last_file": "ТЕКСТ файла"})

    out = await cwt._recall_or_persist_thread_file(r, "t1", "", has_new_file=False)

    assert "ТЕКСТ файла" in out, "follow-up перестал видеть файл треда"


@pytest.mark.asyncio
async def test_detach_erases_remembered_tabular_ids():
    """Открепление стирает и запомненный набор табличных файлов диалога."""
    import json

    r = _Redis({"chat:t1:file_ids": json.dumps(["json-id"])})

    out = await __import__(
        "service.services.chat.infrastructure.agent_context", fromlist=["x"]
    )._recall_or_persist_thread_tabular(r, "t1", [], has_new_file=True)

    assert out == []
    assert "chat:t1:file_ids" in r.deleted, "набор табличных файлов диалога не стёрт"


def test_detach_flag_is_read_as_has_new_file():
    """⚠️ Сигнал detach_files ПОДКЛЮЧЁН: открепление считается «новым файлом», иначе
    thread-память не стирается и выходит «открепил, а он всё равно в контексте».

    ⚠️ ПРОВЕРЯЕМ ПОВЕДЕНИЕ, А НЕ ТЕКСТ ИСХОДНИКА. Прежняя редакция искала подстроку
    `get("detach_files")` рядом с `has_new_file =` внутри воркера — и покраснела, когда
    правило переехало в `chat_worker/turn_context.py`, хотя само правило не изменилось.
    Проверка по тексту стережёт МЕСТО, а не смысл.
    """
    from service.services.chat.infrastructure.chat_worker.turn_context import (
        message_has_new_file,
    )

    assert message_has_new_file(None, {"detach_files": True}) is True, (
        "открепление не считается новым файлом — thread-память не сотрётся"
    )
    assert message_has_new_file([{"filename": "a.pdf"}], None) is True
    assert message_has_new_file(None, {"file_ids": ["f1"]}) is True
    assert message_has_new_file(None, {}) is False
    assert message_has_new_file(None, None) is False


def test_the_worker_uses_that_rule():
    """🔴 ТОЧКА ВЫЗОВА. Правило верное, а воркер считает признак сам — и они разойдутся.

    Разбираем ДЕРЕВО: подстрока нашлась бы и в комментарии, которым вынос объяснён.
    """
    import ast
    import inspect

    from service.services.chat.infrastructure.chat_worker import run_execution

    tree = ast.parse(inspect.getsource(run_execution._prepare_context).strip())
    used = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "message_has_new_file"
    ]

    assert used, "воркер не зовёт общее правило — признак «новый файл» считается дважды"
