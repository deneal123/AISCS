"""Обзор файлов аккаунта: какой файл в каких диалогах появлялся.

🔴 Окно ОТДЕЛЬНОЕ от рабочего каталога треда, и это не вкусовщина: тот временный и
живёт по сроку песочницы, этот накопительный и только на чтение. Путаница между «графом
песочницы» и «графом аккаунта» в проекте уже стоила 9880 кредитов.

⚠️ Связь «файл ↔ диалог» берётся из метаданных реплики пользователя — тех самых, которые
до недавнего заполнял только успешный путь воркера. Обзор поэтому и стал возможен.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from service.services.chat.presentation.http import files_overview_api as api

ROWS = [
    ("тз.pdf", "document", "t-1", "Разбор ТЗ", datetime(2026, 7, 28, 10, tzinfo=UTC), 2),
    ("тз.pdf", "document", "t-2", "Смета", datetime(2026, 7, 27, 9, tzinfo=UTC), 1),
    ("данные.csv", "data", "t-2", "Смета", datetime(2026, 7, 27, 9, tzinfo=UTC), 1),
]


class _Profile:
    user_id = "7"


def _pg(rows, boom: bool = False):
    class _Session:
        async def execute(self, _sql, _params=None):
            if boom:
                raise RuntimeError("db down")

            class _R:
                @staticmethod
                def all():
                    return rows

            return _R()

    class _Ctx:
        async def __aenter__(self):
            return _Session()

        async def __aexit__(self, *exc):
            return False

    class _Pg:
        def get_session_context(self):
            return _Ctx()

    return _Pg()


@pytest.fixture(autouse=True)
def _uuid(monkeypatch):
    monkeypatch.setattr(api, "resolve_user_uuid", lambda uid, anonymous_fallback=False: "u-1")


@pytest.mark.asyncio
async def test_one_file_collects_all_its_dialogs(monkeypatch):
    """⚠️ ГЛАВНОЕ. Смысл окна — «с чем этот файл связан», значит диалоги группируются."""
    monkeypatch.setattr(api, "_connector", lambda: _pg(ROWS))

    out = await api.files_overview(_Profile(), 200)
    by_name = {item["filename"]: item for item in out["files"]}

    assert sorted(by_name) == ["данные.csv", "тз.pdf"]
    assert [t["thread_id"] for t in by_name["тз.pdf"]["threads"]] == ["t-1", "t-2"]
    assert by_name["тз.pdf"]["threads"][0]["title"] == "Разбор ТЗ"


@pytest.mark.asyncio
async def test_query_is_scoped_to_the_owner(monkeypatch):
    """🔴 Обзор — по файлам СПРАШИВАЮЩЕГО. Без ограничения окно показало бы чужие файлы."""
    seen: dict = {}

    class _Session:
        async def execute(self, sql, params=None):
            seen["sql"] = str(sql)
            seen["params"] = params

            class _R:
                @staticmethod
                def all():
                    return []

            return _R()

    class _Ctx:
        async def __aenter__(self):
            return _Session()

        async def __aexit__(self, *exc):
            return False

    class _Pg:
        def get_session_context(self):
            return _Ctx()

    monkeypatch.setattr(api, "_connector", lambda: _Pg())
    await api.files_overview(_Profile(), 200)

    assert "t.user_id = :user_id" in seen["sql"]
    assert seen["params"]["user_id"] == "u-1"


@pytest.mark.asyncio
async def test_read_failure_gives_an_empty_view_not_a_500(monkeypatch):
    """Окно просмотра не должно ронять страницу: сбой чтения — пустой обзор."""
    monkeypatch.setattr(api, "_connector", lambda: _pg([], boom=True))

    assert await api.files_overview(_Profile(), 200) == {"files": []}


@pytest.mark.asyncio
async def test_anonymous_sees_nothing(monkeypatch):
    monkeypatch.setattr(api, "resolve_user_uuid", lambda uid, anonymous_fallback=False: None)

    assert await api.files_overview(_Profile(), 200) == {"files": []}


def test_view_is_read_only():
    """⚠️ Только просмотр: ни удаления, ни правки — начинаем с окна, а не с выводов."""
    methods = {method for route in api.files_overview_router.routes for method in route.methods}

    assert methods == {"GET"}
