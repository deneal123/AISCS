"""Backend отдаёт ссылку на последнюю картинку треда для image-to-image.

Follow-up «перегенерируй с другим цветом волос» редактирует уже созданную картинку.
Она лежит в ``generated_files`` (``kind=image``, ``file_key``) последнего ассистентского
сообщения; backend отдаёт по ней СВЕЖУЮ презайнед-ссылку (та, что в metadata, протухает
через час). Best-effort: нет картинки / сбой БД → None, генерация не падает.
"""

from __future__ import annotations

import pytest

from service.services.chat.infrastructure import agent_context as ac


class _Row:
    def __init__(self, metadata):
        self._m = metadata

    def __getitem__(self, i):
        return self._m


class _Result:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _Session:
    def __init__(self, row):
        self._row = row

    async def execute(self, *a, **k):
        return _Result(self._row)


class _Ctx:
    def __init__(self, s):
        self._s = s

    async def __aenter__(self):
        return self._s

    async def __aexit__(self, *e):
        return False


class _Pg:
    def __init__(self, row):
        self._row = row

    def get_session_context(self):
        return _Ctx(_Session(self._row))


class _FileService:
    async def get_presigned_url_by_key(self, *, file_key):
        return f"https://storage/fresh/{file_key}"


@pytest.fixture
def wire(monkeypatch):
    from service.services.chat.infrastructure.chat_worker import factory as fac

    def _install(row):
        monkeypatch.setattr(
            fac.ChatWorkerDependencyFactory, "create_pg_connector", lambda self, cfg: _Pg(row)
        )
        monkeypatch.setattr(fac, "build_file_service", lambda cfg, pg: _FileService())

    return _install


@pytest.mark.asyncio
async def test_returns_fresh_presigned_for_last_image(wire):
    """⚠️ ГЛАВНОЕ. Есть картинка → свежая ссылка по её file_key (не протухшая из metadata)."""
    meta = {
        "generated_files": [
            {"kind": "image", "file_key": "uploads/CHAT/abc.png", "file_url": "https://OLD/expired"}
        ]
    }
    wire([meta])

    url = await ac.recall_last_thread_image_url("thread-uuid")

    assert url == "https://storage/fresh/uploads/CHAT/abc.png", (
        f"ссылка не перевыпущена по file_key (протухшая ушла бы 403): {url}"
    )


@pytest.mark.asyncio
async def test_non_image_files_are_skipped(wire):
    """⚠️ Берём именно КАРТИНКУ, не первый попавшийся файл.

    В generated_files рядом могут лежать pdf/docx (kind!=image). Референс для
    image-to-image — только картинка; отдать ссылку на pdf значило бы сломать генерацию.
    """
    meta = {
        "generated_files": [
            {"kind": "document", "file_key": "uploads/CHAT/report.pdf"},
            {"kind": "image", "file_key": "uploads/CHAT/pic.png"},
        ]
    }
    wire([meta])

    url = await ac.recall_last_thread_image_url("thread-uuid")

    assert url == "https://storage/fresh/uploads/CHAT/pic.png", (
        f"взят не-image файл как референс: {url}"
    )


@pytest.mark.asyncio
async def test_no_image_in_thread_returns_none(wire):
    """Картинок в треде нет → None (обычная генерация с нуля)."""
    wire(None)
    assert await ac.recall_last_thread_image_url("thread-uuid") is None


@pytest.mark.asyncio
async def test_empty_thread_id_is_noop(wire):
    """Без thread_id идти некуда — не падаем, не ходим в БД."""
    assert await ac.recall_last_thread_image_url("") is None
    assert await ac.recall_last_thread_image_url(None) is None


@pytest.mark.asyncio
async def test_db_failure_is_best_effort(monkeypatch):
    """Сбой БД → None, а не исключение: image-to-image не обязателен для ответа."""

    class _BoomPg:
        def get_session_context(self):
            raise ConnectionError("db down")

    from service.services.chat.infrastructure.chat_worker import factory as fac

    monkeypatch.setattr(
        fac.ChatWorkerDependencyFactory, "create_pg_connector", lambda self, cfg: _BoomPg()
    )

    assert await ac.recall_last_thread_image_url("thread-uuid") is None


def test_recall_is_wired_into_the_worker():
    """⚠️ Функция должна быть ПОДКЛЮЧЕНА к потоку, а не просто существовать."""
    import inspect

    # ⚠️ СБОР ПЕРЕЕХАЛ в `chat_worker/turn_context.py` (вынос из разросшейся функции), а
    # ПЕРЕДАЧА движку осталась в воркере. Стережём оба звена: правило живёт в цепочке, и
    # разрыв в любом из них так же нем, как раньше.
    from service.services.chat.infrastructure.chat_worker import turn_context as tc

    collected = inspect.getsource(tc.collect_engine_inputs)
    from service.services.chat.infrastructure.chat_worker import run_execution

    passed = inspect.getsource(run_execution._execute_agent)
    # Сбор идёт через обёртку collect_message_extras (recall + признак документа).
    assert "collect_message_extras" in collected, (
        "сбор картинки треда не вызывается в потоке — image-to-image не получит референс"
    )
    assert "reference_image_url=prepared.reference_image_url" in passed, (
        "reference_image_url не передаётся в execute — субагент его не увидит"
    )
