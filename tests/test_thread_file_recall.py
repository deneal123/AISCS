"""Файл-контекст на уровне треда: новый файл не должен подменяться прежним.

Баг: юзер приложил файл A, потом файл B — а агент ответил в контексте A. Причина:
если текст нового файла пуст (извлечение не удалось / контент в attachments), воркер
воскрешал ПРЕЖНИЙ файл треда. Теперь при наличии нового файла (attachments/file_ids)
прежний не подставляется.
"""

import pytest

from service.services.chat.infrastructure import chat_worker_tasks as cwt


class _FakeRedis:
    def __init__(self, data=None):
        self.data = dict(data or {})

    def set(self, key, val, ex=None):
        self.data[key] = val

    def get(self, key):
        return self.data.get(key)

    def delete(self, key):
        self.data.pop(key, None)


@pytest.mark.asyncio
async def test_new_file_with_text_persists_and_returns():
    r = _FakeRedis()
    out = await cwt._recall_or_persist_thread_file(r, "t1", "PDF текст", has_new_file=True)
    assert out == "PDF текст"
    assert r.data["chat:t1:last_file"] == "PDF текст"


@pytest.mark.asyncio
async def test_followup_without_file_recalls_cached():
    r = _FakeRedis({"chat:t1:last_file": "старый файл про риски"})
    out = await cwt._recall_or_persist_thread_file(r, "t1", "", has_new_file=False)
    assert "старый файл про риски" in out
    assert "Ранее приложенный" in out  # помечен как прежний


@pytest.mark.asyncio
async def test_new_file_empty_text_does_not_recall_stale():
    """Ключевой фикс: новый файл приложен (has_new_file), но текст пуст → прежний файл
    НЕ воскрешаем (иначе агент отвечает про предыдущее вложение), кэш стираем."""
    r = _FakeRedis({"chat:t1:last_file": "старый файл про риски"})
    out = await cwt._recall_or_persist_thread_file(r, "t1", "", has_new_file=True)
    assert "старый файл" not in out, "подставили прежний файл — регресс"
    assert out == ""
    assert "chat:t1:last_file" not in r.data, "устаревший кэш не стёрт"
