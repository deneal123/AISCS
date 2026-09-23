"""Вложение есть, а текста нет → сервер восстанавливает его САМ.

⚠️ ЖИВОЙ ИНЦИДЕНТ. Пользователь приложил PDF-техзадание (16 076 символов текста) и
попросил «проанализируй документ». Агент ответил «уточни, что нужно сделать» — он
физически не видел документа: промпт основного вызова был 1 606 токенов, содержимого в
нём ноль.

Причина — архитектурный разрыв. Текст вложения извлекает СЕРВЕР (opendataloader на
аплоаде, тут же и отработал успешно) и отдаёт его КЛИЕНТУ, а тот обязан вернуть его
назад полем `file_context` следующего сообщения. Если клиент этого не сделал — гонка,
потеря состояния, сторонний клиент, — сервер оставался слепым, ХОТЯ файл лежит у него в
хранилище и парсер работает.

Хуже того, ветка была намеренной: при пустом `file_context` с новым вложением
`_recall_or_persist_thread_file` стирает кэш треда и возвращает пустоту (правильно — иначе
агент ответит про ПРЕДЫДУЩИЙ файл). То есть код честно выбирал «ничего» вместо «не то»,
но третьего варианта — «взять с сервера» — не было.
"""

from __future__ import annotations

import pytest

from service.services.chat.infrastructure import chat_worker_tasks as cwt


@pytest.mark.asyncio
async def test_recovery_returns_empty_without_user():
    """Без пользователя восстанавливать нечего — не падаем."""
    assert await cwt._recover_attachment_text(None, None, None) == ""


@pytest.mark.asyncio
async def test_recovery_is_best_effort_on_failure(monkeypatch, caplog):
    """⚠️ Сбой восстановления не ломает сообщение — поведение прежнее (пусто).

    Это дополнительный путь, а не обязательный: упал сторедж/парсер — пользователь
    получит прежнее поведение, а не ошибку вместо ответа.
    """

    class _Boom:
        def get_session_context(self):
            raise ConnectionError("БД недоступна")

    text = await cwt._recover_attachment_text(_Boom(), None, "user-1")

    assert text == ""


@pytest.mark.asyncio
async def test_empty_file_context_with_new_file_still_clears_stale_cache(monkeypatch):
    """⚠️ Инвариант, который нельзя сломать восстановлением.

    Если текст так и не удалось получить, прежний файл треда воскрешать НЕЛЬЗЯ: агент
    ответил бы про предыдущее вложение, а это хуже, чем переспросить. Проверяем, что при
    новом файле и пустом тексте кэш треда стирается, а не подставляется.
    """
    deleted: list[str] = []

    class _Redis:
        def get(self, key):
            return "СТАРЫЙ ФАЙЛ ИЗ ПРОШЛОГО СООБЩЕНИЯ"

        def set(self, key, value, ex=None):
            pass

        def delete(self, key):
            deleted.append(key)

    out = await cwt._recall_or_persist_thread_file(_Redis(), "thread-1", "", has_new_file=True)

    assert out == "", "подставился прежний файл — агент ответит не про то вложение"
    assert deleted, "устаревший кэш треда не стёрт"


@pytest.mark.asyncio
async def test_present_file_context_is_persisted_for_followups(monkeypatch):
    """Обратная сторона: текст есть → кладём в кэш треда для follow-up."""
    stored: dict = {}

    class _Redis:
        def get(self, key):
            return None

        def set(self, key, value, ex=None):
            stored[key] = value

        def delete(self, key):
            pass

    out = await cwt._recall_or_persist_thread_file(
        _Redis(), "thread-1", "ТЕКСТ ДОКУМЕНТА", has_new_file=True
    )

    assert out == "ТЕКСТ ДОКУМЕНТА"
    assert stored, "текст не сохранён — follow-up потеряет документ"


def test_recovery_is_actually_wired_into_the_message_flow():
    """⚠️ Функция должна быть ПОДКЛЮЧЕНА, а не просто существовать.

    Мутация «убрать вызов из потока» не роняла тесты выше: они проверяют функцию
    отдельно. А потерять именно вызов — значит вернуть слепого агента, ничего не сломав
    формально. Поэтому проверяем стык: восстановление вызывается там, где вложение есть,
    а текст пуст.
    """
    import inspect

    from service.services.chat.infrastructure.chat_worker import run_execution

    src = inspect.getsource(run_execution._prepare_context)

    assert "recover_attachment_text" in src, (
        "восстановление текста вложения не вызывается в потоке обработки сообщения — "
        "агент снова останется без документа при пустом file_context"
    )
    assert "has_new_file and not" in src, (
        "восстановление вызывается не под условием «вложение есть, а текста нет»"
    )
